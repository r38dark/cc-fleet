#!/usr/bin/env python3
# cc-fleet — автообновление из GitHub Releases (только стандартная библиотека).
#
# Что делает: раз в сутки спрашивает у GitHub, нет ли релиза новее установленного
# (один GET api.github.com без токена), показывает это в панели и — по кнопке или
# автоматически — скачивает архив релиза, проверяет его, подменяет файлы, перезапускает
# службу. Перед заменой делает бэкап; если новая версия не подтвердила запуск
# (CONFIRM_DELAY секунд живой работы), сторож в отдельном systemd-юните возвращает
# прежние файлы и перезапускает службу.
#
# Используется cc_limits.py как модуль, а сторож откат запускается как CLI:
#   python3 cc_update.py watchdog --base DIR --service NAME
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_REPO = "r38dark/cc-fleet"
DEFAULT_API = "https://api.github.com"
# откуда вообще разрешено качать (редиректы проверяются на каждом шаге)
GH_HOSTS = ("github.com", "api.github.com", "codeload.github.com")
GH_SUFFIX = ".githubusercontent.com"
# за пределы BASE пишем только сюда
ALLOWED_ABS_DST = ("/usr/local/bin/cc-switch",)
MAX_ARCHIVE = 30 * 1024 * 1024
MAX_UNPACKED = 80 * 1024 * 1024
MAX_FILES = 400
CHECK_EVERY = 86400          # проверка новой версии — раз в сутки
FIRST_CHECK_DELAY = 45       # после старта службы
RESTART_GRACE = 2            # секунд между «файлы заменены» и рестартом службы
MANUAL_CHECK_GAP = 20        # не чаще, чем раз в N секунд по кнопке
# env — только для изолированных тестов, в боевой установке значения фиксированные
CONFIRM_DELAY = int(os.environ.get("CC_UPDATE_CONFIRM_DELAY", 20))    # новый процесс подтверждает себя через столько секунд работы
ROLLBACK_AFTER = int(os.environ.get("CC_UPDATE_ROLLBACK_AFTER", 120))  # сторож ждёт подтверждения столько секунд после рестарта
KEEP_BACKUPS = 3
UA = "cc-fleet-updater/1"

STATE_NAME = "update_state.json"      # кэш проверки: etag, последний релиз, пропущенная версия
PENDING_NAME = "update_pending.json"  # маркер «идёт обновление» — снимает подтвердивший процесс
RESULT_NAME = "update_result.json"    # итог последнего обновления/отката
BACKUP_DIR = "update_backup"
TMP_DIR = ".update_tmp"

_file_lock = threading.Lock()


class UpdateError(Exception):
    """code — короткий ярлык причины: панель переводит его на язык интерфейса (текст — для логов и Telegram)."""
    def __init__(self, msg="", code="other"):
        super().__init__(msg)
        self.code = code


class NeedsInstall(UpdateError):
    """Релиз меняет то, что автообновление не трогает (служба, nginx, хуки)."""
    def __init__(self, msg=""):
        super().__init__(msg, "needs_install")


# ---------------------------------------------------------------- мелочи
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


def parse_ver(s):
    """'v1.18.0' / '1.18.0' → (1, 18, 0); всё остальное (пре-релизы, мусор) → None."""
    m = re.fullmatch(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})", (s or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def fmt_ver(t):
    return ".".join(str(x) for x in t)


def host_ok(url, api_base):
    """https и хост GitHub — либо тот же адрес, что api_base (нужен только стенду тестов)."""
    try:
        p = urllib.parse.urlparse(url)
        b = urllib.parse.urlparse(api_base)
    except Exception:
        return False
    if p.scheme == b.scheme and p.netloc == b.netloc:
        return True
    host = (p.hostname or "").lower()
    return p.scheme == "https" and (host in GH_HOSTS or host.endswith(GH_SUFFIX))


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, api_base):
        self.api_base = api_base

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_ok(newurl, self.api_base):
            raise UpdateError("редирект на недопустимый адрес: " + newurl[:80], "host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(api_base):
    return urllib.request.build_opener(_SafeRedirect(api_base))


# ---------------------------------------------------------------- проверка новой версии
def fetch_latest(repo, api_base, etag=None, timeout=15):
    """→ (status, release|None, etag). status: 200 | 304 | 404."""
    url = "%s/repos/%s/releases/latest" % (api_base.rstrip("/"), repo)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/vnd.github+json"})
    if etag:
        req.add_header("If-None-Match", etag)
    try:
        with _opener(api_base).open(req, timeout=timeout) as r:
            return 200, json.loads(r.read(2 * 1024 * 1024)), r.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, None, etag
        if e.code == 404:
            return 404, None, None
        raise UpdateError("GitHub ответил %s" % e.code, "net")


# тело релиза двуязычное: блоки «## English» и «## Русский» (старые релизы — без них, одним языком)
_NOTES_HEAD = re.compile(r"^#{1,3}[ \t]*(English|EN|Русский|Russian|RU)[ \t]*$", re.I | re.M)


def split_notes(body):
    """Тело релиза → {"notes_en": …, "notes_ru": …}. Нет таких заголовков — оба поля пустые,
    панель покажет тело как есть."""
    body = (body or "").replace("\r\n", "\n")
    out = {"notes_en": "", "notes_ru": ""}
    ms = list(_NOTES_HEAD.finditer(body))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(body)
        key = "notes_ru" if m.group(1).lower() in ("русский", "russian", "ru") else "notes_en"
        if not out[key]:
            out[key] = body[m.end():end].strip()[:4000]
    return out


def release_info(rel):
    """Нужное из ответа GitHub → компактный словарь или None, если версия не по semver."""
    tag = rel.get("tag_name") or ""
    ver = parse_ver(tag)
    if not ver or rel.get("draft") or rel.get("prerelease"):
        return None
    asset = None
    for a in rel.get("assets") or []:
        n = a.get("name") or ""
        if n.endswith(".tar.gz") and a.get("browser_download_url"):
            asset = a
            break
    url = asset["browser_download_url"] if asset else rel.get("tarball_url")
    digest = (asset or {}).get("digest") or ""
    return {
        "version": fmt_ver(ver), "tag": tag,
        "name": (rel.get("name") or tag)[:200],
        "html_url": rel.get("html_url") or "",
        "notes": (rel.get("body") or "")[:8000],
        "published_at": rel.get("published_at") or "",
        "url": url or "", "sha256": digest[7:] if digest.startswith("sha256:") else "",
    }


# ---------------------------------------------------------------- загрузка и проверка архива
def download(url, dest, api_base, max_bytes=MAX_ARCHIVE, sha256=None, timeout=60):
    if not host_ok(url, api_base):
        raise UpdateError("адрес загрузки не из GitHub: " + url[:80], "host")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    h, n = hashlib.sha256(), 0
    with _opener(api_base).open(req, timeout=timeout) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            n += len(chunk)
            if n > max_bytes:
                raise UpdateError("архив больше %d МБ" % (max_bytes // 1048576), "archive")
            h.update(chunk)
            f.write(chunk)
    if n == 0:
        raise UpdateError("пустой архив", "archive")
    if sha256 and h.hexdigest() != sha256.lower():
        raise UpdateError("контрольная сумма архива не совпала", "sha")
    return h.hexdigest()


def _safe_rel(name):
    if not name or name.startswith("/") or "\\" in name or "\x00" in name:
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def safe_extract(tar_path, dest):
    """Распаковка вручную: только обычные файлы и каталоги, никаких ссылок/устройств,
    путей наружу, лимиты на число и размер."""
    os.makedirs(dest, exist_ok=True)
    total = count = 0
    try:
        tf = tarfile.open(tar_path, "r:gz")
    except Exception as e:
        raise UpdateError("архив не открывается: %s" % e, "archive")
    with tf:
        for m in tf:
            if m.name.endswith("pax_global_header") or m.type == tarfile.XGLTYPE:
                continue
            rel = _safe_rel(m.name)
            if rel is None:
                raise UpdateError("небезопасный путь в архиве: " + m.name[:60], "archive")
            if m.isdir():
                os.makedirs(os.path.join(dest, rel), exist_ok=True)
                continue
            if not m.isreg():
                raise UpdateError("в архиве ссылка/спецфайл: " + m.name[:60], "archive")
            count += 1
            total += m.size
            if count > MAX_FILES or total > MAX_UNPACKED:
                raise UpdateError("архив слишком большой", "archive")
            out = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with tf.extractfile(m) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
    # корень: либо единственный каталог (cc-fleet-vX.Y.Z/), либо сам dest
    items = os.listdir(dest)
    if len(items) == 1 and os.path.isdir(os.path.join(dest, items[0])):
        return os.path.join(dest, items[0])
    return dest


def resolve_dst(dst, base):
    if os.path.isabs(dst):
        if dst in ALLOWED_ABS_DST:
            return dst
        raise UpdateError("манифест: запись вне каталога установки: " + dst, "manifest")
    rel = _safe_rel(dst)
    if rel is None:
        raise UpdateError("манифест: плохой путь " + dst, "manifest")
    full = os.path.normpath(os.path.join(base, rel))
    if not full.startswith(os.path.normpath(base) + os.sep):
        raise UpdateError("манифест: путь выходит за каталог установки: " + dst, "manifest")
    return full


def load_manifest(root, base):
    """→ (manifest, [(src_abs, dst_abs, mode_int, rel_dst)]). Всё проверяется ДО замены."""
    mf = jload(os.path.join(root, "update_manifest.json"))
    if not isinstance(mf, dict):
        raise UpdateError("в архиве нет update_manifest.json", "manifest")
    ver = parse_ver(mf.get("version"))
    if not ver:
        raise UpdateError("в манифесте нет версии", "manifest")
    entries = []
    for f in mf.get("files") or []:
        src = _safe_rel(str(f.get("src") or ""))
        if src is None or not os.path.isfile(os.path.join(root, src)):
            raise UpdateError("в архиве нет файла из манифеста: %s" % f.get("src"), "manifest")
        mode = str(f.get("mode") or "644")
        if mode not in ("644", "755"):
            raise UpdateError("манифест: недопустимые права " + mode, "manifest")
        dst = str(f.get("dst") or src)
        entries.append((os.path.join(root, src), resolve_dst(dst, base), int(mode, 8), dst))
    names = {e[3] for e in entries}
    for must in ("cc_limits.py", "cc_update.py"):
        if must not in names:
            raise UpdateError("в манифесте нет " + must, "manifest")
    return mf, entries


def check_sources(entries, version):
    """Все .py компилируются; VERSION в cc_limits.py совпадает с версией манифеста
    (иначе новый процесс не сможет подтвердить запуск)."""
    for src, _dst, _mode, rel in entries:
        if not rel.endswith(".py"):
            continue
        try:
            text = open(src, encoding="utf-8").read()
            compile(text, rel, "exec")
        except Exception as e:
            raise UpdateError("%s не компилируется: %s" % (rel, str(e)[:120]), "check")
        if rel == "cc_limits.py":
            m = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M)
            if not m or m.group(1) != version:
                raise UpdateError("VERSION в cc_limits.py не равна версии релиза", "check")


# ---------------------------------------------------------------- бэкап и замена
def make_backup(base, entries, from_ver, to_ver):
    root = os.path.join(base, BACKUP_DIR)
    os.makedirs(root, exist_ok=True)
    # время — в начале имени: сортировка по имени = по давности (иначе 1.10 < 1.9);
    # миллисекунды + счётчик — чтобы повторная попытка в ту же секунду не упёрлась в занятое имя
    stamp = int(time.time() * 1000)
    n = 0
    while True:
        bk = os.path.join(root, "%013d-%02d_%s_to_%s" % (stamp, n, from_ver, to_ver))
        try:
            os.makedirs(os.path.join(bk, "files"))
            break
        except FileExistsError:
            n += 1
    items = []
    for i, (_src, dst, _mode, _rel) in enumerate(entries):
        row = {"dst": dst, "existed": os.path.isfile(dst)}
        if row["existed"]:
            row["file"] = "files/%d" % i
            row["mode"] = os.stat(dst).st_mode & 0o777
            shutil.copy2(dst, os.path.join(bk, row["file"]))
        items.append(row)
    # сторож откатывает ЭТИМ экземпляром: новый cc_update.py может оказаться сломанным
    shutil.copy2(os.path.abspath(__file__), os.path.join(bk, "rollback_cc_update.py"))
    jsave(os.path.join(bk, "backup.json"), {"from": from_ver, "to": to_ver, "entries": items})
    # старые бэкапы — под нож, оставляем последние KEEP_BACKUPS
    olds = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    for d in olds[:-KEEP_BACKUPS]:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
    return bk


def _put(src, dst, mode):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".upd.tmp"
    shutil.copyfile(src, tmp)
    os.chmod(tmp, mode)
    os.replace(tmp, dst)


def install_files(entries):
    for src, dst, mode, _rel in entries:
        _put(src, dst, mode)


def restore_backup(bk):
    meta = jload(os.path.join(bk, "backup.json"))
    if not meta:
        raise UpdateError("в бэкапе нет backup.json", "backup")
    for row in meta["entries"]:
        if row["existed"]:
            _put(os.path.join(bk, row["file"]), row["dst"], row.get("mode", 0o644))
        elif os.path.exists(row["dst"]):
            os.remove(row["dst"])
    return meta


# ---------------------------------------------------------------- systemd
def systemd_ok(service):
    return bool(shutil.which("systemd-run") and shutil.which("systemctl")
                and os.path.isdir("/run/systemd/system")
                and os.path.isfile("/etc/systemd/system/%s.service" % service))


def _unit_run(unit, cmd, extra=()):
    """Одноразовый юнит ВНЕ cgroup нашей службы: её рестарт его не убьёт."""
    r = subprocess.run(["systemd-run", "--quiet", "--collect", "--no-block",
                        "--unit=" + unit, *extra, *cmd],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise UpdateError("systemd-run: " + (r.stderr or r.stdout).strip()[:160], "restart")


# ---------------------------------------------------------------- сторож отката (CLI)
def watchdog(base, service, poll=2.0):
    """Живёт в отдельном юните. Ждёт, пока новый процесс снимет маркер pending
    (= подтвердил запуск). Не дождался до дедлайна — возвращает файлы из бэкапа."""
    pend_p = os.path.join(base, PENDING_NAME)
    pend = jload(pend_p)
    if not pend:
        return "нет маркера обновления"
    while True:
        cur = jload(pend_p)       # дедлайн сдвигается перед рестартом — читаем заново
        if cur is None:
            if os.path.exists(pend_p):
                continue          # файл мог быть перезаписан в этот момент
            return "обновление подтверждено"
        pend = cur
        if time.time() > pend.get("deadline", 0):
            break
        time.sleep(poll)
    err = None
    try:
        restore_backup(pend["backup"])
    except Exception as e:
        err = str(e)[:200]
    res = {"ok": False, "from": pend.get("from"), "to": pend.get("to"), "ts": time.time(),
           "rolled_back": err is None, "code": "boot" if err is None else "rollback_failed",
           "error": ("новая версия не подтвердила запуск за %d с — вернул %s"
                     % (ROLLBACK_AFTER, pend.get("from"))) if err is None
                    else ("откат не удался: " + err)}
    jsave(os.path.join(base, RESULT_NAME), res)
    try:
        os.remove(pend_p)
    except OSError:
        pass
    subprocess.run(["systemctl", "reset-failed", service], capture_output=True, timeout=30)
    subprocess.run(["systemctl", "restart", service], capture_output=True, timeout=60)
    return res["error"]


# ---------------------------------------------------------------- Updater
class Updater:
    def __init__(self, base, version, cfg_fn, notify=None, log=print):
        self.base = base
        self.version = version
        self.cfg = cfg_fn
        self.notify = notify or (lambda text: None)
        self.log = log
        self.lock = threading.RLock()
        self.phase = "idle"       # idle | checking | downloading | verifying | installing | restarting
        self.phase_msg = ""
        self.last_error = None
        self._wake = threading.Event()
        self.p_state = os.path.join(base, STATE_NAME)
        self.p_pending = os.path.join(base, PENDING_NAME)
        self.p_result = os.path.join(base, RESULT_NAME)

    # --- конфиг ---
    def repo(self):
        return self.cfg().get("update_repo") or DEFAULT_REPO

    def api_base(self):
        return self.cfg().get("update_api_base") or DEFAULT_API

    def service(self):
        return self.cfg().get("service_name") or "cc-limits"

    def mode(self):
        return "auto" if self.cfg().get("update_mode") == "auto" else "manual"

    def check_enabled(self):
        return self.cfg().get("update_check", True) is not False

    def unsupported(self):
        if not systemd_ok(self.service()):
            return "нужен systemd и юнит %s.service" % self.service()
        return ""

    # --- состояние ---
    def _state(self):
        return jload(self.p_state, {}) or {}

    def _save_state(self, st):
        with _file_lock:
            jsave(self.p_state, st)

    def status(self):
        st = self._state()
        latest = st.get("latest")
        cur = parse_ver(self.version)
        lv = parse_ver((latest or {}).get("version"))
        available = bool(cur and lv and lv > cur)
        res = jload(self.p_result)
        return {
            "ok": True, "version": self.version, "mode": self.mode(),
            "check": self.check_enabled(), "supported": not self.unsupported(),
            "unsupported_reason": self.unsupported(), "unsupported_code": "systemd" if self.unsupported() else "",
            "latest": dict(latest, **split_notes(latest.get("notes"))) if available else None,
            "available": available,
            "skipped": bool(available and st.get("skipped") == latest.get("version")),
            "last_check": st.get("last_check"), "last_error": self.last_error or st.get("last_error"),
            "last_error_code": "net" if (self.last_error or st.get("last_error")) else "",
            "phase": self.phase, "phase_msg": self.phase_msg,
            "pending": os.path.exists(self.p_pending),
            "result": res if res and not res.get("seen") else None,
        }

    def set_phase(self, phase, msg=""):
        self.phase, self.phase_msg = phase, msg

    # --- проверка ---
    def check(self, force=False):
        with self.lock:
            if self.phase not in ("idle",):
                return self.status()
            st = self._state()
            if force and time.time() - (st.get("last_check") or 0) < MANUAL_CHECK_GAP:
                return self.status()
            self.set_phase("checking")
        try:
            status, rel, etag = fetch_latest(self.repo(), self.api_base(), st.get("etag"))
            st["last_check"] = time.time()
            st["last_error"] = None
            self.last_error = None
            if status == 200:
                info = release_info(rel)
                st["etag"] = etag
                st["latest"] = info
            elif status == 404:
                st["latest"], st["etag"] = None, None
            self._save_state(st)
        except Exception as e:
            self.last_error = "проверка не удалась: %s" % str(e)[:160]
            st["last_check"] = time.time()
            st["last_error"] = self.last_error
            self._save_state(st)
        finally:
            self.set_phase("idle")
        self._announce()
        return self.status()

    def _announce(self):
        """Сообщение в Telegram о новой версии — один раз на версию (если TG настроен)."""
        s = self.status()
        if not s["available"] or s["skipped"]:
            return
        st = self._state()
        if st.get("notified") == s["latest"]["version"]:
            return
        st["notified"] = s["latest"]["version"]
        self._save_state(st)
        self.notify("⬆ cc-fleet: вышла версия %s (у тебя %s). %s" % (
            s["latest"]["version"], self.version,
            "Ставлю автоматически." if self.mode() == "auto" and self.check_enabled()
            else "Обновить можно в панели — баннер сверху."))

    def skip(self, version):
        st = self._state()
        st["skipped"] = version if parse_ver(version) else None
        self._save_state(st)
        return self.status()

    def ack(self):
        res = jload(self.p_result)
        if res:
            res["seen"] = True
            jsave(self.p_result, res)
        return self.status()

    # --- применение ---
    def apply(self, version=None):
        """Запускает обновление в фоне. → (ok, message)."""
        why = self.unsupported()
        if why:
            return False, why
        with self.lock:
            if self.phase != "idle" or os.path.exists(self.p_pending):
                return False, "обновление уже идёт"
            st = self._state()
            latest = st.get("latest") or {}
            if not latest or not (parse_ver(latest.get("version")) or (0,)) > (parse_ver(self.version) or (0,)):
                return False, "новой версии нет"
            if version and version != latest.get("version"):
                return False, "вышла другая версия — обнови статус"
            self.set_phase("downloading", latest["version"])
            try:
                os.remove(self.p_result)   # старый итог (в т.ч. прошлый сбой) больше не актуален
            except OSError:
                pass
        threading.Thread(target=self._apply_worker, args=(latest,), daemon=True,
                         name="cc-update").start()
        return True, "начал"

    def _fail(self, latest, err):
        self.log("update: ОШИБКА: %s" % err)
        code = err.code if isinstance(err, UpdateError) else (
            "net" if isinstance(err, (urllib.error.URLError, TimeoutError, ConnectionError)) else "other")
        jsave(self.p_result, {"ok": False, "from": self.version, "to": latest["version"],
                              "ts": time.time(), "rolled_back": False, "error": str(err)[:300], "code": code,
                              "needs_install": isinstance(err, NeedsInstall), "notified": True})
        self.set_phase("idle")
        self.notify("⚠ cc-fleet: обновление до %s не удалось — %s" % (latest["version"], str(err)[:200]))

    def _apply_worker(self, latest):
        base, tmp = self.base, os.path.join(self.base, TMP_DIR)
        bk = None
        try:
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp)
            self.set_phase("downloading", latest["version"])
            tgz = os.path.join(tmp, "release.tar.gz")
            download(latest["url"], tgz, self.api_base(), sha256=latest.get("sha256") or None)
            self.set_phase("verifying", latest["version"])
            root = safe_extract(tgz, os.path.join(tmp, "src"))
            mf, entries = load_manifest(root, base)
            if fmt_ver(parse_ver(mf["version"])) != latest["version"]:
                raise UpdateError("версия в манифесте (%s) не равна версии релиза (%s)"
                                  % (mf["version"], latest["version"]), "manifest")
            if mf.get("needs_install"):
                raise NeedsInstall("в этой версии изменилась установка (служба/nginx/хуки): "
                                   "один раз запусти sudo ./install.sh из архива релиза")
            check_sources(entries, latest["version"])
            self.set_phase("installing", latest["version"])
            bk = make_backup(base, entries, self.version, latest["version"])
            jsave(self.p_pending, {"from": self.version, "to": latest["version"], "backup": bk,
                                   "ts": time.time(), "deadline": time.time() + ROLLBACK_AFTER + 30})
            try:
                # сторож — ДО замены файлов: без него обновление не начинаем
                _unit_run(self.service() + "-rollback",
                          [sys.executable, os.path.join(bk, "rollback_cc_update.py"),
                           "watchdog", "--base", base, "--service", self.service()])
                install_files(entries)
            except Exception:
                try:
                    restore_backup(bk)
                finally:
                    try:
                        os.remove(self.p_pending)
                    except OSError:
                        pass
                raise
            self.set_phase("restarting", latest["version"])
            self.log("update: %s → %s, файлы заменены, перезапускаю службу" % (self.version, latest["version"]))
            shutil.rmtree(tmp, ignore_errors=True)
            # пауза: ответ на запрос «обновить»/«включить авто» должен дойти до браузера раньше, чем служба упадёт
            time.sleep(RESTART_GRACE)
            # рестарт с запасом: отдельный юнит, чтобы он пережил остановку нашего процесса
            pend = jload(self.p_pending)
            pend["deadline"] = time.time() + ROLLBACK_AFTER
            jsave(self.p_pending, pend)
            try:
                _unit_run(self.service() + "-restart", ["systemctl", "restart", self.service()])
            except Exception as e:
                # юнит-рестартер не поднялся — выходим сами, Restart=always перезапустит службу
                self.log("update: рестарт через systemd-run не вышел (%s), завершаю процесс" % e)
                time.sleep(1)
                os._exit(0)
        except Exception as e:
            self._fail(latest, e)

    # --- после старта новой версии ---
    def confirm_boot(self):
        """Вызывается при старте службы. Если шло обновление на нашу версию — через
        CONFIRM_DELAY секунд убедиться, что мы живы и отвечаем, и снять маркер."""
        pend = jload(self.p_pending)
        if pend and pend.get("to") == self.version:
            threading.Thread(target=self._confirm_worker, args=(pend,), daemon=True,
                             name="cc-update-confirm").start()
        res = jload(self.p_result)
        if res and not res.get("notified"):
            res["notified"] = True
            jsave(self.p_result, res)
            if res.get("ok"):
                self.notify("✅ cc-fleet обновлён: %s → %s" % (res.get("from"), res.get("to")))
            else:
                self.notify("⚠ cc-fleet: обновление до %s не удалось — %s" % (
                    res.get("to"), res.get("error")))

    def _confirm_worker(self, pend):
        time.sleep(CONFIRM_DELAY)
        try:
            port = self.cfg().get("port", 8877)
            url = "http://127.0.0.1:%s/api/update?token=%s" % (port, self.cfg().get("hook_token", ""))
            with urllib.request.urlopen(url, timeout=10) as r:
                d = json.loads(r.read())
            if d.get("version") != pend["to"]:
                raise UpdateError("служба отвечает версией %s" % d.get("version"))
        except Exception as e:
            self.log("update: подтверждение не прошло (%s) — оставляю решение сторожу" % e)
            return
        jsave(self.p_result, {"ok": True, "from": pend["from"], "to": pend["to"],
                              "ts": time.time(), "notified": True})
        try:
            os.remove(self.p_pending)
        except OSError:
            pass
        self.log("update: %s подтверждена" % pend["to"])
        self.notify("✅ cc-fleet обновлён: %s → %s" % (pend["from"], pend["to"]))

    # --- фоновая петля ---
    def kick(self):
        """Разбудить петлю (после смены режима)."""
        self._wake.set()

    def loop(self):
        self.confirm_boot()
        first = True
        while True:
            try:
                if not self.check_enabled():
                    self._wake.wait(3600)
                    self._wake.clear()
                    continue
                due = (self._state().get("last_check") or 0) + CHECK_EVERY
                wait = max(FIRST_CHECK_DELAY if first else 0, due - time.time())
                first = False
                if wait > 0 and self._wake.wait(min(wait, 3600)):
                    self._wake.clear()      # разбудили (сменили режим) — без новой проверки
                    self._maybe_auto()
                    continue
                if time.time() >= due:
                    self.check()
                self._maybe_auto()
            except Exception as e:
                self.log("update loop: %s" % e)
                time.sleep(60)

    def _maybe_auto(self):
        if self.mode() != "auto" or not self.check_enabled():
            return
        s = self.status()
        if not s["available"] or s["skipped"] or not s["supported"] or s["pending"]:
            return
        res = jload(self.p_result) or {}
        if res.get("ok") is False and res.get("to") == s["latest"]["version"]:
            return  # эта версия уже не поднялась/не встала — сами её не повторяем
        ok, msg = self.apply(s["latest"]["version"])
        self.log("update: авто-режим: %s" % msg)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watchdog")
    w.add_argument("--base", required=True)
    w.add_argument("--service", required=True)
    a = ap.parse_args()
    print("watchdog:", watchdog(a.base, a.service), flush=True)
