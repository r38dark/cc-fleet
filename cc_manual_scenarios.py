"""Full and orchestrator choices with an explicitly selected companion."""
import copy

ENGINES = ('claude', 'codex')
ROLES = (None, 'full', 'reserve', 'orchestrator', 'executor')


def reserve_access(base, engine):
    """Keep existing Full; entering reserve never grants it to a paired/paused role."""
    choices = base.get('manual_choices')
    full = choices is None or choices.get(engine) == 'full'
    return 'full' if full and not base.get('leader') and base['selected'][engine] == engine+'_solo_full' else 'write'


def validate_choices(choices):
    if not isinstance(choices, dict) or set(choices) != set(ENGINES):
        return False, 'Выбери роли Claude и Codex.'
    if any(value not in ROLES for value in choices.values()):
        return False, 'Неизвестная роль.'
    active = [value for value in choices.values() if value]
    if len(active) == 1 and active[0] in ('full', 'reserve'):
        return True, ''
    if len(active) == 2 and set(active) == {'orchestrator','executor'}:
        return True, ''
    return False, 'Для оркестратора подключи вторую модель для выполнения шагов. Full другой модели несовместим с оркестратором.'


def validate_stored_choices(choices):
    """Read older sessions without promoting their rights or restarting consoles."""
    if isinstance(choices,dict) and set(choices)==set(ENGINES) and all(isinstance(v,str) for v in choices.values()) and set(choices.values())=={'orchestrator','executor'}:
        return True, ''
    return validate_choices(choices)


class ManualScenarioMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Existing sessions remain untouched until a complete scenario is applied.
        self.manual_choices = None

    def definitions(self, engine):
        profiles = super().definitions(engine)
        name = self.actor(engine)
        profiles.insert(2, dict(id='executor', title=name+' · исполнитель', kind='executor',
            mode='self', access='write', task_rights='dev', builtin=True,
            description='Выполняет подтверждённые шаги отдельно выбранной ведущей.',
            can='Выполнять подтверждённые шаги ведущей с пределом прав «дев» и возвращать проверенный результат.',
            cannot='Ставить задания ведущей, делегировать дальше или выполнять неподтверждённые шаги.',
            when='Работа в паре с выбранной тобой ведущей моделью.',
            flow=['Ведущая', 'Подтверждение человека', name+' · дев']))
        return profiles

    def _base(self):
        return dict(super()._base(), manual_choices=copy.deepcopy(self.manual_choices))

    def _restore(self):
        choices = copy.deepcopy(self.restore.get('manual_choices')) if self.restore else None
        super()._restore()
        self.manual_choices = choices

    def reconcile_availability(self):
        previous = copy.deepcopy(self.service)
        super()._reconcile()
        if self.service and self.service != previous:
            engine = self.service['engine']
            self.service['access'] = reserve_access(self.restore, engine)
            self.manual_choices = {e: 'reserve' if e == engine else None for e in ENGINES}

    def public(self):
        result = super().public()
        result['manual_scenario'] = dict(choices=copy.deepcopy(self.manual_choices) or dict.fromkeys(ENGINES),
                                         legacy=self.manual_choices is None)
        result['capabilities'] = dict(manual_scenario=True,full_only=False,orchestrator=True)
        for data in result['engines'].values():
            data['profiles']=[p for p in data['profiles'] if p['kind'] in ('full','orchestrator','reserve')]
        if self.manual_choices is not None:
            for engine, choice in self.manual_choices.items():
                data = result['engines'][engine]
                data.update(role={'full':'solo', 'orchestrator':'leader', 'executor':'executor',
                                  'reserve':'reserve'}.get(choice, 'paused'), active=choice is not None)
                if choice is None:
                    data.update(selected=None, label=self.actor(engine)+' · не участвует')
                elif choice == 'executor':
                    data['label'] = self.actor(engine)+' · исполнитель '+self.actor(self.leader)
        return result

    def apply_scenario(self, choices, confirm='', revision=None):
        with self.lock:
            if type(revision) is not int or revision < 0:
                return dict(ok=False, message='Обнови выбор перед применением сценария.', conflict=True)
            stale = self._check_revision(revision)
            if stale:
                return stale
            valid, message = validate_choices(choices)
            if not valid:
                return dict(ok=False, message=message)
            if choices == self.manual_choices:
                return dict(ok=True, message='Этот сценарий уже действует.', state=self.public())
            if any(value in ('full', 'reserve') for value in choices.values()) and str(confirm).strip().casefold() != 'подтверждаю':
                return dict(ok=False, confirmation_required=True, word='подтверждаю',
                            message='Подтверди весь сценарий: вторая модель не будет участвовать.')
            previous = copy.deepcopy(self.restore if self.service and self.restore else self._base())
            reserve = next((e for e in ENGINES if choices[e] == 'reserve'), None)
            access = (self.service.get('access', 'write') if self.service and self.service['engine'] == reserve
                      else 'write' if self.service else reserve_access(previous, reserve)) if reserve else None
            self.manual_choices = copy.deepcopy(choices)
            self.leader = next((e for e in ENGINES if choices[e] == 'orchestrator'), None)
            self.selected = {e: choices[e] if choices[e] in ('orchestrator', 'executor')
                             else self.last_solo[e] for e in ENGINES}
            for e in ENGINES:
                if choices[e] == 'full':
                    self.selected[e] = self.last_solo[e] = e+'_solo_full'
            self.service = dict(engine=reserve, kind='reserve', source='manual', emergency=False, access=access) if reserve else None
            self.restore = previous if reserve else None
            self.until = 0
            self.auto_blocked.update(e for e in ENGINES if not self.availability[self.other(e)])
            self.revision += 1
            return dict(ok=True, message='Сценарий применён.', state=self.public())

    def apply(self, engine, profile_id, confirm='', revision=None):
        # Cached old clients may still use a one-engine endpoint. It must never
        # infer an executor or bypass Full exclusivity.
        stale = self._check_revision(revision)
        if stale:
            return stale
        if engine not in ENGINES or profile_id not in (engine+'_solo_full', 'reserve'):
            return dict(ok=False, message='Выбери оркестратора в общем окне и подключи вторую модель перед применением.')
        return self.apply_scenario({e: ('reserve' if profile_id == 'reserve' else 'full')
                                    if e == engine else None for e in ENGINES}, confirm, revision)
