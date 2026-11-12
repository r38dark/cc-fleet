"""Local sign-out helpers. Never remove profiles, projects or conversation history."""
import json
import os
import stat

import cc_lock

MARKER = '.ccfleet-disconnected'


def plain(path):
    """Refuse links and special files before changing a credential store."""
    if os.path.islink(path):
        raise OSError('symbolic link')
    if os.path.exists(path) and not stat.S_ISREG(os.stat(path).st_mode):
        raise OSError('not a regular file')


def read(path):
    plain(path)
    try:
        with open(path) as f:
            doc = json.load(f)
    except FileNotFoundError:
        return None
    if not isinstance(doc, dict):
        raise ValueError('expected an object')
    return doc


def write(path, doc):
    plain(path)
    prev = os.stat(path) if os.path.exists(path) else None
    cc_lock.atomic_write(path, json.dumps(doc, ensure_ascii=False, indent=1),
                         stat.S_IMODE(prev.st_mode) if prev else 0o600)
    if prev and os.geteuid() == 0:
        os.chown(path, prev.st_uid, prev.st_gid)


def remove(path):
    plain(path)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def drop_keys(path, keys):
    doc = read(path)
    if doc is None:
        return
    if any(k in doc for k in keys):
        for k in keys:
            doc.pop(k, None)
        write(path, doc)
