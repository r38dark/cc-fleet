 // Роли — черновик пользователя. До общей кнопки применения API не вызывается.
 let manualDraft=null,manualRevision=-1,manualDirty=false;
 const manualEngines=['claude','codex'];
 const manualOther=engine=>engine==='claude'?'codex':'claude';
 const manualSame=(a,b)=>manualEngines.every(engine=>a?.[engine]===b?.[engine]);
 const manualCurrent=()=>mirrorState?.manual_scenario?.choices||{claude:null,codex:'full'};
 paletteTools.remove();paletteFooter.remove();
 const manualThemeBefore=mirrorTheme;
 mirrorTheme=function(){manualThemeBefore();putText(paletteCurrent,monoView==='reserve'?'Без таймеров':'Роли выбираешь вручную')};
 function manualSync(){
  if(!manualDraft||!manualDirty){manualDraft={...manualCurrent()};manualRevision=mirrorState.revision;manualDirty=false}
 }
 function manualReason(engine,role){
  const other=manualOther(engine),op=manualDraft[other],name=mirrorNames[other];
  if(!op)return '';
  if(op==='full')return name+' Full работает самостоятельно. Сними этот выбор, чтобы включить '+mirrorNames[engine]+'.';
  if(op==='reserve')return name+' работает с Notion. Сними резерв в соседнем блоке, чтобы выбрать эту модель.';
  if(op==='orchestrator'&&role!=='executor')return name+' уже выбрана ведущей. Здесь доступна роль «Исполнитель».';
  if(op==='executor'&&role!=='orchestrator')return name+' уже выбрана исполнителем. Здесь доступна роль «Оркестратор».';
  return '';
 }
 function manualStatus(){
  const roles=manualEngines.map(engine=>manualDraft[engine]).filter(Boolean),lead=manualEngines.find(engine=>manualDraft[engine]==='orchestrator'),executor=manualEngines.find(engine=>manualDraft[engine]==='executor');
  if(manualRevision!==mirrorState.revision)return {valid:false,text:'Сценарий изменился в другом окне. Верни текущий выбор перед применением.',stale:true};
  if(lead&&executor)return {valid:true,text:mirrorNames[lead]+' → '+mirrorNames[executor]+' · ведущая и исполнитель'};
  const single=manualEngines.find(engine=>['full','reserve'].includes(manualDraft[engine]));
  if(single&&roles.length===1)return {valid:true,text:manualDraft[single]==='full'?mirrorNames[single]+' Full · самостоятельно; '+mirrorNames[manualOther(single)]+' не участвует':mirrorNames[single]+' + Notion · резерв; '+mirrorNames[manualOther(single)]+' на паузе'};
  if(lead&&roles.length===1)return {valid:false,text:mirrorNames[lead]+' — ведущая. Теперь выбери '+mirrorNames[manualOther(lead)]+' · исполнитель.'};
  if(executor&&roles.length===1)return {valid:false,text:mirrorNames[executor]+' — исполнитель. Теперь выбери '+mirrorNames[manualOther(executor)]+' · оркестратор.'};
  return {valid:false,text:'Выбери Full для одной модели или вручную собери пару: оркестратор → исполнитель.'};
 }
 function manualSelect(engine,role){
  if(mirrorBusy)return;manualSync();
  if(manualDraft[engine]!==role){const reason=manualReason(engine,role);if(reason){toast(reason);return}}
  manualDraft={...manualDraft,[engine]:manualDraft[engine]===role?null:role};manualDirty=!manualSame(manualDraft,manualCurrent());monoSignature='';cxpRender();
 }
 function manualCardTitle(engine,role){
  const other=manualOther(engine);
  if(role==='orchestrator'&&manualDraft[other]==='executor')return mirrorNames[engine]+' → '+mirrorNames[other]+' · ведущая';
  if(role==='executor'&&manualDraft[other]==='orchestrator')return mirrorNames[other]+' → '+mirrorNames[engine]+' · исполнитель';
  return mirrorNames[engine]+({full:' Full · самостоятельно',orchestrator:' · оркестратор',executor:' · исполнитель',reserve:' + Notion · резерв'}[role]);
 }
 function manualRoleCard(engine,role){
  const state=mirrorState.engines[engine],id=role==='full'?engine+'_solo_full':role,p=state.profiles.find(profile=>profile.id===id),selected=manualDraft[engine]===role,reason=manualReason(engine,role),info=mirrorInfo[engine].has(id),current=manualCurrent()[engine]===role;
  const kinds={full:'FULL',orchestrator:'ВЕДУЩАЯ',executor:'ИСПОЛНИТЕЛЬ'},copy={full:'Полные доступные права. Работает одна, вторая модель не участвует.',orchestrator:'Планирует и проверяет. Исполнителя выбираешь вручную напротив.',executor:'Выполняет подтверждённые шаги ведущей с пределом прав «дев».'};
  return '<div class="cxprof fleet-profile-card manual-role'+(selected?' act':'')+'" data-engine="'+engine+'" data-profile-id="'+id+'" data-id="'+id+'" data-manual-role="'+role+'" role="radio" aria-checked="'+selected+'" aria-disabled="'+!!reason+'" tabindex="0"'+(reason?' title="'+acctEsc(reason)+'"':'')+'><div class="mono-mode-head"><span class="mono-mode-kind">'+kinds[role]+'</span><span class="mono-mode-status">'+(reason?'Недоступно':current&&!manualDirty?'Работает сейчас':selected?'В твоём выборе':'')+'</span></div><div class="cxpt"><span class="cxpn"><span class="cxpnm">'+acctEsc(manualCardTitle(engine,role))+'</span></span><span class="cxps">'+copy[role]+'</span>'+(info?monoDetails(p):'')+'</div><div class="fleet-profile-card-footer"><span class="fleet-profile-choose">'+(selected?'✓ Выбрано · нажми, чтобы снять':reason?'Несовместимая роль':'Выбрать →')+'</span><button type="button" class="fleet-profile-more" aria-disabled="false" data-mirror-action="info" aria-expanded="'+info+'">'+(info?'Свернуть':'Подробнее')+'</button></div></div>';
 }
 function manualReserveCard(engine){
  const selected=manualDraft[engine]==='reserve',reason=manualReason(engine,'reserve');
  return '<section class="mono-reserve manual-role'+(selected?' act':'')+'" data-engine="'+engine+'" data-profile-id="reserve" data-manual-role="reserve" role="radio" aria-checked="'+selected+'" aria-disabled="'+!!reason+'" tabindex="0"'+(reason?' title="'+acctEsc(reason)+'"':'')+'><div class="mono-reserve-copy"><strong>'+acctEsc(manualCardTitle(engine,'reserve'))+'</strong><div class="cxps">Без ограничения срока · другая модель на паузе</div></div><div class="mirror-service-actions"><span class="fleet-profile-choose">'+(selected?'✓ Выбрано · нажми, чтобы снять':reason?'Несовместимая роль':'Выбрать →')+'</span><button type="button" aria-disabled="false" data-mirror-action="reserve-settings">Настройки</button></div></section>';
 }
 const manualPaletteBefore=paintMirrorPalette;
 paintMirrorPalette=function(){
  if(!mirrorState)return;if(monoView==='reserve'){manualPaletteBefore();return}manualSync();mirrorTheme();monoParkAgent();
  const scroll=profileBody.scrollTop,focused=document.activeElement,focusedCard=focused?.closest('[data-manual-role]'),focusEngine=focusedCard?.dataset.engine,focusRole=focusedCard?.dataset.manualRole,focusInfo=focused?.dataset.mirrorAction==='info',focusAction=focused?.dataset.manualAction;
  const status=manualStatus(),dirty=manualDirty,signature=JSON.stringify([mirrorState.revision,manualDraft,mirrorInfo.claude.size,mirrorInfo.codex.size,mirrorBusy]);
  if(signature===monoSignature){monoCenter();return}monoSignature=signature;
  let html='<div class="mono-provider-grid manual-provider-grid">';
  for(const engine of manualEngines){
   const other=manualOther(engine),op=manualDraft[other],own=manualDraft[engine],hint=own==='orchestrator'&&op==='executor'?'Ведущая для '+mirrorNames[other]+' · исполнитель выбран вручную.':own==='executor'&&op==='orchestrator'?'Исполнитель '+mirrorNames[other]+' · ведущая выбрана вручную.':op==='full'?mirrorNames[other]+' Full: эта модель не участвует.':op==='reserve'?mirrorNames[other]+' + Notion: эта модель на паузе.':op==='orchestrator'?'Выбери исполнителя для '+mirrorNames[other]+'.':op==='executor'?'Выбери ведущую для '+mirrorNames[other]+'.':own==='orchestrator'?'Ведущая выбрана. Выбери исполнителя напротив.':own==='executor'?'Исполнитель выбран. Выбери ведущую напротив.':'Выбери роль. Повторное нажатие снимает выбор.';
   html+='<section class="mono-provider" data-engine="'+engine+'" aria-label="Роли '+mirrorNames[engine]+'"><header class="mono-provider-head"><strong>'+mirrorNames[engine]+'</strong><span>'+acctEsc(manualDraft[engine]?manualCardTitle(engine,manualDraft[engine]):'Не участвует в выборе')+'</span></header><p class="manual-compatibility"'+(['full','reserve'].includes(op)?' data-blocked="true"':'')+'>'+acctEsc(hint)+'</p><div role="radiogroup" aria-label="Роль '+mirrorNames[engine]+'">'+['full','orchestrator','executor'].map(role=>manualRoleCard(engine,role)).join('')+manualReserveCard(engine)+'</div></section>';
  }
  html+='</div><div class="manual-apply-bar"><div class="manual-selection-summary" role="status"><strong>'+(!dirty?'Работает на демо':status.valid?'Готово к применению':'Выбор не завершён')+'</strong><span>'+acctEsc(status.text)+'</span></div><div class="manual-scenario-actions"><button type="button" class="ghostbtn" data-manual-action="clear">Очистить выбор</button>'+(dirty?'<button type="button" class="ghostbtn" data-manual-action="restore">Вернуть текущий</button>':'')+'<button type="button" class="manual-apply" data-manual-action="apply" '+(!status.valid||!dirty||mirrorBusy?'disabled':'')+'>'+(mirrorBusy?'Применение…':!dirty?'Сценарий применён':'Применить сценарий')+'</button></div></div>';
  profileRoot.innerHTML=html;paletteEmpty.hidden=true;profileBody.scrollTop=scroll;
  if(focusEngine&&focusRole){const node=profileRoot.querySelector('[data-engine="'+focusEngine+'"][data-manual-role="'+focusRole+'"]');(focusInfo?node?.querySelector('[data-mirror-action="info"]'):node)?.focus({preventScroll:true})}
  else if(focusAction)profileRoot.querySelector('[data-manual-action="'+focusAction+'"]')?.focus({preventScroll:true});
  paintMirrorWorkplace();monoCenter();
 }
 const manualClickBefore=mirrorProfileClick;
 mirrorProfileClick=function(event){
  if(monoView!=='profiles')return manualClickBefore(event);
  const action=event.target.closest('[data-manual-action]')?.dataset.manualAction;
  if(action){event.stopImmediatePropagation();if(mirrorBusy)return;if(action==='apply'){manualApplyScenario();return}manualDraft=action==='restore'?{...manualCurrent()}:{claude:null,codex:null};manualRevision=mirrorState.revision;manualDirty=!manualSame(manualDraft,manualCurrent());monoSignature='';cxpRender();return}
  const card=event.target.closest('[data-manual-role]');if(!card)return;event.stopImmediatePropagation();const engine=card.dataset.engine,role=card.dataset.manualRole,sub=event.target.closest('[data-mirror-action]')?.dataset.mirrorAction;
  if(sub==='reserve-settings'){mirrorOpen(engine,'reserve');return}
  if(sub==='info'){const id=card.dataset.profileId;mirrorInfo[engine].has(id)?mirrorInfo[engine].delete(id):mirrorInfo[engine].add(id);monoSignature='';cxpRender();return}
  if(!event.target.closest('.cxpinfo'))manualSelect(engine,role);
 }
 const manualApplyBefore=mirrorApply;
 mirrorApply=function(engine,id,confirmation=''){if(monoView==='profiles'&&!menu.hidden){manualSelect(engine,id.endsWith('_solo_full')?'full':id);return Promise.resolve()}return manualApplyBefore(engine,id,confirmation)};
 profileRoot.addEventListener('keydown',event=>{const card=event.target.closest('.mono-reserve[data-manual-role]');if(monoView!=='profiles'||!card||event.target!==card||!['Enter',' '].includes(event.key))return;event.preventDefault();event.stopImmediatePropagation();manualSelect(card.dataset.engine,'reserve')},true);
 async function manualApplyScenario(confirmation='',choices={...manualDraft},revision=manualRevision){
  if(mirrorBusy||!manualStatus().valid)return;mirrorBusy=true;menu.setAttribute('aria-busy','true');
  try{
   const response=await fetch(API+'profiles/scenario/apply',{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':TOKEN},body:JSON.stringify({choices,revision,confirm:confirmation})}),result=await response.json();
   if(result.confirmation_required){manualConfirmScenario(choices,revision,result.word);return}
   if(!result.ok){toast(result.message||'Не удалось применить сценарий');if(result.conflict)await mirrorLoad();return}
   manualDirty=false;manualDraft=null;monoSignature='';mirrorAccept(result.state);toast(result.message);cxbLoad(true);
  }catch(_){toast('Не удалось применить сценарий. Текущий сценарий продолжает работать.')}
  finally{mirrorBusy=false;menu.removeAttribute('aria-busy');monoSignature='';if(!menu.hidden)cxpRender()}
 }
 function manualConfirmScenario(choices,revision,word){
  const engine=manualEngines.find(e=>choices[e]),name=manualCardTitle(engine,choices[engine]),other=mirrorNames[manualOther(engine)];cxMenuClose();
  acctShow('<div class="mirror-confirm" data-engine="'+engine+'"><h3>'+acctEsc(name)+'</h3><p>'+other+' не участвует в этом сценарии. '+(choices[engine]==='reserve'?'Резерв с Notion работает без ограничения срока.':'Работает только '+mirrorNames[engine]+' с полными доступными правами.')+'</p><p>Введи <b>'+acctEsc(word)+'</b>, чтобы применить весь сценарий на демо.</p><input id="manualConfirmWord" class="dlginp" autocomplete="off" spellcheck="false" aria-label="Слово подтверждения"><div class="modalfoot"><button type="button" id="manualConfirmCancel" class="ghostbtn">Отмена</button><button type="button" id="manualConfirmApply" disabled>Применить сценарий</button></div></div>');
  const input=document.getElementById('manualConfirmWord'),button=document.getElementById('manualConfirmApply');input.oninput=()=>button.disabled=input.value.trim().toLocaleLowerCase('ru')!==word;input.onkeydown=event=>{if(event.key==='Enter'&&!button.disabled)button.click()};document.getElementById('manualConfirmCancel').onclick=()=>{acctClose();mirrorOpen(engine)};button.onclick=()=>{const value=input.value;acctClose();manualApplyScenario(value,choices,revision).then(()=>mirrorOpen(engine))};setTimeout(()=>input.focus(),30);
 }
