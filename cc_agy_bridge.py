"""Telegram bridge for Antigravity (agy) inside cc-fleet: IPv4 keep-alive, HTML, media, PNG limits card, FIFO queue."""
import datetime as dt
import html
import http.client
import io
import json
import os
import queue as std_queue
import re
import secrets
import socket
import ssl
import threading
import time
import urllib.parse
from pathlib import Path

import cc_agy
import cc_agy_console
from cc_input_queue import InputQueue

BASE = "/opt/cc-limits"
LIMIT_PAUSE = lambda: {}
LIMIT_PUBLIC = lambda: {}
LIMIT_CONFIGURE = lambda body: (False, "Лимиты недоступны.")
RESERVED_TOKENS = lambda: set()
CONSOLE = cc_agy_console

TG_TIMEOUT = 15
TG_FILE_MAX_BYTES = 20 * 1024 * 1024
OUT_IMAGE_MAX_BYTES = 10 * 1024 * 1024
OUT_IMAGE_MAX_COUNT = 8
ATTACHMENT_KEEP_DAYS = 7
WORK_QUEUE_MAX = 20
LIM_EVERY = 300
LIM_WARN = 90
LIM_CLEAR = 80
SUB_STEPS = (7, 3, 1, 0)

_ROBOTO_DIR = Path("/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF")
_DEJAVU_DIR = Path("/usr/share/fonts/truetype/dejavu")
_RU_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

_CODE_BLOCK_RE = re.compile(r"```(?:[^\n`]*)\n(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_ITALIC_RE = re.compile(r"(?<!\w)\*([^\s*](?:[^*\n]*[^\s*])?)\*(?!\w)")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_HR_RE = re.compile(r"^\s*[-*_]{3,}\s*$", re.MULTILINE)
_OUT_IMAGE_RE = re.compile(r"^[ \t]*!\[([^\]\r\n]*)\]\((?:<([^<>\r\n]+)>|([^()\r\n]+))\)[ \t]*$")
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

MEDIA_FIELDS = {
    "document": "file",
    "audio": "audio.mp3",
    "video": "video.mp4",
    "animation": "animation.mp4",
    "video_note": "video_note.mp4",
    "voice": "voice.ogg",
}


def _mask(text):
    return re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot<hidden>", str(text or ""))


def _cfg_path():
    return os.path.join(BASE, "agy_bridge.json")


def _state_path():
    return os.path.join(BASE, "agy_bridge_state.json")


def _queue_path():
    return os.path.join(BASE, "agy_input_queue.json")


def _inbox_dir():
    return Path(BASE) / "agy_inbox"


def load():
    data = cc_agy.jload(_cfg_path(), {}) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("enabled", False)
    data.setdefault("token", "")
    data.setdefault("chat_id", "")
    data.setdefault("workdir", "/root")
    return data


def save(updates):
    cur = load()
    for k, v in (updates or {}).items():
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    cc_agy.jsave(_cfg_path(), cur, mode=0o600)
    return cur


def _load_state():
    data = cc_agy.jload(_state_path(), {}) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("offset", 0)
    data.setdefault("alerts", {})
    return data


def _save_state(st):
    cc_agy.jsave(_state_path(), st, mode=0o600)


def public():
    s = load()
    st = _load_state()
    tok = str(s.get("token") or "").strip()
    return {
        "enabled": bool(s.get("enabled")),
        "has_token": bool(tok),
        "token_hint": (tok[:6] + "…" + tok[-4:]) if len(tok) > 12 else ("set" if tok else ""),
        "chat_id": str(s.get("chat_id") or ""),
        "workdir": str(s.get("workdir") or "/root"),
        "bot": st.get("bot") or {},
        "last_error": str(st.get("last_error") or ""),
        "running": BRIDGE.is_running(),
        "queued": len(BRIDGE.inputs),
    }


def set_token(token):
    tok = str(token or "").strip()
    if not re.fullmatch(r"\d{5,15}:[A-Za-z0-9_-]{20,80}", tok):
        return False, "Неверный формат токена Telegram-бота."
    if tok in (RESERVED_TOKENS() or set()):
        return False, "Этот токен уже используется Claude или Codex. Для Antigravity нужен отдельный бот."
    save({"token": tok})
    BRIDGE.sync()
    return True, "Токен бота Antigravity сохранён."


def clear_token():
    save({"token": "", "enabled": False})
    BRIDGE.sync()
    return True, "Токен бота Antigravity удалён."


def save_settings(body):
    updates = {}
    if "enabled" in body:
        updates["enabled"] = bool(body["enabled"])
    if "chat_id" in body:
        cid = str(body["chat_id"] or "").strip()
        if cid and not re.fullmatch(r"-?\d{3,20}", cid):
            return False, "Неверный формат chat_id."
        updates["chat_id"] = cid
    if "workdir" in body:
        wd = str(body["workdir"] or "").strip()
        if wd and not os.path.isdir(wd):
            return False, f"Папка не найдена: {wd}"
        if wd:
            updates["workdir"] = os.path.realpath(wd)
    save(updates)
    if updates.get("workdir"):
        CONSOLE.request_settings({"workdir": updates["workdir"]})
    BRIDGE.sync()
    return True, "Настройки Telegram-моста Antigravity сохранены."


# ---------------------------------------------------------------- Markdown -> Telegram HTML
def markdown_to_telegram_html(text):
    placeholders = {}

    def put(rendered):
        key = f"\x00PH{len(placeholders)}\x00"
        placeholders[key] = rendered
        return key

    def repl_code(m):
        return put(f"<pre><code>{html.escape(m.group(1).rstrip(chr(10)), quote=False)}</code></pre>")

    def repl_inline(m):
        return put(f"<code>{html.escape(m.group(1), quote=False)}</code>")

    def repl_link(m):
        label, url = m.group(1), m.group(2)
        if url.startswith(("http://", "https://")):
            return put(f'<a href="{html.escape(url, quote=True)}">{html.escape(label, quote=False)}</a>')
        return put(f"<code>{html.escape(label, quote=False)}</code>")

    work = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    work = _CODE_BLOCK_RE.sub(repl_code, work)
    work = _INLINE_CODE_RE.sub(repl_inline, work)
    work = _LINK_RE.sub(repl_link, work)
    work = html.escape(work, quote=False)

    out_lines, qbuf = [], []

    def flush_q():
        if qbuf:
            out_lines.append("<blockquote>" + "\n".join(qbuf) + "</blockquote>")
            qbuf.clear()

    for line in work.split("\n"):
        qm = re.match(r"^&gt;\s?(.*)$", line)
        if qm:
            qbuf.append(qm.group(1))
            continue
        flush_q()
        bm = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        if bm:
            ind = bm.group(1)
            out_lines.append(("  ◦ " if len(ind) >= 2 else "• ") + bm.group(2))
            continue
        out_lines.append(line)
    flush_q()
    work = "\n".join(out_lines)

    work = _HR_RE.sub("──────────", work)
    work = _HEADING_RE.sub(r"<b>\1</b>", work)
    work = _BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", work)
    work = _ITALIC_RE.sub(r"<i>\1</i>", work)
    work = _STRIKE_RE.sub(r"<s>\1</s>", work)

    for key, rendered in placeholders.items():
        work = work.replace(key, rendered)
    return re.sub(r"\n{3,}", "\n\n", work).strip()


def split_markdown_chunks(text, limit=3400):
    cleaned = (text or "").strip() or "(пустой ответ)"
    if len(cleaned) <= limit:
        return [cleaned]
    chunks = []
    rem = cleaned
    while len(rem) > limit:
        cut = rem.rfind("\n\n", 0, limit)
        if cut < limit // 3:
            cut = rem.rfind("\n", 0, limit)
        if cut < limit // 3:
            cut = rem.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        part = rem[:cut].rstrip()
        rest = rem[cut:].lstrip("\n")
        fences = re.findall(r"^```[^\n]*", part, flags=re.MULTILINE)
        if len(fences) % 2 == 1:
            part += "\n```"
            rest = fences[-1] + "\n" + rest
        chunks.append(part)
        rem = rest
    if rem:
        chunks.append(rem)
    return chunks


# ---------------------------------------------------------------- Media helpers & PNG card
def _detect_img_ext(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"BM"):
        return "bmp"
    return None


def _safe_filename(name, fallback="file"):
    base = Path(str(name or "").replace("\\", "/")).name.strip()
    cleaned = re.sub(r"[^A-Za-z0-9._\-\u0400-\u04FF]", "_", base).lstrip(".")[:120]
    return cleaned or fallback


def _prune_old(directory):
    cutoff = time.time() - ATTACHMENT_KEEP_DAYS * 86400
    try:
        for entry in Path(directory).iterdir():
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink(missing_ok=True)
    except OSError:
        pass


def _prepare_photo_payload(path, caption=""):
    raw = Path(path).read_bytes()
    ext = _detect_img_ext(raw)
    if ext in ("png", "jpg") and len(raw) <= OUT_IMAGE_MAX_BYTES:
        return Path(path).name, raw, ("image/png" if ext == "png" else "image/jpeg"), caption
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as im:
        if im.width > 4096 or im.height > 4096:
            im.thumbnail((4096, 4096))
        if im.mode in ("RGBA", "LA", "P"):
            buf = io.BytesIO()
            im.convert("RGBA").save(buf, format="PNG", optimize=True)
            data = buf.getvalue()
            if len(data) <= OUT_IMAGE_MAX_BYTES:
                return f"{Path(path).stem}.png", data, "image/png", caption
        rgb = im.convert("RGB")
        for q in (92, 85, 75, 65):
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=q, optimize=True)
            data = buf.getvalue()
            if len(data) <= OUT_IMAGE_MAX_BYTES:
                return f"{Path(path).stem}.jpg", data, "image/jpeg", caption
    raise RuntimeError("Картинка превышает 10 МБ для Telegram.")


def extract_outgoing_images(text, workdir):
    lines_out, images, seen = [], [], set()
    fence, fence_len = "", 0
    for line in str(text or "").splitlines(keepends=True):
        marker = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line)
        if marker:
            run = marker.group(1)
            if not fence:
                fence, fence_len = run[0], len(run)
            elif run[0] == fence and len(run) >= fence_len and not line[marker.end() :].strip():
                fence = ""
            lines_out.append(line)
            continue
        m = None if fence else _OUT_IMAGE_RE.fullmatch(line.rstrip("\r\n"))
        if not m:
            lines_out.append(line)
            continue
        caption = (m.group(1) or "").strip()
        ref = (m.group(2) or m.group(3) or "").strip()
        parsed = urllib.parse.urlsplit(ref)
        if parsed.scheme in ("http", "https"):
            lines_out.append(line)
            continue
        if parsed.scheme == "file":
            ref = urllib.parse.unquote(parsed.path)
        elif ref.startswith("sandbox:"):
            ref = ref[len("sandbox:") :]
        cand = Path(ref) if os.path.isabs(ref) else (Path(workdir) / ref)
        try:
            resolved = cand.resolve(strict=True)
        except OSError:
            lines_out.append(line)
            continue
        if not resolved.is_file() or resolved in seen:
            continue
        if resolved.suffix.lower() not in _IMAGE_EXTS:
            try:
                if not _detect_img_ext(resolved.read_bytes()[:16]):
                    lines_out.append(line)
                    continue
            except OSError:
                lines_out.append(line)
                continue
        if len(images) >= OUT_IMAGE_MAX_COUNT:
            continue
        try:
            images.append(_prepare_photo_payload(resolved, caption))
            seen.add(resolved)
            if caption:
                lines_out.append(f"🖼 {caption}" + ("\n" if line.endswith("\n") else ""))
        except Exception as exc:
            lines_out.append(f"⚠️ Не удалось отправить картинку {resolved.name}: {exc}\n")
    return "".join(lines_out).strip(), images


def _plural_days(n):
    na = abs(int(n))
    if 11 <= (na % 100) <= 19:
        return f"{n} дней"
    rem = na % 10
    if rem == 1:
        return f"{n} день"
    if 2 <= rem <= 4:
        return f"{n} дня"
    return f"{n} дней"


def _fmt_toks(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_reset_iso(iso):
    if not iso:
        return "Доступно"
    try:
        target = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return "Время не получено"
    now = dt.datetime.now().astimezone()
    wd = _RU_WEEKDAYS[target.weekday()]
    if target.date() == now.date():
        return f"сегодня {target.strftime('%H:%M')}"
    if (target.date() - now.date()).days == 1 and (target - now).total_seconds() < 36 * 3600:
        return f"завтра {target.strftime('%H:%M')}"
    return f"{wd} {target.strftime('%d.%m %H:%M')}"


def render_limits_card_png(account, ctx_stats, is_running, is_busy, pause_info):
    """Render compact Gemini-only dark PNG limits card."""
    from PIL import Image, ImageDraw, ImageFont

    def font(weight, size):
        paths = {
            "bold": [_ROBOTO_DIR / "Roboto-Bold.ttf", _DEJAVU_DIR / "DejaVuSans-Bold.ttf"],
            "medium": [_ROBOTO_DIR / "Roboto-Medium.ttf", _ROBOTO_DIR / "Roboto-Regular.ttf", _DEJAVU_DIR / "DejaVuSans.ttf"],
            "regular": [_ROBOTO_DIR / "Roboto-Regular.ttf", _DEJAVU_DIR / "DejaVuSans.ttf"],
        }[weight]
        for p in paths:
            if p.is_file():
                try:
                    return ImageFont.truetype(str(p), size)
                except OSError:
                    pass
        return ImageFont.load_default()

    W, H = 860, 548
    img = Image.new("RGB", (W, H), (19, 23, 32))
    draw = ImageDraw.Draw(img)
    pad = 24
    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=20, fill=(23, 28, 40), outline=(40, 49, 68), width=2)

    f_title, f_badge, f_email = font("bold", 34), font("bold", 19), font("regular", 23)
    f_pill, f_pill_b = font("medium", 21), font("bold", 21)
    f_sec, f_sec_sub = font("bold", 22), font("regular", 18)
    f_label, f_pct, f_meta, f_foot = font("regular", 23), font("bold", 25), font("regular", 20), font("regular", 18)

    c_white, c_muted, c_gold, c_red = (242, 245, 250), (139, 152, 176), (246, 196, 83), (248, 113, 113)
    x0, inner_w, y = pad + 34, W - 2 * (pad + 34), pad + 30

    def pill(px, py, parts, bg, border=None, px_pad=16, py_pad=9, rad=11):
        tw = mh = 0
        ws = []
        for t, _, f in parts:
            bb = draw.textbbox((0, 0), t, font=f)
            ws.append(bb[2] - bb[0])
            tw += bb[2] - bb[0]
            mh = max(mh, bb[3] - bb[1])
        box = [px, py, px + tw + px_pad * 2, py + mh + py_pad * 2 + 2]
        draw.rounded_rectangle(box, radius=rad, fill=bg, outline=border, width=2 if border else 0)
        cx = px + px_pad
        for (t, col, f), w in zip(parts, ws):
            draw.text((cx, py + py_pad - 1), t, fill=col, font=f)
            cx += w
        return box[2]

    draw.text((x0, y), "Antigravity", fill=c_white, font=f_title)
    tb = draw.textbbox((0, 0), "Antigravity", font=f_title)
    pill(x0 + (tb[2] - tb[0]) + 16, y + 4, [(str(account.get("plan_label") or "PRO"), c_muted, f_badge)], (28, 34, 48), (58, 69, 92), 13, 5, 8)
    y += 50
    draw.text((x0, y), str(account.get("email") or "Google AI"), fill=c_muted, font=f_email)
    y += 42

    sub_d = cc_agy.parse_sub_date(account.get("sub_until") or cc_agy.DEFAULT_SUB_UNTIL)
    if sub_d:
        left = (sub_d - dt.date.today()).days
        sval = f"истекла {sub_d.strftime('%d.%m')}" if left < 0 else f"{sub_d.strftime('%d.%m')} · {_plural_days(left)}"
        scol = c_red if left <= 2 else c_gold
        sbdr = (115, 48, 54) if left <= 2 else (106, 92, 54)
        nx = pill(x0, y, [("Подписка до ", c_muted, f_pill), (sval, scol, f_pill_b)], (27, 32, 44), sbdr)
    else:
        nx = pill(x0, y, [("Подписка: ", c_muted, f_pill), ("задайте /sub", c_gold, f_pill_b)], (27, 32, 44), (62, 72, 94))

    if (pause_info or {}).get("active"):
        st_txt, st_bg, st_fg = ("Лимит 100%" if pause_info.get("hard") else "Пауза по лимитам"), (92, 34, 42), c_red
    elif is_busy:
        st_txt, st_bg, st_fg = "Выполняет задачу", (68, 52, 20), (251, 191, 36)
    elif is_running:
        st_txt, st_bg, st_fg = "Работает здесь", (22, 66, 48), (74, 222, 128)
    else:
        st_txt, st_bg, st_fg = "Остановлен", (52, 58, 72), c_muted
    pill(nx + 14, y, [(st_txt, st_fg, f_pill_b)], st_bg, None, 18, 9, 11)
    y += 58

    mod_txt = str(account.get("model") or cc_agy.cli_default_model() or "по умолчанию")
    ctoks = int((ctx_stats or {}).get("context_tokens") or 0)
    turns = int((ctx_stats or {}).get("turns") or 0)
    clbl = f" · Контекст {_fmt_toks(ctoks)} ({turns} сообщ.)" if ctoks > 0 else ""
    pill(x0, y, [("Модель: ", c_muted, f_pill), (mod_txt, c_white, f_pill_b), (clbl, c_muted, f_pill)], (28, 35, 50), (50, 62, 84), 16, 8, 11)
    y += 62

    draw.line([(x0, y), (x0 + inner_w, y)], fill=(38, 46, 64), width=2)
    y += 22
    draw.text((x0, y), "Gemini", fill=c_white, font=f_sec)
    gb = draw.textbbox((0, 0), "Gemini", font=f_sec)
    draw.text((x0 + (gb[2] - gb[0]) + 12, y + 4), "Neon · Carbon · Hydrogen", fill=c_muted, font=f_sec_sub)
    y += 40

    wins = {w.get("mins"): w for w in (account.get("windows") or [])}
    for mins, label in ((300, "Сессия 5ч"), (10080, "Неделя")):
        w = wins.get(mins) or {}
        pct = w.get("pct")
        draw.text((x0, y), label, fill=(156, 168, 190), font=f_label)
        pstr = "—" if pct is None else (f"{pct:.0f}%" if abs(pct - round(pct)) < 0.05 else f"{pct:.1f}%")
        pb = draw.textbbox((0, 0), pstr, font=f_pct)
        draw.text((x0 + int(inner_w * 0.48) - (pb[2] - pb[0]) // 2, y - 1), pstr, fill=c_white, font=f_pct)
        rtxt = _fmt_reset_iso(w.get("resets_at"))
        rb = draw.textbbox((0, 0), rtxt, font=f_meta)
        draw.text((x0 + inner_w - (rb[2] - rb[0]), y + 2), rtxt, fill=(156, 168, 190), font=f_meta)
        by = y + 36
        draw.rounded_rectangle([x0, by, x0 + inner_w, by + 10], radius=5, fill=(42, 50, 66))
        if pct is not None and pct > 0.2:
            col = (242, 139, 146) if pct >= 85 else (245, 184, 77) if pct >= 60 else (74, 222, 128)
            fw = max(12, int(inner_w * min(100.0, float(pct)) / 100.0))
            draw.rounded_rectangle([x0, by, x0 + fw, by + 10], radius=5, fill=col)
        y = by + 36

    ts = float(account.get("ts") or time.time())
    upd = dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    draw.text((x0, H - pad - 42), f"Обновлено {upd} · Израсходовано % · /sub ДД.ММ.ГГГГ для даты подписки", fill=(108, 120, 144), font=f_foot)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------- IPv4 Keep-Alive Telegram Client
class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        infos = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
        if not infos:
            return super().connect()
        last = None
        for af, stype, proto, _, sa in infos:
            s = None
            try:
                s = socket.socket(af, stype, proto)
                if self.timeout is not None:
                    s.settimeout(self.timeout)
                s.connect(sa)
                self.sock = self._context.wrap_socket(s, server_hostname=self.host)
                return
            except OSError as exc:
                last = exc
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass
        if last is not None:
            raise last


class _TgClient:
    def __init__(self, token):
        self._token = token
        self._prefix = f"/bot{token}"
        self._poll_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._poll_conn = None
        self._send_conn = None

    def _get_conn(self, poll, timeout):
        conn = self._poll_conn if poll else self._send_conn
        if conn is None:
            conn = _IPv4HTTPSConnection("api.telegram.org", 443, timeout=timeout)
            if poll:
                self._poll_conn = conn
            else:
                self._send_conn = conn
        else:
            conn.timeout = timeout
            if conn.sock is not None:
                try:
                    conn.sock.settimeout(timeout)
                except OSError:
                    pass
        return conn

    def _drop(self, poll):
        conn = self._poll_conn if poll else self._send_conn
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if poll:
            self._poll_conn = None
        else:
            self._send_conn = None

    def call(self, method, payload, timeout=30):
        poll = method == "getUpdates"
        lock = self._poll_lock if poll else self._send_lock
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Connection": "keep-alive"}
        path = f"{self._prefix}/{method}"
        with lock:
            last = None
            for attempt in range(2):
                conn = self._get_conn(poll, timeout)
                try:
                    conn.request("POST", path, body=data, headers=headers)
                    resp = conn.getresponse()
                    raw = resp.read().decode("utf-8", errors="replace")
                    if resp.status >= 400:
                        raise RuntimeError(f"Telegram HTTP {resp.status} on {method}: {raw}")
                    body = json.loads(raw)
                    if not body.get("ok"):
                        raise RuntimeError(f"Telegram API error on {method}: {body}")
                    return body.get("result")
                except (http.client.HTTPException, OSError, TimeoutError) as exc:
                    last = exc
                    self._drop(poll)
                    if attempt == 1:
                        raise RuntimeError(f"Telegram error on {method}: {type(exc).__name__}") from None
            raise RuntimeError(f"Telegram error on {method}: {last}")

    def download_file(self, file_path, timeout=60):
        fp = str(file_path or "").lstrip("/")
        if not fp or ".." in fp.split("/"):
            raise RuntimeError("Некорректный путь файла Telegram.")
        conn = _IPv4HTTPSConnection("api.telegram.org", 443, timeout=timeout)
        try:
            conn.request("GET", f"/file/bot{self._token}/{urllib.parse.quote(fp)}", headers={"Host": "api.telegram.org"})
            resp = conn.getresponse()
            if resp.status >= 400:
                raise RuntimeError(f"Telegram HTTP {resp.status} при скачивании файла.")
            data = resp.read(TG_FILE_MAX_BYTES + 1)
            if len(data) > TG_FILE_MAX_BYTES:
                raise RuntimeError("Файл больше 20 МБ.")
            return data
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def send_text(self, chat_id, text, reply_markup=None):
        chunks = split_markdown_chunks(text, limit=3400)
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            h = markdown_to_telegram_html(chunk)
            try:
                if len(h) <= 4096:
                    p = {"chat_id": chat_id, "text": h, "parse_mode": "HTML", "disable_web_page_preview": True}
                    if is_last and reply_markup is not None:
                        p["reply_markup"] = reply_markup
                    self.call("sendMessage", p, timeout=15)
                    continue
            except RuntimeError as exc:
                if "HTTP 400" not in str(exc):
                    raise
            p = {"chat_id": chat_id, "text": chunk[:4000], "disable_web_page_preview": True}
            if is_last and reply_markup is not None:
                p["reply_markup"] = reply_markup
            self.call("sendMessage", p, timeout=15)

    def send_photo(self, chat_id, filename, data, mime, caption="", reply_markup=None):
        boundary = secrets.token_hex(16)
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode("utf-8")]
        cap = (caption or "").strip()
        if cap:
            hcap = markdown_to_telegram_html(cap)
            if len(hcap) <= 1024:
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="parse_mode"\r\n\r\nHTML\r\n'.encode("utf-8"))
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{hcap}\r\n'.encode("utf-8"))
            else:
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{cap[:1020]}\r\n'.encode("utf-8"))
        if reply_markup is not None:
            rm = json.dumps(reply_markup, ensure_ascii=False)
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="reply_markup"\r\n\r\n{rm}\r\n'.encode("utf-8"))
        sname = filename.replace('"', "_")
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="{sname}"\r\nContent-Type: {mime}\r\n\r\n'.encode("utf-8"))
        parts.append(data)
        parts.append(f"\r\n--{boundary}--\r\n".encode("ascii"))
        body_bytes = b"".join(parts)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "Connection": "keep-alive"}
        path = f"{self._prefix}/sendPhoto"
        with self._send_lock:
            for attempt in range(2):
                conn = self._get_conn(False, 60)
                try:
                    conn.request("POST", path, body=body_bytes, headers=headers)
                    resp = conn.getresponse()
                    raw = resp.read().decode("utf-8", errors="replace")
                    if resp.status >= 400:
                        raise RuntimeError(f"Telegram HTTP {resp.status} on sendPhoto: {raw}")
                    parsed = json.loads(raw)
                    if not parsed.get("ok"):
                        raise RuntimeError(f"Telegram API error on sendPhoto: {parsed}")
                    return
                except (http.client.HTTPException, OSError, TimeoutError) as exc:
                    self._drop(False)
                    if attempt == 1:
                        raise RuntimeError(f"Telegram sendPhoto error: {type(exc).__name__}") from None


# ---------------------------------------------------------------- Bridge Runtime
class Bridge:
    def __init__(self):
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._client = None
        self._token = ""
        self._threads = []
        self._abort = None
        self._albums = {}
        self._album_lock = threading.Lock()
        self._notices = std_queue.Queue(maxsize=64)
        self.limit_held = None
        self.inputs = InputQueue(WORK_QUEUE_MAX)

    def is_running(self):
        return bool(self._client is not None and not self._stop.is_set() and any(t.is_alive() for t in self._threads))

    def _notice_async(self, text):
        try:
            self._notices.put_nowait(str(text))
        except std_queue.Full:
            pass

    def _main_kb(self):
        return {
            "keyboard": [
                [{"text": "📊 Лимиты"}, {"text": "🧠 Контекст"}],
                [{"text": "🆕 Новая сессия"}, {"text": "🗜 Сжать контекст"}],
                [{"text": "🤖 Модель"}, {"text": "⚙️ Статус"}],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def _limits_kb(self, pause_info):
        rows = [
            [
                {"text": "🔄 Обновить", "callback_data": "cb:limits_refresh"},
                {"text": "🧠 Контекст", "callback_data": "cb:context"},
            ],
            [
                {"text": "🗜 Сжать контекст", "callback_data": "cb:compact"},
                {"text": "🆕 Новая сессия", "callback_data": "cb:new_ask"},
            ],
            [{"text": "🤖 Сменить модель", "callback_data": "cb:model_menu"}],
        ]
        if (pause_info or {}).get("active") and pause_info.get("can_override"):
            rows.insert(0, [{"text": "▶ Отключить паузу (до 100%)", "callback_data": "cb:pause_off"}])
        elif (pause_info or {}).get("override"):
            rows.insert(0, [{"text": "⏸ Включить паузу обратно", "callback_data": "cb:pause_on"}])
        return {"inline_keyboard": rows}

    def _model_kb(self):
        meta = cc_agy.load_meta()
        cur_m = meta.get("model") or ""
        cur_e = meta.get("effort") or ""
        models = [
            ("Gemini 4 Neon", "gemini-4-neon-high"),
            ("Gemini 4 Carbon", "gemini-4-carbon-high"),
            ("Gemini 4 Hydrogen", "gemini-4-hydrogen-high"),
            ("Orchestrator (Neon)", "gemini-pro-orchestrator-neon"),
        ]
        rows, row = [], []
        for label, mid in models:
            mark = "✅ " if cur_m == mid else ""
            row.append({"text": f"{mark}{label}", "callback_data": f"cb:set_model:{mid}"})
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([
            {"text": ("✅ " if cur_e == e else "") + e, "callback_data": f"cb:set_effort:{e}"}
            for e in ("low", "medium", "high", "xhigh")
        ])
        rows.append([
            {"text": "↩️ По умолчанию", "callback_data": "cb:set_model:default"},
            {"text": "📊 Лимиты", "callback_data": "cb:limits"},
        ])
        return {"inline_keyboard": rows}

    def enqueue_console(self, text, request_id):
        """Queue a web-console message while quota-paused."""
        try:
            self.inputs.attach_journal(_queue_path())
            entry = self.inputs.reserve(
                kind="console",
                delivery={"source": "console", "quota_wait": True, "request_id": request_id},
                text=text,
            )
            if entry is None:
                return False, "Очередь сообщений Antigravity заполнена."
            return True, f"Antigravity на паузе по лимитам — сообщение поставлено в очередь (№{len(self.inputs)})."
        except Exception as exc:
            return False, f"Не удалось поставить сообщение в очередь: {type(exc).__name__}"

    def stop_work(self):
        if self._abort is not None:
            self._abort.set()
        self.inputs.clear()
        CONSOLE.interrupt()
        return True, "Выполнение Antigravity остановлено."

    def sync(self):
        with self._lock:
            s = load()
            tok = str(s.get("token") or "").strip()
            cid = str(s.get("chat_id") or "").strip()
            want = bool(s.get("enabled") and tok and cid and tok not in (RESERVED_TOKENS() or set()))
            if not want:
                self._stop.set()
                self._client = None
                self._token = ""
                return
            if self._client is not None and self._token == tok and not self._stop.is_set() and any(t.is_alive() for t in self._threads):
                return
            self._stop.set()
            self._stop = threading.Event()
            self._token = tok
            self._client = _TgClient(tok)
            self.inputs.attach_journal(_queue_path())
            self._threads = [
                threading.Thread(target=self._poll_loop, name="agy-poll", daemon=True),
                threading.Thread(target=self._work_loop, name="agy-queue", daemon=True),
                threading.Thread(target=self._notice_loop, name="agy-notices", daemon=True),
                threading.Thread(target=self._unsolicited_loop, name="agy-unsolicited", daemon=True),
                threading.Thread(target=self._limits_alert_loop, name="agy-limits-alert", daemon=True),
            ]
            for t in self._threads:
                t.start()

    def _send_reply_with_media(self, chat_id, reply, workdir):
        cli = self._client
        if not cli:
            return
        clean_text, images = extract_outgoing_images(reply, workdir)
        if not images:
            cli.send_text(chat_id, reply)
            return
        if len(images) == 1:
            fname, data, mime, cap = images[0]
            if not clean_text or (cap and clean_text.strip() == f"🖼 {cap}"):
                try:
                    cli.call("sendChatAction", {"chat_id": chat_id, "action": "upload_photo"}, timeout=10)
                except Exception:
                    pass
                cli.send_photo(chat_id, fname, data, mime, caption=cap)
                return
        if clean_text:
            cli.send_text(chat_id, clean_text)
        for fname, data, mime, cap in images:
            try:
                cli.call("sendChatAction", {"chat_id": chat_id, "action": "upload_photo"}, timeout=10)
            except Exception:
                pass
            cli.send_photo(chat_id, fname, data, mime, caption=cap)

    def _send_limits_card(self, chat_id, force=False):
        cli = self._client
        if not cli:
            return
        try:
            cli.call("sendChatAction", {"chat_id": chat_id, "action": "upload_photo"}, timeout=10)
        except Exception:
            pass
        b = cc_agy.find_bin()
        acc = cc_agy.fetch_account(b, force=force)
        st = CONSOLE.status()
        ctx = cc_agy.get_context_stats(st.get("conv_id") or "")
        pause = LIMIT_PAUSE() or {}
        png = render_limits_card_png(acc, ctx, st.get("running"), st.get("busy"), pause)
        cli.send_photo(chat_id, "agy_limits.png", png, "image/png", reply_markup=self._limits_kb(pause))

    def _handle_command(self, chat_id, text):
        cli = self._client
        if not cli:
            return True
        parts = text.split(maxsplit=1)
        cmd = parts[0].split("@", 1)[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/start", "/help", "/menu"):
            cli.send_text(
                chat_id,
                "### 🤖 Antigravity (`agy`) — cc-fleet\n\n"
                "Пишите текст, отправляйте фото или файлы, либо пользуйтесь кнопками меню ниже.\n"
                "- `/limits` — карточка 5ч/недельных лимитов и подписки\n"
                "- `/context` — объём контекста в токенах\n"
                "- `/compact` — сжать контекст (`/compact`)\n"
                "- `/new` — новая сессия\n"
                "- `/model` — выбрать модель и `effort`\n"
                "- `/sub ДД.ММ.ГГГГ` — дата окончания подписки\n"
                "- `/status` — статус\n"
                "- `/cancel` — остановить выполнение",
                reply_markup=self._main_kb(),
            )
            return True

        if cmd in ("/limits", "/usage", "/quota"):
            threading.Thread(
                target=self._send_limits_card,
                args=(chat_id, arg.lower() in ("refresh", "force", "now")),
                daemon=True,
            ).start()
            return True

        if cmd == "/context":
            st = CONSOLE.status()
            ctx = cc_agy.get_context_stats(st.get("conv_id") or "")
            kb = {"inline_keyboard": [[{"text": "🗜 Сжать контекст", "callback_data": "cb:compact"}, {"text": "📊 Лимиты", "callback_data": "cb:limits"}]]}
            cli.send_text(
                chat_id,
                f"### 🧠 Контекст Antigravity\n\n"
                f"• Модель: **{st.get('model') or 'по умолчанию'}**\n"
                f"• Активный контекст: **`{_fmt_toks(ctx['context_tokens'])}` токенов**\n"
                f"• Сообщений: **{ctx['turns']}** (шагов: {ctx['steps']})\n"
                f"• Диалог: `{ctx['conv_id'] or 'новый'}`",
                reply_markup=kb,
            )
            return True

        if cmd == "/compact":
            def _do():
                cli.send_text(chat_id, "🗜 Сжимаю контекст (`/compact`)...")
                ok, msg = CONSOLE.compact()
                cli.send_text(chat_id, ("✅ " if ok else "❌ ") + msg)
            threading.Thread(target=_do, daemon=True).start()
            return True

        if cmd == "/new_ask":
            kb = {"inline_keyboard": [[{"text": "✅ Да, новая сессия", "callback_data": "cb:new_confirm"}, {"text": "❌ Отмена", "callback_data": "cb:cancel_menu"}]]}
            cli.send_text(chat_id, "🆕 Сбросить текущий диалог и начать **новую сессию**?", reply_markup=kb)
            return True

        if cmd == "/new":
            ok, msg = CONSOLE.new_session()
            cli.send_text(chat_id, ("✅ " if ok else "❌ ") + msg, reply_markup=self._main_kb())
            return True

        if cmd == "/model":
            if not arg:
                cli.send_text(chat_id, "### 🤖 Выбор модели и уровня размышлений", reply_markup=self._model_kb())
            else:
                ok, msg = cc_agy.set_prefs(model=arg)
                if ok:
                    CONSOLE.request_settings({"model": "" if arg.lower() in ("default", "reset") else arg})
                cli.send_text(chat_id, ("✅ " if ok else "❌ ") + msg)
            return True

        if cmd == "/sub":
            if not arg:
                d = cc_agy.parse_sub_date(cc_agy.load_meta().get("sub_until"))
                if d:
                    left = (d - dt.date.today()).days
                    cli.send_text(chat_id, f"📅 Подписка до **{d.strftime('%d.%m.%Y')}** ({_plural_days(left)}).\nИзменить: `/sub ДД.ММ.ГГГГ`")
                else:
                    cli.send_text(chat_id, "📅 Дата подписки не задана. Укажите: `/sub 28.12.2026`")
                return True
            ok, msg = cc_agy.set_prefs(sub_until=arg)
            cli.send_text(chat_id, ("✅ " if ok else "❌ ") + msg)
            return True

        if cmd == "/status":
            st = CONSOLE.status()
            lp = LIMIT_PUBLIC() or {}
            cli.send_text(
                chat_id,
                f"### ⚙️ Статус Antigravity\n\n"
                f"• Консоль: **{'🟢 работает (pid ' + st['pid'] + ')' if st['running'] else '⚪ остановлена'}**\n"
                f"• Модель: **{st.get('model') or 'по умолчанию'}**\n"
                f"• Папка: `{st.get('cwd')}`\n"
                f"• Очередь: `{len(self.inputs)}` | Порог 5ч: `{lp.get('threshold', 90)}%` | Неделя: `{lp.get('weekly_cap', 99)}%`",
                reply_markup=self._main_kb(),
            )
            return True

        if cmd in ("/cancel", "/stop"):
            self.stop_work()
            cli.send_text(chat_id, "🛑 Выполнение остановлено.")
            return True

        return False

    def _handle_callback(self, cb, allowed_cid):
        cli = self._client
        if not cli:
            return
        cb_id = str(cb.get("id") or "")
        msg = cb.get("message") or {}
        cid = str((msg.get("chat") or {}).get("id") or "")
        mid = msg.get("message_id")
        data = str(cb.get("data") or "")
        if cid != str(allowed_cid):
            try:
                cli.call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "⛔ Доступ запрещён", "show_alert": True}, timeout=10)
            except Exception:
                pass
            return

        def ack(t=""):
            try:
                cli.call("answerCallbackQuery", {"callback_query_id": cb_id, "text": t[:180]}, timeout=10)
            except Exception:
                pass

        if data in ("cb:limits", "cb:limits_refresh"):
            ack("🔄 Обновляю..." if data.endswith("refresh") else "")
            threading.Thread(target=self._send_limits_card, args=(int(cid), data.endswith("refresh")), daemon=True).start()
        elif data == "cb:context":
            ack()
            self._handle_command(int(cid), "/context")
        elif data == "cb:compact":
            ack("🗜 Сжимаю...")
            self._handle_command(int(cid), "/compact")
        elif data == "cb:new_ask":
            ack()
            self._handle_command(int(cid), "/new_ask")
        elif data == "cb:new_confirm":
            ack("🆕 Сброшено")
            ok, res = CONSOLE.new_session()
            if mid:
                try:
                    cli.call("editMessageText", {"chat_id": int(cid), "message_id": mid, "text": ("✅ " if ok else "❌ ") + res}, timeout=15)
                except Exception:
                    pass
        elif data == "cb:cancel_menu":
            ack("Отменено")
            if mid:
                try:
                    cli.call("editMessageText", {"chat_id": int(cid), "message_id": mid, "text": "Отменено."}, timeout=15)
                except Exception:
                    pass
        elif data == "cb:model_menu":
            ack()
            cli.send_text(int(cid), "### 🤖 Выбор модели и уровня размышлений", reply_markup=self._model_kb())
        elif data.startswith("cb:set_model:"):
            val = data.split(":", 2)[2]
            cc_agy.set_prefs(model=val)
            CONSOLE.request_settings({"model": "" if val == "default" else val})
            ack(f"✅ Модель: {val}")
            if mid:
                try:
                    cli.call("editMessageReplyMarkup", {"chat_id": int(cid), "message_id": mid, "reply_markup": self._model_kb()}, timeout=15)
                except Exception:
                    pass
        elif data.startswith("cb:set_effort:"):
            val = data.split(":", 2)[2]
            cc_agy.set_prefs(effort=val)
            CONSOLE.request_settings({"effort": val})
            ack(f"✅ Effort: {val}")
            if mid:
                try:
                    cli.call("editMessageReplyMarkup", {"chat_id": int(cid), "message_id": mid, "reply_markup": self._model_kb()}, timeout=15)
                except Exception:
                    pass
        elif data in ("cb:pause_off", "cb:pause_on"):
            ok, msg_txt = LIMIT_CONFIGURE({"pause_override": data == "cb:pause_off"})
            ack(msg_txt)
            cli.send_text(int(cid), ("✅ " if ok else "❌ ") + msg_txt)
        else:
            ack()

    def _extract_attachments(self, msg):
        out = []
        photos = [p for p in (msg.get("photo") or []) if isinstance(p, dict) and p.get("file_id")]
        if photos:
            best = max(photos, key=lambda p: ((p.get("width") or 0) * (p.get("height") or 0), p.get("file_size") or 0))
            out.append((str(best["file_id"]), "photo.jpg"))
            return out
        for field, dname in MEDIA_FIELDS.items():
            item = msg.get(field)
            if isinstance(item, dict) and item.get("file_id"):
                out.append((str(item["file_id"]), str(item.get("file_name") or dname)))
                return out
        return out

    def _prepare_prompt_with_attachments(self, text, att_list):
        if not att_list:
            return text
        cli = self._client
        saved = []
        inbox = _inbox_dir()
        for fid, orig in att_list:
            info = cli.call("getFile", {"file_id": fid}, timeout=20)
            data = cli.download_file(info["file_path"])
            ext = _detect_img_ext(data)
            ts = time.strftime("%Y%m%d_%H%M%S")
            rnd = secrets.token_hex(4)
            if ext:
                d = inbox / "images"
                d.mkdir(parents=True, exist_ok=True)
                _prune_old(d)
                dest = d / f"img_{ts}_{rnd}_{Path(_safe_filename(orig, 'image')).stem[:50]}.{ext}"
                dest.write_bytes(data)
                saved.append((dest, True, orig))
            else:
                d = inbox / "files"
                d.mkdir(parents=True, exist_ok=True)
                _prune_old(d)
                dest = d / f"doc_{ts}_{rnd}_{_safe_filename(orig)}"
                dest.write_bytes(data)
                saved.append((dest, False, orig))
        head = (text or "").strip() or "Пользователь прислал вложение без подписи. Прочитай его и ответь по содержимому."
        lines = [head, "", "[Вложения из Telegram сохранены на сервере. Обязательно открой и прочитай их через read_file:"]
        for p, is_img, orig in saved:
            lines.append(f"- {'Изображение' if is_img else f'Файл ({orig})'}: {p}")
        lines.append("]")
        return "\n".join(lines)

    def _enqueue_telegram(self, chat_id, text, att_list):
        paused = bool((LIMIT_PAUSE() or {}).get("active"))
        entry = self.inputs.reserve(
            kind="telegram",
            delivery={"source": "telegram", "chat_id": int(chat_id), "quota_wait": paused, "attachments": att_list},
            text=text,
        )
        if entry is None:
            self._notice_async("⚠️ Очередь Antigravity заполнена (20 сообщений). Дождитесь разбора или нажмите /stop.")
            return
        if paused:
            self._notice_async(f"⏸ Antigravity на паузе по лимитам — сообщение сохранено в очереди (№{len(self.inputs)}).")

    def _poll_loop(self):
        cli = self._client
        s = load()
        allowed_cid = str(s.get("chat_id") or "")
        st = _load_state()
        offset = int(st.get("offset") or 0)
        try:
            me = cli.call("getMe", {}, timeout=15)
            st["bot"] = {"username": me.get("username") or "", "id": me.get("id")}
            st["last_error"] = ""
            _save_state(st)
            cli.call("deleteWebhook", {"drop_pending_updates": False}, timeout=15)
            cli.call("setMyCommands", {"commands": [
                {"command": "limits", "description": "📊 Лимиты (5ч / неделя) и подписка"},
                {"command": "context", "description": "🧠 Контекст диалога"},
                {"command": "compact", "description": "🗜 Сжать контекст"},
                {"command": "new", "description": "🆕 Новая сессия"},
                {"command": "model", "description": "🤖 Модель и effort"},
                {"command": "sub", "description": "📅 Дата подписки"},
                {"command": "status", "description": "⚙️ Статус"},
                {"command": "cancel", "description": "🛑 Остановить"},
                {"command": "menu", "description": "🎛 Кнопки меню"},
            ]}, timeout=15)
        except Exception as exc:
            st["last_error"] = _mask(exc)
            _save_state(st)

        quick = {
            "📊 Лимиты": "/limits",
            "🧠 Контекст": "/context",
            "🆕 Новая сессия": "/new_ask",
            "🗜 Сжать контекст": "/compact",
            "🤖 Модель": "/model",
            "⚙️ Статус": "/status",
        }
        backoff = 2
        while not self._stop.is_set():
            try:
                updates = cli.call(
                    "getUpdates",
                    {"offset": offset, "timeout": TG_TIMEOUT, "allowed_updates": ["message", "callback_query"]},
                    timeout=TG_TIMEOUT + 10,
                )
                backoff = 2
                for upd in updates or []:
                    offset = int(upd["update_id"]) + 1
                    st["offset"] = offset
                    _save_state(st)
                    cb = upd.get("callback_query")
                    if isinstance(cb, dict):
                        self._handle_callback(cb, allowed_cid)
                        continue
                    msg = upd.get("message")
                    if not isinstance(msg, dict):
                        continue
                    cid = str((msg.get("chat") or {}).get("id") or "")
                    if cid != allowed_cid:
                        continue
                    txt = (msg.get("text") or msg.get("caption") or "").strip()
                    if txt in quick:
                        txt = quick[txt]
                    if txt.startswith("/") and self._handle_command(int(cid), txt):
                        continue
                    atts = self._extract_attachments(msg)
                    if not txt and not atts:
                        continue
                    mgid = msg.get("media_group_id")
                    if mgid and atts:
                        key = (cid, str(mgid))
                        with self._album_lock:
                            ent = self._albums.get(key)
                            if ent is None:
                                ent = {"text": txt, "atts": list(atts), "timer": None}
                                self._albums[key] = ent
                            else:
                                if txt and not ent["text"]:
                                    ent["text"] = txt
                                ent["atts"].extend(atts)
                                if ent["timer"]:
                                    ent["timer"].cancel()
                            t = threading.Timer(1.0, self._flush_album, args=(cid, str(mgid)))
                            t.daemon = True
                            ent["timer"] = t
                            t.start()
                    else:
                        self._enqueue_telegram(int(cid), txt, atts)
            except Exception as exc:
                if self._stop.is_set():
                    break
                st["last_error"] = _mask(exc)
                _save_state(st)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30)

    def _flush_album(self, cid, mgid):
        with self._album_lock:
            ent = self._albums.pop((cid, mgid), None)
        if ent:
            self._enqueue_telegram(int(cid), ent["text"], ent["atts"])

    def _work_loop(self):
        was_held = False
        while not self._stop.is_set():
            pause = LIMIT_PAUSE() or {}
            if pause.get("active"):
                was_held = True
                self._stop.wait(1.0)
                continue
            if was_held:
                was_held = False
                if len(self.inputs) > 0:
                    self._notice_async(f"▶ Antigravity: лимит снова доступен — отправляю очередь ({len(self.inputs)}).")
            ready = self.inputs.take_ready(limit=1)
            if not ready:
                self._stop.wait(0.25)
                continue
            item = ready[0]
            delivery = item.delivery or {}
            src = delivery.get("source") or "telegram"
            if src == "console":
                CONSOLE.send_input(item.text, request_id=delivery.get("request_id"))
                continue
            cid = int(delivery.get("chat_id") or load().get("chat_id") or 0)
            if not cid or not self._client:
                continue
            typing_stop = threading.Event()

            def _typing():
                while not typing_stop.is_set():
                    try:
                        self._client.call("sendChatAction", {"chat_id": cid, "action": "typing"}, timeout=10)
                    except Exception:
                        pass
                    typing_stop.wait(4.0)

            threading.Thread(target=_typing, daemon=True).start()
            abort_ev = threading.Event()
            self._abort = abort_ev
            try:
                prompt = self._prepare_prompt_with_attachments(item.text, delivery.get("attachments") or [])
                wd = load().get("workdir") or "/root"
                reply, _ = CONSOLE.ask(prompt, abort=abort_ev, timeout=1800, workdir=wd)
                typing_stop.set()
                self._send_reply_with_media(cid, reply, wd)
            except cc_agy_console.Aborted:
                pass
            except Exception as exc:
                typing_stop.set()
                try:
                    self._client.send_text(cid, f"❌ {_mask(exc)}")
                except Exception:
                    pass
            finally:
                typing_stop.set()
                self._abort = None

    def _notice_loop(self):
        while not self._stop.is_set():
            try:
                txt = self._notices.get(timeout=1.0)
            except std_queue.Empty:
                continue
            cid = load().get("chat_id")
            if cid and self._client:
                try:
                    self._client.send_text(int(cid), txt)
                except Exception:
                    pass

    def _unsolicited_loop(self):
        while not self._stop.is_set():
            try:
                cid = load().get("chat_id")
                if cid and self._client:
                    wd = load().get("workdir") or "/root"
                    for reply in CONSOLE.poll_unsolicited():
                        self._send_reply_with_media(int(cid), reply, wd)
            except Exception:
                pass
            self._stop.wait(0.3)

    def _limits_alert_loop(self):
        while not self._stop.wait(LIM_EVERY):
            try:
                s = load()
                if not (s.get("token") and s.get("chat_id")):
                    continue
                b = cc_agy.find_bin()
                if not b:
                    continue
                acc = cc_agy.fetch_account(b, force=False)
                st = _load_state()
                alerts = dict(st.get("alerts") or {})
                changed = False
                for w in acc.get("windows") or []:
                    m = str(w.get("mins"))
                    pct = w.get("pct")
                    if pct is None:
                        continue
                    lbl = "5-часового окна" if m == "300" else "недельного окна"
                    if pct >= 100 and alerts.get(f"full_{m}") != w.get("resets_at"):
                        alerts[f"full_{m}"] = w.get("resets_at") or "1"
                        self._notice_async(f"🔴 Antigravity: лимит {lbl} исчерпан (100%). Сброс: {_fmt_reset_iso(w.get('resets_at'))}.")
                        changed = True
                    elif pct < LIM_CLEAR and alerts.get(f"full_{m}"):
                        alerts.pop(f"full_{m}", None)
                        self._notice_async(f"🟢 Antigravity: лимит {lbl} снова доступен ({pct:.0f}%).")
                        changed = True
                    elif LIM_WARN <= pct < 100 and not alerts.get(f"warn_{m}"):
                        alerts[f"warn_{m}"] = True
                        self._notice_async(f"⚠️ Antigravity: использовано {pct:.0f}% {lbl}.")
                        changed = True
                    elif pct < LIM_CLEAR and alerts.get(f"warn_{m}"):
                        alerts.pop(f"warn_{m}", None)
                        changed = True

                sub_d = cc_agy.parse_sub_date(acc.get("sub_until"))
                if sub_d:
                    left = (sub_d - dt.date.today()).days
                    for step in SUB_STEPS:
                        k = f"sub_{sub_d.isoformat()}_{step}"
                        if left <= step and not alerts.get(k):
                            alerts[k] = True
                            self._notice_async(
                                f"📅 Antigravity: подписка заканчивается {sub_d.strftime('%d.%m.%Y')} ({_plural_days(left)})."
                            )
                            changed = True
                            break
                if changed:
                    st["alerts"] = alerts
                    _save_state(st)
            except Exception:
                pass


BRIDGE = Bridge()


def notify(text):
    """Send an asynchronous status/update notification to the configured Antigravity Telegram chat."""
    if not text:
        return False
    cfg = load()
    if not (cfg.get("enabled") and cfg.get("token") and cfg.get("chat_id")):
        return False
    BRIDGE._notice_async(str(text))
    return True
