#!/bin/bash
# ccfleet · Notion AI — третий агент рядом с Claude и Codex. Ставит сервисы на ЭТОТ сервер.
#   sudo bash notion_ai/install.sh
# Что ставится:
#   /root/notion_web/        — notion-delegate (отправка в чат Notion AI, вход по коду из письма),
#                              notion-ai-view (окно «Notion AI» в консоли), notion-ai-tg (мост Telegram)
#   /usr/local/bin/          — notion-ai-reply, notion-ai-mode, notion-ai-step, notion-delegate
#   $BASE/cc_notion_ai.py    — профили Notion AI, вкладка консоли, ⚙ Общие настройки → Notion AI
#   $BASE/notion_ai.json     — настройки (заполняются в панели; существующие не трогаем)
# Повторный запуск безопасен: прежние файлы сохраняются рядом с суффиксом .bak_<время>,
# вход в Notion (state.json) и токен api_token не трогаются.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
W=${NAI_WEB:-/root/notion_web}
BASE=${CC_LIMITS_BASE:-/opt/cc-limits}
BIN=${NAI_BIN:-/usr/local/bin}
UNITS=${NAI_UNITS:-/etc/systemd/system}
TOKEN_COPY=${NAI_TOKEN_COPY:-/root/.notion_delegate_token}
TS=$(date +%Y%m%d_%H%M%S)
log(){ echo "[notion-ai] $*"; }
die(){ echo "[notion-ai] ОШИБКА: $*" >&2; exit 1; }
keep(){ [ -f "$1" ] && cp -p "$1" "$1.bak_$TS" || true; }

[ "${NAI_TEST:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "запусти от root (sudo)"
command -v python3 >/dev/null || die "нет python3"
[ -d "$BASE" ] || die "нет $BASE — сначала поставь сам балансер (install.sh в корне репозитория)"

if [ "${NAI_SKIP_DEPS:-0}" != 1 ] && ! python3 -c "import playwright" 2>/dev/null; then
  log "Ставлю Playwright и Chromium (браузер для чата Notion)…"
  if ! python3 -m pip --version >/dev/null 2>&1; then  # на чистой Ubuntu pip не стоит
    command -v apt-get >/dev/null || die "нет pip и нет apt-get: поставь python3-pip вручную и запусти снова"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-pip >/dev/null || die "не поставился python3-pip (apt-get install -y python3-pip)"
  fi
  python3 -m pip install -q playwright 2>/dev/null || python3 -m pip install -q --break-system-packages playwright || die "не поставился Playwright (python3 -m pip install playwright)"
  python3 -m playwright install --with-deps chromium || die "не скачался Chromium для Playwright: проверь сеть и место на диске"
fi

log "Файлы сервисов → $W"
mkdir -p "$W"; chmod 700 "$W"
for f in "$HERE"/web/*.py; do n=$(basename "$f"); keep "$W/$n"; install -m 700 "$f" "$W/$n"; done
if [ ! -s "$W/api_token" ]; then
  python3 -c "import secrets; print(secrets.token_hex(16))" > "$W/api_token"; chmod 600 "$W/api_token"; log "создан api_token"
fi
[ -s "$TOKEN_COPY" ] || install -m 600 "$W/api_token" "$TOKEN_COPY"

log "Команды → $BIN"
mkdir -p "$BIN"
for b in "$HERE"/bin/*; do install -m 755 "$b" "$BIN/$(basename "$b")"; done

log "Модуль панели → $BASE/cc_notion_ai.py"
if [ "$HERE/../cc_notion_ai.py" -ef "$BASE/cc_notion_ai.py" ]; then log "(модуль панели уже на месте)"
else keep "$BASE/cc_notion_ai.py"; install -m 644 "$HERE/../cc_notion_ai.py" "$BASE/cc_notion_ai.py"; fi
if [ ! -f "$BASE/notion_ai.json" ]; then
  NAI_CFG="$BASE/notion_ai.json" python3 - <<'PY'
import json, os
d = {"chat_url": "", "owner": "", "notion_email": "", "tg_chat_id": "", "voice": False, "console_tab": True}   # голос включает voice/install.sh, когда он поставлен
fd = os.open(os.environ["NAI_CFG"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, json.dumps(d, ensure_ascii=False, indent=1).encode()); os.close(fd)
PY
  log "созданы пустые настройки $BASE/notion_ai.json"
fi
mkdir -p /root/notion_ai_inbox 2>/dev/null || true

log "Сервисы systemd → $UNITS"
mkdir -p "$UNITS"
for u in "$HERE"/systemd/*.service; do install -m 644 "$u" "$UNITS/$(basename "$u")"; done
if [ "${NAI_NO_SYSTEMCTL:-0}" != 1 ]; then
  systemctl daemon-reload
  systemctl enable notion-delegate.service notion-ai-view.service >/dev/null
  systemctl restart notion-delegate.service notion-ai-view.service
  # мост Telegram сам не включаем: его запускает профиль «Notion AI · только он» (на это время Claude остановлен)
  systemctl is-active -q cc-limits && systemctl restart cc-limits || true
fi
log "Готово. Дальше — в панели: ⚙ Общие настройки → Notion AI → «Как подключить с нуля»."
log "  1) ссылка на постоянный чат Notion AI  2) почта входа → «Войти» → код из письма"
log "  3) SSH-ключ Notion AI  4) «Инструкция для Notion AI» → в чат  5) «Проверить связь»"
