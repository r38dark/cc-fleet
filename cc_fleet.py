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


class ConsoleInput:
    def __init__(self, ns):
        self.ns = ns
        self.locks = {'claude': threading.Lock(), 'codex': threading.Lock()}
        self.receipts = {}
        self.lock = threading.Lock()

    def send(self, session, text, request_id):
        if session not in self.locks:
            return False, 'Неизвестная консоль.'
        if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > 48000:
            return False, 'Нужно непустое сообщение размером до 48 КБ.'
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_id):
            return False, 'Неверный идентификатор отправки.'
        text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]', '', text.replace('\r\n', '\n').replace('\r', '\n')).strip()
        digest = hashlib.sha256(text.encode()).hexdigest()
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
                result = self.ns['cc_codex_console'].send_input(text)
            else:
                result = self._claude(text)
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
        if self.ns['session_busy']():
            return False, 'В консоли Claude идёт ответ. Дождись завершения или нажми Esc.'
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
    rotation = cc_codex_rotation.Rotation(ns['BASE'], codex, console, ns['codex_bin'], bridge)
    models = cc_codex_models.Discovery(codex, rotation, ns['codex_bin'])
    inputs = ConsoleInput(ns)
    ns['FLEET_ROTATION'] = rotation
    bridge.LIMIT_PAUSE = rotation.limit_pause  # [notion-ai] очередь моста ждёт сброса, если лимит исчерпан и переключаться некуда
    import cc_profiles
    profiles = cc_profiles.bind(ns, inputs)
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
            if not path.startswith('/api/profiles/') and path not in ('/api/console/input', '/api/console/key', '/api/chatgpt/rotation/config', '/api/chatgpt/rotation/switch', '/api/chatgpt/models/check', '/api/notion/save'):
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
                if path == '/api/notion/save':
                    if 'reserve' in body:
                        return self._send(200, dict(ok=False, message='Настройки резерва доступны в меню профилей. Аварийный сценарий удалён.'))
                    config = ns['cfg']()
                    ok, conf, error = ns['cc_notion'].save(config.get('notion_agent') or {}, body)
                    if not ok:
                        return self._send(400, dict(ok=False, message='Не принято поле настроек агента.', field=error))
                    config['notion_agent'] = conf
                    ns['jsave'](ns['CONFIG'], config)
                    return self._send(200, dict(ok=True, notion=ns['cc_notion'].public()))
                if path == '/api/chatgpt/models/check':
                    return self._send(200, models.start())
                if path.startswith('/api/profiles/'):
                    parts = path.split('/')
                    result = (profiles.apply_scenario(body) if path == '/api/profiles/scenario/apply' else
                              profiles.tasks.confirm(body) if path == '/api/profiles/task/confirm' else
                              profiles.action(parts[3] if len(parts)>3 else '',parts[4] if len(parts)>4 else '',body))
                    return self._send(200, result)
                if path == '/api/console/input':
                    if body.get('session') in ('claude','codex') and not profiles.input_allowed(body['session']):
                        return self._send(200, dict(ok=False, message='Консоль не участвует в текущем сценарии. Измени общую схему в выборе профилей.'))
                    ok, message = inputs.send(body.get('session'), body.get('text'), body.get('request_id'))
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
    try:  # [notion-ai] профиль «Notion AI · только он» + уведомления о смене профилей в Telegram
        import cc_notion_ai
        cc_notion_ai.install(ns, profiles)
    except Exception as exc:
        print('notion-ai: модуль не подключён: %r' % (exc,), flush=True)
    ns['FLEET_ROTATION'] = rotation
    ns['FLEET_INPUT'] = inputs
    bridge.PROFILE_APPLIED = console.apply_plan
    if ns.get('__name__') == '__main__':
        rotation.start()
