"""Операции с агентами Notion и реестр ротации (agents.json). Импортируется сервисом notion-delegate и new_agent.py.
Схема (решение , 01.11.26): до 5 агентов, каждый работает сутки; когда набралось 5 — при ротации создаём нового
и только потом удаляем самого старого. Удаляются только агенты из этого реестра (созданные нами)."""
import os, re, json, time

D = "/root/notion_web"
REG = f"{D}/agents.json"
MAX_AGENTS = 5
DAY = 86400
MIN_GAP = 20 * 3600       # жёсткий минимум между созданиями (кроме ручного --force)
LATE_MAX = 6 * 3600       # если ротация опоздала больше, чем на это, сутки считаем от фактического переключения
TEST_TEXT = "Проверка связи. Ответь одним словом: «готов». Ничего не создавай и не меняй."


# ---------- реестр ----------
# Поле ввода: личный чат Notion AI («Ask Notion AI…») или чат пользовательского агента («Chat with <агент>»)
INPUT = '[contenteditable=true][placeholder^="Ask Notion AI"], [contenteditable=true][placeholder^="Chat with"]'

def reg_load():
    try: return json.load(open(REG))
    except (FileNotFoundError, ValueError): return {"agents": [], "stop": None, "fails": 0, "next_try": 0}


def reg_save(r):
    tmp = REG + ".tmp"
    with open(tmp, "w") as f: json.dump(r, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600); os.replace(tmp, REG)


def ready(r): return [a for a in r.get("agents", []) if a.get("ready")]


def current_url(default, r=None):
    a = ready(r or reg_load())
    return a[-1]["url"] if a else default


def due_at(r):
    a = ready(r)
    return a[-1]["active_from"] + DAY if a else None


def new_active_from(r, now=None):
    now = now or time.time(); due = due_at(r)
    return due if due and 0 <= now - due < LATE_MAX else now


# ---------- работа со страницей ----------
def find_chat_url(pg):
    m = re.search(r"[?&]t=([0-9a-f]{32})", pg.url)
    return f"https://app.notion.com/chat?t={m.group(1)}" if m else None


def agent_ids(pg):
    """id агентов, ссылки на которых лежат в странице (боковая панель)."""
    return set(pg.evaluate("[...document.documentElement.outerHTML.matchAll(/\\/agent\\/([0-9a-f]{32})/g)].map(m=>m[1])"))


def chat_agent_id(pg, known=()):
    """id агента по ссылке «@Morning brief» в открытом чате настройки (кроме уже известных)."""
    ids = set(pg.evaluate("[...document.querySelectorAll('a[href*=\"/agent/\"]')].map(a=>(a.getAttribute('href').match(/\\/agent\\/([0-9a-f]{32})/)||[])[1]).filter(Boolean)")) - set(known)
    return next(iter(ids)) if len(ids) == 1 else None


def probe(pg, body):
    """Сухая проверка пути создания: открыть окно «New agent», убедиться, что шаблон на месте, закрыть. Ничего не создаёт."""
    pg.get_by_text("New agent", exact=True).first.click(); pg.wait_for_timeout(4000)
    try: bb = _template_row(pg).bounding_box()
    finally: pg.keyboard.press("Escape"); pg.wait_for_timeout(1000)
    return f"окно «Create a new agent» открылось, строка Morning brief найдена (x={bb['x']:.0f}, y={bb['y']:.0f}, w={bb['width']:.0f}), закрыл Escape; агентов в панели: {len(agent_ids(pg))}"


def _template_row(pg):
    rows = pg.locator("[role=dialog] [role=button]").filter(has_text="Morning brief").filter(has_text="Pulls updates")
    if rows.count() != 1: raise RuntimeError(f"строка шаблона Morning brief найдена {rows.count()} раз(а)")
    return rows.first


def create(pg, body, on_url=None):
    """«New agent» → «+» в строке Morning brief → Notion открывает чат настройки (?t=…) и ~40 с настраивает агента.
    Возвращает (url чата, id агента или None). Нового чата ждём по смене адреса — не путать с чатом, с которого начали."""
    prev = find_chat_url(pg)
    pg.wait_for_timeout(2000); before = agent_ids(pg)
    pg.get_by_text("New agent", exact=True).first.click(); pg.wait_for_timeout(4000)
    row = _template_row(pg); bb = row.bounding_box()
    pg.mouse.move(bb["x"] + 100, bb["y"] + bb["height"] / 2); pg.wait_for_timeout(700)
    pg.mouse.click(bb["x"] + bb["width"] - 28, bb["y"] + bb["height"] / 2)      # «+» в правом краю строки
    url = None
    for _ in range(40):                                  # ждём переход в новый чат настройки
        pg.wait_for_timeout(1000)
        u = find_chat_url(pg)
        if u and u != prev: url = u; break
    if not url: raise RuntimeError("чат нового агента не открылся (клик по «+» не сработал или Notion не ответил)")
    if on_url: on_url(url)                               # записать в реестр сразу: при обрыве агент не потеряется
    for _ in range(120):                                 # настройка агента: 40 с … 2 мин
        pg.wait_for_timeout(2000)
        if "Undo" in body(pg): break
    else: raise RuntimeError("Notion не закончил настройку агента за 240 с")
    pg.wait_for_timeout(2000)
    return url, chat_agent_id(pg, before)


def setup(pg, url, body, guard, text=None):
    """В чате url выставить Opus 5.5 + Effort xHigh; при заданном тексте — отправить его (guard() вызывается перед отправкой)
    и ждать ответа «готов». Возвращает (низ чата после выбора, итог: None | «ответ получен» | «нет ответа» | «ОШИБКА ОТПРАВКИ», хвост чата)."""
    pg.goto(url, wait_until="domcontentloaded", timeout=45000)
    pg.locator(INPUT).first.wait_for(timeout=40000); pg.wait_for_timeout(3000)
    if pg.get_by_text("Opus 5.5", exact=True).count() == 0:
        lab = pg.get_by_text("Auto", exact=True).last; lab.click(); pg.wait_for_timeout(1500)
        pg.get_by_text("Opus", exact=False).first.click(); pg.wait_for_timeout(2000)
    lab = pg.get_by_text("Opus 5.5", exact=True).last; bb = lab.bounding_box()
    if not bb: raise RuntimeError("подпись «Opus 5.5» не появилась после выбора модели")
    pg.mouse.click(bb["x"] - 30, bb["y"] + bb["height"] / 2); pg.wait_for_timeout(1500)   # иконка Effort
    pg.get_by_text("xHigh", exact=True).first.click(); pg.wait_for_timeout(1500)
    state = body(pg)[-60:].replace("\n", " | ")
    if not text: return state, None, None
    guard()
    b0 = body(pg); n0 = b0.lower().count("готов"); e0 = b0.count("Error sending message")
    box = pg.locator(INPUT).first; box.focus(); pg.keyboard.insert_text(text); pg.wait_for_timeout(500)
    pg.keyboard.press("Enter")
    t0 = time.time(); cur = b0
    while time.time() - t0 < 240:
        pg.wait_for_timeout(2500); cur = body(pg)
        if cur.count("Error sending message") > e0: return state, "ОШИБКА ОТПРАВКИ", cur[-700:]
        if cur.lower().count("готов") >= n0 + 2: return state, "ответ получен", cur[-700:]   # слово есть в вопросе и в ответе
    return state, "нет ответа", cur[-700:]


# ---------- удаление (только то, что создали мы и что записано в реестре) ----------
def _click_menu_item(pg, title):
    m = pg.locator("[role=menu]")
    m.first.wait_for(timeout=8000)
    it = m.get_by_text(title, exact=True)
    if it.count() != 1: raise RuntimeError(f"в меню пункт «{title}» найден {it.count()} раз(а)")
    it.first.click()


def _confirm_if_any(pg, title):
    pg.wait_for_timeout(1500)
    c = pg.locator("[role=dialog], [role=alertdialog]").get_by_text(title, exact=True)
    if c.count(): c.last.click(); return True
    return False


def delete_chat(pg, url, protect=()):
    """Открыть чат url и удалить его через «⋯» → Delete (меню действует на открытый чат, названия у чатов одинаковые).
    Возвращает True, если после удаления Notion пишет «You don’t have access to this chat»."""
    if url in protect: raise RuntimeError("отказ: это рабочий чат")
    pg.goto(url, wait_until="domcontentloaded", timeout=45000)
    pg.locator(INPUT).first.wait_for(timeout=40000); pg.wait_for_timeout(2500)
    if find_chat_url(pg) != url: raise RuntimeError("открылся не тот чат: " + pg.url[:90])
    pg.mouse.click(1375, 22)                                  # «⋯» справа сверху
    _click_menu_item(pg, "Delete")
    if not _confirm_if_any(pg, "Confirm"): raise RuntimeError("окно подтверждения удаления («Confirm») не появилось")
    pg.wait_for_timeout(3500)
    pg.goto(url, wait_until="domcontentloaded", timeout=45000); pg.wait_for_timeout(9000)
    return "have access to this chat" in pg.evaluate("document.body.innerText")


def trash_agent(pg, aid):
    """Карточка агента → «⋯» → Move to Trash (корзина Notion, 30 дней можно вернуть)."""
    pg.goto(f"https://app.notion.com/agent/{aid}?wfv=agent", wait_until="domcontentloaded", timeout=45000); pg.wait_for_timeout(6000)
    if pg.locator("h1, [role=heading]").get_by_text("Morning brief", exact=True).count() == 0 and "Morning brief" not in body_text(pg):
        raise RuntimeError("страница агента не открылась")
    pg.mouse.click(1359, 22)                                  # «⋯» справа сверху
    _click_menu_item(pg, "Move to Trash"); _confirm_if_any(pg, "Move to Trash"); pg.wait_for_timeout(3000)
    pg.goto(f"https://app.notion.com/agent/{aid}?wfv=agent", wait_until="domcontentloaded", timeout=45000); pg.wait_for_timeout(6000)
    return "Trash" in body_text(pg) or pg.get_by_text("Restore", exact=False).count() > 0 or "agent/" + aid not in pg.url


def body_text(pg):
    return pg.evaluate("document.body.innerText")
