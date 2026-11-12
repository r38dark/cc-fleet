"""Quota gate for the lightweight remote companion. No account tokens leave this host.

Synchronous hooks wait BEFORE a tool or prompt is admitted. An in-flight tool is
allowed to finish; the pending call continues in the same process after reset.
The gate is independent of automatic transfers and does not kill the session.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime

BASE = Path(__file__).resolve().parent
NAME = re.sub(r"[^A-Za-z0-9_-]", "", os.environ.get("CC_REMOTE_TMUX", "ccfleet")) or "ccfleet"
POLICY = BASE / ("limits-" + NAME + ".json")
CACHE = BASE / ("limits-" + NAME + "-usage.json")
SETTINGS = BASE / ("limits-" + NAME + "-settings.json")
VERSION = 1
RESET_GRACE = 60


def load(path):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path, value):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def row_only(row):
    """Keep quota metadata, never credentials, email or transcript text."""
    out = {k: row[k] for k in ("ts", "error", "online") if k in row}
    for k in ("five_hour", "seven_day"):
        w = row.get(k) or {}
        out[k] = {n: w[n] for n in ("pct", "resets_at") if n in w}
    return out


def reset_at(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0


def budget(policy, row, now=None):
    now = time.time() if now is None else now
    reasons, until = [], []
    if not policy.get("enabled"):
        return dict(blocked=False, reasons=[], resume_at=0)
    for key, name, threshold in (
        ("five_hour", "5 ч", 100 if policy.get('override') else float(policy.get("threshold", 90))),
        ("seven_day", "неделя", float(policy.get("weekly_cap", 99)) if policy.get("weekly_pause") and not policy.get('override') else 100),
    ):
        win = row.get(key) or {}
        pct = win.get("pct")
        if not isinstance(pct, (int, float)) or pct < threshold:
            continue
        reset = reset_at(win.get("resets_at"))
        # Old percentages must never hold an already reset window, including
        # the token-expired case: Claude refreshes its token when it resumes.
        if reset and now >= reset + RESET_GRACE:
            continue
        reasons.append("%s: %s%% (порог %s%%)" % (name, round(pct), round(threshold)))
        until.append(reset + RESET_GRACE if reset else 0)
    return dict(blocked=bool(reasons), reasons=reasons,
                resume_at=max(until) if until and all(until) else 0)


def effective_row(policy):
    cached = load(CACHE)
    row = policy.get("row") or {}
    return cached if float(cached.get("ts") or 0) > float(row.get("ts") or 0) else row


def quota(policy, refresh=True):
    """Bound API polling across concurrent hooks; a read failure retains known data."""
    row = effective_row(policy)
    if not refresh or not policy.get("enabled"):
        return row
    near = any(float((row.get(k) or {}).get("pct") or 0) >= 80 for k in ("five_hour", "seven_day"))
    interval = 30 if near else 120
    with open(str(CACHE) + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        row = effective_row(policy)
        checked = max(float(row.get("ts") or 0), float(load(str(CACHE) + ".check").get("ts") or 0))
        if time.time() - checked < interval:
            return row
        save(Path(str(CACHE) + ".check"), {"ts": time.time()})
        try:
            result = subprocess.run([sys.executable, str(BASE / "usage.py")], capture_output=True,
                                    text=True, timeout=12)
            data = json.loads(result.stdout.strip().splitlines()[-1])
            if result.returncode == 0 and data.get("ok"):
                row = row_only(dict(data, ts=time.time(), error="", online=True))
                save(CACHE, row)
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            pass
    return row


def install(policy):
    policy = {k: policy[k] for k in ("enabled", "threshold", "weekly_cap", "weekly_pause", "override") if k in policy}
    save(POLICY, policy)
    command = "CC_REMOTE_TMUX=%s %s %s hook" % (shlex.quote(NAME), shlex.quote(sys.executable),
                                               shlex.quote(str(BASE / "remote_guard.py")))
    # A weekly pause can last seven days. Failure must block rather than silently
    # admitting a call when an enforcing hook is canceled by its timeout.
    handler = dict(type="command", command=command, timeout=8 * 86400,
                   onFailure="block", statusMessage="Пауза по лимитам Claude")
    save(SETTINGS, {"hooks": {
        "PreToolUse": [{"matcher": "*", "hooks": [handler]}],
        "UserPromptSubmit": [{"hooks": [handler]}],
    }})
    return dict(ok=True, version=VERSION)


def configure(policy):
    row = row_only(policy.get("row") or {})
    result = install(policy)
    if row.get("ts") and not row.get("error") and row.get("online", True):
        old = load(CACHE)
        if float(row["ts"]) >= float(old.get("ts") or 0):
            save(CACHE, row)
    return result


def waiters():
    count = 0
    for path in BASE.glob("limits-" + NAME + "-wait-*.json"):
        d = load(path)
        try:
            if d.get("identity") and int(d.get("pid") or 0) > 0 and process_id(int(d.get("pid") or 0)) == d.get("identity"):
                count += 1
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass
    return count


def process_id(pid):
    try:
        text = Path("/proc/%d/stat" % pid).read_text()
        return text[text.rfind(")") + 2:].split()[19]
    except (OSError, IndexError):
        return None


def status():
    policy = load(POLICY)
    state = budget(policy, effective_row(policy))
    state.update(version=VERSION, configured=POLICY.exists(), enabled=bool(policy.get("enabled")),
                 waiting=waiters())
    return state


def hook(data):
    if data.get("hook_event_name") not in ("PreToolUse", "UserPromptSubmit"):
        return
    marker = BASE / ("limits-" + NAME + "-wait-%d.json" % os.getpid())
    try:
        while True:
            policy = load(POLICY)
            if not budget(policy, quota(policy))["blocked"]:
                return
            if not marker.exists():
                save(marker, dict(pid=os.getpid(), identity=process_id(os.getpid()), since=time.time(),
                                  event=data.get("hook_event_name")))
            time.sleep(2)
    finally:
        marker.unlink(missing_ok=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["hook"]:
        try:
            hook(json.load(sys.stdin))
        except Exception:
            # An enforcing hook must not accidentally allow work on an IO error.
            print("Не удалось проверить паузу по лимитам Claude", file=sys.stderr)
            sys.exit(2)
