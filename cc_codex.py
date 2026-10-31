#!/usr/bin/env python3
# cc_codex — аккаунты ChatGPT (Codex CLI) в панели cc-limits.
#
# Это НЕ часть авто-переключателя Claude: Codex — отдельная программа со своим логином.
# Панель делает три вещи: заводит вход (по коду устройства: пароль и почту вводить не нужно),
# показывает план, лимиты и срок подписки (через `codex app-server`), пишет в config.toml
# выбранные модель, усилие рассуждения и режим Fast. Запускает `codex` под нужным профилем
# человек: у каждого аккаунта свой CODEX_HOME = <PROFILES>/gptN (команда есть на карточке).
import base64, datetime, json, os, pwd, queue, re, shlex, shutil, signal, subprocess, tempfile, threading, time

PROFILES = os.environ.get("CC_CODEX_PROFILES", "/root/.codex-profiles")
LOGIN_TTL = 16 * 60  # код устройства живёт 15 минут; ещё минута на то, чтобы CLI дописал auth.json
INFO_TTL = 90  # сколько секунд карточка берётся из кэша, не поднимая app-server
MODELS_TTL = 600
_SLOT_RE = re.compile(r"^gpt[0-9]{1,3}$")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
# [^\s\x00-\x1f\x7f]+ — как в relogin_start: CLI может окружить ссылку управляющими байтами
_URL = re.compile(r"https://[^\s\x00-\x1f\x7f]+")
_CODE = re.compile(r"\b([A-Z0-9]{3,8}-[A-Z0-9]{3,8})\b")
_AUTH_ERR = re.compile(r"401|unauthori|sign in|log ?in again|logged out|token.{0,30}(expired|invalid|revoked)|not logged", re.I)
DELETE_WORDS = ("подтверждаю", "confirm")

NOTIFY = None  # cc_limits подставляет tg_notify: сообщение в телеграм, когда вход завершён
RUN_AS = None  # имя или функция → имя; cc_limits подставляет config.json "codex_user": codex запускается от этого пользователя ОС, а не от root
_PASS_ENV = ("PATH", "LANG", "LC_ALL", "TERM", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
             "http_proxy", "https_proxy", "all_proxy", "no_proxy")
_lock = threading.Lock()  # состояние входов (_logins) и кэш карточек (_cache)
_logins = {}  # slot -> {state, new, label, url, code, started, err, email, plan, proc, home}
_cache = {}  # slot -> {ts, data}
_models_cache = {}  # plan -> {ts, models}
_slot_locks = {}


class CodexError(Exception):
    pass


def _t(lang, ru, en):
    return en if lang == "en" else ru


def _strip(s):
    return _ANSI.sub("", s or "")


def jload(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _jsave(path, data):
    tmp = f"{path}.tmp{os.getpid()}{threading.get_ident()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def find_bin(configured=None):
    """Путь к codex: из config.json → CC_CODEX_BIN → PATH → типичные места. None — Codex не установлен."""
    for p in (configured, os.environ.get("CC_CODEX_BIN")):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    p = shutil.which("codex")
    if p:
        return p
    for p in ("~/.npm-global/bin/codex", "/usr/local/bin/codex", "~/.local/bin/codex"):
        p = os.path.expanduser(p)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def profile_dir(slot):
    return os.path.join(PROFILES, slot)


def profile_slots():
    """Заведённые профили (есть auth.json), по номеру."""
    out = []
    if os.path.isdir(PROFILES):
        for d in os.listdir(PROFILES):
            if _SLOT_RE.match(d) and os.path.isfile(os.path.join(PROFILES, d, "auth.json")):
                out.append(d)
    return sorted(out, key=lambda s: int(s[3:]))


def meta(slot):
    return jload(os.path.join(profile_dir(slot), "meta.json"), {}) or {}


def launch_cmd(slot):
    u = runas_user()
    if u:
        return f"runuser -u {u} -- env HOME={shlex.quote(pwd.getpwnam(u).pw_dir)} CODEX_HOME={shlex.quote(profile_dir(slot))} codex"
    return f"CODEX_HOME={shlex.quote(profile_dir(slot))} codex"


def _free_slot():
    used = set()
    if os.path.isdir(PROFILES):
        used = {int(d[3:]) for d in os.listdir(PROFILES) if _SLOT_RE.match(d)}
    used |= {int(s[3:]) for s in _logins}
    n = 1
    while n in used:
        n += 1
    return f"gpt{n}"


def _jwt(tok):
    try:
        b = tok.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))
    except Exception:
        return {}


def read_claims(auth_path):
    """Из auth.json достаём то, что CLI уже знает без сети: почта, план, срок подписки."""
    a = jload(auth_path, {}) or {}
    idt = _jwt((a.get("tokens") or {}).get("id_token"))
    au = idt.get("https://api.openai.com/auth") or {}
    return {"email": idt.get("email"), "plan": au.get("chatgpt_plan_type"),
            "sub_until": au.get("chatgpt_subscription_active_until"),
            "last_refresh": a.get("last_refresh")}


def runas_user():
    """Пользователь ОС, от которого запускается codex; None — запускаем от себя (панель и так не root, либо не задано)."""
    u = RUN_AS() if callable(RUN_AS) else RUN_AS
    if not u or os.geteuid() != 0:
        return None
    try:
        pwd.getpwnam(u)
    except KeyError:
        return None
    return u


def wrap(argv, home, extra=None):
    """→ (argv, env) для Popen. От RUN_AS — через runuser с чистым окружением (секреты root не наследуются);
    иначе как есть: окружение панели + CODEX_HOME."""
    extra = dict(extra or {}, CODEX_HOME=home)
    u = runas_user()
    if not u:
        return list(argv), dict(os.environ, **extra)
    pw = pwd.getpwnam(u)
    clean = {k: os.environ[k] for k in _PASS_ENV if os.environ.get(k)}
    clean.update(extra, HOME=pw.pw_dir)
    return ["runuser", "-u", u, "--", "env", "-i"] + [f"{k}={v}" for k, v in clean.items()] + list(argv), dict(os.environ)


def own(path, tree=False):
    """Отдаёт файл/папку пользователю RUN_AS (панель создаёт профили от root, а codex читает их от него)."""
    u = runas_user()
    if not u:
        return
    pw = pwd.getpwnam(u)
    try:
        if tree and os.path.isdir(path) and not os.path.islink(path):
            for root, dirs, files in os.walk(path):
                for n in dirs + files:
                    os.chown(os.path.join(root, n), pw.pw_uid, pw.pw_gid, follow_symlinks=False)
        os.chown(path, pw.pw_uid, pw.pw_gid, follow_symlinks=False)
    except OSError:
        pass


def _iso(ts):
    if not ts:
        return None
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- вход по коду устройства
def _kill(proc):
    # codex — обёртка node, настоящий бинарник живёт её потомком: убиваем всю группу (процессы стартуют в своей сессии)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=3)
    except Exception:
        pass


def _login_drop(slot):
    st = _logins.pop(slot, None)
    if not st:
        return
    if st.get("proc") and st["proc"].poll() is None:
        _kill(st["proc"])
    if st.get("home"):
        shutil.rmtree(st["home"], ignore_errors=True)


def _login_sweep():
    now = time.time()
    for s in [s for s, st in list(_logins.items()) if now - st["started"] > LOGIN_TTL + 600]:
        _login_drop(s)
    # временные папки входа, оставшиеся после перезапуска службы посреди входа (в них может лежать токен)
    live = {st.get("home") for st in _logins.values()}
    try:
        for n in os.listdir(PROFILES):
            d = os.path.join(PROFILES, n)
            if n.startswith(".login-") and d not in live and now - os.path.getmtime(d) > LOGIN_TTL + 600:
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def login_start(bin_path, slot=None, label="", lang="ru"):
    """→ (ok, {slot,url,code,expires_in} | сообщение). slot=None — новый аккаунт, иначе перелогин существующего."""
    new = slot is None
    with _lock:
        _login_sweep()
        if not new:
            if not _SLOT_RE.match(slot or "") or slot not in profile_slots():
                return False, _t(lang, "Неизвестный аккаунт.", "Unknown account.")
        else:
            slot = _free_slot()
        _login_drop(slot)  # брошенная попытка — начинаем чисто
        os.makedirs(PROFILES, exist_ok=True)
        os.chmod(PROFILES, 0o700)
        own(PROFILES)
        home = tempfile.mkdtemp(prefix=".login-", dir=PROFILES)
        with open(os.path.join(home, "config.toml"), "w") as f:
            f.write('cli_auth_credentials_store = "file"\n')  # токен — файлом, а не в связке ключей ОС
        own(home, tree=True)
        argv, env = wrap([bin_path, "login", "--device-auth"], home, {"NO_COLOR": "1"})
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=home,
                                    start_new_session=True, text=True, errors="replace")
        except Exception as e:
            shutil.rmtree(home, ignore_errors=True)
            return False, _t(lang, f"Не удалось запустить codex: {e}", f"Could not start codex: {e}")
        st = {"state": "waiting", "new": new, "label": (label or "").strip()[:60], "url": None, "code": None,
              "started": time.time(), "err": None, "email": None, "plan": None, "proc": proc, "home": home,
              "buf": []}
        _logins[slot] = st
    threading.Thread(target=_login_reader, args=(st,), daemon=True).start()
    end = time.time() + 20
    while time.time() < end and not (st["url"] and st["code"]) and proc.poll() is None:
        time.sleep(0.15)
    if not (st["url"] and st["code"]):
        tail = _strip("".join(st["buf"]))[-300:].strip()
        with _lock:
            _login_drop(slot)
        return False, _t(lang, "codex login не показал ссылку и код: ", "codex login showed no link and code: ") + tail
    threading.Thread(target=_login_watch, args=(slot, st), daemon=True).start()
    return True, {"slot": slot, "url": st["url"], "code": st["code"], "expires_in": 15 * 60}


def _login_reader(st):
    out = st["proc"].stdout
    for line in out:
        st["buf"].append(line)
        text = _strip("".join(st["buf"]))
        if not st["url"]:
            m = _URL.search(text)
            if m:
                st["url"] = m.group(0).rstrip(").,")
        if st["url"] and not st["code"]:
            # код ищем только после ссылки, чтобы не принять за него кусок URL или версию
            tail = text[text.find(st["url"]) + len(st["url"]):]
            m = _CODE.search(tail)
            if m:
                st["code"] = m.group(1)
    out.close()


def _cli_tail(buf):
    """Что CLI написал после кода устройства (ошибка и т.п.); сам адрес, код и подсказки не повторяем."""
    keep = []
    for ln in _strip("".join(buf)).splitlines():
        t = ln.strip()
        if not t or _URL.search(t) or _CODE.search(t) or re.match(r"^\d\.\s", t) or t.startswith(("Welcome to Codex", "Continue only")):
            continue
        keep.append(t)
    return " ".join(keep)[-200:]


def _login_watch(slot, st):
    """Ждёт, пока человек введёт код в браузере: CLI сам завершится и запишет auth.json."""
    proc = st["proc"]
    try:
        rc = proc.wait(timeout=LOGIN_TTL)
    except subprocess.TimeoutExpired:
        _kill(proc)
        rc = None
    time.sleep(0.3)  # reader дочитает хвост вывода
    done = None
    with _lock:
        if _logins.get(slot) is not st:  # попытку отменили или перезапустили
            return
        auth = os.path.join(st["home"], "auth.json")
        if rc != 0 or not os.path.isfile(auth):
            tail = _cli_tail(st["buf"])
            st["state"], st["err"] = "failed", (
                "Код не подтверждён вовремя или вход отменён." + (f" Вывод CLI: {tail}" if tail else ""),
                "The code was not confirmed in time or the sign-in was cancelled." + (f" CLI output: {tail}" if tail else ""))
            shutil.rmtree(st["home"], ignore_errors=True)
            return
        cl = read_claims(auth)
        st["email"], st["plan"] = cl.get("email"), cl.get("plan")
        final = profile_dir(slot)
        if st["new"]:
            em = (cl.get("email") or "").lower()
            dup = next((s for s in profile_slots() if em and (meta(s).get("email") or "").lower() == em), None)
            if dup:
                st["state"], st["err"] = "failed", (
                    f"Этот аккаунт ({cl.get('email')}) уже подключён как {dup} — второй раз добавлять не нужно.",
                    f"This account ({cl.get('email')}) is already connected as {dup} — no need to add it twice.")
                shutil.rmtree(st["home"], ignore_errors=True)
                return
            if os.path.exists(final):
                st["state"], st["err"] = "failed", ("Слот уже занят — начни добавление заново.",
                                                    "That slot has just been taken — start adding again.")
                shutil.rmtree(st["home"], ignore_errors=True)
                return
            os.rename(st["home"], final)
            os.chmod(final, 0o700)
            os.chmod(os.path.join(final, "auth.json"), 0o600)
            _jsave(os.path.join(final, "meta.json"),
                   {"label": st["label"], "email": cl.get("email"), "added": int(time.time())})
            own(final, tree=True)
        else:
            old = (meta(slot).get("email") or "").lower()
            if old and cl.get("email") and old != cl["email"].lower():
                st["state"], st["err"] = "failed", (
                    f"Это другой аккаунт ({cl['email']}), а в карточке {meta(slot).get('email')}. Для него нужна новая карточка кнопкой «+».",
                    f"That is a different account ({cl['email']}), the card holds {meta(slot).get('email')}. Add it as a new card with \"+\".")
                shutil.rmtree(st["home"], ignore_errors=True)
                return
            os.chmod(auth, 0o600)
            os.replace(auth, os.path.join(final, "auth.json"))
            own(os.path.join(final, "auth.json"))
            shutil.rmtree(st["home"], ignore_errors=True)
        st["state"], st["home"] = "done", None
        _cache.pop(slot, None)
        done = (st["new"], cl.get("email"), cl.get("plan"))
    if done and NOTIFY:
        try:
            NOTIFY(("✅ ChatGPT (Codex): добавлен аккаунт %s, тариф %s." if done[0] else
                    "✅ ChatGPT (Codex): вход обновлён для %s, тариф %s.") % (done[1], (done[2] or "?").upper()))
        except Exception:
            pass


def login_status(slot, lang="ru"):
    with _lock:
        st = _logins.get(slot)
        if not st:
            return {"state": "none"}
        out = {"state": st["state"], "left": max(0, int(LOGIN_TTL - (time.time() - st["started"]))),
               "email": st["email"], "plan": st["plan"], "new": st["new"]}
        if st["state"] == "failed" and st["err"]:
            out["message"] = _t(lang, *st["err"])
        return out


def login_cancel(slot):
    with _lock:
        _login_drop(slot)
    return True


# ---------------------------------------------------------------- codex app-server (JSON-RPC по stdio)
class AppServer:
    def __init__(self, bin_path, home, timeout=25):
        self.timeout = timeout
        argv, env = wrap([bin_path, "app-server"], home)
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, env=env, cwd=home, text=True, bufsize=1,
                                  start_new_session=True)
        self.q = queue.Queue()
        self.n = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            try:
                self.q.put(json.loads(line))
            except Exception:
                pass
        self.p.stdout.close()
        self.q.put(None)

    def _send(self, obj):
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def request(self, method, params=None, timeout=None):
        self.n += 1
        rid = self.n
        self._send({"id": rid, "method": method, "params": params or {}})
        end = time.time() + (timeout or self.timeout)
        while True:
            left = end - time.time()
            if left <= 0:
                raise CodexError(f"{method}: таймаут")
            try:
                m = self.q.get(timeout=left)
            except queue.Empty:
                raise CodexError(f"{method}: таймаут")
            if m is None:
                raise CodexError("codex app-server завершился")
            if m.get("id") == rid:
                if "error" in m:
                    raise CodexError(str((m["error"] or {}).get("message") or m["error"]))
                return m.get("result") or {}

    def __enter__(self):
        try:
            self.request("initialize", {"clientInfo": {"name": "cc-limits", "title": "cc-limits", "version": "1"}})
            self._send({"method": "initialized"})
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, *a):
        self.close()

    def close(self):
        try:
            self.p.stdin.close()
        except Exception:
            pass
        _kill(self.p)


def _models_view(raw):
    out = []
    for m in raw or []:
        tiers = [t for t in (m.get("serviceTiers") or []) if t.get("id")]
        out.append({"id": m.get("id"), "name": m.get("displayName") or m.get("id"),
                    "efforts": [e.get("reasoningEffort") for e in (m.get("supportedReasoningEfforts") or [])],
                    "default_effort": m.get("defaultReasoningEffort"),
                    "fast": tiers[0]["id"] if tiers else None,
                    "is_default": bool(m.get("isDefault"))})
    return out


def fetch_account(bin_path, slot):
    """Живое чтение карточки: план, лимиты, модели, выбранные настройки. Сеть и app-server — до ~10 с."""
    home = profile_dir(slot)
    mt = meta(slot)
    cl = read_claims(os.path.join(home, "auth.json"))
    out = {"slot": slot, "label": mt.get("label") or "", "email": mt.get("email") or cl.get("email"),
           "plan": cl.get("plan"), "sub_until": cl.get("sub_until"), "last_refresh": cl.get("last_refresh"),
           "windows": [], "models": [], "ts": time.time(), "launch": launch_cmd(slot)}
    try:
        with AppServer(bin_path, home) as c:
            acc = c.request("account/read", {"refreshToken": False})
            a = acc.get("account")
            if not a:
                out["login_required"] = True
                return out
            out["email"] = a.get("email") or out["email"]
            out["plan"] = a.get("planType") or out["plan"]
            rl = c.request("account/rateLimits/read")
            snap = rl.get("rateLimits") or {}
            for w in (snap.get("primary"), snap.get("secondary")):
                if w:
                    out["windows"].append({"mins": w.get("windowDurationMins"), "pct": w.get("usedPercent"),
                                           "resets_at": _iso(w.get("resetsAt"))})
            out["reached"] = snap.get("rateLimitReachedType")
            out["credits"] = snap.get("credits")
            out["usage_allowed"] = rl.get("ordinaryUsageAllowed")
            plan = out["plan"] or "?"
            with _lock:
                mc = _models_cache.get(plan)
            if mc and time.time() - mc["ts"] < MODELS_TTL:
                out["models"] = mc["models"]
            else:
                ml = c.request("model/list", {"includeHidden": False})
                out["models"] = _models_view(ml.get("data"))
                with _lock:
                    _models_cache[plan] = {"ts": time.time(), "models": out["models"]}
            conf = (c.request("config/read", {"includeLayers": False}).get("config")) or {}
            out["model"] = conf.get("model")
            out["effort"] = conf.get("model_reasoning_effort")
            out["fast"] = bool(conf.get("service_tier"))
    except Exception as e:
        out["error"] = str(e)
        if _AUTH_ERR.search(str(e)):
            out["login_required"] = True
    return out


def get_accounts(bin_path, force=False):
    """Карточки всех профилей: из кэша (INFO_TTL), устаревшие читаются параллельно."""
    slots = profile_slots()
    todo, res = [], {}
    now = time.time()
    with _lock:
        for s in list(_cache):
            if s not in slots:
                _cache.pop(s, None)
        for s in slots:
            c = _cache.get(s)
            if c and not force and now - c["ts"] < INFO_TTL:
                res[s] = c["data"]
            else:
                todo.append(s)

    def work(s):
        d = fetch_account(bin_path, s)
        with _lock:
            old = (_cache.get(s) or {}).get("data")
            if d.get("error") and old and not old.get("error"):
                old = dict(old, stale=True, error=d["error"], login_required=d.get("login_required", False))
                d = old  # сбой чтения не стирает последние хорошие цифры
            _cache[s] = {"ts": time.time(), "data": d}
        res[s] = d

    ths = [threading.Thread(target=work, args=(s,), daemon=True) for s in todo]
    for t in ths:
        t.start()
    for t in ths:
        t.join(40)
    return [res[s] for s in slots if s in res]


# ---------------------------------------------------------------- настройки модели
def _slot_lock(slot):
    with _lock:
        return _slot_locks.setdefault(slot, threading.Lock())


def set_prefs(bin_path, slot, model, effort, fast, lang="ru"):
    """Пустое значение = «по умолчанию Codex» (ключ убирается из config.toml). → (ok, сообщение)."""
    if not _SLOT_RE.match(slot or "") or slot not in profile_slots():
        return False, _t(lang, "Неизвестный аккаунт.", "Unknown account.")
    model, effort, fast = (model or "").strip(), (effort or "").strip(), bool(fast)
    with _slot_lock(slot):
        with _lock:
            models = (_cache.get(slot) or {}).get("data", {}).get("models") or []
        if not models:
            models = fetch_account(bin_path, slot).get("models") or []
        by_id = {m["id"]: m for m in models}
        if model and model not in by_id:
            return False, _t(lang, "Такой модели у этого аккаунта нет.", "This account has no such model.")
        cur = by_id.get(model) or next((m for m in models if m["is_default"]), None) or {}
        if effort and cur.get("efforts") and effort not in cur["efforts"]:
            return False, _t(lang, "Эта модель не поддерживает такое усилие рассуждения.",
                             "This model does not support that reasoning effort.")
        tier = None
        if fast:
            tier = cur.get("fast")
            if not tier:
                return False, _t(lang, "Режим Fast для этой модели недоступен.", "Fast mode is not available for this model.")
        home = profile_dir(slot)
        try:
            with AppServer(bin_path, home) as c:
                for key, val in (("model", model or None), ("model_reasoning_effort", effort or None), ("service_tier", tier)):
                    c.request("config/value/write", {"keyPath": key, "value": val, "mergeStrategy": "replace"})
        except Exception as e:
            return False, _t(lang, f"Не удалось записать настройки: {e}", f"Could not write the settings: {e}")
        with _lock:
            _cache.pop(slot, None)
    return True, _t(lang, "✅ Настройки записаны.", "✅ Settings saved.")


# ---------------------------------------------------------------- удаление
def delete_account(bin_path, slot, confirm, lang="ru"):
    """Стирает профиль с токеном. Слово подтверждения проверяет сервер сам, как при удалении Claude."""
    if (confirm or "").strip().lower() not in DELETE_WORDS:
        return False, _t(lang, "Слово подтверждения введено неверно — ничего не удалено.",
                         "The confirmation word is wrong — nothing was deleted.")
    if not _SLOT_RE.match(slot or "") or slot not in profile_slots():
        return False, _t(lang, "Неизвестный аккаунт.", "Unknown account.")
    pdir = profile_dir(slot)
    if os.path.islink(pdir):
        return False, _t(lang, "Профиль — символическая ссылка, удалять не буду.",
                         "The profile is a symbolic link — refusing to delete it.")
    with _lock:
        _login_drop(slot)
    if bin_path:  # отозвать токен на стороне OpenAI; не вышло — не мешает удалению
        try:
            argv, env = wrap([bin_path, "logout"], pdir)
            subprocess.run(argv, env=env, cwd=pdir, timeout=20,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    try:
        shutil.rmtree(pdir)
    except OSError as e:
        return False, _t(lang, f"Не удалось стереть профиль: {e}", f"Could not wipe the profile: {e}")
    with _lock:
        _cache.pop(slot, None)
    return True, _t(lang, "Аккаунт ChatGPT удалён.", "ChatGPT account deleted.")
