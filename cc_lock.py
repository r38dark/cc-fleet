# Запись живого логина Claude Code (~/.claude/.credentials.json, ~/.claude.json) без гонок:
# те же замки, что берёт сам Claude Code, атомарная запись и откат первой записи, если
# не удалась вторая. Только стандартная библиотека; используют cc_limits.py и cc-switch.
#
# Замки Claude Code (2.1.x) — каталоги-мьютексы в стиле proper-lockfile: mkdir занимает,
# rmdir отпускает, держащий раз в несколько секунд обновляет mtime каталога, замок старше
# stale секунд считается брошенным.
#   <claude_dir>/.oauth_refresh.lock   stale 60 с — обновление OAuth-токена и запись credentials
#   <home>/.claude.lock                прежний (legacy) путь того же замка — берём оба, как CLI
#   <home>/.claude.json.lock           stale 10 с — чтение-правка-запись ~/.claude.json
# Не взяли замок за timeout — LockTimeout, ничего не записано: вызывающий повторит позже.
import contextlib
import json
import os
import threading
import time

OAUTH_STALE = 60     # с — как у Claude Code
CONFIG_STALE = 10    # с — как у Claude Code для .claude.json
TOUCH_EVERY = 3      # с — обновляем mtime держимого замка (должно быть заметно меньше stale/2)
TIMEOUT = float(os.environ.get("CC_LOCK_TIMEOUT", 9))  # с — сколько ждём чужой замок (env — для тестов)
POLL = 0.1           # с — шаг ожидания


class LockTimeout(Exception):
    pass


def atomic_write(path, data, mode=0o600):
    """Запись через временный файл рядом + fsync + rename: читатель видит либо старое, либо новое
    содержимое целиком, а не обрезанный файл. Имя временного файла уникально (pid + поток) —
    два писателя не сталкиваются на общем .tmp. data — str или bytes."""
    raw = data.encode() if isinstance(data, str) else data
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            os.write(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class DirLock:
    """Замок-каталог. `with DirLock(path, stale=60):` — взять, держать (touch в фоне), отпустить."""

    def __init__(self, path, stale, timeout=TIMEOUT, touch_every=TOUCH_EVERY):
        self.path, self.stale, self.timeout, self.touch_every = path, stale, timeout, touch_every
        self._stop = threading.Event()
        self._thr = None
        self.held = False

    def _is_stale(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return None  # каталога уже нет — можно занимать
        return (time.time() - st.st_mtime) > self.stale, st.st_mtime

    def _break_stale(self, seen_mtime):
        # Повторно смотрим mtime прямо перед удалением: если замок за это время обновили — он живой
        try:
            if os.stat(self.path).st_mtime != seen_mtime:
                return
            for f in os.listdir(self.path):  # у Claude Code внутри бывает файл владельца
                try:
                    os.unlink(os.path.join(self.path, f))
                except OSError:
                    pass
            os.rmdir(self.path)
        except OSError:
            pass

    def acquire(self):
        deadline = time.time() + self.timeout
        while True:
            try:
                os.mkdir(self.path, 0o700)
                break
            except FileExistsError:
                s = self._is_stale()
                if s and s[0]:
                    self._break_stale(s[1])
                    continue
            except FileNotFoundError:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                continue
            if time.time() >= deadline:
                raise LockTimeout(f"замок занят: {self.path}")
            time.sleep(POLL)
        self.held = True
        self._stop.clear()
        self._thr = threading.Thread(target=self._touch, daemon=True)
        self._thr.start()
        return self

    def _touch(self):
        while not self._stop.wait(self.touch_every):
            try:
                os.utime(self.path)
            except OSError:
                return

    def release(self):
        if not self.held:
            return
        self.held = False
        self._stop.set()
        if self._thr:
            self._thr.join(timeout=1)
        try:
            os.rmdir(self.path)
        except OSError:
            pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


@contextlib.contextmanager
def oauth_lock(claude_dir, home, timeout=TIMEOUT):
    """Замок обновления OAuth-токена: сначала текущий путь Claude Code, затем прежний."""
    with DirLock(os.path.join(claude_dir, ".oauth_refresh.lock"), OAUTH_STALE, timeout):
        with DirLock(os.path.join(home, ".claude.lock"), OAUTH_STALE, timeout):
            yield


def config_lock(cfg_path, timeout=TIMEOUT):
    """Замок ~/.claude.json: чтение-правка-запись, чтобы не потерять чужую правку и не затереть свою."""
    return DirLock(cfg_path + ".lock", CONFIG_STALE, timeout)


def _file_mode(path, default):
    try:
        return os.stat(path).st_mode & 0o777
    except OSError:
        return default


def swap_live(creds_path, creds, cfg_path, oauth_account, claude_dir, home, timeout=TIMEOUT, before=None):
    """Подменить живой логин: credentials.json целиком + oauthAccount в ~/.claude.json.

    Оба замка Claude Code на время подмены. Если вторая запись (cfg) не удалась, первая
    (credentials) откатывается к прежнему содержимому — сессия не остаётся с токенами одного
    аккаунта и аккаунтом другого. creds — dict или готовый str/bytes с JSON; oauth_account=None — не трогать ~/.claude.json.
    before — функция без аргументов, выполняется под замком перед записью (cc-switch сохраняет
    в ней текущие токены в профиль: пока замок наш, CLI их не обновит между копией и подменой)."""
    raw = creds if isinstance(creds, (str, bytes)) else json.dumps(creds, indent=2, ensure_ascii=False)
    with oauth_lock(claude_dir, home, timeout):
        if before:
            before()
        try:
            with open(creds_path, "rb") as f:
                prev = f.read()
        except OSError:
            prev = None
        atomic_write(creds_path, raw, 0o600)
        if oauth_account is None:  # аккаунт в ~/.claude.json не меняется — вторая запись не нужна
            return
        try:
            with config_lock(cfg_path, timeout):
                with open(cfg_path) as f:
                    cfg = json.load(f)
                cfg["oauthAccount"] = oauth_account
                atomic_write(cfg_path, json.dumps(cfg, indent=2, ensure_ascii=False), _file_mode(cfg_path, 0o644))
        except BaseException:
            if prev is not None:
                atomic_write(creds_path, prev, 0o600)
            else:
                try:
                    os.unlink(creds_path)
                except OSError:
                    pass
            raise
