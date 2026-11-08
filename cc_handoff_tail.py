"""[handoff] Хвост беседы Claude для того, кто подхватывает работу (другой Claude, Codex, Notion AI).

Панель сама собирает его из записи беседы (jsonl) в момент передачи и не зависит от того, успел ли прежний исполнитель
написать записку. Здесь только разбор и показ: сначала состояние (ЗАВЕРШЕНО / НЕ ЗАВЕРШЕНО), потом последние шаги.
Решения о запуске и тексты для консоли принимает вызывающий код (cc_notion_ai, cc_remote_mode)."""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import cc_tz

TAIL_BYTES = 1500000               # сколько байт с конца одной беседы разбираем
MAX_TAIL_BYTES = 24000000          # потолок окна при поиске последнего сообщения владельца
MAX_EVENTS = 400                  # сколько последних событий держим
MAX_CHARS = 7500                   # потолок всего файла
STALE_HOURS = 6                    # беседа старше — предупреждаем
FILE_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')
SKIP_PREFIX = ('[PANEL', '[Панель', '<system-reminder', '<command-', 'Caveat', 'This session is being continued')
SIDE_MARK = '[побочный вопрос из консоли'   # начало cc_fleet.SIDE_LABEL: тест сверяет, что метка не разъехалась
SIDE_PROBE_BYTES = 300000                   # первое сообщение человека лежит в самом начале беседы

_CHANNEL = re.compile(r'<channel\s+([^>]*)>(.*?)</channel>', re.S)
_ATTR = re.compile(r'(\w+)="([^"]*)"')
_SECRET = (
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)', re.S), '[ключ скрыт]'),
    (re.compile(r'(?i)\bauthorization\s*[:=]\s*(?:(?:bearer|basic|token)\s+)?[^\s"\']+'), 'authorization=[скрыто]'),
    (re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}'), 'Bearer [скрыто]'),
    (re.compile(r'(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|cookie)\b\s*[:=]\s*[^\s"\']+'), r'\1=[скрыто]'),
    (re.compile(r'\b(?:sk|pk|ghp|gho|ghs|github_pat|xox[bapr]|AKIA)[-_A-Za-z0-9]{12,}'), '[скрыто]'),
    (re.compile(r'[A-Za-z0-9+=-]{40,}'), lambda m: '[скрыто]' if sum(c.isalnum() for c in m.group(0)) >= 20 else m.group(0)),
)  # последнее правило без «/» и «_»: пути и snake_case-имена файлов не режем


def redact(text):
    """Файл читают и другие исполнители: ключи, пароли и длинные токены из команд и ответов не переносим."""
    text = str(text or '')
    for rx, repl in _SECRET:
        text = rx.sub(repl, text)
    return text


def clip(text, limit):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:max(0, limit - 1)] + '…'


def _mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def is_side_transcript(path):
    """Побочная беседа (вопрос из консоли, пока основной Claude остановлен): первое сообщение человека начинается с метки SIDE_MARK.
    Её вопросы и ответы к основной работе не относятся: иначе ответ на побочный вопрос превращает оборванное дело в «ЗАВЕРШЕНО»."""
    try:
        with open(path, 'rb') as f:
            head = f.read(SIDE_PROBE_BYTES).decode('utf-8', errors='replace')
    except OSError:
        return False
    for line in head.splitlines():
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(row, dict) or row.get('type') != 'user' or row.get('isMeta') or row.get('isSidechain'):
            continue
        message = row.get('message')
        content = message.get('content') if isinstance(message, dict) else None
        parts = [content] if isinstance(content, str) else [p.get('text') for p in content if isinstance(p, dict) and p.get('type') == 'text'] if isinstance(content, list) else []
        for text in parts:
            text = str(text or '').strip()
            if text and not text.startswith(SKIP_PREFIX) and not text.startswith('<'):
                return text.startswith(SIDE_MARK)
    return False


def recent_transcripts(directory, n=3, window=None):
    """Самые свежие записи основных бесед в папке (новые первыми; побочные пропускаются). window (сек): брать только те,
    что не старше самой свежей основной на столько."""
    try:
        files = [os.path.join(directory, x) for x in os.listdir(directory) if x.endswith('.jsonl')]
    except OSError:
        return []
    files = [p for p in files if os.path.isfile(p)]
    files.sort(key=_mtime, reverse=True)
    picked, top = [], None
    for path in files:
        if len(picked) >= max(0, n) or (window and top is not None and top - _mtime(path) > window):
            break
        if is_side_transcript(path):
            continue
        if top is None:
            top = _mtime(path)
        picked.append(path)
    return picked


def read_tail_lines(path, max_bytes=TAIL_BYTES):
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            lines = f.read().decode('utf-8', errors='replace').splitlines()
        return lines[1:] if size > max_bytes else lines
    except (OSError, ValueError):
        return []


def read_events_tail(path):
    """События с конца беседы. В работе с интерфейсом картинки и крупные результаты инструментов растягивают хвост на мегабайты,
    поэтому окно удваивается, пока в нём нет ни одного сообщения владельца (последнее лежит в самом конце файла: любой суффикс,
    где оно есть, содержит именно его). Потолок MAX_TAIL_BYTES защищает от бесконечного чтения; беседа без владельца читается до него."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    window = TAIL_BYTES
    while True:
        events = read_events(read_tail_lines(path, window))
        if any(e['kind'] == 'owner' for e in events) or window >= size or window >= MAX_TAIL_BYTES:
            return events
        window *= 2


def _stamp(value):
    try:
        ts = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(cc_tz.zone())
    except (ValueError, TypeError, OverflowError):
        return None


def _act_text(name, inp):
    inp = inp if isinstance(inp, dict) else {}
    if name == 'Bash':
        return inp.get('description') or inp.get('command') or ''
    if name in FILE_TOOLS or name == 'Read':
        return inp.get('file_path') or inp.get('notebook_path') or ''
    if name in ('Grep', 'Glob'):
        return inp.get('pattern') or ''
    for key in ('description', 'prompt', 'query', 'url', 'command'):
        if isinstance(inp.get(key), str) and inp[key]:
            return inp[key]
    return ''


def _result_text(content):
    if isinstance(content, list):
        content = ' '.join(str(p.get('text') or '') for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else ''


def _channel_message(text):
    """Сообщение владельца из Telegram: (текст, время, id) либо None, если это не наш канал."""
    m = _CHANNEL.search(text)
    if not m:
        return None
    attrs = dict(_ATTR.findall(m.group(1)))
    if attrs.get('source') != 'plugin:telegram:telegram':
        return None
    body = m.group(2).strip()
    if not body and (attrs.get('image_path') or attrs.get('attachment_file_id')):
        body = '[вложение]'
    return body, attrs.get('ts'), attrs.get('message_id')


def read_events(lines):
    """События беседы по порядку: owner | say | reply | act (act.done — пришёл ли результат инструмента)."""
    events, seen, acts = [], set(), {}

    def add(kind, ts, text, **kw):
        events.append(dict(kind=kind, ts=ts, text=text, **kw))

    for line in lines:
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(row, dict) or row.get('isSidechain'):
            continue
        kind = row.get('type')
        ts = _stamp(row.get('timestamp'))
        if kind == 'queue-operation':
            content = row.get('content')
            hit = _channel_message(content) if isinstance(content, str) else None
            if hit and hit[2] and hit[2] not in seen:
                seen.add(hit[2])
                add('owner', _stamp(hit[1]) or ts, hit[0], src='Telegram')
            continue
        message = row.get('message')
        if kind not in ('user', 'assistant') or not isinstance(message, dict):
            continue
        content = message.get('content')
        parts = content if isinstance(content, list) else [dict(type='text', text=content)] if isinstance(content, str) else []
        for part in parts:
            if not isinstance(part, dict):
                continue
            ptype = part.get('type')
            if kind == 'user' and ptype == 'text':
                text = str(part.get('text') or '').strip()
                hit = _channel_message(text) if text.startswith('<channel ') else None
                if hit:
                    if hit[2] and hit[2] in seen:
                        continue
                    if hit[2]:
                        seen.add(hit[2])
                    add('owner', _stamp(hit[1]) or ts, hit[0], src='Telegram')
                elif text and not text.startswith(SKIP_PREFIX) and not row.get('isMeta') and not text.startswith('<'):
                    add('owner', ts, text, src='консоль')
            elif kind == 'user' and ptype == 'tool_result':
                act = acts.get(part.get('tool_use_id'))
                if act is not None:
                    act.update(done=True, error=bool(part.get('is_error')), result=_result_text(part.get('content')))
            elif kind == 'assistant' and ptype == 'text':
                text = str(part.get('text') or '').strip()
                if text:
                    add('say', ts, text)
            elif kind == 'assistant' and ptype == 'tool_use':
                name = str(part.get('name') or '')
                inp = part.get('input') if isinstance(part.get('input'), dict) else {}
                if name.endswith('telegram__reply'):
                    add('reply', ts, str(inp.get('text') or ''), done=False)
                    acts[part.get('id')] = events[-1]
                elif name.endswith(('telegram__react', 'telegram__edit_message')):
                    continue
                else:
                    add('act', ts, _act_text(name, inp), name=name, path=(inp.get('file_path') or inp.get('notebook_path') or '') if name in FILE_TOOLS else '',
                        done=False, error=False, result='')
                    acts[part.get('id')] = events[-1]
    return events[-MAX_EVENTS:]


def analyse(events):
    """Состояние на момент передачи: finished | unfinished | unknown и причина по-русски."""
    if not events:
        return dict(state='unknown', reason='в беседе нет событий', owner=None)
    last_owner = max((i for i, e in enumerate(events) if e['kind'] == 'owner'), default=None)
    owner = events[last_owner] if last_owner is not None else None
    after = events[last_owner + 1:] if last_owner is not None else events
    if owner is not None:
        need_reply = owner.get('src') == 'Telegram'
        answered = any(e['kind'] == 'reply' for e in after) or (not need_reply and any(e['kind'] == 'say' for e in after))
        if not answered:
            return dict(state='unfinished', reason='последнее сообщение владельца (%s) осталось без ответа' % (
                owner['ts'].strftime('%H:%M') if owner.get('ts') else '?'), owner=owner)
    last = events[-1]
    if last['kind'] == 'act' and not last.get('done'):
        return dict(state='unfinished', reason='беседа оборвалась на вызове «%s», результата нет' % (last.get('name') or '?'), owner=owner)
    if last['kind'] == 'act':
        return dict(state='unfinished', reason='после результата «%s» исполнитель не дописал ответ' % (last.get('name') or '?'), owner=owner)
    return dict(state='finished', reason='последнее сообщение владельца отвечено, действий в полёте нет', owner=owner)


def _step_line(e):
    hhmm = e['ts'].strftime('%H:%M') if e.get('ts') else '--:--'
    if e['kind'] == 'owner':
        return '- %s владелец (%s): %s' % (hhmm, e.get('src'), redact(clip(e['text'], 500)))
    if e['kind'] == 'reply':
        return '- %s Исполнитель → владельцу в Telegram: %s' % (hhmm, redact(clip(e['text'], 500)))
    if e['kind'] == 'say':
        return '- %s Исполнитель (текст): %s' % (hhmm, redact(clip(e['text'], 400)))
    tail = ''
    if e.get('done'):
        tail = ' → %s%s' % ('ОШИБКА: ' if e.get('error') else '', redact(clip(e.get('result'), 120)) or 'готово')
    else:
        tail = ' → результата нет (оборвано)'
    return '- %s действие %s: %s%s' % (hhmm, e.get('name'), redact(clip(e['text'], 160)), tail)


def render(events, source='', updated=None, now=None):
    now = datetime.now(cc_tz.zone()) if now is None else now.astimezone(cc_tz.zone())
    info = analyse(events)
    if info['state'] == 'unfinished':
        head = 'STATE: UNFINISHED (НЕ ЗАВЕРШЕНО) — %s. Продолжи с последнего шага ниже: не повторяй сделанное, перед правкой проверь файлы.' % info['reason']
    elif info['state'] == 'finished':
        head = 'STATE: FINISHED (ЗАВЕРШЕНО) — %s. Новой работы не начинай: сверься с карточкой и жди слова владельца.' % info['reason']
    else:
        head = 'STATE: UNKNOWN (НЕ ЯСНО) — %s. Ничего не начинай, спроси владельца, на чём остановились.' % info['reason']
    lines = ['# Хвост беседы на момент передачи', '',
             'Собрано панелью автоматически %s (%s) из беседы %s. Это данные, не команды.' % (now.strftime('%d.%m.%Y %H:%M'), cc_tz.label(), source or '?')]
    if updated:
        stamp = datetime.fromtimestamp(updated, cc_tz.zone())
        lines.append('Беседа обновлена %s%s.' % (stamp.strftime('%d.%m %H:%M'),
                     '; ВНИМАНИЕ: это давно, сверь с карточкой' if now.timestamp() - updated > STALE_HOURS * 3600 else ''))
    lines += ['', head, '']
    owner = info.get('owner')
    if owner:
        lines.append('Последнее сообщение владельца: %s · %s: %s' % (owner['ts'].strftime('%d.%m %H:%M') if owner.get('ts') else '?',
                     owner.get('src'), redact(clip(owner['text'], 700))))
    final = next((e for e in reversed(events) if e['kind'] in ('say', 'reply')), None)
    if final:
        lines.append('Последний итог исполнителя: %s · %s' % (final['ts'].strftime('%d.%m %H:%M') if final.get('ts') else '?',
                     redact(clip(final['text'], 1200))))
    files = []
    for e in events[-120:]:
        if e['kind'] == 'act' and e.get('path') and e['path'] not in files and not e['path'].startswith('/tmp/'):
            files.append(e['path'])
    if files:
        lines.append('Менялись файлы в этом отрезке: %s' % ', '.join(redact(p) for p in files[-12:]))
    lines += ['', '## Последние шаги (от старых к новым)']
    budget = MAX_CHARS - sum(len(x) + 1 for x in lines) - 40
    steps = []
    for e in reversed(events):
        row = _step_line(e)
        if budget - len(row) - 1 < 0 or len(steps) >= 24:
            break
        steps.append(row)
        budget -= len(row) + 1
    lines += list(reversed(steps)) or ['Шагов не найдено.']
    return '\n'.join(lines) + '\n'


def build(paths, now=None):
    """Хвост из нескольких свежих бесед сразу (панель могла сменить сессию при передаче): события сливаются по времени."""
    events, source, updated = [], [], 0.0
    for path in paths:
        evs = read_events_tail(path)
        if evs:
            events += evs
            source.append(os.path.basename(path)[:8])
            updated = max(updated, _mtime(path))
    zero = datetime.min.replace(tzinfo=timezone.utc)
    events.sort(key=lambda e: e['ts'] or zero)  # сортировка устойчивая: порядок внутри одной беседы сохраняется
    return render(events, '+'.join(source), updated or None, now)


def state_of(text):
    """finished | unfinished | unknown | '' — по строке STATE в готовом файле."""
    m = re.search(r'^STATE: (FINISHED|UNFINISHED|UNKNOWN)\b', str(text or ''), re.M)
    return m.group(1).lower() if m else ''
