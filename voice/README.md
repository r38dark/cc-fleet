# Голос для cc-fleet (необязательно)

Два локальных инструмента, без ключей и внешних сервисов, всё на вашем сервере:

| Что | Команда | Чем сделано |
|---|---|---|
| Озвучка: текст → голосовое `.ogg` (opus) | `ccfleet-say "текст" файл.ogg [голос]` | Silero v4 (русский) + ruaccent (ударения), служба `ccfleet-tts` на `127.0.0.1:8879` |
| Озвучка длинного текста | `ccfleet-say-long файл.txt файл.ogg [голос]` | режет на куски и склеивает |
| Расшифровка: голосовое → текст | `ccfleet-transcribe файл.oga` | faster-whisper, модель `small`, русский, процессор |

Голоса: `kseniya` (по умолчанию), `aidar`, `baya`, `xenia`, `eugene`.

Где это нужно панели: агент Notion AI отвечает в Telegram текстом **и голосом** (`notion-ai-reply`), а голосовые сообщения из Telegram
расшифровываются в текст. Без голоса всё работает текстом; галка «Голосовые ответы в Telegram» — в ⚙ Настройки → Notion AI.

## Что нужно
Ubuntu/Debian с systemd, root, Python 3.9+, **~5 ГБ места и 2 ГБ памяти**, выход в интернет с сервера (PyTorch, PyPI, Hugging Face, GitHub — только на время установки и первой загрузки моделей).

## Установка
```
sudo bash voice/install.sh            # установка или продолжение прерванной
sudo bash voice/install.sh --check    # что готово (ничего не меняет)
sudo bash voice/install.sh --remove   # убрать голос целиком
```
Если ставите общим установщиком — это его «Шаг 13 из 14 — Голос» (по умолчанию выключен; в вопросах установщика ответьте `y`).

Установка идёт по шагам **«Голос · шаг N из 8»**. После каждого шага — проверка, перед следующим — повторная проверка предыдущих.

| Шаг | Что делает | Как понять, что он прошёл |
|---|---|---|
| 1 | Проверяет сервер | root, apt, systemd, Python 3.9+, место, память, доступ к 4 сайтам |
| 2 | Ставит ffmpeg, venv, pip | `ffmpeg -version` |
| 3 | Окружение озвучки в `/opt/ccfleet-voice/venv-tts` | импорт torch, num2words, omegaconf, ruaccent |
| 4 | Окружение расшифровки `/opt/ccfleet-voice/venv-stt` (версии — `requirements-stt.txt`) | импорт faster_whisper |
| 5 | Кладёт `server.py`, словарь, команды `ccfleet-*`, службу | файлы на месте |
| 6 | Скачивает модели (Silero, ruaccent: ~1,5 ГБ, 5–15 мин) и запускает службу `ccfleet-tts` | `curl http://127.0.0.1:8879/health` → `ok` |
| 7 | **Озвучивает тестовую фразу** | файл `test.ogg` длиннее 0,8 с |
| 8 | **Расшифровывает её обратно** | в тексте есть «провер…» |

Шаги 7–8 — сквозная проверка: голос сказал фразу, расшифровка её услышала.

## Если не вышло
| Что вижу | Причина | Что делать |
|---|---|---|
| «нет доступа к … » на шаге 1 | с сервера закрыт выход в интернет | открыть исходящий HTTPS (443) или использовать прокси: `export HTTPS_PROXY=…` и запустить снова |
| «мало места» / «мало памяти» | не хватает ресурсов | освободить место, `CCFLEET_VOICE_DIR=/другой/каталог sudo -E bash voice/install.sh`; при памяти < 2 ГБ голос не ставьте |
| ошибка pip на шаге 3 или 4 | нет сети до PyPI или download.pytorch.org | смотреть `/opt/ccfleet-voice/pip-tts.err` / `pip-stt.err`, повторить запуск |
| шаг 6 «модели озвучки не загрузились» | нет доступа к github.com / huggingface.co или обрыв загрузки | `/opt/ccfleet-voice/preload.err`; после исправления запустить снова (следы обрыва установщик чистит сам) |
| шаг 6 «служба не запускается» | ошибка при старте | `journalctl -u ccfleet-tts -n 60 --no-pager` |
| `ccfleet-say: голос не получился (HTTP 000)` | служба не запущена | `systemctl status ccfleet-tts`, `systemctl restart ccfleet-tts` |
| голос читает слово не так | ударение/«е»-«э» словаря | поправьте словарь `/opt/ccfleet-voice/dict/hard_e.json` или напишите слово с ударением `+` (например `зам+ок`) |

## Без установщика (вручную)
`python3 -m venv /opt/ccfleet-voice/venv-tts && /opt/ccfleet-voice/venv-tts/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu && …/pip install -r voice/requirements-tts.txt`,
отдельное окружение `venv-stt` (`pip install -r voice/requirements-stt.txt`), затем скопировать `voice/server.py` и `voice/dict/` в `/opt/ccfleet-voice/`, `voice/bin/*` — в `/usr/local/bin/`,
`voice/ccfleet-tts.service` (заменить `@VOICE_DIR@`) — в `/etc/systemd/system/` и `systemctl enable --now ccfleet-tts`.

## Лицензии и источники
- Модели Silero — на условиях автора: https://github.com/snakers4/silero-models (раздел License). **Для коммерческого использования проверьте условия.**
- faster-whisper и модели Whisper — MIT. ruaccent — по лицензии проекта (https://github.com/Den4ikAI/ruaccent).
- `dict/hard_e.json` (слова, где «е» читается как «э») собран из Викисловаря (CC BY-SA); скрипт сборки в репозиторий не входит.
