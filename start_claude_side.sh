#!/bin/bash
# Побочная сессия Claude на dev (вкладка консоли «Claude DEV», пока основной Claude остановлен: работа на PROD или режим Notion AI).
# От /root/start_claude.sh отличается тремя вещами:
#   1) НЕТ --channels plugin:telegram: бот остаётся у ведущего;
#   2) плагин Telegram отключён для этого запуска (--settings), иначе его процесс всё равно опрашивал бы бота;
#   3) только чтение: Bash/Edit/Write/NotebookEdit запрещены, основную работу и файлы дела побочная сессия не меняет.
# Запускает её панель (ConsoleInput), не человек. Гасит панель: nai.stop_claude() перед любым основным запуском или передачей.
cd /root
SIDE_FLAG=/opt/cc-limits/side_claude.json
# основной Claude или чужая побочная уже в этом screen — второго не создаём
if screen -ls 2>/dev/null | grep -q '\.darqai[[:space:]]'; then
  echo "screen darqai уже занят — побочную не запускаю"; exit 2
fi
if pgrep -f 'claude-plugins-official/telegram' >/dev/null 2>&1; then
  echo "плагин Telegram уже работает (бот у кого-то в руках) — побочную не запускаю"; exit 3
fi
export PATH=/root/.bun/bin:/root/.npm-global/bin:/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export HOME=/root USER=root SHELL=/bin/bash LANG=en_US.UTF-8
python3 /root/scripts/claude_trust_fix.py
python3 - <<'PY'
import json, time
json.dump({"started": time.time(), "note": "побочная сессия Claude без Telegram; гасить перед основным запуском"}, open("/opt/cc-limits/side_claude.json", "w"))
PY
screen -U -S darqai -dm bash -c "IS_SANDBOX=1 CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1 claude --dangerously-skip-permissions --settings '{\"enabledPlugins\":{\"telegram@claude-plugins-official\":false}}' --disallowedTools Bash Edit Write NotebookEdit; rm -f $SIDE_FLAG"
echo "Побочный Claude запущен в screen darqai (без Telegram, только чтение)"
