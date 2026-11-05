#!/usr/bin/env python3
"""Вход в Notion по коду из письма (запускает server.py при слетевшей сессии). Код ждёт в code.txt до 12 минут.
Новая сессия сначала проверяется (открывается чат «2») и только потом заменяет state.json."""
import json, os, re, sys, time
from playwright.sync_api import sync_playwright
D = "/root/notion_web"
try:  # [notion-ai] почта и чат — из ⚙ Настройки → Notion AI в панели (/opt/cc-limits/notion_ai.json)
    CFG = json.load(open("/opt/cc-limits/notion_ai.json"))
except Exception:
    CFG = {}
EMAIL = str(CFG.get("notion_email") or os.environ.get("NOTION_EMAIL") or "").strip()
CODE, NEW, CUR = f"{D}/code.txt", f"{D}/state.new.json", f"{D}/state.json"
CHAT = str(CFG.get("chat_url") or "")
if not re.fullmatch(r"https://(app\.notion\.com|www\.notion\.so|notion\.so)/chat\?t=[0-9a-f]{32}", CHAT):
    CHAT = "https://app.notion.com/chat"  # проверка входа на странице нового чата
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
def log(m): print(time.strftime("%H:%M:%S"), m, flush=True)
if not EMAIL: log("почта входа не задана (⚙ Настройки → Notion AI)"); sys.exit(4)
for f in (CODE, NEW):
    try: os.remove(f)
    except FileNotFoundError: pass
with sync_playwright() as p:
    b = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}, locale="ru-RU", timezone_id="Asia/Irkutsk")
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    pg = ctx.new_page()
    try:
        pg.goto("https://app.notion.com/login", wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(4000)
        pg.fill("input[type=email], input[placeholder*='email' i]", EMAIL)
        pg.get_by_role("button", name="Continue").first.click()
        pg.wait_for_timeout(5000)
        log("письмо с кодом запрошено, ждём code.txt (до 12 мин)")
        t0 = time.time()
        while time.time() - t0 < 720 and not os.path.exists(CODE): time.sleep(2)
        if not os.path.exists(CODE): log("код не пришёл"); sys.exit(2)
        code = open(CODE).read().strip(); os.remove(CODE)
        pg.locator("input[placeholder*='code' i], input[type=text]:visible, input[inputmode=numeric]").first.fill(code)
        pg.keyboard.press("Enter")
        for _ in range(40):
            pg.wait_for_timeout(1500)
            if "login" not in pg.url: break
        pg.wait_for_timeout(4000)
        if "login" in pg.url: log("код не принят"); sys.exit(3)
        pg.goto(CHAT, wait_until="domcontentloaded", timeout=45000)
        pg.get_by_placeholder("Ask Notion AI").first.wait_for(timeout=40000)
        ctx.storage_state(path=NEW); os.chmod(NEW, 0o600); os.replace(NEW, CUR)
        log("сессия сохранена")
    finally:
        b.close()
