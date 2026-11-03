"""Только демонстрационные действия: никакого OAuth, исполнения команд и реальных аккаунтов."""
import time

ATTEMPTS={}
DEMO_URL='https://deskpharm.ru/cc-demo/?demo_auth=1'
AUTH_PAGE='''<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Демонстрационный вход</title><body style="background:#0c1017;color:#e8edf4;font:16px/1.6 system-ui;max-width:560px;margin:10vh auto;padding:24px"><h1>Демонстрационный вход</h1><p>Это тестовый сценарий. Входить в настоящие аккаунты и вводить пароли не нужно.</p><p>Для формы Claude используйте код:</p><strong style="font:28px monospace;color:#45d6ab">DEMO</strong><p>Вход Codex завершится автоматически в окне демо.</p><a href="/cc-demo/" style="color:#45d6ab">Вернуться к демо</a></body></html>'''

def prepare(state,rows):
 state['claude_config']={'threshold':90,'weekly_cap':99,'autoswitch':True,'weekly_pause':True}
 for row in rows:row['launch']='# ДЕМО: запуск аккаунта '+row['slot']+'; настоящая команда здесь не выполняется'

def next_slot(prefix,keys):
 return prefix+str(max([int(k[len(prefix):]) for k in keys if k.startswith(prefix) and k[len(prefix):].isdigit()]+[0])+1)

def handle(path,body,state,claude,rows,models,reset):
 def ok(message='Демо: действие выполнено.',**extra):return dict(ok=True,message=message,**extra)
 def fail(message):return dict(ok=False,message=message)
 if path=='/api/config':
  if 'optimize' in body:state['optimize']=bool(body['optimize'])
  for key in ('update_mode','update_check','profile_backup'):
   if key in body:state[key]=body[key]
  for key in ('threshold','weekly_cap','autoswitch','weekly_pause'):
   if key in body:state['claude_config'][key]=body[key]
  return ok()
 if path=='/api/switch':
  if state['optimize']:return fail('Демо: выключите оптимизацию Claude для ручного выбора.')
  slot=body.get('account');keys=list(claude)
  if slot=='next':slot=next((k for k,v in claude.items() if not v.get('active')),keys[0] if keys else '')
  if slot not in claude:return fail('Демонстрационный аккаунт не найден.')
  for key,row in claude.items():row['active']=key==slot
  return ok('Демо: аккаунт Claude выбран.')
 if path in ('/api/account/add/start','/api/relogin/start'):
  slot=body.get('account') if path.startswith('/api/relogin') else next_slot('acc',claude)
  if path.startswith('/api/relogin') and slot not in claude:return fail('Аккаунт не найден.')
  ATTEMPTS[slot]={'provider':'claude','relogin':path.startswith('/api/relogin'),'started':time.time()}
  return ok(slot=slot,url=DEMO_URL,email=(claude.get(slot) or {}).get('email','demo-new@example.com'))
 if path in ('/api/account/add/submit','/api/relogin/submit'):
  slot=body.get('slot') or body.get('account');pending=ATTEMPTS.get(slot)
  if not pending:return fail('Начните демонстрационный вход заново.')
  if str(body.get('code') or '').strip().upper()!='DEMO':return fail('В демонстрации используйте тестовый код DEMO.')
  if not pending.get('relogin'):
   claude[slot]={'email':'demo-'+slot+'@example.com','label':'Новый аккаунт','plan':'pro','active':False,'five_hour':{'pct':5,'resets_at':reset},'seven_day':{'pct':12,'resets_at':reset}}
  ATTEMPTS.pop(slot,None);return ok('Демо: аккаунт Claude добавлен.' if not pending.get('relogin') else 'Демо: вход Claude обновлён.')
 if path=='/api/account/delete':
  slot=body.get('account')
  if str(body.get('confirm') or '').lower().strip() not in ('подтверждаю','confirm'):return fail('Введите слово подтверждения.')
  if len(claude)<=1:return fail('Последний демонстрационный аккаунт удалять нельзя.')
  if slot not in claude:return fail('Аккаунт не найден.')
  if claude[slot].get('active'):return fail('Сначала выберите другой демонстрационный аккаунт.')
  claude.pop(slot);return ok('Демо: аккаунт Claude удалён.')
 if path=='/api/chatgpt/login/start':
  slot=body.get('slot') or next_slot('gpt',[r['slot'] for r in rows]);existing=next((r for r in rows if r['slot']==slot),None)
  if body.get('slot') and not existing:return fail('Аккаунт не найден.')
  ATTEMPTS[slot]={'provider':'codex','label':str(body.get('label') or '')[:60],'existing':bool(existing),'polls':0,'started':time.time()}
  return ok(slot=slot,url=DEMO_URL,code='DEMO-CODE',expires_in=900)
 if path=='/api/chatgpt/login/status':
  slot=body.get('slot');pending=ATTEMPTS.get(slot)
  if not pending:return ok(state='none')
  pending['polls']+=1
  if pending['polls']<2:return ok(state='waiting',left=900)
  existing=next((r for r in rows if r['slot']==slot),None)
  if not existing:
   existing={'slot':slot,'label':pending['label'] or 'Новый аккаунт','email':'demo-'+slot+'@example.com','plan':'plus','windows':[{'mins':300,'pct':5,'resets_at':reset},{'mins':10080,'pct':12,'resets_at':reset}],'models':models,'model':'gpt-6.1-sol','effort':'high','fast':False,'ts':time.time(),'launch':'# ДЕМО: запуск аккаунта '+slot};rows.append(existing)
  return ok(state='done',email=existing['email'],plan=existing['plan'])
 if path=='/api/chatgpt/login/cancel':ATTEMPTS.pop(body.get('slot'),None);return ok()
 if path=='/api/chatgpt/prefs':
  row=next((r for r in rows if r['slot']==body.get('slot')),None)
  if not row:return fail('Аккаунт не найден.')
  model=body.get('model') or next((m['id'] for m in models if m.get('is_default')),models[0]['id'])
  selected=next((m for m in models if m['id']==model),None)
  if not selected:return fail('Модель не найдена.')
  effort=body.get('effort') or selected['default_effort'];row.update(model=model,effort=effort,fast=bool(body.get('fast') and selected.get('fast')))
  if row['slot']==state['active']:state.update(model=model,effort=effort)
  return ok('Демо: модель и усилие сохранены.')
 if path=='/api/chatgpt/rotation/config':
  for key,value in body.items():
   if key in ('optimize','threshold','weekly_cap'):state['cx_optimize' if key=='optimize' else key]=value
  return ok()
 if path=='/api/chatgpt/rotation/switch':
  if state['cx_optimize']:return fail('Демо: выключите оптимизацию Codex для ручного выбора.')
  row=next((r for r in rows if r['slot']==body.get('slot')),None)
  if not row:return fail('Аккаунт не найден.')
  state.update(active=row['slot'],model=row['model'],effort=row['effort']);return ok('Демо: аккаунт Codex выбран.')
 if path=='/api/chatgpt/delete':
  if str(body.get('confirm') or '').lower().strip() not in ('подтверждаю','confirm'):return fail('Введите слово подтверждения.')
  slot=body.get('slot')
  if slot==state['active']:return fail('Сначала выберите другой демонстрационный аккаунт.')
  rows[:]=[r for r in rows if r['slot']!=slot];return ok('Демо: аккаунт Codex удалён.')
 if path=='/api/console/input':return ok('Демо: ввод передан в '+('Codex' if body.get('session')=='codex' else 'Claude')+'. Настоящая команда не выполнялась.')
 if path=='/api/console/key':return ok('Демо: клавиша передана выбранной консоли.')
 return None
