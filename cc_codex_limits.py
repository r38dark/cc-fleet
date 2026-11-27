"""Лимиты, пауза и параметры текущего аккаунта Codex."""
import datetime
import json
import math
import os
import threading
import time
from pathlib import Path


WIN_NAMES = {300: '5 ч', 10080: 'неделя'}
BAD = ('error', 'stale', 'login_required', 'lapsed', 'loading')


def _iso_ts(iso):
    try:
        return datetime.datetime.fromisoformat(str(iso).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return None


def real_limit(account):
    """Настоящий лимит исчерпан (окно 100% или сервис сказал «лимит»)
    → (да/нет, когда освободится — ts или None, длины исчерпанных окон в минутах)."""
    wins = [w for w in account.get('windows') or [] if w.get('pct') is not None]
    full = [w for w in wins if w['pct'] >= 100]
    if not full and (account.get('reached') or account.get('usage_allowed') is False):
        full = [min(wins, key=lambda w: w.get('mins') or 0)] if wins else [{}]
    if not full:
        return False, None, []
    ts = [t for t in (_iso_ts(w.get('resets_at')) for w in full) if t]
    return True, (max(ts) if ts else None), [w.get('mins') for w in full if w.get('mins')]


def policy_limit(account, threshold=90, weekly_cap=99, override=False, now=None, grace=120):
    """Окна, которые удерживают аккаунт по выбранным порогам; override не обходит100%."""
    now = time.time() if now is None else now
    held=[];expired=False
    for w in account.get('windows') or []:
        m=w.get('mins');pct=w.get('pct');cap=100 if override else threshold if m==300 else weekly_cap if m==10080 else 100
        if not isinstance(pct,(int,float)) or not math.isfinite(pct) or pct<cap:continue
        until=_iso_ts(w.get('resets_at'))
        if until is not None and now>until+grace:expired=True;continue
        held.append((w,until))
    reported=bool(account.get('reached') or account.get('usage_allowed') is False)
    return held,reported,expired


def limit_pause_state(accounts, active, now=None, grace=120, threshold=90, weekly_cap=99, override=False):
    """Собственная квота Codex действует и при единственном аккаунте."""
    now = time.time() if now is None else now
    cur = next((a for a in accounts if a.get('slot') == active), None)
    if not cur or any(cur.get(k) for k in BAD) or not cur.get('ts') or now-cur['ts']>180:
        return {'active':False,'unknown':True}
    held,reported,expired=policy_limit(cur,threshold,weekly_cap,override,now,grace)
    if not held and not reported:return {'active':False,'expired':expired,'override':override}
    mins=sorted({w['mins'] for w,_ in held if isinstance(w.get('mins'),int) and w['mins']>0})
    until=max(t for _,t in held) if held and all(t is not None for _,t in held) else None
    lab = lambda a: a.get('label') or a.get('email') or a.get('slot') or ''
    pct = lambda a, m: next((w.get('pct') for w in a.get('windows') or [] if w.get('mins') == m), None)
    hard=reported or any(w.get('pct',0)>=100 for w,_ in held)
    return {'active': True, 'paused':True,'slot': active, 'label': lab(cur), 'windows': mins,
            'window_names': [WIN_NAMES.get(m, f"{round(m / 60)} ч") for m in mins],
            'resume_at': until,
            'resets':{str(w['mins']):u for w,u in held if w.get('mins') and u is not None},
            'percentages':{str(w['mins']):w.get('pct') for w,u in held if w.get('mins')},
            'policy':not hard,'hard':bool(hard),'override':override,'can_override':not hard,
            'threshold':threshold,'weekly_cap':weekly_cap,
            'accounts': [{'label': lab(cur), 'active': True, 'ses': pct(cur, 300), 'week': pct(cur, 10080)}]}


def limit_notice_state(accounts, active, pause=None, now=None, grace=120):
    """Read-only limit warning, including a standalone account; never gates input."""
    now = time.time() if now is None else now
    cur = next((a for a in accounts if a.get('slot') == active), None)
    if (not cur or any(cur.get(k) for k in BAD) or not cur.get('ts')
            or now - cur['ts'] > 180):
        return {'active': False}
    full = []
    expired = False
    for w in cur.get('windows') or []:
        try:
            pct = float(w.get('pct'))
        except (ValueError, TypeError):
            continue
        if not math.isfinite(pct) or pct < 100:
            continue
        until = _iso_ts(w.get('resets_at'))
        if until is not None and now > until + grace:
            expired = True
            continue
        full.append((w, until))
    reported = bool(cur.get('reached') or cur.get('usage_allowed') is False)
    if not full and not reported:
        return {'active': False, 'expired': expired}
    mins = sorted({w['mins'] for w, _ in full if isinstance(w.get('mins'), int) and w['mins'] > 0})
    # An unspecified service limit has no known window/reset; do not guess 5 h.
    until = max(t for _, t in full) if full and all(t is not None for _, t in full) else None
    # сброс каждого исчерпанного окна (минуты → ts): панель пишет на плитке «лимит недели / 5 ч исчерпан до …» о том, что кончается позже
    resets = {str(w['mins']): t for w, t in full if isinstance(w.get('mins'), int) and w['mins'] > 0 and t is not None}
    lab = lambda a: a.get('label') or a.get('email') or a.get('slot') or ''
    pct = lambda m: next((w.get('pct') for w in cur.get('windows') or [] if w.get('mins') == m), None)
    notice = dict(active=True, paused=bool((pause or {}).get('active')),
                  slot=active, label=lab(cur), windows=mins, resets=resets,
                  window_names=[WIN_NAMES.get(m, f'{round(m / 60)} ч') for m in mins],
                  resume_at=until,
                  accounts=[dict(label=lab(cur), active=True, ses=pct(300), week=pct(10080))])
    if notice['paused']:
        for key in ('accounts',):
            if key in pause:
                notice[key] = pause[key]
        if until is not None and pause.get('resume_at') is not None:
            notice['resume_at'] = pause['resume_at']
    return notice


class AccountLimits:

    def __init__(self, base, codex, console, binary, bridge):
        self.path = Path(base)/'codex_rotation.json'
        self.codex, self.console, self.binary, self.bridge = codex, console, binary, bridge
        self.lock = threading.RLock()
        self.accounts = []
        self.updated = 0
        self.refreshing = False
        self.started = False
        self.stop_event = threading.Event()
        self.suspended = lambda: False
        self.last_error = ''
        self.message = 'Проверяем лимиты Codex…'
        self.state = self.codex.jload(str(self.path), {}) or {}
        self.state.setdefault('threshold', 90)
        self.state.setdefault('weekly_cap', 99)
        for key in ('optimize', 'min_switch_sec', 'last_switch', 'history'):
            self.state.pop(key, None)

    def active(self):
        return next(iter(self.codex.profile_slots()), '')

    def save(self):
        self.codex._jsave(str(self.path), self.state)
        os.chmod(self.path, 0o600)

    def configure(self, body):
        with self.lock:
            changed = dict(self.state)
            if 'pause_override' in body:
                value=body['pause_override']
                if not isinstance(value,bool):return False,'Отключение паузы должно быть включено или выключено.'
                cur=next((a for a in self.accounts if a.get('slot')==self.active()),{})
                hard,_,_=real_limit(cur)
                if value and (hard or not cur or any(cur.get(k) for k in BAD) or not cur.get('ts') or time.time()-cur['ts']>180):
                    return False,'Настоящий лимит уже исчерпан или нет свежих данных. Его нельзя отключить.'
                changed.update(pause_override=value,override_slot=self.active() if value else '',override_until=0)
                if value:
                    wins,_,_=policy_limit(cur,changed['threshold'],changed['weekly_cap'])
                    changed['override_until']=max((u for _,u in wins if u),default=0)
            for key in ('threshold', 'weekly_cap'):
                if key in body:
                    value = body[key]
                    if isinstance(value, bool) or not isinstance(value, int) or not 50 <= value <= 100:
                        return False, 'Порог должен быть целым числом от 50 до 100.'
                    changed[key] = value
            self.state = changed
            self.save()
        if getattr(self,'quota',None):self.quota.tick()
        return True, 'Настройки лимитов Codex сохранены.'

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
                    for row in rows:
                        models = self.codex.cached_models(row['slot'])
                        if models is not None:
                            row['models'] = models
                    self.accounts, self.updated = rows, time.time()
            except Exception as exc:
                self.last_error = 'Не удалось обновить лимиты: '+type(exc).__name__
            finally:
                with self.lock:
                    self.refreshing = False
        threading.Thread(target=work, name='codex-account-snapshot', daemon=True).start()

    def publish_models(self, slot, models):
        with self.lock:
            self.accounts = [dict(row, models=models) if row['slot'] == slot else row
                             for row in self.accounts]

    def snapshot(self, force=False):
        self.refresh(force)
        with self.lock:
            rows = [dict(row) for row in self.accounts]
            loading = self.refreshing
        # Добавленные/удалённые профили видны сразу, даже пока прежний снимок обновляется.
        by_slot = {row['slot']: row for row in rows}
        rows = [by_slot.get(slot) or dict(self.codex.meta(slot), slot=slot, windows=[], models=[], loading=True)
                for slot in self.codex.profile_slots()]
        runtime = {'running': False}
        if self.console._pid():
            meta = self.console._meta()
            settings = self.console.active_settings()
            pending = meta.get('pending_settings') or {}
            runtime = dict(running=True, slot=meta.get('slot'),
                           **{key: settings.get(key) for key in ('model', 'effort', 'service_tier')},
                           pending={key: pending[key] for key in ('model', 'effort', 'service_tier') if key in pending} or None)
        return {'ok': True, 'available': bool(self.binary()), 'accounts': rows, 'loading': loading,
                'ts': self.updated, 'runtime': runtime}

    def public(self):
        active = self.active()
        settings = self.console.active_settings() if self.console._pid() else {}
        with self.lock:
            pending = self.console._meta().get('pending_settings') or {}
            message = self.message
            if pending:
                message = 'Модель '+str(pending.get('model') or 'по умолчанию')+' сохранена; ждём завершения текущего ответа.'
            return {'ok': True, 'active': active,
                    'threshold': self.state['threshold'], 'weekly_cap': self.state['weekly_cap'],
                    'message': message, 'last_error': self.last_error, 'updated': self.updated,
                    'model': settings.get('model'), 'effort': settings.get('effort'),
                    'pending_model': pending.get('model'),
                    'limit_pause': self.limit_pause(), 'limit_notice': self.limit_notice(),
                    'quota':self.quota.public() if getattr(self,'quota',None) else {}}

    def limit_pause(self, now=None):
        """Пауза очереди моста. Визуальное предупреждение вычисляется отдельно."""
        active = self.active()
        with self.lock:
            rows = [dict(a) for a in self.accounts]
            if getattr(self,'codex',None) and hasattr(self.codex,'profile_slots'):
                slots=set(self.codex.profile_slots())
                if not slots:return dict(active=False,disconnected=True)
                rows=[a for a in rows if a.get('slot') in slots]
            th, cap = self.state['threshold'], self.state['weekly_cap']
            override=bool(self.state.get('pause_override'))
            if override:
                cur=next((a for a in rows if a.get('slot')==active),{})
                wins,reported,_=policy_limit(cur,th,cap,now=now)
                expired_override=self.state.get('override_until') and (time.time() if now is None else now)>self.state['override_until']+120
                if self.state.get('override_slot')!=active or expired_override or (cur and not any(cur.get(k) for k in BAD) and not wins and not reported):
                    self.state.update(pause_override=False,override_slot='',override_until=0);self.save();override=False
        value=limit_pause_state(rows,active,now,threshold=th,weekly_cap=cap,override=override)
        guard=getattr(self,'quota',None)
        return guard.fallback(value,override) if guard and value.get('unknown') else value

    def limit_notice(self, now=None):
        """UI-only warning; the bridge continues to use limit_pause unchanged."""
        active = self.active()
        slots = set(self.codex.profile_slots())
        slots.intersection_update({active})
        with self.lock:
            rows = [dict(a) for a in self.accounts if a.get('slot') in slots]
        pause = self.limit_pause(now)
        notice = limit_notice_state(rows, active, pause, now)
        # A real queue hold must remain visible even if its last usage sample aged out.
        if notice['active']:return dict(notice,hard=True,override=bool(self.state.get('pause_override')),can_override=False)
        if pause.get('active'):return dict(pause,paused=True)
        soft=limit_pause_state(rows,active,now,threshold=self.state['threshold'],weekly_cap=self.state['weekly_cap'])
        if soft.get('active'):return dict(soft,paused=bool(pause.get('active')),override=bool(self.state.get('pause_override')))
        return notice if not pause.get('active') else dict(pause,paused=True)

    def tick(self):
        self.refresh()
        if getattr(self,'quota',None):self.quota.tick()
        if self.suspended():return
        # Профиль/папка/MCP, изменённые во время ответа, применяются и без нового сообщения.
        if not self.console.busy() and not self.limit_pause().get('active'):
            self.console.apply_plan()
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
                    self.last_error = 'Ошибка проверки лимитов Codex: '+type(exc).__name__
        threading.Thread(target=loop, daemon=True, name='codex-limits').start()
