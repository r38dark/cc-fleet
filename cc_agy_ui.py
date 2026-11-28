"""Frontend CSS + JS plugin injecting Antigravity (agy) into cc-fleet Web UI."""

CSS = r"""
:root{--fleet-agy:#8b9cf7;--fleet-agy-soft:#232844}
#agyPause:not([hidden]){display:block;padding:0;overflow:visible;margin:0 0 8px}
html.conly #agyPause{display:none!important}
.fleet-console-toolbar #ctAgy::before{background:var(--fleet-agy)}
.tpmd[data-m="agy"]{background:var(--fleet-agy)}
.dchip.dx.agy .ddot{background:var(--fleet-agy)}
.fleet-live-account.agy,.fleet-compact-account.agy{--live-accent:var(--fleet-agy)}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc[data-engine="agy"]{grid-column:1/-1}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.agy{--cmod:155px;--cses:128px}
@media(min-width:1380px) and (max-width:1579px){html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.agy{--cmod:148px}}
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
html.agy-desk-fill:not(.conly):root:root #termBox{height:var(--agy-desk-term-h,600px)!important;min-height:240px!important;max-height:none!important}
html.agy-desk-fill:not(.conly):root:root .termwrap.tsplit .fleet-console-viewport{height:var(--agy-desk-split-h,639px)!important;min-height:260px!important;max-height:none!important}
html:root:root .fleet-console-toolbar #cTabs{gap:8px}
html:root:root .fleet-console-toolbar .ctab{display:inline-grid!important;grid-template-columns:auto auto;grid-template-rows:auto auto;align-items:center;align-content:center;justify-content:center;row-gap:3px;column-gap:5px;padding:4px 9px;min-height:48px}
html:root:root .fleet-console-toolbar .ctab::before{grid-column:1;grid-row:1;justify-self:end}
html:root:root .fleet-console-toolbar .ctacts,
html:root:root .fleet-console-toolbar .tzoom{flex:none}
@media(min-width:641px){
 html:root:root .fleet-console-toolbar{flex-wrap:nowrap;gap:10px;padding:0 14px}
 html:root:root .fleet-console-toolbar #cTabs{flex:1 1 auto;min-width:0;gap:10px;flex-wrap:nowrap;overflow:hidden}
 html:root:root .fleet-console-toolbar .ctab{flex:0 0 auto}
 html:root:root .fleet-console-toolbar .ctacts{margin-left:4px}
}
.agy-tab-nm{grid-column:2;grid-row:1;justify-self:start;white-space:nowrap;font-size:11.5px;line-height:1.1;overflow:hidden;text-overflow:ellipsis}
.agy-tab-lim{grid-column:1/-1;grid-row:2;justify-self:center;display:flex;align-items:center;justify-content:center;gap:3px;min-width:0;max-width:100%}
.agy-tab-lim:empty{display:none}
.agy-k-sm{display:none}
.agy-tl{--tlg:76,219,176;--p:0;position:relative;display:inline-flex;align-items:center;gap:2.5px;height:14px;padding:0 4px 2px;border-radius:4px;font-size:9.5px;line-height:1;letter-spacing:0;border:1px solid rgba(132,148,170,.24);background:linear-gradient(90deg,rgba(var(--tlg),.20) calc(var(--p,0)*1%),rgba(255,255,255,.03) 0);overflow:hidden;box-sizing:border-box;flex:0 0 auto}
.agy-tl::after{content:"";position:absolute;left:0;right:0;bottom:0;height:2px;background:linear-gradient(90deg,rgb(var(--tlg)) calc(var(--p,0)*1%),rgba(132,148,170,.24) 0)}
.agy-tl.warn{--tlg:232,185,62}
.agy-tl.bad{--tlg:232,107,107}
.agy-tl.na{opacity:.55}
.agy-tl-k{font-style:normal;font-weight:500;color:#8c9db2}
.agy-tl-v{font-weight:700;font-variant-numeric:tabular-nums;color:#d6e0ec}
.agy-tl.warn .agy-tl-v{color:#f0c451}
.agy-tl.bad .agy-tl-v{color:#f28383}
html:root:root .fleet-console-toolbar .ctab.on .agy-tl{border-color:rgba(var(--tlg),.4)}
html:root:root .fleet-console-toolbar .ctab.on .agy-tl-v{color:#eef4fb}
html:root:root .fleet-console-toolbar .ctab.on .agy-tl.warn .agy-tl-v{color:#f5cc5c}
html:root:root .fleet-console-toolbar .ctab.on .agy-tl.bad .agy-tl-v{color:#ff8f8f}
@media(min-width:641px) and (max-width:1050px){
 #wkAgents .wk-st{display:none}
 #wkAgents .wk-full{display:none}
 #wkAgents .wk-short{display:inline}
}
@media(min-width:641px) and (max-width:900px){
 html:root:root .fleet-console-toolbar{padding:0 10px;gap:6px}
 html:root:root .fleet-console-toolbar #cTabs{gap:6px}
 html:root:root .fleet-console-toolbar .ctab{padding:4px 6px}
}
@media(max-width:640px){
 html:root:root .fleet-console-toolbar{min-height:48px}
 html:root:root .fleet-console-toolbar #cTabs{min-height:48px;gap:2px}
 html:root:root .fleet-console-toolbar .ctab{height:48px!important;min-height:48px;flex:1 1 0;row-gap:3px;column-gap:4px;padding:3px 3px!important}
 .agy-tab-nm{font-size:11px}
 .agy-tab-lim{justify-content:center;gap:2px}
 .agy-tl{height:13px;padding:0 3px 2px;font-size:8.8px;gap:2px;border-radius:4px}
 .agy-k-lg{display:none}
 .agy-k-sm{display:inline}
}
@media(max-width:440px){
 .fleet-composer{gap:4px!important;padding:8px 8px!important}
 .fleet-composer .fleet-key{min-width:20px!important;padding:1px 3px!important;font-size:8.5px!important}
 .fleet-composer #fleetSend{width:26px!important;height:26px!important}
}
#wkAgents .wk-seg[data-ag="agy"]{--c:139,156,247}
html:root:root.ag-pause-agy #wkAgents .wk-seg[data-ag="agy"] .wk-dot{--pz:rgba(139,156,247,.95);width:7px!important;height:8px!important;border:0!important;border-radius:1px!important;box-shadow:none!important;background:linear-gradient(90deg,var(--pz) 0 2.4px,transparent 2.4px 4.6px,var(--pz) 4.6px 7px)!important}
"""

JS = r"""
// [agy] Antigravity (agy) independent 3rd executor: console tab, overview tile, account card, pause/override banner, modals.
(function(){try{
var base=(typeof API!=='undefined'?API:location.origin+'/cc-hook/'),tok=(typeof TOKEN!=='undefined'?TOKEN:'');
var agySnap=null,agyLim=null,agyBr=null,agyCli=null,agyWrap=null,agyModalsBound=false,agyPauseOpen=false;
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
  'gemini-4-neon-high':'4 Neon',
  'gemini-4-neon-xhigh':'4 Neon',
  'gemini-4-neon-medium':'4 Neon',
  'gemini-4-neon-low':'4 Neon',
  'gemini-4-carbon-high':'4 Carbon',
  'gemini-4-carbon-medium':'4 Carbon',
  'gemini-4-carbon-low':'4 Carbon',
  'gemini-4-argon-high':'4 Argon',
  'gemini-4-argon-medium':'4 Argon',
  'gemini-4-argon-low':'4 Argon',
  'gemini-4-hydrogen-high':'4 Hydrogen',
  'gemini-4-hydrogen-xhigh':'4 Hydrogen',
  'gemini-4-hydrogen-medium':'4 Hydrogen',
  'gemini-4-hydrogen-low':'4 Hydrogen',
  'gemini-3.8-flash-high':'3.8 Flash',
  'gemini-3.8-flash-medium':'3.8 Flash',
  'gemini-3.8-flash-low':'3.8 Flash',
  'gemini-pro-orchestrator-neon':'Orchestrator Neon',
  'gemini-pro-orchestrator':'Orchestrator Carbon',
  'gemini-pro-orchestrator-argon':'Orchestrator Argon'
 };
 if(map[s.toLowerCase()])return map[s.toLowerCase()];
 return s.replace(/^gemini[\s-]+/i,'').replace(/\s*\((high|medium|low|xhigh|max)\)\s*$/i,'').trim()||s;
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
 if(typeof window.tabName==='function'&&!window.tabName._agyWrapped){
  var _tabName=window.tabName;
  window.tabName=function(k){
   var b=[].slice.call(document.querySelectorAll('#cTabs .ctab')).find(function(x){return x.dataset&&x.dataset.s===k;});
   if(b&&b.dataset.agyLabel)return b.dataset.agyLabel;
   return _tabName(k);
  };
  window.tabName._agyWrapped=true;
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
   renderTabLimits();
   schedFitConsole();
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
   var bT=document.createElement('button');bT.type='button';bT.id='agyKeyTab';bT.className='fleet-key';bT.textContent='Tab';bT.title='Tab (Antigravity)';bT.hidden=true;
   downBtn.insertAdjacentElement('afterend',bT);
   downBtn.insertAdjacentElement('afterend',bR);
   downBtn.insertAdjacentElement('afterend',bL);
   bL.addEventListener('click',async function(e){e.preventDefault();var r=await apiPost('agy/console/key',{key:'left'});if(!r.ok)sToast('⚠ '+r.message);});
   bR.addEventListener('click',async function(e){e.preventDefault();var r=await apiPost('agy/console/key',{key:'right'});if(!r.ok)sToast('⚠ '+r.message);});
   bT.addEventListener('click',async function(e){e.preventDefault();var r=await apiPost('agy/console/key',{key:'tab'});if(!r.ok)sToast('⚠ '+r.message);});
   lr=bL;
  }
  $i('agyKeyLeft').hidden=!show;
  $i('agyKeyRight').hidden=!show;
  $i('agyKeyTab').hidden=!show;
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
 var dedup=[];
 if(rawModels.length){
  var byDisp={};
  rawModels.forEach(function(m){
   var d=shortModel(m.name||m.id),isCurEff=m.id.toLowerCase().indexOf('-'+curE)>=0,isHigh=m.id.toLowerCase().indexOf('-high')>=0;
   if(!byDisp[d]||(isCurEff&&byDisp[d].p<2)||(isHigh&&byDisp[d].p<1)){
    byDisp[d]={m:m,d:d,p:isCurEff?2:isHigh?1:0};
   }
  });
  Object.keys(byDisp).forEach(function(d){dedup.push({id:byDisp[d].m.id,name:d});});
 }
 var models=dedup.length?dedup:[
  {id:'gemini-4-neon-high',name:'4 Neon'},
  {id:'gemini-4-carbon-high',name:'4 Carbon'},
  {id:'gemini-4-argon-high',name:'4 Argon'},
  {id:'gemini-4-hydrogen-high',name:'4 Hydrogen'},
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
  +'<button type="button" class="agy-btn" id="agyCheckModBtn">🔍 Проверить модели Gemini</button>'
  +'<button type="button" class="agy-btn" id="agyCheckCliBtn">⬆ Проверить CLI'+(agyCli&&agyCli.version?' ('+esc(agyCli.version)+')':'')+'</button>'
  +'<button type="button" class="agy-btn" id="agyBootstrapBtn">✨ Доступ и стиль</button>'
  +'<button type="button" class="agy-btn" id="agyReloginBtn">🔑 Войти заново (Google)</button>'
  +'<button type="button" class="agy-btn danger" id="agyUninstallBtn">🗑 Удалить Antigravity</button>'
  +'</div><div class="agy-msg" id="agyCheckMsg">'
  +(agyCli&&agyCli.version?('Antigravity CLI '+esc(agyCli.version)+(agyCli.update_available?' · доступна '+esc(agyCli.latest):agyCli.latest?' · актуальна':'')):'')
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
 $i('agyCheckModBtn').onclick=async function(){
  var m=$i('agyCheckMsg');if(m)m.textContent='Проверяю каталог моделей Gemini…';
  await apiPost('agy/models/check',{});
  for(var i=0;i<15;i++){
   await new Promise(function(res){setTimeout(res,1000);});
   var d=await apiGet('agy/models/discovery');
   if(m&&d.message)m.textContent=d.message;
   if(!d.checking){sToast(d.ok?'✅ '+d.message:'⚠ '+d.message);loadAll(false);break;}
  }
 };
 $i('agyCheckCliBtn').onclick=async function(){
  var m=$i('agyCheckMsg');if(m)m.textContent='Проверяю обновления Antigravity CLI…';
  var d=await apiGet('agy/cli?check=1');
  agyCli=d;
  if(typeof ccliData!=='undefined'&&ccliData)ccliData.agy=d;
  if(typeof ccliBadgeRender==='function')ccliBadgeRender();
  if(typeof ccliPartVers==='function')ccliPartVers();
  var txt=d.version?('Antigravity CLI '+d.version+(d.update_available?' → доступна '+d.latest:' (актуальная версия)')):'Не удалось определить версию CLI.';
  if(m)m.textContent=txt;
  sToast(d.update_available?'⬆ '+txt:'✅ '+txt);
 };
 $i('agyBootstrapBtn').onclick=async function(){var r=await apiPost('agy/bootstrap',{});sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);};
 $i('agyReloginBtn').onclick=function(e){e.stopPropagation();openInstallWizard($i('agyGear')||anchor,true);};
 $i('agyUninstallBtn').onclick=async function(e){
  e.stopPropagation();
  var ok=window.fleetAsk?await window.fleetAsk(e.currentTarget,'Удалить Antigravity CLI, авторизацию и локальное состояние? После удаления можно установить заново через «Antigravity +».','Удалить'):confirm('Удалить Antigravity CLI и авторизацию, чтобы установить заново?');
  if(!ok)return;
  var r=await apiPost('agy/uninstall',{});
  sToast(r.ok?'✅ '+r.message:'⚠ '+r.message);
  closeAgyPopovers();
  await loadAll(false);
 };

 p.hidden=false;
 if(anchor)anchor.setAttribute('aria-expanded','true');
 if(window.fleetPlace&&anchor)window.fleetPlace(p,anchor,420);
}

// Render #agyPause banner — exact same compact layout, typography, and live countdown timer as Claude & Codex!
function agyLeft(ms){
 if(typeof ccpLeft==='function')return ccpLeft(ms);
 var s=Math.max(0,Math.ceil((ms-Date.now())/1000)),d=Math.floor(s/86400);s%=86400;
 var h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=s%60;
 var p=function(x){return String(x).padStart(2,'0');};
 return d?(d+' д '+h+' ч'):(p(h)+':'+p(m)+':'+p(sec));
}
function agyAt(ms,week){
 if(!ms)return '';
 var d=new Date(ms);
 if(week)return WD.format(d).replace(/,/g,'');
 return clk(d);
}
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
 var prev=el.querySelector(':scope > details');if(prev)agyPauseOpen=prev.open;
 var isHard=!!n.hard;
 var isPaused=!!(p&&p.active);
 var isOver=!!n.override&&!isPaused;
 var upMs=(n.resume_at||0)*1000;
 var mins=n.windows||[];
 var isWeekOnly=mins.indexOf(10080)>=0&&mins.indexOf(300)<0;
 var wins=(n.window_names||[]).join(', ')||'лимит';
 var at=upMs?agyAt(upMs,isWeekOnly):'';
 var acc=(agySnap&&agySnap.accounts&&agySnap.accounts[0])||{};
 var wmap={};(acc.windows||[]).forEach(function(w){wmap[w.mins]=w;});
 var p5=pctVal(wmap[300]),p7=pctVal(wmap[10080]);
 var mainPct=isWeekOnly?(p7!=null?Math.round(p7)+'%':''):(p5!=null?Math.round(p5)+'%':'');
 var brief=isHard?('Antigravity · '+wins+' 100%'+(at?' до '+at:''))
  :isOver?('Antigravity · пауза отключена вручную ('+wins+' до 100%)')
  :('Antigravity · '+wins+(mainPct?' '+mainPct:'')+(at?' до '+at:''));
 var fullTitle=isHard?('Лимит Antigravity исчерпан (100%)'+(at?' до '+at:''))
  :isOver?('Пауза Antigravity отключена вручную — работа до 100%')
  :('Antigravity на паузе по лимитам'+(at?' до '+at:''));
 var sub=isHard?'Настоящий лимит аккаунта исчерпан. Очередь отправится автоматически после сброса окна.'
  :isOver?'Входящие сообщения идут сразу до 100%. Пауза включится обратно автоматически после сброса окна.'
  :'Достигнут настроенный порог ('+(agyLim.threshold||90)+'% / '+(agyLim.weekly_cap||99)+'%). Новые сообщения копятся в очереди.';
 var queued=(agyBr&&agyBr.bridge&&agyBr.bridge.queued)||0;
 var chip='<span class="ccp-chip hot">Antigravity <b>'+(p5==null?'?':Math.round(p5)+'%')+'</b>'+(p7!=null?' · нед <b>'+Math.round(p7)+'%</b>':'')+'</span>';
 var timer=upMs?'<div class="ccp-timer" data-until="'+upMs+'"><div class="t">'+esc(agyLeft(upMs))+'</div><div class="l">до сброса окна</div></div>':'';
 var btn='';
 if(!isHard&&n.can_override!==false){
  btn=isOver
   ?'<button type="button" class="ccp-btn" id="agyPauseToggle" data-over="0">Включить паузу</button>'
   :'<button type="button" class="ccp-btn" id="agyPauseToggle" data-over="1">Отключить паузу (до 100%)</button>';
 }
 var hint=(queued?'В очереди: '+queued+'. ':'')+(isHard?'Доступность обновится после сброса.':'Можно доработать остаток до 100% или дождаться автосброса.');
 el.className='ccpause '+(isHard?'lvl-hard':isOver?'lvl-off':'lvl-pause');
 el.innerHTML='<details class="fleet-pause-fold"'+(agyPauseOpen?' open':'')+'><summary class="fleet-pause-summary">'
  +'<span class="ccp-dot"></span>'
  +'<span class="ccp-title">'+esc(brief)+'</span>'
  +timer
  +'<svg viewBox="0 0 24 24" class="fleet-pause-chevron" aria-hidden="true"><path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  +'</summary><div class="fleet-pause-content"><div class="ccp-body">'
  +'<div class="ccp-title">'+esc(fullTitle)+'</div>'
  +'<div class="ccp-sub">'+esc(sub)+'</div>'
  +'<div class="ccp-meta">'+chip+'</div>'
  +'<div class="ccp-actions">'+btn+'<span class="ccp-hint">'+esc(hint)+'</span></div>'
  +'</div></div></details>';
 el.hidden=false;
 el.querySelector('details').addEventListener('toggle',function(e){agyPauseOpen=e.target.open;});
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
function agyPauseTick(){
 var t=document.querySelector('#agyPause .ccp-timer');if(!t)return;
 var until=+t.dataset.until;if(!until)return;
 var el=t.querySelector('.t');if(el)el.textContent=agyLeft(until);
}
setInterval(agyPauseTick,1000);

// Wire translucent console countdown overlay (#ccps) + Active Accounts top-border pill badge (limxBadges) + CLI version badge (#ccliBadge / #ccliPv)
(function hookLimxAndCli(){
 if(typeof window.limxState==='function'){
  var _limxState=window.limxState;
  window.limxState=function(k){
   if(k!=='agy')return _limxState(k);
   try{
    var p=agyLim&&agyLim.limit_pause,n=agyLim&&agyLim.limit_notice;
    var acc=(agySnap&&agySnap.accounts&&agySnap.accounts[0])||{};
    var wins=(acc.windows||[]).map(function(w){
     var t=w&&w.resets_at?Date.parse(w.resets_at):NaN;
     return {win:w.mins===300?'5h':w.mins===10080?'week':'',pct:typeof w.pct==='number'?w.pct:null,until:isNaN(t)?0:t};
    });
    var pause=null;
    if(p&&p.active&&!p.hard){pause={until:(+(p.resume_at||0))*1000};}
    var reported=!!(n&&n.active&&n.hard&&!wins.some(function(w){return w.pct>=100;}));
    if(typeof limxPick==='function')return limxPick(pause,wins,reported,Date.now());
    if(pause)return {kind:'pause',win:'',until:pause.until};
    return null;
   }catch(e){return null;}
  };
 }
 if(typeof window.limxTitle==='function'){
  var _limxTitle=window.limxTitle;
  window.limxTitle=function(k,s){
   if(k==='agy'&&typeof limxText==='function')return 'Antigravity: '+limxText(s)+'. Новые действия ждут сброса, беседа сохранена.';
   return _limxTitle(k,s);
  };
 }
 if(typeof window.ccpsWindows==='function'){
  var _ccpsWindows=window.ccpsWindows;
  window.ccpsWindows=function(k,s){
   if(k!=='agy')return _ccpsWindows(k,s);
   var n=(agyLim&&(agyLim.limit_pause&&agyLim.limit_pause.active?agyLim.limit_pause:agyLim.limit_notice))||{};
   var mins=n.windows||[];
   var resets=n.resets||{};
   var out=mins.map(function(m){
    return {window:m===300?'5h':m===10080?'week':'',resume_at:resets[m]||resets[String(m)]||(mins.length===1?n.resume_at:0)||0};
   });
   if(!out.length)out=[{window:s.win||'',resume_at:(s.until||0)/1000}];
   return out;
  };
 }
 if(typeof window.ccpsHtml==='function'){
  var _ccpsHtml=window.ccpsHtml;
  window.ccpsHtml=function(k){
   if(k!=='agy')return _ccpsHtml(k);
   var p=agyLim&&agyLim.limit_pause;
   if(!(p&&p.active)||p.hard)return '';
   var upMs=(p.resume_at||0)*1000;
   return '<b>⏸ Antigravity на паузе</b>'+(upMs?' до '+agyAt(upMs,false)+' ('+agyLeft(upMs)+')':'')+'. Новые сообщения встают в очередь.';
  };
 }
 // Integrate Antigravity CLI version & updates into #ccliBadge, #ccliPop, #ccliBox, and console corner pill (#ccliPv)
 if(typeof window.ccliLoad==='function'){
  var _ccliLoad=window.ccliLoad;
  window.ccliLoad=async function(check){
   var p1=_ccliLoad(check);
   var p2=apiGet('agy/cli'+(check?'?check=1':'')).then(function(d){agyCli=d;return d;}).catch(function(){return null;});
   await Promise.all([p1,p2]);
   if(typeof ccliData!=='undefined'&&ccliData&&agyCli&&agyCli.kind)ccliData.agy=agyCli;
   if(typeof ccliRender==='function')ccliRender();
   if(typeof ccliBadgeRender==='function')ccliBadgeRender();
   if(typeof ccliPartVers==='function')ccliPartVers();
  };
 }
 if(typeof window.ccliPost==='function'){
  var _ccliPost=window.ccliPost;
  window.ccliPost=async function(act,body){
   if(body&&body.target==='agy'){
    if(act==='update')return apiPost('agy/cli/update',{version:body.version||'latest'});
    if(act==='restart')return apiPost('agy/cli/restart',{});
   }
   return _ccliPost(act,body);
  };
 }
 if(typeof window.ccliNews==='function'){
  var _ccliNews=window.ccliNews;
  window.ccliNews=function(){
   var list=_ccliNews();
   var x=(typeof ccliData!=='undefined'&&ccliData&&ccliData.agy)||agyCli;
   if(x&&x.ok!==false&&x.kind&&!list.some(function(it){return it[0]==='agy';})){
    var popOn=typeof ccliPopOpen!=='undefined'&&ccliPopOpen;
    if((x.update_available&&x.can_update)||x.state==='running'||!!(x.restart&&x.restart.stale)||(popOn&&(x.state==='done'||x.state==='failed'))){
     list=list.concat([['agy',x]]);
    }
   }
   return list;
  };
 }
 if(typeof window.ccliRow==='function'){
  var _ccliRow=window.ccliRow;
  window.ccliRow=function(k,d){
   var html=_ccliRow(k,d);
   if(k==='agy'){
    html=html.replace(/Claude Code/g,'Antigravity CLI').replace(/Перезапустить Claude/g,'Перезапустить консоль Antigravity');
   }
   return html;
  };
 }
 if(typeof window.ccliRender==='function'){
  var _ccliRender=window.ccliRender;
  window.ccliRender=function(){
   _ccliRender();
   var box=$i('ccliBox'),scrim=$i('scrim');
   if(!box||(scrim&&scrim.hidden))return;
   var x=(typeof ccliData!=='undefined'&&ccliData&&ccliData.agy)||agyCli;
   if(x&&x.kind&&!box.querySelector('[data-k="agy"]')){
    var rowHtml=window.ccliRow('agy',x);
    var hint=box.querySelector('.modalsub:last-child');
    if(hint)hint.insertAdjacentHTML('beforebegin',rowHtml);
    else box.insertAdjacentHTML('beforeend',rowHtml);
   }
  };
 }
 if(typeof window.ccliPopRender==='function'){
  var _ccliPopRender=window.ccliPopRender;
  window.ccliPopRender=function(){
   _ccliPopRender();
   var pop=$i('ccliPop');
   if(!pop||pop.hidden)return;
   pop.querySelectorAll('.cp-row').forEach(function(r){
    var b=r.querySelector('[data-k="agy"]');
    if(b){
     var ttl=r.querySelector('b');if(ttl)ttl.textContent=ttl.textContent.replace('Claude Code','Antigravity CLI');
     if(b.dataset.ccliPop==='restart')b.textContent='Перезапустить консоль Antigravity';
    }
   });
  };
 }
 if(typeof window.ccliPvInfo==='function'){
  var _ccliPvInfo=window.ccliPvInfo;
  window.ccliPvInfo=function(s,x){
   if(s==='agy'){
    var ax=agyCli||(typeof ccliData!=='undefined'&&ccliData&&ccliData.agy);
    if(!ax||ax.ok===false||!ax.version)return null;
    var stale=!!(ax.restart&&ax.restart.stale),old=stale||!!ax.update_available;
    return {k:'agy',old:old,text:'Antigravity '+ax.version,title:old?(stale?'Консоль Antigravity работает на старой версии — перезапустите её.':'Доступна новая версия Antigravity CLI '+ax.latest):'Актуальная версия Antigravity CLI'};
   }
   return _ccliPvInfo(s,x);
  };
 }
})();

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
  var reqs=[apiGet('agy'+(force?'?refresh=1':'')),apiGet('agy/limits'),apiGet('agy/bridge')];
  if(!agyCli)reqs.push(apiGet('agy/cli').catch(function(){return null;}));
  var res=await Promise.all(reqs);
  agySnap=res[0];agyLim=res[1];agyBr=res[2];
  if(res.length>3&&res[3]){
   agyCli=res[3];
   if(typeof ccliData!=='undefined'&&ccliData&&agyCli.kind)ccliData.agy=agyCli;
  }
  try{localStorage.setItem('cc_has_agy',agySnap&&agySnap.available?'1':'0');}catch(e){}
  renderPauseBanner();
  renderTileAndCard();
  syncInstButton();
  renderTabLimits();
  syncWkAgy();
  fitDesktopConsole();
  if(typeof consTabs==='function')consTabs();
  if(typeof limxBadges==='function')limxBadges();
  if(typeof ccpPartStrip==='function')ccpPartStrip();
  if(typeof ccliBadgeRender==='function')ccliBadgeRender();
  if(typeof ccliPartVers==='function')ccliPartVers();
 }catch(e){}
}

var _fitRaf=0,_topSyncRaf=0,_obsInit=false;
function parseDomPct(el){
 if(!el)return null;
 var m=String(el.textContent||'').match(/(\d+(?:\.\d+)?)\s*%/);
 return m?Math.max(0,Math.min(100,Math.round(parseFloat(m[1])))):null;
}
function domWins(engine){
 var card=document.querySelector('#fleetLiveRows .fleet-compact-account.'+engine);
 if(!card)return{p5:null,p7:null,t5:'',t7:''};
 var w5=card.querySelector('.fleet-compact-window[data-window="session"]');
 var w7=card.querySelector('.fleet-compact-window[data-window="week"]');
 return{
  p5:parseDomPct(w5&&w5.querySelector('.fleet-compact-used')),
  p7:parseDomPct(w7&&w7.querySelector('.fleet-compact-used')),
  t5:w5&&w5.querySelector('.fleet-compact-range')?String(w5.querySelector('.fleet-compact-range').textContent||'').trim():'',
  t7:w7&&w7.querySelector('.fleet-compact-range')?String(w7.querySelector('.fleet-compact-range').textContent||'').trim():''
 };
}
function mkLimWin(pct,reached,resetAt,isWeek,domPct,domTxt){
 var v=(pct!=null&&pct!==''&&isFinite(pct))?Math.max(0,Math.min(100,Math.round(Number(pct)))):null;
 if(v==null&&domPct!=null)v=domPct;
 var full=!!reached||(v!=null&&v>=100);
 var tone=full||(v!=null&&v>=95)?'bad':(v!=null&&v>=80)?'warn':'';
 var rstVal=typeof resetAt==='number'&&resetAt>0&&resetAt<1e12?resetAt*1000:resetAt;
 var rst=rstVal?fmtReset(rstVal,isWeek):(domTxt||'');
 return{pct:v,full:full,tone:tone,rst:rst};
}
function readEngineLimits(k){
 var d=domWins(k),snap=typeof lastSnap!=='undefined'?lastSnap:null;
 var ccp=typeof ccpData!=='undefined'?ccpData:null;
 var cxl=typeof cxlpData!=='undefined'?cxlpData:null;
 var rootCl=document.documentElement.classList;
 var paused=false,s5=null,wk=null;
 if(k==='claude'){
  paused=rootCl.contains('ag-pause-claude')||!!(ccp&&((ccp.pause&&ccp.pause.active)||(ccp.claude_limits&&ccp.claude_limits.claude&&ccp.claude_limits.claude.waiting)));
  var a=snap&&snap.accounts&&snap.accounts[snap.active];
  s5=mkLimWin(a&&a.five_hour&&a.five_hour.pct,false,a&&a.five_hour&&a.five_hour.resets_at,false,d.p5,d.t5);
  wk=mkLimWin(a&&a.seven_day&&a.seven_day.pct,false,a&&a.seven_day&&a.seven_day.resets_at,true,d.p7,d.t7);
 }else if(k==='prod'){
  paused=rootCl.contains('ag-pause-prod')||!!(ccp&&ccp.remote_pause&&ccp.remote_pause.active);
  var rm=snap&&snap.remote,rk=rm&&Object.keys(rm)[0],m=rk?rm[rk]:null;
  s5=mkLimWin(m&&m.five_hour&&m.five_hour.pct,false,m&&m.five_hour&&m.five_hour.resets_at,false,d.p5,d.t5);
  wk=mkLimWin(m&&m.seven_day&&m.seven_day.pct,false,m&&m.seven_day&&m.seven_day.resets_at,true,d.p7,d.t7);
 }else if(k==='codex'){
  paused=rootCl.contains('ag-pause-codex')||!!(cxl&&cxl.active&&cxl.paused);
  var ca=typeof cxLimAcc==='function'?cxLimAcc():null;
  var c5=null,c7=null;
  if(ca&&ca.windows){
   ca.windows.forEach(function(w){if(w&&w.mins===300)c5=w;else if(w&&w.mins===10080)c7=w;});
  }
  if(!c5&&!c7&&cxl&&cxl.active&&cxl.percentages){
   c5={pct:cxl.percentages[300],resets_at:(cxl.resets||{})[300]};
   c7={pct:cxl.percentages[10080],resets_at:(cxl.resets||{})[10080]};
  }
  s5=mkLimWin(c5&&c5.pct,c5&&c5.reached,c5&&c5.resets_at,false,d.p5,d.t5);
  wk=mkLimWin(c7&&c7.pct,c7&&c7.reached,c7&&c7.resets_at,true,d.p7,d.t7);
 }else if(k==='agy'){
  paused=rootCl.contains('ag-pause-agy')||!!(agyLim&&agyLim.limit_pause&&agyLim.limit_pause.active);
  var acc=(agySnap&&agySnap.accounts&&agySnap.accounts[0])||{};
  var w5=null,w7=null;
  (acc.windows||[]).forEach(function(w){if(w&&w.mins===300)w5=w;else if(w&&w.mins===10080)w7=w;});
  s5=mkLimWin(w5&&w5.pct,w5&&w5.reached,w5&&w5.resets_at,false,d.p5,d.t5);
  wk=mkLimWin(w7&&w7.pct,w7&&w7.reached,w7&&w7.resets_at,true,d.p7,d.t7);
 }
 return{paused:paused,s5:s5||mkLimWin(null,false,0,false,null,''),wk:wk||mkLimWin(null,false,0,true,null,'')};
}
function tlHtml(lblLg,lblSm,w,paused){
 var p=w&&w.pct!=null?w.pct:null;
 var cls='agy-tl'+(p==null?' na':'')+(w&&w.tone?' '+w.tone:(paused?' bad':''));
 var kHtml=lblSm&&lblSm!==lblLg?('<span class="agy-k-lg">'+esc(lblLg)+'</span><span class="agy-k-sm">'+esc(lblSm)+'</span>'):esc(lblLg);
 return '<span class="'+cls+'" style="--p:'+(p==null?0:Math.min(100,p))+'"><i class="agy-tl-k">'+kHtml+'</i><b class="agy-tl-v">'+(p==null?'—':p+'%')+'</b></span>';
}
function renderTabLimits(){
 var en=typeof LANG!=='undefined'&&LANG==='en';
 var l5=en?'5h':'5ч',lw=en?'wk':'нед',lws=en?'wk':'н';
 [['claude','#ctClaude'],['prod','#ctProd'],['codex','#ctCodex'],['agy','#ctAgy']].forEach(function(pair){
  var k=pair[0],b=$i(pair[1].slice(1));if(!b)return;
  var nmEl=b.querySelector('.agy-tab-nm'),limEl=b.querySelector('.agy-tab-lim');
  if(!nmEl){
   var base=(b.dataset.agyLabel||b.textContent||'').trim()||k;
   b.dataset.agyLabel=base;
   b.textContent='';
   nmEl=document.createElement('span');nmEl.className='agy-tab-nm';nmEl.textContent=base;
   limEl=document.createElement('span');limEl.className='agy-tab-lim';limEl.setAttribute('aria-hidden','true');
   b.appendChild(nmEl);b.appendChild(limEl);
  }else if(!limEl){
   limEl=document.createElement('span');limEl.className='agy-tab-lim';limEl.setAttribute('aria-hidden','true');
   b.appendChild(limEl);
  }
  var info=readEngineLimits(k);
  var hasAny=info.s5.pct!=null||info.wk.pct!=null;
  var html=hasAny?(tlHtml(l5,l5,info.s5,info.paused)+tlHtml(lw,lws,info.wk,false)):'';
  if(limEl.innerHTML!==html)limEl.innerHTML=html;
  var lbl=b.dataset.agyLabel||nmEl.textContent;
  var tipParts=[lbl];
  if(info.s5.pct!=null)tipParts.push((en?'5h: ':'5ч: ')+info.s5.pct+'%'+(info.s5.rst?' ('+info.s5.rst+')':''));
  if(info.wk.pct!=null)tipParts.push((en?'Week: ':'Неделя: ')+info.wk.pct+'%'+(info.wk.rst?' ('+info.wk.rst+')':''));
  var cur=typeof consCur==='function'?consCur():'claude';
  var sw=(k!==cur&&typeof tr==='function')?tr('cxcSw')+lbl+' · ':'';
  b.title=sw+tipParts.join(' · ');
 });
}
function syncWkAgy(){
 var bar=$i('wkAgents');if(!bar)return;
 var avail=window.agyAvail();
 var seg=$i('wkAgy');
 if(!avail){if(seg)seg.remove();return;}
 if(!seg){
  seg=document.createElement('button');
  seg.type='button';seg.id='wkAgy';seg.className='wk-seg';seg.setAttribute('data-ag','agy');
  seg.innerHTML='<span class="wk-dot"></span><span class="wk-nm"><span class="wk-full">Antigravity</span><span class="wk-short">Agy</span></span><span class="wk-st"></span>';
  seg.addEventListener('click',function(e){e.stopPropagation();openProfilePop(seg);});
  var cx=bar.querySelector('[data-ag="codex"]');
  if(cx&&cx.nextSibling)bar.insertBefore(seg,cx.nextSibling);else bar.appendChild(seg);
 }
 var rt=(agySnap&&agySnap.runtime)||{};
 var paused=!!(agyLim&&agyLim.limit_pause&&agyLim.limit_pause.active);
 var on=!!(rt.running&&!paused);
 var en=typeof LANG!=='undefined'&&LANG==='en';
 var stTxt=paused?(en?'paused':'пауза'):on?(en?'running':'работает'):(en?'ready':'готов');
 seg.className='wk-seg '+(paused?'s-pause':on?'s-run on':'s-off');
 var stEl=seg.querySelector('.wk-st');if(stEl&&stEl.textContent!==stTxt)stEl.textContent=stTxt;
 var tip='Antigravity · '+stTxt;
 if(seg.title!==tip){seg.title=tip;seg.setAttribute('aria-label',tip);}
}
function fitDesktopConsole(){
 var root=document.documentElement,wrap=document.querySelector('.termwrap'),box=$i('termBox');
 if(!wrap||!box)return;
 var desk=window.innerWidth>640&&window.innerHeight>=560&&!root.classList.contains('conly');
 if(!desk){
  root.classList.remove('agy-desk-fill');
  root.style.removeProperty('--agy-desk-term-h');
  root.style.removeProperty('--agy-desk-split-h');
  return;
 }
 var wasAtBot=box.scrollTop+box.clientHeight>=box.scrollHeight-24;
 var tsplit=wrap.classList.contains('tsplit');
 var vp=wrap.querySelector('.fleet-console-viewport');
 var wrapTop=Math.round(wrap.getBoundingClientRect().top+(window.scrollY||window.pageYOffset||0));
 var chromeH=0;
 Array.prototype.forEach.call(wrap.children,function(ch){
  if(ch===vp||ch===box)return;
  var cs=getComputedStyle(ch);
  if(cs.display==='none'||cs.position==='absolute'||cs.position==='fixed')return;
  chromeH+=ch.offsetHeight;
 });
 var wcs=getComputedStyle(wrap);
 chromeH+=(parseFloat(wcs.borderTopWidth)||0)+(parseFloat(wcs.borderBottomWidth)||0);
 var h=Math.max(tsplit?280:240,Math.floor(window.innerHeight-wrapTop-chromeH-12));
 if(tsplit){
  root.style.setProperty('--agy-desk-split-h',h+'px');
  root.style.removeProperty('--agy-desk-term-h');
 }else{
  root.style.setProperty('--agy-desk-term-h',h+'px');
  root.style.removeProperty('--agy-desk-split-h');
 }
 root.classList.add('agy-desk-fill');
 if(wasAtBot)box.scrollTop=box.scrollHeight;
}
function schedFitConsole(){
 if(_fitRaf)return;
 _fitRaf=requestAnimationFrame(function(){_fitRaf=0;fitDesktopConsole();});
}
function schedTopSync(){
 if(_topSyncRaf)return;
 _topSyncRaf=requestAnimationFrame(function(){_topSyncRaf=0;renderTabLimits();syncWkAgy();fitDesktopConsole();});
}
function installTopObservers(){
 if(_obsInit)return;
 _obsInit=true;
 window.addEventListener('resize',schedTopSync,{passive:true});
 window.addEventListener('orientationchange',schedTopSync,{passive:true});
 if(typeof MutationObserver!=='undefined'){
  var bObs=new MutationObserver(function(){schedFitConsole();schedTopSync();});
  ['ccPause','ccPauseDev','ccPauseProd','cxPause','agyPause','updBanner'].forEach(function(id){
   var el=$i(id);if(el)bObs.observe(el,{attributes:true,childList:true,subtree:true});
  });
  var tw=document.querySelector('.termwrap');
  if(tw)bObs.observe(tw,{attributes:true,attributeFilter:['class']});
  var rows=$i('fleetLiveRows');
  if(rows){
   var rObs=new MutationObserver(function(){schedTopSync();});
   rObs.observe(rows,{childList:true,subtree:true,characterData:true});
  }
 }
 if(typeof ResizeObserver!=='undefined'){
  var szObs=new ResizeObserver(function(){schedFitConsole();});
  ['ccPause','ccPauseDev','ccPauseProd','cxPause','agyPause','updBanner'].forEach(function(id){
   var el=$i(id);if(el)szObs.observe(el);
  });
  var hdr=document.querySelector('.hdr');if(hdr)szObs.observe(hdr);
 }
 ['cxRender','cxlpRender','renderCards'].forEach(function(fn){
  if(typeof window[fn]==='function'&&!window[fn]._agyTopWrapped){
   var orig=window[fn];
   window[fn]=function(){var res=orig.apply(this,arguments);schedTopSync();return res;};
   window[fn]._agyTopWrapped=true;
  }
 });
}

(function waitBoot(n){
 if($i('fleetLiveRows')||n>=40){
  installTopObservers();
  renderTabLimits();
  fitDesktopConsole();
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
