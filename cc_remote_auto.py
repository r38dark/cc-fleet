"""[remote] Автопереключение работы между Claude-аккаунтами (DEV ↔ PROD): когда лимит заканчивается у того, где идёт работа,
а на другом он есть, работа переключается на другой. Вручную переключённая работа остаётся там, куда её переключили.
Codex и агент Notion сюда не входят: на них переключает человек.

Решение принимает чистая функция decide(): ей даётся снимок (Claude DEV, PROD, режим передачи, память тиков),
она возвращает действие. tick() собирает снимок, вызывает decide() и выполняет действие через cc_remote_mode.
Выключено по умолчанию: включает человек переключателем в панели (remote_auto.json → enabled)."""
import argparse
import json
import os
import threading
import time

import cc_avail
import cc_remote as R

CFG_FILE = os.environ.get("CC_REMOTE_AUTO") or R.BASE + "/remote_auto.json"
DEFAULTS = dict(enabled=False, dry_run=False, ticks=2, cooldown=900, sim_level="", sim_prod="")  # sim_*: проверка вживую — подмена состояния Claude DEV (hard/none) и PROD ("1" пригоден, "0" нет)
TICK_SEC = 30
KICK_FILE = os.environ.get("CC_REMOTE_AUTO_KICK") or R.BASE + "/remote_auto_kick.json"   # хук паузы просит панель передать работу сейчас
HB_FILE = os.environ.get("CC_REMOTE_AUTO_HB") or R.BASE + "/remote_auto_hb.json"          # «пульс» потока панели: жив ли тот, кто примет запрос
MODE_FILE = os.environ.get("CC_REMOTE_MODE") or R.BASE + "/remote_mode.json"
KICK_TTL = 90      # сек: за это время панель обязана взять запрос, иначе хук ставит обычную паузу
HB_MAX = 90        # сек: пульс старше — потока нет, пауза как раньше
PROD_FRESH = 600   # сек: цифры PROD старше не считаем (их обновляет тот же поток)
FORCE_AFTER = 120  # сек: PROD выше порога, а ход не кончается (хука паузы на PROD нет) — после стольких секунд отказов переключаем принудительно
BLOCKED = ("hard", "week", "weekrisk")   # у Claude DEV нет, где работать (уровни pause_ctl.level_state)
_memo = dict(to_prod=0, to_native=0, both_notified=False, last_return=0.0, last_action="", last_reason="", last_at=0.0)
_lock = threading.Lock()


def load():
    try:
        with open(CFG_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        raw = {}
    out = dict(DEFAULTS)
    if isinstance(raw, dict):
        out.update({k: raw[k] for k in DEFAULTS if k in raw})
    out["enabled"] = bool(out["enabled"])
    return out


def save(cfg):
    tmp = "%s.tmp%d" % (CFG_FILE, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: cfg[k] for k in DEFAULTS}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CFG_FILE)


def set_enabled(on):
    with _lock:
        cfg = load()
        cfg["enabled"] = bool(on)
        save(cfg)
        _memo.update(to_prod=0, to_native=0, both_notified=False)
    return cfg


def prod_state(row, thr, cap, now=None):
    """Пригоден ли PROD для работы: на связи, без ошибки входа и ниже порогов (те же, что у аккаунтов Claude DEV)."""
    if not row or not row.get("online"):
        return dict(usable=False, why="нет данных или связи")
    if row.get("error") == "token_expired":
        # Claude на PROD давно не работал, токен истёк: при запуске он обновится сам. Решаем по последним известным цифрам
        view = R.expired_view(row, now)
        if not view.get("known"):
            return dict(usable=False, why="токен устарел, цифр лимита нет", stale=True)
        ok, _t, why = cc_avail.availability(view, thr, cap, now)
        return dict(usable=ok, why=why, stale=True)
    if row.get("error"):
        return dict(usable=False, why="нет данных или связи")
    ok, _t, why = cc_avail.availability(row, thr, cap, now)
    return dict(usable=ok, why=why)


def decide(now, cfg, native, prod, mode, memo):
    """(действие, причина). Действия: None | 'to_prod' | 'to_native' | 'notify_both'.
    native: level, stale, role, notion_active; prod: usable, why; mode: active, busy, since.
    memo (меняется): to_prod, to_native — подряд идущие тики с одним и тем же решением; both_notified, last_return."""
    if not cfg.get("enabled") or mode.get("busy") or native.get("stale"):
        memo.update(to_prod=0, to_native=0)
        return None, ""
    need = max(1, int(cfg.get("ticks") or 2))
    native_blocked = native.get("level") in BLOCKED
    if not mode.get("active"):
        memo["to_native"] = 0
        memo["both_notified"] = False
        works = native.get("role") == "solo" and not native.get("notion_active")
        if (native_blocked and works and prod.get("usable")
                and now - max(float(memo.get("last_return") or 0), float(mode.get("returned") or 0)) >= float(cfg.get("cooldown") or 0)):
            memo["to_prod"] += 1
            if memo["to_prod"] >= need:
                memo["to_prod"] = 0
                return "to_prod", "у Claude DEV нет лимита, на Claude PROD есть"
        else:
            memo["to_prod"] = 0
        return None, ""
    memo["to_prod"] = 0
    native_ok = not native_blocked
    back = None
    # переключаемся только когда лимит заканчивается у того, где идёт работа (здесь — PROD), а на другом есть;
    # «вернуться, потому что у DEV свободно» нет: куда человек переключил вручную, там работа и остаётся
    if native_ok and not prod.get("usable"):
        back = "лимит на Claude PROD исчерпан, у Claude DEV есть"
    if back:
        memo["to_native"] += 1
        if memo["to_native"] >= need:
            memo["to_native"] = 0
            return "to_native", back
        return None, ""
    memo["to_native"] = 0
    if not native_ok and not prod.get("usable"):
        if not memo.get("both_notified"):
            memo["both_notified"] = True
            return "notify_both", "лимиты закончились и у Claude DEV, и на Claude PROD"
    else:
        memo["both_notified"] = False
    return None, ""


def _pc(value):
    return "%s%%" % (round(value) if value is not None else "?")


def limits_line(native, row):
    """Лимиты обоих аккаунтов для уведомления: сколько занято в окне 5 часов и за неделю."""
    shown = R.expired_view(row) if row.get("error") == "token_expired" else row
    line = "Claude DEV — 5 ч %s, неделя %s; Claude PROD — 5 ч %s, неделя %s" % (
        _pc(native.get("pct")), _pc(native.get("wpct")),
        _pc((shown.get("five_hour") or {}).get("pct")), _pc((shown.get("seven_day") or {}).get("pct")))
    return line + (" (цифры PROD по последней проверке: токен устарел)" if row.get("error") == "token_expired" else "")


def sentence(text):
    text = str(text or "")
    return text[:1].upper() + text[1:]


def status():
    cfg = load()
    return dict(cfg, last_action=_memo["last_action"], last_reason=_memo["last_reason"], last_at=_memo["last_at"])


def _notify(ns, text):
    try:
        ns["tg_notify"](text)
    except Exception:
        pass


def _snapshot(ns, mid):
    import pause_ctl
    ls = pause_ctl.level_state()
    role = ""
    try:
        role = ns["FLEET_PROFILES"].state.public()["engines"]["claude"]["role"]
    except Exception:
        pass
    acc = (ls.get("accounts") or {}).get(ls.get("active")) or {}
    native = dict(level=ls.get("level") or "none", stale=bool(ls.get("stale")), role=role,
                  notion_active=bool(pause_ctl._notion_ai_active()), line=ls.get("line") or "",
                  pct=acc.get("pct"), wpct=acc.get("wpct"))
    sim = str(load().get("sim_level") or "")
    if sim:
        native.update(level=sim, stale=False)
    row = R.fetch_limits(mid)
    prod = prod_state(row, pause_ctl._threshold(), pause_ctl._weekly_cap())
    sim_prod = str(load().get("sim_prod") or "")
    if sim_prod in ("0", "1"):
        prod.update(usable=sim_prod == "1")
    prod["row"] = row or {}
    return native, prod


def _jfile(path):
    d = R.jload(path, {})
    return d if isinstance(d, dict) else {}


def _pause():
    import pause_ctl
    return pause_ctl


def handoff_ready(now=None):
    """(можно ли вместо паузы передать работу на PROD, причина). Только файлы: зовут хуки паузы в отдельном процессе.
    Условия: автопередача включена, поток панели жив (свежий пульс), Claude DEV не на PROD, нет профиля Notion AI,
    у DEV нет лимита, остыл кулдаун, у PROD свежие цифры и он пригоден. Передачу всё равно решает панель (tick), хук только просит."""
    now = now or time.time()
    cfg = load()
    if not cfg["enabled"] or cfg["dry_run"]:
        return False, "автопередача выключена"
    hb = _jfile(HB_FILE)
    if now - float(hb.get("ts") or 0) > HB_MAX:
        return False, "поток автопередачи не отвечает"
    md = _jfile(MODE_FILE)
    if md.get("active"):
        return False, "работа уже на PROD"
    if md.get("stage") and now - float(md.get("since_ts") or 0) < 300:
        return True, "передача на PROD уже идёт"
    pc = _pause()
    if pc._notion_ai_active():
        return False, "включён профиль Notion AI"
    if now - max(float(hb.get("last_return") or 0), 0.0) < float(cfg.get("cooldown") or 0):
        return False, "рано после переключения с PROD"
    ls = pc.level_state()
    if ls.get("stale") or ls.get("level") not in BLOCKED:
        return False, "у Claude DEV есть, где работать"
    mid = next(iter(R.members()), "")
    row = R.cached().get(mid) if mid else None
    if not row or now - float(row.get("ts") or 0) > PROD_FRESH:
        return False, "нет свежих цифр PROD"
    prod = prod_state(row, pc._threshold(), pc._weekly_cap(), now)
    sim = str(cfg.get("sim_prod") or "")
    if sim in ("0", "1"):
        prod["usable"] = sim == "1"
    if not prod.get("usable"):
        return False, "Claude PROD непригоден: %s" % (prod.get("why") or "?")
    return True, "у Claude DEV нет лимита, на Claude PROD есть"


def kick_ts():
    return float(_jfile(KICK_FILE).get("ts") or 0)


def pending(now=None):
    """Запрос на передачу отправлен и ещё ждёт панель (свежий, панель его не брала)."""
    d = _jfile(KICK_FILE)
    ts = float(d.get("ts") or 0)
    return bool(ts) and not d.get("taken") and (now or time.time()) - ts <= KICK_TTL


def _kick_taken(ts):
    """Панель взяла запрос: отмечаем, чтобы следующий запрос (новый лимит) не принимали за зависший."""
    d = _jfile(KICK_FILE)
    if float(d.get("ts") or 0) == ts:
        R.jsave(KICK_FILE, dict(d, taken=time.time()))


def request_handoff(now=None):
    """(True, причина) — паузу не ставим: панель передаст работу на PROD в ближайшую секунду-две. Идемпотентно:
    запрос не старше KICK_TTL не переписывается; запрос, который панель не взяла, считается неудавшимся (пауза как раньше)."""
    now = now or time.time()
    ok, why = handoff_ready(now)
    if not ok:
        return False, why
    if why == "передача на PROD уже идёт" or pending(now):
        return True, why
    d = _jfile(KICK_FILE)
    if d.get("ts") and not d.get("taken") and now - float(d["ts"]) <= 600:
        return False, "панель не подхватила запрос на передачу"   # прошлый запрос завис — обычная пауза
    R.jsave(KICK_FILE, {"ts": now, "reason": why})
    return True, why


def _heartbeat():
    R.jsave(HB_FILE, {"ts": time.time(), "last_return": float(_memo.get("last_return") or 0)})


def _queue_text():
    """Сообщения, накопленные очередью (tg_queue) за время паузы: (текст для PROD, их метки времени)."""
    try:
        import tg_queue as Q
        rows = Q._pending()
    except Exception:
        return "", []
    parts, stamps, size = [], [], 0
    for i, r in enumerate(rows, 1):
        one = "%d) %s от %s:\n%s" % (i, Q._hm(r.get("ts")), r.get("user") or "?", (r.get("text") or "").strip() or "(пусто)")
        if size + len(one) > 12000:
            break
        parts.append(one)
        stamps.append(r.get("ts"))
        size += len(one) + 2
    return "\n\n".join(parts), stamps


def _queue_taken(stamps):
    """Эти сообщения уехали на PROD вместе с передачей — отмечаем разобранными (иначе их разберёт Claude DEV после переключения второй раз)."""
    if not stamps:
        return
    try:
        import tg_queue as Q
        rows = Q._rows()
        now = time.time()
        for r in Q._pending(rows):
            if r.get("ts") in stamps:
                r["taken_ts"] = now
        Q._rewrite(rows)
    except Exception as exc:
        print("remote-auto: очередь не отмечена разобранной: %r" % (exc,), flush=True)


def _pause_fallback(ns, why):
    """Запрос на передачу не удался (панель не смогла или передавать нельзя): обычная пауза, как будто хук ничего не просил."""
    try:
        import cc_remote_mode as M
        if M.busy() or M.active():
            return
        pc = _pause()
        ls = pc.level_state()
        if ls.get("stale") or ls.get("level") not in ("hard", "week"):
            return
        print("remote-auto: передача не состоялась (%s) — ставлю паузу" % why, flush=True)
        pc.cmd_set(argparse.Namespace(reason="лимиты сессионного окна", resume_at="", no_handoff=True,
                                      note="передача на Claude PROD не состоялась (%s)" % why))
    except Exception as exc:
        print("remote-auto: пауза после неудачной передачи не встала: %r" % (exc,), flush=True)


def tick(ns, kicked=False):
    """Один проход: собрать снимок, решить, выполнить. Ошибки не пробрасываются (поток живёт дальше).
    kicked: хук паузы попросил передать работу сейчас — вторую проверку подряд не ждём; не вышло — ставим паузу."""
    action, started = None, False
    try:
        action, started = _tick(ns, kicked)
    finally:
        if kicked and not started:
            _pause_fallback(ns, "панель не начала передачу")
    return action


def _tick(ns, kicked=False):
    import cc_remote_mode as M
    cfg = load()
    if not cfg["enabled"]:
        return None, False
    mid = next(iter(R.members()), "")
    if not mid:
        return None, False
    if M.pair_kind():
        return None, False
    native, prod = _snapshot(ns, mid)
    md = M.mode()
    mode = dict(active=bool(md.get("active")), busy=M.busy(), since=md.get("since") or 0)
    with _lock:
        if kicked:
            _memo["to_prod"] = max(0, int(cfg.get("ticks") or 2) - 1)
        action, reason = decide(time.time(), cfg, native, prod, mode, _memo)
        if not mode["active"] or prod.get("usable"):
            _memo["off_wait"] = 0.0   # работа уже на Claude DEV или на PROD снова есть лимит — отсчёт ожидания конца ответа сбрасываем
    if mode["busy"] and kicked:
        return None, True   # передача уже идёт (запрос пришёл повторно): паузу не ставим
    if not action:
        return None, False
    _memo.update(last_action=action, last_reason=reason, last_at=time.time())
    if cfg.get("dry_run"):
        print("remote-auto: (пробный режим) %s — %s" % (action, reason), flush=True)
        return action, False
    row = prod.get("row") or {}
    limits = limits_line(native, row)
    if action == "to_prod":
        queued, stamps = _queue_text()
        res = M.on(mid, "автопередача: " + reason, queued)
        if res.get("ok"):
            _queue_taken(stamps)
            try:
                _pause().release_for_remote()   # паузу по лимитам не держим: Claude DEV остановит передача, будить его не нужно
            except Exception as exc:
                print("remote-auto: пауза не снята: %r" % (exc,), flush=True)
            _notify(ns, "🔁 Переход на Claude PROD: %s. Лимиты сейчас: %s. Работа переходит на Claude PROD." % (sentence(reason), limits))
            return action, True
        print("remote-auto: передача не началась: %s" % res.get("message"), flush=True)
        _memo["to_prod"] = max(0, _memo["to_prod"])
    elif action == "to_native":
        res = M.off("автопереключение: " + reason)
        if not res.get("ok") and res.get("answering"):
            # Claude на PROD отвечает без пауз: на PROD нет хука, который не пустил бы следующий шаг, так что тишины можно не дождаться
            # до самого конца лимита (08.11). Ждём FORCE_AFTER секунд с первого отказа, потом останавливаем его посреди хода.
            if not _memo.get("off_wait"):
                _memo["off_wait"] = time.time()
            first = float(_memo["off_wait"])
            if time.time() - first >= FORCE_AFTER:
                print("remote-auto: Claude на PROD отвечает уже %d с при исчерпанном лимите — переключаю принудительно" % (time.time() - first), flush=True)
                res = M.off("автопереключение: " + reason + " (PROD не замолкал %d с, остановлен посреди хода)" % (time.time() - first), force=True)
        if res.get("ok"):
            _memo["off_wait"] = 0.0
            _memo["last_return"] = time.time()
            _heartbeat()   # время переключения сразу в файл: по нему хук паузы знает про кулдаун
            _notify(ns, "🔁 Переход на Claude DEV: %s. Лимиты сейчас: %s. Работа переходит на Claude DEV." % (sentence(reason), limits))
        else:
            print("remote-auto: переключение не началось: %s" % res.get("message"), flush=True)
    elif action == "notify_both":
        _notify(ns, "⚠️ Лимиты закончились и у Claude DEV, и на Claude PROD. Переключи работу вручную: Codex или агент Notion AI.")
    return action, False


def start(ns):
    """Фоновый поток: проход раз в TICK_SEC, пульс раз в 10 с, запрос хука паузы — в течение секунды. Запускается один раз при старте панели."""
    def loop():
        time.sleep(20)
        _memo["last_return"] = max(float(_memo.get("last_return") or 0), float(_jfile(HB_FILE).get("last_return") or 0))   # кулдаун переживает рестарт панели
        seen = kick_ts()   # запросы до старта панели не разбираем
        last_tick, last_hb = 0.0, 0.0
        while True:
            now = time.time()
            if now - last_hb >= 10:
                last_hb = now
                try:
                    _heartbeat()
                except Exception as exc:
                    print("remote-auto: пульс не записан: %r" % (exc,), flush=True)
            kicked = False
            k = kick_ts()
            if k > seen:
                seen, kicked = k, True
                try:
                    _kick_taken(k)
                except Exception:
                    pass
            if kicked or now - last_tick >= TICK_SEC:
                last_tick = now
                try:
                    tick(ns, kicked=kicked)
                except Exception as exc:
                    print("remote-auto: сбой прохода: %r" % (exc,), flush=True)
            time.sleep(1)
    threading.Thread(target=loop, daemon=True, name="remote-auto").start()
