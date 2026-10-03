#!/usr/bin/env python3
# cc-limits — мониторинг лимитов Pro/Max-аккаунтов Claude Code + авто-переключение.
# Запуск: systemd unit (порт задаётся в config.json, ключ "port", по умолчанию 8877;
# снаружи — через nginx /cc/, см. install.sh).
import fcntl, html, json, os, re, shutil, struct, subprocess, tempfile, termios, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pyte
import cc_avail
import cc_update
import pexpect

VERSION = "1.19.0"  # равна версии релиза; cc_update сверяет её с манифестом перед заменой файлов

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
SWITCH_LOG = os.path.join(BASE, "switch_log.jsonl")  # аудит forced-веток optimize_check
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
        return  # телеграм-уведомления не настроены — тихо пропускаем
    token = tg_token()
    if not token:
        # раньше здесь был молчаливый return — человек не понимал, почему тихо
        print("tg_notify: chat_id задан, но токен бота не найден (ни в %s, "
              "ни в ключе bot_token в config.json)" % TG_ENV, flush=True)
        return
    try:
        http_json(f"https://api.telegram.org/bot{token}/sendMessage",
                  {"chat_id": chat_id, "text": text})
    except Exception as e:
        print(f"tg_notify fail: {e}", flush=True)


# автообновление из GitHub Releases (cc_update.py): проверка раз в сутки, ручной/авто режим
UPDATER = cc_update.Updater(BASE, VERSION, cfg, notify=tg_notify)


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


# Удаление необратимо: стирается папка профиля с токенами. Слово подтверждения сервер
# проверяет сам — запрос без него не пройдёт, даже если дёрнуть API напрямую.
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
        if not oa.get("accountUuid") and not os.path.isfile(f"{d}/credentials.json"):
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


def delete_account(name, confirm, lang="ru"):
    """→ (ok, message, snapshot|None). Убирает аккаунт из ротации навсегда: профиль с токенами,
    строки в снимке, кэшах и state. Берёт lock сама — снаружи не оборачивать."""
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
        real = _real_names()
        if name in real and len(real) <= 1:
            return False, _t(lang, "Это последний аккаунт в ротации — удалить его нельзя.",
                             "This is the last account in the rotation — it cannot be deleted."), None
        oa = jload(f"{pdir}/oauth_account.json", {}) or {}
        email = oa.get("emailAddress") or ""
        moved = None
        if active_name() == name:
            moved, why = _move_off(name)
            if not moved:
                return False, _t(lang, "Это активный аккаунт, а переключить сессию на другой не удалось — ничего не удалено. ",
                                 "This is the active account and the session could not be moved to another one — nothing was deleted. ") + why, None
        _relogin_cleanup(name)
        try:
            shutil.rmtree(pdir)
        except OSError as e:
            return False, _t(lang, f"Не удалось стереть профиль: {e}", f"Could not wipe the profile: {e}"), None
        _plan_cache.pop(name, None)
        backoff_until.pop(name, None)
        good = jload(GOOD, {}) or {}
        if good.pop(name, None) is not None:
            jsave(GOOD, good)
        st = jload(STATE, {})
        for k in ("plans", "renewal", "renew_click"):
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
    tg_notify(f"🗑 Claude: аккаунт {who} удалён из ротации навсегда — профиль и токены стёрты, вернуть нельзя."
              + (f" Живая сессия переведена на {moved}." if moved else "")
              + f" В ротации осталось: {cnt} ({names}).")
    return True, (_t(lang, f"🗑 {who} удалён навсегда.", f"🗑 {who} deleted for good.")
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
        reason = (data.get("error_description") or data.get("error") or "").strip()
        low = reason.lower()
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
    return str(e)


def collect(force=False, force_account=None):
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
    for n in profile_names():
        oa = jload(f"{PROFILES}/{n}/oauth_account.json", {})
        row = {"email": oa.get("emailAddress", "?"), "active": n == act}
        errs = []
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
        stale_ok = (n != act and n != force_account and old.get("ts")
                    and time.time() - old["ts"] < cfg().get("inactive_poll_sec", 300)
                    and not cc_avail.reset_passed(old))
        # после 429 этот аккаунт не трогаем до конца его паузы — показываем кэш
        if n != force_account and old.get("ts") and time.time() < backoff_until.get(n, 0):
            stale_ok = True
        if stale_ok:
            row["five_hour"] = old.get("five_hour")
            row["seven_day"] = old.get("seven_day")
            row["plan"] = old.get("plan")
            row["stale_ts"] = old.get("ts")
            accounts[n] = row
            continue
        try:
            access = get_access(n, act)
        except Exception as e:
            errs.append(_humanize_error(e))
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
                errs.append(_humanize_error(e))
            try:
                row["plan"] = fetch_plan(n, access)
            except Exception as e:
                errs.append(_humanize_error(e))
        if "five_hour" in row and "plan" in row:
            good[n] = {"five_hour": row["five_hour"], "seven_day": row["seven_day"],
                       "plan": row["plan"], "ts": int(time.time())}
        if errs:
            row["error"] = " | ".join(errs)[:200]
            if any("429" in e for e in errs):
                backoff_until[n] = time.time() + cfg().get("poll_sec", 120) * 2
            # разовый сбой (429 и т.п.) не должен стирать карточку — показать
            # последние удачные цифры из отдельного кэша с пометкой возраста
            # (только для того, что реально не получили в этом цикле)
            old = good.get(n) or {}
            for k in ("five_hour", "seven_day", "plan"):
                if row.get(k) is None and old.get(k) is not None:
                    row[k] = old[k]
            row["stale_ts"] = old.get("ts")
        accounts[n] = row
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
                if was == "free":
                    # продление, замеченное фоном (кнопка «Я продлил» могла не
                    # дождаться Anthropic) — якорь таймера = момент нажатия, если был
                    click = (st.get("renew_click") or {}).get(n, 0)
                    anchor = click if time.time() - click < 6 * 3600 else time.time()
                    st.setdefault("renewal", {})[n] = {"confirmed_ts": anchor}
                    (st.get("renew_click") or {}).pop(n, None)
                    jsave(STATE, st)
    if cur != prev:
        st["plans"] = {**prev, **cur}
        jsave(STATE, st)
    return snap


SETTINGS = "/root/.claude/settings.json"
TRANSCRIPTS = "/root/.claude/projects/-root"
MODELS = {  # id → короткое имя для UI
    "claude-fable-5": "Fable 5",
    "claude-fable-5-1": "Fable 5.1",
    "claude-opus-5": "Opus 5",
    "claude-opus-5-5": "Opus 5.5",
    "claude-sonnet-5": "Sonnet 5",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
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
    # ch.underscore сознательно НЕ рендерим: на свежей (не --continue) сессии
    # claude встречается терминальный баг, при котором SGR-underline остаётся
    # "залипшим" почти на всём экране (десятки % ячеек, включая статус-бар) -
    # так как 100%-покрытие экрана подчёркиванием никогда не несёт полезного
    # сигнала в консольном зеркале, безопаснее не отрисовывать этот атрибут.
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
    c = cfg()
    models = all_models()
    enabled = c.get("enabled_models") or list(models.keys())  # ничего не скрыто, пока не сузили в панели
    added_ts = c.get("model_added_ts") or {}
    now = time.time()
    return {"session": sess, "session_name": models.get(sess, sess),
            "default": dflt, "default_name": models.get(dflt, dflt),
            "available": [{"id": k, "name": v, "enabled": k in enabled,
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
        files = [os.path.join(TRANSCRIPTS, f) for f in os.listdir(TRANSCRIPTS) if f.endswith(".jsonl")]
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
        # ручной пин: пользователь сознательно выбрал забитый аккаунт — не трогать до сброса его сессии
        hold = st.get("manual_hold") or {}
        if hold.get("account") == act and time.time() < hold.get("until", 0):
            return
    # кулдаун против пинг-понга; с мёртвого (100% сессии/недели) уходим без него
    if not _dead(accs[act]) and time.time() - st.get("last_switch_ts", 0) < c.get("switch_cooldown_sec", 600):
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
        if not st.get("all_high_notified"):
            reason = "активный слетел в Free, а остальные недоступны" if act_free \
                else "все аккаунты упёрлись в сессию или неделю"
            tg_notify(f"⛔ Claude: {reason} — переключаться некуда, жду.\n"
                      + "\n".join(f"{n}: {(r.get('five_hour') or {}).get('pct')}% [{r.get('plan','?')}]" for n, r in accs.items())
                      + "\nРаньше всех освободится: " + _nearest_reset(accs))
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
    why = (f"аккаунт {act} слетел в Free" if act_free
           else f"сессия {act} дошла до {cur}%" if "сессия" in act_why
           else f"неделя {act} дошла до {cur_w}%")
    if ok:
        tg_notify(f"🔄 Claude: {why} — авто-переключил на {target} ({email}, сессия {fh}%). Рестарт не нужен.")
        snap_set_active()
    else:
        tg_notify(f"⚠️ Claude: авто-переключение на {target} не удалось: {out}")


def _dead(row):
    # аккаунт упёрся в 100% сессии или недели — работать на нём нельзя совсем
    return any(((row.get(k) or {}).get("pct") or 0) >= 100 for k in ("five_hour", "seven_day"))


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
    return (anchor + relativedelta(months=1)).isoformat()


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
        if forced and not st.get("all_high_notified"):
            # раньше уведомление отсюда убрали как спам, и «упёрлись ВСЕ аккаунты» стало
            # происходить молча — пользователь может не понимать, почему сессия не работает,
            # часами. Возвращаем ровно ОДНО сообщение на эпизод (флаг снимается только когда
            # снова появился живой кандидат) и не чаще раза в 2 часа. Это не тот спам, что
            # убирали: успешные переключения по-прежнему молчат.
            if time.time() - st.get("all_high_notified_ts", 0) >= 7200:
                tg_notify("⛔ Claude: все аккаунты упёрлись в лимит (сессия или неделя) — переключаться некуда.\n"
                          + _accs_line(accs)
                          + "\nБлижайшее окно: " + _nearest_reset(accs))
                st["all_high_notified_ts"] = time.time()
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
    ok, out = do_switch(target)
    st["last_switch_ts"] = now
    st["opt_last_switch_ts"] = now
    if ok:
        st["known_active"] = target
    jsave(STATE, st)
    _log_switch_event("switch", forced=forced, from_acc=act, to=target, fh=fh, why=why, ok=ok)
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
        wait = cfg().get("poll_sec", 120)
        nr = cc_avail.next_reset_ts((snap or {}).get("accounts") or {})
        if nr is not None:
            wait = min(wait, max(nr - time.time() + 15, 5))
        time.sleep(wait)


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
                renewal = jload(STATE, {}).get("renewal", {})
            for n, row in (snap.get("accounts") or {}).items():
                ts = (renewal.get(n) or {}).get("confirmed_ts")
                if ts:
                    row["renewal_next"] = _renewal_next(ts)
            act_n = active_name()
            for n, row in (snap.get("accounts") or {}).items():
                le = _login_expires(n, act_n)
                if le:
                    row["login_expires"] = le
            snap["config"] = {k: cfg().get(k) for k in ("autoswitch", "threshold", "optimize")}
            snap["model"] = model_info()
            return self._send(200, snap)
        if u.path == "/api/pause":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, pause_state())
        if u.path == "/api/update":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, UPDATER.status())
        if u.path == "/api/console":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            q = parse_qs(u.query)
            current_html, history_html = console_snapshot(want_history=bool(q.get("history")))
            resp = {"ok": True, "current": current_html}
            if history_html is not None:
                resp["history"] = history_html
            return self._send(200, resp)
        if u.path == "/api/models/candidates":
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, {"ok": True, "candidates": model_candidates()})
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
                st = jload(STATE, {})
                st.setdefault("renew_click", {})[name] = time.time()
                jsave(STATE, st)
                snap = collect(force=True, force_account=name)
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
                    "message": "⏳ Anthropic ещё не обновил план (всё ещё Free) — попробуй через минуту."})
            return self._send(200, {"ok": False, "plan": plan,
                "message": "Не удалось проверить план: " + (row.get("error") or "?")})
        if u.path == "/api/model":
            ok, msg = set_default_model(body.get("model", ""))
            return self._send(200 if ok else 400, {"ok": ok, "message": msg, "model": model_info()})
        if u.path == "/api/effort":
            ok, msg = set_effort(body.get("effort", ""))
            return self._send(200 if ok else 400, {"ok": ok, "message": msg, "model": model_info()})
        if u.path == "/api/session":
            ok, msg = send_session_command(body.get("cmd", ""))
            return self._send(200 if ok else 400, {"ok": ok, "message": msg})
        if u.path == "/api/pause":
            # кнопки «Отключить / Включить паузу» в баннере: pause_ctl off|on — тот же модуль,
            # что у будильника и хуков; лог — рядом с логом будильника
            action = body.get("action")
            if action not in ("off", "on"):
                return self._send(400, {"ok": False, "error": "action: off|on"})
            try:
                r = subprocess.run(["/usr/bin/python3", os.path.join(BASE, "pause_ctl.py"), action,
                                    "--by", "web panel"], capture_output=True, text=True, timeout=30,
                                   env=dict(os.environ, CC_LIMITS_BASE=BASE))
                with open(os.path.join(BASE, "pause_wake.log"), "a", encoding="utf-8") as f:
                    f.write(r.stdout + r.stderr)
                ok, out = r.returncode == 0, (r.stdout + r.stderr).strip()[-300:]
            except Exception as e:
                ok, out = False, str(e)[:200]
            d = pause_state()
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
        if u.path == "/api/config":
            c = cfg()
            for k in ("autoswitch", "threshold", "optimize"):
                if k in body:
                    c[k] = body[k]
            if body.get("update_mode") in ("manual", "auto"):
                c["update_mode"] = body["update_mode"]
            if isinstance(body.get("update_check"), bool):
                c["update_check"] = body["update_check"]
            if "enabled_models" in body:
                # неизвестные id молча отбрасываем; пустой список игнорируем целиком —
                # хотя бы одна модель должна остаться доступной для переключения
                ids = [m for m in body["enabled_models"] if m in all_models()]
                if ids:
                    c["enabled_models"] = ids
            jsave(CONFIG, c)
            UPDATER.kick()  # сменили режим обновлений — пусть петля пересмотрит сразу
            return self._send(200, {"ok": True, "autoswitch": c.get("autoswitch"),
                                    "threshold": c.get("threshold"), "optimize": c.get("optimize"),
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
        if u.path == "/api/relogin/submit":
            # lock берёт сама relogin_submit (вокруг записи в профиль + collect) —
            # тут НЕ оборачивать: lock не реентерабельный, второй with lock = дедлок
            name = body.get("account", "")
            ok, message, snap = relogin_submit(name, body.get("code", ""), lang=body.get("lang"))
            return self._send(200, {"ok": ok, "message": message})
        return self._send(404, {"error": "not found"})


PAGE = r"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude — лимиты аккаунтов</title>
<link rel="icon" href="data:,">
<script>try{var _s=localStorage.getItem('cc_skin');if(/^(phosphor|aurora|slate|blocks)$/.test(_s))document.documentElement.setAttribute('data-skin',_s)}catch(e){}</script>
<style>
:root{--bg:#0f1115;--card:#181c24;--txt:#e8eaf0;--mut:#8b93a7;--ok:#34c07c;--warn:#e8b93e;--bad:#e05b5b;--acc:#7c9aff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:16px;max-width:640px;margin:0 auto}
.hdr{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:4px 0 14px}
h1{font-size:19px;margin:0}
.hdrgear{background:transparent;border:1px solid #2a3140;color:var(--mut);width:28px;height:28px;padding:0;margin:0;border-radius:8px;font-size:14px;display:flex;align-items:center;justify-content:center;flex:none}
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
.ring{position:relative;flex:none}
.ring svg{display:block}
.ringtxt{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--txt);font-weight:700}
.iconrow{display:flex;gap:6px;flex:none}
.iconbtn{width:26px;height:26px;display:inline-flex;align-items:center;justify-content:center;background:var(--card);border:1px solid #2a3140;border-radius:7px;color:var(--mut);cursor:pointer;padding:0;margin:0;flex:none}
.iconbtn:hover{border-color:var(--acc);color:var(--txt)}
.iconbtn svg{width:14px;height:14px}
.row{margin-top:10px}
.lbl{display:flex;justify-content:space-between;font-size:12.5px;color:var(--mut);margin-bottom:4px}
.bar{height:10px;border-radius:99px;background:#242b38;overflow:hidden}
.fill{height:100%;border-radius:99px;transition:width .5s}
button{background:var(--acc);border:0;color:#0f1115;font-weight:700;padding:8px 14px;border-radius:10px;font-size:13.5px;cursor:pointer;margin-top:12px}
button:disabled{opacity:.35;cursor:default}
.thrbtn{background:var(--card);border:1px solid #2a3140;color:var(--txt);font-weight:700;padding:1px 9px;border-radius:6px;font-size:14px;line-height:1.6;margin:0}
.thrbtn:hover{border-color:var(--acc)}
.foot{display:flex;justify-content:space-between;align-items:center;color:var(--mut);font-size:12.5px;margin-top:6px;flex-wrap:wrap;gap:8px}
.err{color:var(--bad);font-size:13px;margin-top:8px}
.switchrow{display:flex;align-items:center;gap:8px;font-size:13.5px;color:var(--mut);margin-bottom:14px}
.switchrow input{transform:scale(1.25)}
#msg{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:#232a36;padding:10px 18px;border-radius:12px;font-size:14px;display:none;max-width:92vw;z-index:20}
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
html[data-skin] .ccp-btn.sec{border-color:rgba(127,127,127,.4);color:var(--mut);background:transparent}
html[data-skin] .ccp-btn.sec:hover{color:var(--txt);border-color:var(--ccp-accent)}
.ccp-link{font-size:12px;color:var(--mut);text-decoration:underline}
.ccp-link:hover{color:var(--txt)}
.upd-notes{margin-top:8px;font-size:12px;color:var(--mut)}
.upd-notes summary{cursor:pointer;color:var(--txt);font-weight:600}
.upd-notes pre{margin:6px 0 0;max-height:140px;overflow:auto;white-space:pre-wrap;word-break:break-word;font:11.5px/1.5 ui-monospace,Consolas,monospace;opacity:.9}
.upd-bar{margin-top:10px;height:3px;border-radius:99px;background:rgba(127,127,127,.25);overflow:hidden}
.upd-bar i{display:block;height:100%;width:35%;background:var(--ccp-accent);border-radius:99px;animation:updslide 1.4s ease-in-out infinite}
@keyframes updslide{0%{margin-left:-35%}100%{margin-left:100%}}
@media (prefers-reduced-motion:reduce){.upd-bar i{animation:none;width:100%;opacity:.45}}
.updrow{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:8px 0}
.updtxt{min-width:0;font-size:13px}
.updsub{font-size:12px;color:var(--mut);margin-top:2px}
.updsub.bad{color:var(--bad)}
.updchk{display:flex;align-items:flex-start;gap:8px;font-size:12px;color:var(--mut);margin-top:8px;cursor:pointer}
.updchk input{margin-top:2px}
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
.acts .chip.login{flex:0 0 auto}
.acts .chip.login+.btn-relogin{margin-left:0}
.poolname{width:100%;box-sizing:border-box;background:#0f1115;border:1px solid #2a3140;color:inherit;border-radius:6px;padding:5px 8px;font-size:13px}
.modal{max-width:380px;max-height:90vh;overflow-y:auto}
.modalh{font-size:12.5px;font-weight:700;margin:14px 0 4px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}
.skgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:4px}
.skgrid .skopt{font:inherit;font-size:13px;font-weight:400;text-align:left;margin:0;background:rgba(127,127,127,.12);border:1px solid rgba(127,127,127,.35);color:var(--txt);border-radius:10px;padding:8px;cursor:pointer;display:flex;flex-direction:column;gap:2px}
.skgrid .skopt:hover{border-color:var(--acc)}
.skgrid .skopt.on{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)}
.sknm{font-size:13px;font-weight:700;margin-top:6px}
.sksb{font-size:11px;color:var(--mut)}
.skp{display:grid;grid-template-columns:1.5fr 1fr;grid-template-rows:repeat(3,1fr);gap:4px;height:62px;padding:6px;border-radius:7px;background:#0e1116}
.skp i{display:block;border-radius:3px}
.skp .c{grid-row:1/4;background:#0b0d10;border:1px solid #2a2f37}
.skp .a{background:#14171c;border:1px solid #2a2f37}
.skp-classic .a:nth-of-type(1){border-color:#7c9aff}
.skp-phosphor{background:#040905;border:1px solid #12351d}
.skp-phosphor .c{background:#020603;border-color:#1f6b36;background-image:repeating-linear-gradient(0deg,rgba(109,255,154,.5) 0 1px,transparent 1px 4px)}
.skp-phosphor .a{background:transparent;border:0;border-top:1px dashed #1f6b36;border-radius:0;background-image:repeating-linear-gradient(90deg,#6dff9a 0 3px,transparent 3px 4px);background-size:60% 3px;background-repeat:no-repeat;background-position:0 70%}
.skp-aurora{background:radial-gradient(60px 40px at 15% 0%,rgba(124,92,255,.7),transparent),radial-gradient(60px 40px at 95% 100%,rgba(255,90,170,.5),transparent),#0a0b14;border-radius:12px}
.skp-aurora .c{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.16);border-radius:8px}
.skp-aurora .a{background:linear-gradient(90deg,rgba(124,92,255,.8),rgba(34,211,238,.8));border:0;border-radius:99px}
.skp-slate{background:#0e0f12;border:1px solid #24272d}
.skp-slate .c{background:#08090b;border:1px solid #31353d;border-radius:4px}
.skp-slate .a{background:#14161a;border:1px solid #24272d;border-top:2px solid #e7e9ee;border-radius:3px}
.skp-blocks{background:#ffd23f}
.skp-blocks .c{background:#111;border:2px solid #111;border-radius:0;box-shadow:2px 2px 0 #111}
.skp-blocks .a{background:#fff;border:2px solid #111;border-radius:0;box-shadow:2px 2px 0 #111}
.skp-blocks .a:nth-of-type(1){background:#b6f23a}
/* --- полный экран консоли: #fsRoot целиком становится фикс-оверлеем; консоль сверху ≈70% высоты, аккаунты снизу ≈30% --- */
.fsbar,.fsacc{display:none}
.fsbtn{margin-left:auto}
.fsseg{display:inline-flex;border:1px solid #2a3140;border-radius:8px;overflow:hidden}
.fsseg button{margin:0;background:transparent;border:0;color:var(--mut);font-weight:600;padding:6px 12px;border-radius:0;font-size:12.5px}
.fsseg button.on{background:var(--acc);color:#0f1115}
.fsinfo{flex:1;min-width:0;font-size:12px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
body.fs-on{overflow:hidden}
#fsRoot{display:contents}
#fsRoot.fs{position:fixed;inset:0;z-index:40;box-sizing:border-box;padding:14px;background:var(--bg);display:grid;gap:10px 14px;grid-template-columns:minmax(0,1fr);grid-template-rows:auto auto minmax(0,7fr) minmax(0,3fr)}
#fsRoot.fs>.fsbar{grid-area:1/1;display:flex;align-items:center;gap:10px}
#fsRoot.fs>.ccpause{grid-area:2/1;margin:0}
#fsRoot.fs>.termwrap{grid-area:3/1;margin:0;min-width:0;min-height:0}
#fsRoot.fs>.fsacc{grid-area:4/1;display:block;min-width:0;min-height:0;overflow-x:hidden;overflow-y:auto;padding:12px 6px 6px 2px}
#fsRoot.fs .fsbtn{display:none}
#fsRoot.fs .termbox{flex:none;max-height:none;font-size:var(--fs-fz,14px);line-height:1.25}
#fsRoot.fs #cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px;align-items:start}
#fsRoot.fs .card{margin-bottom:0}
#fsRoot.fs.phone{grid-template-rows:auto auto minmax(0,1fr) auto}
#fsRoot.fs.phone>.fsacc{max-height:44vh}
#fsRoot.fs.phone #cards{grid-template-columns:1fr}
#fsRoot.fs.phone .termbox{white-space:pre-wrap;word-break:break-word}
#fsRoot.fs.phone .fsseg{display:none}
.scrim{z-index:50}
#msg{z-index:70}
/* скин: phosphor */
/* PHOSPHOR — терминал на зелёном люминофоре: моноширинный шрифт, секционные рамки, сегментные полосы */
html[data-skin="phosphor"]{--bg:#020603;--card:#031008;--txt:#c9ffd9;--mut:#4f9f6b;--ok:#6dff9a;--warn:#ffd24a;--bad:#ff6b5e;--acc:#6dff9a;--ph:#6dff9a;--ph2:#9bf5b5;--phd:#4f9f6b;--phl:#1f6b36;--phbg:#031008}
html[data-skin="phosphor"] body{font-family:ui-monospace,"IBM Plex Mono","SF Mono","Cascadia Mono","Roboto Mono",Consolas,monospace;font-size:13.5px;color:var(--ph2)}
html[data-skin="phosphor"]::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:60;background:repeating-linear-gradient(0deg,rgba(0,0,0,.16) 0 1px,transparent 1px 3px)}
html[data-skin="phosphor"] h1,html[data-skin="phosphor"] .termhead h2{font-size:13px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#d8ffe4;text-shadow:0 0 8px rgba(109,255,154,.7);filter:url(#ccPhosphor)}
html[data-skin="phosphor"] h1::before,html[data-skin="phosphor"] .termhead h2::before{content:"▌";color:var(--ph);margin-right:4px}
html[data-skin="phosphor"] .hdr{padding-bottom:6px;border-bottom:1px dashed var(--phl)}
html[data-skin="phosphor"] .hdrgear,html[data-skin="phosphor"] .iconbtn{background:transparent;border:1px solid var(--phl);border-radius:0;color:var(--ph)}
html[data-skin="phosphor"] .hdrgear:hover,html[data-skin="phosphor"] .iconbtn:hover{background:#0c2a17;border-color:var(--ph);color:var(--ph)}
html[data-skin="phosphor"] .termdot{border-radius:0;background:var(--ph);box-shadow:0 0 8px var(--ph)}
html[data-skin="phosphor"] .termdot.err{background:#ff6b5e;box-shadow:0 0 8px #ff6b5e}
html[data-skin="phosphor"] .termbox{font-family:ui-monospace,"IBM Plex Mono","SF Mono","Cascadia Mono",Consolas,monospace;background:#010502;color:#c8d0dc;border:1px solid var(--phl);border-radius:2px;padding:12px 14px;filter:url(#ccPhosphor);box-shadow:inset 0 0 70px rgba(60,255,120,.10);scrollbar-color:#1f6b36 #010502}
html[data-skin="phosphor"] .termbox::-webkit-scrollbar-track{background:#010502}
html[data-skin="phosphor"] .termbox::-webkit-scrollbar-thumb{background:#1f6b36;border:2px solid #010502;border-radius:0;background-clip:padding-box}
html[data-skin="phosphor"] .termbox::-webkit-scrollbar-thumb:hover{background:#6dff9a;background-clip:padding-box}
html[data-skin="phosphor"] .switchrow{gap:6px;color:var(--phd);font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;cursor:pointer;transition:color .15s}
html[data-skin="phosphor"] .switchrow:hover,html[data-skin="phosphor"] .switchrow:has(input:checked){color:var(--ph2)}
html[data-skin="phosphor"] .switchrow input[type=checkbox]{-webkit-appearance:none;appearance:none;transform:none;flex:none;margin:0;width:3ch;height:1.25em;font:700 12px/1.25 ui-monospace,Consolas,monospace;letter-spacing:0;cursor:pointer;vertical-align:middle}
html[data-skin="phosphor"] .switchrow input[type=checkbox]::before{content:"[ ]";color:var(--phd)}
html[data-skin="phosphor"] .switchrow input[type=checkbox]:checked::before{content:"[x]";color:var(--ph);text-shadow:0 0 8px rgba(109,255,154,.8)}
html[data-skin="phosphor"] .thrbtn{background:transparent;border:1px solid var(--phl);border-radius:0;color:var(--ph);font-family:inherit}
html[data-skin="phosphor"] .thrbtn:hover{border-color:var(--ph);background:#0c2a17}
html[data-skin="phosphor"] .mchip{background:transparent;border:1px solid var(--phl);border-radius:0;color:var(--ph2);font-family:inherit;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.06em}
html[data-skin="phosphor"] .mchip:hover{border-color:var(--ph)}
html[data-skin="phosphor"] .mchip.active{background:var(--ph);color:#021006;border-color:var(--ph);box-shadow:0 0 14px rgba(109,255,154,.45)}
html[data-skin="phosphor"] .card{background:var(--phbg);border:1px solid var(--phl);border-radius:0;box-shadow:inset 0 0 40px rgba(60,255,120,.04)}
html[data-skin="phosphor"] .card.active{border-color:var(--ph);box-shadow:0 0 0 1px var(--ph),0 0 30px rgba(109,255,154,.22),inset 0 0 50px rgba(60,255,120,.09)}
html[data-skin="phosphor"] .tag{border-radius:0;background:transparent;color:var(--ph2);border:1px solid #2fb15a;font-family:inherit;font-size:9.5px;letter-spacing:.08em;padding:0 6px}
html[data-skin="phosphor"] .tag.free{color:var(--phd);border-color:var(--phl);background:transparent}
html[data-skin="phosphor"] .tag.plan{background:transparent;color:var(--ph2)}
html[data-skin="phosphor"] .tag.pin{background:var(--ph);color:#021006;border-color:var(--ph);right:auto;left:12px;transform:translateY(-62%);box-shadow:0 0 12px rgba(109,255,154,.6);padding:1px 8px;font-weight:700;font-size:10.5px}
html[data-skin="phosphor"] .chip{background:transparent;border:1px dashed var(--phl);border-radius:0;color:var(--phd);font-family:inherit}
html[data-skin="phosphor"] .chip b{color:var(--ph2)}
html[data-skin="phosphor"] .chip.urgent{border-color:#ff6b5e}
html[data-skin="phosphor"] .chip.warn{border-color:#ffd24a}
html[data-skin="phosphor"] .chip.warn b{color:#ffd24a}
html[data-skin="phosphor"] .email{font-weight:700;font-size:13px;color:#d8ffe4;text-shadow:0 0 6px rgba(109,255,154,.45)}
html[data-skin="phosphor"] .err{color:#ff6b5e}
html[data-skin="phosphor"] .ring svg circle:first-child{stroke:#0f2e19}
html[data-skin="phosphor"] .ring svg circle{stroke-linecap:butt}
html[data-skin="phosphor"] .ringtxt{color:var(--ph2);text-shadow:0 0 6px rgba(109,255,154,.5)}
html[data-skin="phosphor"] .lbl{color:var(--phd);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
html[data-skin="phosphor"] .lbl b{letter-spacing:0;text-shadow:0 0 8px currentColor}
html[data-skin="phosphor"] .lbl span:last-child{text-transform:none;letter-spacing:0}
html[data-skin="phosphor"] .bar{height:9px;border-radius:0;background:repeating-linear-gradient(90deg,#0d2c18 0 5px,transparent 5px 7px)}
html[data-skin="phosphor"] .fill{border-radius:0;-webkit-mask:repeating-linear-gradient(90deg,#000 0 5px,transparent 5px 7px);mask:repeating-linear-gradient(90deg,#000 0 5px,transparent 5px 7px)}
html[data-skin="phosphor"] .btn-sw{background:transparent;border:1px dashed #2fb15a;border-radius:0;color:var(--ph);font-family:inherit;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
html[data-skin="phosphor"] .btn-sw:hover:not(:disabled){background:#0c2a17;border:1px solid var(--ph);box-shadow:0 0 12px rgba(109,255,154,.3)}
html[data-skin="phosphor"] .btn-relogin{background:transparent;border:1px solid var(--phl);border-radius:0;color:var(--phd);font-family:inherit;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
html[data-skin="phosphor"] .btn-relogin:hover:not(:disabled){border-color:var(--ph);color:var(--ph)}
@keyframes ccBlinkPh{0%,55%{opacity:1}56%,100%{opacity:0}}
html[data-skin="phosphor"] .btn-renew{display:inline-flex;align-items:center;padding:2px 2px;background:transparent;color:var(--ph);border:0;border-radius:0;font-family:inherit;font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;text-shadow:0 0 8px rgba(109,255,154,.55)}
html[data-skin="phosphor"] .btn-renew::before{content:"[";color:var(--phd);margin-right:8px}
html[data-skin="phosphor"] .btn-renew::after{content:"]";color:var(--phd);margin-left:8px}
html[data-skin="phosphor"] .rn-ic{font-size:0;display:inline-block;width:7px;height:12px;margin-right:9px;flex:none;background:var(--ph);box-shadow:0 0 8px var(--ph);animation:ccBlinkPh 1.1s steps(1) infinite}
html[data-skin="phosphor"] .btn-renew:hover:not(:disabled){background:var(--ph);color:#021006;text-shadow:none;box-shadow:0 0 16px rgba(109,255,154,.5)}
html[data-skin="phosphor"] .btn-renew:hover::before,html[data-skin="phosphor"] .btn-renew:hover::after{color:#021006}
html[data-skin="phosphor"] .btn-renew:hover .rn-ic{background:#021006;box-shadow:none;animation:none}
html[data-skin="phosphor"] .foot{color:var(--phd)}
html[data-skin="phosphor"] #rf{display:inline-flex;align-items:center;gap:7px;background:transparent;border:1px solid #2fb15a;border-radius:0;color:var(--ph);font-family:inherit;font-size:12px;text-transform:uppercase;letter-spacing:.06em;padding:7px 12px}
html[data-skin="phosphor"] #rf::before{content:"";flex:none;width:13px;height:13px;background:currentColor;-webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M23 4v6h-6'/%3E%3Cpath d='M20.5 15a9 9 0 1 1-2.1-9.4L23 10'/%3E%3C/svg%3E") center/contain no-repeat;mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M23 4v6h-6'/%3E%3Cpath d='M20.5 15a9 9 0 1 1-2.1-9.4L23 10'/%3E%3C/svg%3E") center/contain no-repeat}
html[data-skin="phosphor"] #rf:hover:not(:disabled){background:#0c2a17;border-color:var(--ph)}
html[data-skin="phosphor"] #rf:disabled::before{animation:ccspin .8s linear infinite}
html[data-skin="phosphor"] .modal{background:var(--phbg);border:1px solid var(--phl);border-radius:0;box-shadow:0 0 40px rgba(60,255,120,.12)}
html[data-skin="phosphor"] .poolrow{border-color:#0f2e19}
html[data-skin="phosphor"] .newbadge{border-radius:0;background:transparent;border:1px solid var(--ph);color:var(--ph)}
html[data-skin="phosphor"] .ghostbtn{border-radius:0;border-color:var(--phl);color:var(--ph);font-family:inherit}
html[data-skin="phosphor"] #modalDone{border-radius:0;background:var(--ph);color:#021006;font-family:inherit}
html[data-skin="phosphor"] .ccpause{border-radius:0}
html[data-skin="phosphor"] .ccp-btn{border-radius:0;font-family:inherit;text-transform:uppercase;letter-spacing:.05em;border-color:var(--ccp-accent);background:transparent}
html[data-skin="phosphor"] .ccp-chip{border-radius:0}
html[data-skin="phosphor"] #msg{background:#031008;border:1px solid var(--ph);border-radius:0;color:var(--ph2)}
html[data-skin="phosphor"] .fsseg{border-color:var(--phl);border-radius:0}
html[data-skin="phosphor"] .fsseg button{font-family:inherit;text-transform:uppercase;letter-spacing:.06em;color:var(--phd)}
html[data-skin="phosphor"] .fsseg button.on{background:var(--ph);color:#021006}
html[data-skin="phosphor"] .fsinfo{color:var(--phd)}
html[data-skin="phosphor"] #fsRoot.fs{background:#010603}
html[data-skin="phosphor"] .skopt.on{box-shadow:0 0 0 1px var(--ph)}
/* скин: aurora */
/* AURORA — тёмное стекло и свечение: плавные градиенты, пилюли */
html[data-skin="aurora"]{--bg:#080915;--card:rgba(255,255,255,.06);--txt:#e8eaff;--mut:#8d94bd;--ok:#34d399;--warn:#fbbf24;--bad:#fb7185;--acc:#7c5cff;--au1:#7c5cff;--au2:#22d3ee;--au3:#ff5aaa}
html[data-skin="aurora"] body{font-family:"Manrope","Inter",-apple-system,"Segoe UI",system-ui,sans-serif;color:var(--txt);
 background:radial-gradient(900px 520px at 4% -12%,rgba(124,92,255,.40),transparent 62%),radial-gradient(820px 520px at 104% 112%,rgba(34,211,238,.26),transparent 62%),radial-gradient(520px 320px at 72% -6%,rgba(255,90,170,.18),transparent 70%),#080915;background-attachment:fixed}
html[data-skin="aurora"] h1,html[data-skin="aurora"] .termhead h2{font-weight:800;letter-spacing:.01em;background:linear-gradient(90deg,#fff,#b9a8ff 60%,#7de7f7);-webkit-background-clip:text;background-clip:text;color:transparent}
html[data-skin="aurora"] .hdrgear,html[data-skin="aurora"] .iconbtn{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.14);border-radius:50%;color:#bfc6ee}
html[data-skin="aurora"] .hdrgear:hover,html[data-skin="aurora"] .iconbtn:hover{border-color:#7de7f7;color:#fff;box-shadow:0 0 14px -2px rgba(34,211,238,.6)}
html[data-skin="aurora"] .termdot{width:9px;height:9px;background:#34d399;box-shadow:0 0 10px #34d399,0 0 22px rgba(52,211,153,.6)}
html[data-skin="aurora"] .termdot.err{background:#fb7185;box-shadow:0 0 10px #fb7185}
html[data-skin="aurora"] .termbox{font-family:"DM Mono",ui-monospace,Consolas,monospace;font-weight:500;background:rgba(3,4,12,.95);color:#eef0ff;border:1px solid rgba(160,150,255,.28);border-radius:18px;padding:14px 16px;filter:brightness(1.18) contrast(1.08);box-shadow:0 24px 60px -24px rgba(0,0,0,.9),0 0 0 1px rgba(124,92,255,.12),inset 0 1px 0 rgba(255,255,255,.08);scrollbar-color:rgba(124,92,255,.6) transparent}
html[data-skin="aurora"] .termbox::-webkit-scrollbar-track{background:transparent}
html[data-skin="aurora"] .termbox::-webkit-scrollbar-thumb{background:linear-gradient(#7c5cff,#22d3ee);border:2px solid transparent;background-clip:padding-box}
html[data-skin="aurora"] .switchrow{gap:9px;color:var(--mut);font-weight:600;cursor:pointer}
html[data-skin="aurora"] .switchrow:has(input:checked){color:var(--txt)}
html[data-skin="aurora"] .switchrow input[type=checkbox]{-webkit-appearance:none;appearance:none;transform:none;position:relative;flex:none;margin:0;width:30px;height:18px;border-radius:99px;background:rgba(255,255,255,.14);transition:background .2s;cursor:pointer}
html[data-skin="aurora"] .switchrow input[type=checkbox]::after{content:"";position:absolute;top:3px;left:3px;width:12px;height:12px;border-radius:50%;background:#c9cff5;transition:transform .2s,background .2s}
html[data-skin="aurora"] .switchrow input[type=checkbox]:checked{background:linear-gradient(90deg,#7c5cff,#22d3ee)}
html[data-skin="aurora"] .switchrow input[type=checkbox]:checked::after{transform:translateX(12px);background:#fff}
html[data-skin="aurora"] .thrbtn{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.14);border-radius:99px;color:var(--txt)}
html[data-skin="aurora"] .thrbtn:hover{border-color:#7de7f7}
html[data-skin="aurora"] .mchip{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.14);color:var(--txt);font-weight:600}
html[data-skin="aurora"] .mchip:hover{border-color:#7de7f7}
html[data-skin="aurora"] .mchip.active{background:linear-gradient(135deg,#7c5cff,#c24bd6);border-color:transparent;color:#fff;box-shadow:0 6px 20px -6px rgba(124,92,255,.9)}
html[data-skin="aurora"] .card{background:linear-gradient(160deg,rgba(255,255,255,.075),rgba(255,255,255,.025));border:1px solid rgba(255,255,255,.12);border-radius:16px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);box-shadow:0 18px 40px -22px rgba(0,0,0,.9),inset 0 1px 0 rgba(255,255,255,.07)}
html[data-skin="aurora"] .card.active{border:1px solid transparent;box-shadow:0 0 46px -12px rgba(124,92,255,.75),0 18px 40px -22px rgba(0,0,0,.9);background:linear-gradient(#10112a,#0c0d1f) padding-box,linear-gradient(135deg,#7c5cff,#22d3ee 55%,#ff5aaa) border-box}
html[data-skin="aurora"] .tag{background:rgba(255,255,255,.1);color:#d8dcff;font-weight:800;letter-spacing:.04em;padding:2px 9px}
html[data-skin="aurora"] .tag.free{background:rgba(255,255,255,.08);color:var(--mut)}
html[data-skin="aurora"] .tag.plan{background:linear-gradient(135deg,rgba(124,92,255,.55),rgba(34,211,238,.45));color:#fff}
html[data-skin="aurora"] .tag.pin{background:linear-gradient(135deg,#7c5cff,#ff5aaa);color:#fff;right:22px;transform:translateY(-58%);box-shadow:0 6px 18px -4px rgba(255,90,170,.7);padding:3px 12px}
html[data-skin="aurora"] .chip{background:rgba(255,255,255,.07);border-color:rgba(255,255,255,.12);color:var(--mut);font-family:inherit}
html[data-skin="aurora"] .chip b{color:var(--txt)}
html[data-skin="aurora"] .chip.urgent{border-color:rgba(251,113,133,.6)}
html[data-skin="aurora"] .chip.warn{border-color:rgba(251,191,36,.6)}
html[data-skin="aurora"] .chip.warn b{color:#fbbf24}
html[data-skin="aurora"] .email{font-weight:800;letter-spacing:.005em}
html[data-skin="aurora"] .ring{filter:drop-shadow(0 0 10px rgba(124,92,255,.35))}
html[data-skin="aurora"] .ring svg circle:first-child{stroke:rgba(255,255,255,.10)}
html[data-skin="aurora"] .ringtxt{color:#fff;font-weight:800}
html[data-skin="aurora"] .lbl{font-weight:600}
html[data-skin="aurora"] .lbl b{font-weight:800}
html[data-skin="aurora"] .bar{height:7px;background:rgba(255,255,255,.08);overflow:visible}
html[data-skin="aurora"] .fill[data-t=ok]{background:linear-gradient(90deg,#22d3ee,#34d399);box-shadow:0 0 14px -2px rgba(52,211,153,.8)}
html[data-skin="aurora"] .fill[data-t=warn]{background:linear-gradient(90deg,#fbbf24,#fb923c);box-shadow:0 0 14px -2px rgba(251,191,36,.75)}
html[data-skin="aurora"] .fill[data-t=bad]{background:linear-gradient(90deg,#fb7185,#f43f5e);box-shadow:0 0 14px -2px rgba(244,63,94,.8)}
html[data-skin="aurora"] .btn-sw{background:linear-gradient(135deg,rgba(124,92,255,.85),rgba(34,211,238,.75));color:#fff;border-radius:99px;font-weight:700}
html[data-skin="aurora"] .btn-sw:hover:not(:disabled){box-shadow:0 0 22px -4px rgba(34,211,238,.7)}
html[data-skin="aurora"] .btn-relogin{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.14);color:var(--mut);border-radius:99px;font-weight:600}
html[data-skin="aurora"] .btn-relogin:hover:not(:disabled){border-color:#7de7f7;color:#fff}
html[data-skin="aurora"] .btn-renew{display:inline-flex;align-items:center;gap:8px;padding:3px 16px 3px 4px;border:1px solid transparent;border-radius:99px;font-size:12.5px;font-weight:700;color:#eaf6ff;background:linear-gradient(#141633,#0e1027) padding-box,linear-gradient(135deg,#34d399,#22d3ee 55%,#7c5cff) border-box;box-shadow:0 8px 22px -10px rgba(34,211,238,.7)}
html[data-skin="aurora"] .rn-ic{font-size:0;width:20px;height:20px;border-radius:50%;flex:none;background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M4.5 12.5l5 5L19.5 6.5'/%3E%3C/svg%3E") center/12px no-repeat,linear-gradient(135deg,#34d399,#22d3ee);box-shadow:0 0 12px rgba(52,211,153,.7)}
html[data-skin="aurora"] .btn-renew:hover:not(:disabled){box-shadow:0 0 26px -2px rgba(34,211,238,.75);background:linear-gradient(#1a1d42,#121534) padding-box,linear-gradient(135deg,#34d399,#22d3ee 55%,#c24bd6) border-box}
html[data-skin="aurora"] #rf{display:inline-flex;align-items:center;gap:7px;padding:7px 15px 7px 12px;border-radius:99px;background:linear-gradient(135deg,#7c5cff,#22d3ee);color:#fff;font-weight:700}
html[data-skin="aurora"] #rf::before{content:"";flex:none;width:13px;height:13px;background:currentColor;-webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M23 4v6h-6'/%3E%3Cpath d='M20.5 15a9 9 0 1 1-2.1-9.4L23 10'/%3E%3C/svg%3E") center/contain no-repeat;mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M23 4v6h-6'/%3E%3Cpath d='M20.5 15a9 9 0 1 1-2.1-9.4L23 10'/%3E%3C/svg%3E") center/contain no-repeat}
html[data-skin="aurora"] #rf:disabled::before{animation:ccspin .8s linear infinite}
html[data-skin="aurora"] .modal{background:#12132b;border:1px solid rgba(255,255,255,.14);border-radius:20px;box-shadow:0 30px 80px -20px rgba(0,0,0,.9)}
html[data-skin="aurora"] .poolrow{border-color:rgba(255,255,255,.08)}
html[data-skin="aurora"] .newbadge{background:rgba(124,92,255,.3);color:#d8dcff}
html[data-skin="aurora"] .ghostbtn{border-radius:99px;border-color:rgba(255,255,255,.14);color:var(--txt)}
html[data-skin="aurora"] #modalDone{background:linear-gradient(135deg,#7c5cff,#c24bd6);color:#fff;border-radius:99px}
html[data-skin="aurora"] .ccpause{border-radius:16px}
html[data-skin="aurora"] .ccp-btn{border-radius:99px;background:rgba(255,255,255,.06)}
html[data-skin="aurora"] #msg{background:#1a1c3a;border:1px solid rgba(255,255,255,.14)}
html[data-skin="aurora"] .fsseg{border:1px solid rgba(255,255,255,.14);border-radius:99px;background:rgba(255,255,255,.05)}
html[data-skin="aurora"] .fsseg button{background:transparent;color:var(--mut);font-weight:700}
html[data-skin="aurora"] .fsseg button.on{background:linear-gradient(135deg,#7c5cff,#c24bd6);color:#fff}
html[data-skin="aurora"] .fsinfo{color:var(--mut)}
html[data-skin="aurora"] #fsRoot.fs{background:radial-gradient(900px 520px at 4% -12%,rgba(124,92,255,.40),transparent 62%),radial-gradient(820px 520px at 104% 112%,rgba(34,211,238,.26),transparent 62%),#080915}
html[data-skin="aurora"] .skopt.on{background:#20203a;box-shadow:0 0 0 1px #7c5cff}
/* скин: slate */
/* SLATE — графит и тишина: одна гарнитура, тонкие линии, акцент только цветом статуса */
html[data-skin="slate"]{--bg:#0e0f12;--card:#14161a;--txt:#e7e9ee;--mut:#8a909c;--ok:#3ecf8e;--warn:#e8b84a;--bad:#ef6a6a;--acc:#e7e9ee;--sl-line:#24272d;--sl-line2:#31353d;--sl-dim:#5f6570}
html[data-skin="slate"],html[data-skin="slate"] body{background:var(--bg);color:var(--txt);font-family:"Inter",-apple-system,"Segoe UI",system-ui,sans-serif;font-feature-settings:"tnum","cv11"}
html[data-skin="slate"] h1{font-size:12px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--mut)}
html[data-skin="slate"] .hdr{padding-bottom:10px;border-bottom:1px solid var(--sl-line)}
html[data-skin="slate"] .hdrgear,html[data-skin="slate"] .iconbtn{background:transparent;border:1px solid var(--sl-line2);border-radius:7px;color:#aab0bc}
html[data-skin="slate"] .hdrgear:hover,html[data-skin="slate"] .iconbtn:hover{background:#1b1e24;border-color:#4d525d;color:#fff}
html[data-skin="slate"] .termhead h2{font-size:11.5px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--mut)}
html[data-skin="slate"] .termdot{width:7px;height:7px;background:var(--ok);box-shadow:0 0 0 3px rgba(62,207,142,.15)}
html[data-skin="slate"] .termdot.err{background:var(--bad);box-shadow:0 0 0 3px rgba(239,106,106,.15)}
html[data-skin="slate"] .termbox{font-family:"JetBrains Mono",ui-monospace,Consolas,monospace;background:#08090b;color:#e3e7ee;border:1px solid var(--sl-line);border-radius:10px;padding:14px 16px;filter:brightness(1.12) contrast(1.06);scrollbar-color:#3a3f48 transparent}
html[data-skin="slate"] .termbox::-webkit-scrollbar-track{background:transparent}
html[data-skin="slate"] .termbox::-webkit-scrollbar-thumb{background:#3a3f48;border-color:#08090b}
html[data-skin="slate"] .switchrow{gap:10px;color:var(--mut);font-size:12.5px;cursor:pointer}
html[data-skin="slate"] .switchrow input[type=checkbox]{-webkit-appearance:none;appearance:none;transform:none;position:relative;flex:none;margin:0;width:26px;height:15px;border-radius:99px;background:#262a31;box-shadow:inset 0 0 0 1px var(--sl-line2);transition:background .15s;cursor:pointer}
html[data-skin="slate"] .switchrow input[type=checkbox]::after{content:"";position:absolute;top:3px;left:3px;width:9px;height:9px;border-radius:50%;background:#8a909c;transition:transform .15s,background .15s}
html[data-skin="slate"] .switchrow input[type=checkbox]:checked{background:#e7e9ee;box-shadow:none}
html[data-skin="slate"] .switchrow input[type=checkbox]:checked::after{transform:translateX(11px);background:#0e0f12}
html[data-skin="slate"] .switchrow input[type=checkbox]:focus-visible{outline:1px solid #e7e9ee;outline-offset:2px}
html[data-skin="slate"] .switchrow:has(input:checked),html[data-skin="slate"] #autoWrap:has(input:checked){color:var(--txt)}
html[data-skin="slate"] .thrbtn{background:transparent;border:1px solid var(--sl-line2);color:#aab0bc;border-radius:6px;font-family:inherit;font-weight:500}
html[data-skin="slate"] .thrbtn:hover{border-color:#e7e9ee;color:#fff}
html[data-skin="slate"] .btn-sw,html[data-skin="slate"] .btn-relogin,html[data-skin="slate"] #rf,html[data-skin="slate"] .ghostbtn,html[data-skin="slate"] #modalDone,html[data-skin="slate"] .ccp-btn{font-family:inherit;font-weight:500;background:transparent;border:1px solid var(--sl-line2);border-radius:7px;color:#c7ccd6;transition:background .15s,border-color .15s,color .15s}
html[data-skin="slate"] .btn-sw:hover:not(:disabled),html[data-skin="slate"] .btn-relogin:hover:not(:disabled),html[data-skin="slate"] #rf:hover:not(:disabled),html[data-skin="slate"] .ghostbtn:hover,html[data-skin="slate"] #modalDone:hover,html[data-skin="slate"] .ccp-btn:hover{background:#1b1e24;border-color:#4d525d;color:#fff}
html[data-skin="slate"] .mchip{border-color:var(--sl-line2);color:#c7ccd6;border-radius:7px;font-weight:500;font-size:12px;padding:4px 11px}
html[data-skin="slate"] .mchip.active{background:#e7e9ee;border-color:#e7e9ee;color:#0e0f12;font-weight:600}
html[data-skin="slate"] .mchip.active:hover:not(:disabled){background:#e7e9ee;color:#0e0f12}
html[data-skin="slate"] .card{background:var(--card);border:1px solid var(--sl-line);border-radius:12px;padding:13px 16px}
html[data-skin="slate"] .card.active{background:#181b20;border-color:#555b66;box-shadow:inset 0 2px 0 #e7e9ee}
html[data-skin="slate"] .tag{background:#1f2228;color:#b3b9c4;border:1px solid var(--sl-line2);border-radius:5px;font-size:10px;font-weight:600;letter-spacing:.07em;padding:1px 6px}
html[data-skin="slate"] .tag.free{background:transparent;color:var(--mut)}
html[data-skin="slate"] .tag.plan{background:#1f2228;color:#e7e9ee}
html[data-skin="slate"] .tag.pin{background:#e7e9ee;color:#0e0f12;border-color:#e7e9ee;padding:2px 9px;box-shadow:none}
html[data-skin="slate"] .chip{background:transparent;border:0;border-radius:0;color:var(--mut);font-family:"JetBrains Mono",monospace;font-size:11.5px;padding:0}
html[data-skin="slate"] .chip b{color:#c7ccd6;font-weight:500}
html[data-skin="slate"] .chip.urgent b{color:var(--bad)}
html[data-skin="slate"] .chip.warn b{color:#e0a64a}
html[data-skin="slate"] .email{font-size:13.5px;font-weight:600;letter-spacing:-.005em}
html[data-skin="slate"] .ring svg circle:first-child{stroke:#23262d}
html[data-skin="slate"] .ring svg circle{stroke-width:2.6}
html[data-skin="slate"] .ringtxt{color:#c7ccd6;font-family:"JetBrains Mono",monospace;font-weight:500}
html[data-skin="slate"] .lbl{color:var(--mut);font-size:12px}
html[data-skin="slate"] .lbl span:last-child{font-family:"JetBrains Mono",monospace;font-size:11px;color:var(--sl-dim)}
html[data-skin="slate"] .lbl b{font-family:"JetBrains Mono",monospace;font-size:13px;font-weight:600}
html[data-skin="slate"] .bar{height:4px;border-radius:2px;background:#1f2228}
html[data-skin="slate"] .fill{border-radius:2px}
html[data-skin="slate"] .btn-sw{color:#e7e9ee;border-color:#4d525d}
html[data-skin="slate"] .btn-sw:hover:not(:disabled){background:#e7e9ee;color:#0e0f12;border-color:#e7e9ee}
html[data-skin="slate"] .ccp-btn{border-color:var(--ccp-accent)}
html[data-skin="slate"] .btn-renew{display:inline-flex;align-items:center;gap:9px;border:0;padding:8px 0;background:transparent;color:#aab0bc;font-size:12px}
html[data-skin="slate"] .btn-renew:hover:not(:disabled){background:transparent;color:#fff}
html[data-skin="slate"] .rn-ic{font-size:0;width:17px;height:17px;border-radius:50%;flex:none;border:1px solid #4d525d;box-sizing:border-box;background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M4.5 12.5l5 5L19.5 6.5'/%3E%3C/svg%3E") center/9px no-repeat;transition:background-color .15s,border-color .15s}
html[data-skin="slate"] .rn-t{border-bottom:1px solid #3a3f48;padding-bottom:1px;transition:border-color .15s}
html[data-skin="slate"] .btn-renew:hover .rn-ic{background-color:#e7e9ee;border-color:#e7e9ee;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='3.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M4.5 12.5l5 5L19.5 6.5'/%3E%3C/svg%3E")}
html[data-skin="slate"] .btn-renew:hover .rn-t{border-color:#e7e9ee}
html[data-skin="slate"] .btn-relogin{color:var(--mut);border-color:var(--sl-line2)}
html[data-skin="slate"] .foot{color:var(--mut);padding-top:2px}
html[data-skin="slate"] #rf{padding:7px 14px 7px 11px;display:inline-flex;align-items:center;gap:7px;font-size:12px}
html[data-skin="slate"] #rf::before{content:"";width:13px;height:13px;background:currentColor;-webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M23 4v6h-6'/%3E%3Cpath d='M20.5 15a9 9 0 1 1-2.1-9.4L23 10'/%3E%3C/svg%3E") center/contain no-repeat;mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M23 4v6h-6'/%3E%3Cpath d='M20.5 15a9 9 0 1 1-2.1-9.4L23 10'/%3E%3C/svg%3E") center/contain no-repeat}
html[data-skin="slate"] #rf:disabled::before{animation:ccspin .8s linear infinite}
html[data-skin="slate"] .modal{background:#14161a;border:1px solid var(--sl-line2);border-radius:14px}
html[data-skin="slate"] .poolrow{border-color:var(--sl-line)}
html[data-skin="slate"] .newbadge{background:#1f2228;color:#e7e9ee}
html[data-skin="slate"] .ccpause{border-radius:12px}
html[data-skin="slate"] .fsseg{border:1px solid var(--sl-line2);border-radius:7px;background:var(--card)}
html[data-skin="slate"] .fsseg button{border:0;background:transparent;color:var(--mut)}
html[data-skin="slate"] .fsseg button.on{background:#e7e9ee;color:#0e0f12}
html[data-skin="slate"] .fsinfo{color:var(--mut);font-family:"JetBrains Mono",ui-monospace,Consolas,monospace;font-size:11.5px}
html[data-skin="slate"] #fsRoot.fs{background:var(--bg)}
html[data-skin="slate"] .skopt.on{box-shadow:0 0 0 1px #e7e9ee}
/* скин: blocks */
/* BLOCKS — нео-брутализм: плоские цвета, толстые чёрные рамки, жёсткие тени */
html[data-skin="blocks"]{--bg:#ffd84d;--card:#fff;--txt:#111;--mut:#2b2b2b;--ok:#00d084;--warn:#ffb400;--bad:#ff3d3d;--acc:#4b3fff;--bk:#111;--by:#ffd84d;--bl:#c6f432;--bb:#4b3fff}
html[data-skin="blocks"] body{font-family:"Space Grotesk",-apple-system,"Segoe UI",system-ui,sans-serif;font-weight:500;color:var(--bk)}
html[data-skin="blocks"] h1,html[data-skin="blocks"] .termhead h2{display:inline-block;background:var(--bk);color:var(--by);font-size:15px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:4px 12px;transform:rotate(-1deg)}
html[data-skin="blocks"] #langSwitch,html[data-skin="blocks"] #langSwitch b{color:var(--bk)!important}
html[data-skin="blocks"] .hdrgear,html[data-skin="blocks"] .iconbtn{background:#fff;border:2px solid var(--bk);border-radius:0;color:var(--bk);box-shadow:2px 2px 0 var(--bk)}
html[data-skin="blocks"] .hdrgear:hover,html[data-skin="blocks"] .iconbtn:hover{background:var(--bl);border-color:var(--bk);color:var(--bk)}
html[data-skin="blocks"] .termdot{border-radius:0;width:11px;height:11px;background:#00d084;border:2px solid var(--bk)}
html[data-skin="blocks"] .termdot.err{background:#ff3d3d}
html[data-skin="blocks"] .termbox{font-family:"JetBrains Mono",ui-monospace,Consolas,monospace;font-weight:500;background:#0a0a0a;color:#fff;border:3px solid var(--bk);border-radius:0;padding:10px 14px;box-shadow:5px 5px 0 var(--bb),5px 5px 0 3px var(--bk);filter:brightness(1.18) contrast(1.1);scrollbar-color:#ffd84d #111}
html[data-skin="blocks"] .termbox::-webkit-scrollbar-track{background:#111}
html[data-skin="blocks"] .termbox::-webkit-scrollbar-thumb{background:#ffd84d;border:2px solid #111;border-radius:0;background-clip:padding-box}
html[data-skin="blocks"] .termwrap{margin-bottom:22px}
html[data-skin="blocks"] .switchrow{gap:9px;color:var(--bk);font-weight:700;cursor:pointer}
html[data-skin="blocks"] .switchrow input[type=checkbox]{-webkit-appearance:none;appearance:none;transform:none;position:relative;flex:none;margin:0;width:20px;height:20px;background:#fff;border:2px solid var(--bk);border-radius:0;box-shadow:2px 2px 0 var(--bk);cursor:pointer}
html[data-skin="blocks"] .switchrow input[type=checkbox]:checked{background:var(--bb)}
html[data-skin="blocks"] .switchrow input[type=checkbox]:checked::after{content:"";position:absolute;inset:1px;background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M4.5 12.5l5 5L19.5 6.5'/%3E%3C/svg%3E") center/14px no-repeat}
html[data-skin="blocks"] .thrbtn{background:#fff;border:2px solid var(--bk);border-radius:0;color:var(--bk);font-weight:700;box-shadow:2px 2px 0 var(--bk)}
html[data-skin="blocks"] .thrbtn:hover{background:var(--bl);border-color:var(--bk)}
html[data-skin="blocks"] .mchip{background:#fff;border:2px solid var(--bk);border-radius:0;color:var(--bk);font-weight:700;box-shadow:3px 3px 0 var(--bk);transition:transform .08s,box-shadow .08s}
html[data-skin="blocks"] .mchip:hover{background:var(--bl);border-color:var(--bk);transform:translate(-1px,-1px);box-shadow:4px 4px 0 var(--bk)}
html[data-skin="blocks"] .mchip.active{background:var(--bb);color:#fff;border-color:var(--bk)}
html[data-skin="blocks"] .card{background:#fff;border:3px solid var(--bk);border-radius:0;box-shadow:4px 4px 0 var(--bk);margin-bottom:16px}
html[data-skin="blocks"] .card.active{background:var(--bl);border:3px solid var(--bk);box-shadow:4px 4px 0 var(--bk)}
html[data-skin="blocks"] .tag{background:var(--bk);color:#fff;border-radius:0;font-size:10.5px;font-weight:700;letter-spacing:.06em;padding:1px 7px}
html[data-skin="blocks"] .tag.free{background:#fff;color:var(--bk);border:2px solid var(--bk)}
html[data-skin="blocks"] .tag.plan{background:var(--by);color:var(--bk);border:2px solid var(--bk)}
html[data-skin="blocks"] .tag.pin{background:var(--bb);color:#fff;border:2px solid var(--bk);right:14px;transform:translateY(-62%) rotate(-2deg);box-shadow:3px 3px 0 var(--bk);padding:2px 10px;font-size:11.5px}
html[data-skin="blocks"] .chip{background:#fff;border:2px solid var(--bk);border-radius:0;color:var(--bk);font-weight:700}
html[data-skin="blocks"] .chip b{color:var(--bk)}
html[data-skin="blocks"] .chip.urgent{background:#ff3d3d;color:#fff}
html[data-skin="blocks"] .chip.urgent b{color:#fff}
html[data-skin="blocks"] .chip.warn{background:#ffd23f}
html[data-skin="blocks"] .chip.warn b{color:var(--bk)}
html[data-skin="blocks"] .email{font-size:15px;font-weight:700;color:var(--bk)}
html[data-skin="blocks"] .err{color:#d41818;font-weight:700}
html[data-skin="blocks"] .ring svg circle{stroke-width:4.5;stroke-linecap:butt}
html[data-skin="blocks"] .ring svg circle:first-child{stroke:#111;opacity:.14}
html[data-skin="blocks"] .ringtxt{color:var(--bk)}
html[data-skin="blocks"] .lbl{color:var(--bk);font-weight:700}
html[data-skin="blocks"] .lbl b{color:var(--bk)!important;font-size:18px;letter-spacing:-.02em}
html[data-skin="blocks"] .lbl span:last-child{font-weight:500;opacity:.8}
html[data-skin="blocks"] .bar{height:12px;border-radius:0;background:#fff;border:2px solid var(--bk)}
html[data-skin="blocks"] .fill{border-radius:0;border-right:2px solid var(--bk)}
html[data-skin="blocks"] .btn-sw{background:var(--bk);color:var(--by);border:2px solid var(--bk);border-radius:0;font-weight:700;box-shadow:3px 3px 0 var(--bb);transition:transform .08s,box-shadow .08s,background .08s}
html[data-skin="blocks"] .btn-sw:hover:not(:disabled){background:var(--bb);color:#fff;transform:translate(-1px,-1px);box-shadow:4px 4px 0 var(--bk)}
html[data-skin="blocks"] .btn-sw:active:not(:disabled){transform:translate(3px,3px);box-shadow:0 0 0 var(--bk)}
html[data-skin="blocks"] .btn-relogin{background:#fff;border:2px solid var(--bk);color:var(--bk);border-radius:0;font-weight:700;box-shadow:3px 3px 0 var(--bk)}
html[data-skin="blocks"] .btn-relogin:hover:not(:disabled){background:var(--bl)}
html[data-skin="blocks"] .btn-renew{display:inline-flex;align-items:center;gap:10px;padding:5px 14px 5px 6px;border:3px solid var(--bk);border-radius:0;background:var(--bb);color:#fff;font-size:12px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;box-shadow:4px 4px 0 var(--bk);transition:transform .08s,box-shadow .08s}
html[data-skin="blocks"] .rn-ic{font-size:0;width:18px;height:18px;flex:none;border:2px solid var(--bk);background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='3.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M4.5 12.5l5 5L19.5 6.5'/%3E%3C/svg%3E") center/12px no-repeat,var(--bl)}
html[data-skin="blocks"] .btn-renew:hover:not(:disabled){background:var(--bl);color:var(--bk);transform:translate(-1px,-1px);box-shadow:5px 5px 0 var(--bk)}
html[data-skin="blocks"] .btn-renew:hover .rn-ic{background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M4.5 12.5l5 5L19.5 6.5'/%3E%3C/svg%3E") center/12px no-repeat,var(--bb)}
html[data-skin="blocks"] .btn-renew:active:not(:disabled){transform:translate(4px,4px);box-shadow:0 0 0 var(--bk)}
html[data-skin="blocks"] .foot{color:var(--bk);font-weight:700}
html[data-skin="blocks"] #rf{display:inline-flex;align-items:center;gap:7px;padding:7px 14px 7px 11px;border:3px solid var(--bk);border-radius:0;background:var(--bk);color:var(--by);font-weight:700;text-transform:uppercase;letter-spacing:.05em;font-size:12px;box-shadow:3px 3px 0 var(--bb)}
html[data-skin="blocks"] #rf::before{content:"";flex:none;width:13px;height:13px;background:currentColor;-webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M23 4v6h-6'/%3E%3Cpath d='M20.5 15a9 9 0 1 1-2.1-9.4L23 10'/%3E%3C/svg%3E") center/contain no-repeat;mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M23 4v6h-6'/%3E%3Cpath d='M20.5 15a9 9 0 1 1-2.1-9.4L23 10'/%3E%3C/svg%3E") center/contain no-repeat}
html[data-skin="blocks"] #rf:hover:not(:disabled){background:var(--bb);color:#fff}
html[data-skin="blocks"] #rf:disabled::before{animation:ccspin .8s linear infinite}
html[data-skin="blocks"] .modal{background:#fff;color:var(--bk);border:3px solid var(--bk);border-radius:0;box-shadow:6px 6px 0 var(--bk)}
html[data-skin="blocks"] .modalsub{color:var(--mut)}
html[data-skin="blocks"] .poolrow{border-color:var(--bk)}
html[data-skin="blocks"] .newbadge{background:var(--bb);color:#fff;border-radius:0}
html[data-skin="blocks"] .ghostbtn{background:#fff;border:2px solid var(--bk);border-radius:0;color:var(--bk);font-weight:700;box-shadow:2px 2px 0 var(--bk)}
html[data-skin="blocks"] #modalDone{background:var(--bk);color:var(--by);border-radius:0;box-shadow:3px 3px 0 var(--bb)}
html[data-skin="blocks"] .ccpause,html[data-skin="blocks"] .ccpause.lvl-hard,html[data-skin="blocks"] .ccpause.lvl-gate,html[data-skin="blocks"] .ccpause.lvl-pause,html[data-skin="blocks"] .ccpause.lvl-off,html[data-skin="blocks"] .ccpause.lvl-upd,html[data-skin="blocks"] .ccpause.lvl-updok,html[data-skin="blocks"] .ccpause.lvl-upderr{background:#fff;color:var(--bk);border:3px solid var(--bk);border-left:12px solid var(--ccp-accent,var(--bk));border-radius:0;box-shadow:4px 4px 0 var(--bk)}
html[data-skin="blocks"] .ccp-title,html[data-skin="blocks"] .ccp-sub .num,html[data-skin="blocks"] .ccp-chip b{color:var(--bk)}
html[data-skin="blocks"] .ccpause.lvl-upd .ccp-title b{color:#1f62c4}html[data-skin="blocks"] .ccpause.lvl-updok .ccp-title b{color:#18804a}html[data-skin="blocks"] .ccpause.lvl-upderr .ccp-title b{color:#c0392b}
html[data-skin="blocks"] .ccp-sub,html[data-skin="blocks"] .ccp-hint,html[data-skin="blocks"] .ccp-timer .l{color:var(--mut)}
html[data-skin="blocks"] .ccp-chip{background:#fff;border:2px solid var(--bk);border-radius:0;color:var(--bk)}
html[data-skin="blocks"] .ccp-chip.hot{background:#ff3d3d;color:#fff}
html[data-skin="blocks"] .ccp-btn{background:var(--bk);color:var(--by);border:2px solid var(--bk);border-radius:0;box-shadow:3px 3px 0 var(--ccp-accent,var(--bb))}
html[data-skin="blocks"] .ccp-btn:hover{background:var(--bb);color:#fff}
html[data-skin="blocks"] .ccp-err{color:#d41818}
html[data-skin="blocks"] #msg{background:var(--bk);color:var(--by);border:3px solid var(--bk);border-radius:0;font-weight:700}
html[data-skin="blocks"] .fsseg{border:2px solid var(--bk);border-radius:0;background:#fff;box-shadow:3px 3px 0 var(--bk)}
html[data-skin="blocks"] .fsseg button{background:transparent;color:var(--bk);font-weight:700}
html[data-skin="blocks"] .fsseg button.on{background:var(--bk);color:var(--by)}
html[data-skin="blocks"] .fsinfo{color:var(--bk);font-weight:700}
html[data-skin="blocks"] #fsRoot.fs{background:var(--by)}
html[data-skin="blocks"] .skopt.on{box-shadow:3px 3px 0 var(--bk);border-color:var(--bk)}

/* ---- добавление/удаление аккаунтов ---- */
.addtile{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;margin:0 0 12px;padding:15px 16px;background:transparent;border:1.5px dashed #333c4d;color:var(--mut);border-radius:14px;font-size:14px;font-weight:600;cursor:pointer;transition:border-color .15s,color .15s,background .15s}
.addtile:hover{border-color:var(--acc);color:var(--txt);background:rgba(124,154,255,.06)}
.addtile .plus{width:24px;height:24px;border-radius:50%;border:1.5px solid currentColor;display:inline-flex;align-items:center;justify-content:center;font-size:17px;line-height:1;font-weight:500;padding-bottom:1px}
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
html[data-skin="phosphor"] .addtile{border:1px dashed var(--phl);border-radius:0;color:var(--phd);font-family:inherit;font-size:12px;text-transform:uppercase;letter-spacing:.08em}
html[data-skin="phosphor"] .addtile:hover{border-color:var(--ph);color:var(--ph);background:#0c2a17;box-shadow:0 0 14px rgba(109,255,154,.22)}
html[data-skin="phosphor"] .addtile .plus{border-radius:0}
html[data-skin="phosphor"] .btn-del{background:transparent;border:1px solid var(--phl);border-radius:0;color:var(--phd);font-family:inherit;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
html[data-skin="phosphor"] .btn-del:hover:not(:disabled){border-color:#ff6b5e;color:#ff6b5e}
html[data-skin="phosphor"] .dlgwarn{border:1px dashed #ff6b5e;border-radius:0;background:rgba(255,107,94,.06);color:#ffd9d4}
html[data-skin="phosphor"] .dlginp{background:#020603;border:1px solid var(--phl);border-radius:0;color:var(--ph)}
html[data-skin="phosphor"] .dlginp:focus{border-color:var(--ph);box-shadow:0 0 10px rgba(109,255,154,.25)}
html[data-skin="phosphor"] .btn-danger{background:#ff6b5e;color:#1a0300;border-radius:0;font-family:inherit;text-transform:uppercase;letter-spacing:.06em}
html[data-skin="phosphor"] #acctBox button:not(.ghostbtn):not(.btn-danger){border-radius:0;background:var(--ph);color:#021006;font-family:inherit;font-weight:700}
html[data-skin="phosphor"] #acctBox .ghostbtn{border-radius:0}
html[data-skin="phosphor"] .dlgstep i{border-radius:0;background:var(--ph);color:#021006}
html[data-skin="phosphor"] .dlgurl{background:#020603;border:1px solid var(--phl);border-radius:0;color:var(--phd)}
html[data-skin="aurora"] .addtile{border:1.5px dashed rgba(255,255,255,.22);border-radius:20px;color:var(--mut);background:rgba(255,255,255,.03)}
html[data-skin="aurora"] .addtile:hover{border-color:#7de7f7;color:#fff;background:linear-gradient(135deg,rgba(124,92,255,.18),rgba(34,211,238,.12));box-shadow:0 10px 30px -12px rgba(124,92,255,.6)}
html[data-skin="aurora"] .btn-del{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.14);color:var(--mut);border-radius:99px;font-weight:600}
html[data-skin="aurora"] .btn-del:hover:not(:disabled){border-color:var(--bad);color:#fff;background:rgba(251,113,133,.16)}
html[data-skin="aurora"] .dlgwarn{border:1px solid rgba(251,113,133,.45);border-radius:14px;background:rgba(251,113,133,.09)}
html[data-skin="aurora"] .dlginp{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.16);border-radius:12px}
html[data-skin="aurora"] .dlginp:focus{border-color:#7de7f7}
html[data-skin="aurora"] .btn-danger{background:linear-gradient(135deg,#fb7185,#c24bd6);color:#fff;border-radius:99px}
html[data-skin="aurora"] .dlgstep i{background:linear-gradient(135deg,#7c5cff,#22d3ee);color:#fff}
html[data-skin="aurora"] .dlgurl{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.14);border-radius:12px}
html[data-skin="slate"] .addtile{border:1px dashed var(--sl-line2);border-radius:14px;color:var(--sl-dim);font-weight:500}
html[data-skin="slate"] .addtile:hover{border-color:#4d525d;color:#fff;background:#14161a}
html[data-skin="slate"] .btn-del{font-family:inherit;font-weight:500;background:transparent;border:1px solid var(--sl-line2);border-radius:7px;color:var(--mut)}
html[data-skin="slate"] .btn-del:hover:not(:disabled){border-color:var(--bad);color:var(--bad);background:#1b1e24}
html[data-skin="slate"] .dlgwarn{border:1px solid rgba(239,106,106,.4);border-radius:10px;background:rgba(239,106,106,.07)}
html[data-skin="slate"] .dlginp{background:#0e0f12;border:1px solid var(--sl-line2);border-radius:8px}
html[data-skin="slate"] .dlginp:focus{border-color:#8a909c}
html[data-skin="slate"] .btn-danger{font-weight:500;background:transparent;border:1px solid var(--bad);color:var(--bad);border-radius:7px}
html[data-skin="slate"] .btn-danger:hover:not(:disabled){background:var(--bad);color:#0e0f12}
html[data-skin="slate"] .dlgstep i{background:transparent;border:1px solid var(--sl-line2);color:#c7ccd6}
html[data-skin="slate"] .dlgurl{background:#0e0f12;border:1px solid var(--sl-line2);border-radius:8px}
html[data-skin="blocks"] .addtile{background:#fff;border:3px dashed var(--bk);border-radius:0;color:var(--bk);font-weight:800;box-shadow:4px 4px 0 var(--bk)}
html[data-skin="blocks"] .addtile:hover{background:var(--bl);border-style:solid}
html[data-skin="blocks"] .addtile .plus{border:2px solid var(--bk);border-radius:0;background:var(--by)}
html[data-skin="blocks"] .btn-del{background:#fff;border:2px solid var(--bk);color:var(--bk);border-radius:0;font-weight:700;box-shadow:3px 3px 0 var(--bk)}
html[data-skin="blocks"] .btn-del:hover:not(:disabled){background:var(--bad);color:#fff}
html[data-skin="blocks"] .dlgwarn{border:2px solid var(--bk);border-radius:0;background:#ffe3e3;color:var(--bk);box-shadow:3px 3px 0 var(--bad)}
html[data-skin="blocks"] .dlgwarn b{color:#c40000}
html[data-skin="blocks"] .dlginp{background:#fff;color:var(--bk);border:2px solid var(--bk);border-radius:0}
html[data-skin="blocks"] .dlginp:focus{background:#fffbe0}
html[data-skin="blocks"] .btn-danger{background:var(--bad);color:#fff;border:2px solid var(--bk);border-radius:0;box-shadow:3px 3px 0 var(--bk)}
html[data-skin="blocks"] .dlgstep i{background:var(--bk);color:var(--by);border-radius:0}
html[data-skin="blocks"] .dlgurl{background:#fff;color:var(--bk);border:2px solid var(--bk);border-radius:0}
html[data-skin="blocks"] .dlgerr{color:#c40000;font-weight:700}
</style></head><body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><filter id="ccPhosphor" color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values="0.1 0.34 0.03 0 0  0.28 0.95 0.1 0 0  0.16 0.52 0.05 0 0  0 0 0 1 0"/></filter></svg>
<div class="hdr"><h1 id="h1">⚡ Claude — лимиты аккаунтов</h1><div style="display:flex;align-items:center;gap:10px"><div id="langSwitch" style="font-size:12px;color:var(--mut);cursor:pointer;white-space:nowrap"></div><button id="gear" class="hdrgear" title="Модели">⚙</button></div></div>
<div class="ccpause" id="updBanner" hidden></div>
<div id="fsRoot">
<div class="fsbar" id="fsBar"><span class="fsinfo" id="fsInfo"></span><div class="fsseg"><button type="button" id="fsMFit"></button><button type="button" id="fsMBig"></button></div><button type="button" class="iconbtn" id="fsClose"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button></div>
<div class="ccpause" id="ccPause" hidden></div>
<div class="termwrap">
 <div class="termhead"><h2 id="consoleTitle">🖥 Консоль (только чтение)</h2><span class="termdot" id="termDot"></span><button type="button" class="iconbtn fsbtn" id="fsBtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg></button></div>
 <pre class="termbox" id="termBox"><span id="termHistory"></span>
<span id="termCurrent">Загрузка…</span></pre>
</div>
<div class="fsacc" id="fsAcc"></div>
</div>
<div class="switchrow">
 <span id="autoWrap"><input type="checkbox" id="auto"> <label for="auto" id="autoLbl">Авто-переключение при <span id="thrLbl">85</span>% сессии</label></span>
 <button type="button" class="thrbtn" id="thrMinus">−</button><button type="button" class="thrbtn" id="thrPlus">+</button>
</div>
<div class="switchrow">
 <input type="checkbox" id="opt"> <label for="opt" id="optLbl">Оптимизация переключений лимитов (рулит сервис, ручные кнопки блокируются)</label>
</div>
<div id="mrow" class="mrowslim"></div>
<div id="cards">Загрузка…</div>
<div class="foot"><span id="upd"></span><button id="rf" style="margin-top:0">Обновить сейчас</button></div>
<div id="msg"></div>
<div id="scrim" class="scrim" hidden>
 <div class="modal">
  <h3 id="modalTitle">Настройки</h3>
  <div class="modalh" id="skinTitle">Оформление</div>
  <div class="skgrid" id="skinGrid" role="radiogroup"></div>
  <div class="modalh" id="updHdr">Обновления</div>
  <div id="updBox"></div>
  <div class="modalh" id="modelsHdr">Модели</div>
  <div class="modalsub" id="modalSub">Отметь, какие показывать кнопками на главной — применяется сразу, без «Сохранить»</div>
  <div id="poolList"></div>
  <div class="modalfoot"><button id="checkNew" class="ghostbtn">🔄 Проверить новые модели</button><button id="modalDone" style="margin-top:0">Готово</button></div>
 </div>
</div>
<div id="acctScrim" class="scrim" hidden><div class="modal" id="acctBox" role="dialog" aria-modal="true"></div></div>
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
  extended:'Я продлил',
  relogin:'🔑 Войти заново',
  addTile:'Добавить аккаунт',
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
  delBtn:'Удалить',
  delBtnTitle:'Удалить аккаунт из ротации навсегда',
  delTitle:'Удалить аккаунт навсегда?',
  delWarn:'<b>Это безвозвратно.</b> Профиль и токены аккаунта будут стёрты сразу — без корзины и без отката. Из ротации он пропадёт полностью; вернуть его можно только добавив заново, с новым входом через браузер.',
  delActive:'Сейчас это активный аккаунт — перед удалением сессия будет переведена на другой.',
  delLast:'Это единственный аккаунт в ротации — удалить его нельзя.',
  delWord:'подтверждаю',
  delType:w=>'Чтобы подтвердить, введи слово «'+w+'»',
  delGo:'Удалить навсегда',
  delWorking:'Удаляю…',
  cancel:'Отмена',
  relStarting:'Запускаю…',
  relChecking:'Проверяю код…',
  relPrompt:email=>`Ссылка входа открылась в новой вкладке (и скопирована в буфер обмена — если вкладка не та или её заблокировал браузер, просто вставь ссылку в нужный профиль).\nВойди под ${email} и вставь код авторизации сюда:`,
  confirmSwitch:n=>`Переключить активный аккаунт на ${n}?`,
  autoOn:'Авто-переключение включено',autoOff:'Авто-переключение выключено',
  thrSet:v=>'Порог: '+v+'%',
  optOn:'Оптимизация лимитов включена — ручные переключения заблокированы',
  optOff:'Оптимизация выключена — ручные переключения доступны',
  checking:'Проверяю…',
  checkErr:e=>`⚠ ошибка проверки: ${e}`,
  staleAt:t=>` · ниже данные на ${t}`,
  renewalIn:(d,h)=>`до ожидаемого PRO→FREE: ~${d} дн ${h} ч`,
  renewalSoon:'подписка: ожидаем обвал в PRO→FREE со дня на день',
  renewalChip:d=>`⏳ ${d} дн`,
  renewalChipToday:'⏳ сегодня',
  loginWord:'логин',
  loginD:d=>`${d} дн`,
  loginH:h=>`${h} ч`,
  loginGone:'истёк',
  loginHint:w=>`Логин истекает ${w}. После этого нужно «Войти заново»`,
  loginHintGone:w=>`Логин истёк ${w}. Нужно «Войти заново»`,
  updHdr:'Обновления',
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
  updCheckLbl:'Проверять новые версии раз в сутки (один запрос к GitHub, без токена)',
  updAutoConfirm:v=>`Сейчас доступна версия ${v} — её поставят сразу. Включить автоматическое обновление?`,
  updNoSupport:r=>`Автообновление здесь недоступно (${r}). Обнови вручную: sudo ./install.sh из архива релиза.`,
  updBTitle:v=>`⬆ Вышла новая версия — <b>${v}</b>`,
  updBSub:(cur,name)=>`У тебя ${cur}`+(name?` · ${name}`:''),
  updBtnNow:'Обновить',
  updBtnSkip:'Пропустить эту версию',
  updBtnPage:'Страница релиза ↗',
  updBtnOk:'Понятно',
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
  ccpHardSub:(thr,na,held)=>`Все аккаунты упёрлись в сессионное окно (порог ${thr}%). Фоновые задачи не стартуют, чтобы не добить окно. `+(na?`Раньше всех освободится <b>${na}</b>`+' — балансер переключится на него сразу после сброса.':'Балансер переключится, как только освободится ближайший.'),
  ccpOffTitle:'▶ Пауза <b>отключена вручную</b> — Claude работает сверх порога',
  ccpOffSub:(na,at)=>'Входящие сообщения доходят сразу, инструменты не блокируются — до настоящего лимита аккаунта. Пауза включится сама, как только отпустит сессионное окно'+(na&&at?` (раньше всех — <b>${na}</b> в <span class="num">${at}</span>)`:'')+', или по кнопке.',
  ccpBtnOff:'Отключить паузу',
  ccpBtnOn:'Включить паузу',
  ccpHintOff:thr=>`Claude продолжит сразу, сверх порога ${thr}%`,
  ccpHintHardOff:'следующее сообщение не встанет в очередь',
  ccpHintOnHard:'окно забито — пауза встанет сразу',
  ccpHintOnFree:'окно уже свободно — пауза просто снова начнёт работать',
  ccpErr:e=>'не получилось: '+e,
  ccpGateTitle:'⏸ Активный аккаунт забит — <b>фоновые задачи приостановлены</b>',
  ccpGateSub:(n,p,w,thr)=>`${n}: сессия <span class="num">${p}</span> (порог ${thr}%), неделя <span class="num">${w}</span>. Свободный аккаунт есть — балансер переключится на следующем тике, после него задачи пойдут сами.`,
  ccpWeek:w=>` · нед ${w}%`,
  ccpActive:' · активный',
  ccpChecks:n=>`перепроверок окна: <b>${n}</b>`,
  ccpTillWake:'до подъёма',
  ccpTillNearest:'до ближайшего окна',
  ccpTillFree:n=>'до освобождения '+n,
  ccpTillReset:'до сброса окна',
  ccpLeft:(h,m,s)=>h?`${h} ч ${m} мин`:`${m} мин ${s} с`,
  modelsBtnTitle:'Настройки',
  modelsTitle:'Настройки',
  modelsHdr:'Модели',
  skinTitle:'Оформление',
  skin_classic:'Классика',skin_phosphor:'Phosphor',skin_aurora:'Aurora',skin_slate:'Slate',skin_blocks:'Blocks',
  skinSub_classic:'как раньше',skinSub_phosphor:'терминал, зелёный люминофор',skinSub_aurora:'тёмное стекло и свечение',skinSub_slate:'графит, тонкие линии',skinSub_blocks:'крупные блоки, жёсткие тени',
  fsOpenTitle:'На весь экран',fsCloseTitle:'Выйти (Esc)',
  fsFit:'Вся консоль',fsFitTitle:'Вся консоль целиком (шрифт не мельче 10 px — иначе нижние строки), аккаунты снизу',
  fsBig:'Крупно',fsBigTitle:'Крупный шрифт на всю ширину консоли, аккаунты снизу',
  fsInfo:(f,c,r,v)=>'шрифт '+f+' px · '+c+'×'+r+(v<r?' · видно '+v+' нижних строк':''),
  modelsSub:'Отметь, какие показывать кнопками на главной — применяется сразу, без «Сохранить»',
  modelsDone:'Готово',
  noModelsEnabled:'Ни одна модель не включена — открой ⚙',
  newBadge:'новая',
  checkNewModels:'🔄 Проверить новые модели',
  candSearching:'Ищу…',
  candFound:'Найдено новых моделей: {n} — отметь нужные',
  candNone:'Новых моделей нет — у тебя уже всё актуальное',
  candErr:'Не удалось проверить модели — сервер ответил ошибкой',
  compactTitle:'Сжать контекст (/compact)',
  newSessionTitle:'Новая сессия (/clear)',
  confirmNewSession:'Начать новую сессию Claude (/clear)? Текущий разговор уйдёт в фон на диск, вернуться можно через /resume в консоли. Продолжить?',
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
  extended:'I renewed',
  relogin:'🔑 Log in again',
  addTile:'Add an account',
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
  delBtn:'Delete',
  delBtnTitle:'Remove the account from the rotation for good',
  delTitle:'Delete this account for good?',
  delWarn:'<b>This cannot be undone.</b> The profile and its tokens are wiped immediately — no recycle bin, no rollback. The account disappears from the rotation entirely; the only way back is to add it again with a fresh browser sign-in.',
  delActive:'This is the active account — the session will be moved to another one first.',
  delLast:'This is the only account in the rotation — it cannot be deleted.',
  delWord:'confirm',
  delType:w=>'To confirm, type the word “'+w+'”',
  delGo:'Delete for good',
  delWorking:'Deleting…',
  cancel:'Cancel',
  relStarting:'Starting…',
  relChecking:'Checking code…',
  relPrompt:email=>`The login link opened in a new tab (and was copied to your clipboard — if it's the wrong tab or got blocked, just paste the link into the right browser profile).\nSign in as ${email} and paste the authorization code here:`,
  confirmSwitch:n=>`Switch the active account to ${n}?`,
  autoOn:'Auto-switch enabled',autoOff:'Auto-switch disabled',
  thrSet:v=>'Threshold: '+v+'%',
  optOn:'Limit optimization enabled — manual switching blocked',
  optOff:'Optimization disabled — manual switching available',
  checking:'Checking…',
  checkErr:e=>`⚠ check failed: ${e}`,
  staleAt:t=>` · data below from ${t}`,
  renewalIn:(d,h)=>`until expected PRO→FREE: ~${d}d ${h}h`,
  renewalSoon:'subscription: expecting PRO→FREE drop any day now',
  renewalChip:d=>`⏳ ${d}d`,
  renewalChipToday:'⏳ today',
  loginWord:'login',
  loginD:d=>`${d}d`,
  loginH:h=>`${h}h`,
  loginGone:'expired',
  loginHint:w=>`Login expires ${w}. After that you need “Log in again”`,
  loginHintGone:w=>`Login expired ${w}. Use “Log in again”`,
  updHdr:'Updates',
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
  updCheckLbl:'Check for new versions once a day (one request to GitHub, no token)',
  updAutoConfirm:v=>`Version ${v} is available right now — it will be installed immediately. Turn on automatic updates?`,
  updNoSupport:r=>`Auto-update is unavailable here (${r}). Update by hand: sudo ./install.sh from the release archive.`,
  updBTitle:v=>`⬆ New version released — <b>${v}</b>`,
  updBSub:(cur,name)=>`You have ${cur}`+(name?` · ${name}`:''),
  updBtnNow:'Update',
  updBtnSkip:'Skip this version',
  updBtnPage:'Release page ↗',
  updBtnOk:'Got it',
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
  ccpHardSub:(thr,na,held)=>`Every account is out of its session window (threshold ${thr}%). Background jobs stay down so they don't burn the rest of the window. `+(na?`<b>${na}</b> frees up first`+' — the balancer switches to it right after the reset.':'The balancer switches as soon as the nearest one frees up.'),
  ccpOffTitle:'▶ Pause <b>disabled manually</b> — Claude works past the threshold',
  ccpOffSub:(na,at)=>'Incoming messages go straight through and tools are not blocked — up to the real account limit. The pause re-arms by itself once a session window frees up'+(na&&at?` (first: <b>${na}</b> at <span class="num">${at}</span>)`:'')+', or with the button.',
  ccpBtnOff:'Disable pause',
  ccpBtnOn:'Enable pause',
  ccpHintOff:thr=>`Claude continues right away, past the ${thr}% threshold`,
  ccpHintHardOff:'the next message will not be queued',
  ccpHintOnHard:'window is full — the pause starts right away',
  ccpHintOnFree:'window is already free — the pause simply works again',
  ccpErr:e=>'failed: '+e,
  ccpGateTitle:'⏸ Active account is full — <b>background jobs paused</b>',
  ccpGateSub:(n,p,w,thr)=>`${n}: session <span class="num">${p}</span> (threshold ${thr}%), week <span class="num">${w}</span>. A free account exists — the balancer switches on the next tick, after that jobs resume by themselves.`,
  ccpWeek:w=>` · wk ${w}%`,
  ccpActive:' · active',
  ccpChecks:n=>`window re-checks: <b>${n}</b>`,
  ccpTillWake:'until resume',
  ccpTillNearest:'until nearest window',
  ccpTillFree:n=>'until '+n+' frees up',
  ccpTillReset:'until window reset',
  ccpLeft:(h,m,s)=>h?`${h}h ${m}m`:`${m}m ${s}s`,
  modelsBtnTitle:'Settings',
  modelsTitle:'Settings',
  modelsHdr:'Models',
  skinTitle:'Appearance',
  skin_classic:'Classic',skin_phosphor:'Phosphor',skin_aurora:'Aurora',skin_slate:'Slate',skin_blocks:'Blocks',
  skinSub_classic:'as before',skinSub_phosphor:'terminal, green phosphor',skinSub_aurora:'dark glass and glow',skinSub_slate:'graphite, thin lines',skinSub_blocks:'bold blocks, hard shadows',
  fsOpenTitle:'Full screen',fsCloseTitle:'Exit (Esc)',
  fsFit:'Whole console',fsFitTitle:'The whole console at once (font not below 10 px — otherwise the bottom lines), accounts below',
  fsBig:'Large',fsBigTitle:'Large font across the full console width, accounts below',
  fsInfo:(f,c,r,v)=>'font '+f+' px · '+c+'×'+r+(v<r?' · showing the bottom '+v+' lines':''),
  modelsSub:'Pick which ones show as quick-switch buttons — applies instantly, no Save button',
  modelsDone:'Done',
  noModelsEnabled:'No models enabled — open ⚙',
  newBadge:'new',
  checkNewModels:'🔄 Check for new models',
  candSearching:'Searching…',
  candFound:'New models found: {n} — tick the ones you want',
  candNone:'No new models — you are up to date',
  candErr:'Could not check for models',
  compactTitle:'Compact context (/compact)',
  newSessionTitle:'New session (/clear)',
  confirmNewSession:'Start a new Claude session (/clear)? The current conversation moves to disk in the background — resume it with /resume in the console. Continue?',
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
let THR=85,lastSnap=null,lastModel=null;
function renderAutoLbl(){$('#autoLbl').innerHTML=tr('autoLbl',THR);}
function applyI18n(){
 document.title=tr('title');document.documentElement.lang=LANG;
 $('#h1').textContent=tr('h1');$('#consoleTitle').textContent=tr('console');
 $('#optLbl').textContent=tr('optLbl');$('#rf').textContent=tr('refresh');
 renderAutoLbl();renderLangSwitch();
 $('#gear').title=tr('modelsBtnTitle');$('#modalTitle').textContent=tr('modelsTitle');
 $('#modelsHdr').textContent=tr('modelsHdr');$('#skinTitle').textContent=tr('skinTitle');buildSkinGrid();
 $('#fsBtn').title=tr('fsOpenTitle');$('#fsClose').title=tr('fsCloseTitle');
 $('#fsMFit').textContent=tr('fsFit');$('#fsMFit').title=tr('fsFitTitle');$('#fsMBig').textContent=tr('fsBig');$('#fsMBig').title=tr('fsBigTitle');
 if(FS.on)fsFitSoon();
 $('#updHdr').textContent=tr('updHdr');
 if(typeof updRender==='function'){updRender();updSettingsRender();}  // смена языка перерисовывает баннер и блок настроек
 $('#modalSub').textContent=tr('modelsSub');$('#modalDone').textContent=tr('modelsDone');$('#checkNew').textContent=tr('checkNewModels');
 const opt=!!(lastSnap&&lastSnap.config&&lastSnap.config.optimize);
 $('#auto').parentElement.title=opt?tr('optDisabledTitle'):'';
 if(typeof ccpRender==='function')ccpRender();  // смена языка перерисовывает баннер без запроса
 if(lastSnap){
  renderCards(lastSnap);
  $('#upd').textContent=tr('updated')+' '+new Date(lastSnap.ts*1000).toLocaleTimeString(LANG==='en'?'en-GB':'ru');
 }
 if(lastModel)renderModel(lastModel);
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
  if(FS.on)fsCheckDims();
  if(atBottom)box.scrollTop=box.scrollHeight;
 }catch(e){dot.className='termdot err';}
}
// ---- оформление: скины ----
const SKINS=['classic','phosphor','aurora','slate','blocks'];
let SKIN='classic';
try{const _s=localStorage.getItem('cc_skin');if(SKINS.includes(_s))SKIN=_s;}catch(e){}
function buildSkinGrid(){
 $('#skinGrid').innerHTML=SKINS.map(id=>'<button type="button" class="skopt'+(id===SKIN?' on':'')+'" data-skin="'+id+'" role="radio" aria-checked="'+(id===SKIN)+'">'
  +'<span class="skp skp-'+id+'"><i class="c"></i><i class="a"></i><i class="a"></i><i class="a"></i></span>'
  +'<span class="sknm">'+tr('skin_'+id)+'</span><span class="sksb">'+tr('skinSub_'+id)+'</span></button>').join('');
}
function applySkin(id,save){
 if(!SKINS.includes(id))id='classic';
 SKIN=id;
 if(id==='classic')document.documentElement.removeAttribute('data-skin');else document.documentElement.setAttribute('data-skin',id);
 if(save){try{localStorage.setItem('cc_skin',id);}catch(e){}}
 document.querySelectorAll('#skinGrid .skopt').forEach(b=>{const on=b.dataset.skin===id;b.classList.toggle('on',on);b.setAttribute('aria-checked',on);});
 // у скина свой шрифт консоли: сбросить замер ширины символа и пересчитать полный экран
 FS.cw=0;if(FS.on)fsFit();
 if(document.fonts&&document.fonts.load){
  const fam=getComputedStyle($('#termBox')).fontFamily;
  Promise.all([document.fonts.load('12px '+fam),document.fonts.load('bold 12px '+fam)]).then(()=>{FS.cw=0;fsFitSoon();}).catch(()=>{});
 }
 const box=$('#termBox');box.scrollTop=box.scrollHeight;
}
// ---- полный экран: сверху консоль (≈70% высоты), снизу аккаунты (≈30%) ----
// Шрифт консоли подбирается так, чтобы весь текущий экран сессии (rows×cols) влез по высоте
// («Вся консоль», но не мельче FS_MIN) или по ширине («Крупно»). Выход: ✕, Esc, «назад», выход из браузерного fullscreen.
const FS={on:false,mode:'fit',rows:0,cols:0,raf:0,browser:false,cw:0};
try{FS.mode=localStorage.getItem('cc_fsmode')==='big'?'big':'fit';}catch(e){}
const FS_LH=1.25,FS_MIN=10;
function fsCharW(){  // ширина символа в долях font-size, замер по шрифту консоли текущего скина
 const fam=getComputedStyle($('#termBox')).fontFamily;
 if(FS.cw&&FS.cwFam===fam)return FS.cw;
 FS.cwFam=fam;
 const p=document.createElement('span');
 p.style.cssText='position:absolute;left:-9999px;visibility:hidden;white-space:pre;font:100px '+fam;
 p.textContent='M'.repeat(40);document.body.appendChild(p);
 FS.cw=p.getBoundingClientRect().width/4000||0.6;p.remove();
 return FS.cw;
}
function fsDims(){
 const ls=($('#termCurrent').textContent||'').replace(/\n$/,'').split('\n');
 let c=0;for(const l of ls)if(l.length>c)c=l.length;
 return{rows:Math.max(ls.length,24),cols:Math.max(c,80)};
}
function fsFit(){
 if(!FS.on)return;
 const root=$('#fsRoot'),term=root.querySelector('.termwrap'),box=$('#termBox'),thead=term.querySelector('.termhead');
 const px=v=>parseFloat(v)||0,rcs=getComputedStyle(root);
 const SW=root.clientWidth-px(rcs.paddingLeft)-px(rcs.paddingRight);
 const phone=root.clientWidth<720;
 root.classList.toggle('phone',phone);
 box.style.height='';
 const dm=fsDims();FS.rows=dm.rows;FS.cols=dm.cols;
 const cw=fsCharW();
 const bcs=getComputedStyle(box),tcs=getComputedStyle(term),hcs=getComputedStyle(thead);
 const OW=px(bcs.paddingLeft)+px(bcs.paddingRight)+px(bcs.borderLeftWidth)+px(bcs.borderRightWidth)+9;  // + скроллбар 9px
 const OH=px(bcs.paddingTop)+px(bcs.paddingBottom)+px(bcs.borderTopWidth)+px(bcs.borderBottomWidth);
 const TX=px(tcs.paddingLeft)+px(tcs.paddingRight)+px(tcs.borderLeftWidth)+px(tcs.borderRightWidth);
 const TY=px(tcs.paddingTop)+px(tcs.paddingBottom);
 const availH=term.clientHeight-TY-thead.offsetHeight-px(hcs.marginBottom);
 const fW=(SW-OW-TX)/(dm.cols*cw);
 let f;
 if(phone)f=11.5;
 else if(FS.mode==='big')f=Math.min(40,fW);
 else f=Math.min(40,fW,Math.max(FS_MIN,(availH-OH)/(dm.rows*FS_LH)));
 box.style.height=Math.max(120,availH)+'px';
 root.style.setProperty('--fs-fz',f.toFixed(2)+'px');
 const vis=Math.min(dm.rows,Math.floor((availH-OH)/(f*FS_LH)));
 $('#fsInfo').textContent=tr('fsInfo',f.toFixed(1),dm.cols,dm.rows,vis);
 $('#fsMFit').classList.toggle('on',FS.mode==='fit');$('#fsMBig').classList.toggle('on',FS.mode==='big');
 // самокалибровка: реальные строки шире «40×M» (пиктограммы из запасных шрифтов) — уточняем ширину символа и пересчитываем раз
 const ov=box.scrollWidth-box.clientWidth;
 if(ov>1&&!FS.recal){FS.cw*=1+ov/(dm.cols*cw*f);FS.recal=true;try{fsFit();}finally{FS.recal=false;}return;}
 box.scrollTop=box.scrollHeight;
}
function fsFitSoon(){if(!FS.on||FS.raf)return;FS.raf=requestAnimationFrame(()=>{FS.raf=0;fsFit();});}
function fsCheckDims(){const d=fsDims();if(d.rows!==FS.rows||d.cols!==FS.cols)fsFitSoon();}
function fsMode(m){FS.mode=m;try{localStorage.setItem('cc_fsmode',m);}catch(e){}fsFit();}
function fsOpen(){
 if(FS.on)return;
 $('#fsAcc').appendChild($('#cards'));  // аккаунты переезжают в нижнюю панель
 $('#fsRoot').classList.add('fs');document.body.classList.add('fs-on');
 FS.on=true;
 try{history.pushState({ccfs:1},'');}catch(e){}
 const el=document.documentElement;
 if(el.requestFullscreen)el.requestFullscreen().then(()=>{FS.browser=true;}).catch(()=>{});
 fsFit();
}
function fsClose(fromPop){
 if(!FS.on)return;
 FS.on=false;
 const root=$('#fsRoot'),box=$('#termBox'),foot=document.querySelector('.foot');
 root.classList.remove('fs','phone');root.style.removeProperty('--fs-fz');
 document.body.classList.remove('fs-on');
 box.style.height='';
 foot.parentNode.insertBefore($('#cards'),foot);
 if(FS.browser&&document.fullscreenElement&&document.exitFullscreen)document.exitFullscreen().catch(()=>{});
 FS.browser=false;
 if(!fromPop){try{if(history.state&&history.state.ccfs)history.back();}catch(e){}}
 box.scrollTop=box.scrollHeight;
}
$('#fsBtn').addEventListener('click',fsOpen);
$('#fsClose').addEventListener('click',()=>fsClose());
$('#fsMFit').addEventListener('click',()=>fsMode('fit'));
$('#fsMBig').addEventListener('click',()=>fsMode('big'));
$('#skinGrid').addEventListener('click',e=>{const b=e.target.closest('.skopt');if(b)applySkin(b.dataset.skin,true);});
window.addEventListener('resize',fsFitSoon);
window.addEventListener('orientationchange',fsFitSoon);
window.addEventListener('popstate',()=>{if(FS.on&&!(history.state&&history.state.ccfs))fsClose(true);});
document.addEventListener('fullscreenchange',()=>{if(FS.on&&FS.browser&&!document.fullscreenElement)fsClose();});
document.addEventListener('keydown',e=>{
 if(e.key!=='Escape')return;
 if(!$('#acctScrim').hidden){acctClose();return;}
 if(!$('#scrim').hidden){$('#scrim').hidden=true;return;}
 if(FS.on)fsClose();
});
new MutationObserver(fsFitSoon).observe($('#ccPause'),{attributes:true,attributeFilter:['hidden','class'],childList:true});
buildSkinGrid();applySkin(SKIN,false);
ccConsoleHistory();ccConsole();setInterval(ccConsole,2000);
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
 if(ms<=0)return`<span class="chip login urgent" title="${tr('loginHintGone',when)}">${tr('loginWord')} <b>${tr('loginGone')}</b></span>`;
 const days=Math.floor(ms/86400000);
 const cls=days<=3?' urgent':days<=7?' warn':'';
 const left=days>=1?tr('loginD',days):tr('loginH',Math.max(1,Math.floor(ms/3600000)));
 return`<span class="chip login${cls}" title="${tr('loginHint',when)}">${tr('loginWord')} <b>${left}</b></span>`}
function urgCol(f){return f>.5?'var(--bad)':f>.2?'var(--warn)':'var(--ok)'}
function frac(iso,windowSec){if(!iso)return 0;const remain=(new Date(iso)-Date.now())/1000;return Math.max(0,Math.min(1,remain/windowSec))}
function ring(o,windowSec,size){o=o||{};size=size||34;const sw=Math.max(3,Math.round(size*.1));const rad=size/2-sw/2;const circ=2*Math.PI*rad;const f=frac(o.resets_at,windowSec);const uc=urgCol(f);const dash=(f*circ).toFixed(1);const c=size/2;
 return `<div class="ring" style="width:${size}px;height:${size}px" title="${rst(o.resets_at)}"><svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}"><circle cx="${c}" cy="${c}" r="${rad}" fill="none" stroke="#242b38" stroke-width="${sw}"/><circle cx="${c}" cy="${c}" r="${rad}" fill="none" stroke="${uc}" stroke-width="${sw}" stroke-linecap="round" stroke-dasharray="${dash} ${circ.toFixed(1)}" transform="rotate(-90 ${c} ${c})"/></svg><span class="ringtxt" style="font-size:${Math.round(size*.26)}px">${Math.round(f*100)}%</span></div>`}
function renderCards(d){
 const opt=!!(d.config&&d.config.optimize);
 $('#cards').innerHTML=Object.entries(d.accounts).map(([n,a])=>{
  const plan=a.plan==='free'?'<span class="tag free">FREE</span> ':a.plan?'<span class="tag plan">'+a.plan.toUpperCase()+'</span> ':'';
  const icons=a.active?`<div class="iconrow">
    <button class="iconbtn" title="${tr('compactTitle')}" onclick="sessionCmd('compact')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4v4a1 1 0 0 1-1 1H4M15 4v4a1 1 0 0 0 1 1h4M9 20v-4a1 1 0 0 0-1-1H4M15 20v-4a1 1 0 0 1 1-1h4"/></svg></button>
    <button class="iconbtn" title="${tr('newSessionTitle')}" onclick="sessionCmd('new')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 1 3 6.7"/><path d="M3 16v-4h4"/></svg></button>
   </div>`:'';
  const r=a.five_hour?ring(a.five_hour,18000):'';
  return `
  <div class="card ${a.active?'active':''}">
   ${a.active?'<span class="tag pin">'+tr('active')+'</span>':''}
   <div class="top"><span class="email">${a.email} ${plan}${a.renewal_next?renewChip(a.renewal_next):''}</span><div class="hdrright">${r}${icons}</div></div>
   ${a.error?`<div class="err">⚠ ${a.error}${a.stale_ts?tr('staleAt',new Date(a.stale_ts*1000).toLocaleTimeString(LANG==='en'?'en-GB':'ru',{hour:'2-digit',minute:'2-digit'})):''}</div>`:''}${a.five_hour?bar(tr('session5'),a.five_hour)+bar(tr('week'),a.seven_day):''}
   <div class="acts"><button class="btn-sw" onclick="sw('${n}')" ${a.active||opt?'disabled':''} ${opt&&!a.active?'title="'+tr('switchBlockedTitle')+'"':''}>${a.active?tr('usingNow'):opt?tr('optimizeRules'):tr('switchTo')}</button>
   ${a.plan==='free'?`<button class="btn-renew" onclick="recheck('${n}',this)"><i class="rn-ic">✅</i> <span class="rn-t">${tr('extended')}</span></button>`:''}
   ${loginChip(a.login_expires)}<button class="btn-relogin" onclick="relogin('${n}',this)">${tr('relogin')}</button>
   <button class="btn-del" title="${tr('delBtnTitle')}" onclick="acctDel('${n}')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14M10 11v6m4-6v6"/></svg>${tr('delBtn')}</button></div>
  </div>`;
 }).join('')+`<button class="addtile" onclick="acctAdd()"><span class="plus">+</span>${tr('addTile')}</button>`;
}
async function load(refresh){
 const r=await fetch(API+'limits?token='+TOKEN+(refresh?'&refresh=1':''));const d=await r.json();
 lastSnap=d;
 $('#auto').checked=!!(d.config&&d.config.autoswitch);
 const opt=!!(d.config&&d.config.optimize);$('#opt').checked=opt;
 $('#auto').disabled=opt;$('#autoWrap').style.opacity=opt?'.5':'';
 $('#autoWrap').title=opt?tr('optDisabledTitle'):'';
 if(d.config&&d.config.threshold)THR=d.config.threshold;
 renderAutoLbl();renderCards(d);
 $('#upd').textContent=tr('updated')+' '+new Date(d.ts*1000).toLocaleTimeString(LANG==='en'?'en-GB':'ru');
 renderModel(d.model);
}
let lastCandidates=[];
function familyOf(name){return (name||'').split(' ')[0].toLowerCase();}
function familyRank(f){return f==='haiku'?1:0;}
function unifiedRows(m,candidates){
 const rows={};
 ((m&&m.available)||[]).forEach(a=>{rows[a.id]={id:a.id,name:a.name,enabled:a.enabled!==false,isNew:!!a.new,known:true};});
 (candidates||[]).forEach(c=>{if(!rows[c.id])rows[c.id]={id:c.id,name:c.guess_name,enabled:false,isNew:false,known:false};});
 return Object.values(rows).sort((a,b)=>{
  const fa=familyOf(a.name),fb=familyOf(b.name);
  if(fa!==fb){const ra=familyRank(fa),rb=familyRank(fb);if(ra!==rb)return ra-rb;return fa<fb?-1:1;}
  return a.id<b.id?1:(a.id>b.id?-1:0);
 });
}
function renderPool(){
 $('#poolList').innerHTML=unifiedRows(lastModel,lastCandidates).map(r=>
  `<div class="poolrow" data-id="${r.id}" data-known="${r.known?1:0}" style="flex-direction:column;align-items:stretch;gap:5px;cursor:default">
    <label style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;cursor:pointer;margin:0">
     <input type="checkbox" class="poolchk" ${r.enabled?'checked':''}>
     <span style="word-break:break-all">${r.id}</span>${r.isNew?' <span class="newbadge" style="margin-left:0">'+tr('newBadge')+'</span>':''}
    </label>
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
}
async function pickModel(id){
 const r=await fetch(API+'model?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:id})});
 const d=await r.json();toast(d.ok?'✅ '+d.message:'⚠ '+d.message);renderModel(d.model);
}
$('#poolList').addEventListener('change',async e=>{
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
$('#modalDone').addEventListener('click',()=>{$('#scrim').hidden=true;});
$('#scrim').addEventListener('click',e=>{if(e.target.id==='scrim')$('#scrim').hidden=true});
function toast(t){const m=$('#msg');m.textContent=t;m.style.display='block';setTimeout(()=>m.style.display='none',4000)}
async function sw(n){
 if(!confirm(tr('confirmSwitch',n)))return;
 const r=await fetch(API+'switch?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:n})});
 const d=await r.json();toast(d.ok?'✅ '+d.message.split('\n')[0]:'⚠ '+d.message);load();
}
async function sessionCmd(cmd){
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
$('#thrMinus').addEventListener('click',()=>setThr(THR-5));
$('#thrPlus').addEventListener('click',()=>setThr(THR+5));
$('#opt').addEventListener('change',async e=>{
 await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({optimize:e.target.checked})});
 toast(e.target.checked?tr('optOn'):tr('optOff'));load();
});
async function recheck(n,btn){
 btn.disabled=true;const orig=btn.innerHTML;btn.innerHTML='<span class="rn-t">'+tr('checking')+'</span>';
 try{
  const r=await fetch(API+'recheck?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:n})});
  const d=await r.json();toast(d.message);
 }catch(e){toast(tr('checkErr',e));}
 finally{btn.disabled=false;btn.innerHTML=orig;load();}
}
async function relogin(n,btn){
 btn.disabled=true;const orig=btn.textContent;btn.textContent=tr('relStarting');
 try{
  const r=await fetch(API+'relogin/start?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:n})});
  const d=await r.json();
  if(!d.ok){toast('⚠ '+d.message);return;}
  try{await navigator.clipboard.writeText(d.url);}catch(e){}
  window.open(d.url,'_blank');
  const code=prompt(tr('relPrompt',d.email||n));
  if(code==null)return;
  btn.textContent=tr('relChecking');
  const r2=await fetch(API+'relogin/submit?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:n,code,lang:LANG})});
  const d2=await r2.json();toast(d2.ok?d2.message:'⚠ '+d2.message);
 }catch(e){toast('⚠ '+e);}
 finally{btn.disabled=false;btn.textContent=orig;load();}
}
$('#rf').addEventListener('click',()=>{$('#rf').disabled=true;load(1).finally(()=>$('#rf').disabled=false)});

// ---- добавление и удаление аккаунтов ----
// Окно одно на оба сценария (#acctBox). Удаление необратимо: кнопка «Удалить навсегда»
// оживает только после ввода слова; ту же проверку делает и сервер.
const acctEsc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let acctBusy=false;
function acctClose(){if(acctBusy)return;$('#acctScrim').hidden=true;$('#acctBox').innerHTML='';}
function acctShow(html){$('#acctBox').innerHTML=html;$('#acctScrim').hidden=false;}
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
  <div class="dlgwarn">${tr('delWarn')}${a.active?'<br><br>'+tr('delActive'):''}</div>
  ${last?`<div class="dlgerr">${tr('delLast')}</div>`:`<label class="dlglbl" for="delInp">${tr('delType',word)}</label>
  <input id="delInp" class="dlginp" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${word}">
  <div class="dlgerr" id="acctErr" hidden></div>`}
  <div class="modalfoot"><button class="ghostbtn" id="acctCancel" style="margin-top:0">${tr('cancel')}</button>${last?'':`<button class="btn-danger" id="delGo" disabled>${tr('delGo')}</button>`}</div>`);
 $('#acctCancel').onclick=acctClose;
 if(last)return;
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
 $('#addCopy').onclick=async()=>{try{await navigator.clipboard.writeText(d.url);const b=$('#addCopy');b.textContent=tr('addCopied');setTimeout(()=>{b.textContent=tr('addCopy')},1800);}catch(e){}};
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
 if(!d||d.stale||(lvl==='none'&&!pause.active&&!pause.override)){el.hidden=true;return;}
 // приоритет: пауза отключена кнопкой > пауза (в ней уже есть будильник) >
 // переключаться некуда > активный забит
 const mode=pause.override?'off':pause.active?'pause':lvl;
 const near=(d.nearest&&d.nearest.resets_at)?new Date(d.nearest.resets_at).getTime():0;
 const thr=Math.round(d.threshold||90);
 let title,sub,timer=null,tlabel='',action=null;
 if(mode==='off'){
  const na=d.nearest&&d.nearest.acc;
  title=tr('ccpOffTitle');sub=tr('ccpOffSub',lvl==='hard'&&na?ccpEsc(na):'',lvl==='hard'&&near?ccpAt(near):'');
  action={act:'on',label:tr('ccpBtnOn'),hint:tr(lvl==='hard'?'ccpHintOnHard':'ccpHintOnFree')};
 }else if(mode==='pause'){
  const upMs=(pause.resume_at||0)*1000;
  title=tr('ccpPauseTitle');
  sub=tr('ccpPauseSub',ccpEsc(pause.reason||tr('ccpDefReason')),upMs?ccpAt(upMs):'')
    +(pause.note?'<br>'+ccpEsc(pause.note):'');
  if(upMs){timer=upMs;tlabel=tr('ccpTillWake');}
  action={act:'off',label:tr('ccpBtnOff'),hint:tr('ccpHintOff',thr)};
 }else if(mode==='hard'){
  const na=d.nearest&&d.nearest.acc;
  title=tr('ccpHardTitle');sub=tr('ccpHardSub',thr,na?ccpEsc(na):'',na?ccpEsc(d.nearest.held||''):'');
  if(near){timer=near;tlabel=na?tr('ccpTillFree',ccpEsc(na)):tr('ccpTillNearest');}
  action={act:'off',label:tr('ccpBtnOff'),hint:tr('ccpHintHardOff')};
 }else{
  const a=(d.accounts||{})[d.active]||{};
  title=tr('ccpGateTitle');
  // без таймера: сброс сессии активного тут ни при чём — балансер уходит на свободный сразу
  sub=tr('ccpGateSub',ccpEsc(d.active||'?'),a.pct==null?'?':a.pct+'%',a.wpct==null?'?':Math.round(a.wpct)+'%',thr);
 }
 const chips=Object.entries(d.accounts||{}).map(([n,a])=>
  '<span class="ccp-chip'+(a.usable===false?' hot':'')+'">'+ccpEsc(n)
  +(a.active?tr('ccpActive'):'')+' <b>'+(a.pct==null?'?':a.pct+'%')+'</b>'
  +(a.wpct!=null&&a.wpct>=90?tr('ccpWeek',Math.round(a.wpct)):'')+'</span>').join('');
 el.className='ccpause lvl-'+mode;el.hidden=false;
 el.innerHTML='<span class="ccp-dot"></span><div class="ccp-body"><div class="ccp-title">'+title+'</div>'
  +'<div class="ccp-sub">'+sub+'</div><div class="ccp-meta">'+chips
  +(pause.active&&pause.checks?'<span class="ccp-chip">'+tr('ccpChecks',pause.checks)+'</span>':'')
  +'</div>'
  +(action?'<div class="ccp-actions"><button type="button" class="ccp-btn" onclick="ccpToggle(\''+action.act+'\',this)">'
    +action.label+'</button><span class="ccp-hint">'+ccpEsc(action.hint)+'</span></div>':'')
  +'</div>'
  +(timer?'<div class="ccp-timer" data-until="'+timer+'"><div class="t">'+ccpLeft(timer)+'</div>'
    +'<div class="l">'+tlabel+'</div></div>':'');
}
function ccpTick(){
 const t=$('#ccPause .ccp-timer');if(!t)return;
 const until=+t.dataset.until;
 t.querySelector('.t').textContent=ccpLeft(until);
 if(Date.now()>until+60000)ccpLoad();  // окно должно было отпустить — перечитаем
}
async function ccpToggle(act,btn){
 if(btn)btn.disabled=true;
 try{
  const r=await fetch(API+'pause?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:act})});
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

// ---- автообновление: баннер «вышла версия», блок в настройках, ручной/авто режим ----
let updData=null,updWait=null,updTimer=null,updDown=false;
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
 updRender();updSettingsRender();
 updTimer=setTimeout(updLoad,(updBusy()||updDown)?2000:60000);
}
// причина ошибки: код → текст на языке интерфейса (сырой текст бэкенда — в подсказке); нет перевода — показываем как есть
function updErrText(code,raw){
 const k='updE_'+code;
 if(code&&I18N[LANG][k])return '<span'+(raw?' title="'+ccpEsc(raw)+'"':'')+'>'+ccpEsc(tr(k))+'</span>';
 return ccpEsc(raw||'');
}
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
   cls='lvl-updok';title=tr('updOkTitle',ccpEsc(res.to));sub=tr('updOkSub',ccpEsc(res.from));
   acts='<button type="button" class="ccp-btn" onclick="updAck()">'+tr('updBtnOk')+'</button>';
  }else{
   cls='lvl-upderr';title=tr('updErrTitle',ccpEsc(res.to));
   sub=updErrText(res.code,res.error)+(res.rolled_back?'<br>'+tr('updRolled'):'');
   acts='<button type="button" class="ccp-btn" onclick="updAck()">'+tr('updBtnOk')+'</button>'
    +((d.available&&!res.needs_install&&d.supported)?'<button type="button" class="ccp-btn sec" onclick="updApply(this)">'+tr('updBtnRetry')+'</button>':'');
  }
 }else if(d.available&&!d.skipped){
  cls='lvl-upd';title=tr('updBTitle',ccpEsc(L.version));sub=tr('updBSub',ccpEsc(d.version),ccpEsc(L.name&&L.name!==L.tag?L.name:''));
  const notes=updNotesText(L.notes);
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
function updSettingsRender(){
 const box=$('#updBox');if(!box||$('#scrim').hidden)return;
 const d=updData;
 if(!d){box.innerHTML='';return;}
 const L=d.latest;
 const line=d.available?tr(d.skipped?'updSkippedLine':'updAvailLine',L.version):tr(d.last_check?'updUpToDate':'updNeverChecked');
 const when=(!d.available&&d.last_check)?' · '+tr('updCheckedAt',updAt(d.last_check)):'';
 box.innerHTML='<div class="updrow"><div class="updtxt"><b>'+tr('updVer',ccpEsc(d.version))+'</b>'
  +'<div class="updsub'+(d.last_error?' bad':'')+'">'+(d.last_error?updErrText(d.last_error_code,d.last_error):ccpEsc(line+when))+'</div></div>'
  +'<button type="button" class="ghostbtn" id="updCheckBtn">'+tr('updCheckBtn')+'</button></div>'
  +((d.available&&d.skipped&&d.supported&&!updBusy())?'<div class="updrow"><div class="updtxt"></div><button type="button" class="ghostbtn" id="updApplyBtn">'+tr('updBtnNow')+'</button></div>':'')
  +'<div class="updrow"><div class="fsseg" role="radiogroup">'
  +['manual','auto'].map(m=>'<button type="button" role="radio" data-m="'+m+'" aria-checked="'+(d.mode===m)+'" class="'+(d.mode===m?'on':'')+'">'+tr(m==='auto'?'updAuto':'updManual')+'</button>').join('')+'</div></div>'
  +'<div class="modalsub" style="margin:0">'+tr(d.mode==='auto'?'updHintAuto':'updHintManual')+'</div>'
  +'<label class="updchk"><input type="checkbox" id="updChk"'+(d.check?' checked':'')+'><span>'+tr('updCheckLbl')+'</span></label>';
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
 if(e.target.id==='updCheckBtn'){
  e.target.disabled=true;
  try{updData=await updPost('check');}catch(x){}
  updRender();updSettingsRender();return;
 }
 if(e.target.id==='updApplyBtn')return updApply(e.target);
});
$('#updBox').addEventListener('change',async e=>{
 if(e.target.id!=='updChk')return;
 await fetch(API+'config?token='+TOKEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({update_check:e.target.checked})});
 updLoad();
});
$('#gear').addEventListener('click',()=>{updSettingsRender();updLoad();});
applyI18n();load();setInterval(()=>load(),60000);
updLoad();
ccpLoad();setInterval(ccpLoad,20000);setInterval(ccpTick,1000);
</script></body></html>"""


if __name__ == "__main__":
    threading.Thread(target=poll_loop, daemon=True).start()
    threading.Thread(target=_dialog_watchdog, daemon=True).start()
    threading.Thread(target=UPDATER.loop, daemon=True, name="cc-update-loop").start()
    port = cfg().get("port", 8877)
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"cc-limits up on 127.0.0.1:{port}", flush=True)
    srv.serve_forever()
