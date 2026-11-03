"""Изолированная витрина рабочего HTML. Все API и данные — подделки, без входа и subprocess."""
import ast,hashlib,json,sys,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
ROOT=Path(__file__).resolve().parent
SOURCE_ROOT=ROOT/'stage' if (ROOT/'stage').is_dir() else ROOT.parent
sys.path.insert(0,str(SOURCE_ROOT))
import cc_overview
import preview_actions
from profile_scenarios import ProfileScenarios
PROFILE_SYSTEM=ProfileScenarios()
source=(SOURCE_ROOT/'cc_limits.py').read_text()
tree=ast.parse(source)
original=next(n.value.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PAGE' for t in n.targets))
PAGE=cc_overview.render(original).replace('__TOKEN__','preview-only').replace('__PAGE_VER__','1.26.0-design')
PAGE=PAGE.replace("location.origin+'/cc-hook/'","location.origin+'/cc-demo-api/'")
PAGE=PAGE.replace('<body>','<body><div class="fleet-preview">Изолированный стенд · демонстрационные данные. Рабочая консоль и аккаунты не подключены.</div>',1)
PAGE=PAGE.replace('</body>','''<script>(()=>{const box=document.getElementById('acctBox');if(!box)return;new MutationObserver(()=>{if(box.querySelector('.fleet-demo-note'))return;const n=document.createElement('div');n.className='fleet-demo-note';n.textContent='Демонстрация: изменения действуют только на стенде. Для входа используйте код DEMO. Настоящие команды не выполняются.';box.prepend(n)}).observe(box,{childList:true})})();</script></body>''',1)
RESET='2026-11-04T18:00:00+08:00'
MODELS=[{'id':'gpt-6.1-sol','name':'GPT-6.1 Sol','efforts':['low','medium','high','xhigh'],'default_effort':'high','is_default':True,'fast':'priority'},
        {'id':'gpt-6.1-terra','name':'GPT-6.1 Terra','efforts':['high','xhigh'],'default_effort':'xhigh','is_default':False,'fast':None}]
ROWS=[{'slot':'gpt'+str(i+1),'label':name,'email':f'codex-{i+1}@example.com','plan':'pro' if i==0 else 'plus',
       'windows':[{'mins':300,'pct':[34,12,6][i],'resets_at':RESET},{'mins':10080,'pct':[46,22,14][i],'resets_at':RESET}],
       'models':MODELS,'model':'gpt-6.1-sol','effort':'high','fast':False,'ts':time.time()} for i,name in enumerate(['Основной','Рабочий','Запасной'])]
CLAUDE={f'acc{i+1}':{'email':f'claude-{i+1}@example.com','plan':'max' if i==0 else 'pro','active':i==0,'five_hour':{'pct':[42,18,100][i],'resets_at':RESET},'seven_day':{'pct':[61,35,78][i],'resets_at':RESET}} for i in range(3)}

for i,row in enumerate(CLAUDE.values()): row['label']=['Основной','Рабочий','Резервный'][i]
PROFILE_DEFS=[{'id':'orchestrator','builtin':True,'mode':'orchestrator','access':'read','task_rights':'dev'},{'id':'codex','builtin':True,'mode':'self','access':'write','task_rights':'dev'},{'id':'codex_solo_full','builtin':True,'mode':'self','access':'full','task_rights':'dev'}]
STATE={'optimize':True,'cx_optimize':True,'threshold':90,'weekly_cap':99,'profile':'codex_solo_full','model':'gpt-6.1-sol','effort':'high','requests':[],'active':'gpt1'}
preview_actions.prepare(STATE,ROWS)
def bridge():
 current=next((p for p in PROFILE_DEFS if p['id']==STATE['profile']),PROFILE_DEFS[-1])
 return {'ok':True,'available':True,'bridge':{'profile':STATE['profile'],'mode':current['mode'],'access':current['access'],'task_rights':current['task_rights'],'workdir':'/opt/codex-trial','project':'/opt/codex-trial','workspace':'/opt/codex-trial','sandbox':'danger-full-access','enabled':False,'token_set':False,'bot':'','chat_id':'','busy':False,'running':True,'slots':[r['slot'] for r in ROWS],'slot':STATE['active'],
 'profiles':PROFILE_DEFS},'profile_system':PROFILE_SYSTEM.public(),'emergency':{'active':bool(STATE.get('demo_emergency_active',False)),'available':True,'configured':True,'hours':2,'services':[],'files':0,'ssh':False,'word':'DEMO','now':time.time(),'until':STATE.get('demo_emergency_until',0),'journal':[]}}
def models():
 model=STATE.get('claude_model','opus');name={'opus':'Opus','sonnet':'Sonnet'}.get(model,model);effort=STATE.get('claude_effort','high')
 return {'session':model,'session_name':name,'default':model,'default_name':name,'available':[{'id':'opus','name':'Opus','enabled':True,'efforts':['low','medium','high','xhigh']},{'id':'sonnet','name':'Sonnet','enabled':True,'efforts':['low','medium','high']}], 'effort':effort,'effort_default':effort,'efforts':['low','medium','high','xhigh'],'effort_supported':['low','medium','high','xhigh']}
PAUSE_END=time.time()+55*3600
PAUSE_OVERRIDE=False
def pause_view(sample=False):
 if not sample:return {'ok':True,'level':'none','pause':{'active':False,'override':False}}
 active=next((key for key,row in CLAUDE.items() if row.get('active')),'acc1')
 return {'ok':True,'level':'week','active':active,'threshold':90,'weekly_cap':99,'nearest':{'acc':active,'resets_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(PAUSE_END))},'accounts':{key:{'active':key==active,'pct':(row.get('five_hour') or {}).get('pct',0),'wpct':100,'usable':False,'held':'неделя','ses_ok':True} for key,row in CLAUDE.items()},'pause':{'active':not PAUSE_OVERRIDE,'override':PAUSE_OVERRIDE,'kind':'week','resume_at':PAUSE_END,'checks':3,'note':'Демонстрационный пример состояния паузы.'}}
def reserve_view():
 manual=bool(STATE.get('reserve_manual',False))
 return {'available':True,'connected':True,'agent':{'name':'Демонстрационный резерв','set':False},'reserve':{'ready':True,'active':manual,'manual':manual,'why':'manual' if manual else '', 'claude':'up','auto':bool(STATE.get('reserve_auto',False)),'auto_emergency':bool(STATE.get('reserve_auto_emergency',False))}}
def backup_view():
 return {'ok':True,'enabled':bool(STATE.get('profile_backup',True)),'profiles':len(CLAUDE),'items':[],'latest':{'ts':STATE['backup_ts']} if STATE.get('backup_ts') else None,'missing':[]}
class H(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,data,status=200,html=False):
  raw=data.encode() if html else json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def path_key(self):return urlparse(self.path).path.replace('/cc-demo-api/','/api/',1)
 def do_GET(self):
  p=self.path_key()
  if p in ['/','/cc-demo/'] and parse_qs(urlparse(self.path).query).get('demo_auth'):return self.send(preview_actions.AUTH_PAGE,html=True)
  if p in ['/','/cc-demo/']:
   page=PAGE
   if parse_qs(urlparse(self.path).query).get('pause'):page=page.replace("API+'pause?token='+TOKEN","API+'pause?token='+TOKEN+'&demo_pause=1'")
   return self.send(page,html=True)
  if p=='/test/requests':return self.send(STATE['requests'])
  if p=='/api/profiles':return self.send(PROFILE_SYSTEM.public())
  if p=='/api/limits':return self.send({'ts':time.time(),'active':next((k for k,v in CLAUDE.items() if v.get('active')),''),'accounts':CLAUDE,'config':dict(STATE['claude_config'],optimize=STATE['optimize']),'model':models(),'notion':reserve_view()})
  if p=='/api/chatgpt':return self.send({'ok':True,'available':True,'accounts':ROWS})
  if p=='/api/chatgpt/bridge':return self.send(bridge())
  if p=='/api/chatgpt/rotation':return self.send({'ok':True,'optimize':STATE['cx_optimize'],'threshold':STATE['threshold'],'weekly_cap':STATE['weekly_cap'],'active':STATE['active'],'next':'gpt2','next_label':'Рабочий','model':STATE['model'],'effort':STATE['effort'],'message':'Демонстрационный автовыбор Codex','last_error':''})
  if p=='/api/console':return self.send({'ok':True,'session':'codex' if 's=codex' in self.path else 'claude','available':True,'running':True,'sandbox':'danger-full-access','cwd':'/opt/codex-trial','current':'<span style="color:#54d6b0">›_ ДЕМО-КОНСОЛЬ</span>\n\nМодель: '+STATE['model']+' · '+STATE['effort']+'\nПапка: /opt/codex-trial\n\nГотов к вводу в изолированном стенде.\n\nНастоящие команды здесь не выполняются.','history':''})
  if p=='/api/pause':return self.send(pause_view(bool(parse_qs(urlparse(self.path).query).get('demo_pause'))))
  if p=='/api/notion':return self.send(reserve_view())
  if p=='/api/update':return self.send({'version':'1.26.0-design','phase':'idle','check':bool(STATE.get('update_check',False)),'mode':STATE.get('update_mode','manual'),'auto':STATE.get('update_mode')=='auto','latest':None,'last_check':STATE.get('last_update_check',0),'state':{}})
  if p=='/api/backup':return self.send(backup_view())
  if p=='/api/changelog':return self.send({'versions':[]})
  return self.send({'ok':True,'available':False,'accounts':[],'candidates':[]})
 def do_POST(self):
  p=self.path_key();length=int(self.headers.get('Content-Length') or 0)
  if length>65536:return self.send({'ok':False,'message':'too large'},413)
  try:d=json.loads(self.rfile.read(length) or b'{}')
  except ValueError:return self.send({'ok':False},400)
  record={'path':p,'fields':{k:v for k,v in d.items() if k in ['slot','account','model','effort','fast','optimize','threshold','weekly_cap','autoswitch','weekly_pause','session','key','request_id','id','cmd','lang']}}
  if isinstance(d.get('text'),str):record['text_sha256']=hashlib.sha256(d['text'].encode()).hexdigest()
  STATE['requests'].append(record);STATE['requests']=STATE['requests'][-200:]
  if p=='/test/availability':return self.send(PROFILE_SYSTEM.set_availability(d.get('engine'),d.get('available')))
  if p.startswith('/api/profiles/'):
   parts=p.split('/');engine=parts[3] if len(parts)>3 else '';action=parts[4] if len(parts)>4 else ''
   if action=='apply':result=PROFILE_SYSTEM.apply(engine,d.get('id'),d.get('confirm',''),d.get('revision'))
   elif action=='stop':result=PROFILE_SYSTEM.stop_service(engine,d.get('revision'))
   elif action=='config':result=PROFILE_SYSTEM.configure(engine,d.get('enabled'),d.get('emergency'),d.get('confirm',''),d.get('revision'))
   elif action=='delete':result=PROFILE_SYSTEM.delete(engine,d.get('id'),d.get('revision'))
   else:return self.send({'ok':False,'message':'Неизвестное действие.'},404)
   snap=PROFILE_SYSTEM.public();cx=snap['engines']['codex'];STATE['profile']=cx['base_selected'];STATE['reserve_manual']=cx['role']=='reserve';STATE['demo_emergency_active']=cx['role']=='emergency';STATE['demo_emergency_until']=cx.get('until',0)
   return self.send(result)
  if p in ['/api/chatgpt/emergency/on','/api/chatgpt/emergency/off']:
   if p.endswith('/on') and d.get('word')!='DEMO':return self.send({'ok':False,'message':'Демо: для подтверждения введите DEMO.'})
   STATE['demo_emergency_active']=p.endswith('/on');STATE['demo_emergency_until']=time.time()+7200 if STATE['demo_emergency_active'] else 0
   return self.send({'ok':True,'message':'Демонстрационное состояние изменено. Настоящие права и службы не затронуты.'})
  if p=='/api/notion/save':
   for k,v in (d.get('reserve') or {}).items():STATE['reserve_'+k]=v
   return self.send({'ok':True,'notion':reserve_view()})
  if p=='/api/pause':
   global PAUSE_OVERRIDE
   PAUSE_OVERRIDE=d.get('action')=='off'
   return self.send(pause_view(True))
  if p in ['/api/backup/now','/api/backup/restore']:
   if p.endswith('/now'):STATE['backup_ts']=time.time()
   return self.send(dict(backup_view(),restored=[]))
  if p=='/api/update/check':
   STATE['last_update_check']=time.time()
   return self.send({'ok':True,'version':'1.26.0-design','phase':'idle','check':bool(STATE.get('update_check',False)),'mode':STATE.get('update_mode','manual'),'latest':None,'last_check':STATE['last_update_check'],'state':{}})
  if p in ['/api/model','/api/effort']:
   value=d.get('model') if p=='/api/model' else d.get('effort')
   if value not in (['opus','sonnet'] if p=='/api/model' else ['minimal','low','medium','high','max','xhigh']):return self.send({'ok':False,'message':'Неверный демонстрационный выбор.'})
   STATE['claude_model' if p=='/api/model' else 'claude_effort']=value
   return self.send({'ok':True,'message':'Демо: выбор Claude сохранён.','model':models()})
  action=preview_actions.handle(p,d,STATE,CLAUDE,ROWS,MODELS,RESET)
  if action is not None:return self.send(action)
  if p=='/api/config':STATE['optimize']=d.get('optimize',STATE['optimize'])
  if p=='/api/chatgpt/rotation/config':
   for k,v in d.items():STATE['cx_optimize' if k=='optimize' else k]=v
  if p=='/api/chatgpt/rotation/switch':STATE['active']=d['slot']
  if p=='/api/chatgpt/bridge/profile/apply':
   profile=next((p for p in PROFILE_DEFS if p['id']==d.get('id')),None)
   if not profile:return self.send({'ok':False,'message':'Такого демонстрационного профиля нет.'})
   if profile['access']=='full' and STATE['profile']!='codex_solo_full' and d.get('confirm')!='подтверждаю':return self.send({'ok':False,'message':'Для этого профиля введите «подтверждаю».'})
   STATE['profile']=profile['id']
   return self.send({'ok':True,'message':'Демо: профиль применён. Настоящая консоль не меняется.'})
  if p=='/api/chatgpt/prefs':
   STATE['model'],STATE['effort']=d.get('model') or STATE['model'],d.get('effort') or STATE['effort']
   for a in ROWS:
    if a['slot']==d.get('slot'):a.update(model=STATE['model'],effort=STATE['effort'],fast=d.get('fast',False))
  if p.endswith('/login/start') or '/account/add/' in p:return self.send({'ok':False,'message':'Демонстрация: настоящий вход не запускается.'})
  return self.send({'ok':True,'message':'Действие проверено только на демонстрационном стенде.'})
if __name__=='__main__':
 port=int(sys.argv[1]) if len(sys.argv)>1 else 18975
 ThreadingHTTPServer(('127.0.0.1',port),H).serve_forever()
