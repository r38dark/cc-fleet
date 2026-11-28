"""Antigravity CLI (agy) discovery, quota/usage polling, models catalog, and metadata."""
import datetime as dt
import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import threading
import time
import uuid
from pathlib import Path

try:
    import pyte
except ImportError:
    pyte = None

BASE = "/opt/cc-limits"
BRAIN_DIR = Path("/root/.gemini/antigravity-cli/brain")
SETTINGS_PATH = Path("/root/.gemini/antigravity-cli/settings.json")
JETSKI_STATE_PATH = Path("/root/.gemini/antigravity-cli/jetski_state.pbtxt")
GEMINI_MD_PATH = Path("/root/.gemini/config/GEMINI.md")
DEFAULT_BIN = "/root/.local/bin/agy"
DEFAULT_SUB_UNTIL = ""
SLOT = "agy1"

TELEGRAM_GUIDELINES_MARKER = "# Telegram Media & Formatting Guidelines"
TELEGRAM_GUIDELINES_BLOCK = (
    "# Telegram Media & Formatting Guidelines\n\n"
    "- **Входящие картинки и файлы из Telegram**: когда Telegram-мост присылает путь к сохранённому изображению или файлу в `/opt/cc-limits/agy_inbox/`, обязательно открой его инструментом `read_file` по указанному абсолютному пути.\n"
    "- **Отправка картинок в Telegram**: чтобы отправить пользователю картинку (скриншот, график, сгенерированное изображение), сохрани её как PNG/JPEG и вставь в финальный ответ **отдельной строкой** (не внутри блока кода):\n"
    "  `![описание](/абсолютный/путь/к/файлу.png)`\n"
    "  Telegram-мост автоматически вырежет эту строку и отправит изображение как фото (с превью, не документом).\n"
    "- **Оформление ответов**: используй понятные абзацы, короткие списки и аккуратные иконки статусов (`✅`, `⚠️`, `❌`, `📌`, `🛠`), без лишней стены текста.\n"
)

INFO_TTL = 90.0
MODELS_TTL = 600.0

_lock = threading.Lock()
_probe_lock = threading.Lock()
_cache = {"data": None, "ts": 0.0}
_models_cache = {"models": None, "ts": 0.0}


def jload(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def jsave(path, value, mode=0o600):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix="." + p.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, str(p))
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def find_bin(configured=""):
    candidates = [
        str(configured or "").strip(),
        os.environ.get("AGY_BIN", "").strip(),
        DEFAULT_BIN,
        shutil.which("agy") or "",
    ]
    for cand in candidates:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return ""


def meta_path():
    return os.path.join(BASE, "agy_meta.json")


def load_meta():
    data = jload(meta_path(), {}) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("slot", SLOT)
    data.setdefault("label", "Antigravity")
    data.setdefault("sub_until", DEFAULT_SUB_UNTIL)
    data.setdefault("model", "")
    data.setdefault("effort", "")
    return data


def save_meta(updates):
    with _lock:
        data = load_meta()
        for k, v in (updates or {}).items():
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v
        jsave(meta_path(), data, mode=0o600)
        return dict(data)


def parse_sub_date(raw):
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def normalize_sub_until(raw):
    if raw is None or str(raw).strip() == "":
        return ""
    parsed = parse_sub_date(raw)
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%d")


def _parse_refresh_delta(raw):
    if not raw:
        return None
    d = h = m = 0
    dm = re.search(r"(\d+)\s*d", raw)
    hm = re.search(r"(\d+)\s*h", raw)
    mm = re.search(r"(\d+)\s*m", raw)
    if not (dm or hm or mm):
        return None
    if dm:
        d = int(dm.group(1))
    if hm:
        h = int(hm.group(1))
    if mm:
        m = int(mm.group(1))
    return dt.timedelta(days=d, hours=h, minutes=m)


def _refresh_to_iso(raw, fetched_at):
    if not raw or "quota available" in raw.lower():
        return None
    delta = _parse_refresh_delta(raw)
    if delta is None:
        return None
    target = dt.datetime.fromtimestamp(fetched_at, tz=dt.timezone.utc) + delta
    return target.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_usage_text(text, fetched_at=None):
    """Parse rendered `agy /usage` screen text into normalized Gemini account quota."""
    now = time.time() if fetched_at is None else float(fetched_at)
    email = ""
    plan = "pro"
    plan_label = "PRO"
    m_email = re.search(
        r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\s*\(([^)]+)\)",
        text,
    )
    if m_email:
        email = m_email.group(1).strip()
        pfull = m_email.group(2).strip()
        low = pfull.lower()
        if "ultra" in low:
            plan, plan_label = "ultra", "ULTRA"
        elif "pro" in low:
            plan, plan_label = "pro", "PRO"
        elif "plus" in low:
            plan, plan_label = "plus", "PLUS"
        elif "free" in low:
            plan, plan_label = "free", "FREE"
        else:
            plan, plan_label = low[:16], pfull.upper()[:12]
    else:
        m_bare = re.search(
            r"(?:Account:\s*)?([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})",
            text,
        )
        if m_bare:
            email = m_bare.group(1).strip()

    flat = re.sub(r"[ \t]+", " ", text)
    idx_gem = flat.find("GEMINI MODELS")
    idx_cg = flat.find("CLAUDE AND GPT MODELS")
    gem_sec = ""
    if idx_gem != -1:
        gem_sec = flat[idx_gem:idx_cg] if idx_cg != -1 and idx_cg > idx_gem else flat[idx_gem:]

    windows = []

    f_match = re.search(
        r"Five\s+Hour\s+Limit\s+Remaining.*?(\d+(?:\.\d+)?)%\s*(?:.*?)(Refreshes\s+in\s+[0-9dhm\s]+|Quota\s+available)",
        gem_sec,
        re.DOTALL | re.IGNORECASE,
    )
    if f_match:
        rem = float(f_match.group(1))
        used = round(max(0.0, min(100.0, 100.0 - rem)), 1)
        ref = re.sub(r"\s+", " ", f_match.group(2)).strip()
        windows.append({
            "mins": 300,
            "pct": used,
            "remaining_pct": round(rem, 2),
            "resets_at": _refresh_to_iso(ref, now),
            "refresh_raw": ref,
        })

    w_match = re.search(
        r"Weekly\s+Limit\s+Remaining.*?(\d+(?:\.\d+)?)%\s*(?:.*?)(Refreshes\s+in\s+[0-9dhm\s]+|Quota\s+available)",
        gem_sec,
        re.DOTALL | re.IGNORECASE,
    )
    if w_match:
        rem = float(w_match.group(1))
        used = round(max(0.0, min(100.0, 100.0 - rem)), 1)
        ref = re.sub(r"\s+", " ", w_match.group(2)).strip()
        windows.append({
            "mins": 10080,
            "pct": used,
            "remaining_pct": round(rem, 2),
            "resets_at": _refresh_to_iso(ref, now),
            "refresh_raw": ref,
        })

    login_required = "currently not signed in" in flat.lower() and not email and not windows
    return {
        "email": email,
        "plan": plan,
        "plan_label": plan_label,
        "windows": windows,
        "login_required": login_required,
        "ts": now,
    }


def cli_default_model():
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("model"):
            return str(data["model"])
    except (OSError, ValueError):
        pass
    return ""


def fetch_models(binary, force=False):
    """Fetch available models via `agy models` with 10-min cache."""
    with _lock:
        if not force and _models_cache["models"] is not None and (time.time() - _models_cache["ts"]) < MODELS_TTL:
            return list(_models_cache["models"])
    if not binary:
        return []
    try:
        res = subprocess.run(
            [binary, "models"],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        raw = res.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return list(_models_cache["models"] or [])

    clean = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\r", "\n", raw)
    default_name = cli_default_model().lower()
    models = []
    for line in clean.splitlines():
        line = line.strip()
        if not line or "fetching available models" in line.lower():
            continue
        m = re.match(r"^([a-z0-9][a-z0-9._\-]{2,})\s{2,}(.+)$", line)
        if not m:
            continue
        mid, name = m.group(1).strip(), m.group(2).strip()
        # Only Gemini / Orchestrator models for Antigravity statistics & primary picker
        if not (mid.startswith("gemini-") or mid.startswith("claude-") or mid.startswith("gpt-")):
            continue
        models.append({
            "id": mid,
            "name": name,
            "efforts": ["low", "medium", "high", "xhigh"],
            "default_effort": "high",
            "is_default": bool(default_name and default_name == name.lower()),
        })
    if models:
        with _lock:
            _models_cache["models"] = models
            _models_cache["ts"] = time.time()
    return list(models or _models_cache["models"] or [])


def cached_models():
    with _lock:
        return list(_models_cache["models"]) if _models_cache["models"] is not None else None


def probe_usage(binary, timeout_sec=20.0):
    """Run an isolated PTY `/usage` probe against `agy` and parse live Gemini quotas."""
    if not binary:
        return {"error": "Antigravity CLI (agy) не установлен.", "windows": [], "ts": time.time()}
    if pyte is None:
        return {"error": "pyte не установлен.", "windows": [], "ts": time.time()}
    try:
        ensure_bootstrap_config()
    except Exception:
        pass

    with _probe_lock:
        master_fd, slave_fd = pty.openpty()
        cols, rows = 120, 55
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        env["LANG"] = "en_US.UTF-8"
        env["HOME"] = "/root"
        env["PATH"] = "/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

        proc = subprocess.Popen(
            [binary, "--dangerously-skip-permissions"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd="/root",
            env=env,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave_fd)

        scr = pyte.Screen(cols, rows)
        stream = pyte.ByteStream(scr)
        sent_usage = False
        header_text = ""
        usage_sent_at = 0.0
        deadline = time.time() + timeout_sec
        parsed = None

        try:
            while time.time() < deadline:
                rlist, _, _ = select.select([master_fd], [], [], 0.2)
                if rlist:
                    try:
                        chunk = os.read(master_fd, 16384)
                        if not chunk:
                            break
                        stream.feed(chunk)
                    except OSError:
                        break
                visible = "\n".join(line.rstrip() for line in scr.display)
                if not sent_usage:
                    if "for shortcuts" in visible:
                        header_text = visible
                        time.sleep(0.2)
                        os.write(master_fd, b"/usage\r")
                        sent_usage = True
                        usage_sent_at = time.time()
                    else:
                        step = _onboarding_action(visible)
                        if step:
                            for seq in step:
                                try:
                                    os.write(master_fd, seq)
                                except OSError:
                                    break
                                time.sleep(0.15)
                            time.sleep(0.35)
                else:
                    if (
                        "GEMINI MODELS" in visible
                        and "Weekly Limit Remaining" in visible
                        and "Five Hour Limit Remaining" in visible
                        and (time.time() - usage_sent_at) >= 0.4
                    ):
                        cand = parse_usage_text(header_text + "\n" + visible, time.time())
                        if len(cand["windows"]) >= 2:
                            parsed = cand
                            break
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass

        if parsed is None:
            visible = "\n".join(line.rstrip() for line in scr.display)
            parsed = parse_usage_text(header_text + "\n" + visible, time.time())
            if not parsed["windows"] and not parsed["login_required"]:
                parsed["error"] = "Не удалось прочитать квоты из /usage."
        return parsed


def fetch_account(binary, force=False):
    """Return normalized Antigravity account dict (with 90s cache & stale fallback)."""
    now = time.time()
    meta = load_meta()
    with _lock:
        if not force and _cache["data"] is not None and (now - _cache["ts"]) < INFO_TTL:
            row = dict(_cache["data"])
            row["email"] = row.get("email") or meta.get("email") or ""
            row["sub_until"] = meta.get("sub_until") or ""
            row["label"] = meta.get("label") or "Antigravity"
            row["model"] = meta.get("model") or cli_default_model()
            row["effort"] = meta.get("effort") or ""
            return row

    probed = probe_usage(binary) if binary else {"error": "Antigravity CLI не найден.", "windows": [], "ts": now}
    models = cached_models()
    if models is None and binary:
        models = fetch_models(binary, force=False)

    if probed.get("error") and not probed.get("windows"):
        with _lock:
            prev = dict(_cache["data"]) if _cache["data"] else None
        if prev and prev.get("windows"):
            prev["stale"] = True
            prev["error"] = probed["error"]
            prev["sub_until"] = meta.get("sub_until") or ""
            prev["label"] = meta.get("label") or "Antigravity"
            prev["model"] = meta.get("model") or cli_default_model()
            prev["effort"] = meta.get("effort") or ""
            return prev

    row = {
        "slot": SLOT,
        "label": meta.get("label") or "Antigravity",
        "email": probed.get("email") or meta.get("email") or "",
        "plan": probed.get("plan") or meta.get("plan") or "pro",
        "plan_label": probed.get("plan_label") or "PRO",
        "sub_until": meta.get("sub_until") or "",
        "windows": probed.get("windows") or [],
        "reached": any((w.get("pct") or 0) >= 100 for w in (probed.get("windows") or [])),
        "usage_allowed": not any((w.get("pct") or 0) >= 100 for w in (probed.get("windows") or [])),
        "models": models or [],
        "model": meta.get("model") or cli_default_model(),
        "effort": meta.get("effort") or "",
        "login_required": bool(probed.get("login_required")),
        "error": probed.get("error") or "",
        "stale": False,
        "ts": probed.get("ts") or now,
    }
    if row["email"] and row["email"] != meta.get("email"):
        save_meta({"email": row["email"], "plan": row["plan"]})
    if row["windows"]:
        with _lock:
            _cache["data"] = dict(row)
            _cache["ts"] = now
    return row


def get_accounts(binary, force=False):
    if not binary:
        return []
    return [fetch_account(binary, force=force)]


def profile_slots(binary=None):
    b = binary if binary is not None else find_bin()
    return [SLOT] if b else []


def get_context_stats(conv_id):
    stats = {
        "conv_id": conv_id or "",
        "turns": 0,
        "steps": 0,
        "context_tokens": 0,
        "input_tokens": 0,
        "cache_read_tokens": 0,
        "output_tokens": 0,
        "model": "",
    }
    if not conv_id:
        return stats
    tpath = BRAIN_DIR / str(conv_id) / ".system_generated" / "logs" / "transcript.jsonl"
    if not tpath.is_file():
        return stats
    try:
        with tpath.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(ev, dict):
                    continue
                stats["steps"] += 1
                if ev.get("type") == "USER_INPUT":
                    stats["turns"] += 1
                elif ev.get("type") == "PLANNER_RESPONSE":
                    inp = int(ev.get("input_tokens") or 0)
                    cr = int(ev.get("cache_read_tokens") or 0)
                    out_t = int(ev.get("output_tokens") or 0)
                    if inp + cr > 0:
                        stats["input_tokens"] = inp
                        stats["cache_read_tokens"] = cr
                        stats["output_tokens"] = out_t
                        stats["context_tokens"] = inp + cr
                    if ev.get("model"):
                        stats["model"] = str(ev["model"])
    except OSError:
        pass
    return stats


def set_prefs(model=None, effort=None, sub_until=None, label=None):
    updates = {}
    if model is not None:
        m = str(model).strip()
        updates["model"] = "" if m.lower() in ("default", "reset") else m
    if effort is not None:
        e = str(effort).strip().lower()
        if e in ("", "default", "reset"):
            updates["effort"] = ""
        elif e in ("low", "medium", "high", "xhigh", "max"):
            updates["effort"] = e
        else:
            return False, "Уровень effort должен быть: low, medium, high, xhigh, max или default."
    if sub_until is not None:
        norm = normalize_sub_until(sub_until)
        if norm is None:
            return False, "Неверный формат даты подписки. Используйте ДД.ММ.ГГГГ или ГГГГ-ММ-ДД."
        updates["sub_until"] = norm
    if label is not None:
        updates["label"] = str(label).strip()[:40] or "Antigravity"
    save_meta(updates)
    return True, "Настройки Antigravity сохранены."


# ---------- Auto-bootstrap (full access, skip onboarding, GEMINI.md formatting rules) ----------

def _onboarding_action(visible_text):
    """Return sequence of bytes to advance an interactive agy first-run onboarding screen, or None."""
    if not visible_text or "for shortcuts" in visible_text:
        return None
    low = visible_text.lower()
    if "select login method" in low or "authorization code" in low:
        return None
    if "[done]" in low or "[next]" in low or "terms of service" in low or "select a theme" in low or "choose a theme" in low:
        # Right arrow moves focus from [Previous] to [Next]/[Done] (no-op if already rightmost), then Enter confirms.
        return (b"\x1b[C", b"\r")
    if "trust this workspace" in low or "do you trust" in low:
        return (b"\r",)
    return None


def ensure_bootstrap_config(workdir="/root", force_full_access=True):
    """Pre-configure agy for headless cc-fleet operation:
    1. settings.json: full access (always-proceed, allowNonWorkspaceAccess, trustedWorkspaces, quiet tips).
    2. jetski_state.pbtxt: mark post-onboarding steps completed so first-run wizard is skipped.
    3. ~/.gemini/config/GEMINI.md: install Telegram media & concise formatting guidelines (preserving user rules).
    """
    changed = []
    # 1. settings.json
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    cur = jload(str(SETTINGS_PATH), {})
    if not isinstance(cur, dict):
        cur = {}
    before = json.dumps(cur, sort_keys=True)
    if force_full_access:
        cur["allowNonWorkspaceAccess"] = True
        cur["toolPermission"] = "always-proceed"
        cur["artifactReviewPolicy"] = "always-proceed"
    else:
        cur.setdefault("allowNonWorkspaceAccess", True)
        cur.setdefault("toolPermission", "always-proceed")
        cur.setdefault("artifactReviewPolicy", "always-proceed")
    cur.setdefault("showTips", False)
    cur.setdefault("showFeedbackSurvey", False)
    trusted = [str(x) for x in (cur.get("trustedWorkspaces") or []) if x]
    for cand in ("/root", str(workdir or "").strip(), BASE):
        if cand and os.path.isdir(cand) and cand not in trusted:
            trusted.append(cand)
    if not trusted:
        trusted = ["/root"]
    cur["trustedWorkspaces"] = trusted
    if json.dumps(cur, sort_keys=True) != before:
        jsave(str(SETTINGS_PATH), cur, mode=0o600)
        changed.append("settings.json")

    # 2. jetski_state.pbtxt (skip first-run onboarding wizard)
    JETSKI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    pb_text = ""
    try:
        if JETSKI_STATE_PATH.is_file():
            pb_text = JETSKI_STATE_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pb_text = ""
    if "POST_ONBOARDING_STEP_TYPE_ADD_WORKSPACE" not in pb_text:
        m_uuid = re.search(r'installation_uuid:\s*"([^"]+)"', pb_text)
        inst_uuid = m_uuid.group(1) if m_uuid else str(uuid.uuid4())
        new_pb = (
            "post_onboarding: {\n"
            "  completed_steps: POST_ONBOARDING_STEP_TYPE_MANAGER_WELCOME\n"
            "  completed_steps: POST_ONBOARDING_STEP_TYPE_USAGE_MODE\n"
            "  completed_steps: POST_ONBOARDING_STEP_TYPE_AGENT_CONFIGURATION\n"
            "  completed_steps: POST_ONBOARDING_STEP_TYPE_ADD_WORKSPACE\n"
            "}\n"
            f'installation_uuid: "{inst_uuid}"\n'
            "migrations: {\n  key: 3\n  value: MIGRATION_STATUS_COMPLETED\n}\n"
            "migrations: {\n  key: 4\n  value: MIGRATION_STATUS_COMPLETED\n}\n"
            "migrations: {\n  key: 5\n  value: MIGRATION_STATUS_COMPLETED\n}\n"
            "migrations: {\n  key: 11\n  value: MIGRATION_STATUS_COMPLETED\n}\n"
        )
        JETSKI_STATE_PATH.write_text(new_pb, encoding="utf-8")
        try:
            os.chmod(str(JETSKI_STATE_PATH), 0o600)
        except OSError:
            pass
        changed.append("jetski_state.pbtxt")

    # 3. ~/.gemini/config/GEMINI.md (formatting & Telegram media rules)
    GEMINI_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing_md = ""
    try:
        if GEMINI_MD_PATH.is_file():
            existing_md = GEMINI_MD_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        existing_md = ""
    if TELEGRAM_GUIDELINES_MARKER not in existing_md:
        sep = "\n\n" if existing_md.strip() else ""
        GEMINI_MD_PATH.write_text(existing_md.rstrip() + sep + TELEGRAM_GUIDELINES_BLOCK, encoding="utf-8")
        changed.append("GEMINI.md")

    return True, changed


# ---------- One-click CLI installer & interactive browser Google OAuth login ----------

INSTALL_SCRIPT_URL = "https://antigravity.google/cli/install.sh"
OAUTH_TOKEN_PATH = Path("/root/.gemini/antigravity-cli/antigravity-oauth-token")

_inst_lock = threading.Lock()
_inst = {
    "state": "idle",   # idle | running | done | error
    "message": "",
    "log": [],
    "proc": None,
    "started": 0.0,
}

_login_lock = threading.Lock()
_login = {
    "state": "idle",   # idle | starting | url | verifying | done | error
    "url": "",
    "message": "",
    "proc": None,
    "master_fd": None,
    "started": 0.0,
    "code_sent": False,
}


def _extract_oauth_url(text):
    """Extract Google OAuth URL from PTY screen text even if wrapped across lines."""
    if not text:
        return ""
    lines = [l.strip() for l in text.splitlines()]
    buf = []
    capturing = False
    for line in lines:
        if not capturing:
            m = re.search(r"(https://accounts\.google\.com/o/oauth2/auth\S*)", line)
            if m:
                buf.append(m.group(1))
                capturing = True
        else:
            if not line or line.lower().startswith("if you ") or line.lower().startswith("authorization ") or " " in line:
                break
            buf.append(line)
    url = "".join(buf).strip()
    if url.startswith("https://accounts.google.com/o/oauth2/auth") and "client_id=" in url:
        return url
    m2 = re.search(r"https://accounts\.google\.com/o/oauth2/auth\S+", text)
    return m2.group(0) if m2 else ""


def install_status():
    b = find_bin()
    with _inst_lock:
        st = _inst["state"]
        if b and st == "idle":
            st = "installed"
        return {
            "ok": True,
            "installed": bool(b),
            "bin": b,
            "state": st,
            "message": _inst["message"],
            "log": list(_inst["log"][-25:]),
        }


def install_cancel():
    with _inst_lock:
        proc = _inst.get("proc")
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                pass
        _inst["proc"] = None
        _inst["state"] = "idle"
        _inst["message"] = "Установка отменена."
    return True, "Установка отменена."


def install_start():
    if find_bin():
        return True, "Antigravity CLI уже установлен."
    with _inst_lock:
        if _inst["state"] == "running":
            return True, "Установка уже выполняется."
        _inst["state"] = "running"
        _inst["message"] = "Скачиваю и устанавливаю Antigravity CLI (agy)…"
        _inst["log"] = []
        _inst["started"] = time.time()

    def _run():
        env = dict(os.environ)
        env["HOME"] = "/root"
        env["PATH"] = "/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        cmd = ["bash", "-c", f"curl -fsSL {INSTALL_SCRIPT_URL} | bash"]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                start_new_session=True,
            )
            with _inst_lock:
                _inst["proc"] = proc
            for line in proc.stdout or []:
                clean = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", line).strip()
                if clean:
                    with _inst_lock:
                        _inst["log"].append(clean[-200:])
                        _inst["log"] = _inst["log"][-40:]
            rc = proc.wait(timeout=300)
            b = find_bin()
            if rc == 0 and b:
                try:
                    ensure_bootstrap_config()
                except Exception:
                    pass
            with _inst_lock:
                _inst["proc"] = None
                if rc == 0 and b:
                    _inst["state"] = "done"
                    _inst["message"] = f"Antigravity CLI установлен ({b}), полный доступ и стиль ответов настроены. Теперь войдите в Google-аккаунт."
                else:
                    _inst["state"] = "error"
                    _inst["message"] = f"Установка завершилась с кодом {rc}."
        except Exception as exc:
            with _inst_lock:
                _inst["proc"] = None
                _inst["state"] = "error"
                _inst["message"] = f"Ошибка установки: {exc}"

    threading.Thread(target=_run, daemon=True, name="agy-install").start()
    return True, "Установка Antigravity CLI запущена."


def _close_login_locked():
    fd = _login.get("master_fd")
    proc = _login.get("proc")
    _login["master_fd"] = None
    _login["proc"] = None
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    if proc is not None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass


def login_status():
    with _login_lock:
        return {
            "ok": True,
            "state": _login["state"],
            "url": _login["url"],
            "message": _login["message"],
            "signed_in": OAUTH_TOKEN_PATH.is_file(),
        }


def login_cancel():
    with _login_lock:
        _close_login_locked()
        _login["state"] = "idle"
        _login["url"] = ""
        _login["message"] = ""
        _login["code_sent"] = False
    return True, "Вход отменён."


def login_start():
    b = find_bin()
    if not b:
        return False, "Сначала установите Antigravity CLI (agy)."
    if pyte is None:
        return False, "Не установлен python3-pyte."

    with _login_lock:
        _close_login_locked()
        _login["state"] = "starting"
        _login["url"] = ""
        _login["message"] = "Запускаю вход через Google OAuth…"
        _login["started"] = time.time()
        _login["code_sent"] = False

    def _run():
        master_fd = None
        proc = None
        tok_backup = None
        try:
            try:
                ensure_bootstrap_config()
            except Exception:
                pass
            if OAUTH_TOKEN_PATH.is_file():
                tok_backup = OAUTH_TOKEN_PATH.with_suffix(".bak_relogin")
                try:
                    os.replace(str(OAUTH_TOKEN_PATH), str(tok_backup))
                except OSError:
                    tok_backup = None

            master_fd, slave_fd = pty.openpty()
            cols, rows = 420, 44
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            env = dict(os.environ)
            env["TERM"] = "xterm-256color"
            env["LANG"] = "en_US.UTF-8"
            env["HOME"] = "/root"
            env["BROWSER"] = "false"
            env.pop("DISPLAY", None)
            env["PATH"] = "/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

            proc = subprocess.Popen(
                [b],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd="/root",
                env=env,
                close_fds=True,
                start_new_session=True,
            )
            os.close(slave_fd)
            with _login_lock:
                _login["proc"] = proc
                _login["master_fd"] = master_fd

            scr = pyte.Screen(cols, rows)
            stream = pyte.ByteStream(scr)
            sent_method = False
            deadline = time.time() + 300.0
            while time.time() < deadline:
                with _login_lock:
                    if _login["proc"] is not proc:
                        break
                    code_sent = _login["code_sent"]
                rlist, _, _ = select.select([master_fd], [], [], 0.25)
                if rlist:
                    try:
                        chunk = os.read(master_fd, 16384)
                        if not chunk:
                            break
                        stream.feed(chunk)
                    except OSError:
                        break
                vis = "\n".join(line.rstrip() for line in scr.display)
                if not sent_method and "Select login method" in vis:
                    time.sleep(0.25)
                    try:
                        os.write(master_fd, b"\r")
                    except OSError:
                        break
                    sent_method = True
                    continue

                if not code_sent:
                    url = _extract_oauth_url(vis)
                    if url:
                        with _login_lock:
                            if _login["proc"] is proc and _login["state"] != "url":
                                _login["url"] = url
                                _login["state"] = "url"
                                _login["message"] = "Откройте ссылку, войдите в Google и вставьте полученный код ниже."
                else:
                    step = _onboarding_action(vis)
                    if step:
                        for seq in step:
                            try:
                                os.write(master_fd, seq)
                            except OSError:
                                break
                            time.sleep(0.15)
                        time.sleep(0.4)
                        continue
                    if "for shortcuts" in vis or (OAUTH_TOKEN_PATH.is_file() and (time.time() - _login["started"]) > 6 and not _onboarding_action(vis)):
                        if tok_backup and tok_backup.exists():
                            try:
                                tok_backup.unlink()
                            except OSError:
                                pass
                        try:
                            ensure_bootstrap_config()
                        except Exception:
                            pass
                        with _lock:
                            _cache["data"] = None
                            _cache["ts"] = 0.0
                        with _login_lock:
                            _close_login_locked()
                            _login["state"] = "done"
                            _login["url"] = ""
                            _login["message"] = "Вход в Google выполнен! Полный доступ и оформление настроены."
                        return
                    low = vis.lower()
                    if "invalid" in low and ("code" in low or "grant" in low or "token" in low):
                        with _login_lock:
                            _login["state"] = "error"
                            _login["message"] = "Код не принят или устарел. Получите ссылку заново."
                        break

            if tok_backup and tok_backup.exists() and not OAUTH_TOKEN_PATH.is_file():
                try:
                    os.replace(str(tok_backup), str(OAUTH_TOKEN_PATH))
                except OSError:
                    pass
            with _login_lock:
                if _login["proc"] is proc:
                    _close_login_locked()
                    if _login["state"] not in ("done", "error", "idle"):
                        _login["state"] = "error"
                        _login["message"] = "Время ожидания входа истекло. Попробуйте ещё раз."
        except Exception as exc:
            if tok_backup and tok_backup.exists() and not OAUTH_TOKEN_PATH.is_file():
                try:
                    os.replace(str(tok_backup), str(OAUTH_TOKEN_PATH))
                except OSError:
                    pass
            with _login_lock:
                _close_login_locked()
                _login["state"] = "error"
                _login["message"] = f"Ошибка входа: {exc}"

    threading.Thread(target=_run, daemon=True, name="agy-login").start()
    return True, "Запускаю получение ссылки Google OAuth…"


def login_submit(code):
    val = re.sub(r"[\r\n\t]+", "", str(code or "")).strip()
    if not val:
        return False, "Вставьте код авторизации."
    with _login_lock:
        fd = _login.get("master_fd")
        if fd is None or _login["state"] not in ("url", "verifying"):
            return False, "Сессия входа не активна. Нажмите «Получить ссылку» заново."
        try:
            os.write(fd, (val + "\r").encode("utf-8"))
        except OSError as exc:
            return False, f"Не удалось передать код: {exc}"
        _login["code_sent"] = True
        _login["state"] = "verifying"
        _login["message"] = "Проверяю код авторизации…"
    return True, "Код отправлен, проверяю…"
