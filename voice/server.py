#!/usr/bin/env python3
"""cc-fleet, голос: локальный TTS-демон (Silero v4 ru + ruaccent), держит модели в памяти, отдаёт аудио по HTTP.
Только localhost, без внешнего доступа и без ключей.
POST /speak {"text": "...", "voice": "kseniya"} -> audio/ogg (opus); GET /health -> ok (когда модели загружены).
Голоса: aidar, baya, kseniya, xenia, eugene. Каталог моделей: CCFLEET_VOICE_DIR (по умолчанию /opt/ccfleet-voice), порт: CCFLEET_VOICE_PORT (8879).
"""
import json
import os
import re
import subprocess
import wave
import xml.sax.saxutils as saxutils
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch
from num2words import num2words

# Silero по голому тексту ставит паузы на знаках препинания слабо и непредсказуемо
# (запятые часто вообще без паузы) — задаём паузу явно через SSML <break>.
_PAUSE_MS = {",": 180, ";": 220, ":": 220, "—": 280, "–": 220}
_PAUSE_RE = re.compile("[" + "".join(_PAUSE_MS) + "]")

# Маркер точки вставки паузы после отдельного слова (см. mark_unmarked_monosyllables) —
# невидимый символ, escape его не трогает, заменяется на <break> уже в to_ssml.
_WORD_BREAK_MARK = "\x00"
_WORD_BREAK_MS = 120


def to_ssml(text: str) -> str:
    escaped = saxutils.escape(text)
    body = _PAUSE_RE.sub(lambda m: f'{m.group(0)}<break time="{_PAUSE_MS[m.group(0)]}ms"/>', escaped)
    body = body.replace(_WORD_BREAK_MARK, f'<break time="{_WORD_BREAK_MS}ms"/>')
    return f"<speak>{body}</speak>"


# Алфавит модели v4_ru — только кириллица (см. model.symbols), латинские буквы
# она молча вырезает регуляркой ещё до синтеза. Транслитерируем в кириллицу,
# чтобы английские слова/аббревиатуры не пропадали из текста бесследно.
_TRANSLIT_KNOWN = {
    "telegram": "телеграм", "slack": "слэк", "python": "пайтон",
    "github": "гитхаб", "claude": "клод", "chatgpt": "чатгпт", "openai": "опенай",
    "json": "джейсон", "ssml": "эс-эс-эм-эл", "tts": "ти-ти-эс", "http": "эйч-ти-ти-пи",
    "ai": "ай", "css": "си-эс-эс", "html": "эйч-ти-эм-эл", "sql": "эс-кью-эл",
    "google": "гугл", "iphone": "айфон", "wifi": "вайфай", "wi-fi": "вайфай",
    "linux": "линукс", "windows": "виндовс", "macos": "макос", "android": "андроид",
    "ip": "ай-пи", "url": "ю-эр-эл", "apk": "эй-пи-кей", "pwa": "пи-дабл-ю-эй", "ok": "окей",
    "ui": "ю-ай", "nginx": "энджин-икс", "cpu": "си-пи-ю", "gpu": "джи-пи-ю", "ssl": "эс-эс-эл",
    "socks": "сокс", "nas": "нэс", "sim": "сим", "lan": "лэн", "v2rayng": "ви-ту-рэй-эн-джи", "termux": "термукс",
}
# Аббревиатуры без гласных (VPN, DNS, TCP, CDN, DPI...) Silero проглатывает целиком — читаем по буквам.
_LETTER_NAMES = {
    "a": "эй", "b": "би", "c": "си", "d": "ди", "e": "и", "f": "эф", "g": "джи", "h": "эйч",
    "i": "ай", "j": "джей", "k": "кей", "l": "эл", "m": "эм", "n": "эн", "o": "оу", "p": "пи",
    "q": "кью", "r": "ар", "s": "эс", "t": "ти", "u": "ю", "v": "ви", "w": "даблью", "x": "икс",
    "y": "уай", "z": "зед",
}
_TRANSLIT_DIGRAPHS = [
    ("tch", "ч"), ("sh", "ш"), ("ch", "ч"), ("th", "т"), ("ph", "ф"),
    ("wh", "в"), ("ck", "к"), ("qu", "кв"), ("oo", "у"), ("ee", "и"),
]
_TRANSLIT_SINGLE = {
    "a": "а", "b": "б", "d": "д", "e": "е", "f": "ф", "h": "х", "i": "и",
    "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "к",
    "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс", "z": "з",
}
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-]*")


def _translit_word(word: str) -> str:
    lw = word.lower()
    if lw in _TRANSLIT_KNOWN:
        out = _TRANSLIT_KNOWN[lw]
    else:
        chars = []
        i, n = 0, len(lw)
        while i < n:
            for pat, rep in _TRANSLIT_DIGRAPHS:
                if lw.startswith(pat, i):
                    chars.append(rep)
                    i += len(pat)
                    break
            else:
                ch = lw[i]
                nxt = lw[i + 1] if i + 1 < n else ""
                if ch == "c":
                    chars.append("с" if nxt in "eiy" else "к")
                elif ch == "g":
                    chars.append("дж" if nxt in "eiy" else "г")
                elif ch == "j":
                    chars.append("дж")
                elif ch == "y":
                    chars.append("й" if i == 0 else "и")
                else:
                    chars.append(_TRANSLIT_SINGLE.get(ch, ch))
                i += 1
        out = "".join(chars)
    return out[0].upper() + out[1:] if word[:1].isupper() else out


def transliterate_latin(text: str):
    translit_words = []

    def repl(m):
        if m.group(0).lower().startswith(_SPELL_PH):
            return m.group(0)
        w = _translit_word(m.group(0))
        translit_words.append(w)
        return w

    return _LATIN_WORD_RE.sub(repl, text), translit_words


# Аббревиатуры (VPN, IP, DNS, DPI...) Silero читает слитно или глотает — ruaccent+модель не умеют
# произносить набор согласных, а "ай-пи"/"ви-пи-эн" одним дефисным словом сливаются в кашу
# (подтверждено расшифровкой Whisper на VPN/IP). Читаем по буквам: каждая буква —
# отдельное слово с явным ударением и микропаузой. Латинский плейсхолдер переживает акцентуатор
# (private-use символы он вырезает, Latin — нет) и подменяется на побуквенное чтение уже после него.
_SPELL_PH = "zzq"
_SPELL_RE = re.compile(r"(?<![A-Za-z\-])[A-Za-z]{2,6}(?![A-Za-z])")
_SPELL_EXTRA = {"api", "ip", "url", "apk", "pwa", "ui", "cpu", "gpu", "ssl", "adb"}


def _should_spell(w: str) -> bool:
    lw = w.lower()
    if lw in _SPELL_EXTRA:
        return True
    if not any(c in "aeiouy" for c in lw):
        return True
    return 2 <= len(w) <= 4 and w.isupper() and lw not in _TRANSLIT_KNOWN


def spell_acronyms(text: str):
    spelled = []

    def repl(m):
        if not _should_spell(m.group(0)):
            return m.group(0)
        spelled.append(m.group(0).lower())
        return _SPELL_PH + "".join(chr(97 + int(d)) for d in str(len(spelled) - 1))

    return _SPELL_RE.sub(repl, text), spelled


_SPELL_PH_RE = re.compile(_SPELL_PH + "([a-j]+)", re.IGNORECASE)


def restore_spelled(text: str, spelled) -> str:
    # Слитно, как произносят носители (ди-эн-эс → «диэнэс»): ударение на первую и последнюю букву.
    # Побуквенно-раздельное чтение звучало как диктовка, слитное Whisper узнаёт как целое слово.
    def stress(name):
        v = next(i for i, c in enumerate(name) if c in _VOWELS)
        return name[:v] + "+" + name[v:]

    def repl(m):
        letters = spelled[int("".join(str(ord(c) - 97) for c in m.group(1).lower()))]
        names = [_LETTER_NAMES[ch] for ch in letters]
        names[0], names[-1] = stress(names[0]), stress(names[-1])
        return "".join(names)

    return _SPELL_PH_RE.sub(repl, text)


# (digit-drop 2026-07-28) Silero v4_ru молча проглатывает цифровые последовательности
# целиком — "ФГ353" на выходе звучит как "фука", отдельное "353" вообще без звука.
# Подтверждено расшифровкой Whisper на живом голосовом. Разворачиваем
# цифры в русские слова ДО акцентуатора, чтобы ruaccent мог расставить ударения как
# в обычном тексте.
_DIGIT_RE = re.compile(r"\d+")
# Даты/время ("22.01", "11:45") — цифры прилипают к разделителю без пробела с обеих
# сторон. Без пробела развёрнутые слова склеиваются в одно "дваодин" — добавляем
# пробел и на стыке с этими разделителями, не только с буквами.
_GLUE_CHARS = set(".:/-")


def expand_digits(text: str) -> str:
    out = []
    last = 0
    for m in _DIGIT_RE.finditer(text):
        start, end = m.span()
        out.append(text[last:start])
        try:
            words = num2words(int(m.group(0)), lang="ru")
        except Exception:
            words = m.group(0)
        prev_ch = text[start - 1] if start > 0 else ""
        next_ch = text[end] if end < len(text) else ""
        prefix = " " if (prev_ch.isalnum() or prev_ch in _GLUE_CHARS) else ""
        suffix = " " if (next_ch.isalnum() or next_ch in _GLUE_CHARS) else ""
        out.append(prefix + words + suffix)
        last = end
    out.append(text[last:])
    return "".join(out)


_VOWELS = "аеёиоуыэюя"


_LETTER_RE = re.compile(r"[а-яёa-z]", re.IGNORECASE)
_TERMINAL_PUNCT_RE = re.compile(r"[.!?…]\s*$")


# Заимствования, где «е» после согласной в обиходе звучит твёрдо, как «э»
# (пример: «плеер» читалось с мягким «ле»). Silero читает «е» всегда мягко,
# поэтому уже ПОСЛЕ ruaccent (он знает ударение и для «е», и для «э») меняем букву.
# Ключ — регэксп на основу слова (с возможным «+» ударения), значение — замена.
_HARD_E = [
    (re.compile(r"(?i)\b(пл)(\+?)е(?=\+?ер)"), r"\1\2э"),  # плеер, плеера, плееры…
]


# Словарь из Викисловаря (dict/build_hard_e.py): словоформа -> индексы «е», которые читать как «э»
# (компьютер, свитер, модель, кафе, отель…). Ручной _HARD_E выше остаётся поверх.
_HARD_E_DICT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dict", "hard_e.json")
try:
    with open(_HARD_E_DICT_PATH, encoding="utf-8") as _f:
        _HARD_E_DICT = json.load(_f)
except OSError:
    _HARD_E_DICT = {}
_WORD_WITH_ACCENT_RE = re.compile(r"[А-Яа-яЁё+]+")


def _harden_word(m: "re.Match") -> str:
    tok = m.group(0)
    letters = [(i, ch) for i, ch in enumerate(tok) if ch != "+"]
    pos = _HARD_E_DICT.get("".join(ch for _, ch in letters).lower())
    if not pos:
        return tok
    out = list(tok)
    for p in pos:
        if p < len(letters):
            i, ch = letters[p]
            if ch in "еЕ":
                out[i] = "э" if ch == "е" else "Э"
    return "".join(out)


def accentize_keep_manual(text: str) -> str:
    """ruaccent игнорирует уже расставленные «+» и переугадывает ударение
    (пример: «зам+ок и з+амок» читалось наоборот). ruaccent только вставляет «+»
    и «ё», число слов не меняется — поэтому слова с ручным «+» возвращаем как были."""
    out = get_accentizer().process_all(text)
    if "+" not in text:
        return out
    src = _WORD_WITH_ACCENT_RE.findall(text)
    dst = list(_WORD_WITH_ACCENT_RE.finditer(out))
    if len(src) != len(dst):
        return out
    parts, last = [], 0
    for w, m in zip(src, dst):
        parts.append(out[last:m.start()])
        parts.append(w if "+" in w else m.group(0))
        last = m.end()
    parts.append(out[last:])
    return "".join(parts)


def harden_e(text: str) -> str:
    if _HARD_E_DICT:
        text = _WORD_WITH_ACCENT_RE.sub(_harden_word, text)
    for rx, repl in _HARD_E:
        text = rx.sub(repl, text)
    return text


def mark_unmarked_monosyllables(text: str, words) -> str:
    # ruaccent принципиально не ставит "+" на односложных словах (ударение и так
    # однозначно) — но акустическая модель Silero при put_accent=False трактует
    # отсутствие "+" как сигнал безударности/редукции, как у предлогов и частиц.
    # Для транслитерированных иностранных слов (не настоящих русских служебных
    # слов) это ломает произношение — редуцирует и склеивает с соседним словом.
    #
    # Одной разметки "+" недостаточно (подтверждено Whisper STT: "Slack" всё равно
    # съезжает в "слык"/"слег"). Эмпирически (перебор через Whisper) модель ведёт
    # себя по-разному в зависимости от того, что идёт после слова:
    #  - слово прямо перед следующей буквой (середина фразы, без знака препинания)
    #    — нужна явная микропауза, иначе сливается со следующим словом;
    #  - слово в самом конце фразы — нужна точка в конце (без неё редуцируется
    #    как безударный предлог); если пауза после слова добавлена ЗДЕСЬ ЖЕ —
    #    ломает то же самое (подтверждено повторным тестом), поэтому паузу не
    #    добавляем, когда после слова вообще ничего нет.
    #  - слово перед уже существующим знаком препинания — не трогаем, знак
    #    препинания уже даёт свою паузу через _PAUSE_RE.
    force_end_period = False
    for w in set(words):
        vowel_positions = [i for i, ch in enumerate(w.lower()) if ch in _VOWELS]
        if len(vowel_positions) != 1:
            continue
        match = re.search(rf"\b{re.escape(w)}\b", text)
        if not match:
            continue
        marked = w
        if "+" not in match.group(0):
            i = vowel_positions[0]
            marked = w[:i] + "+" + w[i:]
        rest = text[match.end():].lstrip(" ")
        if not rest:
            repl = marked
            force_end_period = True
        elif _LETTER_RE.match(rest[0]):
            repl = marked + _WORD_BREAK_MARK
        else:
            repl = marked
        text = re.sub(rf"\b{re.escape(w)}\b", repl, text, count=1)
    if force_end_period and not _TERMINAL_PUNCT_RE.search(text):
        text += "."
    return text

VOICE_DIR = os.environ.get("CCFLEET_VOICE_DIR") or "/opt/ccfleet-voice"
MODEL_DIR = os.path.join(VOICE_DIR, "model")
os.makedirs(MODEL_DIR, exist_ok=True)
PORT = int(os.environ.get("CCFLEET_VOICE_PORT") or 8879)

_model = None
_accentizer = None


def get_model():
    global _model
    if _model is None:
        torch.hub.set_dir(MODEL_DIR)
        _model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-models",
            model="silero_tts",
            language="ru",
            speaker="v4_ru",
            trust_repo=True,
        )
    return _model


def get_accentizer():
    global _accentizer
    if _accentizer is None:
        from ruaccent import RUAccent
        _accentizer = RUAccent()
        _accentizer.load(omograph_model_size="turbo3.1", use_dictionary=True)
    return _accentizer



# Silero (apply_tts) падает с "Model couldn't generate your text, probably
# it's too long" на текстах примерно от ~950 символов (подтверждено эмпирически
# say.sh молча писал этот текст ошибки в .ogg вместо аудио — битые голосовые). Режем длинный текст на куски по границам предложений
# и синтезируем каждый отдельно, склеивая аудио через torch.cat.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
_TTS_CHUNK_MAX_LEN = 400


def _split_for_tts(text: str, max_len: int = _TTS_CHUNK_MAX_LEN):
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s]
    chunks = []
    cur = ""
    for s in sentences:
        candidate = f"{cur} {s}".strip() if cur else s
        if len(candidate) > max_len and cur:
            chunks.append(cur)
            cur = s
        else:
            cur = candidate
    if cur:
        chunks.append(cur)
    # Предложение без знаков препинания длиннее лимита — режем жёстко по длине,
    # чтобы не отправить в Silero кусок за порогом даже в вырожденном случае.
    final = []
    for c in chunks:
        if len(c) <= max_len * 1.5:
            final.append(c)
        else:
            for i in range(0, len(c), max_len):
                final.append(c[i:i + max_len])
    return final or [text]


def synthesize(text: str, voice: str, sample_rate: int = 48000) -> bytes:
    model = get_model()
    text = expand_digits(text)
    text, spelled = spell_acronyms(text)
    text, translit_words = transliterate_latin(text)
    text = accentize_keep_manual(text)
    text = harden_e(text)
    text = restore_spelled(text, spelled)
    text = mark_unmarked_monosyllables(text, translit_words)
    # ruaccent уже расставил + перед ударными гласными и восстановил ё —
    # put_accent/put_yo=True здесь заставляют Silero прогнать текст ЕЩЁ РАЗ
    # через свой (более слабый) акцентор и молча затереть нашу разметку.
    chunks = _split_for_tts(text)
    gap = torch.zeros(int(sample_rate * 0.15))
    parts = []
    for i, chunk in enumerate(chunks):
        ssml = to_ssml(chunk)
        parts.append(model.apply_tts(ssml_text=ssml, speaker=voice, sample_rate=sample_rate, put_accent=False, put_yo=False))
        if i < len(chunks) - 1:
            parts.append(gap)
    audio = torch.cat(parts) if len(parts) > 1 else parts[0]
    pcm16 = (audio.clamp(-1, 1).numpy() * 32767).astype("int16")
    tmp_wav = f"/tmp/tts_{os.getpid()}_{id(text)}.wav"
    tmp_ogg = tmp_wav.replace(".wav", ".ogg")
    with wave.open(tmp_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16.tobytes())
    subprocess.run(
        ["ffmpeg", "-y", "-i", tmp_wav, "-c:a", "libopus", "-b:a", "32k", tmp_ogg],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    with open(tmp_ogg, "rb") as f:
        data = f.read()
    os.remove(tmp_wav)
    os.remove(tmp_ogg)
    return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        if self.path != "/speak":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        text = body.get("text", "").strip()
        voice = body.get("voice", "kseniya")
        if not text:
            self.send_response(400)
            self.end_headers()
            return
        try:
            audio = synthesize(text, voice)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/ogg")
        self.send_header("Content-Length", str(len(audio)))
        self.end_headers()
        self.wfile.write(audio)

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    get_model()
    get_accentizer()
    print(f"TTS ready on :{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
