"""Чтение параметров живой беседы без чтения учётных данных и без записи в БД Codex."""
import json
import os
import sqlite3
import tomllib
from pathlib import Path


def preferences(home):
    try:
        config = tomllib.loads((Path(home) / 'config.toml').read_text())
    except (OSError, ValueError):
        config = {}
    return {key: config.get(key) for key in ('model', 'model_reasoning_effort', 'service_tier', 'sqlite_home')}


def capture(meta, profile_dir, cwd=None, slot=None):
    slot = slot or meta.get('slot')
    if not slot:
        return {}
    home = profile_dir(slot)
    pref = preferences(home)
    target_cwd = os.path.realpath(str(cwd or meta.get('cwd') or '.'))
    db_home = os.path.expanduser(str(meta.get('history_home') or pref.get('sqlite_home') or home))
    if not os.path.isabs(db_home):
        db_home = os.path.join(target_cwd, db_home)
    tid = (meta.get('tids') or {}).get(target_cwd)
    result = {'model': pref.get('model'), 'effort': pref.get('model_reasoning_effort'),
              'service_tier': pref.get('service_tier'), 'thread_id': tid,
              'history_home': os.path.abspath(os.path.expanduser(db_home)), 'cwd': target_cwd}
    # Codex сам хранит текущую модель/effort и абсолютный путь rollout в индексе.
    for db in sorted(Path(result['history_home']).glob('state_*.sqlite'), reverse=True):
        try:
            con = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=1)
            try:
                columns = {row[1] for row in con.execute('PRAGMA table_info(threads)')}
                wanted = [name for name in ('id', 'model', 'reasoning_effort', 'rollout_path', 'cwd', 'updated_at', 'updated_at_ms', 'created_at') if name in columns]
                if not wanted:
                    continue
                if tid:
                    row = con.execute('SELECT '+','.join(wanted)+' FROM threads WHERE id=?', (tid,)).fetchone()
                elif 'cwd' in columns:
                    order = next((k for k in ('updated_at_ms', 'updated_at', 'created_at') if k in columns), 'id')
                    # Новый разговор не должен возобновить старую беседу этой папки.
                    fresh = (meta.get('settings') or {}).get('new_session')
                    if fresh and 'created_at' not in columns:
                        continue
                    clause = ' AND created_at>=?' if fresh else ''
                    params = (target_cwd, meta.get('started', 0)) if fresh else (target_cwd,)
                    row = con.execute('SELECT '+','.join(wanted)+' FROM threads WHERE cwd=?'+clause+' ORDER BY '+order+' DESC LIMIT 1', params).fetchone()
                else:
                    continue
                if row:
                    values = dict(zip(wanted, row))
                    result['thread_id'] = values.get('id') or tid
                    if values.get('model'):
                        result['model'] = values['model']
                    if values.get('reasoning_effort'):
                        result['effort'] = values['reasoning_effort']
                    if values.get('rollout_path'):
                        result['rollout_path'] = values['rollout_path']
                    updated = values.get('updated_at_ms') or values.get('updated_at') or 0
                    if updated > 10**11:
                        updated /= 1000
                    if updated < meta.get('started', 0):
                        # До первого нового хода индекс ещё содержит прежнюю модель.
                        for key in ('model', 'effort', 'service_tier'):
                            if key in (meta.get('settings') or {}):
                                result[key] = meta['settings'][key]
                    break
            finally:
                con.close()
        except (OSError, sqlite3.Error):
            continue
    # Параметры запуска служат резервом для старых схем индекса без модели.
    for key in ('model', 'effort', 'service_tier'):
        if not result.get(key) and (meta.get('settings') or {}).get(key):
            result[key] = meta['settings'][key]
    return result


def launch_args(binary, settings, sandbox, approval, mcp=()):
    args = [binary]
    tid = settings.get('thread_id')
    if not settings.get('new_session') and tid:
        args.append('resume')
        args.append(tid)
        args.append('--all')
    # The managed TUI owns its runtime. A shared daemon can retain the thread
    # after its screen exits and prevent the replacement TUI from resuming it.
    args.extend(['--no-daemon', '--sandbox', sandbox, '--ask-for-approval', approval])
    if settings.get('cwd'):
        args.extend(['--cd', settings['cwd']])
    if settings.get('model'):
        args.extend(['--model', settings['model']])
    if settings.get('effort'):
        args.extend(['-c', 'model_reasoning_effort='+json.dumps(settings['effort'])])
    if settings.get('service_tier'):
        args.extend(['-c', 'service_tier='+json.dumps(settings['service_tier'])])
    if settings.get('history_home'):
        args.extend(['-c', 'sqlite_home='+json.dumps(settings['history_home'])])
    # Для возобновления применяется выбранная рабочая папка, а не папка старой сессии.
    args.extend(['-c', 'tui.resume_cwd="current"'])
    args.extend(mcp)
    return args
