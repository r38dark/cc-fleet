#!/usr/bin/env python3
"""Проверка репозитория на личные данные владельца перед публикацией.

Запуск:  python3 tools/privacy_check.py [--commits N] [--list]
Проверяет: (1) все отслеживаемые git файлы, кроме картинок; (2) тексты сообщений последних N коммитов (по умолчанию все,
которых нет на GitHub — то есть все коммиты после последнего тега, если тегов нет — 20); (3) имена файлов.
Выход 0 — чисто, 1 — найдено. Шаблоны лежат в tools/privacy_patterns.txt (по одному регулярному выражению в строке, # — комментарий);
в самом репозитории личных данных быть не должно, поэтому реальный список хранится ВНЕ git: файл ~/.cc_fleet_privacy.txt
(если есть) дополняет шаблоны. Строка с пометкой `privacy-ok` в тексте исключений не даёт ложных срабатываний у тестовых примеров."""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKIP_EXT = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".ico", ".gz", ".zip")
SELF = os.path.join("tools", "privacy_check.py")
PATTERNS_IN_REPO = os.path.join("tools", "privacy_patterns.txt")


def sh(*args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, errors="replace").stdout


def load_patterns():
    pats = []
    for path in (os.path.join(ROOT, PATTERNS_IN_REPO), os.path.expanduser("~/.cc_fleet_privacy.txt")):
        try:
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#"):
                    pats.append(re.compile(line, re.I))
        except OSError:
            pass
    return pats


def main():
    args = sys.argv[1:]
    commits = int(args[args.index("--commits") + 1]) if "--commits" in args else 0
    show_all = "--list" in args
    pats = load_patterns()
    if not pats:
        print("нет шаблонов (tools/privacy_patterns.txt, ~/.cc_fleet_privacy.txt)")
        return 2
    hits = {}

    def add(kind, where, line_no, text, pat):
        hits.setdefault((kind, pat.pattern), []).append((where, line_no, text.strip()[:140]))

    files = [f for f in sh("git", "ls-files").splitlines() if f and not f.lower().endswith(SKIP_EXT) and f not in (SELF, PATTERNS_IN_REPO)]
    for f in files:
        for pat in pats:
            if pat.search(f):
                add("имя файла", f, 0, f, pat)
        try:
            data = open(os.path.join(ROOT, f), encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        for n, line in enumerate(data, 1):
            if "privacy-ok" in line:
                continue
            for pat in pats:
                if pat.search(line):
                    add("файл", f, n, line, pat)
    tags = sh("git", "describe", "--tags", "--abbrev=0").strip()
    rng = ["%s..HEAD" % tags] if tags and not commits else ["-%d" % (commits or 20)]
    for entry in sh("git", "log", "--format=%h%x00%B%x01", *rng).split("\x01"):
        if "\x00" not in entry:
            continue
        h, body = entry.strip().split("\x00", 1)
        for n, line in enumerate(body.splitlines(), 1):
            for pat in pats:
                if pat.search(line):
                    add("коммит", h, n, line, pat)
    total = sum(len(v) for v in hits.values())
    for (kind, pat), rows in sorted(hits.items(), key=lambda kv: -len(kv[1])):
        files_n = len({r[0] for r in rows})
        print("%-10s %-40s %5d строк в %d" % (kind, pat[:40], len(rows), files_n))
        if show_all:
            for where, n, text in rows:
                print("    %s:%s  %s" % (where, n, text))
    print("ИТОГО: %d" % total)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
