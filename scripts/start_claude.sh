#!/bin/bash
# Запускает Claude Code в screen-сессии (с каналом Telegram, если плагин настроен).
# Вызывается панелью (кнопки «Запустить», возврат работы, смена профиля) и вручную. Настройки — в /opt/cc-limits/config.json:
#   screen_session — имя screen-сессии (по умолчанию claude), work_dir — рабочая папка Claude (по умолчанию домашняя).
BASE="${CC_LIMITS_BASE:-/opt/cc-limits}"
cfg() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2]) or sys.argv[3])' "$BASE/config.json" "$1" "$2" 2>/dev/null || echo "$2"; }
SCREEN="$(cfg screen_session claude)"
WORK="$(cfg work_dir "$HOME")"
cd "$WORK" || exit 1
# работа передана на второй сервер (кнопка в панели) — бота слушает Claude там, здесь Claude не стартует
if python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("active") else 1)' "$BASE/remote_mode.json" 2>/dev/null; then
  echo "Работа на втором сервере — Claude здесь не запускаю (верни её кнопкой «Вернуть» в панели)"; exit 0
fi
# из @reboot cron PATH=/usr/bin:/bin — без этого claude и bun (плагин Telegram) не находятся
export HOME="${HOME:-/root}" SHELL=/bin/bash LANG=en_US.UTF-8
export PATH="$HOME/.bun/bin:$HOME/.npm-global/bin:$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# диалог «доверяешь папке» по умолчанию стоит на «No, exit» (Enter = выход) — доверие ставим до старта
python3 "$BASE/claude_trust_fix.py" "$WORK"
CHANNELS=""
[ -f "$HOME/.claude/channels/telegram/.env" ] && CHANNELS="--channels plugin:telegram@claude-plugins-official"
# IS_SANDBOX=1 обходит запрет на запуск под root для --dangerously-skip-permissions
screen -U -S "$SCREEN" -dm bash -c "IS_SANDBOX=1 CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1 claude --dangerously-skip-permissions $CHANNELS; exec bash"
echo "Claude Code запущен в screen-сессии $SCREEN"
