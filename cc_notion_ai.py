"""Профиль «Notion AI · только он» и уведомления о смене профилей в Telegram ([notion-ai], 05.11.26).

Профиль включён:
  * Claude Code остановлен (screen darqai). Его бота — общий чат Telegram — слушает мост
    notion-ai-tg.service и пересылает сообщения Дениса в постоянный чат Notion AI.
  * Ввод в консоли Claude и Codex закрыт: Codex держит входящие в своей очереди до выключения.
  * Автоматические сценарии балансера не применяются.
Выключение (кнопкой или выбором любого другого профиля) останавливает мост и возвращает
Claude, если он работал до включения.
Любая смена профиля пишет в Telegram: Claude и Notion AI — в общий чат (бот Claude),
Codex — в чат Codex.
Состояние: BASE/notion_ai_mode.json (его же читают мост и /root/start_claude.sh)."""
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from cc_claude_profile import atomic

BRIDGE_UNIT = 'notion-ai-tg.service'
CHAT_URL = 'https://app.notion.com/chat?t=40c55b37d45880e9b91600a9c9425683'
START_CLAUDE = '/root/start_claude.sh'
TG_PLUGIN_MARK = 'claude-plugins-official/telegram'
TITLE = 'Notion AI · только он'
NAMES = {'claude': 'Claude', 'codex': 'Codex'}
AUTO_MESSAGE = 'Автоматический сценарий обновлён.'


def _run(args, timeout=30):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except Exception as exc:
        return -1, type(exc).__name__


class NotionAI:
    def __init__(self, ns, profiles):
        self.ns, self.profiles = ns, profiles
        self.path = Path(ns['BASE']) / 'notion_ai_mode.json'
        self.lock = threading.RLock()
        self.data = self._load()
        self.error = ''

    # ── состояние ──────────────────────────────────────────────────────────
    def _load(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return dict(active=False)

    def active(self):
        return bool(self.data.get('active'))

    def _save(self, data):
        atomic(self.path, data)
        self.data = data

    def screen(self):
        try:
            return self.ns['cfg']().get('screen_session') or 'darqai'
        except Exception:
            return 'darqai'

    def claude_running(self):
        code, out = _run(['screen', '-ls'], 10)
        if ('.' + self.screen() + '\t') in out or ('.' + self.screen() + ' ') in out:
            return True
        return _run(['pgrep', '-f', TG_PLUGIN_MARK], 10)[0] == 0

    def bridge_state(self):
        return _run(['systemctl', 'is-active', BRIDGE_UNIT], 10)[1].strip() or 'unknown'

    def public(self):
        d = self.data
        return dict(ok=True, active=self.active(), title=TITLE, since=d.get('since', 0),
                    claude_was_running=bool(d.get('claude_was_running')), bridge=self.bridge_state(),
                    chat_url=CHAT_URL, last_error=self.error)

    # ── Telegram ───────────────────────────────────────────────────────────
    def _later(self, fn, *args):
        threading.Thread(target=self._safe, args=(fn,) + args, daemon=True).start()

    @staticmethod
    def _safe(fn, *args):
        try:
            fn(*args)
        except Exception as exc:
            print('notion-ai notify fail: %s' % type(exc).__name__, flush=True)

    def tell_claude_chat(self, text):
        self._later(self.ns['tg_notify'], text)

    def tell_codex_chat(self, text):
        bridge = getattr(self.ns.get('cc_codex_bridge'), 'BRIDGE', None)
        if bridge is not None:
            self._later(bridge.send, text)

    def labels(self, out=None):
        out = out or self.original_public()
        return {e: (out.get('engines', {}).get(e) or {}).get('label', '') for e in NAMES}

    # ── Claude Code ────────────────────────────────────────────────────────
    def stop_claude(self):
        _run(['screen', '-S', self.screen(), '-X', 'quit'], 15)
        for _ in range(20):
            if not self.claude_running():
                return True
            time.sleep(0.5)
        _run(['pkill', '-f', TG_PLUGIN_MARK], 10)
        time.sleep(1)
        return not self.claude_running()

    def start_claude(self):
        # своя scope-единица: screen не должен жить в cgroup cc-limits.service
        code, out = _run(['systemd-run', '--scope', '--quiet', '--unit',
                          'claude-darqai-%d' % int(time.time()), START_CLAUDE], 90)
        return code == 0

    # ── включение / выключение ─────────────────────────────────────────────
    def on(self, by='панель', force=False):
        with self.lock:
            if self.active():
                return dict(ok=True, message='Профиль «%s» уже включён.' % TITLE, state=self.public())
            p = self.profiles
            if p.transitioning or p.pending.exists() or p.update_active():
                return dict(ok=False, busy=True, message='Сейчас меняется профиль. Повтори через минуту.', state=self.public())
            if not force:
                try:
                    if p.native.busy():
                        return dict(ok=False, busy=True, message='Сейчас отвечает Claude или Codex. Дождись конца ответа.', state=self.public())
                except Exception:
                    pass
            before = self.labels()
            was_running = self.claude_running()
            self._save(dict(active=True, since=time.time(), by=by, claude_was_running=was_running, before=before))
            if was_running and not self.stop_claude():
                self.error = 'Claude Code не остановился — включение отменено.'
                self._save(dict(active=False, since=time.time()))
                return dict(ok=False, message=self.error, state=self.public())
            code, out = _run(['systemctl', 'restart', BRIDGE_UNIT], 30)
            if code != 0:
                self.error = 'Мост Telegram не запустился: ' + out.strip()[-200:]
                self._save(dict(active=False, since=time.time()))
                if was_running:
                    self.start_claude()
                return dict(ok=False, message=self.error, state=self.public())
            self.error = ''
            self.tell_claude_chat('🤖 Включён профиль «%s».\n%s, Codex на паузе. Пишите сюда — отвечает Notion AI.'
                                  % (TITLE, 'Claude остановлен' if was_running else 'Claude не запущен'))
            self.tell_codex_chat('⏸ Codex на паузе: включён профиль «%s». Сообщения сюда подождут '
                                 'до выключения профиля. Notion AI отвечает в общем чате.' % TITLE)
            return dict(ok=True, message='Профиль «%s» включён. Пиши в общий чат Telegram.' % TITLE, state=self.public())

    def off(self, reason='выключен на панели', notify=True):
        with self.lock:
            if not self.active():
                return dict(ok=True, message='Профиль Notion AI уже выключен.', state=self.public())
            _run(['systemctl', 'stop', BRIDGE_UNIT], 40)
            prev = self.data
            self._save(dict(active=False, since=time.time(), last=dict(since=prev.get('since'), reason=reason)))
            started = False
            if prev.get('claude_was_running'):
                started = self.start_claude()
            self.error = '' if started or not prev.get('claude_was_running') else 'Claude Code не запустился — запусти /root/start_claude.sh.'
            if notify:
                now = self.labels()
                claude = ('Claude запущен заново' if started else 'Claude не запустился — нужен ручной запуск') if prev.get('claude_was_running') else 'Claude не запущен (как и до включения)'
                self.tell_claude_chat('↩️ Профиль «Notion AI» выключен (%s). %s. Профиль Claude: %s' % (reason, claude, now['claude']))
                self.tell_codex_chat('▶️ Codex снова принимает сообщения. Профиль Codex: %s' % now['codex'])
            return dict(ok=True, message='Профиль Notion AI выключен.' + (' ' + self.error if self.error else ''), state=self.public())

    # ── обёртки профилей балансера ─────────────────────────────────────────
    def wrap(self):
        p = self.profiles
        self.original_public = p.public
        orig_paused, orig_transition = p.paused, p.transition
        orig_action, orig_scenario = p.action, p.apply_scenario

        def paused(e):
            return self.active() or orig_paused(e)

        def public():
            out = self.original_public()
            out['notion_ai'] = self.public()
            if self.active():
                for e, name in NAMES.items():
                    if e in out.get('engines', {}):
                        out['engines'][e]['label'] = name + ' · на паузе (работает Notion AI)'
            return out

        def transition(candidate, message, force=None, recover_blocked=False):
            if self.active() and message == AUTO_MESSAGE:
                return dict(ok=False, busy=True, message='Работает Notion AI — автоматические сценарии отложены.')
            before = self.labels()
            result = orig_transition(candidate, message, force, recover_blocked)
            if result.get('ok'):
                try:
                    after = self.labels()
                    tail = ' (автоматически)' if message == AUTO_MESSAGE else ''
                    if after['claude'] != before['claude']:
                        self.tell_claude_chat('🔀 Профиль Claude: %s%s' % (after['claude'], tail))
                    if after['codex'] != before['codex']:
                        self.tell_codex_chat('🔀 Профиль Codex: %s%s' % (after['codex'], tail))
                except Exception:
                    pass
            return result

        def action(e, act, body):
            if self.active() and act in ('apply', 'stop'):
                self.off('выбран другой профиль')
            return orig_action(e, act, body)

        def apply_scenario(body):
            if self.active():
                self.off('выбран другой профиль')
            return orig_scenario(body)

        p.paused, p.public, p.transition = paused, public, transition
        p.action, p.apply_scenario = action, apply_scenario


UI = r'''
<style id="naiStyle">
.nai-btn{display:inline-flex;align-items:center;gap:7px;height:34px;padding:0 12px;border-radius:10px;border:1px solid rgba(139,147,167,.35);background:transparent;color:var(--mut,#8b93a7);font:600 12px/1 system-ui,-apple-system,sans-serif;cursor:pointer;white-space:nowrap}
.nai-btn:hover{color:var(--txt,#e8eaf0);border-color:rgba(232,234,240,.55)}
.nai-btn .nai-dot{width:7px;height:7px;border-radius:50%;background:currentColor;opacity:.55}
.nai-btn.on{color:#120b24;background:#a78bfa;border-color:#a78bfa}
.nai-btn.on .nai-dot{background:#120b24;opacity:1;animation:naiPulse 1.6s infinite}
.nai-btn[disabled]{opacity:.6;cursor:progress}
@keyframes naiPulse{50%{opacity:.25}}
.nai-pop{position:fixed;z-index:99999;width:min(320px,calc(100vw - 24px));background:var(--card,#181c24);color:var(--txt,#e8eaf0);border:1px solid rgba(139,147,167,.35);border-radius:12px;padding:14px;box-shadow:0 12px 32px rgba(0,0,0,.5);font:14px/1.4 system-ui,-apple-system,sans-serif}
.nai-pop b{display:block;margin-bottom:6px}
.nai-pop p{margin:0 0 12px;color:var(--mut,#8b93a7);font-size:13px}
.nai-pop .nai-row{display:flex;gap:8px;justify-content:flex-end}
.nai-pop button{height:32px;padding:0 14px;border-radius:8px;border:1px solid rgba(139,147,167,.35);background:transparent;color:inherit;cursor:pointer;font:600 13px system-ui,-apple-system,sans-serif}
.nai-pop button.nai-yes{background:#a78bfa;border-color:#a78bfa;color:#120b24}
.nai-banner{margin:10px 0 14px;padding:10px 14px;border-radius:12px;border:1px solid rgba(167,139,250,.55);background:rgba(167,139,250,.12);color:var(--txt,#e8eaf0);font:13px/1.45 system-ui,-apple-system,sans-serif;display:flex;gap:12px;align-items:center;justify-content:space-between}
.nai-banner button{flex:none;height:30px;padding:0 12px;border-radius:8px;border:1px solid rgba(167,139,250,.7);background:transparent;color:inherit;font:600 12px system-ui,-apple-system,sans-serif;cursor:pointer}
.nai-banner[hidden],.nai-toast[hidden],.nai-pop[hidden]{display:none!important}
.nai-toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:99999;max-width:calc(100vw - 24px);background:var(--card,#181c24);color:var(--txt,#e8eaf0);border:1px solid rgba(139,147,167,.35);border-radius:10px;padding:10px 14px;font:13px/1.4 system-ui,-apple-system,sans-serif;box-shadow:0 10px 28px rgba(0,0,0,.45)}
</style>
<script id="naiScript">
(function(){try{
var api=(typeof API!=='undefined'?API:location.origin+'/cc-hook/')+'notion-ai',tok=(typeof TOKEN!=='undefined'?TOKEN:''),st=null,busy=false,pop=null,toastT=0;
var btn=document.createElement('button');btn.type='button';btn.id='naiBtn';btn.className='nai-btn';btn.title='Профиль «Notion AI · только он»';
btn.innerHTML='<span class="nai-dot"></span><span class="nai-txt">Notion AI</span>';
var banner=document.createElement('div');banner.className='nai-banner';banner.hidden=true;
banner.innerHTML='<span>🤖 <b>Работает Notion AI.</b> Claude и Codex на паузе. Пиши в общий чат Telegram.</span><button type="button">Выключить</button>';
function place(){var rf=document.getElementById('rfBtn');if(rf&&rf.parentNode){rf.parentNode.insertBefore(btn,rf)}else{btn.style.cssText='position:fixed;left:12px;bottom:12px;z-index:9999';document.body.appendChild(btn)}
 var h=document.querySelector('.hdr');if(h&&h.parentNode){h.parentNode.insertBefore(banner,h.nextSibling)}else{document.body.insertBefore(banner,document.body.firstChild)}}
function toast(t){var el=document.querySelector('.nai-toast');if(!el){el=document.createElement('div');el.className='nai-toast';document.body.appendChild(el)}el.textContent=t;el.hidden=false;clearTimeout(toastT);toastT=setTimeout(function(){el.hidden=true},5000)}
function paint(){var on=!!(st&&st.active);btn.classList.toggle('on',on);btn.querySelector('.nai-txt').textContent=on?'Notion AI · работает':'Notion AI';banner.hidden=!on;btn.disabled=busy}
function closePop(){if(pop){pop.remove();pop=null}}
function ask(){closePop();var on=!!(st&&st.active);pop=document.createElement('div');pop.className='nai-pop';pop.setAttribute('role','dialog');
 pop.innerHTML=on?'<b>Выключить Notion AI?</b><p>Мост Telegram остановится. Claude вернётся, если работал до включения. Codex снова примет сообщения.</p>':'<b>Включить «Notion AI · только он»?</b><p>Claude остановится, Codex встанет на паузу. Пиши в общий чат Telegram — ответит Notion AI текстом и голосом.</p>';
 pop.innerHTML+='<div class="nai-row"><button type="button" class="nai-no">Нет</button><button type="button" class="nai-yes">Да</button></div>';
 document.body.appendChild(pop);var r=btn.getBoundingClientRect(),w=pop.offsetWidth;pop.style.top=Math.min(r.bottom+8,innerHeight-pop.offsetHeight-12)+'px';pop.style.left=Math.max(12,Math.min(r.right-w,innerWidth-w-12))+'px';
 pop.querySelector('.nai-no').onclick=closePop;pop.querySelector('.nai-yes').onclick=function(){closePop();send(!on)}}
function load(){fetch(api,{headers:{'X-CC-Token':tok},cache:'no-store'}).then(function(r){return r.ok?r.json():null}).then(function(j){if(j&&!busy){st=j;paint()}}).catch(function(){})}
function send(on){busy=true;paint();toast(on?'Включаю профиль Notion AI…':'Выключаю профиль Notion AI…');
 fetch(api+'/'+(on?'on':'off'),{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':tok},body:'{}'}).then(function(r){return r.json()}).then(function(j){if(j.state)st=j.state;toast(j.message||(j.ok?'Готово':'Не получилось'))}).catch(function(){toast('Панель не ответила. Обнови страницу.')}).then(function(){busy=false;paint()})}
btn.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();if(!busy)ask()});
banner.querySelector('button').addEventListener('click',function(){if(!busy){st=st||{};st.active=true;ask()}});
document.addEventListener('click',function(e){if(pop&&!pop.contains(e.target)&&e.target!==btn)closePop()});
document.addEventListener('keydown',function(e){if(e.key==='Escape')closePop()});
function boot(){place();paint();load();setInterval(load,10000)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
}catch(e){console.warn('notion-ai',e)}})();
</script>
'''


def inject(page):
    if 'id="naiScript"' in page:
        return page
    i = page.rfind('</body>')
    return page[:i] + UI + page[i:] if i >= 0 else page + UI


def install(ns, profiles):
    nai = NotionAI(ns, profiles)
    nai.wrap()
    base = ns['H']

    class NotionAIHandler(base):
        def do_GET(self):
            if urlparse(self.path).path != '/api/notion-ai':
                return base.do_GET(self)
            if not self._authed():
                return self._send(403, {'ok': False, 'message': 'forbidden'})
            return self._send(200, nai.public())

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in ('/api/notion-ai/on', '/api/notion-ai/off'):
                return base.do_POST(self)
            if not self._authed():
                return self._send(403, {'ok': False, 'message': 'forbidden'})
            try:
                length = int(self.headers.get('Content-Length') or '0')
                body = json.loads(self.rfile.read(min(max(length, 0), 4096)) or b'{}') if length else {}
            except (ValueError, UnicodeDecodeError):
                body = {}
            try:
                if path.endswith('/on'):
                    result = nai.on(by=str(body.get('by') or 'панель')[:40], force=body.get('force') is True)
                else:
                    result = nai.off(str(body.get('reason') or 'выключен на панели')[:80])
            except Exception as exc:
                result = dict(ok=False, message='Не выполнено: ' + type(exc).__name__, state=nai.public())
            return self._send(200, result)

    ns['H'] = NotionAIHandler
    ns['PAGE'] = inject(ns['PAGE'])
    ns['NOTION_AI'] = nai
    return nai
