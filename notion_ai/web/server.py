#!/usr/bin/env python3
"""Мост «поручить работу агенту Notion»: очередь заданий -> чат «2» (сайт, сессия из state.json) -> готовый ответ.
Двери: HTTP 127.0.0.1:8890 (X-Token) и спул-папка для Codex (exchange/notion/in -> out).
Сервис root, закрытый. Выключатель: файл DISABLED (notion-delegate off). Предохранители: пауза между отправками и лимит в час (limits.json)."""
import os, sys, re, json, time, uuid, threading, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

D = "/root/notion_web"
sys.path.insert(0, D)
import agent_ops as AO
import nagents as NA  # агенты Notion для балансера (07.11.26): список, окно чата, создание и настройки
URL0 = "https://app.notion.com/chat"  # запасной адрес, пока реестр agents.json пуст (новый чат Notion AI)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
PORT = 8893
START = time.time()  # запуск процесса: спул-файлы старше него не обрабатываются
LOG, OFF, JOBS, LIM = f"{D}/sent.log", f"{D}/DISABLED", f"{D}/jobs", f"{D}/limits.json"
TOKEN = open(f"{D}/api_token").read().strip()
MAX_TASK = 30000
# индикатор «агент ещё работает»: пока он на странице, молчание текста не значит конец (02.11.26, 5 неполных ответов)
WORKING = re.compile(r"(?m)^\s*(Working for|Working on your request|Giving this a closer look)")
CRUFT = re.compile(r"^(\d{1,2}:\d{2} [AP]M|Worked for .*|Thought|Opus 5\.5.*|Review for me|Artifacts|Instructions|Ask Notion AI)$")

jobs, order, q = {}, [], []
lock = threading.Lock()
cv = threading.Condition(lock)


def limits():
    d = {"gap": 60, "per_hour": 8, "max_wait": 1200}
    try: d.update(json.load(open(LIM)))
    except Exception: pass
    return d


def sent_times():
    try: return [float(x) for x in open(LOG).read().split()]
    except FileNotFoundError: return []


def disabled(): return os.path.exists(OFF)


PROMPT = """[Задание от Claude Code, отправлено автоматически с сервера по просьбе владельца. Ты исполнитель: вся черновая работа за тобой, я только проверю результат.]
Правила:
1. Выполни задание ЦЕЛИКОМ сам: поиск в интернете и в Notion, чтение, анализ, написание текстов, кода и таблиц, сравнение, самопроверка. Не перекладывай часть работы на меня и не предлагай варианты вместо результата.
2. Вопросов не задавай, если можно разумно предположить. Сделанные предположения перечисли одной строкой в конце.
3. В Notion ничего не создавай и не меняй, если задание прямо этого не просит.
4. Ответ: сначала готовый результат (без вступления и без пересказа задания), затем блок «Проверить:» из 2–5 пунктов только про реальные сомнения.
5. Ключей, паролей и токенов в ответе быть не должно.
6. Самой последней строкой ответа напиши ровно: КОНЕЦ-{id}
ЗАДАНИЕ:
{task}
‹конец задания {id}›"""


def build(task, jid, raw):
    return task if raw else PROMPT.format(id=jid, task=task.strip())


def clean(text, jid):
    i = text.rfind(f"‹конец задания {jid}›")
    if i >= 0: text = text[i + len(f"‹конец задания {jid}›"):]
    text = text.replace(f"КОНЕЦ-{jid}", "")
    lines = [l for l in text.splitlines() if not CRUFT.match(l.strip())]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


class AuthLost(Exception): pass


def body(pg):
    return pg.evaluate("(document.querySelector('main,[role=main]')||document.body).innerText")


def cur_url(): return AO.current_url(URL0)


def open_chat(p, url=None):
    b = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(storage_state=f"{D}/state.json", user_agent=UA, viewport={"width": 1400, "height": 900}, locale="ru-RU", timezone_id="Asia/Irkutsk")
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    pg = ctx.new_page()
    try:
        pg.goto(url or cur_url(), wait_until="domcontentloaded", timeout=45000)
        pg.locator(NAI_INPUT).first.wait_for(timeout=40000); pg.wait_for_timeout(2500)
    except Exception as e:
        lost = "/login" in pg.url or "login" in pg.url.split("?")[0]
        b.close()
        if lost: raise AuthLost("сессия Notion слетела")
        raise
    return b, ctx, pg


def guard(mark=False):
    """Ждёт паузу между отправками; при исчерпанном часовом лимите — исключение. mark=True — ещё и записывает отметку об отправке."""
    L = limits()
    while True:
        if disabled(): raise RuntimeError("выключено (DISABLED)")
        t = time.time(); h = [x for x in sent_times() if t - x < 3600]
        if len(h) >= L["per_hour"]: raise RuntimeError(f"лимит {L['per_hour']} сообщений в час, следующее через {int(3600-(t-h[0]))} с")
        if h and t - h[-1] < L["gap"]: time.sleep(L["gap"] - (t - h[-1]) + 1); continue
        if mark: open(LOG, "w").write("\n".join(str(x) for x in h + [t])); os.chmod(LOG, 0o600)
        return


def run_job(j):
    from playwright.sync_api import sync_playwright
    jid = j["id"]; msg = build(j["task"], jid, j.get("raw"))
    if AUTH["state"] != "ok": raise AuthLost(AUTH_MSG())
    guard()
    with BROWSER, sync_playwright() as p:
        b, ctx, pg = open_chat(p)
        try:
            guard(mark=True)
            b0 = body(pg); before = b0.count(f"КОНЕЦ-{jid}"); err0 = b0.count("Error sending message")
            pg.keyboard.press("Escape"); pg.locator(NAI_INPUT).first.focus(); pg.keyboard.insert_text(msg); pg.wait_for_timeout(600)
            pg.keyboard.press("Enter"); pg.wait_for_timeout(2500)
            if msg[:30] in (pg.locator(NAI_INPUT).first.inner_text() or ""):
                pg.locator("div[role=button]:has(svg)").last.click(timeout=3000)
            j["sent"] = time.time(); t0 = time.time(); last, stable, partial = "", 0, False
            max_wait = limits()["max_wait"]
            while True:
                pg.wait_for_timeout(3000); cur = body(pg)
                if cur.count("Error sending message") > err0: raise RuntimeError("Notion: Error sending message")
                if j.get("raw"):
                    stable = stable + 1 if cur == last else 0
                    if stable >= 8 and cur != b0: break
                elif cur.count(f"КОНЕЦ-{jid}") > before + 1: break
                else:
                    stable = stable + 1 if cur == last else 0
                    if stable >= 30 and len(cur) - len(b0) > 200 and not WORKING.search(cur): partial = "без маркера конца"; break
                last = cur
                if time.time() - t0 > max_wait: partial = True; break
            j["result"] = clean(cur, jid) if not j.get("raw") else cur[-4000:]
            j["partial"] = partial
            ctx.storage_state(path=f"{D}/state.json")
        finally:
            b.close()


def worker():
    while True:
        with cv:
            while not q: cv.wait()
            j = jobs[q.pop(0)]
        j["status"] = "running"; j["started"] = time.time(); save(j)
        try:
            run_job(j); j["status"] = "done"
        except AuthLost as e:
            j["status"] = "error"; j["error"] = f"AuthLost: {e}"; on_auth_lost()
        except Exception as e:
            j["status"] = "error"; j["error"] = f"{type(e).__name__}: {str(e)[:300]}"; traceback.print_exc()
        j["finished"] = time.time(); save(j); spool_out(j)


def save(j):
    os.makedirs(JOBS, mode=0o700, exist_ok=True)
    p = f"{JOBS}/{j['id']}.json"; open(p, "w").write(json.dumps(j, ensure_ascii=False)); os.chmod(p, 0o600)


def submit(task, source, raw=False, name=None):
    task = (task or "").strip()
    if not task: raise ValueError("пустое задание")
    if len(task) > MAX_TASK: raise ValueError(f"задание длиннее {MAX_TASK} символов")
    if disabled(): raise RuntimeError("выключено (DISABLED)")
    jid = uuid.uuid4().hex[:8]
    j = {"id": jid, "task": task, "source": source, "raw": raw, "status": "queued", "created": time.time(), "name": name}
    with cv:
        if len(q) >= 5: raise RuntimeError("очередь полна (5)")
        jobs[jid] = j; order.append(jid); q.append(jid); cv.notify()
    save(j)
    while len(order) > 100: jobs.pop(order.pop(0), None)
    return j


def public(j, full=True):
    d = {k: j.get(k) for k in ("id", "status", "source", "created", "started", "finished", "partial", "error")}
    if full: d["result"] = j.get("result")
    return d


# ---------- вход в Notion: слежение и автоматический повторный вход ----------
BROWSER = threading.Lock()
AUTH = {"state": "ok", "since": 0.0}  # ok | login_wait | lost
LOGINS = D + "/logins.json"  # метки попыток входа: не чаще 3 в сутки (не долбить страницу входа)
alock = threading.Lock()


def AUTH_MSG():
    return {"login_wait": "вход в Notion слетел, идёт повторный вход: нужен код из письма (notion-delegate code КОД)",
            "lost": "вход в Notion слетел и не восстановился, нужен новый вход"}.get(AUTH["state"], "")


NAI_CFG = "/opt/cc-limits/notion_ai.json"  # [notion-ai] общие настройки (⚙ Настройки → Notion AI в панели)


def nai_cfg():
    try:
        with open(NAI_CFG) as f: return json.load(f) or {}
    except Exception: return {}


NAI_NOCHAT = "не задан чат Notion AI (⚙ Общие настройки → Notion AI)"


def nai_url():
    """Адрес постоянного чата из настроек; до появления файла настроек — прежний адрес этого сервера."""
    if not os.path.exists(NAI_CFG): return NAI_URL
    u = str(nai_cfg().get("chat_url") or "")
    return u if re.fullmatch(r"https://(app\.notion\.com|www\.notion\.so|notion\.so)/chat\?t=[0-9a-f]{32}", u) else ""


def nai_email():
    return str(nai_cfg().get("notion_email") or "").strip()


def tg_chat():
    cid = str(nai_cfg().get("tg_chat_id") or "").strip()
    if cid: return cid
    try: return str(json.load(open("/opt/cc-limits/config.json")).get("chat_id") or "")
    except Exception: return ""


def tg(text):
    try:
        import urllib.request, urllib.parse
        tok = ""
        for l in open("/root/.claude/channels/telegram/.env"):
            if l.startswith("TELEGRAM_BOT_TOKEN="): tok = l.split("=", 1)[1].strip()
        data = urllib.parse.urlencode({"chat_id": tg_chat(), "text": text}).encode()
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data), timeout=20).read()
    except Exception as e:
        print("tg:", type(e).__name__, flush=True)


def login_marks():
    try: return [x for x in json.load(open(LOGINS)) if time.time() - x < 86400]
    except Exception: return []


LOGIN = {"busy": False}  # [notion-ai] идёт вход (автоматический или по кнопке из панели)


def on_auth_lost():
    with alock:
        if AUTH["state"] != "ok": return
        if LOGIN["busy"]:  # вход по кнопке уже идёт — он и восстановит сессию
            AUTH.update(state="login_wait", since=time.time()); return
        m = login_marks()
        if len(m) >= 3:
            AUTH.update(state="lost", since=time.time())
            tg("⚠️ Notion: вход слетел, 3 попытки автовхода за сутки уже были. Автовход остановлен, нужна ручная проверка."); return
        AUTH.update(state="login_wait", since=time.time()); LOGIN["busy"] = True
        json.dump(m + [time.time()], open(LOGINS, "w"))
    threading.Thread(target=relogin, daemon=True).start()


def start_login():
    """[notion-ai] Вход по кнопке из панели (⚙ → Notion AI → «Войти в Notion»). Те же 3 попытки в сутки.
    Пока вход идёт, рабочая сессия (если она жива) продолжает отправлять сообщения."""
    if not nai_email(): raise RuntimeError("не задана почта входа (⚙ Общие настройки → Notion AI)")
    with alock:
        if LOGIN["busy"] or AUTH["state"] == "login_wait": raise RuntimeError("вход уже идёт — введи код из письма")
        m = login_marks()
        if len(m) >= 3: raise RuntimeError("за сутки уже было 3 попытки входа — попробуй позже")
        LOGIN["busy"] = True
        if AUTH["state"] != "ok": AUTH.update(state="login_wait", since=time.time())
        json.dump(m + [time.time()], open(LOGINS, "w"))
    threading.Thread(target=relogin, kwargs={"manual": True}, daemon=True).start()


def relogin(manual=False):
    import subprocess
    mail = nai_email()
    if not mail:
        with alock: LOGIN["busy"] = False; AUTH.update(state="lost", since=time.time())
        tg("⚠️ Notion: вход слетел, а почта входа не задана. Укажи её в панели: ⚙ Общие настройки → Notion AI, потом нажми «Войти в Notion»."); return
    tg(("🔑 Notion: вход запущен из панели. Письмо с кодом идёт на %s. Введи код из письма (6 символов) в панели (⚙ Общие настройки → Notion AI) или пришли сообщением. Ждём 12 минут." if manual else
        "⚠️ Notion: вход слетел. Письмо с кодом идёт на %s. Пришли код из письма (6 символов) сообщением (я или Codex введём командой notion-delegate code ...). Ждём 12 минут.") % mail)
    try:
        r = subprocess.run([sys.executable, D + "/login2.py"], capture_output=True, text=True, timeout=900, env={k: v for k, v in os.environ.items() if "proxy" not in k.lower()})
        ok = r.returncode == 0
        open(D + "/login.log", "a").write(time.strftime("%F %T") + " rc=%s\n%s\n" % (r.returncode, (r.stdout or "")[-600:]))
    except Exception as e:
        ok = False; open(D + "/login.log", "a").write(f"{time.strftime('%F %T')} {type(e).__name__}\n")
    with alock:
        LOGIN["busy"] = False
        keep = not ok and manual and AUTH["state"] == "ok"  # ручной вход не удался, а прежняя сессия жива — оставляем её
        if not keep: AUTH.update(state="ok" if ok else "lost", since=time.time())
    if keep:
        tg("ℹ️ Notion: новый вход не завершён (код не пришёл или не принят). Прежний вход работает как раньше."); return
    tg(("✅ Notion: новый вход выполнен, сессия обновлена." if manual else "✅ Notion: вход восстановлен, задания агенту снова работают.") if ok else "⚠️ Notion: войти не удалось (код не пришёл или не принят). Автовход повторит проверку позже; задания агенту пока не идут.")


def put_code(code):
    code = (code or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{6}", code): raise ValueError("нужны ровно 6 символов (буквы или цифры) из письма")
    if AUTH["state"] != "login_wait" and not LOGIN["busy"]: raise RuntimeError("сейчас код входа не ждём")
    fd = os.open(D + "/code.txt", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600); os.write(fd, code.encode()); os.close(fd)


def check_session():
    from playwright.sync_api import sync_playwright
    with BROWSER, sync_playwright() as p:
        b, ctx, pg = open_chat(p, None if AO.ready(AO.reg_load()) else nai_url())  # [notion-ai] нет агентов — проверяем вход на постоянном чате
        try: ctx.storage_state(path=D + "/state.json")
        finally: b.close()


def watchdog():
    time.sleep(600)
    while True:
        try:
            if AUTH["state"] == "ok" and not q and not disabled(): check_session()
            elif AUTH["state"] == "lost" and os.path.exists(D + "/state.json") and time.time() - AUTH["since"] > 7200 and not disabled():
                AUTH["state"] = "ok"; check_session()
        except AuthLost: AUTH["state"] = "ok"; on_auth_lost()
        except Exception as e: print("watchdog:", type(e).__name__, str(e)[:200], flush=True)
        time.sleep(6 * 3600)



# ---------- ротация агентов: до 5 штук, каждый работает сутки (решение , 02.11.26) ----------
ROT_LOCK = threading.Lock()
ROTLOG = D + "/rotation.log"
IRK = 8 * 3600


def irk(ts): return time.strftime("%d.%m %H:%M", time.gmtime(ts + IRK)) if ts else "—"


def rlog(msg):
    try: open(ROTLOG, "a").write(time.strftime("%F %T", time.gmtime(time.time() + IRK)) + " (Иркутск) " + msg + "\n")
    except OSError: pass
    print("rotation:", msg, flush=True)


def rotation_info():
    r = AO.reg_load(); rd = AO.ready(r)
    return {"agents": len(rd), "max": AO.MAX_AGENTS, "current_since": irk(rd[-1]["active_from"]) if rd else "—",
            "next_rotation": "отключена", "fails": r.get("fails", 0), "stopped": True}


def cleanup(pg, a, protect):
    """Убрать агента (чат + корзина). Возвращает список того, что не удалось."""
    bad = []
    try:
        if not AO.delete_chat(pg, a["url"], protect=protect): bad.append("чат не удалился")
    except Exception as e: bad.append("чат: %s %s" % (type(e).__name__, str(e)[:100]))
    if a.get("aid"):
        try:
            if not AO.trash_agent(pg, a["aid"]): bad.append("агент не в корзине")
        except Exception as e: bad.append("агент: %s %s" % (type(e).__name__, str(e)[:100]))
    else: bad.append("id агента неизвестен — убрать вручную")
    return bad


def rotate(force=False):
    """Создать нового агента, проверить его тестовым сообщением, переключить сервис на него; если агентов больше 5 — убрать самого старого."""
    # [notion-ai] 06.11.26: по просьбе владельца пересоздание отключено, в том числе вручную.
    return "пересоздание отключено"
    if not ROT_LOCK.acquire(blocking=False): return "уже идёт"
    try:
        r = AO.reg_load()
        if not AO.ready(r): return "реестр пуст"
        now = time.time()
        if not force and (now < AO.due_at(r) or now < r.get("next_try", 0)): return "рано"
        if disabled(): return "выключено (DISABLED)"
        if AUTH["state"] != "ok": return "нет входа в Notion"
        from playwright.sync_api import sync_playwright
        rlog("начинаю ротацию%s" % (" (принудительно)" if force else ""))
        entry = None; err = None
        try:
            with BROWSER, sync_playwright() as p:
                b, ctx, pg = open_chat(p)
                try:
                    guard(mark=True)
                    def on_url(u):
                        nonlocal entry
                        entry = {"url": u, "aid": None, "created": time.time(), "ready": False}
                        rr = AO.reg_load(); rr["agents"].append(entry); AO.reg_save(rr)
                    url, aid = AO.create(pg, body, on_url)
                    entry["aid"] = aid; r = AO.reg_load()
                    for a in r["agents"]:
                        if a["url"] == url: a["aid"] = aid
                    AO.reg_save(r)
                    rlog("создан %s agent=%s" % (url[-12:], (aid or "?")[:8]))
                    st, res, tail = AO.setup(pg, url, body, lambda: guard(mark=True), AO.TEST_TEXT)
                    if not entry.get("aid"): entry["aid"] = AO.chat_agent_id(pg, [a.get("aid") for a in AO.reg_load()["agents"] if a.get("aid")])
                    if res != "ответ получен": raise RuntimeError("тест нового агента не прошёл: %s; низ чата: %s" % (res, st))
                    r = AO.reg_load(); old_ready = [a for a in r["agents"] if a.get("ready")]
                    for a in r["agents"]:
                        if a["url"] == url: a.update(ready=True, aid=entry.get("aid"), active_from=AO.new_active_from(r, time.time()))
                    r["fails"] = 0; r["next_try"] = 0; AO.reg_save(r); entry["ok"] = True   # с этого момента агент рабочий: аварийная очистка его не тронет
                    rlog("переключился на %s (агентов %d)" % (url[-12:], len(old_ready) + 1))
                    try: ctx.storage_state(path=D + "/state.json")
                    except Exception: pass
                    # убрать лишних: больше 5 — удаляем самого старого (сначала новый уже работает)
                    while True:
                        r = AO.reg_load(); rd = AO.ready(r)
                        if len(rd) <= AO.MAX_AGENTS: break
                        old = rd[0]; keep = tuple(a["url"] for a in rd[1:])
                        bad = cleanup(pg, old, keep)
                        if bad:
                            old.update(ready=False, stale=True, delete_failed="; ".join(bad)); AO.reg_save(r)
                            rlog("не удалось убрать старого агента %s: %s" % (old["url"][-12:], old["delete_failed"]))
                            tg("⚠️ Notion: новый агент работает, но старого убрать не удалось: %s. Ссылка: %s" % (old["delete_failed"], old["url"]))
                            break
                        r["agents"] = [a for a in r["agents"] if a["url"] != old["url"]]; AO.reg_save(r)
                        rlog("убран старый агент %s" % old["url"][-12:])
                finally:
                    b.close()
        except AuthLost as e:
            err = "вход слетел"; on_auth_lost()
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, str(e)[:200]); traceback.print_exc()
        r = AO.reg_load()
        if err:
            r["fails"] = r.get("fails", 0) + 1
            r["next_try"] = time.time() + (3600 * r["fails"] if r["fails"] < 3 else 365 * 86400)
            AO.reg_save(r)
            if entry and not entry.get("ok") and err != "вход слетел" and not any(a["url"] == entry["url"] and a.get("ready") for a in AO.reg_load()["agents"]):
                try:
                    with BROWSER, sync_playwright() as p:
                        b, ctx, pg = open_chat(p)
                        try: bad = cleanup(pg, entry, tuple(a["url"] for a in AO.ready(AO.reg_load())))
                        finally: b.close()
                except Exception as e: bad = ["%s %s" % (type(e).__name__, str(e)[:100])]
                r = AO.reg_load()
                if bad:
                    for a in r["agents"]:
                        if a["url"] == entry["url"]: a.update(broken=err, delete_failed="; ".join(bad))
                    rlog("недоделанный агент %s не убран: %s" % (entry["url"][-12:], "; ".join(bad)))
                    tg("⚠️ Notion: недоделанный агент не убрался сам (%s). Ссылка: %s" % ("; ".join(bad), entry["url"]))
                else:
                    r["agents"] = [a for a in r["agents"] if a["url"] != entry["url"]]; rlog("недоделанный агент убран")
                AO.reg_save(r)
            rlog("ОШИБКА ротации (попытка %d): %s" % (r["fails"], err))
            tg("⚠️ Notion: ротация агента не удалась (попытка %d из 3): %s. Работаю на прежнем агенте.%s" % (r["fails"], err, " Автоповтор остановлен, нужна ваша команда." if r["fails"] >= 3 else " Повтор через %d ч." % r["fails"]))
            return "ошибка: " + err
        tg("🔄 Notion: агент заменён на нового (%d из %d). Следующая замена: %s Иркутск." % (len(AO.ready(r)), AO.MAX_AGENTS, irk(AO.due_at(r))))
        return "готово"
    finally:
        ROT_LOCK.release()


def rotator():
    time.sleep(120)
    while True:
        try: rotate()
        except Exception as e: print("rotator:", type(e).__name__, str(e)[:200], flush=True)
        time.sleep(60)


# ---------- спул-папки для Codex (его песочница без сети: пишет файл в свою рабочую папку) ----------
NAME = re.compile(r"^[0-9a-f]{10}$")


def spool_uid():
    import pwd
    name = os.environ.get("NOTION_SPOOL_USER") or ""
    if not name:
        try: name = str(json.load(open("/opt/cc-limits/config.json")).get("codex_user") or "")
        except (OSError, ValueError): name = ""
    if not name: return None  # пользователь Codex не задан (config.json «codex_user») — спул-папки не нужны
    try: return pwd.getpwnam(name)
    except KeyError: return None  # нет пользователя Codex — спул-папки не нужны


def spool_roots():
    """Папки, откуда берём задания: <рабочая>/.notion-delegate у Codex. Берём известные места, чужие пути не читаем."""
    pw = spool_uid(); roots = {pw.pw_dir + "/exchange", pw.pw_dir + "/work"}
    try:
        st = json.load(open("/opt/cc-limits/codex_bridge.json"))
        for k in ("workdir", "exchange"):
            v = os.path.realpath(st.get(k) or "")
            if v.startswith(pw.pw_dir + "/") and v != pw.pw_dir: roots.add(v)
    except Exception: pass
    em = pw.pw_dir + "/emergency"
    try:
        roots.add(em)
        for n in os.listdir(em):
            if os.path.isdir(os.path.join(em, n)) and not os.path.islink(os.path.join(em, n)): roots.add(os.path.join(em, n))
    except OSError: pass
    return sorted(roots)


def safe_dir(path, uid):
    """Папка настоящая (не ссылка) и принадлежит Codex — иначе её содержимое (ссылки на чужие файлы) мы не трогаем."""
    try:
        st = os.lstat(path)
        import stat
        return stat.S_ISDIR(st.st_mode) and st.st_uid == uid
    except OSError: return False


def spool_read(path, uid):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        import stat
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != uid: raise ValueError("не файл Codex")
        return os.read(fd, MAX_TASK * 4 + 1).decode("utf-8", "replace")
    finally: os.close(fd)


def spool_write(outdir, name, text, uid, gid):
    tmp = os.path.join(outdir, f".{name}.tmp")
    try: os.unlink(tmp)
    except OSError: pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try: os.write(fd, text.encode()); os.fchown(fd, uid, gid)
    finally: os.close(fd)
    os.rename(tmp, os.path.join(outdir, f"{name}.result"))


def spool_out(j):
    if j.get("source") != "spool" or not j.get("outdir"): return
    txt = (j.get("result") or "") if j["status"] == "done" else f"ОШИБКА: {j.get('error')}"
    if j.get("partial"): txt = f"[ОТВЕТ НЕПОЛНЫЙ: {j['partial'] if isinstance(j['partial'], str) else 'время вышло'}]\n" + txt
    try:
        pw = spool_uid(); spool_write(j["outdir"], j["name"], txt, pw.pw_uid, pw.pw_gid)
    except Exception as e: print("spool_out:", type(e).__name__, e, flush=True)


def spool_loop():
    seen = set(); pw = spool_uid()
    while True:
        try:
            for root in spool_roots():
                base = os.path.join(root, ".notion-delegate")
                inn, out = os.path.join(base, "in"), os.path.join(base, "out")
                if not (safe_dir(base, pw.pw_uid) and safe_dir(inn, pw.pw_uid) and safe_dir(out, pw.pw_uid)): continue
                for f in sorted(os.listdir(inn)):
                    m = re.fullmatch(r"([0-9a-f]{10})\.(task|code)", f); path = os.path.join(inn, f)
                    if not m or path in seen: continue
                    seen.add(path); name, kind = m.groups()
                    try:
                        if os.lstat(path).st_mtime < START:  # файл остался с прошлого запуска: повторно в Notion не шлём (дубль), просим повторить
                            os.unlink(path); spool_write(out, name, "ОШИБКА: сервис перезапускался, повтори команду", pw.pw_uid, pw.pw_gid); continue
                        try: text = spool_read(path, pw.pw_uid)
                        finally:
                            try: os.unlink(path)  # прочитанное задание/код не храним (код входа — секрет); unlink не следует по ссылке
                            except OSError: pass
                        if kind == "code":
                            try: put_code(text); res = "код принят, вход продолжается"
                            except (ValueError, RuntimeError) as e: res = f"ОШИБКА: {e}"
                            spool_write(out, name, res, pw.pw_uid, pw.pw_gid)
                        else:
                            j = submit(text, "spool", name=name); j["outdir"] = out
                    except Exception as e:
                        try: spool_write(out, name, f"ОШИБКА: {e}", pw.pw_uid, pw.pw_gid)
                        except Exception: pass
                for f in os.listdir(out):  # уборка старых ответов
                    fp = os.path.join(out, f)
                    try:
                        if time.time() - os.lstat(fp).st_mtime > 86400: os.unlink(fp)
                    except OSError: pass
        except Exception: traceback.print_exc()
        time.sleep(3)



# ── [notion-ai] 05.11.26: сообщения из общего чата Telegram -> постоянный чат Notion AI ──
# Профиль балансера «Notion AI · только он»: мост notion-ai-tg.service кладёт сюда сообщения владельца.
# Только отправка (ответ Notion AI шлёт сам через notion-ai-reply); Escape не жмём — он может прервать ответ.
NAI_URL = "https://app.notion.com/chat?t=40c55b37d45880e9b91600a9c9425683"
# Поле ввода: личный чат Notion AI («Ask Notion AI…») или чат пользовательского агента («Chat with <агент>»), 07.11.26
NAI_INPUT = '[contenteditable=true][placeholder^="Ask Notion AI"], [contenteditable=true][placeholder^="Chat with"]'
posts, post_order, post_q = {}, [], []
post_cv = threading.Condition(threading.Lock())


NAI_MODE = "/opt/cc-limits/notion_ai_mode.json"
NAI_WARM_IDLE = 1200  # [notion-ai] после последней отправки окно чата держится открытым 20 минут
NAI_WARM_AGE = 3600   # раз в час тёплое окно переоткрывается в простое (свежая версия Notion)
NAI_NOANIM = """document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');
 s.textContent='*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}';document.documentElement.appendChild(s)})"""


NAI_MODEL = f"{D}/nai_model.json"  # [notion-ai] модель и effort постоянного чата (читает панель, пишет только post_worker)
NAI_EFFORT_ARIA = {"low": "Low", "medium": "Medium", "high": "High", "extra high": "xHigh", "xhigh": "xHigh", "max": "Max", "maximum": "Max"}
NAI_OTHER = ("Other models", "Другие модели", "Older models", "Старые модели")
NAI_MENU_JS = """(i)=>{const m=[...document.querySelectorAll('[role=menu]')][i];if(!m)return null;
 return [...m.querySelectorAll('[role=menuitem],[role=menuitemradio],[role=option]')].map(e=>({t:(e.innerText||'').split('\\n').map(s=>s.trim()).filter(Boolean),dis:e.getAttribute('aria-disabled')==='true'}))}"""


def nai_model_load():
    try:
        with open(NAI_MODEL) as f: return json.load(f)
    except Exception: return {}


def nai_model_save(st):
    old = nai_model_load()
    if not st.get("models") and old.get("models"): st = dict(st, models=old["models"], models_ts=old.get("models_ts", 0))
    if not st.get("efforts") and old.get("efforts") and st.get("model") == old.get("model"): st = dict(st, efforts=old["efforts"])
    tmp = NAI_MODEL + ".tmp"
    with open(tmp, "w") as f: json.dump(st, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600); os.replace(tmp, NAI_MODEL)


def nai_want_load():
    try:
        with open(os.path.join(D, 'nai_want.json'), 'r', encoding='utf-8') as file:
            data = json.load(file)
        model = data.get('model', '')
        effort = data.get('effort', '')
        if not isinstance(model, str) or not isinstance(effort, str):
            raise ValueError('invalid values')
        return {'model': model, 'effort': effort}
    except Exception:
        return {'model': '', 'effort': ''}


def nai_want_save(model, effort):
    import tempfile
    if not isinstance(model, str) or not isinstance(effort, str):
        raise ValueError('model and effort must be strings')
    want = nai_want_load()
    if model and model != want['model']:
        want['model'] = model
        if not effort:
            want['effort'] = ''
    if effort:
        want['effort'] = effort
    want['ts'] = time.time()
    fd, temp = tempfile.mkstemp(prefix='nai_want-', suffix='.tmp', dir=D)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            os.chmod(temp, 0o600)
            json.dump(want, file, ensure_ascii=False)
        os.replace(temp, os.path.join(D, 'nai_want.json'))
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def nai_parse(item):
    """Пункт меню модели: «Opus / 5.5 / Beta» → подпись «Opus 5.5» (как на кнопке в поле ввода), описание, пометки."""
    t = list(item.get("t") or []); name = t[0] if t else ""; ver = ""; rest = t[1:]
    if rest and not (rest[0].endswith(".") or len(rest[0]) > 24 or rest[0] in ("Beta", "New", "Uses Notion credits")):
        ver = rest.pop(0)
    desc = next((x for x in rest if x.endswith(".")), "")
    tags = [x for x in rest if x != desc][:3]
    return {"label": (name + " " + ver).strip(), "name": name, "version": ver, "desc": desc[:120], "tags": tags, "disabled": bool(item.get("dis"))}


def nai_profile_on():
    try:
        with open(NAI_MODE) as f: return bool(json.load(f).get("active"))
    except Exception: return False


class NaiWarm:
    """[notion-ai] Тёплое окно постоянного чата: сообщение уходит без запуска браузера (~2 с вместо ~20 с).
    Окно открыто, пока включён профиль Notion AI, и ещё 20 минут после последней отправки.
    Без анимаций и картинок — чтобы не грузить процессор. Используется только из потока post_worker."""
    def __init__(self): self.p = self.b = self.ctx = self.pg = None; self.opened = self.last = self.fail_until = 0; self.url = ""

    def alive(self):
        try: return self.pg is not None and not self.pg.is_closed() and "login" not in self.pg.url
        except Exception: return False

    def open(self, url=None):
        from playwright.sync_api import sync_playwright
        self.close()
        if AUTH["state"] != "ok": raise AuthLost(AUTH_MSG())
        if disabled(): raise RuntimeError("выключено (DISABLED)")
        t0 = time.time()
        with BROWSER:
            self.p = sync_playwright().start()
            try:
                self.b = self.p.chromium.launch(args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--disable-gpu",
                                                      "--blink-settings=imagesEnabled=false", "--mute-audio"])
                self.ctx = self.b.new_context(storage_state=f"{D}/state.json", user_agent=UA, viewport={"width": 1100, "height": 800},
                                              locale="ru-RU", timezone_id="Asia/Irkutsk", reduced_motion="reduce")
                self.ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
                self.ctx.add_init_script(NAI_NOANIM)
                self.pg = self.ctx.new_page()
                self.url = url or nai_url()  # чат агента из балансера или главный чат из настроек
                if not self.url: raise RuntimeError(NAI_NOCHAT)
                self.pg.goto(self.url, wait_until="domcontentloaded", timeout=45000)
                try:
                    self.pg.locator(NAI_INPUT).first.wait_for(timeout=40000)
                except Exception:
                    if "login" in self.pg.url: raise AuthLost("сессия Notion слетела")
                    raise
                self.pg.wait_for_timeout(1500)
            except Exception:
                self.close(); raise
        self.opened = time.time()
        try: nai_model_save(self.model_state(self.pg, False))  # [notion-ai] подпись модели для карточки панели
        except Exception as e: print(f"[notion-ai] модель не прочитана: {type(e).__name__}", flush=True)
        if self.url == nai_url(): self.reapply_want()  # [notion-ai] выбранная человеком модель слетает на Auto при каждом новом открытии страницы
        print(f"[notion-ai] тёплое окно чата открыто за {self.opened - t0:.1f} с", flush=True)

    def reapply_want(self):
        def report(exc):
            text = ' '.join(str(exc).split())[:120]
            print('[notion-ai] возврат модели не удался: ' + type(exc).__name__ + ': ' + text, flush=True)
        changed = False
        completed = False
        try:
            want = nai_want_load()
            if not want['model'] and not want['effort']:
                return
            st = self.model_state(self.pg, False)
            if want['model'] and want['model'] != st['model']:
                self._pick_model(self.pg, want['model'])
                changed = True
                st = self.model_state(self.pg, False)
            if want['effort'] and st['effort'] and want['effort'] != st['effort']:
                self._pick_effort(self.pg, want['effort'])
                changed = True
            completed = True
        except Exception as exc:
            report(exc)
        finally:
            try:
                st = self.model_state(self.pg, False)
                nai_model_save(st)
                if completed and changed:
                    print('[notion-ai] модель возвращена: ' + st['model'], flush=True)
            except Exception as exc:
                report(exc)

    def close(self):
        if self.p is None: return
        try: self.b and self.b.close()
        except Exception: pass
        try: self.p.stop()
        except Exception: pass
        self.p = self.b = self.ctx = self.pg = None
        print("[notion-ai] тёплое окно чата закрыто", flush=True)

    def post(self, pj):
        if AUTH["state"] != "ok": raise AuthLost(AUTH_MSG())
        if disabled(): raise RuntimeError("выключено (DISABLED)")
        target = pj.get("url") or nai_url()
        if not self.alive() or self.url != target: self.open(target)
        pg = self.pg; box = pg.locator(NAI_INPUT).first
        try: box.wait_for(timeout=4000)
        except Exception:
            self.open(target); pg = self.pg; box = pg.locator(NAI_INPUT).first
        text = pj["text"]; head = (text.strip().splitlines() or [""])[0][:30]
        box.click(timeout=5000); pg.keyboard.press("Control+A"); pg.keyboard.press("Delete")
        pg.keyboard.insert_text(text); pg.wait_for_timeout(400)
        sent = False
        for _ in range(8):
            pg.keyboard.press("Enter")
            for _ in range(10):
                pg.wait_for_timeout(300)
                if head not in (box.inner_text() or ""): sent = True; break
            if sent: break
            pg.wait_for_timeout(5000)
        if not sent: raise RuntimeError("сообщение не ушло: поле ввода не очистилось")
        pj["posted"] = self.last = time.time()
        try:
            with BROWSER: self.ctx.storage_state(path=f"{D}/state.json")
        except Exception: pass

    # ---------- [notion-ai] модель и effort ----------
    def _menus_close(self, pg):
        for _ in range(3):  # Escape — только пока открыто меню (лишний Escape полю ввода не нужен)
            if pg.locator('[role=menu]').count() == 0: return
            pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

    def _open_menu(self, pg, loc):
        loc.click(timeout=5000); pg.locator('[role=menu]').first.wait_for(timeout=6000); pg.wait_for_timeout(400)

    def _other(self, pg):
        o = pg.locator('[role=menu] [role=menuitem]').filter(has_text=NAI_OTHER[0])
        if not o.count(): o = pg.locator('[role=menu] [role=menuitem]').filter(has_text=NAI_OTHER[1])
        if not o.count(): return False
        o.first.hover(); pg.wait_for_timeout(1200); return pg.locator('[role=menu]').count() > 1

    def model_state(self, pg, deep=True):
        lab = pg.locator('[aria-label="Choose AI model"]').first; lab.wait_for(timeout=8000)
        out = {"model": (lab.inner_text() or "").strip(), "effort": "", "ts": time.time()}
        eb = pg.locator('[aria-label^="Change effort"]')
        if eb.count():
            cur = (eb.first.get_attribute("aria-label") or "").lower().split("currently", 1)[-1].strip(" ,.")
            out["effort"] = NAI_EFFORT_ARIA.get(cur, cur)
        if not deep: return out
        try:
            self._open_menu(pg, lab)
            items = [x for x in (pg.evaluate(NAI_MENU_JS, 0) or []) if x.get("t")]
            models = [nai_parse(x) for x in items if x["t"][0] not in NAI_OTHER]
            if any(x["t"][0] in NAI_OTHER for x in items) and self._other(pg):
                models += [dict(nai_parse(x), more=True) for x in (pg.evaluate(NAI_MENU_JS, 1) or []) if x.get("t") and x["t"][0] not in NAI_OTHER]
            out["models"] = models; out["models_ts"] = time.time()
        finally: self._menus_close(pg)
        if eb.count():
            try:
                self._open_menu(pg, eb.first)
                out["efforts"] = [x["t"][0] for x in (pg.evaluate(NAI_MENU_JS, 0) or []) if x.get("t") and not x.get("dis")]
            finally: self._menus_close(pg)
        else: out["efforts"] = []
        return out

    def _pick_model(self, pg, model):
        self._open_menu(pg, pg.locator('[aria-label="Choose AI model"]').first)
        try:
            for i in (0, 1):
                items = pg.evaluate(NAI_MENU_JS, i) or []
                for k, x in enumerate(items):
                    if x.get("t") and nai_parse(x)["label"] == model:
                        if x.get("dis"): raise RuntimeError(f"модель «{model}» сейчас недоступна в Notion (нужны кредиты Notion)")
                        pg.locator('[role=menu]').nth(i).locator('[role=menuitem],[role=menuitemradio],[role=option]').nth(k).click(timeout=5000)
                        pg.wait_for_timeout(1500); return
                if i == 0 and not self._other(pg): break
            raise RuntimeError(f"модели «{model}» нет в списке Notion")
        finally: self._menus_close(pg)

    def _pick_effort(self, pg, effort):
        eb = pg.locator('[aria-label^="Change effort"]')
        if not eb.count(): raise RuntimeError("для этой модели Notion не даёт выбрать effort")
        self._open_menu(pg, eb.first)
        try:
            items = pg.evaluate(NAI_MENU_JS, 0) or []
            k = next((k for k, x in enumerate(items) if x.get("t") and x["t"][0] == effort and not x.get("dis")), None)
            if k is None: raise RuntimeError(f"уровня «{effort}» нет для этой модели")
            pg.locator('[role=menu]').first.locator('[role=menuitem],[role=menuitemradio],[role=option]').nth(k).click(timeout=5000)
            pg.wait_for_timeout(1000)
        finally: self._menus_close(pg)

    def model_job(self, pj):
        """Прочитать (или выставить) модель и effort в поле ввода постоянного чата. Сообщений не пишет."""
        if AUTH["state"] != "ok": raise AuthLost(AUTH_MSG())
        if disabled(): raise RuntimeError("выключено (DISABLED)")
        if not self.alive() or self.url != nai_url(): self.open()
        pg = self.pg; model, effort = pj.get("model") or "", pj.get("effort") or ""
        try:
            if model and model != self.model_state(pg, False)["model"]: self._pick_model(pg, model)
            if effort and effort != self.model_state(pg, False)["effort"]: self._pick_effort(pg, effort)
        finally:
            st = self.model_state(pg, True); nai_model_save(st); pj["result"] = st
        if model and st["model"] != model: raise RuntimeError(f"Notion оставил модель «{st['model']}»")
        if effort and st["effort"] != effort: raise RuntimeError(f"Notion оставил effort «{st['effort']}»")
        if model or effort:
            try: nai_want_save(model, effort)
            except Exception as e: print(f"[notion-ai] выбор модели не запомнен: {type(e).__name__}", flush=True)
            try:
                with BROWSER: self.ctx.storage_state(path=f"{D}/state.json")
            except Exception: pass

    def idle(self):
        """Простой: держать окно открытым, пока включён профиль Notion AI; иначе закрыть через 20 минут."""
        now = time.time()
        want = nai_profile_on() and AUTH["state"] == "ok" and not disabled() and bool(nai_url())
        if self.p is not None and not want and now - self.last > NAI_WARM_IDLE:
            self.close()
        elif self.p is not None and self.url != nai_url() and now >= self.fail_until:
            self.close()  # [notion-ai] в настройках сменили чат — откроем новый при следующем проходе
        elif want and now >= self.fail_until and (not self.alive() or now - self.opened > NAI_WARM_AGE):
            try: self.open()
            except AuthLost: self.close(); on_auth_lost(); self.fail_until = now + 300
            except Exception as e:
                self.close(); self.fail_until = now + 120; print(f"[notion-ai] тёплое окно не открылось: {type(e).__name__}: {str(e)[:200]}", flush=True)


def post_worker():
    warm = NaiWarm()
    while True:
        pid = None
        with post_cv:
            if not post_q: post_cv.wait(timeout=20)
            if post_q: pid = post_q.pop(0)
        if pid is None:
            warm.idle(); continue
        pj = posts[pid]
        pj["status"] = "running"; pj["started"] = time.time()
        run = warm.model_job if pj.get("kind") == "model" else warm.post  # [notion-ai] модель/effort — та же очередь и то же окно
        try:
            try:
                run(pj)
            except AuthLost:
                raise
            except Exception as e:  # окно могло устареть — одна повторная попытка в свежем окне
                if pj.get("posted") or pj.get("result"): raise
                print(f"[notion-ai] повтор в свежем окне: {type(e).__name__}: {str(e)[:200]}", flush=True)
                warm.close(); run(pj)
            pj["status"] = "done"
        except AuthLost as e:
            warm.close(); pj["status"] = "error"; pj["error"] = f"AuthLost: {e}"; on_auth_lost()
        except Exception as e:
            pj["status"] = "error"; pj["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            if pj.get("result"): print(f"[notion-ai] модель: {str(e)[:200]}", flush=True)  # окно исправно — Notion просто не дал выбрать
            else: warm.close(); traceback.print_exc()
        pj["finished"] = time.time()


def submit_post(text, url=None):
    text = (text or "").strip()
    if not text: raise ValueError("пустое сообщение")
    if len(text) > MAX_TASK: raise ValueError(f"сообщение длиннее {MAX_TASK} символов")
    if disabled(): raise RuntimeError("выключено (DISABLED)")
    if not nai_url(): raise RuntimeError(NAI_NOCHAT)
    pj = {"id": uuid.uuid4().hex[:8], "text": text, "status": "queued", "created": time.time()}
    if url: pj["url"] = url
    with post_cv:
        if len(post_q) >= 20: raise RuntimeError("очередь сообщений полна (20)")
        posts[pj["id"]] = pj; post_order.append(pj["id"]); post_q.append(pj["id"]); post_cv.notify()
        while len(post_order) > 200: posts.pop(post_order.pop(0), None)
    return pj


def submit_model(d):
    """[notion-ai] Задание «модель/effort»: пустое = только прочитать список. Повторное чтение не ставится в очередь дважды."""
    model, effort = str(d.get("model") or "").strip(), str(d.get("effort") or "").strip()
    if len(model) > 60 or len(effort) > 20 or not re.fullmatch(r"[\w .,+()-]*", model + effort): raise ValueError("неверная модель или effort")
    if disabled(): raise RuntimeError("выключено (DISABLED)")
    if not nai_url(): raise RuntimeError(NAI_NOCHAT)
    with post_cv:
        for pid in reversed(post_order):
            x = posts.get(pid) or {}
            if x.get("kind") == "model" and x.get("status") in ("queued", "running") and not (model or effort) and not (x.get("model") or x.get("effort")):
                return x
        pj = {"id": uuid.uuid4().hex[:8], "kind": "model", "model": model, "effort": effort, "status": "queued", "created": time.time()}
        if len(post_q) >= 20: raise RuntimeError("очередь сообщений полна (20)")
        posts[pj["id"]] = pj; post_order.append(pj["id"]); post_q.append(pj["id"]); post_cv.notify()
        while len(post_order) > 200: posts.pop(post_order.pop(0), None)
    return pj


def post_public(pj):
    out = {k: pj.get(k) for k in ("id", "status", "error", "created", "started", "posted", "finished")}
    if pj.get("kind") == "model": out["kind"] = "model"; out["result"] = pj.get("result")
    return out


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
    def _auth(self): return self.headers.get("X-Token") == TOKEN
    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True, "disabled": disabled(), "auth": AUTH["state"], "queue": len(q), "sent_last_hour": len([x for x in sent_times() if time.time() - x < 3600]), "limits": limits(), "rotation": rotation_info(), "chat": nai_url(), "logins_24h": len(login_marks()), "login_busy": LOGIN["busy"]})
        if not self._auth(): return self._send(403, {"error": "token"})
        m = re.fullmatch(r"/job/([0-9a-f]{8})", self.path)
        if m and m.group(1) in jobs: return self._send(200, public(jobs[m.group(1)]))
        if self.path == "/nai/model":  # [notion-ai] модель и effort постоянного чата (последнее прочитанное)
            pend = next((pid for pid in reversed(post_order) if (posts.get(pid) or {}).get("kind") == "model" and posts[pid].get("status") in ("queued", "running")), None)
            return self._send(200, {"ok": True, "state": nai_model_load(), "pending": pend})
        if self.path == "/agents":  # список агентов (API Notion, только чтение) + модели из настроек + идущие задания
            try:
                r = NA.reg_load()
                return self._send(200, {"ok": True, "agents": NA.list_agents(nai_url()), "models": r.get("models") or [], "models_ts": r.get("models_ts", 0),
                                        "efforts": NA.EFFORTS, "jobs": [NA.job_public(j) for j in NA.jobs.values() if j["status"] in ("queued", "running") or time.time() - (j.get("finished") or 0) < 120]})
            except Exception as e: return self._send(200, {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"})
        m = re.fullmatch(r"/agents/view/([0-9a-f-]{32,36})", self.path)
        if m:
            try: return self._send(200, NA.view(m.group(1), nai_url()))
            except Exception as e: return self._send(200, {"ok": False, "state": "error", "message": f"{type(e).__name__}: {str(e)[:200]}", "rows": []})
        m = re.fullmatch(r"/agents/job/([0-9a-f]{8})", self.path)
        if m and m.group(1) in NA.jobs: return self._send(200, NA.job_public(NA.jobs[m.group(1)]))
        m = re.fullmatch(r"/post/([0-9a-f]{8})", self.path)  # [notion-ai]
        if m and m.group(1) in posts: return self._send(200, post_public(posts[m.group(1)]))
        self._send(404, {"error": "not found"})
    def do_POST(self):
        if not self._auth(): return self._send(403, {"error": "token"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_TASK * 4: return self._send(413, {"error": "large"})
        try: d = json.loads(self.rfile.read(n) or b"{}")
        except Exception: return self._send(400, {"error": "json"})
        if self.path == "/delegate":
            try: return self._send(200, public(submit(d.get("task"), d.get("source") or "http", raw=bool(d.get("raw"))), full=False))
            except (ValueError, RuntimeError) as e: return self._send(400, {"error": str(e)})
        if self.path == "/post":  # [notion-ai] только отправить в постоянный чат Notion AI
            try:
                url = None
                if d.get("aid"):  # сообщение агенту из балансера — в его чат, тоже через сайт
                    a = NA.agent_by(str(d["aid"]), nai_url())
                    if not a or not a.get("chat"): raise ValueError("у агента нет чата")
                    url = None if a.get("main") else a["chat"]
                return self._send(200, post_public(submit_post(d.get("text"), url)))
            except (ValueError, RuntimeError) as e: return self._send(400, {"error": str(e)})
        if self.path == "/nai/model":  # [notion-ai] выбрать модель/effort ({} — перечитать список)
            try: return self._send(200, post_public(submit_model(d)))
            except (ValueError, RuntimeError) as e: return self._send(400, {"error": str(e)})
        if self.path == "/agents/tg":  # куда агент отвечает в Telegram (без заданий: только реестр)
            try: return self._send(200, NA.set_tg(str(d.get("aid") or ""), d.get("tg_chat_id")))
            except ValueError as e: return self._send(400, {"error": str(e)})
        if self.path == "/agents/tgtest":  # пробное сообщение от бота в этот чат
            try: return self._send(200, NA.tg_test(str(d.get("name") or ""), d.get("tg_chat_id")))
            except ValueError as e: return self._send(400, {"error": str(e)})
        if self.path in ("/agents/create", "/agents/settings", "/agents/sync", "/agents/delete"):
            if AUTH["state"] != "ok": return self._send(400, {"error": AUTH_MSG()})
            try:
                kind = self.path.rsplit("/", 1)[1]
                kw = {k: str(d.get(k) or "").strip() for k in ("name", "model", "effort", "aid")}
                kw = {k: v for k, v in kw.items() if v}
                if kind == "create": kw.pop("aid", None); kw["ssh"] = bool(d.get("ssh")); kw["tg_chat_id"] = str(d.get("tg_chat_id") or "").strip()
                if kind == "settings" and d.get("instructions"): kw["instructions"] = True
                if kind == "settings" and d.get("newkey"): kw["newkey"] = True
                if kind in ("settings", "delete") and not kw.get("aid"): raise ValueError("нет агента")
                return self._send(200, NA.job_public(NA.submit(kind, main_url=nai_url(), **kw)))
            except (ValueError, RuntimeError) as e: return self._send(400, {"error": str(e)})
        if self.path == "/relogin":  # [notion-ai] кнопка «Войти в Notion» в панели
            try: start_login(); return self._send(200, {"ok": True, "email": nai_email()})
            except (ValueError, RuntimeError) as e: return self._send(400, {"error": str(e)})
        if self.path == "/code":
            try: put_code(d.get("code")); return self._send(200, {"ok": True})
            except (ValueError, RuntimeError) as e: return self._send(400, {"error": str(e)})
        if self.path == "/rotate":
            return self._send(410, {"error": "пересоздание агентов отключено"})
        if self.path in ("/off", "/on"):
            if self.path == "/off": open(OFF, "w").write("1")
            elif disabled(): os.remove(OFF)
            return self._send(200, {"disabled": disabled()})
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    if not os.path.exists(D + "/state.json"): AUTH.update(state="lost", since=time.time())  # [notion-ai] новая установка: входа ещё не было
    pw = spool_uid()
    if pw:
        for sub in ("", "/in", "/out"):
            spool = pw.pw_dir + "/exchange/.notion-delegate"
            os.makedirs(spool + sub, exist_ok=True); os.chown(spool + sub, pw.pw_uid, pw.pw_gid)
        threading.Thread(target=spool_loop, daemon=True).start()
    threading.Thread(target=worker, daemon=True).start(); threading.Thread(target=watchdog, daemon=True).start(); threading.Thread(target=post_worker, daemon=True).start()
    NA.start()
    print("notion-delegate: слушаю 127.0.0.1:%d" % PORT, flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
