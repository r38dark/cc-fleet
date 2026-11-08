#!/usr/bin/env bash
# cc-fleet — голос (необязательно): озвучка ответов (Silero, русский) и расшифровка голосовых сообщений (Whisper small).
# Всё работает локально на вашем сервере: без ключей, без внешних сервисов, только localhost.
#
#   sudo bash voice/install.sh            установка (или продолжение прерванной)
#   sudo bash voice/install.sh --check    только проверить, какие шаги готовы (ничего не меняет)
#   sudo bash voice/install.sh --remove   убрать голос (служба, файлы, команды; панель продолжит работать без голоса)
#
# Нужно ~5 ГБ места и 2 ГБ памяти; первая загрузка моделей занимает 5–15 минут. Установка идёт по шагам «Шаг N из 8»:
# после каждого шага проверка, перед следующим — повторная проверка предыдущих. Остановилась — запусти снова, продолжит с места.
# Лицензии: модели Silero — на условиях автора (https://github.com/snakers4/silero-models, раздел License; для коммерческого
# использования проверьте её), faster-whisper и модели Whisper — MIT, ruaccent — по лицензии проекта, словарь dict/hard_e.json
# собран из Викисловаря (CC BY-SA). Подробности — voice/README.md.
set -uo pipefail

VOICE_DIR="${CCFLEET_VOICE_DIR:-/opt/ccfleet-voice}"
PORT="${CCFLEET_VOICE_PORT:-8879}"
BIN_DIR="${CCFLEET_VOICE_BIN:-/usr/local/bin}"
UNIT="${CCFLEET_VOICE_UNIT:-/etc/systemd/system/ccfleet-tts.service}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIN_DISK_MB="${CCFLEET_VOICE_MIN_DISK_MB:-5000}"
MIN_RAM_MB="${CCFLEET_VOICE_MIN_RAM_MB:-1800}"
WAIT_START_SEC="${CCFLEET_VOICE_WAIT:-300}"
TEST_PHRASE="Проверка голоса. Один, два, три."
CHECK_ONLY=0; REMOVE=0
case "${1:-}" in
  --check) CHECK_ONLY=1 ;;
  --remove) REMOVE=1 ;;
  -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

C0=$'\033[0m'; CB=$'\033[1m'; CG=$'\033[1;32m'; CR=$'\033[1;31m'; CY=$'\033[1;33m'; CC=$'\033[1;36m'
okm()  { echo -e "   ${CG}✅${C0} $*"; }
info() { echo -e "   $*"; }
fail() {
  echo -e "   ${CR}❌ $1${C0}" >&2
  [ -n "${2:-}" ] && echo -e "   ${CY}Что делать:${C0} $2" >&2
  echo -e "   Исправь и запусти снова: ${CB}sudo bash voice/install.sh${C0} — он проверит сделанное и продолжит." >&2
  exit 1
}
TITLES=("Проверка сервера" "Системные пакеты" "Озвучка: окружение Python" "Расшифровка: окружение Python" "Файлы и команды" "Модели и служба" "Проверка озвучки" "Проверка расшифровки")
TOTAL=${#TITLES[@]}
header() { echo; echo -e "${CB}━━ Голос · шаг $1 из $TOTAL — ${TITLES[$(($1-1))]} ━━${C0}"; }
health() { curl -fsS -m 5 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q ok; }
pyok() { "$1" -c "$2" >/dev/null 2>&1; }

# ---------- проверки шагов (ничего не меняют); возвращают 0 — шаг готов ----------
# env_problem: печатает «что не так|что делать» для первой найденной проблемы сервера; пусто — всё в порядке
env_problem() {
  [ "$(id -u)" = 0 ] || { echo "нужен root|запусти: sudo bash voice/install.sh"; return; }
  command -v apt-get >/dev/null 2>&1 || { echo "нет apt-get: установщик голоса рассчитан на Ubuntu/Debian|поставь вручную по voice/README.md (раздел «Без установщика»)"; return; }
  command -v systemctl >/dev/null 2>&1 || { echo "нет systemd|поставь вручную по voice/README.md"; return; }
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null || { echo "нужен Python 3.9 или новее ($(python3 --version 2>&1))|обнови python3 (apt-get install python3)"; return; }
  local t="$VOICE_DIR" free_mb ram_mb h
  while [ ! -d "$t" ]; do t="$(dirname "$t")"; done
  free_mb=$(df -Pm "$t" | awk 'NR==2{print $4}')
  [ "${free_mb:-0}" -ge "$MIN_DISK_MB" ] || { echo "мало места: свободно ${free_mb:-?} МБ, нужно не меньше $MIN_DISK_MB МБ в $t|освободи место или задай другой каталог: CCFLEET_VOICE_DIR=/путь sudo -E bash voice/install.sh"; return; }
  ram_mb=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
  [ "${ram_mb:-0}" -ge "$MIN_RAM_MB" ] || { echo "мало памяти: ${ram_mb:-?} МБ, нужно не меньше $MIN_RAM_MB МБ|голос на этом сервере не поместится; панель работает и без него"; return; }
  for h in download.pytorch.org pypi.org huggingface.co github.com; do
    [ "$(curl -s -o /dev/null -m 12 -w '%{http_code}' "https://$h" 2>/dev/null)" != "000" ] || { echo "нет доступа к $h|нужен выход в интернет с сервера (проверь DNS и файрвол)"; return; }  # любой HTTP-ответ (даже 403) — сервер достижим
  done
}
c1() { [ -z "$(env_problem)" ]; }
c2() { command -v ffmpeg >/dev/null 2>&1 && command -v curl >/dev/null 2>&1 && python3 -c 'import venv, ensurepip' 2>/dev/null; }
c3() { [ -x "$VOICE_DIR/venv-tts/bin/python3" ] && pyok "$VOICE_DIR/venv-tts/bin/python3" 'import torch, num2words, ruaccent, numpy, omegaconf'; }
c4() { [ -x "$VOICE_DIR/venv-stt/bin/python3" ] && pyok "$VOICE_DIR/venv-stt/bin/python3" 'import faster_whisper, av; assert int(av.__version__.split(".")[0]) < 19'; }
c5() { [ -f "$VOICE_DIR/server.py" ] && [ -f "$VOICE_DIR/dict/hard_e.json" ] && [ -x "$BIN_DIR/ccfleet-say" ] && [ -x "$BIN_DIR/ccfleet-say-long" ] \
        && [ -x "$BIN_DIR/ccfleet-transcribe" ] && [ -f "$UNIT" ]; }
c6() { systemctl is-active --quiet ccfleet-tts 2>/dev/null && health; }
c7() { [ -s "$VOICE_DIR/test.ogg" ] && ffprobe -v error -show_entries format=duration -of csv=p=0 "$VOICE_DIR/test.ogg" 2>/dev/null | awk '{exit !($1 >= 0.8)}'; }
c8() { [ -s "$VOICE_DIR/test.txt" ] && grep -qi 'провер' "$VOICE_DIR/test.txt"; }
checks=(c1 c2 c3 c4 c5 c6 c7 c8)

# ---------- шаги ----------
s1() {
  local prob; prob="$(env_problem)"
  [ -z "$prob" ] || fail "${prob%%|*}" "${prob#*|}"
  local free_mb ram_mb t="$VOICE_DIR"; while [ ! -d "$t" ]; do t="$(dirname "$t")"; done
  free_mb=$(df -Pm "$t" | awk 'NR==2{print $4}'); ram_mb=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
  okm "root, Ubuntu/Debian, Python $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])'), свободно $((free_mb/1024)) ГБ, память $((ram_mb/1024)) ГБ, интернет есть"
}
s2() {
  export DEBIAN_FRONTEND=noninteractive
  info "apt-get install: python3-venv python3-pip ffmpeg curl ca-certificates…"
  apt-get update -qq >/dev/null 2>&1 || true
  apt-get install -y -qq python3-venv python3-pip ffmpeg curl ca-certificates >/dev/null 2>&1 \
    || fail "apt-get не поставил пакеты" "запусти вручную: apt-get install -y python3-venv python3-pip ffmpeg curl и посмотри ошибку"
  okm "ffmpeg, venv, pip на месте"
}
s3() {
  mkdir -p "$VOICE_DIR"
  [ -x "$VOICE_DIR/venv-tts/bin/python3" ] || python3 -m venv "$VOICE_DIR/venv-tts" || fail "не создалось окружение $VOICE_DIR/venv-tts" "проверь python3-venv"
  local pip="$VOICE_DIR/venv-tts/bin/pip"
  info "pip: torch (версия для процессора, ~200 МБ), num2words, omegaconf, ruaccent… (несколько минут)"
  "$pip" install -q --upgrade pip >/dev/null 2>&1 || true
  "$pip" install -q torch --index-url https://download.pytorch.org/whl/cpu >/dev/null 2>"$VOICE_DIR/pip-tts.err" \
    || fail "не поставился torch" "смотри $VOICE_DIR/pip-tts.err; нужен выход на download.pytorch.org"
  "$pip" install -q -r "$SRC/requirements-tts.txt" >/dev/null 2>>"$VOICE_DIR/pip-tts.err" \
    || fail "не поставились num2words/omegaconf/ruaccent" "смотри $VOICE_DIR/pip-tts.err"
  okm "torch, num2words, omegaconf, ruaccent импортируются"
}
s4() {
  mkdir -p "$VOICE_DIR"
  [ -x "$VOICE_DIR/venv-stt/bin/python3" ] || python3 -m venv "$VOICE_DIR/venv-stt" || fail "не создалось окружение $VOICE_DIR/venv-stt" "проверь python3-venv"
  info "pip: faster-whisper…"
  "$VOICE_DIR/venv-stt/bin/pip" install -q --upgrade pip >/dev/null 2>&1 || true
  "$VOICE_DIR/venv-stt/bin/pip" install -q -r "$SRC/requirements-stt.txt" >/dev/null 2>"$VOICE_DIR/pip-stt.err" \
    || fail "не поставился faster-whisper" "смотри $VOICE_DIR/pip-stt.err"
  okm "faster-whisper импортируется (av подходящей версии)"
}
s5() {
  mkdir -p "$VOICE_DIR/dict" "$BIN_DIR"
  install -m 644 "$SRC/server.py" "$VOICE_DIR/server.py"
  install -m 644 "$SRC/dict/hard_e.json" "$VOICE_DIR/dict/hard_e.json"
  local b
  for b in ccfleet-say ccfleet-say-long ccfleet-transcribe; do install -m 755 "$SRC/bin/$b" "$BIN_DIR/$b"; done
  sed "s#@VOICE_DIR@#$VOICE_DIR#g" "$SRC/ccfleet-tts.service" > "$UNIT"
  systemctl daemon-reload
  okm "файлы в $VOICE_DIR, команды ccfleet-say / ccfleet-say-long / ccfleet-transcribe в $BIN_DIR, служба ccfleet-tts"
}
# preload_models: скачивает и проверяет модели ПЕРЕД запуском службы (в самой службе обрыв загрузки оставил бы ruaccent с пустыми папками: он считает их
# «уже скачанными», и служба падала бы при каждом старте). Если прошлая загрузка оборвана — чистим её следы и пробуем ещё раз.
preload_models() {
  local py="$VOICE_DIR/venv-tts/bin/python3" ra attempt
  ra="$("$py" -c 'import os, ruaccent; print(os.path.dirname(ruaccent.__file__))' 2>/dev/null)" || return 1
  for attempt in 1 2; do
    ( cd "$VOICE_DIR" && CCFLEET_VOICE_DIR="$VOICE_DIR" HF_HOME="$VOICE_DIR/hf" "$py" -c 'import server; server.get_model(); server.get_accentizer(); print("модели загружены")' ) 2>"$VOICE_DIR/preload.err" && return 0
    info "загрузка не удалась (попытка $attempt из 2): $(tail -n 1 "$VOICE_DIR/preload.err" | cut -c1-160)"
    rm -rf "$ra/nn" "$ra/dictionary" "$ra/.cache" "$VOICE_DIR/model/master.zip"
  done
  return 1
}
s6() {
  systemctl stop ccfleet-tts >/dev/null 2>&1 || true
  info "загружаю модели озвучки (Silero и ruaccent, ~1,5 ГБ): первый раз 5–15 минут, ничего не зависло…"
  preload_models || fail "модели озвучки не загрузились" "смотри $VOICE_DIR/preload.err; чаще всего нет доступа к github.com или huggingface.co; после исправления запусти снова"
  systemctl enable ccfleet-tts >/dev/null 2>&1 || true
  systemctl restart ccfleet-tts
  local t=0 bad=0
  while [ "$t" -lt "$WAIT_START_SEC" ]; do
    health && { okm "служба отвечает на http://127.0.0.1:$PORT (модели в памяти)"; return 0; }
    if systemctl is-active --quiet ccfleet-tts; then bad=0; else bad=$((bad+1)); fi
    [ "$bad" -lt 4 ] || fail "служба ccfleet-tts не запускается" "$(journalctl -u ccfleet-tts -n 6 --no-pager 2>/dev/null | tail -n 3 | cut -c1-200 | tr '\n' ' ') — полный журнал: journalctl -u ccfleet-tts -n 60 --no-pager"
    sleep 5; t=$((t+5))
  done
  fail "служба не ответила за $((WAIT_START_SEC/60)) мин" "journalctl -u ccfleet-tts -n 60 --no-pager"
}
s7() {
  rm -f "$VOICE_DIR/test.ogg"
  "$BIN_DIR/ccfleet-say" "$TEST_PHRASE" "$VOICE_DIR/test.ogg" kseniya || fail "озвучка не получилась" "journalctl -u ccfleet-tts -n 60 --no-pager"
  c7 || fail "озвучка вернула пустой или слишком короткий файл" "journalctl -u ccfleet-tts -n 60 --no-pager"
  okm "ccfleet-say сделал голосовое: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VOICE_DIR/test.ogg" | cut -c1-4) с, $(stat -c %s "$VOICE_DIR/test.ogg") байт"
}
s8() {
  info "расшифровываю тестовое голосовое (первый раз скачивается модель Whisper small, ~460 МБ)…"
  rm -f "$VOICE_DIR/test.txt"
  "$BIN_DIR/ccfleet-transcribe" "$VOICE_DIR/test.ogg" > "$VOICE_DIR/test.txt" 2>"$VOICE_DIR/stt.err" \
    || fail "расшифровка не получилась" "смотри $VOICE_DIR/stt.err; нужен выход на huggingface.co (модель скачивается один раз)"
  c8 || fail "расшифровка не узнала тестовую фразу (получилось: «$(head -c 120 "$VOICE_DIR/test.txt")»)" "проверь, что озвучка s7 правильная: послушай $VOICE_DIR/test.ogg"
  okm "ccfleet-transcribe услышал: «$(tr '\n' ' ' < "$VOICE_DIR/test.txt" | head -c 100)»"
}

# enable_in_panel: после успешной установки включает «Голосовые ответы в Telegram» в настройках Notion AI (если панель уже стоит)
enable_in_panel() {
  local cfg="${CC_LIMITS_BASE:-/opt/cc-limits}/notion_ai.json"
  [ -f "$cfg" ] || return 0
  python3 - "$cfg" <<'PY' && info "в настройках Notion AI включены «Голосовые ответы в Telegram»"
import json, sys
p = sys.argv[1]
d = json.load(open(p)); d["voice"] = True
json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
PY
  return 0
}

# ---------- удаление ----------
if [ "$REMOVE" = 1 ]; then
  [ "$(id -u)" = 0 ] || { echo "нужен root" >&2; exit 1; }
  systemctl disable --now ccfleet-tts >/dev/null 2>&1 || true
  rm -f "$UNIT" "$BIN_DIR/ccfleet-say" "$BIN_DIR/ccfleet-say-long" "$BIN_DIR/ccfleet-transcribe"
  systemctl daemon-reload 2>/dev/null || true
  rm -rf "$VOICE_DIR"
  echo "Голос убран: служба, команды и $VOICE_DIR. Панель продолжит работать без голоса."
  exit 0
fi

# ---------- основной цикл: следующий шаг сначала перепроверяет предыдущие ----------
if [ "$CHECK_ONLY" = 1 ]; then
  echo -e "${CB}Голос: что готово${C0}"
  for i in "${!checks[@]}"; do
    if ${checks[$i]}; then echo -e "   ${CG}✅${C0} шаг $((i+1)) из $TOTAL — ${TITLES[$i]}"; else echo -e "   ${CY}⬜${C0} шаг $((i+1)) из $TOTAL — ${TITLES[$i]} (не выполнен)"; fi
  done
  exit 0
fi
for n in 1 2 3 4 5 6 7 8; do
  for p in $(seq 1 $((n-1))); do
    "${checks[$((p-1))]}" || { header "$p"; info "перепроверка: шаг $p не готов — делаю заново"; "s$p"; }
  done
  header "$n"
  if "${checks[$((n-1))]}"; then okm "уже готово"; else "s$n"; fi
done
enable_in_panel
echo
echo -e "${CG}Голос установлен.${C0} Озвучка: ${CB}ccfleet-say \"текст\" файл.ogg${C0} · расшифровка: ${CB}ccfleet-transcribe файл.oga${C0} · служба: systemctl status ccfleet-tts"
echo "Панель и агенты Notion подхватят голос сами (проверка: curl http://127.0.0.1:$PORT/health → ok). Убрать: sudo bash voice/install.sh --remove"
