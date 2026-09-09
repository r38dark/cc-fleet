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
backoff_until = 0  # после 429: реальные запросы к Anthropic заблокированы до этого ts


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
    global rate_limited, backoff_until
    prev = jload(SNAPSHOT) or {}
    # дедуп: не дёргать Anthropic чаще раза в 30с (иначе 429 Too Many Requests),
    # UI-запросы между опросами получают свежий снапшот с актуальным active.
    # backoff_until — доп. защита: 30с-дедуп сам по себе не спасал, если UI
    # опрашивает /api/limits НЕ через force чаще, чем poll_sec, но реже 30с —
    # он проходит дедуп и сразу повторяет запрос, который поймал 429 только
    # что, до того как poll_loop успеет притормозить свой ОТДЕЛЬНЫЙ таймер.
    # backoff_until блокирует ЛЮБОЙ non-force путь на время бэкоффа.
    if not force and (time.time() - prev.get("ts", 0) < 30 or time.time() < backoff_until):
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
        # неактивный аккаунт не расходует свою квоту сам по себе — незачем
        # дёргать его usage/profile так же часто, как активный. При poll_sec,
        # выставленном пониже (быстрая реакция на форс-свитч), это удваивало
        # частоту опроса ВСЕХ аккаунтов разом и ловило 429 на неактивных.
        # force_account — явный обход для кнопки "Я продлил" (/api/recheck),
        # там нужна гарантированная свежесть именно этого аккаунта.
        old = good.get(n) or {}
        stale_ok = (n != act and n != force_account and old.get("ts")
                    and time.time() - old["ts"] < cfg().get("inactive_poll_sec", 300))
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
    if saw_429:
        backoff_until = time.time() + cfg().get("poll_sec", 90) * 2
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
    "claude-fable-5-1": "Fable 5.1",
    "claude-opus-5": "Opus 5",
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


def model_candidates():
    # known_ids копится в model_version_watch.py при каждом изменении версии CLI —
    # там вперемешку публичные релизы и internal/preview-варианты (-fast, -v1,
    # датированные снапшоты). Отдаём то, чего ещё нет в текущем наборе и что не
    # отклонили раньше — какой из них реальная модель, а какой мусор, решает
    # человек в UI (чекбоксы), не автоматика.
    known = (jload(MODEL_WATCH_STATE, {}) or {}).get("known_ids") or []
    have = set(all_models().keys())
    ignored = set(cfg().get("model_ignored_ids") or [])
    cand_ids = sorted(m for m in known if m not in have and m not in ignored)

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

    return [{"id": m, "guess_name": guess_name(m)} for m in cand_ids]


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
                           "new": now - added_ts.get(k, 0) < 14 * 86400}
                          for k, v in models.items()]}


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
    # время сброса в локальной зоне сервера, коротко: «07:40»
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso).astimezone().strftime("%H:%M")
    except Exception:
        return "?"


def _accs_line(accs):
    out = []
    for n, row in sorted(accs.items()):
        fh = row.get("five_hour") or {}
        r = fh.get("resets_at")
        out.append("%s: сессия %s%%%s" % (n, fh.get("pct"),
                                          (" (сброс %s)" % _local_hm(r)) if r else ""))
    return "\n".join(out)


def _nearest_reset(accs):
    best = None
    for n, row in accs.items():
        iso = (row.get("five_hour") or {}).get("resets_at")
        if not iso:
            continue
        try:
            from datetime import datetime
            ts = datetime.fromisoformat(iso).timestamp()
        except Exception:
            continue
        if best is None or ts < best[0]:
            best = (ts, n, iso)
    return ("%s в %s" % (best[1], _local_hm(best[2]))) if best else "неизвестно"


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
            _log_switch_event("forced_no_candidate", active=act, fh=fh, sd=sd)
        if forced and not st.get("all_high_notified"):
            # раньше уведомление отсюда убрали как спам, и «упёрлись ВСЕ аккаунты» стало
            # происходить молча — пользователь может не понимать, почему сессия не работает,
            # часами. Возвращаем ровно ОДНО сообщение на эпизод (флаг снимается только когда
            # снова появился живой кандидат) и не чаще раза в 2 часа. Это не тот спам, что
            # убирали: успешные переключения по-прежнему молчат.
            if time.time() - st.get("all_high_notified_ts", 0) >= 7200:
                tg_notify("⛔ Claude: все аккаунты упёрлись в лимит сессии — переключаться некуда.\n"
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
        if now - st.get("last_switch_ts", 0) < c.get("switch_cooldown_sec", 600):
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
        try:
            with lock:
                # collect(force=True) обходит и 30с-дедуп, и backoff_until — если звать
                # его безусловно каждый тик, во время активного 429-бэкоффа фоновый поток
                # продолжит долбить Anthropic и будет ловить 429 заново. Поэтому во время
                # бэкоффа берём последний снапшот с диска вместо нового запроса.
                if time.time() < backoff_until:
                    snap = jload(SNAPSHOT) or snap_set_active()
                else:
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
                renewal = jload(STATE, {}).get("renewal", {})
            for n, row in (snap.get("accounts") or {}).items():
                ts = (renewal.get(n) or {}).get("confirmed_ts")
                if ts:
                    row["renewal_next"] = _renewal_next(ts)
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
            if plan and plan != "free" and not err:
                # якорь для таймера обратного отсчёта до следующего ожидаемого
                # обвала Pro→Free — момент, когда пользователь подтвердил
                # продление; см. _renewal_next()
                with lock:
                    st = jload(STATE, {})
                    st.setdefault("renewal", {})[name] = {"confirmed_ts": time.time()}
                    jsave(STATE, st)
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
        if u.path == "/api/session":
            ok, msg = send_session_command(body.get("cmd", ""))
            return self._send(200 if ok else 400, {"ok": ok, "message": msg})
        if u.path == "/api/config":
            c = cfg()
            for k in ("autoswitch", "threshold", "optimize"):
                if k in body:
                    c[k] = body[k]
            if "enabled_models" in body:
                # неизвестные id молча отбрасываем; пустой список игнорируем целиком —
                # хотя бы одна модель должна остаться доступной для переключения
                ids = [m for m in body["enabled_models"] if m in all_models()]
                if ids:
                    c["enabled_models"] = ids
            jsave(CONFIG, c)
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
<div class="hdr"><h1 id="h1">⚡ Claude — лимиты аккаунтов</h1><div style="display:flex;align-items:center;gap:10px"><div id="langSwitch" style="font-size:12px;color:var(--mut);cursor:pointer;white-space:nowrap"></div><button id="gear" class="hdrgear" title="Модели">⚙</button></div></div>
<div class="ccpause" id="ccPause" hidden></div>
<div class="termwrap">
 <div class="termhead"><h2 id="consoleTitle">🖥 Консоль (только чтение)</h2><span class="termdot" id="termDot"></span></div>
 <pre class="termbox" id="termBox"><span id="termHistory"></span>
<span id="termCurrent">Загрузка…</span></pre>
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
  <h3 id="modalTitle">Модели</h3>
  <div class="modalsub" id="modalSub">Отметь, какие показывать кнопками на главной — применяется сразу, без «Сохранить»</div>
  <div id="poolList"></div>
  <div class="modalfoot"><button id="checkNew" class="ghostbtn">🔄 Проверить новые модели</button><button id="modalDone" style="margin-top:0">Готово</button></div>
 </div>
</div>
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
  modelsBtnTitle:'Модели',
  modelsTitle:'Модели',
  modelsSub:'Отметь, какие показывать кнопками на главной — применяется сразу, без «Сохранить»',
  modelsDone:'Готово',
  noModelsEnabled:'Ни одна модель не включена — открой ⚙',
  newBadge:'новая',
  checkNewModels:'🔄 Проверить новые модели',
  candSearching:'Ищу…',
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
  extended:'✅ I renewed',
  relogin:'🔑 Log in again',
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
  modelsBtnTitle:'Models',
  modelsTitle:'Models',
  modelsSub:'Pick which ones show as quick-switch buttons — applies instantly, no Save button',
  modelsDone:'Done',
  noModelsEnabled:'No models enabled — open ⚙',
  newBadge:'new',
  checkNewModels:'🔄 Check for new models',
  candSearching:'Searching…',
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
  if(atBottom)box.scrollTop=box.scrollHeight;
 }catch(e){dot.className='termdot err';}
}
ccConsoleHistory();ccConsole();setInterval(ccConsole,2000);
function col(p){return p==null?'#555':p<60?'var(--ok)':p<85?'var(--warn)':'var(--bad)'}
function rst(iso){if(!iso)return'';const d=new Date(iso),m=Math.max(0,Math.round((d-Date.now())/60000));
 const h=Math.floor(m/60),mm=m%60;return tr('resetIn',h,mm,d.toLocaleTimeString(LANG==='en'?'en-GB':'ru',{hour:'2-digit',minute:'2-digit'}))}
function bar(lbl,o){o=o||{};const p=o.pct;return`<div class="row"><div class="lbl"><span>${lbl}: <b style="color:${col(p)}">${p==null?'?':p+'%'}</b></span><span>${rst(o.resets_at)}</span></div>
 <div class="bar"><div class="fill" style="width:${p||0}%;background:${col(p)}"></div></div></div>`}
function renewChip(iso){if(!iso)return'';const d=new Date(iso),ms=d-Date.now();
 const title=tr('renewalIn',Math.max(0,Math.floor(ms/86400000)),Math.max(0,Math.floor((ms%86400000)/3600000)));
 if(ms<=0)return`<span class="chip urgent" title="${tr('renewalSoon')}">${tr('renewalChipToday')}</span>`;
 const days=Math.floor(ms/86400000);
 return`<span class="chip${days<3?' urgent':''}" title="${title}">${tr('renewalChip',days)}</span>`}
function urgCol(f){return f>.5?'var(--bad)':f>.2?'var(--warn)':'var(--ok)'}
function frac(iso,windowSec){if(!iso)return 0;const remain=(new Date(iso)-Date.now())/1000;return Math.max(0,Math.min(1,remain/windowSec))}
function ring(o,windowSec,size){o=o||{};size=size||34;const sw=Math.max(3,Math.round(size*.1));const rad=size/2-sw/2;const circ=2*Math.PI*rad;const f=frac(o.resets_at,windowSec);const uc=urgCol(f);const dash=(f*circ).toFixed(1);const c=size/2;
 return `<div class="ring" style="width:${size}px;height:${size}px" title="${rst(o.resets_at)}"><svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}"><circle cx="${c}" cy="${c}" r="${rad}" fill="none" stroke="#242b38" stroke-width="${sw}"/><circle cx="${c}" cy="${c}" r="${rad}" fill="none" stroke="${uc}" stroke-width="${sw}" stroke-linecap="round" stroke-dasharray="${dash} ${circ.toFixed(1)}" transform="rotate(-90 ${c} ${c})"/></svg><span class="ringtxt" style="font-size:${Math.round(size*.26)}px">${Math.round(f*100)}%</span></div>`}
function renderCards(d){
 const opt=!!(d.config&&d.config.optimize);
 $('#cards').innerHTML=Object.entries(d.accounts).map(([n,a])=>{
  const plan=a.plan==='free'?'<span class="tag" style="background:#2c3547;color:var(--mut)">FREE</span> ':a.plan?'<span class="tag" style="background:var(--acc);color:#0f1115">'+a.plan.toUpperCase()+'</span> ':'';
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
   <button onclick="sw('${n}')" ${a.active||opt?'disabled':''} ${opt&&!a.active?'title="'+tr('switchBlockedTitle')+'"':''}>${a.active?tr('usingNow'):opt?tr('optimizeRules'):tr('switchTo')}</button>
   ${a.plan==='free'?`<button onclick="recheck('${n}',this)" style="margin-top:6px;background:var(--acc);color:#0f1115">${tr('extended')}</button>`:''}
   <button onclick="relogin('${n}',this)" style="margin-top:6px;margin-left:8px;background:transparent;border:1px solid #333c4d;color:var(--mut)">${tr('relogin')}</button>
  </div>`;
 }).join('');
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
    <input type="text" class="poolname" value="${r.name}" style="width:100%;box-sizing:border-box;background:#0f1115;border:1px solid #2a3140;color:inherit;border-radius:6px;padding:5px 8px;font-size:13px">
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
  const r=await fetch(API+'models/candidates?token='+TOKEN);const d=await r.json();
  lastCandidates=(d&&d.candidates)||[];
 }catch(e){lastCandidates=[];}
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
  try{await navigator.clipboard.writeText(d.url);}catch(e){}
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
