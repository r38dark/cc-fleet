#!/usr/bin/env python3
"""[notion-ai] Окно «Notion AI» в консоли балансера: читает постоянный чат Notion AI и пишет
последние сообщения в /root/notion_web/notion_ai_view.json (только чтение, ничего не отправляет).

Работает по запросу: панель трогает notion_ai_view.want при открытой вкладке «Notion AI».
Через 15 минут без запросов браузер закрывается. Вход в Notion — копия state.json моста
notion-delegate (сам state.json не меняется)."""
import json, os, re, shutil, sys, time, traceback

D = '/root/notion_web'
URL = 'https://app.notion.com/chat?t=40c55b37d45880e9b91600a9c9425683'  # по умолчанию; рабочий адрес — из настроек
CFG = '/opt/cc-limits/notion_ai.json'  # [notion-ai] ⚙ Настройки → Notion AI в панели
OUT = D + '/notion_ai_view.json'
WANT = D + '/notion_ai_view.want'
STATE = D + '/state.json'
PRIV = '/root/notion_ai_work/view/state_view.json'
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
IDLE = 900          # закрыть браузер через 15 минут без запросов панели
POLL = 2.5          # опрос страницы, секунд
RELOAD = 3600       # перезагрузка страницы раз в час
KEEP = 160          # сколько записей хранить
# Поле ввода: личный чат Notion AI или чат пользовательского агента («Chat with <агент>»), 07.11.26
INPUT = '[contenteditable=true][placeholder^="Ask Notion AI"], [contenteditable=true][placeholder^="Chat with"]'

EXTRACT = r"""()=>{const sc=[...document.querySelectorAll('.notion-scroller.vertical')].find(e=>e.querySelector('[data-agent-service-scroll-anchor]'));
 if(sc&&sc.scrollHeight-sc.scrollTop-sc.clientHeight>40)sc.scrollTop=sc.scrollHeight;
 const prep=r=>{const undo=[];
  r.querySelectorAll('p *,li *,h1 *,h2 *,h3 *,td *').forEach(e=>{if(/^(UL|OL|LI|P|PRE|TABLE|DIV)$/.test(e.tagName)&&!e.closest('a'))return;
   if(e.tagName!=='BR'&&e.tagName!=='IMG'&&!e.textContent.trim()){undo.push([e,e.style.display]);e.style.display='none';return}const d=getComputedStyle(e).display;
   if(d!=='none'&&d!=='contents'&&!d.startsWith('inline')){undo.push([e,e.style.display]);e.style.display='inline'}});
  r.querySelectorAll('li').forEach(li=>{const l=li.parentElement,ol=l&&l.tagName==='OL',m=document.createElement('span');m.textContent=ol?((l.start||1)+[...l.children].indexOf(li))+'. ':'• ';li.prepend(m);undo.push([m,null])});
  return ()=>undo.forEach(([e,v])=>{if(v===null)e.remove();else e.style.display=v})};
 const txt=r=>{const u=prep(r);try{return (r.innerText||'').trim()}finally{u()}};
 const rows=[...document.querySelectorAll('[data-agent-service-scroll-anchor]')].map(r=>{const a=r.getAttribute('data-agent-service-scroll-anchor')||'';
  return {id:a,text:txt(r),pics:[...r.querySelectorAll('[aria-label^="Preview "]')].map(b=>b.getAttribute('aria-label').slice(8)).slice(0,6),
   user:a.startsWith('local:')||!!r.querySelector('[aria-label="Copy text"]'),end:!!r.querySelector('[aria-label="Copy response"]')}});
 return {rows,running:!!document.querySelector('[aria-label="Stop AI message"]'),login:/\/login/.test(location.pathname)}}"""

NOANIM = r"""document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');
 s.textContent='*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}';document.documentElement.appendChild(s)})"""

TIME = re.compile(r'^(\d{1,2}):(\d{2})\s*([AP]M)$', re.I)


def log(msg):
    print(time.strftime('%d.%m %H:%M:%S'), msg, flush=True)


def t24(s):
    m = TIME.match(s.strip())
    if not m:
        return ''
    h, mi, ap = int(m.group(1)) % 12, m.group(2), m.group(3).upper()
    return '%02d:%s' % (h + (12 if ap == 'PM' else 0), mi)


def ru_dur(s):
    s = re.sub(r'(\d+)h', r'\1 ч', s); s = re.sub(r'(\d+)m', r'\1 мин', s); s = re.sub(r'(\d+)s', r'\1 с', s)
    return s


def classify(r):
    text, rid = r['text'].replace('\u200b', ''), r['id']
    lines = [l for l in text.split('\n')]
    if r['user']:
        tm = ''
        if lines and TIME.match(lines[-1].strip()):
            tm = t24(lines.pop())
        body = '\n'.join(lines).strip()
        src = 'Notion'
        m = re.match(r'^\[(TG|Панель) (\d{1,2}:\d{2})\]\s*', body)
        if m:
            src, tm = ('Telegram' if m.group(1) == 'TG' else 'Панель'), m.group(2); body = body[m.end():]
        body = re.sub(r'\n?—\s*из (Telegram|панели балансера)[^\n]*$', '', body.strip()).strip()
        body = re.sub(r'\(фото: [^)]*\)', '📷 фото', body)
        body = re.sub(r'\(файл: [^)]*\)', '📎 файл', body)
        body = re.sub(r'<br\s*/?>', '\n', body)
        return dict(id=rid, kind='user', text=body[:4000], time=tm, src=src)
    if rid.startswith('tool-group:'):
        if text.startswith('Worked for'):
            return dict(id=rid, kind='work', text='Работал ' + ru_dur(text[len('Worked for'):].strip()))
        return dict(id=rid, kind='step', text=text[:300])
    if r['end'] and TIME.match(text):
        return dict(id=rid, kind='end', text='', time=t24(text))
    return dict(id=rid, kind='ai', text=text[:6000], pics=r.get('pics') or [])


def merge(buf, new):
    if not new:
        return buf
    ids = [b['id'] for b in buf]
    first = new[0]['id']
    if first in ids:
        return (buf[:ids.index(first)] + new)[-KEEP:]
    key = (new[0]['kind'], new[0].get('text'))
    for i in range(len(buf) - 1, -1, -1):
        if (buf[i]['kind'], buf[i].get('text')) == key:
            return (buf[:i] + new)[-KEEP:]
    return new[-KEEP:]


def chat_url():
    if not os.path.exists(CFG):
        return URL  # до появления настроек — прежний адрес этого сервера
    try:
        u = str(json.load(open(CFG)).get('chat_url') or '')
    except Exception:
        u = ''
    return u if re.fullmatch(r'https://(app\.notion\.com|www\.notion\.so|notion\.so)/chat\?t=[0-9a-f]{32}', u) else ''


def write(d):
    d['ts'] = time.time()
    d['chat'] = chat_url()
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(d, f, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, OUT)


def wanted():
    try:
        return time.time() - os.path.getmtime(WANT) < IDLE
    except OSError:
        return False


def load_buf():
    try:
        d = json.load(open(OUT))
    except Exception:
        return []
    return (d.get('rows') or []) if d.get('chat', URL) == chat_url() else []  # сменили чат — старые сообщения не показываем


def session(p, buf):
    os.makedirs(os.path.dirname(PRIV), exist_ok=True)
    shutil.copy(STATE, PRIV); os.chmod(PRIV, 0o600)
    write(dict(ok=True, state='starting', message='Подключаюсь к чату Notion AI…', running=False, rows=buf))
    b = p.chromium.launch(args=['--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage', '--disable-gpu',
                                '--blink-settings=imagesEnabled=false', '--disable-extensions', '--mute-audio'])
    try:
        # [notion-ai] Экономим процессор: без анимаций и картинок, окно поменьше (текст читается из DOM).
        ctx = b.new_context(storage_state=PRIV, user_agent=UA, viewport={'width': 1100, 'height': 1600}, locale='ru-RU', timezone_id='Asia/Irkutsk',
                            reduced_motion='reduce')
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        ctx.add_init_script(NOANIM)
        pg = ctx.new_page()
        url = chat_url()
        if not url:
            raise RuntimeError('чат Notion AI не задан: ⚙ Общие настройки → Notion AI')
        pg.goto(url, wait_until='domcontentloaded', timeout=60000)
        try:
            pg.locator(INPUT).first.wait_for(timeout=45000)
        except Exception:
            if 'login' in pg.url:
                raise RuntimeError('Нет входа в Notion. Мост notion-delegate переподключится сам.')
            raise
        pg.wait_for_timeout(2500)
        log('открыт чат')
        started, last_sig = time.time(), None
        while wanted():
            if chat_url() != url:
                log('в настройках сменили чат — переоткрываю')
                return []
            d = pg.evaluate(EXTRACT)
            if d.get('login'):
                raise RuntimeError('Нет входа в Notion. Мост notion-delegate переподключится сам.')
            rows = [classify(r) for r in d['rows'] if r['text'] or r['user']]
            buf = merge(buf, rows)
            sig = json.dumps([buf[-40:], d['running']], ensure_ascii=False)
            if sig != last_sig or int(time.time()) % 10 < POLL:
                write(dict(ok=True, state='ok', message='', running=d['running'], rows=buf))
                last_sig = sig
            if time.time() - started > RELOAD:
                pg.reload(wait_until='domcontentloaded', timeout=60000)
                pg.locator(INPUT).first.wait_for(timeout=45000)
                pg.wait_for_timeout(2500); started = time.time()
            time.sleep(POLL)
        log('простой — закрываю браузер')
        write(dict(ok=True, state='idle', message='Окно не открыто — чтение чата на паузе.', running=False, rows=buf))
        return buf
    finally:
        try:
            b.close()
        except Exception:
            pass


def main():
    from playwright.sync_api import sync_playwright
    log('старт')
    buf, fails = load_buf(), 0
    while True:
        if not wanted():
            time.sleep(2)
            continue
        try:
            with sync_playwright() as p:
                buf = session(p, buf)
            fails = 0
        except Exception as e:
            fails += 1
            msg = str(e).split('\n')[0][:200]
            log('ошибка: ' + msg)
            if fails == 1:
                traceback.print_exc()
            write(dict(ok=False, state='error', message=msg if msg.startswith('Нет входа') else 'Не удалось прочитать чат: ' + msg,
                       running=False, rows=buf))
            time.sleep(min(300, 15 * fails))


if __name__ == '__main__':
    main()
