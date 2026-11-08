"""Агенты Notion для балансера (, 07.11.26).

Чтение и имя — официальный Agent API Notion (токен владельца в notion_pat, агент при этом НЕ запускается, кредиты не тратятся).
Сообщения агентам — только через сайт (печатаем в чат, как человек), API-запусков агента нет.
Модель, effort, «Web access», инструкции, создание из шаблона «Morning brief», имя чата — через сайт (Playwright).
Реестр nagents.json: чат каждого агента и последний известный effort. Импортируется сервисом notion-delegate."""
import base64, calendar, json, os, re, subprocess, threading, time, traceback, urllib.request, urllib.error, uuid

D = "/root/notion_web"
PAT = f"{D}/notion_pat"
REG = f"{D}/nagents.json"
INSTR = f"{D}/agent_instructions.md"
API = "https://api.notion.com/v1"
VER = "2026-03-11"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
EFFORTS = ["Low", "Medium", "High", "xHigh", "Max"]
EFFORT_ARIA = {"low": "Low", "medium": "Medium", "high": "High", "extra high": "xHigh", "xhigh": "xHigh", "max": "Max", "maximum": "Max"}
MENU_JS = """()=>[...document.querySelectorAll('[role=menu]')].map(m=>[...m.querySelectorAll('[role=menuitem],[role=menuitemradio],[role=option]')].map(e=>({t:(e.innerText||'').split('\\n').map(s=>s.trim()).filter(Boolean),dis:e.getAttribute('aria-disabled')==='true'})))"""
NAME_RE = re.compile(r"^[^\x00-\x1f<>]{1,80}$")
TG_RE = re.compile(r"^(-?\d{4,20}|@[A-Za-z0-9_]{5,32})$")  # куда отвечает агент в Telegram: id чата/канала или @имя канала; пусто — основной чат балансера
LOCK = threading.RLock()
NAI_CFG = os.environ.get("CC_NOTION_AI_CFG") or "/opt/cc-limits/notion_ai.json"  # общие настройки панели (⚙ Настройки → Notion AI)
INSTR_LOCAL = f"{D}/agent_instructions.local.md"  # личные правила владельца сервера: дописываются к общей инструкции, в репозиторий не попадают
HANDOFF = "/opt/cc-limits/profile_exchange/codex/outbox/agent_handoff/current_project"
# Этапы создания агента: (ключ, текст в строке состояния, секунд по умолчанию). Цифры по первому замеру 08.11.2026 (вся цепочка ~3 мин);
# после каждого успешного создания реестр хранит последние 5 замеров этапа, полоса прогресса считает по их среднему.
CREATE_STEPS = [
    ("tpl", "создаю агента из шаблона «Morning brief»…", 20), ("setup", "Notion настраивает агента…", 3),
    ("finish", "агент создан, Notion дописывает настройку…", 51), ("name", "имя агента…", 1),
    ("key", "выдаю ключ доступа к серверу…", 2),
    ("settings", "модель, effort, доступ в интернет, инструкции…", 44), ("cleanup", "убираю чат настройки…", 15),
    ("open", "открываю чат агента…", 18), ("rename", "называю чат…", 14),
    ("login", "ключ в инструкции агента, проверяю вход на сервер…", 30)]
STEP_KEY = {t: k for k, t, _ in CREATE_STEPS}
SSH_STEPS = ("key", "login")
KEEP_TIMES = 5


def step_plan(ssh): return [k for k, _, _ in CREATE_STEPS if ssh or k not in SSH_STEPS]


def step_estimates(plan):
    hist = reg_load().get("timing") or {}
    dflt = {k: d for k, _, d in CREATE_STEPS}
    return {k: (sum(hist[k]) / len(hist[k]) if hist.get(k) else dflt[k]) for k in plan}


def step_mark(j, key, now=None):
    """Этап key начался: предыдущий закрыт, его длительность записана."""
    if not key or key not in (j.get("plan") or []): return
    now = now or time.time()
    step_close(j, now)
    j["cur"], j["cur_t"] = key, now


def step_close(j, now=None):
    if j.get("cur"): j.setdefault("done", {})[j["cur"]] = (now or time.time()) - j["cur_t"]; j["cur"] = None


def progress_of(j, now=None):
    """Полоса по времени: доля сделанных этапов (по средним замерам) + часть текущего; на 100% только когда задание закончено."""
    plan = j.get("plan") or []
    if not plan: return {}
    now = now or time.time(); est = j.get("est") or step_estimates(plan); n = len(plan)
    if j.get("status") == "done": return dict(pct=100, eta=0, step=n, steps=n)
    done, cur = j.get("done") or {}, j.get("cur")
    total = sum(est.values()) or 1
    spent = sum(est[k] for k in plan if k in done)
    el = max(0.0, now - j["cur_t"]) if cur else 0.0
    ce = est.get(cur, 0) if cur else 0
    pct = min(99, int(100 * (spent + min(el, ce * 0.95)) / total))
    after = sum(est[k] for k in plan if k not in done and k != cur)
    eta = int(round(after + (max(ce - el, 5) if cur else 0)))
    return dict(pct=pct, eta=eta, step=(plan.index(cur) + 1 if cur in plan else (len([k for k in plan if k in done]) or 0)), steps=n)


def timing_record(j):
    """Успешное создание: замеры этапов — в реестр (последние KEEP_TIMES на этап)."""
    with LOCK:
        r = reg_load(); t = r.setdefault("timing", {})
        for k, d in (j.get("done") or {}).items():
            if d > 0: t[k] = (t.get(k, []) + [round(d, 1)])[-KEEP_TIMES:]
        reg_save(r)


def nai_cfg():
    try:
        with open(NAI_CFG) as f: return json.load(f) or {}
    except Exception: return {}


_HOST = {"ts": 0, "v": ""}


def server_host():
    """Адрес сервера для SSH агента: ⚙ Настройки → Notion AI → «Адрес сервера» (ssh_host); пусто — внешний IP этого сервера."""
    h = str(nai_cfg().get("ssh_host") or "").strip()
    if h: return h
    if time.time() - _HOST["ts"] < 600 and _HOST["v"]: return _HOST["v"]
    for u in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "curl/8"}), timeout=5) as r:
                v = r.read().decode().strip()
            if re.fullmatch(r"[0-9a-fA-F:.]{3,45}", v): _HOST.update(ts=time.time(), v=v); return v
        except Exception: pass
    try:  # нет выхода к сервисам «мой IP» — первый публичный адрес самой машины
        import subprocess
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout.split()
        return next((a for a in out if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", a) and not a.startswith(("10.", "127.", "192.168.", "172."))), "")
    except Exception: return ""


def key_fingerprint(pub):
    parts = str(pub or "").split()
    if len(parts) < 2: return ""
    try: blob = base64.b64decode(parts[1], validate=True)
    except Exception: return ""
    import hashlib
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def ssh_login_seen(pub, since):
    """Заходил ли агент по своему ключу: отпечаток в журнале sshd («Accepted publickey») после момента since."""
    fp = key_fingerprint(pub)
    if not fp: return False
    import subprocess
    out = ""
    try:
        r = subprocess.run(["journalctl", "-u", "ssh", "-u", "sshd", "--since", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since)), "--no-pager", "-o", "cat"],
                           capture_output=True, text=True, timeout=20)
        out = r.stdout or ""
    except Exception: pass
    if not out:
        try:
            with open("/var/log/auth.log", errors="replace") as f: out = "".join(f.readlines()[-3000:])
        except OSError: pass
    return any("Accepted publickey" in l and fp in l for l in out.splitlines())


# ---------- официальный API (только чтение и имя) ----------
def api(method, path, body=None, timeout=25):
    tok = open(PAT).read().strip()
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + tok, "Notion-Version": VER, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: d = json.loads(e.read() or b"{}")
        except Exception: d = {}
        raise RuntimeError(f"Notion API {e.code}: {d.get('message') or d.get('code') or e.reason}"[:300])


def dash(i):
    i = i.replace("-", "")
    return f"{i[:8]}-{i[8:12]}-{i[12:16]}-{i[16:20]}-{i[20:]}" if len(i) == 32 else i


def chat_url(session_id): return "https://app.notion.com/chat?t=" + session_id.replace("-", "")


def session_of(url):
    m = re.search(r"[?&]t=([0-9a-f]{32})", url or "")
    return dash(m.group(1)) if m else ""


def model_label(m):
    """{mode:auto} → Auto; claude-opus-5-5 → Opus 5.5; иначе id как есть (точная подпись — из настроек агента)."""
    if not m or m.get("mode") != "pinned": return "Auto"
    i = m.get("id") or ""
    x = re.fullmatch(r"claude-(opus|sonnet|haiku)-(\d+)-(\d+)", i)
    return f"{x.group(1).title()} {x.group(2)}.{x.group(3)}" if x else (i or "ранний доступ")


# ---------- реестр ----------
def reg_load():
    try: return json.load(open(REG))
    except (FileNotFoundError, ValueError): return {"agents": {}, "models": [], "models_ts": 0}


def reg_save(r):
    with LOCK:
        tmp = REG + ".tmp"
        with open(tmp, "w") as f: json.dump(r, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600); os.replace(tmp, REG)


def reg_set(aid, **kw):
    with LOCK:
        r = reg_load(); a = r["agents"].setdefault(dash(aid), {}); a.update(kw); reg_save(r); return a


_CACHE = {"ts": 0, "list": None}


def list_agents(main_url="", fresh=False):
    """Пользовательские агенты (активные) + чат и effort из реестра. Главный — тот, чей чат стоит в настройках панели."""
    with LOCK:
        if not fresh and _CACHE["list"] is not None and time.time() - _CACHE["ts"] < 20: return _CACHE["list"]
    res = api("POST", "/agents/query", {})
    r = reg_load(); main_sid = session_of(main_url); out = []; name_upd = {}
    main_aid = r.get("main_aid") if r.get("main_sid") == main_sid else None
    if main_sid and not main_aid:
        try: main_aid = api("GET", f"/sessions/{main_sid}").get("agent_id")
        except Exception: main_aid = None
        if main_aid: r["main_sid"], r["main_aid"] = main_sid, main_aid; reg_save(r)
    for a in res.get("results", []):
        if a.get("agent_type") != "custom_agent" or a.get("status") != "active": continue
        aid = a["id"]; ra = r["agents"].get(aid, {})
        sid = main_sid if aid == main_aid else ra.get("chat_sid", "")
        if not sid:  # агент без записи в реестре: берём его последний чат
            try:
                q = api("POST", "/sessions/query", {"filter": {"property": "agent_id", "string": {"equals": aid}}, "page_size": 5})
                sid = next((x["id"] for x in q.get("results", []) if x.get("trigger_type") == "chat"), "")
                if sid: r["agents"].setdefault(aid, {})["chat_sid"] = sid; reg_save(r)
            except Exception: sid = ""
        nm = a.get("name") or ""
        if aid != main_aid and nm and ra.get("name") != nm: name_upd[aid] = nm  # имя агента в реестре = имя в Notion (по нему notion-ai-reply находит чат Telegram)
        out.append({"aid": aid, "name": a.get("name") or "", "model": ra.get("model_label") or model_label(a.get("model")),
                    "model_api": a.get("model"), "effort": ra.get("effort", ""), "web": ra.get("web"), "main": aid == main_aid,
                    "chat": chat_url(sid) if sid else "", "state": ra.get("state", "ready"), "created": ra.get("created", 0),
                    "tg": ra.get("tg_chat_id", ""), "ssh": bool(ra.get("ssh")), "ssh_ok": ra.get("ssh_ok")})
    if name_upd:
        with LOCK:  # свежий реестр: пока шли запросы к Notion, задание могло дописать свои поля
            rr = reg_load()
            for aid, nm in name_upd.items():
                e = rr["agents"].setdefault(aid, {}); old = e.get("name")
                e["name"] = nm
                if old and old != nm: e["old_names"] = sorted(set(e.get("old_names") or []) | {old})  # прежнее имя остаётся запасным
            reg_save(rr)
    out.sort(key=lambda x: (not x["main"], x["created"] or 0, x["name"]))
    with LOCK: _CACHE.update(ts=time.time(), list=out)
    return out


def agent_by(aid, main_url=""):
    aid = dash(aid)
    return next((a for a in list_agents(main_url) if a["aid"] == aid), None)


def chat_rows(sid, after=0):
    """События чата → строки окна консоли (формат notion_ai_view). Только чтение."""
    rows, cursor, seen = [], None, 0
    for _ in range(20):
        body = {"filter": {"property": "sequence", "number": {"greater_than": after}}} if after else {}
        if cursor: body["start_cursor"] = cursor
        d = api("POST", f"/sessions/{sid}/events/query", body)
        for e in d.get("results", []):
            seen = max(seen, e.get("sequence") or 0)
            t = e.get("type"); txt = "\n".join(c.get("text", "") for c in (e.get("content") or []) if c.get("type") == "text").strip()
            txt = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>~])", r"\1", txt)  # Notion экранирует markdown в тексте событий
            hm = time.strftime("%H:%M", time.gmtime(_ts(e.get("created_at")) + 8 * 3600)) if e.get("created_at") else ""
            if t == "user.message":
                src, m = "Notion", re.match(r"^\[(TG|Панель) (\d{1,2}:\d{2})\]\s*", txt)
                if m: src, txt = ("Telegram" if m.group(1) == "TG" else "Панель"), txt[m.end():]
                txt = re.sub(r"\n\n— из панели балансера.*$", "", txt, flags=re.S)
                rows.append({"id": e["id"], "kind": "user", "src": src, "time": hm, "text": txt})
            elif t == "agent.message" and txt: rows.append({"id": e["id"], "kind": "ai", "text": txt})
            elif t == "agent.tool_use": rows.append({"id": e["id"], "kind": "step", "text": "инструмент: " + (e.get("tool_name") or "")})
            elif t == "session.status" and e.get("status") in ("completed", "failed", "canceled"):
                rows.append({"id": e["id"], "kind": "end", "time": hm, "text": "" if e.get("status") == "completed" else e.get("status")})
        if not d.get("has_more"): break
        cursor = d.get("next_cursor")
    return rows, seen


def _ts(s):
    try: return calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception: return 0


_VIEW = {}


def view(aid, main_url=""):
    """Окно консоли агента: последние 160 строк, «работает» — по статусу сессии. Кэш 3 с на агента."""
    a = agent_by(aid, main_url)
    if not a: return {"ok": False, "state": "error", "message": "агент не найден", "rows": []}
    sid = session_of(a["chat"])
    if not sid: return {"ok": True, "state": "ok", "message": "У агента ещё нет чата.", "rows": [], "running": False, "chat": ""}
    c = _VIEW.get(sid)
    if c and time.time() - c["ts"] < 3: return c["out"]
    rows, seq = (c["rows"], c["seq"]) if c else ([], 0)
    new, seq2 = chat_rows(sid, seq)
    rows = (rows + new)[-160:]
    st = api("GET", f"/sessions/{sid}").get("status")
    out = {"ok": True, "state": "ok", "message": "", "rows": rows, "running": st in ("queued", "in_progress"), "chat": a["chat"], "ts": time.time()}
    _VIEW[sid] = {"ts": time.time(), "rows": rows, "seq": max(seq, seq2), "out": out}
    return out


def wait_reply(sid, after, timeout=240):
    """Ждать ответ агента после события after (чтение событий API)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(4)
        rows, _ = chat_rows(sid, after)
        st = api("GET", f"/sessions/{sid}").get("status")
        ai = [x["text"] for x in rows if x["kind"] == "ai"]
        if ai and st not in ("queued", "in_progress"): return "\n".join(ai)
    raise RuntimeError("агент не ответил за %d с" % timeout)


def last_seq(sid):
    _, s = chat_rows(sid, 0)
    return s


# ---------- сайт (Playwright) ----------
def browser(p):
    b = p.chromium.launch(args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"])
    ctx = b.new_context(storage_state=f"{D}/state.json", user_agent=UA, viewport={"width": 1400, "height": 900}, locale="ru-RU", timezone_id="Asia/Irkutsk")
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return b, ctx, ctx.new_page()


def goto(pg, url, wait=9000):
    pg.goto(url, wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(wait)
    if "/login" in pg.url: raise RuntimeError("нет входа в Notion")


def api_agent_ids():
    """id всех пользовательских агентов по официальному списку (боковой панели не верим: грузится не сразу — сбой 07.11 22:52)."""
    return {a["id"] for a in api("POST", "/agents/query", {}).get("results", []) if a.get("agent_type") == "custom_agent"}


def main_aid():
    return reg_load().get("main_aid") or ""


def _label(t):
    return t[0] if t[0] == "Auto" or len(t) < 2 else t[0] + " " + t[1]


def _menu_pick(pg, label):
    grp = (pg.evaluate(MENU_JS) or [[]])[-1]  # последнее открытое меню — то, что открыли
    for k, x in enumerate(grp):
        if x["t"] and _label(x["t"]) == label:
            if x.get("dis"): raise RuntimeError(f"«{label}» недоступна")
            pg.locator("[role=menu]").last.locator("[role=menuitem],[role=menuitemradio],[role=option]").nth(k).click()
            pg.wait_for_timeout(1500); return True
    return False


def read_settings(pg, aid):
    goto(pg, f"https://app.notion.com/agent/{aid.replace('-', '')}?wfv=settings")
    eb = pg.locator('[aria-label^="Change effort"]').first
    cur = (eb.get_attribute("aria-label") or "").lower().split("currently", 1)[-1].strip(" ,.") if eb.count() else ""
    mb = _model_btn(pg)
    web = pg.evaluate("()=>{const f=l=>{const e=[...document.querySelectorAll('[role=switch]')].find(x=>x.getAttribute('aria-label')===l);return e?!!e.checked:null};const a=f('Toggle web search'),b=f('Toggle web browser');return a===null&&b===null?null:!!(a&&b)}")
    return {"model": (mb.inner_text() or "").strip() if mb else "", "effort": EFFORT_ARIA.get(cur, cur), "web": web}


def _model_btn(pg):
    """Кнопка модели в строке «Model» раздела Advanced (effort при модели Auto Notion не показывает — на него не опираемся)."""
    lab = pg.get_by_text("Model", exact=True)
    for k in range(lab.count()):
        row = lab.nth(k).locator("xpath=ancestor::*[.//*[@role='button' or self::button]][1]")
        b = row.locator("[role=button],button").first
        if b.count() and not (b.get_attribute("aria-label") or "").startswith("Change effort"): return b
    return None


def models_list(pg):
    mb = _model_btn(pg)
    if not mb: return []
    mb.scroll_into_view_if_needed(); mb.click(); pg.wait_for_timeout(1500)
    try:
        grp = (pg.evaluate(MENU_JS) or [[]])[-1]
        return [{"label": _label(x["t"]), "disabled": x["dis"], "beta": "Beta" in x["t"]}
                for x in grp if x["t"] and x["t"][0] not in ("Older models", "Restricted models")]
    finally:
        pg.keyboard.press("Escape"); pg.wait_for_timeout(500)


def set_settings(pg, aid, model=None, effort=None, web=None, instructions=None):
    """Инструкции (API) → страница настроек агента: модель, effort, выход в интернет → Save (публикует и инструкции). Возвращает итог чтения."""
    if instructions is not None:
        if dash(aid) == main_aid(): raise RuntimeError("инструкции главного агента из заданий не меняются")
        replace_instructions(aid, instructions)
    goto(pg, f"https://app.notion.com/agent/{aid.replace('-', '')}?wfv=settings", 10000)
    if model:
        mb = _model_btn(pg)
        if not mb: raise RuntimeError("кнопка модели в настройках не найдена")
        if (mb.inner_text() or "").strip() != model:
            mb.scroll_into_view_if_needed(); mb.click(); pg.wait_for_timeout(1500)
            if not _menu_pick(pg, model): pg.keyboard.press("Escape"); raise RuntimeError(f"модели «{model}» нет в списке")
    if effort:
        eb = pg.locator('[aria-label^="Change effort"]').first
        if not eb.count(): raise RuntimeError("для этой модели Notion не даёт выбрать effort")
        cur = EFFORT_ARIA.get((eb.get_attribute("aria-label") or "").lower().split("currently", 1)[-1].strip(" ,."), "")
        if cur != effort:
            eb.scroll_into_view_if_needed(); eb.click(); pg.wait_for_timeout(1200)
            it = pg.locator("[role=menu]").get_by_text(effort, exact=True)
            if it.count() != 1: pg.keyboard.press("Escape"); raise RuntimeError(f"уровня «{effort}» нет")
            it.first.click(); pg.wait_for_timeout(1500)
    if web is not None:  # выход в интернет у компьютера агента: «Web access» + «Web Browser» (как у главного агента)
        for lab in ("Toggle web search", "Toggle web browser"):
            sw = pg.locator(f'[role=switch][aria-label="{lab}"]').first
            if not sw.count() or bool(sw.is_checked()) == bool(web): continue
            pg.evaluate("e=>e.scrollIntoView({block:'center'})", sw.element_handle()); pg.wait_for_timeout(600)
            bb = sw.locator("xpath=..").bounding_box() or sw.bounding_box()   # кликаем видимую дорожку, а не скрытый input
            pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2); pg.wait_for_timeout(1500)
            ok = pg.locator("[role=dialog],[role=alertdialog]").get_by_role("button", name="Turn on web browser")  # Notion спрашивает «Are you sure?»
            if ok.count(): ok.first.click(); pg.wait_for_timeout(1500)
            if bool(sw.is_checked()) != bool(web): raise RuntimeError(f"переключатель «{lab}» не переключился")
    publish(pg, aid)
    return read_settings(pg, aid)


def agent_state(aid):
    """(есть неопубликованные изменения, время публикации рабочей версии); (None, None) — не удалось узнать. Флаг сам по себе врёт: после Save он может остаться True."""
    try:
        d = api("GET", f"/agents/{dash(aid)}")
        return bool(d.get("has_unpublished_changes")), (d.get("version") or {}).get("published_at")
    except Exception: return None, None


def publish(pg, aid, tries=3):
    """Save на странице настроек и проверка, что Notion правда опубликовал (флаг снят или время публикации сдвинулось): кнопка может не включиться сразу,
    и тогда агент остаётся со старыми инструкциями (08.11, 14:04)."""
    base = agent_state(aid)[1]
    for _ in range(tries):
        flag, ts = agent_state(aid)
        if flag is False or (ts and base and ts != base): return
        sv = pg.get_by_role("button", name="Save", exact=True).first
        for _ in range(30):
            if sv.count() and sv.is_enabled(): sv.click(); pg.wait_for_timeout(5000); break
            pg.wait_for_timeout(700)
        else:
            goto(pg, f"https://app.notion.com/agent/{aid.replace('-', '')}?wfv=settings", 10000); continue  # кнопка не включилась — перечитываем страницу
        for _ in range(6):
            flag, ts = agent_state(aid)
            if flag is None or flag is False or (ts and base and ts != base): return
            pg.wait_for_timeout(2500)
    flag, ts = agent_state(aid)
    if not (flag is None or flag is False or (ts and base and ts != base)): raise RuntimeError("Notion не опубликовал изменения агента: кнопка Save не сработала")


def _rich(text):
    """`код` и **жирный** → rich_text Notion."""
    out = []
    for part in re.split(r"(`[^`]+`|\*\*[^*]+\*\*)", text):
        if not part: continue
        ann = {}
        if part.startswith("`") and part.endswith("`"): part, ann = part[1:-1], {"code": True}
        elif part.startswith("**") and part.endswith("**"): part, ann = part[2:-2], {"bold": True}
        for i in range(0, len(part), 1900): out.append({"type": "text", "text": {"content": part[i:i + 1900]}, "annotations": ann})
    return out


def md_blocks(md):
    bl, code = [], None
    for line in md.splitlines():
        l = line.rstrip()
        if l.strip().startswith("```"):  # ``` … ``` — один блок кода
            if code is None: code = []
            else:
                txt = "\n".join(code)
                bl.append({"type": "code", "code": {"language": "plain text", "rich_text": [{"type": "text", "text": {"content": txt[i:i + 1900]}} for i in range(0, max(len(txt), 1), 1900)]}})
                code = None
            continue
        if code is not None: code.append(line.rstrip("\r")); continue
        if not l.strip(): continue
        for pre, typ in (("### ", "heading_3"), ("## ", "heading_2"), ("# ", "heading_1"), ("- ", "bulleted_list_item")):
            if l.startswith(pre): bl.append({"type": typ, typ: {"rich_text": _rich(l[len(pre):])}}); break
        else:
            m = re.match(r"^\d+\.\s+(.*)", l)
            if m: bl.append({"type": "numbered_list_item", "numbered_list_item": {"rich_text": _rich(m.group(1))}})
            else: bl.append({"type": "paragraph", "paragraph": {"rich_text": _rich(l)}})
    return bl


def replace_instructions(aid, md):
    """Страница инструкций агента (черновик): убрать все блоки шаблона (база шаблона — в Корзину Notion) и записать новые. Официальный API."""
    pid = api("GET", f"/agents/{dash(aid)}").get("instructions_page_id")
    if not pid: raise RuntimeError("у агента нет страницы инструкций")
    ids, cursor = [], None
    for _ in range(20):
        d = api("GET", f"/blocks/{pid}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else ""))
        ids += [b["id"] for b in d.get("results", [])]
        if not d.get("has_more"): break
        cursor = d.get("next_cursor")
    for b in ids: api("DELETE", f"/blocks/{b}")
    blocks = md_blocks(md)
    for i in range(0, len(blocks), 90): api("PATCH", f"/blocks/{pid}/children", {"children": blocks[i:i + 90]})
    return pid


def open_chat_input(pg):
    box = pg.locator('[contenteditable=true][placeholder^="Chat with"], [contenteditable=true][placeholder^="Ask Notion AI"]').first
    box.wait_for(timeout=45000); pg.wait_for_timeout(1500); return box


def type_send(pg, box, text):
    head = (text.strip().splitlines() or [""])[0][:30]
    box.click(); pg.keyboard.press("Control+A"); pg.keyboard.press("Delete"); pg.keyboard.insert_text(text); pg.wait_for_timeout(400)
    for _ in range(6):
        pg.keyboard.press("Enter")
        for _ in range(10):
            pg.wait_for_timeout(300)
            if head not in (box.inner_text() or ""): return True
        pg.wait_for_timeout(3000)
    raise RuntimeError("сообщение не ушло: поле ввода не очистилось")


def new_chat(pg, aid, text):
    """Первый чат агента — через сайт («New chat with …»): печатаем первое сообщение, адрес чата появляется в строке браузера."""
    goto(pg, f"https://app.notion.com/agent/{aid.replace('-', '')}?wfv=chat")
    box = open_chat_input(pg); type_send(pg, box, text)
    for _ in range(40):
        pg.wait_for_timeout(1000)
        sid = session_of(pg.url)
        if sid: return sid
    raise RuntimeError("чат агента не открылся (нет ?t= в адресе)")


def rename_chat(pg, sid, name):
    goto(pg, chat_url(sid))
    pg.locator('[aria-label="Delete, rename, and more…"]').first.click(); pg.wait_for_timeout(1200)
    pg.locator("[role=menu]").get_by_text("Rename", exact=True).first.click(); pg.wait_for_timeout(1200)
    pg.keyboard.press("Control+A"); pg.keyboard.insert_text(name); pg.keyboard.press("Enter"); pg.wait_for_timeout(3000)


def delete_chat(pg, url):
    goto(pg, url)
    pg.locator('[aria-label="Delete, rename, and more…"]').first.click(); pg.wait_for_timeout(1200)
    pg.locator("[role=menu]").get_by_text("Delete", exact=True).first.click(); pg.wait_for_timeout(1500)
    c = pg.locator("[role=dialog], [role=alertdialog]").get_by_text("Confirm", exact=True)
    if not c.count(): raise RuntimeError("нет окна подтверждения удаления")
    c.last.click(); pg.wait_for_timeout(3000)


def create_from_template(pg, log):
    """«New agent» → «+» у шаблона Morning brief. Ждём, пока Notion настроит агента (чат настройки просит ввод или есть «Chat with agent»).
    Возвращает (id агента, адрес чата настройки)."""
    before = api_agent_ids()
    goto(pg, "https://app.notion.com/chat")
    pg.get_by_text("New agent", exact=True).first.wait_for(timeout=30000)
    pg.get_by_text("New agent", exact=True).first.click(); pg.wait_for_timeout(4000)
    rows = pg.locator("[role=dialog] [role=button]").filter(has_text="Morning brief").filter(has_text="Pulls updates")
    if rows.count() != 1: raise RuntimeError(f"строка шаблона Morning brief найдена {rows.count()} раз(а)")
    bb = rows.first.bounding_box(); pg.mouse.move(bb["x"] + 100, bb["y"] + bb["height"] / 2); pg.wait_for_timeout(700)
    pg.mouse.click(bb["x"] + bb["width"] - 28, bb["y"] + bb["height"] / 2)
    setup = None
    for _ in range(40):
        pg.wait_for_timeout(1000)
        if session_of(pg.url): setup = pg.url.split("&")[0]; break
    if not setup: raise RuntimeError("чат настройки нового агента не открылся")
    log("Notion настраивает агента…")
    aid = None
    for i in range(100):  # до 5 минут
        pg.wait_for_timeout(3000)
        if not aid:
            new = api_agent_ids() - before
            if len(new) > 1: raise RuntimeError("появилось сразу несколько новых агентов — остановка, ничего не меняю")
            if new: aid = new.pop(); log("агент создан, Notion дописывает настройку…")
        body = pg.evaluate("document.body.innerText")
        if aid and ("Waiting for input" in body or "Chat with agent" in body or "Undo" in body): break
    if not aid: raise RuntimeError("Notion не создал агента за 5 минут")
    if aid in before or aid == main_aid(): raise RuntimeError("найден не новый агент — остановка, ничего не меняю")
    return aid, setup


def last_file():
    """Имя файла «последние сообщения владельца» в папке текущего проекта (denis_last.md на старых установках, owner_last.md на новых)."""
    try:
        for f in sorted(os.listdir(HANDOFF)):
            if f.endswith("_last.md"): return f
    except OSError: pass
    return "owner_last.md"


SSH_WITH_KEY = (
    "- `ssh root@{host}` по ключу `~/.ssh/id_ed25519`. Твой компьютер пересоздаётся между сообщениями, поэтому ключ выдан панелью и лежит здесь, в инструкции. "
    "В начале любого сеанса, где нужен сервер: если файла `~/.ssh/id_ed25519` нет — создай `~/.ssh` (chmod 700), запиши в файл ключ из блока ниже (chmod 600) и входи: "
    "`ssh -o StrictHostKeyChecking=accept-new root@{host}`.\n"
    "- Ключ никому не показывай: не выводи в чат, не отправляй в Telegram, не копируй в файлы на сервере.\n```\n{key}\n```")
SSH_NO_KEY = "- Ключ доступа к серверу тебе не выдан, поэтому доступа к серверу у тебя нет. Владелец может выдать его в окне агента («Новый ключ SSH»)."


def instructions_for(name, chat_name, key=""):
    t = open(INSTR).read()
    if os.path.exists(INSTR_LOCAL): t = t.rstrip("\n") + "\n" + open(INSTR_LOCAL).read()
    import shlex
    cfg = nai_cfg()
    host = server_host() or "адрес сервера"
    section = SSH_WITH_KEY.replace("{host}", host).replace("{key}", key.strip()) if key.strip() else SSH_NO_KEY
    t = t.replace("{ssh_section}", section)  # первым: ключ не должен проходить через остальные подстановки
    for k, v in (("{name}", name), ("{chat}", chat_name), ("{owner}", str(cfg.get("owner") or "владелец")), ("{host}", host),
                 ("{reply_cmd}", "notion-ai-reply --agent " + shlex.quote(name)), ("{last_file}", last_file())):
        t = t.replace(k, v)
    return t


# ---------- задания (отдельный поток, свой браузер на задание) ----------
jobs, job_q, job_cv = {}, [], threading.Condition(threading.Lock())
AUTH_KEYS = "/root/.ssh/authorized_keys"
KEY_MARK = "ccfleet-notion-ai"  # та же метка, что у ключа из ⚙ Настройки → Notion AI: панель видит и умеет убрать


def add_key(pub):
    parts = str(pub or "").split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519": return False, "нужен ключ ssh-ed25519"
    blob = base64.b64decode(parts[1], validate=True); n = int.from_bytes(blob[:4], "big")
    if blob[4:4 + n].decode("latin1") != parts[0] or len(blob) < 40: return False, "ключ повреждён"
    with LOCK:
        cur = open(AUTH_KEYS).read() if os.path.exists(AUTH_KEYS) else ""
        if any(l.split()[:2] == parts[:2] for l in cur.splitlines() if len(l.split()) >= 2): return True, "ключ уже есть"
        with open(AUTH_KEYS, "a") as f: f.write(("" if not cur or cur.endswith("\n") else "\n") + f"{parts[0]} {parts[1]} {KEY_MARK}\n")
        os.chmod(AUTH_KEYS, 0o600)
    return True, "ключ добавлен"


def job_public(j):
    d = {k: j.get(k) for k in ("id", "kind", "status", "stage", "error", "aid", "name", "created", "finished", "result", "warn")}
    d.update(progress_of(j))
    return d


def submit(kind, **kw):
    if kind == "create":
        if not NAME_RE.match(kw.get("name") or ""): raise ValueError("имя агента: 1–80 символов")
        if kw.get("tg_chat_id") and not TG_RE.match(kw["tg_chat_id"]): raise ValueError("Telegram: нужен id чата (например -1001234567890) или @имя_канала")
        if kw.get("ssh") and not server_host(): raise ValueError("не знаю адрес сервера для SSH агента: впиши его в ⚙ Настройки → Notion AI → «Адрес сервера»")
    if kw.get("newkey") and not server_host(): raise ValueError("не знаю адрес сервера для SSH агента: впиши его в ⚙ Настройки → Notion AI → «Адрес сервера»")
    if kw.get("effort") and kw["effort"] not in EFFORTS: raise ValueError("неверный effort")
    if kw.get("model") and not re.fullmatch(r"[\w .,+()-]{1,40}", kw["model"]): raise ValueError("неверная модель")
    if kw.get("name") and not NAME_RE.match(kw["name"]): raise ValueError("имя агента: 1–80 символов")
    with job_cv:
        if sum(1 for x in jobs.values() if x["status"] in ("queued", "running")) >= 5: raise RuntimeError("очередь заданий агентов полна")
        j = dict(kw, id=uuid.uuid4().hex[:8], kind=kind, status="queued", stage="в очереди", created=time.time())
        if kind == "create": j["plan"] = step_plan(bool(kw.get("ssh"))); j["est"] = step_estimates(j["plan"])
        jobs[j["id"]] = j; job_q.append(j["id"]); job_cv.notify()
    return j


def make_log(j):
    def log(s):
        j["stage"] = s; print(f"[agents] {j['id']} {j['kind']}: {s}", flush=True)
        if j["kind"] == "create": step_mark(j, STEP_KEY.get(s))
    return log


def worker():
    from playwright.sync_api import sync_playwright
    while True:
        with job_cv:
            while not job_q: job_cv.wait()
            j = jobs[job_q.pop(0)]
        j["status"] = "running"
        log = make_log(j)
        try:
            with sync_playwright() as p:
                b, ctx, pg = browser(p)
                try: RUN[j["kind"]](pg, j, log)  # state.json не пишем: его ведёт основной поток сервиса
                finally: b.close()
            step_close(j); j["status"] = "done"; log("готово")
            if j["kind"] == "create":
                try: timing_record(j)
                except Exception: traceback.print_exc()
        except Exception as e:
            j["status"] = "error"; j["error"] = f"{type(e).__name__}: {str(e)[:300]}"; traceback.print_exc()
        j["finished"] = time.time()
        with LOCK: _CACHE["ts"] = 0


def run_create(pg, j, log):
    name, model, effort, ssh = j["name"], j.get("model") or "", j.get("effort") or "", bool(j.get("ssh"))
    tg = str(j.get("tg_chat_id") or "")
    list_agents(j.get("main_url", ""), fresh=True)  # главный агент записан в реестр до любых правок
    if not main_aid(): raise RuntimeError("не удалось определить главного агента — создание остановлено")
    log("создаю агента из шаблона «Morning brief»…")
    aid, setup = create_from_template(pg, log)
    j["aid"] = aid; reg_set(aid, state="creating", created=time.time(), setup_chat=setup, name=name, tg_chat_id=tg)
    issued = False
    try:
        log("имя агента…"); api("PATCH", f"/agents/{aid}", {"name": name})
        pub = ""
        if ssh:
            log(CREATE_STEPS[4][1]); pub = issue_key(aid, name); issued = True  # до настройки: приватный ключ уходит в инструкцию тем же сохранением
        log("модель, effort, доступ в интернет, инструкции…")
        st = set_settings(pg, aid, model=model or None, effort=effort or None, web=True, instructions=instructions_for(name, name, agent_key(aid) if ssh else ""))
        reg_set(aid, model_label=st["model"], effort=st["effort"], web=st["web"])
        log("убираю чат настройки…")
        try: delete_chat(pg, setup)
        except Exception as e: log(f"чат настройки не удалён: {e}")
        log("открываю чат агента…")
        sid = new_chat(pg, aid, f"Привет! Ты — агент «{name}» балансера. Это твой рабочий чат. Ничего не делай, ответь одним словом: готов.")
        reg_set(aid, chat_sid=sid)
        wait_reply(sid, 0, 180)
        log("называю чат…"); rename_chat(pg, sid, name)
        ssh_ok = None
        if ssh:
            log(CREATE_STEPS[-1][1])
            ssh_ok, reply = verify_login(pg, sid, aid, pub)
            if not ssh_ok: j["warn"] = "агент создан, но на сервер по ключу не зашёл: " + (reply or "нет ответа")
    except Exception:
        if issued: revoke_key(aid)  # создание оборвалось — выданный ключ не оставляем
        raise
    reg_set(aid, state="ready")
    j["result"] = {"aid": aid, "chat": chat_url(sid), "model": st["model"], "effort": st["effort"], "ssh_ok": ssh_ok}


def run_settings(pg, j, log):
    aid = dash(j["aid"]); name = j.get("name")
    if name:
        log("переименовываю агента…"); a = agent_by(aid, j.get("main_url", "")); old = (a or {}).get("name") or ""
        api("PATCH", f"/agents/{aid}", {"name": name})
        ra = reg_load()["agents"].get(aid, {})
        reg_set(aid, name=name, old_names=sorted(set((ra.get("old_names") or []) + ([old] if old and old != name else []))))  # notion-ai-reply узнаёт агента и по прежнему имени
        sid = session_of(a["chat"]) if a else ""
        if sid and not (a and a.get("main")):  # чат главного агента называется отдельно («Notion AI Балансер»)
            log("переименовываю чат…"); rename_chat(pg, sid, name)
        if a and not a.get("main"): j["instructions"] = True  # команда ответа в Telegram в инструкции содержит имя агента
    if j.get("newkey"):
        a = agent_by(aid, j.get("main_url", ""))
        if not a: raise RuntimeError("агент не найден")
        if a.get("main"): raise RuntimeError("ключ выдаётся агентам, у главного агента свой")
        log("выдаю новый ключ доступа…"); issue_key(aid, a["name"]); j["instructions"] = True
    if j.get("instructions"):
        a = agent_by(aid, j.get("main_url", "")); nm = name or (a or {}).get("name") or ""
        if not nm: raise RuntimeError("агент не найден")
        log("обновляю инструкции агента…"); set_settings(pg, aid, instructions=instructions_for(nm, nm, agent_key(aid)))
    if j.get("newkey"):
        sid = session_of(a["chat"]) if a and a.get("chat") else ""
        if not sid: raise RuntimeError("у агента нет чата для проверки входа")
        log("проверяю вход агента на сервер…")
        ok, reply = verify_login(pg, sid, aid, reg_load()["agents"][aid]["ssh_pub"])
        if not ok: j["warn"] = "ключ выдан, но агент на сервер не зашёл: " + (reply or "нет ответа")
    if j.get("model") or j.get("effort"):
        log("модель и effort в настройках агента…")
        st = set_settings(pg, aid, model=j.get("model") or None, effort=j.get("effort") or None)
        reg_set(aid, model_label=st["model"], effort=st["effort"], web=st["web"])
        j["result"] = st


def run_sync(pg, j, log):
    """Перечитать с сайта модель/effort всех агентов и список моделей."""
    agents = list_agents(j.get("main_url", ""), fresh=True); models = []
    for a in agents:
        log(f"читаю «{a['name']}»…")
        st = read_settings(pg, a["aid"])
        reg_set(a["aid"], model_label=st["model"], effort=st["effort"], web=st["web"])
        if not models: models = models_list(pg)
    with LOCK:
        r = reg_load(); r["models"] = models; r["models_ts"] = time.time(); reg_save(r)
    j["result"] = {"agents": len(agents), "models": len(models)}


def set_tg(aid, cid):
    """Куда агент отвечает в Telegram (пусто — основной чат балансера). Без заданий и без сайта Notion: пишется в реестр."""
    aid = dash(aid); cid = str(cid or "").strip()
    if cid and not TG_RE.match(cid): raise ValueError("Telegram: нужен id чата (например -1001234567890) или @имя_канала")
    if not (reg_load()["agents"].get(aid) or aid == main_aid()): raise ValueError("агент не найден")
    reg_set(aid, tg_chat_id=cid)
    with LOCK: _CACHE["ts"] = 0
    return {"ok": True, "tg": cid, "message": "Сохранено: " + ("отвечает в чат " + cid if cid else "отвечает в основной канал")}


def tg_test(name, cid):
    """Пробное сообщение от бота в указанный чат: сразу видно, что id неверный или бота там нет."""
    import subprocess
    cid = str(cid or "").strip()
    if cid and not TG_RE.match(cid): raise ValueError("Telegram: нужен id чата (например -1001234567890) или @имя_канала")
    cmd = [os.environ.get("CC_NAI_REPLY") or "/usr/local/bin/notion-ai-reply", "--test", "--agent", name or "агент"] + (["--chat", cid] if cid else [])
    try: r = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
    except Exception as e: return {"ok": False, "message": "проверка не запустилась: " + type(e).__name__}
    try: d = json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception: d = {"ok": False, "error": (r.stderr or r.stdout or "нет ответа")[-200:]}
    return {"ok": bool(d.get("ok")), "message": ("Тест отправлен в " + str(d.get("chat") or "чат") + ": проверь, что он пришёл") if d.get("ok") else str(d.get("error") or "не отправлено")[:200]}


KEYS_DIR = f"{D}/agent_keys"


def key_path(aid): return f"{KEYS_DIR}/{dash(aid)}.key"


def agent_key(aid):
    try:
        with open(key_path(aid)) as f: return f.read()
    except OSError: return ""


def gen_keypair():
    import shutil, subprocess, tempfile
    d = tempfile.mkdtemp(prefix="nakey_")
    try:
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "notion-agent", "-f", d + "/k"], check=True, capture_output=True, timeout=30)
        with open(d + "/k") as f: priv = f.read()
        with open(d + "/k.pub") as f: pub = f.read().strip()
        return priv, " ".join(pub.split()[:2])
    finally: shutil.rmtree(d, ignore_errors=True)


def issue_key(aid, name):
    """Новая пара ключей агенту: публичная — в authorized_keys, приватная — в файл (600) для инструкции агента. Прежний ключ агента убирается.
    Компьютер агента в Notion пересоздаётся между сообщениями, поэтому «ключ создаёт сам агент» не живёт: приватный ключ хранится в его инструкции."""
    aid = dash(aid); old = reg_load()["agents"].get(aid, {}).get("ssh_pub")
    priv, pub = gen_keypair()
    ok, msg = add_key(pub)
    if not ok: raise RuntimeError(msg)
    os.makedirs(KEYS_DIR, mode=0o700, exist_ok=True); os.chmod(KEYS_DIR, 0o700)
    fd = os.open(key_path(aid), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: f.write(priv)
    if old and old != pub: del_key(old)
    reg_set(aid, ssh=True, ssh_pub=pub, ssh_ok=None, key_at=time.time())
    return pub


def revoke_key(aid):
    aid = dash(aid); ra = reg_load()["agents"].get(aid, {})
    if ra.get("ssh_pub"): del_key(ra["ssh_pub"])
    try: os.remove(key_path(aid))
    except OSError: pass
    reg_set(aid, ssh=False, ssh_pub="", ssh_ok=None)


LOGIN_ASK = ("Твой ключ доступа к серверу выдан панелью и записан в твоей инструкции (раздел «Доступ к серверу»). Запиши его в ~/.ssh/id_ed25519 (chmod 600) и проверь вход: "
             "`ssh -o StrictHostKeyChecking=accept-new root@{host} hostname`. Ответь одним словом «доступ есть». Не вышло — одной строкой пришли текст ошибки "
             "(ключ не показывай). Больше на сервере ничего не делай.")


def verify_login(pg, sid, aid, pub):
    """Агенту — «запиши ключ и войди»; ждём ответ и проверяем, что он правда вошёл (отпечаток в журнале sshd). → (вошёл, ответ агента)."""
    t0 = time.time(); after = last_seq(sid)
    goto(pg, chat_url(sid)); box = open_chat_input(pg)
    type_send(pg, box, LOGIN_ASK.replace("{host}", server_host()))
    reply = ""
    try: reply = wait_reply(sid, after, 180)
    except RuntimeError as e: reply = str(e)
    seen = False
    for _ in range(6):
        seen = ssh_login_seen(pub, t0 - 5)
        if seen: break
        time.sleep(5)
    reg_set(aid, ssh_ok=seen, ssh_checked=time.time())
    return seen, re.sub(r"\s+", " ", reply)[:200]


def del_key(pub):
    parts = str(pub or "").split()[:2]
    if len(parts) < 2: return False
    with LOCK:
        lines = open(AUTH_KEYS).read().splitlines()
        keep = [l for l in lines if l.split()[:2] != parts]
        if len(keep) == len(lines): return False
        open(AUTH_KEYS, "w").write("\n".join(keep) + "\n"); os.chmod(AUTH_KEYS, 0o600)
    return True


def run_delete(pg, j, log):
    """Удалить агента: его чаты (сайт), агент — в Корзину Notion (API, 30 дней можно вернуть), его SSH-ключ. Главного — нельзя."""
    aid = dash(j["aid"]); a = agent_by(aid, j.get("main_url", ""))
    if not a: raise RuntimeError("агент не найден")
    if a.get("main"): raise RuntimeError("главного агента удалять нельзя")
    q = api("POST", "/sessions/query", {"filter": {"property": "agent_id", "string": {"equals": aid}}, "page_size": 50})
    for x in q.get("results", []):
        log(f"удаляю чат «{x.get('title') or ''}»…")
        try: delete_chat(pg, chat_url(x["id"]))
        except Exception as e: log(f"чат не удалён: {e}")
    ra = reg_load()["agents"].get(aid, {})
    if ra.get("setup_chat"):
        try: delete_chat(pg, ra["setup_chat"])
        except Exception: pass
    log("агент — в Корзину Notion…"); api("DELETE", f"/agents/{aid}")
    if ra.get("ssh_pub") and del_key(ra["ssh_pub"]): log("ключ доступа убран")
    try: os.remove(key_path(aid))
    except OSError: pass
    with LOCK:
        r = reg_load(); r["agents"].pop(aid, None); reg_save(r)
    try:  # если этот агент принимал сообщения из Telegram — вернуть главному
        c = nai_cfg()
        if dash(str(c.get("tg_agent") or "")) == aid:
            c["tg_agent"] = ""
            with open(NAI_CFG, "w") as f: json.dump(c, f, ensure_ascii=False, indent=1)
    except Exception: pass


RUN = {"create": run_create, "settings": run_settings, "sync": run_sync, "delete": run_delete}


def start():
    threading.Thread(target=worker, daemon=True).start()
