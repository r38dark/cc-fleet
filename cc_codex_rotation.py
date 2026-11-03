"""Ротация аккаунтов Codex: быстрый снимок, отдельное обновление, смена только в паузе."""
import datetime
import json
import os
import threading
import time
from pathlib import Path


def eligible(account, model=None, effort=None, now=None, max_session=85, cap=99):
    if any(account.get(k) for k in ('error', 'stale', 'login_required', 'lapsed', 'loading')):
        return False
    if account.get('usage_allowed') is False or account.get('reached'):
        return False
    if not account.get('ts') or (time.time() if now is None else now)-account['ts'] > 180:
        return False
    windows = {w.get('mins'): w for w in account.get('windows') or []}
    session, week = windows.get(300), windows.get(10080)
    if not session or not week or session.get('pct') is None or week.get('pct') is None:
        return False
    if session['pct'] >= max_session or week['pct'] >= cap:
        return False
    if model:
        selected = next((m for m in account.get('models') or [] if m.get('id') == model), None)
        if not selected or effort and selected.get('efforts') and effort not in selected['efforts']:
            return False
    return True


def score(account, now=None):
    now = time.time() if now is None else now
    windows = {w.get('mins'): w for w in account.get('windows') or []}
    week, session = windows.get(10080) or {}, windows.get(300) or {}
    try:
        reset = datetime.datetime.fromisoformat(week['resets_at'].replace('Z', '+00:00')).timestamp()
        hours = max(0.25, (reset-now)/3600)
    except (KeyError, ValueError, TypeError):
        hours = 168
    return (100-week.get('pct', 100))/hours * (100-session.get('pct', 100))/100


class Rotation:
    def __init__(self, base, codex, console, binary, bridge):
        self.path = Path(base)/'codex_rotation.json'
        self.codex, self.console, self.binary, self.bridge = codex, console, binary, bridge
        self.lock = threading.RLock()
        self.accounts = []
        self.updated = 0
        self.refreshing = False
        self.started = False
        self.stop_event = threading.Event()
        self.last_error = ''
        self.message = 'Проверяем лимиты Codex…'
        self.state = self.codex.jload(str(self.path), {}) or {}
        self.state.setdefault('optimize', True)
        self.state.setdefault('threshold', 90)
        self.state.setdefault('weekly_cap', 99)
        self.state.setdefault('min_switch_sec', 1800)

    def active(self):
        return self.bridge.load().get('slot') or self.console._meta().get('slot') or next(iter(self.codex.profile_slots()), '')

    def save(self):
        self.codex._jsave(str(self.path), self.state)
        os.chmod(self.path, 0o600)

    def configure(self, body):
        with self.lock:
            changed = dict(self.state)
            if 'optimize' in body:
                if not isinstance(body['optimize'], bool):
                    return False, 'Оптимизация должна быть включена или выключена.'
                changed['optimize'] = body['optimize']
            for key in ('threshold', 'weekly_cap'):
                if key in body:
                    value = body[key]
                    if isinstance(value, bool) or not isinstance(value, int) or not 50 <= value <= 100:
                        return False, 'Порог должен быть целым числом от 50 до 100.'
                    changed[key] = value
            self.state = changed
            self.save()
        return True, 'Настройки оптимизации Codex сохранены.'

    def refresh(self, force=False):
        with self.lock:
            if self.refreshing or not force and time.time()-self.updated < 60:
                return
            self.refreshing = True
        def work():
            try:
                binary = self.binary()
                rows = self.codex.get_accounts(binary, force=force) if binary else []
                with self.lock:
                    self.accounts, self.updated = rows, time.time()
            except Exception as exc:
                self.last_error = 'Не удалось обновить лимиты: '+type(exc).__name__
            finally:
                with self.lock:
                    self.refreshing = False
        threading.Thread(target=work, name='codex-account-snapshot', daemon=True).start()

    def snapshot(self, force=False):
        self.refresh(force)
        with self.lock:
            rows = [dict(row) for row in self.accounts]
            loading = self.refreshing
        # Добавленные/удалённые профили видны сразу, даже пока прежний снимок обновляется.
        by_slot = {row['slot']: row for row in rows}
        rows = [by_slot.get(slot) or dict(self.codex.meta(slot), slot=slot, windows=[], models=[], loading=True)
                for slot in self.codex.profile_slots()]
        return {'ok': True, 'available': bool(self.binary()), 'accounts': rows, 'loading': loading,
                'ts': self.updated}

    def public(self):
        active = self.active()
        settings = self.console.active_settings() if self.console._pid() else {}
        with self.lock:
            candidates = [a for a in self.accounts if a.get('slot') != active and eligible(
                a, settings.get('model'), settings.get('effort'), max_session=min(85, self.state['threshold']), cap=self.state['weekly_cap'])]
            candidates.sort(key=score, reverse=True)
            next_account = candidates[0] if candidates else {}
            message = self.message
            if not self.state['optimize']:
                message = 'Ручной выбор аккаунта Codex'
            elif len(self.accounts) == 1:
                message = 'Один аккаунт; ротация начнётся после добавления других.'
            elif self.accounts and not candidates:
                message = 'Нет подтверждённых кандидатов с запасом лимитов для выбранной модели.'
            pending = self.console._meta().get('pending_settings') or {}
            if pending:
                message = 'Модель '+str(pending.get('model') or 'по умолчанию')+' сохранена; ждём завершения текущего ответа.'
            return {'ok': True, 'optimize': self.state['optimize'], 'active': active,
                    'threshold': self.state['threshold'], 'weekly_cap': self.state['weekly_cap'],
                    'next': next_account.get('slot'), 'next_label': next_account.get('label') or next_account.get('email'),
                    'message': message, 'last_error': self.last_error, 'updated': self.updated,
                    'model': settings.get('model'), 'effort': settings.get('effort'),
                    'pending_model': pending.get('model'), 'history': self.state.get('history', [])[-15:]}

    def _store_slot(self, slot):
        with self.bridge._lock:
            config = self.bridge.load()
            config['slot'] = slot
            self.bridge._save(config)

    def switch(self, slot, manual=False, reason='Плановая оптимизация'):
        with self.lock:
            if manual and self.state['optimize']:
                return False, 'Выключи оптимизацию Codex для ручного выбора аккаунта.'
            old = self.active()
            if slot == old:
                return True, 'Этот аккаунт уже выбран.'
            if slot not in self.codex.profile_slots():
                return False, 'Неизвестный аккаунт Codex.'
            selected = next((a for a in self.accounts if a.get('slot') == slot), None)
            saved = self.console.active_settings() if self.console._pid() else {}
            if not selected or not eligible(selected, saved.get('model'), saved.get('effort'), max_session=100,
                                             cap=self.state['weekly_cap']):
                return False, 'Аккаунт недоступен, лимиты устарели или выбранная модель не подтверждена.'
            if self.console.busy():
                return False, 'Переключение отложено: в Codex идёт ответ.'
            # Предпочтения следующего аккаунта не должны сбросить выбранную модель/effort/Fast.
            if saved.get('model') and saved.get('service_tier') in (None, 'priority', 'fast'):
                selected_model = next((m for m in selected.get('models') or [] if m.get('id') == saved['model']), {})
                if saved.get('service_tier') and selected_model.get('fast') != saved['service_tier']:
                    return False, 'Следующий аккаунт не поддерживает выбранный режим Fast.'
                ok, message = self.codex.set_prefs(self.binary(), slot, saved['model'], saved.get('effort') or '',
                                                  bool(saved.get('service_tier')))
                if not ok:
                    return False, message
            if not self.console._ask_lock.acquire(blocking=False):
                return False, 'Переключение отложено: консоль занята.'
            try:
                if self.console.current_turn_open():
                    return False, 'Переключение отложено: в Codex идёт ответ.'
                running = bool(self.console._pid())
                if running:
                    meta = self.console._meta()
                    meta['pending_settings'] = saved
                    self.codex._jsave(self.console._meta_path(), meta)
                    self.codex.own(self.console._meta_path())
                    ok, message = self.console.stop()
                    if not ok:
                        return False, message
                self._store_slot(slot)
                if running:
                    ok, message = self.console.start()
                    if ok:
                        ok, message = self.console.verify_ready()
                    if not ok:
                        self.console.stop()
                        self._store_slot(old)
                        # start() уже мог заменить metadata: возвращаем исходные настройки и ID.
                        self.codex._jsave(self.console._meta_path(), dict(meta, pending_settings=saved))
                        self.codex.own(self.console._meta_path())
                        restored, _ = self.console.start()
                        if restored:
                            restored, _ = self.console.verify_ready()
                        self.last_error = ('Смена аккаунта не удалась; восстановлен предыдущий аккаунт.' if restored else
                                           'Смена аккаунта отменена; прежний аккаунт выбран, но консоль требует проверки запуска.')
                        return False, self.last_error
                self.state['last_switch'] = time.time()
                event = {'ts': int(time.time()), 'from': old, 'to': slot, 'reason': reason,
                         'model': saved.get('model'), 'effort': saved.get('effort')}
                self.state['history'] = (self.state.get('history', [])+[event])[-50:]
                self.save()
                self.message, self.last_error = reason, ''
                return True, 'Аккаунт Codex переключён с сохранением беседы, модели и профиля.'
            finally:
                self.console._ask_lock.release()

    def tick(self):
        self.refresh()
        # Профиль/папка/MCP, изменённые во время ответа, применяются и без нового сообщения.
        if not self.console.busy():
            self.console.apply_plan()
        with self.lock:
            if not self.state['optimize'] or self.refreshing or not self.console._pid():
                return
            active = self.active()
            current = next((a for a in self.accounts if a.get('slot') == active), None)
            if (not current or current.get('error') and not current.get('login_required')
                    or current.get('stale') or current.get('loading')
                    or not current.get('ts') or time.time()-current['ts'] > 180):
                return
            settings = self.console.active_settings()
            pool = [a for a in self.accounts if a.get('slot') != active and eligible(
                a, settings.get('model'), settings.get('effort'), max_session=min(85, self.state['threshold']), cap=self.state['weekly_cap'])]
            if not pool:
                return
            best = max(pool, key=score)
            windows = {w.get('mins'): w for w in current.get('windows') or []}
            session, week = windows.get(300) or {}, windows.get(10080) or {}
            forced = bool(current.get('reached') or current.get('usage_allowed') is False or current.get('login_required')
                          or current.get('lapsed') or session.get('pct', 0) >= self.state['threshold']
                          or week.get('pct', 0) >= self.state['weekly_cap'])
            planned = (time.time()-self.state.get('last_switch', 0) >= self.state['min_switch_sec']
                       and eligible(current, settings.get('model'), settings.get('effort'), max_session=100)
                       and score(best) > max(.001, score(current))*1.5)
            if not forced and not planned:
                return
            reason = 'Достигнут порог лимита' if forced else 'Больше доступного запаса до близкого сброса'
            if self.console.busy():
                self.message = 'Следующий аккаунт выбран; смена после текущего ответа.'
                return
        self.switch(best['slot'], reason=reason)

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
        def loop():
            while not self.stop_event.wait(5):
                try:
                    self.tick()
                except Exception as exc:
                    self.last_error = 'Оптимизация временно недоступна: '+type(exc).__name__
        threading.Thread(target=loop, daemon=True, name='codex-rotation').start()
