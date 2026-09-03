#!/usr/bin/env python3
# Гейт лимитов — «можно ли сейчас запускать фоновый (headless) прогон Claude».
#
# Зачем: фоновые задачи (cron, вотчеры, автоответчики) идут по ТОМУ ЖЕ активному
# аккаунту, что и живая интерактивная сессия. Если окно уже почти выбрано, такой
# прогон просто добивает остаток и падает на 429 — а окно нужно человеку.
#
# rc=10 — работать нельзя: либо активный аккаунт выше порога (ждём, пока балансер
#         уйдёт на свежий), либо ВСЕ аккаунты выше порога (переключаться некуда).
# rc=0  — есть живой аккаунт, запускаться можно.
# Fail-open: снапшота нет или он протух — НЕ блокируем (лишний прогон лучше
#            молча стоящего демона).
#
# Запуск:  python3 limits_gate.py [порог]      # порог по умолчанию — из config.json
# В своём скрипте:
#   python3 /opt/cc-limits/limits_gate.py || exit 0   # rc=10 => просто не стартуем
import json
import os
import sys
import time
from datetime import datetime

BASE = os.environ.get("CC_LIMITS_BASE", os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(BASE, "snapshot.json")
CONFIG = os.path.join(BASE, "config.json")
MAX_AGE = 900  # снапшот старше 15 минут считаем неизвестным состоянием


def _hm(iso):
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%H:%M")
    except Exception:
        return "?"


def _default_threshold():
    try:
        return float(json.load(open(CONFIG)).get("threshold") or 90)
    except Exception:
        return 90.0


def main():
    ceil = float(sys.argv[1]) if len(sys.argv) > 1 else _default_threshold()
    try:
        d = json.load(open(SNAP))
    except Exception as e:
        print("snapshot недоступен (%s) — гейт пропускает" % e)
        return 0

    accs = d.get("accounts") or {}
    age = time.time() - float(d.get("ts") or 0)
    if not accs or age > MAX_AGE:
        print("snapshot протух (%.0f с) — гейт пропускает" % age)
        return 0

    pcts = {}
    for name, row in accs.items():
        fh = row.get("five_hour") or {}
        pct = fh.get("pct")
        # неизвестный процент = считаем аккаунт живым, блокировать не на чем
        pcts[name] = (float(pct if pct is not None else 0.0), fh.get("resets_at") or "")

    line = ", ".join("%s %.0f%%" % (n, p) for n, (p, _) in sorted(pcts.items()))

    # Порог смотрим и на АКТИВНОМ аккаунте, а не только «на всех сразу»: пауза здесь
    # короткая — балансер уходит с аккаунта на том же пороге, после переключения
    # активным станет свежий и гейт откроется сам на следующем тике.
    active = d.get("active") or ""
    ap = pcts.get(active, (0.0, ""))[0]
    if active in pcts and ap > ceil:
        print("активный %s %.0f%% выше %.0f%% (%s) — жду переключения балансера"
              % (active, ap, ceil, line))
        return 10

    if [n for n, (p, _) in pcts.items() if p <= ceil]:
        print("ок (%s)" % line)
        return 0

    best = None
    for name, (_p, iso) in pcts.items():
        if not iso:
            continue
        try:
            ts = datetime.fromisoformat(iso).timestamp()
        except Exception:
            continue
        if best is None or ts < best[0]:
            best = (ts, name, iso)
    nearest = ("%s в %s" % (best[1], _hm(best[2]))) if best else "неизвестно"
    print("все аккаунты выше %.0f%% (%s), ближайшее окно: %s" % (ceil, line, nearest))
    return 10


if __name__ == "__main__":
    sys.exit(main())
