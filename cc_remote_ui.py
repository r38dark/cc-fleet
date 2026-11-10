"""[remote] Панель: удалённый Claude-аккаунт (прод друга) — строка и плитка в «Активных аккаунтах» (как у Claude DEV)
и карточка в «Лимитах и переключениях». Данные приходят в /api/limits под ключом remote (cc_remote.cached);
в автовыборе аккаунтов он не участвует. Состояние «работает/пауза» берёт шапка (cc_notion_ai, сегмент prod)."""

CSS = r"""
.fleet-live-account.prod{--live-accent:var(--fleet-claude)}
.fleet-compact-account.prod{--live-accent:var(--fleet-claude)}
.fleet-live-account[data-provider="prod"]{border-color:color-mix(in srgb,var(--fleet-claude) 38%,var(--fleet-line));background:linear-gradient(120deg,var(--fleet-claude-soft),var(--card) 60%)}
.fleet-live-account[data-provider="prod"] .mirror-profile-button{border-color:color-mix(in srgb,var(--fleet-claude) 40%,var(--fleet-line))}
.fleet-live-account[data-provider="prod"] .mirror-profile-button .cxdot{background:var(--fleet-claude)}
.fleet-live-account.prod .mirror-profile-button .cxdot.err{background:var(--warn)}
.fleet-live-account.prod .rm-prof[aria-disabled="true"]{opacity:.6;cursor:default}
.rm-quick .cxqnote{margin:10px 0 0;font-size:12px;color:var(--fleet-muted)}
.rm-quick .cxqnote.bad{color:var(--warn)}
.fleet-live-account.prod .fleet-live-email{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
html:root:root.ag-live-prod #fleetActiveAccounts .fleet-compact-account.prod{box-shadow:inset 0 0 0 1px #49d6aa}
html:root:root.ag-live-prod #fleetActiveAccounts .fleet-live-account.prod{border-color:#49d6aa}
html:root:root.ag-pause-prod .fleet-live-account.prod .fleet-live-name::before,html:root:root.ag-pause-prod .fleet-live-account.prod .cxdot,html:root:root.ag-pause-prod .fleet-compact-account.prod .fleet-compact-name::before,html:root:root.ag-pause-prod .fleet-console-toolbar #ctProd::before{--pz:var(--fleet-claude,#e7af85);width:7px!important;height:8px!important;border:0!important;border-radius:1px!important;box-shadow:none!important;animation:none!important;background:linear-gradient(90deg,var(--pz) 0 2.4px,transparent 2.4px 4.6px,var(--pz) 4.6px 7px)!important}
.fleet-compact-account.prod[data-online="0"] .fleet-compact-name::before{background:var(--warn)}
.fleet-remote-card{position:relative}
.fleet-remote-card .fleet-card-footer{flex-wrap:wrap;row-gap:8px}
.fleet-remote-card .fleet-card-caption{flex:1 1 0;white-space:normal;overflow:visible;text-overflow:clip}
.fleet-remote-card .rm-relogin{margin:0}
.fleet-remote-card .fleet-card-state.off{color:var(--warn)}
.fleet-remote-card .fleet-card-date b{font-variant-numeric:tabular-nums}
.fleet-card-auto{display:flex;align-items:center;gap:8px;margin:10px 0 2px;font-size:12px;color:var(--fleet-muted);cursor:pointer}
.fleet-card-auto input{accent-color:var(--fleet-claude);width:15px;height:15px;margin:0}
.rm-hand{--rm-c:var(--live-accent,var(--fleet-claude));--rm-ic:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.1' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M4 8h14l-3.5-3.5M20 16H6l3.5 3.5'/%3E%3C/svg%3E");grid-area:hand;align-self:center;justify-self:end;display:inline-flex;align-items:center;justify-content:center;gap:8px;box-sizing:border-box;width:252px;height:34px;margin:0 28px 0 0;padding:0 14px;border-radius:7px;border:1px solid color-mix(in srgb,var(--rm-c) 55%,var(--fleet-line));background:color-mix(in srgb,var(--rm-c) 10%,var(--bg));color:var(--txt);font:inherit;font-size:12px;font-weight:600;line-height:1;white-space:nowrap;cursor:pointer;-webkit-tap-highlight-color:transparent;transition:border-color .15s,background .15s,color .15s}
.fleet-live-account.notion .rm-hand{--rm-c:#a78bfa}
.rm-hand::before{content:"";flex:none;width:15px;height:15px;background:currentColor;-webkit-mask:var(--rm-ic) center/contain no-repeat;mask:var(--rm-ic) center/contain no-repeat}
.rm-hand:hover:not([disabled]){border-color:var(--rm-c);background:color-mix(in srgb,var(--rm-c) 18%,var(--bg))}
.rm-hand:focus-visible{outline:2px solid var(--rm-c);outline-offset:2px}
.rm-hand[disabled]{cursor:default}
.rm-hand.wait,.rm-hand.lock{opacity:.55}
.rm-hand.here{--rm-ic:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 12.5l4.5 4.5L19 7.5'/%3E%3C/svg%3E");border-color:var(--fleet-line);background:var(--bg);color:var(--fleet-muted)}
.rm-hand.here::before{background:#49d6aa}
@keyframes rmspin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:no-preference){.rm-hand.go::before{animation:rmspin 1.1s linear infinite}}
html:root:root:root #fleetActiveAccounts .fleet-live-account{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"identity hand" "profile profile";column-gap:12px}
@media(max-width:640px){html:root:root:root #fleetActiveAccounts .fleet-live-account{grid-template-columns:minmax(0,1fr);grid-template-areas:"identity" "hand" "profile"}
 html:root:root:root #fleetActiveAccounts .rm-hand{justify-self:stretch;width:auto;margin:0;height:38px}}
.rm-hconf{--rm-c:var(--fleet-claude)}
.rm-hconf .cxpbody{padding:14px 16px 16px}
.rm-hconf h3{margin:0 0 6px;font-size:14px;font-weight:600;color:var(--txt)}
.rm-hconf p,.rm-hconf li{margin:0;font-size:12px;line-height:1.5;color:var(--fleet-muted)}
.rm-hconf ul{margin:8px 0 0;padding:0;list-style:none}
.rm-hconf li{position:relative;padding-left:16px}
.rm-hconf li::before{content:"";position:absolute;left:3px;top:.62em;width:5px;height:5px;border-radius:50%;background:var(--rm-c)}
.rm-hconf .rm-hnote{margin-top:10px}
.rm-hconf .rm-hnote.bad{color:var(--warn)}
.rm-hbtns{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}
.rm-hbtns button{height:32px;padding:0 14px;border-radius:7px;border:1px solid var(--fleet-line);background:var(--bg);color:var(--txt);font:inherit;font-size:12px;font-weight:600;cursor:pointer}
.rm-hbtns button:focus-visible{outline:2px solid var(--rm-c);outline-offset:2px}
.rm-hbtns .rm-hyes{border-color:var(--rm-c);background:color-mix(in srgb,var(--rm-c) 22%,var(--bg))}
.rm-hbtns button[disabled]{opacity:.55;cursor:default}
.rm-popts{display:grid;gap:8px;margin:10px 0 0}
.rm-popt{display:grid;grid-template-columns:16px minmax(0,1fr) auto;column-gap:10px;row-gap:3px;align-items:start;box-sizing:border-box;width:100%;padding:10px 12px;border-radius:8px;border:1px solid var(--fleet-line);background:var(--bg);color:var(--txt);font:inherit;text-align:left;cursor:pointer;-webkit-tap-highlight-color:transparent}
.rm-popt i{grid-row:1/3;box-sizing:border-box;width:14px;height:14px;margin-top:2px;border-radius:50%;border:2px solid var(--fleet-line)}
.rm-popt b{min-width:0;font-size:13px;font-weight:600}
.rm-popt em{font-style:normal;font-size:11px;font-weight:600;color:var(--rm-c)}
.rm-popt span{grid-column:2/4;font-size:12px;line-height:1.45;color:var(--fleet-muted)}
.rm-popt.on{border-color:color-mix(in srgb,var(--rm-c) 55%,var(--fleet-line))}
.rm-popt.on i,.rm-popt.sel i{border-color:var(--rm-c);background:radial-gradient(circle,var(--rm-c) 0 36%,transparent 40%)}
.rm-popt.sel{border-color:var(--rm-c);background:color-mix(in srgb,var(--rm-c) 12%,var(--bg))}
.rm-popt[disabled]{opacity:.55;cursor:default}
.rm-popt.on[disabled]{opacity:1}
.rm-popt:focus-visible{outline:2px solid var(--rm-c);outline-offset:2px}
.rm-pair .rm-hint{margin:10px 0 0}
"""

JS = r"""
// [remote] Аккаунт на другом сервере (PROD): строка и плитка как у Claude DEV (модель, effort, профиль, лимиты).
(function(){try{
var compact=null,tile=null;
function $i(id){return document.getElementById(id)}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function mem(){var s=null;try{s=typeof lastSnap!=='undefined'?lastSnap:null}catch(e){}var r=s&&s.remote;if(!r)return null;var k=Object.keys(r)[0];return k?Object.assign({id:k},r[k]):null}
var WD=new Intl.DateTimeFormat('ru',{weekday:'short',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:window.FLEET_TZ});
var CK=new Intl.DateTimeFormat('ru',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:window.FLEET_TZ}),DY=new Intl.DateTimeFormat('ru',{day:'2-digit',month:'2-digit',timeZone:window.FLEET_TZ});
function clk(t){var d=DY.format(t),c=CK.format(t);return d===DY.format(new Date())?c:d+' '+c}   // время сброса 5 ч по Иркутску
function when(win,week){var t=win&&win.resets_at?new Date(win.resets_at):null;if(!t||isNaN(t))return 'Время не получено';
 if(week)return WD.format(t).replace(/,/g,'');var m=Math.ceil((t.getTime()-Date.now())/60000);if(m<=0)return 'сброс ожидается';var h=Math.floor(m/60),r=m%60;return clk(t)+' · через '+(h?h+' ч'+(r?' ':''):'')+(r?r+' мин':'')}
function pct(win){return win&&isFinite(win.pct)?Math.round(win.pct):null}
function tone(p){return p==null?'unknown':p>=99?'bad':p>=85?'warn':'normal'}
function color(p){return p==null?'var(--txt)':p>=99?'var(--bad)':p>=85?'var(--warn)':'var(--ok)'}
function httpCode(m){return m&&m.error&&m.error.indexOf('http_')===0?m.error.slice(5):''}
function status(m){return !m.online?'нет связи':m.error==='no_login'?'нужен вход':m.error==='token_expired'?'токен устарел':httpCode(m)?'лимиты не обновились · '+httpCode(m):'онлайн'}
// пояснение к надписи: что случилось и почему цифры на плитке могут быть старыми
function statusHint(m){var c=httpCode(m);if(!c)return '';
 var why=c==='429'?'слишком частые запросы к Anthropic':c==='401'||c==='403'?'доступ отклонён, возможно, нужен новый вход':c.charAt(0)==='5'?'сбой на стороне Anthropic':'ответ сервера Anthropic с ошибкой';
 return 'Запрос лимитов вернул ошибку '+c+' ('+why+'). Показаны цифры последнего удачного опроса — они могли устареть. Опрос повторится сам; Claude на PROD от этого не останавливается.'}
function modelName(id){if(!id)return '—';var m=/^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-|$)/.exec(id);if(!m)return id;return m[1].charAt(0).toUpperCase()+m[1].slice(1)+' '+m[2]+(m[3]?'.'+m[3]:'')}
var base=(typeof API!=='undefined'?API:location.origin+'/cc-hook/'),tok=(typeof TOKEN!=='undefined'?TOKEN:''),pollT=0,note='';
function rmode(){var s=null;try{s=typeof lastSnap!=='undefined'?lastSnap:null}catch(e){}return s&&s.remote_mode||{}}
function post(path,body){return fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':tok},body:JSON.stringify(body||{})}).then(function(r){return r.json()})}
function poll(){clearTimeout(pollT);pollT=setTimeout(function(){pollT=0;fetch(base+'remote',{headers:{'X-CC-Token':tok},cache:'no-store'}).then(function(r){return r.json()}).then(function(j){
 try{if(lastSnap){lastSnap.remote_mode=j;if(j.limits)lastSnap.remote=j.limits}}catch(e){}paint();try{window.naiReload&&window.naiReload()}catch(e){}if(j.busy)poll()}).catch(function(){poll()})},2000)}
var NM={dev:'Claude DEV',prod:'Claude PROD',codex:'Codex',notion:'Notion AI'},TG={claude:'dev',prod:'prod',codex:'codex',notion:'notion'},ACC={dev:'var(--fleet-claude)',prod:'var(--fleet-claude)',codex:'var(--fleet-accent)',notion:'#a78bfa'};
var hp=null,hAnchor=null,hTarget='',hForce=false,hMine=false,wasBusy=false,hRaf=0;
function worker(){return rmode().worker||'dev'}
function sToast(t){try{typeof toast==='function'&&toast(t)}catch(e){}}
function hSteps(src,tg){
 var stop={dev:'Claude DEV остановится',prod:'Claude PROD остановится',codex:'Codex встанет на паузу',notion:'Notion AI выключится'},start={dev:'Claude DEV запустится заново',prod:'Claude PROD возьмёт работу (лимиты аккаунта друга)',codex:'Codex возьмёт работу',notion:'Notion AI возьмёт работу'};
 var l=[stop[src],start[tg],'Telegram перейдёт к '+NM[tg]];
 if(tg==='prod'&&src!=='dev')l.push('передача идёт через Claude DEV: он ненадолго запустится');
 if(src==='prod'&&tg!=='dev')l.push('Claude DEV при этом не запускается');
 return l}
function hPaint(warn){if(!hp)return;var src=worker();
 hp.style.setProperty('--rm-c',ACC[hTarget]||'var(--fleet-claude)');
 hp.querySelector('.cxpbody').innerHTML='<h3>'+(hForce?'Claude на PROD отвечает':'Передать работу в '+esc(NM[hTarget])+'?')+'</h3>'
  +'<p>Сейчас работает: '+esc(NM[src])+'.</p><ul>'+hSteps(src,hTarget).map(function(x){return '<li>'+esc(x)+'</li>'}).join('')+'</ul>'
  +(warn?'<p class="rm-hnote bad">'+esc(warn)+'</p>':'')
  +'<div class="rm-hbtns"><button type="button" class="rm-hno">Отмена</button><button type="button" class="rm-hyes">'+(hForce?'Всё равно передать':'Передать')+'</button></div>'}
function hPlace(){if(!hp)return;var a=hAnchor;
 if(a&&a.isConnected&&a.offsetParent!==null&&window.fleetPlace){window.fleetPlace(hp,a,360);return}
 var w=Math.min(360,innerWidth-24);hp.style.width=w+'px';hp.style.left=Math.max(12,Math.round((innerWidth-w)/2))+'px';hp.style.top=Math.max(12,Math.round(innerHeight/4))+'px';hp.style.right='auto';hp.style.bottom='auto'}
function hClose(){if(hp&&!hp.hidden)hp.hidden=true}
function locked(md){return !!((md||rmode()).pair&&(md||rmode()).pair.lock)}
function hOpen(tg,anchor){var md=rmode();if(md.busy||tg===worker()||locked(md))return;
 ['cxQClose','cxPopClose','cxMenuClose'].forEach(function(f){try{typeof window[f]==='function'&&window[f]()}catch(_){}});qClose();sClose();pClose();
 if(hp&&!hp.hidden&&hAnchor===anchor&&hTarget===tg){hClose();return}
 if(!hp){hp=document.createElement('div');hp.className='cxpop rm-hconf';hp.setAttribute('role','dialog');hp.setAttribute('aria-label','Передача работы');hp.hidden=true;hp.innerHTML='<div class="cxpbody"></div>';document.body.appendChild(hp);
  hp.addEventListener('click',function(e){if(e.target.closest('.rm-hno'))hClose();else if(e.target.closest('.rm-hyes'))hGo()});
  document.addEventListener('pointerdown',function(e){if(hp&&!hp.hidden&&!hp.contains(e.target)&&!e.target.closest('.rm-hand,.rm-act'))hClose()});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&hp&&!hp.hidden)hClose()});
  addEventListener('resize',function(){if(hp&&!hp.hidden)hPlace()})}
 hTarget=tg;hAnchor=anchor||null;hForce=false;hPaint('');hp.hidden=false;hPlace();hPlace();var y=hp.querySelector('.rm-hyes');if(y)y.focus({preventScroll:true})}
function hGo(){var tg=hTarget,y=hp.querySelector('.rm-hyes');if(y)y.disabled=true;hMine=true;
 post('remote/handoff',{target:tg,reason:'по кнопке в панели',force:hForce}).then(function(j){
  if(j.ok&&j.started){hClose();try{var m=rmode();m.busy=true;m.to=tg;m.stage='начало';m.error=''}catch(e){}paintHand();sToast(j.message||'Передача началась');poll();return}
  if(j.ok){hClose();hMine=false;sToast(j.message||'Готово');return}
  if(j.answering&&!hForce){hForce=true;hPaint('Claude на PROD сейчас отвечает: ответ может оборваться.');hPlace();return}
  hClose();hMine=false;sToast('⚠ '+(j.message||'Не получилось'))
 }).catch(function(){hClose();hMine=false;sToast('⚠ Панель не ответила')})}
function handLabel(md){var w=(md||rmode()).worker||'dev';if(locked(md))return 'Передача закрыта: пара';return 'Передать работу в '+NM[w==='prod'?'dev':'prod']}
function toggleHand(){if(locked()){sToast(rmode().pair.message);return}var tg=worker()==='prod'?'dev':'prod';hOpen(tg,document.querySelector('.rm-hand[data-target="'+tg+'"]'))}
function ensureHand(){document.querySelectorAll('#fleetLiveRows .fleet-live-account').forEach(function(t){var tg=null;for(var k in TG)if(t.classList.contains(k)){tg=TG[k];break}
 if(!tg||t.querySelector(':scope>.rm-hand'))return;var b=document.createElement('button');b.type='button';b.className='rm-hand';b.dataset.target=tg;t.appendChild(b)})}
// Состояние кнопки передачи работы в tg: одно для кнопок плиток и для окон значков в шапке (текст, подсказка, доступность)
function handInfo(tg,md){md=md||rmode();var w=md.worker||'dev',busy=!!md.busy,to=md.to||'',m=mem(),bad=!!(m&&(!m.online||m.error)),lk=locked(md);
 var here=tg===w&&!busy,going=busy&&tg===to,off=tg==='prod'&&bad&&w!=='prod'&&!busy,lock=lk&&!here&&!busy;
 var txt=here?'Работа здесь':going?'Идёт: '+(md.stage||'…'):'Передать работу в '+NM[tg];
 var tt=here?'Сейчас работает '+NM[tg]:going?'Передача в '+NM[tg]+' идёт':busy?'Идёт передача работы':lock?md.pair.message:off?'PROD сейчас недоступен: '+status(m):'Передать работу в '+NM[tg]+': Telegram перейдёт к '+NM[tg]+', '+NM[w]+' остановится';
 return {here:here,going:going,off:off,lock:lock,busy:busy,txt:txt,tt:tt,dis:here||busy||off||lock}}
function paintHand(){var md=rmode(),w=md.worker||'dev',busy=!!md.busy;
 document.querySelectorAll('.rm-hand,.rm-act').forEach(function(b){var h=handInfo(b.dataset.target,md);
  if(b.textContent!==h.txt)b.textContent=h.txt;
  b.disabled=h.dis;b.classList.toggle('here',h.here);b.classList.toggle('go',h.going);b.classList.toggle('wait',busy&&!h.going);b.classList.toggle('lock',h.lock);
  if(b.title!==h.tt){b.title=h.tt;b.setAttribute('aria-label',h.tt)}});
 if(busy&&!pollT)poll();
 if(wasBusy&&!busy){try{typeof load==='function'&&load()}catch(e){}if(hMine){hMine=false;if(md.error)sToast('⚠ '+md.error);else sToast('Работа у '+NM[w])}
  if(pMine){pMine=false;if(md.error)sToast('⚠ '+md.error);else sToast(md.pair?'Включена пара: '+md.pair.name:'Пара снята')}}
 wasBusy=busy}
// Меню профиля на плитке PROD: Full / «Claude PROD → Codex» (Codex-оркестратор выбирается в колонке Codex общего окна). Пока пара включена, передача между местами закрыта.
var pp=null,pAnchor=null,pSel='',pForce=false,pMine=false,pBusy=false;
function pKind(){var d=rmode();return d.pair?d.pair.kind:''}
function pOpts(){var d=rmode(),k=pKind(),on=!!d.active;
 return [k==='codex_prod'?{id:'off',name:'Снять пару · Codex Full',desc:'Claude PROD остановится, Codex работает один. Telegram у Codex.'}
  :{id:'off',name:'PROD Full · самостоятельно',desc:!k&&!on?'Включается кнопкой «Передать работу в Claude PROD».':'Claude PROD работает один: планирует, выполняет и проверяет. Telegram у него.',cur:!k&&on,dis:!k},
  {id:'prod_codex',name:'Claude PROD → Codex',desc:'PROD планирует и проверяет, Codex выполняет шаги после твоего подтверждения. Telegram у PROD.',cur:k==='prod_codex'}]}
function pSteps(kind){var d=rmode(),k=pKind(),w=worker(),on=!!d.active,l=[];
 if(kind==='off')return k==='codex_prod'?['Claude PROD остановится','Codex продолжит работать один (Full)','Telegram у Codex','Claude DEV при этом не запускается']:['Codex перестанет быть исполнителем','Claude PROD продолжит работать один (Full)','Telegram остаётся у Claude PROD'];
 if(kind==='prod_codex'){
  if(on){if(k==='codex_prod')l.push('Claude PROD перезапустится: Telegram включится')}
  else{if(w==='dev')l.push('Claude DEV остановится');else l.push('передача идёт через Claude DEV: он ненадолго запустится');l.push('Claude PROD возьмёт работу (лимиты аккаунта друга)')}
  l.push('Claude PROD — оркестратор, Codex — исполнитель','Шаги Codex выполняются после твоего подтверждения','Telegram у Claude PROD');return l}
 return l}
function pPaint(note){if(!pp)return;var d=rmode(),nt=worker()==='notion',opts=pOpts();
 var body='<h3>Профиль Claude PROD</h3><p>Выбери, как работают Claude PROD и Codex.</p><div class="rm-popts" role="radiogroup" aria-label="Профиль Claude PROD">'
  +opts.map(function(o){var dis=o.dis||o.cur||nt;return '<button type="button" class="rm-popt'+(o.cur?' on':'')+(o.id===pSel?' sel':'')+'" role="radio" aria-checked="'+(o.cur||o.id===pSel)+'" data-kind="'+o.id+'"'+(dis?' disabled':'')+'><i></i><b>'+esc(o.name)+'</b><em>'+(o.cur?'Действующий':'')+'</em><span>'+esc(o.desc)+'</span></button>'}).join('')+'</div>';
 if(nt)body+='<p class="rm-hnote bad rm-hint">Сейчас включён профиль Notion AI: сначала передай работу в Claude или Codex.</p>';
 else if(pSel)body+='<ul>'+pSteps(pSel).map(function(x){return '<li>'+esc(x)+'</li>'}).join('')+'</ul>';
 if(note)body+='<p class="rm-hnote bad rm-hint">'+esc(note)+'</p>';
 else if(pSel&&pSel!=='off'&&!pKind())body+='<p class="rm-hnote rm-hint">Пока пара включена, передача работы между DEV и PROD закрыта. Занимает около минуты.</p>';
 else if(pSel)body+='<p class="rm-hnote rm-hint">Занимает около минуты.</p>';
 body+='<div class="rm-hbtns"><button type="button" class="rm-hno">Отмена</button><button type="button" class="rm-hyes"'+(pSel&&!pBusy?'':' disabled')+'>'+(pForce?'Всё равно применить':'Применить')+'</button></div>';
 pp.querySelector('.cxpbody').innerHTML=body}
function pPlace(){if(!pp)return;var a=pAnchor;
 if(a&&a.isConnected&&a.offsetParent!==null&&window.fleetPlace){window.fleetPlace(pp,a,380);return}
 var w=Math.min(380,innerWidth-24);pp.style.width=w+'px';pp.style.left=Math.max(12,Math.round((innerWidth-w)/2))+'px';pp.style.top=Math.max(12,Math.round(innerHeight/5))+'px';pp.style.right='auto';pp.style.bottom='auto'}
function pClose(){if(pp&&!pp.hidden){pp.hidden=true;if(pAnchor)pAnchor.setAttribute('aria-expanded','false')}}
function pOpen(anchor){var d=rmode();if(d.busy)return;
 ['cxQClose','cxPopClose','cxMenuClose'].forEach(function(f){try{typeof window[f]==='function'&&window[f]()}catch(_){}});hClose();qClose();sClose();
 if(pp&&!pp.hidden){pClose();return}
 if(!pp){pp=document.createElement('div');pp.className='cxpop rm-hconf rm-pair';pp.setAttribute('role','dialog');pp.setAttribute('aria-label','Профиль Claude PROD');pp.hidden=true;pp.innerHTML='<div class="cxpbody"></div>';document.body.appendChild(pp);
  pp.addEventListener('click',function(e){var o=e.target.closest('.rm-popt');
   if(o){if(o.disabled)return;pSel=o.dataset.kind;pForce=false;pPaint('');pPlace();var n=pp.querySelector('.rm-popt.sel');if(n)n.focus({preventScroll:true});return}
   if(e.target.closest('.rm-hno'))pClose();else if(e.target.closest('.rm-hyes'))pGo()});
  document.addEventListener('pointerdown',function(e){if(pp&&!pp.hidden&&!pp.contains(e.target)&&!e.target.closest('.rm-prof'))pClose()});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&pp&&!pp.hidden)pClose()});
  addEventListener('resize',function(){if(pp&&!pp.hidden)pPlace()})}
 pAnchor=anchor||null;pSel='';pForce=false;pBusy=false;pPaint('');pp.hidden=false;if(pAnchor)pAnchor.setAttribute('aria-expanded','true');pPlace();pPlace()}
function pGo(){var kind=pSel,was=pKind();if(!kind||pBusy)return;pBusy=true;var y=pp.querySelector('.rm-hyes');if(y)y.disabled=true;pMine=true;
 post('remote/pair',{kind:kind,reason:'по кнопке в панели',force:pForce}).then(function(j){pBusy=false;
  if(j.ok&&j.started){pClose();try{var m=rmode();m.busy=true;m.to=(kind==='off'&&was==='codex_prod')?'codex':'prod';m.stage='начало';m.error=''}catch(e){}paint();sToast(j.message||'Меняю пару');poll();return}
  if(j.ok){pClose();pMine=false;sToast(j.message||'Готово');return}
  if(j.answering&&!pForce){pForce=true;pPaint('Claude на PROD сейчас отвечает: ответ может оборваться.');pPlace();return}
  pClose();pMine=false;sToast('⚠ '+(j.message||'Не получилось'))
 }).catch(function(){pBusy=false;pClose();pMine=false;sToast('⚠ Панель не ответила')})}
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.rm-prof');if(!b||!tile||!tile.contains(b))return;e.stopPropagation();if(b.getAttribute('aria-disabled')==='true')return;pOpen(b)});
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.rm-hand,.rm-act');if(!b||b.disabled)return;e.stopPropagation();hOpen(b.dataset.target||'prod',b)});
// «Войти заново» на карточке Claude PROD: то же окно со ссылкой и кодом, что у обычных аккаунтов, но вход идёт на втором сервере
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.rm-relogin');if(!b||b.disabled)return;e.stopPropagation();if(typeof reloginAsk==='function')reloginAsk('prod',b,true)});
document.addEventListener('change',function(e){var c=e.target;if(c&&c.classList&&c.classList.contains('rm-auto')){var on=c.checked;c.checked=!on;window.fleetAsk(c,(on?'Включить':'Выключить')+' автопередачу работы на PROD при лимитах?',on?'Включить':'Выключить').then(function(ok){if(!ok)return;c.checked=on;c.disabled=true;setAuto(on).then(function(){c.disabled=false}).catch(function(){c.checked=!on;c.disabled=false})})}});
// для шапки (cc_notion_ai): состояние и переключение передачи
function autoState(){var s=null;try{s=typeof lastSnap!=='undefined'?lastSnap:null}catch(e){}return s&&s.remote_mode&&s.remote_mode.auto||{}}
function setAuto(on){return post('remote/auto',{enabled:!!on}).then(function(j){try{if(lastSnap&&lastSnap.remote_mode&&j.auto)lastSnap.remote_mode.auto=j.auto}catch(e){}paint();try{window.naiReload&&window.naiReload()}catch(e){}return j})}
window.fleetRemote={mode:rmode,toggle:toggleHand,label:handLabel,handInfo:handInfo,hand:hOpen,auto:autoState,setAuto:setAuto,model:function(){var m=mem();return m?{id:m.model||'',name:modelName(m.model),effort:m.effort||''}:null},account:mem};
function row(label,win,week){var p=pct(win),t=when(win,week);
 return '<div class="row" data-fleet-tone="'+tone(p)+'"><div class="lbl"><span>'+label+'</span><b style="color:'+color(p)+'">'+(p==null?'—':p+'%')+'</b><span title="'+esc(t)+'">'+esc(t)+'</span></div><div class="bar"><div class="fill" data-t="'+(p==null?'ok':p>=99?'bad':p>=85?'warn':'ok')+'" style="width:'+(p==null?0:Math.min(100,p))+'%"></div></div></div>'}
var SVG_TERM='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="4" width="19" height="16" rx="4"></rect><path d="M7 9.5l3 2.5-3 2.5"></path><path d="M12.5 15h4.5"></path></svg>';
var SVG_MOD='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M17 7h3M4 17h3M11 17h9"></path><circle cx="15" cy="7" r="2"></circle><circle cx="9" cy="17" r="2"></circle></svg>';
var SVG_CAR='<svg class="cxcar" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"></path></svg>';
var SVG_SWAP='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h14l-3.5-3.5M20 16H6l3.5 3.5"></path></svg>';
function meter(kind){return '<div class="fleet-live-meter" data-window="'+kind+'"><div class="fleet-live-meter-label"><span>'+(kind==='session'?'5 часов':'Неделя')+'</span><b>—</b><span class="fleet-live-reset">Время не получено</span></div><span class="fleet-live-track" aria-hidden="true"><span class="fleet-live-fill"></span></span></div>'}
function gearIcon(){var g=$i('gear'),s=g&&g.querySelector('svg');return s?s.outerHTML:'⚙'}
// ближайшая годовщина оформления подписки (раз в месяц): «Подписка до» у PROD считается так же, как у локальных плиток
function nextRenewal(iso){if(!iso)return'';var d=new Date(iso);if(isNaN(d))return'';var now=Date.now(),k=0,t;
 do{k++;var y=d.getFullYear(),mo=d.getMonth()+k,last=new Date(y,mo+1,0).getDate();
  t=new Date(y,mo,Math.min(d.getDate(),last),d.getHours(),d.getMinutes(),d.getSeconds())}while(t.getTime()<=now&&k<1200);
 return t.toISOString()}
function buildStrip(){
 if(tile)return true;var rows=$i('fleetLiveRows'),sum=$i('fleetActiveSummary');if(!rows||!sum)return false;
 compact=document.createElement('span');compact.className='fleet-compact-account prod';compact.dataset.engine='prod';
 compact.innerHTML='<strong class="fleet-compact-name">Claude PROD</strong><span class="fleet-compact-warning"></span>'
  +'<span class="fleet-compact-model"><span class="fleet-compact-label">Модель</span><b class="rm-cmodel">—</b></span>'
  +'<span class="fleet-compact-effort"><span class="fleet-compact-label">Effort</span><b class="rm-ceffort">—</b></span>'
  +'<span class="fleet-compact-window" data-window="session"><span class="fleet-compact-label">5ч</span><b class="fleet-compact-used">—</b><span class="fleet-compact-range">Время не получено</span></span>'
  +'<span class="fleet-compact-window" data-window="week"><span class="fleet-compact-label">Неделя</span><b class="fleet-compact-used">—</b><span class="fleet-compact-range">Время не получено</span></span>';
 sum.appendChild(compact);
 tile=document.createElement('article');tile.className='fleet-live-account prod';tile.id='fleetProd';tile.dataset.engine='prod';tile.dataset.provider='prod';
 tile.innerHTML='<a class="fleet-live-identity" href="#cards"><strong class="fleet-live-name">Claude PROD</strong><span class="fleet-live-email"></span></a>'
  +'<div class="mirror-profile-footer"><div class="mirror-profile-holder"><button type="button" class="hdrgear cxbtn mirror-profile-button rm-prof" aria-haspopup="dialog" aria-expanded="false">'+SVG_TERM+'<i class="cxdot"></i><span class="cxbtnname">PROD Full · самостоятельно</span><span class="cxlim"></span>'+SVG_CAR+'</button></div>'
  +'<div class="fleet-provider-controls"><button type="button" class="hdrgear cxmodbtn fleet-model-tile rm-model" aria-haspopup="dialog" aria-expanded="false">'+SVG_MOD+'<span class="cxmodn">—</span><span class="cxmode"></span></button>'
  +'<button type="button" class="hdrgear fleet-provider-gear rm-gear" title="Настройки PROD" aria-label="Настройки PROD" aria-haspopup="dialog" aria-expanded="false">'+gearIcon()+'</button></div>'
  +meter('session')+meter('week')+'</div>';
 rows.appendChild(tile);return true}
function paintStrip(m){
 if(!buildStrip())return;var wins=[m&&m.five_hour,m&&m.seven_day],st=m?status(m):'нет данных';
 var name='Claude PROD',mail=m&&m.email||'',mname=m?modelName(m.model):'—',eff=m&&m.effort||'—';
 compact.dataset.state=m&&m.online&&!m.error?'ready':'warning';compact.dataset.online=m&&m.online?'1':'0';
 compact.querySelector('.fleet-compact-name').title=name+(mail?' · '+mail:'')+(m&&m.plan?' · '+m.plan.toUpperCase():'');
 compact.querySelector('.rm-cmodel').textContent=mname;compact.querySelector('.rm-ceffort').textContent=eff;
 var cwn=compact.querySelector('.fleet-compact-warning');cwn.textContent=m&&(!m.online||m.error)?st:'';cwn.title=m?statusHint(m):'';
 var cw=compact.querySelectorAll('.fleet-compact-window'),lim=tile.querySelector('.cxlim'),lims='';
 wins.forEach(function(w,i){var p=pct(w);cw[i].dataset.tone=tone(p);cw[i].querySelector('.fleet-compact-used').textContent=p==null?'—':p+'%';cw[i].querySelector('.fleet-compact-range').textContent=(i===0&&w&&w.resets_at&&!isNaN(new Date(w.resets_at)))?(new Date(w.resets_at)>new Date()?clk(new Date(w.resets_at)):'сброс'):when(w,i===1);
  var mt=tile.querySelectorAll('.fleet-live-meter')[i];mt.dataset.tone=tone(p);mt.querySelector('b').textContent=p==null?'—':p+'%';mt.querySelector('.fleet-live-fill').style.width=(p==null?0:Math.min(100,p))+'%';mt.querySelector('.fleet-live-reset').textContent=when(w,i===1);
  lims+='<span class="cxl'+(p!=null&&p>=99?' bad':p!=null&&p>=85?' warn':'')+'" style="--p:'+(p==null?0:p)+'"><i>'+(i?'нед':'5ч')+'</i><b>'+(p==null?'—':p+'%')+'</b></span>'});
 lim.innerHTML=lims;
 tile.querySelector('.fleet-live-name').textContent=name;tile.querySelector('.fleet-live-email').textContent=(mail||'почта не получена')+(m&&m.plan?' · '+m.plan.toUpperCase():'');
 var dot=tile.querySelector('.cxdot');dot.classList.toggle('err',!!(m&&(!m.online||m.error)));
 var mn=tile.querySelector('.rm-model');mn.querySelector('.cxmodn').textContent=mname;mn.querySelector('.cxmode').textContent=m&&m.effort||'';
 var tt='Модель Claude на PROD: '+mname+(m&&m.effort?' · '+m.effort:'')+'. Нажми, чтобы сменить.';mn.title=tt;mn.setAttribute('aria-label',tt);
 var md=rmode(),pb=tile.querySelector('.rm-prof'),pn=md.pair?md.pair.name:'PROD Full · самостоятельно',pt=md.busy?'Идёт операция: профиль сменить нельзя.':md.pair?'Профиль PROD: '+pn+'. Нажми, чтобы сменить или снять пару.':'Профиль PROD: Full — самостоятельно. Нажми, чтобы включить пару с Codex.';
 var pl=pb.querySelector('.cxbtnname');if(pl.textContent!==pn)pl.textContent=pn;pb.title=pt;pb.setAttribute('aria-label',pt);if(md.busy)pb.setAttribute('aria-disabled','true');else pb.removeAttribute('aria-disabled');
 tile.dataset.state=compact.dataset.state}
function paintCard(m){
 var box=$i('cards');if(!box)return;var old=box.querySelector('.fleet-remote-card');
 if(!m){if(old){old.remove();if(window.fleetClaudeCount)window.fleetClaudeCount()}return}
 var md=rmode(),sig=JSON.stringify([autoState().enabled,m.email,m.plan,m.model,m.effort,m.five_hour,m.seven_day,m.subscription_since,m.login_expires,m.online,m.error,md.active,md.worker,md.to,md.busy,md.stage,md.error,md.pair&&md.pair.kind,md.tg,Math.floor(Date.now()/60000)]);
 if(old&&old.dataset.sig===sig)return;
 var el=document.createElement('div');el.className='card fleet-remote-card';el.dataset.sig=sig;el.dataset.remote=m.id;
 var st=status(m),bad=st!=='онлайн';
 el.innerHTML='<div class="top"><div class="fleet-identity"><div class="fleet-titleline"><strong class="fleet-account-name" title="Claude PROD">Claude PROD</strong>'+(m.plan?'<span class="tag plan">'+esc(m.plan.toUpperCase())+'</span>':'')+'</div><span class="email" title="'+esc(m.email||'')+'">'+esc(m.email||'почта не получена')+'</span></div></div>'
  +'<span class="fleet-card-state'+(bad&&!md.active?' off':' active')+'" title="'+esc(statusHint(m))+'">'+esc(md.active?'Работает здесь':st.charAt(0).toUpperCase()+st.slice(1))+'</span>'
  +row('Сессия 5ч',m.five_hour,false)+row('Неделя',m.seven_day,true)
  +'<label class="fleet-card-auto" title="Когда лимит заканчивается у аккаунта, где идёт работа, она сама переключается на другой (DEV ↔ PROD). Вручную переключённая работа остаётся там, куда её переключили. Codex и агент Notion переключаются вручную."><input type="checkbox" class="rm-auto"'+(autoState().enabled?' checked':'')+'> <span>Автопередача при лимитах</span></label>'
  +'<div class="fleet-card-footer"><span class="fleet-card-caption">'+esc(md.error||(md.pair?md.pair.name:md.active?'Telegram у Claude на PROD':bad?(m.error==='token_expired'?'Токен устарел: войди заново':'Проверь сервер PROD'):'Claude на сервере PROD · токен остаётся там'))+'</span>'
  +'<button type="button" class="btn-relogin fleet-footer-relogin rm-relogin" title="Новый вход в Claude на сервере PROD: ссылка и код, токен останется там">\ud83d\udd11 Войти заново</button>'
  +'</div>';   // кнопки «Передать работу» в этой карточке нет: она живёт в плитке «Активные аккаунты»
 try{var top=el.querySelector('.top');if(top&&window.fleetClaudeDates){var dbox=document.createElement('div');dbox.className='fleet-card-dates';
  window.fleetClaudeDates({renewal_next:nextRenewal(m.subscription_since),login_expires:m.login_expires,plan:m.plan}).forEach(function(x){dbox.appendChild(x)});top.after(dbox)}}catch(e){}
 if(old)old.replaceWith(el);else box.appendChild(el);
 if(window.fleetClaudeCount)window.fleetClaudeCount()}
var hadTab=null;
// выбор модели и effort Claude на PROD: записывается в настройки там и применяется в запущенной сессии
var qp=null,mdata=null,qnote='',qbad=false,qjob=false;
function curModel(){var m=mem();return m?{id:m.model||'',effort:m.effort||''}:{id:'',effort:''}}
function qPaint(){if(!qp)return;var cur=curModel(),list=mdata&&mdata.models||[],sel=list.filter(function(x){return x.id===cur.id})[0],effs=sel?sel.efforts:[];
 var h='<div class="cxqh">Модель Claude на PROD</div><div class="cxqlist" role="radiogroup" aria-label="Модель Claude на PROD">';
 h+=list.length?list.map(function(x){var on=x.id===cur.id;return '<button type="button" class="cxqm'+(on?' on':'')+'" role="radio" aria-checked="'+on+'" data-model="'+esc(x.id)+'"'+(qjob?' disabled':'')+'><i class="cxqr"></i><span>'+esc(x.name)+'</span></button>'}).join(''):'<p class="cxqnote">'+(mdata?'Список моделей пуст.':'Читаю список моделей…')+'</p>';
 h+='</div><div class="cxqh">Уровень рассуждений (effort)</div><div class="cxqeff" role="radiogroup" aria-label="Effort Claude на PROD">';
 h+=effs.length?effs.map(function(e){return '<button type="button" class="cxqe'+(e===cur.effort?' on':'')+'" role="radio" aria-checked="'+(e===cur.effort)+'" data-effort="'+esc(e)+'"'+(qjob?' disabled':'')+'>'+esc(e)+'</button>'}).join(''):'<span class="cxsub">Эта модель не принимает effort.</span>';
 h+='</div><p class="cxqnote'+(qbad?' bad':'')+'">'+esc(qnote||'Выбор записывается на сервере PROD и действует в Claude на PROD.')+'</p>';
 qp.querySelector('.cxpbody').innerHTML=h}
function qPlace(){var t=tile&&tile.querySelector('.rm-model');if(!t||!qp)return;if(window.fleetPlace)return window.fleetPlace(qp,t,340);var r=t.getBoundingClientRect(),w=Math.min(340,innerWidth-24),top=Math.min(r.bottom+8,Math.max(12,innerHeight-260));
 qp.style.width=w+'px';qp.style.top=Math.round(top)+'px';qp.style.left=Math.max(12,Math.min(Math.round(r.right-w),innerWidth-w-12))+'px';qp.style.right='auto';qp.style.bottom='auto';qp.style.maxHeight=Math.max(160,innerHeight-top-12)+'px'}
function qClose(){if(qp&&!qp.hidden){qp.hidden=true;var t=tile&&tile.querySelector('.rm-model');if(t)t.setAttribute('aria-expanded','false')}}
function qOpen(){['cxQClose','cxPopClose','cxMenuClose'].forEach(function(f){try{typeof window[f]==='function'&&window[f]()}catch(_){}});sClose();pClose();
 if(!qp){qp=document.createElement('div');qp.className='cxpop cxquick fleet-quick-panel rm-quick';qp.setAttribute('role','dialog');qp.setAttribute('aria-label','Модель и effort Claude на PROD');qp.hidden=true;qp.innerHTML='<div class="cxpbody"></div>';document.body.appendChild(qp);
  qp.addEventListener('click',function(e){var m=e.target.closest('[data-model]'),f=e.target.closest('[data-effort]');if(qjob)return;var c=curModel();
   if(m&&m.dataset.model!==c.id)window.fleetAsk(m,'Переключить Claude на PROD на модель «'+m.dataset.model+'»?','Переключить').then(function(ok){if(ok)qPick({model:m.dataset.model},'Переключаю модель…')});else if(f&&f.dataset.effort!==c.effort)window.fleetAsk(f,'Поставить effort «'+f.dataset.effort+'» для Claude на PROD?','Поставить').then(function(ok){if(ok)qPick({effort:f.dataset.effort},'Ставлю effort «'+f.dataset.effort+'»…')})});
  document.addEventListener('pointerdown',function(e){if(qp&&!qp.hidden&&!qp.contains(e.target)&&!e.target.closest('.rm-model'))qClose()});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&qp&&!qp.hidden)qClose()});
  addEventListener('resize',function(){if(qp&&!qp.hidden)qPlace()})}
 qp.hidden=false;tile.querySelector('.rm-model').setAttribute('aria-expanded','true');qPlace();qPaint();
 if(!mdata)fetch(base+'remote/models',{headers:{'X-CC-Token':tok},cache:'no-store'}).then(function(r){return r.json()}).then(function(j){if(j&&j.ok){mdata=j;qPaint();qPlace()}}).catch(function(){})}
function qPick(body,text){qjob=true;qnote=text;qbad=false;qPaint();
 post('remote/model',body).then(function(j){qbad=!j.ok;qnote=j.message||(j.ok?'Готово':'Не получилось');return fetch(base+'remote',{headers:{'X-CC-Token':tok},cache:'no-store'}).then(function(r){return r.json()}).then(function(s){try{if(lastSnap&&s.limits)lastSnap.remote=s.limits}catch(e){}})}).catch(function(){qbad=true;qnote='Панель не ответила'}).then(function(){qjob=false;paint();qPaint();qPlace()})}
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.rm-model');if(!b||!tile||!tile.contains(b))return;e.stopPropagation();if(qp&&!qp.hidden)qClose();else qOpen()});
// Окно «Настройки PROD» (настроек у PROD должно быть столько же, сколько у Claude DEV).
// Тот же вид и размещение, те же группы: 1) переключение и лимиты, 2) модели в быстром меню. Пороги и пул моделей общие с Claude DEV:
// PROD берётся в работу по тем же порогам (cc_avail.availability), а быстрое меню PROD показывает те же отмеченные модели.
// «Аккаунты и копии» не переносятся: аккаунт второго сервера один, его вход здесь не копируется.
var sp=null,spBtn=null,spMoved=false;
function thrNow(){var t=90,c=99;try{if(typeof THR!=='undefined')t=THR;if(typeof WCAP!=='undefined')c=WCAP}catch(e){}return {t:t,c:c}}
function sBuild(){
 var x=$i('cxPopX');sp=document.createElement('div');sp.className='cxpop fleet-settings-panel rm-settings';sp.setAttribute('role','dialog');sp.setAttribute('aria-label','Настройки PROD');sp.hidden=true;
 sp.innerHTML='<div class="cxphead"><h3>Настройки PROD</h3><button type="button" class="hdrgear fleet-panel-close rm-sclose" aria-label="Закрыть настройки">'+(x?x.innerHTML:'×')+'</button></div>'
  +'<div class="cxpbody"><section class="fleet-settings-group"><div class="fleet-settings-group-title">Переключение и лимиты</div>'
  +'<div class="fleet-cx-options"><label>Сессия, % <input class="rm-thr" type="number" min="50" max="99"></label><label>Неделя, % <input class="rm-cap" type="number" min="50" max="100"></label><button type="button" class="rm-ssave">Сохранить</button></div>'
  +'<div class="fleet-catalog-note fleet-limit-hint">Пороги общие с Claude DEV: PROD берётся в работу, пока окно 5 часов и неделя ниже них. Сессия — с какого % окна 5 часов аккаунт считается занятым. Неделя — потолок недели.</div>'
  +'<label class="fleet-card-auto" title="Если переключаться некуда, Claude останавливается на недельном потолке и не расходует остаток."><input type="checkbox" class="rm-wk"><span>Пауза на недельном потолке: остановить Claude на пороге недели, если переключаться некуда</span></label>'
  +'<label class="fleet-card-auto" title="Когда лимит заканчивается у аккаунта, где идёт работа, она сама переключается на другой (DEV ↔ PROD)."><input type="checkbox" class="rm-auto"><span>Автопередача: когда лимит заканчивается у аккаунта, где идёт работа, она сама переключается на другой</span></label>'
  +'<div class="fleet-catalog-note">Codex и агент Notion переключаются вручную.</div></section>'
  +'<section class="fleet-settings-group"><div class="fleet-settings-group-title">Модели в быстром меню</div><div class="fleet-catalog-note">Отмеченные модели показываются в быстром меню Claude и PROD; список общий. Применяется сразу.</div><div class="rm-smbox"></div></section></div>';
 document.body.appendChild(sp);
 sp.addEventListener('click',function(e){
  if(e.target.closest('.rm-sclose')){sClose();return}
  var b=e.target.closest('.rm-ssave');if(!b)return;
  var t=Math.round(Number(sp.querySelector('.rm-thr').value)),c=Math.round(Number(sp.querySelector('.rm-cap').value));
  if(!(t>=50&&t<=99)||!(c>=50&&c<=100)){sToast('⚠ Сессия — от 50 до 99 %, неделя — от 50 до 100 %');return}
  b.disabled=true;
  post('config',{threshold:t,weekly_cap:c}).then(function(j){
   if(j&&j.error){sToast('⚠ '+j.error);return}
   try{THR=t;WCAP=c}catch(e){}try{typeof renderAutoLbl==='function'&&renderAutoLbl()}catch(e){}
   sToast('Пороги сохранены: сессия '+t+' %, неделя '+c+' %');try{typeof load==='function'&&load()}catch(e){}
  }).catch(function(){sToast('⚠ Панель не ответила')}).then(function(){b.disabled=false})});
 addEventListener('resize',function(){if(sp&&!sp.hidden)sPlace()});
 document.addEventListener('pointerdown',function(e){if(sp&&!sp.hidden&&!sp.contains(e.target)&&!e.target.closest('.rm-gear'))sClose()});
 document.addEventListener('keydown',function(e){if(e.key==='Escape'&&sp&&!sp.hidden)sClose()})}
document.addEventListener('change',function(e){var c=e.target;if(!c||!c.classList||!c.classList.contains('rm-wk'))return;c.disabled=true;
 post('config',{weekly_pause:c.checked}).then(function(j){if(j&&j.error)throw new Error(j.error);try{if(lastSnap&&lastSnap.config)lastSnap.config.weekly_pause=c.checked}catch(e){}sToast(c.checked?'Пауза на недельном потолке включена':'Пауза на недельном потолке выключена')})
  .catch(function(){c.checked=!c.checked;sToast('⚠ Не сохранилось')}).then(function(){c.disabled=false})});
function sPlace(){if(!sp||!spBtn)return;if(window.fleetPlace)return window.fleetPlace(sp,spBtn,580)}
function sSync(){if(!sp)return;var a=sp.querySelector('.rm-auto'),w=sp.querySelector('.rm-wk'),on=false;if(a&&document.activeElement!==a)a.checked=!!autoState().enabled;
 try{on=!!(lastSnap&&lastSnap.config&&lastSnap.config.weekly_pause)}catch(e){}if(w&&document.activeElement!==w)w.checked=on}
function sOpen(){
 ['cxQClose','cxPopClose','cxMenuClose'].forEach(function(f){try{typeof window[f]==='function'&&window[f]()}catch(_){}});qClose();pClose();
 if(!sp)sBuild();
 var th=thrNow();sp.querySelector('.rm-thr').value=th.t;sp.querySelector('.rm-cap').value=th.c;sSync();
 // «Модели в быстром меню»: на время открытия сюда переезжают настоящие узлы из окна Claude (пул, подсказка, «Проверить новые модели»), по закрытии возвращаются на место
 var box=sp.querySelector('.rm-smbox'),nodes=[$i('poolList'),$i('checkNew')].filter(Boolean);
 if(box&&nodes.length){box.append.apply(box,nodes);spMoved=true}
 sp.hidden=false;spBtn.setAttribute('aria-expanded','true');sPlace();sPlace()}
function sClose(){if(!sp||sp.hidden)return;sp.hidden=true;if(spBtn)spBtn.setAttribute('aria-expanded','false');
 if(spMoved){var g=$i('fleetClaudeModels');if(g)[$i('poolList'),$i('checkNew')].forEach(function(n){if(n)g.append(n)});spMoved=false}
 mdata=null}
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.rm-gear');if(!b||!tile||!tile.contains(b))return;e.stopPropagation();spBtn=b;if(sp&&!sp.hidden)sClose();else sOpen()});
function paint(){var m=mem();paintStrip(m);paintCard(m);ensureHand();paintHand();sSync();if(pp&&!pp.hidden&&rmode().busy&&!pBusy)pClose();var has=!!m;if(has!==hadTab){hadTab=has;try{typeof consTabs==='function'&&consTabs()}catch(e){}}}
try{var prev=renderCards;renderCards=function(d){prev(d);try{paint()}catch(e){}}}catch(e){}
setInterval(function(){if(!document.hidden)try{paint()}catch(e){}},15000);
(function wait(n){if(buildStrip()){paint();try{new MutationObserver(function(){if(hRaf)return;hRaf=requestAnimationFrame(function(){hRaf=0;ensureHand();paintHand()})}).observe($i('fleetLiveRows'),{childList:true,subtree:true})}catch(e){}}else if(n<40)setTimeout(function(){wait(n+1)},250)})(0);
}catch(e){console.warn('remote',e)}})();
"""


def inject(page):
    return page.replace('</head>', '<style id="fleetRemoteStyle">' + CSS + '</style></head>', 1).replace(
        '</body>', '<script id="fleetRemoteScript">' + JS + '</script></body>', 1)
