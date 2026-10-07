#!/usr/bin/env python3
# PreToolUse-хук Claude Code: на паузе по лимитам работа реально стоит.
#
# Без него пауза (pause_ctl.py) глушит только новые входящие (queue_on_limits.py),
# а уже начатый ход идёт дальше и добивает окно, пока сам не закончится. С ним:
# пауза активна (или активный выше сессионного порога и переключаться некуда, или активный на недельном
# потолке без запасного при включённой «Паузе на недельном потолке» — тогда пауза
# ставится здесь же) → первый вызов инструмента получает отказ с инструкцией, дальше GRACE
# секунд на то, чтобы довести начатое до целостного состояния и записать, что
# сделано и что осталось, потом любой инструмент — отказ до будильника.
#
# Всегда пропускаем: memory проектов, settings.json и хуки Claude Code, команды
# pause_ctl/tg_queue (запасной выход: `pause_ctl.py clear` или `off`).
# Пауза отключена кнопкой на панели (pause_ctl off) — пропускаем всё.
# Любая ошибка — пропуск (fail-open).
#
# Установка (install.sh предлагает сделать это за вас):
#   ~/.claude/settings.json → hooks.PreToolUse:
#     [{"matcher":"*","hooks":[{"type":"command","command":"python3 /opt/cc-limits/hooks/pause_tool_gate.py"}]}]
#   Каталог пакета берётся из CC_LIMITS_DIR (по умолчанию /opt/cc-limits).
import json
import os
import sys
import time
from datetime import datetime

CCL = os.environ.get("CC_LIMITS_DIR", "/opt/cc-limits")
MARK = os.path.join(CCL, "pause_tool_gate.json")
GRACE = 120

CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
ALWAYS_PATHS = (os.path.join(CLAUDE_DIR, "settings.json"), os.path.join(CLAUDE_DIR, "hooks") + "/")
ALWAYS_BASH = ("pause_ctl", "tg_queue")


def passthrough():
    sys.exit(0)


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
        "systemMessage": "⏸ Пауза по лимитам — инструмент заблокирован",
    }, ensure_ascii=False))
    sys.exit(0)


def always_ok(data):
    ti = data.get("tool_input") or {}
    path = str(ti.get("file_path") or "")
    if path:
        if any(path.startswith(p) for p in ALWAYS_PATHS):
            return True
        # memory любого проекта: ~/.claude/projects/<проект>/memory/...
        if path.startswith(os.path.join(CLAUDE_DIR, "projects") + "/") and "/memory/" in path:
            return True
    if data.get("tool_name") == "Bash":
        cmd = str(ti.get("command") or "")
        if any(w in cmd for w in ALWAYS_BASH):
            return True
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        passthrough()
    if always_ok(data):
        passthrough()

    os.environ.setdefault("CC_LIMITS_BASE", CCL)
    sys.path.insert(0, CCL)
    import pause_ctl
    st = pause_ctl.load()
    now = time.time()
    if st.get("override"):
        passthrough()
    if not st.get("active"):
        lvl = pause_ctl.level_state()
        if lvl.get("level") not in ("hard", "week") or lvl.get("stale"):
            passthrough()
        # активный выше сессионного порога и уйти некуда (или неделя на потолке) —
        # встаём на паузу сами, будильник поднимет; причину на неделе cmd_set напишет сам
        import argparse
        import contextlib
        import io
        # cmd_set печатает строку лога в stdout — хуку там нужен только JSON
        with contextlib.redirect_stdout(io.StringIO()):
            pause_ctl.cmd_set(argparse.Namespace(
                reason="лимиты сессионного окна", resume_at="",
                note="остановлен посреди работы (%s)" % (lvl.get("line") or "")))
        st = pause_ctl.load()
        if not st.get("active"):
            passthrough()
    resume = float(st.get("resume_at") or 0)
    if resume and resume < now:
        passthrough()  # будильник просрочен — не держим сессию, пусть крон разбирается
    since = float(st.get("since") or 0)
    at = datetime.fromtimestamp(resume).strftime("%H:%M") if resume else "?"

    try:
        mark = json.load(open(MARK))
    except Exception:
        mark = {}
    if mark.get("since") != since:
        tmp = MARK + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"since": since, "notice_ts": now}, f)
        os.replace(tmp, MARK)
        deny("Пауза по лимитам с %s (%s), подъём в %s — будильник pause_ctl разбудит сам. "
             "Новых шагов не начинай. У тебя %d с: если начатое действие оставляет систему "
             "в сломанном состоянии — доведи его до целостного и запиши, что сделано и что "
             "осталось (memory проекта доступна). Потом заверши ход без дальнейших действий."
             % (datetime.fromtimestamp(since).strftime("%H:%M"), st.get("reason") or "лимиты",
                at, GRACE))
    if now - float(mark.get("notice_ts") or 0) <= GRACE:
        passthrough()
    deny("Пауза по лимитам, подъём в %s. Инструменты заблокированы до будильника — "
         "заверши ход без действий (memory и pause_ctl доступны)." % at)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
