"""Isolated preview policy. Does not import native consoles or invoke any agent."""
import copy
from profile_scenarios import ProfileScenarios as PreviousScenarios, ENGINES

ROLES = (None, 'full', 'orchestrator', 'executor', 'reserve')


def validate_choices(choices):
    if not isinstance(choices, dict) or set(choices) != set(ENGINES):
        return False, 'Выбери роли Claude и Codex.'
    if any(value not in ROLES for value in choices.values()):
        return False, 'Неизвестная роль.'
    active = [value for value in choices.values() if value]
    if len(active) == 1 and active[0] in ('full', 'reserve'):
        return True, ''
    if set(active) == {'orchestrator', 'executor'} and len(active) == 2:
        return True, ''
    if not active:
        return False, 'Выбери самостоятельную модель или собери пару ведущая → исполнитель.'
    if active == ['orchestrator']:
        return False, 'Теперь выбери исполнителя в соседнем блоке.'
    if active == ['executor']:
        return False, 'Теперь выбери оркестратора в соседнем блоке.'
    return False, 'Роли несовместимы. Full и резерв работают отдельно; для пары нужны оркестратор и исполнитель.'


class ManualScenarios(PreviousScenarios):
    def __init__(self):
        super().__init__()
        self.choices = dict(claude=None, codex='full')
        self.restore_choices = None

    def _reconcile(self):
        # Regular roles are never completed or changed by a GET or first click.
        self.until = 0

    def definitions(self, engine):
        profiles = super().definitions(engine)
        lead = next(p for p in profiles if p['id'] == 'orchestrator')
        lead.update(title=self.actor(engine)+' · оркестратор',
                    description='Планирует и проверяет. Исполнителя выбери в соседнем блоке.',
                    cannot='Самостоятельно менять проект или назначать вторую модель без твоего выбора.')
        profiles[0]['description'] = 'Работает одна с полными доступными правами. Другая модель не участвует.'
        profiles.insert(2, dict(id='executor', title=self.actor(engine)+' · исполнитель', kind='executor',
            mode='self', access='write', task_rights='dev', builtin=True,
            description='Выполняет подтверждённые шаги. Оркестратора выбери в соседнем блоке.',
            can='Выполнять подтверждённое задание ведущей с пределом прав «дев» и возвращать проверенный результат.',
            cannot='Самостоятельно ставить задачи ведущей, делегировать дальше или выполнять неподтверждённые шаги.',
            when='Работа в паре с отдельно выбранной ведущей моделью.',
            flow=['Ведущая', 'Подтверждение человека', self.actor(engine)+' · дев']))
        return profiles

    def public(self):
        with self.lock:
            result = super().public()
            result['demo'] = True
            result['manual_scenario'] = dict(choices=copy.deepcopy(self.choices))
            for engine, choice in self.choices.items():
                data = result['engines'][engine]
                role = {'full': 'solo', 'orchestrator': 'leader', 'executor': 'executor', 'reserve': 'reserve'}.get(choice, 'paused')
                data.update(role=role, active=bool(choice), applied=True)
                if choice == 'full':
                    data['label'] = self.actor(engine)+' Full · самостоятельно'
                elif choice in ('orchestrator', 'executor'):
                    data['label'] = self.actor(self.leader)+' → '+self.actor(self.other(self.leader))+' · '+('ведущая' if choice == 'orchestrator' else 'исполнитель')
                elif choice == 'reserve':
                    data['label'] = self.actor(engine)+' + Notion · резерв'
                else:
                    data.update(selected=None, label=self.actor(engine)+' · не используется')
            return result

    def apply_scenario(self, choices, confirm='', revision=None):
        with self.lock:
            stale = self._check_revision(revision)
            if stale:
                return stale
            valid, message = validate_choices(choices)
            if not valid:
                return dict(ok=False, message=message)
            if choices == self.choices:
                return dict(ok=True, message='Этот сценарий уже действует на демо.', state=self.public())
            if any(value in ('full', 'reserve') for value in choices.values()) and str(confirm).strip().casefold() != 'подтверждаю':
                return dict(ok=False, confirmation_required=True, word='подтверждаю', message='Подтверди весь сценарий. Вторая модель не будет участвовать.')
            previous = copy.deepcopy(self.restore_choices if self.service and self.restore_choices else self.choices)
            self._assign(choices)
            if self.service:
                self.restore_choices = previous
            else:
                self.restore_choices = None
            self.auto_blocked.update(e for e in ENGINES if not self.availability[self.other(e)])
            self.revision += 1
            return dict(ok=True, message='Демо: сценарий применён. Рабочие консоли не менялись.', state=self.public())

    def _assign(self, choices, source='manual'):
        self.choices = copy.deepcopy(choices)
        self.leader = next((e for e in ENGINES if choices[e] == 'orchestrator'), None)
        reserve = next((e for e in ENGINES if choices[e] == 'reserve'), None)
        self.service = dict(engine=reserve, kind='reserve', source=source, emergency=False) if reserve else None
        self.selected = {e: choices[e] if choices[e] in ('orchestrator', 'executor') else e+'_solo_full' for e in ENGINES}
        self.until = 0

    def apply(self, engine, profile_id, confirm='', revision=None):
        # Existing quick reserve and settings remain available; ordinary roles use the composer.
        if engine not in ENGINES or profile_id != 'reserve':
            return dict(ok=False, message='Собери обе роли в окне профилей и нажми «Применить сценарий».')
        return self.apply_scenario({e: 'reserve' if e == engine else None for e in ENGINES}, confirm, revision)

    def stop_service(self, engine, revision=None):
        with self.lock:
            stale = self._check_revision(revision)
            if stale:
                return stale
            if not self.service or self.service['engine'] != engine:
                return dict(ok=False, message='У этой модели резерв не включён.')
            previous = self.restore_choices or {e: 'full' if e == engine else None for e in ENGINES}
            self._assign(previous)
            self.restore_choices = None
            self.auto_blocked.add(engine)
            self.revision += 1
            return dict(ok=True, message='Демо: предыдущий сценарий восстановлен.', state=self.public())

    def _restore(self):
        previous = self.restore_choices or dict(claude=None, codex='full')
        self._assign(previous)
        self.restore_choices = None
        self.revision += 1

    def configure(self, engine, enabled, emergency=False, confirm='', revision=None):
        result = super().configure(engine, enabled, emergency, confirm, revision)
        if result.get('ok'):
            self._auto_reserve()
            result['state'] = self.public()
        return result

    def set_availability(self, engine, available):
        with self.lock:
            if engine not in ENGINES or type(available) is not bool:
                return dict(ok=False)
            self.availability[engine] = available
            self._auto_reserve()
            return dict(ok=True, state=self.public())

    def _auto_reserve(self):
        for engine in ENGINES:
            if self.availability[self.other(engine)]:
                self.auto_blocked.discard(engine)
        if self.service:
            engine = self.service['engine']
            if self.service['source'] == 'auto' and (self.availability[self.other(engine)] or not self.availability[engine] or not self.auto[engine]['enabled']):
                self.stop_service(engine)
            return
        for engine in ENGINES:
            if self.auto[engine]['enabled'] and engine not in self.auto_blocked and self.availability[engine] and not self.availability[self.other(engine)]:
                self.restore_choices = copy.deepcopy(self.choices)
                self._assign({e: 'reserve' if e == engine else None for e in ENGINES}, source='auto')
                self.revision += 1
                return
