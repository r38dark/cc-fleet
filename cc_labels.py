"""Названия двух серверов в интерфейсе и в сообщениях: config.json → "labels": {"main": "A", "remote": "B"}.

В коде и в тестах сервер, где стоит панель, называется DEV, второй (куда передаётся работа) — PROD. Если в config.json заданы
свои короткие названия, панель подменяет эти два слова на границах вывода: страница и ответы API, уведомления в Telegram,
текст передачи работы второму серверу. Без настройки ничего не меняется — у владельца остаются DEV и PROD.
Новая установка записывает A и B («Claude A», «Claude B»); поменять можно в «Общие настройки» → «Названия серверов» в любой момент."""
import json
import os
import re
import tempfile

BASE = os.environ.get("CC_LIMITS_BASE") or os.path.dirname(os.path.abspath(__file__))
DEFAULTS = {"main": "DEV", "remote": "PROD"}
NEW_INSTALL = {"main": "A", "remote": "B"}
_NAME = re.compile(r"[A-Za-z0-9_-]{1,12}")
# содержимое консолей и чатов — чужой текст (код, логи, переписка): подмене не подлежит
SKIP_PATHS = ("/api/console", "/api/remote/console", "/api/notion-ai/view", "/api/notion-ai/agents/view")
_DEV = re.compile(r"\bDEV\b")
_PROD = re.compile(r"\bPROD\b")
_cache = {"mtime": None, "names": dict(DEFAULTS)}


def _config_path():
    return os.path.join(BASE, "config.json")


def names():
    """→ {"main": ..., "remote": ...}: из config.json, иначе DEV/PROD. Название — латиница, цифры, «_» и «-», до 12 знаков."""
    path = _config_path()
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return dict(DEFAULTS)
    if _cache["mtime"] == mtime:
        return _cache["names"]
    out = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            raw = (json.load(f) or {}).get("labels") or {}
        for key in out:
            val = str(raw.get(key) or "").strip()
            if _NAME.fullmatch(val):
                out[key] = val
    except (OSError, ValueError, AttributeError):
        pass
    _cache.update(mtime=mtime, names=out)
    return out


def active():
    return names() != DEFAULTS


def text(s):
    """Подменяет слова DEV и PROD (целыми словами: DEVICE и PRODUCT не трогает)."""
    if not isinstance(s, str) or not s or not active():
        return s
    n = names()
    return _PROD.sub(n["remote"], _DEV.sub(n["main"], s))


def obj(o):
    """Рекурсивно подменяет слова в строковых значениях (ключи словарей не трогает)."""
    if not active():
        return o
    if isinstance(o, str):
        return text(o)
    if isinstance(o, list):
        return [obj(x) for x in o]
    if isinstance(o, dict):
        return {k: obj(v) for k, v in o.items()}
    return o


def finish(body, ctype=""):
    """Тело HTTP-ответа: словарь/список — по значениям, байты страницы и JSON — по тексту, остальное без изменений."""
    if not active():
        return body
    if isinstance(body, (bytes, bytearray)):
        if "json" in ctype or ctype.startswith("text/"):
            try:
                return text(bytes(body).decode("utf-8")).encode("utf-8")
            except UnicodeDecodeError:
                return body
        return body
    return obj(body)


def valid(value):
    return bool(_NAME.fullmatch(str(value or "").strip()))


def save(main, remote, jload=None, jsave=None, path=None):
    """Записывает названия в config.json (пустые или совпадающие с DEV/PROD — убирает ключ). → (ok, сообщение)."""
    main, remote = str(main or "").strip(), str(remote or "").strip()
    for label, val in (("Этот сервер", main), ("Второй сервер", remote)):
        if val and not valid(val):
            return False, "%s: название — латиница, цифры, «_» и «-», до 12 знаков." % label
    if main and remote and main.lower() == remote.lower():
        return False, "Названия серверов должны отличаться."
    path = path or _config_path()
    try:
        cfg = (jload(path, {}) if jload else json.load(open(path, encoding="utf-8"))) or {}
    except (OSError, ValueError):
        cfg = {}
    labels = {k: v for k, v in (("main", main), ("remote", remote)) if v and v != DEFAULTS[k]}
    if labels:
        cfg["labels"] = {"main": main or DEFAULTS["main"], "remote": remote or DEFAULTS["remote"]}
    else:
        cfg.pop("labels", None)
    if jsave:
        jsave(path, cfg)
    else:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".config.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    _cache["mtime"] = None
    return True, "Названия сохранены."


def init_new_install(path=None):
    """Установщик: в config.json без ключа labels пишет A и B. Уже заданное не трогает. → True, если записал."""
    path = path or _config_path()
    try:
        cfg = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    except (OSError, ValueError):
        return False
    if cfg.get("labels"):
        return False
    cfg["labels"] = dict(NEW_INSTALL)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".config.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    _cache["mtime"] = None
    return True


# ---- блок «Названия серверов» в «Общие настройки» (подставляется в страницу; сам текст блока подмене не подлежит: названия берутся из API)
UI = r"""
<style>
#fleetLabels .fl-row{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:flex-end;margin:10px 0 4px}
#fleetLabels label{display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--fleet-muted,#8c9bad)}
#fleetLabels input{width:150px;padding:7px 9px;border:1px solid var(--fleet-line,#263140);border-radius:7px;background:var(--fleet-terminal,#0b0d10);color:var(--txt,#e8eaf0);font:13px system-ui,sans-serif}
#fleetLabels input:focus-visible{outline:1px solid var(--fleet-accent,#73dbb7)}
#fleetLabels .fl-msg{min-height:16px;margin-top:6px;font-size:11px;color:var(--fleet-muted,#8c9bad)}
</style>
<script>
(function(){try{
var base=(typeof API!=='undefined'?API:location.origin+'/cc-hook/'),tok=(typeof TOKEN!=='undefined'?TOKEN:'');
function $i(id){return document.getElementById(id)}
function api(path,body){return fetch(base+path,body?{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':tok},body:JSON.stringify(body)}:{headers:{'X-CC-Token':tok},cache:'no-store'}).then(function(r){return r.json()})}
var NAME=/^[A-Za-z0-9_-]{1,12}$/;
function build(c){
 var s=document.createElement('section');s.className='fleet-settings-group';s.id='fleetLabels';
 s.innerHTML='<div class="fleet-settings-group-title">Названия серверов</div>'
  +'<div class="fleet-catalog-note">Так два сервера называются в панели и в сообщениях: «Claude <b data-m>…</b>» — здесь, «Claude <b data-r>…</b>» — второй. Короткое название: латиница, цифры, «_», «-», до 12 знаков. Поменять можно в любой момент; страница обновится.</div>'
  +'<div class="fl-row"><label>Этот сервер<input id="fleetLabMain" maxlength="12" autocomplete="off" spellcheck="false"></label>'
  +'<label>Второй сервер<input id="fleetLabRemote" maxlength="12" autocomplete="off" spellcheck="false"></label>'
  +'<button type="button" class="ghostbtn" id="fleetLabSave">Сохранить</button></div><div class="fl-msg" id="fleetLabMsg"></div>';
 c.append(s);
 $i('fleetLabSave').onclick=function(){
  var m=$i('fleetLabMain').value.trim(),r=$i('fleetLabRemote').value.trim(),msg=$i('fleetLabMsg');
  if(!NAME.test(m)||!NAME.test(r)){msg.textContent='Название — латиница, цифры, «_» и «-», до 12 знаков.';return}
  if(m.toLowerCase()===r.toLowerCase()){msg.textContent='Названия серверов должны отличаться.';return}
  this.disabled=true;var btn=this;
  api('labels',{main:m,remote:r}).then(function(d){msg.textContent=d.message||'';if(d.ok)setTimeout(function(){location.reload()},700)}).catch(function(){msg.textContent='Панель не ответила.'}).then(function(){btn.disabled=false})};
 return s}
function paint(){api('labels').then(function(d){if(!d||!d.ok)return;
  var a=$i('fleetLabMain'),b=$i('fleetLabRemote');if(a&&document.activeElement!==a)a.value=d.main;if(b&&document.activeElement!==b)b.value=d.remote;
  document.querySelectorAll('#fleetLabels [data-m]').forEach(function(e){e.textContent=d.main});document.querySelectorAll('#fleetLabels [data-r]').forEach(function(e){e.textContent=d.remote})}).catch(function(){})}
function place(){var c=document.querySelector('#scrim .fleet-common-settings');if(!c)return false;var s=$i('fleetLabels')||build(c);if(c.lastElementChild!==s&&!c.contains(document.activeElement))c.append(s);paint();return true}
var n=0;(function tryPlace(){if(!place()&&++n<40)setTimeout(tryPlace,250)})();
var sc=$i('scrim');if(sc&&window.MutationObserver)new MutationObserver(function(){if(!sc.hidden&&sc.dataset.view==='general'){place()}}).observe(sc,{attributes:true,attributeFilter:['hidden','data-view']});
}catch(e){console.warn('labels',e)}})();
</script>
"""


def inject(page):
    """Добавляет блок настроек перед закрывающим </body>."""
    return page.replace("</body>", UI + "</body>", 1) if "</body>" in page else page + UI


def install(ns):
    """Подключается последним в cc_fleet.install: подмена слов в ответах панели, маршрут /api/labels, блок в «Общие настройки»,
    подмена в уведомлениях Telegram (tg_notify, _tg_call)."""
    base = ns["H"]
    jload, jsave = ns.get("jload"), ns.get("jsave")
    cfg_path = ns.get("CONFIG")

    class LabelsHandler(base):
        def _send(self, code, body, *args, **kw):
            # сигнатуру базового _send не меняем (ctype необязателен): в тестах и у других обёрток он бывает без него
            if str(getattr(self, "path", "") or "").startswith(SKIP_PATHS):
                return base._send(self, code, body, *args, **kw)
            ctype = args[0] if args else kw.get("ctype", "application/json; charset=utf-8")
            return base._send(self, code, finish(body, ctype), *args, **kw)

        def do_GET(self):
            from urllib.parse import urlparse
            if urlparse(self.path).path != "/api/labels":
                return base.do_GET(self)
            if not self._authed():
                return self._send(403, {"ok": False, "message": "forbidden"})
            n = names()
            # PROD и DEV в ответе не печатаем (подмена затронула бы их же): отдаём действующие названия
            return self._send(200, {"ok": True, "main": n["main"], "remote": n["remote"], "custom": active()})

        def do_POST(self):
            from urllib.parse import urlparse
            if urlparse(self.path).path != "/api/labels":
                return base.do_POST(self)
            if not self._authed():
                return self._send(403, {"ok": False, "message": "forbidden"})
            try:
                n = int(self.headers.get("Content-Length") or "0")
                body = json.loads(self.rfile.read(min(max(n, 0), 4096)) or b"{}") if n else {}
            except ValueError:
                body = {}
            if not isinstance(body, dict):
                body = {}
            ok, message = save(body.get("main"), body.get("remote"), jload, jsave, cfg_path)
            return self._send(200 if ok else 400, {"ok": ok, "message": message})

    ns["H"] = LabelsHandler
    ns["PAGE"] = inject(ns["PAGE"])
    orig_notify = ns.get("tg_notify")
    if orig_notify:
        def tg_notify(msg, *a, **k):
            return orig_notify(text(msg), *a, **k)
        ns["tg_notify"] = tg_notify
    orig_call = ns.get("_tg_call")
    if orig_call:
        def _tg_call(method, payload=None, *a, **k):
            if isinstance(payload, dict) and isinstance(payload.get("text"), str):
                payload = dict(payload, text=text(payload["text"]))
            return orig_call(method, payload, *a, **k)
        ns["_tg_call"] = _tg_call
