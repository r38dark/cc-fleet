"""Profile adapter for the existing Claude screen. Never invokes a model itself."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time

UUID = re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$', re.I)

class ProfileError(RuntimeError):
    pass

def atomic(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.tmp')
    fd = os.open(temp, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, ensure_ascii=False);f.flush();os.fsync(f.fileno())
    os.replace(temp, path)

class ClaudeProfile:
    def __init__(self, ns, run=subprocess.run, clock=time.time):
        self.ns, self.run, self.clock = ns, run, clock
        self.base = Path(ns['BASE']);self.runtime = self.base/'profile_runtime'

    def screen(self):
        name = self.ns['cfg']().get('screen_session', 'claude')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', name):raise ProfileError('invalid_claude_screen')
        return name

    def process(self):
        root = self.ns['_current_screen_pid'](self.screen())
        if not root:raise ProfileError('claude_console_missing')
        level = [str(root)];found = []
        for _ in range(5):
            children = []
            for pid in level:
                try:children += Path('/proc/'+pid+'/task/'+pid+'/children').read_text().split()
                except OSError:continue
            for pid in children:
                try:
                    comm = Path('/proc/'+pid+'/comm').read_text().strip()
                    if comm == 'claude':found.append(pid)
                except OSError:pass
            level = children
        if len(found) != 1:raise ProfileError('claude_process_ambiguous')
        return found[0]

    def capture(self):
        pid = self.process();cwd = os.readlink('/proc/'+pid+'/cwd')
        argv = Path('/proc/'+pid+'/cmdline').read_bytes().decode('utf-8', 'replace').rstrip('\0').split('\0')
        tid = None
        directory = Path(self.ns['transcripts_dir']())
        metadata_dir = Path(self.ns.get('CLAUDE_SESSIONS') or Path(self.ns.get('SETTINGS', os.path.expanduser('~/.claude/settings.json'))).parent/'sessions')
        metadata = metadata_dir/(pid+'.json')
        if metadata.is_file():
            session = json.loads(metadata.read_text())
            if session.get('pid') != int(pid) or os.path.realpath(session.get('cwd') or '') != os.path.realpath(cwd):raise ProfileError('claude_session_metadata_mismatch')
            tid = session.get('sessionId') or session.get('session_id')
            if not isinstance(tid,str) or not UUID.fullmatch(tid):raise ProfileError('claude_session_metadata_invalid')
        else:
            for i, value in enumerate(argv[:-1]):
                if value in ('--resume', '-r') and UUID.fullmatch(argv[i+1]):tid = argv[i+1]
        if not tid:raise ProfileError('claude_history_unknown')
        history = directory/(tid+'.jsonl')
        if not history.is_file():raise ProfileError('claude_history_missing')
        history_model = history_effort = None
        with history.open('rb') as stream:
            stream.seek(0,2);stream.seek(max(0,stream.tell()-300000));tail=stream.read().decode('utf-8','replace')
        for line in tail.splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('type')=='assistant':
                history_model=(event.get('message') or {}).get('model') or history_model
                if event.get('effort') in ('low','medium','high','xhigh','max'):history_effort=event['effort']
        text=self.ns['screen_hardcopy']()
        status_name=self.ns.get('status_model_name',lambda value:True)(text)
        model=self.ns['session_model']() if status_name else history_model or self.ns['session_model']()
        effort=None
        for line in text.splitlines():
            if status_name and (self.ns.get('_STATUS_MODEL_RE') is None or self.ns['_STATUS_MODEL_RE'].match(line)):
                match=re.search(r'[^\w\s]\s*(low|medium|high|xhigh|max)\b',line)
                if match:effort=match.group(1)
        effort=effort or history_effort or self.ns['session_effort'](model)
        if not model or re.search(r'\s',model):raise ProfileError('claude_model_unknown')
        if effort is not None and effort not in ('low','medium','high','xhigh','max'):raise ProfileError('claude_effort_unknown')
        telegram_channel = any(argv[i] == '--channels' and i+1 < len(argv) and argv[i+1] == 'plugin:telegram@claude-plugins-official' for i in range(len(argv)))
        try:
            sandbox_root = b'IS_SANDBOX=1' in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0')
        except OSError:
            sandbox_root = False
        return dict(pid=pid, thread_id=tid, history=str(history), cwd=cwd, model=model, effort=effort,
                    telegram_channel=telegram_channel, sandbox_root=sandbox_root,
                    bypass='--dangerously-skip-permissions' in argv or any(argv[i]=='--permission-mode' and i+1<len(argv) and argv[i+1]=='bypassPermissions' for i in range(len(argv))))

    def command(self, snapshot, policy, prompt):
        if not snapshot.get('model') or re.search(r'\s',snapshot['model']):raise ProfileError('claude_model_unknown')
        if snapshot.get('effort') is not None and snapshot['effort'] not in ('low','medium','high','xhigh','max'):raise ProfileError('claude_effort_unknown')
        parts = shlex.split(self.ns['cfg']().get('claude_cmd') or 'claude')
        if not parts or any(p in (';', '&&', '||', '|', '&') for p in parts):raise ProfileError('unsupported_claude_command')
        flags_with_value = {'--permission-mode', '--model', '--effort', '--resume', '-r', '--append-system-prompt', '--append-system-prompt-file', '--system-prompt-snapshot', '--settings'}
        if policy.get('agents'):flags_with_value.add('--agents')
        flags = {'--dangerously-skip-permissions', '--allow-dangerously-skip-permissions', '--continue', '-c', '--fork-session'}
        cleaned = [];i = 0
        while i<len(parts):
            value=parts[i]
            if value in flags_with_value:
                i+=1
                if i<len(parts) and not parts[i].startswith('-'):i+=1
                continue
            if value in flags:i+=1;continue
            cleaned.append(value);i+=1
        if not cleaned:raise ProfileError('claude_binary_missing')
        environment = ['env', 'CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1']
        if snapshot.get('sandbox_root') and 'IS_SANDBOX=1' not in cleaned:environment.append('IS_SANDBOX=1')
        # «Opus → Sonnet»: все субагенты сессии идут на Sonnet (профиль задаёт id из пула моделей)
        if policy.get('subagent_model'):environment.append('CLAUDE_CODE_SUBAGENT_MODEL='+policy['subagent_model'])
        argv = environment+cleaned
        if snapshot.get('telegram_channel') and '--channels' not in cleaned:
            argv += ['--channels', 'plugin:telegram@claude-plugins-official']
        argv += ['--resume', snapshot['thread_id'], '--model', snapshot['model'], '--permission-mode', 'bypassPermissions' if policy['access']=='full' else 'dontAsk']
        if snapshot.get('effort'):argv += ['--effort', snapshot['effort']]
        argv += ['--settings', str(self.runtime/'claude-settings.json'), '--system-prompt-snapshot', 'off', '--append-system-prompt', prompt]
        if policy.get('agents'):argv += ['--agents', json.dumps(policy['agents'], ensure_ascii=False)]
        return argv

    def prepare(self, snapshot, policy, prompt):
        if not Path(snapshot['history']).is_file():raise ProfileError('claude_history_missing')
        if not Path(policy['cwd']).is_dir():Path(policy['cwd']).mkdir(parents=True, exist_ok=True)
        argv=self.command(snapshot, policy, prompt);i=1
        while i<len(argv) and (re.match(r'^[A-Za-z_][A-Za-z0-9_]*=',argv[i]) or argv[i] in ('env','/usr/bin/env')):i+=1
        if i>=len(argv):raise ProfileError('claude_binary_missing')
        program=argv[i]
        if program=='claude' and self.ns.get('CLAUDE_BIN'):program=self.ns['CLAUDE_BIN']
        resolved=program if os.path.isabs(program) and Path(program).is_file() else shutil.which(program)
        if not resolved:raise ProfileError('claude_binary_missing')
        argv[i]=resolved
        return argv

    def apply(self, snapshot, policy, prompt):
        argv = self.prepare(snapshot, policy, prompt)
        hook = shlex.join(['/usr/bin/python3', str(self.base/'cc_profile_gate.py'), '--base', str(self.base)])
        atomic(self.runtime/'claude-settings.json', {'hooks': {'PreToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': hook}]}], 'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': hook}]}]}})
        atomic(self.runtime/'claude-policy.json', policy)
        rc = self.runtime/'claude.screenrc';rc.write_text('startup_message off\ndefutf8 on\ndefscrollback 3000\nlogfile flush 1\ntermcapinfo * "Km=\\E[M"\n')
        name = self.screen();start_log=self.runtime/'claude-start.log';start_log.write_text('');start_log.chmod(0o600)
        done = self.run(['/usr/bin/screen', '-S', name, '-X', 'quit'], capture_output=True, timeout=10)
        if done.returncode:raise ProfileError('claude_stop_failed')
        self.run(['/usr/bin/systemctl','stop','cc-claude-profile-console.service'],capture_output=True,timeout=15)
        argv_screen=['/usr/bin/screen', '-U', '-c', str(rc), '-L', '-Logfile', str(start_log), '-D', '-mS', name, '/usr/bin/bash', '-lc', 'cd '+shlex.quote(policy['cwd'])+' && exec '+shlex.join(argv)]
        done=self.run(['/usr/bin/systemd-run','--unit=cc-claude-profile-console','--collect','--property=KillMode=control-group','--description=Native Claude console managed by cc-fleet profiles','--',*argv_screen],capture_output=True,timeout=15)
        if done.returncode:raise ProfileError('claude_start_failed')
        self.ns['_tdir_cache'].update(ts=0, dir=None)
        deadline = self.clock()+30
        while self.clock()<deadline:
            time.sleep(.5)
            try:
                pid = self.process();text = self.ns['screen_hardcopy']()
                text += start_log.read_bytes()[-65536:].decode('utf-8','replace')
                if any(x in text for x in ('This session is already', 'No conversation found', 'Invalid API key', 'unknown option')):raise ProfileError('claude_resume_rejected')
                if '❯' in text or '> ' in text or 'bypass permissions' in text.lower():
                    return dict(pid=pid, thread_id=snapshot['thread_id'], model=snapshot['model'], effort=snapshot.get('effort'), cwd=policy['cwd'])
            except ProfileError as exc:
                if str(exc)=='claude_resume_rejected':raise
        raise ProfileError('claude_ready_timeout')
