#!/usr/bin/env bash
# cc-fleet v1.8.0 — self-host ротация нескольких Pro/Max аккаунтов Claude Code:
# мониторинг лимитов (5ч/неделя), авто-переключение по порогу, веб-панель
# (карточки аккаунтов + переключение), read-only зеркало консоли живой
# screen-сессии Claude Code, гейт лимитов для фоновых задач и пауза с
# будильником (снимается системным cron на ближайшем сбросе окна).
#
# Ставится на СВОЙ VDS от root. Каждый пользователь — отдельная изолированная
# инсталляция на своём сервере: чужие OAuth-токены нигде не хранятся и никуда
# не отправляются.
#
# Запуск (интерактивно):   sudo ./install.sh
# Запуск (без вопросов, значения по умолчанию/из переменных окружения):
#                           CC_FLEET_YES=1 sudo -E ./install.sh
set -euo pipefail

# ---------- параметры (можно переопределить переменными окружения) ----------
BASE="${CC_FLEET_BASE:-/opt/cc-limits}"
PROFILES_DIR="${CC_FLEET_PROFILES:-/root/.claude-profiles}"
SERVICE_NAME="${CC_FLEET_SERVICE_NAME:-cc-limits}"
PORT="${CC_FLEET_PORT:-8877}"
SCREEN_SESSION="${CC_FLEET_SCREEN:-claude}"
N_ACCOUNTS="${CC_FLEET_ACCOUNTS:-2}"
THRESHOLD="${CC_FLEET_THRESHOLD:-85}"
NONINTERACTIVE="${CC_FLEET_YES:-0}"
DOMAIN="${CC_FLEET_DOMAIN:-}"
BASIC_USER="${CC_FLEET_BASIC_USER:-}"
BASIC_PASS="${CC_FLEET_BASIC_PASS:-}"
CHAT_ID="${CC_FLEET_CHAT_ID:-}"
BOT_TOKEN="${CC_FLEET_BOT_TOKEN:-}"
WANT_NGINX="${CC_FLEET_NGINX:-}"
WANT_TG="${CC_FLEET_TG:-}"
TG_ENV_FILE="/root/.claude/channels/telegram/.env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { echo -e "\033[1;36m==>\033[0m $*"; }
warn() { echo -e "\033[1;33m!!\033[0m $*"; }
die()  { echo -e "\033[1;31mERROR:\033[0m $*" >&2; exit 1; }

ask() {
  # ask <var_name> <prompt> <default>
  local __var="$1" __prompt="$2" __default="$3" __ans
  if [ "$NONINTERACTIVE" = "1" ]; then printf -v "$__var" '%s' "${!__var:-$__default}"; return; fi
  read -r -p "$__prompt [$__default]: " __ans || true
  printf -v "$__var" '%s' "${__ans:-$__default}"
}

ask_yn() {
  # ask_yn <var_name> <prompt> <default y|n>
  local __var="$1" __prompt="$2" __default="$3" __ans
  if [ "$NONINTERACTIVE" = "1" ]; then printf -v "$__var" '%s' "${!__var:-$__default}"; return; fi
  read -r -p "$__prompt [y/n, по умолчанию $__default]: " __ans || true
  __ans="${__ans:-$__default}"
  printf -v "$__var" '%s' "$__ans"
}

[ "$(id -u)" = "0" ] || die "Запускай от root (sudo ./install.sh)."
[ -f "$SCRIPT_DIR/cc_limits.py" ] || die "cc_limits.py не найден рядом со скриптом ($SCRIPT_DIR)."

log "cc-fleet v1.8.0 — установка ротации Claude-аккаунтов"
echo "Ставим на этот сервер как systemd-сервис + (опционально) nginx-панель."
echo

# ---------- вопросы ----------
# BASE и PROFILES_DIR — фиксированные конвенции (совпадают с путями, которые
# ждёт cc-switch), их можно переопределить только переменными окружения
# CC_FLEET_BASE/CC_FLEET_PROFILES перед запуском — это не обычный пользовательский
# сценарий, поэтому вопросом не задаём, чтобы не плодить рассинхрон с cc-switch.
log "Ставлю в $BASE, профили аккаунтов — в $PROFILES_DIR (стандартные пути, см. README для смены)"
ask SCREEN_SESSION "Имя screen-сессии, в которой живёт Claude Code" "$SCREEN_SESSION"
ask N_ACCOUNTS "Сколько аккаунтов заведём (пустые слоты под онбординг)" "$N_ACCOUNTS"
ask THRESHOLD "Порог авто-переключения, % занятости 5-часовой сессии" "$THRESHOLD"

ask_yn WANT_NGINX "Настроить nginx-панель на домене с Basic Auth (иначе — только 127.0.0.1:$PORT, прокси сам)" "y"
if [ "$WANT_NGINX" = "y" ] || [ "$WANT_NGINX" = "Y" ]; then
  ask DOMAIN "Домен (A-запись уже должна указывать на этот сервер)" "$DOMAIN"
  ask BASIC_USER "Логин Basic Auth для веб-панели" "${BASIC_USER:-admin}"
  if [ "$NONINTERACTIVE" != "1" ]; then
    read -r -s -p "Пароль Basic Auth: " BASIC_PASS; echo
  fi
  [ -n "$DOMAIN" ] || die "Домен обязателен для настройки nginx."
  [ -n "$BASIC_PASS" ] || die "Пароль Basic Auth обязателен."
fi

ask_yn WANT_TG "Включить уведомления в Telegram (переключение аккаунтов, пауза по лимитам)" "n"
if [ "$WANT_TG" = "y" ] || [ "$WANT_TG" = "Y" ]; then
  ask CHAT_ID "Telegram chat_id получателя" "$CHAT_ID"
  if grep -qs "TELEGRAM_BOT_TOKEN=" "$TG_ENV_FILE"; then
    log "Токен бота найден в $TG_ENV_FILE — беру оттуда."
  else
    warn "Файла телеграм-канала Claude Code ($TG_ENV_FILE) нет или в нём нет токена."
    warn "Укажи токен бота (@BotFather) здесь — он ляжет в config.json (chmod 600)."
    warn "Пусто — уведомления просто не будут уходить, сервис от этого не сломается."
    ask BOT_TOKEN "Токен Telegram-бота" "$BOT_TOKEN"
  fi
fi

echo
log "План: BASE=$BASE, PROFILES=$PROFILES_DIR, screen=$SCREEN_SESSION, аккаунтов=$N_ACCOUNTS, порт=$PORT"
[ "$WANT_NGINX" = "y" ] && log "nginx: https://$DOMAIN/cc/ (Basic Auth $BASIC_USER)"
[ "$WANT_TG" = "y" ] && log "Telegram: chat_id=$CHAT_ID"
if [ "$NONINTERACTIVE" != "1" ]; then
  read -r -p "Продолжить? [y/N]: " CONFIRM
  [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ] || die "Отменено."
fi

# ---------- зависимости ----------
log "Ставлю системные зависимости (apt)…"
apt-get update -qq
APT_PKGS="python3 python3-pyte python3-pexpect screen"
[ "$WANT_NGINX" = "y" ] && APT_PKGS="$APT_PKGS nginx apache2-utils"
apt-get install -y -qq $APT_PKGS

command -v claude >/dev/null 2>&1 || warn "Бинарник 'claude' не найден в PATH — веб-кнопка 'Войти заново' работать не будет, пока не поставишь Claude Code (npm i -g @anthropic-ai/claude-code)."

# ---------- сервис ----------
log "Копирую cc_limits.py → $BASE"
mkdir -p "$BASE"
cp "$SCRIPT_DIR/cc_limits.py" "$BASE/cc_limits.py"
chmod 644 "$BASE/cc_limits.py"

log "Копирую limits_gate.py и pause_ctl.py → $BASE (гейт фоновых задач + пауза с будильником)"
cp "$SCRIPT_DIR/limits_gate.py" "$BASE/limits_gate.py"
cp "$SCRIPT_DIR/pause_ctl.py" "$BASE/pause_ctl.py"
chmod 755 "$BASE/limits_gate.py" "$BASE/pause_ctl.py"

log "Копирую tg_queue.py и hooks/ → $BASE (очередь входящих на время лимитов)"
cp "$SCRIPT_DIR/tg_queue.py" "$BASE/tg_queue.py"
mkdir -p "$BASE/hooks"
cp "$SCRIPT_DIR/hooks/queue_on_limits.py" "$BASE/hooks/queue_on_limits.py"
chmod 755 "$BASE/tg_queue.py" "$BASE/hooks/queue_on_limits.py"

log "Ставлю cc-switch → /usr/local/bin/cc-switch"
cp "$SCRIPT_DIR/cc-switch" /usr/local/bin/cc-switch
chmod 755 /usr/local/bin/cc-switch

log "Завожу $N_ACCOUNTS пустых профиля в $PROFILES_DIR (под онбординг через веб-кнопку 'Войти заново')"
mkdir -p "$PROFILES_DIR"
for i in $(seq 1 "$N_ACCOUNTS"); do
  d="$PROFILES_DIR/acc$i"
  mkdir -p "$d"
  [ -f "$d/oauth_account.json" ] || echo '{}' > "$d/oauth_account.json"
done

# При повторном запуске (обновление версии) config.json НЕ обнуляем: старый
# hook_token и уже настроенные ключи сохраняются, ответы этого запуска ложатся сверху.
EXIST_TOKEN=""
if [ -f "$BASE/config.json" ]; then
  EXIST_TOKEN="$(python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("hook_token",""))
except Exception: print("")' "$BASE/config.json" 2>/dev/null || true)"
fi
if [ -n "$EXIST_TOKEN" ]; then
  HOOK_TOKEN="$EXIST_TOKEN"
  log "config.json уже есть — обновляю его, hook_token оставляю прежним"
else
  HOOK_TOKEN="$(openssl rand -hex 24)"
  log "Генерирую config.json (hook_token сгенерирован случайно, храни в секрете)"
fi
python3 - "$BASE/config.json" "$HOOK_TOKEN" "$THRESHOLD" "$SCREEN_SESSION" "$CHAT_ID" "$PORT" "$BOT_TOKEN" <<'PYEOF'
import json, os, sys
path, token, threshold, screen, chat_id, port, bot_token = sys.argv[1:8]
cfg = {
    "hook_token": token,
    "autoswitch": True,
    "threshold": int(threshold),
    "poll_sec": 120,
    "switch_cooldown_sec": 300,
    "optimize": False,
    "screen_session": screen,
    "port": int(port),
}
if os.path.exists(path):
    try:
        old = json.load(open(path))
        if isinstance(old, dict):
            old.update(cfg)   # свои ключи пользователя переживают обновление
            cfg = old
    except Exception:
        pass
if chat_id:
    cfg["chat_id"] = chat_id
if bot_token:
    cfg["bot_token"] = bot_token  # запасной путь, если файла телеграм-канала нет
with open(path, "w") as f:
    json.dump(cfg, f, indent=1, ensure_ascii=False)
PYEOF
chmod 600 "$BASE/config.json"

log "Ставлю systemd unit $SERVICE_NAME.service"
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<UNIT
[Unit]
Description=Claude accounts limits monitor + autoswitch (cc-fleet)
After=network-online.target

[Service]
Environment=CC_LIMITS_BASE=$BASE
Environment=CC_LIMITS_PROFILES=$PROFILES_DIR
ExecStart=/usr/bin/python3 $BASE/cc_limits.py
Restart=always
RestartSec=5
WorkingDirectory=$BASE

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
sleep 1

# Будильник паузы: тик раз в минуту. Живёт в системном cron, а не внутри сессии
# Claude Code — иначе умрёт вместе с ней (/clear, перезапуск, ребут).
CRON_FILE="/etc/cron.d/$SERVICE_NAME-pause"
log "Ставлю cron-будильник паузы ($CRON_FILE)"
cat > "$CRON_FILE" <<CRON
# cc-fleet: снятие паузы по лимитам, когда сессионное окно отпустило
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
* * * * * root CC_LIMITS_BASE=$BASE /usr/bin/python3 $BASE/pause_ctl.py wake --if-due >> $BASE/pause_wake.log 2>&1
CRON
chmod 644 "$CRON_FILE"

# Очередь входящих: хук UserPromptSubmit блокирует сообщение из чат-канала, пока все
# окна сожжены. Правим чужой settings.json только с явного согласия — по умолчанию да,
# без него очередь не работает вообще (сообщения продолжат будить сессию).
ask_yn HOOK_QUEUE "Подключить хук очереди входящих (UserPromptSubmit) в settings.json Claude Code?" y
if [ "$HOOK_QUEUE" = "y" ]; then
  ask CLAUDE_SETTINGS "Путь к settings.json Claude Code" "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
  mkdir -p "$(dirname "$CLAUDE_SETTINGS")"
  [ -f "$CLAUDE_SETTINGS" ] || echo '{}' > "$CLAUDE_SETTINGS"
  cp "$CLAUDE_SETTINGS" "$CLAUDE_SETTINGS.bak_$(date +%Y%m%d%H%M%S)"
  CC_SETTINGS="$CLAUDE_SETTINGS" CC_HOOK_CMD="CC_LIMITS_DIR=$BASE /usr/bin/python3 $BASE/hooks/queue_on_limits.py" python3 <<'PY'
import json, os
p = os.environ["CC_SETTINGS"]
cmd = os.environ["CC_HOOK_CMD"]
try:
    d = json.load(open(p))
    if not isinstance(d, dict):
        d = {}
except Exception:
    d = {}
ups = d.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
# идемпотентность: ищем наш скрипт, а не точную строку — путь мог поменяться
if any("queue_on_limits.py" in json.dumps(x) for x in ups):
    ups[:] = [x for x in ups if "queue_on_limits.py" not in json.dumps(x)]
ups.append({"hooks": [{"type": "command", "command": cmd}]})
json.dump(d, open(p, "w"), ensure_ascii=False, indent=2)
print("  OK: хук очереди прописан в %s" % p)
PY
  warn "Claude Code читает settings.json при старте — перезапусти сессию, чтобы хук заработал."
else
  log "Хук очереди не подключён. Вручную: hooks.UserPromptSubmit → команда"
  echo "  CC_LIMITS_DIR=$BASE /usr/bin/python3 $BASE/hooks/queue_on_limits.py"
fi

log "Проверяю health-check (127.0.0.1:$PORT)…"
HC="$(curl -fsS "http://127.0.0.1:$PORT/api/limits?token=$HOOK_TOKEN" || true)"
if echo "$HC" | grep -q '"accounts"'; then
  echo "  OK: сервис отвечает, аккаунтов в снапшоте: $(echo "$HC" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("accounts",{})))')"
else
  die "Сервис не ответил на 127.0.0.1:$PORT — смотри journalctl -u $SERVICE_NAME -n 50"
fi

PC="$(curl -fsS "http://127.0.0.1:$PORT/api/pause?token=$HOOK_TOKEN" || true)"
if echo "$PC" | grep -q '"ok": *true'; then
  echo "  OK: баннер лимитов/паузы подключён (/api/pause)"
else
  warn "/api/pause не ответил ok — баннер паузы работать не будет: $PC"
fi

# ---------- nginx (опционально) ----------
if [ "$WANT_NGINX" = "y" ] || [ "$WANT_NGINX" = "Y" ]; then
  HTPASSWD_FILE="/etc/nginx/.htpasswd_$SERVICE_NAME"
  log "Пишу Basic Auth в $HTPASSWD_FILE"
  htpasswd -bc "$HTPASSWD_FILE" "$BASIC_USER" "$BASIC_PASS" >/dev/null

  VHOST="/etc/nginx/sites-available/$DOMAIN"
  log "Пишу nginx vhost $VHOST"
  cat > "$VHOST" <<NGINX
server {
    listen 80;
    server_name $DOMAIN;

    location /cc/ {
        auth_basic "Restricted";
        auth_basic_user_file $HTPASSWD_FILE;
        proxy_pass http://127.0.0.1:$PORT/;
        proxy_set_header X-Auth-User \$remote_user;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }

    # без Basic Auth: браузер может не переслать её в fetch() —
    # страница сама ходит сюда с вшитым hook_token в query
    location /cc-hook/ {
        proxy_pass http://127.0.0.1:$PORT/api/;
        proxy_set_header X-Auth-User "";
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
NGINX
  ln -sf "$VHOST" "/etc/nginx/sites-enabled/$DOMAIN"
  nginx -t
  systemctl reload nginx
  echo
  log "Готово. Панель: http://$DOMAIN/cc/  (после certbot — https)"
  warn "HTTPS не настроен автоматически. Дальше: certbot --nginx -d $DOMAIN"
else
  echo
  log "nginx не настраивал. Сервис слушает 127.0.0.1:$PORT (только localhost)."
  echo "  Подключи свой reverse-proxy: главная страница отдаётся с заголовком X-Auth-User"
  echo "  (Basic Auth от прокси), API — с ?token=$HOOK_TOKEN (см. README.md)."
fi

echo
log "Установка завершена."
echo "hook_token: $HOOK_TOKEN"
echo "Дальше — онбординг аккаунтов, см. README.md."
