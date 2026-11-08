#!/usr/bin/env python3
"""[notion-ai] 05.11.26. Мост «общий чат Telegram (бот Claude) -> постоянный чат Notion AI».
Работает, только пока включён профиль «Notion AI · только он» (/opt/cc-limits/notion_ai_mode.json).
Claude Code в это время остановлен, поэтому getUpdates бота слушает только этот мост.
Сообщения владельца (allowFrom из access.json) пачкой уходят через notion-delegate (/post) в чат Notion AI.
Голосовые расшифровываются ccfleet-transcribe (voice/install.sh; на серверах с ручной установкой — /root/tts/transcribe.sh), фото и файлы сохраняются в /root/notion_ai_inbox.
Доставку в Notion отмечает реакция 👀; ответы Notion AI отправляет сам командой notion-ai-reply.
Кнопки шагов оркестратора (callback nai:ok:<id> / nai:no:<id>) передаются в балансер: POST /api/notion-ai/step/confirm."""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

MODE = "/opt/cc-limits/notion_ai_mode.json"
ENV = "/root/.claude/channels/telegram/.env"
ACCESS = "/root/.claude/channels/telegram/access.json"
STATE = "/root/notion_web/notion_ai_tg_state.json"
LOG = "/root/notion_web/notion_ai_tg.log"
INBOX = "/root/notion_ai_inbox"
DELEGATE = "http://127.0.0.1:8893"
DTOKEN = "/root/notion_web/api_token"
CC_CONFIG = "/opt/cc-limits/config.json"
UPDATES = ["message", "callback_query"]
IRK = 8 * 3600
FOOT = "\n\n— из Telegram (общий чат). Ответ: notion-ai-reply на сервере (текст + голос)."
NAI_CFG = "/opt/cc-limits/notion_ai.json"  # tg_agent — агент, которому идут сообщения из Telegram (пусто — главный агент Notion AI)
NAGENTS = "/root/notion_web/nagents.json"
BATCH_WAIT = 2  # [notion-ai] пачка: альбом и пару сообщений подряд отправляем одним куском
MAX_FILE = 20 * 1024 * 1024


def log(msg):
    with open(LOG, "a") as f:
        f.write(time.strftime("%d.%m %H:%M:%S ") + msg + "\n")


def mode():
    try:
        return json.load(open(MODE))
    except Exception:
        return {}


def bot_token():
    m = re.search(r"TELEGRAM_BOT_TOKEN=(\S+)", open(ENV).read())
    if not m:
        sys.exit("нет TELEGRAM_BOT_TOKEN")
    return m.group(1)


TOKEN = bot_token()


def allowed():
    try:
        return {str(x) for x in json.load(open(ACCESS)).get("allowFrom") or []}
    except Exception:
        return set()


def tg(method, payload, timeout=40):
    req = urllib.request.Request("https://api.telegram.org/bot%s/%s" % (TOKEN, method),
                                 data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def say(chat, text):
    try:
        tg("sendMessage", {"chat_id": chat, "text": text}, 20)
    except Exception as e:
        log("sendMessage fail %s" % type(e).__name__)


def react(chat, mid):
    try:
        tg("setMessageReaction", {"chat_id": chat, "message_id": mid, "reaction": [{"type": "emoji", "emoji": "👀"}]}, 15)
    except Exception:
        pass


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"offset": 0}


def save_state(s):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE)


def download(file_id, name_hint):
    info = tg("getFile", {"file_id": file_id}, 30).get("result") or {}
    if int(info.get("file_size") or 0) > MAX_FILE or not info.get("file_path"):
        return None
    os.makedirs(INBOX, mode=0o700, exist_ok=True)
    ext = os.path.splitext(info["file_path"])[1] or ""
    path = os.path.join(INBOX, time.strftime("%Y%m%d_%H%M%S_") + re.sub(r"[^\w.-]", "_", name_hint)[:60] + ext)
    with urllib.request.urlopen("https://api.telegram.org/file/bot%s/%s" % (TOKEN, info["file_path"]), timeout=120) as r:
        data = r.read(MAX_FILE + 1)
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, 0o600)
    return path


def transcribe_tool():
    for p in ("/usr/local/bin/ccfleet-transcribe", "/root/tts/transcribe.sh"):
        if os.path.exists(p):
            return p
    return "/usr/local/bin/ccfleet-transcribe"


def transcribe(path):
    try:
        r = subprocess.run([transcribe_tool(), path], capture_output=True, text=True, timeout=300)
        return (r.stdout or "").strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def hhmm(ts, full=False):
    return time.strftime("%d.%m %H:%M" if full else "%H:%M", time.gmtime(ts + IRK))


def describe(m, since):
    parts = []
    text = (m.get("text") or m.get("caption") or "").strip()
    if m.get("forward_origin") or m.get("forward_from") or m.get("forward_sender_name"):
        parts.append("(переслано)")
    rep = m.get("reply_to_message")
    if rep:
        q = (rep.get("text") or rep.get("caption") or "").strip().replace("\n", " ")
        parts.append("(в ответ на: «%s»)" % (q[:300] + ("…" if len(q) > 300 else "")) if q else "(в ответ на сообщение)")
    for kind in ("voice", "audio"):
        if kind in m:
            p = download(m[kind]["file_id"], kind)
            tr = transcribe(p) if p else ""
            parts.append("(голосовое, расшифровка) " + tr if tr else "(голосовое не расшифровалось: %s)" % (p or "файл больше 20 МБ"))
    if m.get("photo"):
        p = download(m["photo"][-1]["file_id"], "photo")
        parts.append("(фото: %s)" % (p or "больше 20 МБ"))
    for kind in ("document", "video", "video_note", "animation"):
        if kind in m:
            p = download(m[kind]["file_id"], m[kind].get("file_name") or kind)
            parts.append("(%s: %s)" % ({"document": "файл", "video": "видео", "video_note": "кружок", "animation": "гиф"}[kind], p or "больше 20 МБ"))
    if m.get("sticker"):
        parts.append("(стикер %s)" % (m["sticker"].get("emoji") or ""))
    if m.get("location"):
        parts.append("(геопозиция %s, %s)" % (m["location"].get("latitude"), m["location"].get("longitude")))
    if text:
        parts.append(text)
    ts = int(m.get("date") or time.time())
    head = "[TG %s]" % hhmm(ts) if ts >= since - 30 else "[TG %s, отправлено до включения профиля]" % hhmm(ts, True)
    return head + " " + (" ".join(parts) or "(пустое сообщение)")


def dcall(path, data=None, timeout=30):
    req = urllib.request.Request(DELEGATE + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"X-Token": open(DTOKEN).read().strip(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def tg_agent():
    """(aid, имя) агента, принимающего сообщения из Telegram; (None, None) — главный агент. Агента, которого нет в реестре, не берём."""
    try:
        aid = str(json.load(open(NAI_CFG)).get("tg_agent") or "").strip()
        a = (json.load(open(NAGENTS)).get("agents") or {}).get(aid) if aid else None
    except Exception:
        return None, None
    return (aid, a.get("name") or "") if a and a.get("name") else (None, None)


def post(text, aid=None):
    """Отправить в чат Notion AI (или выбранного агента); True — доставлено."""
    j = dcall("/post", dict(text=text, **({"aid": aid} if aid else {})))
    if not j.get("id"):
        raise RuntimeError(j.get("error") or "notion-delegate не принял сообщение")
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(1)
        st = dcall("/post/" + j["id"])
        if st.get("status") == "done":
            return True
        if st.get("status") == "error":
            raise RuntimeError(st.get("error") or "ошибка отправки")
    raise RuntimeError("Notion не принял сообщение за 15 минут")


def cc_confirm(sid, approve):
    cfg = json.load(open(CC_CONFIG))
    req = urllib.request.Request("http://127.0.0.1:%s/api/notion-ai/step/confirm" % cfg.get("port", 8877),
                                 data=json.dumps({"id": sid, "approve": approve, "via": "Telegram"}).encode(),
                                 headers={"X-CC-Token": cfg.get("hook_token", ""), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def callback(cq, who):
    """Кнопка шага под сообщением бота: только от владельца, решение — в балансер."""
    uid = str((cq.get("from") or {}).get("id") or "")
    data = cq.get("data") or ""
    m = re.fullmatch(r"nai:(ok|no):([0-9a-f]{6,32})", data)
    text = "Кнопка устарела."
    if uid in who and m:
        try:
            j = cc_confirm(m.group(2), m.group(1) == "ok")
            text = j.get("message") or ("Готово" if j.get("ok") else "Не получилось")
        except Exception as e:
            text = "Балансер не ответил: %s" % type(e).__name__
        log("кнопка шага %s %s: %s" % (m.group(1), m.group(2), text[:120]))
    elif uid not in who:
        text = "Нет доступа."
    try:
        tg("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": text[:190]}, 20)
    except Exception:
        pass


PLUGIN_MARK = "claude-plugins-official/telegram"


def _cmdline(pid, proc="/proc"):
    try:
        with open("%s/%s/cmdline" % (proc, pid), "rb") as f:
            return [x.decode("utf-8", "replace") for x in f.read().split(b"\0") if x]
    except OSError:
        return []


def claude_plugin_pids(proc="/proc"):
    """PID Telegram-плагина Claude (bun/node с путём плагина). Шеллы и grep с этой строкой не считаются."""
    out = set()
    for pid in os.listdir(proc):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        argv = _cmdline(pid, proc)
        if argv and PLUGIN_MARK in " ".join(argv) and os.path.basename(argv[0]).startswith(("bun", "node")):
            out.add(pid)
    return frozenset(out)


def _children(pids, proc="/proc"):
    """Все потомки процессов pids (сервер плагина — дочерний bun)."""
    parent = {}
    for pid in os.listdir(proc):
        if pid.isdigit():
            try:
                with open("%s/%s/stat" % (proc, pid)) as f:
                    parent[pid] = f.read().rsplit(")", 1)[1].split()[1]
            except (OSError, IndexError):
                pass
    found, todo = set(pids), list(pids)
    while todo:
        p = todo.pop()
        for c, pp in parent.items():
            if pp == p and c not in found:
                found.add(c)
                todo.append(c)
    return found


def claude_plugin_off():
    """[notion-ai] 06.11, правило владельца: при профиле Notion AI Claude Telegram не слушает.
    Запущенному вручную Claude отключаем плагин (SIGTERM ему и потомкам); сам Claude остаётся в консоли."""
    pids = claude_plugin_pids()
    if not pids:
        return []
    killed = []
    for pid in sorted(_children(pids), key=int):
        try:
            os.kill(int(pid), 15)
            killed.append(pid)
        except OSError:
            pass
    log("Claude слушал бота при профиле Notion AI — плагин Telegram остановлен (PID %s)" % ",".join(killed))
    return killed


def claude_plugin_running():
    return bool(claude_plugin_pids())


def main():
    st = load_state()
    who = allowed()
    log("старт, offset=%s" % st.get("offset"))
    fails = 0
    last_warn = 0
    while True:
        md = mode()
        if not md.get("active"):
            log("профиль Notion AI выключен — выхожу")
            return 0
        since = float(md.get("since") or 0)
        if claude_plugin_off() and time.time() - last_warn > 1800:
            last_warn = time.time()
            for chat in who:
                say(chat, "⚠️ Claude запустили при профиле Notion AI — отключил ему Telegram, чтобы бота слушал один агент. "
                          "Claude остаётся в консоли без бота. Вернуть Claude в Telegram: выключи профиль Notion AI "
                          "(кнопка «Notion AI» в шапке панели или notion-ai-mode off).")
        try:
            ups = tg("getUpdates", {"offset": st.get("offset", 0), "timeout": 20, "allowed_updates": UPDATES}, 35).get("result") or []
            if ups:
                time.sleep(BATCH_WAIT)
                more = tg("getUpdates", {"offset": ups[-1]["update_id"] + 1, "timeout": 0, "allowed_updates": UPDATES}, 20).get("result") or []
                ups += more
        except urllib.error.HTTPError as e:
            log("getUpdates HTTP %s" % e.code)
            time.sleep(10 if e.code == 409 else 5)
            continue
        except Exception as e:
            log("getUpdates %s" % type(e).__name__)
            time.sleep(5)
            continue
        if not ups:
            continue
        lines, marks, chat = [], [], None
        for u in ups:
            if u.get("callback_query"):
                callback(u["callback_query"], who)
                continue
            m = u.get("message") or {}
            cid = str((m.get("chat") or {}).get("id") or "")
            uid = str((m.get("from") or {}).get("id") or "")
            if not m or uid not in who or cid != uid:
                continue
            chat = cid
            try:
                lines.append(describe(m, since))
            except Exception as e:
                lines.append("[TG] (сообщение не разобрано: %s)" % type(e).__name__)
            marks.append(m["message_id"])
        nxt = ups[-1]["update_id"] + 1
        if lines:
            aid, aname = tg_agent()
            text = "\n\n".join(lines) + (FOOT.replace("notion-ai-reply на сервере", 'notion-ai-reply --agent "%s" на сервере' % aname.replace('"', "'")) if aid else FOOT)
            try:
                post(text, aid)
                fails = 0
                for mid in marks:
                    react(chat, mid)
                log("доставлено %d сообщ. (%d симв.)" % (len(lines), len(text)))
            except Exception as e:
                fails += 1
                log("не доставлено (%d): %s" % (fails, str(e)[:200]))
                if fails in (1, 4) or fails % 10 == 0:
                    say(chat, "⚠️ Не смог передать сообщение в Notion AI: %s. Повторяю." % str(e)[:200])
                time.sleep(min(20 * fails, 120))
                continue  # offset не двигаем — эти же сообщения придут снова
        st["offset"] = nxt
        save_state(st)
        try:  # подтвердить Telegram, что эти апдейты забраны (иначе Claude получит их повторно)
            tg("getUpdates", {"offset": nxt, "timeout": 0, "limit": 1, "allowed_updates": UPDATES}, 20)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
