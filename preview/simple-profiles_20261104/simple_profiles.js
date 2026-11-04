 // Единое центральное окно двух исполнителей и настроек резерва.
 let monoView='profiles',monoSignature='',monoAgentReady=false;
 const monoAgentBody=document.getElementById('ntPopB'),monoAgentHome=document.getElementById('ntPop');
 const monoRawOpen=cxMenuOpen;let monoPendingOpen=null;
 cxMenuOpen=function(){if(!mirrorMounted){monoPendingOpen=['codex'];mirrorLoad();return}mirrorOpen('codex')};
 ntOpen=function(){if(!mirrorMounted){monoPendingOpen=['codex','reserve'];mirrorLoad();return}mirrorOpen(mirrorEngine,'reserve')};

 const monoOriginalFilter=filterProfiles,monoOriginalResults=repaintProfileResults;
 filterProfiles=function(){
  if(!mirrorMounted)return monoOriginalFilter();if(search.value!==profileQuery)search.value=profileQuery;
  if(monoView!=='profiles')return;
  const query=profileQuery.trim().toLocaleLowerCase('ru');
  profileRoot.querySelectorAll('.fleet-profile-card,.mono-reserve').forEach(node=>node.hidden=!!query&&!node.textContent.toLocaleLowerCase('ru').includes(query));
  for(const section of profileRoot.querySelectorAll('.mono-provider'))section.hidden=![...section.querySelectorAll('.fleet-profile-card,.mono-reserve')].some(node=>!node.hidden);if(!menu.hidden)monoCenter();
 }
 repaintProfileResults=function(){
  if(!mirrorMounted)return monoOriginalResults();
  if(monoView!=='profiles'){paletteEmpty.hidden=true;putText(paletteCount,'Резерв Claude и Codex');return}
  const cards=[...profileRoot.querySelectorAll('.fleet-profile-card')],reserves=[...profileRoot.querySelectorAll('.mono-reserve')],visible=cards.filter(node=>!node.hidden).length,services=reserves.filter(node=>!node.hidden).length;
  paletteEmpty.hidden=visible+services>0;putText(paletteCount,(profileQuery.trim()?'Найдено: '+visible+' из '+cards.length:cards.length+' рабочих профиля')+' · резервов: '+services);
 }

 function monoParkAgent(){if(monoAgentBody.parentElement!==monoAgentHome)monoAgentHome.append(monoAgentBody)}
 function monoCenter(){
  const viewport=window.visualViewport,w=viewport?.width||innerWidth,h=viewport?.height||innerHeight,left=viewport?.offsetLeft||0,top=viewport?.offsetTop||0,width=Math.min(monoView==='reserve'?960:1040,w-24);menu.style.width=width+'px';menu.style.maxHeight=Math.max(160,h-32)+'px';menu.style.left=Math.round(left+(w-width)/2)+'px';menu.style.right='auto';menu.style.bottom='auto';menu.style.top=(top+Math.max(16,Math.round((h-menu.getBoundingClientRect().height)/2)))+'px';
 }
 cxMenuPlace=monoCenter;
 mirrorTheme=function(){
  menu.dataset.engine='both';menu.dataset.view=monoView;menu.classList.add('mono-profile-window');
  putText(paletteHeading.querySelector('h2'),monoView==='reserve'?'Настройки резерва':'Профили работы');
  menu.setAttribute('aria-label',monoView==='reserve'?'Настройки резерва Claude и Codex':'Профили Claude и Codex');
  paletteHeading.querySelector('.mirror-profile-tabs')?.setAttribute('hidden','');
  paletteTools.hidden=monoView!=='profiles';compareButton.hidden=true;
 }
 mirrorOpen=function(engine,info){
  mirrorEngine=engine;monoView=info==='reserve'?'reserve':'profiles';compareProfiles=false;resetProfileSearch();monoSignature='';mirrorTheme();
  if(menu.hidden)nativeMirrorOpen();else cxpRender();monoCenter();
 }
 function monoDetails(profile){
  return '<div class="cxpinfo"><p><b>Может:</b> '+acctEsc(profile.can)+'</p><p><b>Ограничения:</b> '+acctEsc(profile.cannot)+'</p><p>'+acctEsc(profile.when)+'</p></div>';
 }
 function monoCard(engine,profile,state){
  const selected=profile.id===state.base_selected,info=mirrorInfo[engine].has(profile.id);
  const effective=selected&&['solo','leader'].includes(state.role)&&state.applied!==false;
  const status=selected?(state.applied===false?'Текущие права':effective?'Работает сейчас':'Базовый профиль'):profile.kind==='full'?'Полный доступ':'Чтение + папка обмена';
  return '<div class="cxprof fleet-profile-card'+(selected?' act':'')+'" data-engine="'+engine+'" data-profile-id="'+profile.id+'" data-id="'+profile.id+'" role="radio" aria-checked="'+selected+'" tabindex="0"><div class="mono-mode-head"><span class="mono-mode-kind">'+(profile.kind==='full'?'FULL':'ОРКЕСТРАТОР')+'</span><span class="mono-mode-status">'+status+'</span></div><div class="cxpt"><span class="cxpn"><span class="cxpnm">'+acctEsc(profile.title)+'</span></span><span class="cxps">'+acctEsc(profile.description)+'</span><span class="fleet-profile-index" hidden>'+acctEsc(profile.can+' '+profile.cannot+' '+profile.when)+'</span>'+(info?monoDetails(profile):'')+'</div><div class="fleet-profile-card-footer"><span class="fleet-profile-choose">'+(effective?'Выбран':'Выбрать →')+'</span><button type="button" class="fleet-profile-more" data-mirror-action="info" aria-expanded="'+info+'">'+(info?'Свернуть':'Подробнее')+'</button></div></div>';
 }
 function monoReserve(engine,state,settings){
  const profile=state.profiles.find(p=>p.id==='reserve'),active=state.role==='reserve';
  if(settings)return '<section class="mono-reserve-config" data-engine="'+engine+'" data-profile-id="reserve"><div class="mono-reserve-status">'+(active?'Резерв включён':'Резерв выключен')+'<span>Без ограничения срока</span></div><label class="mono-auto"><input type="checkbox" data-mirror-setting="auto" data-engine="'+engine+'" '+(state.auto.enabled?'checked':'')+'> <span>Включать автоматически, когда '+mirrorNames[engine==='claude'?'codex':'claude']+' недоступен</span></label><p class="mono-note">После восстановления другой модели автоматический резерв вернёт прежний сценарий.</p><div class="mono-reserve-actions"><button type="button" data-mirror-action="'+(active?'stop':'apply')+'">'+(active?'Выключить резерв':'Включить вручную…')+'</button></div></section>';
  return '<section class="mirror-service mono-reserve" data-engine="'+engine+'" data-profile-id="reserve"><div class="mono-reserve-copy"><strong>'+acctEsc(profile.title)+'</strong><div class="cxps">'+(active?'Включён · другая модель на паузе':'Без ограничения срока · другая модель на паузе при включении')+'</div></div><div class="mirror-service-actions"><button type="button" data-mirror-action="'+(active?'stop':'apply')+'">'+(active?'Выключить':'Включить…')+'</button><button type="button" data-mirror-action="reserve-settings" aria-label="Настройки резерва '+mirrorNames[engine]+'">Настройки</button></div></section>';
 }
 function monoAgentLayout(){
  const note=[...monoAgentBody.querySelectorAll(':scope > .ntnote')].find(n=>n.textContent.includes('Резерв и аварийный'));note?.remove();
  const first=monoAgentBody.querySelector(':scope > .ntsec');
  if(first){const help=el('details','mono-notion-help');help.append(el('summary','','Как подключить Notion'));let node=first;while(node){const next=node.nextElementSibling;help.append(node);node=next}monoAgentBody.append(help)}
 }
 function monoNotionStatus(){
  const node=document.getElementById('monoNotionStatus');if(node)putText(node,ntData?.connected?'Notion подключён'+(ntData.agent?.name?' · '+ntData.agent.name:''):'Notion не подключён');
  const login=document.getElementById('ntLoginV');if(login&&ntData){login.className=ntData.connected?'ok':'bad';putText(login,tr(ntData.connected?'ntLoginOk':'ntLoginBad'))}
 }
 paintMirrorPalette=function(){
  if(!mirrorState)return;mirrorTheme();
  const signature=JSON.stringify([monoView,mirrorState.revision,mirrorState.service,mirrorState.engines]);
  if(signature===monoSignature){monoNotionStatus();monoCenter();return}monoSignature=signature;
  const focus=document.activeElement,focusId=focus?.id,focusCard=focus?.closest('[data-profile-id]'),focusEngine=focus?.dataset.engine||focusCard?.dataset.engine,focusProfile=focusCard?.dataset.profileId,action=focus?.dataset.mirrorAction,setting=focus?.dataset.mirrorSetting;
  monoParkAgent();
  let html='<div class="mono-provider-grid">';
  for(const engine of ['claude','codex']){
   const state=mirrorState.engines[engine];html+='<section class="mono-provider" data-engine="'+engine+'" aria-label="Профили '+mirrorNames[engine]+'"><header class="mono-provider-head"><strong>'+mirrorNames[engine]+'</strong><span>'+acctEsc(state.label)+'</span></header>';
   html+=monoView==='profiles'?'<div class="cxplist" role="radiogroup" aria-label="Рабочий профиль '+mirrorNames[engine]+'">'+state.profiles.filter(p=>p.kind!=='reserve').map(p=>monoCard(engine,p,state)).join('')+'</div>'+monoReserve(engine,state,false):monoReserve(engine,state,true);
   html+='</section>';
  }
  html+='</div>';
  if(monoView==='reserve')html+='<section class="mono-agent"><header><strong>Общий Notion-агент</strong><span id="monoNotionStatus"></span></header><div id="monoAgentSlot"></div></section>';
  html+='<div class="mono-window-note">'+(monoView==='profiles'?'Ведущая указана первой. В оркестраторе каждый шаг подтверждает человек.':'Резерв работает без срока. Другая модель остаётся на паузе до возврата прежнего сценария.')+'</div>';
  profileRoot.innerHTML=html;
  if(monoView==='reserve'){
   document.getElementById('monoAgentSlot').append(monoAgentBody);
   if(!monoAgentReady&&ntData){ntRender();monoAgentReady=true}monoNotionStatus();
  }
  putText(paletteCurrent,monoView==='profiles'?'У каждой модели: 2 профиля + резерв':'Без таймеров');putText(paletteCount,monoView==='profiles'?'Claude + Codex · единый выбор':'Резерв Claude и Codex');putText(paletteHelp,'Esc — закрыть');
  paletteEmpty.hidden=true;if(monoView==='profiles')filterProfiles();repaintProfileResults();
  if(focusId&&document.getElementById(focusId))document.getElementById(focusId).focus({preventScroll:true});
  else if(focusEngine&&focusProfile){const card=profileRoot.querySelector('[data-engine="'+focusEngine+'"][data-profile-id="'+focusProfile+'"]'),target=action?card?.querySelector('[data-mirror-action="'+action+'"]'):setting?card?.querySelector('[data-mirror-setting="'+setting+'"]'):card;target?.focus({preventScroll:true})}
  paintMirrorWorkplace();monoCenter();
 }
 mirrorProfileClick=function(event){
  const card=event.target.closest('[data-profile-id]');if(!card)return;event.stopImmediatePropagation();if(event.target.closest('.mono-auto'))return;
  const engine=card.dataset.engine||mirrorEngine,action=event.target.closest('[data-mirror-action]')?.dataset.mirrorAction,id=card.dataset.profileId;
  if(action==='reserve-settings'){mirrorOpen(engine,'reserve');return}
  if(action==='info'){mirrorInfo[engine].has(id)?mirrorInfo[engine].delete(id):mirrorInfo[engine].add(id);monoSignature='';cxpRender();return}
  if(action==='stop'){mirrorStop(engine);return}
  if(action==='apply'||card.matches('.fleet-profile-card')&&!event.target.closest('.cxpinfo'))mirrorApply(engine,id);
 }
 const monoMount=mountMirrorProfiles;mountMirrorProfiles=function(){
  monoMount();nativeMirrorOpen=monoRawOpen;cxMenuPlace=monoCenter;cxMenuOpen=function(){mirrorOpen('codex')};
  const originalWorkplace=paintMirrorWorkplace;paintMirrorWorkplace=function(){originalWorkplace();for(const engine of ['claude','codex']){mirrorButtons[engine].setAttribute('aria-expanded',String(!menu.hidden&&monoView==='profiles'));mirrorReserves[engine].querySelector('.ntgbtn').setAttribute('aria-expanded',String(!menu.hidden&&monoView==='reserve'))}};
  for(const engine of ['claude','codex']){
   mirrorButtons[engine].addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();if(!menu.hidden&&monoView==='profiles')cxMenuClose();else mirrorOpen(engine)},true);
   mirrorReserves[engine].querySelector('.ntgbtn').addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();mirrorOpen(engine,'reserve')},true);
  }
  const renderAgent=ntRender;ntRender=function(){renderAgent();monoAgentLayout();monoNotionStatus()};
  const applyAgent=ntApply;ntApply=function(data){applyAgent(data);if(monoView==='reserve'&&!menu.hidden&&!monoAgentReady&&ntData){ntRender();monoAgentReady=true;monoCenter()}monoNotionStatus()};
  ntOpen=function(){mirrorOpen(mirrorEngine,'reserve')};
  const close=cxMenuClose;cxMenuClose=function(){monoParkAgent();monoSignature='';close()};
  new MutationObserver(()=>{if(!menu.hidden&&monoView==='profiles'&&matchMedia('(pointer:fine)').matches)profileRoot.querySelector('.fleet-profile-card.act[data-engine="'+mirrorEngine+'"]')?.focus({preventScroll:true})}).observe(menu,{attributes:true,attributeFilter:['hidden']});
  monoSignature='';paintMirrorPalette();if(monoPendingOpen){const pending=monoPendingOpen;monoPendingOpen=null;mirrorOpen(...pending)}
 }
 addEventListener('resize',()=>{if(!menu.hidden)monoCenter()});window.visualViewport?.addEventListener('resize',()=>{if(!menu.hidden)monoCenter()});
