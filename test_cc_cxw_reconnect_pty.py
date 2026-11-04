"""Actual Screen/client PTY, isolated sockets and metadata; no model/API calls."""
import argparse, json, os, pty, pwd, select, shutil, signal, subprocess, tempfile, time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT
SCREEN='/opt/cc-limits/terminal/screen-5.0.2/screen'
USER=None

class Harness:
    def __init__(self):
        self.root=Path(tempfile.mkdtemp(prefix='ccatt-'))
        self.base=self.root/'base';self.base.mkdir()
        self.home=self.root/'home';self.home.mkdir()
        self.console=self.home/'codex_console';self.console.mkdir()
        self.sockets=self.console/'screen5';self.sockets.mkdir(mode=0o700)
        self.bin=self.root/'bin';self.bin.mkdir()
        # Replace only installation-specific helper/getent lookup, not attach logic.
        code=(SOURCE/'cc-cmd').read_text().replace('/usr/local/sbin/cc-codex-console-localize','/usr/bin/true')
        (self.base/'cc-cmd').write_text(code);(self.base/'cc-cmd').chmod(0o755)
        (self.bin/'cxw').symlink_to(self.base/'cc-cmd')
        shutil.copy2(SOURCE/'cc_codex_terminal.py',self.base/'cc_codex_terminal.py')
        binary=self.base/'terminal/screen-5.0.2/screen';binary.parent.mkdir(parents=True);binary.symlink_to(SCREEN)
        user=pwd.getpwnam(USER) if USER else pwd.getpwuid(os.getuid())
        self.runner=['/usr/sbin/runuser','-u',user.pw_name,'--'] if os.getuid()==0 and user.pw_uid!=0 else []
        (self.base/'config.json').write_text(json.dumps({'codex_user':user.pw_name}))
        (self.bin/'getent').write_text('#!/bin/sh\nprintf "%s\\n" '+repr(f'{user.pw_name}:x:{user.pw_uid}:{user.pw_gid}::{self.home}:/bin/bash')+'\n')
        (self.bin/'getent').chmod(0o755)
        self.env=dict(os.environ,PATH=str(self.bin)+':/usr/bin:/bin',TERM='xterm-256color',LANG='C.UTF-8')
        self.env.pop('STY',None);self.env.pop('SCREENDIR',None)
        self.screen_env=dict(self.env,SCREENDIR=str(self.sockets))
        self.rc=self.root/'screenrc';self.rc.write_text('term screen-256color\ntruecolor on\ntermcapinfo * "Km=\\E[M"\n')
        self.emitter=self.root/'emitter.py'
        self.emitter.write_text('''import os,sys,tty
tty.setraw(0)
os.write(1,b'\\x1b[?2004h\\x1b[?1002h\\x1b[?1006h\\x1b[38;2;137;180;250mREADY-'+sys.argv[1].encode()+b'\\x1b[0m\\r\\n')
with open(sys.argv[2],'ab',buffering=0) as stream:
 while True:
  data=os.read(0,4096)
  if not data:break
  stream.write(data)
''')
        self.pid=None;self.fd=None;self.meta={};self.generation=0;self.output=b'';self.client_ids=[]
        if self.runner:
            for path in [self.root,*self.root.rglob('*')]:
                if not path.is_symlink():os.chown(path,user.pw_uid,user.pw_gid)

    def ctl(self,*args):
        return subprocess.run(self.runner+[SCREEN,*args],env=self.screen_env,capture_output=True,timeout=10)

    def write_meta(self):
        target=self.console/'console.json';tmp=target.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.meta));os.replace(tmp,target)

    def start_screen(self):
        self.generation+=1
        result=self.ctl('-c',str(self.rc),'-dmS','cc-codex','python3',str(self.emitter),str(self.generation),str(self.root/f'input{self.generation}'))
        assert result.returncode==0
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            socks=list(self.sockets.glob('*.cc-codex'))
            if socks:break
            time.sleep(.03)
        assert len(socks)==1
        self.meta=dict(pid=socks[0].name.split('.')[0],screen_bin=str(self.base/'terminal/screen-5.0.2/screen'),screen_dir=str(self.sockets),settings={})
        self.write_meta()

    def start_client(self):
        self.output=b''
        self.pid,self.fd=pty.fork()
        if self.pid==0:
            os.execve(str(self.bin/'cxw'),[str(self.bin/'cxw')],self.env)
        self.client_ids.append(self.pid)
        self.wait_output(f'READY-{self.generation}'.encode())

    def read(self,seconds=.1):
        if select.select([self.fd],[],[],seconds)[0]:
            try:self.output+=os.read(self.fd,65536)
            except OSError:pass

    def wait_output(self,needle,seconds=6):
        deadline=time.monotonic()+seconds
        while needle not in self.output and time.monotonic()<deadline:
            self.read()
        assert needle in self.output, ('missing_output',needle,repr(self.output[-500:]))

    def input_exact(self):
        data='Кириллица '.encode()+b'\x1b[200~paste\x1b[201~\x1b[<0;10;5M\x1b[<0;10;5m'
        os.write(self.fd,data)
        target=self.root/f'input{self.generation}'
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if target.exists() and target.read_bytes()==data:return
            self.read(.03)
        raise AssertionError(('input_corrupted',target.read_bytes() if target.exists() else None))

    def wait_exit(self,seconds=4):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            pid,status=os.waitpid(self.pid,os.WNOHANG)
            if pid:
                self.pid=None;os.close(self.fd);self.fd=None
                return os.waitstatus_to_exitcode(status)
            self.read(.05)
        raise AssertionError('client_did_not_exit')

    def cleanup(self):
        if self.pid:
            os.kill(self.pid,signal.SIGTERM)
            try:self.wait_exit()
            except Exception:os.kill(self.pid,signal.SIGKILL)
        self.ctl('-S','cc-codex','-X','quit')

def run():
    h=Harness();checks={}
    try:
        h.start_screen();h.start_client();original=h.pid
        h.input_exact();checks['initial_unicode_paste_mouse']=True
        checks['rgb']=b'38;2;137;180;250' in h.output
        # Intent is written before old server exits; replacement follows after a gap.
        h.meta['pending_settings']={'new_session':True};h.write_meta()
        h.ctl('-S','cc-codex','-X','quit');time.sleep(.6);h.start_screen()
        h.wait_output(b'READY-2');assert h.pid==original
        h.input_exact();checks['new_session_gap_reconnect_same_client']=True
        # New Screen and first input metadata can already be present when -rd returns.
        h.meta['pending_settings']={'new_session':True};h.write_meta()
        h.ctl('-S','cc-codex','-X','quit');h.start_screen()
        h.wait_output(b'READY-3');assert h.pid==original
        h.input_exact();checks['fast_replacement_reconnect_same_client']=True
        os.write(h.fd,b'\x01d');assert h.wait_exit()==0
        assert h.ctl('-ls').returncode==0;checks['manual_detach_exits_and_leaves_screen']=True
        h.start_client();started=time.monotonic()
        h.ctl('-S','cc-codex','-X','quit');h.wait_exit()
        assert time.monotonic()-started<3;checks['explicit_stop_exits_without_wait']=True
        h.start_screen();h.start_client()
        h.meta['pending_settings']={'new_session':True};h.write_meta()
        h.ctl('-S','cc-codex','-X','quit');started=time.monotonic()
        assert h.wait_exit(18)==1
        assert 13<time.monotonic()-started<18;checks['failed_restart_bounded_and_reported']=True
        h.start_screen();h.start_client()
        os.killpg(h.pid,signal.SIGTERM);assert h.wait_exit()==143
        checks['signal_exits_without_reattach']=True
        checks['screen_survives_client_signal']=h.ctl('-ls').returncode==0
        checks['ok']=all(checks.values())
        return checks
    finally:h.cleanup()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,default=ROOT)
    parser.add_argument('--screen',default=SCREEN)
    parser.add_argument('--user',help='Target account for root-to-user runuser verification')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();SOURCE=args.base;SCREEN=args.screen;USER=args.user
    report=run()
    if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
