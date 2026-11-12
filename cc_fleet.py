"""Интеграция обзора и Codex-ротации; существующие маршруты и настройки сохраняются."""
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlparse, parse_qs

import cc_codex_rotation
import cc_codex_models
import cc_overview

# Побочная беседа: ответ должен прийти туда же, откуда написали, а основная работа остаться нетронутой.
SIDE_LABEL = '[побочный вопрос из консоли: ответь здесь, в консоли, не в Telegram; основную работу и файлы дела не трогай] '
SLASH_COMMAND = re.compile(r'(/[A-Za-z][A-Za-z0-9_-]{0,79})(?:[ \t]+(.*))?')   # как в _claude и cc_codex_console.send_input


START_SIDE = '/opt/cc-limits/start_claude_side.sh'    # запасной путь; настоящий — config.json «start_claude_side» (side_script)
SIDE_CLAUDE_FLAG = '/opt/cc-limits/side_claude.json'  # пишет скрипт запуска, стирает сам Claude при выходе
SIDE_READY = ('for shortcuts', 'bypass permissions', '❯')   # признаки готового приглашения ввода на экране Claude
SIDE_START_WAIT = 45
SIDE_TG_MARK = 'claude-plugins-official/telegram'   # процесс плагина Telegram: в побочной сессии его быть не должно (R2-3)
SIDE_TG_SETTLE = 3                                  # плагин поднимается чуть позже приглашения ввода — даём ему время показаться


def claude_alive(ns):
    """Есть ли screen-сессия Claude (основная или побочная): по ней вкладка и ввод работают одинаково."""
    screen = ns['cfg']().get('screen_session', 'claude')
    try:
        out = subprocess.run(['screen', '-ls'], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return ('.' + screen + '\t') in out or ('.' + screen + ' ') in out


def side_claude_flag():
    """Идёт ли побочная сессия: флаг от скрипта запуска и нет плагина Telegram (у основного Claude он работает,
    так что устаревший флаг после перезапуска основного метку не включает)."""
    if not os.path.exists(SIDE_CLAUDE_FLAG):
        return False
    try:
        return subprocess.run(['pgrep', '-f', 'claude-plugins-official/telegram'], capture_output=True, timeout=10).returncode != 0
    except (OSError, subprocess.SubprocessError):
        return False


def _claude_prompt_ready(ns):
    screen = ns['cfg']().get('screen_session', 'claude')
    path = os.path.join(ns['BASE'], '.side-ready-%d' % os.getpid())
    try:
        if subprocess.run(['screen', '-S', screen, '-p', '0', '-X', 'hardcopy', path], capture_output=True, timeout=10).returncode:
            return False
        with open(path, encoding='utf-8', errors='replace') as stream:
            shown = stream.read()
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return any(mark in shown for mark in SIDE_READY)


def _telegram_plugin_running():
    try:
        return subprocess.run(['pgrep', '-f', SIDE_TG_MARK], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _quit_side(ns):
    """Гасит побочную сессию (screen) и её плагин; основной Claude к этому моменту остановлен."""
    screen = ns['cfg']().get('screen_session', 'claude')
    for cmd in (['screen', '-S', screen, '-X', 'quit'], ['pkill', '-f', SIDE_TG_MARK]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        os.unlink(SIDE_CLAUDE_FLAG)
    except OSError:
        pass


def side_script(ns):
    """Скрипт побочной сессии Claude: config.json «start_claude_side», иначе start_claude_side.sh рядом с панелью."""
    try:
        custom = str(ns['cfg']().get('start_claude_side') or '').strip()
    except Exception:
        custom = ''
    return custom or os.path.join(str(ns.get('BASE') or os.path.dirname(START_SIDE)), 'start_claude_side.sh')


def start_side_claude(ns):
    """Запускает побочную сессию Claude на dev, если основной остановлен. Возвращает (ok, сообщение).
    Основной Claude, уже работающий в том же screen, не трогаем: тогда ничего не запускаем и сообщаем, что запуск не нужен."""
    if claude_alive(ns):
        return True, ''
    try:
        result = subprocess.run(['systemd-run', '--scope', '--quiet', '--unit', 'claude-side-%d' % int(time.time()), side_script(ns)],
                                capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, 'Не удалось запустить побочную сессию Claude: ' + type(exc).__name__
    if result.returncode:
        return False, 'Побочная сессия Claude не запущена (код %d). Бот Telegram и основная работа не затронуты.' % result.returncode
    deadline = time.time() + SIDE_START_WAIT
    while time.time() < deadline:
        if claude_alive(ns) and _claude_prompt_ready(ns):
            time.sleep(SIDE_TG_SETTLE)
            if _telegram_plugin_running():
                # --settings не отключил плагин: второй опрос бота украл бы сообщения у ведущего — гасим сразу
                _quit_side(ns)
                return False, 'Побочная сессия Claude поднялась вместе с плагином Telegram — остановил её, чтобы не отбирать бота у ведущего. Основная работа не затронута.'
            return True, ''
        time.sleep(1.5)
    return False, 'Побочная сессия Claude запустилась, но не готова принять ввод за %d с. Повтори чуть позже.' % SIDE_START_WAIT


class ConsoleInput:
    def __init__(self, ns):
        self.ns = ns
        self.locks = {'claude': threading.Lock(), 'codex': threading.Lock()}
        self.receipts = {}
        self.lock = threading.Lock()

    def send(self, session, text, request_id, side=False):
        if session not in self.locks:
            return False, 'Неизвестная консоль.'
        if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > 48000:
            return False, 'Нужно непустое сообщение размером до 48 КБ.'
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_id):
            return False, 'Неверный идентификатор отправки.'
        text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]', '', text.replace('\r\n', '\n').replace('\r', '\n')).strip()
        digest = hashlib.sha256(text.encode()).hexdigest()
        payload = text if not side or SLASH_COMMAND.fullmatch(text) else SIDE_LABEL + text   # слэш-команды остаются командами
        key = session, request_id
        with self.lock:
            previous = self.receipts.get(key)
            if previous:
                if previous['digest'] != digest:
                    return False, 'Этот идентификатор уже использован для другого сообщения.'
                return previous['result']
            if not self.locks[session].acquire(blocking=False):
                return False, 'Предыдущий ввод ещё отправляется. Проверь консоль перед повтором.'
            self.receipts[key] = {'digest': digest, 'result': (False, 'Ввод отправляется; проверь консоль перед повтором.'), 'ts': time.time()}
        uncertain = False
        try:
            if session == 'codex':
                rotation=self.ns.get('FLEET_ROTATION')
                if rotation and rotation.limit_pause().get('active'):
                    result=self.ns['cc_codex_bridge'].BRIDGE.enqueue_console(payload,request_id)
                else:result = self.ns['cc_codex_console'].send_input(payload)
            else:
                result = self._claude(payload)
        except Exception as exc:
            uncertain = True
            result = False, 'Не удалось передать ввод: '+type(exc).__name__+'. Проверь консоль перед повтором.'
        finally:
            self.locks[session].release()
        with self.lock:
            self.receipts[key]['result'] = result
            safe_retry = any(part in result[1].lower() for part in ('идёт ответ', 'идёт запрос', 'консоль занята'))
            if not result[0] and not uncertain and safe_retry:
                # Явный отказ до отправки допускает повтор после освобождения консоли.
                self.receipts.pop(key, None)
            for old in list(self.receipts):
                if len(self.receipts) <= 256:
                    break
                if old != key:
                    self.receipts.pop(old)
        return result

    def _claude(self, text):
        # обычное сообщение можно отправлять, пока Claude отвечает: Claude Code ставит его в очередь и разберёт после хода.
        # Слэш-команды (/compact, /model…) в ходе ответа не принимаются — их по-прежнему держим до конца ответа.
        if self.ns['session_busy']() and re.fullmatch(r'/[A-Za-z][A-Za-z0-9_-]{0,79}(?:[ \t]+.*)?', text, re.S):
            return False, 'В консоли Claude идёт ответ: команду можно отправить после его завершения (или нажми Esc).'
        screen = self.ns['cfg']().get('screen_session', 'claude')
        base = ['screen', '-S', screen, '-p', '0', '-X']
        command = re.fullmatch(r'(/[A-Za-z][A-Za-z0-9_-]{0,79})(?:[ \t]+(.*))?', text)
        if command:
            prefix, args = command.groups()
            response = subprocess.run(base+['stuff', prefix+(' ' if args else '')],capture_output=True,timeout=10)
            if response.returncode:
                return False, 'Консоль Claude недоступна.'
            time.sleep(1)
            if not args:
                response = subprocess.run(base+['stuff', '\r'],capture_output=True,timeout=10)
                return response.returncode == 0, 'Команда передана в консоль Claude.' if not response.returncode else 'Консоль Claude не приняла Enter.'
            text = args
        fd, path = tempfile.mkstemp(prefix='.console-input-', dir=self.ns['BASE'])
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write('\x1b[200~'+text+'\x1b[201~')
            for command in [('readbuf', path), ('paste', '.')]:
                response = subprocess.run(base+list(command), capture_output=True, timeout=10)
                if response.returncode:
                    return False, 'Консоль Claude недоступна.'
            time.sleep(1)
            response = subprocess.run(base+['stuff', '\r'], capture_output=True, timeout=10)
            return response.returncode == 0, 'Ввод передан в консоль Claude.' if not response.returncode else 'Консоль Claude не приняла Enter.'
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def key(self, session, key):
        rotation=self.ns.get('FLEET_ROTATION')
        if session=='codex' and key!='escape' and rotation and rotation.limit_pause().get('active'):
            return False,'Codex на паузе по лимитам. Новые задания отправляй через поле сообщения: они сохранятся в очереди.'
        keys = {'escape': '\x1b', 'enter': '\r', 'up': '\x1b[A', 'down': '\x1b[B'}
        if session not in self.locks or key not in keys:
            return False, 'Неизвестная клавиша или консоль.'
        if session == 'codex':
            con = self.ns['cc_codex_console']
            if not con._pid():
                return False, 'Консоль Codex не запущена.'
            response = con._ctl(['-S', con.NAME, '-p', '0', '-X', 'stuff', keys[key]])
        else:
            screen = self.ns['cfg']().get('screen_session', 'claude')
            response = subprocess.run(['screen', '-S', screen, '-p', '0', '-X', 'stuff', keys[key]], capture_output=True, timeout=10)
        return response.returncode == 0, 'Клавиша передана в выбранную консоль.' if not response.returncode else 'Консоль не приняла клавишу.'


def install(ns):
    codex, console, bridge = ns['cc_codex'], ns['cc_codex_console'], ns['cc_codex_bridge']
    # один аккаунт Codex — ротации нет: профиль Claude Full не ставит Codex на паузу (число аккаунтов смотрим при каждом обращении)
    import cc_profile_state
    cc_profile_state.ProfileState.codex_independent = staticmethod(lambda: len(codex.profile_slots()) <= 1)
    rotation = cc_codex_rotation.Rotation(ns['BASE'], codex, console, ns['codex_bin'], bridge)
    models = cc_codex_models.Discovery(codex, rotation, ns['codex_bin'])
    inputs = ConsoleInput(ns)
    ns['FLEET_ROTATION'] = rotation
    import cc_codex_quota
    rotation.quota=cc_codex_quota.Guard(ns['BASE'],rotation,console,bridge.BRIDGE)
    bridge.LIMIT_PAUSE = rotation.limit_pause  # очередь моста ждёт сброса, если лимит исчерпан и переключаться некуда
    bridge.INPUT_QUEUE_PATH=os.path.join(ns['BASE'],'codex_input_queue.json')
    if hasattr(bridge.BRIDGE.inputs,'attach_journal'):bridge.BRIDGE.inputs.attach_journal(bridge.INPUT_QUEUE_PATH)
    console.QUOTA_PAUSE=rotation.limit_pause
    console.QUOTA_ENQUEUE=bridge.BRIDGE.enqueue_console
    import cc_profiles
    profiles = cc_profiles.bind(ns, inputs)
    try:   # Codex раньше стоял на паузе (SIGSTOP), а теперь по правилу выше не должен: снимаем заморозку при старте панели
        if not profiles.paused('codex'):
            profiles.native._codex_pause(False)
    except Exception as exc:
        print('profiles: заморозка Codex не снята: %r' % (exc,), flush=True)
    original = ns['H']

    class FleetHandler(original):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path not in ('/api/profiles', '/api/chatgpt/bridge', '/api/chatgpt/rotation', '/api/chatgpt', '/api/chatgpt/models'):
                return original.do_GET(self)
            if not self._authed():
                return self._send(403, {'ok': False, 'message': 'forbidden'})
            if parsed.path == '/api/profiles':
                return self._send(200, profiles.public())
            if parsed.path == '/api/chatgpt/models':
                return self._send(200, models.public())
            if parsed.path == '/api/chatgpt/bridge':
                return self._send(200, dict(ok=True, available=True, bridge=bridge.public(), emergency=dict(available=False,configured=False,active=ns['cc_codex_emergency'].active(),hours=0,removed=True), profile_system=profiles.public()))
            if parsed.path == '/api/chatgpt':
                force = bool(parse_qs(parsed.query).get('refresh'))
                return self._send(200, rotation.snapshot(force))
            rotation.refresh()
            return self._send(200, rotation.public())

        def do_POST(self):
            path = urlparse(self.path).path
            if path in ('/api/model','/api/effort') and not profiles.input_allowed('claude'):
                if not self._authed():return self._send(403, {'ok':False})
                return self._send(200, {'ok':False,'message':'Claude на паузе или меняется профиль. Повтори выбор модели после завершения переключения.'})
            if not path.startswith('/api/profiles/') and path not in ('/api/console/input', '/api/console/key', '/api/chatgpt/rotation/config', '/api/chatgpt/rotation/switch', '/api/chatgpt/models/check'):
                return original.do_POST(self)
            if not self._authed():
                return self._send(403, {'ok': False, 'message': 'forbidden'})
            try:
                length = int(self.headers.get('Content-Length') or '0')
                if length < 0 or length > 65536:
                    return self._send(413, {'ok': False, 'message': 'Слишком большой запрос.'})
                body = json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(body, dict):
                    raise ValueError('object required')
            except (ValueError, UnicodeDecodeError):
                return self._send(400, {'ok': False, 'message': 'Неверный JSON.'})
            try:
                if path == '/api/chatgpt/models/check':
                    return self._send(200, models.start())
                if path.startswith('/api/profiles/'):
                    parts = path.split('/')
                    rm = ns.get('REMOTE_MODE')
                    routed = rm.scenario_route(body) if rm is not None and path == '/api/profiles/scenario/apply' else None
                    if routed is not None:
                        if routed.get('ok'):
                            routed['state'] = profiles.public()
                        return self._send(200, routed)
                    bad = '' if rm is None or path == '/api/profiles/task/confirm' else (
                        rm.scenario_guard(body.get('choices')) if path == '/api/profiles/scenario/apply' else rm.action_guard(parts[4] if len(parts)>4 else ''))
                    if bad:
                        return self._send(200, dict(ok=False, message=bad))
                    result = (profiles.apply_scenario(body) if path == '/api/profiles/scenario/apply' else
                              profiles.tasks.confirm(body) if path == '/api/profiles/task/confirm' else
                              profiles.action(parts[3] if len(parts)>3 else '',parts[4] if len(parts)>4 else '',body))
                    return self._send(200, result)
                if path == '/api/console/input':
                    session = body.get('session')
                    if session in ('claude','codex') and not profiles.console_allowed(session):
                        if profiles.transitioning or profiles.pending.exists():
                            return self._send(200, dict(ok=False, message='Идёт переключение профиля. Повтори чуть позже.'))
                        if not profiles.paused(session):
                            return self._send(200, dict(ok=False, message='Консоль не участвует в текущем сценарии. Измени общую схему в выборе профилей.'))
                        if not body.get('side'):
                            # Побочная беседа: на паузе вкладка просыпается только после «Да» в окне на странице.
                            return self._send(200, dict(ok=False, ask='side', message=('Codex' if session == 'codex' else 'Claude')+' сейчас на паузе: профиль отдал работу другой стороне. Написать ему всё равно? Он ненадолго проснётся, ответит и снова встанет на паузу.'))
                        ok_side, message_side = profiles.side_open(session)
                        if not ok_side:
                            return self._send(200, dict(ok=False, message=message_side))
                    claude_side = False
                    if session == 'claude' and not claude_alive(ns):
                        # Основной Claude остановлен (работа на PROD): писать некуда. Побочная сессия
                        # (без Telegram, только чтение) запускается только после «Да» на странице.
                        if not body.get('side'):
                            return self._send(200, dict(ok=False, ask='side', message='Claude DEV сейчас остановлен: основная работа идёт в другом месте. Запустить побочную сессию Claude здесь? Она работает без Telegram и только читает, основную работу не трогает. Перед возвратом работы её остановят.'))
                        ok_start, message_start = start_side_claude(ns)
                        if not ok_start:
                            return self._send(200, dict(ok=False, message=message_start))
                        claude_side = True
                    side_now = isinstance(session, str) and (profiles.side_active(session) or claude_side or (session == 'claude' and side_claude_flag()))   # побочная беседа: окно открыто или идёт побочная сессия
                    ok, message = inputs.send(body.get('session'), body.get('text'), body.get('request_id'), side=side_now)
                elif path == '/api/console/key':
                    ok, message = inputs.key(body.get('session'), body.get('key'))
                elif path.endswith('/config'):
                    ok, message = rotation.configure(body)
                else:
                    ok, message = rotation.switch(body.get('slot'), manual=True, reason='Ручной выбор')
                return self._send(200 if ok else 409, {'ok': ok, 'message': message})
            except Exception as exc:
                return self._send(500, {'ok': False, 'message': 'Действие не выполнено: '+type(exc).__name__})

        def _chatgpt_post(self, action, body):
            if action=='bridge/save':
                current=bridge.load()
                if any(key in body and body[key]!=current.get(key) for key in ('mode','access','task_rights')):
                    return self._send(200,dict(ok=False,message='Сценарий и права выбираются через Full или Оркестратор в меню профилей.'))
            if action=='bridge/save' and profiles.transitioning:
                return self._send(200, {'ok':False,'message':'Сейчас применяется профиль. Сохрани настройки после завершения переключения.'})
            if action=='prefs' and not profiles.input_allowed('codex'):
                return self._send(200, {'ok':False,'message':'Codex на паузе или меняется профиль. Повтори выбор модели после завершения переключения.'})
            if action in ('bridge/profile/apply','bridge/profile/delete','emergency/on','emergency/off'):
                name = 'delete' if action.endswith('/delete') else 'stop' if action.endswith('/off') else 'apply'
                body = dict(body)
                if action.startswith('emergency/'):body.update(id='emergency', confirm=body.get('word',''))
                return self._send(200, profiles.action('codex',name,body))
            if action in ('delete', 'wipe'):
                slot = body.get('slot')
                if console.busy() and (action == 'wipe' or slot == rotation.active()):
                    return self._send(200, {'ok': False, 'message': 'Codex сейчас отвечает. Удаление доступно после завершения ответа.'})
                if action == 'delete' and slot and slot != rotation.active():
                    history = console._meta().get('history_home')
                    if history and os.path.realpath(history) == os.path.realpath(codex.profile_dir(slot)):
                        return self._send(200, {'ok': False, 'message': 'В этом аккаунте хранится текущая беседа. Начни новую сессию в выбранном аккаунте перед удалением прежнего.'})
            if action != 'prefs':
                return original._chatgpt_post(self, action, body)
            slot = body.get('slot')
            was_active = slot == rotation.active() and bool(console._pid())
            catalog = []
            if was_active:
                # Сохраняем текущую модель до записи новых defaults аккаунта.
                meta = console._meta()
                meta['settings'] = console.active_settings()
                codex._jsave(console._meta_path(), meta)
                codex.own(console._meta_path())
                with codex._lock:
                    catalog = list(((codex._cache.get(slot) or {}).get('data') or {}).get('models') or [])
            ok, message = codex.set_prefs(ns['codex_bin'](), slot, body.get('model', ''), body.get('effort', ''), body.get('fast'), lang=body.get('lang'))
            pending = False
            if ok and was_active:
                if not catalog:
                    catalog = codex.fetch_account(ns['codex_bin'](), slot).get('models') or []
                model = body.get('model') or next((m.get('id') for m in catalog if m.get('is_default')), None)
                selected = next((m for m in catalog if m.get('id') == model), {})
                values = {'model': model, 'effort': body.get('effort') or selected.get('default_effort'),
                          'service_tier': selected.get('fast') if body.get('fast') else None}
                if not model:
                    return self._send(200, {'ok': False, 'message': 'Настройки записаны, но модель по умолчанию не определена. Выбери модель явно.'})
                ok, message, pending = console.request_settings(values, lang=body.get('lang'))
            rotation.refresh(True)
            return self._send(200, {'ok': ok, 'message': message, 'pending': pending})

    ns['H'] = FleetHandler
    ns['PAGE'] = cc_overview.render(ns['PAGE'])
    try:  # названия двух серверов (по умолчанию DEV/PROD, у новых установок A/B): подмена в страницах, ответах API и уведомлениях
        import cc_labels
        cc_labels.install(ns)
    except Exception as exc:
        print('labels: названия серверов не подключены: %r' % (exc,), flush=True)
    try:  # общая механика исполнителей: шапка Claude DEV/PROD/Codex, передача работы, уведомления о смене профилей в Telegram
        import cc_workers
        cc_workers.install(ns, profiles)
    except Exception as exc:
        print('workers: модуль не подключён: %r' % (exc,), flush=True)
    try:  # [remote] удалённый аккаунт Claude (PROD): строка, плитка, лимиты
        import cc_remote_ui
        ns['PAGE'] = cc_remote_ui.inject(ns['PAGE'])
    except Exception as exc:
        print('remote: интерфейс не подключён: %r' % (exc,), flush=True)
    try:  # [remote] передача работы на удалённый сервер (PROD) и возврат
        import cc_remote_mode
        cc_remote_mode.install(ns)
    except Exception as exc:
        print('remote: режим передачи не подключён: %r' % (exc,), flush=True)
    try:  # мастер «Второй сервер»: проверка, подключение, обратный ключ (⚙ Общие настройки)
        import cc_remote_setup
        cc_remote_setup.install(ns)
    except Exception as exc:
        print('remote: мастер второго сервера не подключён: %r' % (exc,), flush=True)
    ns['FLEET_ROTATION'] = rotation
    ns['FLEET_INPUT'] = inputs
    bridge.PROFILE_APPLIED = console.apply_plan
    if ns.get('__name__') == '__main__':
        rotation.start()
