"""Durable mirrored profiles; all console changes are explicit, checked transactions."""
import copy
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import threading
import time
import uuid

from cc_claude_profile import ClaudeProfile, ProfileError, atomic
from cc_profile_state import ProfileScenarios, ProfileState, ENGINES

class NativeProfiles:
    def __init__(self, ns):
        self.ns = ns;self.base = Path(ns['BASE']);self.claude = ClaudeProfile(ns);self.manager = None
        self.bridge = ns['cc_codex_bridge'];self.codex = ns['cc_codex_console'];self.emergency = ns['cc_codex_emergency']
        initial_settings=self.bridge.load()
        self.initial_codex = {k:initial_settings.get(k) for k in ('mode','access','task_rights','profile','workdir','project')}
        self.claude_cwd = ns['_session_cwd']() or os.path.expanduser('~')
        self.claude_work = str(self.base.parent/'claude-work')
        self.exchange_root = self.base/'profile_exchange'

    def seed(self):
        state = ProfileState()
        pid = self.bridge.active_profile(self.bridge.load())
        if pid == 'orchestrator':
            state.selected['codex'] = 'orchestrator'
            state.leader = 'codex'
        # Только принимаем существующую сессию; права применяются по явному выбору.
        return state

    def _remote(self):
        # Пока работа на PROD, слот Claude в профилях — Claude на PROD: локальную консоль не трогаем.
        rm=self.ns.get('REMOTE_MODE')
        return rm if rm is not None and rm.active() else None

    def _announce(self, state, strict=True):
        rm=self.ns['REMOTE_MODE'];role=self.plan(state,'claude')['role']
        if role not in rm.ROLE_TEXT:return
        ok=False
        try:ok=rm.announce_role(role)
        except Exception:pass
        if not ok and strict:raise ProfileError('claude_prod_role_failed')

    def busy(self):
        # A paused queue worker may be alive while waiting; it must not prevent unpausing.
        if self.ns.get('_busy_tick'):self.ns['_busy_tick'](self.ns['screen_hardcopy']())
        bridge_busy = self.bridge.BRIDGE.busy() and self.manager.input_allowed('codex')
        remote=self._remote()
        return bool(self.codex.busy() or bridge_busy or self.ns['session_busy']() or remote and remote.prod_busy())

    def plan(self, state, e):
        data=state.public()['engines'][e];profile=next(p for p in state.definitions(e) if p['id']==data['base_selected'])
        service=state.service if state.service and state.service['engine']==e else None
        access=profile['access']
        if service:
            access='full' if service['kind']=='emergency' or service.get('emergency') or service.get('access')=='full' else 'write'
        mode='self' if service or data['role']=='executor' else profile['mode']
        return dict(role=data['role'],profile=data['selected'],base=data['base_selected'],access=access,mode=mode,task_rights=profile.get('task_rights','dev'),leader=state.leader,service=copy.deepcopy(service))

    def prompt(self, state, e):
        data=state.public()['engines'][e];other='codex' if e=='claude' else 'claude';name=e.capitalize() if e=='claude' else 'Codex';op=other.capitalize() if other=='claude' else 'Codex'
        prefix='[Профиль балансера: '+data['label']+'.] '
        if e=='claude' and self.plan(state,e)['access']!='full':prefix+='Папка для файлов: '+(str(self.manager.exchange('claude')) if data['role']=='leader' else self.claude_work)+'. Используй абсолютные пути. '
        if data['role']=='leader':
            out=self.manager.exchange(e)/'outbox/task.md'
            return prefix+f'Ты ведущий, {op} исполнитель. Проект самостоятельно не изменяй. Один проверяемый шаг запиши в {out}; первая строка права: чтение / дев / полные. Шаг уходит исполнителю только после подтверждения человека в балансере. Не вызывай второго исполнителя самостоятельно и не создавай встречные связки. После получения результата проверь его относительно цели и подготовь следующий шаг либо сообщи итог.'
        if data['role']=='executor':return prefix+f'Ты исполнитель {op}. Выполняй только подтверждённый шаг и его ограничения. Не делегируй задачу ведущему или другим агентам. Верни проверенный результат и проверки.'
        return prefix+'Работай самостоятельно в пределах настроенных прав пользователя ОС. '+self.bridge.team_note('Другой исполнитель не используется.')+' Согласование изменений с человеком сохраняется; секреты не выводи.'

    def claude_policy(self, state):
        plan=self.plan(state,'claude');cwd=self.claude_cwd if plan['access']=='full' else str(self.manager.exchange('claude')) if plan['role']=='leader' else self.claude_work
        project=self.bridge.project_dir()
        workspace=cwd
        return dict(expires=0,access=plan['access'],paused=plan['role']=='paused',cwd=self.claude_cwd,workspace=workspace,
                    write_roots=[workspace],read_roots=list(dict.fromkeys([workspace,str(self.manager.exchange('claude')),str(self.manager.exchange('codex'))]+([project] if project else []))))

    def capture(self, changed):
        out={}
        if 'codex' in changed:
            settings=self.bridge.load()
            out['codex_settings']={k:settings.get(k) for k in ('mode','access','task_rights','profile','workdir','project')}
            out['codex_runtime']=self.codex.active_settings()
            out['codex_sandbox']=self.codex.status().get('sandbox')
        remote=self._remote()
        if 'claude' in changed and remote:out['claude_remote']=dict(tg=remote.tg())
        elif 'claude' in changed:
            try:
                out['claude']=self.claude.capture()
                expected = getattr(self, '_handoff_snapshot', None)
                if expected:
                    if out['claude'].get('thread_id') != expected.get('thread_id'):raise ProfileError('claude_history_unknown')
                    out['claude']['model'], out['claude']['effort'] = expected['model'], expected.get('effort')
                if getattr(self, '_handoff_telegram', False):out['claude']['telegram_channel'] = True
                if getattr(self, '_handoff_sandbox_root', False):out['claude']['sandbox_root'] = True
            except ProfileError as exc:
                if str(exc)!='claude_console_missing':raise
                out['claude_absent']=True
        return out

    def preflight(self, before, after, changed, captured):
        if self.busy():raise ProfileError('console_busy')
        legacy=self.bridge._state()
        if legacy.get('pending') or any(t.get('state') in ('sent','accepted') for t in (legacy.get('tasks') or {}).values()):raise ProfileError('legacy_task_pending')
        for e in ENGINES:
            out=self.manager.exchange(e)/'outbox';out.mkdir(parents=True,exist_ok=True)
            for directory in (out.parent.parent,out.parent,out):
                if directory.is_symlink():raise ProfileError('exchange_symlink_rejected')
            if e=='codex':self.ns['cc_codex'].own(str(out))
        if after.service and after.service.get('access')=='full' and after.service!=before.service:
            engine=after.service['engine']
            actual_full=(captured.get('codex_settings',{}).get('access')=='full' and captured.get('codex_sandbox')=='danger-full-access' if engine=='codex'
                         else captured.get('claude',{}).get('bypass',False))
            if not actual_full:raise ProfileError('full_access_not_active')
        if 'claude' in changed and 'claude_remote' in captured:
            rm=self.ns['REMOTE_MODE']
            if self.plan(after,'claude')['role'] in rm.ROLE_TEXT and not rm.prod_ready():raise ProfileError('claude_prod_not_ready')
        if 'claude' in changed and 'claude_remote' not in captured:Path(self.claude_work).mkdir(parents=True,exist_ok=True)
        if 'claude' in changed and 'claude_remote' not in captured:
            if captured.get('claude_absent'):
                if not self.claude_policy(after)['paused']:raise ProfileError('claude_history_unknown')
            else:self.claude.prepare(captured['claude'],self.claude_policy(after),self.prompt(after,'claude'))
        if 'codex' in changed and not captured.get('codex_runtime',{}).get('thread_id'):raise ProfileError('codex_history_unknown')
        if after.service and after.service['engine']=='codex' and (after.service['kind']=='emergency' or after.service.get('emergency')):
            plan,error=self.emergency._plan()
            if error:raise ProfileError('emergency_not_configured')

    def _codex_pause(self, on):
        path=self.base/'profile_runtime/codex-paused.json'
        if not on:
            try:rows=json.loads(path.read_text())
            except (OSError,ValueError):rows=[]
            for row in rows:
                try:
                    start=Path('/proc/'+str(row['pid'])+'/stat').read_text().rsplit(')',1)[1].split()[19]
                    if start==row['start']:os.kill(row['pid'],signal.SIGCONT)
                except (OSError,KeyError):pass
            path.unlink(missing_ok=True);return
        if path.exists():return
        level=[str(self.codex._pid() or '')];rows=[]
        for _ in range(5):
            nxt=[]
            for pid in level:
                try:nxt+=Path('/proc/'+pid+'/task/'+pid+'/children').read_text().split()
                except OSError:pass
            for pid in nxt:
                try:
                    if Path('/proc/'+pid+'/comm').read_text().strip()=='codex':rows.append(dict(pid=int(pid),start=Path('/proc/'+pid+'/stat').read_text().rsplit(')',1)[1].split()[19]))
                except OSError:pass
            level=nxt
        if not rows:raise ProfileError('codex_pause_process_missing')
        atomic(path,rows)
        for row in rows:os.kill(row['pid'],signal.SIGSTOP)

    def ensure_codex(self):
        ok,message=self.codex.apply_plan() if self.codex._pid() else self.codex.start()
        if ok:ok,message=self.codex.verify_ready()
        return ok,message

    def apply(self, before, after, changed, captured):
        self._codex_pause(False)
        prev_emg=bool(before.service and before.service['engine']=='codex' and (before.service['kind']=='emergency' or before.service.get('emergency')))
        next_emg=bool(after.service and after.service['engine']=='codex' and (after.service['kind']=='emergency' or after.service.get('emergency')))
        if prev_emg and not next_emg:
            ok,_=self.emergency.off('смена профиля',quiet=True)
            if not ok:raise ProfileError('emergency_teardown_failed')
        if 'codex' in changed:
            plan=self.plan(after,'codex')
            if not next_emg and plan['role']!='paused':
                config=self.bridge.load();config.update(mode=plan['mode'],access=plan['access'],task_rights=plan['task_rights'],profile=plan['profile'] if plan['profile']!='emergency' else '')
                # Keep the user's selected workdir; the native leader sandbox still uses exchange.
                if not config.get('workdir'):config['workdir']=self.initial_codex.get('workdir') or self.bridge.workspace_dir()
                with self.bridge._lock:self.bridge._save(config)
                self.bridge.ensure_exchange()
            if next_emg and not prev_emg:
                ok,_=self.emergency.on('аварийный',auto='подтверждено в профилях')
                if not ok:raise ProfileError('emergency_start_failed')
                after.until=self.emergency.until() or 0
            if plan['role']!='paused':
                ok,_=self.ensure_codex()
                if not ok:raise ProfileError('codex_resume_locked' if 'занята другим подключением' in _ else 'codex_apply_failed')
                saved=captured['codex_runtime'];current=self.codex.active_settings()
                for key in ('model','effort','thread_id'):
                    if saved.get(key) and current.get(key)!=saved[key]:raise ProfileError('codex_'+key+'_changed')
            if plan['role']=='paused':self._codex_pause(True)
        if 'claude' in changed and 'claude_remote' in captured:self._announce(after)
        elif 'claude' in changed and not captured.get('claude_absent'):self.claude.apply(captured['claude'],self.claude_policy(after),self.prompt(after,'claude'))

    def rollback(self, before, changed, captured):
        self._codex_pause(False)
        if 'codex' in changed:
            wanted=bool(before.service and before.service['engine']=='codex' and (before.service['kind']=='emergency' or before.service.get('emergency')))
            if self.emergency.active() and not wanted:
                ok,_=self.emergency.off('откат профиля',quiet=True)
                if not ok:raise ProfileError('rollback_emergency_failed')
            if wanted and not self.emergency.active():raise ProfileError('emergency_revoked_no_regrant')
            config=self.bridge.load();config.update(captured['codex_settings'])
            with self.bridge._lock:self.bridge._save(config)
            meta=self.codex._meta();meta['pending_settings']=captured['codex_runtime'];self.ns['cc_codex']._jsave(self.codex._meta_path(),meta);self.ns['cc_codex'].own(self.codex._meta_path())
            if not wanted:
                ok,_=self.ensure_codex()
                if not ok:raise ProfileError('rollback_codex_failed')
            if self.plan(before,'codex')['role']=='paused':self._codex_pause(True)
        if 'claude' in changed and 'claude_remote' in captured:self._announce(before,strict=False)
        elif 'claude' in changed and not captured.get('claude_absent'):self.claude.apply(captured['claude'],self.claude_policy(before),self.prompt(before,'claude'))

    def recovery_matches(self,before,changed,captured):
        """Clear a stale barrier only after a read-only check of the old runtime."""
        try:
            if 'codex' in changed:
                if not self.codex._pid():return False
                settings=self.bridge.load()
                if any(settings.get(key)!=value for key,value in captured['codex_settings'].items()):return False
                meta=self.codex._meta();current=self.codex.active_settings()
                if meta.get('pending_settings') or meta.get('sandbox')!=captured.get('codex_sandbox'):return False
                if list(meta.get('mcp') or [])!=list(self.codex.MCP()):return False
                if any(current.get(key)!=captured['codex_runtime'].get(key) for key in ('thread_id','model','effort','cwd')):return False
                if not self.codex.verify_ready(wait=False)[0]:return False
            if 'claude' in changed:
                if 'claude_remote' in captured:
                    if not self.ns['REMOTE_MODE'].prod_ready():return False
                elif captured.get('claude_absent'):
                    try:self.claude.process()
                    except ProfileError as exc:
                        if str(exc)!='claude_console_missing':return False
                    else:return False
                else:
                    current=self.claude.capture();saved=captured['claude']
                    if any(current.get(key)!=saved.get(key) for key in ('thread_id','model','effort','cwd','bypass')):return False
                    policy_path=self.claude.runtime/'claude-policy.json'
                    if policy_path.exists() and json.loads(policy_path.read_text())!=self.claude_policy(before):return False
            return True
        except Exception:return False

    def interrupt(self,e):
        if e=='codex':self.codex.interrupt()
        else:
            import subprocess
            subprocess.run(['/usr/bin/screen','-S',self.claude.screen(),'-p','0','-X','stuff','\x1b'],capture_output=True,timeout=5)

    def availability(self):
        claude=claude_status(self.ns['pause_state']())
        rotation=self.ns['FLEET_ROTATION'];rows=rotation.snapshot().get('accounts') or [];now=time.time();good=[]
        for row in rows:
            if row.get('loading') or row.get('stale') or row.get('error') or now-float(row.get('ts') or 0)>180:return dict(claude=claude,codex='unknown')
            good.append(not(row.get('login_required') or row.get('lapsed') or row.get('reached') or row.get('usage_allowed') is False or any(float(w.get('pct') or 0)>=100 for w in row.get('windows') or [])))
        return dict(claude=claude,codex=('up' if any(good) else 'down') if good else 'unknown')

def claude_status(lv):
    """down — лимиты всех аккаунтов кончились и Claude стоит на паузе; up — работает; unknown — снимку не верим.
    «Кончились» — ровно то, что ставит паузу (pause_ctl.level_state): hard (сессии) или week (недельный потолок,
    если пауза по неделе включена). Не считаем: ручной выбор аккаунта, отключённую вручную паузу, старый снимок."""
    if not isinstance(lv, dict) or lv.get("ok") is False or lv.get("stale") or "level" not in lv:
        return "unknown"
    if (lv.get("pause") or {}).get("override") or lv.get("manual"):
        return "up"
    return "down" if lv.get("level") in ("hard", "week") else "up"

SIDE_IDLE = 90    # побочная беседа: сколько секунд тишины после ответа держать вкладку проснувшейся
SIDE_MAX = 1800   # жёсткий потолок окна, даже если консоль всё ещё отвечает

class Profiles:
    def __init__(self, base, native, clock=time.time):
        self.base=Path(base);self.native=native;native.manager=self;self.clock=clock;self.lock=threading.RLock();self.transitioning=False;self.error='';self.managed={'claude':False,'codex':False};self.worker=None;self.avail={e:dict(status='unknown',since=clock()) for e in ENGINES};self.tasks=None
        self.side={};self.side_busy={}  # побочная беседа: движок -> dict(since,until); движок -> функция «сейчас отвечает»
        self.path=self.base/'work_profiles.json';self.pending=self.base/'profile-transition.json'
        if self.path.exists():
            raw=json.loads(self.path.read_text());self.state=ProfileState.from_data(raw['core'],clock);self.managed.update(raw.get('managed') or {})
            for engine in ENGINES:
                if raw['core']['selected'][engine] not in ('orchestrator', 'executor', engine+'_solo_full'):
                    self.managed[engine] = False
            native.claude_cwd=raw.get('claude_cwd') or native.claude_cwd
        else:self.state=native.seed();self.save()
        if self.pending.exists():self.error='Обнаружено незавершённое переключение. Восстанавливаю прежний профиль.'
        else:self.save()

    def exchange(self,e):
        return getattr(self.native,'exchange_root',self.base/'profile_exchange')/e

    def save(self):
        atomic(self.path,dict(schema=1,core=self.state.export(),managed=self.managed,claude_cwd=self.native.claude_cwd))

    def paused(self,e):
        return self.state.public()['engines'][e]['role']=='paused'

    def input_allowed(self,e):
        return not self.transitioning and not self.paused(e) and not self.pending.exists()

    # Побочная беседа: человек пишет в вкладку, которую профиль держит на паузе. Окно открывается только по его
    # подтверждению, будит один движок и закрывается само после ответа. Мосты и ротация Codex остаются на input_allowed.
    def side_active(self,e):
        return e in self.side

    def console_allowed(self,e):
        return self.input_allowed(e) or (e in self.side and not self.transitioning and not self.pending.exists())

    def _claude_policy_file(self):
        path=self.native.claude.runtime/'claude-policy.json'
        return path if path.exists() else None

    def side_open(self,e):
        if e not in ENGINES:return False,'Неизвестная консоль.'
        if self.transitioning or self.pending.exists():return False,'Идёт переключение профиля. Повтори чуть позже.'  # не ждём замок смены профиля
        with self.lock:
            if self.transitioning or self.pending.exists():return False,'Идёт переключение профиля. Повтори чуть позже.'
            if not self.paused(e):return True,''
            now=self.clock()
            if e in self.side:
                self.side[e]['until']=now+SIDE_IDLE;return True,''
            try:
                if e=='codex':self.native._codex_pause(False)
                else:
                    path=self._claude_policy_file()
                    if path:atomic(path,dict(self.native.claude_policy(self.state),paused=False,access='read',write_roots=[]))
            except Exception as exc:
                return False,'Не удалось разбудить: '+type(exc).__name__
            self.side[e]=dict(since=now,until=now+SIDE_IDLE)
            return True,''

    def side_close(self,e):
        with self.lock:
            self.side.pop(e,None)
            if not self.paused(e) or self.transitioning or self.pending.exists():return
            try:
                if e=='codex':self.native._codex_pause(True)
                else:
                    path=self._claude_policy_file()
                    if path:atomic(path,self.native.claude_policy(self.state))
            except Exception as exc:
                print('side: не удалось вернуть паузу %s: %r'%(e,exc),flush=True)

    def side_tick(self):
        if not self.side or not self.lock.acquire(blocking=False):return  # идёт смена профиля — она сама сбросит окна
        try:
            for e in list(self.side):
                if not self.paused(e):
                    self.side.pop(e,None);continue
                w=self.side[e];now=self.clock()
                try:busy=bool(self.side_busy.get(e,lambda:False)())
                except Exception:busy=False
                if busy and now-w['since']<SIDE_MAX:w['until']=max(w['until'],now+SIDE_IDLE)
                if now>=w['until'] or now-w['since']>=SIDE_MAX:self.side_close(e)
        finally:self.lock.release()

    def public(self):
        with self.lock:
            out=self.state.public();out.update(snapshot_ts=self.clock(),transitioning=self.transitioning,updating=self.update_active(),last_error=self.error,availability={e:v['status'] for e,v in self.avail.items()})
            if self.tasks:out['task']=self.tasks.public()
            if self.pending.exists():
                recovery=json.loads(self.pending.read_text())
                out['recovery']=dict(blocked=bool(recovery.get('recovery_blocked')),attempts=recovery.get('recovery_attempts',0))
            for e in ENGINES:
                out['engines'][e]['applied'] = self.managed[e]
                out['engines'][e]['emergency_hours'] = 0
                if not self.managed[e] and out['engines'][e]['role']=='solo':
                    out['engines'][e]['label'] = ('Claude' if e == 'claude' else 'Codex')+' Full · текущая сессия'
            return out

    def update_active(self):
        # The installer checks process identity while publishing the new panel.
        # Hold scenario switches until that check ends; never pause console input.
        try:
            marker=json.loads((self.base/'profile-update.json').read_text())
            pid=int(marker['pid'])
            start=Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()[19]
            return start==marker['start']
        except (OSError,ValueError,TypeError,KeyError):return False

    def _changed(self,before,after):
        return [e for e in ENGINES if self.native.plan(before,e)!=self.native.plan(after,e)]

    def transition(self,candidate,message,force=None,recover_blocked=False):
        rotation=getattr(self.native,'ns',{}).get('FLEET_ROTATION')
        with rotation.lock if rotation else nullcontext():
            return self._transition(candidate,message,force,recover_blocked)

    def _transition(self,candidate,message,force=None,recover_blocked=False):
        if self.update_active():return dict(ok=False,busy=True,message='Завершается обновление панели. Примени сценарий после проверки.')
        if self.pending.exists():
            blocked=json.loads(self.pending.read_text()).get('recovery_blocked')
            if recover_blocked and blocked:
                if self.native.busy() or self.tasks and self.tasks.busy():return dict(ok=False,busy=True,message='Дождись завершения текущего ответа.')
                if not self.recover(manual=True):return dict(ok=False,message=self.error,state=self.public())
            else:return dict(ok=False,message='Идёт восстановление предыдущего переключения. Дождись завершения.')
        before=self.state;changed=self._changed(before,candidate)
        if force and force not in changed:changed.append(force)
        if not changed:
            self.state=candidate;self.save();return dict(ok=True,message=message,state=self.public())
        if self.native.busy() or self.tasks and self.tasks.busy():return dict(ok=False,busy=True,message='Сейчас идёт ответ или подтверждённый шаг. Профили можно менять после его завершения.')
        self.transitioning=True;self.side.clear();old_managed=dict(self.managed);captured=None
        try:
            captured=self.native.capture(changed);self.native.preflight(before,candidate,changed,captured)
            atomic(self.pending,dict(before=before.export(),after=candidate.export(),managed=old_managed,changed=changed,captured=captured))
            self.state=candidate
            for e in changed:self.managed[e]=True
            self.native.apply(before,candidate,changed,captured);self.save();self.pending.unlink();self.error=''
            return dict(ok=True,message=message,state=self.public())
        except Exception as exc:
            if self.pending.exists():
                failed=json.loads(self.pending.read_text())
                code=str(exc)
                failed['failure']=dict(type=type(exc).__name__,code=code if re.fullmatch(r'[a-z_]+',code) else None)
                atomic(self.pending,failed)
            reasons={'codex_resume_locked':'Беседа ещё занята предыдущим подключением Codex. Дождись освобождения беседы; автоматические перезапуски остановлены.','full_access_not_active':'Сначала примени Full к выбранной модели.','emergency_not_configured':'Аварийный доступ Codex ещё не настроен.','claude_history_unknown':'Открой нужную беседу Claude в рабочей консоли и повтори выбор.','claude_history_missing':'История выбранной беседы Claude недоступна. Проверь её в консоли.','codex_history_unknown':'Открой нужную беседу Codex через cxw и повтори выбор.','console_busy':'Дождись завершения текущего ответа и повтори выбор.','claude_prod_not_ready':'Claude на PROD не отвечает или не запущен. Проверь вкладку «Claude PROD» и повтори выбор.','claude_prod_role_failed':'Не удалось сообщить роль Claude на PROD. Проверь связь с PROD и повтори выбор.'}
            self.error='Переключение отменено. '+reasons.get(str(exc),'Консоль не подтвердила применение профиля; проверь её экран перед повтором.')
            revoked=bool(before.service and before.service['engine']=='codex' and (before.service['kind']=='emergency' or before.service.get('emergency')) and hasattr(self.native,'emergency') and not self.native.emergency.active() and self.pending.exists())
            if revoked:
                pending=json.loads(self.pending.read_text());pending['recover_to']='after';atomic(self.pending,pending);self.state=candidate;self.save();self.error='Аварийный доступ снят. Восстанавливаю консоль с выбранным профилем.'
                return dict(ok=False,message=self.error,state=self.public())
            self.state=before;self.managed=old_managed
            if captured and self.pending.exists():
                try:self.native.rollback(before,changed,captured);self.save();self.pending.unlink()
                except Exception as rollback_error:
                    failed=json.loads(self.pending.read_text());code=str(rollback_error)
                    failed['rollback_failure']=dict(type=type(rollback_error).__name__,code=code if re.fullmatch(r'[a-z_]+',code) else None);atomic(self.pending,failed)
                    self._block_recovery()
            return dict(ok=False,message=self.error,state=self.public())
        finally:self.transitioning=False

    def apply_scenario(self, body):
        if not self.lock.acquire(blocking=False):return dict(ok=False,message='Переключение уже выполняется. Дождись результата.')
        try:
            candidate=ProfileState.from_data(self.state.export(),self.clock)
            result=candidate.apply_scenario(body.get('choices'),body.get('confirm',''),body.get('revision'))
            if not result.get('ok'):return result
            active=[e for e in ENGINES if candidate.manual_choices[e]]
            force=next((e for e in active if not self.managed[e]),None)
            return self.transition(candidate,'Сценарий применён к консолям.',force,recover_blocked=True)
        finally:self.lock.release()

    def action(self,e,action,body):
        if e not in ENGINES:return dict(ok=False,message='Неизвестный исполнитель.')
        if not self.lock.acquire(blocking=False):return dict(ok=False,message='Переключение уже выполняется. Дождись результата.')
        try:
            candidate=ProfileState.from_data(self.state.export(),self.clock)
            if action=='apply' and not self.managed[e] and body.get('id')==e+'_solo_full' and body.get('confirm')!='подтверждаю':
                return dict(ok=False,confirmation_required=True,word='подтверждаю',message='Подтверди применение Full к текущей сессии.')
            if action=='apply':result=candidate.apply(e,body.get('id'),body.get('confirm',''),body.get('revision'))
            elif action=='stop':result=candidate.stop_service(e,body.get('revision'))
            elif action=='config':result=candidate.configure(e,body.get('enabled'),body.get('emergency',False),body.get('confirm',''),body.get('revision'))
            elif action=='delete':result=candidate.delete(e,body.get('id'),body.get('revision'))
            else:return dict(ok=False,message='Неизвестное действие.')
            if not result.get('ok'):return result
            message='Предыдущий сценарий восстановлен.' if action=='stop' else 'Профиль применён к консоли.'
            original=self.state
            result=self.transition(candidate,message,e if action=='apply' and not self.managed[e] else None,recover_blocked=True)
            if result.get('ok') and action=='delete' and e=='codex':
                try:ok,_=self.native.bridge.delete_profile(body.get('id'))
                except Exception:ok=False
                if not ok:
                    self.state=original;self.save();return dict(ok=False,message='Профиль не удалён. Повтори после обновления данных.',state=self.public())
            return result
        finally:self.lock.release()

    def _block_recovery(self):
        raw=json.loads(self.pending.read_text());raw['recovery_blocked']=True;atomic(self.pending,raw)
        self.error='Восстановление остановлено после ошибки, чтобы не перезапускать консоль по кругу. После освобождения беседы повтори выбор профиля.'

    def recover(self,manual=False):
        if not self.pending.exists():return True
        raw=json.loads(self.pending.read_text());before=ProfileState.from_data(raw['before'],self.clock)
        if raw.get('recovery_blocked') and not manual:
            matches=getattr(self.native,'recovery_matches',lambda *args:False)
            if raw.get('recover_to')!='after' and not self.native.busy() and matches(before,raw['changed'],raw['captured']):
                self.state=before;self.managed.update(raw.get('managed') or {})
                atomic(self.base/'profile_runtime'/('recovered-'+uuid.uuid4().hex+'.json'),raw)
                self.save();self.pending.unlink();self.error='';return True
            self.error='Автоматические повторы восстановления остановлены. После освобождения беседы повтори выбор профиля.'
            return False
        forward=raw.get('recover_to')=='after';self.state=ProfileState.from_data(raw['after'],self.clock) if forward else before
        self.managed.update({e:True for e in raw['changed']} if forward else raw.get('managed') or {})
        if self.native.busy():return False
        # Persist the attempt before touching a process; a crash cannot restart
        # the same failed recovery indefinitely on the next panel boot.
        if raw.get('recovery_attempts',0)>=1 and not manual:
            self._block_recovery();return False
        raw['recovery_attempts']=raw.get('recovery_attempts',0)+1;atomic(self.pending,raw)
        self.transitioning=True;self.side.clear()
        try:
            if forward:self.native.apply(before,self.state,raw['changed'],raw['captured'])
            else:self.native.rollback(before,raw['changed'],raw['captured'])
            self.save();self.pending.unlink();self.error='';return True
        except Exception:
            self._block_recovery();return False
        finally:self.transitioning=False

    def tick(self):
        try:self.side_tick()
        except Exception as exc:print('side: сбой проверки окна: %r'%(exc,),flush=True)
        if not self.lock.acquire(blocking=False):return
        try:
            if self.pending.exists():self.recover();return
            if self.error.startswith(('Автоматические повторы восстановления остановлены.','Восстановление остановлено после ошибки,')):
                self.error=''
            statuses=self.native.availability();now=self.clock()
            for e in ENGINES:
                if self.avail[e]['status']!=statuses[e]:self.avail[e]=dict(status=statuses[e],since=now)
            candidate=ProfileState.from_data(self.state.export(),self.clock)
            # Unknown/stale snapshots cannot change the availability-driven scenario.
            if all(v['status']!='unknown' and now-v['since']>=120 for v in self.avail.values()):
                candidate.availability={e:self.avail[e]['status']=='up' for e in ENGINES}
                candidate.reconcile_availability()
            if candidate.export()!=self.state.export():self.transition(candidate,'Автоматический сценарий обновлён.')
        finally:self.lock.release()

    def start(self):
        if self.worker and self.worker.is_alive():return
        def work():
            while True:
                try:
                    self.tick()
                    if self.tasks:self.tasks.tick()
                except Exception as exc:self.error='Проверка профилей: '+type(exc).__name__
                time.sleep(3)
        self.worker=threading.Thread(target=work,daemon=True,name='mirrored-profiles');self.worker.start()


def bind(ns, inputs):
    from cc_profile_tasks import ProfileTasks, completed_claude_answer
    native=NativeProfiles(ns);profiles=Profiles(ns['BASE'],native)
    bridge,console=native.bridge,native.codex
    original_mcp=console.MCP
    def codex_mcp():
        if not profiles.managed['codex']:return original_mcp()
        try:bridge.ensure_exchange()   # перед каждым запуском Codex: AGENTS.md с текущим текстом из config.json (файл с меткой моста обновится сам)
        except Exception:pass
        return ['-c','sandbox_workspace_write.writable_roots='+json.dumps([str(profiles.exchange('codex')/'outbox')]+native.bridge.extra_writable_roots()),'-c','developer_instructions='+json.dumps(native.prompt(profiles.state,'codex'),ensure_ascii=False)]
    console.MCP=codex_mcp;bridge.MCP_ARGS=codex_mcp
    ns['FLEET_ROTATION'].suspended=lambda:not profiles.input_allowed('codex')
    console.PRESERVE_THREAD=lambda:profiles.managed['codex']
    console.INPUT_ALLOWED=lambda:profiles.console_allowed('codex')  # ввод человека; мосты и ротация ниже остаются на input_allowed
    console.PAUSED=lambda:profiles.paused('codex') and not profiles.side_active('codex')
    profiles.side_busy=dict(codex=console.busy,claude=lambda:ns['session_busy']())
    bridge.DISPATCH_ALLOWED=lambda:profiles.input_allowed('codex')
    bridge.TAKE_DRAFT_ALLOWED=lambda:not profiles.managed['codex']
    bridge.PROFILE_NOTE=lambda:native.prompt(profiles.state,'codex') if profiles.managed['codex'] else bridge.solo_note()
    # Native emergency changes are coordinated synchronously by a profile transaction.
    native.emergency._restart_console=lambda:None
    bridge.PROFILE_APPLIED=console.apply_plan
    def send(engine,text):
        if engine=='codex':bridge.BRIDGE.enqueue_work(('text',text));return
        rm=ns.get('REMOTE_MODE')
        if rm is not None and rm.active():
            ok,_=rm.prod_send(text,wait=900,cancel=profiles.tasks.cancel)
            if not ok:raise ProfileError('claude_input_rejected')
            return
        ok,_=inputs.send('claude',text,'profile-'+uuid.uuid4().hex)
        if not ok:raise ProfileError('claude_input_rejected')
    def ask(engine,text):
        if engine=='codex':return console.ask(text,abort=profiles.tasks.cancel)[0]
        rm=ns.get('REMOTE_MODE')
        if rm is not None and rm.active():
            try:return rm.prod_ask(text,profiles.tasks.cancel)
            except RuntimeError as exc:raise ProfileError(str(exc))
        snapshot=native.claude.capture();history=Path(snapshot['history']);offset=history.stat().st_size;carry=b'';send(engine,text);deadline=time.monotonic()+6*3600;started=False
        while time.monotonic()<deadline:
            if profiles.tasks.cancel.is_set():raise ProfileError('step_cancelled_at_expiry')
            time.sleep(1)
            with history.open('rb') as f:f.seek(offset);raw=f.read();offset=f.tell()
            lines=(carry+raw).split(b'\n');carry=lines.pop()
            for line in lines:
                try:event=json.loads(line)
                except ValueError:continue
                if event.get('type')=='user':started=True
                if event.get('type')=='assistant' and (event.get('message') or {}).get('stop_reason')=='max_tokens':raise ProfileError('claude_incomplete_answer')
                answer=completed_claude_answer(event)
                if answer:return answer
            if not started and time.monotonic()>deadline-6*3600+45:raise ProfileError('claude_start_not_confirmed')
        raise ProfileError('claude_step_timeout')
    profiles.tasks=ProfileTasks(profiles,send,ask)
    ns['FLEET_PROFILES']=profiles
    return profiles
