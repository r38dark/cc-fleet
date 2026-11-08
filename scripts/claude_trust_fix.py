#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ставит hasTrustDialogAccepted=true для рабочей папки в ~/.claude.json перед запуском claude.
Диалог «Is this a project you trust?» из корневой папки не запоминается и по умолчанию стоит на «No, exit» (Enter = выход);
без этого автозапуск Claude Code в screen/tmux закрывается сразу. Способ описан в самом claude
(«set projects[<path>].hasTrustDialogAccepted: true»). Запускать, когда claude не работает.
Папки: аргументы командной строки, иначе рабочая папка из config.json панели («work_dir»), иначе домашняя."""
import json
import os
import shutil
import sys
import tempfile

CFG = os.path.expanduser("~/.claude.json")
PANEL_CFG = os.path.join(os.environ.get("CC_LIMITS_BASE") or "/opt/cc-limits", "config.json")


def paths():
    if len(sys.argv) > 1:
        return sys.argv[1:]
    try:
        with open(PANEL_CFG, encoding="utf-8") as f:
            wd = str(json.load(f).get("work_dir") or "").strip()
    except (OSError, ValueError):
        wd = ""
    return [wd or os.path.expanduser("~")]


def main():
    try:
        with open(CFG, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        print(f"claude_trust_fix: пропуск, {CFG} не прочитан: {e}")
        return 0
    proj = cfg.setdefault("projects", {})
    changed = []
    for p in paths():
        ent = proj.setdefault(p, {})
        if ent.get("hasTrustDialogAccepted") is not True:
            ent["hasTrustDialogAccepted"] = True
            changed.append(p)
    if not changed:
        print("claude_trust_fix: уже стоит")
        return 0
    shutil.copy2(CFG, CFG + ".bak_trustfix")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CFG), prefix=".claude.json.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, os.stat(CFG).st_mode & 0o777)
    os.replace(tmp, CFG)
    print("claude_trust_fix: поставлено для", ", ".join(changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
