#!/usr/bin/env python3
# UserPromptSubmit-хук Claude Code: пока все окна лимитов сожжены, входящее сообщение
# из чат-канала (Telegram и т.п.) НЕ доходит до модели.
#
# Без этого хука очереди не существует: каждое сообщение будит сессию, та берётся за
# работу и добивает остаток окна — а человек в чате уверен, что его сообщения копятся
# и будут разобраны позже. Хук делает это правдой: при «красном» гейте промпт
# блокируется ДО обращения к модели (значит без расхода токенов), текст ложится в
# tg_queue.jsonl, а отправителю отвечает сам хук через Bot API. Очередь разбирается,
# когда pause_ctl.py разбудит сессию после сброса окна.
#
# Установка (install.sh предлагает сделать это за вас):
#   ~/.claude/settings.json → hooks.UserPromptSubmit:
#     [{"hooks":[{"type":"command","command":"python3 /opt/cc-limits/hooks/queue_on_limits.py"}]}]
#   Каталог пакета берётся из CC_LIMITS_DIR (по умолчанию /opt/cc-limits).
#
# Fail-open: любая ошибка, нечитаемый вход или сообщение не из чат-канала — пропускаем.
import json
import os
import re
import subprocess
import sys
import tempfile
import time

CCL = os.environ.get("CC_LIMITS_DIR", "/opt/cc-limits")
LOG = os.path.join(CCL, "tg_queue.log")
QUEUE_CLI = os.path.join(CCL, "tg_queue.py")

CH_RE = re.compile(r"<channel\s+([^>]*)>(.*?)</channel>", re.S)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%d.%m %H:%M:%S"), msg))
    except Exception:
        pass


def allow():
    sys.exit(0)


def block(reason):
    print(json.dumps({
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit"},
        "systemMessage": "Incoming message queued — limit windows are burnt",
    }, ensure_ascii=False))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        allow()

    prompt = data.get("prompt") or ""
    m = CH_RE.search(prompt)
    log("prompt[%d] channel=%s: %s" % (len(prompt), bool(m), prompt[:120].replace("\n", " ")))
    if not m:
        allow()  # обычный ввод в терминале — не трогаем

    attrs = dict(ATTR_RE.findall(m.group(1)))
    text = m.group(2).strip()
    tf = ""
    try:
        fd, tf = tempfile.mkstemp(prefix="ccq_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        r = subprocess.run(
            [sys.executable, QUEUE_CLI, "enqueue",
             "--chat", attrs.get("chat_id") or "",
             "--msg-id", attrs.get("message_id") or "",
             "--user", attrs.get("user") or "",
             "--ts", attrs.get("ts") or "",
             "--text-file", tf],
            capture_output=True, text=True, timeout=30)
    except Exception as e:
        log("enqueue failed: %s — passing through" % e)
        allow()
    finally:
        if tf:
            try:
                os.unlink(tf)
            except Exception:
                pass

    if r.returncode != 10:
        log("gate green: %s" % (r.stdout or "").strip())
        allow()

    log("QUEUED msg %s: %s" % (attrs.get("message_id"), (r.stdout or "").strip()))
    block("Limit windows are burnt. The incoming message was saved to the queue "
          "(%s) and the sender has already been told so. Do nothing and do not reply — "
          "the session is paused until the window resets; the queue will be worked "
          "through after pause_ctl wakes it up." % os.path.join(CCL, "tg_queue.jsonl"))


if __name__ == "__main__":
    main()
