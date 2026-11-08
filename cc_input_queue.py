"""Ordered inputs with bounded background preparation; no network/model dependencies."""
from collections import deque
from dataclasses import dataclass, field
import threading
import time


@dataclass(eq=False)
class Input:
    kind: str
    generation: int
    queued_at: float
    delivery: dict
    state: str = 'collecting'
    text: str = ''
    error: str = ''
    files: tuple = ()
    deadline: float = None
    cancelled: threading.Event = field(default_factory=threading.Event)
    prepare: object = None


class InputQueue:
    def __init__(self, limit=20, workers=2, timeout=30, cleanup=lambda files: None):
        self.limit, self.timeout, self.cleanup = limit, timeout, cleanup
        self.items, self.generation = [], 0
        self._condition = threading.Condition()
        self._jobs, self._threads = deque(), []
        self._workers, self.closed = workers, False

    def __len__(self):
        with self._condition:
            return len(self.items)

    def reserve(self, kind, delivery=None, text=None):
        with self._condition:
            if self.closed or len(self.items) >= self.limit:
                return None
            now = time.monotonic()
            entry = Input(kind, self.generation, now, dict(delivery or {}))
            if text is not None:
                entry.state, entry.text = 'ready', text
            else:
                entry.deadline = now + self.timeout
            self.items.append(entry)
            self._condition.notify_all()
            return entry

    def prepare(self, entry, callback):
        with self._condition:
            if not self._current(entry) or entry.state != 'collecting':
                return False
            entry.prepare, entry.state = callback, 'pending'
            self._jobs.append(entry)
            while len(self._threads) < self._workers:
                thread = threading.Thread(target=self._prepare_loop, daemon=True, name='bridge-media')
                self._threads.append(thread)
                thread.start()
            self._condition.notify_all()
            return True

    def _current(self, entry):
        return (not self.closed and entry.generation == self.generation
                and not entry.cancelled.is_set())

    def _expire(self, entry):
        if entry.state in ('collecting', 'pending', 'preparing') and time.monotonic() >= entry.deadline:
            entry.error = 'Загрузка картинки не завершилась вовремя. Пришли её ещё раз.'
            entry.state = 'failed'
            entry.cancelled.set()

    def _prepare_loop(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self.closed or self._jobs)
                if self.closed:
                    return
                entry = self._jobs.popleft()
                self._expire(entry)
                if not self._current(entry) or entry.state != 'pending':
                    continue
                entry.state = 'preparing'
            files, text, error = (), '', ''
            try:
                text, files = entry.prepare(entry)
                files = tuple(files)
            except Exception as exc:
                # Preparation supplies safe user-facing errors. Unknown errors never expose URLs/tokens.
                error = getattr(exc, 'public_message', None) or 'Не удалось подготовить картинку: '+type(exc).__name__
            discard = False
            with self._condition:
                self._expire(entry)
                entry.prepare = None
                if not self._current(entry) or entry.state != 'preparing':
                    discard = True
                elif error:
                    entry.error, entry.state = error, 'failed'
                else:
                    entry.text, entry.files, entry.state = text, files, 'ready'
                self._condition.notify_all()
            if discard or error:
                self.cleanup(files)

    def take_ready(self, limit=1):
        """Never wait for downloads. Failed entries also leave the head so later text can proceed."""
        ready = []
        with self._condition:
            while self.items and len(ready) < limit:
                entry = self.items[0]
                self._expire(entry)
                if entry.state not in ('ready', 'failed'):
                    break
                self.items.pop(0)
                entry.state = 'taken'
                ready.append(entry)
            self._condition.notify_all()
        return ready

    def wait(self, timeout=.05):
        with self._condition:
            self._condition.wait(timeout)

    def clear(self):
        files = []
        with self._condition:
            count = len(self.items)
            self.generation += 1
            for entry in self.items:
                entry.cancelled.set()
                entry.state = 'cancelled'
                files.extend(entry.files)
            self.items.clear()
            self._jobs.clear()
            self._condition.notify_all()
        self.cleanup(files)
        return count

    def close(self):
        with self._condition:
            self.closed = True
        self.clear()
        with self._condition:
            self._condition.notify_all()
