#!/usr/bin/env bash
# cc-fleet — установка «под ключ»: панель для нескольких подписок Claude Code, Codex и Notion AI на ВАШЕМ сервере.
#
#   sudo ./install.sh            установка (или продолжение прерванной / обновление)
#   sudo ./install.sh --check    только проверить, какие шаги уже выполнены (ничего не меняет)
#   CC_FLEET_YES=1 sudo -E ./install.sh   без вопросов: значения по умолчанию и из переменных CC_FLEET_*
#
# Установка идёт по шагам «Шаг N из M». После каждого шага установщик проверяет результат и пишет ✅ или ❌ с подсказкой.
# Перед каждым следующим шагом он заново проверяет предыдущие. Если что-то не вышло — исправь по подсказке и запусти его снова:
# он повторит безопасные шаги и продолжит. Подробная инструкция: docs/INSTALL.md.
#
# Ставится на СВОЙ сервер от root. Каждая установка изолирована: чужие OAuth-токены нигде не хранятся и никуда не отправляются.
set -uo pipefail

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
WANT_HTTPS="${CC_FLEET_HTTPS:-}"
CERT_EMAIL="${CC_FLEET_CERT_EMAIL:-}"
WANT_TG="${CC_FLEET_TG:-}"
WANT_CODEX="${CC_FLEET_CODEX:-}"
WANT_CLAUDE="${CC_FLEET_CLAUDE:-}"
CODEX_USER="${CC_FLEET_CODEX_USER:-codex}"
WANT_NOTION="${CC_FLEET_NOTION:-}"
WANT_VOICE="${CC_FLEET_VOICE:-}"
OWNER_NAME="${CC_FLEET_OWNER:-}"
TZ_NAME="${CC_FLEET_TZ:-}"
WORK_DIR="${CC_FLEET_WORKDIR:-}"
HOOK_QUEUE="${CC_FLEET_HOOK_QUEUE:-}"
HOOK_TOOLS="${CC_FLEET_HOOK_TOOLS:-}"
TG_ENV_FILE="${CC_FLEET_TG_ENV:-/root/.claude/channels/telegram/.env}"
CLAUDE_SETTINGS="${CC_FLEET_CLAUDE_SETTINGS:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1
[ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] && { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
VERSION="$(sed -n 's/^VERSION = "\([^"]*\)".*/\1/p' "$SCRIPT_DIR/cc_limits.py" 2>/dev/null | head -1)"
STATE_FILE="$BASE/install_answers.env"   # ответы прошлого запуска (без паролей): при повторе не спрашиваем заново

# ---------- оформление ----------
C0=$'\033[0m'; CB=$'\033[1m'; CG=$'\033[1;32m'; CR=$'\033[1;31m'; CY=$'\033[1;33m'; CC=$'\033[1;36m'
log()  { echo -e "${CC}==>${C0} $*"; }
warn() { echo -e "${CY}!!${C0} $*"; }
okm()  { echo -e "   ${CG}✅${C0} $*"; }
skip() { echo -e "   ⏭  $*"; }
info() { echo -e "   $*"; }
fail() {
  # fail "что не так" "что делать"
  echo -e "   ${CR}❌ $1${C0}" >&2
  [ -n "${2:-}" ] && echo -e "   ${CY}Что делать:${C0} $2" >&2
  echo -e "   Исправь и запусти установщик снова: ${CB}sudo ./install.sh${C0} — он проверит сделанное и продолжит." >&2
  exit 1
}
scheme() { yes_ "$WANT_HTTPS" && echo https || echo http; }
yes_() { case "${1:-}" in y|Y|yes|д|Д|да) return 0 ;; *) return 1 ;; esac; }

ask() {
  # ask <var_name> <prompt> <default>
  local __var="$1" __prompt="$2" __default="$3" __ans
  if [ "$NONINTERACTIVE" = "1" ]; then printf -v "$__var" '%s' "${!__var:-$__default}"; return; fi
  if [ -n "${!__var:-}" ]; then __default="${!__var}"; fi
  read -r -p "   $__prompt [$__default]: " __ans || true
  printf -v "$__var" '%s' "${__ans:-$__default}"
}
ask_yn() {
  # ask_yn <var_name> <prompt> <default y|n>
  local __var="$1" __prompt="$2" __default="$3" __ans
  if [ "$NONINTERACTIVE" = "1" ]; then printf -v "$__var" '%s' "${!__var:-$__default}"; return; fi
  if [ -n "${!__var:-}" ]; then __default="${!__var}"; fi
  read -r -p "   $__prompt [y/n, по умолчанию $__default]: " __ans || true
  printf -v "$__var" '%s' "${__ans:-$__default}"
}

# ---------- шаги ----------
STEP_TITLES=(
  "Проверка сервера"
  "Параметры установки"
  "Системные пакеты"
  "Claude Code"
  "Файлы панели"
  "Настройки и профили аккаунтов"
  "Служба панели"
  "Будильник паузы и хуки Claude Code"
  "Адрес панели: домен, пароль, HTTPS"
  "Telegram"
  "Codex"
  "Notion AI"
  "Голос"
  "Итог"
)
TOTAL=${#STEP_TITLES[@]}
CURRENT=0
header() { CURRENT=$1; echo; echo -e "${CB}━━ Шаг $1 из $TOTAL — ${STEP_TITLES[$(($1-1))]} ━━${C0}"; }

VERBOSE=1   # 0 — молча (перепроверка пройденных шагов), 1 — с подробностями

json_get() { python3 -c 'import json,sys
try: v=json.load(open(sys.argv[1])).get(sys.argv[2],"")
except Exception: v=""
print(v if v is not None else "")' "$1" "$2" 2>/dev/null; }

node_major() { node -v 2>/dev/null | sed -n 's/^v\([0-9]*\).*/\1/p'; }
ensure_node() {
  # Node.js 18+ (нужен для Claude Code и Codex): сначала из apt, если версия старая — NodeSource 20
  [ "$(node_major || echo 0)" -ge 18 ] 2>/dev/null && command -v npm >/dev/null 2>&1 && return 0
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs npm >/dev/null 2>&1 || true
  [ "$(node_major || echo 0)" -ge 18 ] 2>/dev/null && command -v npm >/dev/null 2>&1 && return 0
  info "в apt Node.js старее 18 — ставлю Node.js 20 из репозитория NodeSource…"
  curl -fsSL https://deb.nodesource.com/setup_20.x 2>/dev/null | bash - >/dev/null 2>&1 || return 1
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs >/dev/null 2>&1 || return 1
  [ "$(node_major || echo 0)" -ge 18 ] 2>/dev/null && command -v npm >/dev/null 2>&1
}

module_list() {
  # все файлы пакета из update_manifest.json: "src dst mode"
  python3 - "$SCRIPT_DIR" <<'PY'
import json, os, sys
root = sys.argv[1]
m = json.load(open(os.path.join(root, "update_manifest.json")))
for f in m["files"]:
    print(f["src"], f.get("dst") or f["src"], f.get("mode") or "644")
PY
}

# ---------- Шаг 1 ----------
c1() {
  [ "$(id -u)" = "0" ] || return 1
  command -v apt-get >/dev/null && command -v python3 >/dev/null || return 1
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || return 1
  [ -f "$SCRIPT_DIR/cc_limits.py" ] && [ -f "$SCRIPT_DIR/update_manifest.json" ]
}
s1() {
  header 1
  [ "$(id -u)" = "0" ] || fail "нужны права root" "запусти: sudo ./install.sh"
  command -v apt-get >/dev/null || fail "нужен Debian/Ubuntu (команда apt-get не найдена)" "установщик рассчитан на Ubuntu 22.04+/Debian 12+; на другой системе ставь вручную по README"
  command -v python3 >/dev/null || { info "python3 не найден — поставлю на шаге 3"; }
  if command -v python3 >/dev/null; then
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || fail "Python старше 3.9" "обнови систему до Ubuntu 22.04+ / Debian 12+"
  fi
  [ -f "$SCRIPT_DIR/cc_limits.py" ] || fail "cc_limits.py не найден рядом со скриптом ($SCRIPT_DIR)" "запускай ./install.sh из распакованной папки релиза"
  [ -f "$SCRIPT_DIR/update_manifest.json" ] || fail "update_manifest.json не найден" "папка релиза неполная: скачай архив заново"
  local free_mb; free_mb=$(df -Pm / | awk 'NR==2{print $4}')
  [ "${free_mb:-0}" -ge 1000 ] || fail "на диске меньше 1 ГБ свободного места ($free_mb МБ)" "освободи место"
  okm "root, $(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-Linux}"), свободно ${free_mb} МБ"
  if curl -fsS -m 10 -o /dev/null https://api.github.com 2>/dev/null; then okm "есть выход в интернет (GitHub доступен)"; else
    warn "GitHub недоступен с этого сервера: автообновление из панели не заработает. Установка продолжится."
  fi
  if curl -s -m 10 -o /dev/null https://api.anthropic.com 2>/dev/null; then okm "api.anthropic.com отвечает"; else
    warn "api.anthropic.com не отвечает с этого сервера: проверь сеть/файрвол — без этого лимиты аккаунтов не читаются."
  fi
}

# ---------- Шаг 2 ----------
c2() { return 0; }
s2() {
  header 2
  [ -f "$STATE_FILE" ] && [ "$NONINTERACTIVE" != "1" ] && { info "Нашёл ответы прошлой установки — они подставлены по умолчанию (Enter = оставить)."; . "$STATE_FILE"; }
  info "Ставим в $BASE, профили аккаунтов — в $PROFILES_DIR (стандартные пути)."
  ask SCREEN_SESSION "Имя screen-сессии, в которой живёт Claude Code" "$SCREEN_SESSION"
  ask N_ACCOUNTS "Сколько аккаунтов Claude заведём (пустые слоты, войдёшь в них потом в панели)" "$N_ACCOUNTS"
  ask THRESHOLD "Порог авто-переключения, % занятости 5-часового окна" "$THRESHOLD"
  ask OWNER_NAME "Как к тебе обращаться (имя подставляется в записки агентам)" "${OWNER_NAME:-владелец}"
  [ -n "$TZ_NAME" ] || TZ_NAME="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  ask TZ_NAME "Твой часовой пояс (IANA, например Europe/Moscow) — по нему показываются время сброса и записки" "${TZ_NAME:-UTC}"
  ask WORK_DIR "Рабочая папка Claude Code (где он стартует)" "${WORK_DIR:-/root}"
  echo
  info "${CB}Доступ к панели${C0}"
  local nginx_default=y; [ "$NONINTERACTIVE" = "1" ] && [ -z "$DOMAIN" ] && nginx_default=n   # без вопросов и без домена nginx не настраиваем
  ask_yn WANT_NGINX "Открыть панель на своём домене с паролем (nginx)? Нет — панель только на 127.0.0.1:$PORT" "$nginx_default"
  if yes_ "$WANT_NGINX"; then
    ask DOMAIN "Домен (A-запись уже должна указывать на этот сервер)" "$DOMAIN"
    ask BASIC_USER "Логин для входа в панель" "${BASIC_USER:-admin}"
    if [ "$NONINTERACTIVE" != "1" ] && [ -z "$BASIC_PASS" ]; then read -r -s -p "   Пароль для входа в панель: " BASIC_PASS; echo; fi
    [ -n "$DOMAIN" ] || fail "домен обязателен для настройки nginx" "укажи домен или ответь «n» на вопрос про nginx"
    [ -n "$BASIC_PASS" ] || fail "пароль для панели обязателен" "задай пароль"
    if [[ "$DOMAIN" =~ ^[0-9.]+$ ]] || [[ "$DOMAIN" == *:* ]]; then
      info "Вместо домена указан IP-адрес: сертификат HTTPS (Let's Encrypt) для IP не выдаётся — панель будет по http (пароль идёт открытым текстом). Домен и HTTPS можно добавить позже."
      WANT_HTTPS=n
    else
      ask_yn WANT_HTTPS "Получить бесплатный сертификат HTTPS (Let's Encrypt) сразу?" "y"
    fi
    if yes_ "$WANT_HTTPS"; then ask CERT_EMAIL "Почта для уведомлений Let's Encrypt" "$CERT_EMAIL"; [ -n "$CERT_EMAIL" ] || fail "для сертификата нужна почта" "укажи почту или ответь «n»"; fi
  fi
  echo
  info "${CB}Подключения (каждое можно пропустить и подключить позже)${C0}"
  ask_yn WANT_TG "Telegram: бот для уведомлений о переключениях и (позже) чат с Claude/Codex" "n"
  if yes_ "$WANT_TG"; then
    if grep -qs "TELEGRAM_BOT_TOKEN=" "$TG_ENV_FILE"; then info "Токен бота найден в $TG_ENV_FILE — возьму оттуда."
    else
      info "Бота создаёт @BotFather (команда /newbot) — он выдаст токен вида 123456:ABC…"
      ask BOT_TOKEN "Токен Telegram-бота (пусто — подключишь позже)" "$BOT_TOKEN"
    fi
    ask CHAT_ID "Твой Telegram chat_id (пусто — определю сам: напишешь боту любое сообщение)" "$CHAT_ID"
  fi
  ask_yn WANT_CLAUDE "Claude Code: установить, если его нет (Node.js 18+ и npm install -g @anthropic-ai/claude-code)" "y"
  ask_yn WANT_CODEX "Codex (ChatGPT): подготовить отдельного пользователя ОС для него" "y"
  ask_yn WANT_NOTION "Notion AI: поставить службы (браузер Chromium ~300 МБ, нужен аккаунт Notion с Notion AI)" "n"
  ask_yn WANT_VOICE "Голос: озвучка ответов и расшифровка голосовых (нужно ~5 ГБ места и 2 ГБ памяти)" "n"
  ask_yn HOOK_QUEUE "Хук очереди входящих в settings.json Claude Code (рекомендуется)" "y"
  ask_yn HOOK_TOOLS "Стоп-кран инструментов на паузе в settings.json Claude Code (рекомендуется)" "y"
  [ -n "$CLAUDE_SETTINGS" ] || CLAUDE_SETTINGS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
  echo
  log "План:"
  info "панель: $BASE (порт $PORT), служба $SERVICE_NAME, аккаунтов: $N_ACCOUNTS, screen: $SCREEN_SESSION, пояс: $TZ_NAME"
  if yes_ "$WANT_NGINX"; then info "адрес: $(scheme)://$DOMAIN/cc/ (вход: $BASIC_USER)"; else info "адрес: только 127.0.0.1:$PORT (свой прокси или SSH-туннель)"; fi
  info "Telegram: $(yes_ "$WANT_TG" && echo да || echo нет) · Codex: $(yes_ "$WANT_CODEX" && echo да || echo нет) · Notion AI: $(yes_ "$WANT_NOTION" && echo да || echo нет) · голос: $(yes_ "$WANT_VOICE" && echo да || echo нет)"
  if [ "$NONINTERACTIVE" != "1" ]; then
    read -r -p "   Продолжить установку? [y/N]: " CONFIRM
    yes_ "$CONFIRM" || fail "отменено" "запусти установщик снова, когда будешь готов"
  fi
  mkdir -p "$BASE"
  { for v in WANT_CLAUDE SCREEN_SESSION N_ACCOUNTS THRESHOLD OWNER_NAME TZ_NAME WORK_DIR WANT_NGINX DOMAIN BASIC_USER WANT_HTTPS CERT_EMAIL WANT_TG CHAT_ID WANT_CODEX CODEX_USER WANT_NOTION WANT_VOICE HOOK_QUEUE HOOK_TOOLS CLAUDE_SETTINGS; do printf '%s=%q\n' "$v" "${!v}"; done; } > "$STATE_FILE"
  chmod 600 "$STATE_FILE"
  okm "ответы записаны ($STATE_FILE, без паролей)"
}

# ---------- Шаг 3 ----------
c3() { python3 -c 'import pyte, pexpect, dateutil' 2>/dev/null && command -v screen >/dev/null && command -v curl >/dev/null; }
s3() {
  header 3
  local pkgs="python3 python3-pyte python3-pexpect python3-dateutil screen curl openssl ca-certificates"
  yes_ "$WANT_NGINX" && pkgs="$pkgs nginx apache2-utils"
  yes_ "$WANT_HTTPS" && pkgs="$pkgs certbot python3-certbot-nginx"
  log "Ставлю пакеты: $pkgs"
  apt-get update -qq || warn "apt-get update завершился с ошибкой — пробую ставить дальше"
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $pkgs >/dev/null || fail "не удалось поставить пакеты через apt" "посмотри ошибку выше: чаще всего занят dpkg (подожди минуту) или нет сети"
  c3 || fail "после установки не импортируются pyte/pexpect/dateutil или нет screen" "поставь вручную: apt-get install -y $pkgs"
  okm "python3, pyte, pexpect, screen, curl на месте"
}

# ---------- Шаг 4 ----------
c4() { command -v claude >/dev/null 2>&1; }
s4() {
  header 4
  if c4; then okm "Claude Code установлен: $(claude --version 2>/dev/null | head -1)"; return; fi
  warn "Claude Code (команда claude) не найден."
  if yes_ "$WANT_CLAUDE"; then
    info "ставлю Node.js 18+ и Claude Code (1–3 минуты)…"
    if ensure_node; then
      npm install -g @anthropic-ai/claude-code >/tmp/cc_claude_npm.log 2>&1 || true
      hash -r
    else
      warn "Node.js 18+ не поставился (нужен выход на deb.nodesource.com)."
    fi
  fi
  if c4; then okm "Claude Code установлен: $(claude --version 2>/dev/null | head -1)"; return; fi
  warn "Claude Code не установлен. Панель работает, но не сможет войти в аккаунты и показать консоль."
  info "Поставь вручную: apt-get install -y nodejs npm (нужен Node.js 18+; на Ubuntu 22.04 — через NodeSource, см. docs/INSTALL.md),"
  info "затем: npm install -g @anthropic-ai/claude-code, проверка: claude --version. Установщик это не останавливает."
}

# ---------- Шаг 5 ----------
c5() {
  [ -f "$BASE/cc_limits.py" ] || return 1
  while read -r src dst mode; do
    case "$dst" in /*) target="$dst" ;; *) target="$BASE/$dst" ;; esac
    cmp -s "$SCRIPT_DIR/$src" "$target" || return 1
  done < <(module_list)
  for f in "$BASE"/*.py; do python3 -m py_compile "$f" 2>/dev/null || return 1; done
}
s5() {
  header 5
  mkdir -p "$BASE"
  local n=0
  while read -r src dst mode; do
    case "$dst" in /*) target="$dst" ;; *) target="$BASE/$dst" ;; esac
    mkdir -p "$(dirname "$target")"
    cp "$SCRIPT_DIR/$src" "$target" && chmod "$mode" "$target" || fail "не скопировался $src" "проверь права на $BASE"
    n=$((n+1))
  done < <(module_list)
  install -m 755 "$SCRIPT_DIR/cc-codex-console-localize" /usr/local/sbin/cc-codex-console-localize
  okm "скопировано файлов: $n (панель, скрипты запуска Claude, шаблоны текстов, cc-switch)"
  info "проверяю, что все файлы Python компилируются и совпадают с архивом…"
  c5 || fail "файлы в $BASE не совпали с архивом или не компилируются" "посмотри: python3 -m py_compile $BASE/*.py"
  okm "все файлы на месте и целые"
}

# ---------- Шаг 6 ----------
c6() {
  [ -f "$BASE/config.json" ] || return 1
  python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); assert c.get("hook_token") and c.get("screen_session")' "$BASE/config.json" 2>/dev/null || return 1
  [ -d "$PROFILES_DIR" ] && ls "$PROFILES_DIR"/acc*/oauth_account.json >/dev/null 2>&1
}
s6() {
  header 6
  mkdir -p "$PROFILES_DIR"
  for i in $(seq 1 "$N_ACCOUNTS"); do
    d="$PROFILES_DIR/acc$i"; mkdir -p "$d"
    [ -f "$d/oauth_account.json" ] || echo '{}' > "$d/oauth_account.json"
  done
  okm "профили аккаунтов: $N_ACCOUNTS пустых слота в $PROFILES_DIR (войдёшь в них в панели: «Добавить аккаунт» или «Войти заново»)"
  # config.json не обнуляем: hook_token и уже настроенные ключи переживают обновление
  local old_token; old_token="$(json_get "$BASE/config.json" hook_token)"
  if [ -n "$old_token" ]; then HOOK_TOKEN="$old_token"; info "config.json уже есть — обновляю, hook_token оставляю прежним"
  else HOOK_TOKEN="$(openssl rand -hex 24)"; info "config.json создан, hook_token сгенерирован случайно (храни в секрете)"; fi
  python3 - "$BASE/config.json" "$HOOK_TOKEN" "$THRESHOLD" "$SCREEN_SESSION" "$PORT" "$SERVICE_NAME" "$TZ_NAME" "$WORK_DIR" "$BASE" "$BOT_TOKEN" "$CHAT_ID" "$([ "$WANT_NGINX" = y ] && echo "$DOMAIN")" "$([ "$WANT_HTTPS" = y ] && echo https || echo http)" <<'PYEOF'
import json, os, sys
path, token, threshold, screen, port, service, tz, work, base, bot, chat, domain, scheme = sys.argv[1:14]
cfg = {"hook_token": token, "autoswitch": True, "threshold": int(threshold), "poll_sec": 120, "switch_cooldown_sec": 300,
       "optimize": False, "screen_session": screen, "port": int(port)}
fresh = not os.path.exists(path)
if os.path.exists(path):
    try:
        old = json.load(open(path))
        if isinstance(old, dict):
            old.update(cfg)   # свои ключи пользователя переживают обновление
            cfg = old
    except Exception:
        pass
if fresh: cfg["labels"] = {"main": "A", "remote": "B"}   # названия серверов («Claude A», «Claude B»): поменять в «Общие настройки»
cfg.setdefault("update_mode", "manual")      # автообновление по умолчанию ручное (кнопка в панели)
cfg.setdefault("update_check", True)
cfg["service_name"] = service                # по нему обновлятор перезапускает службу
cfg["tz"] = tz                               # время сброса и записки — в твоём часовом поясе
cfg["work_dir"] = work                       # где стартует Claude Code
cfg["start_claude"] = os.path.join(base, "start_claude.sh")
cfg["start_claude_side"] = os.path.join(base, "start_claude_side.sh")
if chat: cfg["chat_id"] = chat
if bot: cfg["bot_token"] = bot               # запасной путь, если файла телеграм-канала Claude Code нет
if domain: cfg["public_url"] = scheme + "://" + domain   # база для кнопок «меню консоли → Telegram»
with open(path, "w") as f:
    json.dump(cfg, f, indent=1, ensure_ascii=False)
PYEOF
  chmod 600 "$BASE/config.json"
  # настройки Notion AI (имя владельца для записок); существующие не трогаем
  if [ ! -f "$BASE/notion_ai.json" ]; then
    NAI_CFG="$BASE/notion_ai.json" NAI_OWNER="$OWNER_NAME" NAI_VOICE="$(yes_ "$WANT_VOICE" && echo 1 || echo 0)" python3 - <<'PY'
import json, os
d = {"chat_url": "", "owner": os.environ["NAI_OWNER"], "notion_email": "", "tg_chat_id": "", "voice": os.environ.get("NAI_VOICE") == "1", "console_tab": True}   # голосовые ответы включены, только если голос ставится
fd = os.open(os.environ["NAI_CFG"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, json.dumps(d, ensure_ascii=False, indent=1).encode()); os.close(fd)
PY
  fi
  c6 || fail "config.json или профили не в порядке" "посмотри $BASE/config.json и $PROFILES_DIR"
  okm "config.json записан (права 600), токен панели создан"
}

# ---------- Шаг 7 ----------
panel_up() { curl -fsS -m 10 "http://127.0.0.1:$PORT/api/limits?token=$(json_get "$BASE/config.json" hook_token)" 2>/dev/null | grep -q '"accounts"'; }
c7() { systemctl is-active -q "$SERVICE_NAME" && panel_up; }
s7() {
  header 7
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
  systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
  systemctl restart "$SERVICE_NAME"
  info "жду ответа панели (до 30 секунд)…"
  for _ in $(seq 1 15); do panel_up && break; sleep 2; done
  panel_up || fail "служба $SERVICE_NAME не ответила на 127.0.0.1:$PORT" "посмотри журнал: journalctl -u $SERVICE_NAME -n 50 --no-pager"
  okm "служба $SERVICE_NAME запущена, панель отвечает на 127.0.0.1:$PORT"
  local pc; pc="$(curl -fsS -m 10 "http://127.0.0.1:$PORT/api/pause?token=$(json_get "$BASE/config.json" hook_token)" 2>/dev/null || true)"
  echo "$pc" | grep -q '"ok": *true' && okm "баннер лимитов и паузы подключён (/api/pause)" || warn "/api/pause не ответил ok — баннер паузы может не работать: $pc"
}

# ---------- Шаг 8 ----------
hook_present() { grep -qs "$2" "$1" 2>/dev/null; }
c8() {
  [ -f "/etc/cron.d/$SERVICE_NAME-pause" ] || return 1
  if yes_ "$HOOK_QUEUE"; then hook_present "$CLAUDE_SETTINGS" queue_on_limits.py || return 1; fi
  if yes_ "$HOOK_TOOLS"; then hook_present "$CLAUDE_SETTINGS" pause_tool_gate.py || return 1; fi
}
add_hook() {
  # add_hook <событие> <скрипт> <matcher|-> : идемпотентно прописывает хук в settings.json Claude Code (с бэкапом)
  mkdir -p "$(dirname "$CLAUDE_SETTINGS")"
  [ -f "$CLAUDE_SETTINGS" ] || echo '{}' > "$CLAUDE_SETTINGS"
  cp "$CLAUDE_SETTINGS" "$CLAUDE_SETTINGS.bak_$(date +%Y%m%d%H%M%S)"
  CC_SETTINGS="$CLAUDE_SETTINGS" CC_EVENT="$1" CC_SCRIPT="$2" CC_MATCHER="$3" CC_HOOK_CMD="CC_LIMITS_DIR=$BASE /usr/bin/python3 $BASE/hooks/$2" python3 <<'PY'
import json, os
p, ev, script, matcher, cmd = os.environ["CC_SETTINGS"], os.environ["CC_EVENT"], os.environ["CC_SCRIPT"], os.environ["CC_MATCHER"], os.environ["CC_HOOK_CMD"]
try:
    d = json.load(open(p))
    if not isinstance(d, dict): d = {}
except Exception:
    d = {}
lst = d.setdefault("hooks", {}).setdefault(ev, [])
lst[:] = [x for x in lst if script not in json.dumps(x)]   # идемпотентность: ищем наш скрипт, а не точную строку
item = {"hooks": [{"type": "command", "command": cmd}]}
if matcher != "-": item["matcher"] = matcher
lst.append(item)
json.dump(d, open(p, "w"), ensure_ascii=False, indent=2)
PY
}
s8() {
  header 8
  local cron="/etc/cron.d/$SERVICE_NAME-pause"
  cat > "$cron" <<CRON
# cc-fleet: снятие паузы по лимитам, когда сессионное окно отпустило
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
* * * * * root CC_LIMITS_BASE=$BASE /usr/bin/python3 $BASE/pause_ctl.py wake --if-due >> $BASE/pause_wake.log 2>&1
CRON
  chmod 644 "$cron"
  okm "будильник паузы: $cron (раз в минуту, живёт в системном cron)"
  if yes_ "$HOOK_QUEUE"; then add_hook UserPromptSubmit queue_on_limits.py - && okm "хук очереди входящих прописан в $CLAUDE_SETTINGS"; else info "хук очереди не подключён (вручную: hooks.UserPromptSubmit → $BASE/hooks/queue_on_limits.py)"; fi
  if yes_ "$HOOK_TOOLS"; then add_hook PreToolUse pause_tool_gate.py '*' && okm "стоп-кран инструментов прописан в $CLAUDE_SETTINGS"; info "аварийный выход, если мешает: python3 $BASE/pause_ctl.py off"; else info "стоп-кран не подключён (вручную: hooks.PreToolUse, matcher \"*\" → $BASE/hooks/pause_tool_gate.py)"; fi
  # перезапускать нечего, пока Claude Code не запущен: при первом старте он сам прочитает settings.json
  if { yes_ "$HOOK_QUEUE" || yes_ "$HOOK_TOOLS"; } && { pgrep -x claude >/dev/null 2>&1 || pgrep -f 'claude-code' >/dev/null 2>&1; }; then warn "Claude Code читает settings.json при старте: перезапусти его сессию, чтобы хуки заработали."; fi
  c8 || fail "будильник или хуки не прописались" "проверь $cron и $CLAUDE_SETTINGS"
  okm "проверено: будильник и выбранные хуки на месте"
}

# ---------- Шаг 9 ----------
c9() {
  yes_ "$WANT_NGINX" || return 0
  [ -f "/etc/nginx/sites-enabled/$DOMAIN" ] && nginx -t >/dev/null 2>&1
}
s9() {
  header 9
  if ! yes_ "$WANT_NGINX"; then
    skip "пропущено: панель доступна только на 127.0.0.1:$PORT."
    info "Открыть с компьютера через SSH-туннель: ssh -L $PORT:127.0.0.1:$PORT root@<адрес-сервера>, потом http://127.0.0.1:$PORT/"
    info "(главная страница ждёт заголовок X-Auth-User от вашего прокси; напрямую API отвечает по ?token=…, см. README)"
    return
  fi
  local htpasswd="/etc/nginx/.htpasswd_$SERVICE_NAME"
  htpasswd -bc "$htpasswd" "$BASIC_USER" "$BASIC_PASS" >/dev/null 2>&1 || fail "не создался файл паролей" "проверь пакет apache2-utils"
  cat > "/etc/nginx/sites-available/$DOMAIN" <<NGINX
server {
    listen 80;
    server_name $DOMAIN;

    location /cc/ {
        auth_basic "Restricted";
        auth_basic_user_file $htpasswd;
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
  ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
  nginx -t >/dev/null 2>&1 || fail "nginx отверг конфиг" "посмотри: nginx -t"
  systemctl reload nginx
  okm "nginx: http://$DOMAIN/cc/ (вход: $BASIC_USER)"
  if yes_ "$WANT_HTTPS"; then
    info "получаю сертификат Let's Encrypt для $DOMAIN…"
    if certbot --nginx -d "$DOMAIN" -m "$CERT_EMAIL" --agree-tos -n --redirect >/tmp/cc_certbot.log 2>&1; then
      okm "HTTPS включён: https://$DOMAIN/cc/ (продление certbot делает сам)"
    else
      warn "сертификат не получен (лог: /tmp/cc_certbot.log). Чаще всего домен ещё не указывает на этот сервер или закрыт порт 80."
      warn "Панель работает по http. Когда исправишь: certbot --nginx -d $DOMAIN -m $CERT_EMAIL --agree-tos --redirect"
    fi
  else
    if [[ "$DOMAIN" =~ ^[0-9.]+$ ]] || [[ "$DOMAIN" == *:* ]]; then warn "HTTPS не включён: вместо домена указан IP, пароль идёт открытым текстом — используй только в доверенной сети. Домен и HTTPS добавишь позже (docs/INSTALL.md, раздел 2)."
    else warn "HTTPS не включён: пароль идёт открытым текстом. Включи: certbot --nginx -d $DOMAIN"; fi
  fi
  c9 || fail "nginx не в порядке" "посмотри: nginx -t && systemctl status nginx"
  okm "проверено: nginx работает"
}

# ---------- Шаг 10 ----------
tg_token() {
  local t=""
  [ -f "$TG_ENV_FILE" ] && t="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$TG_ENV_FILE" | head -1)"
  [ -n "$t" ] || t="$(json_get "$BASE/config.json" bot_token)"
  echo "$t"
}
tg_me() { curl -fsS -m 15 "https://api.telegram.org/bot$1/getMe" 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["result"]["username"]) if d.get("ok") else sys.exit(1)' 2>/dev/null; }
c10() {
  yes_ "$WANT_TG" || return 0
  local t; t="$(tg_token)"; [ -n "$t" ] && tg_me "$t" >/dev/null && [ -n "$(json_get "$BASE/config.json" chat_id)" ]
}
s10() {
  header 10
  if ! yes_ "$WANT_TG"; then skip "пропущено. Подключишь позже: README → «Telegram-уведомления» или мастер «Codex +» в панели."; return; fi
  local t; t="$(tg_token)"
  [ -n "$t" ] || { warn "токена бота нет — Telegram подключишь позже (⚙ в панели → «Мост Telegram»)."; return; }
  local bot; bot="$(tg_me "$t")" || fail "Telegram не принял токен бота" "проверь токен у @BotFather (/mybots → бот → API Token); токен вида 123456:ABC…"
  okm "бот найден: @$bot"
  local chat; chat="$(json_get "$BASE/config.json" chat_id)"
  if [ -z "$chat" ] && [ "$NONINTERACTIVE" != "1" ]; then
    info "Открой в Telegram @$bot и отправь ему любое сообщение (например «привет»). Жду до 2 минут…"
    for _ in $(seq 1 60); do
      chat="$(curl -fsS -m 10 "https://api.telegram.org/bot$t/getUpdates" 2>/dev/null | python3 -c 'import json,sys
try:
    r=json.load(sys.stdin).get("result",[])
    ids=[(u.get("message") or {}).get("chat",{}).get("id") for u in r]
    ids=[i for i in ids if i]
    print(ids[-1] if ids else "")
except Exception: print("")')"
      [ -n "$chat" ] && break; sleep 2
    done
    [ -n "$chat" ] && info "увидел сообщение: твой chat_id = $chat"
  fi
  [ -n "$chat" ] || fail "chat_id не определён" "отправь боту сообщение и запусти установщик снова, либо укажи chat_id: CC_FLEET_CHAT_ID=<число> sudo -E ./install.sh"
  python3 - "$BASE/config.json" "$chat" <<'PY'
import json, sys
p = sys.argv[1]; c = json.load(open(p)); c["chat_id"] = sys.argv[2]
json.dump(c, open(p, "w"), indent=1, ensure_ascii=False)
PY
  chmod 600 "$BASE/config.json"
  curl -fsS -m 15 "https://api.telegram.org/bot$t/sendMessage" --data-urlencode "chat_id=$chat" --data-urlencode "text=✅ cc-fleet установлен. Уведомления о переключениях аккаунтов будут приходить сюда." >/dev/null 2>&1 \
    && okm "тестовое сообщение отправлено в Telegram — проверь, что оно пришло" \
    || fail "бот не смог написать в чат $chat" "открой бота в Telegram и нажми Start, затем запусти установщик снова"
  systemctl restart "$SERVICE_NAME" >/dev/null 2>&1 || true
}

# ---------- Шаг 11 ----------
c11() { yes_ "$WANT_CODEX" || return 0; id "$CODEX_USER" >/dev/null 2>&1 && [ "$(json_get "$BASE/config.json" codex_user)" = "$CODEX_USER" ]; }
s11() {
  header 11
  if ! yes_ "$WANT_CODEX"; then skip "пропущено. Подключишь позже кнопкой «Codex +» в шапке панели."; return; fi
  id "$CODEX_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$CODEX_USER" || fail "не создался пользователь $CODEX_USER" "создай вручную: useradd -m -s /bin/bash $CODEX_USER"
  python3 - "$BASE/config.json" "$CODEX_USER" <<'PY'
import json, sys
p = sys.argv[1]; c = json.load(open(p)); c["codex_user"] = sys.argv[2]
json.dump(c, open(p, "w"), indent=1, ensure_ascii=False)
PY
  chmod 600 "$BASE/config.json"
  ensure_node || warn "Node.js 18+ не поставился: поставь вручную (см. docs/INSTALL.md), иначе «Codex +» не сможет установить Codex"
  systemctl restart "$SERVICE_NAME" >/dev/null 2>&1 || true
  c11 || fail "пользователь Codex не настроен" "проверь: id $CODEX_USER и codex_user в $BASE/config.json"
  okm "пользователь ОС «$CODEX_USER» создан и записан в config.json (codex_user)"
  info "Дальше в панели: кнопка «Codex +» → мастер установит Codex и подключит ChatGPT-аккаунт (docs/INSTALL.md, раздел 5)."
}

# ---------- Шаг 12 ----------
c12() { yes_ "$WANT_NOTION" || return 0; systemctl is-active -q notion-delegate; }
s12() {
  header 12
  if ! yes_ "$WANT_NOTION"; then skip "пропущено. Подключишь позже: sudo bash notion_ai/install.sh и ⚙ → Notion AI."; return; fi
  [ -f "$SCRIPT_DIR/notion_ai/install.sh" ] || fail "нет notion_ai/install.sh в архиве" "скачай релиз заново"
  bash "$SCRIPT_DIR/notion_ai/install.sh" || fail "установка служб Notion AI не удалась" "посмотри вывод выше (чаще всего Playwright/Chromium не скачался — проверь сеть и место на диске)"
  sleep 2
  c12 || fail "служба notion-delegate не запустилась" "journalctl -u notion-delegate -n 50 --no-pager"
  okm "службы Notion AI запущены (notion-delegate, notion-ai-view)"
  info "Дальше в панели: ⚙ Общие настройки → Notion AI → «Как подключить с нуля» (ссылка на чат, вход по коду из письма, ключ, проверка связи)."
}

# ---------- Шаг 13 ----------
c13() { yes_ "$WANT_VOICE" || return 0; [ -f "$SCRIPT_DIR/voice/install.sh" ] || return 0; [ -x /usr/local/bin/ccfleet-say ] && curl -fsS -m 5 http://127.0.0.1:8879/health 2>/dev/null | grep -q ok; }
s13() {
  header 13
  if ! yes_ "$WANT_VOICE"; then skip "пропущено. Подключишь позже: sudo bash voice/install.sh"; return; fi
  [ -f "$SCRIPT_DIR/voice/install.sh" ] || { skip "в этой версии голос не входит в пакет (код умеет пользоваться готовым /root/tts/say.sh, если он у тебя есть)"; return; }
  bash "$SCRIPT_DIR/voice/install.sh" || fail "установка голоса не удалась" "посмотри вывод выше; голос необязателен — можно подключить позже"
  c13 || fail "служба голоса не отвечает" "journalctl -u ccfleet-tts -n 50 --no-pager"
  okm "голос работает: озвучка (ccfleet-say) и расшифровка (ccfleet-transcribe)"
}

# ---------- Шаг 14 ----------
s14() {
  header 14
  local url
  if yes_ "$WANT_NGINX"; then url="$(scheme)://$DOMAIN/cc/"; else url="http://127.0.0.1:$PORT/ (через SSH-туннель)"; fi
  echo
  echo -e "${CG}Установка завершена.${C0} cc-fleet $VERSION"
  echo -e "  Панель:      ${CB}$url${C0}"
  yes_ "$WANT_NGINX" && echo -e "  Вход:        $BASIC_USER / (пароль, который ты задал)"
  echo -e "  hook_token:  лежит в $BASE/config.json ${CY}(секрет, нужен для API: здесь не печатаю, чтобы он не попал в журнал установки)${C0}"
  echo
  echo -e "${CB}Что осталось сделать руками (по порядку):${C0}"
  command -v claude >/dev/null 2>&1 || echo "  ☐ Поставить Claude Code: npm install -g @anthropic-ai/claude-code (нужен Node.js 18+)"
  echo "  ☐ Войти в аккаунты Claude: панель → «Добавить аккаунт» или «Войти заново» в меню ⋯ карточки (docs/INSTALL.md, раздел 3)"
  echo "  ☐ Запустить Claude Code в screen-сессии: $BASE/start_claude.sh (или кнопка «Запустить» в панели)"
  yes_ "$WANT_TG" || echo "  ☐ Подключить Telegram: docs/INSTALL.md, раздел 4"
  yes_ "$WANT_CODEX" && echo "  ☐ Codex: панель → «Codex +» → мастер (docs/INSTALL.md, раздел 5)" || echo "  ☐ Codex (по желанию): запусти установщик снова и ответь «y» на вопрос про Codex"
  yes_ "$WANT_NOTION" && echo "  ☐ Notion AI: панель → ⚙ Общие настройки → Notion AI (docs/INSTALL.md, раздел 6)"
  echo "  ☐ Второй сервер (по желанию): панель → ⚙ Общие настройки → «Второй сервер» (docs/INSTALL.md, раздел 7)"
  echo
  echo "Проверить установку в любой момент: sudo ./install.sh --check"
  echo "Подробная инструкция со всеми подключениями: docs/INSTALL.md"
}

STEP_FUNCS=(s1 s2 s3 s4 s5 s6 s7 s8 s9 s10 s11 s12 s13 s14)
CHECK_FUNCS=(c1 c2 c3 c4 c5 c6 c7 c8 c9 c10 c11 c12 c13 true)

# перепроверка пройденных шагов перед очередным (кроме шага 4: Claude Code необязателен для установки)
recheck_before() {
  local upto=$1 bad=""
  VERBOSE=0
  for i in $(seq 1 $((upto-1))); do
    [ "$i" = 2 ] || [ "$i" = 4 ] && continue
    "${CHECK_FUNCS[$((i-1))]}" || bad="$bad $i"
  done
  VERBOSE=1
  [ -z "$bad" ] || fail "перед шагом $upto сломалась проверка шагов:$bad" "запусти ./install.sh --check, чтобы увидеть подробности"
  [ "$upto" -le 2 ] || info "↺ проверил предыдущие шаги: всё на месте"
}

if [ "$CHECK_ONLY" = 1 ]; then
  [ -f "$STATE_FILE" ] && . "$STATE_FILE"
  [ -n "$CLAUDE_SETTINGS" ] || CLAUDE_SETTINGS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
  [ -f "$BASE/config.json" ] && [ -z "$SCREEN_SESSION" ] && SCREEN_SESSION="$(json_get "$BASE/config.json" screen_session)"
  [ -f "$BASE/config.json" ] && PORT="$(json_get "$BASE/config.json" port)"
  echo -e "${CB}cc-fleet $VERSION — проверка установки${C0}"
  bad=0
  for i in $(seq 1 $((TOTAL-1))); do
    [ "$i" = 2 ] && continue
    if "${CHECK_FUNCS[$((i-1))]}"; then okm "Шаг $i из $TOTAL — ${STEP_TITLES[$((i-1))]}"; else echo -e "   ${CR}❌ Шаг $i из $TOTAL — ${STEP_TITLES[$((i-1))]}${C0}"; bad=1; fi
  done
  [ "$bad" = 0 ] && echo -e "${CG}Всё в порядке.${C0}" || echo -e "${CY}Есть невыполненные шаги: запусти sudo ./install.sh — он доделает.${C0}"
  exit $bad
fi

echo -e "${CB}cc-fleet $VERSION — установка${C0}"
echo "Ставим на этот сервер как службу systemd. Всего шагов: $TOTAL. Любой шаг можно повторить — установщик безопасен к перезапуску."
for n in $(seq 1 "$TOTAL"); do
  [ "$n" -gt 2 ] && recheck_before "$n"
  "${STEP_FUNCS[$((n-1))]}"
done
