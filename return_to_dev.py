#!/usr/bin/env python3
"""Вернуть работу с Claude PROD на Claude DEV (то же, что кнопка «Вернуть» в панели): POST /api/remote/off с force.

Запуск на dev (с PROD через ssh):  python3 /root/cc-fleet-dist/return_to_dev.py "причина"
Вызывать ПОСЛЕДНИМ действием: панель остановит Claude PROD, соберёт хвост беседы и отдаст его Claude DEV запиской.
Токен берётся из /opt/cc-limits/config.json внутри процесса и не печатается."""
import json
import sys
import urllib.error
import urllib.request

PORT = 8877   # cc-limits.service (config.json: port, по умолчанию 8877)


def main():
    try:
        config = json.load(open('/opt/cc-limits/config.json', encoding='utf-8'))
    except (OSError, ValueError):
        print('config.json не прочитан'); return 2
    reason = (sys.argv[1] if len(sys.argv) > 1 else 'возврат после работы на PROD')[:80]
    request = urllib.request.Request(
        'http://127.0.0.1:%d/api/remote/off' % int(config.get('port', PORT)),
        data=json.dumps({'reason': reason, 'force': True}, ensure_ascii=False).encode(),
        headers={'X-CC-Token': config.get('hook_token', ''), 'Content-Type': 'application/json'}, method='POST')
    try:
        answer = json.load(urllib.request.urlopen(request, timeout=60))
    except urllib.error.URLError as exc:
        print('панель не ответила: %s' % type(exc).__name__); return 3
    print(json.dumps({k: answer.get(k) for k in ('ok', 'started', 'message')}, ensure_ascii=False))
    return 0 if answer.get('ok') else 1


if __name__ == '__main__':
    sys.exit(main())
