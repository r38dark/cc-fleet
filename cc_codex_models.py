"""Ручная фоновая проверка каталога активного аккаунта Codex."""
import copy
import threading
import time


class Discovery:
    def __init__(self, codex, rotation, binary):
        self.codex, self.rotation, self.binary = codex, rotation, binary
        self.lock = threading.Lock()
        self.state = dict(ok=True, checking=False, slot='', checked_at=None, models=[], new_ids=[], message='')

    def public(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def start(self):
        with self.lock:
            if self.state['checking']:
                return copy.deepcopy(self.state)
            binary, slot = self.binary(), self.rotation.active()
            if not binary or slot not in self.codex.profile_slots():
                return dict(ok=False, checking=False, message='Сначала выбери аккаунт Codex с выполненным входом.')
            with self.rotation.lock:
                account = next((r for r in self.rotation.accounts if r['slot'] == slot), {})
                known = {m['id'] for m in account.get('models') or []}
            self.state = dict(ok=True, checking=True, slot=slot, checked_at=None, models=[], new_ids=[],
                              message='Проверяем новые модели…')
        threading.Thread(target=self._work, args=(binary, slot, known), name='codex-model-discovery', daemon=True).start()
        return self.public()

    def _work(self, binary, slot, known):
        try:
            models = self.codex.refresh_models(binary, slot)
            self.rotation.publish_models(slot, models)
            added = [m['id'] for m in models if m['id'] not in known] if known else []
            message = ('Найдено новых моделей: '+str(len(added))+'.' if added else 'Список моделей актуален.')
            result = dict(ok=True, models=models, new_ids=added, message=message)
        except Exception:
            # Не отправляем в браузер сырые ошибки RPC/авторизации.
            result = dict(ok=False, models=[], new_ids=[],
                          message='Не удалось проверить модели. Проверь вход в аккаунт и повтори попытку. Прежний список сохранён.')
        with self.lock:
            self.state.update(result, checking=False, checked_at=time.time())
