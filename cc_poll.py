# Темп опроса usage-эндпоинта Anthropic — чистые функции без сети, диска и часов:
# время и «случайность» приходят аргументами, поэтому правила проверяются тестами
# (test_cc_poll.py), а cc_limits.py только вызывает их и хранит состояние.
#
# Зачем. Эндпоинт /api/oauth/usage лимитирует не-first-party клиентов: по замерам
# сообщества — порядка 28–30 запросов в час на аккаунт (скользящий час), перегруз даёт
# 429 на срок до часа, паузой не снимается. Фиксированный poll_sec=120 с — это 30
# запросов в час, ровно на потолке; история 90 → 110 → 120 с совпала с 429-инцидентами.
# Поэтому темп считаем по ситуации: часто — когда это нужно (окно растёт и близко
# порог), редко — когда цифры стоят на месте, и никогда — выше бюджета в час.
import email.utils
import time

# --- Константы. Каждая с причиной; менять только здесь (или ключом adaptive_poll в config.json).
BASE_ACTIVE = 180    # с. Активный аккаунт: 20 запросов/ч — запас до потолка ~28–30
IDLE_ACTIVE = 300    # с. Цифры стоят — активный опрашиваем реже (12/ч)
BASE_SPARE = 300     # с. Запасные не расходуют квоту сами по себе (=прежний inactive_poll_sec)
IDLE_SPARE = 600     # с. Запасной, где ничего не меняется
NEAR_POLL = 60       # с. Окно растёт и порог близко: реакция на переключение важнее экономии
NEAR_MARGIN = 15     # пп до порога, с которых включается NEAR_POLL
MOVE_EPS = 1.0       # пп. Меньшее изменение — «без движения» (утилизация приходит с шагом 1)
STILL_STEPS = 3      # столько опросов подряд без движения до IDLE (рост линейный)
JITTER = 0.10        # ±10 %: развести во времени аккаунты и несколько установок на одном IP
MIN_INTERVAL = 30    # с. Не чаще: прежний «дедуп 30 с» в collect()
BUDGET_PER_HOUR = 20  # запросов usage в скользящий час на аккаунт; потолок ~28–30, запас на profile/рефреш
WINDOW = 3600        # с. Окно подсчёта бюджета
RESET_SLACK = 15     # с после сброса окна, когда опрашиваем снова (как в poll_loop)
RA_SLACK = 30        # с поверх Retry-After
RA_MAX = 3600        # с. Дольше часа не ждём, даже если сервер попросил больше
BACKOFF_BASE = 300   # с. 429 без Retry-After (или с Retry-After: 0 от edge): первая пауза
BACKOFF_FACTOR = 1.5  # рост паузы при подряд идущих 429
BACKOFF_CAP = 1800   # с. Потолок роста
SLEEP_MAX = 120      # с. Цикл просыпается не реже: переключение по времени, смена паузы и т.п.
SLEEP_MIN = 5        # с. Не чаще, чем раз в 5 с

DEFAULTS = {
    "base_active": BASE_ACTIVE, "idle_active": IDLE_ACTIVE,
    "base_spare": BASE_SPARE, "idle_spare": IDLE_SPARE,
    "near_poll": NEAR_POLL, "near_margin": NEAR_MARGIN, "move_eps": MOVE_EPS,
    "still_steps": STILL_STEPS, "jitter": JITTER, "min_interval": MIN_INTERVAL,
    "budget_per_hour": BUDGET_PER_HOUR, "reset_slack": RESET_SLACK,
    "ra_slack": RA_SLACK, "backoff_base": BACKOFF_BASE, "backoff_cap": BACKOFF_CAP,
}


def enabled(cfg):
    """adaptive_poll в config.json: true (по умолчанию) | false (прежнее поведение) | {переопределения}."""
    v = (cfg or {}).get("adaptive_poll", True)
    return bool(v) if not isinstance(v, dict) else v.get("enabled", True) is not False


def params(cfg):
    """Константы + переопределения из adaptive_poll-словаря. poll_sec / inactive_poll_sec, поднятые
    выше базы вручную, считаем осознанным решением «опрашивать реже» и берём как базу."""
    p = dict(DEFAULTS)
    v = (cfg or {}).get("adaptive_poll")
    if isinstance(v, dict):
        for k, x in v.items():
            if k in p and isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0:
                p[k] = x
    try:
        ps = float((cfg or {}).get("poll_sec") or 0)
    except (TypeError, ValueError):
        ps = 0
    if ps > p["base_active"]:
        p["base_active"] = ps
        p["idle_active"] = max(p["idle_active"], ps)
    try:
        isp = float((cfg or {}).get("inactive_poll_sec") or 0)
    except (TypeError, ValueError):
        isp = 0
    if isp > p["base_spare"]:  # так же: inactive_poll_sec, поднятый выше базы, — осознанное «реже»
        p["base_spare"] = isp
    p["idle_active"] = max(p["idle_active"], p["base_active"])
    p["idle_spare"] = max(p["idle_spare"], p["base_spare"])
    return p


def parse_retry_after(value, now=None):
    """Retry-After: число секунд или HTTP-дата → секунды (float ≥ 0); нет/мусор → None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        sec = float(s)
        return sec if sec >= 0 and sec == sec and sec != float("inf") else None
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(s)
        now = time.time() if now is None else now
        return max(dt.timestamp() - now, 0.0)
    except (TypeError, ValueError, IndexError):
        return None


def backoff_seconds(retry_after, fails, p=None):
    """Сколько ждать после 429. Retry-After > 0 — слушаемся (+запас, не больше часа).
    Нет или 0 (так отвечает edge) — растущая пауза 300 → 450 → 675 … до 1800 с."""
    p = p or DEFAULTS
    if retry_after is not None and retry_after > 0:
        return min(retry_after + p["ra_slack"], RA_MAX + p["ra_slack"])
    n = max(int(fails or 1), 1) - 1
    return min(p["backoff_base"] * BACKOFF_FACTOR ** n, p["backoff_cap"])


def budget_wait(hist, now, budget=BUDGET_PER_HOUR):
    """Через сколько секунд можно сделать следующий запрос, не выходя за budget в скользящий час."""
    recent = sorted(t for t in (hist or []) if now - t < WINDOW)
    if len(recent) < budget:
        return 0.0
    return max(recent[len(recent) - budget] + WINDOW - now, 0.0) + 1.0  # +1 с: запас на округление секунд сервером


def _moved(cur, prev, eps):
    """Изменилась ли хоть одна из цифр окон на eps пп и больше (сброс окна — тоже движение)."""
    for a, b in zip(cur, prev):
        if a is not None and b is not None and abs(a - b) >= eps:
            return True
    return False


def _near(cur, prev, limits, p):
    """Окно растёт, и до его порога осталось меньше near_margin пп (но аккаунт ещё не на 100 %)."""
    for a, b, lim in zip(cur, prev, limits):
        if a is None or b is None or lim is None or a >= 100:
            continue
        if a - b >= p["move_eps"] and lim - a < p["near_margin"]:
            return True
    return False


def interval(*, is_active, still, near, reset_in, p, unit=0.5):
    """Желаемая пауза до следующего опроса, с. still — опросов подряд без движения;
    reset_in — через сколько секунд сбросится ближайшее окно (None — неизвестно);
    unit ∈ [0, 1] — «случайность» для джиттера (в тестах подставляется явно)."""
    if near:
        base = p["near_poll"]
    else:
        lo, hi = (p["base_active"], p["idle_active"]) if is_active else (p["base_spare"], p["idle_spare"])
        k = min(max(still, 0), p["still_steps"]) / p["still_steps"]
        base = lo + (hi - lo) * k
    base *= 1 + p["jitter"] * (2 * unit - 1)
    if reset_in is not None and reset_in >= 0 and reset_in + p["reset_slack"] < base:
        base = reset_in + p["reset_slack"]  # сброс окна замечаем сразу, а не через интервал
    return max(base, p["min_interval"])


def after_poll(st, now, *, ok, pcts=None, resets_in=None, is_active=False, limits=(None, None),
               wait429=None, p=None, unit=0.5):
    """Новое состояние расписания аккаунта после попытки опроса.

    st      — прежнее {hist, pct, still, fails, next, interval} (None — первый опрос);
    ok      — usage получен; pcts — (сессия %, неделя %) из ответа;
    resets_in — секунды до ближайшего будущего сброса любого окна; limits — (порог сессии, потолок недели);
    wait429 — пауза после 429 из backoff_seconds (None — сбой не 429, ждём обычный интервал).
    Бюджет учитывается всегда: запрос засчитывается и при сбое — сервер считает попытки."""
    p = p or DEFAULTS
    st = dict(st or {})
    hist = [t for t in st.get("hist") or [] if now - t < WINDOW] + [now]
    prev = st.get("pct")
    still = st.get("still", 0)
    near = False
    if ok and pcts is not None:
        if prev is None:
            still = 0
        elif _moved(pcts, prev, p["move_eps"]):
            still = 0
        else:
            still += 1
        near = prev is not None and _near(pcts, prev, limits, p)
        st["pct"] = list(pcts)
    fails = st.get("fails", 0)
    if wait429 is not None:  # 429 мог прийти и от profile/рефреша при удачном usage — тоже считаем
        fails += 1
    elif ok:
        fails = 0
    iv = interval(is_active=is_active, still=still, near=near, reset_in=resets_in, p=p, unit=unit)
    if wait429 is not None:
        iv = max(iv, wait429)
    iv = max(iv, budget_wait(hist, now, int(p["budget_per_hour"])))
    st.update(hist=hist, still=still, fails=fails, near=near, interval=round(iv, 1), next=now + iv)
    return st


def due(st, now):
    """Пора ли опрашивать: расписания нет (первый раз, после перезапуска без файла) или срок пришёл."""
    return not st or now >= st.get("next", 0)


def sleep_for(sched, now):
    """Сколько спать циклу опроса: до ближайшего срока любого аккаунта, не меньше SLEEP_MIN
    и не больше SLEEP_MAX (по времени идут и другие дела цикла, не только сеть)."""
    nxt = [s.get("next", 0) for s in (sched or {}).values() if s]
    if not nxt:
        return SLEEP_MAX
    return min(max(min(nxt) - now, SLEEP_MIN), SLEEP_MAX)


def retarget(st, is_active, p=None):
    """Запасной стал активным: срок опроса не позже базы активного от последнего опроса
    (иначе свежеактивный аккаунт мог бы ждать до 600 с). Во время паузы после 429 не трогаем."""
    p = p or DEFAULTS
    if not st or not is_active or st.get("active", True) or st.get("fails"):
        return st
    hist = st.get("hist") or []
    if not hist:
        return st
    return dict(st, next=min(st.get("next", 0), max(hist) + p["base_active"]))
