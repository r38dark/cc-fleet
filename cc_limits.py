#!/usr/bin/env python3
# cc-limits — мониторинг лимитов Pro/Max-аккаунтов Claude Code + авто-переключение.
# Запуск: systemd unit (порт задаётся в config.json, ключ "port", по умолчанию 8877;
# снаружи — через nginx /cc/, см. install.sh).
import html, json, os, re, shutil, subprocess, tempfile, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pyte
import pexpect

# BASE/PROFILES переопределяемы через env только для изолированного тестирования
# инсталлятора (install.sh их не трогает — на реальном сервере это фиксированные пути,
# один Claude Code живёт в одном /root на VDS).
BASE = os.environ.get("CC_LIMITS_BASE", "/opt/cc-limits")
PROFILES = os.environ.get("CC_LIMITS_PROFILES", "/root/.claude-profiles")
LIVE_CREDS = "/root/.claude/.credentials.json"
LIVE_CFG = "/root/.claude.json"
TG_ENV = "/root/.claude/channels/telegram/.env"
CONFIG = os.path.join(BASE, "config.json")
SNAPSHOT = os.path.join(BASE, "snapshot.json")
STATE = os.path.join(BASE, "state.json")
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"  # публичный client_id Claude Code
# абсолютный путь: у systemd-сервиса нет ~/.bashrc с PATH — ищем claude в типичных местах,
# в install.sh прописывается точный путь, найденный на конкретной машине
CLAUDE_BIN = (shutil.which("claude")
              or next((p for p in (
                  os.path.expanduser("~/.npm-global/bin/claude"),
                  "/usr/local/bin/claude",
                  os.path.expanduser("~/.local/bin/claude"),
              ) if os.path.isfile(p)), "claude"))

lock = threading.Lock()


def jload(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def jsave(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def cfg():
    return jload(CONFIG, {})


def http_json(url, payload=None, headers=None, timeout=20):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {})
    # без нормального UA WAF Anthropic отдаёт 403
    req.add_header("User-Agent", "claude-cli/2.0 (external, cli)")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def tg_notify(text):
    chat_id = cfg().get("chat_id")
    if not chat_id:
        return  # телеграм-уведомления не настроены — тихо пропускаем
    try:
        env = open(TG_ENV).read()
        m = re.search(r"TELEGRAM_BOT_TOKEN=(\S+)", env)
        if not m:
            return
        http_json(f"https://api.telegram.org/bot{m.group(1)}/sendMessage",
                  {"chat_id": chat_id, "text": text})
    except Exception as e:
        print(f"tg_notify fail: {e}", flush=True)


def profile_names():
    if not os.path.isdir(PROFILES):
        return []
    return sorted(n for n in os.listdir(PROFILES)
                  if not n.startswith("_") and os.path.isfile(f"{PROFILES}/{n}/oauth_account.json"))


def active_name():
    uuid = (jload(LIVE_CFG, {}) or {}).get("oauthAccount", {}).get("accountUuid")
    for n in profile_names():
        oa = jload(f"{PROFILES}/{n}/oauth_account.json", {})
        if oa.get("accountUuid") == uuid:
            return n
    return None


def refresh_tokens(creds_path):
    # Обмен refresh-токена на свежую пару; сохраняет на место атомарно
    c = jload(creds_path)["claudeAiOauth"]
    r = http_json("https://platform.claude.com/v1/oauth/token",
                  {"grant_type": "refresh_token", "refresh_token": c["refreshToken"],
                   "client_id": CLIENT_ID})
    c["accessToken"] = r["access_token"]
    c["refreshToken"] = r.get("refresh_token", c["refreshToken"])
    c["expiresAt"] = int(time.time() * 1000) + int(r.get("expires_in", 28800)) * 1000
    jsave(creds_path, {"claudeAiOauth": c})
    return c


def get_access(name, act):
    # Для активного профиля access берём из live-файла (его ведёт сам CLI),
    # рефрешим live только если он уже протух. Неактивным рефрешим свои файлы профилей.
    path = LIVE_CREDS if name == act else f"{PROFILES}/{name}/credentials.json"
    c = jload(path)["claudeAiOauth"]
    if c["expiresAt"] / 1000 - time.time() < 120:
        c = refresh_tokens(path)
        if name == act:  # live обновили — продублировать в профиль
            jsave(f"{PROFILES}/{name}/credentials.json", {"claudeAiOauth": c})
    return c["accessToken"]


# --- Перелогин через веб (08.08.26) — кнопка "Войти заново" в панели вместо
# SSH, когда refresh-токен протух насмерть (invalid_grant). Ведём настоящий `claude auth
# login` в изолированном HOME (pexpect держит псевдотерминал, т.к. это TUI-команда):
# start возвращает OAuth-ссылку с login_hint, submit дописывает вставленный код и,
# по факту появления credentials.json в изолированном HOME (самый надёжный сигнал
# успеха — не гадаем по тексту вывода CLI), переносит файлы в профиль.
_relogin = {}  # account name -> {child, home, started}
_RELOGIN_TTL = 600  # 10 мин без submit — попытка считается брошенной


def _relogin_cleanup(name):
    st = _relogin.pop(name, None)
    if not st:
        return
    try:
        st["child"].close(force=True)
    except Exception:
        pass
    shutil.rmtree(st["home"], ignore_errors=True)


def _relogin_sweep():
    now = time.time()
    for n in [n for n, st in _relogin.items() if now - st["started"] > _RELOGIN_TTL]:
        _relogin_cleanup(n)


def relogin_start(name):
    _relogin_sweep()
    if name not in profile_names():
        return False, "неизвестный аккаунт", None
    _relogin_cleanup(name)  # если была брошенная попытка — начинаем чисто
    oa = jload(f"{PROFILES}/{name}/oauth_account.json", {})
    email = oa.get("emailAddress", "")
    home = tempfile.mkdtemp(prefix=f"cc-relogin-{name}-")
    env = dict(os.environ)
    env["HOME"] = home
    cmd = f"{CLAUDE_BIN} auth login" + (f" --email {email}" if email else "")
    try:
        child = pexpect.spawn(cmd, env=env, cwd=home, timeout=20, encoding="utf-8")
        # [^\s\x00-\x1f\x7f]+ — не \S+: CLI печатает ссылку дважды (обычным текстом и
        # ещё раз как OSC-8 гиперссылку), \S+ не считает ESC/управляющие байты "пробелом"
        # и склеивает обе копии в один битый URL (поймано живым тестом 08.08.26)
        idx = child.expect([r"(https://[^\s\x00-\x1f\x7f]+)", pexpect.TIMEOUT, pexpect.EOF], timeout=15)
    except Exception as e:
        shutil.rmtree(home, ignore_errors=True)
        return False, f"не удалось запустить claude auth login: {e}", None
    if idx != 0:
        tail = (child.before or "")[-300:]
        try:
            child.close(force=True)
        except Exception:
            pass
        shutil.rmtree(home, ignore_errors=True)
        return False, "claude auth login не показал ссылку: " + tail.strip(), None
    url = child.match.group(1).rstrip(").,")
    _relogin[name] = {"child": child, "home": home, "started": time.time()}
    return True, url, email


def relogin_submit(name, code):
    st = _relogin.get(name)
    if not st:
        return False, "Нет активной попытки для этого аккаунта — начни заново.", None
    child, home = st["child"], st["home"]
    creds_path = os.path.join(home, ".claude", ".credentials.json")
    try:
        child.sendline((code or "").strip())
        child.expect(pexpect.EOF, timeout=30)
    except Exception:
        pass  # неважно — успех проверяем по факту наличия файла ниже
    time.sleep(0.3)
    if not os.path.isfile(creds_path):
        print(f"relogin_submit({name}): fail, CLI tail: {(child.before or '')[-300:]!r}", flush=True)
        _relogin_cleanup(name)
        return False, "Логин не завершился — код мог быть неверным, просроченным или ещё не подтверждён в браузере. Попробуй ещё раз (кнопка «Войти заново» заново) или проверь, что вход в браузере точно завершён.", None
    with lock:  # один захват на весь критический участок — collect() ниже lock уже не берёт
        try:
            creds = jload(creds_path)
            jsave(f"{PROFILES}/{name}/credentials.json", creds)
            oa = (jload(os.path.join(home, ".claude.json"), {}) or {}).get("oauthAccount")
            if oa:
                jsave(f"{PROFILES}/{name}/oauth_account.json", oa)
            act = active_name()
            if act == name:  # перелогинили АКТИВНЫЙ профиль — продублировать в live-файлы
                jsave(LIVE_CREDS, creds)
                if oa:
                    live = jload(LIVE_CFG, {})
                    live["oauthAccount"] = oa
                    jsave(LIVE_CFG, live)
        finally:
            _relogin_cleanup(name)
        _plan_cache.pop(name, None)
        snap = collect(force=True)
    row = (snap.get("accounts") or {}).get(name, {})
    email = row.get("email", name)
    tg_notify(f"🔑 Claude: аккаунт {name} ({email}) перелогинен через сайт — токен обновлён.")
    return True, f"✅ {email} — вход выполнен, токен обновлён.", snap


def fetch_usage(access):
    d = http_json("https://api.anthropic.com/api/oauth/usage", headers={
        "Authorization": f"Bearer {access}", "anthropic-beta": "oauth-2025-04-20"})
    out = {}
    for k in ("five_hour", "seven_day"):
        v = d.get(k) or {}
        out[k] = {"pct": v.get("utilization"), "resets_at": v.get("resets_at")}
    return out


_plan_cache = {}  # name -> (ts, plan) — profile дёргаем не чаще раза в 10 мин

def fetch_plan(name, access):
    hit = _plan_cache.get(name)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    d = http_json("https://api.anthropic.com/api/oauth/profile", headers={
        "Authorization": f"Bearer {access}", "anthropic-beta": "oauth-2025-04-20"})
    a = d.get("account") or {}
    plan = "max" if a.get("has_claude_max") else ("pro" if a.get("has_claude_pro") else "free")
    _plan_cache[name] = (time.time(), plan)
    return plan


GOOD = os.path.join(BASE, "last_good.json")
rate_limited = False  # был 429 в последнем сборе — poll_loop притормозит


def collect(force=False):
    global rate_limited
    prev = jload(SNAPSHOT) or {}
    # дедуп: не дёргать Anthropic чаще раза в 30с (иначе 429 Too Many Requests),
    # UI-запросы между опросами получают свежий снапшот с актуальным active
    if not force and time.time() - prev.get("ts", 0) < 30:
        return snap_set_active()
    act = active_name()
    good = jload(GOOD, {})
    accounts = {}
    saw_429 = False
    for n in profile_names():
        oa = jload(f"{PROFILES}/{n}/oauth_account.json", {})
        row = {"email": oa.get("emailAddress", "?"), "active": n == act}
        errs = []
        access = None
        try:
            access = get_access(n, act)
        except Exception as e:
            errs.append(str(e))
        # (plan-freshness 2026-07-21) usage и plan запрашиваются НЕЗАВИСИМО. Раньше
        # plan вообще не запрашивался, если fetch_usage падал первым (напр. 429) —
        # значит pro→free переход (см. tg_notify ниже) и исключение из авто-кандидатов
        # молчали сколько угодно долго, пока usage-эндпоинт был недоступен. Именно
        # так cc-switch вручную приземлил живую сессию на реально-Free аккаунт
        # (21.07, "organization has disabled Claude subscription access") — карточка
        # показывала кэшированный "pro", хотя аккаунт уже был Free.
        if access is not None:
            try:
                row.update(fetch_usage(access))
            except Exception as e:
                errs.append(str(e))
            try:
                row["plan"] = fetch_plan(n, access)
            except Exception as e:
                errs.append(str(e))
        if "five_hour" in row and "plan" in row:
            good[n] = {"five_hour": row["five_hour"], "seven_day": row["seven_day"],
                       "plan": row["plan"], "ts": int(time.time())}
        if errs:
            row["error"] = " | ".join(errs)[:200]
            if any("429" in e for e in errs):
                saw_429 = True
            # разовый сбой (429 и т.п.) не должен стирать карточку — показать
            # последние удачные цифры из отдельного кэша с пометкой возраста
            # (только для того, что реально не получили в этом цикле)
            old = good.get(n) or {}
            for k in ("five_hour", "seven_day", "plan"):
                if row.get(k) is None and old.get(k) is not None:
                    row[k] = old[k]
            row["stale_ts"] = old.get("ts")
        accounts[n] = row
    rate_limited = saw_429
    jsave(GOOD, good)
    snap = {"ts": int(time.time()), "active": act, "accounts": accounts}
    jsave(SNAPSHOT, snap)
    # детект внешнего переключения: cc-switch из консоли мимо этого сервиса.
    # Переключения через /api/switch и авто/оптимизацию сами обновляют
    # known_active — сюда попадает только то, что сделали руками извне.
    st0 = jload(STATE, {})
    if st0.get("known_active") != act:
        if st0.get("known_active") and act:
            email = (accounts.get(act) or {}).get("email", "")
            tg_notify("👆 Claude: аккаунт переключён извне (cc-switch из консоли): %s → %s (%s)."
                      % (st0["known_active"], act, email))
        st0["known_active"] = act
        jsave(STATE, st0)
    # смена плана (Pro истёк / продлён) — уведомить один раз на переход
    st = jload(STATE, {})
    prev = st.get("plans") or {}
    cur = {n: r.get("plan") for n, r in accounts.items() if r.get("plan")}
    for n, p in cur.items():
        was = prev.get(n)
        if was and was != p:
            email = accounts[n].get("email", n)
            if p == "free":
                tg_notify(f"⛔ Claude: аккаунт {n} ({email}) слетел с Pro в Free — пора продлевать подписку. Из ротации исключён.")
            else:
                tg_notify(f"✅ Claude: аккаунт {n} ({email}) снова {p.upper()} — вернул в ротацию.")
    if cur != prev:
        st["plans"] = {**prev, **cur}
        jsave(STATE, st)
    return snap


SETTINGS = "/root/.claude/settings.json"
TRANSCRIPTS = "/root/.claude/projects/-root"
MODELS = {  # id → короткое имя для UI
    "claude-fable-5": "Fable 5",
    "claude-opus-5": "Opus 5",
    "claude-sonnet-5": "Sonnet 5",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
}


def screen_hardcopy():
    # снять текущий экран живой сессии (read-only, ввод не трогаем).
    # Вызывается из нескольких мест (консоль /api/console, session_model() для
    # model_info, диалог подтверждения модели) на разных потоках ThreadingHTTPServer
    # одновременно — общий фиксированный tmp-файл давал гонку: один запрос читает,
    # пока другой ещё пишет ту же hardcopy, получается урезанный/битый текст, из-за
    # чего "геометрия" консоли (см. _console_dims) ложно скакала (инцидент 12.07,
    # деградация консоли/оффлайн-индикатор). Уникальный файл на вызов убирает гонку.
    _sweep_stale_hardcopy_dumps()
    try:
        scr = cfg().get("screen_session", "claude")
        fd, tmp = tempfile.mkstemp(prefix="scr_dump_", dir="/opt/cc-limits")
        os.close(fd)
        try:
            subprocess.run(["screen", "-S", scr, "-p", "0", "-X", "hardcopy", tmp],
                           capture_output=True, timeout=10)
            # screen -X — это команда клиента демону screen, клиент выходит сразу
            # после ОТПРАВКИ команды, не дожидаясь пока демон реально допишет файл.
            # Под конкурентной нагрузкой (несколько одновременных опросов /api/console
            # с разных вкладок/потоков) демон обслуживает hardcopy-команды по очереди
            # — наш read() может обогнать запись и увидеть пустой файл. Короткий
            # добор (до 300мс) ждёт появления контента вместо немедленного чтения.
            for _ in range(30):
                if os.path.getsize(tmp) > 0:
                    break
                time.sleep(0.01)
            with open(tmp, errors="replace") as f:
                return f.read()
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    except Exception:
        return ""


def _sweep_stale_hardcopy_dumps():
    # Подчистка на случай, если демон дописал файл ПОСЛЕ того как мы его уже
    # удалили (та же гонка, что и выше, только на хвосте) — такие файлы больше
    # никто не тронет, копятся вечно. Метём то, что старше минуты — нормальный
    # цикл запроса живёт доли секунды, минута с запасом отсекает только сирот.
    try:
        cutoff = time.time() - 60
        for name in os.listdir("/opt/cc-limits"):
            if not name.startswith("scr_dump_"):
                continue
            p = os.path.join("/opt/cc-limits", name)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass
    except Exception:
        pass


# --- Консоль для веб-панели (read-only) ---
# `screen hardcopy` для НЕ-ASCII (кириллица) пишет только codepoint & 0x7F на
# символ — необратимая порча (проверено на живых данных 11.07.26: "Консоль"
# превращалось в бессмысленные латинские байты). Это баг сериализации самого
# hardcopy, не настройки encoding — `screen -X encoding utf8` его не чинит.
# Обход: включаем `screen log` (сырой поток байт как есть, без пересборки
# hardcopy) и восстанавливаем актуальный экран через pyte (VT100-эмулятор) —
# он корректно декодирует UTF-8. screen_hardcopy() выше НЕ трогаем — им
# пользуется session_model()/_dialog_watchdog(), там только ASCII.
CONSOLE_LOG = os.path.join(BASE, "console.log")
_console_log_ready = False
_console_screen_pid = None


def _current_screen_pid(scr):
    try:
        r = subprocess.run(["screen", "-list"], capture_output=True, timeout=10, text=True)
        m = re.search(r"(\d+)\." + re.escape(scr) + r"\b", r.stdout)
        return m.group(1) if m else None
    except Exception:
        return None


def _console_ensure_logging():
    # Если screen-сессию пересоздали (тот же имя, новый PID — напр. после ребута
    # или ручного restart), старая арматура "logfile+log on" была выдана мёртвой
    # сессии и на новую не переносится сама — консоль молча замирает на старом
    # содержимом навсегда. Поэтому проверяем PID сессии, а не только факт "уже
    # армили когда-то", и переармливаем при смене PID.
    global _console_log_ready, _console_screen_pid, _console_screen, _console_offset
    scr = cfg().get("screen_session", "claude")
    pid = _current_screen_pid(scr)
    if _console_log_ready and pid == _console_screen_pid:
        return
    # Старый CONSOLE_LOG принадлежит мёртвой сессии — убираем с дороги, чтобы
    # не тащить гигабайты неактуального скроллбэка в pyte на каждый реparse
    # (инцидент 12.07: 29МБ статичного огрызка вешали сервер на ~90с на запрос).
    if os.path.exists(CONSOLE_LOG):
        try:
            os.replace(CONSOLE_LOG, CONSOLE_LOG + ".prev")
        except OSError:
            pass
    subprocess.run(["screen", "-S", scr, "-p", "0", "-X", "logfile", CONSOLE_LOG],
                   capture_output=True, timeout=10)
    subprocess.run(["screen", "-S", scr, "-p", "0", "-X", "log", "on"],
                   capture_output=True, timeout=10)
    _console_log_ready = True
    _console_screen_pid = pid
    with _console_lock:
        _console_screen = None
        _console_offset = 0


def _console_dims():
    # геометрия (число строк/колонок) у hardcopy честная, ломается только
    # значение не-ASCII символов — берём размер отсюда, контент из pyte
    txt = screen_hardcopy()
    lines = txt.split("\n") if txt else []
    rows = len(lines) or 24
    cols = max((len(l) for l in lines), default=80) or 80
    return max(cols, 20), max(rows, 5)


# pyte хранит цвет каждой ячейки: имя одного из 8 базовых ANSI-цветов ("red",
# "green", "brown"=жёлтый и т.д.), "default", либо hex-строка без "#" (256-color
# / truecolor). bold применяем как "яркий" вариант базовой палитры — так цвет
# на веб-странице совпадает с тем что видно в реальном терминале.
ANSI_FG = {"black": "#6b7078", "red": "#e05b5b", "green": "#34c07c", "brown": "#e8b93e",
           "blue": "#7c9aff", "magenta": "#c07ce0", "cyan": "#4fc7d9", "white": "#c8d0dc"}
ANSI_FG_BOLD = {"black": "#8b93a7", "red": "#ff6b6b", "green": "#4cd97b", "brown": "#f5d76e",
                "blue": "#9db4ff", "magenta": "#e0a0ff", "cyan": "#6fe0f2", "white": "#ffffff"}


def _resolve_color(name, bold):
    if not name or name == "default":
        return None
    if len(name) == 6 and all(c in "0123456789abcdefABCDEF" for c in name):
        return "#" + name
    return (ANSI_FG_BOLD if bold else ANSI_FG).get(name)


def _cell_style(ch):
    fg, bg = _resolve_color(ch.fg, ch.bold), _resolve_color(ch.bg, False)
    if ch.reverse:
        fg, bg = bg, fg
    parts = []
    if fg:
        parts.append(f"color:{fg}")
    if bg:
        parts.append(f"background:{bg}")
    if ch.bold:
        parts.append("font-weight:700")
    if ch.underscore:
        parts.append("text-decoration:underline")
    return ";".join(parts)


def _row_html(line, ncols):
    out, style, buf = [], "", []
    for x in range(ncols):
        ch = line[x]
        st = _cell_style(ch)
        if st != style:
            if buf:
                txt = html.escape("".join(buf))
                out.append(f'<span style="{style}">{txt}</span>' if style else txt)
            buf, style = [], st
        buf.append(ch.data or " ")
    if buf:
        txt = html.escape("".join(buf))
        out.append(f'<span style="{style}">{txt}</span>' if style else txt)
    return "".join(out) or " "


# --- Персистентное состояние pyte (скроллбэк) ---
# Наивный вариант — пересобирать pyte.Screen с нуля из хвоста лога на КАЖДЫЙ
# запрос — не даёт скроллбэка (Screen помнит только текущий видимый экран) и
# не масштабируется: полный re-parse растёт вместе с логом (бенчмарк 11.07:
# 600КБ ≈ 2с на HistoryScreen — уже на грани 2-секундного опроса с фронта).
# Поэтому держим ОДИН живой pyte.HistoryScreen на процесс и на каждый запрос
# докармливаем только НОВЫЕ байты с прошлого раза (смещение в файле) — тогда
# стоимость запроса не растёт вместе с логом, а скроллбэк копится в
# screen.history бесконечно (пока не упрётся в CONSOLE_HISTORY_LINES).
CONSOLE_HISTORY_LINES = 2000  # строк скроллбэка сверх текущего экрана
_console_lock = threading.Lock()
_console_screen = None
_console_stream = None
_console_offset = 0
_console_geom = (0, 0)


def _console_reset(cols, rows):
    global _console_screen, _console_stream, _console_offset, _console_geom
    _console_screen = pyte.HistoryScreen(cols, rows, history=CONSOLE_HISTORY_LINES)
    _console_stream = pyte.ByteStream(_console_screen)
    _console_offset = 0
    _console_geom = (cols, rows)


def _console_resize(cols, rows):
    # _console_dims() меряет геометрию по длине строк hardcopy — это не истинный
    # размер терминала, а "плотная коробка" вокруг текущего контента, и она гуляет
    # вместе с ним (короткая/длинная строка, кириллица режет длину иначе). Раньше
    # ЛЮБОЕ изменение (cols, rows) било в _console_reset(), который обнулял
    # _console_offset — следующий _console_feed() перечитывал ВЕСЬ CONSOLE_LOG
    # (десятки МБ) через pyte заново. При активной сессии геометрия "меняется"
    # почти на каждый опрос — сервер прогрессивно отставал и уходил в timeout
    # (инцидент 12.07, рецидив внешне похожего бага 12.07 утра, но другая причина:
    # там ломался PID сессии, здесь — offset обнулялся штатно на каждый чих).
    # pyte.HistoryScreen.resize() меняет размер БЕЗ потери history/offset — дёшево
    # независимо от того как часто вызывается.
    global _console_geom
    _console_screen.resize(rows, cols)
    _console_geom = (cols, rows)


def _console_feed():
    global _console_offset
    try:
        size = os.path.getsize(CONSOLE_LOG)
    except OSError:
        return
    if size < _console_offset:
        _console_offset = 0  # лог обрезан/пересоздан — докармливаем тот же экран с начала файла
    with open(CONSOLE_LOG, "rb") as f:
        f.seek(_console_offset)
        data = f.read()
    if data:
        _console_stream.feed(data)
        _console_offset += len(data)


def console_snapshot(want_history=False):
    # want_history=False (дефолт, дёргается раз в 2с с фронта) — рендерит ТОЛЬКО
    # текущий экран (десятки строк, дёшево). history.top растёт до 2000 строк и
    # рендерить/пересылать её КАЖДЫЙ опрос — то что вешало браузер: клиент
    # делал box.innerHTML = <растущая HTML-простыня> каждые 2с навсегда, полный
    # reflow гигантского DOM без остановки. history теперь считается только по
    # явному запросу (первая загрузка страницы), текущий экран — отдельно и часто.
    _console_ensure_logging()
    cols, rows = _console_dims()
    with _console_lock:
        if _console_screen is None:
            _console_reset(cols, rows)
        elif _console_geom != (cols, rows):
            _console_resize(cols, rows)
        _console_feed()
        screen = _console_screen
        # screen.display — уже проверенный источник голого текста построчно,
        # используем его только чтобы отрезать пустой хвост ТЕКУЩЕГО экрана снизу
        current = list(zip(screen.display, (_row_html(screen.buffer[y], cols) for y in range(rows))))
        while current and not current[-1][0].strip():
            current.pop()
        current_html = "\n".join(h for _, h in current)
        history_html = None
        if want_history:
            history_html = "\n".join(_row_html(line, cols) for line in screen.history.top)
    return current_html, history_html


def session_model():
    # Источник истины = статус-строка живой сессии (то, что видно в терминале):
    # "  Fable 5     40%  root  ⏵ xhigh". Именно она отражает и авто-переключения
    # рантайма (напр. safeguard'ы Fable→Opus), которых нет в settings.json.
    txt = screen_hardcopy()
    for line in txt.splitlines():
        for mid, name in MODELS.items():
            # имя модели в начале строки статуса + где-то дальше "root"
            if re.search(r"\b" + re.escape(name) + r"\b\s+\d+%\s+root", line):
                return mid
    # запасной путь — последний assistant в свежем транскрипте
    try:
        files = [os.path.join(TRANSCRIPTS, f) for f in os.listdir(TRANSCRIPTS) if f.endswith(".jsonl")]
        newest = max(files, key=os.path.getmtime)
        with open(newest, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 300_000))
            tail = f.read().decode("utf-8", "replace")
        model = None
        for line in tail.splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = (d.get("message") or {}).get("model")
            if d.get("type") == "assistant" and m:
                model = m
        return model
    except Exception:
        return None


def model_info():
    dflt = (jload(SETTINGS, {}) or {}).get("model")
    sess = session_model()
    return {"session": sess, "session_name": MODELS.get(sess, sess),
            "default": dflt, "default_name": MODELS.get(dflt, dflt),
            "available": [{"id": k, "name": v} for k, v in MODELS.items()]}


def _dialog_watchdog():
    # Постоянный сторож диалога "Switch model?" (Yes/No), крутится с самого
    # старта сервиса, а не только 12с после конкретного клика по кнопке модели.
    # Инцидент 15.07.26: пользователь кликнул "Новая сессия" и "Модель" почти одновременно
    # (2с разницы) — /clear запускает тяжёлую session-start обработку (CLAUDE.md,
    # MEMORY.md), и пока TUI была занята этим, старый одноразовый 12-секундный
    # слушатель не застал момент появления диалога и вышел ни с чем. Диалог провисел
    # неотвеченным 2ч25м — вся сессия (единственный серийный процесс) не обрабатывала
    # вообще ничего, пока следующий клик по кнопке модели случайно не прислал Enter
    # ему на подтверждение. Постоянный цикл ловит диалог независимо от того, кто и
    # когда его открыл — максимальная задержка подтверждения ~5с вместо "никогда".
    scr = cfg().get("screen_session", "claude")
    while True:
        try:
            txt = screen_hardcopy()
            if "Switch model?" in txt:
                time.sleep(0.3)
                subprocess.run(["screen", "-S", scr, "-p", "0", "-X", "stuff", "\r"],
                               capture_output=True, timeout=10)
                time.sleep(2)  # дать экрану обновиться, не долбить ещё раз тот же диалог
        except Exception:
            pass
        time.sleep(5)


def set_default_model(model_id):
    if model_id not in MODELS:
        return False, "unknown model"
    s = jload(SETTINGS, {}) or {}
    s["model"] = model_id
    with open(SETTINGS + ".tmp", "w") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)
    os.replace(SETTINGS + ".tmp", SETTINGS)
    # settings.json меняет дефолт новых сессий. Живую сессию так не переключить —
    # один best-effort /model в консоль. Сработает, только если TUI
    # сейчас простаивает; если занята — ввод отбрасывается (не ставится в очередь).
    # Диалог "Switch model?", если появится, подтвердит фоновый _dialog_watchdog
    # (крутится постоянно с старта сервиса, см. его комментарий) — отдельный
    # one-shot поток здесь больше не нужен.
    live = False
    try:
        scr = cfg().get("screen_session", "claude")
        p = subprocess.run(["screen", "-S", scr, "-p", "0", "-X", "stuff", f"/model {model_id}\r"],
                           capture_output=True, text=True, timeout=10)
        live = p.returncode == 0
    except Exception:
        pass
    # live=True значит лишь что stuff прошёл технически — не гарантия, что TUI была
    # свободна и приняла команду. Честная формулировка без обещаний.
    return True, MODELS[model_id] + (" — дефолт сохранён; в текущей сессии применится, если она сейчас свободна (иначе повтори)" if live else " — сохранён дефолт для новых сессий (живая недоступна)")


SESSION_COMMANDS = {  # ключ с сайта -> реальная slash-команда в живой сессии
    "compact": "/compact",
    "new": "/clear",  # "/new" — алиас /clear: старый разговор остаётся на диске, resumable
}


def send_session_command(key):
    # Прямая инъекция в живую сессию (screen stuff), тот же принцип что и у модели:
    # ни /compact, ни /clear не показывают диалог подтверждения — выполняются сразу
    # по Enter. Best-effort: если TUI сейчас занята, ввод молча отбрасывается.
    cmd = SESSION_COMMANDS.get(key)
    if not cmd:
        return False, "unknown command"
    try:
        scr = cfg().get("screen_session", "claude")
        p = subprocess.run(["screen", "-S", scr, "-p", "0", "-X", "stuff", f"{cmd}\r"],
                           capture_output=True, text=True, timeout=10)
        ok = p.returncode == 0
    except Exception:
        ok = False
    return ok, (f"Команда {cmd} отправлена — сработает, если сессия сейчас свободна (иначе повтори)"
                if ok else "не удалось отправить (сессия недоступна)")


def snap_set_active():
    # после переключения обновить в снапшоте только флаги active — без похода в API
    snap = jload(SNAPSHOT) or {}
    act = active_name()
    snap["active"] = act
    for n, row in (snap.get("accounts") or {}).items():
        row["active"] = n == act
    jsave(SNAPSHOT, snap)
    return snap


def do_switch(target):
    p = subprocess.run(["/usr/local/bin/cc-switch", target], capture_output=True, text=True, timeout=30)
    ok = p.returncode == 0
    return ok, (p.stdout + p.stderr).strip()


def autoswitch_check(snap):
    c = cfg()
    if not c.get("autoswitch", True):
        return
    thr = c.get("threshold", 85)
    st = jload(STATE, {})
    act = snap.get("active")
    accs = snap.get("accounts", {})
    if not act or act not in accs:
        return
    act_free = accs[act].get("plan") == "free"
    cur = (accs[act].get("five_hour") or {}).get("pct")
    if not act_free:
        if cur is None or cur < thr:
            st["all_high_notified"] = False
            jsave(STATE, st)
            return
        # ручной пин: пользователь сознательно выбрал забитый аккаунт — не трогать до сброса его сессии
        hold = st.get("manual_hold") or {}
        if hold.get("account") == act and time.time() < hold.get("until", 0):
            return
    if time.time() - st.get("last_switch_ts", 0) < c.get("switch_cooldown_sec", 600):
        return
    # кандидаты: не активный, без ошибок, НЕ Free; при живом Pro-активном ещё и ниже порога
    cand = []
    for n, row in accs.items():
        if n == act or row.get("error") or row.get("plan") == "free":
            continue
        fh = (row.get("five_hour") or {}).get("pct")
        sd = (row.get("seven_day") or {}).get("pct")
        if fh is None:
            continue
        if act_free or (fh < thr and (sd is None or sd < thr)):
            cand.append((fh, n))
    if not cand:
        if not st.get("all_high_notified"):
            reason = "активный слетел в Free, а остальные недоступны" if act_free \
                else f"у ВСЕХ аккаунтов сессия ≥{thr}%"
            tg_notify(f"⛔ Claude: {reason} — переключаться некуда, жду.\n"
                      + "\n".join(f"{n}: {(r.get('five_hour') or {}).get('pct')}% [{r.get('plan','?')}]" for n, r in accs.items()))
            st["all_high_notified"] = True
            jsave(STATE, st)
        return
    cand.sort()
    fh, target = cand[0]
    ok, out = do_switch(target)
    st["last_switch_ts"] = time.time()
    st["all_high_notified"] = False
    if ok:
        st["known_active"] = target
    jsave(STATE, st)
    email = accs[target].get("email", target)
    why = f"аккаунт {act} слетел в Free" if act_free else f"сессия {act} дошла до {cur}%"
    if ok:
        tg_notify(f"🔄 Claude: {why} — авто-переключил на {target} ({email}, сессия {fh}%). Рестарт не нужен.")
        snap_set_active()
    else:
        tg_notify(f"⚠️ Claude: авто-переключение на {target} не удалось: {out}")


def _hours_until(iso, default_h):
    try:
        from datetime import datetime
        return max((datetime.fromisoformat(iso).timestamp() - time.time()) / 3600.0, 0.05)
    except Exception:
        return default_h


def _fmt_hours(h):
    if h >= 48:
        return "%.0f д" % (h / 24)
    if h >= 1:
        return "%.0f ч" % h
    return "%.0f мин" % (h * 60)


def _opt_score(row):
    # Сколько недельного запаса приходится на час до сброса недели аккаунта.
    # Большой score = сброс скоро и/или запас большой — жечь выгоднее всего его
    # (неистраченный к сбросу недельный лимит просто сгорает). Маленький score =
    # впереди вся неделя — беречь.
    sd = row.get("seven_day") or {}
    pct = sd.get("pct")
    pct = 0 if pct is None else pct
    resets_at = sd.get("resets_at")
    if resets_at is None:
        # (starvation-fix 2026-07-17) Нет resets_at = аккаунт ни разу не использовался в
        # текущем цикле, окна сброса ещё не существует. Дефолт 168ч (целая неделя) навсегда
        # занижал score: у активных аккаунтов часы-до-сброса тикают вниз и score растёт со
        # временем, а у нетронутого — нет, он никогда их не обгонит (долго нетронутый профиль вечно
        # ~0.6 против ~1.5-1.9 у остальных, см. reference_cc_switch_accounts.md в памяти
        # Claude). Трактуем отсутствие окна как максимальную срочность, чтобы аккаунт
        # попал в ротацию хоть раз и получил реальный resets_at — после этого сюда больше
        # не попадает (там дальше уже обычная ветка с реальным countdown).
        return (100.0 - pct) / 4.0
    return (100.0 - pct) / _hours_until(resets_at, 168.0)


def optimize_check(snap):
    # Режим «оптимизация переключений лимитов»: сервис сам рулит и порогами —
    # настройки threshold/autoswitch здесь игнорируются (UI их гасит).
    # Неделя: держим активным аккаунт с максимальным _opt_score (запас/час до
    # сброса — неистраченное сгорает). Сессия: нагрузку размазываем, чтобы не
    # оказаться со всеми забитыми сессиями разом — ранний уход с opt_ses_soft
    # при свежем кандидате, аварийный форс с opt_ses_ceil, кандидаты штрафуются
    # за забитую сессию. manual_hold игнорируем: ручные свитчи заблокированы.
    c = cfg()
    ses_ceil = c.get("opt_ses_ceil", 90)      # аварийный уход
    ses_soft = c.get("opt_ses_soft", 70)      # ранний уход при свежем кандидате
    ses_cand = c.get("opt_ses_cand_max", 85)  # кандидат: сессия не выше
    ses_fresh = c.get("opt_ses_fresh", 50)    # «свежая» сессия для раннего ухода
    cap = c.get("weekly_cap", 95)
    ratio = c.get("optimize_ratio", 1.5)
    st = jload(STATE, {})
    act = snap.get("active")
    accs = snap.get("accounts", {})
    if not act or act not in accs:
        return
    a = accs[act]
    act_free = a.get("plan") == "free"
    fh = (a.get("five_hour") or {}).get("pct")
    sd = (a.get("seven_day") or {}).get("pct")
    forced = act_free or (fh is not None and fh >= ses_ceil) or (sd is not None and sd >= cap)

    def collect_cand(max_ses):
        out = []
        for n, row in accs.items():
            if n == act or row.get("error") or row.get("plan") == "free":
                continue
            cfh = (row.get("five_hour") or {}).get("pct")
            csd = (row.get("seven_day") or {}).get("pct")
            if cfh is None or cfh >= max_ses or (csd is not None and csd >= cap):
                continue
            # недельный запас/час, взвешенный на свободу сессии кандидата
            out.append((_opt_score(row) * (100.0 - cfh) / 100.0, cfh, n))
        return out

    cand = collect_cand(ses_cand)
    if forced and not cand:
        # аварийно допускаем и подзабитую сессию — лучше, чем стоять совсем
        cand = collect_cand(97)
    if forced and not cand:
        # настоящий крайний случай: не прошёл никто даже с послаблением до 97%.
        # Без потолка вообще берём наименее забитый живой (не-free) аккаунт —
        # лишь бы он был реально лучше активного (иначе бессмысленный треш).
        # Смысл: не дать всем трём одновременно упереться в 100% и застрять
        # без единого рабочего окна — немного запаса лучше, чем совсем ноль.
        best = None
        for n, row in accs.items():
            if n == act or row.get("error") or row.get("plan") == "free":
                continue
            cfh = (row.get("five_hour") or {}).get("pct")
            if cfh is None:
                continue
            if best is None or cfh < best[0]:
                best = (cfh, n)
        if best and (fh is None or best[0] < fh):
            now = time.time()
            if now - st.get("last_switch_ts", 0) >= c.get("switch_cooldown_sec", 600):
                target = best[1]
                trow = accs[target]
                tfh = (trow.get("five_hour") or {}).get("pct")
                tsd = (trow.get("seven_day") or {}).get("pct")
                ok, out = do_switch(target)
                st["last_switch_ts"] = now
                st["opt_last_switch_ts"] = now
                if ok:
                    st["known_active"] = target
                jsave(STATE, st)
                email = trow.get("email", target)
                if ok:
                    # (30.07.26) уведомление о крайнем случае убрано - спамило в чат.
                    # Переключение по-прежнему происходит, просто молча.
                    snap_set_active()
                else:
                    tg_notify("⚠️ Claude (оптимизация): переключение на %s не удалось: %s" % (target, out))
                return
    if not cand:
        if forced and not st.get("all_high_notified"):
            # (30.07.26) уведомление "некуда переключаться" убрано - спамило в чат.
            st["all_high_notified"] = True
            jsave(STATE, st)
        return
    if st.get("all_high_notified"):
        st["all_high_notified"] = False
        jsave(STATE, st)
    cand.sort(reverse=True)
    eff, tfh_c, target = cand[0]
    now = time.time()
    trow = accs[target]
    tsd = (trow.get("seven_day") or {}).get("pct")
    my_w = _opt_score(a)
    my_eff = my_w * (100.0 - (fh or 0)) / 100.0
    if forced:
        if now - st.get("last_switch_ts", 0) < c.get("switch_cooldown_sec", 600):
            return
        why = ("аккаунт %s слетел в Free" % act if act_free
               else "сессия %s дошла до %s%% (аварийный потолок %s%%)" % (act, fh, ses_ceil)
               if fh is not None and fh >= ses_ceil
               else "неделя %s дошла до %s%%" % (act, sd))
    elif (fh is not None and fh >= ses_soft and tfh_c <= ses_fresh
          and _opt_score(trow) * ratio >= my_w):
        # ранний уход: сессия активного прилично забита, у цели свежая сессия
        # и неделя не сильно хуже — размазываем сессионную нагрузку
        if now - st.get("last_switch_ts", 0) < c.get("switch_cooldown_sec", 600):
            return
        why = ("сессия %s уже %s%%, у %s свежая (%s%%) и неделя не хуже — размазываю сессионную нагрузку"
               % (act, fh, target, tfh_c))
    else:
        # плановое переключение по неделе: не чаще optimize_min_switch_sec и
        # только если взвешенный запас/час цели существенно лучше (гистерезис)
        if now - st.get("opt_last_switch_ts", 0) < c.get("optimize_min_switch_sec", 1800):
            return
        if eff < my_eff * ratio:
            return
        t_resets = (trow.get("seven_day") or {}).get("resets_at")
        t_hrs = _hours_until(t_resets, 168.0)
        a_hrs = _hours_until((a.get("seven_day") or {}).get("resets_at"), 168.0)
        if t_resets is None:
            why = ("%s ни разу не использовался (нет окна сброса) — даю ему шанс, чтобы не застрял в вечном резерве; %s берегу (сброс через %s, запас %s%%)"
                   % (target, act, _fmt_hours(a_hrs), round(100 - (sd or 0))))
        else:
            why = ("у %s сброс недели через %s (запас %s%%) — выгоднее жечь его; %s берегу (сброс через %s, запас %s%%)"
                   % (target, _fmt_hours(t_hrs), round(100 - (tsd or 0)),
                      act, _fmt_hours(a_hrs), round(100 - (sd or 0))))
    ok, out = do_switch(target)
    st["last_switch_ts"] = now
    st["opt_last_switch_ts"] = now
    if ok:
        st["known_active"] = target
    jsave(STATE, st)
    if ok:
        # (04.08.26: "постоянно пишет переключился переключился переключился") —
        # уведомление об успешном плановом/оптимизационном переключении убрано, спамило.
        # Переключение по-прежнему происходит молча, известный активный акк обновляется.
        snap_set_active()
    else:
        tg_notify("⚠️ Claude (оптимизация): переключение на %s не удалось: %s" % (target, out))


def switch_policy_check(snap):
    # оптимизация — отдельный режим, при включении полностью заменяет простой
    # авто-порог (пороговые уходы с забитого аккаунта в неё встроены)
    if cfg().get("optimize"):
        optimize_check(snap)
    else:
        autoswitch_check(snap)


def poll_loop():
    while True:
        try:
            with lock:
                snap = collect(force=True)
                switch_policy_check(snap)
        except Exception as e:
            print(f"poll fail: {e}", flush=True)
        # при 429 удвоить паузу — дать rate-limit'у Anthropic отойти
        time.sleep(cfg().get("poll_sec", 120) * (2 if rate_limited else 1))


# ---------- HTTP ----------

def fmt_reset(iso):
    return iso or ""


def pause_state():
    """Состояние «упёрлись в лимиты / стоим на паузе» для баннера панели.

    Логику НЕ дублируем: считает её pause_ctl.level_state() — тот же модуль, что
    управляет паузой и будильником, и тот же порог, что у limits_gate.py. Иначе
    страница будет обещать одно, а фоновые задачи вести себя иначе.
    """
    try:
        import sys
        if BASE not in sys.path:
            sys.path.insert(0, BASE)
        import pause_ctl  # данные модуль читает с диска на каждый вызов — кэш не мешает
        d = pause_ctl.level_state()
        d["ok"] = True
        return d
    except Exception as e:
        # pause_ctl.py может отсутствовать (установка до v1.2.0) — баннер просто не покажется
        return {"ok": False, "err": str(e)[:200], "level": "none", "pause": {"active": False}}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authed(self):
        # либо nginx прислал имя пользователя Basic Auth, либо валидный hook-токен
        if self.headers.get("X-Auth-User"):
            return True
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        tok = q.get("token", [None])[0] or self.headers.get("X-CC-Token")
        return tok == cfg().get("hook_token")

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            if not self.headers.get("X-Auth-User"):
                return self._send(403, {"error": "forbidden"})
            # токен вшивается в страницу: браузер может не переслать Basic Auth в fetch
            html = PAGE.replace("__TOKEN__", cfg().get("hook_token", ""))
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        if u.path == "/api/limits":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            q = parse_qs(u.query)
            with lock:
                snap = collect(force=True) if q.get("refresh") else (jload(SNAPSHOT) or collect())
            snap["config"] = {k: cfg().get(k) for k in ("autoswitch", "threshold", "optimize")}
            snap["model"] = model_info()
            return self._send(200, snap)
        if u.path == "/api/pause":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, pause_state())
        if u.path == "/api/console":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            q = parse_qs(u.query)
            current_html, history_html = console_snapshot(want_history=bool(q.get("history")))
            resp = {"ok": True, "current": current_html}
            if history_html is not None:
                resp["history"] = history_html
            return self._send(200, resp)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        from urllib.parse import urlparse
        u = urlparse(self.path)
        if not self._authed():
            return self._send(403, {"error": "forbidden"})
        ln = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(ln) or b"{}") if ln else {}
        if u.path == "/api/switch":
            # при включённой оптимизации ручные переключения заблокированы —
            # 200 + ok:false, чтобы страница/бот показали message как есть
            # (409 бы потерялся: urlopen в прокси/боте кидает исключение)
            if cfg().get("optimize"):
                return self._send(200, {"ok": False, "blocked": True,
                    "message": "Оптимизация переключений лимитов включена — ручное переключение заблокировано. Выключи тумблер оптимизации, чтобы переключать вручную."})
            target = body.get("account", "next")
            with lock:
                prev_act = active_name()
                ok, out = do_switch(target)
                snap = snap_set_active()  # только флаги active, без похода в API (бережём rate-limit)
                if ok:
                    st = jload(STATE, {})
                    st["last_switch_ts"] = time.time()
                    # ручной выбор ЗАБИТОГО аккаунта (≥порога) — пин до сброса его сессии,
                    # авто не перебивает; выбор свободного — обычный авто-режим
                    act = snap.get("active")
                    st["known_active"] = act  # чтобы poll не принял за внешнее переключение
                    row = (snap.get("accounts") or {}).get(act, {})
                    fh = (row.get("five_hour") or {}).get("pct")
                    sd = (row.get("seven_day") or {}).get("pct")
                    thr = cfg().get("threshold", 85)
                    if fh is not None and fh >= thr:
                        iso = (row.get("five_hour") or {}).get("resets_at")
                        try:
                            from datetime import datetime
                            until = datetime.fromisoformat(iso).timestamp()
                        except Exception:
                            until = time.time() + 5 * 3600
                        st["manual_hold"] = {"account": act, "until": until}
                    else:
                        st.pop("manual_hold", None)
                    jsave(STATE, st)
                    email = row.get("email", act)
                    tg_notify("👆 Claude: ручное переключение %s → %s (%s, сессия %s%%, неделя %s%%)."
                              % (prev_act or "?", act, email,
                                 fh if fh is not None else "?", sd if sd is not None else "?"))
            return self._send(200 if ok else 500, {"ok": ok, "message": out, "snapshot": snap})
        if u.path == "/api/recheck":
            # мгновенная перепроверка плана одного аккаунта в обход 10-минутного
            # _plan_cache — для кнопки "Я продлил": после оплаты Pro на стороне
            # Anthropic план обновляется за секунды, не хочется ждать до 10 мин
            name = body.get("account", "")
            if name not in profile_names():
                return self._send(400, {"ok": False, "message": "неизвестный аккаунт"})
            _plan_cache.pop(name, None)
            with lock:
                snap = collect(force=True)
            row = (snap.get("accounts") or {}).get(name, {})
            plan = row.get("plan")
            email = row.get("email", name)
            if plan and plan != "free":
                return self._send(200, {"ok": True, "plan": plan,
                    "message": f"✅ снова {plan.upper()} — вернул в ротацию."})
            if plan == "free":
                return self._send(200, {"ok": False, "plan": plan,
                    "message": "⏳ Anthropic ещё не обновил план (всё ещё Free) — попробуй через минуту."})
            return self._send(200, {"ok": False, "plan": plan,
                "message": "Не удалось проверить план: " + (row.get("error") or "?")})
        if u.path == "/api/model":
            ok, msg = set_default_model(body.get("model", ""))
            return self._send(200 if ok else 400, {"ok": ok, "message": msg, "model": model_info()})
        if u.path == "/api/session":
            ok, msg = send_session_command(body.get("cmd", ""))
            return self._send(200 if ok else 400, {"ok": ok, "message": msg})
        if u.path == "/api/config":
            c = cfg()
            for k in ("autoswitch", "threshold", "optimize"):
                if k in body:
                    c[k] = body[k]
            jsave(CONFIG, c)
            return self._send(200, {"ok": True, "autoswitch": c.get("autoswitch"),
                                    "threshold": c.get("threshold"), "optimize": c.get("optimize")})
        if u.path == "/api/relogin/start":
            # без lock: только спавнит изолированный процесс в своём temp HOME,
            # общие файлы (снапшот/профили) не трогает — блокировать остальных на 15с смысла нет
            name = body.get("account", "")
            ok, url_or_msg, email = relogin_start(name)
            if not ok:
                return self._send(400, {"ok": False, "message": url_or_msg})
            return self._send(200, {"ok": True, "url": url_or_msg, "email": email})
        if u.path == "/api/relogin/submit":
            # lock берёт сама relogin_submit (вокруг записи в профиль + collect) —
            # тут НЕ оборачивать: lock не реентерабельный, второй with lock = дедлок
            name = body.get("account", "")
            ok, message, snap = relogin_submit(name, body.get("code", ""))
            return self._send(200, {"ok": ok, "message": message})
        return self._send(404, {"error": "not found"})


PAGE = r"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude — лимиты аккаунтов</title>
<link rel="icon" href="data:,">
<style>
:root{--bg:#0f1115;--card:#181c24;--txt:#e8eaf0;--mut:#8b93a7;--ok:#34c07c;--warn:#e8b93e;--bad:#e05b5b;--acc:#7c9aff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:16px;max-width:640px;margin:0 auto}
.hdr{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:4px 0 14px}
h1{font-size:19px;margin:0}
.card{background:var(--card);border-radius:14px;padding:14px 16px;margin-bottom:12px;border:1px solid #232a36}
.card.active{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)}
.top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.email{font-weight:600;font-size:15px;word-break:break-all}
.tag{font-size:11px;padding:2px 8px;border-radius:99px;background:var(--acc);color:#0f1115;font-weight:700;white-space:nowrap}
.row{margin-top:10px}
.lbl{display:flex;justify-content:space-between;font-size:12.5px;color:var(--mut);margin-bottom:4px}
.bar{height:10px;border-radius:99px;background:#242b38;overflow:hidden}
.fill{height:100%;border-radius:99px;transition:width .5s}
button{background:var(--acc);border:0;color:#0f1115;font-weight:700;padding:8px 14px;border-radius:10px;font-size:13.5px;cursor:pointer;margin-top:12px}
button:disabled{opacity:.35;cursor:default}
.foot{display:flex;justify-content:space-between;align-items:center;color:var(--mut);font-size:12.5px;margin-top:6px;flex-wrap:wrap;gap:8px}
.err{color:var(--bad);font-size:13px;margin-top:8px}
.switchrow{display:flex;align-items:center;gap:8px;font-size:13.5px;color:var(--mut);margin-bottom:14px}
.switchrow input{transform:scale(1.25)}
#msg{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:#232a36;padding:10px 18px;border-radius:12px;font-size:14px;display:none;max-width:92vw}
.termwrap{display:flex;flex-direction:column;min-height:130px;margin-bottom:18px}
.termhead{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.termhead h2{font-size:15px;margin:0}
.termdot{width:8px;height:8px;border-radius:50%;background:var(--ok);flex:none}
.termdot.err{background:var(--bad)}
.termbox{background:#0b0d10;border:1px solid #232a36;border-radius:8px;padding:10px 12px;max-height:42vh;overflow-x:hidden;overflow-y:auto;margin:0;font:11px/1.3 ui-monospace,Consolas,monospace;color:#c8d0dc;white-space:pre-wrap;word-break:break-word;scrollbar-width:thin;scrollbar-color:#3a3f4b #14171c}
.termbox::-webkit-scrollbar{width:9px}
.termbox::-webkit-scrollbar-track{background:#14171c}
.termbox::-webkit-scrollbar-thumb{background:#3a3f4b;border-radius:99px;border:2px solid #14171c;background-clip:padding-box}
/* баннер лимитов/паузы — в норме скрыт целиком и места не занимает */
.ccpause{display:flex;gap:12px;align-items:flex-start;margin:0 0 14px;padding:12px 14px;border-radius:14px;background:var(--card);border:1px solid #232a36;border-left:4px solid var(--ccp-accent,var(--mut))}
.ccpause[hidden]{display:none}
.ccpause.lvl-hard{--ccp-accent:#e05b5b;background:linear-gradient(90deg,rgba(224,91,91,.10),rgba(224,91,91,0) 55%),var(--card)}
.ccpause.lvl-gate{--ccp-accent:#e8b93e;background:linear-gradient(90deg,rgba(232,185,62,.10),rgba(232,185,62,0) 55%),var(--card)}
.ccpause.lvl-pause{--ccp-accent:#a78bfa;background:linear-gradient(90deg,rgba(167,139,250,.12),rgba(167,139,250,0) 55%),var(--card)}
.ccp-dot{flex:none;width:10px;height:10px;margin-top:5px;border-radius:50%;background:var(--ccp-accent);box-shadow:0 0 0 0 var(--ccp-accent);animation:ccp-pulse 2.4s ease-out infinite}
@keyframes ccp-pulse{70%{box-shadow:0 0 0 7px rgba(255,255,255,0)}100%{box-shadow:0 0 0 0 rgba(255,255,255,0)}}
@media (prefers-reduced-motion:reduce){.ccp-dot{animation:none}}
.ccp-body{min-width:0;flex:1 1 auto}
.ccp-title{font-size:14px;font-weight:700;color:var(--txt);letter-spacing:.2px}
.ccp-title b{color:var(--ccp-accent)}
.ccp-sub{margin-top:3px;font-size:12.5px;line-height:1.5;color:#a7b0bd}
.ccp-sub .num{font-variant-numeric:tabular-nums;color:var(--txt);font-weight:600}
.ccp-meta{margin-top:6px;display:flex;flex-wrap:wrap;gap:6px}
.ccp-chip{font-size:11.5px;padding:2px 9px;border-radius:99px;background:#1b2029;border:1px solid #2a2f37;color:var(--mut);white-space:nowrap}
.ccp-chip b{color:var(--txt);font-weight:600}
.ccp-chip.hot{border-color:rgba(224,91,91,.45);color:#ffb1b1}
.ccp-timer{flex:none;text-align:right}
.ccp-timer .t{font-size:20px;font-weight:700;color:var(--ccp-accent);font-variant-numeric:tabular-nums;white-space:nowrap}
.ccp-timer .l{font-size:11px;color:var(--mut);margin-top:2px}
@media (max-width:620px){.ccpause{flex-wrap:wrap}.ccp-timer{text-align:left}}
</style></head><body>
<div class="hdr"><h1 id="h1">⚡ Claude — лимиты аккаунтов</h1><div id="langSwitch" style="font-size:12px;color:var(--mut);cursor:pointer;white-space:nowrap"></div></div>
<div class="ccpause" id="ccPause" hidden></div>
<div class="termwrap">
 <div class="termhead"><h2 id="consoleTitle">🖥 Консоль (только чтение)</h2><span class="termdot" id="termDot"></span></div>
 <pre class="termbox" id="termBox"><span id="termHistory"></span>
<span id="termCurrent">Загрузка…</span></pre>
</div>
<div class="switchrow">
 <input type="checkbox" id="auto"> <label for="auto" id="autoLbl">Авто-переключение при <span id="thrLbl">85</span>% сессии</label>
</div>
<div class="switchrow">
 <input type="checkbox" id="opt"> <label for="opt" id="optLbl">Оптимизация переключений лимитов (рулит сервис, ручные кнопки блокируются)</label>
</div>
<div id="cards">Загрузка…</div>
<div class="foot"><span id="upd"></span><button id="rf" style="margin-top:0">Обновить сейчас</button></div>
<div id="msg"></div>
<script>
const $=s=>document.querySelector(s);const TOKEN='__TOKEN__';const API=location.origin+'/cc-hook/';
const I18N={
 ru:{
  title:'Claude — лимиты аккаунтов',
  h1:'⚡ Claude — лимиты аккаунтов',
  console:'🖥 Консоль (только чтение)',
  loading:'Загрузка…',
  autoLbl:thr=>'Авто-переключение при <span id="thrLbl">'+thr+'</span>% сессии',
  optLbl:'Оптимизация переключений лимитов (рулит сервис, ручные кнопки блокируются)',
  optDisabledTitle:'Неактивно: включена оптимизация лимитов',
  refresh:'Обновить сейчас',
  updated:'Обновлено',
  active:'АКТИВНЫЙ',
  session5:'Сессия 5ч',
  week:'Неделя',
  resetIn:(h,mm,clock)=>`сброс через ${h?h+' ч ':''}${mm} мин (${clock})`,
  usingNow:'Используется сейчас',
  optimizeRules:'Рулит оптимизация',
  switchTo:'Переключиться',
  switchBlockedTitle:'Заблокировано: включена оптимизация переключений лимитов',
  extended:'✅ Я продлил',
  relogin:'🔑 Войти заново',
  relStarting:'Запускаю…',
  relChecking:'Проверяю код…',
  relPrompt:email=>`Открылась ссылка входа в новой вкладке.\nВойди под ${email} и вставь код авторизации сюда:`,
  confirmSwitch:n=>`Переключить активный аккаунт на ${n}?`,
  autoOn:'Авто-переключение включено',autoOff:'Авто-переключение выключено',
  optOn:'Оптимизация лимитов включена — ручные переключения заблокированы',
  optOff:'Оптимизация выключена — ручные переключения доступны',
  checking:'Проверяю…',
  checkErr:e=>`⚠ ошибка проверки: ${e}`,
  staleAt:t=>` · ниже данные на ${t}`,
  ccpPauseTitle:'⏸ Claude на <b>паузе по лимитам</b> — подъём автоматический',
  ccpDefReason:'лимиты сессионного окна',
  ccpPauseSub:(reason,at)=>'Причина: '+reason+(at?`. Будильник на <span class="num">${at}</span>: окно перепроверяется само, команда не нужна.`:'.'),
  ccpHardTitle:'⛔ Уперлись в сессионные лимиты — <b>переключаться некуда</b>',
  ccpHardSub:thr=>`Все аккаунты выше ${thr}%. Фоновые задачи не стартуют, чтобы не добить окно; балансер переключится, как только освободится ближайшее.`,
  ccpGateTitle:'⏸ Активный аккаунт забит — <b>фоновые задачи приостановлены</b>',
  ccpGateSub:(n,p,thr)=>`${n} на <span class="num">${p}</span> (порог ${thr}%). Свободный аккаунт есть — ждём переключения балансера, после него задачи пойдут сами.`,
  ccpActive:' · активный',
  ccpChecks:n=>`перепроверок окна: <b>${n}</b>`,
  ccpTillWake:'до подъёма',
  ccpTillNearest:'до ближайшего окна',
  ccpTillReset:'до сброса окна',
  ccpLeft:(h,m,s)=>h?`${h} ч ${m} мин`:`${m} мин ${s} с`,
 },
 en:{
  title:'Claude — Account Limits',
  h1:'⚡ Claude — Account Limits',
  console:'🖥 Console (read-only)',
  loading:'Loading…',
  autoLbl:thr=>'Auto-switch at <span id="thrLbl">'+thr+'</span>% of session',
  optLbl:'Limit optimization (service decides, manual buttons blocked)',
  optDisabledTitle:'Inactive: limit optimization is on',
  refresh:'Refresh now',
  updated:'Updated',
  active:'ACTIVE',
  session5:'Session 5h',
  week:'Week',
  resetIn:(h,mm,clock)=>`resets in ${h?h+'h ':''}${mm}m (${clock})`,
  usingNow:'In use now',
  optimizeRules:'Optimizer active',
  switchTo:'Switch to this',
  switchBlockedTitle:'Blocked: limit-switch optimization is on',
  extended:'✅ I renewed',
  relogin:'🔑 Log in again',
  relStarting:'Starting…',
  relChecking:'Checking code…',
  relPrompt:email=>`A login link opened in a new tab.\nSign in as ${email} and paste the authorization code here:`,
  confirmSwitch:n=>`Switch the active account to ${n}?`,
  autoOn:'Auto-switch enabled',autoOff:'Auto-switch disabled',
  optOn:'Limit optimization enabled — manual switching blocked',
  optOff:'Optimization disabled — manual switching available',
  checking:'Checking…',
  checkErr:e=>`⚠ check failed: ${e}`,
  staleAt:t=>` · data below from ${t}`,
  ccpPauseTitle:'⏸ Claude is <b>paused on limits</b> — it resumes on its own',
  ccpDefReason:'session window limits',
  ccpPauseSub:(reason,at)=>'Reason: '+reason+(at?`. Alarm at <span class="num">${at}</span>: the window is re-checked automatically, no command needed.`:'.'),
  ccpHardTitle:'⛔ Session limits reached — <b>nothing to switch to</b>',
  ccpHardSub:thr=>`All accounts are above ${thr}%. Background jobs stay down so they don't burn the rest of the window; the balancer switches as soon as the nearest one resets.`,
  ccpGateTitle:'⏸ Active account is full — <b>background jobs paused</b>',
  ccpGateSub:(n,p,thr)=>`${n} is at <span class="num">${p}</span> (threshold ${thr}%). A free account exists — waiting for the balancer to switch, after that jobs resume by themselves.`,
  ccpActive:' · active',
  ccpChecks:n=>`window re-checks: <b>${n}</b>`,
  ccpTillWake:'until resume',
  ccpTillNearest:'until nearest window',
  ccpTillReset:'until window reset',
  ccpLeft:(h,m,s)=>h?`${h}h ${m}m`:`${m}m ${s}s`,
 },
};
let LANG='ru';
try{LANG=localStorage.getItem('cc_lang')||'ru';}catch(e){}
function tr(k,...a){const v=I18N[LANG][k];return typeof v==='function'?v(...a):v;}
function setLang(l){LANG=l;try{localStorage.setItem('cc_lang',l);}catch(e){}applyI18n();}
function renderLangSwitch(){
 $('#langSwitch').innerHTML=LANG==='ru'
  ?'<b style="color:var(--txt)">RU</b> · <span onclick="setLang(\'en\')" style="cursor:pointer;text-decoration:underline">EN</span>'
  :'<span onclick="setLang(\'ru\')" style="cursor:pointer;text-decoration:underline">RU</span> · <b style="color:var(--txt)">EN</b>';
}
let THR=85,lastSnap=null;
function renderAutoLbl(){$('#autoLbl').innerHTML=tr('autoLbl',THR);}
function applyI18n(){
 document.title=tr('title');document.documentElement.lang=LANG;
 $('#h1').textContent=tr('h1');$('#consoleTitle').textContent=tr('console');
 $('#optLbl').textContent=tr('optLbl');$('#rf').textContent=tr('refresh');
 renderAutoLbl();renderLangSwitch();
 const opt=!!(lastSnap&&lastSnap.config&&lastSnap.config.optimize);
 $('#auto').parentElement.title=opt?tr('optDisabledTitle'):'';
 if(typeof ccpRender==='function')ccpRender();  // смена языка перерисовывает баннер без запроса
 if(lastSnap){
  renderCards(lastSnap);
  $('#upd').textContent=tr('updated')+' '+new Date(lastSnap.ts*1000).toLocaleTimeString(LANG==='en'?'en-GB':'ru');
 }
}
async function ccConsoleHistory(){
 try{
  const r=await fetch(API+'console?token='+TOKEN+'&history=1');const d=await r.json();
  if(d.ok&&d.history!=null){const box=$('#termBox');$('#termHistory').innerHTML=d.history;box.scrollTop=box.scrollHeight;}
 }catch(e){}
}
async function ccConsole(){
 const box=$('#termBox'),dot=$('#termDot');
 try{
  const r=await fetch(API+'console?token='+TOKEN);const d=await r.json();
  if(!d.ok||d.current==null){dot.className='termdot err';return;}
  dot.className='termdot';
  const atBottom=box.scrollTop+box.clientHeight>=box.scrollHeight-20;
  $('#termCurrent').innerHTML=d.current||'';
  if(atBottom)box.scrollTop=box.scrollHeight;
 }catch(e){dot.className='termdot err';}
}
ccConsoleHistory();ccConsole();setInterval(ccConsole,2000);
function col(p){return p==null?'#555':p<60?'var(--ok)':p<85?'var(--warn)':'var(--bad)'}
function rst(iso){if(!iso)return'';const d=new Date(iso),m=Math.max(0,Math.round((d-Date.now())/60000));
 const h=Math.floor(m/60),mm=m%60;return tr('resetIn',h,mm,d.toLocaleTimeString(LANG==='en'?'en-GB':'ru',{hour:'2-digit',minute:'2-digit'}))}
function bar(lbl,o){o=o||{};const p=o.pct;return`<div class="row"><div class="lbl"><span>${lbl}: <b style="color:${col(p)}">${p==null?'?':p+'%'}</b></span><span>${rst(o.resets_at)}</span></div>
 <div class="bar"><div class="fill" style="width:${p||0}%;background:${col(p)}"></div></div></div>`}
function renderCards(d){
 const opt=!!(d.config&&d.config.optimize);
 $('#cards').innerHTML=Object.entries(d.accounts).map(([n,a])=>`
  <div class="card ${a.active?'active':''}">
   <div class="top"><span class="email">${a.email}</span><span>${a.plan==='free'?'<span class="tag" style="background:#2c3547;color:var(--mut)">FREE</span> ':a.plan?'<span class="tag" style="background:var(--acc);color:#0f1115">'+a.plan.toUpperCase()+'</span> ':''}${a.active?'<span class="tag">'+tr('active')+'</span>':''}</span></div>
   ${a.error?`<div class="err">⚠ ${a.error}${a.stale_ts?tr('staleAt',new Date(a.stale_ts*1000).toLocaleTimeString(LANG==='en'?'en-GB':'ru',{hour:'2-digit',minute:'2-digit'})):''}</div>`:''}${a.five_hour?bar(tr('session5'),a.five_hour)+bar(tr('week'),a.seven_day):''}
   <button onclick="sw('${n}')" ${a.active||opt?'disabled':''} ${opt&&!a.active?'title="'+tr('switchBlockedTitle')+'"':''}>${a.active?tr('usingNow'):opt?tr('optimizeRules'):tr('switchTo')}</button>
   ${a.plan==='free'?`<button onclick="recheck('${n}',this)" style="margin-top:6px;background:var(--acc);color:#0f1115">${tr('extended')}</button>`:''}
   <button onclick="relogin('${n}',this)" style="margin-top:6px;margin-left:8px;background:transparent;border:1px solid #333c4d;color:var(--mut)">${tr('relogin')}</button>
  </div>`).join('');
}
async function load(refresh){
 const r=await fetch(API+'limits?token='+TOKEN+(refresh?'&refresh=1':''));const d=await r.json();
 lastSnap=d;
 $('#auto').checked=!!(d.config&&d.config.autoswitch);
 const opt=!!(d.config&&d.config.optimize);$('#opt').checked=opt;
 $('#auto').disabled=opt;$('#auto').parentElement.style.opacity=opt?'.5':'';
 $('#auto').parentElement.title=opt?tr('optDisabledTitle'):'';
 if(d.config&&d.config.threshold)THR=d.config.threshold;
 renderAutoLbl();renderCards(d);
 $('#upd').textContent=tr('updated')+' '+new Date(d.ts*1000).toLocaleTimeString(LANG==='en'?'en-GB':'ru');
}
function toast(t){const m=$('#msg');m.textContent=t;m.style.display='block';setTimeout(()=>m.style.display='none',4000)}
async function sw(n){
 if(!confirm(tr('confirmSwitch',n)))return;
 const r=await fetch(API+'switch?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:n})});
 const d=await r.json();toast(d.ok?'✅ '+d.message.split('\n')[0]:'⚠ '+d.message);load();
}
$('#auto').addEventListener('change',async e=>{
 await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({autoswitch:e.target.checked})});
 toast(e.target.checked?tr('autoOn'):tr('autoOff'));
});
$('#opt').addEventListener('change',async e=>{
 await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({optimize:e.target.checked})});
 toast(e.target.checked?tr('optOn'):tr('optOff'));load();
});
async function recheck(n,btn){
 btn.disabled=true;const orig=btn.textContent;btn.textContent=tr('checking');
 try{
  const r=await fetch(API+'recheck?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:n})});
  const d=await r.json();toast(d.message);
 }catch(e){toast(tr('checkErr',e));}
 finally{btn.disabled=false;btn.textContent=orig;load();}
}
async function relogin(n,btn){
 btn.disabled=true;const orig=btn.textContent;btn.textContent=tr('relStarting');
 try{
  const r=await fetch(API+'relogin/start?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:n})});
  const d=await r.json();
  if(!d.ok){toast('⚠ '+d.message);return;}
  window.open(d.url,'_blank');
  const code=prompt(tr('relPrompt',d.email||n));
  if(code==null)return;
  btn.textContent=tr('relChecking');
  const r2=await fetch(API+'relogin/submit?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:n,code})});
  const d2=await r2.json();toast(d2.ok?d2.message:'⚠ '+d2.message);
 }catch(e){toast('⚠ '+e);}
 finally{btn.disabled=false;btn.textContent=orig;load();}
}
$('#rf').addEventListener('click',()=>{$('#rf').disabled=true;load(1).finally(()=>$('#rf').disabled=false)});

// ---- баннер лимитов/паузы ----
// Данные тянем раз в 20 с, а обратный отсчёт тикает локально каждую секунду —
// чтобы цифра жила, но сервер не дёргался лишний раз.
let ccpData=null;
const ccpEsc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function ccpLeft(untilMs){
 const s=Math.max(0,Math.round((untilMs-Date.now())/1000));
 const h=Math.floor(s/3600),m=Math.floor(s%3600/60);
 return tr('ccpLeft',h,h?String(m).padStart(2,'0'):m,String(s%60).padStart(2,'0'));
}
function ccpAt(ms){return new Date(ms).toLocaleTimeString(LANG==='en'?'en-GB':'ru',{hour:'2-digit',minute:'2-digit'});}
function ccpRender(){
 const el=$('#ccPause'),d=ccpData;if(!el)return;
 const pause=(d&&d.pause)||{},lvl=(d&&d.level)||'none';
 if(!d||d.stale||(lvl==='none'&&!pause.active)){el.hidden=true;return;}
 // приоритет: пауза (в ней уже есть будильник) > переключаться некуда > активный забит
 const mode=pause.active?'pause':lvl;
 const near=(d.nearest&&d.nearest.resets_at)?new Date(d.nearest.resets_at).getTime():0;
 const thr=Math.round(d.threshold||90);
 let title,sub,timer=null,tlabel='';
 if(mode==='pause'){
  const upMs=(pause.resume_at||0)*1000;
  title=tr('ccpPauseTitle');
  sub=tr('ccpPauseSub',ccpEsc(pause.reason||tr('ccpDefReason')),upMs?ccpAt(upMs):'')
    +(pause.note?'<br>'+ccpEsc(pause.note):'');
  if(upMs){timer=upMs;tlabel=tr('ccpTillWake');}
 }else if(mode==='hard'){
  title=tr('ccpHardTitle');sub=tr('ccpHardSub',thr);
  if(near){timer=near;tlabel=tr('ccpTillNearest');}
 }else{
  const a=(d.accounts||{})[d.active]||{};
  title=tr('ccpGateTitle');
  sub=tr('ccpGateSub',ccpEsc(d.active||'?'),a.pct==null?'?':a.pct+'%',thr);
  if(a.resets_at){timer=new Date(a.resets_at).getTime();tlabel=tr('ccpTillReset');}
 }
 const chips=Object.entries(d.accounts||{}).map(([n,a])=>
  '<span class="ccp-chip'+(a.pct!=null&&a.pct>thr?' hot':'')+'">'+ccpEsc(n)
  +(a.active?tr('ccpActive'):'')+' <b>'+(a.pct==null?'?':a.pct+'%')+'</b></span>').join('');
 el.className='ccpause lvl-'+mode;el.hidden=false;
 el.innerHTML='<span class="ccp-dot"></span><div class="ccp-body"><div class="ccp-title">'+title+'</div>'
  +'<div class="ccp-sub">'+sub+'</div><div class="ccp-meta">'+chips
  +(pause.active&&pause.checks?'<span class="ccp-chip">'+tr('ccpChecks',pause.checks)+'</span>':'')
  +'</div></div>'
  +(timer?'<div class="ccp-timer" data-until="'+timer+'"><div class="t">'+ccpLeft(timer)+'</div>'
    +'<div class="l">'+tlabel+'</div></div>':'');
}
function ccpTick(){
 const t=$('#ccPause .ccp-timer');if(!t)return;
 const until=+t.dataset.until;
 t.querySelector('.t').textContent=ccpLeft(until);
 if(Date.now()>until+60000)ccpLoad();  // окно должно было отпустить — перечитаем
}
async function ccpLoad(){
 try{const r=await fetch(API+'pause?token='+TOKEN);ccpData=await r.json();}catch(e){ccpData=null;}
 ccpRender();
}
applyI18n();load();setInterval(()=>load(),60000);
ccpLoad();setInterval(ccpLoad,20000);setInterval(ccpTick,1000);
</script></body></html>"""


if __name__ == "__main__":
    threading.Thread(target=poll_loop, daemon=True).start()
    threading.Thread(target=_dialog_watchdog, daemon=True).start()
    port = cfg().get("port", 8877)
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"cc-limits up on 127.0.0.1:{port}", flush=True)
    srv.serve_forever()
