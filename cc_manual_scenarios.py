"""Профили по одному движку: Full (Claude и Codex) и «Opus → Sonnet» (только Claude). Связки Claude↔Codex убраны."""
import copy

ENGINES = ('claude', 'codex')
# orchestrator/executor остаются в списке только для чтения старых записей: новые пары не принимаются
ROLES = (None, 'full', 'duo', 'orchestrator', 'executor')
DUO_ENGINE = 'claude'   # «Opus → Sonnet» есть только у Claude
DUO_ID = 'claude_opus_sonnet'   # id профиля: Opus ведёт, Sonnet исполняет (одна сессия + субагент)


def validate_choices(choices):
    if not isinstance(choices, dict) or set(choices) != set(ENGINES):
        return False, 'Выбери роли Claude и Codex.'
    if any(value not in ROLES for value in choices.values()):
        return False, 'Неизвестная роль.'
    active = [(engine, value) for engine, value in choices.items() if value]
    if len(active) == 1:
        engine, value = active[0]
        if value == 'full' or (value == 'duo' and engine == DUO_ENGINE):
            return True, ''
    return False, 'Выбери один профиль: Full или «Opus → Sonnet» (только Claude). Связки Claude и Codex убраны.'


def validate_stored_choices(choices):
    """Read older sessions without promoting their rights or restarting consoles."""
    if isinstance(choices,dict) and set(choices)==set(ENGINES) and all(isinstance(v,str) for v in choices.values()) and set(choices.values())=={'orchestrator','executor'}:
        return True, ''
    return validate_choices(choices)


class ManualScenarioMixin:
    # Codex с одним аккаунтом на балансере не участвует в ротации — профиль «Full» у Claude его на паузу не ставит:
    # он остаётся самостоятельным (с прежним профилем), пишет в свой Telegram и принимает ввод в консоли.
    # Функцию подставляет cc_fleet.install (число аккаунтов Codex); по умолчанию Codex ставится на паузу, как раньше.
    codex_independent = staticmethod(lambda: False)

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
        super()._reconcile()  # служебный режим сам не включается: только снимаем устаревший

    def public(self):
        result = super().public()
        result['manual_scenario'] = dict(choices=copy.deepcopy(self.manual_choices) or dict.fromkeys(ENGINES),
                                         legacy=self.manual_choices is None)
        result['capabilities'] = dict(manual_scenario=True,full_only=False,orchestrator=False,duo=True)
        for data in result['engines'].values():
            data['profiles']=[p for p in data['profiles'] if p['kind'] in ('full','duo')]   # связок в списке больше нет
        if self.manual_choices is not None:
            for engine, choice in self.manual_choices.items():
                data = result['engines'][engine]
                free = choice is None and engine == 'codex' and self._codex_free()
                data.update(role={'full':'solo', 'duo':'solo', 'orchestrator':'leader', 'executor':'executor'}.get(choice, 'solo' if free else 'paused'),
                            active=choice is not None or free)
                if choice is None and not free:
                    data.update(selected=None, label=self.actor(engine)+' · не участвует')
                elif choice == 'executor':
                    data['label'] = self.actor(engine)+' · исполнитель '+self.actor(self.leader)
        if self.service and self.service.get('access') == 'full':
            engine = self.service['engine']
            # A service mode changes the workflow; Full remains the working profile.
            result['engines'][engine].update(selected=engine+'_solo_full', label=self.actor(engine)+' Full')
            result['manual_scenario']['choices'][engine] = 'full'
        return result

    def _codex_free(self):
        """Codex вне сценария остаётся самостоятельным, если на балансере у него один аккаунт (ротации нет)."""
        try:
            return bool(self.codex_independent())
        except Exception:
            return False

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
            if any(v in ('full', 'duo') for v in choices.values()) and str(confirm).strip().casefold() != 'подтверждаю':
                return dict(ok=False, confirmation_required=True, word='подтверждаю',
                            message='Подтверди весь сценарий: вторая модель не будет участвовать.')
            self.manual_choices = copy.deepcopy(choices)
            self.leader = next((e for e in ENGINES if choices[e] == 'orchestrator'), None)
            self.selected = {e: self.last_solo[e] for e in ENGINES}
            for e in ENGINES:
                if choices[e] == 'full':
                    self.selected[e] = self.last_solo[e] = e+'_solo_full'
                elif choices[e] == 'duo':
                    self.selected[e] = DUO_ID   # last_solo не трогаем: выход из «Opus → Sonnet» вернёт Full
            self.service = None
            self.restore = None
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
        if engine not in ENGINES or profile_id not in (engine+'_solo_full', DUO_ID if engine == DUO_ENGINE else None):
            return dict(ok=False, message='Выбери профиль в общем окне: Full или «Opus → Sonnet» (только Claude).')
        role = 'duo' if profile_id == DUO_ID else 'full'
        return self.apply_scenario({e: role if e == engine else None for e in ENGINES}, confirm, revision)
