#!/usr/bin/env python3
# Гейт лимитов — «можно ли сейчас запускать фоновый (headless) прогон Claude».
#
# Зачем: фоновые задачи (cron, вотчеры, автоответчики) идут по ТОМУ ЖЕ активному
# аккаунту, что и живая интерактивная сессия. Если окно уже почти выбрано, такой
# прогон просто добивает остаток и падает на 429 — а окно нужно человеку.
#
# rc=10 — работать нельзя: либо активный аккаунт не пригоден (ждём, пока балансер
#         уйдёт на свежий), либо не пригоден НИ ОДИН (переключаться некуда).
#         Не пригоден = сессия выше порога. Неделя не держит: она сбрасывается раз
#         в 7 дней, гейт стоял бы сутками (балансер всё равно уходит с аккаунта у потолка).
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc_avail  # noqa: E402

BASE = os.environ.get("CC_LIMITS_BASE", os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(BASE, "snapshot.json")
CONFIG = os.path.join(BASE, "config.json")
MAX_AGE = 900  # снапшот старше 15 минут считаем неизвестным состоянием


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

    # Неделя гейт не держит (v1.15.1): пауза фоновых прогонов — только по сессии, как и
    # пауза живой сессии; с аккаунта у потолка недели уходит балансер
    cap = float("inf")
    pcts, usable = {}, {}
    for name, row in accs.items():
        fh = row.get("five_hour") or {}
        pct = fh.get("pct")
        # неизвестный процент = считаем аккаунт живым, блокировать не на чем
        pcts[name] = float(pct if pct is not None else 0.0)
        # пригоден = сессия ниже порога (неделю не смотрим, см. выше)
        usable[name] = cc_avail.availability(row, ceil, cap)[0]

    line = ", ".join("%s %.0f%%/нед %s%%" % (n, p, (accs[n].get("seven_day") or {}).get("pct"))
                     for n, p in sorted(pcts.items()))

    # Порог смотрим и на АКТИВНОМ аккаунте, а не только «на всех сразу»: пауза здесь
    # короткая — балансер уходит с аккаунта на том же пороге, после переключения
    # активным станет свежий и гейт откроется сам на следующем тике.
    active = d.get("active") or ""
    if active in usable and not usable[active]:
        print("активный %s не пригоден (%s) — жду переключения балансера" % (active, line))
        return 10

    if any(usable.values()):
        print("ок (%s)" % line)
        return 0

    nb = cc_avail.nearest(accs, ceil, cap)
    nearest = ("%s в %s" % (nb[1], datetime.fromtimestamp(nb[0]).astimezone().strftime("%H:%M"))) if nb else "неизвестно"
    print("все аккаунты упёрлись в сессию (%s), раньше всех освободится: %s" % (line, nearest))
    return 10


if __name__ == "__main__":
    sys.exit(main())
