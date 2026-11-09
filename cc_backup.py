"""Резервные копии профилей аккаунтов Claude (в них токены входа).

Что делает балансер сам:
- раз в сутки и при новом/пропавшем аккаунте — датированная копия `profiles_ГГГГММДД_ЧЧММСС_nN.tar.gz`, хранится 14 штук;
- при любом изменении токенов (их обновляет сам Claude) — «свежая» копия `latest.tar.gz`: у неё самые новые токены;
- пустые и тестовые слоты не копируются: если настоящих профилей нет, копии не трогаются (старые не вытесняются пустотой);
- восстановление возвращает ТОЛЬКО недостающие профили. Живой аккаунт не перезаписывается: после перелогина старый токен из копии мог бы его испортить.
Папка копий — только для root (700), файлы 600.
"""
import hashlib
import json
import os
import re
import tarfile
import tempfile
import threading
import time
import cc_disconnect

KEEP = 14  # сколько датированных копий хранить
DAY = 86400
EVENT_GAP = 3600  # новый/пропавший аккаунт даёт внеочередную копию, но не чаще раза в час
TICK = 60  # как часто сторож смотрит на токены
LATEST = "latest.tar.gz"
FILES = ("credentials.json", "oauth_account.json")  # из чего состоит профиль
_ACC_RE = re.compile(r"^acc[0-9]{1,3}$")
_NAME_RE = re.compile(r"^profiles_([0-9]{8}_[0-9]{6})_n([0-9]+)\.tar\.gz$")
MAX_FILE = 1 << 20  # профиль — пара небольших json; больше 1 МБ в архиве не принимаем

_lock = threading.Lock()
_st = {"sig": None, "covered": None, "err": "", "t": None}


def _jload(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def is_real(profiles, name):
    """Настоящий профиль: сохранён аккаунт (accountUuid) и есть токены, а не пустой слот установщика."""
    d = os.path.join(profiles, name)
    if os.path.exists(os.path.join(d, cc_disconnect.MARKER)):
        return False
    oa = _jload(os.path.join(d, "oauth_account.json"))
    cr = os.path.join(d, "credentials.json")
    return bool(isinstance(oa, dict) and oa.get("accountUuid")) and os.path.isfile(cr) and os.path.getsize(cr) > 2


def real_names(profiles):
    if not os.path.isdir(profiles):
        return []
    return sorted(n for n in os.listdir(profiles) if _ACC_RE.match(n) and is_real(profiles, n))


def signature(profiles, names):
    """Отпечаток токенов и аккаунтов: меняется, когда Claude обновил токен или добавили/убрали аккаунт."""
    h = hashlib.sha256()
    for n in names:
        for f in FILES:
            try:
                with open(os.path.join(profiles, n, f), "rb") as fh:
                    h.update(n.encode() + b"/" + f.encode() + b"\0" + fh.read())
            except OSError:
                h.update(b"?")
    return h.hexdigest()


def _ensure_dir(dest):
    os.makedirs(dest, exist_ok=True)
    os.chmod(dest, 0o700)


def _pack(profiles, names, path):
    """Собрать архив во временный файл рядом и проверить, что он читается и профили целые; затем переименовать."""
    part = path + ".part"
    try:
        old = os.umask(0o077)
        try:
            with tarfile.open(part, "w:gz") as tf:
                for n in names:
                    for f in FILES:
                        src = os.path.join(profiles, n, f)
                        if os.path.isfile(src):
                            tf.add(src, arcname=f"{n}/{f}", recursive=False)
        finally:
            os.umask(old)
        got = archive_names(part)
        if sorted(got) != sorted(names):
            raise RuntimeError(f"в архиве {sorted(got)}, ожидалось {sorted(names)}")
        os.chmod(part, 0o600)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass


def _safe_member(m):
    """Имя файла из архива → (профиль, файл) или None. Принимаем только accN/credentials.json и accN/oauth_account.json."""
    if not m.isreg() or m.size > MAX_FILE:
        return None
    parts = m.name.split("/")
    if len(parts) == 3 and parts[0] == ".claude-profiles":  # копия, снятая командой tar от корня папки профилей
        parts = parts[1:]
    if len(parts) != 2 or not _ACC_RE.match(parts[0]) or parts[1] not in FILES:
        return None
    return parts[0], parts[1]


def archive_profiles(path):
    """{профиль: accountUuid} для профилей, что целиком (оба файла) лежат в архиве. Читает архив до конца: битый — исключение."""
    seen, uuid = {}, {}
    with tarfile.open(path, "r:gz") as tf:
        for m in tf:
            sm = _safe_member(m)
            if sm:
                data = tf.extractfile(m).read()
                if len(data) > 2:
                    seen.setdefault(sm[0], set()).add(sm[1])
                    if sm[1] == "oauth_account.json":
                        try:
                            uuid[sm[0]] = str((json.loads(data) or {}).get("accountUuid") or "")
                        except Exception:
                            uuid[sm[0]] = ""
    return {n: uuid.get(n, "") for n, fs in seen.items() if set(FILES) <= fs}


def archive_names(path):
    return list(archive_profiles(path))


def _live_uuids(profiles):
    return {(_jload(os.path.join(profiles, n, "oauth_account.json")) or {}).get("accountUuid") for n in real_names(profiles)}


# аккаунт, который удалили кнопкой «Удалить», в копиях остаётся, но «потерянным» не считается и не возвращается
DELETED = "deleted.json"


def _deleted(dest):
    d = _jload(os.path.join(dest, DELETED))
    return set(d) if isinstance(d, dict) else set()


def note_deleted(dest, uuid):
    """Запомнить, что аккаунт удалён намеренно (по accountUuid): «Восстановить недостающие» его не предложит."""
    if not uuid:
        return
    with _lock:
        _ensure_dir(dest)
        d = _jload(os.path.join(dest, DELETED))
        d = d if isinstance(d, dict) else {}
        d[str(uuid)] = int(time.time())
        fd, tmp = tempfile.mkstemp(prefix=".deleted.", dir=dest)
        with os.fdopen(fd, "w") as fh:
            json.dump(d, fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, os.path.join(dest, DELETED))


def _dated(dest):
    """Датированные копии, свежие первыми: [(время, имя, n профилей)]."""
    out = []
    if os.path.isdir(dest):
        for f in os.listdir(dest):
            m = _NAME_RE.match(f)
            if m:
                out.append((time.mktime(time.strptime(m.group(1), "%Y%m%d_%H%M%S")), f, int(m.group(2))))
    return sorted(out, reverse=True)


def _rotate(dest, keep):
    # старые стираем только после того, как новая копия уже записана и проверена
    for _, f, _ in _dated(dest)[keep:]:
        try:
            os.remove(os.path.join(dest, f))
        except OSError:
            pass


def make(profiles, dest, now=None, keep=KEEP):
    """Датированная копия сейчас. → {"ok", "name", "profiles"} или {"ok": False, "why": "empty"|"error", "err"}."""
    now = time.time() if now is None else now
    with _lock:
        names = real_names(profiles)
        if not names:
            return {"ok": False, "why": "empty"}
        try:
            _ensure_dir(dest)
            name = "profiles_%s_n%d.tar.gz" % (time.strftime("%Y%m%d_%H%M%S", time.localtime(now)), len(names))
            _pack(profiles, names, os.path.join(dest, name))
            _write_latest(profiles, dest, names)
            _rotate(dest, keep)
        except Exception as e:
            _st["err"] = str(e)[:200]
            return {"ok": False, "why": "error", "err": _st["err"]}
        _st["err"] = ""
        _st["sig"] = signature(profiles, names)
        _st["covered"] = set(names)
        return {"ok": True, "name": name, "profiles": len(names)}


def _write_latest(profiles, dest, names):
    _ensure_dir(dest)
    _pack(profiles, names, os.path.join(dest, LATEST))


def tick(profiles, dest, enabled=True, now=None):
    """Один шаг сторожа. → "daily" | "event" | "latest" | None (ничего не потребовалось)."""
    if not enabled:
        return None
    now = time.time() if now is None else now
    names = real_names(profiles)
    if not names:
        return None  # пусто — ничего не затираем
    dated = _dated(dest)
    if _st["covered"] is None:  # после перезапуска: какие аккаунты уже есть в самой свежей датированной копии
        try:
            _st["covered"] = set(archive_names(os.path.join(dest, dated[0][1]))) if dated else set()
        except Exception:
            _st["covered"] = set()
    last = dated[0][0] if dated else 0
    changed = set(names) != _st["covered"]
    if not dated or now - last >= DAY:
        return "daily" if make(profiles, dest, now).get("ok") else None
    if changed and now - last >= EVENT_GAP:
        return "event" if make(profiles, dest, now).get("ok") else None
    sig = signature(profiles, names)
    if sig != _st["sig"]:
        with _lock:
            try:
                _write_latest(profiles, dest, names)
                _st["sig"] = sig
                _st["err"] = ""
            except Exception as e:
                _st["err"] = str(e)[:200]
                return None
        return "latest"
    return None


def listing(profiles, dest):
    """Для панели: что лежит в копиях и что бы вернулось. Читает только имена и размеры."""
    items = []
    for ts, f, n in _dated(dest):
        try:
            sz = os.path.getsize(os.path.join(dest, f))
        except OSError:
            sz = 0
        items.append({"name": f, "ts": int(ts), "n": n, "size": sz})
    lt = os.path.join(dest, LATEST)
    latest = None
    if os.path.isfile(lt):
        try:
            latest = {"ts": int(os.path.getmtime(lt)), "n": len(archive_names(lt)), "size": os.path.getsize(lt)}
        except Exception:
            latest = {"ts": 0, "n": 0, "size": 0, "bad": True}
    return {"items": items, "latest": latest, "profiles": len(real_names(profiles)),
            "missing": missing(profiles, dest), "error": _st["err"]}


def _sources(dest):
    """Копии от самой свежей по токенам к старым: latest, затем датированные от новых к старым."""
    out = []
    lt = os.path.join(dest, LATEST)
    if os.path.isfile(lt):
        out.append(lt)
    out += [os.path.join(dest, f) for _, f, _ in _dated(dest)]
    return out


def _wanted(profiles, dest):
    """{профиль: путь копии, откуда его вернуть} для тех, кого сейчас нет. Профиль берётся из самой свежей копии, где он есть.
    Не предлагаем аккаунт, который уже есть под другим именем (вошли заново) или удалён кнопкой: иначе вышел бы двойник со старым токеном."""
    want, skip, taken = {}, _deleted(dest), _live_uuids(profiles)
    for path in _sources(dest):
        try:
            found = archive_profiles(path)
        except Exception:
            continue  # битую копию пропускаем, остальные работают
        for n, uid in found.items():
            if n in want or is_real(profiles, n) or (uid and (uid in skip or uid in taken)):
                continue
            want[n] = path
            if uid:
                taken.add(uid)  # один аккаунт в разных копиях под одним именем — берём из самой свежей
    return want


def missing(profiles, dest):
    return sorted(_wanted(profiles, dest))


def restore_missing(profiles, dest):
    """Вернуть из копий профили, которых сейчас нет (или слот пуст). Живые не трогает. → {"restored": [...]}."""
    with _lock:
        want = _wanted(profiles, dest)
        restored = []
        for name, path in sorted(want.items()):
            if is_real(profiles, name):
                continue  # пока шли — профиль появился (вошли заново): живой важнее копии
            try:
                with tarfile.open(path, "r:gz") as tf:
                    blobs = {}
                    for m in tf:
                        sm = _safe_member(m)
                        if sm and sm[0] == name:
                            blobs[sm[1]] = tf.extractfile(m).read()
                if set(blobs) != set(FILES):
                    continue
                d = os.path.join(profiles, name)
                os.makedirs(d, exist_ok=True)
                for f in FILES:  # сначала oauth_account, потом credentials: профиль «настоящий» только когда есть оба
                    fd, tmp = tempfile.mkstemp(prefix="." + f + ".", dir=d)
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(blobs[f])
                    os.chmod(tmp, 0o600)
                    os.replace(tmp, os.path.join(d, f))
                restored.append(name)
            except Exception as e:
                _st["err"] = str(e)[:200]
        return {"restored": restored}


def _loop(get_profiles, dest, get_enabled):
    time.sleep(20)  # дать сервису подняться
    while True:
        try:
            tick(get_profiles(), dest, get_enabled())
        except Exception as e:  # сторож не должен падать из-за одного сбоя
            _st["err"] = str(e)[:200]
        time.sleep(TICK)


def start(get_profiles, dest, get_enabled):
    """Из cc_limits при старте: запустить сторож копий."""
    if not (_st["t"] and _st["t"].is_alive()):
        _st["t"] = threading.Thread(target=_loop, args=(get_profiles, dest, get_enabled), daemon=True, name="profile-backup")
        _st["t"].start()
