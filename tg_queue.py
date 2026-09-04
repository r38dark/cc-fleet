#!/usr/bin/env python3
# Очередь входящих сообщений на время, пока все окна лимитов сожжены.
#
# Зачем: у чата с Claude Code нет очереди — каждое входящее сообщение будит сессию,
# та немедленно берётся за работу и добивает остаток окна. Пользователь при этом
# уверен, что его сообщения «копятся» и будут разобраны позже. Этот модуль делает
# такое поведение настоящим: пока гейт «красный», сообщение не доходит до модели —
# оно ложится в tg_queue.jsonl, а отправителю отвечает сам скрипт (значит без
# расхода токенов). Разбор — когда pause_ctl поднимет сессию после сброса окна.
#
# Вызывается из хука UserPromptSubmit (hooks/queue_on_limits.py), но работает и руками.
#
# Команды:
#   tg_queue.py enqueue --chat ID --msg-id N --user U [--ts ISO] [--text-file F]
#         rc=0  — гейт зелёный, ничего не поставлено, отдавать сообщение модели
#         rc=10 — поставлено в очередь; на stdout текст ответа отправителю
#   tg_queue.py count [--json] / list / take / clear
import argparse
import json
import os
import sys
import time
from datetime import datetime

BASE = os.environ.get("CC_LIMITS_BASE", os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(BASE, "tg_queue.jsonl")
CONFIG = os.path.join(BASE, "config.json")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Ответ отправителю, пока идёт пауза. Переопределяется ключом "queue_ack_message"
# в config.json; подставляются {n} — сколько сообщений ждёт, {line} — проценты окон,
# {when} — время планового подъёма.
ACK_MSG = ("Got it, queued ({n} waiting). All limit windows are burnt ({line}); "
           "I will be back around {when} and work through them in order.")


def _cfg():
    try:
        d = json.load(open(CONFIG))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _pause():
    """pause_ctl импортом, а не подпроцессом — хук висит на каждом сообщении."""
    import pause_ctl
    return pause_ctl


def _rows():
    out = []
    try:
        with open(QUEUE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return out


def _pending(rows=None):
    return [r for r in (rows if rows is not None else _rows()) if not r.get("taken_ts")]


def _rewrite(rows):
    tmp = QUEUE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, QUEUE)


def _hm(ts):
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%H:%M")
    except Exception:
        return "?"


def blocked_now():
    """(блокировать?, level, строка процентов, iso ближайшего сброса).

    Блокируем только когда работать реально негде:
      hard  — все аккаунты выше порога;
      пауза — сессия уже стоит и ждёт будильника.
    level == "gate" (активный сожжён, но свободный есть) НЕ блокируем: балансер
    переключится на следующем тике и работа поедет дальше.
    """
    st = _pause().level_state()
    lvl = st.get("level")
    paused = bool((st.get("pause") or {}).get("active"))
    iso = (st.get("nearest") or {}).get("resets_at") or ""
    return (lvl == "hard" or paused), lvl, st.get("line") or "", iso


def cmd_enqueue(a):
    blocked, lvl, line, iso = blocked_now()
    if not blocked:
        print("gate is green (%s) — passing through" % (line or lvl))
        return 0

    text = ""
    if a.text_file:
        try:
            text = open(a.text_file, encoding="utf-8").read()
        except Exception:
            text = ""
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read()

    rows = _rows()
    key = (str(a.chat), str(a.msg_id))
    dup = bool(a.msg_id) and any(
        (str(r.get("chat_id")), str(r.get("message_id"))) == key for r in rows)
    if not dup:
        rows.append({
            "ts": time.time(),
            "chat_id": str(a.chat),
            "message_id": str(a.msg_id or ""),
            "user": a.user or "",
            "src_ts": a.ts or "",
            "text": text.strip(),
            "gate": line,
            "taken_ts": 0,
        })
        _rewrite(rows)

    # первое сообщение в очереди поднимает паузу — иначе cron-будильник нас не разбудит
    pc = _pause()
    if not (pc.load() or {}).get("active"):
        try:
            pc.cmd_set(argparse.Namespace(
                reason="limit windows burnt",
                resume_at="",
                note="incoming queue: %d message(s)" % len(_pending(rows)),
            ))
        except Exception as e:
            print("could not start the pause: %s" % e, file=sys.stderr)

    n = len(_pending(rows))
    when = ""
    try:
        when = datetime.fromisoformat(iso).astimezone().strftime("%H:%M") if iso else ""
    except Exception:
        when = ""
    resume = (pc.load() or {}).get("resume_at") or 0
    if resume:
        when = _hm(resume)
    tmpl = _cfg().get("queue_ack_message") or ACK_MSG
    try:
        ack = tmpl.format(n=n, line=line or "?", when=when or "?")
    except Exception:
        ack = tmpl
    print(ack)
    if a.notify:
        try:
            pc._tg(ack, force=bool(_cfg().get("queue_ack", True)))
        except Exception as e:
            print("ack not delivered: %s" % e, file=sys.stderr)
    return 10


def cmd_count(a):
    p = _pending()
    if a.json:
        print(json.dumps({"pending": len(p)}, ensure_ascii=False))
    else:
        print(len(p))
    return 0


def _dump(rows):
    for i, r in enumerate(rows, 1):
        print("%d) %s msg %s from %s:\n%s\n" % (
            i, _hm(r.get("ts")), r.get("message_id") or "?", r.get("user") or "?",
            (r.get("text") or "").strip() or "(empty)"))


def cmd_list(_a):
    p = _pending()
    if not p:
        print("queue is empty")
        return 0
    print("%d message(s) queued:" % len(p))
    _dump(p)
    return 0


def cmd_take(_a):
    rows = _rows()
    p = _pending(rows)
    if not p:
        print("queue is empty")
        return 0
    print("%d message(s) queued (marked as taken):" % len(p))
    _dump(p)
    now = time.time()
    for r in p:
        r["taken_ts"] = now
    _rewrite(rows)
    return 0


def cmd_clear(_a):
    rows = _rows()
    p = _pending(rows)
    now = time.time()
    for r in p:
        r["taken_ts"] = now
    _rewrite(rows)
    print("dropped %d message(s)" % len(p))
    return 0


def main():
    ap = argparse.ArgumentParser(description="incoming queue while limits are burnt")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("enqueue")
    s.add_argument("--chat", required=True)
    s.add_argument("--msg-id", default="", dest="msg_id")
    s.add_argument("--user", default="")
    s.add_argument("--ts", default="")
    s.add_argument("--text-file", default="", dest="text_file")
    s.add_argument("--no-notify", action="store_false", dest="notify",
                   help="не отправлять подтверждение отправителю")
    s.set_defaults(fn=cmd_enqueue, notify=True)

    s = sub.add_parser("count")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_count)

    s = sub.add_parser("list")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("take")
    s.set_defaults(fn=cmd_take)

    s = sub.add_parser("clear")
    s.set_defaults(fn=cmd_clear)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
