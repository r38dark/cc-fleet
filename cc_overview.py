"""Компоновка «Обзор»: существующие узлы и обработчики остаются на месте в DOM."""

CSS = r'''
#cxp .cxprof[hidden]{display:none!important}
html:not(.conly) body{height:auto!important;min-height:100dvh;overflow:auto!important;display:block!important;max-width:1600px;margin:0 auto;padding:24px 32px;background:var(--bg,#0c1119)}
html:not(.conly) .hdr{display:flex;align-items:center;gap:18px;margin-bottom:20px;padding:0}
html:not(.conly) .hdrl{flex:1;min-width:0;gap:12px;flex-wrap:wrap}
html:not(.conly) #h1{font-size:22px;letter-spacing:-.6px;margin:0;color:var(--txt)}
.fleet-brand{color:#41d5ac;font-family:ui-monospace,monospace;font-weight:700;margin-right:9px}
html:not(.conly) .hdrctl{flex-wrap:wrap;justify-content:flex-end}
html:not(.conly) .termwrap{height:auto!important;min-height:0;margin-bottom:0;border:1px solid #2c3848;border-radius:15px;background:#0b1018;overflow:hidden}
html:not(.conly) #termBox{height:clamp(340px,48dvh,720px)!important;min-height:340px!important;max-height:none!important;flex:none!important;margin:0;border:0;border-radius:0;padding:55px 16px 16px;background:#0a0e14;white-space:pre-wrap}
.fleet-profilebar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:11px 15px;border-bottom:1px solid #273242;background:var(--card,#141c28)}
.fleet-profilebar .cxgrp{margin-left:auto}.fleet-profilebar .hdrgear{margin:0}.fleet-profilebar .cxbtn{max-width:min(600px,80vw)}
.fleet-profilelabel{font-size:11px;color:var(--mut);white-space:nowrap}
.fleet-composer{display:flex;align-items:flex-end;gap:9px;padding:12px 14px;border-top:1px solid #273242;background:#121a25}
.fleet-composer textarea{flex:1;resize:vertical;min-height:39px;max-height:180px;margin:0;padding:10px 12px;background:#0c121c;color:var(--txt);border:1px solid #2a3749;border-radius:8px;font:12px/1.5 ui-monospace,Consolas,monospace}
.fleet-composer button{margin:0;padding:10px 13px;min-height:39px;font-size:12px}.fleet-key{background:transparent!important;color:var(--mut)!important;border:1px solid #2a3749!important;padding:10px!important}
.fleet-input-status{display:flex;gap:12px;align-items:center;font-size:10px;color:var(--mut);padding:6px 16px 9px;background:#121a25}.fleet-input-status span:last-child{margin-left:auto}
.fleet-model-label{font-size:10px;color:var(--mut);display:block;margin:0 8px 8px 0}.fleet-cx-options label{font-size:12px;margin-right:12px;display:inline-flex;gap:6px;align-items:center}.fleet-cx-options input{width:60px;padding:5px;color:var(--txt);background:var(--card);border:1px solid #344256;border-radius:6px}.fleet-cx-options button{font-size:11px;padding:7px 10px}.fleet-section{margin:24px 0 0;min-width:0}.fleet-section-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 12px}.fleet-section-head h2{font-size:16px;font-weight:650;margin:0}.fleet-provider{display:inline-block;width:23px;height:23px;border-radius:7px;text-align:center;line-height:23px;margin-right:8px;background:#352a25;color:#e8b18a}.fleet-provider.codex{background:#13352e;color:#43d5ac;font:700 14px/23px ui-monospace,monospace}
.fleet-section-head .switchrow{margin:0 0 0 auto;font-size:11px}.fleet-section-head .hdrgear{margin:0}.fleet-section-head #optWrap{display:flex;align-items:center;gap:7px;font-size:11px;margin-left:auto}
html:not(.conly) #cards,html:not(.conly) #cxcards{height:auto!important;max-height:none!important;min-height:0!important;overflow:visible!important;display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px}
.fleet-section .card{height:auto;min-width:0;margin:0;border:1px solid #283446;border-radius:12px;padding:16px;background:var(--card,#141c28)}.fleet-section .card.active{border-color:#c89b76}.fleet-section .card .email{font-size:12px;overflow-wrap:anywhere}.fleet-section .acts{flex-wrap:wrap}.fleet-section .acts button{font-size:11px}.fleet-section .bar{height:5px}.fleet-section .lbl{font-size:11px}.fleet-section .row{margin-top:12px}
html:not(.conly) .toolrow{margin:12px 0 0;padding:10px 12px;background:#121a25;border:1px solid #273242;border-radius:10px}.fleet-codex #cxAccW{border:0;margin:0}.fleet-codex #cxAccW>.cxacch{display:none}.fleet-codex #cxAccW>#cx{display:block!important}.fleet-codex #cx{margin:0}.fleet-codex .cxhead{margin-bottom:10px}.fleet-codex .cxhead .hdrgear{margin:0}.fleet-codex #cxcards .card{margin:0}.fleet-codex .card.fleet-active{border-color:#41d5ac;box-shadow:inset 0 0 0 1px #41d5ac22}.fleet-active-label{color:#41d5ac;font-size:10px;margin-left:7px}.fleet-rotation-state{font-size:11px;color:var(--mut);padding:10px 1px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}.fleet-rotation-state button{margin:0;padding:5px 9px;font-size:10px}.fleet-rotation-state .err{font-size:11px;margin:0}
.fleet-profile-search{display:block;width:calc(100% - 32px);margin:16px 16px 2px;padding:10px 12px;border:1px solid #344256;border-radius:8px;color:var(--txt);background:#101722;font-size:13px}.fleet-profile-note{font-size:11px;line-height:1.5;color:var(--mut);padding:0 16px;margin:10px 0 4px}
html:root:root .cxpop.cxmenu{width:min(480px,calc(100vw - 20px))}.cxmenu .cxpbody{padding:10px 16px 18px}.cxmenu .cxprof{padding:13px 10px 13px 15px}.cxmenu .cxpnm{font-size:14px}.cxmenu .cxprof .cxps{font-size:12px;line-height:1.5;-webkit-line-clamp:3}.cxmenu .cxprof .cxpf{display:flex;margin-top:7px}.cxmenu .cxpinfo{font-size:12px;line-height:1.6}.cxmenu .cxw{font-size:10px}
html:not(.conly) #verTag{position:static;margin:22px 0 4px;text-align:right;font-size:10px}html.conly #fleetAccounts,html.conly .fleet-profilebar,html.conly .toolrow{display:none!important}html.conly .fleet-composer{flex:none}html.conly .fleet-input-status{flex:none}
.fleet-preview{background:#40321b;color:#ecd09e;font-size:12px;padding:10px 15px;border-radius:8px;margin-bottom:15px}
@media(max-width:1080px){html:not(.conly) body{padding:18px 20px}html:not(.conly) #cards,html:not(.conly) #cxcards{grid-template-columns:repeat(2,minmax(0,1fr))}.fleet-profilebar{gap:8px}.fleet-profilebar .cxgrp{margin-left:0}.fleet-profilelabel{display:none}}
@media(max-width:640px){html:not(.conly) body{padding:14px 10px}.hdr{align-items:flex-start!important}.hdrl{gap:9px!important}#h1{font-size:19px!important}.hdrctl{gap:5px!important}.hdr .hdrgear{width:29px;height:29px}.fleet-section{margin-top:19px}html:not(.conly) #cards,html:not(.conly) #cxcards{grid-template-columns:1fr}.fleet-profilebar{padding:10px}.fleet-profilebar .cxgrp{flex-wrap:wrap;gap:6px}.fleet-profilebar .cxbtn{max-width:calc(100vw - 65px)}.fleet-profilebar .cxlim{font-size:9px}.fleet-composer{flex-wrap:wrap;padding:10px}.fleet-composer textarea{flex-basis:calc(100% - 100px);font-size:12px}.fleet-key{display:none}.fleet-input-status{font-size:9px;padding:5px 11px 8px}.fleet-input-status span:last-child{display:none}html:not(.conly) #termBox{height:390px!important;min-height:300px!important;padding-left:10px;padding-right:10px}.fleet-section-head #optWrap{font-size:10px;flex-basis:100%;margin:0}.fleet-section-head .switchrow{font-size:10px}.cxmenu .cxprof .cxpf{display:flex}.fleet-section .card{padding:14px}.fleet-section .acts .chip.login{font-size:10px}.fleet-section-head h2{font-size:15px}}
'''

JS = r'''
(()=>{
 const el=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls||'';if(text)n.textContent=text;return n};
 document.body.classList.add('fleet-overview');
 const hdr=document.querySelector('.hdr'),term=document.querySelector('.termwrap');
 document.getElementById('h1').innerHTML='<span class="fleet-brand">›_</span>ccfleet';
 const accountArea=el('main','');accountArea.id='fleetAccounts';term.after(accountArea);
 const claude=el('section','fleet-section');claude.id='fleetClaude';
 const ch=el('div','fleet-section-head');ch.innerHTML='<h2><span class="fleet-provider">✳</span>Claude</h2>';
 ch.append(document.getElementById('optWrap'),document.getElementById('addAcct'));
 claude.append(ch,document.getElementById('cards'));accountArea.append(claude);
 const codex=el('section','fleet-section fleet-codex');codex.id='fleetCodex';
 const xh=el('div','fleet-section-head');xh.innerHTML='<h2><span class="fleet-provider codex">›_</span>Codex / ChatGPT</h2><label class="switchrow"><input type="checkbox" id="fleetCxOpt"> Оптимизация переключений лимитов</label>';
 const rotation=el('div','fleet-rotation-state');rotation.id='fleetRotation';
 codex.append(xh,document.getElementById('cxAccW'),rotation);accountArea.append(codex);
 const models=document.querySelector('.toolrow');models.prepend(el('span','fleet-model-label','Claude: модель и уровень рассуждений'));term.after(models);
 const profilebar=el('div','fleet-profilebar');profilebar.innerHTML='<span class="fleet-profilelabel">Профиль, модель и настройки Codex</span>';
 profilebar.append(document.getElementById('cxGrp'));term.before(profilebar);
 const form=el('form','fleet-composer');form.id='fleetConsoleForm';
 form.innerHTML='<textarea id="fleetInput" rows="1" aria-label="Сообщение или команда в выбранную консоль" placeholder="Сообщение или команда… Enter — отправить, Shift+Enter — новая строка"></textarea><button type="button" class="fleet-key" data-console-key="escape" title="Esc в консоль">Esc</button><button type="submit" id="fleetSend">Отправить ↑</button>';
 const inputStatus=el('div','fleet-input-status');inputStatus.innerHTML='<span id="fleetInputState">Ввод в выбранную консоль</span><span>Claude / Codex · действующая сессия</span>';term.append(form,inputStatus);
 const menu=document.getElementById('cxMenu');const search=el('input','fleet-profile-search');search.placeholder='Найти профиль…';search.setAttribute('aria-label','Поиск профилей');
 const note=el('p','fleet-profile-note','Профиль определяет права и способ работы. Аккаунт определяет подписку и лимиты. Активный профиль отмечен галочкой.');menu.prepend(search,note);
 function filterProfiles(){const q=search.value.trim().toLocaleLowerCase('ru');menu.querySelectorAll('.cxprof').forEach(n=>n.hidden=!!q&&!n.textContent.toLocaleLowerCase('ru').includes(q))}
 search.addEventListener('input',filterProfiles);new MutationObserver(filterProfiles).observe(document.getElementById('cxp'),{childList:true});
 const cxOptions=el('div','fleet-cx-options');cxOptions.innerHTML='<div class="modalh">Codex · пороги оптимизации</div><label>Сессия, % <input id="fleetCxThreshold" type="number" min="50" max="100" value="90"></label><label>Неделя, % <input id="fleetCxCap" type="number" min="50" max="100" value="99"></label><button type="button" id="fleetCxSave">Сохранить пороги Codex</button>';
 document.getElementById('autoNote').after(cxOptions);
 document.getElementById('fleetCxSave').addEventListener('click',async e=>{e.target.disabled=true;try{const d=await post('chatgpt/rotation/config',{threshold:Number(document.getElementById('fleetCxThreshold').value),weekly_cap:Number(document.getElementById('fleetCxCap').value)});toast(d.message);await loadRotation()}catch(err){toast('⚠ '+err.message)}finally{e.target.disabled=false}});
 const stateNode=document.getElementById('fleetInputState'),input=document.getElementById('fleetInput'),send=document.getElementById('fleetSend');
 let sending=false,rotationData=null,lastRequest=null;
 async function post(path,body){const r=await fetch(API+path,{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':TOKEN},body:JSON.stringify(body)});const d=await r.json();if(!r.ok||!d.ok)throw Error(d.message||'Не удалось выполнить действие');return d}
 form.addEventListener('submit',async e=>{e.preventDefault();if(sending||!input.value.trim())return;const text=input.value;const session=typeof consCur==='function'?consCur():'claude';sending=true;send.disabled=true;stateNode.textContent='Отправляю в '+(session==='codex'?'Codex':'Claude')+'…';try{const d=await post('console/input',{session,text,request_id:(lastRequest&&lastRequest.text===text&&lastRequest.session===session?lastRequest.id:(lastRequest={text,session,id:crypto.randomUUID()}).id)});if(input.value===text)input.value='';lastRequest=null;stateNode.textContent=d.message||'Ввод передан в консоль';ccConsole()}catch(err){stateNode.textContent=err.message;toast('⚠ '+err.message)}finally{sending=false;send.disabled=false}});
 input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();form.requestSubmit()}});
 form.querySelector('[data-console-key]').addEventListener('click',async()=>{try{const d=await post('console/key',{session:typeof consCur==='function'?consCur():'claude',key:'escape'});stateNode.textContent=d.message;ccConsole()}catch(e){toast('⚠ '+e.message)}});
 function renderRotation(d){rotationData=d;if(!document.querySelector('.fleet-cx-options:focus-within')){document.getElementById('fleetCxThreshold').value=d.threshold||90;document.getElementById('fleetCxCap').value=d.weekly_cap||99;}document.getElementById('fleetCxOpt').checked=!!d.optimize;rotation.replaceChildren();const text=el('span','',d.message||'Проверка лимитов');rotation.append(text);if(d.next_label)rotation.append(el('span','','Следующий: '+d.next_label));if(d.last_error)rotation.append(el('span','err',d.last_error));
  document.querySelectorAll('#cxcards .card').forEach((c,i)=>{const a=typeof cxData!=='undefined'&&cxData.accounts&&cxData.accounts[i];c.classList.toggle('fleet-active',!!a&&a.slot===d.active);if(!a)return;const top=c.querySelector('.top .email');if(top&&a.slot!==d.active)top.querySelector('.fleet-active-label')?.remove();if(top&&a.slot===d.active&&!top.querySelector('.fleet-active-label'))top.append(el('span','fleet-active-label','Выбран'));const existing=c.querySelector('.fleet-pick');if(existing){existing.textContent=a.slot===d.active?'Выбран':'Выбрать';existing.disabled=a.slot===d.active||!!d.optimize;existing.title=d.optimize?'Ручной выбор доступен при выключенной оптимизации':'';}if(!existing){const b=el('button','btn-sw fleet-pick',a.slot===d.active?'Выбран':'Выбрать');b.disabled=a.slot===d.active||!!d.optimize;b.title=d.optimize?'Ручной выбор доступен при выключенной оптимизации':'';b.onclick=async()=>{b.disabled=true;try{const r=await post('chatgpt/rotation/switch',{slot:a.slot});toast(r.message);loadRotation()}catch(e){toast('⚠ '+e.message);loadRotation()}};const acts=c.querySelector('.acts');if(acts)acts.prepend(b)}});
 }
 let refreshing=false;async function loadRotation(){if(refreshing)return;refreshing=true;try{const r=await fetch(API+'chatgpt/rotation',{headers:{'X-CC-Token':TOKEN}});if(r.ok)renderRotation(await r.json())}catch(e){}finally{refreshing=false}}
 document.getElementById('fleetCxOpt').addEventListener('change',async e=>{const on=e.target.checked;e.target.disabled=true;try{await post('chatgpt/rotation/config',{optimize:on});await loadRotation()}catch(err){e.target.checked=!on;toast('⚠ '+err.message)}finally{e.target.disabled=false}});
 const oldCxRender=cxRender;cxRender=function(){oldCxRender();if(rotationData)renderRotation(rotationData);if(typeof cxData!=='undefined'&&cxData&&cxData.loading&&!cxData.accounts.length)document.getElementById('cx').textContent='Загружаем сохранённые аккаунты…'};
 const accLink=document.querySelector('#cxAccW>.cxacch');if(accLink)accLink.title='Аккаунты показаны на главной странице';
 document.getElementById('cxAccW').classList.add('open');
 loadRotation();setInterval(()=>{if(!document.hidden)loadRotation()},5000);
})();
'''


def render(page):
    return page.replace('</head>', '<style id="fleetOverviewStyle">'+CSS+'</style></head>', 1).replace(
        '</body>', '<script id="fleetOverviewScript">'+JS+'</script></body>', 1)
