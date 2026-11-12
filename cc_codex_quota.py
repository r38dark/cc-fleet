"""Own-quota pause of the existing native Codex process; profiles and sessions stay intact."""
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
import time


def atomic(path, value):
    path=Path(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.'+path.name+'.')
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.chmod(name,0o600);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def read(path, default=None):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return default


def identity(pid):
    try:
        fields=Path('/proc/'+str(int(pid))+'/stat').read_text().rsplit(')',1)[1].split()
        return dict(pid=int(pid),start=fields[19],state=fields[0])
    except (OSError,ValueError,TypeError,IndexError):return None


def same(row):
    current=identity(row.get('pid'))
    return bool(current and current['start']==str(row.get('start')))


def processes(root):
    level=[str(root)];result=[]
    for _ in range(8):
        next_level=[]
        for pid in level:
            try:
                if Path('/proc/'+pid+'/comm').read_text().strip()=='codex':
                    row=identity(pid)
                    if row:result.append(dict(pid=row['pid'],start=row['start']))
                next_level+=Path('/proc/'+pid+'/task/'+pid+'/children').read_text().split()
            except OSError:continue
        level=next_level
    return result


class Guard:
    def __init__(self, base, rotation, console, bridge):
        self.base=Path(base);self.rotation=rotation;self.console=console;self.bridge=bridge
        self.path=self.base/'codex_quota_runtime.json'
        self.marker=self.base/'profile_runtime/codex-quota-paused.json'
        self.grace=self.base/'profile_runtime/codex-quota-grace.json'
        self.state=read(self.path,{}) or {};self.lock=threading.RLock();self.finishing=False
        if self.state.get('notified'):self.bridge.limit_held=(self.state.get('last_pause') or {}).get('resume_at') or True

    def fallback(self, value, override=False):
        previous=self.state.get('last_pause') or {}
        if previous.get('resume_at') and time.time()>previous['resume_at']+120:
            return dict(active=False,expired=True)
        if previous.get('active') and (not override or previous.get('hard')):
            return dict(previous,unknown=True)
        return value

    def _save(self):atomic(self.path,self.state)

    def _grace(self):
        value=read(self.grace,{}) or {}
        point=self.console.mark() if value else None
        if (point and point.get('turn') and point.get('turn')==value.get('turn')
                and str(self.console._pid())==str(value.get('screen_pid'))):return True
        self.grace.unlink(missing_ok=True);return False

    def tick(self):
        with self.lock:
            pause=self.rotation.limit_pause();rows=[r for r in read(self.marker,[]) or [] if same(r)]
            was=bool(self.state.get('notified'))
            self.finishing=False
            if pause.get('active'):
                self.state['last_pause']={k:v for k,v in pause.items() if k not in ('label','resume_label','accounts')}
                if self._grace():
                    self.finishing=True;self._save();return
                if not rows:rows=processes(self.console._pid()) if self.console._pid() else []
                if rows:
                    atomic(self.marker,rows)
                    for row in rows:
                        try:
                            if same(row):os.kill(row['pid'],signal.SIGSTOP)
                        except ProcessLookupError:pass
                self.state['notified']=True;self._save()
                if not was and not getattr(self.bridge,'limit_held',None):
                    self.bridge._notice_async('⏸ Codex: достигнут порог лимита. Работа приостановлена, беседа и Full сохранены. Новые задания копятся до сброса или ручного отключения паузы.')
                self.bridge.limit_held=pause.get('resume_at') or True
                return
            if pause.get('unknown'):return
            # Another owner can still hold the same process (the profile pause).
            profile_rows=read(self.base/'profile_runtime/codex-paused.json',[]) or []
            for row in rows:
                owned_elsewhere=any(r.get('pid')==row.get('pid') and str(r.get('start'))==str(row.get('start')) for r in profile_rows)
                try:
                    if same(row) and not owned_elsewhere and not self.console.PAUSED():os.kill(row['pid'],signal.SIGCONT)
                except ProcessLookupError:pass
            self.marker.unlink(missing_ok=True);self.grace.unlink(missing_ok=True)
            if self.state:
                self.state={};self._save()
            self.bridge.limit_held=None
            if was:self.bridge._notice_async('▶ Codex: пауза по лимитам снята. Работа и очередь продолжаются в той же беседе.')

    def public(self):
        rows=read(self.marker,[]) or []
        return dict(frozen=any(same(r) and (identity(r['pid']) or {}).get('state')=='T' for r in rows),
                    finishing_current=self.finishing,queued=len(self.bridge.inputs))
