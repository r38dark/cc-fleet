"""Own-quota pause (SIGSTOP/SIGCONT) of the native Antigravity CLI process."""
import json
import os
import signal
import tempfile
import threading
import time
from pathlib import Path


def atomic(path, value):
    p = Path(path)
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=str(p.parent), prefix="." + p.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, str(p))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def identity(pid):
    try:
        fields = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()
        return dict(pid=int(pid), start=fields[19], state=fields[0])
    except (OSError, ValueError, TypeError, IndexError):
        return None


def same(row):
    current = identity(row.get("pid"))
    return bool(current and current["start"] == str(row.get("start")))


def processes(root):
    """Find agy / antigravity worker processes under screen root PID."""
    level = [str(root)]
    result = []
    seen = set()
    for _ in range(8):
        next_level = []
        for pid in level:
            if pid in seen:
                continue
            seen.add(pid)
            try:
                comm = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8", errors="ignore").strip().lower()
                if comm in ("agy", "antigravity", "node") or comm.startswith("agy"):
                    cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "ignore").lower()
                    if "agy" in cmdline or "antigravity" in cmdline:
                        row = identity(pid)
                        if row:
                            result.append(dict(pid=row["pid"], start=row["start"]))
                children_path = Path(f"/proc/{pid}/task/{pid}/children")
                if children_path.is_file():
                    next_level += children_path.read_text().split()
            except OSError:
                continue
        level = next_level
    return result


class Guard:
    """Freezes/resumes agy process cleanly on quota pause with grace and fail-safe fallback."""

    def __init__(self, base, limits, console, bridge):
        self.base = Path(base)
        self.limits = limits
        self.console = console
        self.bridge = bridge
        self.path = self.base / "agy_quota_runtime.json"
        self.marker = self.base / "profile_runtime/agy-quota-paused.json"
        self.grace = self.base / "profile_runtime/agy-quota-grace.json"
        self.state = read(self.path, {}) or {}
        self.lock = threading.RLock()
        self.finishing = False
        if self.state.get("notified") and self.bridge is not None:
            self.bridge.limit_held = (self.state.get("last_pause") or {}).get("resume_at") or True

    def fallback(self, value, override=False):
        previous = self.state.get("last_pause") or {}
        if previous.get("resume_at") and time.time() > previous["resume_at"] + 120:
            return dict(active=False, expired=True)
        if previous.get("active") and (not override or previous.get("hard")):
            return dict(previous, unknown=True)
        return value

    def _save(self):
        atomic(self.path, self.state)

    def _grace(self):
        value = read(self.grace, {}) or {}
        if not value:
            return False
        if self.console and self.console.busy() and str(self.console._pid()) == str(value.get("screen_pid")):
            return True
        self.grace.unlink(missing_ok=True)
        return False

    def tick(self):
        with self.lock:
            pause = self.limits.limit_pause()
            rows = [r for r in (read(self.marker, []) or []) if same(r)]
            was = bool(self.state.get("notified"))
            self.finishing = False

            if pause.get("active"):
                self.state["last_pause"] = {
                    k: v for k, v in pause.items() if k not in ("label", "resume_label", "accounts")
                }
                if self._grace():
                    self.finishing = True
                    self._save()
                    return
                if not rows and self.console and self.console._pid():
                    rows = processes(self.console._pid())
                if rows:
                    atomic(self.marker, rows)
                    for row in rows:
                        try:
                            if same(row):
                                os.kill(row["pid"], signal.SIGSTOP)
                        except ProcessLookupError:
                            pass
                self.state["notified"] = True
                self._save()
                if not was and self.bridge is not None and not getattr(self.bridge, "limit_held", None):
                    kind_txt = "достигнут лимит 100%" if pause.get("hard") else "достигнут порог лимита"
                    self.bridge._notice_async(
                        f"⏸ Antigravity: {kind_txt}. Работа приостановлена, беседа сохранена. "
                        "Новые сообщения копятся в очереди до сброса окна или отключения паузы."
                    )
                if self.bridge is not None:
                    self.bridge.limit_held = pause.get("resume_at") or True
                return

            if pause.get("unknown"):
                return

            for row in rows:
                try:
                    if same(row):
                        os.kill(row["pid"], signal.SIGCONT)
                except ProcessLookupError:
                    pass
            self.marker.unlink(missing_ok=True)
            self.grace.unlink(missing_ok=True)
            if self.state:
                self.state = {}
                self._save()
            if self.bridge is not None:
                self.bridge.limit_held = None
                if was:
                    self.bridge._notice_async(
                        "▶ Antigravity: пауза по лимитам снята. Работа и очередь продолжаются в той же беседе."
                    )

    def public(self):
        rows = read(self.marker, []) or []
        queued = len(self.bridge.inputs) if (self.bridge is not None and hasattr(self.bridge, "inputs")) else 0
        return dict(
            frozen=any(same(r) and (identity(r["pid"]) or {}).get("state") == "T" for r in rows),
            finishing_current=self.finishing,
            queued=queued,
        )
