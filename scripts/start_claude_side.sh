#!/bin/bash
# Побочная сессия Claude на основном сервере (вкладка консоли, пока основной Claude остановлен: работа на втором сервере).
# От start_claude.sh отличается тремя вещами:
#   1) НЕТ --channels plugin:telegram: бот остаётся у ведущего;
#   2) плагин Telegram отключён для этого запуска (--settings), иначе его процесс всё равно опрашивал бы бота;
#   3) только чтение: Bash/Edit/Write/NotebookEdit запрещены, основную работу и файлы дела побочная сессия не меняет.
# Запускает её панель (ConsoleInput), не человек. Гасит панель: stop_claude() (cc_workers) перед любым основным запуском или передачей.
BASE="${CC_LIMITS_BASE:-/opt/cc-limits}"
cfg() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2]) or sys.argv[3])' "$BASE/config.json" "$1" "$2" 2>/dev/null || echo "$2"; }
SCREEN="$(cfg screen_session claude)"
WORK="$(cfg work_dir "$HOME")"
cd "$WORK" || exit 1
SIDE_FLAG="$BASE/side_claude.json"
# основной Claude или чужая побочная уже в этом screen — второго не создаём
if screen -ls 2>/dev/null | grep -q "\.$SCREEN[[:space:]]"; then
  echo "screen $SCREEN уже занят — побочную не запускаю"; exit 2
fi
if pgrep -f 'claude-plugins-official/telegram' >/dev/null 2>&1; then
  echo "плагин Telegram уже работает (бот у кого-то в руках) — побочную не запускаю"; exit 3
fi
export HOME="${HOME:-/root}" SHELL=/bin/bash LANG=en_US.UTF-8
export PATH="$HOME/.bun/bin:$HOME/.npm-global/bin:$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
python3 "$BASE/claude_trust_fix.py" "$WORK"
python3 - "$SIDE_FLAG" <<'PY'
import json, sys, time
json.dump({"started": time.time(), "note": "побочная сессия Claude без Telegram; гасить перед основным запуском"}, open(sys.argv[1], "w"))
PY
screen -U -S "$SCREEN" -dm bash -c "IS_SANDBOX=1 CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1 claude --dangerously-skip-permissions --settings '{\"enabledPlugins\":{\"telegram@claude-plugins-official\":false}}' --disallowedTools Bash Edit Write NotebookEdit; rm -f $SIDE_FLAG"
echo "Побочный Claude запущен в screen $SCREEN (без Telegram, только чтение)"
