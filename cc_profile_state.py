"""Deterministic profile scenarios. Runtime effects belong to cc_profiles."""
import copy,threading,time
ENGINES=('claude','codex')
class ProfileScenarios:
 def __init__(self,clock=time.time):
  self.clock=clock;self.lock=threading.RLock();self.revision=0;self.leader=None;self.service=None;self.restore=None
  self.selected={'claude':'claude','codex':'codex_solo_full'};self.last_solo=dict(self.selected);self.custom={e:[] for e in ENGINES};self.until=0
  self.auto={e:dict(enabled=False,emergency=False) for e in ENGINES};self.availability={e:True for e in ENGINES};self.auto_blocked=set()
 def other(self,e):return 'codex' if e=='claude' else 'claude'
 def actor(self,e):return {'claude':'Claude','codex':'Codex'}[e]
 def definitions(self,e):
  a,b=self.actor(e),self.actor(self.other(e))
  return [dict(id='orchestrator',title=a+' → '+b,kind='orchestrator',mode='orchestrator',access='read',builtin=True,description=a+' ведёт задачу, '+b+' исполняет шаги после подтверждения.',can='Планировать шаги, передавать исполнителю и проверять результат.',cannot='Передавать изменения без подтверждения и создавать встречную связку.',when='Нужна работа двух исполнителей с одним ведущим.',flow=[a,'Твоё подтверждение',b,a+' проверяет']),
   dict(id=e,title=a+' · самостоятельно',kind='solo',mode='self',access='write',builtin=True,description='Самостоятельная работа в своей рабочей папке. Проект доступен для чтения.',can='Отвечать, читать проект и работать с файлами в своей папке.',cannot='Менять проект или подключать второго исполнителя.',when='Нужна отдельная самостоятельная задача.',flow=[a,'Ответ и файлы']),
   dict(id=e+'_solo_full',title=a+' Full · самостоятельно',kind='full',mode='self',access='full',builtin=True,description='Полная песочница исполнителя в пределах прав его пользователя ОС.',can='Выполнять доступные пользователю команды и работать с файлами.',cannot='Самостоятельно получать новые права ОС или доступы к серверам.',when='Нужна самостоятельная работа с расширенным доступом.',flow=[a+' Full','Ответ и файлы']),
   dict(id='reserve',title=a+' + Notion · резерв',kind='reserve',mode='self',access='write',builtin=True,description='Когда '+b+' недоступен, '+a+' продолжает работу вместе с агентом. '+b+' находится на паузе.',can='Продолжать работу резервной стороной и вернуть прежний сценарий при отключении.',cannot='Запускать два противоположных резерва одновременно.',when='Основной исполнитель недоступен.',flow=[a,'Notion',a+' проверяет']),
   dict(id='emergency',title=a+' · самостоятельно · аварийный',kind='emergency',mode='self',access='full',builtin=True,description='Отдельный аварийный сценарий с подтверждением словом и сроком действия.',can='Работать в пределах отдельно настроенного аварийного доступа.',cannot='Получать права сверх заданной конфигурации или сохранять их после срока.',when='Нужно восстановить работу при недоступности другой стороны.',flow=[a,'Подтверждение','Срок 2 часа'])]+copy.deepcopy(self.custom[e])
 def _stop_pair(self):
  if self.leader:
   self.selected[self.leader]=self.last_solo[self.leader];self.leader=None
 def _base(self):return dict(selected=copy.deepcopy(self.selected),last_solo=copy.deepcopy(self.last_solo),leader=self.leader)
 def _expire(self):
  if self.service and self.until and self.clock()>=self.until:
   self.auto_blocked.add(self.service['engine']);self._restore()
 def _restore(self):
  if self.restore:
   self.selected=self.restore['selected'];self.last_solo=self.restore['last_solo'];self.leader=self.restore['leader']
  self.service=None;self.restore=None;self.until=0;self.revision+=1
 def _reconcile(self):
  self._expire()
  for e in ENGINES:
   if self.availability[self.other(e)]:self.auto_blocked.discard(e)
  if self.service and self.service.get('source')=='auto':
   e=self.service['engine']
   if self.availability[self.other(e)] or not self.availability[e] or not self.auto[e]['enabled']:self._restore()
  if not self.service:
   for e in ENGINES:
    if self.auto[e]['enabled'] and e not in self.auto_blocked and self.availability[e] and not self.availability[self.other(e)]:
     self.restore=self._base();self._stop_pair();self.service=dict(engine=e,kind='reserve',source='auto',emergency=self.auto[e]['emergency']);self.until=self.clock()+7200 if self.auto[e]['emergency'] else 0;self.revision+=1;break
 def _check_revision(self,revision):
  return dict(ok=False,message='Сценарий уже изменился. Обнови выбор.',conflict=True) if revision is not None and revision!=self.revision else None
 def configure(self,e,enabled,emergency,confirm='',revision=None):
  with self.lock:
   self._reconcile()
   if e not in ENGINES:return dict(ok=False,message='Неизвестный исполнитель.')
   stale=self._check_revision(revision)
   if stale:return stale
   if type(enabled) is not bool or type(emergency) is not bool:return dict(ok=False,message='Неверные настройки резерва.')
   if emergency and not enabled:return dict(ok=False,message='Сначала включи автоматический резерв.')
   word='аварийный' if emergency and not self.auto[e]['emergency'] else 'подтверждаю' if enabled and not self.auto[e]['enabled'] else ''
   if word and str(confirm).casefold().strip()!=word:return dict(ok=False,confirmation_required=True,word=word,message='Подтверди автоматический резерв.')
   if self.auto[e]!=dict(enabled=enabled,emergency=emergency):
    self.auto[e]=dict(enabled=enabled,emergency=emergency);self.revision+=1
    if self.service and self.service['engine']==e and self.service.get('source')=='auto':self._restore()
   return dict(ok=True,message='Настройки резерва сохранены.',state=self.public())
 def set_availability(self,e,available):
  # Only the isolated test server supplies availability; never queries real accounts.
  with self.lock:
   if e not in ENGINES or type(available) is not bool:return dict(ok=False)
   self.availability[e]=available;return dict(ok=True,state=self.public())
 def public(self):
  with self.lock:
   self._reconcile();engines={}
   for e in ENGINES:
    role='solo'
    if self.service:role='reserve' if e==self.service['engine'] and self.service['kind']=='reserve' else 'emergency' if e==self.service['engine'] else 'paused'
    elif self.leader:role='leader' if e==self.leader else 'executor'
    selected=self.service['kind'] if self.service and e==self.service['engine'] else self.selected[e]
    definitions=self.definitions(e);item=next((p for p in definitions if p['id']==selected),{})
    label=item.get('title',selected)
    if role=='executor':label=self.actor(self.leader)+' → '+self.actor(e)+(' Full' if item.get('access')=='full' else '')+' · исполнитель'
    if role=='paused':label=self.actor(e)+(' Full' if item.get('access')=='full' else '')+' · на паузе'
    engines[e]=dict(id=e,title=self.actor(e),selected=selected,base_selected=self.selected[e],role=role,label=label,profiles=definitions,auto=copy.deepcopy(self.auto[e]),auto_blocked=e in self.auto_blocked,until=self.until if self.service and e==self.service['engine'] else 0)
   return dict(ok=True,available=True,demo=True,revision=self.revision,leader=self.leader,follower=self.other(self.leader) if self.leader else None,service=copy.deepcopy(self.service),engines=engines)
 def apply(self,e,pid,confirm='',revision=None):
  with self.lock:
   self._reconcile()
   if e not in ENGINES:return dict(ok=False,message='Неизвестный исполнитель.')
   stale=self._check_revision(revision)
   if stale:return stale
   p=next((p for p in self.definitions(e) if p['id']==pid),None)
   if not p:return dict(ok=False,message='Профиль не найден.')
   word='аварийный' if p['kind']=='emergency' else 'подтверждаю' if p['kind'] in ('full','reserve') else ''
   already=self.public()['engines'][e]['selected']==pid and self.public()['engines'][e]['role'] not in ('executor','paused')
   if already:return dict(ok=True,message='Этот профиль уже выбран.',state=self.public())
   if word and str(confirm).casefold().strip()!=word:return dict(ok=False,confirmation_required=True,word=word,message='Подтверди выбор профиля '+p['title']+'.')
   if self.service:self._restore()
   self.auto_blocked.update(e for e in ENGINES if not self.availability[self.other(e)])
   if p['kind'] in ('reserve','emergency'):
    self.restore=self._base();self._stop_pair();self.service=dict(engine=e,kind=p['kind'],source='manual',emergency=p['kind']=='emergency');self.until=self.clock()+7200 if p['kind']=='emergency' else 0
   else:
    self._stop_pair();self.selected[e]=pid
    if p['kind']=='orchestrator':self.leader=e
    else:self.last_solo[e]=pid
   self.revision+=1;return dict(ok=True,message='Сценарий выбран.',state=self.public())
 def stop_service(self,e,revision=None):
  with self.lock:
   if e not in ENGINES:return dict(ok=False,message='Неизвестный исполнитель.')
   stale=self._check_revision(revision)
   if stale:return stale
   if self.service and self.service['engine']!=e:return dict(ok=False,message='Режим включён у другой стороны.')
   self.auto_blocked.add(e)
   if self.service:self._restore()
   return dict(ok=True,message='Предыдущий сценарий восстановлен.',state=self.public())
 def delete(self,e,pid,revision=None):
  with self.lock:
   if e not in ENGINES:return dict(ok=False,message='Неизвестный исполнитель.')
   stale=self._check_revision(revision)
   if stale:return stale
   item=next((p for p in self.definitions(e) if p['id']==pid),None)
   if not item or item.get('builtin'):return dict(ok=False,message='Встроенный профиль удалять нельзя.')
   if self.selected[e]==pid:return dict(ok=False,message='Сначала выбери другой профиль.')
   self.custom[e]=[p for p in self.custom[e] if p['id']!=pid];self.revision+=1;return dict(ok=True,state=self.public())


class ProfileState(ProfileScenarios):
    """Reads never trigger runtime changes; the coordinator advances time explicitly."""
    FIELDS = ('revision', 'leader', 'service', 'restore', 'selected', 'last_solo',
              'custom', 'until', 'auto', 'availability', 'auto_blocked')

    def _reconcile(self):
        pass

    def export(self):
        out = {k: copy.deepcopy(getattr(self, k)) for k in self.FIELDS}
        out['auto_blocked'] = sorted(self.auto_blocked)
        return out

    @classmethod
    def from_data(cls, data, clock=time.time):
        state = cls(clock)
        for key in cls.FIELDS:
            if key in data:
                setattr(state, key, copy.deepcopy(data[key]))
        state.auto_blocked = set(state.auto_blocked)
        if set(state.selected) != set(ENGINES) or state.leader not in (None, *ENGINES):
            raise ValueError('invalid_profile_state')
        for e in ENGINES:
            if state.selected[e] not in {p['id'] for p in state.definitions(e)}:
                raise ValueError('unknown_stored_profile')
        return state

    def public(self):
        result = super().public()
        result.pop('demo', None)
        return result

    def delete(self, e, pid, revision=None):
        if e in ENGINES and (self.last_solo.get(e)==pid and self.selected.get(e)!=pid or self.restore and pid in (self.restore.get('selected',{}).get(e),self.restore.get('last_solo',{}).get(e))):
            return dict(ok=False,message='Профиль сохранён для возврата. Сначала заверши текущую связку или служебный режим.')
        return super().delete(e,pid,revision)
