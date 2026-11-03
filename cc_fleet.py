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
    inputs = ConsoleInput(ns)
    original = ns['H']

    class FleetHandler(original):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path not in ('/api/chatgpt/rotation', '/api/chatgpt'):
                return original.do_GET(self)
            if not self._authed():
                return self._send(403, {'ok': False, 'message': 'forbidden'})
            if parsed.path == '/api/chatgpt':
                force = bool(parse_qs(parsed.query).get('refresh'))
                return self._send(200, rotation.snapshot(force))
            rotation.refresh()
            return self._send(200, rotation.public())

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in ('/api/console/input', '/api/console/key', '/api/chatgpt/rotation/config', '/api/chatgpt/rotation/switch'):
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
                if path == '/api/console/input':
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
    ns['FLEET_ROTATION'] = rotation
    ns['FLEET_INPUT'] = inputs
    bridge.PROFILE_APPLIED = console.apply_plan
    if ns.get('__name__') == '__main__':
        rotation.start()
