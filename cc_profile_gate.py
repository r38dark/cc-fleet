"""Claude CLI hooks: enforce the selected profile independently of prompt text."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

READ_TOOLS = {'Read', 'Glob', 'Grep', 'WebSearch', 'WebFetch'}
WRITE_TOOLS = {'Edit', 'Write', 'NotebookEdit'}
AGENT_TOOLS = {'Agent', 'Task', 'SendMessage', 'TeamCreate', 'TeamDelete'}

def inside(path, roots):
    path = os.path.realpath(path)
    return any(path == os.path.realpath(r) or path.startswith(os.path.realpath(r).rstrip('/')+'/') for r in roots)

def own_executor(policy, event):
    """Профиль «Opus → Sonnet»: разрешён только вызов своего исполнителя (имя из policy.agents, модель задана
    профилем). Чужие агенты, fork, общий агент, удалённый запуск и вложенный вызов из самого исполнителя — нет."""
    agents = policy.get('agents')
    if event.get('tool_name') != 'Agent' or not policy.get('subagent_model') or not isinstance(agents, dict):
        return False
    args = event.get('tool_input') or {}
    if event.get('agent_id') or args.get('isolation') == 'remote':
        return False
    return args.get('subagent_type') in agents

def decide(policy, event):
    if policy.get('paused'):
        return 'Claude на паузе: активен служебный режим другой стороны.'
    if event.get('hook_event_name') == 'UserPromptSubmit':
        return ''
    name = event.get('tool_name', '')
    if own_executor(policy, event):
        return ''
    if name in AGENT_TOOLS or name.startswith(('mcp__codex', 'mcp__claude')):
        return 'Этот профиль использует только подтверждённые шаги через балансер.'
    if name.startswith(('mcp__plugin_telegram','mcp__telegram')) and name.rsplit('__',1)[-1] in ('reply','react','download_attachment'):
        return ''
    if policy.get('access') == 'full':
        return ''
    if name not in READ_TOOLS | WRITE_TOOLS:
        return 'В этом профиле доступны чтение и файлы рабочей папки. Для команд выбери Full.'
    if name in ('WebFetch', 'WebSearch'):
        return ''
    args = event.get('tool_input') or {}
    path = args.get('file_path') or args.get('notebook_path') or args.get('path') or event.get('cwd') or policy['cwd']
    if not os.path.isabs(path):
        path = os.path.join(event.get('cwd') or policy['cwd'], path)
    roots = policy.get('write_roots', []) if name in WRITE_TOOLS else policy.get('read_roots', [])
    if not inside(path, roots):
        return 'Путь вне разрешённых папок этого профиля.'
    return ''

def main():
    parser = argparse.ArgumentParser();parser.add_argument('--base', required=True);args = parser.parse_args()
    try:
        policy = json.loads((Path(args.base)/'profile_runtime/claude-policy.json').read_text())
        event = json.load(sys.stdin)
        reason = decide(policy, event)
    except Exception:
        event = {};reason = 'Не удалось проверить профиль. Дождись восстановления балансера.'
    if reason:
        result = {'decision': 'block', 'reason': reason} if event.get('hook_event_name') == 'UserPromptSubmit' else {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': reason}}
        print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
