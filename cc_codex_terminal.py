"""Codex-only Screen transport; old sessions keep their original client/socket."""
import json
import os
import sys

VERSION = '5.0.2'


def private_binary(base):
    return os.path.join(base, 'terminal', 'screen-'+VERSION, 'screen')


def private_directory(console_dir):
    return os.path.join(console_dir, 'screen5')


def legacy():
    return {'screen_bin': '/usr/bin/screen', 'screen_dir': os.environ.get('SCREENDIR', ''), 'screen_rgb': False}


def runtime(meta, base, console_dir):
    # Never execute arbitrary paths supplied by user-owned console metadata.
    if (meta.get('screen_bin') == private_binary(base)
            and meta.get('screen_dir') == private_directory(console_dir)):
        return {'screen_bin': private_binary(base), 'screen_dir': private_directory(console_dir), 'screen_rgb': True}
    return legacy()


def target(base, console_dir):
    if os.path.isfile(private_binary(base)) and os.access(private_binary(base), os.X_OK):
        return {'screen_bin': private_binary(base), 'screen_dir': private_directory(console_dir), 'screen_rgb': True}
    return legacy()


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(2)
    base, console_dir = sys.argv[1:]
    try:
        with open(os.path.join(console_dir, 'console.json')) as stream:
            meta = json.load(stream)
    except (OSError, ValueError):
        meta = {}
    transport = runtime(meta, base, console_dir)
    print(transport['screen_bin'])
    print(transport['screen_dir'])
