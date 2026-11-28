"""Frontend CSS + JS plugin injecting Antigravity (agy) into cc-fleet Web UI."""

CSS = r"""
:root{--fleet-agy:#8b9cf7;--fleet-agy-soft:#232844}
.fleet-console-toolbar #ctAgy::before{background:var(--fleet-agy)}
.tpmd[data-m="agy"]{background:var(--fleet-agy)}
.dchip.dx.agy .ddot{background:var(--fleet-agy)}
.fleet-live-account.agy,.fleet-compact-account.agy{--live-accent:var(--fleet-agy)}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc[data-engine="agy"]{grid-column:1/-1}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.agy{--cses:128px}
.fleet-live-account[data-provider="agy"]{border-color:color-mix(in srgb,var(--fleet-agy) 38%,var(--fleet-line));background:linear-gradient(120deg,var(--fleet-agy-soft),var(--card) 60%)}
.fleet-live-account[data-provider="agy"] .mirror-profile-button{border-color:color-mix(in srgb,var(--fleet-agy) 40%,var(--fleet-line))}
.fleet-live-account.agy .mirror-profile-button .cxdot{background:var(--fleet-agy)}
.fleet-live-account.agy .mirror-profile-button .cxdot.off{background:var(--fleet-muted)}
.fleet-live-account.agy .mirror-profile-button .cxdot.err{background:var(--warn)}
.fleet-compact-account.agy .fleet-compact-name::before{background:var(--fleet-agy)}
html:root:root #fleetActiveAccounts .fleet-live-account.agy .mirror-profile-footer .fleet-provider-controls{flex:0 1 255px;width:auto;max-width:265px;min-width:0}
html:root:root #fleetActiveAccounts .fleet-live-account.agy .fleet-provider-controls .fleet-model-tile{max-width:none}
html:root:root #fleetActiveAccounts .fleet-live-account.agy .fleet-provider-controls .cxmodn{max-width:150px}
@media(max-width:900px){
 html:root:root #fleetActiveAccounts .fleet-live-account.agy .mirror-profile-footer .fleet-provider-controls{flex:1 1 calc(50% - 5px);width:auto;max-width:none}
}
@media(max-width:640px){
 html:root:root:root #fleetActiveAccounts .fleet-live-account.agy{grid-template-columns:minmax(0,1fr);grid-template-areas:"identity" "profile"}
 html:root:root #fleetActiveAccounts .fleet-live-account.agy .mirror-profile-footer{flex-wrap:wrap;gap:10px}
 html:root:root #fleetActiveAccounts .fleet-live-account.agy .mirror-profile-holder,
 html:root:root #fleetActiveAccounts .fleet-live-account.agy .mirror-profile-footer .fleet-provider-controls{flex:1 1 100%;max-width:none;width:100%}
 html:root:root #fleetActiveAccounts .fleet-live-account.agy .mirror-profile-footer .fleet-live-meter,
 html:root:root #fleetActiveAccounts .fleet-live-account.agy .mirror-profile-footer .fleet-live-meter[data-window="week"]{flex:1 1 calc(50% - 5px);min-width:130px}
}
.fleet-provider.agy{background:var(--fleet-agy-soft);color:var(--fleet-agy)}
.fleet-provider.agy svg{width:15px;height:15px;display:block}
html:root:root #fleetAgy .card.active{border-color:color-mix(in srgb,var(--fleet-agy) 56%,var(--fleet-line));background:linear-gradient(120deg,var(--fleet-agy-soft),var(--card) 68%)}
html:root:root #fleetAgy .card.active.fleet-paused{border-color:var(--fleet-line);background:var(--card)}
html:root:root #fleetAgy .card>.row .fill{background:var(--fleet-agy)!important}
html:root:root #fleetAgy .card>.row[data-fleet-tone="warn"] .fill{background:var(--warn)!important}
html:root:root #fleetAgy .card>.row[data-fleet-tone="bad"] .fill{background:var(--bad)!important}
html:root:root.ag-live-agy #fleetActiveAccounts .fleet-compact-account.agy{box-shadow:inset 0 0 0 1px #49d6aa}
html:root:root:root.ag-live-agy #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.agy{box-shadow:inset 0 0 0 1px #49d6aa}
html:root:root.ag-live-agy #fleetActiveAccounts .fleet-live-account.agy{border-color:#49d6aa}
html:root:root.ag-pause-agy .fleet-live-account.agy .fleet-live-name::before,
html:root:root.ag-pause-agy .fleet-live-account.agy .cxdot,
html:root:root.ag-pause-agy .fleet-compact-account.agy .fleet-compact-name::before,
html:root:root.ag-pause-agy .fleet-console-toolbar #ctAgy::before{
 --pz:var(--fleet-agy,#8b9cf7);width:7px!important;height:8px!important;border:0!important;border-radius:1px!important;box-shadow:none!important;animation:none!important;
 background:linear-gradient(90deg,var(--pz) 0 2.4px,transparent 2.4px 4.6px,var(--pz) 4.6px 7px)!important
}
.agy-form{display:grid;gap:10px}
.agy-row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.agy-field{display:grid;gap:4px;font-size:12px;color:var(--fleet-muted)}
.agy-field input,.agy-field select{height:34px;padding:0 10px;border-radius:7px;border:1px solid var(--fleet-line);background:var(--bg);color:var(--txt);font:inherit;font-size:12px;box-sizing:border-box;width:100%}
.agy-field input:focus{outline:1px solid var(--fleet-agy);border-color:var(--fleet-agy)}
.agy-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
.agy-btn{height:32px;padding:0 12px;border-radius:7px;border:1px solid var(--fleet-line);background:var(--bg);color:var(--txt);font:inherit;font-size:12px;font-weight:600;cursor:pointer}
.agy-btn:hover{border-color:var(--fleet-agy)}
.agy-btn.prim{border-color:var(--fleet-agy);background:color-mix(in srgb,var(--fleet-agy) 22%,var(--bg))}
.agy-btn.danger{border-color:rgba(239,150,158,.45);color:var(--bad)}
.agy-sec{padding:10px 0;border-top:1px solid var(--fleet-line)}
.agy-sec:first-child{border-top:0;padding-top:0}
.agy-sec h4{margin:0 0 8px;font-size:13px;color:var(--txt)}
.agy-msg{font-size:12px;color:var(--fleet-muted);margin-top:6px;line-height:1.45}
.agy-chk{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--txt);cursor:pointer}
.agy-chk input{accent-color:var(--fleet-agy);width:15px;height:15px}
.agy-card-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;align-items:stretch}
@media(max-width:900px){.agy-card-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:640px){.agy-card-grid{grid-template-columns:1fr}}
.agy-prof-card{padding:10px 12px;border-radius:8px;border:1px solid color-mix(in srgb,var(--fleet-agy) 55%,var(--fleet-line));background:color-mix(in srgb,var(--fleet-agy) 10%,var(--bg));margin-bottom:10px}
.agy-prof-head{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:13px;font-weight:600;color:var(--txt)}
.agy-prof-badge{font-size:11px;font-weight:600;color:var(--fleet-agy)}
.agy-prof-desc{margin:5px 0 0;font-size:12px;line-height:1.45;color:var(--fleet-muted)}
.agy-prof-meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;font-size:11px;color:var(--fleet-muted)}
.agy-prof-meta span{padding:2px 6px;border-radius:5px;border:1px solid var(--fleet-line);background:var(--bg)}
#agyInst{border-color:color-mix(in srgb,var(--fleet-agy) 45%,var(--fleet-line));color:var(--txt)}
#agyInst svg{color:var(--fleet-agy)}
.agy-log{max-height:140px;overflow:auto;margin:8px 0;padding:8px 10px;border-radius:7px;border:1px solid var(--fleet-line);background:var(--fleet-terminal,#0a0e14);color:#c7d3e3;font:11px/1.45 ui-monospace,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.agy-url-box{display:flex;gap:6px;align-items:center;margin:8px 0}
.agy-url-link{flex:1;display:inline-flex;align-items:center;justify-content:center;gap:6px;height:34px;padding:0 12px;border-radius:7px;border:1px solid var(--fleet-agy);background:color-mix(in srgb,var(--fleet-agy) 20%,var(--bg));color:var(--txt);text-decoration:none;font-size:12px;font-weight:600}
.agy-url-link:hover{background:color-mix(in srgb,var(--fleet-agy) 30%,var(--bg))}
"""

JS = r"""
// [agy] Antigravity (agy) independent 3rd executor: console tab, overview tile, account card, pause/override banner, modals.
(function(){try{
var base=(typeof API!=='undefined'?API:location.origin+'/cc-hook/'),tok=(typeof TOKEN!=='undefined'?TOKEN:'');
var agySnap=null,agyLim=null,agyBr=null,agyWrap=null,agyModalsBound=false;
var WD=new Intl.DateTimeFormat('ru',{weekday:'short',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:window.FLEET_TZ});
var CK=new Intl.DateTimeFormat('ru',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:window.FLEET_TZ});
var DY=new Intl.DateTimeFormat('ru',{day:'2-digit',month:'2-digit',timeZone:window.FLEET_TZ});

var SVG_AGY='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 19.5L12 4.5L19 19.5"/><path d="M7.8 14.2C9.8 11.8 14.2 11.8 16.2 14.2"/><circle cx="12" cy="4.5" r="1.4" fill="currentColor" stroke="none"/></svg>';
var SVG_MOD='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M17 7h3M4 17h3M11 17h9"></path><circle cx="15" cy="7" r="2"></circle><circle cx="9" cy="17" r="2"></circle></svg>';
var SVG_CAR='<svg class="cxcar" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"></path></svg>';
var SVG_GEAR='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>';

function $i(id){return document.getElementById(id)}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function apiGet(p){return fetch(base+p,{headers:{'X-CC-Token':tok},cache:'no-store'}).then(function(r){return r.json()})}
function apiPost(p,b){return fetch(base+p,{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':tok},body:JSON.stringify(b||{})}).then(function(r){return r.json()})}
function sToast(t){try{typeof toast==='function'&&toast(t)}catch(e){}}
function clk(d){var dy=DY.format(d),ck=CK.format(d);return dy===DY.format(new Date())?ck:dy+' '+ck}
function fmtReset(iso,week){
 if(!iso)return 'Доступно';
 var d=new Date(iso);if(isNaN(d))return 'Время не получено';
 if(week)return WD.format(d).replace(/,/g,'');
 var m=Math.ceil((d.getTime()-Date.now())/60000);
 if(m<=0)return 'сброс ожидается';
 var h=Math.floor(m/60),r=m%60;
 return clk(d)+' · через '+(h?h+' ч'+(r?' ':''):'')+(r?r+' мин':'');
}
function fmtCompactReset(iso,week){
 if(!iso)return 'Доступно';
 var d=new Date(iso);if(isNaN(d))return 'Время не получено';
 if(week)return WD.format(d).replace(/,/g,'');
 return d.getTime()>Date.now()?clk(d):'сброс';
}
function fmtTs(ts){
 if(!ts)return '';
 var d=new Date(ts*1000);
 return WD.format(d).replace(/,/g,'');
}
function fmtSub(raw){
 if(!raw)return null;
 var m=/^(\d{4})-(\d{2})-(\d{2})/.exec(String(raw));if(!m)return null;
 var d=new Date(+m[1],+m[2]-1,+m[3]),today=new Date();today.setHours(0,0,0,0);
 var days=Math.round((d-today)/86400000);
 var dd=String(d.getDate()).padStart(2,'0')+'.'+String(d.getMonth()+1).padStart(2,'0');
 var abs=Math.abs(days),rem=abs%10,w=(abs%100>=11&&abs%100<=19)?'дней':rem===1?'день':(rem>=2&&rem<=4)?'дня':'дней';
 return {text:days<0?('истекла '+dd):(dd+' · '+days+' '+w),tone:days<=2?'urgent':days<=7?'warn':'normal'};
}
function pctVal(win){return win&&isFinite(win.pct)?Math.round(win.pct*10)/10:null}
function pctStr(p){return p==null?'—':(Math.abs(p-Math.round(p))<0.05?Math.round(p)+'%':p.toFixed(1)+'%')}
function pctTone(p){return p==null?'unknown':p>=99?'bad':p>=85?'warn':'normal'}
function pctColor(p){return p==null?'var(--txt)':p>=99?'var(--bad)':p>=85?'var(--warn)':'var(--ok)'}
function fmtTok(n){n=+n||0;return n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e3?(n/1e3).toFixed(1)+'K':String(n)}
function shortModel(raw){
 if(!raw)return 'По умолчанию';
 var s=String(raw).trim();
 var map={
  'gemini-4-neon-high':'Gemini 4 Neon',
  'gemini-4-neon-medium':'Gemini 4 Neon',
  'gemini-4-neon-low':'Gemini 4 Neon',
  'gemini-4-carbon-high':'Gemini 4 Carbon',
  'gemini-4-carbon-medium':'Gemini 4 Carbon',
  'gemini-4-hydrogen-high':'Gemini 4 Hydrogen',
  'gemini-pro-orchestrator-neon':'Orchestrator Neon'
 };
 if(map[s.toLowerCase()])return map[s.toLowerCase()];
 return s.replace(/\s*\((high|medium|low|xhigh)\)\s*$/i,'').trim()||s;
}
function gearIcon(){var g=$i('gear'),s=g&&g.querySelector('svg');return s?s.outerHTML:SVG_GEAR}

window.agyAvail=function(){
 if(!agySnap)return localStorage.getItem('cc_has_agy')==='1';
 return !!agySnap.available;
};
window.agyConsCmd=async function(cmd,anchor){
 if(cmd==='compact'&&window.fleetAsk&&!await window.fleetAsk(anchor||$i('ctCompact'),'Сжать контекст Antigravity (/compact)?','Да'))return;
 if(cmd==='new'&&!confirm('Начать новую сессию Antigravity?'))return;
 try{
  var r=await apiPost('agy/console/cmd',{cmd:cmd});
  sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);
  if(r.ok&&typeof tickAll==='function')tickAll();
 }catch(e){sToast('⚠ '+e);}
};
window.agyConsStart=async function(P){
 try{
  var r=await apiPost('agy/console/start',{});
  sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);
  if(typeof ccConsole==='function'&&P)ccConsole(P);
  loadAll(false);
 }catch(e){sToast('⚠ '+e);}
};

// Wire Antigravity tab (#ctAgy) and console wrappers cleanly without mutating cc_limits.py JS strings
(function hookConsole(){
 var ctabs=$i('cTabs'),ctCodex=$i('ctCodex');
 if(ctabs&&ctCodex&&!$i('ctAgy')){
  var b=document.createElement('button');
  b.type='button';b.className='iconbtn ctab';b.id='ctAgy';
  b.setAttribute('role','tab');b.setAttribute('aria-selected','false');
  b.dataset.s='agy';b.hidden=true;b.textContent='Antigravity';
  ctCodex.insertAdjacentElement('afterend',b);
 }
 try{if(localStorage.getItem('cc_contab')==='agy'&&typeof CONS!=='undefined')CONS='agy';}catch(e){}
 if(typeof window.isKey==='function'){
  var _isKey=window.isKey;
  window.isKey=function(k){return k==='agy'||_isKey(k);};
 }
 if(typeof window.baseCur==='function'){
  var _baseCur=window.baseCur;
  window.baseCur=function(){
   if(typeof CONS!=='undefined'&&CONS==='agy'&&window.agyAvail())return 'agy';
   return _baseCur();
  };
 }
 if(typeof window.splitKeysAvail==='function'){
  var _splitKeys=window.splitKeysAvail;
  window.splitKeysAvail=function(){
   var ks=_splitKeys().slice();
   if(window.agyAvail()&&ks.indexOf('agy')<0)ks.push('agy');
   return ks;
  };
 }
 if(typeof window.consQuery==='function'){
  var _consQuery=window.consQuery;
  window.consQuery=function(s,P){return s==='agy'?'&s=agy':_consQuery(s,P);};
 }
 if(typeof window.ctActsSync==='function'){
  var _ctActsSync=window.ctActsSync;
  window.ctActsSync=function(){
   _ctActsSync();
   if(typeof consCur==='function'&&consCur()==='agy'){
    if($i('ctCompact'))$i('ctCompact').hidden=false;
    if($i('ctNew'))$i('ctNew').hidden=false;
    if($i('ctRedraw'))$i('ctRedraw').hidden=true;
    if($i('cTabs'))$i('cTabs').classList.add('cacts');
    var tw=document.querySelector('.termwrap');if(tw)tw.classList.add('hascacts');
   }
  };
 }
 if(typeof window.fitPane==='function'){
  var _fitPane=window.fitPane;
  window.fitPane=function(P){
   if(P&&P.k==='agy'&&P.box&&P.box.closest('.termwrap.tsplit')){
    P.box.classList.add('tcwrap');
    if(P.box.style.getPropertyValue('--pz'))P.box.style.removeProperty('--pz');
    return;
   }
   return _fitPane(P);
  };
 }
 if(typeof window.consTabs==='function'){
  var _consTabs=window.consTabs;
  window.consTabs=function(){
   _consTabs();
   var agv=window.agyAvail(),cur=typeof consCur==='function'?consCur():'claude';
   var ks=(typeof splitEff==='function'?splitEff():null)||[];
   var agBtn=$i('ctAgy');
   if(agBtn){
    var on=cur==='agy';
    agBtn.hidden=!agv;
    agBtn.classList.toggle('on',on);
    agBtn.classList.toggle('tshown',!on&&ks.indexOf('agy')>=0);
    agBtn.setAttribute('aria-selected',String(on));
    agBtn.draggable=!!(typeof splitMq!=='undefined'&&splitMq.matches&&agv);
   }
   if(agv){
    if($i('cTabs'))$i('cTabs').hidden=false;
    var tw=document.querySelector('.termwrap');if(tw)tw.classList.add('hastabs');
   }
   var stopBtn=document.querySelector('#fleetConsoleForm [data-console-key=stop]');
   if(stopBtn&&cur==='agy')stopBtn.hidden=false;
   syncAgyArrows(cur==='agy');
  };
 }
 function syncAgyArrows(show){
  var form=$i('fleetConsoleForm');if(!form)return;
  var downBtn=form.querySelector('[data-console-key=down]');
  if(!downBtn)return;
  var lr=$i('agyKeyLeft');
  if(!lr){
   var bL=document.createElement('button');bL.type='button';bL.id='agyKeyLeft';bL.className='fleet-key fk-arrow';bL.textContent='←';bL.title='Стрелка влево (Antigravity)';bL.hidden=true;
   var bR=document.createElement('button');bR.type='button';bR.id='agyKeyRight';bR.className='fleet-key fk-arrow';bR.textContent='→';bR.title='Стрелка вправо (Antigravity)';bR.hidden=true;
   downBtn.insertAdjacentElement('afterend',bR);
   downBtn.insertAdjacentElement('afterend',bL);
   bL.addEventListener('click',async function(e){e.preventDefault();var r=await apiPost('agy/console/key',{key:'left'});if(!r.ok)sToast('⚠ '+r.message);});
   bR.addEventListener('click',async function(e){e.preventDefault();var r=await apiPost('agy/console/key',{key:'right'});if(!r.ok)sToast('⚠ '+r.message);});
   lr=bL;
  }
  $i('agyKeyLeft').hidden=!show;
  $i('agyKeyRight').hidden=!show;
 }
 if(typeof window.ccConsole==='function'){
  var _ccConsole=window.ccConsole;
  window.ccConsole=async function(P){
   if(!P||P.k!=='agy')return _ccConsole(P);
   var box=P.box,dot=dotOf(P),requestSeq=++P.seq;
   if(typeof ctActsSync==='function')ctActsSync();
   try{
    var r=await fetch(base+'console?token='+tok+'&s=agy');var d=await r.json();
    if(P.k!=='agy'||requestSeq<P.applied)return;
    P.applied=requestSeq;
    if(!d.ok){dot.className='termdot err';return;}
    dot.className='termdot';
    if(d.running){if(d.started!==P.cxRun){P.cxRun=d.started;ccConsoleHistory(P);}}
    else P.cxRun=null;
    idleUi(P,d,dot,d.quota_paused?'Antigravity на паузе по лимитам.':'Консоль Antigravity не запущена.','Antigravity',d.running?null:{id:'agy',label:'Запустить',disabled:false});
    var atBottom=box.scrollTop+box.clientHeight>=box.scrollHeight-20;
    P.cur.innerHTML=typeof fitSep==='function'?fitSep(d.current||'',box):(d.current||'');
    if(typeof fitPane==='function')fitPane(P);
    box.classList.toggle('termempty',!P.idle.hidden&&!P.cur.textContent.trim()&&!P.hist.textContent.trim());
    if(atBottom)box.scrollTop=box.scrollHeight;
   }catch(e){dot.className='termdot err';}
  };
 }
 if(typeof window.paneGo==='function'){
  var _paneGo=window.paneGo;
  window.paneGo=async function(P){
   if(P&&P.idleGo&&P.idleGo.dataset.go==='agy'){return window.agyConsStart(P);}
   return _paneGo(P);
  };
 }
 if(typeof window.consActCmd==='function'){
  var _consActCmd=window.consActCmd;
  window.consActCmd=function(cmd,anchor){
   if(typeof consCur==='function'&&consCur()==='agy')return window.agyConsCmd(cmd,anchor);
   return _consActCmd(cmd,anchor);
  };
 }
})();

// Popovers
var agyInstPoll=0;
function closeAgyPopovers(except){
 ['agyQ','agyPop','agyProfPop','agyInstPop'].forEach(function(id){
  if(id===except)return;
  var el=$i(id);if(el)el.hidden=true;
 });
 if(except!=='agyInstPop'&&agyInstPoll){clearTimeout(agyInstPoll);agyInstPoll=0;}
 var pb=$i('agyProf');if(pb&&except!=='agyProfPop')pb.setAttribute('aria-expanded','false');
 var mb=$i('agyMod');if(mb&&except!=='agyQ')mb.setAttribute('aria-expanded','false');
 var gb=$i('agyGear');if(gb&&except!=='agyPop')gb.setAttribute('aria-expanded','false');
 var ib=$i('agyInst');if(ib&&except!=='agyInstPop')ib.setAttribute('aria-expanded','false');
}

function ensureInstButton(){
 var btn=$i('agyInst');
 if(btn)return btn;
 var ctl=document.querySelector('.hdr .hdrctl');
 if(!ctl)return null;
 btn=document.createElement('button');
 btn.id='agyInst';btn.type='button';btn.className='hdrgear cxinst';
 btn.setAttribute('aria-haspopup','dialog');btn.setAttribute('aria-expanded','false');
 btn.hidden=true;
 btn.innerHTML=SVG_AGY+'<span class="cxinstn">Antigravity</span><span class="cxinstp" aria-hidden="true">+</span>';
 var cxInst=$i('cxInst');
 if(cxInst&&cxInst.parentNode===ctl)cxInst.insertAdjacentElement('afterend',btn);
 else ctl.appendChild(btn);
 btn.addEventListener('click',function(e){e.stopPropagation();openInstallWizard(btn);});
 return btn;
}

function syncInstButton(){
 var btn=ensureInstButton();
 if(!btn)return;
 var avail=!!(agySnap&&agySnap.available);
 var acc=(agySnap&&agySnap.accounts&&agySnap.accounts[0])||{};
 var needLogin=!!(avail&&acc.login_required);
 btn.hidden=avail&&!needLogin;
 btn.title=!avail?'Установить Antigravity CLI и подключить Google':'Войти в аккаунт Google для Antigravity';
}

function ensureModals(){
 if(!$i('agyQ')){
  var q=document.createElement('div');
  q.id='agyQ';q.className='cxpop cxquick fleet-quick-panel';q.hidden=true;q.setAttribute('role','dialog');q.setAttribute('aria-label','Модель и effort Antigravity');
  q.innerHTML='<div class="cxpbody" id="agyQb"></div>';
  document.body.appendChild(q);
 }
 if(!$i('agyProfPop')){
  var pp=document.createElement('div');
  pp.id='agyProfPop';pp.className='cxpop cxquick fleet-quick-panel';pp.hidden=true;pp.setAttribute('role','dialog');pp.setAttribute('aria-label','Режим Antigravity');
  pp.innerHTML='<div class="cxpbody" id="agyProfBody"></div>';
  document.body.appendChild(pp);
 }
 if(!$i('agyInstPop')){
  var ip=document.createElement('div');
  ip.id='agyInstPop';ip.className='cxpop cxinstpop fleet-settings-panel';ip.hidden=true;ip.setAttribute('role','dialog');ip.setAttribute('aria-label','Установка и вход Antigravity');
  ip.innerHTML='<div class="cxphead"><b>Antigravity — подключение</b><span class="cxsub" id="agyInstSt"></span><button type="button" class="hdrgear" id="agyInstX" style="margin:0" aria-label="×"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div><div class="cxpbody" id="agyInstBody"></div>';
  document.body.appendChild(ip);
  $i('agyInstX').addEventListener('click',function(){closeAgyPopovers();});
 }
 if(!$i('agyPop')){
  var p=document.createElement('div');
  p.id='agyPop';p.className='cxpop fleet-settings-panel';p.hidden=true;p.setAttribute('role','dialog');p.setAttribute('aria-label','Настройки Antigravity');
  p.innerHTML='<div class="cxphead"><b>Antigravity</b><span class="cxsub" id="agyPopSt"></span><button type="button" class="hdrgear" id="agyPopX" style="margin:0" aria-label="×"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div><div class="cxpbody" id="agyPopBody"></div>';
  document.body.appendChild(p);
  $i('agyPopX').addEventListener('click',function(){closeAgyPopovers();});
 }
 if(!agyModalsBound){
  agyModalsBound=true;
  document.addEventListener('click',function(e){
   var q=$i('agyQ');if(q&&!q.hidden&&!e.target.closest('#agyQ')&&!e.target.closest('#agyMod')){q.hidden=true;if($i('agyMod'))$i('agyMod').setAttribute('aria-expanded','false');}
   var pp=$i('agyProfPop');if(pp&&!pp.hidden&&!e.target.closest('#agyProfPop')&&!e.target.closest('#agyProf')){pp.hidden=true;if($i('agyProf'))$i('agyProf').setAttribute('aria-expanded','false');}
   var ip=$i('agyInstPop');if(ip&&!ip.hidden&&!e.target.closest('#agyInstPop')&&!e.target.closest('#agyInst')&&!e.target.closest('#agyReloginBtn')){ip.hidden=true;if(agyInstPoll){clearTimeout(agyInstPoll);agyInstPoll=0;}if($i('agyInst'))$i('agyInst').setAttribute('aria-expanded','false');}
   var p=$i('agyPop');if(p&&!p.hidden&&!e.target.closest('#agyPop')&&!e.target.closest('#agyGear')&&!e.target.closest('[data-agy-gear]')){p.hidden=true;if($i('agyGear'))$i('agyGear').setAttribute('aria-expanded','false');}
  });
  document.addEventListener('keydown',function(e){if(e.key==='Escape')closeAgyPopovers();});
 }
}

async function paintInstallWizard(anchor,forceLogin){
 var ip=$i('agyInstPop'),b=$i('agyInstBody'),st=$i('agyInstSt');
 if(!ip||ip.hidden)return;
 var res=await Promise.all([apiGet('agy/install'),apiGet('agy/login')]);
 var ins=res[0]||{},lg=res[1]||{};
 var installed=!!ins.installed;
 st.textContent=!installed?'шаг 1 из 2 · установка CLI':(lg.signed_in&&!forceLogin&&lg.state==='idle')?'подключено':'шаг 2 из 2 · вход Google';
 var h='';
 if(!installed){
  h+='<div class="agy-sec"><h4>Шаг 1. Установка Antigravity CLI (agy)</h4>'
   +'<div class="agy-msg">Скачивает официальный бинарник Google Antigravity CLI в <code>/root/.local/bin/agy</code>. Автоматически настраивает полный доступ (<code>always-proceed</code>), пропуск первичного мастера и правила оформления/картинок (<code>GEMINI.md</code>).</div>';
  if(ins.message)h+='<div class="agy-msg" style="color:'+(ins.state==='error'?'var(--warn)':'var(--txt)')+'">'+esc(ins.message)+'</div>';
  if(ins.log&&ins.log.length)h+='<pre class="agy-log">'+esc(ins.log.join('\n'))+'</pre>';
  h+='<div class="agy-actions">'
   +(ins.state==='running'
    ?'<button type="button" class="agy-btn danger" id="agyInstCancel">Отменить</button>'
    :'<button type="button" class="agy-btn prim" id="agyInstGo">Установить Antigravity CLI</button>')
   +'</div></div>';
 }else{
  h+='<div class="agy-sec"><h4>'+(forceLogin?'Вход в аккаунт Google (Antigravity)':'Шаг 2. Вход в Google-аккаунт')+'</h4>'
   +'<div class="agy-msg">CLI установлен (<code>'+esc(ins.bin||'agy')+'</code>). Нажмите кнопку ниже — панель получит OAuth-ссылку Google, которую можно открыть с любого устройства.</div>';
  if(lg.message)h+='<div class="agy-msg" style="color:'+(lg.state==='error'?'var(--warn)':lg.state==='done'?'var(--ok)':'var(--txt)')+'">'+esc(lg.message)+'</div>';
  if(lg.url){
   h+='<div class="agy-url-box"><a class="agy-url-link" href="'+esc(lg.url)+'" target="_blank" rel="noopener noreferrer">Открыть ссылку входа Google ↗</a>'
    +'<button type="button" class="agy-btn" id="agyCopyUrl">Копировать</button></div>'
    +'<div class="agy-form"><label class="agy-field">Вставьте код авторизации из браузера<input id="agyAuthCode" type="text" placeholder="4/0A..." autocomplete="off"></label>'
    +'<div class="agy-actions"><button type="button" class="agy-btn prim" id="agySendCode">Подтвердить код</button>'
    +'<button type="button" class="agy-btn" id="agyLoginCancel">Отмена</button></div></div>';
  }else if(lg.state==='starting'||lg.state==='verifying'){
   h+='<div class="agy-actions"><button type="button" class="agy-btn" id="agyLoginCancel">Отмена</button></div>';
  }else if(lg.state==='done'){
   h+='<div class="agy-actions"><button type="button" class="agy-btn prim" id="agyLoginDone">Готово</button></div>';
  }else{
   h+='<div class="agy-actions"><button type="button" class="agy-btn prim" id="agyLoginGo">Получить ссылку для входа в Google</button></div>';
  }
  h+='</div>';
 }
 var prevCode=$i('agyAuthCode')?$i('agyAuthCode').value:'';
 b.innerHTML=h;
 if(prevCode&&$i('agyAuthCode'))$i('agyAuthCode').value=prevCode;

 if($i('agyInstGo'))$i('agyInstGo').onclick=async function(){
  var r=await apiPost('agy/install/start',{});
  sToast(r.ok?'🛠 '+r.message:'⚠ '+r.message);
  paintInstallWizard(anchor,forceLogin);
 };
 if($i('agyInstCancel'))$i('agyInstCancel').onclick=async function(){
  await apiPost('agy/install/cancel',{});
  paintInstallWizard(anchor,forceLogin);
 };
 if($i('agyLoginGo'))$i('agyLoginGo').onclick=async function(){
  var r=await apiPost('agy/login/start',{});
  sToast(r.ok?'🔑 '+r.message:'⚠ '+r.message);
  paintInstallWizard(anchor,true);
 };
 if($i('agyCopyUrl'))$i('agyCopyUrl').onclick=function(){
  try{navigator.clipboard.writeText(lg.url);sToast('✅ Ссылка скопирована');}catch(e){sToast('⚠ Не удалось скопировать');}
 };
 if($i('agySendCode'))$i('agySendCode').onclick=async function(){
  var code=($i('agyAuthCode')&&$i('agyAuthCode').value||'').trim();
  if(!code){sToast('⚠ Вставьте код авторизации');return;}
  var r=await apiPost('agy/login/submit',{code:code});
  sToast(r.ok?'⏳ '+r.message:'⚠ '+r.message);
  paintInstallWizard(anchor,true);
 };
 if($i('agyLoginCancel'))$i('agyLoginCancel').onclick=async function(){
  await apiPost('agy/login/cancel',{});
  paintInstallWizard(anchor,forceLogin);
 };
 if($i('agyLoginDone'))$i('agyLoginDone').onclick=async function(){
  closeAgyPopovers();
  await loadAll(true);
 };
 if(window.fleetPlace&&anchor)window.fleetPlace(ip,anchor,430);
 if(agyInstPoll){clearTimeout(agyInstPoll);agyInstPoll=0;}
 if(ins.state==='running'||lg.state==='starting'||lg.state==='verifying'){
  agyInstPoll=setTimeout(function(){paintInstallWizard(anchor,forceLogin);},1500);
 }else if(lg.state==='done'){
  loadAll(true);
 }
}

function openInstallWizard(anchor,forceLogin){
 ensureModals();
 var ip=$i('agyInstPop');
 if(!ip.hidden&&!forceLogin){closeAgyPopovers();return;}
 closeAgyPopovers('agyInstPop');
 ['cxQClose','cxPopClose','cxMenuClose'].forEach(function(f){try{typeof window[f]==='function'&&window[f]()}catch(_){}});
 ip.hidden=false;
 if(anchor&&anchor.id==='agyInst')anchor.setAttribute('aria-expanded','true');
 paintInstallWizard(anchor||$i('agyInst')||$i('agyGear'),!!forceLogin);
}

function openProfilePop(anchor){
 ensureModals();
 var pp=$i('agyProfPop'),b=$i('agyProfBody');
 if(!pp.hidden){closeAgyPopovers();return;}
 closeAgyPopovers('agyProfPop');
 ['cxQClose','cxPopClose','cxMenuClose'].forEach(function(f){try{typeof window[f]==='function'&&window[f]()}catch(_){}});
 var acc=(agySnap&&agySnap.accounts&&agySnap.accounts[0])||{};
 var rt=(agySnap&&agySnap.runtime)||{};
 var ctx=(agySnap&&agySnap.context)||{};
 var lim=agyLim||{};
 var br=(agyBr&&agyBr.bridge)||{};
 var paused=!!(lim.limit_pause&&lim.limit_pause.active);
 var stTxt=paused?'на паузе по лимитам':rt.running?'консоль работает':'консоль остановлена';
 b.innerHTML='<div class="cxqh"><b>Профиль Antigravity</b></div>'
  +'<div class="agy-prof-card">'
  +'<div class="agy-prof-head"><span>Antigravity Full · самостоятельный</span><span class="agy-prof-badge">Действующий</span></div>'
  +'<p class="agy-prof-desc">Независимый 3-й исполнитель (root). Работает параллельно с Claude и Codex, со своей консолью, Telegram-мостом и автопаузой по лимитам.</p>'
  +'<div class="agy-prof-meta">'
  +'<span>Статус: '+esc(stTxt)+'</span>'
  +'<span>Пороги: '+(lim.threshold||90)+'% / '+(lim.weekly_cap||99)+'%</span>'
  +(ctx.context_tokens?'<span>Контекст: '+esc(fmtTok(ctx.context_tokens))+'</span>':'')
  +(br.running?'<span>Telegram: онлайн</span>':'')
  +'</div></div>'
  +'<div class="agy-actions">'
  +'<button type="button" class="agy-btn prim" id="agyGoCons">Открыть консоль</button>'
  +(rt.running?'<button type="button" class="agy-btn" id="agyPStop">⏹ Остановить</button>':'<button type="button" class="agy-btn" id="agyPStart">▶ Запустить</button>')
  +'<button type="button" class="agy-btn" id="agyPSet">⚙ Настройки</button>'
  +'</div>';
 $i('agyGoCons').onclick=function(){
  closeAgyPopovers();
  var tab=$i('ctAgy');if(tab&&!tab.hidden)tab.click();
  var tw=document.querySelector('.termwrap');if(tw)tw.scrollIntoView({behavior:'smooth',block:'nearest'});
 };
 if($i('agyPStart'))$i('agyPStart').onclick=async function(){
  closeAgyPopovers();
  var r=await apiPost('agy/console/start',{});
  sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);
  loadAll(false);
 };
 if($i('agyPStop'))$i('agyPStop').onclick=async function(){
  closeAgyPopovers();
  var r=await apiPost('agy/console/stop',{});
  sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);
  loadAll(false);
 };
 $i('agyPSet').onclick=function(){closeAgyPopovers();openSettings($i('agyGear')||anchor);};
 pp.hidden=false;
 if(anchor)anchor.setAttribute('aria-expanded','true');
 if(window.fleetPlace&&anchor)window.fleetPlace(pp,anchor,360);
}

function openQuickModel(anchor){
 ensureModals();
 var q=$i('agyQ'),b=$i('agyQb');
 if(!q.hidden){closeAgyPopovers();return;}
 closeAgyPopovers('agyQ');
 ['cxQClose','cxPopClose','cxMenuClose'].forEach(function(f){try{typeof window[f]==='function'&&window[f]()}catch(_){}});
 var acc=(agySnap&&agySnap.accounts&&agySnap.accounts[0])||{};
 var rt=(agySnap&&agySnap.runtime)||{};
 var curM=(rt.model||acc.model||'');
 var curE=(rt.effort||acc.effort||'high');
 var rawModels=(acc.models&&acc.models.length)?acc.models.filter(function(m){return m&&m.id&&m.id.indexOf('gemini-')===0;}):[];
 var models=rawModels.length?rawModels:[
  {id:'gemini-4-neon-high',name:'Gemini 4 Neon'},
  {id:'gemini-4-carbon-high',name:'Gemini 4 Carbon'},
  {id:'gemini-4-hydrogen-high',name:'Gemini 4 Hydrogen'},
  {id:'gemini-pro-orchestrator-neon',name:'Orchestrator Neon'}
 ];
 var html='<div class="cxqh"><b>Модель Antigravity</b></div><div class="cxqlist">';
 models.forEach(function(m){
  var disp=shortModel(m.name||m.id);
  var on=(curM===m.id||shortModel(curM).toLowerCase()===disp.toLowerCase());
  html+='<button type="button" class="cxqm'+(on?' on':'')+'" data-m="'+esc(m.id)+'"><i class="cxqr"></i><span>'+esc(disp)+'</span></button>';
 });
 html+='<button type="button" class="cxqm'+(!curM?' on':'')+'" data-m="default"><i class="cxqr"></i><span>По умолчанию</span></button></div>';
 html+='<div class="cxqh" style="margin-top:10px"><b>Уровень рассуждений (effort)</b></div><div class="cxqeff">';
 ['low','medium','high','xhigh'].forEach(function(e){
  html+='<button type="button" class="cxqe'+(curE===e?' on':'')+'" data-e="'+e+'">'+e+'</button>';
 });
 html+='</div>';
 b.innerHTML=html;
 b.querySelectorAll('[data-m]').forEach(function(btn){
  btn.addEventListener('click',async function(){
   closeAgyPopovers();
   var r=await apiPost('agy/prefs',{model:btn.dataset.m});
   sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);
   loadAll(false);
  });
 });
 b.querySelectorAll('[data-e]').forEach(function(btn){
  btn.addEventListener('click',async function(){
   closeAgyPopovers();
   var r=await apiPost('agy/prefs',{effort:btn.dataset.e});
   sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);
   loadAll(false);
  });
 });
 q.hidden=false;
 if(anchor)anchor.setAttribute('aria-expanded','true');
 if(window.fleetPlace&&anchor)window.fleetPlace(q,anchor,300);
}

function openSettings(anchor){
 ensureModals();
 var p=$i('agyPop'),b=$i('agyPopBody'),st=$i('agyPopSt');
 if(!p.hidden){closeAgyPopovers();return;}
 closeAgyPopovers('agyPop');
 ['cxQClose','cxPopClose','cxMenuClose'].forEach(function(f){try{typeof window[f]==='function'&&window[f]()}catch(_){}});
 var acc=(agySnap&&agySnap.accounts&&agySnap.accounts[0])||{};
 var lim=agyLim||{};
 var br=(agyBr&&agyBr.bridge)||{};
 var rt=(agySnap&&agySnap.runtime)||{};
 st.textContent=rt.running?'консоль работает':'консоль остановлена';
 b.innerHTML=''
  +'<div class="agy-sec"><h4>Пороги лимитов и пауза</h4><div class="agy-form">'
  +'<div class="agy-row"><label class="agy-field">Сессия 5ч (%)<input id="agyThr" type="number" min="50" max="100" value="'+esc(lim.threshold||90)+'"></label>'
  +'<label class="agy-field">Неделя (оставить резерв, %)<input id="agyCap" type="number" min="50" max="100" value="'+esc(lim.weekly_cap||99)+'"></label></div>'
  +'<label class="agy-field">Подписка Google AI Pro до (ГГГГ-ММ-ДД или ДД.ММ.ГГГГ)<input id="agySub" type="text" placeholder="2026-12-28" value="'+esc(acc.sub_until||'')+'"></label>'
  +'<div class="agy-actions"><button type="button" class="agy-btn prim" id="agySaveLim">Сохранить лимиты и подписку</button></div>'
  +'</div></div>'
  +'<div class="agy-sec"><h4>Telegram-мост Antigravity</h4><div class="agy-form">'
  +'<label class="agy-chk"><input id="agyBrOn" type="checkbox"'+(br.enabled?' checked':'')+'>Включить Telegram-мост внутри балансера</label>'
  +'<div class="agy-row"><label class="agy-field">Chat ID<input id="agyBrCid" type="text" value="'+esc(br.chat_id||'')+'"></label>'
  +'<label class="agy-field">Рабочая папка<input id="agyBrWd" type="text" value="'+esc(br.workdir||'/root')+'"></label></div>'
  +'<label class="agy-field">Токен бота ('+(br.has_token?esc(br.token_hint):'не задан')+')<input id="agyBrTok" type="password" placeholder="Вставьте новый токен от @BotFather"></label>'
  +'<div class="agy-actions"><button type="button" class="agy-btn prim" id="agySaveBr">Сохранить мост</button>'
  +(br.has_token?'<button type="button" class="agy-btn danger" id="agyClrTok">Удалить токен</button>':'')
  +'</div>'
  +(br.bot&&br.bot.username?'<div class="agy-msg">Бот: @'+esc(br.bot.username)+' · '+(br.running?'работает':'выключен')+(br.queued?' · в очереди: '+br.queued:'')+'</div>':'')
  +(br.last_error?'<div class="agy-msg" style="color:var(--warn)">⚠ '+esc(br.last_error)+'</div>':'')
  +'</div></div>'
  +'<div class="agy-sec"><h4>Консоль Antigravity (cc-agy)</h4><div class="agy-actions">'
  +'<button type="button" class="agy-btn" id="agyStartBtn">▶ Запустить</button>'
  +'<button type="button" class="agy-btn" id="agyRestartBtn">🔄 Перезапустить</button>'
  +'<button type="button" class="agy-btn danger" id="agyStopBtn">⏹ Остановить</button>'
  +'<button type="button" class="agy-btn" id="agyRefLimBtn">📊 Обновить квоты</button>'
  +'<button type="button" class="agy-btn" id="agyBootstrapBtn">✨ Доступ и стиль</button>'
  +'<button type="button" class="agy-btn" id="agyReloginBtn">🔑 Войти заново (Google)</button>'
  +'</div></div>';

 $i('agySaveLim').onclick=async function(){
  var r1=await apiPost('agy/limits/config',{threshold:parseInt($i('agyThr').value,10),weekly_cap:parseInt($i('agyCap').value,10)});
  var r2=await apiPost('agy/prefs',{sub_until:$i('agySub').value.trim()});
  sToast((r1.ok&&r2.ok)?'✅ Сохранено':'⚠ '+(r1.ok?r2.message:r1.message));
  loadAll(false);
 };
 $i('agySaveBr').onclick=async function(){
  var tokVal=$i('agyBrTok').value.trim();
  if(tokVal){
   var rt=await apiPost('agy/bridge/token',{token:tokVal});
   if(!rt.ok){sToast('⚠ '+rt.message);return;}
  }
  var r=await apiPost('agy/bridge/save',{enabled:$i('agyBrOn').checked,chat_id:$i('agyBrCid').value.trim(),workdir:$i('agyBrWd').value.trim()});
  sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);
  loadAll(false);closeAgyPopovers();
 };
 if($i('agyClrTok'))$i('agyClrTok').onclick=async function(){
  var r=await apiPost('agy/bridge/token/clear',{});
  sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);
  loadAll(false);closeAgyPopovers();
 };
 $i('agyStartBtn').onclick=async function(){var r=await apiPost('agy/console/start',{});sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);loadAll(false);};
 $i('agyRestartBtn').onclick=async function(){var r=await apiPost('agy/console/restart',{});sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);loadAll(false);};
 $i('agyStopBtn').onclick=async function(){var r=await apiPost('agy/console/stop',{});sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);loadAll(false);};
 $i('agyRefLimBtn').onclick=async function(){sToast('🔄 Обновляю квоты Antigravity...');await loadAll(true);sToast('✅ Квоты обновлены');};
 $i('agyBootstrapBtn').onclick=async function(){var r=await apiPost('agy/bootstrap',{});sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);};
 $i('agyReloginBtn').onclick=function(e){e.stopPropagation();openInstallWizard($i('agyGear')||anchor,true);};

 p.hidden=false;
 if(anchor)anchor.setAttribute('aria-expanded','true');
 if(window.fleetPlace&&anchor)window.fleetPlace(p,anchor,420);
}

// Render #agyPause banner (100% hard limit + soft weekly/5h policy pause + "Отключить паузу" override!)
function renderPauseBanner(){
 var el=$i('agyPause');
 if(!el){
  var cxp=$i('cxPause');
  if(!cxp)return;
  el=document.createElement('div');
  el.id='agyPause';el.className='ccpause lvl-pause';el.hidden=true;
  cxp.insertAdjacentElement('afterend',el);
 }
 var n=agyLim&&agyLim.limit_notice;
 var p=agyLim&&agyLim.limit_pause;
 var active=n&&n.active;
 document.documentElement.classList.toggle('ag-pause-agy',!!(p&&p.active));
 if(!active){el.hidden=true;el.innerHTML='';return;}
 var isHard=!!n.hard;
 var isPaused=!!(p&&p.active);
 var isOver=!!n.override&&!isPaused;
 el.className='ccpause '+(isHard?'lvl-hard':isOver?'lvl-off':'lvl-pause');
 var wins=(n.window_names||[]).join(' и ')||'лимит';
 var until=n.resume_at?('до '+fmtTs(n.resume_at)):'до сброса окна';
 var title=isHard?('⚠ Лимит Antigravity <b>исчерпан (100%)</b> — '+wins+' '+until)
  :isOver?('▶ Пауза Antigravity <b>отключена вручную</b> — работа на остатке '+wins+' до 100%')
  :('⏸ Antigravity на <b>паузе по лимитам</b> ('+wins+' '+until+') — подъём автоматический');
 var sub=isHard?'Настоящий лимит аккаунта исчерпан — отключать паузу бесполезно. Очередь отправится автоматически после сброса окна.'
  :isOver?'Входящие сообщения идут сразу до реальных 100%. Пауза включится обратно автоматически после сброса окна или по кнопке.'
  :'Достигнут настроенный порог ('+(agyLim.threshold||90)+'% / '+(agyLim.weekly_cap||99)+'%). Новые сообщения копятся в очереди. Можно отключить паузу, чтобы доработать последние % недели/сессии.';
 var btn='';
 if(!isHard&&n.can_override!==false){
  btn=isOver
   ?'<button type="button" class="ccp-btn" id="agyPauseToggle" data-over="0">Включить паузу</button>'
   :'<button type="button" class="ccp-btn" id="agyPauseToggle" data-over="1">Отключить паузу (до 100%)</button>';
 }
 el.innerHTML='<details class="fleet-pause-fold" open><summary class="fleet-pause-summary"><span class="ccp-dot"></span><span>'+title+'</span>'+btn+'</summary><div class="fleet-pause-content"><p>'+esc(sub)+'</p></div></details>';
 el.hidden=false;
 var tbtn=$i('agyPauseToggle');
 if(tbtn){
  tbtn.onclick=async function(ev){
   ev.preventDefault();ev.stopPropagation();
   tbtn.disabled=true;
   var r=await apiPost('agy/limits/config',{pause_override:tbtn.dataset.over==='1'});
   sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);
   await loadAll(false);
  };
 }
}

function buildAccordionWrap(){
 var rows=$i('fleetLiveRows');
 if(!rows)return null;
 var wrap=rows.querySelector(':scope>.fleet-acc[data-engine="agy"]');
 if(wrap)return wrap;
 wrap=document.createElement('div');
 wrap.className='fleet-acc';wrap.dataset.engine='agy';
 var isOpen=false;
 try{var o=JSON.parse(localStorage.getItem('cc_acc_open')||'{}');isOpen=!!o.agy;}catch(e){}
 wrap.classList.toggle('open',isOpen);
 wrap.innerHTML=''
  +'<span class="fleet-compact-account agy" data-engine="agy" data-acc="1" role="button" tabindex="0" aria-expanded="'+String(isOpen)+'" aria-label="Развернуть: Antigravity">'
  +'<span class="fleet-compact-id"><strong class="fleet-compact-name">Antigravity</strong><span class="fleet-compact-prof"></span></span>'
  +'<span class="fleet-compact-warning"></span>'
  +'<span class="fleet-compact-model"><span class="fleet-compact-label">Модель</span><b class="agy-cmodel">—</b></span>'
  +'<span class="fleet-compact-effort"><span class="fleet-compact-label">Effort</span><b class="agy-ceffort">—</b></span>'
  +'<span class="fleet-compact-window" data-window="session"><span class="fleet-compact-label">5ч</span><b class="fleet-compact-used">—</b><span class="fleet-compact-range">Время не получено</span></span>'
  +'<span class="fleet-compact-window" data-window="week"><span class="fleet-compact-label">Неделя</span><b class="fleet-compact-used">—</b><span class="fleet-compact-range">Время не получено</span></span>'
  +'<span class="fleet-acc-chev" aria-hidden="true"></span>'
  +'</span>'
  +'<article class="fleet-live-account agy" id="fleetAgyTile" data-engine="agy" data-provider="agy">'
  +'<a class="fleet-live-identity" href="#fleetAgy" title="Свернуть строку" aria-expanded="'+String(isOpen)+'"><strong class="fleet-live-name">Antigravity</strong><span class="fleet-live-email" id="agyTileEmail"></span></a>'
  +'<div class="mirror-profile-footer">'
  +'<div class="mirror-profile-holder"><button type="button" class="hdrgear cxbtn mirror-profile-button" id="agyProf" aria-haspopup="dialog" aria-expanded="false">'+SVG_AGY+'<i class="cxdot" id="agyProfDot"></i><span class="cxbtnname" id="agyProfName">Antigravity · Full</span><span class="cxlim" id="agyProfLim"></span>'+SVG_CAR+'</button></div>'
  +'<div class="fleet-provider-controls">'
  +'<button type="button" class="hdrgear cxmodbtn fleet-model-tile" id="agyMod" aria-haspopup="dialog" aria-expanded="false">'+SVG_MOD+'<span class="cxmodn" id="agyModN">—</span><span class="cxmode" id="agyModE"></span></button>'
  +'<button type="button" class="hdrgear fleet-provider-gear" id="agyGear" title="Настройки Antigravity" aria-label="Настройки Antigravity" aria-haspopup="dialog" aria-expanded="false">'+gearIcon()+'</button>'
  +'</div>'
  +'<div class="fleet-live-meter" data-window="session"><div class="fleet-live-meter-label"><span>5 часов</span><b id="agyM5P">—</b><span class="fleet-live-reset" id="agyM5R"></span></div><span class="fleet-live-track" aria-hidden="true"><span class="fleet-live-fill" id="agyM5F"></span></span></div>'
  +'<div class="fleet-live-meter" data-window="week"><div class="fleet-live-meter-label"><span>Неделя</span><b id="agyM7P">—</b><span class="fleet-live-reset" id="agyM7R"></span></div><span class="fleet-live-track" aria-hidden="true"><span class="fleet-live-fill" id="agyM7F"></span></span></div>'
  +'</div>'
  +'</article>';
 rows.appendChild(wrap);
 $i('agyProf').addEventListener('click',function(e){e.stopPropagation();openProfilePop($i('agyProf'));});
 $i('agyMod').addEventListener('click',function(e){e.stopPropagation();openQuickModel($i('agyMod'));});
 $i('agyGear').addEventListener('click',function(e){e.stopPropagation();openSettings($i('agyGear'));});
 agyWrap=wrap;
 return wrap;
}

// Render tile in #fleetLiveRows and account section in #fleetAccountsFold
function renderTileAndCard(){
 var avail=agySnap&&agySnap.available;
 var paused=!!(agyLim&&agyLim.limit_pause&&agyLim.limit_pause.active);
 document.documentElement.classList.toggle('ag-live-agy',!!(avail&&agySnap.runtime&&agySnap.runtime.running&&!paused));

 if(!avail){
  if(agyWrap){agyWrap.remove();agyWrap=null;}
  var oldSec=$i('fleetAgy');if(oldSec)oldSec.remove();
  return;
 }

 var wrap=buildAccordionWrap();
 var acc=(agySnap.accounts&&agySnap.accounts[0])||{};
 var rt=agySnap.runtime||{};
 var ctx=agySnap.context||{};
 var wins={};(acc.windows||[]).forEach(function(w){wins[w.mins]=w;});
 var w5=wins[300]||null,w7=wins[10080]||null;
 var p5=pctVal(w5),p7=pctVal(w7);
 var r5=fmtReset(w5&&w5.resets_at,false),r7=fmtReset(w7&&w7.resets_at,true);
 var rc5=fmtCompactReset(w5&&w5.resets_at,false),rc7=fmtCompactReset(w7&&w7.resets_at,true);
 var modDisp=shortModel(rt.model||acc.model||'');
 var effName=rt.effort||acc.effort||'high';
 var sub=fmtSub(acc.sub_until);
 var emailTxt=acc.email||'почта не получена';
 var planTxt=(acc.plan_label||'PRO').toUpperCase();
 var profLabel='Antigravity · Full'+(paused?' (пауза)':rt.running?' (работает)':'');

 if(wrap){
  var compact=wrap.querySelector('.fleet-compact-account.agy');
  var nmEl=compact.querySelector('.fleet-compact-name');
  nmEl.title='Antigravity · '+emailTxt+' · '+planTxt;
  compact.querySelector('.fleet-compact-prof').textContent=profLabel;
  compact.querySelector('.agy-cmodel').textContent=modDisp;
  compact.querySelector('.agy-ceffort').textContent=effName;
  compact.querySelector('.fleet-compact-warning').textContent=acc.error?'проверить':'';
  var cw5=compact.querySelector('.fleet-compact-window[data-window="session"]');
  cw5.dataset.tone=pctTone(p5);
  cw5.querySelector('.fleet-compact-used').textContent=pctStr(p5);
  cw5.querySelector('.fleet-compact-range').textContent=rc5;
  var cw7=compact.querySelector('.fleet-compact-window[data-window="week"]');
  cw7.dataset.tone=pctTone(p7);
  cw7.querySelector('.fleet-compact-used').textContent=pctStr(p7);
  cw7.querySelector('.fleet-compact-range').textContent=rc7;

  var emailLine=emailTxt+' · '+planTxt+(sub?' · подписка до '+sub.text:'')+(ctx.context_tokens?' · контекст '+fmtTok(ctx.context_tokens):'');
  $i('agyTileEmail').textContent=emailLine;
  $i('agyProfName').textContent=profLabel;
  var pdot=$i('agyProfDot');
  pdot.classList.toggle('off',!rt.running&&!paused);
  pdot.classList.toggle('err',!!acc.error);
  $i('agyModN').textContent=modDisp;
  $i('agyModE').textContent=effName;
  $i('agyMod').title='Модель Antigravity: '+modDisp+' · '+effName+'. Нажми, чтобы сменить.';

  var m5=wrap.querySelector('.fleet-live-meter[data-window="session"]');
  m5.dataset.tone=pctTone(p5);
  $i('agyM5P').textContent=pctStr(p5);$i('agyM5P').style.color=pctColor(p5);
  $i('agyM5R').textContent=r5;
  $i('agyM5F').style.width=(p5==null?0:Math.min(100,p5))+'%';

  var m7=wrap.querySelector('.fleet-live-meter[data-window="week"]');
  m7.dataset.tone=pctTone(p7);
  $i('agyM7P').textContent=pctStr(p7);$i('agyM7P').style.color=pctColor(p7);
  $i('agyM7R').textContent=r7;
  $i('agyM7F').style.width=(p7==null?0:Math.min(100,p7))+'%';
 }

 // Lower account section inside #fleetAccountsFold (matches Claude & Codex heading & card markup)
 var fold=$i('fleetAccountsFold');
 if(fold){
  var sec=$i('fleetAgy');
  if(!sec){
   sec=document.createElement('section');sec.id='fleetAgy';sec.className='fleet-section';
   sec.innerHTML='<div class="fleet-section-head"><h2><span class="fleet-provider agy" aria-hidden="true">'+SVG_AGY+'</span>Antigravity</h2><span class="fleet-count">1 аккаунт</span><button type="button" class="hdrgear" data-agy-gear="1" title="Настройки Antigravity" aria-label="Настройки Antigravity" style="margin-left:auto">'+gearIcon()+'</button></div><div class="agy-card-grid" id="agyCards"></div>';
   fold.appendChild(sec);
   sec.querySelector('[data-agy-gear]').addEventListener('click',function(e){e.stopPropagation();openSettings(e.currentTarget);});
  }
  var stClass=paused?'paused':rt.running?'active':'';
  var stText=paused?'Пауза по лимитам':rt.running?'Работает здесь':'Консоль остановлена';
  var cardHtml='<div class="card active'+(paused?' fleet-paused':'')+'">'
   +'<div class="top"><div class="fleet-identity"><div class="fleet-titleline"><strong class="fleet-account-name">Antigravity</strong><span class="tag plan">'+esc(planTxt)+'</span></div><span class="email" title="'+esc(emailTxt)+'">'+esc(emailTxt)+'</span></div></div>'
   +(sub?'<div class="fleet-card-dates"><span class="fleet-card-date '+sub.tone+'"><span class="fleet-card-date-label">Подписка до</span><b>'+esc(sub.text)+'</b></span></div>':'')
   +'<span class="fleet-card-state '+stClass+'">'+esc(stText)+'</span>'
   +'<div class="row" data-fleet-tone="'+pctTone(p5)+'"><div class="lbl"><span>Сессия 5ч</span><b style="color:'+pctColor(p5)+'">'+pctStr(p5)+'</b><span title="'+esc(r5)+'">'+esc(r5)+'</span></div><div class="bar"><div class="fill" data-t="'+(pctTone(p5)==='bad'?'bad':pctTone(p5)==='warn'?'warn':'ok')+'" style="width:'+(p5==null?0:Math.min(100,p5))+'%"></div></div></div>'
   +'<div class="row" data-fleet-tone="'+pctTone(p7)+'"><div class="lbl"><span>Неделя</span><b style="color:'+pctColor(p7)+'">'+pctStr(p7)+'</b><span title="'+esc(r7)+'">'+esc(r7)+'</span></div><div class="bar"><div class="fill" data-t="'+(pctTone(p7)==='bad'?'bad':pctTone(p7)==='warn'?'warn':'ok')+'" style="width:'+(p7==null?0:Math.min(100,p7))+'%"></div></div></div>'
   +'<div class="fleet-card-footer"><span class="fleet-card-caption">'+esc(modDisp+' · '+effName+(ctx.context_tokens?' · '+fmtTok(ctx.context_tokens):''))+'</span>'
   +'<button type="button" class="agy-btn" id="agyCardRef" style="height:28px;padding:0 10px">Обновить</button>'
   +'<button type="button" class="agy-btn" id="agyCardGear" style="height:28px;padding:0 10px">Настройки</button>'
   +'</div></div>';
  $i('agyCards').innerHTML=cardHtml;
  $i('agyCardRef').onclick=async function(){sToast('🔄 Обновляю Antigravity...');await loadAll(true);sToast('✅ Обновлено');};
  $i('agyCardGear').onclick=function(e){e.stopPropagation();openSettings(e.currentTarget);};
 }
}

async function loadAll(force){
 try{
  var res=await Promise.all([apiGet('agy'+(force?'?refresh=1':'')),apiGet('agy/limits'),apiGet('agy/bridge')]);
  agySnap=res[0];agyLim=res[1];agyBr=res[2];
  try{localStorage.setItem('cc_has_agy',agySnap&&agySnap.available?'1':'0');}catch(e){}
  renderPauseBanner();
  renderTileAndCard();
  syncInstButton();
  if(typeof consTabs==='function')consTabs();
 }catch(e){}
}

(function waitBoot(n){
 if($i('fleetLiveRows')||n>=40){
  loadAll(false);
  setInterval(function(){if(!document.hidden)loadAll(false);},15000);
 }else{
  setTimeout(function(){waitBoot(n+1);},200);
 }
})(0);
}catch(e){console.error('agy_ui',e);}})();
"""


def inject(page_html):
    style_tag = f'<style id="fleetAgyStyle">{CSS}</style>'
    script_tag = f'<script id="fleetAgyScript">{JS}</script>'
    if "</head>" in page_html:
        page_html = page_html.replace("</head>", style_tag + "</head>", 1)
    else:
        page_html = style_tag + page_html
    if "</body>" in page_html:
        page_html = page_html.replace("</body>", script_tag + "</body>", 1)
    else:
        page_html = page_html + script_tag
    return page_html
