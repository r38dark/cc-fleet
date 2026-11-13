"""Два рабочих профиля (Full и Оркестратор) для каждого исполнителя, без срока действия. Служебных режимов нет:
записи прежних версий с ними читаются как обычный сценарий (см. ProfileState.from_data)."""
import copy
import threading
import time
from cc_manual_scenarios import ManualScenarioMixin, validate_stored_choices, DUO_ID

ENGINES = ('claude', 'codex')


class ProfileScenarios:
    def __init__(self, clock=time.time):
        self.clock, self.lock = clock, threading.RLock()
        self.revision, self.leader, self.service, self.restore = 0, None, None, None
        self.selected = {e: e+'_solo_full' for e in ENGINES}
        self.last_solo = dict(self.selected)
        self.custom = {e: [] for e in ENGINES}  # прежние записи хранятся, но не предлагаются
        self.until = 0
        self.auto = {e: dict(enabled=False, emergency=False) for e in ENGINES}
        self.availability = {e: True for e in ENGINES}
        self.auto_blocked = set()

    def other(self, engine):
        return 'codex' if engine == 'claude' else 'claude'

    def actor(self, engine):
        return {'claude': 'Claude', 'codex': 'Codex'}[engine]

    def definitions(self, engine):
        name, other = self.actor(engine), self.actor(self.other(engine))
        profiles = [
            dict(id=engine+'_solo_full', title=name+' Full · самостоятельно', kind='full', mode='self',
                 access='full', task_rights='dev', builtin=True,
                 description='Все инструменты, команды и файлы в пределах прав пользователя ОС.',
                 can='Работать самостоятельно со всеми доступными файлами и командами без ограничений песочницы модели.',
                 cannot='Самостоятельно получать отсутствующие права ОС или подключать другого исполнителя.',
                 when='Модель должна выполнить задачу самостоятельно с полными доступными правами.',
                 flow=[name+' Full', 'Работа и проверенный результат']),
            dict(id='orchestrator', title=name+' → '+other, kind='orchestrator', mode='orchestrator',
                 access='read', task_rights='dev', builtin=True,
                 description=name+' планирует и проверяет. '+other+' выполняет подтверждённые шаги.',
                 can='Читать проект, писать задания в папку обмена и проверять результат. Ведомая выполняет шаги с правами «дев».',
                 cannot='Менять проект силами ведущей, отправлять неподтверждённые шаги или создавать встречную связку.',
                 when='Нужна ведущая модель и отдельный исполнитель под контролем человека.',
                 flow=[name+' · чтение', 'Подтверждение человека', other+' · дев', name+' проверяет'])]
        if engine == 'claude':
            profiles.append(dict(id=DUO_ID, title='Claude · Opus → Sonnet', kind='duo', mode='self',
                 access='full', task_rights='dev', builtin=True,
                 description='Opus ставит задачи и принимает результат, Sonnet пишет код. Права — как у Full.',
                 can='Планировать и проверять силами Opus, поручать написание кода и правки файлов помощнику-исполнителю на Sonnet; работать со всеми файлами и командами в пределах прав пользователя ОС.',
                 cannot='Управлять Codex или получать от него задания; самостоятельно получать отсутствующие права ОС.',
                 when='Большая задача: нужен сильный планировщик, а основной объём кода дешевле писать Sonnet. Модели берутся из пула: последний Opus и последний Sonnet.',
                 flow=['Ты', 'Opus: ставит задачу', 'Sonnet: пишет код', 'Opus: проверяет']))
        return profiles

    def _stop_pair(self):
        if self.leader:
            self.selected[self.leader] = self.last_solo[self.leader]
            self.leader = None

    def _base(self):
        return dict(selected=copy.deepcopy(self.selected), last_solo=copy.deepcopy(self.last_solo), leader=self.leader)

    def _expire(self):
        self.until = 0

    def _restore(self):
        if self.restore:
            self.selected = self.restore['selected']
            self.last_solo = self.restore['last_solo']
            self.leader = self.restore['leader']
        self.service, self.restore, self.until = None, None, 0
        self.revision += 1

    def _reconcile(self):
        self.until = 0
        for engine in ENGINES:
            if self.availability[self.other(engine)]:
                self.auto_blocked.discard(engine)
        if self.service and self.service.get('source') == 'auto':
            engine = self.service['engine']
            if self.availability[self.other(engine)] or not self.availability[engine] or not self.auto[engine]['enabled']:
                self._restore()
        # служебный режим сам не включается

    def _check_revision(self, revision):
        if revision is not None and revision != self.revision:
            return dict(ok=False, message='Сценарий уже изменился. Обнови выбор.', conflict=True)

    def configure(self, engine, enabled, emergency=False, confirm='', revision=None):
        """Настроек служебного режима больше нет: включить нечего."""
        with self.lock:
            if engine not in ENGINES:
                return dict(ok=False, message='Неизвестный исполнитель.')
            stale = self._check_revision(revision)
            if stale:
                return stale
            return dict(ok=False, message='Служебный режим убран из панели: включать нечего.')

    def set_availability(self, engine, available):
        with self.lock:
            if engine not in ENGINES or type(available) is not bool:
                return dict(ok=False)
            self.availability[engine] = available
            return dict(ok=True, state=self.public())

    def public(self):
        with self.lock:
            self._reconcile()
            engines = {}
            for engine in ENGINES:
                role = 'solo'
                if self.service:
                    role = 'reserve' if self.service['engine'] == engine else 'paused'
                elif self.leader:
                    role = 'leader' if self.leader == engine else 'executor'
                selected = 'reserve' if self.service and self.service['engine'] == engine else self.selected[engine]
                definitions = self.definitions(engine)
                item = next((p for p in definitions if p['id'] == selected), {})
                label = item.get('title', selected)
                if role == 'executor':
                    label = self.actor(engine)+' · исполнитель '+self.actor(self.leader)
                elif role == 'paused':
                    label = self.actor(engine)+' · на паузе'
                engines[engine] = dict(id=engine, title=self.actor(engine), selected=selected,
                    base_selected=self.selected[engine], role=role, label=label, profiles=definitions,
                    auto=copy.deepcopy(self.auto[engine]), auto_blocked=engine in self.auto_blocked, until=0)
            return dict(ok=True, available=True, demo=True, revision=self.revision, leader=self.leader,
                follower=self.other(self.leader) if self.leader else None, service=copy.deepcopy(self.service), engines=engines)

    def apply(self, engine, profile_id, confirm='', revision=None):
        with self.lock:
            self._reconcile()
            if engine not in ENGINES:
                return dict(ok=False, message='Неизвестный исполнитель.')
            stale = self._check_revision(revision)
            if stale:
                return stale
            profile = next((p for p in self.definitions(engine) if p['id'] == profile_id), None)
            if not profile:
                return dict(ok=False, message='Профиль удалён. Доступны Full и Оркестратор.')
            already = self.public()['engines'][engine]
            if already['selected'] == profile_id and already['role'] not in ('executor', 'paused'):
                return dict(ok=True, message='Этот профиль уже выбран.', state=self.public())
            word = 'подтверждаю' if profile['kind'] in ('full', 'duo') else ''
            if word and str(confirm).casefold().strip() != word:
                return dict(ok=False, confirmation_required=True, word=word, message='Подтверди выбор профиля '+profile['title']+'.')
            if self.service:
                self._restore()
            self.auto_blocked.update(e for e in ENGINES if not self.availability[self.other(e)])
            self._stop_pair()
            self.selected[engine] = profile_id
            if profile['kind'] == 'orchestrator':
                self.leader = engine
            elif profile['kind'] == 'full':
                self.last_solo[engine] = profile_id
            self.until = 0
            self.revision += 1
            return dict(ok=True, message='Сценарий выбран.', state=self.public())

    def stop_service(self, engine, revision=None):
        with self.lock:
            if engine not in ENGINES:
                return dict(ok=False, message='Неизвестный исполнитель.')
            stale = self._check_revision(revision)
            if stale:
                return stale
            if self.service and self.service['engine'] != engine:
                return dict(ok=False, message='Режим включён у другой стороны.')
            self.auto_blocked.add(engine)
            if self.service:
                self._restore()
            return dict(ok=True, message='Предыдущий сценарий восстановлен.', state=self.public())

    def delete(self, engine, profile_id, revision=None):
        return dict(ok=False, message='Доступны только встроенные профили: Full и «Opus → Sonnet».')


class ProfileState(ManualScenarioMixin, ProfileScenarios):
    """Чтение не запускает эффекты консолей. Старые записи нормализуются без активации прав."""
    FIELDS = ('revision', 'leader', 'service', 'restore', 'selected', 'last_solo',
              'custom', 'until', 'auto', 'availability', 'auto_blocked', 'manual_choices')

    def _reconcile(self):
        pass

    def export(self):
        out = {key: copy.deepcopy(getattr(self, key)) for key in self.FIELDS}
        out['until'] = 0
        out['auto_blocked'] = sorted(self.auto_blocked)
        return out

    @classmethod
    def from_data(cls, data, clock=time.time):
        state = cls(clock)
        for key in cls.FIELDS:
            if key in data:
                setattr(state, key, copy.deepcopy(data[key]))
        if set(state.selected) != set(ENGINES) or state.leader not in (None, *ENGINES):
            raise ValueError('invalid_profile_state')
        state.auto_blocked = set(state.auto_blocked)
        def normalize(base):
            for engine in ENGINES:
                allowed = ('orchestrator', 'executor', engine+'_solo_full') + ((DUO_ID,) if engine == 'claude' else ())
                for key in ('selected', 'last_solo'):
                    if base[key][engine] not in allowed:
                        base[key][engine] = engine+'_solo_full'
        if state.service:  # служебных режимов прежних версий больше нет: возвращаем прежний сценарий
            state._restore()
        # прежний служебный выбор («reserve») из старых записей не активируем — сессии остаются как есть до нового выбора
        if isinstance(state.manual_choices, dict) and 'reserve' in state.manual_choices.values():
            state.manual_choices = None
        if isinstance(state.restore, dict) and isinstance(state.restore.get('manual_choices'), dict) \
                and 'reserve' in state.restore['manual_choices'].values():
            state.restore['manual_choices'] = None
        normalize(dict(selected=state.selected, last_solo=state.last_solo))
        if state.restore:
            normalize(state.restore)
        if state.service:
            state.service['emergency'] = False
        for engine in ENGINES:
            # автоматических служебных режимов нет — старые галочки выключаются
            state.auto[engine] = dict(enabled=False, emergency=False)
        state.until = 0
        for base in [dict(manual_choices=state.manual_choices,selected=state.selected,leader=state.leader),state.restore or {}]:
            choices=base.get('manual_choices')
            if choices is not None:
                leader=next((e for e in ENGINES if choices.get(e)=='orchestrator'),None) if isinstance(choices,dict) else None
                if not validate_stored_choices(choices)[0] or base.get('leader')!=leader:
                    raise ValueError('invalid_manual_scenario')
                for engine,role in choices.items():
                    wanted=engine+'_solo_full' if role=='full' else DUO_ID if role=='duo' else role
                    if role in ('full','duo','orchestrator','executor') and base['selected'][engine]!=wanted:
                        raise ValueError('invalid_manual_scenario_profile')
        return state

    def public(self):
        result = super().public()
        result.pop('demo', None)
        return result
