#!/usr/bin/env python3
# cc-limits — мониторинг лимитов Pro/Max-аккаунтов Claude Code + авто-переключение.
# Запуск: systemd unit (порт задаётся в config.json, ключ "port", по умолчанию 8877;
# снаружи — через nginx /cc/, см. install.sh).
import fcntl, html, json, os, random, re, shutil, struct, subprocess, tempfile, termios, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pyte
import cc_avail
import cc_backup
import cc_codex
import cc_codex_bridge
import cc_codex_console
import cc_codex_emergency
import cc_cli_notice
import cc_model_notice
import cc_remote
import cc_lock
import cc_disconnect
import cc_poll
import cc_update
import pexpect

VERSION = "2.0.45"  # равна версии релиза; cc_update сверяет её с манифестом перед заменой файлов

# BASE/PROFILES переопределяемы через env только для изолированного тестирования
# инсталлятора (install.sh их не трогает — на реальном сервере это фиксированные пути,
# один Claude Code живёт в одном /root на VDS).
BASE = os.environ.get("CC_LIMITS_BASE", "/opt/cc-limits")
PROFILES = os.environ.get("CC_LIMITS_PROFILES", "/root/.claude-profiles")
BACKUP_DIR = os.path.join(BASE, "profile_backups")  # копии профилей аккаунтов (cc_backup): сутки + при новом входе, 14 штук
LIVE_CREDS = "/root/.claude/.credentials.json"
LIVE_CFG = "/root/.claude.json"
TG_ENV = "/root/.claude/channels/telegram/.env"
CONFIG = os.path.join(BASE, "config.json")
SNAPSHOT = os.path.join(BASE, "snapshot.json")
STATE = os.path.join(BASE, "state.json")
SWITCH_LOG = os.path.join(BASE, "switch_log.jsonl")  # аудит forced-веток optimize_check
POLL_STATE = os.path.join(BASE, "poll_state.json")  # расписание опроса по аккаунтам (cc_poll)
FAIL_LOG = os.path.join(BASE, "usage_fail.jsonl")  # журнал сбоев опроса: подбирать константы cc_poll
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
    # tmp с pid и потоком: два писателя (поток опроса и HTTP-запрос панели) не делят один .tmp
    cc_lock.atomic_write(path, json.dumps(data, indent=1, ensure_ascii=False), 0o600)


def cfg():
    return jload(CONFIG, {})


# консольные команды балансера (cl, cla, cln, clw — Claude; cxw — Codex): один скрипт cc-cmd, имена — ссылки на него
CMD_NAMES = ("cl", "cla", "cln", "clw", "cxw")


def ensure_cmd_links(bin_dir="/usr/local/bin"):
    """Ссылки команд на BASE/cc-cmd в bin_dir (при старте сервиса — после установки и после каждого обновления).
    Чужое не трогаем: файл с таким именем или другая программа с таким именем в PATH — пропуск.
    → {имя: 'создана' | 'есть' | 'пропущена: …'}."""
    src = os.path.join(BASE, "cc-cmd")
    out = {}
    if not os.path.isfile(src):
        return out
    for n in CMD_NAMES:
        p = os.path.join(bin_dir, n)
        try:
            if os.path.islink(p):
                cur = os.readlink(p)
                if cur == src:
                    out[n] = "есть"
                    continue
                if os.path.basename(cur) != "cc-cmd":
                    out[n] = "пропущена: чужая ссылка"
                    continue
                os.remove(p)  # наша ссылка со старого места установки — перекладываем
            elif os.path.exists(p):
                out[n] = "пропущена: файл не наш"
                continue
            elif shutil.which(n):
                out[n] = "пропущена: имя занято в PATH"
                continue
            os.symlink(src, p)
            out[n] = "создана"
        except OSError as e:
            out[n] = "пропущена: " + str(e)[:80]
    return out


def http_json(url, payload=None, headers=None, timeout=20):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {})
    # без нормального UA WAF Anthropic отдаёт 403
    req.add_header("User-Agent", "claude-cli/2.0 (external, cli)")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def tg_token():
    """Токен бота: сначала файл телеграм-канала Claude Code, потом ключ "bot_token"
    в config.json. Второй путь — для тех, у кого канал не настроен: без него
    уведомления не уходили вообще, даже с заданным chat_id."""
    try:
        m = re.search(r"TELEGRAM_BOT_TOKEN=(\S+)", open(TG_ENV).read())
        if m:
            return m.group(1)
    except Exception:
        pass
    return (cfg().get("bot_token") or "").strip()


def tg_notify(text):
    chat_id = cfg().get("chat_id")
    if not chat_id:
        return False
    token = tg_token()
    if not token:
        print("tg_notify: notification token unavailable", flush=True)
        return False
    try:
        result = http_json(f"https://api.telegram.org/bot{token}/sendMessage",
                           {"chat_id": chat_id, "text": text})
        return bool(result.get("ok"))
    except Exception as e:
        # Exceptions can include the request URL and therefore the bot token.
        print("tg_notify fail:", type(e).__name__, flush=True)
        return False


cc_codex.NOTIFY = tg_notify  # вход в ChatGPT завершён — сообщение в телеграм


def _codex_say(text):
    """Сообщение про Codex: в чат Codex, если мост настроен, иначе — в общий чат уведомлений."""
    return bool(cc_codex_bridge.BRIDGE.send(text)) or tg_notify(text)


# сообщения в Telegram: смена модели/effort в панели и обновления Claude Code и Codex (выключатели в config.json: model_change_notify, cli_update_notify)
cc_model_notice.ENABLED = lambda: cfg().get("model_change_notify", True) is not False
cc_model_notice.SEND = {"claude": lambda text: tg_notify(text), "codex": _codex_say}
cc_cli_notice.STATE = os.path.join(BASE, "cli_notice.json")
cc_cli_notice.ENABLED = lambda: cfg().get("cli_update_notify", True) is not False
cc_cli_notice.SEND = {"claude": lambda text: tg_notify(text), "codex": _codex_say}


def codex_bin():
    """Путь к codex (config.json → "codex_bin", затем PATH/типичные места); None — Codex не установлен."""
    return cc_codex.find_bin(cfg().get("codex_bin"))


# Codex запускается от отдельного пользователя ОС ("codex_user"), чтобы не видеть /root; мост Telegram — тоже через него
cc_codex.RUN_AS = lambda: cfg().get("codex_user") or None
# каталог профилей аккаунтов ChatGPT: переменная CC_CODEX_PROFILES, иначе config.json "codex_profiles" (читается при старте)
cc_codex.PROFILES = os.environ.get("CC_CODEX_PROFILES") or cfg().get("codex_profiles") or cc_codex.PROFILES
cc_codex.INSTALL_PREFIX = lambda: os.path.join(BASE, "codex-cli")  # кнопка «Установить Codex» в панели ставит сюда


def _codex_installed(path):
    c = cfg()  # без lock — как /api/config
    c["codex_bin"] = path
    jsave(CONFIG, c)


cc_codex.ON_INSTALLED = _codex_installed
cc_codex_bridge.BASE = BASE
cc_codex_bridge.BIN = codex_bin
cc_codex_bridge.SESSION = lambda: cfg().get("screen_session", "claude")
cc_codex_bridge.DEFAULT_CHAT = lambda: cfg().get("chat_id")
cc_codex_bridge.RESERVED_TOKENS = lambda: [tg_token(), (cfg().get("bot_token") or "").strip()]


def _codex_console_plan():
    """Права и папка консоли Codex — те же, что у моста Telegram (настройки «Доступ»/режим); → (песочница, папка, слот)."""
    s = cc_codex_bridge.load()
    sandbox, cwd = cc_codex_bridge.plan(s)
    return sandbox, cwd, s.get("slot")


cc_codex_console.BASE = BASE
cc_codex_console.BIN = codex_bin
cc_codex_console.PLAN = _codex_console_plan
cc_codex_console.pyte = pyte
cc_codex_bridge.CONSOLE = cc_codex_console  # мост ведёт разговор в консоли Codex, а не отдельным запуском
# аварийный режим Codex: полный доступ к проекту на время, когда Claude недоступен (config.json → "codex_emergency")
cc_codex_emergency.BASE = BASE
cc_codex_emergency.CONFIG = lambda: cfg().get("codex_emergency") or {}
cc_codex_emergency.NOTIFY = tg_notify
cc_codex.EXTRA_ENV = cc_codex_emergency.env_extra
# строка про самостоятельный профиль Codex Full в AGENTS.md (cc_profiles подменяет PROFILE_NOTE, когда профилями ведает панель)
cc_codex_bridge.SOLO_PROFILE = lambda: cc_codex_bridge.active_profile(cc_codex_bridge.load()) == "codex_solo_full"
cc_codex_bridge.PROFILE_NOTE = cc_codex_bridge.solo_note
cc_codex_bridge.PROFILE_APPLIED = cc_codex_emergency._restart_console
cc_codex_bridge.EMERGENCY = cc_codex_emergency


# автообновление из GitHub Releases (cc_update.py): проверка раз в 6 часов, ручной/авто режим
UPDATER = cc_update.Updater(BASE, VERSION, cfg, notify=tg_notify)


def profile_names():
    if not os.path.isdir(PROFILES):
        return []
    return sorted(n for n in os.listdir(PROFILES)
                  if not n.startswith("_") and os.path.isfile(f"{PROFILES}/{n}/oauth_account.json")
                  and not os.path.exists(f"{PROFILES}/{n}/{cc_disconnect.MARKER}"))


def active_name():
    uuid = (jload(LIVE_CFG, {}) or {}).get("oauthAccount", {}).get("accountUuid")
    for n in profile_names():
        oa = jload(f"{PROFILES}/{n}/oauth_account.json", {})
        if oa.get("accountUuid") == uuid:
            return n
    return None


def _exchange_tokens(creds_path, full):
    # Обмен refresh-токена на свежую пару; сохраняет на место атомарно. Прочие ключи файла
    # (например mcpOAuth, которые ведёт сам Claude Code) остаются как были.
    c = full["claudeAiOauth"]
    r = http_json("https://platform.claude.com/v1/oauth/token",
                  {"grant_type": "refresh_token", "refresh_token": c["refreshToken"],
                   "client_id": CLIENT_ID})
    c["accessToken"] = r["access_token"]
    c["refreshToken"] = r.get("refresh_token", c["refreshToken"])
    c["expiresAt"] = int(time.time() * 1000) + int(r.get("expires_in", 28800)) * 1000
    jsave(creds_path, full)
    return c


def refresh_tokens(creds_path):
    if creds_path != LIVE_CREDS:  # профильные файлы пишем только мы
        return _exchange_tokens(creds_path, jload(creds_path))
    # Живой файл делит с нами сам Claude Code, а refresh-токен одноразовый: два одновременных
    # обмена — один из них получит invalid_grant и сбросит логин. Поэтому берём тот же замок,
    # что и CLI, и читаем файл заново уже под замком: пока ждали, CLI мог обновить токен сам.
    with cc_lock.oauth_lock(os.path.dirname(LIVE_CREDS), os.path.dirname(LIVE_CFG)):
        full = jload(creds_path)
        if full["claudeAiOauth"]["expiresAt"] / 1000 - time.time() >= 120:
            return full["claudeAiOauth"]
        return _exchange_tokens(creds_path, full)


def _login_expires(name, act):
    # Срок жизни логина: refreshTokenExpiresAt в credentials.json — абсолютная дата
    # (~28 дней от настоящего /login), refresh её НЕ продлевает. После неё аккаунт
    # отваливается с «Login expired», лечится только «Войти заново». У активного профиля
    # истину ведёт live-файл CLI, у остальных — файл профиля. Сами токены наружу не уходят.
    from datetime import datetime, timezone
    try:
        path = LIVE_CREDS if name == act else f"{PROFILES}/{name}/credentials.json"
        ms = (jload(path, {}) or {}).get("claudeAiOauth", {}).get("refreshTokenExpiresAt")
        if not ms and name == act:
            ms = (jload(f"{PROFILES}/{name}/credentials.json", {}) or {}).get("claudeAiOauth", {}).get("refreshTokenExpiresAt")
        if not ms:
            return None
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None


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
    for n in [n for n, st in list(_relogin.items()) if now - st["started"] > _RELOGIN_TTL]:
        _relogin_cleanup(n)


def relogin_start(name, new_email=None):
    # new_email=None — перелогин существующего аккаунта; строка (может быть пустой) —
    # вход нового аккаунта в свободный слот name (см. addacct_start)
    _relogin_sweep()
    if new_email is None:
        if name not in profile_names():
            return False, "неизвестный аккаунт", None
        oa = jload(f"{PROFILES}/{name}/oauth_account.json", {})
        email = oa.get("emailAddress", "")
    else:
        if not _ACC_RE.match(name or ""):
            return False, "неверное имя слота", None
        email = new_email
    _relogin_cleanup(name)  # если была брошенная попытка — начинаем чисто
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
    _relogin[name] = {"child": child, "home": home, "started": time.time(), "new": new_email is not None}
    return True, url, email


def relogin_submit(name, code, new=False, lang="ru"):
    st = _relogin.get(name)
    # попытка нового аккаунта (слот ещё без профиля) завершается только через add/submit, и наоборот
    if not st or bool(st.get("new")) != bool(new):
        return False, _t(lang, "Нет активной попытки для этого аккаунта — начни заново.",
                         "No sign-in in progress for this account — start again."), None
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
        return False, _t(lang,
                         "Логин не завершился — код мог быть неверным, просроченным или ещё не подтверждён в браузере. Попробуй ещё раз (кнопка «Войти заново» заново) или проверь, что вход в браузере точно завершён.",
                         "Sign-in did not complete — the code may be wrong, expired, or not yet confirmed in the browser. Try again (the Log in again button) or make sure the browser sign-in really finished."), None
    with lock:  # один захват на весь критический участок — collect() ниже lock уже не берёт
        keep_login = False
        try:
            creds = jload(creds_path)
            oa = (jload(os.path.join(home, ".claude.json"), {}) or {}).get("oauthAccount")
            if new:
                # без accountUuid профиль не опознать (ни в ротации, ни как активный)
                if not (oa and oa.get("accountUuid")):
                    return False, _t(lang, "Вход прошёл, но Claude Code не вернул данные аккаунта — попробуй ещё раз.",
                                     "Signed in, but Claude Code returned no account data — try again."), None
                dup = next((n for n in _real_names()
                            if (jload(f"{PROFILES}/{n}/oauth_account.json", {}) or {}).get("accountUuid") == oa["accountUuid"]), None)
                if dup:
                    em = oa.get('emailAddress', '?')
                    return False, _t(lang, f"Этот аккаунт ({em}) уже в ротации как {dup} — второй раз добавлять не нужно.",
                                     f"This account ({em}) is already in the rotation as {dup} — no need to add it twice."), None
                if name in _real_names():  # слот заняли, пока шёл вход
                    return False, _t(lang, "Слот уже занят — начни добавление заново.",
                                     "That slot has just been taken — start adding again."), None
                os.makedirs(f"{PROFILES}/{name}", exist_ok=True)
                os.chmod(f"{PROFILES}/{name}", 0o700)  # слот установщика мог быть создан с 755
            jsave(f"{PROFILES}/{name}/credentials.json", creds)
            if oa:
                jsave(f"{PROFILES}/{name}/oauth_account.json", oa)
            act = active_name()
            if act == name:  # перелогинили АКТИВНЫЙ профиль — продублировать в live-файлы
                try:
                    cc_lock.swap_live(LIVE_CREDS, creds, LIVE_CFG, oa,
                                      os.path.dirname(LIVE_CREDS), os.path.dirname(LIVE_CFG))
                except cc_lock.LockTimeout:
                    keep_login = True  # вход уже выполнен — оставляем его, повтор подхватит те же файлы
                    return False, _t(lang,
                                     "Вход выполнен, но Claude Code сейчас обновляет логин — живая сессия не тронута. Нажми «Отправить» ещё раз через минуту.",
                                     "Signed in, but Claude Code is refreshing its login right now — the live session was left untouched. Press Submit again in a minute."), None
        finally:
            if not keep_login:
                _relogin_cleanup(name)
        _plan_cache.pop(name, None)
        snap = collect(force=True, force_account=name)  # перелогиненный аккаунт читаем заново, не из кэша
    row = (snap.get("accounts") or {}).get(name, {})
    email = row.get("email", name)
    if new:
        cnt, names = _rotation_text()
        plan = row.get("plan")
        tg_notify(f"➕ Claude: аккаунт {name} ({email}" + (f", {plan.upper()}" if plan else "")
                  + f") добавлен в ротацию. Теперь в ротации: {cnt} ({names})."
                  + (" ⚠️ Сейчас это Free — в авто-переключении он не участвует, пока не станет Pro." if plan == "free" else ""))
        return True, _t(lang, f"✅ {email} добавлен в ротацию как {name}.",
                        f"✅ {email} added to the rotation as {name}."), snap
    tg_notify(f"🔑 Claude: аккаунт {name} ({email}) перелогинен через сайт — токен обновлён.")
    return True, _t(lang, f"✅ {email} — вход выполнен, токен обновлён.",
                    f"✅ {email} — signed in, token refreshed."), snap


# ---------------------------------------------------------------- добавление и удаление аккаунтов
def _t(lang, ru, en):
    # серверные тексты для окон добавления/удаления: язык берётся из тела запроса (по умолчанию ru)
    return en if lang == "en" else ru


# Отключение удаляет только авторизацию; история и файлы сохраняются. Слово
# подтверждения проверяет сервер, в том числе при прямом вызове API.
DELETE_WORDS = ("подтверждаю", "confirm")  # русское слово — основное, английское — для EN-интерфейса
_ACC_RE = re.compile(r"^acc[0-9]{1,3}$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")


def _is_real(name):
    # «настоящий» профиль: аккаунт сохранён (accountUuid + токены), а не пустой слот установщика
    oa = jload(f"{PROFILES}/{name}/oauth_account.json", {}) or {}
    return bool(oa.get("accountUuid")) and os.path.isfile(f"{PROFILES}/{name}/credentials.json")


def _real_names():
    return [n for n in profile_names() if _is_real(n)]


def _rotation_text():
    names = _real_names()
    return len(names), ", ".join(names) or "—"


def _free_slot():
    # первый пустой слот установщика (oauth_account.json = {}), иначе следующий номер
    nums = []
    if os.path.isdir(PROFILES):
        for d in os.listdir(PROFILES):
            if _ACC_RE.match(d) and os.path.isdir(f"{PROFILES}/{d}"):
                nums.append(int(d[3:]))
    for n in sorted(nums):
        d = f"{PROFILES}/acc{n}"
        oa = jload(f"{d}/oauth_account.json", {}) or {}
        if (not oa.get("accountUuid") and not os.path.isfile(f"{d}/credentials.json")
                and not os.path.exists(f"{d}/{cc_disconnect.MARKER}")):
            return f"acc{n}"
    return f"acc{max(nums, default=0) + 1}"


def addacct_start(email, lang="ru"):
    """→ (ok, url|message, slot, email). Почта необязательна: уходит в ссылку входа как подсказка."""
    email = (email or "").strip()
    if email and not _EMAIL_RE.match(email):
        return False, _t(lang, "Почта выглядит некорректно.", "The email looks invalid."), None, None
    slot = _free_slot()
    ok, url_or_msg, em = relogin_start(slot, new_email=email)
    return ok, url_or_msg, slot, em


def _move_off(name):
    """Активный аккаунт удаляют — сначала перевести живую сессию на другой. → (target|None, причина)."""
    accs = (jload(SNAPSHOT) or {}).get("accounts") or {}
    c = cfg()
    thr, cap = c.get("threshold", 85), c.get("weekly_cap", 99)
    cands = []
    for n in _real_names():
        if n == name:
            continue
        row = accs.get(n) or {}
        if row.get("plan") == "free":
            continue  # cc-switch на Free всё равно откажет
        free_now = bool(row) and cc_avail.availability(row, thr, cap)[0]
        fh = (row.get("five_hour") or {}).get("pct")
        cands.append((0 if free_now else 1, fh if fh is not None else 101, n))
    last = "нет другого пригодного аккаунта (остальные Free или без токенов)"
    for _a, _b, n in sorted(cands):
        ok, out = do_switch(n)
        if ok:
            return n, ""
        last = out
    return None, last


def backup_status():
    """Для окна ⚙: копии профилей, их свежесть и что из потерянного можно вернуть."""
    d = cc_backup.listing(PROFILES, BACKUP_DIR)
    d["enabled"] = cfg().get("profile_backup", True) is not False
    d["keep"] = cc_backup.KEEP
    return d


def delete_account(name, confirm, lang="ru"):
    """Disconnect a Claude login. Retain its directory and all non-authentication data."""
    if (confirm or "").strip().lower() not in DELETE_WORDS:
        return False, _t(lang, "Слово подтверждения введено неверно — ничего не удалено.",
                         "The confirmation word is wrong — nothing was deleted."), None
    if not _ACC_RE.match(name or "") or name not in profile_names():
        return False, _t(lang, "Неизвестный аккаунт.", "Unknown account."), None
    pdir = f"{PROFILES}/{name}"
    if os.path.islink(pdir):
        return False, _t(lang, "Профиль — символическая ссылка, удалять не буду.",
                         "The profile is a symbolic link — refusing to delete it."), None
    with lock:
        oa = jload(f"{pdir}/oauth_account.json", {}) or {}
        email = oa.get("emailAddress") or ""
        moved = None
        was_active = active_name() == name
        # Some CLI versions leave the token file without oauthAccount metadata.
        # Only compare non-empty tokens when no live identity is known.
        if not (jload(LIVE_CFG, {}) or {}).get('oauthAccount', {}).get('accountUuid'):
            saved_auth = (jload(f'{pdir}/credentials.json', {}) or {}).get('claudeAiOauth') or {}
            live_auth = (jload(LIVE_CREDS, {}) or {}).get('claudeAiOauth') or {}
            was_active = was_active or any(saved_auth.get(k) and saved_auth[k] == live_auth.get(k)
                                           for k in ('accessToken', 'refreshToken'))
        try:
            cc_disconnect.read(f'{pdir}/credentials.json')
            cc_disconnect.plain(f'{pdir}/{cc_disconnect.MARKER}')
            if was_active:
                cc_disconnect.read(LIVE_CREDS)
                cc_disconnect.read(LIVE_CFG)
        except (OSError, ValueError):
            return False, _t(lang, 'Не удалось безопасно прочитать авторизацию — отключение отменено.',
                             'Could not safely read authorization — disconnect cancelled.'), None
        if was_active and len(_real_names()) > 1:
            moved, why = _move_off(name)
            if not moved:
                return False, _t(lang, "Это активный аккаунт, а переключить сессию на другой не удалось — ничего не удалено. ",
                                 "This is the active account and the session could not be moved to another one — nothing was deleted. ") + why, None
        elif was_active:
            # The last login must not survive in a running process or in live credentials.
            scr = cfg().get('screen_session', 'claude')
            if _current_screen_pid(scr):
                if session_busy():
                    return False, _t(lang, 'Claude занят — дождись ответа перед отключением.',
                                     'Claude is busy — wait for its response before disconnecting.'), None
                try:
                    subprocess.run(['screen', '-S', scr, '-X', 'quit'], capture_output=True, timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    return False, _t(lang, 'Не удалось остановить консоль Claude.', 'Could not stop the Claude console.'), None
                if _current_screen_pid(scr):
                    return False, _t(lang, 'Консоль Claude ещё работает — отключение отменено.',
                                     'The Claude console is still running — disconnect cancelled.'), None
        _relogin_cleanup(name)
        try:
            cc_backup.note_deleted(BACKUP_DIR, oa.get("accountUuid"))  # копии хранят его токены, но «потерянным» он больше не считается
        except Exception:
            return False, _t(lang, 'Не удалось исключить вход из восстановления резервных копий.',
                             'Could not exclude the login from backup restoration.'), None
        try:
            if was_active and not moved:
                with cc_lock.oauth_lock(os.path.dirname(LIVE_CREDS), os.path.dirname(LIVE_CFG)):
                    cc_disconnect.drop_keys(LIVE_CREDS, ('claudeAiOauth',))
                    with cc_lock.config_lock(LIVE_CFG):
                        cc_disconnect.drop_keys(LIVE_CFG, ('oauthAccount',))
            cc_disconnect.drop_keys(f'{pdir}/credentials.json', ('claudeAiOauth',))
            cc_disconnect.write(f'{pdir}/{cc_disconnect.MARKER}', {'disconnected': True})
        except (OSError, ValueError, cc_lock.LockTimeout) as exc:
            print('disconnect Claude: ' + type(exc).__name__, flush=True)
            return False, _t(lang, 'Не удалось удалить всю авторизацию. Повтори отключение.',
                             'Could not remove all authorization. Retry disconnecting.'), None
        _plan_cache.pop(name, None)
        backoff_until.pop(name, None)
        good = jload(GOOD, {}) or {}
        if good.pop(name, None) is not None:
            jsave(GOOD, good)
        st = jload(STATE, {})
        for k in ("plans", "renewal", "renew_click", "lapsed", "plan_pending"):
            if isinstance(st.get(k), dict):
                st[k].pop(name, None)
        if (st.get("manual_hold") or {}).get("account") == name:
            st.pop("manual_hold", None)
        if moved:
            st["known_active"] = moved
            st["last_switch_ts"] = time.time()
        elif st.get("known_active") == name:
            st["known_active"] = active_name()
        jsave(STATE, st)
        snap = jload(SNAPSHOT) or {}
        (snap.get("accounts") or {}).pop(name, None)
        if snap.get("active") == name:
            snap["active"] = None
        jsave(SNAPSHOT, snap)
        snap = snap_set_active()
    cnt, names = _rotation_text()
    who = f"{name} ({email})" if email else f"{name} ({_t(lang, 'пустой слот', 'empty slot')})"
    tg_notify(f"Claude: аккаунт {who} отключён — вход удалён, история и файлы сохранены."
              + (f" Живая сессия переведена на {moved}." if moved else "")
              + f" В ротации осталось: {cnt} ({names}).")
    return True, (_t(lang, f'{who} отключён. История и файлы сохранены.', f'{who} disconnected. History and files retained.')
                  + (_t(lang, f" Сессия переведена на {moved}.", f" Session moved to {moved}.") if moved else "")), snap


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
# 429 ловится на конкретном аккаунте (лимит частоты у Anthropic — на токен), поэтому
# и пауза после него — по аккаунту: имя → ts, до которого этот аккаунт не опрашиваем.
# Общая пауза на всех замораживала бы и соседей: освободившийся аккаунт балансер
# увидел бы с опозданием, пока активный ловит 429.
backoff_until = {}

_FAIL_LOG_MAX = 1024 * 1024  # при превышении старый журнал уходит в .1 (один поколением), новый начинается заново


def _http_info(e):
    """(код, сырой Retry-After) из исключения опроса; (None, None) — это не HTTP-ответ."""
    if isinstance(e, urllib.error.HTTPError):
        try:
            return e.code, e.headers.get("Retry-After")
        except Exception:
            return e.code, None
    return None, None


def fail_log(name, stage, e, calls_1h=None, interval=None):
    """Строка в usage_fail.jsonl на каждый сбой опроса: аккаунт, этап, код, Retry-After, сколько
    запросов было за последний час и какой интервал стоял. Токенов и почты здесь нет.
    Сбой журнала не должен ломать опрос."""
    try:
        code, ra = _http_info(e)
        rec = {"ts": int(time.time()), "at": time.strftime("%Y-%m-%d %H:%M:%S"), "account": name,
               "stage": stage, "code": code, "retry_after": ra,
               "error": None if code else type(e).__name__, "calls_1h": calls_1h, "interval": interval}
        try:
            if os.path.getsize(FAIL_LOG) > _FAIL_LOG_MAX:
                os.replace(FAIL_LOG, FAIL_LOG + ".1")
        except OSError:
            pass
        with open(FAIL_LOG, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as ex:
        print(f"fail_log: {ex}", flush=True)


# Карточки показывали сырой текст исключения ("HTTP Error 400: Bad Request") —
# непонятно без похода в код (см. ERRORS.md). Переводим частые, документированные
# там случаи в понятный русский текст; тело HTTP-ответа читаем здесь один раз (у
# HTTPError .read() срабатывает только один раз за объект, поэтому в collect() эта
# функция — единственное место, где ошибку разбирают). Строку с кодом сохраняем
# внутри текста — на неё завязана детекция 429 (any("429" in e for e in errs) ниже).
def _humanize_error(e):
    if isinstance(e, urllib.error.HTTPError):
        code = e.code
        try:
            body = e.read().decode("utf-8", "ignore")
        except Exception:
            body = ""
        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {}
        raw_reason = data.get("error_description") or data.get("error") or ""
        kind = data.get("error") if isinstance(data.get("error"), str) else ""  # код вроде invalid_grant
        if isinstance(raw_reason, dict):
            # Anthropic иногда отдаёт {"error": {"type": ..., "message": ...}}, а не строку
            kind = str(raw_reason.get("type") or "")
            raw_reason = raw_reason.get("message") or kind or json.dumps(raw_reason, ensure_ascii=False)
        reason = str(raw_reason).strip()
        low = (reason + " " + kind).lower()
        if code in (400, 401) and ("refresh token expired" in low or "invalid_grant" in low):
            return f"Токен протух ({code}) — нажми «Войти заново»"
        if code == 401:
            return "Токен не принят Anthropic (401) — попробуй «Войти заново»"
        if code == 403:
            return "Anthropic заблокировал запрос (403)"
        if code == 429:
            return "Anthropic ограничил частоту запросов (429) — само пройдёт через пару минут"
        if 500 <= code < 600:
            return f"Anthropic временно недоступен ({code})"
        return f"Ошибка Anthropic ({code})" + (f": {reason}" if reason else "")
    if isinstance(e, urllib.error.URLError):
        low = str(e.reason if hasattr(e, "reason") else e).lower()
        if "timed out" in low or "timeout" in low:
            return "Anthropic не отвечает (таймаут)"
        return "Нет связи с Anthropic (сеть)"
    if isinstance(e, cc_lock.LockTimeout):
        return "Claude Code сейчас обновляет логин — повторю при следующем опросе"
    return str(e)


def collect(force=False, force_account=None, renew_account=None):
    prev = jload(SNAPSHOT) or {}
    # дедуп: не дёргать Anthropic чаще раза в 30с (иначе 429 Too Many Requests),
    # UI-запросы между опросами получают свежий снапшот с актуальным active.
    # Страницы Anthropic не опрашивают вообще — только читают снапшот; его раз в
    # poll_sec обновляет poll_loop. Иначе каждый заход страницы шёл бы в Anthropic
    # сам, и вместе с poll_loop активный аккаунт опрашивался бы раз в 30–60с — 429.
    if not force and prev.get("accounts") and time.time() - prev.get("ts", 0) < 900:
        return snap_set_active()
    act = active_name()
    good = jload(GOOD, {})
    accounts = {}
    # адаптивный опрос (cc_poll): у каждого аккаунта свой срок следующего запроса к usage;
    # adaptive_poll=false в config.json — прежнее поведение (раз в poll_sec активный, раз в
    # inactive_poll_sec остальные)
    ap = cc_poll.enabled(cfg())
    ap_p = cc_poll.params(cfg()) if ap else None
    sched = (jload(POLL_STATE, {}) or {}) if ap else {}
    st_pre = jload(STATE, {}) or {}
    lapsed_pre = st_pre.get("lapsed") or {}
    plans_pre = st_pre.get("plans") or {}
    for n in profile_names():
        oa = jload(f"{PROFILES}/{n}/oauth_account.json", {})
        row = {"email": oa.get("emailAddress", "?"), "active": n == act}
        # (lapsed) аккаунт, слетевший с Pro на Free (план подтверждён, см. блок ниже), не опрашиваем
        # совсем — ни usage, ни profile, ни обновление токена — пока человек не нажмёт «Я продлил»
        # (/api/recheck передаёт renew_account). «Обновить» в панели и перелогин его не будят:
        # на грани подписки Anthropic отдаёт то Pro, то Free, и вечный опрос только разгонял дребезг.
        if n in lapsed_pre and n != renew_account:
            old = good.get(n) or {}
            row["five_hour"] = old.get("five_hour")
            row["seven_day"] = old.get("seven_day")
            if old.get("ts"):
                row["stale_ts"] = old["ts"]
            row["plan"] = plans_pre.get(n) or "free"
            accounts[n] = row
            sched.pop(n, None)  # иначе устаревший срок опроса будил бы цикл вхолостую
            continue
        errs = []
        fails = []  # [(этап, исключение)] — для Retry-After и журнала сбоев
        access = None
        # неактивный аккаунт не расходует свою квоту сам по себе — незачем
        # дёргать его usage/profile так же часто, как активный. При poll_sec,
        # выставленном пониже (быстрая реакция на форс-свитч), это удваивало
        # частоту опроса ВСЕХ аккаунтов разом и ловило 429 на неактивных.
        # force_account — явный обход для кнопки "Я продлил" (/api/recheck),
        # там нужна гарантированная свежесть именно этого аккаунта.
        old = good.get(n) or {}
        # Кэш не годится, если в нём уже наступил сброс окна: аккаунт мог только что
        # освободиться, и балансеру это нужно знать сразу, а не через inactive_poll_sec.
        # Free-план это правило не касается: ему окна сессии/недели не помогают стать
        # пригодным (cc_avail.availability всё равно вернёт False при plan=="free"),
        # а их resets_at у нетронутого аккаунта почти всегда уже в прошлом — без этой
        # оговорки free-аккаунт опрашивался бы почти так же часто, как активный
        # (09.10.26: так неактивный free-аккаунт продолбился сутками как активный).
        if ap:
            sched[n] = cc_poll.retarget(sched.get(n), n == act, ap_p) or {}
            hist = sched[n].get("hist") or []
            # force_account (кнопка «Я продлил», перелогин, «обновить» в панели) обходит расписание,
            # но не чаще min_interval — прежний «дедуп 30 с»
            forced = (n == force_account and (not hist or time.time() - max(hist) >= ap_p["min_interval"]))
            stale_ok = bool(old.get("ts")) and not forced and not cc_poll.due(sched[n], time.time())
        else:
            stale_ok = (n != act and n != force_account and old.get("ts")
                        and time.time() - old["ts"] < cfg().get("inactive_poll_sec", 300)
                        and (old.get("plan") == "free" or not cc_avail.reset_passed(old)))
        # после 429 этот аккаунт не трогаем до конца его паузы — показываем кэш.
        # Без исключения для force_account: кнопка "Я продлил" раньше била мимо
        # паузы и могла продлевать 429 повторным запросом.
        if old.get("ts") and time.time() < backoff_until.get(n, 0):
            stale_ok = True
        if stale_ok:
            row["five_hour"] = old.get("five_hour")
            row["seven_day"] = old.get("seven_day")
            row["stale_ts"] = old.get("ts")
        try:
            access = get_access(n, act)
        except Exception as e:
            errs.append(_humanize_error(e))
            fails.append(("token", e))
        # (plan-freshness 2026-07-21) usage и plan запрашиваются НЕЗАВИСИМО. Раньше
        # plan вообще не запрашивался, если fetch_usage падал первым (напр. 429) —
        # значит pro→free переход (см. tg_notify ниже) и исключение из авто-кандидатов
        # молчали сколько угодно долго, пока usage-эндпоинт был недоступен. Именно
        # так cc-switch вручную приземлил живую сессию на реально-Free аккаунт
        # (21.07, "organization has disabled Claude subscription access") — карточка
        # показывала кэшированный "pro", хотя аккаунт уже был Free.
        if access is not None:
            if not stale_ok:
                try:
                    row.update(fetch_usage(access))
                except Exception as e:
                    errs.append(_humanize_error(e))
                    fails.append(("usage", e))
            # (plan-vs-backoff 23.10.26) план читаем всегда, даже когда usage в
            # стейле/бэкоффе — это разные эндпойнты, у fetch_plan свой кэш (10 мин).
            # Раньше stale_ok выходил из цикла ДО этого вызова и подставлял
            # замороженный good[n]["plan"] — на acc2 он не обновлялся 30+ часов
            # (сутками 403 на usage держал стейл), и этот замороженный "pro" каждый
            # фоновый цикл сбивал дебаунс "2 подряд" для free обратно в 0, хотя сам
            # profile всё это время честно отдавал free.
            try:
                row["plan"] = fetch_plan(n, access)
            except Exception as e:
                errs.append(_humanize_error(e))
                fails.append(("profile", e))
        if stale_ok:
            if row.get("plan") is None:
                row["plan"] = old.get("plan")
            accounts[n] = row
            continue
        got_usage = "five_hour" in row  # до подстановки кэша ниже
        if "five_hour" in row and "plan" in row:
            good[n] = {"five_hour": row["five_hour"], "seven_day": row["seven_day"],
                       "plan": row["plan"], "ts": int(time.time())}
        if errs:
            row["error"] = " | ".join(errs)[:200]
            # 403 (доступ запрещён) бэкофф не ставил — опрос долбил заблокированный
            # эндпойнт каждый цикл без паузы, пока сам не упирался в реальный 429
            # Anthropic (найдено 23.10.26, acc2 trading-VM: usage 403 24ч подряд,
            # sd/fh всё это время — замороженный кэш, не живые цифры).
            if any("429" in e or "403" in e for e in errs):
                if ap:
                    # ждём сколько просит сервер (Retry-After + запас), а не вслепую 2×poll_sec;
                    # без заголовка — растущая пауза 300 → 450 → … → 1800 с
                    ras = [cc_poll.parse_retry_after(_http_info(e)[1]) for _st, e in fails if _http_info(e)[0] == 429]
                    ras = [r for r in ras if r is not None]
                    wait429 = cc_poll.backoff_seconds(max(ras) if ras else None,
                                                      (sched.get(n) or {}).get("fails", 0) + 1, ap_p)
                    backoff_until[n] = time.time() + wait429
                else:
                    backoff_until[n] = time.time() + cfg().get("poll_sec", 120) * 2
            # разовый сбой (429 и т.п.) не должен стирать карточку — показать
            # последние удачные цифры из отдельного кэша с пометкой возраста
            # (только для того, что реально не получили в этом цикле)
            old = good.get(n) or {}
            for k in ("five_hour", "seven_day", "plan"):
                if row.get(k) is None and old.get(k) is not None:
                    row[k] = old[k]
            row["stale_ts"] = old.get("ts")
        if ap and not stale_ok:
            nowt = time.time()
            w429 = wait429 if any("429" in e or "403" in e for e in errs) else None
            pcts = ((row["five_hour"] or {}).get("pct"), (row["seven_day"] or {}).get("pct")) if got_usage else None
            nr = cc_avail.next_reset_ts({n: row}, nowt)
            c = cfg()
            sched[n] = cc_poll.after_poll(
                sched.get(n), nowt, ok=got_usage, pcts=pcts,
                resets_in=(nr - nowt) if nr is not None else None, is_active=(n == act),
                limits=(c.get("threshold", 85), c.get("weekly_cap", 99)), wait429=w429,
                p=ap_p, unit=random.random())
            sched[n]["active"] = n == act
            for stage, e in fails:
                fail_log(n, stage, e, calls_1h=len(sched[n].get("hist") or []), interval=sched[n].get("interval"))
        elif fails:
            for stage, e in fails:
                fail_log(n, stage, e)
        accounts[n] = row
    if ap:
        jsave(POLL_STATE, {k: v for k, v in sched.items() if k in accounts})
    jsave(GOOD, good)
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
    # смена плана (Pro истёк / продлён) — уведомить и показать в снимке только
    # после 2 одинаковых подряд чтений. Anthropic у себя не мгновенно консистентен
    # на грани подписки (похоже на повторные попытки списания/отмены) — одиночные
    # чтения дребезжали pro/free каждые ~4 минуты 27+ часов, 08-09.10.26. До 23.10.26
    # дебаунс защищал только уведомления и state.json["plans"] — снимок (SNAPSHOT)
    # писался раньше этого блока сырым accounts[n]["plan"], и именно сырое значение
    # видели бейдж в UI и cc_avail.availability() (бейдж аккаунта acc2
    # мигал free/pro вслед за дребезгом Anthropic, хотя state.json уже был стабилен).
    st = jload(STATE, {})
    prev = st.get("plans") or {}
    pending = st.get("plan_pending") or {}
    cur = {n: r.get("plan") for n, r in accounts.items() if r.get("plan")}
    plans_changed = False
    pending_changed = False
    for n, p in cur.items():
        was = prev.get(n)
        if not was:
            # первое наблюдение этого аккаунта — фиксируем сразу, без дебаунса
            prev[n] = p
            plans_changed = True
            if pending.pop(n, None) is not None:
                pending_changed = True
            continue
        if p == was:
            if pending.pop(n, None) is not None:
                pending_changed = True
            continue
        cand = pending.get(n) or {}
        cnt = (cand.get("count", 0) + 1) if cand.get("plan") == p else 1
        if n == renew_account and p != "free":
            cnt = 2  # явное «Я продлил»: человек сам подтвердил оплату, второго чтения не ждём
        if cnt < 2:
            pending[n] = {"plan": p, "count": cnt}
            pending_changed = True
            continue
        pending.pop(n, None)
        pending_changed = True
        email = accounts[n].get("email", n)
        if p == "free":
            tg_notify(f"⛔ Claude: аккаунт {n} ({email}) слетел с Pro в Free — пора продлевать подписку. Из ротации исключён, опрос остановлен до нажатия «Я продлил».")
        else:
            tg_notify(f"✅ Claude: аккаунт {n} ({email}) снова {p.upper()} — вернул в ротацию.")
            if was == "free":
                # продление, замеченное фоном (кнопка «Я продлил» могла не
                # дождаться Anthropic) — якорь таймера = момент нажатия, если был
                click = (st.get("renew_click") or {}).get(n, 0)
                anchor = click if time.time() - click < 6 * 3600 else time.time()
                st.setdefault("renewal", {})[n] = {"confirmed_ts": anchor}
                (st.get("renew_click") or {}).pop(n, None)
        prev[n] = p
        plans_changed = True
    if plans_changed:
        st["plans"] = prev
    if pending_changed:
        if pending:
            st["plan_pending"] = pending
        else:
            st.pop("plan_pending", None)
    # слетевшие: подтверждённый Free = неактивный (опрос стоит, см. начало collect); подтверждённый
    # не-Free снимает отметку. Заодно подхватывает аккаунты, что уже были Free до появления отметки
    lapsed = st.get("lapsed") or {}
    lapsed_changed = False
    for n in accounts:
        p = prev.get(n)
        if p == "free" and n not in lapsed:
            lapsed[n] = {"since": int(time.time())}
            lapsed_changed = True
        elif p and p != "free" and n in lapsed:
            lapsed.pop(n)
            lapsed_changed = True
    for n in [k for k in lapsed if k not in accounts]:
        lapsed.pop(n)
        lapsed_changed = True
    if lapsed_changed:
        if lapsed:
            st["lapsed"] = lapsed
        else:
            st.pop("lapsed", None)
    if plans_changed or pending_changed or lapsed_changed:
        jsave(STATE, st)
    # снимок несёт ПОДТВЕРЖДЁННЫЙ план (prev[n] после дебаунса выше), не сырое
    # чтение этого цикла — иначе бейдж и availability() всё равно мигают, пока
    # уведомление уже молчит. На первом наблюдении (prev[n] выставлен без
    # дебаунса парой строк выше) и во время "pending" (cnt<2) здесь остаётся
    # прежний подтверждённый план — ровно то, что нужно.
    for n, row in accounts.items():
        confirmed = prev.get(n)
        if confirmed:
            row["plan"] = confirmed
        if n in lapsed:
            row["lapsed"] = True
            row["lapsed_since"] = (lapsed[n] or {}).get("since")
    snap = {"ts": int(time.time()), "active": act, "accounts": accounts}
    jsave(SNAPSHOT, snap)
    return snap


SETTINGS = "/root/.claude/settings.json"
TRANSCRIPTS = "/root/.claude/projects/-root"
MODELS = {  # id → короткое имя для UI
    "claude-fable-5": "Fable 5",
    "claude-fable-5-1": "Fable 5.1",
    "claude-opus-5": "Opus 5",
    "claude-opus-5-5": "Opus 5.5",
    "claude-sonnet-5": "Sonnet 5",
    "claude-sonnet-5-5": "Sonnet 5.5",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
    "claude-haiku-5-5": "Haiku 5.5",
}

# Необязательный источник для кнопки "Проверить новые модели": если рядом крутится
# свой скрипт-сторож CLI-релизов (см. model_version_watch.py в этом репозитории),
# он копит сюда id новых моделей, найденных в бинарнике claude-code. Файла нет —
# кандидатов просто не будет, ничего не ломается.
MODEL_WATCH_STATE = "/root/.model_version_watch_state.json"


def all_models():
    # MODELS — базовый набор из кода; extra_models в config.json — то, что добавили
    # через кнопку "Проверить новые модели", без правки исходника при каждом релизе
    return {**MODELS, **(cfg().get("extra_models") or {})}


def _find_claude_bins():
    # Бинарник/скрипт Claude Code, в строках которого зашиты ID моделей. Ставят его
    # по-разному (npm -g в /usr/lib или ~/.npm-global, нативный установщик в ~/.local),
    # поэтому идём от `claude` в PATH и добираем типовые места.
    cands = []
    w = shutil.which("claude")
    if w:
        cands.append(os.path.realpath(w))
    for root in ("/root/.npm-global/lib/node_modules", "/usr/lib/node_modules",
                 "/usr/local/lib/node_modules"):
        pkg = os.path.join(root, "@anthropic-ai", "claude-code")
        cands += [os.path.join(pkg, "bin", "claude.exe"), os.path.join(pkg, "cli.js")]
    cands += [os.path.expanduser("~/.local/bin/claude")]
    out = []
    for p in cands:
        p = os.path.realpath(p)
        if os.path.isfile(p) and p not in out:
            out.append(p)
    return out


_MODEL_ID_RE = re.compile(rb"claude-(?:opus|sonnet|haiku|fable)-[0-9][a-z0-9-]*")
# «чистый» ID релиза: claude-opus-5, claude-opus-5-5, claude-haiku-4-5-20251001.
# Всё остальное из бинарника (-v1, -fast, -mythos-…) — внутренние варианты, не показываем
_CLEAN_ID_RE = re.compile(r"claude-(opus|sonnet|haiku|fable)-(\d{1,2})(?:-(\d{1,2}))?(?:-\d{8})?")


def _scan_claude_model_ids():
    found = set()
    for p in _find_claude_bins():
        try:
            with open(p, "rb") as f:
                found |= {m.decode() for m in _MODEL_ID_RE.findall(f.read())}
        except Exception:
            pass
    return found


# (effort-lock) Какие уровни effort поддерживает модель — берём из
# каталога моделей, зашитого в бинарник Claude Code (тот же источник, что у его /effort):
# capabilities «effort» → low/medium/high, «max_effort» → max, «xhigh_effort» → xhigh.
# Нет модели в каталоге / не смогли прочитать → None = не блокируем (лучше дать выбрать,
# чем ложно запретить новой модели то, что она умеет).
_EFFORT_CAT_RE = re.compile(rb'\{id:"(claude-[a-z0-9-]+)",family:"')
_EFFORT_CAPS_RE = re.compile(rb"capabilities:\[([^\]]*)\]")
_effort_cat_cache = {"key": None, "map": {}}


def _effort_catalog():
    import mmap
    out = {}
    key = []
    bins = _find_claude_bins()
    for p in bins:
        try:
            key.append((p, os.path.getmtime(p)))
        except Exception:
            pass
    if _effort_cat_cache["key"] == key and _effort_cat_cache["map"]:
        return _effort_cat_cache["map"]
    for p in bins:
        try:
            with open(p, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                heads = [(m.start(), m.group(1).decode()) for m in _EFFORT_CAT_RE.finditer(mm)]
                for i, (pos, mid) in enumerate(heads):
                    end = heads[i + 1][0] if i + 1 < len(heads) else pos + 4000
                    seg = mm[pos:min(end, pos + 4000)]
                    cm = _EFFORT_CAPS_RE.search(seg)
                    caps = {c.strip().strip(b'"').decode() for c in cm.group(1).split(b",")} if cm else set()
                    lv = []
                    if "effort" in caps:
                        lv = ["low", "medium", "high"]
                        if "xhigh_effort" in caps:
                            lv.append("xhigh")
                        if "max_effort" in caps:
                            lv.append("max")
                    out[mid] = lv
        except Exception:
            continue
        if out:
            break
    _effort_cat_cache["key"] = key
    _effort_cat_cache["map"] = out
    return out


def effort_support(model_id):
    # список уровней, которые модель принимает; [] — effort не поддерживается совсем;
    # None — модель неизвестна каталогу (не блокируем)
    if not model_id:
        return None
    mid = re.sub(r"\[1m\]$", "", model_id)
    cat = _effort_catalog()
    if mid in cat:
        return cat[mid]
    m = re.fullmatch(r"(.+)-\d{8}", mid)  # датированный снапшот: claude-haiku-4-5-20251001
    if m and m.group(1) in cat:
        return cat[m.group(1)]
    return None


def _model_ver(mid):
    m = _CLEAN_ID_RE.fullmatch(mid)
    if not m:
        return None
    return m.group(1), (int(m.group(2)), int(m.group(3) or 0))


def model_candidates():
    # Кнопка «Проверить новые модели». Источники ID:
    #  1) скан установленного Claude Code прямо сейчас (у любой установки, ~0.2 с);
    #  2) known_ids из model_version_watch.py, если такой сторож крутится рядом.
    # В бинарнике вперемешку релизы, старьё и внутренние варианты — отдаём только
    # чистые ID, которые НОВЕЕ всего, что уже есть в наборе по этому семейству
    # (opus-5-5 при известном opus-5), и которые не отклоняли. Решает человек в UI.
    known = set((jload(MODEL_WATCH_STATE, {}) or {}).get("known_ids") or [])
    known |= _scan_claude_model_ids()
    have_map = all_models()
    have = set(have_map.keys())
    have_names = set(have_map.values())
    ignored = set(cfg().get("model_ignored_ids") or [])
    newest = {}
    for mid in have:
        v = _model_ver(mid)
        if v and v[1] > newest.get(v[0], (0, 0)):
            newest[v[0]] = v[1]
    cand_ids = []
    for m in sorted(known):
        v = _model_ver(m)
        if m in have or m in ignored or not v or v[1] <= newest.get(v[0], (0, 0)):
            continue
        cand_ids.append(m)
    # из одного релиза оставляем короткий алиас, датированный снапшот рядом не нужен
    cand_ids = [m for m in cand_ids if not (re.search(r"-\d{8}$", m) and m.rsplit("-", 1)[0] in cand_ids)]

    def guess_name(mid):
        parts = mid.split("-")[1:]  # без "claude"
        if not parts:
            return mid
        family = parts[0].capitalize()
        nums = []
        for p in parts[1:]:
            if re.fullmatch(r"\d+[a-z]?", p) and not re.fullmatch(r"\d{8}", p):
                nums.append(p)
            else:
                break
        return family + (" " + ".".join(nums) if nums else "")

    result = []
    for m in cand_ids:
        name = guess_name(m)
        result.append({"id": m, "guess_name": name, "already": name in have_names})
    return result


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
CONSOLE_LOG_OWNER = CONSOLE_LOG + ".session"   # PID screen-сессии, которая пишет в CONSOLE_LOG (чтобы рестарт панели не откладывал лог живой сессии)
_console_log_ready = False
_console_screen_pid = None


def _console_owner_id(pid):
    """«PID:время старта процесса» — после перезагрузки сервера PID мог совпасть случайно, время старта не совпадёт."""
    try:
        with open("/proc/%d/stat" % int(pid), encoding="utf-8") as f:
            raw = f.read()
        return "%s:%s" % (int(pid), raw[raw.rindex(")") + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        return ""


def _console_log_owner_read():
    try:
        with open(CONSOLE_LOG_OWNER, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _console_log_owner_write(pid):
    try:
        tmp = CONSOLE_LOG_OWNER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(str(pid or ""))
        os.replace(tmp, CONSOLE_LOG_OWNER)
    except OSError:
        pass


def _current_screen_pid(scr):
    try:
        r = subprocess.run(["screen", "-list"], capture_output=True, timeout=10, text=True)
        m = re.search(r"(\d+)\." + re.escape(scr) + r"\b", r.stdout)
        return m.group(1) if m else None
    except Exception:
        return None


_tdir_cache = {"ts": 0.0, "dir": None}


def _session_cwd():
    # папка запуска Claude Code в screen-сессии: идём вглубь по потомкам PID screen и берём
    # cwd первого процесса с "claude" в командной строке (иначе — самого глубокого потомка)
    pid = _current_screen_pid(cfg().get("screen_session", "claude"))
    if not pid:
        return None
    last, level = None, [pid]
    for _ in range(4):
        nxt = []
        for p in level:
            try:
                nxt += subprocess.run(["pgrep", "-P", p], capture_output=True, timeout=5, text=True).stdout.split()
            except Exception:
                pass
        if not nxt:
            break
        for p in nxt:
            try:
                cwd = os.readlink(f"/proc/{p}/cwd")
                with open(f"/proc/{p}/cmdline", "rb") as f:
                    cmd = f.read().decode("utf-8", "replace")
            except OSError:
                continue
            if "claude" in cmd:
                return cwd
            last = cwd
        level = nxt
    return last


def transcripts_dir():
    # Каталог транскриптов живой сессии. Claude Code кладёт их в projects/<cwd, где всё кроме
    # букв и цифр заменено на "-">: из /root это -root, из /root/trade — -root-trade. Порядок:
    # явный ключ transcripts_dir в config.json → cwd Claude Code в screen-сессии → прежний -root.
    d = cfg().get("transcripts_dir")
    if d:
        return d
    now = time.time()
    if _tdir_cache["dir"] and now - _tdir_cache["ts"] < 20:
        return _tdir_cache["dir"]
    d = TRANSCRIPTS
    try:
        cwd = _session_cwd()
        if cwd:
            cand = os.path.join(os.path.dirname(SETTINGS), "projects", re.sub(r"[^A-Za-z0-9]", "-", cwd))
            if os.path.isdir(cand):
                d = cand
    except Exception:
        pass
    _tdir_cache.update(ts=now, dir=d)
    return d


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
    owner = _console_owner_id(pid) if pid else ""
    if owner and os.path.exists(CONSOLE_LOG) and _console_log_owner_read() == owner:
        # Перезапустили саму панель (обновление), а screen-сессия та же и уже пишет в этот лог: он её. Откладывать его в .prev
        # нельзя: Claude Code рисует экран дифф-обновлениями, и без начала лога на экране остаются только мелкие обрывки
        # (пропадают рамка поля ввода, полоски лимитов, строка режима). Просто подхватываем.
        subprocess.run(["screen", "-S", scr, "-p", "0", "-X", "log", "on"], capture_output=True, timeout=10)
        _console_log_ready = True
        _console_screen_pid = pid
        with _console_lock:
            _console_screen = None
            _console_offset = 0
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
    _console_log_owner_write(owner)
    with _console_lock:
        _console_screen = None
        _console_offset = 0


def _console_dims_fallback():
    # геометрия по "плотной коробке" вокруг текста hardcopy — приблизительная,
    # гуляет вместе с контентом (короткая/длинная строка меняют cols). Используется
    # только если _console_real_dims() не смог получить honest-размер через ioctl.
    txt = screen_hardcopy()
    lines = txt.split("\n") if txt else []
    rows = len(lines) or 24
    cols = max((len(l) for l in lines), default=80) or 80
    return max(cols, 20), max(rows, 5)


def _console_window_pty(master_pid):
    # pty-устройство ОКНА screen (не самого screen-мультиплексора) — находим
    # прямого child-процесса мастер-PID сессии, у которого fd 0 указывает на
    # /dev/pts/N (slave-сторона pty, которую держит shell/claude внутри окна).
    # Размер терминала — атрибут pty на уровне ядра, одинаковый что со стороны
    # master (держит screen), что со стороны slave — читаем его напрямую
    # ioctl'ом, не спрашивая сам screen.
    if not master_pid:
        return None
    try:
        out = subprocess.run(["pgrep", "-P", master_pid], capture_output=True,
                              timeout=5, text=True).stdout
        for cpid in out.split():
            try:
                link = os.readlink(f"/proc/{cpid}/fd/0")
            except OSError:
                continue
            if link.startswith("/dev/pts/"):
                return link
    except Exception:
        pass
    return None


def _console_real_dims():
    # Честный размер терминала БЕЗ обращения к command/socket-каналу screen.
    # Раньше (до этой правки) геометрию брали "плотной коробкой" по hardcopy
    # (см. _console_dims_fallback) — неточно, гуляет вместе с контентом.
    # Альтернатива "спросить у самого screen" (`screen -Q info`) выглядит
    # правильно, но ломается если вызывающий процесс не привязан к той же
    # управляющей сессии: screen пишет ответ НЕ в stdout вызывающего, а прямо
    # в message line ЖИВОЙ консоли — визуальная порча экрана на каждый вызов
    # (не зависит от того, как редко дёргать — кэш/throttling это не чинит,
    # только уменьшает частоту, сам артефакт остаётся). Правильный путь —
    # прочитать размер прямо с ядра через ioctl(TIOCGWINSZ) на pty-устройстве
    # screen-окна: это атрибут pty, а не screen, никакого сообщения screen'у
    # не шлётся вообще.
    try:
        # _console_screen_pid уже свежий — console_snapshot() зовёт
        # _console_ensure_logging() прямо перед этой функцией, а та внутри
        # себя уже сходила за master PID через _current_screen_pid(). Второй
        # раз `screen -list` дёргать незачем.
        path = _console_window_pty(_console_screen_pid)
        if path:
            fd = os.open(path, os.O_RDONLY | os.O_NOCTTY)
            try:
                packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
            finally:
                os.close(fd)
            rows, cols, _xp, _yp = struct.unpack("HHHH", packed)
            if cols > 0 and rows > 0:
                return max(cols, 20), max(rows, 5)
    except Exception:
        pass
    return _console_dims_fallback()


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


def _cell_style(ch, bg_map=None):
    fg, bg = _resolve_color(ch.fg, ch.bold), _resolve_color(ch.bg, False)
    if ch.reverse:
        fg, bg = bg, fg
    if bg_map and bg in bg_map:
        bg = bg_map[bg]
    parts = []
    if fg:
        parts.append(f"color:{fg}")
    if bg:
        parts.append(f"background:{bg}")
    if ch.bold:
        parts.append("font-weight:700")
    # ch.underscore сознательно НЕ рендерим: на свежей (не --continue) сессии
    # claude встречается терминальный баг, при котором SGR-underline остаётся
    # "залипшим" почти на всём экране (десятки % ячеек, включая статус-бар) -
    # так как 100%-покрытие экрана подчёркиванием никогда не несёт полезного
    # сигнала в консольном зеркале, безопаснее не отрисовывать этот атрибут.
    return ";".join(parts)


def _row_html(line, ncols, bg_map=None):
    out, style, buf = [], "", []
    for x in range(ncols):
        ch = line[x]
        st = _cell_style(ch, bg_map)
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


# Codex рисует блок сообщения пользователя полосой (SGR 48;5;8): pyte отдаёт индекс 8 как 7f7f7f, и светлый текст
# на таком сером нечитаем. Полоса нужна, чтобы отличать сообщение человека от ответа, поэтому в Codex-зеркале
# подменяем её на тёмный сине-серый фон, на котором текст читается. В консоли Claude таких полос нет.
CODEX_BG_MAP = {"#7f7f7f": "#303744"}


def _row_html_codex(line, ncols):
    return _row_html(line, ncols, CODEX_BG_MAP)


cc_codex_console.ROW_HTML = _row_html_codex  # остальная раскраска консоли Codex та же, что у консоли Claude


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
    # Раньше геометрию мерили "плотной коробкой" вокруг текста hardcopy (см.
    # _console_dims_fallback) — она гуляла вместе с контентом (короткая/длинная
    # строка, кириллица режет длину иначе), и ЛЮБОЕ изменение (cols, rows) било
    # в _console_reset(), который обнулял _console_offset — следующий
    # _console_feed() перечитывал ВЕСЬ CONSOLE_LOG (десятки МБ) через pyte
    # заново. При активной сессии геометрия "менялась" почти на каждый опрос —
    # сервер прогрессивно отставал и уходил в timeout (инцидент 12.07). С
    # переходом на _console_real_dims() (честный ioctl-размер) геометрия почти
    # никогда не меняется — но resize() всё равно должен быть дешёвым на
    # единичный реальный ресайз. pyte.HistoryScreen.resize() меняет размер БЕЗ
    # потери history/offset — дёшево независимо от того как часто вызывается.
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


def console_idle_reason():
    """Подпись в пустой консоли Claude (сессии нет). cc_remote_mode подменяет: «работа сейчас на PROD…»."""
    return "Claude сейчас не запущен — консоль появится, когда сессию Claude запустят."


# Последний экран остановленной сессии: console.log.prev разбирается один раз (кэш по mtime+size),
# хвост не больше CONSOLE_FROZEN_MAX — инцидент 12.07: многомегабайтный лог через pyte вешал сервер.
CONSOLE_FROZEN_MAX = 1536 * 1024
_frozen_lock = threading.Lock()
_frozen = {"key": None, "current": "", "history": ""}


def _frozen_cols(data):
    # ширину мёртвой сессии уже не спросить у pty — берём по самой длинной линии ─ (Claude рисует её во всю ширину)
    txt = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", data[-300000:]).decode("utf-8", "replace")
    runs = [len(m) for m in re.findall("─{40,}", txt)]
    return max(40, min(400, max(runs))) if runs else 120


def console_frozen_snapshot(want_history=False):
    path = CONSOLE_LOG + ".prev"
    try:
        st = os.stat(path)
    except OSError:
        return "", ("" if want_history else None), 0
    key = (st.st_mtime_ns, st.st_size)
    with _frozen_lock:
        if _frozen["key"] != key:
            try:
                with open(path, "rb") as f:
                    if st.st_size > CONSOLE_FROZEN_MAX:
                        f.seek(st.st_size - CONSOLE_FROZEN_MAX)
                    data = f.read()
                cols = _frozen_cols(data)
                scr = pyte.HistoryScreen(cols, 50, history=CONSOLE_HISTORY_LINES)
                pyte.ByteStream(scr).feed(data)
                cur = list(zip(scr.display, (_row_html(scr.buffer[y], cols) for y in range(scr.lines))))
                while cur and not cur[-1][0].strip():
                    cur.pop()
                _frozen.update(key=key, current="\n".join(h for _, h in cur),
                               history="\n".join(_row_html(line, cols) for line in scr.history.top))
            except Exception as e:
                print("console: последний экран не разобран:", type(e).__name__, flush=True)
                _frozen.update(key=key, current="", history="")
        return _frozen["current"], (_frozen["history"] if want_history else None), int(st.st_mtime)


def console_snapshot(want_history=False):
    # want_history=False (дефолт, дёргается раз в 2с с фронта) — рендерит ТОЛЬКО
    # текущий экран (десятки строк, дёшево). history.top растёт до 2000 строк и
    # рендерить/пересылать её КАЖДЫЙ опрос — то что вешало браузер: клиент
    # делал box.innerHTML = <растущая HTML-простыня> каждые 2с навсегда, полный
    # reflow гигантского DOM без остановки. history теперь считается только по
    # явному запросу (первая загрузка страницы), текущий экран — отдельно и часто.
    _console_ensure_logging()
    cols, rows = _console_real_dims()
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


# Имя модели в статус-строке живой сессии. Строка бывает и "  Fable 5     40%  root",
# и "  Opus 5.5 │ ✍️ 45% │ project" — hardcopy режет не-ASCII (│ → \x02, эмодзи → \x00),
# поэтому между именем и процентом допускаем любой короткий мусор. Берём последнюю
# такую строку (статус внизу экрана). Имя может быть не из MODELS (Opus 4.8 — модель
# отката safeguard'ов), поэтому возвращаем именно имя, а не ID.
_STATUS_MODEL_RE = re.compile(r"^\s{0,4}((?:Opus|Sonnet|Haiku|Fable) \d+(?:\.\d+)?)\b[^\n]{0,24}?\d+%")


def status_model_name(txt):
    name = None
    for line in txt.splitlines():
        m = _STATUS_MODEL_RE.match(line)
        if m:
            name = m.group(1)
    return name


def session_model():
    # Источник истины = статус-строка живой сессии (то, что видно в терминале):
    # "  Fable 5     40%  root  ⏵ xhigh". Именно она отражает и авто-переключения
    # рантайма (напр. safeguard'ы Fable→Opus), которых нет в settings.json.
    txt = screen_hardcopy()
    name = status_model_name(txt)
    if name:
        return next((mid for mid, n in all_models().items() if n == name), name)
    for line in txt.splitlines():
        for mid, name in all_models().items():
            # имя модели в начале строки статуса + где-то дальше "root"
            if re.search(r"\b" + re.escape(name) + r"\b\s+\d+%\s+root", line):
                return mid
    # запасной путь — последний assistant в свежем транскрипте
    model = None
    try:
        td = transcripts_dir()
        files = [os.path.join(td, f) for f in os.listdir(td) if f.endswith(".jsonl")]
        newest = max(files, key=os.path.getmtime)
        with open(newest, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 300_000))
            tail = f.read().decode("utf-8", "replace")
        for line in tail.splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = (d.get("message") or {}).get("model")
            if d.get("type") == "assistant" and m and not m.startswith("<"):  # «<synthetic>» — служебный ответ Claude Code, не модель
                model = m
    except Exception:
        pass
    # ни статус-строки, ни транскрипта (панель без своей статус-строки, сессия ещё без ответов) —
    # модель по умолчанию из settings.json: туда пишет и /model, и кнопки панели
    return model or (jload(SETTINGS, {}) or {}).get("model")


def model_info():
    dflt = (jload(SETTINGS, {}) or {}).get("model")
    sess = session_model()
    c = cfg()
    models = all_models()
    enabled = c.get("enabled_models") or list(models.keys())  # ничего не скрыто, пока не сузили в панели
    added_ts = c.get("model_added_ts") or {}
    hidden = set(c.get("model_hidden") or [])
    now = time.time()
    return {"session": sess, "session_name": models.get(sess, sess),
            "default": dflt, "default_name": models.get(dflt, dflt),
            "available": [{"id": k, "name": v, "enabled": k in enabled, "hidden": k in hidden,
                           "new": now - added_ts.get(k, 0) < 14 * 86400,
                           "efforts": effort_support(k)}
                          for k, v in models.items()],
            "effort": session_effort(sess), "effort_default": settings_effort(sess),
            "efforts": list(EFFORT_LEVELS), "effort_supported": effort_support(sess)}


# Уровень effort живой сессии — хвост той же статус-строки, что и модель: "  Opus 5.5     50%  root  ⏵ xhigh". Не нашли строку —
# берём effortLevel из settings.json (дефолт новых сессий).
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
# перед уровнем — значок ⏵, который hardcopy отдаёт мусорным не-словесным символом
_STATUS_EFFORT_RE = re.compile(r"[^\w\s]\s*(low|medium|high|xhigh|max)\b")


def settings_effort(model_id=None, s=None):
    # Claude Code хранит effort ПО МОДЕЛИ: modelSettings[<id>].effortLevel — туда пишет
    # /effort; верхний effortLevel — лишь общий фолбэк, /effort его не трогает
    s = s if s is not None else (jload(SETTINGS, {}) or {})
    per = ((s.get("modelSettings") or {}).get(model_id) or {}).get("effortLevel") if model_id else None
    return per or s.get("effortLevel")


_TR_EFFORT_CMD_RE = re.compile(r"<local-command-stdout>Set effort level to (low|medium|high|xhigh|max)\b")


def transcript_effort():
    # effort живой сессии по её транскрипту: вывод /effort пишется туда сразу (в т.ч.
    # «max — this session only», которого нет в settings.json), а у каждой реплики
    # ассистента есть поле "effort". Берём то, что встретилось последним.
    try:
        td = transcripts_dir()
        files = [os.path.join(td, f) for f in os.listdir(td) if f.endswith(".jsonl")]
        newest = max(files, key=os.path.getmtime)
        with open(newest, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 300_000))
            tail = f.read().decode("utf-8", "replace")
    except Exception:
        return None
    eff = None
    for line in tail.splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") == "assistant" and d.get("effort") in EFFORT_LEVELS:
            eff = d["effort"]
        elif d.get("type") == "user":
            c = (d.get("message") or {}).get("content")
            m = _TR_EFFORT_CMD_RE.search(c) if isinstance(c, str) else None
            if m:
                eff = m.group(1)
    return eff


def session_effort(model_id=None):
    # 1) транскрипт живой сессии; 2) settings по модели сессии (/effort сохраняет туда
    # всё, кроме session-only max); 3) статус-строка; 4) общий effortLevel
    eff = transcript_effort()
    if eff:
        return eff
    model_id = model_id or session_model()
    per = ((((jload(SETTINGS, {}) or {}).get("modelSettings") or {}).get(model_id) or {}).get("effortLevel")
           if model_id else None)
    if per:
        return per
    try:
        txt = screen_hardcopy()
        for line in txt.splitlines():
            if _STATUS_MODEL_RE.match(line):
                m = _STATUS_EFFORT_RE.search(line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return settings_effort(model_id)


def _model_notice_state(mid=None, top=False):
    """Модель и effort для сообщения о смене в Telegram: по settings.json (то, что записала панель), экран не читаем.
    top — effort лежит в общем effortLevel (так set_effort пишет, когда живой сессии нет), а не у модели."""
    try:
        s = jload(SETTINGS, {}) or {}
        mid = mid or s.get("model")
        return {"model": all_models().get(mid, mid), "effort": s.get("effortLevel") if top else settings_effort(mid, s)}
    except Exception:
        return {}


def set_effort(level):
    # тот же принцип, что set_default_model: effortLevel в settings.json (дефолт новых
    # сессий) + best-effort "/effort <уровень>" в живую консоль через screen stuff
    if level not in EFFORT_LEVELS:
        return False, "unknown effort"
    sup = effort_support(session_model())
    if sup is not None and level not in sup:
        nm = all_models().get(session_model(), session_model())
        return False, (nm + " не поддерживает effort вообще" if not sup else
                       nm + " не поддерживает effort «" + level + "» (доступно: " + ", ".join(sup) + ")")
    s = jload(SETTINGS, {}) or {}
    mid = session_model()
    if mid and mid.startswith("claude-"):
        s.setdefault("modelSettings", {}).setdefault(mid, {})["effortLevel"] = level
    else:
        s["effortLevel"] = level
    with open(SETTINGS + ".tmp", "w") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)
    os.replace(SETTINGS + ".tmp", SETTINGS)
    live = False
    try:
        scr = cfg().get("screen_session", "claude")
        p = subprocess.run(["screen", "-S", scr, "-p", "0", "-X", "stuff", f"/effort {level}\r"],
                           capture_output=True, text=True, timeout=10)
        live = p.returncode == 0
    except Exception:
        pass
    return True, "effort " + level + (" — дефолт сохранён; в текущей сессии применится, если она сейчас свободна (иначе повтори)" if live else " — сохранён дефолт для новых сессий (живая недоступна)")


# ── Меню выбора в консоли → Telegram ────────────────────────────────────────
# Claude Code иногда останавливается на интерактивном меню («Model switch» при
# срабатывании safeguards и т.п.) и ждёт клавишу: пока человек не подойдёт к консоли,
# сессия стоит — soft lock. Сторож замечает такое меню (футер «Enter to select ·
# ↑/↓ to navigate»), шлёт его в Telegram с URL-кнопками вариантов; кнопка открывает
# /cc-hook/dialog/answer с одноразовым ключом, и номер варианта уходит в screen.
# URL-кнопки, а не callback: getUpdates этого бота уже слушает телеграм-канал
# Claude Code, второй опрос забирал бы у него апдейты.
_DLG_FOOTER_RE = re.compile(r"Enter to select.*to navigate")
# hardcopy режет не-ASCII до codepoint & 0x7F (см. ниже у _console_dims): курсор «❯»
# приходит буквой/знаком, линия «─» — нулевыми байтами, поэтому префиксы — любые
_DLG_OPT_RE = re.compile(r"^\s*(?:[^\d\s]{1,2}\s+)?(\d{1,2})\.\s+(\S.*?)\s*$")
_DLG_RULE_RE = re.compile(r"^\s*[─━\x00-]{10,}\s*$")
_DLG_SKIP_OPTS = ("Type something",)  # требует ввода текста — из Telegram не ответить
_DLG = {"sig": None, "seen": 0, "key": None, "msg_id": None, "opts": {}, "title": ""}
_DLG_LOCK = threading.Lock()
_html_escape = html.escape  # в do_GET имя html занято локальной переменной


def _tg_call(method, payload):
    token = tg_token()
    if not token or not cfg().get("chat_id"):
        return None
    try:
        return http_json(f"https://api.telegram.org/bot{token}/{method}", payload)
    except Exception as e:
        print(f"tg {method} fail: {e}", flush=True)
        return None


def parse_console_menu(txt):
    """Нижнее интерактивное меню на экране → {"title", "body", "options": [(n, text, hint)]}
    или None. Заголовок и текст — от ближайшей горизонтальной линии над «1.»."""
    lines = [l.rstrip() for l in (txt or "").splitlines()]
    foot = max((i for i, l in enumerate(lines) if _DLG_FOOTER_RE.search(l)), default=None)
    if foot is None:
        return None
    # футер живого меню — внизу экрана; та же фраза выше по экрану — это цитата в
    # переписке, а не меню
    if sum(1 for l in lines[foot + 1:] if l.strip()) > 3:
        return None
    first = None
    for i in range(foot - 1, max(foot - 60, -1), -1):
        m = _DLG_OPT_RE.match(lines[i])
        if m and m.group(1) == "1":
            first = i
            break
    if first is None:
        return None
    opts, cur = [], None
    for l in lines[first:foot]:
        m = _DLG_OPT_RE.match(l)
        if m and int(m.group(1)) == len(opts) + 1:
            cur = [int(m.group(1)), m.group(2).rstrip("."), ""]
            opts.append(cur)
        elif cur and l.strip() and not _DLG_RULE_RE.match(l) and not cur[2]:
            cur[2] = l.strip()
        elif not l.strip():
            cur = None if cur and cur[2] else cur
    top = first
    for i in range(first - 1, max(first - 40, -1), -1):
        if _DLG_RULE_RE.match(lines[i]):
            break
        top = i
    head = [l.strip(" │|") .strip() for l in lines[top:first]]
    head = [re.sub(r"^[^\w«\"(]+\s*", "", l) if j == 0 else l for j, l in enumerate(head) if l.strip()]
    title = head[0] if head else ""
    body = " ".join(head[1:])
    return {"title": title, "body": body, "options": [tuple(o) for o in opts]} if opts else None


def _dlg_public_base():
    return (cfg().get("public_url") or "").rstrip("/")


def _dlg_notify(menu):
    key = os.urandom(12).hex()
    opts = [o for o in menu["options"] if not any(s in o[1] for s in _DLG_SKIP_OPTS)]
    text = "⏸ Консоль ждёт выбора\n\n" + (menu["title"] or "Меню") + "\n"
    if menu["body"]:
        text += menu["body"][:1500] + "\n"
    text += "\n" + "\n".join(f"{n}. {t}" + (f" — {h}" if h else "") for n, t, h in menu["options"])
    base = _dlg_public_base()
    payload = {"chat_id": cfg().get("chat_id"), "text": text}
    if base:
        payload["reply_markup"] = {"inline_keyboard": [
            [{"text": f"{n}. {t}"[:60], "url": f"{base}/cc-hook/dialog/answer?k={key}&n={n}"}]
            for n, t, _ in opts]}
    else:
        payload["text"] += "\n\n(кнопок нет: в config.json не задан public_url — ответь в консоли)"
    r = _tg_call("sendMessage", payload)
    mid = ((r or {}).get("result") or {}).get("message_id")
    _DLG.update(key=key, msg_id=mid, opts={n: t for n, t, _ in opts}, title=menu["title"])


def _dlg_close_msg(note):
    if _DLG.get("msg_id"):
        _tg_call("editMessageReplyMarkup", {"chat_id": cfg().get("chat_id"),
                 "message_id": _DLG["msg_id"], "reply_markup": {"inline_keyboard": []}})
        _tg_call("sendMessage", {"chat_id": cfg().get("chat_id"), "text": note,
                 "reply_to_message_id": _DLG["msg_id"]})
    _DLG.update(sig=None, seen=0, key=None, msg_id=None, opts={}, title="")


def _dlg_tick(txt):
    """Вызывается сторожем раз в ~5 с с текущим экраном."""
    menu = parse_console_menu(txt)
    with _DLG_LOCK:
        if not menu:
            if _DLG.get("msg_id"):
                _dlg_close_msg("Меню в консоли закрыто — выбор больше не нужен.")
            else:
                _DLG.update(sig=None, seen=0)
            return
        sig = menu["title"] + "|" + "|".join(t for _, t, _ in menu["options"])
        if sig != _DLG.get("sig"):
            if _DLG.get("msg_id"):
                _dlg_close_msg("Меню в консоли сменилось.")
            _DLG.update(sig=sig, seen=1)
            return
        _DLG["seen"] += 1
        # второй тик подряд (~5–10 с): не дёргать Telegram из-за меню, которое
        # человек открыл в консоли сам и тут же закрыл
        if _DLG["seen"] == 2 and not _DLG.get("msg_id"):
            _dlg_notify(menu)


def dialog_answer(key, n):
    """Нажатие кнопки из Telegram. → (ok, текст для страницы)."""
    scr = cfg().get("screen_session", "claude")
    with _DLG_LOCK:
        if not key or key != _DLG.get("key"):
            return False, "Это меню уже закрыто или на него уже ответили."
        if n not in _DLG["opts"]:
            return False, "Такого варианта нет."
        sig = _DLG["sig"]
        choice = _DLG["opts"][n]
        _DLG["key"] = None  # одноразовый ключ
    subprocess.run(["screen", "-S", scr, "-p", "0", "-X", "stuff", str(n)],
                   capture_output=True, timeout=10)
    time.sleep(1.5)
    menu = parse_console_menu(screen_hardcopy())
    if menu and menu["title"] + "|" + "|".join(t for _, t, _ in menu["options"]) == sig:
        # цифра только перевела курсор — подтверждаем
        subprocess.run(["screen", "-S", scr, "-p", "0", "-X", "stuff", "\r"],
                       capture_output=True, timeout=10)
    with _DLG_LOCK:
        if _DLG.get("sig") == sig:
            _dlg_close_msg(f"✅ Выбрано: {n}. {choice}")
    return True, f"Выбрано: {n}. {choice}"


# Рантайм иногда сам отдаёт сессию другой модели — напр. safeguard
# Opus 5.5 пометил сессию, и «Opus 4.8 is answering instead» — без меню и без записи
# в settings.json, поэтому это было незаметно. Сторож сравнивает модель в статус-строке
# с дефолтом из settings.json: ушла с дефолта не через /model (/model дефолт тоже
# меняет) — сообщение в Telegram; вернулась — второе сообщение.
_MW = {"last": None, "cand": None, "cand_n": 0, "away": False}
_SAFEGUARD_RE = re.compile(r"(\w+ \d+(?:\.\d+)?)'s safeguards? flagged this session")


def _model_watch_tick(txt):
    name = status_model_name(txt)
    if not name:
        return
    # две одинаковые подряд (~10 с) — чтобы битый кадр hardcopy не дал ложную смену
    if name != _MW["cand"]:
        _MW["cand"], _MW["cand_n"] = name, 1
        return
    _MW["cand_n"] += 1
    if _MW["cand_n"] < 2 or name == _MW["last"]:
        return
    prev, _MW["last"] = _MW["last"], name
    if prev is None:
        return  # первый замер после старта сервиса
    dflt_id = (jload(SETTINGS, {}) or {}).get("model")
    # профиль «Opus → Sonnet» запускает консоль на Opus при дефолте Sonnet — ждём модель профиля, а не дефолт
    try:
        dflt_id = (jload(os.path.join(BASE, "profile_runtime", "claude-policy.json"), {}) or {}).get("expected_model") or dflt_id
    except Exception:
        pass
    dflt = all_models().get(dflt_id, dflt_id)
    if name != dflt:
        sg = _SAFEGUARD_RE.search(txt.replace("\n", " "))
        why = (f"сработал safeguard {sg.group(1)} — рантайм сам отдал ответы {name}"
               if sg else "не через /model (дефолт в настройках — " + str(dflt) + ")")
        tg_notify(f"⚠️ Модель сессии сменилась автоматически: {prev} → {name}\n"
                  f"Причина: {why}.\nВернуть: /model {dflt_id} в консоли или кнопка «Модель» в панели.")
        _MW["away"] = True
    elif _MW["away"]:
        tg_notify(f"✅ Модель сессии снова {name} (была {prev}).")
        _MW["away"] = False


# Занятость живой сессии — по строке спиннера над полем ввода, пока идёт ход:
# "✻ Harmonizing… (27s · ↓ 2.0k tokens)". hardcopy режет не-ASCII (… → &, значок
# спиннера → любой символ), поэтому опираемся на ASCII-часть: слово, многоточие,
# "(Ns". После хода строка становится "✻ Worked for 27s" — без скобки, не совпадает.
_SPINNER_RE = re.compile(
    r"^\s*(?:\S{1,2}\s+)?[A-Za-z][\w-]*(?:…|&|\.\.\.)\s*"
    r"\((?:(?:\d+h\s*)?(?:\d+m\s*)?\d+s\b|esc to interrupt)", re.M)
# idle_n — сколько тиков сторожа подряд спиннера нет: один битый кадр hardcopy не
# должен выглядеть паузой. defer_pending ставит optimize_check, пока ждёт паузу.
_BUSY = {"idle_n": 99, "tick_ts": 0.0, "defer_pending": False, "wake_ts": 0.0}
_POLL_WAKE = threading.Event()


def _busy_tick(txt):
    tail = "\n".join([l for l in (txt or "").splitlines() if l.strip()][-30:])
    _BUSY["tick_ts"] = time.time()
    if _SPINNER_RE.search(tail):
        _BUSY["idle_n"] = 0
        return
    _BUSY["idle_n"] += 1
    # пауза только что началась, а плановое переключение ждёт её — будим poll_loop,
    # не дожидаясь poll_sec (иначе короткую паузу между ходами можно проспать)
    if _BUSY["idle_n"] == 2 and _BUSY["defer_pending"] and time.time() - _BUSY["wake_ts"] > 60:
        _BUSY["wake_ts"] = time.time()
        _POLL_WAKE.set()


def session_busy():
    # сторож не тикал больше минуты (нет screen-сессии, hardcopy висит) — занятость
    # неизвестна, переключение не держим
    if time.time() - _BUSY["tick_ts"] > 60:
        return False
    return _BUSY["idle_n"] < 2


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
            else:
                _dlg_tick(txt)
            _model_watch_tick(txt)
            _busy_tick(txt)
        except Exception:
            pass
        time.sleep(5)


def set_default_model(model_id):
    models = all_models()
    if model_id not in models:
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
    return True, models[model_id] + (" — дефолт сохранён; в текущей сессии применится, если она сейчас свободна (иначе повтори)" if live else " — сохранён дефолт для новых сессий (живая недоступна)")


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


_redraw_lock = threading.Lock()
REDRAW_HOLD = 2.0   # сек: сколько окно сессии остаётся на колонку уже, пока Claude Code перестраивает кадр


def redraw_console(lang="ru"):
    """Кнопка «Перерисовать консоль» (вкладка Claude DEV). Claude Code рисует экран диф-обновлениями: что потерялось
    в console.log (полоски лимитов под консолью, обрезанный кусок), само не вернётся. Настоящий ресайз pty окна сессии
    (cols -> cols-1 -> cols; ядро шлёт SIGWINCH) заставляет его перестроить кадр целиком, и полный кадр попадает в лог.
    В сессию ничего не вводится (в отличие от /clear), разговор не затрагивается, размер возвращается как был."""
    if not _redraw_lock.acquire(blocking=False):
        return False, _t(lang, "Перерисовка уже идёт.", "A redraw is already running.")
    try:
        pid = _current_screen_pid(cfg().get("screen_session", "claude"))
        path = _console_window_pty(pid)
        if not path:
            return False, _t(lang, "Консоль Claude не запущена: перерисовывать нечего.", "Claude console is not running: nothing to redraw.")
        fd = os.open(path, os.O_RDONLY | os.O_NOCTTY)
        try:
            rows, cols = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0)))[:2]
            if rows < 5 or cols < 21:
                return False, _t(lang, "Неожиданный размер окна консоли, не трогаю.", "Unexpected console window size, leaving it alone.")
            try:
                fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols - 1, 0, 0))
                time.sleep(REDRAW_HOLD)
            finally:
                fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))   # размер возвращаем при любом исходе
        finally:
            os.close(fd)
        return True, _t(lang, "Консоль перерисована: полный кадр появится через пару секунд.", "Console redrawn: the full frame appears in a couple of seconds.")
    except Exception:
        return False, _t(lang, "Не удалось перерисовать консоль (сессия недоступна).", "Could not redraw the console (session unavailable).")
    finally:
        _redraw_lock.release()


def codex_setup_prompt(lang="ru"):
    return cc_codex.setup_prompt(lang, CONFIG, cfg().get("port", 8877))


SETUP_CHUNK = 200  # байт за один screen stuff (предел ~730; на старых screen ниже)
SETUP_PAUSE = (0.4, 1.2)  # сек: между текстом и Enter; после Enter перед чтением экрана


def send_codex_setup(lang="ru"):
    """Вставляет промт «подключи Codex» в живую консоль Claude → (ok, seen). ok — screen принял ввод; seen — метка промта
    видна на экране консоли (занятая консоль может молча потерять ввод, тогда seen=False и человек копирует промт руками)."""
    scr = cfg().get("screen_session", "claude")
    base = ["screen", "-S", scr, "-p", "0", "-X"]
    try:
        # screen stuff целиком выбрасывает ввод длиннее ~730 байт (rc=0, ничего не приходит) → кусками по SETUP_CHUNK байт (промт ASCII);
        # потом Enter отдельным вводом: длинный ввод консоль принимает как вставку, и Enter в её конце не отправил бы запрос
        text = codex_setup_prompt(lang)
        for i in range(0, len(text), SETUP_CHUNK):
            if subprocess.run(base + ["stuff", text[i:i + SETUP_CHUNK]], capture_output=True, timeout=10).returncode != 0:
                return False, False
        time.sleep(SETUP_PAUSE[0])
        if subprocess.run(base + ["stuff", "\r"], capture_output=True, timeout=10).returncode != 0:
            return False, False
        time.sleep(SETUP_PAUSE[1])
        fd, path = tempfile.mkstemp(prefix="ccsetup_", suffix=".txt")
        os.close(fd)
        try:
            subprocess.run(base + ["hardcopy", path], capture_output=True, timeout=10)
            with open(path, encoding="utf-8", errors="replace") as f:
                return True, cc_codex.SETUP_MARK in f.read()
        finally:
            os.remove(path)
    except Exception:
        return False, False


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
    cap = c.get("weekly_cap", 99)
    act_free = accs[act].get("plan") == "free"
    cur = (accs[act].get("five_hour") or {}).get("pct")
    cur_w = (accs[act].get("seven_day") or {}).get("pct")
    act_ok, _t, act_why = cc_avail.availability(accs[act], thr, cap)
    if not act_free:
        if act_ok:
            st["all_high_notified"] = False
            jsave(STATE, st)
            return
        # ручной выбор: человек сознательно взял забитый аккаунт (сессия выше порога или неделя
        # на потолке) — не трогать до сброса этого окна или до 100%
        if cc_avail.manual_pick(st.get("manual_hold"), act, accs[act]):
            return
    # кулдаун против пинг-понга; с мёртвого (100% сессии/недели) и с недельного потолка
    # уходим без него: неделя держит днями, вернуться туда балансер не сможет
    week_full = not act_free and cur_w is not None and cur_w >= cap
    if (not _dead(accs[act]) and not week_full
            and time.time() - st.get("last_switch_ts", 0) < c.get("switch_cooldown_sec", 600)):
        return
    # кандидаты: не активный, без ошибок, пригодный сейчас (сессия и неделя ниже порогов, не Free)
    cand = []
    for n, row in accs.items():
        if n == act or row.get("error"):
            continue
        fh = (row.get("five_hour") or {}).get("pct")
        if fh is None:
            continue
        if cc_avail.availability(row, thr, cap)[0]:
            cand.append((fh, n))
    if not cand:
        if _handoff_coming():
            return  # работа уходит на Claude PROD: «некуда» неправда, флаг эпизода не ставим — если передача не выйдет, сообщение уйдёт на следующем проходе
        text, lvl = _nowhere_text(accs, act, act_free)
        if not st.get("all_high_notified") or _week_news(st, lvl):
            _notice_send(text, lvl)
            st["all_high_notified"] = True
            st["nowhere_lvl"] = lvl
            jsave(STATE, st)
        return
    cand.sort()
    fh, target = cand[0]
    ok, out = do_switch(target)
    st["last_switch_ts"] = time.time()
    st["all_high_notified"] = False
    week_why = not act_free and "сессия" not in act_why
    if ok:
        st["known_active"] = target
        if (st.get("manual_hold") or {}).get("account") == act:
            st.pop("manual_hold", None)  # ручной выбор отработал: аккаунт дошёл до 100%
        if week_why:
            # это сообщение и есть предупреждение о недельном потолке — _week_cap_warn() второго не шлёт
            st.setdefault("week_warned", {})[act] = _week_key(accs[act].get("seven_day") or {})
    jsave(STATE, st)
    email = accs[target].get("email", target)
    wreset = (accs[act].get("seven_day") or {}).get("resets_at")
    why = (f"аккаунт {act} слетел в Free" if act_free
           else f"сессия {act} дошла до {cur}%" if not week_why
           else f"неделя {act} дошла до {round(cur_w or 0)}% (потолок {cap:g}%), до сброса недели"
                + (f" ({_local_dhm(wreset)})" if wreset else "") + " балансер его не берёт")
    if ok:
        tg_notify(f"🔄 Claude: {why} — авто-переключил на {target} ({email}, сессия {fh}%). Рестарт не нужен.")
        snap_set_active()
    else:
        tg_notify(f"⚠️ Claude: авто-переключение на {target} не удалось: {out}")


_dead = cc_avail.dead  # аккаунт упёрся в 100% сессии или недели — работать на нём нельзя совсем


def _manual_until(row):
    """До когда держать ручной выбор аккаунта: он не пригоден по сессии или неделе — до сброса
    позднейшего из держащих окон (cc_avail знает, какие держат); пригоден или Free — 0, пина нет."""
    c = cfg()
    ok, ts, why = cc_avail.availability(row, c.get("threshold", 85), c.get("weekly_cap", 99))
    if ok or why == "free" or row.get("error"):
        return 0
    return ts or time.time() + (5 * 3600 if why == "сессия" else 7 * 86400)


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


def _renewal_next(confirmed_ts):
    # Таймер до следующего ожидаемого обвала Pro→Free: якорь минус 30 мин
    # буфера (подтверждение продления не секунда в секунду) плюс календарный
    # месяц (relativedelta, не фиксированные 30 дней — иначе на длинных
    # месяцах дата "уезжает" вперёд от реального списания).
    from datetime import datetime, timedelta, timezone
    from dateutil.relativedelta import relativedelta
    anchor = datetime.fromtimestamp(confirmed_ts, tz=timezone.utc) - timedelta(minutes=30)
    now = datetime.now(timezone.utc)
    nxt = anchor + relativedelta(months=1)
    # если подписка продлилась тихо, без видимого обвала в Free (анкор не
    # обновился ни авто-детектом, ни кнопкой «Я продлил») — предсказанная дата
    # уезжает в прошлое и виснет там навсегда. Докручиваем на календарные
    # месяцы, пока не попадём в будущее — иначе на экране вечно "ждём сегодня".
    while nxt <= now:
        nxt += relativedelta(months=1)
    return nxt.isoformat()


def _renewal_applicable(row):
    # Чип "⏳ до PRO→FREE" осмыслен только пока аккаунт реально Pro — это
    # прогноз КОГДА подписка упадёт в Free. Если план уже free, обвал уже
    # случился: показывать новый отсчёт до следующего "обвала" до нажатия
    # «Я продлил» — путает (обвал уже произошёл, значения больше нет),
    # найдено живьём 24.10: экран одновременно показывал FREE и "⏳ 29 дн".
    return row.get("plan") == "pro"


def _page_tz():
    """IANA-имя зоны для времени на странице (config.json "tz"); пусто — браузер показывает свою зону."""
    name = str(cfg().get("tz") or "")
    return name if re.fullmatch(r"[A-Za-z0-9_+./-]{1,64}", name) else ""


def _local_hm(iso):
    # время сброса, коротко: «07:40». Если self-host крутится не в твоём
    # часовом поясе (сервер в одном регионе, ты в другом) — голый
    # .astimezone() тихо покажет ВРЕМЯ СЕРВЕРА, а не твоё. Задай IANA-имя
    # зоны в ключе "tz" config.json (например "Asia/Irkutsk") — тогда время
    # переводится явно, независимо от того, где физически стоит сервер. Без
    # ключа — прежнее поведение (зона сервера).
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso)
        tzname = cfg().get("tz")
        if tzname:
            from zoneinfo import ZoneInfo
            return dt.astimezone(ZoneInfo(tzname)).strftime("%H:%M")
        return dt.astimezone().strftime("%H:%M")
    except Exception:
        return "?"


def _local_dhm(iso):
    # «сб 04.10 в 05:00»: для недельного сброса одного HH:MM мало; зона — как в _local_hm()
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso)
        tzname = cfg().get("tz")
        if tzname:
            from zoneinfo import ZoneInfo
            dt = dt.astimezone(ZoneInfo(tzname))
        else:
            dt = dt.astimezone()
        return "%s %s в %s" % ("пн вт ср чт пт сб вс".split()[dt.weekday()], dt.strftime("%d.%m"), dt.strftime("%H:%M"))
    except Exception:
        return "?"


def _accs_line(accs):
    out = []
    for n, row in sorted(accs.items()):
        fh = row.get("five_hour") or {}
        r = fh.get("resets_at")
        sd = row.get("seven_day") or {}
        rw = sd.get("resets_at")
        out.append("%s: сессия %s%%%s, неделя %s%%%s" % (
            n, fh.get("pct"), (" (сброс %s)" % _local_hm(r)) if r else "",
            sd.get("pct"), (" (сброс %s)" % _local_hm(rw)) if rw else ""))
    return "\n".join(out)


def _nearest_reset(accs):
    # кто раньше всех снова станет пригоден — с учётом и сессии, и недели
    c = cfg()
    nb = cc_avail.nearest(accs, c.get("threshold", 90), c.get("weekly_cap", 99))
    if not nb:
        return "неизвестно"
    from datetime import datetime
    return "%s в %s" % (nb[1], _local_hm(datetime.fromtimestamp(nb[0]).astimezone().isoformat()))


WEEK_LEVELS = ("week", "weekrisk")


def _pause_mod():
    import sys
    if BASE not in sys.path:
        sys.path.insert(0, BASE)
    import pause_ctl  # данные модуль читает с диска на каждый вызов — кэш не мешает
    return pause_ctl


def _prod_hint():
    """Claude PROD свободен, а у DEV лимит (pause_ctl.prod_hint) → {…}; нет PROD или сбой → {}."""
    try:
        return _pause_mod().prod_hint()
    except Exception:
        return {}


def _prod_phrase(h):
    return _pause_mod().prod_phrase(h)


def _notice_send(text, key):
    """Одно сообщение «упёрлись в лимит» на эпизод: пауза, балансер и очередь делят отметку (pause_ctl.notice_claim).
    Раньше про один и тот же лимит приходило 3–4 сообщения подряд. Отметка недоступна — пишем как раньше."""
    try:
        if not _pause_mod().notice_claim(key):
            print("notice %s: об эпизоде уже написали — второе сообщение не шлю" % key, flush=True)
            return False
    except Exception:
        pass
    return tg_notify(text)


def _nowhere_text(accs, act, act_free=False):
    """(текст, level) уведомления «переключаться некуда» — что будет дальше, по тому же
    pause_ctl.level_state(), что и баннер. До v1.21.0 здесь всегда было «жду», хотя с
    недельного потолка никто не уходил и аккаунт добивался до 100%."""
    ls = pause_state()
    lvl = ls.get("level") or "none"
    override = bool((ls.get("pause") or {}).get("override"))
    w = round(((accs.get(act) or {}).get("seven_day") or {}).get("pct") or 0)
    cap = ls.get("weekly_cap") or cfg().get("weekly_cap", 99)
    tail = "\n" + _accs_line(accs) + "\nРаньше всех освободится: " + _nearest_reset(accs)
    # Claude PROD свободен, но работа к нему не уходит (автопередача выключена и т. п.): «переключаться некуда» было бы неправдой
    prod = {} if act_free or lvl not in ("hard", "week") else _prod_hint()
    nowhere = _prod_phrase(prod) if prod else "переключаться некуда"
    who = "Claude DEV" if prod else "Claude"
    if prod:
        tail = ("\n" + _accs_line(accs) + "\nDEV поднимется сам: " + _nearest_reset(accs)
                + ("" if prod.get("on") else "\nРаньше — передать работу на PROD: «Работа на PROD» на панели"
                   + (" или включить «Автопередача» в «Настройки PROD»." if prod.get("why") == "автопередача выключена" else ".")))
    if act_free:
        head = f"⛔ Claude: {act} слетел в Free, остальные недоступны — переключаться некуда, жду, пока освободится другой."
    elif lvl == "week" and not override:
        head = (f"⏸ Claude: неделя {act} — {w}% (потолок {cap:.0f}%), {nowhere} — {who} встаёт на паузу. "
                "Поднимется сам, когда освободится другой аккаунт или сбросится неделя"
                # на 100% недели настоящий лимит исчерпан — отключать паузу бесполезно
                + ("." if w >= 100 else "; продолжить сразу — «Отключить паузу» на панели."))
    elif lvl in WEEK_LEVELS:
        head = (f"⚠️ Claude: неделя {act} — {w}%, переключаться некуда. Балансер не остановит заполнение "
                "до 100% — работаешь на свой страх и риск.")
        head += ("\nПауза отключена вручную на панели." if override else
                 f"\nОстановку на {cap:.0f}% можно включить: ⚙ Настройки → «Пауза на недельном потолке».")
    elif lvl == "hard" and not override:
        head = f"⛔ Claude: {ls.get('why') or 'все аккаунты выше порога сессии'} — {who} встаёт на паузу до сброса окна."
    elif lvl == "hard":
        head = (f"⛔ Claude: {ls.get('why') or 'все аккаунты выше порога сессии'}. "
                "Пауза отключена вручную: работа идёт до настоящего лимита аккаунта.")
    else:
        head = f"⛔ Claude: переключаться некуда — работа идёт дальше на {act} сверх порога, пока не освободится другой аккаунт."
    return head + tail, lvl


def _handoff_coming():
    """[remote] Работа вот-вот уйдёт на Claude PROD (автопередача готова) или уже идёт там: «переключаться некуда» в Telegram не пишем —
    о переходе скажет сама передача; не вышла — встанет обычная пауза со своим сообщением (владелец 62582, как баннер 62577)."""
    try:
        d = pause_state()
        return bool(d.get("handoff") or d.get("remote"))
    except Exception:
        return False


def _week_news(st, lvl):
    """Эпизод «некуда» уже начался по сессии, а теперь упёрлись в недельный потолок —
    об этом сообщаем отдельно (иначе флаг эпизода проглотит предупреждение о 100%)."""
    return lvl in WEEK_LEVELS and st.get("nowhere_lvl") not in WEEK_LEVELS


def _week_key(sd):
    # ключ недели аккаунта — время её сброса (resets_at плавает на доли секунды, поэтому число, не строка)
    try:
        from datetime import datetime
        return datetime.fromisoformat(sd["resets_at"]).timestamp()
    except Exception:
        return 0


def _week_cap_warn(snap):
    """Неделя аккаунта дошла до потолка (weekly_cap, 99%) — ровно одно сообщение на аккаунт
    за неделю, активный он или нет и есть ли куда переключиться. Где это уже сказало
    сообщение балансера («авто-переключил… неделя», «переключаться некуда» на неделе),
    второго не шлём. Активный, с которого балансер вот-вот уйдёт, ждёт ухода: тогда
    сообщение скажет, куда ушли."""
    c = cfg()
    cap = c.get("weekly_cap", 99)
    st = jload(STATE, {})
    warned = dict(st.get("week_warned") or {})
    accs = snap.get("accounts") or {}
    act = (jload(SNAPSHOT) or {}).get("active") or snap.get("active")  # после переключения в этом же тике
    now = time.time()
    for n in list(warned):
        w = ((accs.get(n) or {}).get("seven_day") or {}).get("pct")
        if (warned[n] and now > warned[n] + 600) or (w is not None and w < cap - 5):
            del warned[n]  # неделя сбросилась — следующий потолок снова предупредит
    lvl = None
    for n, row in sorted(accs.items()):
        sd = row.get("seven_day") or {}
        w = sd.get("pct")
        if row.get("error") or row.get("plan") == "free" or w is None or w < cap:
            continue
        key = _week_key(sd)
        if n in warned and abs(warned[n] - key) < 6 * 3600:
            continue
        reset = sd.get("resets_at")
        head = f"⚠️ Claude: неделя {n} дошла до {round(w)}% (потолок {cap:g}%)."
        text = None
        if n != act:
            # обычная смена аккаунта, а не пауза: «Пауза на недельном потолке» тут ни при чём
            text = (f"ℹ️ Claude: неделя {n} — {round(w)}%, это потолок балансера"
                    + (f" (последний {100 - cap:g}% — запас)" if cap < 100 else "") + "."
                    + f" {n} отдыхает до сброса недели"
                    + (f" — {_local_dhm(reset)}" if reset else "")
                    + (f", работа идёт на {act}." if act else ".")
                    + " Это обычная смена аккаунта, не пауза: «Пауза на недельном потолке»"
                      " срабатывает, только когда переключаться некуда.")
        else:
            if lvl is None:
                lvl = pause_state().get("level") or "none"
            hold = st.get("manual_hold") or {}
            if lvl in WEEK_LEVELS:
                if not (st.get("all_high_notified") and st.get("nowhere_lvl") in WEEK_LEVELS):
                    text = _nowhere_text(accs, act)[0]  # балансер выключен — «некуда» никто не сказал
            elif not c.get("optimize") and not c.get("autoswitch", True):
                text = (f"{head} Авто-переключение выключено — балансер не уведёт с {n}: "
                        "переключись вручную, иначе он добьётся до 100%.")
            elif not c.get("optimize") and hold.get("account") == n and now < hold.get("until", 0):
                from datetime import datetime
                text = (f"{head} {n} выбран вручную — балансер не уведёт с него до "
                        f"{_local_dhm(datetime.fromtimestamp(hold['until']).astimezone().isoformat())} "
                        "или до 100%; заполнение до 100% — на твой риск.")
            else:
                continue  # балансер уходит с него в ближайшие тики — предупредим, когда уйдёт
        warned[n] = key
        if text:
            if n == act and lvl in WEEK_LEVELS:
                _notice_send(text, lvl)  # это «некуда» на неделе — делит отметку с паузой и балансером
            else:
                tg_notify(text)
    if warned != (st.get("week_warned") or {}):
        st["week_warned"] = warned
        jsave(STATE, st)


def _log_switch_event(event, **kw):
    # Аудит-лог forced-веток: state.json хранит только ПОСЛЕДНИЙ переключение
    # (last_switch_ts), поэтому разобрать задним числом "почему не переключилось
    # раньше" (гейт-баннер против cooldown, отсутствие кандидата и т.п.) нечем.
    # Пишем по строке на каждый forced-момент — для последующей диагностики
    # тайминга, не для логики самого переключения.
    try:
        rec = {"ts": time.time(), "event": event}
        rec.update(kw)
        with open(SWITCH_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def optimize_check(snap):
    # Режим «оптимизация переключений лимитов»: сервис сам рулит и порогами —
    # настройки threshold/autoswitch здесь игнорируются (UI их гасит).
    # Неделя: держим активным аккаунт с максимальным _opt_score (запас/час до
    # сброса — неистраченное сгорает). Сессия: нагрузку размазываем, чтобы не
    # оказаться со всеми забитыми сессиями разом — ранний уход с opt_ses_soft
    # при свежем кандидате, аварийный форс с opt_ses_ceil, кандидаты штрафуются
    # за забитую сессию. manual_hold игнорируем: ручные свитчи заблокированы.
    c = cfg()
    # аварийный уход: тот же порог, что и на слайдере/баннере (threshold), не
    # отдельный ключ opt_ses_ceil — раньше он никогда не выставлялся install.sh
    # и не был связан со слайдером, поэтому его правка ничего не меняла в режиме
    # оптимизации, хотя визуально выглядела как рабочая настройка.
    ses_ceil = c.get("threshold", c.get("opt_ses_ceil", 90))
    ses_soft = c.get("opt_ses_soft", 70)      # ранний уход при свежем кандидате
    ses_cand = c.get("opt_ses_cand_max", 85)  # кандидат: сессия не выше
    ses_fresh = c.get("opt_ses_fresh", 50)    # «свежая» сессия для раннего ухода
    # порог поднят с 95 до 99 (v1.9.7) — 95% недельного лимита ещё оставляет
    # заметный запас, отсекать кандидата/форсить уход с этой отметки было
    # слишком рано; используется и как порог форс-ухода (forced ниже), и
    # как порог допуска кандидата в collect_cand()
    cap = c.get("weekly_cap", 99)
    ratio = c.get("optimize_ratio", 1.5)
    _BUSY["defer_pending"] = False
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
    if forced:
        _log_switch_event("forced_true", active=act, fh=fh, sd=sd, act_free=act_free)

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
        # Без потолка по СЕССИИ вообще берём наименее забитый живой (не-free)
        # аккаунт — лишь бы он был реально лучше активного (иначе бессмысленный
        # треш). Смысл: не дать всем трём одновременно упереться в 100% и
        # застрять без единого рабочего окна — немного запаса лучше, чем совсем
        # ноль. НО недельный потолок (cap) по-прежнему обязателен даже здесь —
        # без этой проверки сюда мог попасть аккаунт со свежей сессией, но
        # забитой под 100% неделей: переключались на него, а дальше выбраться
        # некуда — его низкий five_hour% вечно выглядит "лучше" любого
        # кандидата по этой же метрике, и балансер застревал на функционально
        # мёртвом (по неделе) аккаунте навсегда (v1.10.0).
        best = None
        for n, row in accs.items():
            if n == act or row.get("error") or row.get("plan") == "free":
                continue
            cfh = (row.get("five_hour") or {}).get("pct")
            if cfh is None:
                continue
            csd = (row.get("seven_day") or {}).get("pct")
            if csd is not None and csd >= cap:
                continue
            if best is None or cfh < best[0]:
                best = (cfh, n)
        if best and (fh is None or best[0] < fh):
            now = time.time()
            if _dead(a) or now - st.get("last_switch_ts", 0) >= c.get("switch_cooldown_sec", 600):
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
                _log_switch_event("extreme_switch", from_acc=act, to=target, fh=fh, target_fh=tfh, ok=ok)
                if ok:
                    # (30.07.26) уведомление о крайнем случае убрано - спамило в чат.
                    # Переключение по-прежнему происходит, просто молча.
                    snap_set_active()
                else:
                    tg_notify("⚠️ Claude (оптимизация): переключение на %s не удалось: %s" % (target, out))
                return
            else:
                _log_switch_event("extreme_blocked_cooldown", active=act, fh=fh,
                                   remaining_sec=round(c.get("switch_cooldown_sec", 600) - (now - st.get("last_switch_ts", 0))))
    if not cand:
        if forced:
            _log_switch_event("forced_no_candidate", active=act, fh=fh, sd=sd,
                              nearest=_nearest_reset(accs))
        if forced and _handoff_coming():
            return  # работа уходит на Claude PROD (см. autoswitch_check): «некуда» не пишем
        text, lvl = _nowhere_text(accs, act, act_free) if forced else ("", "")
        if forced and (not st.get("all_high_notified") or _week_news(st, lvl)):
            # раньше уведомление отсюда убрали как спам, и «упёрлись ВСЕ аккаунты» стало
            # происходить молча — пользователь может не понимать, почему сессия не работает,
            # часами. Возвращаем ровно ОДНО сообщение на эпизод (флаг снимается только когда
            # снова появился живой кандидат) и не чаще раза в 2 часа. Это не тот спам, что
            # убирали: успешные переключения по-прежнему молчат.
            # предупреждение о недельном потолке не глушим двухчасовым окном: без него
            # человек не узнает, что аккаунт добивается до 100% (или что Claude встал)
            if lvl in WEEK_LEVELS or time.time() - st.get("all_high_notified_ts", 0) >= 7200:
                _notice_send(text, lvl)
                st["all_high_notified_ts"] = time.time()
            st["all_high_notified"] = True
            st["nowhere_lvl"] = lvl
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
        if not _dead(a) and now - st.get("last_switch_ts", 0) < c.get("switch_cooldown_sec", 600):
            _log_switch_event("forced_blocked_cooldown", active=act, fh=fh, target=target,
                               remaining_sec=round(c.get("switch_cooldown_sec", 600) - (now - st.get("last_switch_ts", 0))))
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
    # Смена аккаунта посреди хода сбрасывает кэш промпта (вся сессия перечитывается за
    # счёт нового аккаунта), а у Sonnet 5.5 ещё и выкидывает рассуждения хода (thinking
    # привязан к организации). Плановое переключение ждёт паузы между ходами, но не
    # дольше opt_defer_max_sec; аварийное (forced) уходит сразу. 0 — не ждать.
    dfr = st.get("defer") or {}
    if dfr and now - dfr.get("seen", 0) > 300:
        dfr = {}  # прошлое ожидание прервалось (переключение стало не нужно) — новый эпизод
    defer_max = c.get("opt_defer_max_sec", 900)
    if not forced and defer_max > 0 and session_busy() and now - dfr.get("since", now) < defer_max:
        first = not dfr
        st["defer"] = {"since": dfr.get("since", now), "seen": now, "to": target}
        jsave(STATE, st)
        _BUSY["defer_pending"] = True
        if first:
            _log_switch_event("deferred_busy", from_acc=act, to=target, fh=fh, why=why)
        return
    waited = round(now - dfr["since"]) if dfr else 0
    st.pop("defer", None)
    _BUSY["defer_pending"] = False
    ok, out = do_switch(target)
    st["last_switch_ts"] = now
    st["opt_last_switch_ts"] = now
    if ok:
        st["known_active"] = target
    jsave(STATE, st)
    _log_switch_event("switch", forced=forced, from_acc=act, to=target, fh=fh, why=why, ok=ok,
                      waited_sec=waited, busy=session_busy())
    if ok:
        # (04.08.26: "постоянно пишет переключился переключился переключился") —
        # уведомление об успешном плановом/оптимизационном переключении убрано, спамило.
        # Переключение по-прежнему происходит молча, известный активный акк обновляется.
        snap_set_active()
    else:
        tg_notify("⚠️ Claude (оптимизация): переключение на %s не удалось: %s" % (target, out))


LIM_WARN, LIM_CLEAR = 90, 80  # как у Codex (cc_codex_bridge): «подходит» с 90%, порог взводится снова ниже 80%


def _lim_at(iso):
    """ISO-время → «21:40» (сегодня) или «06.11 02:00» — как в сообщениях Codex; зона — cfg «tz»."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        tzname = cfg().get("tz")
        if tzname:
            from zoneinfo import ZoneInfo
            dt, now = dt.astimezone(ZoneInfo(tzname)), datetime.now(ZoneInfo(tzname))
        else:
            dt, now = dt.astimezone(), datetime.now().astimezone()
        return dt.strftime("%H:%M") if dt.date() == now.date() else dt.strftime("%d.%m %H:%M")
    except Exception:
        return ""


def claude_limit_alerts(accs, prev, hush=()):
    """Сообщения о лимитах Claude в том же виде, что у Codex: на каждом пороге одно —
    «израсходовано на 90%», «исчерпан» (100%) и «снова доступен». По каждому аккаунту и окну
    (5 ч, неделя); имя аккаунта — только если аккаунтов больше одного. Ошибка чтения или Free —
    состояние аккаунта не меняется. hush — окна ("five_hour"/"seven_day"), про которые уже написано (пауза или «некуда»
    с теми же цифрами): порог «подходит» для них молча запоминается. → (сообщения, новое состояние)."""
    prev = {n: dict(v) for n, v in (prev or {}).items() if n in accs}
    out, multi = [], len(accs) > 1
    for n, row in sorted(accs.items()):
        if row.get("error") or row.get("plan") == "free":
            continue
        mem, who = prev.setdefault(n, {}), (" (%s)" % (row.get("limit_label") or n) if multi else "")
        for key, nm in (("five_hour", "5 ч"), ("seven_day", "неделя")):
            w = row.get(key) or {}
            pct = w.get("pct")
            if pct is None:
                continue
            old = int(mem.get(key, 0))
            lvl = 100 if pct >= 100 else LIM_WARN if pct >= LIM_WARN else 0
            at = _lim_at(w["resets_at"]) if w.get("resets_at") else ""
            tail = f" Сбросится в {at}." if at else ""
            if lvl > old:
                if not (lvl < 100 and key in hush and not n.startswith("remote:")):
                    out.append(f"⚠ Лимит Claude{who} исчерпан: окно {nm}.{tail}" if lvl == 100 else
                               f"⚠ Лимит Claude{who}: окно {nm} израсходовано на {round(pct)}%.{tail}")
                mem[key] = lvl
            elif old == 100 and lvl < 100:
                out.append(f"✅ Лимит Claude{who} снова доступен: окно {nm}, занято {round(pct)}%.")
                mem[key] = lvl
            elif lvl < old and pct < LIM_CLEAR:
                mem[key] = lvl  # спад ниже гистерезиса — порог взведён заново, сообщать не о чем
    return out, prev


def _claude_limit_tick(snap):
    """Сверить лимиты Claude после опроса и написать в Telegram о новом пороге (config «limit_alerts»: false — выкл.)."""
    if cfg().get("limit_alerts") is False:
        return
    accs = dict(snap.get("accounts") or {})
    # Remote accounts must participate even when automatic transfers are off.
    for mid, row in cc_remote.cached().items():
        error = row.get("error") or ("offline" if not row.get("online") else "stale" if time.time() - float(row.get("ts") or 0) >= 600 else "")
        accs["remote:" + mid] = dict(row, error=error, limit_label=(getattr(cc_remote, "members", lambda: {})().get(mid) or {}).get("label") or mid)
    if not accs:
        return
    st = jload(STATE, {})
    first = "limit_alerts" not in st
    hush = set()  # про этот лимит уже написала пауза или «некуда» балансера — второе «⚠ Лимит Claude» было бы тем же самым
    try:
        pc = _pause_mod()
        if pc.notice_fresh("hard"):
            hush.add("five_hour")
        if pc.notice_fresh("week") or pc.notice_fresh("weekrisk"):
            hush.add("seven_day")
    except Exception:
        pass
    msgs, st["limit_alerts"] = claude_limit_alerts(accs, st.get("limit_alerts"), hush)
    jsave(STATE, st)
    if first:
        return  # первый запуск: запоминаем текущие пороги молча — не пишем о том, что было до установки
    for m in msgs:
        tg_notify(m)


def switch_policy_check(snap):
    # оптимизация — отдельный режим, при включении полностью заменяет простой
    # авто-порог (пороговые уходы с забитого аккаунта в неё встроены)
    if cfg().get("optimize"):
        optimize_check(snap)
    else:
        autoswitch_check(snap)
    try:
        _week_cap_warn(snap)
    except Exception as e:
        print(f"week cap warn fail: {e}", flush=True)
    try:
        _claude_limit_tick(snap)
    except Exception as e:
        print(f"limit alerts fail: {e}", flush=True)


def poll_loop():
    while True:
        snap = {}
        try:
            with lock:
                # 429-паузы — по аккаунтам, внутри collect(); здесь опрашиваем всегда
                snap = collect(force=True)
                switch_policy_check(snap)
        except Exception as e:
            print(f"poll fail: {e}", flush=True)
        try:
            _relogin_sweep()  # брошенная попытка входа (ссылку взяли, код не ввели) не висит дольше TTL
        except Exception as e:
            print(f"relogin sweep fail: {e}", flush=True)
        # Просыпаемся не только по poll_sec, но и сразу после ближайшего сброса окна
        # любого аккаунта (+15с запаса): освободившийся аккаунт подхватываем в первую
        # же минуту, а не через несколько тиков и inactive_poll_sec кэша неактивных.
        if cc_poll.enabled(cfg()):
            # просыпаемся к ближайшему сроку опроса любого аккаунта (сброс окна в нём уже учтён)
            wait = cc_poll.sleep_for(jload(POLL_STATE, {}), time.time())
        else:
            wait = cfg().get("poll_sec", 120)
            nr = cc_avail.next_reset_ts((snap or {}).get("accounts") or {})
            if nr is not None:
                wait = min(wait, max(nr - time.time() + 15, 5))
        # раньше срока будит _busy_tick: отложенное плановое переключение дождалось паузы
        _POLL_WAKE.wait(wait)
        _POLL_WAKE.clear()


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
        # [remote] работа передана на Claude PROD: аккаунты DEV забиты, но переключились туда — «некуда» не показываем
        d["remote"] = pause_ctl._remote_active()
        import cc_remote_limits
        rm = jload(os.path.join(BASE, "remote_mode.json"), {})
        rp = cc_remote_limits.public().get(rm.get("member")) or {}
        d["remote_pause"] = rp if d["remote"] and time.time() - float(rp.get("ts") or 0) < 600 else {}
        # Общая сводка включает подключённые аккаунты. Сам локальный гейт,
        # его уровень и время пробуждения остаются без изменений.
        snapshot = jload(SNAPSHOT) or {}
        d["fleet"] = cc_avail.fleet_summary(snapshot.get("accounts") or {}, cc_remote.cached(),
                                             d.get("threshold", 90), d.get("weekly_cap", 99))
        d["claude_limits"] = cc_remote_limits.agent_limits(d, snapshot, cc_remote.cached(), d["remote_pause"])
        # [remote] «некуда» на DEV, но автопередача вот-вот отдаст работу Claude PROD (те же условия, что у хука паузы): баннер говорит «ищу», а не «некуда» (владелец 62577)
        d["handoff"] = ""
        # Claude PROD свободен, а у DEV лимит и работа к нему не уходит: баннер и тексты не говорят «переключаться некуда»
        d["prod_free"] = _prod_hint() if d.get("level") in ("hard", "week") else {}
        if not d["remote"] and d.get("level") in ("hard", "week", "weekrisk"):
            try:
                import cc_remote_auto
                ok, why = cc_remote_auto.handoff_ready()
                if ok:
                    d["handoff"] = why
            except Exception:
                pass  # нет модуля или сбой — баннер как раньше
        d["ok"] = True
        return d
    except Exception as e:
        # pause_ctl.py может отсутствовать (установка до v1.2.0) — баннер просто не покажется
        return {"ok": False, "err": str(e)[:200], "level": "none", "pause": {"active": False}}


def claude_restart_info_local(cl):
    """Claude на этом сервере: запущен ли (screen-сессия), запущен ли ДО установки текущей версии (тогда работает на прежней)."""
    try:
        alive = bool(cc_fleet.claude_alive(globals()))
        pid = _current_screen_pid(cfg().get("screen_session", "claude")) if alive else None
        started = os.stat("/proc/%d" % pid).st_ctime if pid else 0
        stale = bool(alive and started and cl.get("pkg_mtime") and started < float(cl["pkg_mtime"]))
        return {"running": alive, "stale": stale, "busy": False}
    except Exception:
        return None


def claude_restart_info_remote(r):
    """Claude на втором сервере по данным ctl.py cli status (поле restart)."""
    x = r.get("restart") if isinstance(r, dict) else None
    if not isinstance(x, dict):
        return None
    started = float(x.get("started") or 0)
    return {"running": bool(x.get("running")), "stale": bool(x.get("running") and started and r.get("pkg_mtime") and started < float(r["pkg_mtime"])), "busy": False}


def claude_restart_local():
    """Перезапуск Claude на этом сервере: остановить и запустить штатно (start_claude.sh) — НОВАЯ сессия. Не трогаем, если скрипт всё равно не запустит Claude
    (работа на PROD): иначе после остановки он так и остался бы выключенным."""
    wk = globals().get("WORKERS")
    if wk is None:
        return {"ok": False, "error": "not_supported"}
    if not cc_fleet.claude_alive(globals()):
        return {"ok": False, "error": "not_running"}
    import pause_ctl
    if pause_ctl._remote_active():
        return {"ok": False, "error": "other_worker"}
    if wk.side_running():
        return {"ok": False, "error": "side_session"}
    if not wk.stop_claude():
        return {"ok": False, "error": "stop_failed"}
    if not wk.start_claude():
        return {"ok": False, "error": "start_failed"}
    return {"ok": True}


def claude_restart_remote():
    """Перезапуск Claude на втором сервере: ctl.py stop, затем start (новая сессия, Telegram — как было до остановки)."""
    import cc_remote_mode as M
    mid = M._member_id()
    if not mid or not cc_remote.members().get(mid):
        return {"ok": False, "error": "ssh"}
    job = M._job.get("t")
    if job is not None and job.is_alive():   # идёт передача работы между серверами
        return {"ok": False, "error": "busy"}
    st = cc_remote.ctl(mid, "status")
    if st is None:
        return {"ok": False, "error": "ssh"}
    if not st.get("running"):
        return {"ok": False, "error": "not_running"}
    tg = "1" if st.get("tg") else "0"
    cc_remote.ctl(mid, "stop")
    d = cc_remote.ctl(mid, "start", "-", tg, timeout=200)
    return {"ok": True} if d and d.get("ok") else {"ok": False, "error": "start_failed", "message": str((d or {}).get("error") or "")}


def codex_restart_info(cx):
    """Консоль Codex: запущена ли, запущена ли ДО установки текущей версии (тогда она работает на прежней), идёт ли сейчас запрос."""
    try:
        running = bool(cc_codex_console.status().get("running"))
        started = float((cc_codex_console._meta() or {}).get("started") or 0)
        stale = bool(running and started and cx.get("pkg_mtime") and started < float(cx["pkg_mtime"]))
        return {"running": running, "stale": stale, "busy": bool(running and cc_codex_console.busy())}
    except Exception:
        return None


def claude_cli_view(check=False):
    """GET /api/claude-cli: версия Claude Code и Codex и ход обновления на этом сервере и Claude Code на втором (если пара подключена). check — спросить реестр."""
    import claude_cli
    out = {"ok": True, "local": claude_cli.status(check=check), "remote": None, "codex": None}
    if out["local"].get("kind"):
        out["local"]["restart"] = claude_restart_info_local(out["local"])
    cbin = codex_bin()
    if cbin:   # Codex на этом сервере: путь подсказываем модулю (он лежит в папке установки панели или в системном npm)
        claude_cli.BIN_HINT["codex"] = cbin
        cx = claude_cli.status(check=check, tool="codex")
        out["codex"] = cx if cx.get("kind") else None
        if out["codex"]:
            out["codex"]["restart"] = codex_restart_info(out["codex"])
    try:
        import cc_remote_mode
        if cc_remote_mode._member_id():
            r = cc_remote_mode.cli_remote("status", *(["check"] if check else []))
            out["remote"] = r if r is not None else {"ok": False, "error": "ssh"}
            if isinstance(r, dict) and r.get("ok"):
                r["restart"] = claude_restart_info_remote(r)
    except Exception:
        out["remote"] = None
    return out


def claude_cli_action(action, body):
    """POST /api/claude-cli/update|rollback: target «local»/«remote» обязателен (опечатка не должна обновить не то), версия — x.y.z или latest."""
    import claude_cli
    where = body.get("target")
    ver = str(body.get("version") or "latest")
    if action == "update" and ver != "latest" and not claude_cli.VERSION_RE.match(ver):
        return {"ok": False, "error": "bad_target"}
    if action == "restart":   # перезапуск консоли Codex после обновления: разговор продолжается (codex resume), мост Telegram подцепится сам
        if where == "local":
            return claude_restart_local()
        if where == "remote":
            return claude_restart_remote()
        if where != "codex":
            return {"ok": False, "error": "not_supported"}
        if not codex_bin():
            return {"ok": False, "error": "not_installed"}
        if cc_codex_console.busy():   # посреди запроса не перезапускаем
            return {"ok": False, "error": "busy"}
        ok, message = cc_codex_console.stop()
        if not ok:
            return {"ok": False, "error": "stop_failed", "message": message}
        ok, message = cc_codex_console.start()
        return {"ok": True, "message": message} if ok else {"ok": False, "error": "start_failed", "message": message}
    if where == "remote":
        import cc_remote_mode
        r = cc_remote_mode.cli_remote(*(["update", ver] if action == "update" else ["rollback"]))
        return dict(r, ok=bool(r.get("ok"))) if r is not None else {"ok": False, "error": "ssh"}
    if where == "local":
        return claude_cli.start(ver) if action == "update" else claude_cli.rollback()
    if where == "codex":
        cbin = codex_bin()
        if not cbin:
            return {"ok": False, "error": "not_installed"}
        claude_cli.BIN_HINT["codex"] = cbin
        return claude_cli.start(ver, tool="codex") if action == "update" else claude_cli.rollback(tool="codex")
    return {"ok": False, "error": "bad_where"}


def changelog():
    """История изменений для «⚙ Настройки → Обновления»: CHANGELOG.json в каталоге установки
    (приезжает с обновлениями по update_manifest.json). Нет файла или он битый — пустой список."""
    for d in (BASE, os.path.dirname(os.path.abspath(__file__))):
        data = jload(os.path.join(d, "CHANGELOG.json"))
        if isinstance(data, dict) and isinstance(data.get("versions"), list):
            return {"versions": data["versions"]}
    return {"versions": []}


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
        # только настоящий (непустой) токен: X-Auth-User браузер шлёт сам на любой запрос к
        # источнику (Basic Auth, как cookie) — это не защищает ни от подделки локальным
        # процессом (другой пользователь ОС на этом же сервере бьёт прямо в 127.0.0.1:8877,
        # минуя nginx), ни от межсайтовой подделки запроса (CSRF). Токен так не утекает:
        # его знает только сама загруженная страница. Единственное исключение — отдача
        # самой страницы, см. _index_authed().
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        tok = q.get("token", [None])[0] or self.headers.get("X-CC-Token")
        token = cfg().get("hook_token") or ""
        return bool(token) and tok == token

    def _index_authed(self):
        # отдача HTML-страницы: в неё вшивается настоящий hook_token, так что X-Auth-User
        # одного недостаточно (его может подделать любой локальный процесс) — нужен ещё
        # internal_secret, который знают только nginx/супервизор: config.json 0600, его не
        # прочитать непривилегированному локальному пользователю (например codex-песочнице).
        secret = cfg().get("internal_secret") or ""
        return bool(secret) and bool(self.headers.get("X-Auth-User")) and self.headers.get("X-CC-Internal") == secret

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        if u.path == "/api/dialog/answer":
            # без авторизации: доступ даёт одноразовый ключ из кнопки в Telegram
            q = parse_qs(u.query)
            try:
                n = int((q.get("n") or ["0"])[0])
            except ValueError:
                n = 0
            ok, msg = dialog_answer((q.get("k") or [""])[0], n)
            page = ('<!doctype html><meta charset="utf-8"><meta name="viewport" '
                    'content="width=device-width,initial-scale=1"><title>Консоль</title>'
                    '<body style="font:16px system-ui,sans-serif;background:#111;color:#ddd;'
                    'display:flex;align-items:center;justify-content:center;height:90vh;'
                    'text-align:center;padding:16px">' + ("✅ " if ok else "⚠ ") +
                    _html_escape(msg) + '<br><br><span style="color:#888;font-size:14px">'
                    'Можно закрыть страницу</span></body>')
            return self._send(200 if ok else 410, page.encode(), "text/html; charset=utf-8")
        if u.path in ("/", "/index.html"):
            if not self._index_authed():
                return self._send(403, {"error": "forbidden"})
            # токен вшивается в страницу: браузер может не переслать Basic Auth в fetch
            html = PAGE.replace("__TOKEN__", cfg().get("hook_token", "")).replace("__PAGE_VER__", VERSION).replace("__FLEET_TZ__", _page_tz())
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        if u.path == "/api/limits":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            q = parse_qs(u.query)
            with lock:
                snap = collect(force=True, force_account=active_name()) if q.get("refresh") else (jload(SNAPSHOT) or collect())
                renewal = jload(STATE, {}).get("renewal", {})
            for n, row in (snap.get("accounts") or {}).items():
                ts = (renewal.get(n) or {}).get("confirmed_ts")
                if ts and _renewal_applicable(row):
                    row["renewal_next"] = _renewal_next(ts)
            act_n = active_name()
            hold = jload(STATE, {}).get("manual_hold") or {}
            for n, row in (snap.get("accounts") or {}).items():
                le = _login_expires(n, act_n)
                if le:
                    row["login_expires"] = le
                # подпись «выбран вручную» на карточке — пока балансер держит ручной выбор
                if (n == snap.get("active") and not cfg().get("optimize")
                        and cc_avail.manual_pick(hold, n, row)):
                    row["manual_until"] = float(hold.get("until") or 0)
            snap["config"] = {k: cfg().get(k) for k in ("autoswitch", "threshold", "optimize")}
            snap["config"]["weekly_pause"] = bool(cfg().get("weekly_pause"))
            snap["config"]["weekly_cap"] = cfg().get("weekly_cap", 99)
            snap["config"]["codex_hidden"] = list(cfg().get("codex_hidden") or [])  # модели Codex, убранные из быстрого меню
            snap["model"] = model_info()
            snap["remote"] = cc_remote.cached()
            try:
                import cc_remote_mode
                snap["remote_mode"] = cc_remote_mode.public()
            except Exception:
                snap["remote_mode"] = {}  # [remote] аккаунты на чужих серверах: только показ, в автовыборе не участвуют
            return self._send(200, snap)
        if u.path == "/api/pause":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, pause_state())
        if u.path == "/api/claude-cli":  # версия Claude Code и ход обновления (⚙ Настройки Claude)
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, claude_cli_view(bool(parse_qs(u.query).get("check"))))
        if u.path == "/api/update":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, UPDATER.status())
        if u.path == "/api/changelog":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, changelog())
        if u.path == "/api/backup":  # копии профилей аккаунтов: что лежит и что можно вернуть
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, backup_status())
        if u.path == "/api/console":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            q = parse_qs(u.query)
            if (q.get("s") or ["claude"])[0] == "codex":
                # консоль Codex: сессия может быть не запущена — страница покажет кнопку запуска
                if not codex_bin():
                    return self._send(200, {"ok": True, "session": "codex", "available": False, "running": False})
                snap = cc_codex_console.snapshot(want_history=bool(q.get("history")))
                resp = dict(cc_codex_console.status(), ok=True, session="codex", current=None)
                if snap is not None:
                    resp["current"] = snap[0]
                    if snap[1] is not None:
                        resp["history"] = snap[1]
                else:
                    # остановлена: как у Claude — последний экран из лога и время, когда он остановился
                    cur, hist, stopped = cc_codex_console.frozen_snapshot(want_history=bool(q.get("history")))
                    resp.update(current=cur, stopped=stopped)
                    if hist is not None:
                        resp["history"] = hist
                return self._send(200, resp)
            # При остановленной сессии не читать живой лог: показываем сохранённый экран и причину остановки.
            running = _current_screen_pid(cfg().get("screen_session", "claude")) is not None
            if running:
                current_html, history_html = console_snapshot(want_history=bool(q.get("history")))
                resp = {"ok": True, "current": current_html, "running": True}
            else:
                current_html, history_html, stopped = console_frozen_snapshot(want_history=bool(q.get("history")))
                resp = {"ok": True, "current": current_html, "running": False,
                        "idle": console_idle_reason(), "stopped": stopped}
            if history_html is not None:
                resp["history"] = history_html
            return self._send(200, resp)
        if u.path == "/api/models/candidates":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, {"ok": True, "candidates": model_candidates()})
        if u.path == "/api/chatgpt/bridge":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            if not codex_bin():  # install — для кнопки «Подключить Codex» в шапке: что уже стоит и как идёт установка
                return self._send(200, {"ok": True, "available": False,
                                        "install": cc_codex.install_status(parse_qs(u.query).get("lang", ["ru"])[0])})
            return self._send(200, {"ok": True, "available": True, "bridge": cc_codex_bridge.public(),
                                    "emergency": cc_codex_emergency.public()})
        if u.path == "/api/chatgpt/install/prompt":  # текст для кнопки «Скопировать промт»: человек вставит его в консоль Claude сам
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, {"ok": True, "prompt": codex_setup_prompt(parse_qs(u.query).get("lang", ["ru"])[0])})
        if u.path == "/api/chatgpt/install":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, dict(cc_codex.install_status(parse_qs(u.query).get("lang", ["ru"])[0]), ok=True,
                                        available=bool(codex_bin())))
        if u.path == "/api/chatgpt":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            # отдельным запросом от /api/limits: чтение через codex app-server до ~10 с на аккаунт,
            # карточки Claude из-за него ждать не должны
            b = codex_bin()
            if not b:
                return self._send(200, {"ok": True, "available": False, "accounts": []})
            q = parse_qs(u.query)
            return self._send(200, {"ok": True, "available": True,
                                    "accounts": cc_codex.get_accounts(b, force=bool(q.get("refresh")))})
        return self._send(404, {"error": "not found"})

    def _chatgpt_post(self, action, body):
        """POST /api/chatgpt/<login/start|login/status|login/cancel|prefs|delete> — аккаунты ChatGPT (Codex)."""
        lang = body.get("lang")
        # установка Codex из панели: до проверки «Codex есть» — она как раз для случая, когда его ещё нет
        if action == "install/start":
            if codex_bin():
                return self._send(200, {"ok": False, "message": _t(lang, "Codex уже установлен на этом сервере.",
                                                                   "Codex is already installed on this server.")})
            ok, message = cc_codex.install_start(lang=lang)
            return self._send(200, dict(cc_codex.install_status(lang), ok=ok, message=message))
        if action == "install/cancel":
            cc_codex.install_cancel()
            return self._send(200, dict(cc_codex.install_status(lang), ok=True))
        if action == "install/ask-claude":  # «Поручить Claude»: фиксированный промт в консоль, чужой текст маршрут не принимает
            if codex_bin():
                return self._send(200, {"ok": False, "message": _t(lang, "Codex уже установлен на этом сервере.",
                                                                   "Codex is already installed on this server.")})
            ok, seen = send_codex_setup(lang if lang == "en" else "ru")
            return self._send(200, {"ok": ok, "seen": seen, "message": "" if ok else _t(
                lang, "Не удалось вставить промт в консоль Claude (сессия недоступна). Скопируй промт и вставь сам.",
                "Could not paste the prompt into the Claude console (session unavailable). Copy the prompt and paste it yourself.")})
        if action == "wipe":  # «Удалить Codex целиком»: бинарь не нужен — стираем и когда он уже пропал
            ok, message = cc_codex_bridge.wipe_all(codex_bin(), body.get("confirm", ""), lang=lang)
            return self._send(200, {"ok": ok, "message": message})
        b = codex_bin()
        if not b:
            return self._send(400, {"ok": False, "message": _t(lang, "Codex не установлен на этом сервере.",
                                                               "Codex is not installed on this server.")})
        if action == "login/start":
            ok, res = cc_codex.login_start(b, body.get("slot") or None, body.get("label", ""), lang=lang)
            return self._send(200 if ok else 400, dict(res, ok=True) if ok else {"ok": False, "message": res})
        if action == "login/status":
            return self._send(200, dict(cc_codex.login_status(body.get("slot", ""), lang=lang), ok=True))
        if action == "login/cancel":
            cc_codex.login_cancel(body.get("slot", ""))
            return self._send(200, {"ok": True})
        if action == "prefs":
            ok, message = cc_codex.set_prefs(b, body.get("slot", ""), body.get("model", ""), body.get("effort", ""),
                                             body.get("fast"), lang=lang)
            return self._send(200, {"ok": ok, "message": message})
        if action == "renew":
            ok, message = cc_codex.renew(b, body.get("slot", ""), lang=lang)
            if ok:  # сразу сверить карточку: пуш «план снова …» уйдёт без ожидания очередного круга
                threading.Thread(target=cc_codex_bridge.BRIDGE.limits_tick, daemon=True).start()
            return self._send(200, {"ok": ok, "message": message})
        if action == "delete":
            ok, message = cc_codex.delete_account(b, body.get("slot", ""), body.get("confirm", ""), lang=lang,
                                                 before=cc_codex_bridge.prepare_disconnect)
            if ok:  # мост был привязан к этому аккаунту — возвращаем «первый подходящий», иначе он ждал бы стёртый вход
                cc_codex_bridge.drop_slot(body.get("slot", ""))
            return self._send(200, {"ok": ok, "message": message})
        if action == "console/start":
            ok, message = cc_codex_console.start(lang=lang)
            return self._send(200, dict(cc_codex_console.status(), ok=ok, message=message))
        if action == "console/stop":
            ok, message = cc_codex_console.stop(lang=lang)
            return self._send(200, dict(cc_codex_console.status(), ok=ok, message=message))
        if action == "console/cmd":  # кнопки «Сжать контекст» и «Новая сессия» вкладки Codex
            cmd = body.get("cmd")
            if cmd == "compact":
                ok, message = cc_codex_console.compact(lang=lang)
            elif cmd == "new":  # как /new в Telegram: разговор забыт, консоль стартует заново чистой
                cc_codex_bridge.reset_thread()
                ok, message = cc_codex_console.start(lang=lang)
                if ok:
                    message = _t(lang, "Новая сессия Codex: прошлый разговор забыт.", "New Codex session: the previous conversation is forgotten.")
            else:
                return self._send(400, {"ok": False, "message": "unknown command"})
            return self._send(200, dict(cc_codex_console.status(), ok=ok, message=message))
        if action == "bridge/save":
            ok, message = cc_codex_bridge.save(body, lang=lang)
            return self._send(200, {"ok": ok, "message": message})
        if action == "bridge/token":
            ok, message = cc_codex_bridge.set_token(body.get("token", ""), lang=lang)
            return self._send(200, {"ok": ok, "message": message})
        if action == "bridge/token/clear":
            cc_codex_bridge.clear_token()
            return self._send(200, {"ok": True})
        if action == "bridge/reset":
            cc_codex_bridge.reset_thread()
            return self._send(200, {"ok": True})
        if action == "bridge/profile/apply":
            ok, message = cc_codex_bridge.apply_profile(body.get("id", ""), body.get("confirm", ""), lang=lang)
            return self._send(200, {"ok": ok, "message": message})
        if action == "bridge/profile/delete":
            ok, message = cc_codex_bridge.delete_profile(body.get("id", ""), lang=lang)
            return self._send(200, {"ok": ok, "message": message})
        if action == "emergency/on":
            ok, message = cc_codex_emergency.on(body.get("word", ""), lang=lang)
            return self._send(200, {"ok": ok, "message": message})
        if action == "emergency/off":
            ok, message = cc_codex_emergency.off("кнопка в панели", lang=lang)
            return self._send(200, {"ok": ok, "message": message})
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
                    # ручной выбор ЗАБИТОГО аккаунта (сессия ≥порога или неделя на потолке) —
                    # пин до сброса того окна, что держит, или до 100%: авто не перебивает;
                    # выбор свободного — обычный авто-режим
                    act = snap.get("active")
                    st["known_active"] = act  # чтобы poll не принял за внешнее переключение
                    row = (snap.get("accounts") or {}).get(act, {})
                    fh = (row.get("five_hour") or {}).get("pct")
                    sd = (row.get("seven_day") or {}).get("pct")
                    until = _manual_until(row)
                    from datetime import datetime
                    if until:
                        st["manual_hold"] = {"account": act, "until": until}
                        if sd is not None and sd >= cfg().get("weekly_cap", 99):
                            # о потолке недели скажет это сообщение — _week_cap_warn() второго не шлёт
                            st.setdefault("week_warned", {})[act] = _week_key(row.get("seven_day") or {})
                    else:
                        st.pop("manual_hold", None)
                    jsave(STATE, st)
                    email = row.get("email", act)
                    tg_notify("👆 Claude: ручное переключение %s → %s (%s, сессия %s%%, неделя %s%%)."
                              % (prev_act or "?", act, email,
                                 fh if fh is not None else "?", sd if sd is not None else "?")
                              + (" Выбран вручную: балансер не уведёт с него до %s или до 100%%."
                                 % _local_dhm(datetime.fromtimestamp(until).astimezone().isoformat())
                                 if until else ""))
            return self._send(200 if ok else 500, {"ok": ok, "message": out, "snapshot": snap})
        if u.path == "/api/recheck":
            # мгновенная перепроверка плана одного аккаунта в обход 10-минутного
            # _plan_cache — для кнопки "Я продлил": после оплаты Pro на стороне
            # Anthropic план обновляется за секунды, не хочется ждать до 10 мин
            name = body.get("account", "")
            if name not in profile_names():
                return self._send(400, {"ok": False, "message": "неизвестный аккаунт"})
            # аккаунт недавно словил 429 — повторный реальный запрос сейчас же его
            # только продлит; collect() с этого цикла сам отдаст кэш (force_account
            # больше не обходит backoff_until), здесь просто говорим пользователю,
            # почему свежих данных не будет (раньше recheck пробивал паузу
            # насквозь при каждом клике)
            wait_left = backoff_until.get(name, 0) - time.time()
            if wait_left > 0:
                return self._send(200, {"ok": False, "message":
                    f"⏳ Anthropic недавно ограничил частоту запросов для этого аккаунта — подожди ~{int(wait_left)} сек и попробуй снова."})
            _plan_cache.pop(name, None)
            with lock:
                st = jload(STATE, {})
                st.setdefault("renew_click", {})[name] = time.time()
                jsave(STATE, st)
                snap = collect(force=True, force_account=name, renew_account=name)
            row = (snap.get("accounts") or {}).get(name, {})
            plan = row.get("plan")
            email = row.get("email", name)
            err = row.get("error")
            # plan и usage у Anthropic — независимые эндпоинты: план может уже
            # вернуться на Pro, пока usage-эндпоинт всё ещё 429-ит. Раньше отсюда
            # шло "вернул в ротацию" по одному только plan, хотя autoswitch_check/
            # optimize_check хард-скипают любой аккаунт с error — реально в
            # ротацию он не попадал, сообщение вводило в заблуждение.
            if plan and plan != "free":
                # якорь для таймера обратного отсчёта до следующего ожидаемого
                # обвала Pro→Free — момент, когда пользователь подтвердил
                # продление; см. _renewal_next(). Пишется и при err: план уже
                # Pro, недоступен только usage-эндпоинт
                with lock:
                    st = jload(STATE, {})
                    st.setdefault("renewal", {})[name] = {"confirmed_ts": time.time()}
                    (st.get("renew_click") or {}).pop(name, None)
                    jsave(STATE, st)
            if plan and plan != "free" and not err:
                return self._send(200, {"ok": True, "plan": plan,
                    "message": f"✅ снова {plan.upper()} — вернул в ротацию."})
            if plan and plan != "free" and err:
                return self._send(200, {"ok": False, "plan": plan,
                    "message": f"План снова {plan.upper()}, но данные по использованию ещё недоступны ({err}) — в ротацию пока не включён."})
            if plan == "free":
                return self._send(200, {"ok": False, "plan": plan,
                    "message": "⏳ Anthropic ещё не обновил план (всё ещё Free) — аккаунт остаётся неактивным, опрос стоит. Нажми «Я продлил» снова, когда оплата пройдёт."})
            return self._send(200, {"ok": False, "plan": plan,
                "message": "Не удалось проверить план: " + (row.get("error") or "?")})
        if u.path == "/api/model":
            before = _model_notice_state()
            ok, msg = set_default_model(body.get("model", ""))
            if ok:
                cc_model_notice.changed("Claude DEV", "claude", before, _model_notice_state())
            return self._send(200 if ok else 400, {"ok": ok, "message": msg, "model": model_info()})
        if u.path == "/api/effort":
            smid = session_model()
            top = not (smid and smid.startswith("claude-"))   # так set_effort выбирает, куда писать
            before = _model_notice_state(smid, top)
            ok, msg = set_effort(body.get("effort", ""))
            if ok:
                cc_model_notice.changed("Claude DEV", "claude", before, _model_notice_state(smid, top))
            return self._send(200 if ok else 400, {"ok": ok, "message": msg, "model": model_info()})
        if u.path == "/api/session":
            if body.get("cmd") == "redraw":   # не slash-команда: ресайз pty окна, в сессию ничего не вводится
                ok, msg = redraw_console(body.get("lang"))
                return self._send(200 if ok else 400, {"ok": ok, "message": msg})
            ok, msg = send_session_command(body.get("cmd", ""))
            return self._send(200 if ok else 400, {"ok": ok, "message": msg})
        if u.path == "/api/pause":
            # кнопки «Отключить / Включить паузу» в баннере: pause_ctl off|on — тот же модуль,
            # что у будильника и хуков; лог — рядом с логом будильника
            action = body.get("action")
            if action not in ("off", "on"):
                return self._send(400, {"ok": False, "error": "action: off|on"})
            # у Claude DEV и Claude PROD «отключена вручную» — отдельные флаги: кнопка трогает только свой
            engine = body.get("engine") or "claude"
            if engine not in ("claude", "prod"):
                return self._send(400, {"ok": False, "error": "engine: claude|prod"})
            try:
                r = subprocess.run(["/usr/bin/python3", os.path.join(BASE, "pause_ctl.py"), action,
                                    "--by", "web panel", "--engine", engine], capture_output=True, text=True, timeout=30,
                                   env=dict(os.environ, CC_LIMITS_BASE=BASE))
                with open(os.path.join(BASE, "pause_wake.log"), "a", encoding="utf-8") as f:
                    f.write(r.stdout + r.stderr)
                ok, out = r.returncode == 0, (r.stdout + r.stderr).strip()[-300:]
            except Exception as e:
                ok, out = False, str(e)[:200]
            d = pause_state()
            if ok:
                import cc_remote_limits
                threading.Thread(target=cc_remote_limits.sync_policy,args=(globals(),),daemon=True,name='remote-pause-toggle').start()
            d.update(ok=ok, out=out)
            return self._send(200 if ok else 500, d)
        if u.path == "/api/update/check":
            return self._send(200, UPDATER.check(force=True))
        if u.path == "/api/update/apply":
            ok, msg = UPDATER.apply(body.get("version"))
            d = UPDATER.status()
            d.update(ok=ok, message=msg)
            return self._send(200, d)
        if u.path == "/api/update/skip":
            return self._send(200, UPDATER.skip(str(body.get("version") or "")))
        if u.path == "/api/update/ack":
            return self._send(200, UPDATER.ack())
        if u.path == "/api/backup/now":  # «Копия сейчас»
            res = cc_backup.make(PROFILES, BACKUP_DIR)
            return self._send(200, dict(backup_status(), ok=res.get("ok", False), why=res.get("why", ""), name=res.get("name", "")))
        if u.path == "/api/backup/restore":  # «Восстановить недостающие»: живые профили не трогаются
            res = cc_backup.restore_missing(PROFILES, BACKUP_DIR)
            return self._send(200, dict(backup_status(), ok=True, restored=res["restored"]))
        if u.path in ("/api/claude-cli/update", "/api/claude-cli/rollback", "/api/claude-cli/restart"):  # «Обновить» / «Вернуть» Claude Code (⚙ Настройки Claude)
            return self._send(200, claude_cli_action(u.path.rsplit("/", 1)[1], body))
        if u.path == "/api/config":
            c = cfg()
            for k in ("autoswitch", "threshold", "optimize"):
                if k in body:
                    c[k] = body[k]
            if body.get("update_mode") in ("manual", "auto"):
                c["update_mode"] = body["update_mode"]
            if isinstance(body.get("update_check"), bool):
                c["update_check"] = body["update_check"]
            if isinstance(body.get("weekly_pause"), bool):
                c["weekly_pause"] = body["weekly_pause"]
            if isinstance(body.get("profile_backup"), bool):
                c["profile_backup"] = body["profile_backup"]
            if "weekly_cap" in body:  # «Неделя, %» в «⚙ Настройки Claude» → «Переключение и лимиты»
                try:
                    cap = int(body["weekly_cap"])
                except (TypeError, ValueError):
                    cap = 0
                if not 50 <= cap <= 100:
                    return self._send(200, {"ok": False, "message": "Неделя: число от 50 до 100 %"})
                c["weekly_cap"] = cap
            if isinstance(body.get("codex_hidden"), list):  # галочки «в быстром меню» в «⚙ Настройки Codex»
                c["codex_hidden"] = sorted({m.strip()[:80] for m in body["codex_hidden"] if isinstance(m, str) and m.strip()})[:200]
            if "enabled_models" in body:
                # неизвестные id молча отбрасываем; пустой список игнорируем целиком —
                # хотя бы одна модель должна остаться доступной для переключения
                ids = [m for m in body["enabled_models"] if m in all_models()]
                if ids:
                    c["enabled_models"] = ids
                    c["model_hidden"] = [m for m in (c.get("model_hidden") or []) if m not in ids]
            if isinstance(body.get("hide"), dict):
                # скрытая модель выключена и не в чипах; снять скрытие = вернуть в строй. Пустой набор не сохраняем
                hidden = set(c.get("model_hidden") or [])
                enabled = list(c.get("enabled_models") or all_models().keys())
                for mid, flag in body["hide"].items():
                    if mid not in all_models() or not isinstance(flag, bool):
                        continue
                    if flag:
                        hidden.add(mid)
                        enabled = [m for m in enabled if m != mid]
                    elif mid in hidden:
                        hidden.discard(mid)
                        if mid not in enabled:
                            enabled.append(mid)
                if enabled:
                    c["enabled_models"] = enabled
                    c["model_hidden"] = sorted(hidden)
            jsave(CONFIG, c)
            UPDATER.kick()  # сменили режим обновлений — пусть петля пересмотрит сразу
            return self._send(200, {"ok": True, "autoswitch": c.get("autoswitch"),
                                    "threshold": c.get("threshold"), "optimize": c.get("optimize"),
                                    "weekly_cap": c.get("weekly_cap", 99), "codex_hidden": list(c.get("codex_hidden") or []),
                                    "model": model_info()})
        if u.path == "/api/models/candidates":
            # add: {id: показываемое_имя} — принять кандидата в оборот;
            # ignore: [id, ...] — убрать из будущих подсказок (не мусорить исторический "-fast"/"-v1" повторно)
            c = cfg()
            extra = c.get("extra_models") or {}
            added_ts = c.get("model_added_ts") or {}
            enabled = c.get("enabled_models")
            if enabled is None:
                enabled = list(all_models().keys())
            now = time.time()
            for mid, name in (body.get("add") or {}).items():
                if not isinstance(mid, str) or not isinstance(name, str) or not name.strip():
                    continue
                if mid in all_models():
                    continue  # уже есть — не перетираем существующее отображаемое имя
                extra[mid] = name.strip()
                added_ts[mid] = now
                if mid not in enabled:
                    enabled.append(mid)
            ignored = set(c.get("model_ignored_ids") or [])
            ignored.update(i for i in (body.get("ignore") or []) if isinstance(i, str))
            c["extra_models"] = extra
            c["model_added_ts"] = added_ts
            c["enabled_models"] = enabled
            c["model_ignored_ids"] = sorted(ignored)
            jsave(CONFIG, c)
            return self._send(200, {"ok": True, "model": model_info()})
        if u.path == "/api/relogin/start":
            # без lock: только спавнит изолированный процесс в своём temp HOME,
            # общие файлы (снапшот/профили) не трогает — блокировать остальных на 15с смысла нет
            name = body.get("account", "")
            ok, url_or_msg, email = relogin_start(name)
            if not ok:
                return self._send(400, {"ok": False, "message": url_or_msg})
            return self._send(200, {"ok": True, "url": url_or_msg, "email": email})
        if u.path == "/api/account/delete":
            ok, message, snap = delete_account(body.get("account", ""), body.get("confirm", ""), lang=body.get("lang"))
            return self._send(200, {"ok": ok, "message": message})
        if u.path == "/api/account/add/start":
            ok, url_or_msg, slot, email = addacct_start(body.get("email", ""), lang=body.get("lang"))
            if not ok:
                return self._send(400, {"ok": False, "message": url_or_msg})
            return self._send(200, {"ok": True, "url": url_or_msg, "slot": slot, "email": email})
        if u.path == "/api/account/add/submit":
            # lock берёт сама relogin_submit — снаружи не оборачивать
            ok, message, snap = relogin_submit(body.get("slot", ""), body.get("code", ""), new=True, lang=body.get("lang"))
            return self._send(200, {"ok": ok, "message": message})
        if u.path.startswith("/api/chatgpt/"):
            return self._chatgpt_post(u.path[len("/api/chatgpt/"):], body)
        if u.path == "/api/relogin/submit":
            # lock берёт сама relogin_submit (вокруг записи в профиль + collect) —
            # тут НЕ оборачивать: lock не реентерабельный, второй with lock = дедлок
            name = body.get("account", "")
            ok, message, snap = relogin_submit(name, body.get("code", ""), lang=body.get("lang"))
            return self._send(200, {"ok": ok, "message": message})
        return self._send(404, {"error": "not found"})


PAGE = r"""<!doctype html>
<html lang="ru"><head><script>try{if(localStorage.getItem('cc_has_prod')!=='1')document.documentElement.classList.add('no-prod')}catch(e){document.documentElement.classList.add('no-prod')}</script>
<script>try{var _u=(localStorage.getItem('cc_unl')||'').split(',');for(var _i=0;_i<_u.length;_i++)if(/^[a-z]+$/.test(_u[_i]))document.documentElement.classList.add('ag-unlinked-'+_u[_i])}catch(e){}</script>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude — лимиты аккаунтов</title>
<link rel="icon" href="data:,">
<script>window.FLEET_TZ='__FLEET_TZ__'||undefined;</script>
<script>try{localStorage.removeItem('cc_skin')}catch(e){}try{if(localStorage.getItem('cc_conly')==='1')document.documentElement.classList.add('conly')}catch(e){}</script>
<style>
:root{--bg:#0f1115;--card:#181c24;--txt:#e8eaf0;--mut:#8b93a7;--ok:#34c07c;--warn:#e8b93e;--bad:#e05b5b;--acc:#7c9aff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:16px}
.hdr{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:4px 0 14px}
h1{font-size:19px;margin:0}
.hdrgear{background:transparent;border:1px solid #2a3140;color:var(--mut);width:28px;height:28px;padding:0;margin:0;border-radius:8px;display:flex;align-items:center;justify-content:center;flex:none}
.mchip{margin:0;background:transparent;border:1px solid #2a3140;color:var(--txt);font-weight:600;padding:5px 12px;border-radius:99px;font-size:13px;cursor:pointer}
.mchip.active{background:var(--acc);color:#0f1115;border-color:var(--acc)}
.mrowslim{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.scrim{position:fixed;inset:0;background:rgba(6,8,12,.72);display:flex;align-items:center;justify-content:center;padding:20px;z-index:10}
.scrim[hidden]{display:none}
.modal{background:var(--card);border:1px solid #2a3140;border-radius:16px;padding:18px 18px 14px;max-width:360px;width:100%}
.modal h3{font-size:15px;margin-bottom:4px}
.modalsub{font-size:12px;color:var(--mut);margin-bottom:12px}
.poolrow{display:flex;align-items:center;gap:9px;font-size:14px;padding:7px 2px;border-bottom:1px solid #1e232c;cursor:pointer}
.poolrow:last-of-type{border-bottom:none}
.poolrow input[type=checkbox]{transform:scale(1.2)}
.newbadge{font-size:10px;padding:1px 7px;border-radius:99px;background:rgba(124,154,255,.18);color:var(--acc);font-weight:700;margin-left:auto}
.modalfoot{display:flex;justify-content:flex-end;margin-top:8px;gap:8px}
.ghostbtn{margin:0;background:transparent;border:1px solid #2a3140;color:var(--txt);font-weight:600;padding:8px 14px;border-radius:10px;font-size:13px;cursor:pointer}
.card{position:relative;background:var(--card);border-radius:14px;padding:14px 16px;margin-bottom:12px;border:1px solid #232a36}
.card.active{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)}
#cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(340px,100%),1fr));gap:14px;align-items:start;margin-bottom:12px}
#cards .card{margin-bottom:0}
.top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.email{font-weight:600;font-size:15px;word-break:break-all}
.tag{font-size:11px;padding:2px 8px;border-radius:99px;background:var(--acc);color:#0f1115;font-weight:700;white-space:nowrap}
.tag.pin{position:absolute;top:0;right:14px;transform:translateY(-55%);background:#7c5cff;color:#fff;box-shadow:0 2px 6px rgba(0,0,0,.4);z-index:3}
.hdrright{display:flex;align-items:center;gap:8px;flex:none}
.chip{font-size:10.5px;padding:2px 8px;border-radius:99px;background:#1b2029;border:1px solid #2a3140;color:var(--mut);white-space:nowrap;vertical-align:2px;display:inline-flex;align-items:center;gap:3px}
.chip b{color:var(--txt);font-weight:700}
.chip.urgent{border-color:rgba(224,91,91,.4)}
.chip.urgent b{color:var(--bad)}
.chip.warn{border-color:rgba(232,170,60,.45)}
.chip.warn b{color:var(--warn)}
.chip.login{cursor:help;vertical-align:baseline}
.chip.login svg{width:13px;height:13px;flex:none;color:var(--ok)}
.chip.login.warn svg{color:var(--warn)}
.chip.login.urgent svg{color:var(--bad)}
.acts .chip.login{height:26px;box-sizing:border-box;padding:0 10px;gap:5px;font-size:12px}
.ring{position:relative;flex:none}
.ring svg{display:block}
.ringtxt{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--txt);font-weight:700}
.iconrow{display:flex;gap:6px;flex:none}
.iconbtn{width:26px;height:26px;display:inline-flex;align-items:center;justify-content:center;background:var(--card);border:1px solid #2a3140;border-radius:7px;color:var(--mut);cursor:pointer;padding:0;margin:0;flex:none}
.iconbtn:hover{border-color:var(--acc);color:var(--txt)}
.iconbtn svg{width:14px;height:14px;display:block}
.row{margin-top:10px}
.lbl{display:flex;justify-content:space-between;font-size:12.5px;color:var(--mut);margin-bottom:4px}
.bar{height:10px;border-radius:99px;background:#242b38;overflow:hidden}
.fill{height:100%;border-radius:99px;transition:width .5s}
button{background:var(--acc);border:0;color:#0f1115;font-weight:700;padding:8px 14px;border-radius:10px;font-size:13.5px;cursor:pointer;margin-top:12px}
button:disabled{opacity:.35;cursor:default}
.thrbtn{background:var(--card);border:1px solid #2a3140;color:var(--txt);width:30px;height:26px;padding:0;border-radius:6px;margin:0;display:inline-flex;align-items:center;justify-content:center}
.thrbtn svg{width:14px;height:14px;display:block}
.thrbtn:hover{border-color:var(--acc)}
.err{color:var(--bad);font-size:13px;margin-top:8px}
.switchrow{display:flex;align-items:center;gap:8px;font-size:13.5px;color:var(--mut);margin-bottom:14px}
.switchrow input{transform:scale(1.25)}
#msg{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:#232a36;padding:10px 18px;border-radius:12px;font-size:14px;display:none;max-width:92vw;z-index:20}
.termwrap{position:relative;display:flex;flex-direction:column;min-height:130px;margin-bottom:18px}
.termdot{width:8px;height:8px;border-radius:50%;background:var(--ok);flex:none}
.tzoom{position:absolute;top:7px;right:8px;z-index:2;display:flex;align-items:center;gap:4px;padding:2px;border-radius:9px;background:rgba(0,0,0,.6)}
/* вкладки консолей Claude | Codex: слева над консолью, без своей плашки; показываются, только если Codex установлен */
.ctabs{position:absolute;top:7px;left:8px;z-index:2;display:flex;align-items:center;gap:4px;padding:2px;border-radius:9px;background:transparent}
.ctabs[hidden],.ctstop[hidden],.ctab[hidden]{display:none}
html.no-prod #ctProd,html.no-prod .wk-seg[data-ag="prod"],html.no-prod .fleet-live-account.prod,html.no-prod .fleet-compact-account.prod,html.no-prod .fleet-acc[data-engine="prod"],html.no-prod .wk-h3.t-prod,html.no-prod .rm-hand[data-target="prod"],html.no-prod .tpmi[data-k="prod"]{display:none!important}
@media(max-width:520px){.ctab .ctlong{display:none}}
.ctacts{display:contents}  /* кнопки действий Codex: на телефоне уходят второй строкой */
.iconbtn.ctab{width:auto;padding:0 11px;font:600 12px/1 system-ui,sans-serif;letter-spacing:.01em}
.iconbtn.ctab.on{border-color:var(--acc);color:var(--txt);background:rgba(255,255,255,.08)}
/* цвет вкладки: обе всегда цветные (Claude — оранжевый, Codex — синий), перекрывает окраску тем.
   Неактивная — только окантовка (фона нет совсем, плашки под кнопками тоже; чтобы подпись читалась поверх текста консоли — тёмный ореол у букв);
   активная — залита цветом целиком */
html:root:root .iconbtn.ctab[data-s]{--tc:224,144,90;--tt:#efbf9c;--ton:#1d1206;color:var(--tt);background:transparent;border:1px solid rgba(var(--tc),.7);box-shadow:none;text-shadow:0 0 2px #000,0 0 2px #000}
html:root:root .iconbtn.ctab[data-s="codex"]{--tc:104,154,236;--tt:#aac6f6;--ton:#061429}
html:root:root .iconbtn.ctab[data-s]:hover{background:transparent;border-color:rgb(var(--tc));color:var(--tt)}
html:root:root .iconbtn.ctab[data-s].on{background:rgb(var(--tc));border-color:rgb(var(--tc));color:var(--ton);box-shadow:none;text-shadow:none}
.termwrap.hastabs .termbox{padding-top:42px}
.hdrl{display:flex;align-items:center;gap:10px;min-width:0}
.hdrgear:disabled svg{animation:ccspin .8s linear infinite}
.tzval{margin:0;padding:0 4px;min-width:48px;background:transparent;border:0;color:var(--mut);font-family:inherit;font-size:12.5px;font-weight:600;text-align:center;cursor:pointer}
.tzval:hover{color:var(--txt)}
.termdot.err{background:var(--bad);margin:0}
.termdot.idle{background:#6b7280;margin:0}
.termidle{position:sticky;bottom:0;white-space:normal;font:13px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:#d6dbe4;background:rgba(23,27,35,.96);border:1px solid #3a4250;border-radius:8px;padding:9px 12px;margin-top:10px}
.termidle{display:flex;align-items:center;flex-wrap:wrap;gap:8px 14px}
.termidle span{flex:1 1 240px;min-width:0}
.termidle button{flex:none;padding:6px 16px;margin:0}
.termidle[hidden],.termidle button[hidden]{display:none}
/* экрана нет (PROD ещё не запускали, у Codex нет лога): sticky не к чему прижимать — плашку опускаем вниз колонкой */
.termbox.termempty{display:flex;flex-direction:column}
.termbox.termempty .termidle{margin-top:auto}
.termbox{background:#0b0d10;border:1px solid #232a36;border-radius:8px;padding:10px 12px;overflow-x:hidden;overflow-y:auto;margin:0;font:11px/1.3 ui-monospace,Consolas,monospace;font-size:calc(11px*var(--tz,1));color:#c8d0dc;white-space:pre-wrap;word-break:break-word;scrollbar-width:thin;scrollbar-color:#3a3f4b #14171c}
.termbox::-webkit-scrollbar{width:9px}
.termbox::-webkit-scrollbar-track{background:#14171c}
.termbox::-webkit-scrollbar-thumb{background:#3a3f4b;border-radius:99px;border:2px solid #14171c;background-clip:padding-box}

/* --- разделение консоли (ПК, ≥1100px): 2–3 панели рядом --- */
.tpheads,.tpadd{display:none}
html:root:root #splitBtn[hidden]{display:none!important}  /* у кнопок блока масштаба display задаётся классом и перебивает hidden */
.termwrap.tsplit .fleet-console-viewport{position:relative;display:flex!important;flex-direction:row;min-width:0;background:var(--fleet-terminal,#0b0d10)}
/* общее окно ввода со строкой статуса выше окон частей на 39px: добавляем их к экрану, чтобы консоль и активные аккаунты занимали столько же места, как при одной консоли */
html:not(.conly) .termwrap.tsplit .fleet-console-viewport{height:calc(clamp(408px,calc(41dvh + 48px),558px) + 39px)}
@media(min-width:1100px) and (min-height:700px){html:not(.conly) .termwrap.tsplit .fleet-console-viewport{height:calc(clamp(388px,calc(100dvh - 382px),688px) + 39px)}html:not(.conly) body.fleet-mirror .termwrap.tsplit .fleet-console-viewport{height:calc(clamp(368px,calc(100dvh - 422px),658px) + 39px)}}
html.conly .termwrap.tsplit .fleet-console-viewport{flex:1 1 0;min-height:0}
html:root:root .termwrap.tsplit .fleet-console-viewport>.tpextra{border-left:1px solid #263140}
html:root:root .termwrap.tsplit .fleet-console-viewport>#termBox,html:root:root .termwrap.tsplit .fleet-console-viewport>.tpextra{flex:1 1 0!important;min-width:0!important;width:auto!important;height:100%!important;min-height:0!important;max-height:none!important;margin:0!important;border:0;border-radius:0;padding:36px 12px 14px!important;overflow:auto;box-sizing:border-box;font-size:calc(12px*var(--tz,1)*var(--pz,1))!important}
.tpextra{background:var(--fleet-terminal,#0b0d10);color:#d2dce9;white-space:pre;font:calc(12px*var(--tz,1)*var(--pz,1))/1.65 ui-monospace,"SFMono-Regular",Consolas,monospace}
html:root:root .termwrap.tsplit .tcwrap{white-space:pre-wrap!important;overflow-wrap:anywhere;overflow-x:hidden}
.termwrap.tsplit .termbox.tpdrop{box-shadow:inset 0 0 0 2px var(--fleet-accent,#73dbb7);background-image:linear-gradient(rgba(115,219,183,.08),rgba(115,219,183,.08))}
.termwrap.tsplit .tpheads{display:flex;position:absolute;left:0;right:0;top:0;height:30px;z-index:5;pointer-events:none}
.tphd{flex:1 1 0;min-width:0;display:flex;align-items:center;gap:7px;padding:0 10px;margin:0;font:600 12px system-ui,-apple-system,Segoe UI,sans-serif;color:#9fb0c3;cursor:grab;pointer-events:auto;background:#0e1219;border-bottom:1px solid #263140;user-select:none}
.tphd.on{color:#eaf2fb}
.tphd+.tphd{border-left:1px solid #263140}
.tphd.tpdrop{background:#173a33}
.tphd b{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tphd .tpdot{flex:none}
.tphd{cursor:pointer}
.tphd .tpcaret{flex:none;color:#7d8ea3;font-size:10px;margin-left:-2px}
.tphd:hover .tpcaret{color:#cfe9e0}
.tpmenu{position:fixed;z-index:70;min-width:224px;max-width:min(320px,calc(100vw - 16px));padding:6px;background:#141a23;border:1px solid #2a3644;border-radius:10px;box-shadow:0 14px 34px rgba(0,0,0,.5);font:500 13px system-ui,-apple-system,Segoe UI,sans-serif;color:#c9d4e0}
.tpmt{padding:5px 10px 6px;font-size:10.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:#6d7f94}
.tpmi{display:flex;align-items:center;gap:9px;width:100%;margin:0;padding:8px 10px;border:0;border-radius:7px;background:none;color:inherit;font:inherit;text-align:left;cursor:pointer}
.tpmi:hover,.tpmi:focus-visible{background:rgba(255,255,255,.07);outline:0}
.tpmi.cur{color:#e7f3ee}
.tpmd{width:7px;height:7px;border-radius:50%;flex:none;background:#e0905a}
.tpmd[data-m=codex]{background:#4cdbb0}
.tpmn{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tpmw{flex:none;font-size:11px;color:#6d7f94}
.tpmc{flex:none;color:#68ac92}
.tphd .tpx{margin:0 0 0 auto;padding:0 4px;min-height:0;width:auto;background:none;border:0;color:#7d8ea3;font:16px/1 system-ui,sans-serif;cursor:pointer}
.tphd .tpx:hover{color:#eaf2fb}
.tphd .tpacts{flex:none;display:flex;align-items:center;gap:2px;margin-left:4px}
.tphd .tpab{flex:none;display:grid;place-items:center;width:22px;height:22px;margin:0;padding:0;min-height:0;background:none;border:0;border-radius:5px;color:#7d8ea3;cursor:pointer}
.tphd .tpab:hover{color:#eaf2fb;background:rgba(255,255,255,.07)}
.tphd .tpab svg{display:block;width:14px;height:14px;pointer-events:none}
html:root:root .termwrap.tsplit .fleet-console-toolbar .ctacts{display:none!important}
.tphd .tpfs{flex:none;display:grid;place-items:center;width:22px;height:22px;margin:0 0 0 auto;padding:0;min-height:0;background:none;border:0;border-radius:5px;color:#7d8ea3;cursor:pointer}
.tphd .tpfs:hover{color:#eaf2fb;background:rgba(255,255,255,.07)}
.tphd .tpfs svg{display:block;width:14px;height:14px;pointer-events:none}
.tphd .tpfs .tpfsx,.tphd .tpfs.on .tpfsi{display:none}
.tphd .tpfs.on .tpfsx{display:block}
.tphd .tpfs+.tpx{margin-left:2px}
/* часть развёрнута на всю консоль: остальные части (экран, шапка, окно ввода) спрятаны, но не закрыты */
.termwrap.tpmax .fleet-console-viewport>.tphide,.termwrap.tpmax .tpheads .tphide,.termwrap.tpmax .tpcomps .tphide{display:none!important}
body.tpdraging .tpadd{display:flex;position:fixed;z-index:60;align-items:center;justify-content:center;text-align:center;padding:14px;font:600 13px system-ui,sans-serif;color:#cfe9e0;background:rgba(25,60,52,.78);border:2px dashed var(--fleet-accent,#73dbb7);box-sizing:border-box}
body.tpdraging .tpadd.tpdrop{background:rgba(25,80,66,.9)}
/* --- у каждой части разделённой консоли своё окно ввода (форма — как общее окно, отправка — его же код) --- */
.tpcomps{display:none}
.termwrap.tsplit.tpcomps-on>.tpcomps{display:flex;flex:none;min-width:0}
.termwrap.tsplit.tpcomps-on>#fleetConsoleForm,.termwrap.tsplit.tpcomps-on>.fleet-input-status{display:none!important}
.tpcw{flex:1 1 0;min-width:0;display:flex;flex-direction:column}
.tpcw+.tpcw{border-left:1px solid #263140}
.tpcomp{display:flex;align-items:center;gap:8px;margin:0;padding:8px 10px;border-top:1px solid #263140;background:#101620;color:#dbe3ed}
.tpcomp::before{content:"›";color:#73dbb7;font:20px ui-monospace,monospace}
.tpcomp textarea{flex:1;min-width:0;resize:vertical;min-height:26px;max-height:140px;margin:0;padding:4px 0;background:none;color:#dbe3ed;border:0;outline:0;border-radius:0;font:12px/1.5 ui-monospace,Consolas,monospace}
.tpcomp textarea::placeholder{color:#65768c}
.tpcomp textarea:focus-visible{box-shadow:0 1px #45d6ab}
.tpcomp button{margin:0;min-height:0;padding:0;flex:none}
.tpcomp .tpsend{display:grid;place-items:center;width:28px;height:28px;background:#1a342d;color:#a5c6bb;border:0;border-radius:6px;box-shadow:none}
.tpcomp .tpsend svg{display:block;width:16px;height:16px;pointer-events:none}
.tpcomp .tpkey{background:transparent;color:#73869d;border:1px solid #2a3644;padding:2px 5px;border-radius:4px;font:10px ui-monospace,monospace;min-width:20px;text-align:center}
.tpfr{display:none;position:absolute;z-index:6;pointer-events:none;box-sizing:border-box;border:1px solid transparent}
.tpfr.on{z-index:7;border-color:rgba(104,172,146,.62)}
.termwrap.tsplit .tpfr{display:block}
/* верхнее меню (ПК): открытая консоль — аккуратная прозрачная серая рамка вокруг вкладки, активная — такая же мягкого приглушённого зелёного */
@media(min-width:1100px) and (pointer:fine){
 html:root:root .fleet-console-toolbar .iconbtn.ctab[data-s]{align-self:center;height:30px!important;padding:0 12px!important;border-radius:8px}
 html:root:root .fleet-console-toolbar .iconbtn.ctab[data-s].tshown:not(.on){box-shadow:inset 0 0 0 1px rgba(170,182,200,.28)!important}
 html:root:root .fleet-console-toolbar .iconbtn.ctab[data-s].on{box-shadow:inset 0 0 0 1px rgba(104,172,146,.62)!important}
 html:root:root .fleet-console-toolbar .iconbtn.ctab[data-s].on::after{display:none}
}
/* баннер лимитов/паузы — в норме скрыт целиком и места не занимает */
.ccpause{display:flex;gap:12px;align-items:flex-start;margin:0 0 14px;padding:12px 14px;border-radius:14px;background:var(--card);border:1px solid #232a36;border-left:4px solid var(--ccp-accent,var(--mut))}
.ccpause[hidden]{display:none}
.ccpause.lvl-hard{--ccp-accent:#e86b6b;background:linear-gradient(90deg,rgba(224,91,91,.10),rgba(224,91,91,0) 55%),var(--card)}
.ccpause.lvl-gate{--ccp-accent:#e8b93e;background:linear-gradient(90deg,rgba(232,185,62,.10),rgba(232,185,62,0) 55%),var(--card)}
.ccpause.lvl-pause{--ccp-accent:#a78bfa;background:linear-gradient(90deg,rgba(167,139,250,.12),rgba(167,139,250,0) 55%),var(--card)}
.ccpause.lvl-off{--ccp-accent:#5fd08a;background:linear-gradient(90deg,rgba(95,208,138,.10),rgba(95,208,138,0) 55%),var(--card)}
.ccpause.lvl-upd{--ccp-accent:#4f9dff;background:linear-gradient(90deg,rgba(79,157,255,.12),rgba(79,157,255,0) 55%),var(--card)}
.ccpause.lvl-updok{--ccp-accent:#5fd08a;background:linear-gradient(90deg,rgba(95,208,138,.10),rgba(95,208,138,0) 55%),var(--card)}
.ccpause.lvl-upderr{--ccp-accent:#e05b5b;background:linear-gradient(90deg,rgba(224,91,91,.10),rgba(224,91,91,0) 55%),var(--card)}
.ccp-actions{margin-top:10px;display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.ccp-btn{font:inherit;font-size:12.5px;font-weight:600;padding:6px 14px;border-radius:8px;cursor:pointer;color:var(--txt);background:#1b2029;border:1px solid var(--ccp-accent)}
.ccp-btn:hover{background:#232a36}
.ccp-btn:disabled{opacity:.55;cursor:wait}
.ccp-hint{font-size:11.5px;color:var(--mut)}
/* баннер обновления и блок «Обновления» в настройках */
.ccp-link{font-size:12px;color:var(--mut);text-decoration:underline}
.ccp-link:hover{color:var(--txt)}
.upd-notes{margin-top:8px;font-size:12px;color:var(--mut)}
.upd-notes summary{cursor:pointer;color:var(--txt);font-weight:600}
.upd-notes pre{margin:6px 0 0;max-height:140px;overflow:auto;white-space:pre-wrap;word-break:break-word;font:11.5px/1.5 ui-monospace,Consolas,monospace;opacity:.9}
.upd-ok-notes b{color:var(--txt);font-weight:600}
.upd-ok-notes .uo-t{margin-top:4px;color:var(--txt)}
.upd-ok-notes ul{margin:4px 0 0;padding-left:16px;max-height:140px;overflow:auto}
.upd-ok-notes li{line-height:1.45;margin:2px 0}
.upd-ok-notes code{font:.95em ui-monospace,Consolas,monospace}
.upd-bar{margin-top:10px;height:3px;border-radius:99px;background:rgba(127,127,127,.25);overflow:hidden}
.upd-bar i{display:block;height:100%;width:35%;background:var(--ccp-accent);border-radius:99px;animation:updslide 1.4s ease-in-out infinite}
@keyframes updslide{0%{margin-left:-35%}100%{margin-left:100%}}
@media (prefers-reduced-motion:reduce){.upd-bar i{animation:none;width:100%;opacity:.45}}
.updrow{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:8px 0}
#ccliBox .ccli-btns{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.updsub.ok{color:var(--ok,#45d6ab)}.ccli-bar{margin:8px 0 2px}
.ccli-pvbox{position:absolute;left:0;top:0;width:0;height:0;z-index:4;pointer-events:none}
.ccli-pv{position:absolute;padding:1px 5px;border-radius:4px;background:rgba(11,13,16,.78);font:9px/1.3 Inter,system-ui,sans-serif;white-space:nowrap;pointer-events:auto;cursor:default}
.ccli-pv[hidden]{display:none}.ccli-pv.new{color:var(--ok,#45d6ab)}.ccli-pv.old{color:var(--warn,#ecc277)}
@media (max-width:640px){.ccli-pvbox{display:none}}
.ccps-box{position:absolute;left:0;top:0;width:0;height:0;z-index:4;pointer-events:none}
.ccps{position:absolute;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:16px;color:rgba(185,194,212,.82);text-shadow:0 2px 16px #080b10;pointer-events:none;container-type:size}
.ccps-clock{display:flex;flex-direction:column;align-items:center;gap:12px;max-width:100%;text-align:center}
.ccps-caption{font-size:clamp(16px,min(calc(130cqw / var(--ccps-caption-chars)),calc(12cqh / var(--ccps-count))),160px);line-height:1.2;font-weight:600;letter-spacing:.04em;text-transform:uppercase;white-space:nowrap}
.ccps-value{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:clamp(22px,min(calc(152cqw / var(--ccps-chars)),calc(65cqh / var(--ccps-count))),400px);font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.04em;line-height:1.02;white-space:nowrap}
.ccps-unknown{font-size:clamp(16px,min(calc(140cqw / var(--ccps-chars)),calc(38cqh / var(--ccps-count))),80px);white-space:normal}
.ccps[hidden]{display:none}
@media (max-width:640px){.ccps{gap:16px;padding:10px}.ccps-clock{gap:9px}}
#ccliBox pre{margin:6px 0 0;max-height:110px;overflow:auto;white-space:pre-wrap;word-break:break-word;font:11px/1.45 ui-monospace,Consolas,monospace;opacity:.85}
.ccli-badge{display:inline-flex;align-items:center;gap:5px;height:24px;padding:0 9px 0 7px;margin:0 0 0 8px;border:1px solid rgba(69,214,171,.45);border-radius:99px;background:rgba(69,214,171,.12);color:var(--fleet-accent,#45d6ab);font:600 11px/1 Inter,system-ui,sans-serif;cursor:pointer;flex:none;animation:ccliGlow 2.6s ease-in-out infinite}
.ccli-badge[hidden]{display:none}.ccli-badge svg{width:12px;height:12px;display:block}.ccli-badge b{font-weight:650}
@keyframes ccliGlow{0%,100%{box-shadow:0 0 0 0 rgba(69,214,171,0)}50%{box-shadow:0 0 0 4px rgba(69,214,171,.2)}}
@media (prefers-reduced-motion:reduce){.ccli-badge{animation:none}}
.ccli-pop{position:fixed;z-index:60;width:min(340px,calc(100vw - 24px));box-sizing:border-box;padding:12px 14px;border:1px solid var(--fleet-line,#25303f);border-radius:12px;background:var(--card,#131923);color:var(--txt,#e8edf4);box-shadow:0 12px 32px rgba(0,0,0,.45);font:12.5px/1.45 Inter,system-ui,sans-serif;text-align:left}
.ccli-pop[hidden]{display:none}.ccli-pop h4{margin:0 0 6px;font-size:13px}
.ccli-pop .cp-row{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:8px 0}.ccli-pop .cp-row small{display:block;color:var(--mut,#8c9bad);margin-top:2px}.ccli-pop small.bad,.ccli-pop .cp-note.bad{color:var(--bad,#ef969e)}
.ccli-pop .cp-note{margin-top:8px;font-size:11.5px;color:var(--mut,#8c9bad)}.ccli-pop .cp-foot{display:flex;justify-content:flex-end;margin-top:10px}
.segctl{display:inline-flex;border:1px solid #2a3140;border-radius:8px;overflow:hidden}
.segctl button{margin:0;background:transparent;border:0;color:var(--mut);font-weight:600;padding:6px 12px;border-radius:0;font-size:12.5px}
.segctl button.on{background:var(--acc);color:#0f1115}
.updtxt{min-width:0;font-size:13px}
.updsub{font-size:12px;color:var(--mut);margin-top:2px}
.updsub.bad{color:var(--bad)}
.updchk{display:flex;align-items:flex-start;gap:8px;font-size:12px;color:var(--mut);margin-top:8px;cursor:pointer}
.updchk input{margin-top:2px}
.updlog{margin:4px 0 10px;border:1px solid #2a3140;border-radius:8px}
.updlog>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px;padding:7px 10px;font-size:13px;font-weight:600;color:var(--txt);user-select:none}
.updlog>summary::-webkit-details-marker{display:none}
.updlog>summary::before{content:'';flex:none;border-left:5px solid currentColor;border-top:4px solid transparent;border-bottom:4px solid transparent;transition:transform .15s}
.updlog[open]>summary::before{transform:rotate(90deg)}
.updlog-list{max-height:260px;overflow-y:auto;padding:0 10px 4px;border-top:1px solid #1e232c}
.ul-it{padding:7px 0;border-bottom:1px solid #1e232c}
.ul-it:last-child{border-bottom:0}
.ul-h{font-size:12.5px;line-height:1.4;color:var(--txt)}
.ul-v{font-weight:700;font-variant-numeric:tabular-nums}
.ul-d{color:var(--mut);font-size:11.5px;margin:0 6px;font-variant-numeric:tabular-nums}
.ul-cur{display:inline-block;font-size:10.5px;line-height:1.3;color:var(--acc);border:1px solid currentColor;border-radius:99px;padding:0 6px;margin-right:6px;vertical-align:1px}
.ul-it ul{margin:3px 0 0;padding-left:16px}
.ul-it li{font-size:11.5px;line-height:1.4;color:var(--mut);margin:1px 0}
.ul-it code{font:.95em ui-monospace,Consolas,monospace}
.ul-empty{font-size:12px;color:var(--mut);padding:8px 0}
.ccp-err{font-size:11.5px;color:#ffb1b1}
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
/* --- оформление: базовые классы (вместо inline-стилей), чтобы скины могли их переопределять --- */
@keyframes ccspin{to{transform:rotate(360deg)}}
.tag.free{background:#2c3547;color:var(--mut)}
.fill{background:#555}
.fill[data-t=ok]{background:var(--ok)}
.fill[data-t=warn]{background:var(--warn)}
.fill[data-t=bad]{background:var(--bad)}
.rn-ic{font-style:normal}
.btn-relogin{margin-left:8px;background:transparent;border:1px solid #333c4d;color:var(--mut)}
.acts{display:flex;flex-wrap:wrap;align-items:center;gap:5px;margin-top:12px}
.acts .btn-sw,.acts .btn-renew,.acts .btn-relogin{margin-top:0}
.btn-sw:disabled{opacity:1;background:transparent;border:1px solid #333c4d;color:var(--mut);padding:7px 13px}
.acts .chip.login{flex:0 0 auto}
.acts .chip.login+.btn-relogin{margin-left:0}
.poolname{width:100%;box-sizing:border-box;background:#0f1115;border:1px solid #2a3140;color:inherit;border-radius:6px;padding:5px 8px;font-size:13px}
.modal{max-width:380px;max-height:90vh;overflow-y:auto}
.modalh{font-size:12.5px;font-weight:700;margin:14px 0 4px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}
.scrim{z-index:50}
#msg{z-index:70}
/* скин: phosphor */
/* PHOSPHOR — терминал на зелёном люминофоре: моноширинный шрифт, секционные рамки, сегментные полосы */
@keyframes ccBlinkPh{0%,55%{opacity:1}56%,100%{opacity:0}}
/* скин: aurora */
/* AURORA — тёмное стекло и свечение: плавные градиенты, пилюли */
/* скин: slate */
/* SLATE — графит и тишина: одна гарнитура, тонкие линии, акцент только цветом статуса */
/* скин: blocks */
/* BLOCKS — нео-брутализм: плоские цвета, толстые чёрные рамки, жёсткие тени */
/* акцент баннера (заголовок, таймер, полоса) на белом — тёмные варианты, светлые не читались (2,7–3,6) */

/* ---- добавление/удаление аккаунтов ---- */
.hdrgear svg{width:14px;height:14px;display:block}
.efrow{display:flex;align-items:center;gap:8px;margin:-6px 0 14px;font-size:12px;color:var(--mut)}
.efrow .eflbl{flex:0 0 auto;min-width:84px;cursor:default}
.efrow .eflbl b{font-weight:600;color:var(--ef);transition:color .25s}
.efrow .eflbl.mis b{text-decoration:underline dotted #c8a24a}
.efrow .eflbl.na{min-width:0;font-style:italic}
.efB{position:relative;flex:0 1 260px;min-width:150px;height:16px;cursor:pointer;margin:0 6px;--ef:#7c9aff}
.efB.busy{opacity:.6;pointer-events:none}
.efB.lock{cursor:not-allowed}
.efB.lock .th{opacity:.55}
.efB.unk .fl,.efB.unk .th{display:none}
.efB .tr{position:absolute;left:0;right:0;top:6px;height:4px;border-radius:99px;background:#242b38}
.efB .fl{position:absolute;left:0;top:6px;height:4px;border-radius:99px;background:linear-gradient(90deg,#6f86b3,var(--ef));transition:width .25s}
.efB .tk{position:absolute;top:5px;width:6px;height:6px;margin-left:-3px;border-radius:50%;background:#3a4250}
.efB .tk.pass{background:rgba(255,255,255,.55)}
.efB .tk.off{background:#1a1e27;box-shadow:0 0 0 1px #2a2f3a;cursor:not-allowed}
.efB .th{position:absolute;top:2px;width:12px;height:12px;margin-left:-6px;border-radius:50%;background:var(--bg);border:2px solid var(--ef);box-shadow:0 0 0 3px color-mix(in srgb,var(--ef) 22%,transparent);transition:left .25s,border-color .25s}
.btn-del{margin:0 0 0 auto;display:inline-flex;align-items:center;gap:5px;background:transparent;border:1px solid #333c4d;color:var(--mut)}
.btn-del svg{width:14px;height:14px}
.btn-del:hover:not(:disabled){border-color:var(--bad);color:var(--bad)}
.acts .btn-del{margin-top:0}
#acctScrim{z-index:60}
.dlgwarn{border:1px solid rgba(224,91,91,.5);background:rgba(224,91,91,.09);border-radius:10px;padding:10px 12px;font-size:13px;line-height:1.5;margin:10px 0 12px}
.dlgwarn b{color:var(--bad)}
.dlglbl{display:block;font-size:12.5px;color:var(--mut);margin-top:6px}
.dlginp{width:100%;background:#0f1115;border:1px solid #2a3140;color:var(--txt);border-radius:9px;padding:9px 11px;font-size:14px;margin-top:6px;font-family:inherit}
.dlginp:focus{outline:none;border-color:var(--acc)}
.dlgerr{color:var(--bad);font-size:13px;margin-top:10px;line-height:1.4}
.dlgerr[hidden]{display:none}
.btn-danger{background:var(--bad);color:#fff;margin-top:0}
.dlgstep{display:flex;align-items:center;gap:9px;margin:14px 0 6px;font-size:13px;font-weight:600}
.dlgstep i{flex:none;width:20px;height:20px;border-radius:50%;background:var(--acc);color:#0f1115;font-style:normal;font-size:12px;font-weight:700;display:inline-flex;align-items:center;justify-content:center}
.dlgurl{word-break:break-all;font-size:11.5px;line-height:1.4;background:#0f1115;border:1px solid #2a3140;border-radius:9px;padding:8px 10px;color:var(--mut);max-height:62px;overflow:auto}
.dlgrow{display:flex;gap:8px;margin-top:8px}
.dlgrow button{margin-top:0}
#acctScrim.side{justify-content:flex-end;align-items:stretch;padding:0}
#acctScrim.side #acctBox{max-width:min(400px,92vw);height:100%;max-height:none;overflow-y:auto;border-radius:0;border-width:0 0 0 1px;box-shadow:-8px 0 24px rgba(0,0,0,.35);animation:acctSide .25s ease}
#acctBox .modalfoot button{margin-top:0}
@keyframes acctSide{from{transform:translateX(100%)}to{transform:none}}

/* ---- вёрстка «вписано в окно» (ПК): консоль забирает всю свободную высоту, остальное компактно;
   «−/+» над консолью меняют только шрифт внутри неё — размер блока от масштаба не зависит ---- */
.toolrow,.tgrp{display:flex;flex-wrap:wrap;align-items:center;gap:6px 18px}
.toolrow{margin-bottom:14px}
.toolrow .switchrow,.toolrow .mrowslim,.toolrow .efrow{margin:0}
.toolrow .tgrp:last-child{flex:1 1 auto}
.toolrow .efrow{flex:1 1 280px;min-width:0}
.toolrow .efB{flex:1 1 150px;max-width:none}
.termbox{height:42vh;max-height:none}
@media (min-width:900px){
html:root:root body{height:100vh;height:100dvh;display:flex;flex-direction:column;padding:4px 16px 8px}
html:root:root body>*{flex:none}
html:root:root .hdr{margin:0 0 4px}
html:root:root .termwrap{flex:1 1 0;min-height:120px;margin-bottom:6px}
html:root:root .termbox{flex:1 1 0;height:auto;min-height:0}
html:root:root .toolrow{margin-bottom:6px}
html:root:root #cards{margin:12px 0 4px;gap:10px}
html:root:root .card{padding:8px 12px}
html:root:root .card .row{margin-top:5px}
html:root:root .card .lbl{margin-bottom:2px;line-height:1.25}
html:root:root .acts{margin-top:7px}
html:root:root .top{flex-wrap:nowrap}
html:root:root .email{min-width:0}
html:root:root .acts button{padding:4px 10px;font-size:12.5px}
html:root:root #cards .card{container-type:inline-size}
@container (max-width:470px){
html:root:root .btn-del .dl{display:none}
html:root:root .acts{gap:4px}
html:root:root .acts button{padding:4px 8px}
html:root:root .acts .btn-del{padding:4px 6px}
html:root:root .acts .chip{padding:2px 6px}
}
@container (max-width:420px){
html:root:root .acts{gap:3px}
html:root:root .acts button{padding:4px 6px;font-size:12px}
html:root:root .acts .btn-del{padding:4px 5px}
html:root:root .acts .chip{padding:2px 5px;font-size:10.5px}
}
}

/* ---- оптимизация в шапке рядом с названием; авто-переключение — в настройках ---- */
.hdrl{flex-wrap:wrap}
.hdrl .switchrow{margin:0;gap:8px;font-size:13px}
.hdrl .switchrow label{cursor:pointer}
.modal .switchrow{margin:2px 0 6px;gap:6px;font-size:13px}
.modal #autoWrap{flex:1 1 auto;display:flex;align-items:center;gap:6px}
.modal #autoNote{margin:0 0 6px}
.modal .wkchk{margin:2px 0 6px;font-size:12.5px}.modal .wkchk input{transform:scale(1.25);margin:3px 3px 0 2px;flex:none}
.modal .wkchk b{color:var(--txt)}
/* ---- версия приложения: мелко, справа внизу под карточками ---- */
/* подпись версии — в нижнем отступе под карточками, строку не занимает: карточки и консоль не сжимаются */
#verTag{align-self:flex-end;flex:none;height:0;overflow:visible;text-align:right;margin:0 2px;font-size:9px;line-height:1;color:var(--mut);letter-spacing:.03em;font-variant-numeric:tabular-nums;white-space:nowrap;pointer-events:none;user-select:none}
@media (min-width:900px){#verTag{position:fixed;right:18px;bottom:0;height:auto;margin:0}}
html.conly #verTag{display:none}
/* ---- режим «только консоль» ---- */
#fsBtn .fsx{display:none}
html.conly #fsBtn .fsi{display:none}
html.conly #fsBtn .fsx{display:block}
html.conly .svnav,html.conly .svnav+div,html.conly .hdr,html.conly .toolrow,html.conly #cards,html.conly #updBanner,html.conly #ccPause,html.conly #ccPauseDev,html.conly #ccPauseProd,html.conly #cxPause{display:none!important}
#cxPause:not([hidden]){display:block;padding:0;overflow:visible;margin:0 0 8px}
html:root:root.conly body{height:100vh;height:100dvh;display:flex;flex-direction:column;padding:0}
html:root:root.conly .termwrap{flex:1 1 0;min-height:0;margin:0}
html:root:root.conly .termbox{flex:1 1 0;height:auto;min-height:0;border:0;border-radius:0;box-shadow:none;padding-bottom:36px}
/* ---- панель аккаунтов: язычок у нижнего края, при наведении выезжает панель, у аккаунта — подробности ---- */
.dock{display:none}
html.conly .dock{display:block}
.dockzone{position:fixed;left:0;right:0;bottom:0;height:30px;z-index:40}
.docktab{position:absolute;left:50%;bottom:6px;transform:translateX(-50%);display:flex;align-items:center;gap:6px;padding:4px 12px;border-radius:99px;background:rgba(0,0,0,.6);color:var(--mut);font:600 11px/1 system-ui,sans-serif;letter-spacing:.04em;cursor:pointer;opacity:.8;transition:opacity .2s}
.docktab svg{width:12px;height:12px;display:block;flex:none}
.dockzone:hover .docktab,.dockzone.pin .docktab{opacity:0}
.dockpanel{position:absolute;left:0;right:0;bottom:0;display:flex;flex-wrap:wrap;justify-content:center;gap:10px;padding:12px 14px 14px;background:var(--bg);border-top:1px solid rgba(128,128,128,.28);box-shadow:0 -14px 34px rgba(0,0,0,.5);transform:translateY(110%);transition:transform .22s ease .35s;pointer-events:none}
.dockzone:hover .dockpanel,.dockzone.pin .dockpanel{transform:none;transition-delay:0s;pointer-events:auto}
.dchip{position:relative;display:flex;align-items:center;gap:11px;padding:7px 12px;border-radius:10px;background:var(--card);border:1px solid #2a3140;color:var(--txt);font-size:12.5px;line-height:1.2;font-weight:600;min-width:0;cursor:default}
.dchip.act{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)}
.ddot{width:8px;height:8px;border-radius:50%;background:#4a5263;flex:none}
.dchip.act .ddot{background:var(--ok);box-shadow:0 0 0 3px rgba(52,192,124,.22)}
.dchip.er .ddot{background:var(--bad)}
.dmail{max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dmet{display:flex;flex-direction:column;gap:3px;min-width:58px;font-size:11.5px}
.dmet .dml{color:var(--mut);font-weight:600;font-size:10.5px}
.dmet b{font-weight:700}
.dmet .dtop{display:flex;justify-content:space-between;gap:8px}
.dbar{display:block;height:3px;border-radius:99px;background:#242b38;overflow:hidden}
.dbar .fill{display:block}
.dpop{position:absolute;left:0;bottom:calc(100% + 10px);width:350px;max-width:92vw;padding:10px 12px 12px;border-radius:12px;background:linear-gradient(var(--card),var(--card)),var(--bg);border:1px solid #2a3140;box-shadow:0 12px 30px rgba(0,0,0,.55);color:var(--txt);font-weight:400;opacity:0;pointer-events:none;transition:opacity .15s;z-index:2;white-space:normal}
.dchip:hover .dpop{opacity:1}
.dpop .dpt{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-weight:700;font-size:13px}
.dpop .dpe{overflow:hidden;text-overflow:ellipsis}
.dpop .lbl{gap:12px}
.dpop .lbl span{white-space:nowrap}
.dpop .dpa{font-size:11px;color:var(--ok);font-weight:700}
.dpop .row:first-of-type{margin-top:8px}
/* ---- телефон (≤640 px): компактная шапка, высокая консоль, масштаб над консолью, карточки плотнее ---- */
@media (max-width:640px){
html:root:root body{padding:10px 10px 14px}
html:root:root .hdr{display:flex;flex-wrap:wrap;justify-content:flex-start;align-items:center;gap:6px 8px;margin:2px 0 8px}
html:root:root .hdrl{display:contents}
html:root:root h1{font-size:16px;order:1;min-width:0}
html:root:root #termDot{order:2;margin-right:auto}
html:root:root #optWrap{order:3;flex:1 1 150px;min-width:0;align-items:center;gap:8px;font-size:12px}
html:root:root #optWrap label{line-height:1.25}
html:root:root .hdrbtns{order:3;gap:8px!important}
html:root:root .hdrctl{order:4;margin-left:auto;gap:8px!important}
html:root:root .termwrap{margin-bottom:10px}
html:root:root .tzoom{top:6px;right:8px}
html:root:root .ctabs{top:6px;left:8px}
html:root:root .iconbtn.ctab,html:root:root .iconbtn.ctstop{height:34px}
html:root:root .iconbtn.ctab{padding:0 14px;font-size:13px}
html:root:root .iconbtn.ctstop{width:34px}
html:root:root .termwrap.hastabs .termbox{padding-top:50px}
html:root:root .ctabs.cacts:not([hidden]){display:grid;grid-template-columns:auto auto}
html:root:root .ctabs.cacts .ctacts{display:flex;gap:4px;grid-column:1/-1}
html:root:root .termwrap.hascacts .termbox{padding-top:92px}
html:root:root .termbox{height:62vh;height:62svh;min-height:300px;padding:8px 10px;font-size:calc(10.5px*var(--tz,1))}
html:root:root .toolrow{margin-bottom:10px}
html:root:root .card{padding:12px 12px}
html:root:root .top{flex-wrap:nowrap;align-items:flex-start}
html:root:root .email{min-width:0;font-size:14px;line-height:1.45;overflow-wrap:anywhere}
html:root:root .btn-del .dl{display:none}
html:root:root .acts .btn-del{padding:4px 8px}
html:root:root.conly .termbox{padding:8px 10px 40px}
html:root:root.conly .termwrap.hastabs .termbox{padding-top:50px}
html:root:root.conly .termwrap.hascacts .termbox{padding-top:92px}
html:root:root .dockpanel{flex-direction:column;flex-wrap:nowrap;align-items:stretch;gap:6px;padding:10px 10px 12px}
html:root:root .dchip{box-sizing:border-box;width:100%;gap:9px;padding:7px 10px}
html:root:root .dmail{flex:1 1 auto;min-width:0;max-width:none}
html:root:root .dmet{flex:none;min-width:62px}
html:root:root .dmet .dml{white-space:nowrap}
html:root:root .dmet .dtop{gap:6px}
}
/* ---- слетевший с Pro на Free аккаунт: красная рамка и «неактивный» — во всех скинах (!important
   перебивает рамки .card/.card.active скинов; рамка = border + кольцо box-shadow, как у .card.active) ---- */
.lpnote{display:flex;align-items:flex-start;gap:8px;margin:9px 0 2px;padding:7px 10px;border-radius:8px;background:rgba(229,72,77,.13);border:1px solid rgba(229,72,77,.5);color:#ffaaa6;font-size:12.5px;line-height:1.35}
.lpnote svg{flex:none;width:16px;height:16px;margin-top:1px;display:block}
.lpnote b{color:#ff8d88}
.dchip.lapsed .ddot{background:#e5484d;box-shadow:0 0 0 3px rgba(229,72,77,.22)}

.cxsec{margin-top:6px}
.cxsec[hidden]{display:none}
.cxhead{display:flex;align-items:center;flex-wrap:wrap;gap:6px 10px;margin:20px 0 10px}
.cxhead h2{font-size:16px;margin:0}
.cxsub{font-size:12px;color:var(--mut);line-height:1.4}
#cxcards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(340px,100%),1fr));gap:14px;align-items:start;margin-bottom:12px}
#cxcards .card{margin-bottom:0}
.cxsel{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:12px}
.cxsel select.dlginp{width:auto;flex:1 1 170px;min-width:0;margin-top:0}
.cxfast{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--mut);cursor:pointer;white-space:nowrap}
.cxfast input{transform:scale(1.15)}
.cxfast.off{opacity:.45;cursor:default}
.cxcode{font:700 28px/1.2 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.12em;text-align:center;background:#0f1115;border:1px solid #2a3140;border-radius:10px;padding:12px 8px;margin:8px 0 0;user-select:all}
.cxwait{font-size:12.5px;color:var(--mut);margin-top:12px;min-height:1.4em}
.cxcard-note{margin-top:8px}
#cxb .card{margin-bottom:12px}
.cxbgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr));gap:4px 14px;align-items:start}
.cxbgrid .dlglbl{margin-top:10px}
.cxbgrid[hidden],#cxb [hidden]{display:none}
.cxbrow{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:12px}
.cxbrow .dlginp{flex:1 1 220px;width:auto;min-width:0;margin-top:0}
.cxbfoot{justify-content:space-between;margin-top:16px}
.cxbfoot button{margin-top:0;margin-bottom:0}
.cxbfoot .btn-del{margin-left:auto}
.cxbstat{font-size:12.5px;color:var(--mut);margin-top:10px;line-height:1.5}
.cxbstat b{color:var(--txt)}
.cxbwarn{font-size:12.5px;color:var(--warn);margin-top:8px;line-height:1.4}
/* ---- Codex: значок в шапке и выпадающее окно (на странице места не занимает — консоль остаётся главной) ---- */
.hdrgear.cxbtn{width:auto;min-width:28px;padding:0 9px 0 7px;gap:6px;font-size:12px;font-weight:600;color:var(--txt);position:relative}
.hdrgear.cxbtn[hidden]{display:none}
.hdrgear.cxbtn svg{width:16px;height:16px}
.cxbtnname{max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cxbtnname:empty{display:none}
.cxdot{width:8px;height:8px;border-radius:50%;background:var(--mut);flex:none;display:block}
.cxdot.on{background:var(--ok)}
.cxdot.err{background:var(--bad);margin:0}
.cxdot.busy{background:var(--warn);animation:cxpulse 1.1s ease-in-out infinite}
@keyframes cxpulse{50%{opacity:.35}}
.cxbtn[aria-expanded="true"],.cxgbtn[aria-expanded="true"]{border-color:var(--acc);color:var(--acc)}
/* профиль и настройки — одна плашка: слева меню профилей, справа ⚙ */
.cxgrp{display:flex;align-items:center;flex:none}
.cxgrp[hidden]{display:none}
.cxgrp .hdrgear.cxbtn{border-radius:8px 0 0 8px}
.cxgrp .hdrgear.cxgbtn{border-radius:0 8px 8px 0;margin-left:-1px}
.cxgrp .hdrgear:hover,.cxgrp .hdrgear[aria-expanded="true"]{position:relative;z-index:1}
.hdrgear.cxbtn svg.cxcar{width:12px;height:12px;opacity:.7;transition:transform .15s}
.hdrgear.cxinst{width:auto;padding:0 9px 0 7px;gap:6px;font-size:12px;font-weight:600;color:var(--txt);border-style:dashed;cursor:pointer}
.hdrgear.cxinst[hidden]{display:none}
.hdrgear.cxinst svg{width:16px;height:16px}
.hdrgear.cxinst .cxinstp{color:var(--acc);font-size:15px;line-height:1;font-weight:700}
.cxinst[aria-expanded="true"]{border-color:var(--acc);color:var(--acc)}
.cxpop.cxinstpop{width:min(580px,calc(100vw - 20px))}
.cxinstpop .cxpbody{padding-bottom:16px}
.cxilead{font-size:13px;line-height:1.5;color:var(--txt);margin:6px 0 0}
.cxisteps{list-style:none;margin:12px 0 0;padding:0;display:flex;flex-direction:column;gap:8px}
.cxisteps li{display:flex;gap:10px;align-items:flex-start;font-size:13px;line-height:1.4;color:var(--mut)}
.cxisteps li b{flex:none;width:20px;height:20px;border-radius:50%;border:1px solid #2a3140;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700}
.cxisteps li.cur{color:var(--txt)}
.cxisteps li.cur b{border-color:var(--acc);color:var(--acc)}
.cxisteps li.done b{border-color:var(--ok);color:var(--ok)}
.cxisteps li .cxist{flex:1;min-width:0}
.cxisteps li.cur .cxist>span{font-weight:600}
.cxisb .cxinote:first-child{margin-top:8px}
.cxisb .dlglbl{display:block;margin-top:10px;font-size:12.5px;color:var(--mut)}
.cxinote{font-size:12.5px;line-height:1.45;color:var(--mut);margin:12px 0 0}
.cxinote.warn{color:var(--warn)}
.cxinote.bad{color:var(--bad)}
.cxilog{margin:10px 0 0;padding:8px 10px;max-height:130px;overflow:auto;background:#0f1115;border:1px solid #2a3140;border-radius:8px;font:11.5px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-all;color:#8b93a7}
.cxirow{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.cxirow button{margin-top:0}
.cxispin{display:inline-block;width:12px;height:12px;border:2px solid #2a3140;border-top-color:var(--acc);border-radius:50%;animation:cxispin .8s linear infinite;vertical-align:-2px;margin-right:6px}
@keyframes cxispin{to{transform:rotate(360deg)}}
.cxbtn[aria-expanded="true"] svg.cxcar{transform:rotate(180deg)}
.cxpop{position:fixed;z-index:40;width:min(580px,calc(100vw - 20px));display:flex;flex-direction:column;background:var(--card);border:1px solid #2a3140;border-radius:16px;box-shadow:0 18px 50px -12px rgba(0,0,0,.7)}
.cxpop[hidden]{display:none}
.cxphead{display:flex;align-items:center;gap:10px;padding:12px 14px 8px;flex:none}
.cxphead b{font-size:15px}
.cxphead .cxsub{flex:1;min-width:0}
.cxpbody{overflow-y:auto;padding:0 14px 14px;overscroll-behavior:contain}
.cxpbody .cxhead{margin:12px 0 8px}
.cxplist{display:grid;gap:8px}
.cxprof{display:flex;align-items:flex-start;gap:10px;width:100%;margin:0;text-align:left;background:transparent;border:1px solid #2a3140;color:var(--txt);font-weight:500;padding:10px 12px;border-radius:12px;cursor:pointer}
.cxprof:hover{border-color:var(--acc)}
.cxprof.act{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc);background:rgba(124,154,255,.08)}
.cxprof .cxpr{flex:none;width:16px;height:16px;border-radius:50%;border:2px solid var(--mut);margin-top:1px;position:relative}
.cxprof.act .cxpr{border-color:var(--acc)}
.cxprof.act .cxpr::after{content:"";position:absolute;inset:2px;border-radius:50%;background:var(--acc)}
.cxprof .cxpt{flex:1;min-width:0;display:block}
.cxprof .cxpn{display:block;font-weight:700;font-size:14px}
.cxprof .cxps{display:block;font-size:12px;color:var(--mut);line-height:1.4;margin-top:2px;font-weight:400}
.cxprof .cxpx{flex:none;margin:-4px -6px 0 0;padding:2px 8px;background:transparent;color:var(--mut);border:0;font-size:18px;line-height:1;border-radius:8px;cursor:pointer}
.cxprof .cxpx:hover{color:var(--bad)}
.cxpmanual{font-size:12px;color:var(--warn);margin-top:8px;line-height:1.4}
/* значок ⓘ и раскрывающееся пояснение профиля */
.cxprof .cxpi{flex:none;margin:-5px -4px 0 0;padding:4px;width:28px;height:28px;display:flex;align-items:center;justify-content:center;background:transparent;border:0;color:var(--mut);border-radius:8px;cursor:pointer}
.cxprof .cxpi svg{width:17px;height:17px}
.cxprof .cxpi:hover,.cxprof .cxpi.on{color:var(--acc)}
.cxprof .cxpx{margin-left:-6px}
/* карточка встроенного профиля: название, маршрут со стрелкой, цветные основные функции */
.cxprof{position:relative;overflow:hidden;padding-left:15px}
.cxprof::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--pc,var(--acc))}
.cxprof[data-id="orchestrator"]{--pc:linear-gradient(180deg,#19c3a0,#f0905f)}
.cxprof[data-id="codex"]{--pc:#19c3a0}
.cxprof.rsv:not(.act){opacity:.65;cursor:default}
.cxprof.rsv:not(.act):hover{border-color:#2a3140}
.cxprof .cxpn{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px}
.cxpnm{font-weight:800;font-size:14px;letter-spacing:.02em}
.cxpnm.caps{text-transform:uppercase;letter-spacing:.07em}
.cxroute{display:inline-flex;align-items:center;gap:6px}
.cxw{display:inline-block;padding:1px 8px;border-radius:999px;border:1px solid;font-size:11px;font-weight:700;line-height:1.5;letter-spacing:0}
.cxw.cx{color:#19c3a0;background:rgba(25,195,160,.12);border-color:rgba(25,195,160,.5)}
.cxw.cl{color:#f0905f;background:rgba(240,144,95,.12);border-color:rgba(240,144,95,.5)}
.cxw.nat{color:#9b8cff;background:rgba(155,140,255,.13);border-color:rgba(155,140,255,.5)}
.cxw.ok{color:var(--ok);background:rgba(52,192,124,.12);border-color:rgba(52,192,124,.45)}
.cxw.me{color:var(--txt);background:rgba(139,147,167,.14);border-color:rgba(139,147,167,.45)}
.cxarr{flex:none;width:26px;height:10px;vertical-align:middle}
.cxst{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
.cxroute{flex-wrap:wrap}
.cxprof .cxpf{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}
.cxpf>span{display:inline-flex;align-items:center;gap:5px;padding:2px 9px 2px 7px;border-radius:999px;border:1px solid;font-size:11px;font-weight:700;line-height:1.5}
.cxpf>span i{font-style:normal;font-size:12px;line-height:1}
.cxpf .g{color:var(--ok);background:rgba(52,192,124,.12);border-color:rgba(52,192,124,.4)}
.cxpf .b{color:var(--acc);background:rgba(124,154,255,.13);border-color:rgba(124,154,255,.45)}
.cxpf .o{color:var(--warn);background:rgba(232,185,62,.12);border-color:rgba(232,185,62,.4)}
.cxpf .r{color:var(--bad);background:rgba(224,91,91,.12);border-color:rgba(224,91,91,.45)}
.cxpinfo .cxflow{display:flex;flex-wrap:wrap;align-items:center;gap:4px 5px;margin-top:3px}
.cxpinfo .cxpik.can{color:var(--ok);font-weight:700}
.cxpinfo .cxpik.not{color:var(--bad);font-weight:700}
/* выключатель бота над профилями */
.cxpinfo{display:block;margin-top:8px;padding:8px 10px;border-radius:8px;background:rgba(124,154,255,.08);font-size:12px;line-height:1.45;font-weight:400;color:var(--txt);cursor:default}
.cxpinfo>span{display:block}
.cxpinfo .cxpirow+.cxpirow{margin-top:6px}
.cxpinfo .cxpik{display:inline;color:var(--mut)}
.cxpinfo .cxpid{display:block;color:var(--mut)}
.cxpinfo .cxpwhen{margin-top:8px;padding-top:6px;border-top:1px dashed #2a3140}
/* аварийный режим: красная карточка под профилями */
.cxw.rd{color:var(--bad);background:rgba(224,91,91,.12);border-color:rgba(224,91,91,.5)}
.cxemg{display:flex;align-items:flex-start;gap:10px;position:relative;overflow:hidden;margin:8px 0 0;padding:10px 12px 10px 15px;border:1px solid rgba(224,91,91,.5);border-radius:12px;background:rgba(224,91,91,.07)}
.cxemg::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:linear-gradient(180deg,var(--bad),#f0905f)}
.cxemg.on{border-color:var(--bad);box-shadow:0 0 0 1px var(--bad);background:rgba(224,91,91,.15)}
.cxemg .cxemm{flex:1;min-width:0;display:block}
.cxemg .cxen{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px}
.cxemg .cxen .cxpnm{color:var(--bad)}
.cxemg .cxes{display:block;font-size:12px;color:var(--mut);line-height:1.4;margin-top:2px;font-weight:400}
.cxemg .cxpf{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}
.cxemg .cxpi{flex:none;margin:-5px -4px 0 0;padding:4px;width:28px;height:28px;display:flex;align-items:center;justify-content:center;background:transparent;border:0;color:var(--mut);border-radius:8px;cursor:pointer}
.cxemg .cxpi svg{width:17px;height:17px}
.cxemg .cxpi:hover,.cxemg .cxpi.on{color:var(--bad)}
.cxemg .cxpinfo{background:rgba(224,91,91,.08)}
.cxemg .cxembtn{display:block;margin:10px 0 0;padding:7px 14px;font-size:13px;font-weight:700;border-radius:10px;cursor:pointer;background:transparent;color:var(--bad);border:1px solid var(--bad)}
.cxemg .cxembtn:hover{background:rgba(224,91,91,.14)}
.cxemg .cxembtn.off{background:var(--bad);color:#fff}
.cxemg .cxemtime{margin-top:4px;font-size:13px;font-weight:700;color:var(--bad)}
.cxemg .cxemj{margin-top:8px;padding:6px 8px;border-radius:8px;background:rgba(0,0,0,.18);font:11px/1.45 ui-monospace,Menlo,Consolas,monospace;color:var(--mut);white-space:pre-wrap;word-break:break-word}
.cxdot.emg{background:var(--bad);animation:cxpulse 1.1s ease-in-out infinite}
#cxBtn.emg{border-color:var(--bad)}
.cxeul{margin:0 0 12px;padding-left:18px;font-size:13px;line-height:1.5}
.cxeul li{margin:2px 0}
#cxeGo{background:var(--bad);color:#fff;border-color:var(--bad)}
/* счётчики лимитов в кнопке шапки: 5 ч · неделя, в одну строку; цвет по занятости */
.cxlim{display:inline-flex;align-items:center;gap:9px;font-size:11px;font-weight:600;line-height:1;white-space:nowrap}
.cxlim:empty{display:none}
.cxlim.stale{opacity:.55}
.cxl{--gc:var(--ok);position:relative;display:inline-flex;align-items:baseline;gap:3px;padding-bottom:3px}
.cxl.warn{--gc:var(--warn)}
.cxl.bad{--gc:var(--bad)}
.cxl i{font-style:normal;font-weight:500;font-size:10px;color:var(--mut)}
.cxl b{font-weight:700;font-variant-numeric:tabular-nums;color:var(--txt)}
.cxl.warn b{color:var(--warn)}
.cxl.bad b{color:var(--bad)}
.cxl::after{content:"";position:absolute;left:0;right:0;bottom:0;height:2px;border-radius:2px;background:linear-gradient(90deg,var(--gc) calc(var(--p,0)*1%),rgba(128,128,128,.28) 0)}
.cxl.nobar::after{display:none}
.cxacc{margin-top:12px;border-top:1px solid #232a36}
.cxwipe{margin-top:12px;padding-top:12px;border-top:1px solid #232a36;display:flex}
.cxwipe .btn-del{margin:0}
.cxacch{display:flex;align-items:center;gap:8px;width:100%;margin:0;padding:11px 2px;background:transparent;border:0;color:var(--txt);font-size:14px;font-weight:700;text-align:left;cursor:pointer;border-radius:0}
.cxacch .cxsum{flex:1;min-width:0;text-align:right;font-weight:400;font-size:12px;color:var(--mut);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cxacch .cxar{flex:none;width:16px;height:16px;transition:transform .15s}
.cxacc.open .cxacch .cxar{transform:rotate(180deg)}
.cxacc:not(.open)>.cxsec{display:none}
.cxpop #cxcards{grid-template-columns:1fr}
/* меню профилей Codex (просьба владельца): компактно, без «пилюль» и кружков, подробности — по шеврону.
   ПК — боковая шторка справа во всю высоту, телефон — раскрывается под кнопкой, как раньше */
.cxmenu{width:min(440px,calc(100vw - 20px));border-radius:12px}
.cxscrim{position:fixed;inset:0;z-index:39;background:rgba(4,7,12,.5);animation:cxfade .18s ease-out}
.cxscrim[hidden]{display:none}
@keyframes cxfade{from{opacity:0}to{opacity:1}}
@keyframes cxslide{from{transform:translateX(28px);opacity:0}to{transform:none;opacity:1}}
.cxmenu .cxpbody{padding:10px 12px 12px}
.cxmenu #cxp{display:flex;flex-direction:column;gap:8px}
.cxmenu .cxhead{margin:0;flex-wrap:nowrap;align-items:baseline;gap:8px}
.cxmenu .cxhead h2{font-size:14px;flex:none}
.cxmenu .cxhead .cxsub{flex:1;min-width:0;font-size:11px}
.cxmx{display:none;flex:none;align-self:center;width:26px;height:26px;margin:-2px -4px -2px 0;padding:0;align-items:center;justify-content:center;background:transparent;border:0;border-radius:6px;color:var(--mut);cursor:pointer}
.cxmx svg{width:15px;height:15px}
.cxmx:hover{color:var(--txt);background:rgba(255,255,255,.07)}
.cxmenu .cxplist{gap:6px}
.cxmenu .cxprof{gap:8px;padding:8px 6px 8px 12px;border-radius:8px}
.cxmenu .cxprof::before{width:3px}
.cxmenu .cxprof .cxpr{display:none}
.cxmenu .cxprof.act .cxpn::after{content:"";flex:none;width:4px;height:9px;margin:0 0 2px 2px;border:solid var(--acc);border-width:0 2px 2px 0;transform:rotate(45deg)}
.cxmenu .cxprof .cxpn{gap:3px 7px}
.cxmenu .cxpnm{font-size:13px}
.cxmenu .cxw{font-size:10px;font-weight:600;padding:0 5px;border-radius:4px}
.cxmenu .cxarr{width:18px;height:8px}
.cxmenu .cxprof .cxps,.cxmenu .cxemg .cxes{font-size:11px;line-height:1.35;margin-top:2px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.cxmenu .cxprof .cxpf,.cxmenu .cxemg .cxpf{display:none}
.cxmenu .cxprof .cxpi,.cxmenu .cxemg .cxpi{margin:-2px 0 0;width:22px;height:22px}
.cxmenu .cxprof .cxpi svg,.cxmenu .cxemg .cxpi svg{width:14px;height:14px;transition:transform .15s}
.cxmenu .cxprof .cxpi.on svg,.cxmenu .cxemg .cxpi.on svg{transform:rotate(180deg)}
.cxmenu .cxpinfo{font-size:11px;margin-top:6px;padding:6px 8px;border-radius:6px}
.cxmenu .cxemg{margin:0;padding:8px 6px 8px 12px;border-radius:8px}
.cxmenu .cxemg::before{width:3px}
.cxmenu .cxemg .cxembtn{margin-top:6px;padding:5px 12px;font-size:12px;border-radius:6px}
.cxmenu .cxpmanual{margin:0;font-size:11px}
@media (min-width:641px){
html:root:root .cxpop.cxmenu{top:0;bottom:0;right:0;left:auto;width:340px;height:100%;max-height:none;border-width:0 0 0 1px;border-radius:12px 0 0 12px;animation:cxslide .2s cubic-bezier(.2,.8,.2,1)}
.cxmx{display:flex}
}
@media (max-width:640px){.cxscrim{display:none!important}}
/* быстрая смена модели и усилия: третья кнопка группы и маленькая панель под ней */
.hdrgear.cxmodbtn{width:auto;min-width:28px;padding:0 8px;gap:6px;font-size:12px;font-weight:600;color:var(--txt);position:relative}
.hdrgear.cxmodbtn[hidden]{display:none}
.hdrgear.cxmodbtn svg{width:15px;height:15px;flex:none}
.cxgrp .hdrgear.cxmodbtn{border-radius:0;margin-left:-1px}
.cxmodbtn[aria-expanded="true"]{border-color:var(--acc);color:var(--acc)}
.cxmodn{max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cxmode{font-size:11px;font-weight:700;color:var(--acc);white-space:nowrap}
.cxmode:empty{display:none}
.cxquick{width:min(330px,calc(100vw - 20px))}
.cxquick .cxpbody{padding:12px 14px 14px}
.cxquick.busy .cxpbody{opacity:.55;pointer-events:none}
.cxqh{display:flex;align-items:baseline;gap:8px;margin:0 0 6px;font-size:12px;font-weight:700;color:var(--mut)}
.cxqh~.cxqh{margin-top:12px}
.cxqa{flex:1;min-width:0;text-align:right;font-weight:400;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cxqlist{display:grid;gap:4px;max-height:min(280px,42vh);overflow-y:auto;overscroll-behavior:contain}
.cxqm{display:flex;align-items:center;gap:10px;width:100%;margin:0;padding:7px 10px;text-align:left;background:transparent;border:1px solid #2a3140;color:var(--txt);border-radius:10px;cursor:pointer;font-size:13px;font-weight:500}
.cxqm:hover,.cxqe:hover{border-color:var(--acc)}
.cxqm.on,.cxqe.on{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc);background:rgba(124,154,255,.08)}
.cxqm .cxqr{flex:none;width:14px;height:14px;border-radius:50%;border:2px solid var(--mut);position:relative}
.cxqm.on .cxqr{border-color:var(--acc)}
.cxqm.on .cxqr::after{content:"";position:absolute;inset:2px;border-radius:50%;background:var(--acc)}
.cxqeff{display:flex;flex-wrap:wrap;gap:6px}
.cxqe{margin:0;padding:6px 11px;background:transparent;border:1px solid #2a3140;color:var(--txt);border-radius:999px;font-size:12px;font-weight:600;cursor:pointer}
.cxqe.on{color:var(--acc)}
@media (max-width:640px){
html:root:root .cxpop{left:10px!important;right:10px!important;width:auto}
html:root:root .hdrgear.cxbtn{padding:0 7px 0 6px;gap:4px}
html:root:root .cxbtnname{max-width:84px}
/* с счётчиками кнопка профиля не помещается в одну строку с остальными кнопками — занимает свою строку на всю ширину */
html:root:root .hdrctl{flex:1 1 100%;min-width:0;flex-wrap:wrap;justify-content:flex-end}
html:root:root .cxgrp{flex:1 1 280px;min-width:0}  /* меньше 280 px группе Codex не отдаём: не помещается рядом с соседней группой — уходит на свою строку */
html:root:root .cxgrp .hdrgear.cxbtn{flex:1 1 auto;min-width:0;justify-content:flex-start}
html:root:root .cxlim{margin-left:auto}
html:root:root .hdrgear.cxmodbtn{flex:0 1 auto;min-width:0;padding:0 6px;gap:5px}
html:root:root .hdrgear.cxmodbtn svg{display:none}
html:root:root .cxmodn{max-width:78px}
}
@media (max-width:360px){
html:root:root .cxbtnname{max-width:104px}
html:root:root .cxmodn{display:none}
html:root:root .hdrgear.cxmodbtn svg{display:block}
}
</style></head><body>
<div class="hdr"><div class="hdrl"><h1 id="h1">⚡ Claude — лимиты аккаунтов</h1><span class="termdot" id="termDot"></span><button type="button" class="ccli-badge" id="ccliBadge" hidden aria-haspopup="dialog"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg><b>0</b></button><div class="ccli-pop" id="ccliPop" role="dialog" hidden></div><span class="switchrow" id="optWrap"><input type="checkbox" id="opt"> <label for="opt" id="optLbl">Оптимизация переключений лимитов</label></span><div class="hdrbtns" style="display:flex;align-items:center;gap:10px"><button id="rfBtn" class="hdrgear" title="Обновить сейчас" aria-label="Обновить сейчас"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg></button><button id="gear" class="hdrgear" title="Модели"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg></button><button id="addAcct" class="hdrgear" title="Добавить аккаунт" aria-label="Добавить аккаунт" onclick="acctAdd()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg></button></div></div><div class="hdrctl" style="display:flex;align-items:center;gap:10px"><button id="cxInst" class="hdrgear cxinst" type="button" aria-haspopup="dialog" aria-expanded="false" hidden><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="4" width="19" height="16" rx="4"/><path d="M7 9.5l3 2.5-3 2.5"/><path d="M12.5 15h4.5"/></svg><span class="cxinstn" id="cxInstN">Codex</span><span class="cxinstp" aria-hidden="true">+</span></button><div class="cxgrp" id="cxGrp" hidden><button id="cxBtn" class="hdrgear cxbtn" type="button" aria-haspopup="true" aria-expanded="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="4" width="19" height="16" rx="4"/><path d="M7 9.5l3 2.5-3 2.5"/><path d="M12.5 15h4.5"/></svg><i class="cxdot" id="cxDot"></i><span class="cxbtnname" id="cxBtnName"></span><span class="cxlim" id="cxLim"></span><svg class="cxcar" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button><button id="cxMod" class="hdrgear cxmodbtn" type="button" aria-haspopup="dialog" aria-expanded="false" hidden><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/></svg><span class="cxmodn" id="cxModN"></span><span class="cxmode" id="cxModE"></span></button><button id="cxGear" class="hdrgear cxgbtn" type="button" aria-haspopup="dialog" aria-expanded="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg></button></div></div></div>
<div class="ccpause" id="updBanner" hidden></div>
<div class="ccpause" id="ccPause" hidden></div>
<div class="ccpause" id="ccPauseDev" hidden></div>
<div class="ccpause" id="ccPauseProd" hidden></div>
<div class="ccpause lvl-pause" id="cxPause" hidden></div>
<div class="termwrap">
 <div class="ctabs" id="cTabs" role="tablist" hidden><button type="button" class="iconbtn ctab on" id="ctClaude" role="tab" aria-selected="true" data-s="claude"><span class="ctlong">Claude </span>DEV</button><button type="button" class="iconbtn ctab" id="ctProd" role="tab" aria-selected="false" data-s="prod" hidden><span class="ctlong">Claude </span>PROD</button><button type="button" class="iconbtn ctab" id="ctCodex" role="tab" aria-selected="false" data-s="codex">Codex</button><span class="ctacts"><button type="button" class="iconbtn ctstop" id="ctCompact" hidden><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 4v4a1 1 0 0 1-1 1H4M15 4v4a1 1 0 0 0 1 1h4M9 20v-4a1 1 0 0 0-1-1H4M15 20v-4a1 1 0 0 1 1-1h4"/></svg></button><button type="button" class="iconbtn ctstop" id="ctNew" hidden><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 1 3 6.7"/><path d="M3 16v-4h4"/></svg></button><button type="button" class="iconbtn ctstop" id="ctRedraw" hidden><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg></button></span></div>
 <div class="tzoom"><button type="button" class="iconbtn" id="tzMinus"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/></svg></button><button type="button" class="tzval" id="tzVal">100%</button><button type="button" class="iconbtn" id="tzPlus"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg></button><button type="button" class="iconbtn" id="splitBtn" hidden><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/></svg></button><button type="button" class="iconbtn" id="fsBtn"><svg class="fsi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg><svg class="fsx" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg></button></div>
 <pre class="termbox" id="termBox"><span id="termHistory"></span>
<span id="termCurrent">Загрузка…</span><div class="termidle" id="termIdle" hidden><span id="termIdleTxt"></span><button type="button" id="termIdleGo" hidden></button></div></pre>
</div>
<div class="toolrow"><div class="tgrp">
<div id="mrow" class="mrowslim"></div>
<div id="efrow" class="efrow"></div>
</div></div>
<div id="cards">Загрузка…</div>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><linearGradient id="cxpg" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#19c3a0"/><stop offset="1" stop-color="#f0905f"/></linearGradient></defs></svg>
<div id="cxMenuScrim" class="cxscrim" hidden></div>
<div id="cxMenu" class="cxpop cxmenu" role="dialog" aria-label="Codex" hidden><div class="cxpbody"><div id="cxp"></div></div></div>
<div id="cxQ" class="cxpop cxquick" role="dialog" aria-label="Codex" hidden><div class="cxpbody" id="cxQb"></div></div>
<div id="cxPop" class="cxpop" role="dialog" aria-labelledby="cxPopTitle" hidden>
 <div class="cxphead"><b id="cxPopTitle">Codex</b><span class="cxsub" id="cxPopSt"></span><button type="button" class="hdrgear" id="cxPopX" style="margin:0" aria-label="×"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
 <div class="cxpbody">
  <div class="cxacc" id="cxBrW"><button type="button" class="cxacch" data-sec="br"><span id="cxBrT"></span><span class="cxsum" id="cxBrS"></span><svg class="cxar" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></button><div id="cxb" class="cxsec" hidden></div></div>
  <div class="cxacc" id="cxAccW"><button type="button" class="cxacch" data-sec="acc"><span id="cxAccT"></span><span class="cxsum" id="cxAccS"></span><svg class="cxar" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></button><div id="cx" class="cxsec" hidden></div></div>
  <div class="cxwipe" id="cxWipeW" hidden><button type="button" class="btn-del" id="cxWipe" onclick="cxWipe()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14M10 11v6m4-6v6"/></svg><span id="cxWipeT"></span></button></div>
 </div>
</div>
<div id="cxInstPop" class="cxpop cxinstpop" role="dialog" aria-labelledby="cxInstTitle" hidden>
 <div class="cxphead"><b id="cxInstTitle">Codex</b><span class="cxsub"></span><button type="button" class="hdrgear" id="cxInstX" style="margin:0" aria-label="×"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
 <div class="cxpbody" id="cxInstB"></div>
</div>
<div id="msg"></div>
<div id="verTag" title="cc-fleet">cc-fleet v__PAGE_VER__</div>
<div class="dock"><div class="dockzone" id="dockZone"><div class="docktab" id="dockTab" role="button" tabindex="0"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 15l6-6 6 6"/></svg><span id="dockTabLbl">Аккаунты</span></div><div class="dockpanel" id="dockPanel"></div></div></div>
<div id="scrim" class="scrim" hidden>
 <div class="modal">
  <h3 id="modalTitle">Настройки</h3>
  <div class="modalh" id="autoHdr">Авто-переключение</div>
  <div class="switchrow"><span id="autoWrap"><input type="checkbox" id="auto"> <label for="auto" id="autoLbl">Авто-переключение при <span id="thrLbl">85</span>% сессии</label></span><button type="button" class="thrbtn" id="thrMinus" aria-label="−"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/></svg></button><button type="button" class="thrbtn" id="thrPlus" aria-label="+"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg></button></div>
  <div class="modalsub" id="autoNote" hidden></div>
  <label class="updchk wkchk"><input type="checkbox" id="wkPause"><span id="wkLbl">Пауза на недельном потолке</span></label>
  <div class="modalh" id="updHdr">Обновления</div>
  <div id="updBox"></div>
  <div class="modalh" id="bkHdr">Копии аккаунтов</div>
  <div id="bkBox"></div>
  <div class="modalh" id="ccliHdr">Claude Code и Codex</div>
  <div id="ccliBox"></div>
  <div class="modalh" id="modelsHdr">Модели</div>
  <div class="modalsub" id="modalSub">Отметь, какие показывать кнопками на главной — применяется сразу, без «Сохранить»</div>
  <div id="poolList"></div>
  <div class="modalfoot"><button id="checkNew" class="ghostbtn">🔄 Проверить новые модели</button><button id="modalDone" style="margin-top:0">Готово</button></div>
 </div>
</div>
<div id="acctScrim" class="scrim" hidden><div class="modal" id="acctBox" role="dialog" aria-modal="true"></div></div>
<script>
const $=s=>document.querySelector(s);const TOKEN='__TOKEN__';const PAGE_VER='__PAGE_VER__';const API=location.origin+'/cc-hook/';
const I18N={
 ru:{
  title:'Claude — лимиты аккаунтов',
  h1:'⚡ Claude — лимиты аккаунтов',
  loading:'Загрузка…',
  autoLbl:thr=>'Авто-переключение при <span id="thrLbl">'+thr+'</span>% сессии',
  optLbl:'Автовыбор',
  optDisabledTitle:'Не действует: включён «Автовыбор» в «Управление аккаунтами» — он сам выбирает аккаунт по этим порогам',
  refresh:'Обновить сейчас',
  updated:'Обновлено',
  active:'АКТИВНЫЙ',
  session5:'Сессия 5ч',
  week:'Неделя',
  resetIn:(h,mm,clock)=>`сброс через ${h?h+' ч ':''}${mm} мин (${clock})`,
  usingNow:'Используется сейчас',
  optimizeRules:'Рулит автовыбор',
  switchTo:'Переключиться',
  switchBlockedTitle:'Заблокировано: включён автовыбор аккаунта',
  extended:'Я продлил',
  lapsedTag:'НЕАКТИВНЫЙ',
  lapsedTitle:'Аккаунт неактивный',
  lapsedNote:'подписка закончилась, в ротации не участвует. Опрос остановлен, пока не нажмёшь «Я продлил»',
  lapsedSince:t=>` (с ${t})`,
  relogin:'🔑 Войти заново',
  addBtnTitle:'Добавить аккаунт',
  addTitle:'Добавить аккаунт в ротацию',
  addSub:'Войди в Claude под нужным аккаунтом — после входа он сам встанет в ротацию, настраивать вручную ничего не нужно.',
  addEmailLbl:'Почта аккаунта (необязательно)',
  addEmailHint:'Подставится на странице входа, чтобы не набирать её заново.',
  addGetLink:'Получить ссылку для входа',
  addStarting:'Готовлю ссылку…',
  addStep1:'Открой ссылку и войди в нужный аккаунт Claude',
  addOpen:'Открыть ссылку',
  addCopy:'Копировать',
  addCopied:'Скопировано ✓',
  addStep2:'Вставь код, который покажет страница после входа',
  addCodePh:'Код со страницы входа',
  addSubmit:'Добавить в ротацию',
  addChecking:'Проверяю вход…',
  addRestart:'Начать заново',
  addNeedCode:'Вставь код со страницы входа.',
  delBtn:"Отключить",
  delBtnTitle:"Отключить аккаунт, сохранив историю и файлы",
  delTitle:"Отключить аккаунт?",
  delWarn:"Авторизация будет удалена, аккаунт исчезнет из балансера. Установленная программа, история, настройки и файлы останутся на сервере. Для повторного подключения понадобится новый вход.",
  delActive:"Активная сессия сначала перейдёт на другой аккаунт.",
  delLast:"Это единственный аккаунт Claude: его свободная консоль будет остановлена, вход удалён. История сохранится.",
  delWord:'подтверждаю',
  delType:w=>'Чтобы подтвердить, введи слово «'+w+'»',
  delGo:"Отключить",
  delWorking:"Отключаю…",
  cancel:'Отмена',
  askYes:'Да',
  askCompact:'Сжать контекст Claude (/compact)?',
  askProdCompact:'Сжать контекст Claude PROD (/compact)?',
  confirmNewProd:'Начать новую сессию Claude PROD (/clear)? Текущий разговор уйдёт в фон на диск, вернуться можно через /resume в консоли PROD. Продолжить?',
  askCxCompact:'Сжать контекст Codex (/compact)?',
  askStartCx:'Запустить консоль Codex?',
  askStartProd:'Запустить консоль PROD?',
  askOptOn:'Включить автовыбор аккаунта? Ручные переключения аккаунтов Claude будут заблокированы.',
  askOptOff:'Выключить автовыбор аккаунта? Ручные переключения аккаунтов Claude снова станут доступны.',
  askRelogin:'Войти заново в этот аккаунт? Запустится новый вход: понадобятся ссылка и код.',
  askRenew:'Отметить, что подписка продлена, и проверить вход?',
  askCxPref:'Применить выбор модели Codex для этого аккаунта?',
  askCxSet:w=>'Применить для Codex: '+w+'?',
  relTitle:'Войти заново',
  relStep1:email=>`Открой ссылку и войди под ${email}`,
  relHint:'Если браузер предлагает другой аккаунт — выбери «Использовать другой аккаунт».',
  relSubmit:'Подтвердить',
  relChecking:'Проверяю код…',
  confirmSwitch:n=>`Переключить активный аккаунт на ${n}?`,
  confirmModel:n=>`Сменить модель на ${n}?`,
  confirmEffort:l=>`Изменить effort на «${l}»?`,
  autoOn:'Авто-переключение включено',autoOff:'Авто-переключение выключено',
  wkLbl:cap=>`<b>Пауза на недельном потолке</b> — остановить Claude на ${cap}% недели, если переключаться некуда. Выключено — балансер не остановит заполнение до 100%.`,
  wkOn:'Пауза на недельном потолке включена',wkOff:'Пауза на недельном потолке выключена',
  ccpWeekTitle:'⏸ Неделя на потолке — <b>переключаться некуда</b>',
  ccpFleetWeekTitle:'⏸ Неделя на потолке у <b>всех аккаунтов Claude</b>',
  ccpFleetHardTitle:'⏸ Нет доступных аккаунтов Claude',
  ccpFleetSub:'Учтены этот сервер и подключённые серверы. Таймер — до доступности ближайшего аккаунта.',
  ccpWeekSub:(n,w,cap,na)=>`${n}: неделя <span class="num">${w}</span> (потолок ${cap}%), остальные аккаунты недоступны. Включена «Пауза на недельном потолке» — Claude встанет на паузу на следующем шаге и продолжит сам, когда `+(na?`освободится <b>${na}</b>.`:'освободится другой аккаунт или сбросится неделя.'),
  ccpRiskTitle:'⚠ Неделя на потолке — <b>балансер не остановит заполнение до 100%</b>',
  ccpRiskSub:(n,w,cap)=>`${n}: неделя <span class="num">${w}</span>, переключаться некуда — работаешь на свой страх и риск. Остановку на ${cap}% можно включить: ⚙ Настройки → «Пауза на недельном потолке».`,
  ccpWeekReason:(n,w,cap)=>`неделя ${n} на ${w}% (потолок ${cap}%), переключаться некуда`,
  ccpHintWeekOff:'работа пойдёт до 100% недели',
  ccpBtnSettings:'Открыть настройки',ccpHintSettings:'опция «Пауза на недельном потолке»',
  thrSet:v=>'Порог: '+v+'%',
  optOn:'Автовыбор включён — ручные переключения заблокированы',
  optOff:'Автовыбор выключен — ручные переключения доступны',
  ccliHdr:'Claude Code и Codex',ccliThis:'на этом сервере',ccliProd:'на PROD',
  ccliLine:(n,w,v)=>`${n} ${w}: ${v||'—'}`,
  ccliLatest:v=>`Доступна версия ${v}`,ccliUpToDate:'Установлена последняя версия',ccliNeverChecked:'Проверка новой версии ещё не выполнялась',
  ccliBtnCheck:'Проверить',ccliBtnUpdate:v=>`Обновить до ${v}`,ccliBtnRollback:v=>`Вернуть ${v}`,ccliBtnRetry:'Повторить',
  ccliAskUpdate:(n,w,a,b)=>`Обновить ${n} ${w} с ${a} до ${b}? Запущенные сессии не прервутся, новая версия подхватится при следующем запуске.`,
  ccliAskRollback:(n,w,a,b)=>`Вернуть ${n} ${w} с ${a} на ${b}?`,
  ccliRunning:(n,w,v)=>`Идёт обновление ${n} ${w}${v?' до '+v:''}…`,
  ccliNextClaudeStopped:'Claude сейчас не запущен: новая версия включится при его следующем запуске.',ccliNextCodexStopped:'Консоль Codex сейчас не запущена: новая версия включится при её запуске.',
  ccliPvOld:'Версия старая: есть новее.',ccliPvNew:'Версия актуальная.',ccliSec:s=>`${s} с`,ccliOkTitle:(n,a,b)=>`✅ Установлено: ${n} ${b} (было ${a})`,
  ccliNextClaude:'Запущенная сессия Claude пока на старой версии. Перезапусти Claude кнопкой: начнётся новая сессия.',ccliNextCodex:'Чтобы Codex заработал на новой версии, перезапусти консоль Codex.',
  ccliStaleNote:'Консоль запущена до обновления и работает на старой версии. Перезапусти её.',ccliRestartBtn:'Перезапустить консоль Codex',
  ccliStaleClaude:'Claude запущен до обновления и работает на старой версии. Перезапусти его: начнётся новая сессия.',ccliRestartClaude:'Перезапустить Claude',
  ccliAskRestartClaude:w=>`Перезапустить Claude ${w}? Текущий ход прервётся и начнётся НОВАЯ сессия: разговор не продолжается, остаются память и заметки. В Telegram он на минуту замолчит.`,
  ccliE_not_running:'Claude сейчас не запущен: при следующем запуске будет новая версия.',ccliE_other_worker:'Сейчас работа ведётся не на этом Claude: перезапуск не нужен, новая версия включится, когда он запустится.',ccliE_side_session:'Идёт побочная сессия Claude: заверши её и повтори.',
  ccliAskRestart:'Перезапустить консоль Codex? Разговор продолжится с того же места. Если Codex сейчас отвечает на запрос, подожди.',
  ccliE_busy:'Codex сейчас отвечает на запрос. Дождись ответа и повтори.',ccliE_stop_failed:'Не удалось остановить консоль Codex.',ccliE_start_failed:'Консоль остановлена, но не запустилась: запусти её кнопкой «Запустить».',ccliE_not_supported:'Для этой программы перезапуск из панели пока недоступен.',
  ccliDoneRb:(a,b)=>`Возврат выполнен: ${a} → ${b}. Запущенные сессии подхватят её после перезапуска.`,
  ccliFailed:e=>`Не удалось обновить: ${e||'ошибка npm'}. Прежняя версия осталась.`,
  ccliNative:p=>`Установка такого вида (${p}) кнопке незнакома — обновляй программу тем способом, которым ставил.`,
  ccliNone:'Claude Code не найден на этом сервере.',ccliNoNode:'Для обновления нужны Node.js 18 или новее и npm.',ccliNoLink:'Нет связи со вторым сервером.',
  ccliHint:'Кнопка запускает npm или штатное обновление Claude Code; работающую сессию она не перезапускает.',
  ccliE_not_npm:'Установка такого вида кнопке незнакома — она её не трогает.',ccliE_not_installed:'Claude Code не найден.',ccliE_no_node:'Нужны Node.js 18+ и npm.',
  ccliE_ssh:'Нет связи со вторым сервером.',ccliE_bad_target:'Недопустимая версия.',ccliE_nothing_to_rollback:'Возвращать нечего.',ccliE_spawn:'Не удалось запустить npm.',ccliE_x:'Не получилось. Попробуй ещё раз.',
  ccliBadgeTitle:n=>`Доступны новые версии программ: ${n}`,ccliPopTitle:'Доступны новые версии',ccliPopSub:(a,b)=>`${a} → ${b}`,ccliPopUpdate:'Обновить',ccliPopCancel:'Отмена',ccliPopNone:'Всё актуально',
  ccliPopNote:'Запущенные сессии не прервутся: новая версия подхватится при следующем запуске.',
  checking:'Проверяю…',
  checkErr:e=>`⚠ ошибка проверки: ${e}`,
  staleAt:t=>` · ниже данные на ${t}`,
  renewalIn:(d,h)=>`до ожидаемого PRO→FREE: ~${d} дн ${h} ч`,
  renewalSoon:'подписка: ожидаем обвал в PRO→FREE со дня на день',
  renewalChip:d=>`⏳ ${d} дн`,
  renewalChipToday:'⏳ сегодня',
  loginD:d=>`${d} дн`,
  loginH:h=>`${h} ч`,
  loginGone:'истёк',
  loginHint:w=>`Логин истекает ${w}. После этого нужно «Войти заново»`,
  loginHintGone:w=>`Логин истёк ${w}. Нужно «Войти заново»`,
  updHdr:'Обновления',
  updLog:'История изменений',
  updLogCur:'установлена',
  updLogEmpty:'Журнал изменений недоступен',
  updVer:v=>`cc-fleet v${v}`,
  updUpToDate:'Установлена последняя версия',
  updNeverChecked:'Проверка ещё не выполнялась',
  updCheckedAt:t=>`проверено в ${t}`,
  updCheckBtn:'Проверить',
  updAvailLine:v=>`Доступна версия ${v}`,
  updSkippedLine:v=>`Версия ${v} пропущена`,
  updManual:'Вручную',
  updAuto:'Автоматически',
  updHintManual:'Вручную: покажу баннер о новой версии, а ты решишь — обновляться или нет.',
  updHintAuto:'Автоматически: сам скачаю релиз, проверю, заменю файлы и перезапущу панель. Перед заменой делается бэкап, при сбое файлы возвращаются.',
  updCheckLbl:'Проверять новые версии раз в 6 часов (один запрос к GitHub, без токена)',
  bkHdr:'Копии аккаунтов',
  bkLine:(n,k)=>`Аккаунтов сейчас: ${n} · копий: ${k}`,
  bkLast:t=>`Последняя копия: ${t}`,
  bkNone:'Копий пока нет — первая появится в течение минуты',
  bkNow:'Копия сейчас',
  bkNowEmpty:'Копировать нечего: настоящих аккаунтов нет.',
  bkNowErr:'Не удалось сделать копию.',
  bkLost:l=>`⚠️ Нет в панели, но есть в копии: ${l}`,
  bkRestore:'Восстановить недостающие',
  bkRestoreAsk:l=>`Вернуть из копий: ${l}? Живые аккаунты не тронутся.`,
  bkRestored:l=>`Возвращено: ${l}. Если вход не сработает — нажми «Войти заново» у аккаунта.`,
  bkRestoreNone:'Возвращать нечего.',
  bkAuto:'Делать копии сами: раз в сутки и при новом входе, хранится 14 штук',
  bkHint:'Копии лежат на сервере (только root) и содержат токены входа — никому не передавай. Аккаунт, удалённый кнопкой, не возвращается.',
  bkErr:e=>`Ошибка копирования: ${e}`,
  updAutoConfirm:v=>`Сейчас доступна версия ${v} — её поставят сразу. Включить автоматическое обновление?`,
  updNoSupport:r=>`Автообновление здесь недоступно (${r}). Обнови вручную: sudo ./install.sh из архива релиза.`,
  updBTitle:v=>`⬆ Вышла новая версия — <b>${v}</b>`,
  updBSub:(cur,name)=>`У тебя ${cur}`+(name?` · ${name}`:''),
  updBtnNow:'Обновить',
  updBtnSkip:'Пропустить эту версию',
  updBtnPage:'Страница релиза ↗',
  updBtnOk:'Понятно',
  updBtnReload:'Обновить страницу',
  updStaleTitle:v=>`⬆ Служба уже на версии <b>${v}</b>`,
  updStaleSub:'Эта вкладка открыта на прежней версии — обнови страницу, чтобы увидеть новое.',
  updStaleHeld:'Страница обновится сама, как только закроешь диалог, допишешь ввод или выйдешь из полноэкранного режима.',
  updBtnRetry:'Повторить',
  updNotes:'Что нового',
  updAutoSoon:'Автообновление включено — поставлю при ближайшей проверке.',
  updRunTitle:v=>`⬆ Обновляю до <b>${v}</b>`,
  updPhDownloading:'Скачиваю релиз…',
  updPhVerifying:'Проверяю архив…',
  updPhInstalling:'Делаю бэкап и заменяю файлы…',
  updPhRestarting:'Перезапускаю службу — панель вернётся через несколько секунд…',
  updPhConfirm:'Новая версия запущена, проверяю, что всё работает…',
  updOkTitle:v=>`✅ Обновлено до версии <b>${v}</b>`,
  updOkSub:f=>`Было ${f}. Служба перезапущена и работает.`,
  updErrTitle:v=>`⚠ Обновление до <b>${v}</b> не удалось`,
  updRolled:'Прежняя версия возвращена — всё работает как раньше.',
  updE_net:'Нет связи с GitHub — попробуй позже.',
  updE_host:'Адрес загрузки не с GitHub — отказался качать.',
  updE_sha:'Контрольная сумма архива не совпала — ничего не менялось.',
  updE_archive:'Архив релиза повреждён или небезопасен — ничего не менялось.',
  updE_manifest:'Манифест релиза некорректен — ничего не менялось.',
  updE_check:'Файлы релиза не прошли проверку — ничего не менялось.',
  updE_backup:'Бэкап непригоден — ничего не менялось.',
  updE_restart:'Не удалось запланировать перезапуск службы (systemd-run).',
  updE_needs_install:'В этом релизе изменилась установка — один раз запусти sudo ./install.sh из архива релиза.',
  updE_boot:'Новая версия не подтвердила запуск вовремя.',
  updE_rollback_failed:'Откат не удался — поставь заново: sudo ./install.sh.',
  updE_systemd:'нужен systemd и юнит службы',
  updToastSkipped:'Версия пропущена',
  ccpPauseTitle:'⏸ Claude на <b>паузе по лимитам</b> — подъём автоматический',
  ccpDefReason:'лимиты сессионного окна',
  ccpPauseSub:(reason,at)=>'Причина: '+reason+(at?`. Будильник на <span class="num">${at}</span>: окно перепроверяется само, команда не нужна.`:'.'),
  ccpHardTitle:'⛔ Уперлись в лимиты — <b>переключаться некуда</b>',
  ccpHardAll:thr=>`Все аккаунты упёрлись в сессионное окно (порог ${thr}%).`,
  ccpHardSome:(n,why,rest)=>`${n}: ${why}, а остальные не годятся: ${rest}.`,
  ccpHardSub:(head,na,self)=>head+' Фоновые задачи не стартуют, чтобы не добить окно. '+(na?`Раньше всех освободится <b>${na}</b>`+(self?' — после сброса сессии работа продолжится на нём.':' — балансер переключится на него сразу после сброса.'):'Балансер переключится, как только освободится ближайший.'),
  ccpWhySes:(p,thr)=>`сессия <span class="num">${p}</span> (порог ${thr}%)`,
  ccpWhyWeek:(w,cap)=>`неделя <span class="num">${w}</span> — на потолке ${cap}%`,
  ccpWhyWeekOk:w=>`неделя <span class="num">${w}</span>`,
  ccpHeldSes:p=>`сессия ${p}`,ccpHeldWeek:w=>`неделя ${w}`,ccpHeldErr:'ошибка',
  ccpOffTitle:'▶ Пауза <b>отключена вручную</b> — Claude работает сверх порога',
  ccpOffSub:(na,at)=>'Входящие сообщения доходят сразу, инструменты не блокируются — до настоящего лимита аккаунта. Пауза включится сама, как только освободится окно'+(na&&at?` (раньше всех — <b>${na}</b> в <span class="num">${at}</span>)`:'')+', или по кнопке.',
  ccpBtnOff:'Отключить паузу',
  ccpBtnOn:'Включить паузу',
  ccpHintOff:thr=>`Claude продолжит сразу, сверх порога ${thr}%`,
  ccpHintHardOff:'следующее сообщение не встанет в очередь',
  ccpHintLimitOut:'настоящий лимит аккаунта исчерпан — отключать паузу бесполезно, Claude продолжит сам после сброса',
  cxlpBrief:at=>`Codex на паузе · сброс в ${at}`,
  cxlpBriefNoAt:'Codex на паузе · ждём сброса лимита',
  cxlpTitle:'⏸ Codex на <b>паузе по лимитам</b> — подъём автоматический',
  cxqpTitle:'Codex · настроенный порог лимита',
  cxqpBrief:(w,o)=>`Codex · ${w} · ${o?'автопауза отключена':'пауза по порогу'}`,
  cxqpLimitBrief:w=>`Codex · ${w} · 100%`,
  cxqpHardHint:n=>`Настоящий лимит исчерпан. Ожидает заданий: ${n}. Работа и очередь продолжатся после сброса; отключение паузы не обходит100%.`,
  cxqpSub:(s,w)=>`Порог 5 часов — ${s}%, недели — ${w}%. Беседа и Full сохранены. Задания ждут в очереди до сброса.`,
  cxqpOff:'Автопауза отключена вручную: можно использовать остаток до настоящих100%. Нажми «Включить паузу», чтобы вернуть защиту.',
  cxqpHint:n=>`Ожидает заданий: ${n}. Очередь сохраняется при перезапуске панели. /stop очищает ожидающие задания.`,
  cxlpSub:(n,why,at,nl)=>`Лимит Codex${n?` <b>${n}</b>`:''} исчерпан: ${why}. Переключаться некуда — сообщения из Telegram ждут в очереди и уйдут сами`+(at?` после сброса в <span class="num">${at}</span>`:' после сброса')+(nl?` (раньше всех освободится <b>${nl}</b>)`:'')+'.',
  cxlpWin:m=>m===300?'окно 5 ч':m===10080?'окно неделя':`окно ${Math.round(m/60)} ч`,
  cxlpWinAny:'сервис сообщил о лимите',
  cxlpTill:'до сброса',
  cxlpHint:'настоящий лимит исчерпан — отключать паузу бесполезно, Codex продолжит сам после сброса',
  cxlnBrief:(why,at)=>`Лимит Codex: ${why}`+(at?` · сброс в ${at}`:''),
  cxlnTitle:'⚠ Лимит Codex <b>исчерпан</b>',
  cxlnSub:(n,why,at,left)=>`Достигнут лимит Codex${n?` <b>${n}</b>`:''}: ${why}.`+(at?` Сброс в <span class="num">${at}</span>.`:left?` Сброс через <span class="num">${left}</span>.`:' Время сброса пока неизвестно.'),
  cxlnHint:'После освобождения лимита повторите запрос. Профиль и права Codex сохранены.',
  cxlnHintMulti:'Можно выбрать другой доступный аккаунт в настройках Codex или повторить запрос после сброса.',
  ccpHintOnHard:'окно забито — пауза встанет сразу',
  ccpHintOnFree:'окно уже свободно — пауза просто снова начнёт работать',
  ccpErr:e=>'не получилось: '+e,
  ccpGateTitle:'⏸ Активный аккаунт забит — <b>фоновые задачи приостановлены</b>',
  ccpGateWeekTitle:'⏸ Неделя активного аккаунта <b>на потолке</b>',
  ccpProdSes:p=>'сессия '+p+'%',ccpProdWeek:w=>'неделя '+w+'%',ccpProdFree:'свободен',
  ccpProdTitle:'⏸ Claude DEV в лимите — <b>Claude PROD свободен</b>',
  ccpProdSub:(n,why,prod,on,off)=>`${n}: ${why}. ${prod}`+(on?', передача на него включена.':off?', но автопередача выключена. DEV ждёт сброса окна; передать работу сейчас — «Работа на PROD» или «Автопередача» в «Настройки PROD».':', но передача на него не готова.'),
  ccpSearchTitle:'🔎 Ищу свободный аккаунт — <b>переключусь сам</b>',
  ccpSearchSub:(n,why)=>`${n}: ${why}. Свободного аккаунта здесь нет — смотрю Claude PROD. Если там есть лимит, работа перейдёт туда сама в течение минуты; если нет — здесь встанет пауза.`,
  ccpGateSub:(n,why,auto,bg)=>`${n}: ${why}. `+(auto?'Свободный аккаунт есть — балансер переключится на следующем тике'+(bg?', после него задачи пойдут сами.':'.'):'Свободный аккаунт есть, но авто-переключение выключено — переключись вручную.'),
  ccpManTitle:n=>`✋ ${n} <b>выбран вручную</b> — балансер не уводит с него`,
  ccpManSub:(n,why,at,bg)=>`${n}: ${why}. Работа идёт до 100% или до сброса окна`+(at?` в <span class="num">${at}</span>`:'')+' — паузы не будет. Вернуть авто-выбор — переключиться на свободный аккаунт.'+(bg?' Фоновые задачи не стартуют, пока сессия выше порога.':''),
  ccpTillMan:'до сброса окна',
  manTag:'Выбран вручную',manTagTitle:at=>`Выбран вручную — балансер не уведёт с него до ${at} или до 100%`,
  ccpWeek:w=>` · нед ${w}%`,
  ccpActive:' · активный',
  ccpChecks:n=>`перепроверок окна: <b>${n}</b>`,
  ccpTillWake:'до подъёма',
  ccpsTitle:'Claude на паузе по лимитам',ccpsTitleCx:'Codex на паузе по лимитам',ccpsUntil:(at,left)=>` до ${at} (осталось ${left})`,
  ccpsBody:'Новые действия ждут сброса. Сообщения в Telegram встают в очередь, беседа сохранена — после сброса работа продолжится сама.',
  ccpsBodyCx:'Переключаться некуда. Сообщения из Telegram ждут в очереди и уйдут сами после сброса.',
  ccpsReset5h:'5 часов · до сброса',ccpsResetWeek:'Неделя · до сброса',ccpsReset:'До сброса лимита',ccpsUnknown:'Время уточняется',ccpsDays:n=>`${n} д`,
  limxPause:at=>'пауза по лимитам'+(at?' до '+at:''),limxOutWeek:at=>'лимит недели исчерпан'+(at?' до '+at:''),limxOut5h:at=>'лимит 5 ч исчерпан'+(at?' до '+at:''),limxOut:at=>'лимит исчерпан'+(at?' до '+at:''),
  limxTipPause:'Новые действия ждут сброса, беседа сохранена.',limxTipOut:'Настоящий лимит исчерпан: новые запросы не пройдут до сброса, беседа сохранена.',
  ccpaWeek:(n,p,a)=>`${n} · неделя ${p}%${a?' до '+a:''}`,ccpaSession:(n,p,a)=>`${n} · 5 ч ${p}%${a?' до '+a:''}`,
  ccpaPause:(n,p,a)=>`${n} · пауза по лимитам${a?' до '+a:''}`,ccpaKnownPause:'Пауза подтверждена, точные проценты сейчас не получены. Состояние обновится автоматически.',
  ccpaWait:c=>`Достигнут порог ${c}%. Доступность обновится после сброса.`,ccpaOverride:'Автопауза отключена вручную; ограничение провайдера сохраняется.',ccpaManual:'Аккаунт выбран вручную; автоматическая пауза не применена.',ccpaWarn:c=>`Достигнут порог ${c}%; автоматическая пауза выключена.`,
  ccpTillNearest:'до ближайшего окна',
  ccpTillFree:n=>'до освобождения '+n,
  ccpTillReset:'до сброса окна',
  ccpLeft:(h,m,s)=>h?`${h} ч ${m} мин`:`${m} мин ${s} с`,ccpLeftD:(d,h)=>`${d} д ${h} ч`,
  modelsBtnTitle:'Настройки',
  modelsTitle:'Настройки',
  modelsHdr:'Модели',
  modelsSub:'Отмеченные модели показываются в быстром меню плитки Claude. Применяется сразу.',
  tzMinusTitle:'Шрифт консоли меньше',tzPlusTitle:'Шрифт консоли крупнее',tzResetTitle:'Размер шрифта консоли — клик вернёт 100%',
  fsTitle:'Только консоль, во весь экран',fsExitTitle:'Вернуться к обычному виду (Esc)',dockTab:'Аккаунты',dockSes:'Сессия 5ч',dockWeek:'Неделя',autoHdr:'Авто-переключение',optHint:'Автовыбор: сервис сам выбирает аккаунт, ручные кнопки блокируются',
  modelsDone:'Готово',
  noModelsEnabled:'Ни одна модель не включена — открой ⚙',
  efName:k=>({low:'низкий',medium:'средний',high:'высокий',xhigh:'очень высокий',max:'максимум'})[k]||k,
  efMis:d=>' (дефолт в settings.json: '+d+')',
  efNaTxt:'effort: эта модель не поддерживает',
  efUnk:'не задан',
  efUnkTip:'Уровень effort не найден ни в транскрипте, ни в settings.json, ни в статус-строке консоли — выбери его на шкале',
  efNaTitle:n=>(n||'Эта модель')+' не поддерживает уровни effort',
  efOffTip:n=>' не поддерживается моделью '+(n||''),
  efBlocked:(l,n)=>'⛔ Effort «'+l+'» не поддерживается моделью '+(n||'')+' — выбери другой уровень',
  efChecking:' · проверяю…',
  efDone:l=>'✅ Effort сессии: '+l,
  efNoConfirm:'Команда отправлена, но сессия ещё не подтвердила уровень — возможно, была занята. Кликни ещё раз.',
  newBadge:'новая',
  hideModelLbl:'скрыть',
  checkNewModels:'🔄 Проверить новые модели',
  candSearching:'Ищу…',
  candFound:'Найдено новых моделей: {n} — отметь нужные',
  candNone:'Новых моделей нет — у тебя уже всё актуальное',
  candErr:'Не удалось проверить модели — сервер ответил ошибкой',
  compactTitle:'Сжать контекст (/compact)',
  newSessionTitle:'Новая сессия (/clear)',
  redrawTitle:'Перерисовать консоль (если пропал кусок экрана, например полоски лимитов)',
  confirmNewSession:'Начать новую сессию Claude (/clear)? Текущий разговор уйдёт в фон на диск, вернуться можно через /resume в консоли. Продолжить?',
  cxTitle:'ChatGPT (Codex)',
  cxHint:'Отдельные аккаунты, модели и оптимизация лимитов Codex',
  cxAddTitle:'Добавить аккаунт ChatGPT',
  cxAddSub:'Пароль и почту вводить не нужно — вход по коду устройства. Сначала включи его в ChatGPT → Настройки → Безопасность («вход по коду устройства для Codex»); в рабочем пространстве это делает администратор. Если страница входа не принимает код — причина почти всегда в этом.',
  cxLabelLbl:'Название (необязательно)',
  cxLabelPh:'например, «Основной»',
  cxGetCode:'Получить код',
  cxStep1:'Открой ссылку и войди в нужный аккаунт ChatGPT',
  cxStep2:'Введи этот код на открывшейся странице',
  cxWait:t=>'Жду подтверждения… осталось '+t,
  cxDone:(e,p)=>'✅ Подключено: '+e+(p?' · '+String(p).toUpperCase():''),
  cxFailed:'Вход не завершён.',
  cxRetry:'Начать заново',
  cxRelTitle:'Войти заново в ChatGPT',
  cxEmpty:'Аккаунтов ChatGPT пока нет — «+» добавит первый.',
  cxCredits:b=>'Кредиты: '+b,
  cxCreditsUnl:'Кредиты: без ограничений',
  cxReached:'Лимит исчерпан — Codex будет отвечать ошибкой до сброса.',
  cxNotAllowed:'Сейчас использование для этого аккаунта недоступно.',
  cxLoginNeeded:'Вход устарел или отозван — нажми «Войти заново».',
  cxStale:'Показаны последние сохранённые цифры',
  cxSubChip:d=>'подписка '+d+' дн.',
  cxSubOver:'подписка закончилась',
  cxSubTitle:t=>'Подписка активна до '+t,
  cxAuthChip:d=>d<1?'вход обновлён сегодня':'вход обновлён '+d+' дн. назад',
  cxAuthTitle:t=>'Токен входа обновлён '+t+'. Codex продлевает его сам, пока им пользуются',
  cxModelTip:'Модель Codex',
  cxEffortTip:'Усилие рассуждения',
  cxEffort:'Усилие',
  cxDefault:'по умолчанию',
  cxFast:'⚡ Fast',
  cxFastTip:'Быстрее ответы, но лимит расходуется быстрее',
  cxFastNa:'Для этой модели Fast недоступен',
  cxQTip:'Быстрая смена модели и усилия',
  cxRelogin:'🔑 Войти заново',
  cxLaunch:'Команда запуска',
  cxLaunchTip:'Скопировать команду, которая запускает Codex под этим аккаунтом',
  cxDelTitle:"Отключить аккаунт ChatGPT?",
  cxDelWarn:"Вход в ChatGPT будет удалён, аккаунт исчезнет из балансера. Программа Codex, история разговоров, настройки и файлы останутся. Для подключения понадобится войти заново.",
  cxWin:h=>'Окно '+h+' ч',
  cxbTitle:'Мост Telegram ↔ Codex',
  cxbHint:'Пишешь Codex в своём боте. Как он работает, задаёт профиль в меню Codex в шапке: «Оркестратор» — Codex ведёт цель, а Claude исполняет шаги только после твоего «да»; «Codex» — работает сам, без Claude. Здесь — аккаунт, папки, токен и чат.',
  cxbMode:'Режим',
  cxbModeMed:'Посредник (задания Claude)',
  cxbModeOrch:'Оркестратор (Codex ведёт, Claude исполняет)',
  cxbModeSelf:'Самостоятельно',
  cxPopTitle:'Codex · ChatGPT',
  cxiTip:'Подключить Codex: установка и вход',
  cxiTitle:'Подключить Codex',
  cxiLead:'Codex — отдельный ИИ-помощник от OpenAI, работает по подписке ChatGPT. Подключение в три шага:',
  cxiS1:'Установить Codex на этот сервер (одной кнопкой)',
  cxiS1n:'Поставить Node.js и Codex на этот сервер — поручи Claude кнопкой ниже или сделай сам',
  cxiS2:'Войти в аккаунт ChatGPT: по коду устройства, пароль вводить не нужно',
  cxiS3:'Подключить своего Telegram-бота (по желанию)',
  cxiS1ok:'Codex установлен на сервер',
  cxiS2ok:v=>'Вход в ChatGPT выполнен'+(v?': '+v:''),
  cxiS2Hint:'Нажми — покажу код и ссылку: откроешь её в браузере и введёшь код. Когда войдёшь, окно само перейдёт к боту.',
  cxiLogin:'Войти в ChatGPT',
  cxiS3Hint:'Бот нужен, чтобы писать Codex из Telegram. Создай его у @BotFather и вставь токен; без бота Codex работает в консоли и в панели.',
  cxiBot:'Подключить бота',
  cxiSkip:'Пропустить этот шаг и завершить',
  cxiBotNoTok:'Вставь токен бота',
  cxiBotNoChat:'Нужен chat_id — число из Telegram',
  cxiSkipped:'Готово. Бота можно подключить позже: ⚙ у Codex → «Мост Telegram и все настройки».',
  cxiAllDone:'Готово: Codex установлен, вход выполнен, бот подключён.',
  cxiNodeOk:v=>`Node.js ${v} найден — всё готово к установке.`,
  cxiNodeOld:(v,np)=>`Найден Node.js ${v}${np}, а нужен Node.js 16 или новее вместе с npm. Поручи Claude обновить его или сделай сам и нажми «Проверить снова».`,
  cxiNoNpm:' (npm не найден)',
  cxiNoNode:'Не нашёл Node.js и npm — они нужны для установки. Проще всего поручить это Claude: он поставит Node.js и сам запустит установку Codex. Или поставь Node.js 16 или новее сам (nodejs.org или менеджер пакетов системы) и нажми «Проверить снова».',
  cxiAsk:'Поручить Claude',
  cxiAskAgain:'Отправить ещё раз',
  cxiCopy:'Скопировать промт',
  cxiAsked:'Отправил Claude в консоль. Он поставит Node.js и Codex — окно само перейдёт к входу в ChatGPT, когда закончит. Если он спросит разрешение или пароль — ответь ему в консоли.',
  cxiAskedUnsure:'Отправил, но в консоли Claude не вижу промт — возможно, она занята. Проверь консоль; если пусто — нажми «Отправить ещё раз» или скопируй промт и вставь сам.',
  cxiInstall:'Установить Codex',
  cxiRun:'Ставлю Codex… обычно это пара минут.',
  cxiCancel:'Отмена',
  cxiRetry:'Повторить',
  cxiRecheck:'Проверить снова',
  cxiFail:'Не получилось:',
  cxiDone:v=>`Codex установлен${v?' ('+v+')':''}. Теперь войди в ChatGPT.`,
  cxBtnTip:'Профиль Codex: выбрать',
  cxGearTip:'Настройки Codex: аккаунты, лимиты, мост Telegram',
  cxAccSec:'Аккаунты и лимиты ChatGPT',
  cxWipe:"Отключить Codex",
  cxWipeTip:"Удалить все входы ChatGPT и отключить бота, сохранив программу, историю и файлы",
  cxWipeTitle:"Отключить Codex?",
  cxWipeWarn:"Все входы ChatGPT будут удалены, Telegram-бот отключён. Аккаунты исчезнут из балансера. Программа Codex, история, профили настроек, папка обмена и файлы останутся. Для повторного подключения потребуется новый вход.",
  cxBrSec:'Мост Telegram и все настройки',
  cxS5:'5 ч',
  cxS7:'нед',
  cxpTitle:'Профили',
  cxpHint:'Выбери — применится сразу.',
  cxpN_orchestrator:'Оркестратор',
  cxpN_codex:'Codex',
  cxpN_codex_solo_full:'Codex Full · сам',
  cxpRoute_orchestrator:['Codex','Claude'],
  cxpRoute_codex:['Нативный ИИ'],
  cxpRoute_codex_solo_full:['Codex','Самостоятельно'],
  cxpS_orchestrator:'Codex — главный: ведёт цель к результату и принимает работу. Claude выполняет шаги, но каждый — только после твоего «да».',
  cxpS_codex:'Работает сам, без Claude: отвечает на твои сообщения, читает и пишет в своей рабочей папке. Проект только читает.',
  cxpS_codex_solo_full:'Работает один, без Claude. Полная песочница Codex действует с правами настроенного пользователя ОС; root и SSH-доступ профиль не выдаёт.',
  cxpF_orchestrator:['Codex ведёт цель','Шаг — по твоему «да»','Claude исполняет','«Стоп» снимает всё'],
  cxpF_codex:['Работает сам','Пишет в своей папке','Проект — только чтение'],
  cxpF_codex_solo_full:['Без Claude и агента','Полная песочница Codex','Права пользователя ОС','Нужно подтверждение'],
  cxpFlowLbl:'Как это идёт',
  cxpFlow_orchestrator:['Ты','Codex: составляет шаг','Твоё «да»','Claude: выполняет','Codex: принимает'],
  cxpFlow_codex:['Ты','Codex','Ответ и файлы'],
  cxpFlow_codex_solo_full:['Ты','Codex','Ответ и файлы'],
  cxpCanL:'Может:',
  cxpNotL:'Не может:',
  cxpCan_orchestrator:'Составлять шаги, вести цель, принимать результат от Claude и писать в общую папку обмена.',
  cxpNot_orchestrator:'Менять проект сам и отправлять шаг Claude без твоего «да». «Стоп» в Telegram снимает задание и ожидание.',
  cxpCan_codex:'Отвечать сам, читать проект, создавать и править файлы в своей рабочей папке.',
  cxpCan_codex_solo_full:'Самостоятельно выполнять задачи с полным доступом Codex в пределах прав пользователя ОС, включая доступные ему файлы и команды.',
  cxpNot_codex:'Менять проект, видеть секреты и подключать Claude.',
  cxpNot_codex_solo_full:'Самостоятельно получать root или SSH-ключи. Доступ к серверам и перезапуск служб возможны только если уже разрешены пользователю ОС и настройкам аварийного режима.',
  cxpManual:'Настройки изменены вручную — ни один профиль не выбран.',
  cxpManualShort:'Свои настройки',
  cxpDel:'Удалить профиль',
  cxpDelAsk:n=>'Удалить профиль «'+n+'»?',
  cxpApply:'Применить',
  cxpConfTitle:'Профиль с полным доступом',
  cxpClose:'Закрыть',
  cxpInfo:'Что делает этот профиль',
  cxpWhenLbl:'Когда выбрать:',
  cxpWhen_orchestrator:'Большая цель в несколько шагов: Codex планирует и проверяет, Claude делает.',
  cxpWhen_codex:'Нужен отдельный помощник: разобрать код, подготовить текст или скрипт, дать второе мнение — пока Claude занят своим.',
  cxpWhen_codex_solo_full:'Нужно, чтобы Codex сам выполнял работу с полным доступом своей учётной записи ОС. Для серверных привилегий отдельно настрой аварийный режим.',
  cxeN:'Аварийный',
  cxeHdr:'🆘 Аварийный',
  cxeRoute:['Codex','Полный доступ к проекту'],
  cxeS:h=>'Когда Claude недоступен: Codex сам чинит проект — правит файлы, коммитит, перезапускает сервисы. Включается только вводом слова, выключается '+(h?'кнопкой или само через '+h+' ч.':'только кнопкой или /emergency_off — срока нет.'),
  cxeF:h=>['Пишет в проект','Перезапускает сервисы',h?'Само выключится по сроку':'Без срока','Снять — кнопкой или /emergency_off'],
  cxeFlow:h=>['Ты','Слово «аварийный»','Codex: полный доступ',h?'Срок или «Выключить»':'«Выключить»','Доступы сняты'],
  cxeCan:'Править и создавать файлы проекта, коммитить, запускать скрипты, перезапускать выбранные сервисы, читать файлы с доступами и ключ SSH для другого сервера.',
  cxeNot:h=>(h?'Работать после срока и получить больше, чем показано при включении.':'Получить больше, чем показано при включении. Срока нет: сам режим не выключится.')+' Перезапуск сервисов запускает код проекта от root — по сути это полный доступ к серверу. Всё, что Codex читает, уходит на серверы OpenAI.',
  cxeWhen:'Claude недоступен (лимиты, блокировка, сбой), а чинить нужно сейчас.',
  cxeBtn:'Включить…',
  cxeOnT:'АВАРИЙНЫЙ режим ВКЛЮЧЁН',
  cxeUntil:(t,l)=>'до '+t+' · осталось '+l,
  cxeNoLimit:t=>'без срока · включён с '+t,
  cxeStat:(n,f,k)=>'Перезапуск сервисов: '+n+' · файлов с доступами: '+f+(k?' · ключ SSH':''),
  cxeOffBtn:'Выключить сейчас',
  cxeOffAsk:'Выключить аварийный режим? Codex потеряет полный доступ, незавершённая работа остановится.',
  cxeConfTitle:'Включить аварийный режим?',
  cxeConfIntro:'Codex получит ПОЛНЫЙ доступ к проекту. Всё, что он прочитает, уходит на серверы OpenAI.',
  cxeConfProj:'Проект открывается Codex на запись, пока режим включён.',
  cxeConfSvc:l=>'Сможет перезапускать сервисы: '+l+'.',
  cxeConfFiles:'Получит копии файлов с доступами и ключ SSH для другого сервера.',
  cxeConfRoot:'Перезапуск сервисов запускает код проекта от root — это фактически доступ ко всему серверу.',
  cxeConfEnd:h=>h?'Само выключится через '+h+' ч, все доступы снимутся.':'Срока нет: доступ остаётся, пока ты сам не выключишь режим (кнопка в панели или /emergency_off).',
  cxeConfWord:w=>'Чтобы включить, введи слово «'+w+'».',
  cxeGo:'Включить',
  cxeLog:'Журнал',
  cxeLastBad:'⚠ В прошлый раз не всё снялось: ',
  cxeOnToast:'Аварийный режим включён',
  cxoRtLbl:'Права заданий Claude',
  cxoMode_mediator:'Codex сам проект не меняет: оформляет задание для Claude, а ты подтверждаешь «да» или «нет».',
  cxoMode_orchestrator:'Codex ведёт задачу к цели, Claude исполняет по шагу. Каждый следующий шаг — только после твоего «да», «стоп» останавливает.',
  cxoMode_self:'Codex отвечает сам, Claude не участвует.',
  cxoAcc_read:'Codex только читает проект и ничего не меняет.',
  cxoAcc_write:'Codex может создавать и править файлы в рабочей папке.',
  cxoAcc_full:'Codex работает без песочницы — на твоей ответственности.',
  cxoRt_read:'Claude по заданиям только отвечает и ничего не меняет.',
  cxoRt_dev:'Claude правит и коммитит на деве, прод не трогает.',
  cxoRt_full:'Claude может менять и прод — по обычным правилам: сначала бэкап.',
  cxpBrief:(m,r)=>m+' · задания: '+r.toLowerCase(),
  cxpBriefSelf:(m,a)=>m+' · доступ: '+a.toLowerCase(),
  cxLimUntil:t=>'до '+t,
  cxLimLogin:'вход!',
  cxLimLoginTip:'Нужен повторный вход в ChatGPT',
  cxLimSub:'подп.',
  cxLimSubD:d=>d+' дн.',
  cxLimSubEnd:'истекла',
  cxLimPlan:'план',
  cxLimFreeTip:'Подписка слетела на Free — нажми «Я продлил» в окне Codex',
  cxLapsedNote:was=>'Подписка слетела на Free'+(was?' (была '+was+')':'')+' — Codex работает урезанно. Продлил? Нажми «Я продлил» — перечитаю план и срок.',
  cxRenewBtn:'Я продлил',
  cxRenewTip:'Перечитать план и срок подписки',
  cxRenewing:'Проверяю…',
  cxLimFull:'исчерпан',
  cxLimReset:t=>'сброс '+t,
  cxLimIn:t=>'через '+t,
  cxDH:(d,h)=>d+' дн. '+h+' ч',
  cxHM:(h,m)=>h+' ч '+m+' мин',
  cxMin:m=>m+' мин',
  cxbAccess:'Доступ Codex',
  cxbAccRead:'Только чтение',
  cxbAccWrite:'Запись в рабочей папке',
  cxbAccFull:'Полный доступ (вне песочницы)',
  cxbProject:'Проект (Codex его только читает)',
  cxbProjHint:'Папка проекта, о котором говорит Codex. Менять её он не может — правит Claude. Пусто — берётся рабочая папка.',
  cxbDir:'Рабочая папка Codex',
  cxbProjectSelf:'Проект (только чтение)',
  cxbProjHintSelf:'Код проекта, который Codex только читает. Править его он не может — правки вносишь ты или Claude.',
  cxbDirSelf:'Здесь Codex может всё: создавать файлы и папки, менять и запускать. Вне этой папки писать он не может. Пусто — своя папка по умолчанию.',
  cxbRRead:'Чтение — ничего не менять',
  cxbRDev:'Дев — правки и коммиты на деве',
  cxbRFull:'Полные — включая прод',
  cxbSlot:'Аккаунт ChatGPT',
  cxbSlotAuto:'первый подходящий',
  cxbTokLbl:'Telegram-бот',
  cxbTokPh:'Токен нового бота от @BotFather',
  cxbConnect:'Подключить',
  cxbDisc:'Отключить бота',
  cxbBotInfo:(n,t)=>'Бот @'+n+' · токен …'+t,
  cxbChat:'Твой chat_id в Telegram (Codex отвечает только ему)',
  cxbOn:'Мост включён',
  cxbSave:'Сохранить',
  cxbNew:'Новый разговор',
  cxbConfirm:'Полный доступ — на твоей ответственности. Введи слово «подтверждаю»:',
  cxbRunning:'работает',
  cxbOff:'выключен',
  cxbBusy:' · Codex сейчас отвечает',
  cxbPending:' · ждёт твоё «да/нет» по заданию',
  cxbTasks:'Последние задания Claude: ',
  cxbSaved:'Сохранено',
  cxbDelAcct:"Отключить аккаунт",
  cxbDelTip:"Отключить выбранный аккаунт ChatGPT, сохранив историю",
  cxbDelPick:'Сначала выбери аккаунт в поле «Аккаунт ChatGPT» выше',
  cxbNoSlot:'Нет аккаунта ChatGPT — сначала добавь его выше.',
  cxcOff:'Консоль Codex не запущена',
  cxcSub:(sb,cwd)=>'Ввод — под выбранной консолью. Права — '+sb+(cwd?' · папка '+cwd:'')+'. Меняются в окне Codex (мост Telegram).',
  cxcStart:'Запустить',
  cxcStarting:'Запускаю консоль Codex…',
  cxcShown:(who,at)=>'Показан последний экран '+who+' на '+at+', он не обновляется.',
  cxcPaused:'Codex на паузе: профиль балансера его не использует, ввод не принимается.',
  cxcFrozen:'Процесс заморожен, экран не обновляется.',
  cxcPausedOff:'Профиль балансера держит Codex на паузе, поэтому сам он не запускается: только кнопкой.',
  cxcStopTip:'Остановить консоль Codex',
  cxcCompactTip:'Сжать контекст (/compact)',
  cxcNewTip:'Новая сессия Codex',
  cxcNewQ:'Начать новую сессию Codex? Прошлый разговор забудется — и в консоли, и в Telegram; на диске он останется. Продолжить?',
  cxcStopQ:'Остановить консоль Codex? Всё, что в ней выполняется, прервётся.',
  cxcSbRead:'только чтение',
  cxcSbWrite:'запись в рабочей папке',
  cxcSbFull:'полный доступ',
  cxcSw:'Консоль: переключить на ',
 },
 en:{
  title:'Claude — Account Limits',
  h1:'⚡ Claude — Account Limits',
  loading:'Loading…',
  autoLbl:thr=>'Auto-switch at <span id="thrLbl">'+thr+'</span>% of session',
  optLbl:'Auto-pick',
  optDisabledTitle:'Inactive: Auto-pick in Account management chooses the account by these thresholds',
  refresh:'Refresh now',
  updated:'Updated',
  active:'ACTIVE',
  session5:'Session 5h',
  week:'Week',
  resetIn:(h,mm,clock)=>`resets in ${h?h+'h ':''}${mm}m (${clock})`,
  usingNow:'In use now',
  optimizeRules:'Auto-pick active',
  switchTo:'Switch to this',
  switchBlockedTitle:'Blocked: Auto-pick is on',
  extended:'I renewed',
  lapsedTag:'INACTIVE',
  lapsedTitle:'Account inactive',
  lapsedNote:'the subscription has ended, so it is out of the rotation. Polling is stopped until you press “I renewed”',
  lapsedSince:t=>` (since ${t})`,
  relogin:'🔑 Log in again',
  addBtnTitle:'Add an account',
  addTitle:'Add an account to the rotation',
  addSub:'Sign in to Claude with the account you want — once you are in, it joins the rotation by itself, no manual setup.',
  addEmailLbl:'Account email (optional)',
  addEmailHint:'Pre-fills the sign-in page so you do not have to type it again.',
  addGetLink:'Get the sign-in link',
  addStarting:'Preparing the link…',
  addStep1:'Open the link and sign in to the Claude account',
  addOpen:'Open link',
  addCopy:'Copy',
  addCopied:'Copied ✓',
  addStep2:'Paste the code the page shows after sign-in',
  addCodePh:'Code from the sign-in page',
  addSubmit:'Add to rotation',
  addChecking:'Checking sign-in…',
  addRestart:'Start over',
  addNeedCode:'Paste the code from the sign-in page.',
  delBtn:"Disconnect",
  delBtnTitle:"Disconnect the account, retaining history and files",
  delTitle:"Disconnect this account?",
  delWarn:"Authorization will be removed and the account will disappear from the balancer. The installed program, history, settings and files stay on the server. Reconnecting requires a fresh sign-in.",
  delActive:"The active session will move to another account first.",
  delLast:"This is the only Claude account: its idle console will stop and its login will be removed. History is retained.",
  delWord:'confirm',
  delType:w=>'To confirm, type the word “'+w+'”',
  delGo:"Disconnect",
  delWorking:"Disconnecting…",
  cancel:'Cancel',
  askYes:'Yes',
  askCompact:'Compact the Claude context (/compact)?',
  askProdCompact:'Compact the Claude PROD context (/compact)?',
  confirmNewProd:'Start a new Claude PROD session (/clear)? The current conversation moves to disk in the background — resume it with /resume in the PROD console. Continue?',
  askCxCompact:'Compact the Codex context (/compact)?',
  askStartCx:'Start the Codex console?',
  askStartProd:'Start the PROD console?',
  askOptOn:'Enable Auto-pick? Manual switching of Claude accounts will be blocked.',
  askOptOff:'Disable Auto-pick? Manual switching of Claude accounts will be available again.',
  askRelogin:'Sign in to this account again? A new sign-in starts: you will need the link and the code.',
  askRenew:'Mark the subscription as renewed and check the sign-in?',
  askCxPref:'Apply the Codex model choice for this account?',
  askCxSet:w=>'Apply for Codex: '+w+'?',
  relTitle:'Log in again',
  relStep1:email=>`Open the link and sign in as ${email}`,
  relHint:'If the browser offers another account, choose “Use another account”.',
  relSubmit:'Confirm',
  relChecking:'Checking code…',
  confirmSwitch:n=>`Switch the active account to ${n}?`,
  confirmModel:n=>`Switch the model to ${n}?`,
  confirmEffort:l=>`Change effort to “${l}”?`,
  autoOn:'Auto-switch enabled',autoOff:'Auto-switch disabled',
  wkLbl:cap=>`<b>Pause at the weekly cap</b> — stop Claude at ${cap}% of the week when there is nothing to switch to. Off — the balancer won't stop the account from filling up to 100%.`,
  wkOn:'Pause at the weekly cap enabled',wkOff:'Pause at the weekly cap disabled',
  ccpWeekTitle:'⏸ Weekly cap reached — <b>nothing to switch to</b>',
  ccpWeekSub:(n,w,cap,na)=>`${n}: week <span class="num">${w}</span> (cap ${cap}%), the other accounts are unavailable. “Pause at the weekly cap” is on — Claude pauses at the next step and resumes by itself when `+(na?`<b>${na}</b> frees up.`:'another account frees up or the week resets.'),
  ccpRiskTitle:'⚠ Weekly cap reached — <b>the balancer won\'t stop it at 100%</b>',
  ccpRiskSub:(n,w,cap)=>`${n}: week <span class="num">${w}</span>, nothing to switch to — you work at your own risk. To stop at ${cap}%, turn on ⚙ Settings → “Pause at the weekly cap”.`,
  ccpWeekReason:(n,w,cap)=>`week of ${n} at ${w}% (cap ${cap}%), nothing to switch to`,
  ccpHintWeekOff:'work goes on up to 100% of the week',
  ccpBtnSettings:'Open settings',ccpHintSettings:'option “Pause at the weekly cap”',
  thrSet:v=>'Threshold: '+v+'%',
  optOn:'Auto-pick enabled — manual switching blocked',
  optOff:'Auto-pick disabled — manual switching available',
  ccliHdr:'Claude Code and Codex',ccliThis:'on this server',ccliProd:'on PROD',
  ccliLine:(n,w,v)=>`${n} ${w}: ${v||'—'}`,
  ccliLatest:v=>`Version ${v} is available`,ccliUpToDate:'The latest version is installed',ccliNeverChecked:'No version check yet',
  ccliBtnCheck:'Check',ccliBtnUpdate:v=>`Update to ${v}`,ccliBtnRollback:v=>`Roll back to ${v}`,ccliBtnRetry:'Retry',
  ccliAskUpdate:(n,w,a,b)=>`Update ${n} ${w} from ${a} to ${b}? Running sessions are not interrupted; the new version is picked up on the next start.`,
  ccliAskRollback:(n,w,a,b)=>`Roll ${n} ${w} back from ${a} to ${b}?`,
  ccliRunning:(n,w,v)=>`Updating ${n} ${w}${v?' to '+v:''}…`,
  ccliNextClaudeStopped:'Claude is not running now: the new version is used on its next start.',ccliNextCodexStopped:'The Codex console is not running now: the new version is used when it starts.',
  ccliPvOld:'The version is old: a newer one is available.',ccliPvNew:'The version is up to date.',ccliSec:s=>`${s}s`,ccliOkTitle:(n,a,b)=>`✅ Installed: ${n} ${b} (was ${a})`,
  ccliNextClaude:'The running Claude session is still on the old version. Restart Claude with the button: a new session starts.',ccliNextCodex:'Restart the Codex console to run Codex on the new version.',
  ccliStaleNote:'The console was started before the update and runs the old version. Restart it.',ccliRestartBtn:'Restart the Codex console',
  ccliStaleClaude:'Claude was started before the update and runs the old version. Restart it: a new session starts.',ccliRestartClaude:'Restart Claude',
  ccliAskRestartClaude:w=>`Restart Claude ${w}? The current turn is interrupted and a NEW session starts: the conversation does not continue, memory and notes stay. It goes quiet in Telegram for a minute.`,
  ccliE_not_running:'Claude is not running now: the new version is used on the next start.',ccliE_other_worker:'Work is not on this Claude right now: no restart is needed, the new version is used when it starts.',ccliE_side_session:'A side Claude session is running: finish it and try again.',
  ccliAskRestart:'Restart the Codex console? The conversation continues from the same place. If Codex is answering a request right now, wait.',
  ccliE_busy:'Codex is answering a request right now. Wait for the reply and try again.',ccliE_stop_failed:'Could not stop the Codex console.',ccliE_start_failed:'The console was stopped but did not start: start it with the Start button.',ccliE_not_supported:'Restart from the panel is not available for this program yet.',
  ccliDoneRb:(a,b)=>`Rolled back: ${a} → ${b}. Running sessions pick it up after a restart.`,
  ccliFailed:e=>`Update failed: ${e||'npm error'}. The previous version is kept.`,
  ccliNative:p=>`This kind of installation (${p}) is unknown to the button — update the program the way you installed it.`,
  ccliNone:'Claude Code is not found on this server.',ccliNoNode:'Updating needs Node.js 18 or newer and npm.',ccliNoLink:'No connection to the second server.',
  ccliHint:'The button runs npm or the built-in Claude Code updater; it does not restart a running session.',
  ccliE_not_npm:'This kind of installation is unknown to the button — it does not touch it.',ccliE_not_installed:'Claude Code is not found.',ccliE_no_node:'Node.js 18+ and npm are required.',
  ccliE_ssh:'No connection to the second server.',ccliE_bad_target:'Invalid version.',ccliE_nothing_to_rollback:'Nothing to roll back.',ccliE_spawn:'Could not start npm.',ccliE_x:'It did not work. Try again.',
  ccliBadgeTitle:n=>`New program versions available: ${n}`,ccliPopTitle:'New versions available',ccliPopSub:(a,b)=>`${a} → ${b}`,ccliPopUpdate:'Update',ccliPopCancel:'Cancel',ccliPopNone:'Everything is up to date',
  ccliPopNote:'Running sessions are not interrupted: the new version is picked up on the next start.',
  checking:'Checking…',
  checkErr:e=>`⚠ check failed: ${e}`,
  staleAt:t=>` · data below from ${t}`,
  renewalIn:(d,h)=>`until expected PRO→FREE: ~${d}d ${h}h`,
  renewalSoon:'subscription: expecting PRO→FREE drop any day now',
  renewalChip:d=>`⏳ ${d}d`,
  renewalChipToday:'⏳ today',
  loginD:d=>`${d}d`,
  loginH:h=>`${h}h`,
  loginGone:'expired',
  loginHint:w=>`Login expires ${w}. After that you need “Log in again”`,
  loginHintGone:w=>`Login expired ${w}. Use “Log in again”`,
  updHdr:'Updates',
  updLog:'Changelog',
  updLogCur:'installed',
  updLogEmpty:'Changelog is unavailable',
  updVer:v=>`cc-fleet v${v}`,
  updUpToDate:'You are on the latest version',
  updNeverChecked:'Not checked yet',
  updCheckedAt:t=>`checked at ${t}`,
  updCheckBtn:'Check now',
  updAvailLine:v=>`Version ${v} is available`,
  updSkippedLine:v=>`Version ${v} skipped`,
  updManual:'Manual',
  updAuto:'Automatic',
  updHintManual:'Manual: I show a banner about a new version and you decide whether to update.',
  updHintAuto:'Automatic: I download the release, verify it, replace the files and restart the panel. A backup is made first; on failure the files are put back.',
  updCheckLbl:'Check for new versions every 6 hours (one request to GitHub, no token)',
  bkHdr:'Account backups',
  bkLine:(n,k)=>`Accounts now: ${n} · backups: ${k}`,
  bkLast:t=>`Last backup: ${t}`,
  bkNone:'No backups yet — the first one appears within a minute',
  bkNow:'Back up now',
  bkNowEmpty:'Nothing to back up: there are no real accounts.',
  bkNowErr:'Could not make a backup.',
  bkLost:l=>`⚠️ Missing in the panel but present in a backup: ${l}`,
  bkRestore:'Restore missing',
  bkRestoreAsk:l=>`Bring back from backups: ${l}? Live accounts are not touched.`,
  bkRestored:l=>`Restored: ${l}. If the sign-in does not work, press “Sign in again” on the account.`,
  bkRestoreNone:'Nothing to restore.',
  bkAuto:'Back up automatically: once a day and on a new sign-in, 14 are kept',
  bkHint:'Backups live on the server (root only) and contain sign-in tokens — never share them. An account deleted with the button is not brought back.',
  bkErr:e=>`Backup error: ${e}`,
  updAutoConfirm:v=>`Version ${v} is available right now — it will be installed immediately. Turn on automatic updates?`,
  updNoSupport:r=>`Auto-update is unavailable here (${r}). Update by hand: sudo ./install.sh from the release archive.`,
  updBTitle:v=>`⬆ New version released — <b>${v}</b>`,
  updBSub:(cur,name)=>`You have ${cur}`+(name?` · ${name}`:''),
  updBtnNow:'Update',
  updBtnSkip:'Skip this version',
  updBtnPage:'Release page ↗',
  updBtnOk:'Got it',
  updBtnReload:'Reload page',
  updStaleTitle:v=>`⬆ The service is already on <b>${v}</b>`,
  updStaleSub:'This tab is still on the previous version — reload the page to see what’s new.',
  updStaleHeld:'The page will reload by itself once you close the dialog, finish typing or leave full screen.',
  updBtnRetry:'Retry',
  updNotes:'What’s new',
  updAutoSoon:'Auto-update is on — it will be installed at the next check.',
  updRunTitle:v=>`⬆ Updating to <b>${v}</b>`,
  updPhDownloading:'Downloading the release…',
  updPhVerifying:'Verifying the archive…',
  updPhInstalling:'Backing up and replacing files…',
  updPhRestarting:'Restarting the service — the panel will be back in a few seconds…',
  updPhConfirm:'The new version is running, checking that everything works…',
  updOkTitle:v=>`✅ Updated to version <b>${v}</b>`,
  updOkSub:f=>`Was ${f}. The service restarted and is running.`,
  updErrTitle:v=>`⚠ Update to <b>${v}</b> failed`,
  updRolled:'The previous version was restored — everything works as before.',
  updE_net:'Could not reach GitHub — try again later.',
  updE_host:'The download address is not GitHub — refused to download.',
  updE_sha:'Archive checksum mismatch — nothing was changed.',
  updE_archive:'The release archive is broken or unsafe — nothing was changed.',
  updE_manifest:'The release manifest is invalid — nothing was changed.',
  updE_check:'Release files failed the check — nothing was changed.',
  updE_backup:'The backup is unusable — nothing was changed.',
  updE_restart:'Could not schedule the service restart (systemd-run).',
  updE_needs_install:'This release changes the installation — run sudo ./install.sh from the release archive once.',
  updE_boot:'The new version did not confirm startup in time.',
  updE_rollback_failed:'Rollback failed — reinstall with sudo ./install.sh.',
  updE_systemd:'systemd and the service unit are required',
  updToastSkipped:'Version skipped',
  ccpPauseTitle:'⏸ Claude is <b>paused on limits</b> — it resumes on its own',
  ccpDefReason:'session window limits',
  ccpPauseSub:(reason,at)=>'Reason: '+reason+(at?`. Alarm at <span class="num">${at}</span>: the window is re-checked automatically, no command needed.`:'.'),
  ccpHardTitle:'⛔ Limits reached — <b>nothing to switch to</b>',
  ccpFleetWeekTitle:'⏸ All Claude accounts reached the weekly cap',
  ccpFleetHardTitle:'⏸ No Claude accounts available',
  ccpFleetSub:'Includes this server and connected servers. The timer shows when the first account becomes available.',
  ccpHardAll:thr=>`Every account is out of its session window (threshold ${thr}%).`,
  ccpHardSome:(n,why,rest)=>`${n}: ${why}, and none of the others will do: ${rest}.`,
  ccpHardSub:(head,na,self)=>head+" Background jobs stay down so they don't burn the rest of the window. "+(na?`<b>${na}</b> frees up first`+(self?' — work continues on it once its session resets.':' — the balancer switches to it right after the reset.'):'The balancer switches as soon as the nearest one frees up.'),
  ccpWhySes:(p,thr)=>`session <span class="num">${p}</span> (threshold ${thr}%)`,
  ccpWhyWeek:(w,cap)=>`week <span class="num">${w}</span> — at the ${cap}% cap`,
  ccpWhyWeekOk:w=>`week <span class="num">${w}</span>`,
  ccpHeldSes:p=>`session ${p}`,ccpHeldWeek:w=>`week ${w}`,ccpHeldErr:'error',
  ccpOffTitle:'▶ Pause <b>disabled manually</b> — Claude works past the threshold',
  ccpOffSub:(na,at)=>'Incoming messages go straight through and tools are not blocked — up to the real account limit. The pause re-arms by itself once a window frees up'+(na&&at?` (first: <b>${na}</b> at <span class="num">${at}</span>)`:'')+', or with the button.',
  ccpBtnOff:'Disable pause',
  ccpBtnOn:'Enable pause',
  ccpHintOff:thr=>`Claude continues right away, past the ${thr}% threshold`,
  ccpHintHardOff:'the next message will not be queued',
  ccpHintLimitOut:'the real account limit is used up — disabling the pause would not help; Claude resumes by itself after the reset',
  cxlpBrief:at=>`Codex paused · resets at ${at}`,
  cxlpBriefNoAt:'Codex paused · waiting for the limit reset',
  cxlpTitle:'⏸ Codex is <b>paused on limits</b> — it resumes on its own',
  cxqpTitle:'Codex · configured quota threshold',
  cxqpBrief:(w,o)=>`Codex · ${w} · ${o?'automatic pause disabled':'paused at threshold'}`,
  cxqpLimitBrief:w=>`Codex · ${w} · 100%`,
  cxqpHardHint:n=>`The real quota is exhausted. Waiting tasks: ${n}. Work and the queue resume after reset; disabling pause cannot bypass100%.`,
  cxqpSub:(s,w)=>`5-hour threshold: ${s}%; weekly threshold: ${w}%. The conversation and Full access are kept. Tasks wait for reset.`,
  cxqpOff:'Automatic pause is disabled manually: use the remaining quota up to the real100%. Enable pause to restore protection.',
  cxqpHint:n=>`Waiting tasks: ${n}. The queue survives panel restarts. /stop clears waiting tasks.`,
  cxlpSub:(n,why,at,nl)=>`Codex limit${n?` <b>${n}</b>`:''} is used up: ${why}. Nowhere to switch — Telegram messages wait in the queue and go out by themselves`+(at?` after the reset at <span class="num">${at}</span>`:' after the reset')+(nl?` (first to free up: <b>${nl}</b>)`:'')+'.',
  cxlpWin:m=>m===300?'5 h window':m===10080?'weekly window':`${Math.round(m/60)} h window`,
  cxlpWinAny:'the service reported the limit',
  cxlpTill:'until reset',
  cxlpHint:'the real limit is used up — disabling the pause would not help; Codex resumes by itself after the reset',
  cxlnBrief:(why,at)=>`Codex limit: ${why}`+(at?` · resets at ${at}`:''),
  cxlnTitle:'⚠ Codex <b>limit reached</b>',
  cxlnSub:(n,why,at,left)=>`Codex account${n?` <b>${n}</b>`:''} has reached the ${why}.`+(at?` Resets at <span class="num">${at}</span>.`:left?` Resets in <span class="num">${left}</span>.`:' The reset time is not known yet.'),
  cxlnHint:'Retry after the limit resets. The Codex profile and permissions are retained.',
  cxlnHintMulti:'Choose another available account in Codex settings or retry after the reset.',
  ccpHintOnHard:'window is full — the pause starts right away',
  ccpHintOnFree:'window is already free — the pause simply works again',
  ccpErr:e=>'failed: '+e,
  ccpGateTitle:'⏸ Active account is full — <b>background jobs paused</b>',
  ccpGateWeekTitle:'⏸ Active account <b>at the weekly cap</b>',
  ccpProdSes:p=>'session '+p+'%',ccpProdWeek:w=>'week '+w+'%',ccpProdFree:'is free',
  ccpProdTitle:'⏸ Claude DEV hit its limit — <b>Claude PROD is free</b>',
  ccpProdSub:(n,why,prod,on,off)=>`${n}: ${why}. ${prod}`+(on?', handoff to it is on.':off?', but auto handoff is off. DEV waits for the window reset; to move the work now use "Work on PROD" or "Auto handoff" in "PROD settings".':', but handoff to it is not ready.'),
  ccpSearchTitle:'🔎 Looking for a free account — <b>will switch by itself</b>',
  ccpSearchSub:(n,why)=>`${n}: ${why}. No free account here — checking Claude PROD. If it has room, work moves there by itself within a minute; if not, a pause starts here.`,
  ccpGateSub:(n,why,auto,bg)=>`${n}: ${why}. `+(auto?'A free account exists — the balancer switches on the next tick'+(bg?', after that jobs resume by themselves.':'.'):'A free account exists, but auto-switching is off — switch manually.'),
  ccpManTitle:n=>`✋ ${n} <b>picked manually</b> — the balancer keeps it`,
  ccpManSub:(n,why,at,bg)=>`${n}: ${why}. Work goes on up to 100% or until the window resets`+(at?` at <span class="num">${at}</span>`:'')+' — no pause. To bring back automatic choice, switch to a free account.'+(bg?' Background jobs stay down while the session is above the threshold.':''),
  ccpTillMan:'until the window resets',
  manTag:'Picked manually',manTagTitle:at=>`Picked manually — the balancer keeps it until ${at} or 100%`,
  ccpWeek:w=>` · wk ${w}%`,
  ccpActive:' · active',
  ccpChecks:n=>`window re-checks: <b>${n}</b>`,
  ccpTillWake:'until resume',
  ccpsTitle:'Claude paused on limits',ccpsTitleCx:'Codex paused on limits',ccpsUntil:(at,left)=>` until ${at} (${left} left)`,
  ccpsBody:'New actions wait for the reset. Telegram messages are queued, the conversation is kept — work resumes by itself after the reset.',
  ccpsBodyCx:'Nowhere to switch. Telegram messages wait in the queue and go out by themselves after the reset.',
  ccpsReset5h:'5 hours · until reset',ccpsResetWeek:'Week · until reset',ccpsReset:'Until limit reset',ccpsUnknown:'Reset time unavailable',ccpsDays:n=>`${n} d`,
  limxPause:at=>'paused on limits'+(at?' until '+at:''),limxOutWeek:at=>'weekly limit used up'+(at?' until '+at:''),limxOut5h:at=>'5 h limit used up'+(at?' until '+at:''),limxOut:at=>'limit used up'+(at?' until '+at:''),
  limxTipPause:'New actions wait for the reset; the conversation is kept.',limxTipOut:'The real limit is used up: new requests fail until the reset; the conversation is kept.',
  ccpaWeek:(n,p,a)=>`${n} · week ${p}%${a?' until '+a:''}`,ccpaSession:(n,p,a)=>`${n} · 5 h ${p}%${a?' until '+a:''}`,
  ccpaPause:(n,p,a)=>`${n} · paused on limits${a?' until '+a:''}`,ccpaKnownPause:'The pause is confirmed; exact percentages are unavailable. Status updates automatically.',
  ccpaWait:c=>`The ${c}% threshold was reached. Availability updates after reset.`,ccpaOverride:'Automatic pause was disabled manually; provider limits still apply.',ccpaManual:'The account was selected manually; automatic pause is not applied.',ccpaWarn:c=>`The ${c}% threshold was reached; automatic pause is disabled.`,
  ccpTillNearest:'until nearest window',
  ccpTillFree:n=>'until '+n+' frees up',
  ccpTillReset:'until window reset',
  ccpLeft:(h,m,s)=>h?`${h}h ${m}m`:`${m}m ${s}s`,ccpLeftD:(d,h)=>`${d}d ${h}h`,
  modelsBtnTitle:'Settings',
  modelsTitle:'Settings',
  modelsHdr:'Models',
  modelsSub:'Checked models show in the Claude tile quick menu. Applies instantly.',
  tzMinusTitle:'Smaller console font',tzPlusTitle:'Larger console font',tzResetTitle:'Console font size — click to reset to 100%',
  fsTitle:'Console only, full screen',fsExitTitle:'Back to the normal view (Esc)',dockTab:'Accounts',dockSes:'Session 5h',dockWeek:'Week',autoHdr:'Auto-switch',optHint:'Auto-pick: the service chooses the account, manual buttons are blocked',
  modelsDone:'Done',
  noModelsEnabled:'No models enabled — open ⚙',
  efName:k=>({low:'low',medium:'medium',high:'high',xhigh:'extra high',max:'maximum'})[k]||k,
  efMis:d=>' (default in settings.json: '+d+')',
  efNaTxt:'effort: not supported by this model',
  efUnk:'not set',
  efUnkTip:'Effort level was not found in the transcript, settings.json or the console status line — pick one on the scale',
  efNaTitle:n=>(n||'This model')+' does not support effort levels',
  efOffTip:n=>' is not supported by '+(n||'this model'),
  efBlocked:(l,n)=>'⛔ Effort “'+l+'” is not supported by '+(n||'this model')+' — pick another level',
  efChecking:' · checking…',
  efDone:l=>'✅ Session effort: '+l,
  efNoConfirm:'Command sent, but the session has not confirmed the level yet — it may have been busy. Click again.',
  newBadge:'new',
  hideModelLbl:'hide',
  checkNewModels:'🔄 Check for new models',
  candSearching:'Searching…',
  candFound:'New models found: {n} — tick the ones you want',
  candNone:'No new models — you are up to date',
  candErr:'Could not check for models',
  compactTitle:'Compact context (/compact)',
  newSessionTitle:'New session (/clear)',
  redrawTitle:'Redraw console (if part of the screen is missing, e.g. the limit bars)',
  confirmNewSession:'Start a new Claude session (/clear)? The current conversation moves to disk in the background — resume it with /resume in the console. Continue?',
  cxTitle:'ChatGPT (Codex)',
  cxHint:'A separate program with its own sign-in — not part of the Claude rotation',
  cxAddTitle:'Add a ChatGPT account',
  cxAddSub:'No password or email needed — sign-in by device code. Turn it on first in ChatGPT → Settings → Security (the device-code switch for Codex); in a workspace an admin does it. If the sign-in page does not accept the code, this is almost always the reason.',
  cxLabelLbl:'Name (optional)',
  cxLabelPh:'e.g. "Main"',
  cxGetCode:'Get code',
  cxStep1:'Open the link and sign in to the right ChatGPT account',
  cxStep2:'Enter this code on the page that opens',
  cxWait:t=>'Waiting for confirmation… '+t+' left',
  cxDone:(e,p)=>'✅ Connected: '+e+(p?' · '+String(p).toUpperCase():''),
  cxFailed:'Sign-in did not finish.',
  cxRetry:'Start over',
  cxRelTitle:'Sign in to ChatGPT again',
  cxEmpty:'No ChatGPT accounts yet — "+" adds the first one.',
  cxCredits:b=>'Credits: '+b,
  cxCreditsUnl:'Credits: unlimited',
  cxReached:'Limit reached — Codex will answer with an error until the reset.',
  cxNotAllowed:'Usage is currently not available for this account.',
  cxLoginNeeded:'The sign-in expired or was revoked — click "Sign in again".',
  cxStale:'Showing the last saved numbers',
  cxSubChip:d=>'subscription '+d+' d',
  cxSubOver:'subscription ended',
  cxSubTitle:t=>'Subscription is active until '+t,
  cxAuthChip:d=>d<1?'sign-in refreshed today':'sign-in refreshed '+d+' d ago',
  cxAuthTitle:t=>'Sign-in token refreshed '+t+'. Codex renews it by itself while it is in use',
  cxModelTip:'Codex model',
  cxEffortTip:'Reasoning effort',
  cxEffort:'Effort',
  cxDefault:'default',
  cxFast:'⚡ Fast',
  cxFastTip:'Faster replies, but the limit is used up faster',
  cxFastNa:'Fast is not available for this model',
  cxQTip:'Quick model and effort switch',
  cxRelogin:'🔑 Sign in again',
  cxLaunch:'Launch command',
  cxLaunchTip:'Copy the command that starts Codex under this account',
  cxDelTitle:"Disconnect this ChatGPT account?",
  cxDelWarn:"The ChatGPT login will be removed and the account will disappear from the balancer. Codex, conversation history, settings and files stay. Reconnecting requires a fresh sign-in.",
  cxWin:h=>h+' h window',
  cxbTitle:'Telegram ↔ Codex bridge',
  cxbHint:'You message Codex in your own bot. How it works is set by the profile in the Codex menu in the header: "Orchestrator" — Codex drives the goal and Claude does steps only after your "yes"; "Codex" — works on its own, without Claude. Here: account, folders, token and chat.',
  cxbMode:'Mode',
  cxbModeMed:'Mediator (tasks for Claude)',
  cxbModeOrch:'Orchestrator (Codex leads, Claude executes)',
  cxbModeSelf:'Standalone',
  cxPopTitle:'Codex · ChatGPT',
  cxiTip:'Connect Codex: install and sign in',
  cxiTitle:'Connect Codex',
  cxiLead:'Codex is a separate AI assistant from OpenAI that runs on a ChatGPT subscription. Three steps to connect it:',
  cxiS1:'Install Codex on this server (one button)',
  cxiS1n:'Get Node.js and Codex onto this server — ask Claude with the button below or do it yourself',
  cxiS2:'Sign in to your ChatGPT account with a device code, no password needed',
  cxiS3:'Connect your own Telegram bot (optional)',
  cxiS1ok:'Codex is installed on the server',
  cxiS2ok:v=>'Signed in to ChatGPT'+(v?': '+v:''),
  cxiS2Hint:'Press the button — I will show a code and a link: open the link in a browser and enter the code. Once you are in, this window moves on to the bot.',
  cxiLogin:'Sign in to ChatGPT',
  cxiS3Hint:'A bot lets you write to Codex from Telegram. Create one with @BotFather and paste its token; without a bot Codex still works in the console and in the panel.',
  cxiBot:'Connect the bot',
  cxiSkip:'Skip this step and finish',
  cxiBotNoTok:'Paste the bot token',
  cxiBotNoChat:'A chat_id is required — a number from Telegram',
  cxiSkipped:'Done. You can connect the bot later: ⚙ next to Codex → “Telegram bridge and all settings”.',
  cxiAllDone:'Done: Codex is installed, signed in, and the bot is connected.',
  cxiNodeOk:v=>`Node.js ${v} found — ready to install.`,
  cxiNodeOld:(v,np)=>`Found Node.js ${v}${np}, but Node.js 16 or newer with npm is required. Ask Claude to update it, or do it yourself and press “Check again”.`,
  cxiNoNpm:' (npm not found)',
  cxiNoNode:'Node.js and npm were not found — they are required for the install. The easiest way is to ask Claude: it installs Node.js and starts the Codex install itself. Or install Node.js 16 or newer yourself (nodejs.org or your system package manager) and press “Check again”.',
  cxiAsk:'Ask Claude',
  cxiAskAgain:'Send again',
  cxiCopy:'Copy prompt',
  cxiAsked:'Sent to the Claude console. It will install Node.js and Codex — this window moves on to the ChatGPT sign-in when it is done. If it asks for permission or a password, answer it in the console.',
  cxiAskedUnsure:'Sent, but I do not see the prompt in the Claude console — it may be busy. Check the console; if it is empty, press “Send again” or copy the prompt and paste it yourself.',
  cxiInstall:'Install Codex',
  cxiRun:'Installing Codex… usually takes a couple of minutes.',
  cxiCancel:'Cancel',
  cxiRetry:'Retry',
  cxiRecheck:'Check again',
  cxiFail:'It did not work:',
  cxiDone:v=>`Codex installed${v?' ('+v+')':''}. Now sign in to ChatGPT.`,
  cxBtnTip:'Codex profile: pick one',
  cxGearTip:'Codex settings: accounts, limits, Telegram bridge',
  cxAccSec:'ChatGPT accounts and limits',
  cxWipe:"Disconnect Codex",
  cxWipeTip:"Remove all ChatGPT logins and disconnect the bot, retaining the program, history and files",
  cxWipeTitle:"Disconnect Codex?",
  cxWipeWarn:"All ChatGPT logins will be removed and the Telegram bot disconnected. Accounts disappear from the balancer. Codex, history, profile settings, the exchange directory and files stay. Reconnecting requires a fresh sign-in.",
  cxBrSec:'Telegram bridge and all settings',
  cxS5:'5 h',
  cxS7:'wk',
  cxpTitle:'Profiles',
  cxpHint:'Pick one — it applies right away.',
  cxpN_orchestrator:'Orchestrator',
  cxpN_codex:'Codex',
  cxpN_codex_solo_full:'Codex Full · solo',
  cxpRoute_orchestrator:['Codex','Claude'],
  cxpRoute_codex:['Native AI'],
  cxpRoute_codex_solo_full:['Codex','Standalone'],
  cxpS_orchestrator:'Codex is in charge: it drives the goal and accepts the work. Claude runs the steps, but each one only after your "yes".',
  cxpS_codex:'Works on its own, without Claude: answers your messages, reads and writes in its own working folder. Only reads the project.',
  cxpS_codex_solo_full:'Works alone, without Claude. Codex gets its full sandbox under the configured OS user; this profile does not grant root or SSH access.',
  cxpF_orchestrator:['Codex drives the goal','Step — on your "yes"','Claude executes','"Stop" cancels all'],
  cxpF_codex:['Works on its own','Writes in its folder','Project — read only'],
  cxpF_codex_solo_full:['No Claude or agent','Full Codex sandbox','OS user permissions','Confirmation required'],
  cxpFlowLbl:'How it goes',
  cxpFlow_orchestrator:['You','Codex: drafts a step','Your "yes"','Claude: executes','Codex: accepts'],
  cxpFlow_codex:['You','Codex','Answer and files'],
  cxpFlow_codex_solo_full:['You','Codex','Answer and files'],
  cxpCanL:'Can:',
  cxpNotL:'Cannot:',
  cxpCan_orchestrator:'Draft steps, drive the goal, accept Claude\'s result and write to the shared exchange folder.',
  cxpNot_orchestrator:'Change the project itself or send a step to Claude without your "yes". "Stop" in Telegram cancels the task and the wait.',
  cxpCan_codex:'Answer on its own, read the project, create and edit files in its own working folder.',
  cxpCan_codex_solo_full:'Complete tasks independently with Codex full access, within the configured OS user permissions, including files and commands available to that user.',
  cxpNot_codex:'Change the project, see secrets or involve Claude.',
  cxpNot_codex_solo_full:'Grant itself root or SSH keys. Server access and service restarts work only if already allowed for the OS user and configured in emergency mode.',
  cxpManual:'Settings were changed by hand — no profile is selected.',
  cxpManualShort:'Custom settings',
  cxpDel:'Delete profile',
  cxpDelAsk:n=>'Delete profile "'+n+'"?',
  cxpApply:'Apply',
  cxpConfTitle:'Profile with full access',
  cxpClose:'Close',
  cxpInfo:'What this profile does',
  cxpWhenLbl:'When to pick it:',
  cxpWhen_orchestrator:'A big goal in several steps: Codex plans and checks, Claude does.',
  cxpWhen_codex:'You need a separate helper: go through code, prepare a text or script, give a second opinion — while Claude is busy.',
  cxpWhen_codex_solo_full:'You want Codex to do the work itself with full access for its OS account. Configure emergency mode separately for server privileges.',
  cxeN:'Emergency',
  cxeHdr:'🆘 Emergency',
  cxeRoute:['Codex','Full access to the project'],
  cxeS:h=>'When Claude is unavailable: Codex fixes the project itself — edits files, commits, restarts services. Turns on only by typing a word, turns off '+(h?'with a button or on its own after '+h+' h.':'only with a button or /emergency_off — no time limit.'),
  cxeF:h=>['Writes to the project','Restarts services',h?'Turns off by itself':'No time limit','Cancel — button or /emergency_off'],
  cxeFlow:h=>['You','The word "emergency"','Codex: full access',h?'Time up or "Turn off"':'"Turn off"','Access removed'],
  cxeCan:'Edit and create project files, commit, run scripts, restart the listed services, read the files with credentials and the SSH key for another server.',
  cxeNot:h=>(h?'Work after the deadline or get more than shown when turning it on.':'Get more than shown when turning it on. There is no time limit: the mode will not turn off by itself.')+' Restarting services runs project code as root — effectively full access to the server. Everything Codex reads goes to OpenAI servers.',
  cxeWhen:'Claude is unavailable (limits, a ban, an outage) and the fix cannot wait.',
  cxeBtn:'Turn on…',
  cxeOnT:'EMERGENCY mode is ON',
  cxeUntil:(t,l)=>'until '+t+' · '+l+' left',
  cxeNoLimit:t=>'no time limit · on since '+t,
  cxeStat:(n,f,k)=>'Service restarts: '+n+' · credential files: '+f+(k?' · SSH key':''),
  cxeOffBtn:'Turn off now',
  cxeOffAsk:'Turn off emergency mode? Codex loses full access and unfinished work stops.',
  cxeConfTitle:'Turn on emergency mode?',
  cxeConfIntro:'Codex gets FULL access to the project. Everything it reads goes to OpenAI servers.',
  cxeConfProj:'The project is opened to Codex for writing while the mode is on.',
  cxeConfSvc:l=>'It will be able to restart services: '+l+'.',
  cxeConfFiles:'It gets copies of the credential files and an SSH key for another server.',
  cxeConfRoot:'Restarting services runs project code as root — effectively access to the whole server.',
  cxeConfEnd:h=>h?'Turns off by itself after '+h+' h, all access is removed.':'No time limit: access stays until you turn the mode off yourself (button in the panel or /emergency_off).',
  cxeConfWord:w=>'To turn it on, type the word "'+w+'".',
  cxeGo:'Turn on',
  cxeLog:'Log',
  cxeLastBad:'⚠ Last time not everything was removed: ',
  cxeOnToast:'Emergency mode is on',
  cxoRtLbl:'Rights for Claude tasks',
  cxoMode_mediator:'Codex never changes the project itself: it drafts a task for Claude and you confirm "yes" or "no".',
  cxoMode_orchestrator:'Codex drives the goal, Claude executes step by step. Each next step only after your "yes"; "stop" halts it.',
  cxoMode_self:'Codex answers on its own, Claude is not involved.',
  cxoAcc_read:'Codex only reads the project and changes nothing.',
  cxoAcc_write:'Codex may create and edit files in the working folder.',
  cxoAcc_full:'Codex runs without a sandbox — at your own responsibility.',
  cxoRt_read:'Claude only answers for tasks and changes nothing.',
  cxoRt_dev:'Claude edits and commits on dev, never touches prod.',
  cxoRt_full:'Claude may change prod too — by the usual rules: backup first.',
  cxpBrief:(m,r)=>m+' · tasks: '+r.toLowerCase(),
  cxpBriefSelf:(m,a)=>m+' · access: '+a.toLowerCase(),
  cxLimUntil:t=>'until '+t,
  cxLimLogin:'login!',
  cxLimLoginTip:'Sign in to ChatGPT again',
  cxLimSub:'sub',
  cxLimSubD:d=>d+' d',
  cxLimSubEnd:'expired',
  cxLimPlan:'plan',
  cxLimFreeTip:'The subscription dropped to Free — press “I renewed” in the Codex window',
  cxLapsedNote:was=>'The subscription dropped to Free'+(was?' (was '+was+')':'')+' — Codex runs with reduced limits. Renewed? Press “I renewed” and I will re-read the plan and the date.',
  cxRenewBtn:'I renewed',
  cxRenewTip:'Re-read the plan and the subscription date',
  cxRenewing:'Checking…',
  cxLimFull:'used up',
  cxLimReset:t=>'resets '+t,
  cxLimIn:t=>'in '+t,
  cxDH:(d,h)=>d+' d '+h+' h',
  cxHM:(h,m)=>h+' h '+m+' min',
  cxMin:m=>m+' min',
  cxbAccess:'Codex access',
  cxbAccRead:'Read only',
  cxbAccWrite:'Write in the working folder',
  cxbAccFull:'Full access (no sandbox)',
  cxbProject:'Project (Codex only reads it)',
  cxbProjHint:'The project folder Codex talks about. It cannot change it — Claude does. Empty — the working folder is used.',
  cxbDir:'Codex working folder',
  cxbProjectSelf:'Project (read only)',
  cxbProjHintSelf:'The project code Codex only reads. It cannot change it — you or Claude make the edits.',
  cxbDirSelf:'Codex can do anything here: create files and folders, change and run things. It cannot write outside this folder. Empty — its own default folder.',
  cxbRRead:'Read — change nothing',
  cxbRDev:'Dev — edits and commits on dev',
  cxbRFull:'Full — including production',
  cxbSlot:'ChatGPT account',
  cxbSlotAuto:'first available',
  cxbTokLbl:'Telegram bot',
  cxbTokPh:'Token of a new bot from @BotFather',
  cxbConnect:'Connect',
  cxbDisc:'Disconnect bot',
  cxbBotInfo:(n,t)=>'Bot @'+n+' · token …'+t,
  cxbChat:'Your Telegram chat_id (Codex answers only this chat)',
  cxbOn:'Bridge enabled',
  cxbSave:'Save',
  cxbNew:'New conversation',
  cxbConfirm:'Full access is your responsibility. Type the word "confirm":',
  cxbRunning:'running',
  cxbOff:'off',
  cxbBusy:' · Codex is answering',
  cxbPending:' · waiting for your yes/no on a task',
  cxbTasks:'Recent Claude tasks: ',
  cxbSaved:'Saved',
  cxbDelAcct:"Disconnect account",
  cxbDelTip:"Disconnect the selected ChatGPT account, retaining history",
  cxbDelPick:'First pick an account in the “ChatGPT account” field above',
  cxbNoSlot:'No ChatGPT account — add one above first.',
  cxcOff:'The Codex console is not running',
  cxcSub:(sb,cwd)=>'Use the input below the selected console. Access — '+sb+(cwd?' · folder '+cwd:'')+'. Change it in the Codex window (Telegram bridge).',
  cxcStart:'Start',
  cxcStarting:'Starting the Codex console…',
  cxcShown:(who,at)=>'Showing the last '+who+' screen from '+at+'; it is not updating.',
  cxcPaused:'Codex is paused: the balancer profile does not use it, input is not accepted.',
  cxcFrozen:'The process is frozen, the screen is not updating.',
  cxcPausedOff:'The balancer profile keeps Codex paused, so it does not start by itself: use the button.',
  cxcStopTip:'Stop the Codex console',
  cxcCompactTip:'Compact context (/compact)',
  cxcNewTip:'New Codex session',
  cxcNewQ:'Start a new Codex session? The previous conversation is forgotten — in the console and in Telegram; it stays on disk. Continue?',
  cxcStopQ:'Stop the Codex console? Anything running in it will be interrupted.',
  cxcSbRead:'read only',
  cxcSbWrite:'write in the working folder',
  cxcSbFull:'full access',
  cxcSw:'Console: switch to ',
 },
};
let LANG='ru';
try{LANG=localStorage.getItem('cc_lang')||'ru';}catch(e){}
try{const q=new URLSearchParams(location.search).get('lang');if(q==='ru'||q==='en'){LANG=q;try{localStorage.setItem('cc_lang',q);}catch(e){}}}catch(e){}  // кнопки смены языка нет: ?lang=en|ru в ссылке, выбор запоминается
function tr(k,...a){const v=I18N[LANG][k];return typeof v==='function'?v(...a):v;}
let THR=85,lastSnap=null,lastModel=null;
let WCAP=99;
function renderAutoLbl(){$('#autoLbl').innerHTML=tr('autoLbl',THR);$('#wkLbl').innerHTML=tr('wkLbl',WCAP);}
function applyI18n(){
 document.title=tr('title');document.documentElement.lang=LANG;
 if(!$('#h1').querySelector('.fleet-brand-name'))$('#h1').textContent=tr('h1');
 $('#optLbl').textContent=tr('optLbl');$('#rfBtn').title=tr('refresh');$('#rfBtn').setAttribute('aria-label',tr('refresh'));
 renderAutoLbl();
 $('#gear').title=tr('modelsBtnTitle');$('#addAcct').title=tr('addBtnTitle');$('#addAcct').setAttribute('aria-label',tr('addBtnTitle'));$('#modalTitle').textContent=tr('modelsTitle');
 $('#modelsHdr').textContent=tr('modelsHdr');
 $('#tzMinus').title=tr('tzMinusTitle');$('#tzPlus').title=tr('tzPlusTitle');$('#tzVal').title=tr('tzResetTitle');
 $('#updHdr').textContent=tr('updHdr');$('#bkHdr').textContent=tr('bkHdr');
 $('#autoHdr').textContent=tr('autoHdr');$('#optWrap').title=tr('optHint');$('#dockTabLbl').textContent=tr('dockTab');
 $('#autoNote').textContent=tr('optDisabledTitle');setConly(document.documentElement.classList.contains('conly'),false);
 if(typeof updRender==='function'){updRender();updSettingsRender();if(typeof bkRender==='function')bkRender();$('#ccliHdr').textContent=tr('ccliHdr');if(typeof ccliRender==='function'){ccliRender();ccliBadgeRender();}}  // смена языка перерисовывает баннер и блок настроек
 $('#modalSub').textContent=tr('modelsSub');$('#modalDone').textContent=tr('modelsDone');$('#checkNew').textContent=tr('checkNewModels');
 const opt=!!(lastSnap&&lastSnap.config&&lastSnap.config.optimize);
 $('#auto').parentElement.title=opt?tr('optDisabledTitle'):'';
 if(typeof ccpRender==='function')ccpRender();
 if(typeof cxlpRender==='function')cxlpRender();  // смена языка перерисовывает баннер без запроса
 if(lastSnap){
  renderCards(lastSnap);
  setUpd(lastSnap.ts);
 }
 if(lastModel)renderModel(lastModel);
 cxRender();  // смена языка перерисовывает секцию ChatGPT из последних данных
 cxbRender(true);
 cxAll();
}
// линии из ─ шире консоли переносятся на несколько строк и рвутся: укорачиваем до числа колонок, которые помещаются (заметно на телефоне)
function termCols(box){
 const b=box||$('#termBox'),cs=getComputedStyle(b),p=document.createElement('span'),pz=b.style.getPropertyValue('--pz');
 if(pz)b.style.setProperty('--pz','1');  // в разделённой панели мерим при обычном шрифте: уменьшенный дал бы больше колонок и ещё меньший шрифт
 p.textContent='0000000000';p.style.cssText='position:absolute;visibility:hidden;white-space:pre';b.appendChild(p);
 const w=p.getBoundingClientRect().width/10;b.removeChild(p);
 const avail=b.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);
 if(pz)b.style.setProperty('--pz',pz);
 return w>0?Math.max(10,Math.floor(avail/w)-1):0;
}
function fitSep(h,box){const c=termCols(box);return c?h.replace(/([─━═])\1{9,}/g,m=>m.length>c?m[0].repeat(c):m):h;}
// вкладки консолей: первая (Claude) по умолчанию, вторая (Codex) — только когда Codex установлен
let CONS='claude';
let prodStarting=false;
// ---- панели консоли: одна панель = один экран консоли модели. Панель 0 — прежний #termBox; в режиме «разделение» (ПК)
// справа добавляются ещё панели (всего до 3), у каждой свой экран, история, плашка и опрос
const SPLIT_MAX=3;
const PANES=[{k:'claude',primary:true,seq:0,applied:0,idleKey:'',cxRun:null,prodRun:false,stick:true,dotCls:'',chipDot:null,
 box:$('#termBox'),hist:$('#termHistory'),cur:$('#termCurrent'),idle:$('#termIdle'),idleTxt:$('#termIdleTxt'),idleGo:$('#termIdleGo')}];
/*SPLIT-PURE-START*/
function splitDrop(keys,act,i,k){keys=keys.slice();const j=keys.indexOf(k);if(j>=0&&j!==i)keys[j]=keys[i];keys[i]=k;return {keys:keys,act:i};}
function splitSwap(keys,act,i,j){keys=keys.slice();if(i===j)return {keys:keys,act:act};const t=keys[i];keys[i]=keys[j];keys[j]=t;return {keys:keys,act:act===i?j:act===j?i:act};}
function splitAdd(keys,avail,k){if(keys.length>=SPLIT_MAX)return null;const n=k&&avail.includes(k)&&!keys.includes(k)?k:avail.find(x=>!keys.includes(x));return n?keys.concat(n):null;}
function splitCloseAt(keys,act,i){const ks=keys.filter((_,x)=>x!==i);let a=act>i?act-1:act;if(act===i)a=Math.min(i,ks.length-1);return {keys:ks,act:Math.max(0,Math.min(a,ks.length-1))};}
function splitPick(keys,act,k){const j=keys.indexOf(k);if(j>=0)return {keys:keys,act:j};const ks=keys.slice();ks[act]=k;return {keys:ks,act:act};}
// консоль идёт за исполнителем: новый занимает часть ПРЕЖНЕГО исполнителя (кончился аккаунт — его окно и меняется), а не ту, что выбрана рукой (владелец 62577); уже показан — выбираем его часть; прежнего нет на экране — как обычная вкладка
function splitFollow(keys,act,oldK,newK){const j=keys.indexOf(newK);if(j>=0)return {keys:keys,act:j};const i=oldK?keys.indexOf(oldK):-1;if(i<0)return splitPick(keys,act,newK);const ks=keys.slice();ks[i]=newK;return {keys:ks,act:i};}
/*SPLIT-PURE-END*/
let SPLIT={keys:[],act:0};  // keys — модели по панелям при разделении; пусто — одна панель (вкладки как раньше)
function isKey(k){return typeof k==='string'&&/^(claude|prod|codex)$/.test(k);}
try{const _sp=JSON.parse(localStorage.getItem('cc_split')||'null');if(_sp&&Array.isArray(_sp.keys))SPLIT={keys:_sp.keys.filter((k,i,a)=>isKey(k)&&a.indexOf(k)===i).slice(0,SPLIT_MAX),act:Math.max(0,+_sp.act||0)};}catch(e){}
function splitSave(){try{localStorage.setItem('cc_split',JSON.stringify(SPLIT));}catch(e){}}
const splitMq=matchMedia('(min-width:1100px) and (pointer:fine)');
// серая плашка «консоль не запущена» под последним экраном — общая для Claude, Claude на PROD и Codex:
// причина, время последнего экрана и (у PROD и Codex) кнопка запуска; пока консоль идёт, плашки нет
function idleUi(P,d,dot,txt,who,go){
 const idle=d.running===false?String(d.stopped||0):d.paused?'paused':'';  // остановлена — по времени остановки; заморожена паузой профиля — своя метка
 if(idle!==P.idleKey){P.idleKey=idle;P.hist.innerHTML='';ccConsoleHistory(P);}
 const note=P.idle,b=P.idleGo;note.hidden=!idle;
 if(!idle)return;
 dot.className='termdot idle';
 let t=txt;
 if(d.stopped){const at=new Date(d.stopped*1000).toLocaleTimeString('ru-RU',{timeZone:window.FLEET_TZ,hour:'2-digit',minute:'2-digit'});t+=' '+tr('cxcShown',who,at);}
 P.idleTxt.textContent='⏸ '+t;
 b.hidden=!go;
 if(go){b.textContent=go.label;b.disabled=!!go.disabled;b.dataset.go=go.id;}
}
try{const _ct=localStorage.getItem('cc_contab');if(_ct==='codex'||_ct==='prod')CONS=_ct;}catch(e){}
function prodAvail(){try{if(!lastSnap)return localStorage.getItem('cc_has_prod')==='1';return !!(lastSnap.remote&&Object.keys(lastSnap.remote).length)}catch(e){return false}}  // снимка ещё нет (первые секунды после обновления страницы): по запомненному cc_has_prod, иначе вкладка PROD на миг откатывается на DEV
// второй сервер не подключён — прячем всё, что с ним связано (вкладка, плашка шапки, карточка, кнопки передачи); запоминаем, чтобы страница не мигала при загрузке
function noProdSync(){const hp=prodAvail();document.documentElement.classList.toggle('no-prod',!hp);try{localStorage.setItem('cc_has_prod',hp?'1':'0')}catch(e){}}
// запомненная вкладка Codex не выбирается, пока Codex не подключён (призрачная плитка), и консоль Codex сама не стартует без входа в ChatGPT — иначе при каждой загрузке страницы «Нет входа в ChatGPT» (владелец 62657)
function baseCur(){return CONS==='prod'&&prodAvail()?'prod':CONS==='codex'&&cxAvail()&&!document.documentElement.classList.contains('ag-unlinked-codex')?'codex':'claude';}
// не подключённый Codex (призрачная плитка, html.ag-unlinked-codex) в разделение консоли не предлагается (правка владельца 62622)
function splitKeysAvail(){const R=document.documentElement.classList;return ['claude'].concat(prodAvail()?['prod']:[],cxAvail()&&!R.contains('ag-unlinked-codex')?['codex']:[]);}
// модели по панелям при разделении (только доступные); null — разделения нет (узкий экран, одна модель, не включено)
function splitEff(){
 if(!splitMq.matches)return null;
 const av=splitKeysAvail(),ks=[];
 for(const k of SPLIT.keys)if(av.includes(k)&&!ks.includes(k))ks.push(k);
 return ks.length>1?ks.slice(0,SPLIT_MAX):null;
}
function splitActIdx(ks){return Math.min(Math.max(0,SPLIT.act|0),ks.length-1);}
// выбранная консоль: при разделении — модель подсвеченной панели; иначе прежняя вкладка
function consCur(){const ks=splitEff();return ks?ks[splitActIdx(ks)]:baseCur();}
function activePane(){const ks=splitEff();return ks&&PANES[splitActIdx(ks)]||PANES[0];}
function consQuery(s,P){return s==='codex'?'&s=codex':s==='prod'?'&s=prod&cols='+termCols(P&&P.box):'';}
// значок состояния панели: у выбранной ещё и общий кружок в шапке
function dotOf(P){return {set className(v){P.dotCls=v;if(P.chipDot)P.chipDot.className=v+' tpdot';if(P===activePane())$('#termDot').className=v;}};}
async function ccConsoleHistory(P){
 P=P||PANES[0];
 const s=P.k;
 try{
  const r=await fetch(API+'console?token='+TOKEN+'&history=1'+consQuery(s,P));const d=await r.json();
  if(s!==P.k)return;  // пока шёл запрос, переключили вкладку
  if(d.ok&&d.history!=null){P.histW=P.box.clientWidth;P.hist.innerHTML=fitSep(d.history,P.box);P.box.scrollTop=P.box.scrollHeight;fitPane(P);}
 }catch(e){}
}
function cxConsSb(sb){return tr(sb==='workspace-write'?'cxcSbWrite':sb==='danger-full-access'?'cxcSbFull':'cxcSbRead');}
// «не запущена» / кнопка остановки — для вкладки Codex
let cxAutoGo=true;  // вкладка Codex сама запускает консоль (как у Claude); после остановки или ошибки — только кнопкой
let cxStarting=false;
// «Сжать контекст» и «Новая сессия» в панели консоли на вкладках Claude DEV, Claude PROD и Codex: видны всегда, сессия не запущена — нажатие вернёт понятную ошибку.
// Кнопки «Остановить консоль» нет: консоль Codex запускается сама и гасится профилем.
function ctActsSync(){const k=consCur(),show=k==='claude'||k==='prod'||k==='codex';
 $('#ctCompact').hidden=$('#ctNew').hidden=!show;
 $('#ctRedraw').hidden=k!=='claude';{const b=$('#ctRedraw');b.title=tr('redrawTitle');b.setAttribute('aria-label',tr('redrawTitle'));}
 $('#cTabs').classList.toggle('cacts',show);$('.termwrap').classList.toggle('hascacts',show);
 if(show)for(const [id,t] of [['#ctCompact',k==='codex'?'cxcCompactTip':'compactTitle'],['#ctNew',k==='codex'?'cxcNewTip':'newSessionTitle']]){const b=$(id);b.title=tr(t);b.setAttribute('aria-label',tr(t));}}
function cxConsUi(d){
 if(!d||d.ok!==true||typeof d.running!=='boolean')return;
 ctActsSync();
}
async function ccConsole(P){
 if(!P)return tickAll();
 const box=P.box,dot=dotOf(P),s=P.k,requestSeq=++P.seq;
 ctActsSync();
 try{
  const r=await fetch(API+'console?token='+TOKEN+consQuery(s,P));const d=await r.json();
  if(s!==P.k||requestSeq<P.applied)return;
  if(s==='prod'){  // Claude на сервере PROD: живой экран; остановлен — последний сохранённый экран и плашка
   P.applied=requestSeq;
   if(!d.ok){  // нет связи: экран не трогаем, плашка только объясняет
    dot.className='termdot err';P.idleKey='x';
    P.idleTxt.textContent='⏸ '+(d.message||d.error||'Нет связи с сервером PROD.');P.idleGo.hidden=true;P.idle.hidden=false;
    return;
   }
   dot.className='termdot';
   const go=d.starting||prodStarting;
   if(d.running){if(!P.prodRun){P.prodRun=true;ccConsoleHistory(P);}}else P.prodRun=false;
   idleUi(P,d,dot,go?'Запускаю Claude на PROD…':(d.idle||'Claude на PROD не запущен.')+' Запускается без Telegram. Когда работу передают на PROD, он запускается сам.','Claude на PROD',d.running?null:{id:'prod',label:'Запустить',disabled:!!go});
  }else{
   if(s==='codex'&&(d.ok!==true||typeof d.running!=='boolean')){dot.className='termdot err';return;}
   P.applied=requestSeq;
   if(s==='codex'){
    cxConsUi(d);
    if(d.running)cxAutoGo=false;  // уже работала — любая остановка дальше осознанная
    else if(cxAutoGo&&d.available!==false&&d.ok!==false&&!d.profile_paused&&ciAcc()){cxAutoGo=false;cxConsAct('start',true,P);}  // один раз за загрузку страницы; пока профиль держит Codex на паузе — не запускаем сами
    if(!d.ok){dot.className='termdot err';return;}
    dot.className='termdot';
    if(d.running){if(d.started!==P.cxRun){P.cxRun=d.started;ccConsoleHistory(P);}}  // консоль запущена (в т.ч. заново) — подтянуть прокрутку
    else P.cxRun=null;
    idleUi(P,d,dot,d.running&&d.paused?tr('cxcPaused')+(d.frozen?' '+tr('cxcFrozen'):''):tr(cxStarting?'cxcStarting':'cxcOff')+'. '+tr('cxcSub',cxConsSb(d.plan_sandbox),d.plan_cwd||'')+(d.profile_paused&&!cxStarting?' '+tr('cxcPausedOff'):''),'Codex',d.running?null:{id:'codex',label:tr('cxcStart'),disabled:cxStarting});
   }else{
    if(!d.ok||d.current==null){dot.className='termdot err';return;}
    dot.className='termdot';
    // сессии Claude нет (напр. работа на PROD): сервер отдаёт последний экран остановленной
    // сессии (не обновляется) — показываем его и плашку «почему»; при переходе туда/обратно подтягиваем прокрутку заново
    idleUi(P,d,dot,d.idle||'Claude сейчас не запущен.','Claude',null);
   }
  }
  const atBottom=box.scrollTop+box.clientHeight>=box.scrollHeight-20;
  P.cur.innerHTML=fitSep(d.current||'',box);fitPane(P);
  box.classList.toggle('termempty',!P.idle.hidden&&!P.cur.textContent.trim()&&!P.hist.textContent.trim());
  if(atBottom)box.scrollTop=box.scrollHeight;
 }catch(e){dot.className='termdot err';}
}
// Скины убраны: панель всегда в классическом оформлении (без атрибута data-skin).
// ---- масштаб шрифта консоли: процент от базового размера, запоминается в браузере ----
const TZ_STEPS=[50,60,70,80,90,100,110,125,150,175,200,250,300];
let TZ=100;
try{const _z=parseInt(localStorage.getItem('cc_termzoom'),10);if(TZ_STEPS.includes(_z))TZ=_z;}catch(e){}
function applyTz(save){
 document.documentElement.style.setProperty('--tz',TZ/100);
 $('#tzVal').textContent=TZ+'%';
 $('#tzMinus').disabled=TZ<=TZ_STEPS[0];$('#tzPlus').disabled=TZ>=TZ_STEPS[TZ_STEPS.length-1];
 if(save){try{localStorage.setItem('cc_termzoom',TZ);}catch(e){}}
 stickBottom();fitAll();
}
function tzStep(d){const i=TZ_STEPS.indexOf(TZ)+d;if(i<0||i>=TZ_STEPS.length)return;TZ=TZ_STEPS[i];applyTz(true);}
$('#tzMinus').addEventListener('click',()=>tzStep(-1));
$('#tzPlus').addEventListener('click',()=>tzStep(1));
$('#tzVal').addEventListener('click',()=>{TZ=100;applyTz(true);});
applyTz(false);
// консоль «прилипает» ко дну: пока читатель внизу, любая смена размера блока (выход из полноэкранного режима, поворот экрана) оставляет на виду последние строки
function stickBottom(){for(const P of PANES)P.box.scrollTop=P.box.scrollHeight;}
function wirePane(P){
 P.box.addEventListener('scroll',()=>{P.stick=P.box.scrollTop+P.box.clientHeight>=P.box.scrollHeight-20;},{passive:true});
 if(window.ResizeObserver)new ResizeObserver(()=>{if(P.stick)P.box.scrollTop=P.box.scrollHeight;fitPane(P);if(P.k==='prod'&&P.box.clientWidth>0&&Math.abs(P.box.clientWidth-(P.histW||0))>24)ccConsoleHistory(P);}).observe(P.box);  // PROD отдаёт историю под заданную ширину: панель стала другой — берём заново
 P.box.addEventListener('pointerdown',()=>{const i=PANES.indexOf(P);if(splitEff()&&i>=0)splitActivate(i);},true);
 dropTarget(P.box,()=>PANES.indexOf(P));
 P.idleGo.addEventListener('click',()=>paneGo(P));
}
// в узкой панели экран не ломаем переносом строк, а уменьшаем шрифт (не мельче половины), дальше — прокрутка вправо
function fitPane(P){
 const b=P.box;
 b.classList.remove('tcwrap');
 if(!b.closest('.termwrap.tsplit')){if(b.style.getPropertyValue('--pz'))b.style.removeProperty('--pz');return;}
 // Codex, Claude DEV и PROD рисуют экран шире окна части: сжимать шрифт нельзя (при тех же 100% он выходил мельче соседних, владелец 62811/62838, 63297), поэтому строки переносятся
 if(P.k==='codex'||P.k==='claude'||P.k==='prod'){b.classList.add('tcwrap');if(b.style.getPropertyValue('--pz'))b.style.removeProperty('--pz');return;}
 // подгонку по ширине меряем при масштабе 100% (--tz=1 на самой части): иначе шрифт, выросший от «+», тут же сжимался обратно, и у частей с длинными строками масштаб не менялся, а у остальных менялся (владелец 62676)
 b.style.setProperty('--tz','1');b.style.setProperty('--pz','1');
 const cs=getComputedStyle(b),pad=parseFloat(cs.paddingLeft)+parseFloat(cs.paddingRight),avail=b.clientWidth-pad,need=b.scrollWidth-pad;
 b.style.removeProperty('--tz');
 const f=need>avail+1&&avail>0?Math.max(.5,avail/need):1;
 b.style.setProperty('--pz',f.toFixed(3));
}
function fitAll(){for(const P of PANES)fitPane(P);}
addEventListener('resize',fitAll);

// ---- режим «только консоль»: виден лишь терминал; у нижнего края — панель аккаунтов по наведению ----
function setConly(on,save){
 document.documentElement.classList.toggle('conly',on);
 const b=$('#fsBtn');b.title=tr(on?'fsExitTitle':'fsTitle');b.setAttribute('aria-label',b.title);
 if(save){try{localStorage.setItem('cc_conly',on?'1':'0');}catch(e){}}
 $('#dockZone').classList.remove('pin');
 try{if(!on&&document.fullscreenElement)document.exitFullscreen().catch(()=>{});}catch(e){}
 PANES.forEach(P=>{P.stick=true});stickBottom();
 requestAnimationFrame(stickBottom);
 setTimeout(stickBottom,350);
}
function conlyToggle(){
 const on=!document.documentElement.classList.contains('conly');
 setConly(on,true);
 try{if(on&&document.documentElement.requestFullscreen)document.documentElement.requestFullscreen().catch(()=>{});}catch(e){}
}
$('#fsBtn').addEventListener('click',conlyToggle);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.documentElement.classList.contains('conly')){e.preventDefault();setConly(false,true);}});
// Esc в полноэкранном режиме браузера закрывает его сам — вместе с ним выходим и из режима
document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement&&document.documentElement.classList.contains('conly'))setConly(false,true);});
// на сенсорных экранах панель открывается касанием язычка
$('#dockTab').addEventListener('click',()=>$('#dockZone').classList.toggle('pin'));
document.addEventListener('click',e=>{if(!e.target.closest('#dockZone'))$('#dockZone').classList.remove('pin');});
function renderDock(d){
 const el=$('#dockPanel');if(!el)return;
 const met=(lbl,o)=>{const p=o&&o.pct;return `<span class="dmet"><span class="dtop"><span class="dml">${lbl}</span><b style="color:${col(p)}">${p==null?'?':p+'%'}</b></span><span class="bar dbar"><span class="fill" data-t="${tone(p)}" style="width:${p||0}%"></span></span></span>`};
 el.innerHTML=Object.entries(d.accounts).map(([n,a])=>{
  const plan=a.plan==='free'?'<span class="tag free">FREE</span>':a.plan?'<span class="tag plan">'+a.plan.toUpperCase()+'</span>':'';
  const err=a.error?`<div class="err">⚠ ${a.error}</div>`:'';
  const det=a.five_hour&&!a.lapsed?bar(tr('session5'),a.five_hour)+bar(tr('week'),a.seven_day):'';
  const lpd=a.lapsed?'<span class="tag lpt">'+tr('lapsedTag')+'</span>':'';
  return `<div class="dchip${a.active?' act':''}${a.error?' er':''}${a.lapsed?' lapsed':''}"><span class="ddot"></span><span class="dmail">${a.email}</span>`
   +(a.five_hour&&!a.lapsed?met(tr('dockSes'),a.five_hour)+met(tr('dockWeek'),a.seven_day):'')
   +`<div class="dpop"><div class="dpt"><span class="dpe">${a.email}</span>${plan}${lpd}${a.active?'<span class="dpa">'+tr('active')+'</span>':''}</div>${err}${det}</div></div>`;
 }).join('');
}
// подсказка аккаунта не должна вылезать за края окна
$('#dockPanel').addEventListener('mouseover',e=>{
 const c=e.target.closest('.dchip');if(!c)return;
 const p=c.querySelector('.dpop'),r=c.getBoundingClientRect(),w=Math.min(350,innerWidth*.92);
 p.style.left=(Math.max(8,Math.min(r.left+r.width/2-w/2,innerWidth-w-8))-r.left)+'px';
});
setConly(document.documentElement.classList.contains('conly'),false);
document.addEventListener('keydown',e=>{
 if(e.key!=='Escape')return;
 if(!$('#acctScrim').hidden){acctClose();return;}
 if(!$('#scrim').hidden){$('#scrim').hidden=true;return;}
});
document.documentElement.removeAttribute('data-skin');{const box=$('#termBox');box.scrollTop=box.scrollHeight;}
function consTabs(){
 const av=cxAvail(),pv=prodAvail(),cur=consCur(),ks=splitEff()||[];
 $('#cTabs').hidden=!(av||pv);$('.termwrap').classList.toggle('hastabs',av||pv);$('#ctProd').hidden=!pv;$('#ctCodex').hidden=!av;  // Codex недоступен — его вкладки нет
 [['claude','#ctClaude'],['prod','#ctProd'],['codex','#ctCodex']].forEach(([k,id])=>{
  const b=$(id),on=k===cur;
  b.classList.toggle('on',on);b.classList.toggle('tshown',!on&&ks.includes(k));b.setAttribute('aria-selected',on);
  b.title=on?'':tr('cxcSw')+b.textContent;
  b.draggable=splitMq.matches&&(av||pv);
 });
 splitBtnSync();
 ctActsSync();  // подсказки кнопок — по текущей вкладке (раньше здесь жёстко стояли подсказки Codex)
 syncPanes();
}
function consPick(k){
 const ks=splitEff();
 if(ks){const r=splitPick(ks,splitActIdx(ks),k);SPLIT={keys:r.keys,act:r.act};splitSave();}
 CONS=k;try{localStorage.setItem('cc_contab',k);}catch(e){}
 consTabs();
}
$('#cTabs').addEventListener('click',e=>{const b=e.target.closest('.ctab');if(!b)return;const k=tabKey(b);if(isKey(k)&&k!==consCur())consPick(k);});
// ---- разделение: панели, заголовки, перетаскивание
function tabKey(b){return b.dataset.s;}
function tabName(k){const b=[...document.querySelectorAll('#cTabs .ctab')].find(x=>tabKey(x)===k);return b?b.textContent.trim():k;}
function resetPane(P,k){
 P.k=k;P.cxRun=null;P.prodRun=false;P.idleKey='';P.stick=true;P.dotCls='';
 P.hist.innerHTML='';P.cur.innerHTML='';P.idle.hidden=true;P.box.classList.remove('termempty');
 ccConsoleHistory(P);ccConsole(P);
}
function newPane(){
 const box=document.createElement('pre');box.className='termbox tpextra';
 box.innerHTML='<span class="tph"></span>\n<span class="tpc"></span><div class="termidle" hidden><span></span><button type="button" hidden></button></div>';
 const P={k:null,primary:false,seq:0,applied:0,idleKey:'',cxRun:null,prodRun:false,stick:true,dotCls:'',chipDot:null,box:box,hist:box.children[0],cur:box.children[1],idle:box.children[2],idleTxt:box.children[2].children[0],idleGo:box.children[2].children[1]};
 return P;
}
// ---- у каждой части своё окно ввода: форма как у общего окна (cc_overview.py), отправка — его же код (window.fleetBindComposer)
const DRAFTS={};  // черновик по модели: переставили части местами — текст ушёл вместе с моделью
function compMake(P){
 const w=document.createElement('div');w.className='tpcw';
 w.innerHTML='<form class="tpcomp"><textarea rows="1"></textarea><button type="button" class="tpkey" data-console-key="up">↑</button><button type="button" class="tpkey" data-console-key="down">↓</button><button type="button" class="tpkey" data-console-key="enter">⏎</button><button type="button" class="tpkey" data-console-key="escape">Esc</button><button type="submit" class="tpsend"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/></svg></button></form>';
 const form=w.children[0],input=form.children[0],send=form.querySelector('.tpsend'),stat=document.createElement('span');  // строки «Ввод в …» у части нет: статус отправки пишется в невидимый узел, ошибки показывает toast
 P.comp={w:w,form:form,input:input,send:send,stat:stat,model:null};
 input.addEventListener('input',()=>{DRAFTS[P.k]=input.value;});
 w.addEventListener('pointerdown',()=>{const i=PANES.indexOf(P);if(splitEff()&&i>=0)splitActivate(i);},true);
 window.fleetBindComposer(form,input,send,stat,()=>P.k);
 return w;
}
function compSync(P,on){
 const c=P.comp;if(!c)return;
 const n=tabName(P.k);
 c.w.classList.toggle('on',on);
 if(c.model!==P.k){
  c.model=P.k;c.input.value=DRAFTS[P.k]||'';
  c.input.placeholder=(LANG==='en'?'Message to ':'Сообщение в ')+n+'…';c.input.setAttribute('aria-label',c.input.placeholder);
  c.send.title=LANG==='en'?'Send':'Отправить';c.form.querySelectorAll('.tpkey').forEach(b=>{const k=b.dataset.consoleKey;b.title=LANG==='en'?({up:'Arrow up',down:'Arrow down',enter:'Enter (select)',escape:'Esc'}[k]+' to console'):({up:'Стрелка вверх в консоль',down:'Стрелка вниз в консоль',enter:'Enter в консоль (выбрать пункт)',escape:'Esc в консоль'}[k]);b.setAttribute('aria-label',b.title);});
 }
}
function placeFrame(ks){
 const wrap=document.querySelector('.termwrap');
 let fr=[...wrap.querySelectorAll(':scope > .tpfr')];
 if(!ks){fr.forEach(f=>f.remove());return;}
 if(!wrap.dataset.tpro&&window.ResizeObserver){wrap.dataset.tpro='1';new ResizeObserver(()=>placeFrame(splitEff())).observe(wrap);}
 while(fr.length<PANES.length){const f=document.createElement('div');f.className='tpfr';wrap.appendChild(f);fr.push(f);}
 while(fr.length>PANES.length)fr.pop().remove();
 // по рамке на часть вокруг шапки (у верхнего края консоли), экрана и окна ввода; у выбранной цвет другой. Размеры дробные, без округления:
 // иначе правый край уходит на пиксель под рамку блока и обрезается; нижние углы повторяют скругление блока там, где часть к нему примыкает.
 // Соседние рамки перекрываются на 1px — между частями одна линия, а не две
 const w=wrap.getBoundingClientRect(),act=splitActIdx(splitEff()||[0]),rad=Math.max(0,(parseFloat(getComputedStyle(wrap).borderBottomLeftRadius)||0)-(wrap.clientLeft||0));
 const mx=wrap.classList.contains('tpmax');
 PANES.forEach((P,i)=>{
  const f=fr[i];
  f.style.display=P.hid?'none':'';if(P.hid)return;
  const b=P.box.getBoundingClientRect(),bottom=P.comp?P.comp.w.getBoundingClientRect().bottom:b.bottom,lap=i>0&&!mx?1:0;
  f.style.left=(b.left-w.left-wrap.clientLeft-lap).toFixed(2)+'px';f.style.top=(b.top-w.top-wrap.clientTop).toFixed(2)+'px';
  f.style.width=(b.width+lap).toFixed(2)+'px';f.style.height=(bottom-b.top).toFixed(2)+'px';
  f.style.borderBottomLeftRadius=i===0||mx?rad+'px':'0';f.style.borderBottomRightRadius=i===PANES.length-1||mx?rad+'px':'0';
  f.classList.toggle('on',i===act);
 });
}
addEventListener('resize',()=>placeFrame(splitEff()));
function renderComps(ks){
 const wrap=document.querySelector('.termwrap'),shared=document.getElementById('fleetConsoleForm');
 let row=document.getElementById('tpComps');
 if(!ks||!shared||typeof window.fleetBindComposer!=='function'){if(row)row.remove();wrap.classList.remove('tpcomps-on');PANES.forEach(P=>{P.comp=null});return;}
 if(!row){row=document.createElement('div');row.id='tpComps';row.className='tpcomps';shared.before(row);}
 wrap.classList.add('tpcomps-on');
 const act=splitActIdx(ks);
 PANES.forEach((P,i)=>{if(!P.comp)row.appendChild(compMake(P));compSync(P,i===act);});
}
function syncPanes(){
 const ks=splitEff(),keys=ks||[baseCur()],vp=PANES[0].box.parentNode;
 if(!ks)MAXED=false;
 $('.termwrap').classList.toggle('tsplit',!!ks);
 if(ks)CONS=ks[splitActIdx(ks)];
 while(PANES.length<keys.length){const P=newPane();vp.appendChild(P.box);PANES.push(P);wirePane(P);}
 while(PANES.length>keys.length){const P=PANES.pop();P.box.remove();if(P.comp){P.comp.w.remove();P.comp=null;}}
 PANES.forEach((P,i)=>{if(P.k!==keys[i])resetPane(P,keys[i]);});
 const act=ks?splitActIdx(ks):-1;
 PANES.forEach((P,i)=>P.box.classList.toggle('tpact',i===act));
 if(ks&&PANES[act]&&PANES[act].dotCls)$('#termDot').className=PANES[act].dotCls;
 renderHeads(ks);
 renderComps(ks);
 applyMax(ks);
 placeFrame(ks);
 if(ks)fitAll();
}
// ---- выпадающее меню моделей в шапке части: выбрать модель для этой части сразу, без перетаскивания
function closeModelMenu(){const m=document.getElementById('tpMenu');if(m)m.remove();document.removeEventListener('pointerdown',menuOutside,true);document.removeEventListener('keydown',menuKey,true);removeEventListener('resize',closeModelMenu);}
function menuOutside(e){const m=document.getElementById('tpMenu');if(m&&!m.contains(e.target)&&!(e.target.closest&&e.target.closest('.tphd')))closeModelMenu();}
function menuKey(e){if(e.key==='Escape'){e.stopPropagation();closeModelMenu();}}
function openModelMenu(i){
 closeModelMenu();
 const ks=splitEff();if(!ks||i<0||i>=ks.length)return;
 const chip=document.querySelector('#tpHeads .tphd[data-i="'+i+'"]');if(!chip)return;
 const m=document.createElement('div');m.id='tpMenu';m.className='tpmenu';m.dataset.i=i;m.setAttribute('role','menu');
 m.innerHTML='<div class="tpmt">'+(LANG==='en'?'Model in this part':'Модель в этой части')+'</div>'+splitKeysAvail().map(k=>{
  const j=ks.indexOf(k),cur=j===i;
  return '<button type="button" role="menuitem" class="tpmi'+(cur?' cur':'')+'" data-k="'+acctEsc(k)+'"><span class="tpmd" data-m="'+k+'"></span><span class="tpmn">'+acctEsc(tabName(k))+'</span>'
   +(j>=0&&!cur?'<span class="tpmw">'+(LANG==='en'?'part ':'часть ')+(j+1)+'</span>':'')+(cur?'<span class="tpmc">✓</span>':'')+'</button>';}).join('');
 document.body.appendChild(m);
 const r=chip.getBoundingClientRect();m.style.left=Math.max(8,Math.min(r.left,innerWidth-m.offsetWidth-8))+'px';m.style.top=(r.bottom+4)+'px';
 m.addEventListener('click',e=>{const b=e.target.closest('.tpmi');if(!b)return;const k=b.dataset.k;closeModelMenu();pickPartModel(i,k);});
 document.addEventListener('pointerdown',menuOutside,true);document.addEventListener('keydown',menuKey,true);addEventListener('resize',closeModelMenu);
 const f=m.querySelector('.tpmi.cur')||m.querySelector('.tpmi');if(f)f.focus({preventScroll:true});
}
// выбрана модель для части i: показана в другой части — части меняются местами (как при перетаскивании), иначе заменяется
function pickPartModel(i,k){const ks=splitEff();if(!ks||!isKey(k))return;if(ks[i]===k){splitActivate(i);return;}splitCommit(splitDrop(ks,splitActIdx(ks),i,k),k);}
const ACT_SVG={compact:'<path d="M9 4v4a1 1 0 0 1-1 1H4M15 4v4a1 1 0 0 0 1 1h4M9 20v-4a1 1 0 0 0-1-1H4M15 20v-4a1 1 0 0 1 1-1h4"/>',new:'<path d="M3 12a9 9 0 1 1 3 6.7"/><path d="M3 16v-4h4"/>'};
// «Сжать контекст» и «Новая сессия» у каждой части с консолью (Claude DEV, Claude PROD, Codex) — справа от названия модели
function partActs(k,i){
 if(!(k==='claude'||k==='prod'||k==='codex'))return '';
 const tip=c=>tr(c==='compact'?(k==='codex'?'cxcCompactTip':'compactTitle'):(k==='codex'?'cxcNewTip':'newSessionTitle'));
 return '<span class="tpacts">'+['compact','new'].map(c=>'<button type="button" class="tpab" data-cmd="'+c+'" data-i="'+i+'" title="'+acctEsc(tip(c))+'" aria-label="'+acctEsc(tip(c))+'"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+ACT_SVG[c]+'</svg></button>').join('')+'</span>';
}
function splitPartCmd(i,cmd,btn){const ks=splitEff();if(!ks||i<0||i>=ks.length)return;splitActivate(i);consActCmd(cmd,btn);}
function fsTip(on){return LANG==='en'?(on?'Show the other consoles':'Expand this console to the full block'):(on?'Вернуть остальные консоли':'Развернуть эту консоль на весь блок');}
function renderHeads(ks){
 const vp=PANES[0].box.parentNode;let h=document.getElementById('tpHeads');
 if(!ks){if(h)h.remove();PANES.forEach(P=>{P.chipDot=null});return;}
 if(!h){
  h=document.createElement('div');h.id='tpHeads';h.className='tpheads';vp.appendChild(h);
  h.addEventListener('click',e=>{const x=e.target.closest('[data-x]');if(x){splitClose(+x.dataset.x);return;}const fs=e.target.closest('[data-fs]');if(fs){splitMaxToggle(+fs.dataset.fs);return;}const ab=e.target.closest('[data-cmd]');if(ab){splitPartCmd(+ab.dataset.i,ab.dataset.cmd,ab);return;}const c=e.target.closest('.tphd');if(c){const i=+c.dataset.i,m=document.getElementById('tpMenu');if(m&&+m.dataset.i===i){closeModelMenu();return;}splitActivate(i);openModelMenu(i);}});
  h.addEventListener('dragstart',e=>{const c=e.target.closest('.tphd');if(!c)return;DRAG={t:'pane',v:+c.dataset.i};try{e.dataTransfer.setData('text/plain','pane:'+c.dataset.i);e.dataTransfer.effectAllowed='move';}catch(x){}dragBegin();});
  h.addEventListener('dragend',dragEnd);
  dropTarget(h,e=>{const c=e.target.closest('.tphd');return c?+c.dataset.i:-1;});
 }
 const act=splitActIdx(ks),sig=ks.join()+'|'+act+'|'+MAXED+'|'+LANG+'|'+ks.map(tabName).join();
 if(h.dataset.sig===sig)return;
 h.dataset.sig=sig;
 h.innerHTML=ks.map((k,i)=>'<div class="tphd'+(i===act?' on':'')+'" data-i="'+i+'" draggable="true" title="'+(LANG==='en'?'Drag onto another part to swap':'Перетащи на другую часть, чтобы поменять местами')+'"><span class="termdot tpdot" data-i="'+i+'"></span><b>'+tabName(k)+'</b><span class="tpcaret" aria-hidden="true">▾</span>'+partActs(k,i)+'<button type="button" class="tpfs'+(MAXED&&i===act?' on':'')+'" data-fs="'+i+'" title="'+fsTip(MAXED&&i===act)+'" aria-label="'+fsTip(MAXED&&i===act)+'"><svg class="tpfsi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg><svg class="tpfsx" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg></button><button type="button" class="tpx" data-x="'+i+'" title="'+(LANG==='en'?'Close this part':'Закрыть часть')+'" aria-label="'+(LANG==='en'?'Close this part':'Закрыть часть')+'">×</button></div>').join('');
 PANES.forEach((P,i)=>{P.chipDot=h.querySelector('.tpdot[data-i="'+i+'"]');if(P.chipDot&&P.dotCls)P.chipDot.className=P.dotCls+' tpdot';});
}
// «на весь экран» у части: выбранная часть занимает всю консоль на месте, остальные спрятаны (не закрыты); выбор другой модели сверху/в меню ведёт развёрнутое окно за выбранной частью
let MAXED=false;
function applyMax(ks){
 const wrap=document.querySelector('.termwrap'),mi=MAXED&&ks?splitActIdx(ks):-1;
 wrap.classList.toggle('tpmax',mi>=0);
 PANES.forEach((P,i)=>{const h=mi>=0&&i!==mi;P.hid=h;P.box.classList.toggle('tphide',h);if(P.comp)P.comp.w.classList.toggle('tphide',h);});
 document.querySelectorAll('#tpHeads .tphd').forEach((c,i)=>c.classList.toggle('tphide',mi>=0&&i!==mi));
}
function splitMaxToggle(i){
 const ks=splitEff();if(!ks||i<0||i>=ks.length)return;
 if(MAXED&&i===splitActIdx(ks))MAXED=false;else{splitActivate(i);MAXED=true;}
 tickAll();
}
let DRAG=null;
function dragBegin(){
 const ks=splitEff();
 if(DRAG&&DRAG.t==='tab'&&splitMq.matches&&(!ks||(ks.length<SPLIT_MAX&&!ks.includes(DRAG.v)))){
  const z=ensureAddZone(),a=PANES[0].box.getBoundingClientRect(),c=PANES[PANES.length-1].box.getBoundingClientRect();
  let w=Math.round((c.right-a.left)*.34);if(ks)w=Math.min(w,170);  // при разделении — узкая полоса у правого края, остальное остаётся под замену частей
  z.style.left=Math.round(c.right-w)+'px';z.style.top=Math.round(a.top+30)+'px';z.style.width=w+'px';z.style.height=Math.max(60,Math.round(a.height-30))+'px';
  document.body.classList.add('tpdraging');
 }
}
function dragEnd(){DRAG=null;document.body.classList.remove('tpdraging');document.querySelectorAll('.tpdrop').forEach(e=>e.classList.remove('tpdrop'));}
function ensureAddZone(){
 let z=document.getElementById('tpAdd');
 if(z)return z;
 z=document.createElement('div');z.id='tpAdd';z.className='tpadd';document.body.appendChild(z);
 z.textContent=LANG==='en'?'Drop here to open on the right':'Отпусти, чтобы открыть справа';
 z.addEventListener('dragover',e=>{if(DRAG&&DRAG.t==='tab'){e.preventDefault();z.classList.add('tpdrop');}});
 z.addEventListener('dragleave',()=>z.classList.remove('tpdrop'));
 z.addEventListener('drop',e=>{e.preventDefault();const d=DRAG;dragEnd();if(d&&d.t==='tab')splitAddDrop(d.v);});
 return z;
}
function dropTarget(el,idxOf){
 el.addEventListener('dragover',e=>{const i=idxOf(e);if(i<0||!DRAG||!splitEff())return;e.preventDefault();try{e.dataTransfer.dropEffect='move';}catch(x){}
  document.querySelectorAll('.tpdrop').forEach(n=>n.classList.remove('tpdrop'));
  if(PANES[i])PANES[i].box.classList.add('tpdrop');const c=document.querySelector('#tpHeads .tphd[data-i="'+i+'"]');if(c)c.classList.add('tpdrop');});
 el.addEventListener('dragleave',e=>{if(e.relatedTarget&&el.contains(e.relatedTarget))return;document.querySelectorAll('.tpdrop').forEach(n=>n.classList.remove('tpdrop'));});
 el.addEventListener('drop',e=>{const i=idxOf(e);if(i<0||!DRAG||!splitEff())return;e.preventDefault();const d=DRAG;dragEnd();splitDropOn(i,d);});
}
function splitCommit(r,cur){SPLIT={keys:r.keys,act:r.act};splitSave();CONS=cur||SPLIT.keys[SPLIT.act];try{localStorage.setItem('cc_contab',CONS);}catch(e){}consTabs();}
function splitDropOn(i,d){
 const ks=splitEff();if(!ks)return;
 if(d.t==='tab'){const r=splitDrop(ks,splitActIdx(ks),i,d.v);splitCommit(r,d.v);}
 else if(d.t==='pane'){const r=splitSwap(ks,splitActIdx(ks),d.v,i);splitCommit(r);}
}
function splitAddDrop(k){
 const av=splitKeysAvail(),ks=splitEff()||[consCur()],nk=splitAdd(ks,av,k);
 if(!nk)return;
 MAXED=false;
 splitCommit({keys:nk,act:nk.length-1},k);
}
function splitActivate(i){const ks=splitEff();if(!ks||i===splitActIdx(ks)||i<0||i>=ks.length)return;splitCommit({keys:ks,act:i});}
function splitClose(i){
 const ks=splitEff();if(!ks)return;
 MAXED=false;
 const r=splitCloseAt(ks,splitActIdx(ks),i);
 if(r.keys.length<2){SPLIT={keys:[],act:0};splitSave();CONS=r.keys[0]||'claude';try{localStorage.setItem('cc_contab',CONS);}catch(e){}consTabs();return;}
 splitCommit(r);
}
// кнопка в блоке масштаба: 1 → 2 → 3 части → обратно в одну (3-й нет, если моделей меньше)
function splitToggle(){
 const av=splitKeysAvail();if(av.length<2||!splitMq.matches)return;
 MAXED=false;
 const ks=splitEff();
 if(!ks){const nk=splitAdd([consCur()],av,null);if(nk)splitCommit({keys:nk,act:0},consCur());return;}
 const nk=splitAdd(ks,av,null);
 if(nk){splitCommit({keys:nk,act:splitActIdx(ks)});return;}
 const cur=ks[splitActIdx(ks)];SPLIT={keys:[],act:0};splitSave();CONS=cur;try{localStorage.setItem('cc_contab',CONS);}catch(e){}consTabs();
}
function splitBtnSync(){
 const b=document.getElementById('splitBtn');if(!b)return;
 const ok=splitMq.matches&&splitKeysAvail().length>1,ks=splitEff();
 b.hidden=!ok;
 const more=ks?(ks.length<Math.min(SPLIT_MAX,splitKeysAvail().length)):true;
 const t=LANG==='en'?(ks?(more?'Add a part':'Back to one console'):'Split console'):(ks?(more?'Добавить часть':'Вернуть одну консоль'):'Разделить консоль');
 b.title=t;b.setAttribute('aria-label',t);b.classList.toggle('on',!!ks);
}
document.getElementById('splitBtn').addEventListener('click',splitToggle);
$('#cTabs').addEventListener('dragstart',e=>{const b=e.target.closest&&e.target.closest('.ctab');if(!b)return;const k=tabKey(b);if(!isKey(k)||!splitMq.matches||!splitKeysAvail().includes(k)){e.preventDefault();return;}DRAG={t:'tab',v:k};try{e.dataTransfer.setData('text/plain','tab:'+k);e.dataTransfer.effectAllowed='move';}catch(x){}dragBegin();});
$('#cTabs').addEventListener('dragend',dragEnd);
splitMq.addEventListener('change',()=>{consTabs();fitAll();});
function tickAll(){syncPanes();document.querySelectorAll('#cTabs .ctab').forEach(b=>{const d=splitMq.matches&&isKey(tabKey(b))&&splitKeysAvail().includes(tabKey(b));if(b.draggable!==d)b.draggable=d;});for(const P of PANES)if(!P.hid&&!document.hidden)ccConsole(P);}
// фоновая вкладка консоль не опрашивает (её запрос с другой шириной менял экран общего tmux); вернулись на вкладку — экран обновляется сразу, не через 2 с
document.addEventListener('visibilitychange',()=>{if(!document.hidden)tickAll();});
window.fleetSplitOn=function(){try{return !!splitEff()}catch(e){return false}};
window.fleetSplitWanted=function(){return splitMq.matches&&SPLIT.keys.length>1};
window.fleetSplitShow=function(k){if(isKey(k))consPick(k);};
// консоль идёт за исполнителем: панель знает, кто сейчас работает (remote_mode.worker: dev/prod/codex).
// Сменился — вкладка консоли переключается сама. Пока исполнитель тот же, ручной выбор вкладки не трогаем.
let consFollowed='',consFollowWait=0;
// сохранённая раскладка ещё не собралась: модели частей приходят в панель позже страницы — следом за исполнителем идём, когда она готова
function splitPending(){const av=splitKeysAvail();return splitMq.matches&&SPLIT.keys.length>1&&SPLIT.keys.some(k=>!av.includes(k));}
function consFollow(d){
 try{
  const w=d&&d.remote_mode&&d.remote_mode.worker;if(!w)return;
  let seen=consFollowed;if(!seen){try{seen=localStorage.getItem('cc_conworker')||'';}catch(e){}}
  if(seen===w)return;
  const b=document.getElementById({prod:'ctProd',codex:'ctCodex'}[w]||'ctClaude');
  if(!b||(w==='prod'&&!prodAvail())||(w==='codex'&&!cxAvail())||splitPending()){
   // страница только открылась: данные Codex и PROD приходят чуть позже — ждём до 30 с, потом отстаём до следующего опроса
   const t=Date.now();if(!consFollowWait||t-consFollowWait>30000)consFollowWait=t;
   if(t-consFollowWait<30000)setTimeout(()=>consFollow(lastSnap),700);
   return;
  }
  consFollowed=w;try{localStorage.setItem('cc_conworker',w);}catch(e){}  // запоминаем до клика: сам клик зовёт consTabs
  // разделённая консоль: окно нового исполнителя встаёт на место окна прежнего, выбранная рукой часть остаётся (владелец 62577)
  const ks=splitEff();
  if(ks&&splitKeysAvail().includes(tabKey(b))){const ob=seen?document.getElementById({prod:'ctProd',codex:'ctCodex'}[seen]||'ctClaude'):null;splitCommit(splitFollow(ks,splitActIdx(ks),ob?tabKey(ob):'',tabKey(b)),tabKey(b));return;}
  b.click();  // обычный клик: обработчик вкладки зовёт consPick
 }catch(e){}
}
async function cxConsAct(path,quiet,P){
 P=P||PANES[0];
 const g=P.idleGo;g.disabled=true;
 cxStarting=path==='start';if(cxStarting&&!P.idle.hidden)P.idleTxt.textContent='⏸ '+tr('cxcStarting');
 try{
  const r=await acctPost('chatgpt/console/'+path,{});
  if(!(r.ok&&quiet))toast(r.ok?r.message:'⚠ '+r.message);
  P.cxRun=null;cxConsUi(r);
  P.hist.innerHTML='';P.cur.innerHTML='';
  await ccConsole(P);ccConsoleHistory(P);
 }catch(e){toast('⚠ '+e);}
 cxStarting=false;g.disabled=false;
}
async function prodStart(P){
 P=P||PANES[0];
 prodStarting=true;P.idleTxt.textContent='⏸ Запускаю Claude на PROD…';P.idleGo.disabled=true;
 try{const r=await fetch(API+'remote/console/start',{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':TOKEN},body:'{}'});const j=await r.json();if(!j.ok)toast('⚠ '+(j.message||'Не запустилось'));}
 catch(e){toast('⚠ Панель не ответила');}
 prodStarting=false;ccConsole(P);
}
// одна кнопка в плашке: что она запускает, решает вкладка (ставит idleUi)
async function paneGo(P){const b=P.idleGo,w=b.dataset.go;if(w!=='codex'&&w!=='prod')return;if(!await window.fleetAsk(b,tr(w==='codex'?'askStartCx':'askStartProd'),tr('askYes')))return;if(w==='codex')cxConsAct('start',false,P);else prodStart(P);}
wirePane(PANES[0]);
async function cxConsCmd(cmd,anchor){  // «Сжать контекст» / «Новая сессия» вкладки Codex
 if(cmd==='compact'&&!await window.fleetAsk(anchor||$('#ctCompact'),tr('askCxCompact'),tr('askYes')))return;
 if(cmd==='new'&&!confirm(tr('cxcNewQ')))return;
 const bs=[$('#ctCompact'),$('#ctNew')];bs.forEach(b=>b.disabled=true);
 try{
  const r=await acctPost('chatgpt/console/cmd',{cmd});
  toast(r.ok?'✅ '+r.message:'⚠ '+r.message);
  if(cmd==='new'&&r.ok){const P=activePane();P.cxRun=null;cxConsUi(r);P.hist.innerHTML='';P.cur.innerHTML='';await ccConsole(P);ccConsoleHistory(P);}
 }catch(e){toast('⚠ '+e);}
 bs.forEach(b=>b.disabled=false);
}
async function prodSessionCmd(cmd,anchor){  // «Сжать контекст» / «Новая сессия» вкладки Claude PROD: команда вводится в консоль PROD, как её набрал бы человек
 const b=anchor||$(cmd==='compact'?'#ctCompact':'#ctNew');
 if(cmd==='compact'&&!await window.fleetAsk(b,tr('askProdCompact'),tr('askYes')))return;
 if(cmd==='new'&&!confirm(tr('confirmNewProd')))return;
 try{
  const r=await fetch(API+'console/input?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session:'prod',text:cmd==='compact'?'/compact':'/clear'})});
  const d=await r.json();toast(d.ok?'✅ '+d.message:'⚠ '+(d.message||''));
 }catch(e){toast('⚠ '+e)}
}
function consActCmd(cmd,anchor){const s=consCur();return s==='codex'?cxConsCmd(cmd,anchor):s==='prod'?prodSessionCmd(cmd,anchor):sessionCmd(cmd,anchor||$(cmd==='compact'?'#ctCompact':'#ctNew'));}
$('#ctCompact').addEventListener('click',()=>consActCmd('compact'));
$('#ctNew').addEventListener('click',()=>consActCmd('new'));
async function consRedraw(){  // «Перерисовать консоль» (только Claude DEV): ресайз pty окна сессии на сервере, полный кадр придёт в консоль сам
 const b=$('#ctRedraw');b.disabled=true;
 try{
  const r=await fetch(API+'session?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'redraw',lang:LANG})});
  const d=await r.json();toast(d.ok?'✅ '+d.message:'⚠ '+(d.message||''));
 }catch(e){toast('⚠ '+e)}
 b.disabled=false;
}
$('#ctRedraw').addEventListener('click',consRedraw);
setTimeout(()=>{consTabs();ccConsoleHistory();tickAll();},0);setInterval(tickAll,2000);  // после загрузки скрипта: consCur() читает cxData, объявленный ниже
function col(p){return p==null?'#555':p<60?'var(--ok)':p<85?'var(--warn)':'var(--bad)'}
function tone(p){return p==null?'na':p<60?'ok':p<85?'warn':'bad'}
function rst(iso){if(!iso)return'';const d=new Date(iso),m=Math.max(0,Math.round((d-Date.now())/60000));
 const h=Math.floor(m/60),mm=m%60;return tr('resetIn',h,mm,d.toLocaleTimeString(LANG==='en'?'en-GB':'ru',{hour:'2-digit',minute:'2-digit'}))}
function bar(lbl,o){o=o||{};const p=o.pct;return`<div class="row"><div class="lbl"><span>${lbl}: <b style="color:${col(p)}">${p==null?'?':p+'%'}</b></span><span>${rst(o.resets_at)}</span></div>
 <div class="bar"><div class="fill" data-t="${tone(p)}" style="width:${p||0}%"></div></div></div>`}
function renewChip(iso){if(!iso)return'';const d=new Date(iso),ms=d-Date.now();
 const title=tr('renewalIn',Math.max(0,Math.floor(ms/86400000)),Math.max(0,Math.floor((ms%86400000)/3600000)));
 if(ms<=0)return`<span class="chip urgent" title="${tr('renewalSoon')}">${tr('renewalChipToday')}</span>`;
 const days=Math.floor(ms/86400000);
 return`<span class="chip${days<3?' urgent':''}" title="${title}">${tr('renewalChip',days)}</span>`}
function loginChip(iso){if(!iso)return'';const d=new Date(iso),ms=d-Date.now();
 const when=d.toLocaleString(LANG==='en'?'en-GB':'ru',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
 if(ms<=0)return`<span class="chip login urgent" title="${tr('loginHintGone',when)}"><svg class="lgi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z"/><path d="M9 12l2 2 4-4"/></svg><b>${tr('loginGone')}</b></span>`;
 const days=Math.floor(ms/86400000);
 const cls=days<=3?' urgent':days<=7?' warn':'';
 const left=days>=1?tr('loginD',days):tr('loginH',Math.max(1,Math.floor(ms/3600000)));
 return`<span class="chip login${cls}" title="${tr('loginHint',when)}"><svg class="lgi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z"/><path d="M9 12l2 2 4-4"/></svg><b>${left}</b></span>`}
function urgCol(f){return f>.5?'var(--bad)':f>.2?'var(--warn)':'var(--ok)'}
function frac(iso,windowSec){if(!iso)return 0;const remain=(new Date(iso)-Date.now())/1000;return Math.max(0,Math.min(1,remain/windowSec))}
function ring(o,windowSec,size){o=o||{};size=size||34;const sw=Math.max(3,Math.round(size*.1));const rad=size/2-sw/2;const circ=2*Math.PI*rad;const f=frac(o.resets_at,windowSec);const uc=urgCol(f);const dash=(f*circ).toFixed(1);const c=size/2;
 return `<div class="ring" style="width:${size}px;height:${size}px" title="${rst(o.resets_at)}"><svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}"><circle cx="${c}" cy="${c}" r="${rad}" fill="none" stroke="#242b38" stroke-width="${sw}"/><circle cx="${c}" cy="${c}" r="${rad}" fill="none" stroke="${uc}" stroke-width="${sw}" stroke-linecap="round" stroke-dasharray="${dash} ${circ.toFixed(1)}" transform="rotate(-90 ${c} ${c})"/></svg><span class="ringtxt" style="font-size:${Math.round(size*.26)}px">${Math.round(f*100)}%</span></div>`}
function renderCards(d){
 const opt=!!(d.config&&d.config.optimize);
 $('#cards').innerHTML=Object.entries(d.accounts).map(([n,a])=>{
  const plan=a.plan==='free'?'<span class="tag free">FREE</span> ':a.plan?'<span class="tag plan">'+a.plan.toUpperCase()+'</span> ':'';
  const icons=a.active?`<div class="iconrow">
    <button class="iconbtn" title="${tr('compactTitle')}" onclick="sessionCmd('compact',this)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4v4a1 1 0 0 1-1 1H4M15 4v4a1 1 0 0 0 1 1h4M9 20v-4a1 1 0 0 0-1-1H4M15 20v-4a1 1 0 0 1 1-1h4"/></svg></button>
    <button class="iconbtn" title="${tr('newSessionTitle')}" onclick="sessionCmd('new')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 1 3 6.7"/><path d="M3 16v-4h4"/></svg></button>
   </div>`:'';
  const lp=!!a.lapsed;  // слетел с Pro на Free: опрос остановлен до «Я продлил»
  const r=a.five_hour&&!lp?ring(a.five_hour,18000):'';
  const lpTag=lp?'<span class="tag lpt">'+tr('lapsedTag')+'</span> ':'';
  const lpNote=lp?`<div class="lpnote" role="status"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/></svg><span><b>${tr('lapsedTitle')}</b> — ${tr('lapsedNote')}${a.lapsed_since?tr('lapsedSince',new Date(a.lapsed_since*1000).toLocaleString(LANG==='en'?'en-GB':'ru',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})):''}</span></div>`:'';
  return `
  <div class="card ${a.active?'active':''}${lp?' lapsed':''}">
   ${a.active?'<span class="tag pin">'+tr('active')+'</span>':''}
   <div class="top"><span class="email">${a.email} ${plan}${lpTag}${a.renewal_next?renewChip(a.renewal_next):''}</span><div class="hdrright">${r}${icons}</div></div>
   ${lpNote}
   ${a.error&&!lp?`<div class="err">⚠ ${a.error}${a.stale_ts?tr('staleAt',new Date(a.stale_ts*1000).toLocaleTimeString(LANG==='en'?'en-GB':'ru',{hour:'2-digit',minute:'2-digit'})):''}</div>`:''}${a.five_hour&&!lp?bar(tr('session5'),a.five_hour)+bar(tr('week'),a.seven_day):''}
   <div class="acts">${lp&&!a.active?'':`<button class="btn-sw" onclick="sw('${n}')" ${a.active||opt?'disabled':''} ${opt&&!a.active?'title="'+tr('switchBlockedTitle')+'"':a.manual_until?'title="'+ccpEsc(tr('manTagTitle',ccpAt(a.manual_until*1000)))+'"':''}>${a.active?(a.manual_until?'✋ '+tr('manTag'):tr('usingNow')):opt?tr('optimizeRules'):tr('switchTo')}</button>`}
   ${a.plan==='free'?`<button class="btn-renew" onclick="recheck('${n}',this)"><i class="rn-ic">✅</i> <span class="rn-t">${tr('extended')}</span></button>`:''}
   ${loginChip(a.login_expires)}<button class="btn-relogin" onclick="reloginAsk('${n}',this)">${tr('relogin')}</button>
   <button class="btn-del" title="${tr('delBtnTitle')}" aria-label="${tr('delBtn')}" onclick="acctDel('${n}')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14M10 11v6m4-6v6"/></svg><span class="dl">${tr('delBtn')}</span></button></div>
  </div>`;
 }).join('');
 renderDock(d);
}
// время последнего обновления данных — в подсказки зелёной точки и кнопки «Обновить»
function setUpd(ts){const t=tr('updated')+' '+new Date(ts*1000).toLocaleTimeString(LANG==='en'?'en-GB':'ru');$('#termDot').title=t;$('#rfBtn').title=tr('refresh')+' · '+t}
async function load(refresh){
 const r=await fetch(API+'limits?token='+TOKEN+(refresh?'&refresh=1':''));const d=await r.json();
 lastSnap=d;noProdSync();consFollow(d);
 $('#auto').checked=!!(d.config&&d.config.autoswitch);
 const opt=!!(d.config&&d.config.optimize);$('#opt').checked=opt;
 $('#auto').disabled=opt;$('#autoWrap').style.opacity=opt?'.5':'';
 $('#autoWrap').title=opt?tr('optDisabledTitle'):'';$('#autoNote').hidden=!opt;
 if(d.config&&d.config.threshold)THR=d.config.threshold;
 if(d.config&&d.config.weekly_cap)WCAP=Math.round(d.config.weekly_cap);
 $('#wkPause').checked=!!(d.config&&d.config.weekly_pause);
 renderAutoLbl();renderCards(d);
 setUpd(d.ts);
 renderModel(d.model);
}
let lastCandidates=[];
let poolScanned=false;
function familyOf(name){return (name||'').split(' ')[0].toLowerCase();}
function familyRank(f){return f==='haiku'?1:0;}
function unifiedRows(m,candidates){
 const rows={};
 ((m&&m.available)||[]).forEach(a=>{rows[a.id]={id:a.id,name:a.name,enabled:a.enabled!==false,isNew:!!a.new,known:true,hidden:!!a.hidden};});
 (candidates||[]).forEach(c=>{if(!rows[c.id])rows[c.id]={id:c.id,name:c.guess_name,enabled:false,isNew:true,known:false,hidden:false};});
 return Object.values(rows).sort((a,b)=>{
  const fa=familyOf(a.name),fb=familyOf(b.name);
  if(fa!==fb){const ra=familyRank(fa),rb=familyRank(fb);if(ra!==rb)return ra-rb;return fa<fb?-1:1;}
  return a.id<b.id?1:(a.id>b.id?-1:0);
 });
}
function renderPool(){
 $('#poolList').innerHTML=unifiedRows(lastModel,lastCandidates).filter(r=>poolScanned||!r.hidden).map(r=>
  `<div class="poolrow" data-id="${r.id}" data-known="${r.known?1:0}" style="flex-direction:column;align-items:stretch;gap:5px;cursor:default${r.hidden?';opacity:.6':''}">
    <div style="display:flex;align-items:center;gap:8px">
     <label style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;cursor:pointer;margin:0;min-width:0">
      <input type="checkbox" class="poolchk" ${r.enabled?'checked':''}>
      <span style="word-break:break-all">${r.id}</span>${r.isNew?' <span class="newbadge" style="margin-left:0">'+tr('newBadge')+'</span>':''}
     </label>
     ${r.known?`<label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin:0 0 0 auto;font-size:12px;color:var(--mut);white-space:nowrap"><input type="checkbox" class="hidechk-in" ${r.hidden?'checked':''}>${tr('hideModelLbl')}</label>`:''}
    </div>
    <input type="text" class="poolname" value="${r.name}">
   </div>`
 ).join('');
}
function renderModel(m){
 if(!m)return;
 lastModel=m;
 const en=m.available.filter(x=>x.enabled);
 $('#mrow').innerHTML=en.length?en.map(x=>`<button class="mchip ${x.id===m.default?'active':''}" onclick="pickModel('${x.id}')">${x.name}</button>`).join('')
  :`<span style="color:var(--mut);font-size:12.5px">${tr('noModelsEnabled')}</span>`;
 renderPool();
 $('#efrow').innerHTML=effortHtml(m);
}
const EF=['low','medium','high','xhigh','max'];
const EF_COL={low:'#6f86b3',medium:'#3fae9e',high:'#7c5cff',xhigh:'#d9973a',max:'#e0574f'};
let efPending=null;  // пока команда в пути, держим выбранный уровень — автообновление не откатит бегунок
function effortHtml(m){
 const sup=Array.isArray(m.effort_supported)?m.effort_supported:null;  // null = не знаем, не блокируем
 if(sup&&!sup.length)return '<span class="eflbl na" title="'+ccpEsc(tr('efNaTitle',m.session_name))+'">'+tr('efNaTxt')+'</span>';
 const cur=efPending||m.effort||m.effort_default,i=EF.indexOf(cur),unk=i<0;  // unk: уровень нигде не найден — шкалу всё равно показываем, чтобы его можно было задать
 const pc=unk?0:i*25,mis=!efPending&&m.effort&&m.effort_default&&m.effort!==m.effort_default,col=unk?'#7c9aff':EF_COL[cur];
 const tip=unk?tr('efUnkTip'):'Effort: '+cur+' · '+tr('efName',cur)+(mis?tr('efMis',m.effort_default):'');
 const off=sup?EF.filter(e=>!sup.includes(e)):[];
 return '<span class="eflbl'+(mis?' mis':'')+'" title="'+ccpEsc(tip)+'">effort <b style="--ef:'+col+'">'+(unk?tr('efUnk'):cur)+'</b></span>'
  +'<div class="efB'+(efPending?' busy':'')+(off.length?' lock':'')+(unk?' unk':'')+'" style="--ef:'+col+'" data-off="'+off.join(',')+'" data-model="'+ccpEsc(m.session_name||'')+'" onclick="effortClick(event,this)">'
  +'<div class="tr"></div><div class="fl" style="width:'+pc+'%"></div>'
  +EF.map((e,j)=>off.includes(e)?'<div class="tk off" style="left:'+j*25+'%" title="'+e+' ·'+ccpEsc(tr('efOffTip',m.session_name))+'"></div>'
   :'<div class="tk'+(j<i?' pass':'')+'" style="left:'+j*25+'%" title="'+e+' · '+tr('efName',e)+'"></div>').join('')
  +'<div class="th" style="left:'+pc+'%"></div></div>';
}
function effortClick(ev,el){
 const r=el.getBoundingClientRect(),j=Math.max(0,Math.min(4,Math.round((ev.clientX-r.left)/r.width*4)));
 if((el.dataset.off||'').split(',').includes(EF[j])){toast(tr('efBlocked',EF[j],el.dataset.model));return;}
 if(efPending||(lastModel&&lastModel.effort===EF[j]))return;
 if(!confirm(tr('confirmEffort',EF[j])))return;
 setEffort(EF[j]);
}
async function setEffort(level){
 if(efPending||(lastModel&&lastModel.effort===level))return;
 efPending=level;if(lastModel)renderModel(lastModel);
 try{
  const r=await fetch(API+'effort?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({effort:level})});
  const d=await r.json();
  if(!d.ok){toast('⚠ '+(d.message||'error'));return;}
  toast(d.message+tr('efChecking'));
  for(let k=0;k<6;k++){
   await new Promise(res=>setTimeout(res,2000));
   const d2=await (await fetch(API+'limits?token='+TOKEN)).json();
   if(d2.model&&d2.model.effort===level){toast(tr('efDone',level));break;}
   if(k===5)toast(tr('efNoConfirm'));
  }
 }catch(e){toast('⚠ '+e);}
 finally{efPending=null;load();}
}
async function pickModel(id){
 const mi=lastModel&&lastModel.available.find(x=>x.id===id);
 if(!confirm(tr('confirmModel',mi?mi.name:id)))return;
 const r=await fetch(API+'model?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:id})});
 const d=await r.json();toast(d.ok?'✅ '+d.message:'⚠ '+d.message);renderModel(d.model);
}
$('#poolList').addEventListener('change',async e=>{
 if(e.target.classList.contains('hidechk-in')){
  const id=e.target.closest('[data-id]').dataset.id;
  const r=await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hide:{[id]:e.target.checked}})});
  const d=await r.json();if(d&&d.model)renderModel(d.model);
  return;
 }
 if(!e.target.classList.contains('poolchk'))return;
 const row=e.target.closest('[data-id]'),id=row.dataset.id,known=row.dataset.known==='1';
 const name=row.querySelector('.poolname').value.trim()||id;
 let d=null;
 if(known){
  const ids=[...document.querySelectorAll('#poolList [data-known="1"] .poolchk:checked')].map(i=>i.closest('[data-id]').dataset.id);
  const r=await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled_models:ids})});
  d=await r.json();
 }else if(e.target.checked){
  const r=await fetch(API+'models/candidates?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({add:{[id]:name},ignore:[]})});
  d=await r.json();
  lastCandidates=lastCandidates.filter(c=>c.id!==id);
 }
 if(d&&d.model)renderModel(d.model);
});
async function checkNewModels(){
 poolScanned=true;
 $('#poolList').innerHTML='<div style="color:var(--mut);font-size:12.5px;padding:6px 2px">'+tr('candSearching')+'</div>';
 try{
  const r=await fetch(API+'models/candidates?token='+TOKEN);
  if(!r.ok)throw new Error(r.status);const d=await r.json();
  lastCandidates=(d&&d.candidates)||[];
  toast(lastCandidates.length?tr('candFound').replace('{n}',lastCandidates.length):tr('candNone'));
 }catch(e){lastCandidates=[];toast('⚠ '+tr('candErr'));}
 renderPool();
}
$('#checkNew').addEventListener('click',checkNewModels);
$('#gear').addEventListener('click',()=>{$('#scrim').hidden=false});
$('#modalDone').addEventListener('click',()=>{$('#scrim').hidden=true;poolScanned=false;renderPool();});
$('#scrim').addEventListener('click',e=>{if(e.target.id==='scrim'){$('#scrim').hidden=true;poolScanned=false;renderPool();}});
function toast(t){const m=$('#msg');m.textContent=t;m.style.display='block';setTimeout(()=>m.style.display='none',4000)}
async function sw(n){
 if(!confirm(tr('confirmSwitch',n)))return;
 const r=await fetch(API+'switch?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:n})});
 const d=await r.json();toast(d.ok?'✅ '+d.message.split('\n')[0]:'⚠ '+d.message);load();
}
async function sessionCmd(cmd,btn){
 if(cmd==='compact'&&!await window.fleetAsk(btn,tr('askCompact'),tr('askYes')))return;
 if(cmd==='new'&&!confirm(tr('confirmNewSession')))return;
 try{
  const r=await fetch(API+'session?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd})});
  const d=await r.json();toast(d.ok?'✅ '+d.message:'⚠ '+(d.message||''));
 }catch(e){toast('⚠ '+e)}
}
$('#auto').addEventListener('change',async e=>{
 await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({autoswitch:e.target.checked})});
 toast(e.target.checked?tr('autoOn'):tr('autoOff'));
});
async function setThr(v){
 v=Math.max(50,Math.min(99,v));
 if(v===THR)return;
 THR=v;renderAutoLbl();
 await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({threshold:THR})});
 toast(tr('thrSet',THR));
}
$('#wkPause').addEventListener('change',async e=>{
 await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({weekly_pause:e.target.checked})});
 toast(e.target.checked?tr('wkOn'):tr('wkOff'));ccpLoad();
});
$('#thrMinus').addEventListener('click',()=>setThr(THR-5));
$('#thrPlus').addEventListener('click',()=>setThr(THR+5));
$('#opt').addEventListener('change',async e=>{
 const box=e.target,on=box.checked;box.checked=!on;
 if(!await window.fleetAsk(box.closest('label,.switchrow')||box,tr(on?'askOptOn':'askOptOff'),tr('askYes')))return;
 box.checked=on;
 await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({optimize:on})});
 toast(on?tr('optOn'):tr('optOff'));load();
});
async function recheck(n,btn){
 btn.disabled=true;const orig=btn.innerHTML;btn.innerHTML='<span class="rn-t">'+tr('checking')+'</span>';
 try{
  const r=await fetch(API+'recheck?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:n})});
  const d=await r.json();toast(d.message);
 }catch(e){toast(tr('checkErr',e));}
 finally{btn.disabled=false;btn.innerHTML=orig;load();}
}
// «Войти заново» — боковая панель (#acctScrim.side): ссылка входа + поле для кода.
// Без новой вкладки и prompt(): вкладку блокирует попап-блокер или она открывается
// не в том профиле браузера, а prompt остаётся на исходной вкладке.
// remote=true — Claude на втором сервере (PROD): вход идёт там же, токены остаются на нём
function reloginAsk(n,btn,remote){window.fleetAsk(btn,tr('askRelogin'),tr('askYes')).then(ok=>{if(ok)relogin(n,remote)})}
function relogin(n,remote){
 const a=remote?{}:(((lastSnap&&lastSnap.accounts)||{})[n]||{});
 const who=remote?'Claude PROD':(a.email&&a.email!=='?'?a.email:n);
 const head=`<h3>${tr('relTitle')}</h3><div class="modalsub"><b>${acctEsc(who)}</b> · ${acctEsc(n)}</div>`;
 $('#acctScrim').classList.add('side');
 acctShow(`${head}<div class="modalsub" id="relWait">${tr('addStarting')}</div><div class="dlgerr" id="acctErr" hidden></div>
  <div class="modalfoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button></div>`);
 $('#acctCancel').onclick=acctClose;
 acctBusy=true;
 acctPost(remote?'remote/relogin/start':'relogin/start',remote?{}:{account:n}).then(d=>{
  acctBusy=false;
  if(!d.ok){$('#relWait').hidden=true;acctErr(d.message);return;}
  reloginStep2(n,head,d,remote);
 }).catch(e=>{acctBusy=false;$('#relWait').hidden=true;acctErr(String(e));});
}
function reloginStep2(n,head,d,remote){
 acctShow(`${head}
  <div class="dlgstep"><i>1</i><span>${tr('relStep1',acctEsc(d.email||n))}</span></div>
  <div class="modalsub" style="margin:0 0 6px">${tr('relHint')}</div>
  <div class="dlgurl">${acctEsc(d.url)}</div>
  <div class="dlgrow"><button id="addOpen">${tr('addOpen')}</button><button class="ghostbtn" id="addCopy">${tr('addCopy')}</button></div>
  <div class="dlgstep"><i>2</i><span>${tr('addStep2')}</span></div>
  <input id="addCode" class="dlginp" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${tr('addCodePh')}">
  <div class="dlgerr" id="acctErr" hidden></div>
  <div class="modalfoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button><button id="addSend">${tr('relSubmit')}</button></div>`);
 $('#acctCancel').onclick=acctClose;
 $('#addOpen').onclick=()=>window.open(d.url,'_blank');
 $('#addCopy').onclick=()=>acctCopy($('#addCopy'),d.url);
 const code=$('#addCode'),send=$('#addSend');
 code.addEventListener('keydown',e=>{if(e.key==='Enter')send.click();});
 send.onclick=async()=>{
  if(acctBusy)return;
  if(!code.value.trim()){acctErr(tr('addNeedCode'));return;}
  acctBusy=true;send.disabled=true;send.textContent=tr('relChecking');acctErr('');
  try{
   const r=await acctPost(remote?'remote/relogin/submit':'relogin/submit',remote?{code:code.value.trim()}:{account:n,code:code.value.trim()});
   acctBusy=false;
   if(r.ok){acctClose();toast(r.message);load();return;}
   // неудачная попытка на сервере уже сброшена — тот же код второй раз не пройдёт, нужна новая ссылка
   acctErr(r.message);send.disabled=false;send.textContent=tr('addRestart');send.onclick=()=>relogin(n,remote);
  }catch(e){acctBusy=false;acctErr(String(e));send.disabled=false;send.textContent=tr('relSubmit');}
 };
 setTimeout(()=>code.focus(),30);
}
$('#rfBtn').addEventListener('click',()=>{$('#rfBtn').disabled=true;cxLoad(true);load(1).finally(()=>$('#rfBtn').disabled=false)});

// ---- добавление и удаление аккаунтов ----
// Окно одно на все сценарии (#acctBox); «Войти заново» открывает его боковой панелью (.side). Удаление необратимо: кнопка «Удалить навсегда»
// оживает только после ввода слова; ту же проверку делает и сервер.
const acctEsc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let acctBusy=false;
function acctClose(){if(acctBusy)return;$('#acctScrim').hidden=true;$('#acctScrim').classList.remove('side');$('#acctBox').innerHTML='';}
function acctShow(html){$('#acctBox').innerHTML=html;$('#acctScrim').hidden=false;}
// navigator.clipboard есть только в защищённом контексте (https/localhost) — на http копируем через execCommand
async function acctCopy(b,t){
 const orig=b.textContent;let ok=false;
 try{await navigator.clipboard.writeText(t);ok=true;}catch(e){
  const ta=document.createElement('textarea');ta.value=t;ta.style.cssText='position:fixed;opacity:0';
  document.body.appendChild(ta);ta.select();try{ok=document.execCommand('copy');}catch(e2){}ta.remove();
 }
 if(ok){b.textContent=tr('addCopied');setTimeout(()=>{b.textContent=orig},1800);}
}
function acctErr(t){const e=$('#acctErr');if(!e)return;e.textContent=t;e.hidden=!t;}
async function acctPost(path,body){
 const r=await fetch(API+path+'?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.assign({lang:LANG},body))});
 return r.json();
}
function acctDel(n){
 const accs=(lastSnap&&lastSnap.accounts)||{};const a=accs[n]||{};
 const real=Object.values(accs).filter(x=>x.email&&x.email!=='?').length;
 const isReal=a.email&&a.email!=='?';const last=isReal&&real<=1;
 const word=tr('delWord');
 acctShow(`<h3>${tr('delTitle')}</h3>
  <div class="modalsub"><b>${acctEsc(isReal?a.email:n)}</b> · ${acctEsc(n)}</div>
  <div class="dlgwarn">${tr('delWarn')}${a.active?'<br><br>'+tr('delActive'):''}${last?'<br><br>'+tr('delLast'):''}</div>
  <label class="dlglbl" for="delInp">${tr('delType',word)}</label>
  <input id="delInp" class="dlginp" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${word}">
  <div class="dlgerr" id="acctErr" hidden></div>
  <div class="modalfoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button><button class="btn-danger" id="delGo" disabled>${tr('delGo')}</button></div>`);
 $('#acctCancel').onclick=acctClose;
 const inp=$('#delInp'),go=$('#delGo');
 inp.addEventListener('input',()=>{go.disabled=inp.value.trim().toLowerCase()!==word;});
 inp.addEventListener('keydown',e=>{if(e.key==='Enter'&&!go.disabled)go.click();});
 go.onclick=async()=>{
  if(acctBusy||go.disabled)return;
  acctBusy=true;go.disabled=true;go.textContent=tr('delWorking');acctErr('');
  try{
   const d=await acctPost('account/delete',{account:n,confirm:inp.value});
   acctBusy=false;
   if(d.ok){acctClose();toast(d.message);load();return;}
   acctErr(d.message);go.textContent=tr('delGo');go.disabled=inp.value.trim().toLowerCase()!==word;
  }catch(e){acctBusy=false;acctErr(String(e));go.textContent=tr('delGo');go.disabled=false;}
 };
 setTimeout(()=>inp.focus(),30);
}
function acctAdd(){
 acctShow(`<h3>${tr('addTitle')}</h3>
  <div class="modalsub">${tr('addSub')}</div>
  <label class="dlglbl" for="addEmail">${tr('addEmailLbl')}</label>
  <input id="addEmail" class="dlginp" type="email" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="name@example.com">
  <div class="modalsub" style="margin:6px 0 0">${tr('addEmailHint')}</div>
  <div class="dlgerr" id="acctErr" hidden></div>
  <div class="modalfoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button><button id="addGo">${tr('addGetLink')}</button></div>`);
 $('#acctCancel').onclick=acctClose;
 const go=$('#addGo'),em=$('#addEmail');
 em.addEventListener('keydown',e=>{if(e.key==='Enter')go.click();});
 go.onclick=async()=>{
  if(acctBusy)return;
  acctBusy=true;go.disabled=true;go.textContent=tr('addStarting');acctErr('');
  try{
   const d=await acctPost('account/add/start',{email:em.value.trim()});
   acctBusy=false;
   if(!d.ok){acctErr(d.message);go.disabled=false;go.textContent=tr('addGetLink');return;}
   acctAddStep2(d);
  }catch(e){acctBusy=false;acctErr(String(e));go.disabled=false;go.textContent=tr('addGetLink');}
 };
 setTimeout(()=>em.focus(),30);
}
function acctAddStep2(d){
 acctShow(`<h3>${tr('addTitle')}</h3>
  <div class="dlgstep"><i>1</i>${tr('addStep1')}</div>
  <div class="dlgurl">${acctEsc(d.url)}</div>
  <div class="dlgrow"><button id="addOpen">${tr('addOpen')}</button><button class="ghostbtn" id="addCopy">${tr('addCopy')}</button></div>
  <div class="dlgstep"><i>2</i>${tr('addStep2')}</div>
  <input id="addCode" class="dlginp" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${tr('addCodePh')}">
  <div class="dlgerr" id="acctErr" hidden></div>
  <div class="modalfoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button><button id="addSend">${tr('addSubmit')}</button></div>`);
 $('#acctCancel').onclick=acctClose;
 $('#addOpen').onclick=()=>window.open(d.url,'_blank');
 $('#addCopy').onclick=()=>acctCopy($('#addCopy'),d.url);
 const code=$('#addCode'),send=$('#addSend');
 code.addEventListener('keydown',e=>{if(e.key==='Enter')send.click();});
 send.onclick=async()=>{
  if(acctBusy)return;
  if(!code.value.trim()){acctErr(tr('addNeedCode'));return;}
  acctBusy=true;send.disabled=true;send.textContent=tr('addChecking');acctErr('');
  try{
   const r=await acctPost('account/add/submit',{slot:d.slot,code:code.value.trim()});
   acctBusy=false;
   if(r.ok){acctClose();toast(r.message);load();return;}
   // неудачная попытка на сервере уже сброшена — второй раз тот же код не сработает, нужна новая ссылка
   acctErr(r.message);send.disabled=false;send.textContent=tr('addRestart');send.onclick=acctAdd;
  }catch(e){acctBusy=false;acctErr(String(e));send.disabled=false;send.textContent=tr('addSubmit');}
 };
 setTimeout(()=>code.focus(),30);
}
$('#acctScrim').addEventListener('mousedown',e=>{if(e.target.id==='acctScrim')acctClose();});

// ---- ChatGPT (Codex): секция под карточками Claude ----
// Данные — отдельным запросом /api/chatgpt (чтение через codex app-server до ~10 с на аккаунт).
// Секция скрыта, пока на сервере нет Codex. Вход — по коду устройства, пароли не вводятся.
let cxData=null,cxBusy=false,cxAgain=false,cxPending=false,cxPoll=null;
function cxAcc(slot){return((cxData&&cxData.accounts)||[]).find(a=>a.slot===slot)||null;}
function cxWin(a,mins){return(a.windows||[]).find(w=>w.mins===mins)||null;}
function cxDate(iso,withTime){return new Date(iso).toLocaleString(LANG==='en'?'en-GB':'ru',withTime?{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}:{day:'2-digit',month:'2-digit',year:'numeric'});}
function cxSubChip(a){
 if(!a.sub_until)return'';
 const ms=new Date(a.sub_until)-Date.now(),d=Math.floor(ms/86400000),tip=acctEsc(tr('cxSubTitle',cxDate(a.sub_until)));
 if(ms<=0)return`<span class="chip urgent" title="${tip}"><b>${tr('cxSubOver')}</b></span>`;
 return`<span class="chip${d<=3?' urgent':d<=7?' warn':''}" title="${tip}"><b>${tr('cxSubChip',d)}</b></span>`;
}
function cxAuthChip(a){
 if(!a.last_refresh)return'';
 const d=Math.floor((Date.now()-new Date(a.last_refresh))/86400000);
 return`<span class="chip" title="${acctEsc(tr('cxAuthTitle',cxDate(a.last_refresh,true)))}">${tr('cxAuthChip',Math.max(0,d))}</span>`;
}
function cxSelects(a){
 const ms=a.models||[];
 if(!ms.length)return'';
 const def=ms.find(m=>m.is_default)||ms[0];
 const known=a.model&&ms.some(m=>m.id===a.model);
 const cur=(known&&ms.find(m=>m.id===a.model))||def;
 const efs=cur.efforts||[];
 const ef=a.effort&&efs.includes(a.effort)?a.effort:'';
 const sl=acctEsc(a.slot);
 const canFast=!!cur.fast;
 const mOpts=`<option value=""${known||a.model?'':' selected'}>${acctEsc(tr('cxDefault')+' · '+def.name)}</option>`
  +(a.model&&!known?`<option value="${acctEsc(a.model)}" selected>${acctEsc(a.model)}</option>`:'')
  +ms.map(m=>`<option value="${acctEsc(m.id)}"${known&&m.id===a.model?' selected':''}>${acctEsc(m.name)}</option>`).join('');
 const eOpts=`<option value=""${ef?'':' selected'}>${acctEsc(tr('cxEffort')+': '+tr('cxDefault')+(cur.default_effort?' ('+cur.default_effort+')':''))}</option>`
  +efs.map(e=>`<option value="${acctEsc(e)}"${e===ef?' selected':''}>${acctEsc(tr('cxEffort')+': '+e)}</option>`).join('');
 return`<div class="cxsel">
   <select class="dlginp" id="cxm-${sl}" title="${tr('cxModelTip')}" aria-label="${tr('cxModelTip')}" onchange="cxPref('${sl}',this)">${mOpts}</select>
   ${efs.length?`<select class="dlginp" id="cxe-${sl}" title="${tr('cxEffortTip')}" aria-label="${tr('cxEffortTip')}" onchange="cxPref('${sl}',this)">${eOpts}</select>`:''}
   <label class="cxfast${canFast?'':' off'}" title="${acctEsc(canFast?tr('cxFastTip'):tr('cxFastNa'))}"><input type="checkbox" id="cxf-${sl}"${a.fast&&canFast?' checked':''}${canFast?'':' disabled'} onchange="cxPref('${sl}',this)"><span>${tr('cxFast')}</span></label>
  </div>`;
}
function cxNeedsRenew(a){return!!a.lapsed||(!!a.sub_until&&new Date(a.sub_until)-Date.now()<=0);}
function cxCard(a){
 const sl=acctEsc(a.slot);
 const plan=a.lapsed?'<span class="tag lpt">FREE</span> ':a.plan?'<span class="tag plan">'+acctEsc(String(a.plan).toUpperCase())+'</span> ':'';
 const who=(a.label?acctEsc(a.label)+' · ':'')+acctEsc(a.email||'?');
 const w5=cxWin(a,300),w7=cxWin(a,10080);
 const rest=(a.windows||[]).filter(w=>w!==w5&&w!==w7);
 const rg=w5?ring(w5,18000):'';
 let notes='';
 if(a.login_required)notes+=`<div class="lpnote cxcard-note" role="status"><span><b>${tr('cxLoginNeeded')}</b></span></div>`;
 else{
  if(a.lapsed)notes+=`<div class="lpnote cxcard-note" role="status"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/></svg><span><b>FREE</b> — ${acctEsc(tr('cxLapsedNote',a.paid_plan?String(a.paid_plan).replace(/^./,c=>c.toUpperCase()):''))}</span></div>`;
  if(a.error)notes+=`<div class="err">⚠ ${acctEsc(a.error)}${a.stale?' · '+tr('cxStale'):''}</div>`;
  if(a.reached||a.usage_allowed===false)notes+=`<div class="lpnote cxcard-note" role="status"><span><b>${a.reached?tr('cxReached'):tr('cxNotAllowed')}</b></span></div>`;
 }
 const bars=(w5?bar(tr('session5'),w5):'')+(w7?bar(tr('week'),w7):'')
  +rest.map(w=>bar(tr('cxWin',Math.round((w.mins||0)/60)),w)).join('');
 const cr=a.credits&&(a.credits.unlimited?tr('cxCreditsUnl'):a.credits.hasCredits?tr('cxCredits',acctEsc(a.credits.balance)):'');
 return`<div class="card${a.lapsed?' lapsed':''}">
  <div class="top"><span class="email">${who} ${plan}${a.lapsed?'':cxSubChip(a)}</span><div class="hdrright">${rg}</div></div>
  ${notes}${bars}${cr?`<div class="cxsub" style="margin-top:8px">${cr}</div>`:''}
  ${a.login_required?'':cxSelects(a)}
  <div class="acts">${cxAuthChip(a)}${cxNeedsRenew(a)&&!a.login_required?`<button class="btn-relogin" title="${acctEsc(tr('cxRenewTip'))}" onclick="cxRenew('${sl}',this)">✅ ${tr('cxRenewBtn')}</button>`:''}<button class="btn-relogin" onclick="cxReloginAsk('${sl}',this)">${tr('cxRelogin')}</button>
   <button class="btn-relogin" title="${acctEsc(tr('cxLaunchTip'))}" onclick="cxLaunch('${sl}',this)">${tr('cxLaunch')}</button>
   <button class="btn-del" title="${tr('delBtnTitle')}" aria-label="${tr('delBtn')}" onclick="cxDel('${sl}')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14M10 11v6m4-6v6"/></svg><span class="dl">${tr('delBtn')}</span></button></div>
 </div>`;
}
function cxRender(){
 const el=$('#cx'),d=cxData;
 if(!d||!d.available){el.hidden=true;el.innerHTML='';return;}
 // открытый выпадающий список перерисовка закрыла бы под рукой — отложим до ухода фокуса
 const f=document.activeElement;
 if(f&&f.tagName==='SELECT'&&el.contains(f)){cxPending=true;return;}
 cxPending=false;el.hidden=false;
 el.innerHTML=`<div class="cxhead"><button class="hdrgear" title="${tr('cxAddTitle')}" aria-label="${tr('cxAddTitle')}" onclick="cxAdd()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg></button><span class="cxsub">${tr('cxAddTitle')} · ${tr('cxHint')}</span></div>
  <div id="cxcards">${d.accounts.length?d.accounts.map(cxCard).join(''):`<div class="cxsub">${tr('cxEmpty')}</div>`}</div>`;
}
$('#cx').addEventListener('focusout',()=>{if(cxPending)setTimeout(cxRender,60);});
// ---- Мост Telegram ↔ Codex: отдельная карточка под аккаунтами ChatGPT ----
// Перерисовывается только по загрузке/сохранению и не трогается, пока в ней стоит курсор, — введённое не теряется.
let cxbData=null,cxbBusy=false;
const CXB_ST={sent:'→',accepted:'👀',done:'✅',timeout:'⏱'};
function cxbVal(id){const e=$('#'+id);return e?e.value:'';}
// «Проект» в форме: в режиме «Самостоятельно» без своего проекта он совпадает с рабочей папкой — тогда поле пустое
function cxbProjVal(b){return b.mode==='self'&&b.project===b.workdir?'':(b.project||'');}
// рабочая папка нужна только профилю «Codex» (самостоятельная работа); режим задаёт профиль, не форма
function cxbSync(){
 const b=(cxbData&&cxbData.bridge)||{};
 $('#cxbDirRow').hidden=b.mode!=='self';
 cxbDelSync();
}
// «Удалить аккаунт» в карточке моста — тот аккаунт, что выбран в поле «Аккаунт ChatGPT»; «первый подходящий» — неясно какой, кнопка неактивна
function cxbDelSync(){
 const btn=$('#cxbDel');if(!btn)return;
 const sel=$('#cxbSlot'),has=!!(sel&&sel.value);
 btn.disabled=!has;btn.title=tr(has?'cxbDelTip':'cxbDelPick');
}
function cxbDelAcct(){const sel=$('#cxbSlot');if(sel&&sel.value)cxDel(sel.value);}
function cxbStatus(b){
 const st=(b.running?'🟢 <b>'+tr('cxbRunning')+'</b>':'⚪ '+tr('cxbOff'))+(b.busy?tr('cxbBusy'):'')+(b.pending?tr('cxbPending'):'');
 const ts=(b.tasks||[]).map(t=>'#'+t.n+' '+(CXB_ST[t.state]||t.state)+' '+acctEsc(t.rights)).join(' · ');
 return st+(b.last_error?`<div class="cxbwarn">⚠ ${acctEsc(b.last_error)}</div>`:'')+(ts?`<div>${tr('cxbTasks')}${ts}</div>`:'');
}
function cxbRender(force){
 const el=$('#cxb'),d=cxbData;
 if(!d||!d.available){el.hidden=true;el.innerHTML='';return;}
 const f=document.activeElement;
 if(!force&&f&&el.contains(f)&&/^(INPUT|SELECT)$/.test(f.tagName)){const s=$('#cxbStat');if(s)s.innerHTML=cxbStatus(d.bridge);return;}
 const b=d.bridge,o=(v,l,cur)=>`<option value="${v}"${cur===v?' selected':''}>${acctEsc(l)}</option>`;
 const slots=(b.slots||[]).length
  ?`<select class="dlginp" id="cxbSlot" onchange="cxbDelSync()">${o('',tr('cxbSlotAuto'),b.slot)}${b.slots.map(s=>o(s,s+((cxAcc(s)||{}).email?' · '+cxAcc(s).email:''),b.slot)).join('')}</select>`
  :`<div class="cxsub" style="margin-top:8px">${tr('cxbNoSlot')}</div>`;
 // профиль «Codex»: рабочая папка (где он может всё) идёт первой, проект — только чтение; в «Оркестраторе» видно только проект
 const self=b.mode==='self';
 const projBlock=`<label class="dlglbl" for="cxbProj"${self?' style="margin-top:14px"':''}>${tr(self?'cxbProjectSelf':'cxbProject')}</label>
  <input id="cxbProj" class="dlginp" autocomplete="off" spellcheck="false" placeholder="/home/…/project" value="${acctEsc(cxbProjVal(b))}">
  <div class="cxsub" style="margin-top:6px">${tr(self?'cxbProjHintSelf':'cxbProjHint')}</div>`;
 const dirBlock=`<div id="cxbDirRow"><label class="dlglbl" for="cxbDir">${tr('cxbDir')}</label>
   <input id="cxbDir" class="dlginp" autocomplete="off" spellcheck="false" placeholder="${acctEsc(b.workspace||'/home/…/work')}" value="${acctEsc(b.workdir||'')}">
   <div class="cxsub" style="margin-top:6px">${tr('cxbDirSelf')}</div></div>`;
 el.hidden=false;
 el.innerHTML=`<div class="cxsub" style="margin:10px 0 8px">${tr('cxbHint')}</div>
 <div class="card">
  <div class="cxbgrid">
   <div><label class="dlglbl" for="cxbSlot">${tr('cxbSlot')}</label>${slots}</div>
  </div>
  ${self?dirBlock+projBlock:projBlock+dirBlock}
  <label class="dlglbl" for="cxbTok" style="margin-top:14px">${tr('cxbTokLbl')}</label>
  ${b.token_set
   ?`<div class="cxbrow"><span class="cxsub">${acctEsc(tr('cxbBotInfo',b.bot||'?',b.token_tail))}</span><button class="ghostbtn" onclick="cxbTokClear()">${tr('cxbDisc')}</button></div>`
   :`<div class="cxbrow"><input id="cxbTok" class="dlginp" type="password" autocomplete="off" spellcheck="false" placeholder="${acctEsc(tr('cxbTokPh'))}"><button onclick="cxbTokSet()">${tr('cxbConnect')}</button></div>`}
  <label class="dlglbl" for="cxbChat" style="margin-top:14px">${tr('cxbChat')}</label>
  <input id="cxbChat" class="dlginp" inputmode="numeric" autocomplete="off" value="${acctEsc(b.chat_id||'')}">
  <div class="cxbrow"><label class="cxfast"><input type="checkbox" id="cxbOn"${b.enabled?' checked':''}${b.token_set?'':' disabled'}><span>${tr('cxbOn')}</span></label>
   <button class="ghostbtn" onclick="cxbReset()">${tr('cxbNew')}</button></div>
  <div class="cxbstat" id="cxbStat">${cxbStatus(b)}</div>
  <div class="cxbrow cxbfoot"><button id="cxbSave" onclick="cxbSave()">${tr('cxbSave')}</button>
   <button class="btn-del" id="cxbDel" onclick="cxbDelAcct()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14M10 11v6m4-6v6"/></svg><span>${tr('cxbDelAcct')}</span></button></div>
 </div>`;
 cxbSync();
}
async function cxbLoad(force){
 if(cxbBusy)return;cxbBusy=true;
 try{
  const r=await fetch(API+'chatgpt/bridge?token='+TOKEN);const d=await r.json();
  if(d&&d.ok){cxbData=d;cxbRender(force);cxAll();}
 }catch(e){}
 finally{cxbBusy=false;}
}
async function cxbSave(){
 const btn=$('#cxbSave');btn.disabled=true;
 try{
  const on=$('#cxbOn'),b=(cxbData&&cxbData.bridge)||{},pj=cxbVal('cxbProj').trim();
  const body={slot:cxbVal('cxbSlot'),workdir:cxbVal('cxbDir').trim(),chat_id:cxbVal('cxbChat').trim(),enabled:!!(on&&on.checked)};
  if(pj!==cxbProjVal(b))body.project=pj;  // проект уходит, только если его поменяли
  const r=await acctPost('chatgpt/bridge/save',body);
  toast(r.ok?tr('cxbSaved'):'⚠ '+r.message);
  if(r.ok)await cxbLoad(true);
 }catch(e){toast('⚠ '+e);}
 btn.disabled=false;
}
async function cxbTokSet(){
 const t=cxbVal('cxbTok').trim();if(!t)return;
 try{const r=await acctPost('chatgpt/bridge/token',{token:t});toast(r.ok?r.message:'⚠ '+r.message);if(r.ok)await cxbLoad(true);}
 catch(e){toast('⚠ '+e);}
}
async function cxbTokClear(){try{await acctPost('chatgpt/bridge/token/clear',{});}catch(e){}cxbLoad(true);}
async function cxbReset(){try{await acctPost('chatgpt/bridge/reset',{});toast('✓');}catch(e){}}
// ---- Codex в шапке: значок с точкой статуса + выпадающее окно (профили, лимиты, мост) ----
// На странице Codex места не занимает: всё, что он показывал под карточками, живёт в окне по клику.
let cxpBusy=false;
const CXP_SEC={acc:false,br:false};
try{Object.assign(CXP_SEC,JSON.parse(localStorage.getItem('cxpSec')||'{}'));}catch(e){}
function cxAvail(){return!!((cxData&&cxData.available)||(cxbData&&cxbData.available));}
function cxpName(p){return p.builtin?tr('cxpN_'+p.id):p.name;}
const CXO_MK={mediator:'cxbModeMed',orchestrator:'cxbModeOrch',self:'cxbModeSelf'},CXO_AK={read:'cxbAccRead',write:'cxbAccWrite',full:'cxbAccFull'},CXO_RK={read:'cxbRRead',dev:'cxbRDev',full:'cxbRFull'};
function cxoMode(m){return tr(CXO_MK[m]||'cxbModeMed').replace(/\s*\(.*$/,'');}
function cxoAcc(a){return tr(CXO_AK[a]||'cxbAccRead').replace(/\s*\(.*$/,'');}
function cxoRt(r){return tr(CXO_RK[r]||'cxbRDev').replace(/\s*[—-].*$/,'');}
// состав кратко: «Посредник · задания: дев» / «Самостоятельно · доступ: только чтение»
function cxpBrief(d){return d.mode==='self'?tr('cxpBriefSelf',cxoMode('self'),cxoAcc(d.access)):tr('cxpBrief',cxoMode(d.mode),cxoRt(d.task_rights));}
function cxpSub(p){
 return p.builtin?tr('cxpS_'+p.id):cxpBrief(p);
}
// оформление встроенных профилей: цвета названий маршрута, цвет и значок каждой основной функции, цвета шагов схемы
const CXP_META={
 orchestrator:{caps:true,rc:['cx','cl'],fc:['g','b','o','r'],fi:['🧭','✋','🔨','⏹'],fl:['me','cx','ok','cl','cx']},
 codex:{caps:false,rc:['nat'],fc:['g','b','o'],fi:['⚡','✏️','👁'],fl:['me','cx','nat']},
 codex_solo_full:{caps:false,rc:['nat','r'],fc:['g','r','o','b'],fi:['⚡','🔓','👤','✋'],fl:['me','cx','nat']}
};
const CXP_ARR='<svg class="cxarr" viewBox="0 0 26 10" aria-hidden="true"><path d="M1 5h21M17.5 1.2 22.5 5l-5 3.8" fill="none" stroke="url(#cxpg)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
function cxpChip(c,t){return`<span class="cxw ${c}">${acctEsc(t)}</span>`;}
// цепочка «a ➜ b ➜ c»: стрелка держится за следующим звеном, при переносе строки не остаётся висеть в конце
function cxpSeq(chips){return chips.map((c,i)=>i?`<span class="cxst">${CXP_ARR}${c}</span>`:c).join('');}
function cxpNameHtml(p){
 const m=p.builtin&&CXP_META[p.id];
 if(!m)return acctEsc(cxpName(p));
 return`<span class="cxpnm${m.caps?' caps':''}">${acctEsc(cxpName(p))}</span><span class="cxroute">${cxpSeq(tr('cxpRoute_'+p.id).map((t,i)=>cxpChip(m.rc[i],t)))}</span>`;
}
function cxpFeatHtml(p){
 const m=p.builtin&&CXP_META[p.id];if(!m)return'';
 return`<span class="cxpf">${tr('cxpF_'+p.id).map((t,i)=>`<span class="${m.fc[i]}"><i>${m.fi[i]}</i>${acctEsc(t)}</span>`).join('')}</span>`;
}
// пояснение по значку ⓘ: из чего состоит профиль и когда его выбирать
const CXP_INFO=new Set();  // раскрытые пояснения переживают перерисовку
function cxpInfoHtml(p){
 const row=(k,v,d)=>`<span class="cxpirow"><span class="cxpik">${acctEsc(k)}:</span> <b>${acctEsc(v)}</b><span class="cxpid">${acctEsc(d)}</span></span>`;
 const kv=(c,k,v)=>`<span class="cxpirow"><span class="cxpik ${c}">${acctEsc(k)}</span> ${acctEsc(v)}</span>`;
 const m=p.builtin&&CXP_META[p.id];
 let rows;
 if(m){
  rows=`<span class="cxpirow"><span class="cxpik">${acctEsc(tr('cxpFlowLbl'))}:</span><span class="cxflow">${cxpSeq(tr('cxpFlow_'+p.id).map((t,i)=>cxpChip(m.fl[i],t)))}</span></span>`
   +kv('can',tr('cxpCanL'),tr('cxpCan_'+p.id))+kv('not',tr('cxpNotL'),tr('cxpNot_'+p.id));
 }else{
  rows=row(tr('cxbMode'),cxoMode(p.mode),tr('cxoMode_'+p.mode));
  rows+=p.mode==='self'?row(tr('cxbAccess'),cxoAcc(p.access),tr('cxoAcc_'+p.access)):row(tr('cxoRtLbl'),cxoRt(p.task_rights),tr('cxoRt_'+p.task_rights));
 }
 const when=m?`<span class="cxpwhen"><b>${tr('cxpWhenLbl')}</b> ${acctEsc(tr('cxpWhen_'+p.id))}</span>`:'';
 return`<span class="cxpinfo">${rows}${when}</span>`;
}
function cxpCur(){
 const b=cxbData&&cxbData.bridge;if(!b)return null;
 return(b.profiles||[]).find(p=>p.id===b.profile)||null;
}
function cxHdr(){
 const btn=$('#cxBtn'),grp=$('#cxGrp');if(!btn||!grp)return;
 const av=cxAvail();ciHdr();
 const hide=!av||ciStage()===2;  // шаг 2 мастера (аккаунта нет): значок, профиль и ⚙ не нужны — вход ведёт «Codex +»
 grp.hidden=hide;
 if(hide){cxPopClose();cxMenuClose();cxQClose();return;}
 const b=cxbData&&cxbData.bridge,cur=cxpCur();
 let cls='';
 if(b){if(b.last_error)cls='err';else if(b.running)cls=b.busy?'busy':'on';}
 const emg=!!(cxbData&&cxbData.emergency&&cxbData.emergency.active);
 if(emg)cls='emg';
 btn.classList.toggle('emg',emg);
 $('#cxDot').className='cxdot '+cls;
 const name=emg?tr('cxeHdr'):cur?cxpName(cur):(b&&b.enabled?tr('cxpManualShort'):'');
 $('#cxBtnName').textContent=name;
 const st=b?(b.last_error?'⚠ '+b.last_error:b.running?tr('cxbRunning'):tr('cxbOff')):'';
 const la=cxLimAcc(),lim=$('#cxLim');
 lim.innerHTML=la?cxLimHtml(la):'';lim.classList.toggle('stale',!!(la&&(la.stale||la.error)));
 btn.title=[tr('cxBtnTip')+(st?' — '+st:'')].concat(la?cxLimTip(la):[]).join('\n');btn.setAttribute('aria-label',btn.title);
 const gb=$('#cxGear');gb.title=tr('cxGearTip');gb.setAttribute('aria-label',gb.title);
 cxQBtn();
 $('#cxPopTitle').textContent=tr('cxPopTitle');
 const ps=$('#cxPopSt');ps.textContent=st;ps.title=st;
 $('#cxPopX').title=tr('cxpClose');$('#cxPopX').setAttribute('aria-label',tr('cxpClose'));
}
// ---- счётчики лимитов в кнопке шапки: 5 ч · неделя в одну строку, цвет по занятости, при исчерпании — когда сбросится ----
// Берём аккаунт, которым работает мост (слот из настроек, иначе первый). Время — местное время браузера.
function cxLimAcc(){
 const as=(cxData&&cxData.accounts)||[],b=cxbData&&cxbData.bridge;
 if(!as.length)return null;
 const slot=(b&&b.slot)||(b&&b.slots&&b.slots[0])||as[0].slot;
 return as.find(a=>a.slot===slot)||as[0];
}
function cxLoc(){return LANG==='en'?'en-GB':'ru';}
function cxClock(iso){
 const d=new Date(iso);if(isNaN(d))return'';
 const tm=d.toLocaleTimeString(cxLoc(),{hour:'2-digit',minute:'2-digit'});
 return d.toDateString()===new Date().toDateString()?tm:d.toLocaleDateString(cxLoc(),{day:'2-digit',month:'2-digit'})+' '+tm;
}
function cxLeft(iso){
 const m=Math.round((new Date(iso)-Date.now())/60000);if(isNaN(m)||m<=0)return'';
 const d=Math.floor(m/1440),h=Math.floor(m%1440/60);
 return d?tr('cxDH',d,h):h?tr('cxHM',h,m%60):tr('cxMin',m);
}
function cxWinLbl(mins){return mins===300?tr('cxS5'):mins===10080?tr('cxS7'):Math.round(mins/60)+(LANG==='en'?' h':' ч');}
// окна лимита → [{label,pct,full,lvl,reset}]; «исчерпан», если 100% или сервис сказал «лимит», а цифра ещё не доросла
function cxLimSegs(a){
 const ws=(a.windows||[]).filter(w=>w.pct!=null&&w.mins).sort((x,y)=>x.mins-y.mins).slice(0,2);
 const blocked=!!a.reached||a.usage_allowed===false,hasFull=ws.some(w=>w.pct>=100);
 return ws.map((w,i)=>{
  const p=Math.round(w.pct),full=p>=100||(blocked&&!hasFull&&i===0);
  return{label:cxWinLbl(w.mins),pct:p,full,lvl:full||p>=95?'bad':p>=80?'warn':'',reset:w.resets_at};
 });
}
// подписка: в шапке — только когда осталась неделя или меньше; полная дата всегда в подсказке
function cxLimSub(a){
 if(!a.sub_until||a.lapsed)return null;  // слёт на Free уже показан красным «план Free»
 const ms=new Date(a.sub_until)-Date.now();if(isNaN(ms))return null;
 const d=Math.ceil(ms/86400000);
 if(ms<=0)return{lvl:'bad',txt:tr('cxLimSubEnd')};
 return d>7?null:{lvl:d<=3?'bad':'warn',txt:tr('cxLimSubD',d)};
}
function cxLimHtml(a){
 if(a.login_required)return`<span class="cxl bad nobar"><b>${acctEsc(tr('cxLimLogin'))}</b></span>`;
 let h=cxLimSegs(a).map(s=>{
  const t=s.full&&cxClock(s.reset)?tr('cxLimUntil',cxClock(s.reset)):s.pct+'%';
  return`<span class="cxl ${s.lvl}" style="--p:${Math.min(100,s.pct)}"><i>${acctEsc(s.label.replace(/\s+/g,''))}</i><b>${acctEsc(t)}</b></span>`;
 }).join('');
 if(a.lapsed)h=`<span class="cxl bad nobar"><i>${acctEsc(tr('cxLimPlan'))}</i><b>Free</b></span>`+h;
 const sb=cxLimSub(a);
 if(sb)h+=`<span class="cxl ${sb.lvl} nobar"><i>${acctEsc(tr('cxLimSub'))}</i><b>${acctEsc(sb.txt)}</b></span>`;
 return h;
}
function cxLimTip(a){
 const L=[(a.label||String(a.email||'?').split('@')[0])+(a.plan?' · '+String(a.plan).replace(/^./,c=>c.toUpperCase()):'')];
 if(a.login_required){L.push(tr('cxLimLoginTip'));return L;}
 cxLimSegs(a).forEach(s=>{
  const r=s.reset?cxClock(s.reset):'',lf=s.reset?cxLeft(s.reset):'';
  L.push(s.label+': '+(s.full?tr('cxLimFull'):s.pct+'%')+(r?' · '+tr('cxLimReset',r)+(lf?' ('+tr('cxLimIn',lf)+')':''):''));
 });
 if(a.lapsed)L.push(tr('cxLimFreeTip'));
 if(a.sub_until&&!a.lapsed)L.push(tr('cxSubTitle',cxDate(a.sub_until)));
 return L;
}
function cxAccSummary(){
 const as=(cxData&&cxData.accounts)||[];
 return as.map(a=>{
  const w5=cxWin(a,300),w7=cxWin(a,10080),nm=(a.label||String(a.email||'?').split('@')[0]);
  const f=w=>w&&w.pct!=null?w.pct+'%':'?';
  return a.login_required?nm+': !':nm+(a.lapsed?' ⛔ Free':'')+' '+tr('cxS5')+' '+f(w5)+' · '+tr('cxS7')+' '+f(w7);
 }).join(' | ');
}
// ---- аварийный режим: красная карточка под профилями; включение — только словом, выключение — кнопкой ----
function cxeLeftTxt(e){
 const m=Math.max(0,Math.round((e.until-e.now)/60)),h=Math.floor(m/60);
 return h?tr('cxHM',h,m%60):tr('cxMin',m);
}
function cxeInfoHtml(e){
 const kv=(c,k,v)=>`<span class="cxpirow"><span class="cxpik ${c}">${acctEsc(k)}</span> ${acctEsc(v)}</span>`;
 const m={fl:['me','rd','rd','cl','ok']};
 return`<span class="cxpinfo"><span class="cxpirow"><span class="cxpik">${acctEsc(tr('cxpFlowLbl'))}:</span><span class="cxflow">${cxpSeq(tr('cxeFlow',e.hours).map((t,i)=>cxpChip(m.fl[i],t)))}</span></span>`
  +kv('can',tr('cxpCanL'),tr('cxeCan'))+kv('not',tr('cxpNotL'),tr('cxeNot',e.hours))
  +`<span class="cxpwhen"><b>${tr('cxpWhenLbl')}</b> ${acctEsc(tr('cxeWhen'))}</span></span>`;
}
function cxeHtml(e){
 if(!e||!(e.configured||e.active))return'';
 const open=CXP_INFO.has('emergency'),on=!!e.active;
 const rc=['cx','rd'],fc=['r','o','b','g'],fi=['🔓','🔁','⏱','🛑'];
 const infoBtn=`<button type="button" class="cxpi${open?' on':''}" data-info="emergency" aria-expanded="${open}" title="${acctEsc(tr('cxpInfo'))}" aria-label="${acctEsc(tr('cxpInfo'))}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>`;
 const name=`<span class="cxen"><span class="cxpnm caps">${on?acctEsc(tr('cxeOnT')):'🆘 '+acctEsc(tr('cxeN'))}</span>${on?'':`<span class="cxroute">${cxpSeq(tr('cxeRoute').map((t,i)=>cxpChip(rc[i],t)))}</span>`}</span>`;
 let body;
 if(on){
  const jr=(e.journal||[]).slice(-6).join('\n');
  const lim=e.until?tr('cxeUntil',cxClock(new Date(e.until*1000).toISOString()),cxeLeftTxt(e)):tr('cxeNoLimit',cxClock(new Date((e.since||e.now)*1000).toISOString()));
  body=`<span class="cxemtime">${acctEsc(lim)}</span>
   <span class="cxes">${acctEsc(tr('cxeStat',(e.services||[]).length,e.files||0,e.ssh))}</span>
   <button type="button" class="cxembtn off" data-emg="off">${acctEsc(tr('cxeOffBtn'))}</button>
   ${jr?`<div class="cxemj" title="${acctEsc(tr('cxeLog'))}">${acctEsc(jr)}</div>`:''}`;
 }else{
  const bad=e.last&&e.last.problems&&e.last.problems.length?`<span class="cxbwarn">${acctEsc(tr('cxeLastBad')+e.last.problems.join('; '))}</span>`:'';
  body=`<span class="cxes">${acctEsc(tr('cxeS',e.hours))}</span>
   <span class="cxpf">${tr('cxeF',e.hours).map((t,i)=>`<span class="${fc[i]}"><i>${fi[i]}</i>${acctEsc(t)}</span>`).join('')}</span>
   ${bad}<button type="button" class="cxembtn" data-emg="on">${acctEsc(tr('cxeBtn'))}</button>`;
 }
 return`<div class="cxemg${on?' on':''}" id="cxEmg"><span class="cxemm">${name}${body}${open?cxeInfoHtml(e):''}</span>${infoBtn}</div>`;
}
function cxeOn(){
 const e=cxbData&&cxbData.emergency;if(!e||!e.configured||e.active)return;
 const li=[tr('cxeConfProj')];
 if((e.services||[]).length)li.push(tr('cxeConfSvc',e.services.join(', ')));
 if(e.files||e.ssh)li.push(tr('cxeConfFiles'));
 if((e.services||[]).length)li.push(tr('cxeConfRoot'));
 li.push(tr('cxeConfEnd',e.hours));
 cxMenuClose();
 acctShow(`<h3>${tr('cxeConfTitle')}</h3>
  <div class="modalsub">${tr('cxeConfIntro')}</div>
  <ul class="cxeul">${li.map(t=>`<li>${acctEsc(t)}</li>`).join('')}</ul>
  <div class="modalsub">${acctEsc(tr('cxeConfWord',e.word))}</div>
  <input id="cxeWord" class="dlginp" autocomplete="off" spellcheck="false">
  <div class="modalfoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button><button id="cxeGo">${tr('cxeGo')}</button></div>`);
 $('#acctCancel').onclick=acctClose;
 const inp=$('#cxeWord'),go=$('#cxeGo');
 inp.addEventListener('keydown',ev=>{if(ev.key==='Enter')go.click();});
 go.onclick=async()=>{
  const w=inp.value.trim();go.disabled=true;
  try{
   const r=await acctPost('chatgpt/emergency/on',{word:w});
   toast(r.ok?tr('cxeOnToast'):'⚠ '+r.message);
   if(r.ok)acctClose();else go.disabled=false;
  }catch(err){toast('⚠ '+err);go.disabled=false;}
  await cxbLoad(true);
 };
 setTimeout(()=>inp.focus(),30);
}
async function cxeOff(){
 if(!confirm(tr('cxeOffAsk')))return;
 try{const r=await acctPost('chatgpt/emergency/off',{});toast(r.ok?r.message:'⚠ '+r.message);}
 catch(err){toast('⚠ '+err);}
 await cxbLoad(true);
}
function cxpRender(){
 const el=$('#cxp'),b=cxbData&&cxbData.bridge;
 if(!el)return;
 if(!b){el.innerHTML='';return;}
 const items=(b.profiles||[]).map(p=>{
  const act=p.id===b.profile,open=CXP_INFO.has(p.id);
  return`<div class="cxprof${act?' act':''}" role="radio" aria-checked="${act}" tabindex="0" data-id="${acctEsc(p.id)}"><span class="cxpr"></span>
   <span class="cxpt"><span class="cxpn">${cxpNameHtml(p)}</span><span class="cxps">${acctEsc(cxpSub(p))}</span>${cxpFeatHtml(p)}${open?cxpInfoHtml(p):''}</span>
   <button type="button" class="cxpi${open?' on':''}" data-info="${acctEsc(p.id)}" aria-expanded="${open}" title="${acctEsc(tr('cxpInfo'))}" aria-label="${acctEsc(tr('cxpInfo'))}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>
   ${p.builtin?'':`<button type="button" class="cxpx" title="${acctEsc(tr('cxpDel'))}" aria-label="${acctEsc(tr('cxpDel'))}" data-del="${acctEsc(p.id)}">×</button>`}</div>`;
 }).join('');
 el.innerHTML=`<div class="cxhead"><h2>${tr('cxpTitle')}</h2><span class="cxsub">${tr('cxpHint')}</span><button type="button" class="cxmx" data-close="1" title="${acctEsc(tr('cxpClose'))}" aria-label="${acctEsc(tr('cxpClose'))}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
  <div class="cxplist" role="radiogroup" aria-label="${acctEsc(tr('cxpTitle'))}">${items}</div>
  ${cxeHtml(cxbData.emergency)}
  ${!b.profile&&b.enabled?`<div class="cxpmanual">${tr('cxpManual')}</div>`:''}`;
}
function cxAll(){
 cxHdr();consTabs();
 const aw=$('#cxAccW'),bw=$('#cxBrW');
 aw.hidden=!(cxData&&cxData.available);bw.hidden=!(cxbData&&cxbData.available);
 aw.classList.toggle('open',!!CXP_SEC.acc);bw.classList.toggle('open',!!CXP_SEC.br);
 $('#cxAccT').textContent=tr('cxAccSec');$('#cxBrT').textContent=tr('cxBrSec');
 $('#cxWipeW').hidden=!cxAvail();$('#cxWipeT').textContent=tr('cxWipe');$('#cxWipe').title=tr('cxWipeTip');
 $('#cxAccS').textContent=cxAccSummary();
 const b=cxbData&&cxbData.bridge;
 $('#cxBrS').textContent=b?(b.token_set?'@'+(b.bot||'?'):''):'';
 cxpRender();
 if(!$('#cxPop').hidden)cxPopPlace();
 if(!$('#cxMenu').hidden)cxMenuPlace();
 if(!$('#cxQ').hidden){cxQRender();cxQPlace();}
}
function cxPopPlace(){
 const pop=$('#cxPop'),r=$('#cxGear').getBoundingClientRect();
 const top=Math.round(r.bottom+8);
 pop.style.top=top+'px';pop.style.maxHeight='calc(100vh - '+(top+12)+'px)';
 if(innerWidth>640){pop.style.right=Math.max(10,Math.round(innerWidth-r.right-4))+'px';pop.style.left='auto';}
 else{pop.style.right='';pop.style.left='';}
}
function cxPopOpen(){
 if(!cxAvail())return;
 cxMenuClose();cxQClose();
 $('#cxPop').hidden=false;$('#cxGear').setAttribute('aria-expanded','true');
 cxAll();cxPopPlace();cxbLoad(true);cxLoad();
}
function cxPopClose(){
 const pop=$('#cxPop');if(!pop||pop.hidden)return;
 pop.hidden=true;$('#cxGear').setAttribute('aria-expanded','false');
}
// ---- «Подключить Codex»: мастер из трёх шагов — установка, вход в ChatGPT, бот Telegram (по желанию) ----
// Пока Codex не установлен, вместо блока Codex в шапке — кнопка с мастером. Мастер ведёт до конца настройки: после установки сам
// раскрывает шаг 2 (вход в ChatGPT), после входа — шаг 3 (бот; необязателен, есть «Пропустить этот шаг и завершить»).
// Где мастер остановился, считаем по данным сервера; флаг «мастер начат» — в localStorage этого браузера (только удобство).
let ciData=null,ciTimer=null,ciBusy=false,ciAsked=null,ciLast=0,ciAwait=0;  // ciAsked — ответ на «Поручить Claude»: пока он есть, окно ждёт, что Claude сам запустит установку; ciAwait — шаг, с которого человек ушёл во вход (вернуть окно, когда шаг сменится)
function ciNeedInst(){return!!(cxbData&&cxbData.available===false&&!(cxData&&cxData.available));}
function ciWizOn(){try{return localStorage.getItem('cxWiz')==='1';}catch(e){return false;}}
function ciWizSet(on){try{if(on)localStorage.setItem('cxWiz','1');else localStorage.removeItem('cxWiz');}catch(e){}}
function ciAcc(){return((cxData&&cxData.accounts)||[]).find(a=>!a.login_required)||null;}  // аккаунт, в который уже вошли
// на каком шаге мастер: 1 — установка, 2 — вход в ChatGPT, 3 — бот Telegram, 0 — мастер не нужен
function ciStage(){
 if(ciNeedInst())return 1;
 if(!ciWizOn()||!cxAvail())return 0;
 if(!ciAcc())return 2;
 const b=cxbData&&cxbData.bridge;
 return b&&b.token_set?0:3;
}
function ciShow(){return ciStage()>0;}
function ciHdr(){
 const b=$('#cxInst');if(!b)return;
 const st=ciStage(),on=st>0;b.hidden=!on;
 if(ciNeedInst())ciWizSet(true);  // пока Codex нет, мастер уже начат — дальше он ведёт до конца
 else if(!on&&ciWizOn()&&cxAvail())ciWizSet(false);  // вход и бот на месте — настройка закончена
 if(on){
  if(st===1&&cxbData.install)ciData=cxbData.install;
  b.title=tr('cxiTip');b.setAttribute('aria-label',tr('cxiTip'));
  ciSync(st);
 }else ciClose();
}
// шаг сменился (вошли в ChatGPT, подключили бота): окно перерисовывается само; ушёл во вход и окно закрылось — возвращаем
function ciSync(st){
 const pop=$('#cxInstPop');if(!pop)return;
 if(ciAwait&&st>ciAwait){ciAwait=0;if(pop.hidden)ciOpen();}
 if(pop.hidden)return;
 const f=document.activeElement;
 if(st===ciLast&&f&&pop.contains(f)&&f.tagName==='INPUT')return;  // человек вводит токен — не перерисовываем под руками
 ciRender();
}
// у не подключённого Codex кнопки «Codex +» в шапке нет (её роль у призрачной плитки): окно мастера встаёт под плитку
function ciAnchor(){const b=$('#cxInst');return b&&b.offsetParent!==null?b:(document.querySelector('#wkAgents .wk-seg[data-ag="codex"]')||b)}
function ciPlace(){
 const pop=$('#cxInstPop'),r=ciAnchor().getBoundingClientRect();
 const top=Math.round(r.bottom+8);
 pop.style.top=top+'px';pop.style.maxHeight='calc(100vh - '+(top+12)+'px)';
 if(innerWidth>640){pop.style.left='auto';pop.style.right=Math.max(10,Math.round(innerWidth-r.right-4))+'px';}
 else{pop.style.right='';pop.style.left='';}
}
// шаг 1 раскрыт: ход установки, подсказки про Node.js, кнопки «Установить» / «Поручить Claude» / «Скопировать промт»
function ciBody1(d,st,run){
 let h='';
 if(run){
  h+=`<p class="cxinote"><span class="cxispin"></span>${tr('cxiRun')}</p>`;
  if(d.log)h+=`<pre class="cxilog" id="cxiLog">${acctEsc(d.log)}</pre>`;
  h+=`<div class="cxirow"><button class="ghostbtn" onclick="ciCancel()">${tr('cxiCancel')}</button></div>`;
 }else{
  if(st==='failed'){
   h+=`<p class="cxinote bad">${tr('cxiFail')}</p><pre class="cxilog">${acctEsc(d.err||d.log||'')}</pre>`;
  }else if(d.ready){
   h+=`<p class="cxinote">${tr('cxiNodeOk',acctEsc(d.node||''))}</p>`;
  }else if(d.node||d.npm){
   h+=`<p class="cxinote warn">${tr('cxiNodeOld',acctEsc(d.node||'—'),d.npm?'':tr('cxiNoNpm'))}</p>`;
  }else if(d.node===null&&d.npm===false){
   h+=`<p class="cxinote warn">${tr('cxiNoNode')}</p>`;
  }
  if(ciAsked)h+=`<p class="cxinote ${ciAsked.ok?'':'bad'}">${ciAsked.ok?tr(ciAsked.seen?'cxiAsked':'cxiAskedUnsure'):acctEsc(ciAsked.message||'')}</p>`;
  // Node.js есть → одна кнопка «Установить». Иначе (или установка не вышла) главное — поручить Claude, он на этой машине уже работает
  const askBtn=(main)=>`<button ${main?'id="cxiGo" ':'class="ghostbtn" id="cxiAsk" '}onclick="ciAsk()">${tr(ciAsked&&ciAsked.ok?'cxiAskAgain':'cxiAsk')}</button>`;
  const copyBtn=`<button class="ghostbtn" id="cxiCopy" onclick="ciCopy(this)">${tr('cxiCopy')}</button>`;
  h+=`<div class="cxirow">`;
  if(d.ready||st==='failed'){
   h+=d.ready?`<button id="cxiGo" onclick="ciStart()">${tr(st==='failed'?'cxiRetry':'cxiInstall')}</button>`+askBtn(false):askBtn(true);
   h+=copyBtn;
  }else h+=askBtn(true)+copyBtn+`<button class="ghostbtn" id="cxiRe" onclick="ciRecheck()">${tr('cxiRecheck')}</button>`;
  h+=`</div>`;
 }
 return h;
}
// шаг 2 раскрыт: вход в ChatGPT по коду устройства — то же окно, что у «+» в ⚙
function ciBody2(){
 return `<p class="cxinote">${tr('cxiS2Hint')}</p><div class="cxirow"><button id="cxiLogin" onclick="ciLogin()">${tr('cxiLogin')}</button></div>`;
}
// шаг 3 раскрыт: токен бота и chat_id прямо здесь; шаг необязательный — «Пропустить этот шаг и завершить»
function ciBody3(){
 const b=(cxbData&&cxbData.bridge)||{};
 return `<p class="cxinote">${tr('cxiS3Hint')}</p>
  <input id="cxiTok" class="dlginp" type="password" autocomplete="off" spellcheck="false" aria-label="${acctEsc(tr('cxbTokLbl'))}" placeholder="${acctEsc(tr('cxbTokPh'))}">
  <label class="dlglbl" for="cxiChat">${tr('cxbChat')}</label>
  <input id="cxiChat" class="dlginp" inputmode="numeric" autocomplete="off" value="${acctEsc(b.chat_id||'')}">
  <div class="cxirow"><button id="cxiBot" onclick="ciBot()">${tr('cxiBot')}</button><button class="ghostbtn" id="cxiSkip" onclick="ciFinish(true)">${tr('cxiSkip')}</button></div>`;
}
function ciRender(){
 const pop=$('#cxInstPop');if(!pop||pop.hidden)return;
 const d=ciData||{},st=d.state||'idle',run=st==='running';
 const stage=ciStage()||1;ciLast=stage;
 $('#cxInstTitle').textContent=tr('cxiTitle');
 const one=run||d.ready;  // «одной кнопкой» — только когда Node.js уже есть и кнопка «Установить» правда есть
 const acc=ciAcc();
 const KEY=['','cxiS1','cxiS2','cxiS3'],KOK=['','cxiS1ok','cxiS2ok'];
 const text=i=>i<stage?tr(KOK[i],acctEsc((acc&&acc.email)||'')):tr(i===1&&!one?'cxiS1n':KEY[i]);
 const body=[ciBody1,ciBody2,ciBody3][stage-1];
 const steps=[1,2,3].map(i=>`<li class="${i<stage?'done':i===stage?'cur':''}"><b>${i<stage?'✓':i}</b><div class="cxist"><span>${text(i)}</span>${i===stage?`<div class="cxisb">${body(d,st,run)}</div>`:''}</div></li>`).join('');
 const h=`<p class="cxilead">${tr('cxiLead')}</p><ol class="cxisteps">${steps}</ol>`;
 const keep=$('#cxiLog');const atEnd=keep?keep.scrollTop+keep.clientHeight>=keep.scrollHeight-4:true;
 const typed={};['cxiTok','cxiChat'].forEach(id=>{const e=$('#'+id);if(e&&e.value)typed[id]=e.value;});  // введённое не теряем при перерисовке
 $('#cxInstB').innerHTML=h;
 Object.keys(typed).forEach(id=>{const e=$('#'+id);if(e)e.value=typed[id];});
 const lg=$('#cxiLog');if(lg&&atEnd)lg.scrollTop=lg.scrollHeight;
 ciPlace();
}
function ciOpen(){
 if(!ciShow())return;
 cxPopClose();cxMenuClose();cxQClose();
 $('#cxInstPop').hidden=false;$('#cxInst').setAttribute('aria-expanded','true');
 ciRender();
 if(ciStage()===1)ciLoad();  // ход установки нужен только на шаге 1
}
function ciClose(){
 const pop=$('#cxInstPop');if(!pop||pop.hidden)return;
 pop.hidden=true;$('#cxInst').setAttribute('aria-expanded','false');
 clearTimeout(ciTimer);ciTimer=null;ciAsked=null;
}
async function ciLoad(){
 if(ciBusy)return;ciBusy=true;
 try{
  const r=await fetch(API+'chatgpt/install?token='+TOKEN+'&lang='+LANG);const d=await r.json();
  if(d&&d.ok){ciData=d;await ciAfter(d);}
 }catch(e){}
 finally{ciBusy=false;}
 clearTimeout(ciTimer);ciTimer=null;
 if(!$('#cxInstPop').hidden&&ciStage()===1){
  if(ciData&&ciData.state==='running')ciTimer=setTimeout(ciLoad,1500);  // пока идёт установка — живой ход
  else if(ciAsked&&ciAsked.ok)ciTimer=setTimeout(ciLoad,3000);  // Claude ставит Node.js и запускает установку сам — ждём
 }
}
// установка закончилась: панель узнаёт, что Codex есть, и мастер сам переходит к шагу 2 (окно остаётся открытым)
async function ciAfter(d){
 if(ciStage()!==1)return;  // шаг 1 уже позади (данные успели обновиться опросом шапки)
 ciRender();
 if(d.state==='done'||d.available){
  const v=d.version||'';
  ciWizSet(true);
  await cxbLoad(true);await cxLoad(true);
  ciAsked=null;
  if(cxAvail()){toast(tr('cxiDone',v));ciHdr();ciRender();}
 }
}
// шаг 2: окно входа по коду; когда войдут, опрос шапки увидит аккаунт и мастер раскроет шаг 3 (ciSync)
function ciLogin(){ciAwait=ciStage();cxAdd();}
// шаг 3: токен бота и chat_id → бот подключён, мост включён, мастер завершён
async function ciBot(){
 const tok=(($('#cxiTok')||{}).value||'').trim(),chat=(($('#cxiChat')||{}).value||'').trim();
 if(!tok){toast('⚠ '+tr('cxiBotNoTok'));return;}
 if(!/^-?[0-9]{3,}$/.test(chat)){toast('⚠ '+tr('cxiBotNoChat'));return;}
 const bt=$('#cxiBot');bt.disabled=true;
 try{
  const r=await acctPost('chatgpt/bridge/token',{token:tok});
  if(!r.ok){toast('⚠ '+r.message);bt.disabled=false;return;}
  const s=await acctPost('chatgpt/bridge/save',{chat_id:chat,enabled:true});
  await cxbLoad(true);
  ciFinish(false,s.ok?r.message:'⚠ '+s.message);
 }catch(e){toast('⚠ '+e);bt.disabled=false;}
}
// конец мастера: кнопка из шапки уходит; skipped — бота не подключали
function ciFinish(skipped,msg){
 ciWizSet(false);ciClose();ciHdr();
 toast(msg||tr(skipped?'cxiSkipped':'cxiAllDone'));
}
async function ciStart(){
 const b=$('#cxiGo');if(b)b.disabled=true;
 try{
  const d=await acctPost('chatgpt/install/start',{});
  if(!d.ok){toast('⚠ '+d.message);ciData=Object.assign(ciData||{},d,{state:'failed',err:d.message});ciRender();return;}
  ciData=d;ciRender();ciLoad();
 }catch(e){toast('⚠ '+e);}
}
async function ciCancel(){try{ciData=await acctPost('chatgpt/install/cancel',{});}catch(e){}ciRender();}
// «Поручить Claude»: панель вставляет в консоль Claude готовый промт (Node.js, запуск установки), окно ждёт результата
async function ciAsk(){
 document.querySelectorAll('#cxiGo,#cxiAsk').forEach(x=>x.disabled=true);
 try{ciAsked=await acctPost('chatgpt/install/ask-claude',{});}catch(e){ciAsked={ok:false,message:String(e)};}
 ciRender();
 if(ciAsked.ok)ciLoad();
}
// запасной путь: тот же промт — в буфер, человек вставит его в консоль Claude сам
async function ciCopy(b){
 try{const r=await fetch(API+'chatgpt/install/prompt?token='+TOKEN+'&lang='+LANG);const d=await r.json();if(d&&d.prompt)await acctCopy(b,d.prompt);}catch(e){toast('⚠ '+e);}
}
async function ciRecheck(){
 const b=$('#cxiRe');if(b)b.disabled=true;
 await cxbLoad(true);
 if(cxbData&&cxbData.install)ciData=cxbData.install;
 ciRender();
}
$('#cxInst').addEventListener('click',()=>{$('#cxInstPop').hidden?ciOpen():ciClose();});
$('#cxInstX').addEventListener('click',ciClose);
// выбор профиля: на ПК боковая шторка справа, на телефоне — под кнопкой «>_ Профиль ▾» (просьба владельца); выбрал строку — применилось и закрылось
let cxmPushed=false,cxmBacking=false;  // шаг в истории браузера: кнопка «назад» закрывает шторку, а не страницу
function cxMenuPlace(){
 const m=$('#cxMenu');
 if(innerWidth>640){m.style.top=m.style.left=m.style.right=m.style.maxHeight='';return;}  // ПК: шторка стоит по CSS
 const top=Math.round($('#cxBtn').getBoundingClientRect().bottom+8);
 m.style.top=top+'px';m.style.maxHeight='calc(100vh - '+(top+12)+'px)';m.style.left='';m.style.right='';
}
function cxMenuOpen(){
 if(!cxAvail())return;
 cxPopClose();cxQClose();
 $('#cxMenu').hidden=false;$('#cxMenuScrim').hidden=false;$('#cxBtn').setAttribute('aria-expanded','true');
 if(!cxmPushed&&!cxmBacking){try{history.pushState({cxm:1},'');cxmPushed=true;}catch(e){}}
 cxpRender();cxMenuPlace();cxbLoad(true);
}
function cxMenuClose(fromPop){
 const m=$('#cxMenu');if(!m||m.hidden)return;
 m.hidden=true;$('#cxMenuScrim').hidden=true;$('#cxBtn').setAttribute('aria-expanded','false');
 if(cxmPushed){cxmPushed=false;if(fromPop!==true){cxmBacking=true;try{history.back();}catch(e){cxmBacking=false;}}}
}
addEventListener('popstate',()=>{
 if(cxmBacking){cxmBacking=false;return;}
 if(cxmPushed){cxmPushed=false;cxMenuClose(true);}
});
// ---- быстрая смена модели и усилия: кнопка в шапке и маленькая панель под ней (те же настройки, что в окне ⚙ → Аккаунты) ----
// Аккаунт — тот, чьи лимиты видны в шапке (им работает мост). Пустое значение = «по умолчанию Codex».
function cxQCur(a){
 const ms=a.models||[],def=ms.find(m=>m.is_default)||ms[0];
 const known=!!a.model&&ms.some(m=>m.id===a.model);
 const mod=(known&&ms.find(m=>m.id===a.model))||def;
 const efs=mod.efforts||[];
 const ef=a.effort&&efs.includes(a.effort)?a.effort:'';
 return{ms,def,known,mod,efs,ef,eff:ef||mod.default_effort||'',name:a.model&&!known?a.model:mod.name};
}
function cxQBtn(){
 const btn=$('#cxMod');if(!btn)return;
 const a=cxLimAcc(),ok=!!(a&&(a.models||[]).length);
 btn.hidden=!ok;
 if(!ok){cxQClose();return;}
 const c=cxQCur(a);
 $('#cxModN').textContent=c.name;$('#cxModE').textContent=c.eff;
 const t=tr('cxQTip')+': '+c.name+(c.eff?' · '+c.eff:'');
 btn.title=t;btn.setAttribute('aria-label',t);
}
function cxQRender(){
 const q=$('#cxQb'),a=cxLimAcc();if(!q)return;
 if(!a||!(a.models||[]).length){q.innerHTML='';return;}
 const c=cxQCur(a),multi=((cxData&&cxData.accounts)||[]).length>1;
 const mrow=(id,name,on)=>`<button type="button" class="cxqm${on?' on':''}" role="radio" aria-checked="${on}" data-m="${acctEsc(id)}"><i class="cxqr"></i><span>${acctEsc(name)}</span></button>`;
 let ml=mrow('',tr('cxDefault')+' · '+c.def.name,!a.model);
 if(a.model&&!c.known)ml+=mrow(a.model,a.model,true);
 const hid=(typeof lastSnap!=='undefined'&&lastSnap&&lastSnap.config&&lastSnap.config.codex_hidden)||[];  // без галочки «в быстром меню» — не показываем (кроме выбранной)
 ml+=c.ms.filter(m=>!hid.includes(m.id)||(c.known&&m.id===a.model)).map(m=>mrow(m.id,m.name,c.known&&m.id===a.model)).join('');
 const erow=(e,label,on)=>`<button type="button" class="cxqe${on?' on':''}" role="radio" aria-checked="${on}" data-e="${acctEsc(e)}">${acctEsc(label)}</button>`;
 const el=c.efs.length?erow('',tr('cxDefault')+(c.mod.default_effort?' · '+c.mod.default_effort:''),!c.ef)+c.efs.map(e=>erow(e,e,e===c.ef)).join(''):'';
 q.innerHTML=`<div class="cxqh"><span>${tr('cxModelTip')}</span>${multi?`<span class="cxqa">${acctEsc(a.label||a.email||a.slot)}</span>`:''}</div>
  <div class="cxqlist" role="radiogroup" aria-label="${acctEsc(tr('cxModelTip'))}">${ml}</div>
  ${el?`<div class="cxqh">${tr('cxEffortTip')}</div><div class="cxqeff" role="radiogroup" aria-label="${acctEsc(tr('cxEffortTip'))}">${el}</div>`:''}`;
}
function cxQPlace(){
 const m=$('#cxQ'),r=$('#cxMod').getBoundingClientRect(),top=Math.round(r.bottom+8);
 m.style.top=top+'px';m.style.maxHeight='calc(100vh - '+(top+12)+'px)';
 if(innerWidth>640){const w=Math.min(330,innerWidth-20);m.style.left=Math.max(10,Math.min(Math.round(r.left),innerWidth-w-10))+'px';m.style.right='auto';}
 else{m.style.left='';m.style.right='';}
}
function cxQOpen(){
 if(!cxAvail()||$('#cxMod').hidden)return;
 cxPopClose();cxMenuClose();
 cxQRender();
 $('#cxQ').hidden=false;$('#cxMod').setAttribute('aria-expanded','true');
 cxQPlace();cxLoad();
}
function cxQClose(){
 const m=$('#cxQ');if(!m||m.hidden)return;
 m.hidden=true;$('#cxMod').setAttribute('aria-expanded','false');
}
// model/effort: null — это поле не меняем. Модель можно менять несколько раз подряд, выбор усилия — последний шаг, панель закрывается.
let cxQBusy=false;
async function cxQSet(model,effort){
 if(cxQBusy)return;
 const a=cxLimAcc();if(!a)return;
 const c=cxQCur(a),curM=a.model||'';
 const mid=model===null?curM:model;
 const mod=c.ms.find(x=>x.id===mid)||c.def;
 let ef=effort===null?c.ef:effort;
 if(ef&&mod.efforts&&!mod.efforts.includes(ef))ef='';  // у другой модели может не быть такого усилия — сбрасываем, чтобы сервер не отказал
 if(mid===curM&&ef===c.ef){if(effort!==null)cxQClose();return;}
 if(!await window.fleetAsk($('#cxMod'),tr('askCxSet',model!==null?mid+(ef&&ef!==c.ef?' · '+ef:''):ef),tr('askYes')))return;
 const fast=!!(a.fast&&mod.fast);
 cxQBusy=true;$('#cxQ').classList.add('busy');
 try{const r=await acctPost('chatgpt/prefs',{slot:a.slot,model:mid,effort:ef,fast});toast(r.ok===false?'⚠ '+r.message:r.message);}
 catch(err){toast('⚠ '+err);}
 cxQBusy=false;$('#cxQ').classList.remove('busy');
 if(effort!==null)cxQClose();
 await cxLoad(true);
}
async function cxpApply(id,confirm){
 if(cxpBusy)return;cxpBusy=true;
 try{
  const r=await acctPost('chatgpt/bridge/profile/apply',{id,confirm:confirm||''});
  if(!r.ok&&/подтверждаю|confirm/i.test(r.message||'')&&!confirm){cxpBusy=false;cxpConfirm(id);return;}
  toast(r.ok?r.message:'⚠ '+r.message);
 }catch(e){toast('⚠ '+e);}
 cxpBusy=false;
 await cxbLoad(true);
}
function cxpConfirm(id){
 acctShow(`<h3>${tr('cxpConfTitle')}</h3>
  <div class="modalsub">${tr('cxbConfirm')}</div>
  <input id="cxpConf" class="dlginp" autocomplete="off" spellcheck="false">
  <div class="modalfoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button><button id="cxpConfGo">${tr('cxpApply')}</button></div>`);
 $('#acctCancel').onclick=acctClose;
 const inp=$('#cxpConf'),go=$('#cxpConfGo');
 inp.addEventListener('keydown',e=>{if(e.key==='Enter')go.click();});
 go.onclick=()=>{const w=inp.value.trim();acctClose();cxpApply(id,w||'-');};
 setTimeout(()=>inp.focus(),30);
}
async function cxpDelete(id){
 const p=((cxbData&&cxbData.bridge&&cxbData.bridge.profiles)||[]).find(x=>x.id===id);
 if(!p||!confirm(tr('cxpDelAsk',cxpName(p))))return;
 try{const r=await acctPost('chatgpt/bridge/profile/delete',{id});toast(r.ok?r.message:'⚠ '+r.message);}
 catch(e){toast('⚠ '+e);}
 await cxbLoad(true);
}
$('#cxBtn').addEventListener('click',()=>{$('#cxMenu').hidden?cxMenuOpen():cxMenuClose();});
$('#cxGear').addEventListener('click',()=>{$('#cxPop').hidden?cxPopOpen():cxPopClose();});
$('#cxMod').addEventListener('click',()=>{$('#cxQ').hidden?cxQOpen():cxQClose();});
$('#cxQ').addEventListener('click',e=>{
 const m=e.target.closest('[data-m]'),f=e.target.closest('[data-e]');
 if(m)cxQSet(m.dataset.m,null);else if(f)cxQSet(null,f.dataset.e);
});
$('#cxPopX').addEventListener('click',cxPopClose);
$('#cxp').addEventListener('click',e=>{
 if(e.target.closest('[data-close]')){e.stopPropagation();cxMenuClose();return;}
 const d=e.target.closest('[data-del]');
 if(d){e.stopPropagation();cxpDelete(d.dataset.del);return;}
 const i=e.target.closest('[data-info]');
 if(i){
  e.stopPropagation();const id=i.dataset.info;
  CXP_INFO.has(id)?CXP_INFO.delete(id):CXP_INFO.add(id);
  cxpRender();cxMenuPlace();
  const nb=$('#cxp').querySelector('[data-info="'+id+'"]');if(nb)nb.focus();
  return;
 }
 if(e.target.closest('.cxpinfo'))return;
 const em=e.target.closest('[data-emg]');
 if(em){e.stopPropagation();em.dataset.emg==='on'?cxeOn():cxeOff();return;}
 if(e.target.closest('.cxemg'))return;
  const r=e.target.closest('.cxprof');if(r){cxMenuClose();cxpApply(r.dataset.id);}
});
$('#cxp').addEventListener('keydown',e=>{
 const r=e.target.closest&&e.target.closest('.cxprof');
 if(r&&e.target===r&&(e.key==='Enter'||e.key===' ')){e.preventDefault();cxMenuClose();cxpApply(r.dataset.id);}
});
document.querySelectorAll('.cxacch').forEach(h=>h.addEventListener('click',()=>{
 const k=h.dataset.sec;CXP_SEC[k]=!CXP_SEC[k];
 try{localStorage.setItem('cxpSec',JSON.stringify(CXP_SEC));}catch(e){}
 h.parentElement.classList.toggle('open',!!CXP_SEC[k]);
}));
document.addEventListener('pointerdown',e=>{
 if(e.target.closest('#acctScrim,#scrim'))return;
 if(!$('#cxPop').hidden&&!e.target.closest('#cxPop,#cxGear'))cxPopClose();
 if(!$('#cxInstPop').hidden&&!e.target.closest('#cxInstPop,#cxInst'))ciClose();
 if(!$('#cxMenu').hidden&&!e.target.closest('#cxMenu,#cxBtn'))cxMenuClose();
 if(!$('#cxQ').hidden&&!e.target.closest('#cxQ,#cxMod'))cxQClose();
});
document.addEventListener('keydown',e=>{
 if(e.key==='Escape'&&$('#acctScrim').hidden&&$('#scrim').hidden){cxPopClose();cxMenuClose();cxQClose();ciClose();}
});
addEventListener('resize',()=>{if(!$('#cxInstPop').hidden)ciPlace();if(!$('#cxPop').hidden)cxPopPlace();if(!$('#cxMenu').hidden)cxMenuPlace();if(!$('#cxQ').hidden)cxQPlace();});
async function cxLoad(refresh){
 if(cxBusy){if(refresh)cxAgain=true;return;}
 cxBusy=true;
 try{
  const r=await fetch(API+'chatgpt?token='+TOKEN+(refresh?'&refresh=1':''));const d=await r.json();
  if(d&&d.ok){cxData=d;cxRender();cxbRender();cxAll();}
 }catch(e){}
 finally{cxBusy=false;if(cxAgain){cxAgain=false;cxLoad(true);}}
}
async function cxRenew(slot,btn){
 if(!await window.fleetAsk(btn,tr('askRenew'),tr('askYes')))return;
 const orig=btn?btn.textContent:'';
 if(btn){btn.disabled=true;btn.textContent=tr('cxRenewing');}
 try{const r=await acctPost('chatgpt/renew',{slot});toast(r.message);}
 catch(err){toast('⚠ '+err);}
 if(btn){btn.disabled=false;btn.textContent=orig;}
 cxLoad();
}
function cxLaunch(slot,btn){const a=cxAcc(slot);if(a&&a.launch)acctCopy(btn,a.launch);}
async function cxPref(slot,src){
 const a=cxAcc(slot);if(!a)return;
 if(!await window.fleetAsk(src&&(src.closest('label')||src),tr('askCxPref'),tr('askYes'))){cxRender();return;}
 const m=$('#cxm-'+slot),e=$('#cxe-'+slot),f=$('#cxf-'+slot);
 const ms=a.models||[];
 const mod=ms.find(x=>x.id===m.value)||ms.find(x=>x.is_default)||null;
 // у другой модели может не быть такого усилия или режима Fast — сбрасываем, чтобы сервер не отказал
 let effort=e?e.value:'',fast=!!(f&&f.checked);
 if(mod&&effort&&mod.efforts&&!mod.efforts.includes(effort))effort='';
 if(!(mod&&mod.fast))fast=false;
 [m,e,f].forEach(x=>{if(x)x.disabled=true;});
 try{const r=await acctPost('chatgpt/prefs',{slot,model:m.value,effort,fast});toast(r.message);}
 catch(err){toast('⚠ '+err);}
 cxLoad(true);
}
function cxStop(slot,cancel){
 clearInterval(cxPoll);cxPoll=null;
 if(cancel)acctPost('chatgpt/login/cancel',{slot}).catch(()=>{});
}
// slot не задан — новая карточка, задан — перелогин существующей
function cxReloginAsk(slot,btn){window.fleetAsk(btn,tr('askRelogin'),tr('askYes')).then(ok=>{if(ok)cxAdd(slot)})}
function cxAdd(slot){
 if(slot){
  const a=cxAcc(slot)||{};
  cxStart(slot,'',`<h3>${tr('cxRelTitle')}</h3><div class="modalsub"><b>${acctEsc(a.email||slot)}</b> · ${acctEsc(slot)}</div>`);
  return;
 }
 acctShow(`<h3>${tr('cxAddTitle')}</h3><div class="modalsub">${tr('cxAddSub')}</div>
  <label class="dlglbl" for="cxLabel">${tr('cxLabelLbl')}</label>
  <input id="cxLabel" class="dlginp" maxlength="60" autocomplete="off" spellcheck="false" placeholder="${tr('cxLabelPh')}">
  <div class="dlgerr" id="acctErr" hidden></div>
  <div class="modalfoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button><button id="cxGo">${tr('cxGetCode')}</button></div>`);
 $('#acctCancel').onclick=acctClose;
 const lb=$('#cxLabel');
 lb.addEventListener('keydown',ev=>{if(ev.key==='Enter')$('#cxGo').click();});
 $('#cxGo').onclick=()=>cxStart('',lb.value.trim(),`<h3>${tr('cxAddTitle')}</h3>`);
 setTimeout(()=>lb.focus(),30);
}
async function cxStart(slot,label,head){
 acctShow(`${head}<div class="modalsub" id="cxWait0">${tr('addStarting')}</div><div class="dlgerr" id="acctErr" hidden></div>
  <div class="modalfoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button></div>`);
 $('#acctCancel').onclick=acctClose;
 acctBusy=true;
 let d;
 try{d=await acctPost('chatgpt/login/start',{slot,label});}catch(e){d={ok:false,message:String(e)};}
 acctBusy=false;
 if(!d.ok){const w=$('#cxWait0');if(w)w.hidden=true;acctErr(d.message);return;}
 cxStep2(head,d,slot,label);
}
function cxStep2(head,d,slot,label){
 acctShow(`${head}
  <div class="dlgstep"><i>1</i><span>${tr('cxStep1')}</span></div>
  <div class="dlgurl">${acctEsc(d.url)}</div>
  <div class="dlgrow"><button id="addOpen">${tr('addOpen')}</button><button class="ghostbtn" id="addCopy">${tr('addCopy')}</button></div>
  <div class="dlgstep"><i>2</i><span>${tr('cxStep2')}</span></div>
  <div class="cxcode" id="cxCode">${acctEsc(d.code)}</div>
  <div class="dlgrow"><button class="ghostbtn" id="cxCopyCode">${tr('addCopy')}</button></div>
  <div class="cxwait" id="cxWait">${tr('cxWait','15:00')}</div>
  <div class="dlgerr" id="acctErr" hidden></div>
  <div class="modalfoot" id="cxFoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button></div>`);
 $('#acctCancel').onclick=acctClose;
 $('#addOpen').onclick=()=>window.open(d.url,'_blank');
 $('#addCopy').onclick=()=>acctCopy($('#addCopy'),d.url);
 $('#cxCopyCode').onclick=()=>acctCopy($('#cxCopyCode'),d.code);
 const sl=d.slot;
 clearInterval(cxPoll);
 // окно закрыли — попытку отменяем на сервере, иначе процесс входа провисит до конца срока кода
 cxPoll=setInterval(async()=>{
  if(!$('#cxWait')){cxStop(sl,true);return;}
  let s;try{s=await acctPost('chatgpt/login/status',{slot:sl});}catch(e){return;}
  const w=$('#cxWait');
  if(!w){cxStop(sl,true);return;}
  if(s.state==='waiting'){
   const l=Math.max(0,s.left-60);  // код живёт 15 минут, сервер ждёт ещё минуту на запись файла
   w.textContent=tr('cxWait',Math.floor(l/60)+':'+String(l%60).padStart(2,'0'));
   return;
  }
  cxStop(sl,true);  // done / failed / none — запись о попытке больше не нужна
  if(s.state==='done'){acctClose();toast(tr('cxDone',s.email,s.plan));cxLoad(true);return;}
  w.textContent='';acctErr(s.message||tr('cxFailed'));
  $('#cxFoot').insertAdjacentHTML('beforeend',`<button id="cxRetry">${tr('cxRetry')}</button>`);
  $('#cxRetry').onclick=()=>slot?cxAdd(slot):cxStart('',label,head);
 },2000);
}
// свежие данные аккаунтов: опрос мог быть в пути со старым ответом — ждём его и повторный (cxAgain), иначе флаг мастера снимется по устаревшему списку
async function cxSettle(){
 await cxLoad(true);
 for(let i=0;i<40&&(cxBusy||cxAgain);i++)await new Promise(r=>setTimeout(r,150));
}
// аккаунтов не осталось → «Codex +» возвращается (мастер со шага 2)
function cxAfterDel(){
 if(cxAvail()&&!(((cxData&&cxData.accounts)||[]).length)){ciWizSet(true);cxPopClose();}
 cxHdr();
}
function cxWipe(){
 const word=tr('delWord');
 acctShow(`<h3>${tr('cxWipeTitle')}</h3>
  <div class="dlgwarn">${tr('cxWipeWarn')}</div>
  <label class="dlglbl" for="delInp">${tr('delType',word)}</label>
  <input id="delInp" class="dlginp" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${word}">
  <div class="dlgerr" id="acctErr" hidden></div>
  <div class="modalfoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button><button class="btn-danger" id="delGo" disabled>${tr('delGo')}</button></div>`);
 $('#acctCancel').onclick=acctClose;
 const inp=$('#delInp'),go=$('#delGo');
 inp.addEventListener('input',()=>{go.disabled=inp.value.trim().toLowerCase()!==word;});
 inp.addEventListener('keydown',e=>{if(e.key==='Enter'&&!go.disabled)go.click();});
 go.onclick=async()=>{
  if(acctBusy||go.disabled)return;
  acctBusy=true;go.disabled=true;go.textContent=tr('delWorking');acctErr('');
  try{
   const d=await acctPost('chatgpt/wipe',{confirm:inp.value});
   acctBusy=false;
   if(d.ok){acctClose();toast(d.message);await cxSettle();cxbLoad(true);ciWizSet(true);cxPopClose();cxHdr();return;}
   acctErr(d.message);go.textContent=tr('delGo');go.disabled=inp.value.trim().toLowerCase()!==word;
  }catch(e){acctBusy=false;acctErr(String(e));go.textContent=tr('delGo');go.disabled=false;}
 };
 setTimeout(()=>inp.focus(),30);
}
function cxDel(slot){
 const a=cxAcc(slot)||{};const word=tr('delWord');
 acctShow(`<h3>${tr('cxDelTitle')}</h3>
  <div class="modalsub"><b>${acctEsc(a.email||slot)}</b> · ${acctEsc(slot)}</div>
  <div class="dlgwarn">${tr('cxDelWarn')}</div>
  <label class="dlglbl" for="delInp">${tr('delType',word)}</label>
  <input id="delInp" class="dlginp" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${word}">
  <div class="dlgerr" id="acctErr" hidden></div>
  <div class="modalfoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button><button class="btn-danger" id="delGo" disabled>${tr('delGo')}</button></div>`);
 $('#acctCancel').onclick=acctClose;
 const inp=$('#delInp'),go=$('#delGo');
 inp.addEventListener('input',()=>{go.disabled=inp.value.trim().toLowerCase()!==word;});
 inp.addEventListener('keydown',e=>{if(e.key==='Enter'&&!go.disabled)go.click();});
 go.onclick=async()=>{
  if(acctBusy||go.disabled)return;
  acctBusy=true;go.disabled=true;go.textContent=tr('delWorking');acctErr('');
  try{
   const d=await acctPost('chatgpt/delete',{slot,confirm:inp.value});
   acctBusy=false;
   if(d.ok){acctClose();toast(d.message);await cxSettle();cxbLoad(true);cxAfterDel();return;}
   acctErr(d.message);go.textContent=tr('delGo');go.disabled=inp.value.trim().toLowerCase()!==word;
  }catch(e){acctBusy=false;acctErr(String(e));go.textContent=tr('delGo');go.disabled=false;}
 };
 setTimeout(()=>inp.focus(),30);
}

// ---- баннер лимитов/паузы ----
// Данные тянем раз в 20 с, а обратный отсчёт тикает локально каждую секунду —
// чтобы цифра жила, но сервер не дёргался лишний раз.
let ccpData=null;
const ccpEsc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function ccpLeft(untilMs){
 const s=Math.max(0,Math.round((untilMs-Date.now())/1000));
 const h=Math.floor(s/3600),m=Math.floor(s%3600/60);
 if(h>=48)return tr('ccpLeftD',Math.floor(h/24),String(h%24).padStart(2,'0'));  // пауза до сброса недели
 return tr('ccpLeft',h,h?String(m).padStart(2,'0'):m,String(s%60).padStart(2,'0'));
}
// дальше суток (пауза на неделе) — с днём недели, иначе «14:00» читается как сегодня
function ccpAt(ms){return new Date(ms).toLocaleString(LANG==='en'?'en-GB':'ru',ms-Date.now()>20*3600e3?{weekday:'short',hour:'2-digit',minute:'2-digit'}:{hour:'2-digit',minute:'2-digit'});}
// что держит аккаунт, подробно (для активного): «сессия 93% (порог 90%), неделя 60%»,
// «неделя 99% — на потолке 99%»; held — из cc_avail: «сессия», «неделя», «сессия+неделя», «free»
function ccpWhy(a,thr,wcap){
 const h=a.held||'',p=a.pct==null?'?':Math.round(a.pct)+'%',w=a.wpct==null?'?':Math.round(a.wpct)+'%',out=[];
 if(h==='free')return 'Free';
 if(h.includes('сессия'))out.push(tr('ccpWhySes',p,thr));
 if(h.includes('неделя'))out.push(tr('ccpWhyWeek',w,wcap));else out.push(tr('ccpWhyWeekOk',w));
 return out.join(', ');
}
// то же коротко, для списка «остальные не годятся»: «неделя 100%», «сессия 91%, неделя 98%»
function ccpHeld(a){
 const h=a.held||'',out=[];
 if(a.error)return tr('ccpHeldErr');
 if(h==='free')return 'Free';
 if(h.includes('сессия'))out.push(tr('ccpHeldSes',a.pct==null?'?':Math.round(a.pct)+'%'));
 if(h.includes('неделя'))out.push(tr('ccpHeldWeek',a.wpct==null?'?':Math.round(a.wpct)+'%'));
 return out.join(', ')||'?';
}
function ccpAgents(d){
 const states=(d&&d.claude_limits)||{};let count=0;
 for(const [key,id,name] of [['claude','ccPauseDev','Claude DEV'],['prod','ccPauseProd','Claude PROD']]){
  const el=document.getElementById(id);if(!el)continue;
  const s=states[key];if(!s){el.hidden=true;el.innerHTML='';continue;}
  const until=(s.resume_at||0)*1000;
  const at=until?new Date(until).toLocaleString(LANG==='en'?'en-GB':'ru',{timeZone:window.FLEET_TZ,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'';
  const title=tr(s.window==='pause'?'ccpaPause':s.window==='week'?'ccpaWeek':'ccpaSession',name,s.pct==null?'?':Math.round(s.pct),at);
  const sub=s.override?tr('ccpaOverride'):s.manual?tr('ccpaManual'):s.window==='pause'?tr('ccpaKnownPause'):tr(s.waiting?'ccpaWait':'ccpaWarn',s.threshold);
  const toggle=s.override?'on':!s.manual&&s.waiting&&s.can_override?'off':'';
  const action=toggle?'<div class="ccp-actions"><button type="button" class="ccp-btn" onclick="ccpToggle(\''+toggle+'\',this,\''+key+'\')">'+tr(toggle==='on'?'ccpBtnOn':'ccpBtnOff')+'</button></div>':'';
  el.className='ccpause lvl-'+(s.waiting?'pause':'hard');el.hidden=false;
  el.innerHTML='<span class="ccp-dot"></span><div class="ccp-body"><div class="ccp-title">'+ccpEsc(title)+'</div><div class="ccp-sub">'+ccpEsc(sub)+'</div>'+action+'</div>'
   +(until?'<div class="ccp-timer" data-until="'+until+'"><div class="t">'+ccpLeft(until)+'</div><div class="l">'+tr('ccpTillReset')+'</div></div>':'');
  count++;
 }
 return count;
}
function ccpRender(){
 const el=$('#ccPause'),d=ccpData;if(!el)return;
 const pause=(d&&d.pause)||{},lvl=(d&&d.level)||'none';
 // Два Claude показываются независимо: работа на PROD/Codex не скрывает лимиты DEV.
 const agentCount=ccpAgents(d);
 if(agentCount&&!d.handoff&&!d.manual){el.hidden=true;el.innerHTML='';return;}
 // Локальная пауза и активный PROD не скрывают исчерпание всей пары.
 const rp=d&&d.remote_pause;
 if(rp&&rp.enabled&&rp.applied&&rp.blocked){
  const until=(rp.resume_at||0)*1000;
  el.className='ccpause lvl-pause';el.hidden=false;
  // (63532) один текст паузы: подробный, что раньше был полосой в консоли, теперь здесь; в консоли осталась большая иконка паузы
  const title='\u23f8 '+tr('ccpsTitle')+(until?tr('ccpsUntil',ccpAt(until),'<span class="ccp-left" data-until="'+until+'">'+ccpLeft(until)+'</span>'):'');
  const sub=tr('ccpsBody');
  el.innerHTML='<span class="ccp-dot"></span><div class="ccp-body"><div class="ccp-title">'+title
   +'</div><div class="ccp-sub">'+sub+'</div><div class="ccp-meta">'+ccpEsc((rp.reasons||[]).join('; '))+'</div></div>'
   +(until?'<div class="ccp-timer" data-until="'+until+'"><div class="t">'+ccpLeft(until)+'</div><div class="l">'+tr('ccpTillWake')+'</div></div>':'');
  return;
 }
 const fleet=d&&d.fleet;
 if(fleet&&fleet.remote_count&&fleet.all_blocked){
  const next=fleet.nearest||{},until=next.resets_at?new Date(next.resets_at).getTime():0;
  const chips=Object.values(fleet.accounts||{}).map(a=>'<span class="ccp-chip hot">'+ccpEsc(a.label)
   +' <b>'+(a.pct==null?'?':Math.round(a.pct)+'%')+'</b>'
   +(a.wpct!=null?tr('ccpWeek',Math.round(a.wpct)):'')+'</span>').join('');
  el.className='ccpause lvl-pause';el.hidden=false;
  el.innerHTML='<span class="ccp-dot"></span><div class="ccp-body"><div class="ccp-title">'
   +tr(fleet.all_week_capped?'ccpFleetWeekTitle':'ccpFleetHardTitle')+'</div><div class="ccp-sub">'+tr('ccpFleetSub')
   +'</div><div class="ccp-meta">'+chips+'</div></div>'
   +(until?'<div class="ccp-timer" data-until="'+until+'"><div class="t">'+ccpLeft(until)
     +'</div><div class="l">'+tr('ccpTillFree',ccpEsc(next.label||next.acc||''))+'</div></div>':'');
  return;
 }
 if(!d||d.stale||(lvl==='none'&&!pause.active&&!pause.override)){el.hidden=true;return;}
 // приоритет: пауза отключена кнопкой > пауза (в ней уже есть будильник) >
 // переключаться некуда > активный забит
 const mode=pause.override?'off':pause.active?'pause':lvl;
 // [remote] работа на Claude PROD: лимиты DEV не значат «переключаться некуда» — переключились туда
 // пауза по лимитам, «пауза отключена» и ручной выбор тоже относятся к этому серверу: работа идёт на PROD, на плитке аккаунта они видны
 if(d.remote&&['hard','week','weekrisk','gate','pause','off','manual'].includes(mode)){el.hidden=true;return;}
 const near=(d.nearest&&d.nearest.resets_at)?new Date(d.nearest.resets_at).getTime():0;
 const thr=Math.round(d.threshold||90),wcap=Math.round(d.weekly_cap||99);
 let title,sub,timer=null,tlabel='',action=null;
 // автопередача вот-вот отдаст работу Claude PROD: «некуда» пока не правда — «ищу свободный аккаунт»; красный баннер и пауза — только если искать негде (владелец 62577)
 const search=!!d.handoff&&['hard','week','weekrisk'].includes(mode);
 if(search){
  const a=(d.accounts||{})[d.active]||{};
  title=tr('ccpSearchTitle');sub=tr('ccpSearchSub',ccpEsc(d.active||'?'),ccpWhy(a,thr,wcap));
 }else if(d.prod_free&&['hard','week'].includes(mode)){
  // DEV упёрся, а Claude PROD свободен и работа к нему не уходит (автопередача выключена): «переключаться некуда» — неправда
  const pf=d.prod_free,a=(d.accounts||{})[d.active]||{};
  title=tr('ccpProdTitle');
  const nums=[pf.pct==null?'':tr('ccpProdSes',Math.round(pf.pct)),pf.wpct==null?'':tr('ccpProdWeek',Math.round(pf.wpct))].filter(Boolean).join(', ');
  sub=tr('ccpProdSub',ccpEsc(d.active||'?'),ccpWhy(a,thr,wcap),ccpEsc(pf.label||'Claude PROD')+(nums?' ('+nums+')':'')+' '+tr('ccpProdFree'),!!pf.on,!pf.on&&pf.why==='автопередача выключена');
  if(near){timer=near;tlabel=tr('ccpTillNearest');}
  action={act:'off',label:tr('ccpBtnOff'),hint:tr('ccpHintHardOff')};
 }else if(mode==='off'){
  const na=d.nearest&&d.nearest.acc;
  const full=lvl==='hard'||lvl==='week';
  title=tr('ccpOffTitle');sub=tr('ccpOffSub',full&&na?ccpEsc(na):'',full&&near?ccpAt(near):'');
  action={act:'on',label:tr('ccpBtnOn'),hint:tr(full?'ccpHintOnHard':'ccpHintOnFree')};
 }else if(mode==='pause'){
  const upMs=(pause.resume_at||0)*1000;
  title=tr('ccpPauseTitle');
  const wk=pause.kind==='week',wa=(d.accounts||{})[d.active]||{};
  const reason=wk?tr('ccpWeekReason',ccpEsc(d.active||'?'),wa.wpct==null?'?':Math.round(wa.wpct),wcap):(pause.reason||tr('ccpDefReason'));
  sub=tr('ccpPauseSub',wk?reason:ccpEsc(reason),upMs?ccpAt(upMs):'')
    +(pause.note?'<br>'+ccpEsc(pause.note):'');
  if(upMs){timer=upMs;tlabel=tr('ccpTillWake');}
  action={act:'off',label:tr('ccpBtnOff'),hint:wk?tr('ccpHintWeekOff'):tr('ccpHintOff',thr)};
 }else if(mode==='week'||mode==='weekrisk'){
  const na=d.nearest&&d.nearest.acc,a=(d.accounts||{})[d.active]||{};
  const n=ccpEsc(d.active||'?'),w=a.wpct==null?'?':Math.round(a.wpct)+'%';
  if(mode==='week'){
   title=tr('ccpWeekTitle');sub=tr('ccpWeekSub',n,w,wcap,na?ccpEsc(na):'');
   action={act:'off',label:tr('ccpBtnOff'),hint:tr('ccpHintWeekOff')};
  }else{
   title=tr('ccpRiskTitle');sub=tr('ccpRiskSub',n,w,wcap);
   action={act:'settings',label:tr('ccpBtnSettings'),hint:tr('ccpHintSettings')};
  }
  if(near){timer=near;tlabel=na?tr('ccpTillFree',ccpEsc(na)):tr('ccpTillNearest');}
 }else if(mode==='hard'){
  const na=d.nearest&&d.nearest.acc,accs=d.accounts||{},a=accs[d.active]||{};
  // все сессии забиты — старый текст; иначе называем, что держит каждый из остальных
  const allSes=!Object.values(accs).some(x=>x.ses_ok);
  const rest=Object.entries(accs).filter(([n])=>n!==d.active).sort(([x],[y])=>x<y?-1:1)
   .map(([n,x])=>ccpEsc(n)+' — '+ccpHeld(x)).join(', ');
  title=tr('ccpHardTitle');
  sub=tr('ccpHardSub',allSes?tr('ccpHardAll',thr):tr('ccpHardSome',ccpEsc(d.active||'?'),ccpWhy(a,thr,wcap),rest),
   na?ccpEsc(na):'',na&&na===d.active);
  if(near){timer=near;tlabel=na?tr('ccpTillFree',ccpEsc(na)):tr('ccpTillNearest');}
  action={act:'off',label:tr('ccpBtnOff'),hint:tr('ccpHintHardOff')};
 }else if(mode==='manual'){
  const a=(d.accounts||{})[d.active]||{},n=ccpEsc(d.active||'?'),upMs=((d.manual||{}).until||0)*1000;
  title=tr('ccpManTitle',n);
  sub=tr('ccpManSub',n,ccpWhy(a,thr,wcap),upMs?ccpAt(upMs):'',!a.ses_ok);
  if(upMs){timer=upMs;tlabel=tr('ccpTillMan');}
 }else{
  const a=(d.accounts||{})[d.active]||{},ses=(a.held||'').includes('сессия');
  // фоновые задачи гейт держит только по сессии — на недельном потолке они идут
  title=tr(ses?'ccpGateTitle':'ccpGateWeekTitle');
  // без таймера: сброс окна активного тут ни при чём — балансер уходит на свободный сразу
  sub=tr('ccpGateSub',ccpEsc(d.active||'?'),ccpWhy(a,thr,wcap),d.autoswitch!==false,ses);
 }
 // у активного исчерпан настоящий лимит (сессия или неделя 100%) — «Отключить паузу» ничего не даст: кнопку прячем
 const aa=(d.accounts||{})[d.active]||{};
 if(action&&action.act==='off'&&(aa.pct>=100||aa.wpct>=100))action={act:'',label:'',hint:tr('ccpHintLimitOut')};
 const chips=Object.entries(d.accounts||{}).map(([n,a])=>
  '<span class="ccp-chip'+(a.usable===false?' hot':'')+'">'+ccpEsc(n)
  +(a.active?tr('ccpActive'):'')+' <b>'+(a.pct==null?'?':a.pct+'%')+'</b>'
  +(a.wpct!=null&&a.wpct>=90?tr('ccpWeek',Math.round(a.wpct)):'')+'</span>').join('');
 el.className='ccpause lvl-'+(search?'gate':({week:'pause',weekrisk:'hard',manual:'gate'}[mode]||mode));el.hidden=false;
 el.innerHTML='<span class="ccp-dot"></span><div class="ccp-body"><div class="ccp-title">'+title+'</div>'
  +'<div class="ccp-sub">'+sub+'</div><div class="ccp-meta">'+chips
  +(pause.active&&pause.checks?'<span class="ccp-chip">'+tr('ccpChecks',pause.checks)+'</span>':'')
  +'</div>'
  +(action?'<div class="ccp-actions">'+(action.act?'<button type="button" class="ccp-btn" onclick="ccpToggle(\''+action.act+'\',this)">'
    +action.label+'</button>':'')+'<span class="ccp-hint">'+ccpEsc(action.hint)+'</span></div>':'')
  +'</div>'
  +(timer?'<div class="ccp-timer" data-until="'+timer+'"><div class="t">'+ccpLeft(timer)+'</div>'
    +'<div class="l">'+tlabel+'</div></div>':'');
}
function ccpTick(){
 document.querySelectorAll('#ccPause .ccp-left,#ccPauseDev .ccp-left,#ccPauseProd .ccp-left').forEach(e=>{e.textContent=ccpLeft(+e.dataset.until)});
 let expired=false;
 document.querySelectorAll('#ccPause .ccp-timer,#ccPauseDev .ccp-timer,#ccPauseProd .ccp-timer').forEach(t=>{
  const until=+t.dataset.until;t.querySelector('.t').textContent=ccpLeft(until);
  if(Date.now()>until+60000)expired=true;
 });
 if(expired)ccpLoad();  // один запрос на все истёкшие окна
}
async function ccpToggle(act,btn,engine){
 if(act==='settings'){$('#gear').click();return;}
 if(btn)btn.disabled=true;
 try{
  const r=await fetch(API+'pause?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:act,engine:engine||'claude'})});
  const d=await r.json();
  if(!r.ok||!d.ok)throw new Error(d.out||d.error||('HTTP '+r.status));
  ccpData=d;ccpRender();
 }catch(e){
  if(btn){btn.disabled=false;const h=btn.parentNode.querySelector('.ccp-hint');if(h){h.className='ccp-err';h.textContent=tr('ccpErr',e.message);}}
 }
}
async function ccpLoad(){
 try{const r=await fetch(API+'pause?token='+TOKEN);ccpData=await r.json();}catch(e){ccpData=null;}
 ccpRender();
}

// ---- Codex: предупреждение о лимитах отдельно от паузы очереди (/api/chatgpt/rotation → limit_notice) ----
let cxlpData=null,cxlpOpen=false,cxlpLoadedAt=0;
function cxlpRender(){
 const el=$('#cxPause');if(!el)return;
 const p=cxlpData;
 if(!p||!p.active){el.hidden=true;el.innerHTML='';return;}
 const paused=p.hard?false:p.paused===undefined?true:!!p.paused;
 const policy=!!p.policy,override=!!p.override;
 const prev=el.querySelector(':scope > details');if(prev)cxlpOpen=prev.open;
 const upMs=(p.resume_at||0)*1000;
 const sessionOnly=(p.windows||[]).length===1&&p.windows[0]===300;
 const at=upMs?(paused?ccpAt(upMs):sessionOnly?'':new Date(upMs).toLocaleString(LANG==='en'?'en-GB':'ru',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})):'';
 const why=(p.windows||[]).map(m=>tr('cxlpWin',m)).join(', ')||tr('cxlpWinAny');
 const chips=(p.accounts||[]).map(a=>'<span class="ccp-chip hot">'+ccpEsc(a.label)+(a.active?tr('ccpActive'):'')
  +' <b>'+(a.ses==null?'?':Math.round(a.ses)+'%')+'</b>'+(a.week!=null?tr('ccpWeek',Math.round(a.week)):'')+'</span>').join('');
 const timer=upMs?'<div class="ccp-timer" data-until="'+upMs+'"><div class="t">'+ccpLeft(upMs)+'</div><div class="l">'+tr('cxlpTill')+'</div></div>':'';
 el.className='ccpause '+(paused?'lvl-pause':'lvl-hard');el.hidden=false;
 el.innerHTML='<details class="fleet-pause-fold"'+(cxlpOpen?' open':'')+'><summary class="fleet-pause-summary"><span class="ccp-dot"></span>'
  +'<span class="ccp-title">'+(policy?ccpEsc(tr('cxqpBrief',why,override)):p.hard&&(p.windows||[]).length?ccpEsc(tr('cxqpLimitBrief',why)):paused?(at?tr('cxlpBrief',at):tr('cxlpBriefNoAt')):ccpEsc(tr('cxlnBrief',why,at)))+'</span>'+timer
  +'<svg viewBox="0 0 24 24" class="fleet-pause-chevron" aria-hidden="true"><path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></summary>'
  +'<div class="fleet-pause-content"><div class="ccp-body"><div class="ccp-title">'+tr(policy?'cxqpTitle':paused?'cxlpTitle':'cxlnTitle')+'</div>'
  +'<div class="ccp-sub">'+(policy?ccpEsc(tr(override?'cxqpOff':'cxqpSub',p.threshold,p.weekly_cap)):paused?tr('cxlpSub',p.multi?ccpEsc(p.label):'',why,at,p.multi&&p.resume_label&&p.resume_slot!==p.slot?ccpEsc(p.resume_label):''):tr('cxlnSub',p.multi?ccpEsc(p.label):'',why,at,upMs?ccpLeft(upMs):''))+'</div>'
  +'<div class="ccp-meta">'+chips+'</div>'
  +'<div class="ccp-actions">'+(override||p.can_override?'<button type="button" class="ccp-btn" onclick="cxlpToggle('+(!override)+',this)">'+tr(override?'ccpBtnOn':'ccpBtnOff')+'</button>':'')+'<span class="ccp-hint">'+ccpEsc(tr(policy?'cxqpHint':p.hard?'cxqpHardHint':paused?'cxlpHint':p.multi?'cxlnHintMulti':'cxlnHint',p.queued||0))+'</span></div></div></div></details>';
 el.querySelector('details').addEventListener('toggle',e=>{cxlpOpen=e.target.open});
}
async function cxlpToggle(off,btn){
 if(btn)btn.disabled=true;
 try{
  const r=await fetch(API+'chatgpt/rotation/config',{method:'POST',headers:{'X-CC-Token':TOKEN,'Content-Type':'application/json'},body:JSON.stringify({pause_override:off})}),d=await r.json();
  if(!r.ok||d.ok===false)throw new Error(d.message||'HTTP '+r.status);
  await cxlpLoad();
 }catch(e){if(btn)btn.disabled=false;toast(tr('ccpErr',e.message));}
}
function cxlpTick(){
 const t=$('#cxPause .ccp-timer');if(!t)return;
 const until=+t.dataset.until;t.querySelector('.t').textContent=ccpLeft(until);
 if(Date.now()>until+60000&&Date.now()-cxlpLoadedAt>30000)cxlpLoad();  // окно должно было отпустить — перечитаем
}
async function cxlpLoad(){
 if(document.hidden&&cxlpData!==null)return;
 cxlpLoadedAt=Date.now();
 try{const r=await fetch(API+'chatgpt/rotation',{headers:{'X-CC-Token':TOKEN}});if(!r.ok)return;const d=await r.json();cxlpData=d.limit_notice||d.limit_pause||{active:false};cxlpData.queued=(d.quota||{}).queued||0;}catch(e){return;}
 cxlpRender();
}

// ---- автообновление: баннер «вышла версия», блок в настройках, ручной/авто режим ----
let updData=null,updWait=null,updTimer=null,updDown=false,updHeld=false;
const updBusy=()=>!!(updWait||(updData&&(updData.phase!=='idle'||updData.pending)));
const updAt=ts=>ts?new Date(ts*1000).toLocaleTimeString(LANG==='en'?'en-GB':'ru',{hour:'2-digit',minute:'2-digit'}):'';
async function updPost(path,body){
 const r=await fetch(API+'update/'+path+'?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
 return r.json();
}
async function updLoad(){
 clearTimeout(updTimer);
 try{
  const r=await fetch(API+'update?token='+TOKEN);
  if(!r.ok)throw new Error(r.status);
  updData=await r.json();updDown=false;
  if(updWait){
   const res=updData.result;
   // итог пришёл (успех — когда служба подтвердила запуск, сбой/откат — сразу) или ждём слишком долго
   if((res&&res.to===updWait.to&&(!res.ok||updData.version===updWait.to))||Date.now()-updWait.ts>300000)updWait=null;
  }
 }catch(e){updDown=true;}  // служба перезапускается — просто ждём, баннер покажет это
 updHeld=false;
 if(updStale())updReload(false);
 updRender();updSettingsRender();
 updTimer=setTimeout(updLoad,(updBusy()||updDown)?2000:(updHeld?5000:60000));
}
// служба уже на новой версии, а HTML/JS этой вкладки — с прежней (обновили отсюда, из другой вкладки или
// авто-режимом): новое приезжает только с перезагрузкой — делаем её сами, если она ничего не оборвёт
function updStale(){return !!(updData&&!updDown&&updData.version&&updData.version!==PAGE_VER&&updData.phase==='idle'&&!updData.pending);}
function updHold(){  // перезагрузка сейчас потеряет ввод: диалог аккаунта, набранный текст, полноэкранный режим
 if(!$('#acctScrim').hidden||document.fullscreenElement)return true;
 return [...document.querySelectorAll('input,textarea')].some(el=>(el.tagName==='TEXTAREA'||/^(text|email|search|url|number|password)$/.test(el.type))
  &&el.value!==el.defaultValue&&el.offsetParent!==null);
}
function updReload(force){
 const v=updData&&updData.version;
 if(!force){
  let tried='';try{tried=sessionStorage.getItem('cc_upd_reload')||'';}catch(e){}
  if(tried===v)return;  // уже перезагружались ради этой версии, а вкладка всё равно прежняя — дальше только кнопкой
  if((updHeld=updHold()))return;  // проверим снова через 5 с
 }
 try{sessionStorage.setItem('cc_upd_reload',v||'');if(!$('#scrim').hidden)sessionStorage.setItem('cc_upd_reopen','1');}catch(e){}
 location.reload();
}
// причина ошибки: код → текст на языке интерфейса (сырой текст бэкенда — в подсказке); нет перевода — показываем как есть
function updErrText(code,raw){
 const k='updE_'+code;
 if(code&&I18N[LANG][k])return '<span'+(raw?' title="'+ccpEsc(raw)+'"':'')+'>'+ccpEsc(tr(k))+'</span>';
 return ccpEsc(raw||'');
}
function updNotesPick(L){return(LANG==='en'?(L.notes_en||L.notes_ru):(L.notes_ru||L.notes_en))||L.notes||'';}  // блок описания на языке интерфейса; без блоков — тело релиза целиком
function updNotesText(t){return String(t||'').replace(/^#+\s*/gm,'').replace(/\*\*/g,'').replace(/`/g,'').trim().slice(0,1500);}
function updRender(){
 const el=$('#updBanner');if(!el)return;
 const d=updData;
 if(!d&&!updWait){el.hidden=true;return;}
 const L=d&&d.latest,res=d&&d.result;
 let cls,title,sub='',more='',acts='',bar=false;
 if(updWait||(d&&(d.phase!=='idle'||d.pending))){
  const to=updWait?updWait.to:((L&&L.version)||(res&&res.to)||'');
  const k={downloading:'updPhDownloading',verifying:'updPhVerifying',installing:'updPhInstalling',restarting:'updPhRestarting'}[d?d.phase:''];
  cls='lvl-upd';bar=true;title=tr('updRunTitle',ccpEsc(to));
  sub=tr(k||(updDown?'updPhRestarting':'updPhConfirm'));
 }else if(res){
  if(res.ok){
   cls='lvl-updok';title=tr('updOkTitle',ccpEsc(res.to));sub=tr('updOkSub',ccpEsc(res.from));more=updOkNotes(res.to);
   acts='<button type="button" class="ccp-btn" onclick="updAck()">'+tr('updBtnOk')+'</button>';
   if(updStale()){
    sub+='<br>'+tr(updHeld?'updStaleHeld':'updStaleSub');
    acts='<button type="button" class="ccp-btn" onclick="updReload(true)">'+tr('updBtnReload')+'</button>'+acts.replace('ccp-btn"','ccp-btn sec"');
   }
  }else{
   cls='lvl-upderr';title=tr('updErrTitle',ccpEsc(res.to));
   sub=updErrText(res.code,res.error)+(res.rolled_back?'<br>'+tr('updRolled'):'');
   acts='<button type="button" class="ccp-btn" onclick="updAck()">'+tr('updBtnOk')+'</button>'
    +((d.available&&!res.needs_install&&d.supported)?'<button type="button" class="ccp-btn sec" onclick="updApply(this)">'+tr('updBtnRetry')+'</button>':'')
    +(d.supported?'<button type="button" class="ccp-btn sec" onclick="updCheckNow(this)">'+tr('updCheckBtn')+'</button>':'');
  }
 }else if(updStale()){
  cls='lvl-updok';title=tr('updStaleTitle',ccpEsc(d.version));sub=tr(updHeld?'updStaleHeld':'updStaleSub');
  acts='<button type="button" class="ccp-btn" onclick="updReload(true)">'+tr('updBtnReload')+'</button>';
 }else if(d.available&&!d.skipped){
  cls='lvl-upd';title=tr('updBTitle',ccpEsc(L.version));sub=tr('updBSub',ccpEsc(d.version),ccpEsc(L.name&&L.name!==L.tag?L.name:''));
  const notes=updNotesText(updNotesPick(L));
  if(notes)more='<details class="upd-notes"><summary>'+tr('updNotes')+'</summary><pre>'+ccpEsc(notes)+'</pre></details>';
  if(d.supported){
   acts='<button type="button" class="ccp-btn" onclick="updApply(this)">'+tr('updBtnNow')+'</button>'
    +'<button type="button" class="ccp-btn sec" onclick="updSkip()">'+tr('updBtnSkip')+'</button>';
  }else acts='<span class="ccp-hint">'+ccpEsc(tr('updNoSupport',I18N[LANG]['updE_'+d.unsupported_code]?tr('updE_'+d.unsupported_code):d.unsupported_reason))+'</span>';
  if(L.html_url)acts+='<a class="ccp-link" href="'+ccpEsc(L.html_url)+'" target="_blank" rel="noopener">'+tr('updBtnPage')+'</a>';
  if(d.mode==='auto'&&d.supported)acts+='<span class="ccp-hint">'+tr('updAutoSoon')+'</span>';
 }else{el.hidden=true;return;}
 el.className='ccpause '+cls;el.hidden=false;
 el.innerHTML='<span class="ccp-dot"></span><div class="ccp-body"><div class="ccp-title">'+title+'</div>'
  +'<div class="ccp-sub">'+sub+'</div>'+(bar?'<div class="upd-bar"><i></i></div>':'')+more
  +(acts?'<div class="ccp-actions">'+acts+'</div>':'')+'</div>';
}
async function updCheckNow(btn){
 if(btn)btn.disabled=true;
 try{updData=await updPost('check');}catch(e){}
 updRender();updSettingsRender();
}
async function updApply(btn){
 if(btn)btn.disabled=true;
 const to=updData&&updData.latest&&updData.latest.version;
 try{
  const d=await updPost('apply',{version:to});
  if(!d.ok)throw new Error(d.message||'error');
  updWait={to,ts:Date.now()};updData=d;
 }catch(e){toast('⚠ '+e.message);if(btn)btn.disabled=false;}
 updLoad();
}
async function updSkip(){
 const v=updData&&updData.latest&&updData.latest.version;if(!v)return;
 try{updData=await updPost('skip',{version:v});toast(tr('updToastSkipped'));}catch(e){}
 updRender();updSettingsRender();
}
async function updAck(){
 try{updData=await updPost('ack');}catch(e){}
 updRender();updSettingsRender();
}
// история изменений: CHANGELOG.json грузится при первом раскрытии; узел живёт отдельно и переносится
// при каждой перерисовке #updBox (раз в минуту), поэтому раскрытие и прокрутка не сбрасываются
let updLogEl=null,updLogData=null,updLogKey='';
function updLogDate(s){const m=/^(\d{4})-(\d\d)-(\d\d)$/.exec(s||'');return !m?ccpEsc(s||''):(LANG==='en'?m[0]:m[3]+'.'+m[2]+'.'+m[1]);}
function updLogTxt(s){return ccpEsc(s||'').replace(/`([^`]+)`/g,'<code>$1</code>');}
function updLogList(){
 const list=updLogEl.querySelector('.updlog-list'),vs=(updLogData&&updLogData.versions)||[];
 if(!vs.length){list.innerHTML='<div class="ul-empty">'+tr(updLogData?'updLogEmpty':'loading')+'</div>';return;}
 const cur=updData&&updData.version;
 list.innerHTML=vs.map(e=>{
  const x=(LANG==='en'?(e.en||e.ru):(e.ru||e.en))||{},p=Array.isArray(x.p)?x.p:[];
  return '<div class="ul-it"><div class="ul-h"><span class="ul-v">v'+ccpEsc(e.v)+'</span><span class="ul-d">'+updLogDate(e.date)+'</span>'
   +(e.v===cur?'<span class="ul-cur">'+tr('updLogCur')+'</span>':'')+updLogTxt(x.t)+'</div>'
   +(p.length?'<ul>'+p.map(t=>'<li>'+updLogTxt(t)+'</li>').join('')+'</ul>':'')+'</div>';
 }).join('');
 updLogKey=LANG+'|'+cur;
}
async function updLogFetch(){
 try{const r=await fetch(API+'changelog?token='+TOKEN);if(!r.ok)throw new Error(r.status);updLogData=await r.json();updLogList();}
 catch(e){updLogData=null;updLogEl.querySelector('.updlog-list').innerHTML='<div class="ul-empty">'+tr('updLogEmpty')+'</div>';}  // при следующем раскрытии — новая попытка
}
function updLogNode(){
 if(!updLogEl){
  updLogEl=document.createElement('details');updLogEl.className='updlog';
  updLogEl.innerHTML='<summary></summary><div class="updlog-list"></div>';
  updLogEl.addEventListener('toggle',()=>{if(updLogEl.open&&!updLogData){updLogList();updLogFetch();}});
 }
 updLogEl.querySelector('summary').textContent=tr('updLog');
 if(updLogData&&updLogKey!==LANG+'|'+(updData&&updData.version))updLogList();
 return updLogEl;
}
// «Что нового» в плашке после обновления: запись версии из CHANGELOG.json (та же, что в истории изменений)
let updOkTry='';
function updOkNotes(v){
 const e=((updLogData&&updLogData.versions)||[]).find(x=>x.v===v);
 if(!e){
  if(updOkTry!==v){updOkTry=v;updOkLoad();}  // списка ещё нет или он старее этой версии — один раз перечитать
  return '';
 }
 const x=(LANG==='en'?(e.en||e.ru):(e.ru||e.en))||{},p=Array.isArray(x.p)?x.p:[];
 if(!x.t&&!p.length)return '';
 return '<div class="upd-notes upd-ok-notes"><b>'+tr('updNotes')+'</b>'+(x.t?'<div class="uo-t">'+updLogTxt(x.t)+'</div>':'')
  +(p.length?'<ul>'+p.map(t=>'<li>'+updLogTxt(t)+'</li>').join('')+'</ul>':'')+'</div>';
}
async function updOkLoad(){
 try{
  const r=await fetch(API+'changelog?token='+TOKEN);if(!r.ok)throw new Error(r.status);
  updLogData=await r.json();
 }catch(e){return;}
 updRender();
}
function updSettingsRender(){
 const box=$('#updBox');if(!box||$('#scrim').hidden)return;
 const d=updData;
 if(!d){box.innerHTML='';return;}
 const logSt=updLogEl?updLogEl.querySelector('.updlog-list').scrollTop:0;
 const L=d.latest;
 const line=d.available?tr(d.skipped?'updSkippedLine':'updAvailLine',L.version):tr(d.last_check?'updUpToDate':'updNeverChecked');
 const when=(!d.available&&d.last_check)?' · '+tr('updCheckedAt',updAt(d.last_check)):'';
 box.innerHTML='<div class="updrow"><div class="updtxt"><b>'+tr('updVer',ccpEsc(d.version))+'</b>'
  +'<div class="updsub'+(d.last_error?' bad':'')+'">'+(d.last_error?updErrText(d.last_error_code,d.last_error):ccpEsc(line+when))+'</div></div>'
  +'<button type="button" class="ghostbtn" id="updCheckBtn">'+tr('updCheckBtn')+'</button></div>'
  +((d.available&&d.skipped&&d.supported&&!updBusy())?'<div class="updrow"><div class="updtxt"></div><button type="button" class="ghostbtn" id="updApplyBtn">'+tr('updBtnNow')+'</button></div>':'')
  +'<div class="updrow"><div class="segctl" role="radiogroup">'
  +['manual','auto'].map(m=>'<button type="button" role="radio" data-m="'+m+'" aria-checked="'+(d.mode===m)+'" class="'+(d.mode===m?'on':'')+'">'+tr(m==='auto'?'updAuto':'updManual')+'</button>').join('')+'</div></div>'
  +'<div class="modalsub" style="margin:0">'+tr(d.mode==='auto'?'updHintAuto':'updHintManual')+'</div>'
  +'<label class="updchk"><input type="checkbox" id="updChk"'+(d.check?' checked':'')+'><span>'+tr('updCheckLbl')+'</span></label>';
 const seg=box.querySelector('.segctl');  // под строкой версии, перед «Вручную / Автоматически»
 seg.parentNode.before(updLogNode());
 updLogEl.querySelector('.updlog-list').scrollTop=logSt;
}
$('#updBox').addEventListener('click',async e=>{
 const d=updData;if(!d)return;
 const m=e.target.closest('[data-m]');
 if(m){
  const mode=m.dataset.m;if(mode===d.mode)return;
  if(mode==='auto'&&d.available&&!d.skipped&&d.supported&&!confirm(tr('updAutoConfirm',d.latest.version)))return;
  await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({update_mode:mode})});
  return updLoad();
 }
 if(e.target.id==='updCheckBtn'){return updCheckNow(e.target);}
 if(e.target.id==='updApplyBtn')return updApply(e.target);
});
$('#updBox').addEventListener('change',async e=>{
 if(e.target.id!=='updChk')return;
 await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({update_check:e.target.checked})});
 updLoad();
});
// «Копии аккаунтов» в ⚙: что лежит в копиях профилей, кнопки «Копия сейчас» и «Восстановить недостающие»
let bkData=null,bkMsg='';
const bkAt=ts=>{if(!ts)return '';const d=new Date(ts*1000),loc=LANG==='en'?'en-GB':'ru',t=d.toLocaleTimeString(loc,{hour:'2-digit',minute:'2-digit'});
 return d.toDateString()===new Date().toDateString()?t:d.toLocaleDateString(loc,{day:'2-digit',month:'2-digit'})+' '+t;};
async function bkPost(p){
 const r=await fetch(API+'backup/'+p+'?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
 return r.json();
}
async function bkLoad(){
 try{const r=await fetch(API+'backup?token='+TOKEN);if(!r.ok)throw new Error(r.status);bkData=await r.json();}catch(e){return;}
 bkRender();
}
function bkRender(){
 const box=$('#bkBox');if(!box||$('#scrim').hidden)return;
 const d=bkData;if(!d){box.innerHTML='';return;}
 const items=d.items||[],k=items.length+(d.latest?1:0);
 const last=Math.max((d.latest&&d.latest.ts)||0,...items.map(x=>x.ts),0);
 const lost=d.missing||[];
 box.innerHTML='<div class="updrow"><div class="updtxt"><b>'+tr('bkLine',d.profiles||0,k)+'</b>'
  +'<div class="updsub'+(d.error?' bad':'')+'">'+ccpEsc(d.error?tr('bkErr',d.error):(last?tr('bkLast',bkAt(last)):tr('bkNone')))+'</div></div>'
  +'<button type="button" class="ghostbtn" id="bkNowBtn">'+tr('bkNow')+'</button></div>'
  +(lost.length?'<div class="updrow"><div class="updtxt"><div class="updsub bad">'+ccpEsc(tr('bkLost',lost.join(', ')))+'</div></div>'
   +'<button type="button" class="ghostbtn" id="bkRestoreBtn">'+tr('bkRestore')+'</button></div>':'')
  +(bkMsg?'<div class="modalsub" style="margin:0">'+ccpEsc(bkMsg)+'</div>':'')
  +'<label class="updchk"><input type="checkbox" id="bkChk"'+(d.enabled?' checked':'')+'><span>'+tr('bkAuto')+'</span></label>'
  +'<div class="modalsub" style="margin:6px 0 0">'+tr('bkHint')+'</div>';
}
$('#bkBox').addEventListener('click',async e=>{
 const d=bkData;if(!d)return;
 if(e.target.id==='bkNowBtn'){
  e.target.disabled=true;
  try{const r=await bkPost('now');bkMsg=r.ok?'':tr(r.why==='empty'?'bkNowEmpty':'bkNowErr');bkData=r;}catch(x){bkMsg=tr('bkNowErr');}
  return bkRender();
 }
 if(e.target.id==='bkRestoreBtn'){
  const lost=(d.missing||[]).join(', ');
  if(!confirm(tr('bkRestoreAsk',lost)))return;
  e.target.disabled=true;
  try{const r=await bkPost('restore');bkMsg=(r.restored&&r.restored.length)?tr('bkRestored',r.restored.join(', ')):tr('bkRestoreNone');bkData=r;}catch(x){bkMsg=tr('bkNowErr');}
  bkRender();load();  // load() — перечитать карточки: вернувшиеся аккаунты появятся в списке
 }
});
$('#bkBox').addEventListener('change',async e=>{
 if(e.target.id!=='bkChk')return;
 await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_backup:e.target.checked})});
 bkLoad();
});
// «Claude Code» в ⚙: версия, «Обновить» / «Вернуть» и ход npm — на этом сервере и на втором (PROD)
let ccliData=null,ccliTimer=null,ccliMsg='',ccliPopOpen=false;
async function ccliPost(p,body){
 const r=await fetch(API+'claude-cli/'+p+'?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
 return r.json();
}
async function ccliLoad(check){
 try{const r=await fetch(API+'claude-cli?token='+TOKEN+(check?'&check=1':''));if(!r.ok)throw new Error(r.status);ccliData=await r.json();}catch(e){return;}
 ccliRender();ccliBadgeRender();
 clearTimeout(ccliTimer);
 const busy=['local','remote','codex'].some(k=>ccliData[k]&&ccliData[k].state==='running');
 if(busy&&(!$('#scrim').hidden||ccliPopOpen))ccliTimer=setTimeout(()=>ccliLoad(false),3000);
}
function ccliRow(k,d){
 const where=tr(k==='remote'?'ccliProd':'ccliThis'),nm=k==='codex'?'Codex':'Claude Code';
 if(!d)return '';
 if(d.ok===false)return '<div class="updrow"><div class="updtxt"><b>'+ccpEsc(tr('ccliLine',nm,where,''))+'</b><div class="updsub bad">'+ccpEsc(tr('ccliNoLink'))+'</div></div></div>';
 const head='<b>'+ccpEsc(tr('ccliLine',nm,where,d.version||''))+'</b>',r=d.restart||null,fresh=!!d.finished&&(Date.now()/1000-d.finished)<600;
 let sub='',btns='',pre='',bar='',next='',bad=false,ok=false;
 if(!d.kind){sub=tr('ccliNone');bad=true;}
 else if(d.kind==='native'&&!d.version){sub=tr('ccliNative',d.path||'');}
 else if(d.state==='running'){
  const sec=d.started?Math.max(0,Math.round(Date.now()/1000-d.started)):0;
  sub=tr('ccliRunning',nm,where,d.target==='latest'?(d.latest||''):d.target)+' · '+tr('ccliSec',sec);pre=d.log;bar='<div class="upd-bar ccli-bar"><i></i></div>';
 }else{
  if(d.state==='failed'){sub=tr('ccliFailed',d.err||'');bad=true;pre=d.log;}
  else if(d.state==='done'&&fresh){
   sub=d.op==='rollback'?tr('ccliDoneRb',d.from_version,d.version_after||d.version):tr('ccliOkTitle',nm,d.from_version,d.version_after||d.version);ok=true;pre=d.log;
   next=tr(r&&r.running===false?(k==='codex'?'ccliNextCodexStopped':'ccliNextClaudeStopped'):(k==='codex'?'ccliNextCodex':'ccliNextClaude'));
  }
  else if(d.update_available)sub=tr('ccliLatest',d.latest);
  else sub=tr(d.latest?'ccliUpToDate':'ccliNeverChecked');
  if(r&&r.stale&&!ok)next=tr(k==='codex'?'ccliStaleNote':'ccliStaleClaude');
  if(d.kind==='npm'&&(!d.node||!d.node.ready)){sub=tr('ccliNoNode');bad=true;}
  else{
   btns+='<button type="button" class="ghostbtn" data-ccli="check">'+tr('ccliBtnCheck')+'</button>';
   if(d.state!=='failed'&&d.update_available&&d.can_update)btns+='<button type="button" class="ghostbtn" data-ccli="update" data-k="'+k+'" data-v="'+ccpEsc(d.latest)+'">'+ccpEsc(tr('ccliBtnUpdate',d.latest))+'</button>';
   else if(d.state==='failed'&&d.can_update)btns+='<button type="button" class="ghostbtn" data-ccli="update" data-k="'+k+'" data-v="latest">'+tr('ccliBtnRetry')+'</button>';
   if(d.prev_version&&d.can_update)btns+='<button type="button" class="ghostbtn" data-ccli="rollback" data-k="'+k+'" data-v="'+ccpEsc(d.prev_version)+'">'+ccpEsc(tr('ccliBtnRollback',d.prev_version))+'</button>';
   if(r&&r.running&&(r.stale||ok))btns+='<button type="button" class="ghostbtn" data-ccli="restart" data-k="'+k+'"'+(r.busy?' disabled':'')+'>'+tr(k==='codex'?'ccliRestartBtn':'ccliRestartClaude')+'</button>';
  }
 }
 return '<div class="updrow"><div class="updtxt">'+head+'<div class="updsub'+(bad?' bad':ok?' ok':'')+'">'+ccpEsc(sub)+'</div>'+bar
  +(next?'<div class="updsub">'+ccpEsc(next)+'</div>':'')+(pre?'<pre>'+ccpEsc(pre)+'</pre>':'')+'</div><div class="ccli-btns">'+btns+'</div></div>';
}
function ccliRender(){
 const box=$('#ccliBox');if(!box||$('#scrim').hidden)return;
 const d=ccliData;if(!d){box.innerHTML='';return;}
 box.innerHTML=ccliRow('local',d.local)+ccliRow('remote',d.remote)+ccliRow('codex',d.codex)
  +(ccliMsg?'<div class="modalsub" style="margin:0">'+ccpEsc(ccliMsg)+'</div>':'')
  +'<div class="modalsub" style="margin:6px 0 0">'+tr('ccliHint')+'</div>';
}
$('#ccliBox').addEventListener('click',async e=>{
 const b=e.target.closest('[data-ccli]');if(!b||!ccliData)return;
 const act=b.dataset.ccli,k=b.dataset.k,v=b.dataset.v;
 if(act==='check'){b.disabled=true;ccliMsg='';return ccliLoad(true);}
 const d=ccliData[k]||{},where=tr(k==='remote'?'ccliProd':'ccliThis'),nm=k==='codex'?'Codex':'Claude Code';
 const q=act==='restart'?(k==='codex'?tr('ccliAskRestart'):tr('ccliAskRestartClaude',where)):act==='update'?tr('ccliAskUpdate',nm,where,d.version||'',v==='latest'?(d.latest||''):v):tr('ccliAskRollback',nm,where,d.version||'',v);
 if(!await window.fleetAsk(b,q,tr('askYes')))return;
 b.disabled=true;
 try{const r=await ccliPost(act,{target:k,version:act==='update'?v:undefined});ccliMsg=r.ok?'':tr('ccliE_'+(r.error||'x'));}catch(x){ccliMsg=tr('ccliE_x');}
 ccliLoad(false);
});
// Бейдж «есть новая версия» в шапке (Claude Code, Claude Code на PROD, Codex) и окошко «Обновить / Отмена»
function ccliNews(){
 const d=ccliData;if(!d)return [];
 return ['local','remote','codex'].filter(k=>{const x=d[k];if(!x||x.ok===false||!x.kind)return false;
  return (x.update_available&&x.can_update)||x.state==='running'||!!(x.restart&&x.restart.stale)||(ccliPopOpen&&(x.state==='done'||x.state==='failed'));}).map(k=>[k,d[k]]);
}
function ccliPopRender(){
 const pop=$('#ccliPop');if(!pop||!ccliPopOpen)return;
 const rows=ccliNews().map(([k,d])=>{
  const nm=k==='codex'?'Codex':'Claude Code',where=tr(k==='remote'?'ccliProd':'ccliThis'),r=d.restart||null,fresh=!!d.finished&&(Date.now()/1000-d.finished)<600;
  let sub='',btn='',bar='',cls='';
  if(d.state==='running'){
   const sec=d.started?Math.max(0,Math.round(Date.now()/1000-d.started)):0;
   sub=tr('ccliRunning',nm,where,d.target==='latest'?(d.latest||''):d.target)+' · '+tr('ccliSec',sec);bar='<div class="upd-bar ccli-bar"><i></i></div>';
  }
  else if(d.state==='done'&&fresh){
   sub=d.op==='rollback'?tr('ccliDoneRb',d.from_version,d.version_after||d.version):tr('ccliOkTitle',nm,d.from_version,d.version_after||d.version);cls=' ok';
   sub+=' '+tr(r&&r.running===false?(k==='codex'?'ccliNextCodexStopped':'ccliNextClaudeStopped'):(k==='codex'?'ccliNextCodex':'ccliNextClaude'));
  }
  else if(d.state==='failed'){
   sub=tr('ccliFailed',d.err||'');cls=' bad';
   if(d.can_update)btn='<button type="button" class="ghostbtn" data-ccli-pop="update" data-k="'+k+'" data-v="latest">'+tr('ccliBtnRetry')+'</button>';
  }
  else if(d.update_available&&d.can_update){sub=tr('ccliPopSub',d.version||'',d.latest||'');btn='<button type="button" class="ghostbtn" data-ccli-pop="update" data-k="'+k+'" data-v="'+ccpEsc(d.latest||'latest')+'">'+tr('ccliPopUpdate')+'</button>';}
  else if(r&&r.stale)sub=tr(k==='codex'?'ccliStaleNote':'ccliStaleClaude');
  if(r&&r.running&&(r.stale||(d.state==='done'&&fresh)))btn='<button type="button" class="ghostbtn" data-ccli-pop="restart" data-k="'+k+'"'+(r.busy?' disabled':'')+'>'+tr(k==='codex'?'ccliRestartBtn':'ccliRestartClaude')+'</button>';
  return '<div class="cp-row"><div><b>'+ccpEsc(nm+' '+where)+'</b><small class="'+cls.trim()+'">'+ccpEsc(sub)+'</small>'+bar+'</div>'+btn+'</div>';
 }).join('');
 pop.innerHTML='<h4>'+tr('ccliPopTitle')+'</h4>'+(rows||'<div class="cp-row"><small>'+tr('ccliPopNone')+'</small></div>')
  +(ccliMsg?'<div class="cp-note bad">'+ccpEsc(ccliMsg)+'</div>':'')
  +'<div class="cp-note">'+tr('ccliPopNote')+'</div><div class="cp-foot"><button type="button" class="ghostbtn" data-ccli-pop="close">'+tr('ccliPopCancel')+'</button></div>';
}
function ccliBadgeRender(){
 const b=$('#ccliBadge');if(!b)return;
 const news=ccliNews();
 b.hidden=!news.length&&!ccliPopOpen;
 const n=b.querySelector('b');if(n)n.textContent=String(news.length);
 b.title=tr('ccliBadgeTitle',news.length);
 ccliPopRender();
}
function ccliPopClose(){ccliPopOpen=false;const p=$('#ccliPop');if(p)p.hidden=true;ccliBadgeRender();}
$('#ccliBadge').addEventListener('click',e=>{
 e.stopPropagation();
 if(ccliPopOpen)return ccliPopClose();
 ccliPopOpen=true;ccliMsg='';
 const p=$('#ccliPop'),r=e.currentTarget.getBoundingClientRect();p.hidden=false;
 p.style.top=(r.bottom+8)+'px';p.style.left=Math.max(12,Math.min(r.left,innerWidth-356))+'px';
 ccliPopRender();ccliLoad(false);
});
$('#ccliPop').addEventListener('click',async e=>{
 const b=e.target.closest('[data-ccli-pop]');if(!b)return;
 const act=b.dataset.ccliPop;
 if(act==='close')return ccliPopClose();
 if(act==='restart'){const k=b.dataset.k;if(!await window.fleetAsk(b,k==='codex'?tr('ccliAskRestart'):tr('ccliAskRestartClaude',tr(k==='remote'?'ccliProd':'ccliThis')),tr('askYes')))return;}
 b.disabled=true;
 try{const r=await ccliPost(act,{target:b.dataset.k,version:act==='update'?b.dataset.v:undefined});ccliMsg=r.ok?'':tr('ccliE_'+(r.error||'x'));}catch(x){ccliMsg=tr('ccliE_x');}
 ccliLoad(false);
});
document.addEventListener('click',e=>{if(ccliPopOpen&&!e.target.closest('#ccliPop,#ccliBadge'))ccliPopClose();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&ccliPopOpen)ccliPopClose();});
// Версия программы в правом верхнем углу КАЖДОГО окна консоли: жёлтая — старая (запущена до обновления или есть новее), зелёная — актуальная
function ccliPvInfo(s,x){
 const k=s==='prod'?'remote':s==='codex'?'codex':s==='claude'?'local':'';
 if(!k||!x||x.ok===false||!x.version)return null;
 const stale=!!(x.restart&&x.restart.stale),old=stale||!!x.update_available;
 return {k:k,old:old,text:(k==='codex'?'Codex ':'Claude Code ')+x.version,
  title:old?tr(stale?(k==='codex'?'ccliStaleNote':'ccliStaleClaude'):'ccliPvOld'):tr('ccliPvNew')};
}
function ccliPartVers(){
 const wrap=document.querySelector('.termwrap');if(!wrap||typeof PANES==='undefined')return;
 let box=document.getElementById('ccliPv');
 if(!box){box=document.createElement('div');box.id='ccliPv';box.className='ccli-pvbox';wrap.appendChild(box);}
 const wr=wrap.getBoundingClientRect(),off=wrap.classList.contains('tsplit')?40:10;   // под шапкой части (30 px), иначе надпись оказывается под ней
 PANES.forEach((P,i)=>{
  const id='ccliPv'+i;let el=document.getElementById(id);
  const d=ccliData,info=P.k&&d?ccliPvInfo(P.k,d[P.k==='prod'?'remote':P.k==='codex'?'codex':'local']):null,b=P.box,r=b&&b.getBoundingClientRect();
  if(!info||P.hid||!r||r.width<140||b.offsetParent===null){if(el)el.hidden=true;return;}
  if(!el){el=document.createElement('span');el.id=id;box.appendChild(el);}
  el.className='ccli-pv '+(info.old?'old':'new');el.textContent=info.text;el.title=info.title;el.hidden=false;
  el.style.top=Math.round(r.top-wr.top+off)+'px';el.style.left=Math.round(r.right-wr.left-el.offsetWidth-18)+'px';
 });
}
setInterval(ccliPartVers,2000);addEventListener('resize',ccliPartVers);setTimeout(()=>{ccliLoad(false);},1500);
// Пауза по лимитам в окне консоли Claude DEV, Claude PROD и Codex: пока работа стоит на лимитах, видно, что это пауза, до какого часа и что сообщения встают в очередь
function ccpsHtml(k){
 const at=(ms,r,lead)=>'<b>⏸ '+tr(lead)+'</b>'+(ms?tr('ccpsUntil',ccpAt(ms),ccpLeft(ms)):'')+(r?' · '+ccpEsc(r):'');
 // Claude: тот же нормализованный бюджет, что в отдельных верхних плашках.
 // Исчерпанные 100% обозначает крестик; ожидание настроенного порога — пауза.
 if((k==='claude'||k==='prod')&&ccpData&&ccpData.claude_limits){
  const s=ccpData.claude_limits[k];if(!s||!s.waiting||typeof s.pct==='number'&&s.pct>=100)return '';
  const until=(+s.resume_at||0)*1000,name=k==='prod'?'Claude PROD':'Claude DEV';
  const title=tr(s.window==='pause'?'ccpaPause':s.window==='week'?'ccpaWeek':'ccpaSession',name,s.pct==null?'?':Math.round(s.pct),until?ccpAt(until):'');
  return '<b>⏸ '+ccpEsc(title)+'</b>. '+ccpEsc(tr(s.window==='pause'?'ccpaKnownPause':'ccpaWait',s.threshold));
 }
 if(k==='prod'){const rp=ccpData&&ccpData.remote_pause;if(!(rp&&rp.enabled&&rp.applied&&rp.blocked))return '';
  return at((rp.resume_at||0)*1000,(rp.reasons||[]).join('; '),'ccpsTitle')+'. '+tr('ccpsBody');}
 if(k==='codex'){const p=typeof cxlpData!=='undefined'?cxlpData:null;if(!(p&&p.active&&p.paused)||p.hard)return '';
  return at((p.resume_at||0)*1000,(p.windows||[]).map(m=>tr('cxlpWin',m)).join(', '),'ccpsTitleCx')+'. '+tr('ccpsBodyCx');}
 // Claude DEV: пауза балансера этого сервера (та же, что в верхнем баннере); отключена вручную или снимок устарел — паузы нет
 if(k==='claude'){const p=ccpData&&!ccpData.stale&&ccpData.pause;if(!(p&&p.active&&!p.override))return '';
  return at((p.resume_at||0)*1000,p.reason||'','ccpsTitle')+'. '+tr('ccpsBody');}
 return '';
}
// ---- Лимит агента: бейдж на верхней рамке строки «Активных аккаунтов» и большая иконка в окне консоли — ОДНО правило на оба места.
// Пауза по лимитам (та же, что у ccpsHtml) важнее исчерпания. Исчерпан — настоящий лимит: окно 5 ч или недели на 100 % и его сброс ещё не прошёл
// (Claude DEV и PROD — по снимку лимитов; Codex — limit_notice сервера, там же «сервис сказал: лимит», в том числе при единственном аккаунте, когда паузы нет).
/*LIMX-PURE-START*/
// pause: null | {until: мс}; wins: [{win:'5h'|'week'|'', pct, until: мс | 0}]; reported — лимит назван сервисом без окна
// → null | {kind:'pause'|'out', win, until}
function limxPick(pause,wins,reported,now){
 if(pause)return {kind:'pause',win:'',until:pause.until||0};
 const full=(wins||[]).filter(w=>w&&typeof w.pct==='number'&&w.pct>=100&&!(w.until&&now>w.until+120000));  // сброс прошёл (2 мин запаса) — окно уже свободно, цифры просто старые
 if(!full.length)return reported?{kind:'out',win:'',until:0}:null;
 // исчерпаны оба окна — показываем то, что кончается позже: реально ждать до него; одинаково — неделю
 const w=full.reduce((a,b)=>(b.until||0)>(a.until||0)||((b.until||0)===(a.until||0)&&b.win==='week')?b:a);
 return {kind:'out',win:w.win||'',until:w.until||0};
}
/*LIMX-PURE-END*/
function limxWinOf(w,name){const t=w&&w.resets_at?Date.parse(w.resets_at):NaN;return {win:name,pct:w&&typeof w.pct==='number'?w.pct:null,until:isNaN(t)?0:t};}
function limxState(k){
 let pause=null,wins=[],reported=false;
 try{
  if((k==='claude'||k==='prod')&&ccpData&&ccpData.claude_limits){
   const s=ccpData.claude_limits[k];if(!s)return null;
   const until=(+s.resume_at||0)*1000,full=typeof s.pct==='number'&&s.pct>=100;
   if(s.waiting&&!full)pause={until};
   if(s.window==='week'||s.window==='5h')wins=[{win:s.window,pct:s.pct,until}];
   return limxPick(pause,wins,false,Date.now());
  }
  if(ccpsHtml(k)){const d=ccpData||{},u=k==='prod'?(d.remote_pause||{}).resume_at:k==='codex'?(cxlpData||{}).resume_at:(d.pause||{}).resume_at;pause={until:(+u||0)*1000};}
  const snap=typeof lastSnap!=='undefined'?lastSnap:null;
  if(k==='claude'){const a=snap&&snap.accounts&&snap.accounts[snap.active];if(a)wins=[limxWinOf(a.five_hour,'5h'),limxWinOf(a.seven_day,'week')];}
  else if(k==='prod'){const r=snap&&snap.remote,m=r&&r[Object.keys(r)[0]];if(m)wins=[limxWinOf(m.five_hour,'5h'),limxWinOf(m.seven_day,'week')];}
  else if(k==='codex'){const p=typeof cxlpData!=='undefined'?cxlpData:null;
   if(p&&p.active){wins=(p.windows||[]).map(m=>({win:m===300?'5h':m===10080?'week':'',pct:p.policy?+(p.percentages||{})[m]:100,until:(+((p.resets||{})[m]||p.resume_at)||0)*1000}));reported=!p.policy&&!wins.length;}}
 }catch(e){return null;}
 return limxPick(pause,wins,reported,Date.now());
}
// время в надписи (часовой пояс панели): у недели — с днём недели «Чт 12.11 17:59»; иначе как у «пауза по лимитам до»: сегодня — «02:29», другой день — «12.11 02:29»
const LIMX_DF={};
function limxDf(o){const loc=LANG==='en'?'en-GB':'ru',key=loc+JSON.stringify(o);return LIMX_DF[key]||(LIMX_DF[key]=new Intl.DateTimeFormat(loc,Object.assign({hourCycle:'h23',timeZone:window.FLEET_TZ},o)));}
function limxAt(ms,week){
 const d=new Date(ms),dm=x=>limxDf({day:'2-digit',month:'2-digit'}).format(x).replace(/\//g,'.'),hm=limxDf({hour:'2-digit',minute:'2-digit'}).format(d);
 if(week){const wd=limxDf({weekday:'short'}).format(d).replace(/\.$/,'');return wd.charAt(0).toUpperCase()+wd.slice(1)+' '+dm(d)+' '+hm;}
 return dm(d)===dm(new Date())?hm:dm(d)+' '+hm;
}
const LIMX_NAMES={claude:'Claude DEV',prod:'Claude PROD',codex:'Codex'};
// short — узкий экран (телефон): без дня недели, чтобы бейдж уместился справа от названия строки
function limxText(s,short){return tr(s.kind==='pause'?'limxPause':s.win==='week'?'limxOutWeek':s.win==='5h'?'limxOut5h':'limxOut',s.until?limxAt(s.until,s.kind==='out'&&s.win==='week'&&!short):'');}
function limxTitle(k,s){return (LIMX_NAMES[k]||k)+': '+limxText(s)+'. '+tr(s.kind==='pause'?'limxTipPause':'limxTipOut');}
// бейдж — «пилюля» на верхней рамке строки аккаунта (position:absolute в .fleet-acc): ничего не сдвигает и строки не занимает
const LIMX_NARROW=matchMedia('(max-width:640px)');
function limxBadges(){
 const rows=document.getElementById('fleetLiveRows');if(!rows)return;
 rows.querySelectorAll(':scope>.fleet-acc[data-engine]').forEach(acc=>{
  const k=acc.dataset.engine,s=limxState(k);let b=acc.querySelector(':scope>.fleet-acc-badge');
  if(!s){if(b)b.remove();return;}
  if(!b){b=document.createElement('span');b.className='fleet-acc-badge';b.innerHTML='<i aria-hidden="true"></i><span></span>';acc.appendChild(b);}
  const t=limxText(s,LIMX_NARROW.matches),tip=limxTitle(k,s);
  if(b.dataset.kind!==s.kind)b.dataset.kind=s.kind;
  if(b.lastChild.textContent!==t)b.lastChild.textContent=t;
  if(b.title!==tip){b.title=tip;b.setAttribute('aria-label',tip);}
  // на рамке ВИДИМОЙ строки (свёрнутой или раскрытой; на телефоне строка PROD и Codex ниже обёртки на 2 px) и не заходит на название:
  // ширина — до места справа от названия, длиннее — многоточие (полный текст — в подсказке)
  const row=[...acc.children].find(c=>c!==b&&c.offsetParent!==null),top=(row?row.offsetTop:0)+'px';
  if(b.style.top!==top)b.style.top=top;
  const nm=row&&row.querySelector('.fleet-compact-name,.fleet-live-name');let mw='';
  if(nm&&nm.textContent.trim()){const g=document.createRange();g.selectNodeContents(nm);const nr=g.getBoundingClientRect(),rr=row.getBoundingClientRect();
   if(nr.width&&nr.top<rr.top+9)mw=Math.max(56,Math.floor(acc.getBoundingClientRect().right-14-(nr.right+10)))+'px';}
  if(b.style.maxWidth!==mw)b.style.maxWidth=mw;
 });
}
setInterval(limxBadges,1000);
function ccpsWindows(k,s){
 let windows=[];
 if(k==='codex'){
  const p=typeof cxlpData!=='undefined'&&cxlpData||{},mins=p.windows||[];
  windows=mins.map(m=>({window:m===300?'5h':m===10080?'week':'',resume_at:(p.resets||{})[m]||(mins.length===1?p.resume_at:0)||0}));
 }else if(ccpData&&ccpData.claude_limits){
  const q=ccpData.claude_limits[k];if(q)windows=q.windows||[{window:q.window==='pause'?'':q.window,resume_at:q.resume_at||0}];
 }else{
  const snap=typeof lastSnap!=='undefined'&&lastSnap||{},rows=snap.remote||{};
  const a=k==='claude'?(snap.accounts||{})[snap.active]:rows[Object.keys(rows)[0]],d=ccpData||{};
  for(const [key,window,threshold] of [['five_hour','5h',d.threshold||90],['seven_day','week',d.weekly_cap||99]]){
   const w=a&&a[key];if(w&&typeof w.pct==='number'&&(w.pct>=100||s.kind==='pause'&&w.pct>=threshold))windows.push({window,resume_at:(limxWinOf(w,window).until||0)/1000});
  }
 }
 if(!windows.length)windows=[{window:s.win||'',resume_at:(s.until||0)/1000}];
 return [...new Map(windows.map(w=>[w.window,w])).values()].sort((a,b)=>['5h','week',''].indexOf(a.window)-['5h','week',''].indexOf(b.window));
}
function ccpsCountdown(until,now){
 if(!Number.isFinite(until)||until<=0)return tr('ccpsUnknown');
 let left=Math.max(0,Math.ceil((until-now)/1000));const days=Math.floor(left/86400);left%=86400;
 const pad=n=>String(n).padStart(2,'0');
 return (days?tr('ccpsDays',days)+' ':'')+pad(Math.floor(left/3600))+':'+pad(Math.floor(left%3600/60))+':'+pad(left%60);
}
function ccpsTimerHtml(k,s,now){
 const windows=ccpsWindows(k,s);
 return windows.map(w=>{
  const caption=tr(w.window==='5h'?'ccpsReset5h':w.window==='week'?'ccpsResetWeek':'ccpsReset'),value=ccpsCountdown((+w.resume_at||0)*1000,now);
  return '<div class="ccps-clock" style="--ccps-count:'+windows.length+';--ccps-chars:'+value.length+';--ccps-caption-chars:'+caption.length+'"><div class="ccps-caption">'+ccpEsc(caption)+'</div><div class="ccps-value'+(!w.resume_at?' ccps-unknown':'')+'" role="timer" aria-live="off">'+ccpEsc(value)+'</div></div>';
 }).join('');
}
function ccpPlain(h){return String(h).replace(/<[^>]+>/g,'').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&amp;/g,'&');}
function ccpPartStrip(){
 const wrap=document.querySelector('.termwrap');if(!wrap||typeof PANES==='undefined')return;
 let box=document.getElementById('ccps');
 const sts=PANES.map(P=>limxState(P.k));
 if(!box){if(!sts.some(Boolean))return;box=document.createElement('div');box.id='ccps';box.className='ccps-box';wrap.appendChild(box);}
 const wr=wrap.getBoundingClientRect();
 PANES.forEach((P,i)=>{
  const id='ccps'+i;let el=document.getElementById(id);
  const s=sts[i],b=P.box,r=b&&b.getBoundingClientRect();
  if(!s||P.hid||!r||r.width<200||b.offsetParent===null){if(el)el.hidden=true;return;}
  if(!el){el=document.createElement('div');el.id=id;el.className='ccps';box.appendChild(el);}
  // Полупрозрачный обратный отсчёт по центру своей части, обновляется каждую секунду.
  const html=ccpsTimerHtml(P.k,s,Date.now());if(el.innerHTML!==html)el.innerHTML=html;el.dataset.kind=s.kind;
  el.title=s.kind==='pause'?ccpPlain(ccpsHtml(P.k)):limxTitle(P.k,s);el.hidden=false;
  el.style.top=Math.round(r.top-wr.top)+'px';el.style.left=Math.round(r.left-wr.left)+'px';el.style.width=Math.round(r.width)+'px';el.style.height=Math.round(r.height)+'px';
 });
}
setInterval(ccpPartStrip,1000);addEventListener('resize',ccpPartStrip);
setTimeout(()=>ccliLoad(true),8000);       // после загрузки страницы — тихая проверка версий
setInterval(()=>ccliLoad(true),1800000);   // и раз в полчаса
$('#gear').addEventListener('click',()=>{bkMsg='';updSettingsRender();updLoad();bkLoad();ccliMsg='';ccliLoad(!ccliData||Date.now()/1000-((ccliData.local&&ccliData.local.checked)||0)>((ccliData.local&&ccliData.local.ttl)||1800));});
applyI18n();load();setInterval(()=>load(),60000);cxLoad();setInterval(()=>cxLoad(),60000);cxbLoad(true);setInterval(()=>cxbLoad(),15000);
updLoad();
ccpLoad();setInterval(ccpLoad,20000);setInterval(ccpTick,1000);
cxlpLoad();setInterval(cxlpLoad,30000);setInterval(cxlpTick,1000);
try{if(sessionStorage.getItem('cc_upd_reopen')){sessionStorage.removeItem('cc_upd_reopen');$('#gear').click();}}catch(e){}
</script></body></html>"""


import cc_fleet
cc_fleet.install(globals())

def _remote_loop():
    # [remote] лимиты удалённых аккаунтов (прод друга) раз в минуту; кэш внутри держит 3 минуты
    while True:
        try:
            cc_remote.refresh_all()
            import cc_remote_limits
            cc_remote_limits.tick(globals())
            with lock:
                _claude_limit_tick(jload(SNAPSHOT, {}))
        except Exception as e:
            print("remote: ошибка опроса", type(e).__name__, flush=True)
        time.sleep(30)


# Сторож обновлений Claude Code и Codex → сообщения в Telegram (cc_cli_notice): вышла новая версия, обновлён, не удалось.
# Версии в сети проверяет раз в 6 часов, итог обновления (кнопкой в панели) ловит за ~минуту; PROD — раз в 10 минут, пока идёт обновление — чаще.
def _cli_notice_loop():
    import claude_cli
    time.sleep(45)
    last_check = last_remote = 0.0
    remote_running = False
    while True:
        try:
            now = time.time()
            check = now - last_check > 6 * 3600
            views = {}
            loc = claude_cli.status(check=check)
            if loc.get("kind"):
                loc["restart"] = claude_restart_info_local(loc)
                views["claude@local"] = loc
            cbin = codex_bin()
            if cbin:
                claude_cli.BIN_HINT["codex"] = cbin
                cx = claude_cli.status(check=check, tool="codex")
                if cx.get("kind"):
                    cx["restart"] = codex_restart_info(cx)
                    views["codex@local"] = cx
            if check or now - last_remote > (30 if remote_running else 600):
                last_remote = now
                try:
                    import cc_remote_mode
                    if cc_remote_mode._member_id():
                        r = cc_remote_mode.cli_remote("status", *(["check"] if check else []))
                        if isinstance(r, dict) and r.get("ok") and r.get("kind"):
                            r["restart"] = claude_restart_info_remote(r)
                            views["claude@remote"] = r
                            remote_running = r.get("state") == "running"
                except Exception:
                    pass
            if check:
                last_check = now
            cc_cli_notice.tick(views)
        except Exception as e:
            print("cli-notice:", type(e).__name__, flush=True)
        time.sleep(60)


if __name__ == "__main__":
    try:  # internal_secret для _index_authed(): один раз, переживает перезапуски и обновления
        _c = cfg()
        if not _c.get("internal_secret"):
            _c["internal_secret"] = os.urandom(24).hex()
            jsave(CONFIG, _c)
    except Exception as e:
        print("internal_secret: не создан", e, flush=True)
    try:
        made = {n: s for n, s in ensure_cmd_links().items() if s != "есть"}
        if made:
            print("команды cl/cla/cln/clw/cxw:", made, flush=True)
    except Exception as e:  # команды — удобство, из-за них сервис не падает
        print("команды cl/cla/cln/clw/cxw: ошибка", e, flush=True)
    threading.Thread(target=poll_loop, daemon=True).start()
    threading.Thread(target=_dialog_watchdog, daemon=True).start()
    threading.Thread(target=_remote_loop, daemon=True, name="cc-remote-loop").start()
    threading.Thread(target=UPDATER.loop, daemon=True, name="cc-update-loop").start()
    threading.Thread(target=_cli_notice_loop, daemon=True, name="cc-cli-notice").start()
    cc_codex_emergency.start()  # аварийный режим: после перезапуска довести до рабочего состояния или снять, запустить сторож срока
    cc_backup.start(lambda: PROFILES, BACKUP_DIR, lambda: cfg().get("profile_backup", True) is not False)  # копии профилей аккаунтов
    if globals().get("FLEET_PROFILES") is not None:  # такт профилей: доступность, автосценарий, восстановление прерванного переключения
        FLEET_PROFILES.start()
    cc_codex_bridge.BRIDGE.sync()  # мост Telegram ↔ Codex: поднимется, только если включён в карточке
    port = cfg().get("port", 8877)
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"cc-limits up on 127.0.0.1:{port}", flush=True)
    srv.serve_forever()
