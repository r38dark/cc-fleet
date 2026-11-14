"""Настоящий перенос работы между Claude DEV и Claude PROD: _on_job и _off_job выполняются целиком, подменены только ssh, rsync и запуск.

Раньше во всех тестах эти две функции были заглушками, поэтому зелёные тесты не показывали главного: получит ли тот, кто
подхватывает работу, место, где остановился прежний. Здесь проверяется именно это: что попало в записку, что скопировано,
что проверено и что сказано владельцу."""
import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import cc_workers as N
import cc_remote
import cc_remote_mode as M
from test_cc_handoff_tail import reply, result, say, tg

FRIEND_MD = 'правила для Claude PROD'


class Wk:
    """Настоящие методы записки cc_workers.Workers на временных папках; остальное — заглушки."""
    handoff_sync_dir = N.Workers.handoff_sync_dir
    handoff_project_dir = N.Workers.handoff_project_dir
    handoff_transcripts = N.Workers.handoff_transcripts
    handoff_write = N.Workers.handoff_write
    handoff_refresh_owner_last = N.Workers.handoff_refresh_owner_last
    handoff_tail_state = N.Workers.handoff_tail_state

    def __init__(self, base):
        self.ns = {'BASE': base}
        self.running = True
        self.started = 0
        self.stopped = 0
        self.sync_calls = []
        self.sync_ok = True
        self.later = []
        self.thread_id = None   # беседа живого Claude; у погашенного её не определить, как и у настоящего capture()

    def claude_running(self):
        return self.running

    def screen_busy(self):
        return self.running

    def stop_claude(self):
        self.running = False
        self.stopped += 1
        return True

    def start_claude(self):
        self.running = True
        self.started += 1
        return True

    def claude_snapshot(self):
        return {'thread_id': self.thread_id} if self.running and self.thread_id else None

    def handoff_sync(self, target):
        self.sync_calls.append(target)
        return self.sync_ok

    def _later(self, fn, *args):
        self.later.append((fn.__name__, args))


class Transfer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, 'base')
        self.hist = os.path.join(self.tmp, 'hist')        # беседы Claude на dev
        self.prod = os.path.join(self.tmp, 'prod_hist')   # беседы Claude на PROD
        for d in (self.base, self.hist, self.prod, self.base + '/profile_runtime'):
            os.makedirs(d)
        self.project = Path(self.base) / 'profile_exchange/codex/outbox/agent_handoff/current_project'
        self.project.mkdir(parents=True)
        (self.project / 'card.md').write_text('# Карточка\nЦель: тест передачи\n')
        self.files = (M.MODE_FILE, cc_remote.MEMBERS_FILE, cc_remote.STATE_FILE)
        cc_remote.MEMBERS_FILE = os.path.join(self.tmp, 'm.json')
        cc_remote.STATE_FILE = os.path.join(self.tmp, 's.json')
        M.MODE_FILE = os.path.join(self.tmp, 'mode.json')
        with open(cc_remote.MEMBERS_FILE, 'w') as f:
            json.dump({'prod': {'label': 'Claude PROD', 'host': '192.0.2.1', 'tmux': 'friend'}}, f)
        self.wk = Wk(self.base)
        self.notes = []
        self.events = []      # порядок действий: ('ctl', 'stop'), ('rsync', путь) ...
        self.ctl_args = []    # полные команды ctl.py
        self.briefs = []      # тексты, отправленные Claude на PROD
        self.pending = 0
        self.sha_ok = True
        self.size_delta = 0
        self.prod_names = []  # беседы на PROD, которые найдёт find
        self.on_stop = None   # что происходит на PROD в момент остановки
        self.rsync_extra = []  # дополнительные ключи rsync у каждой копии беседы
        self.saved = (M.PROJ, M._NS.copy(), N.CLAUDE_HISTORY_DIR, M._notify, M.R.ssh_run, M.rsync, M.rsync_pending, M.remote_sha,
                      M.remote_size, M.ctl, M.deploy_tools, M.put_file, M.freeze_screen, M.friend_claude_md)
        M.PROJ = self.hist
        N.CLAUDE_HISTORY_DIR = self.hist
        M._NS.clear()
        M._NS.update(WORKERS=self.wk, BASE=self.base, tg_notify=lambda t: None)
        M._wcache.update(ts=0.0, val='dev', key=None)
        M._notify = self.notes.append
        M.R.ssh_run = self.fake_ssh
        M.rsync = self.fake_rsync
        M.rsync_pending = lambda m, src, dst, to_remote: self.pending
        M.remote_sha = lambda m, path: hashlib.sha256(FRIEND_MD.encode()).hexdigest() if self.sha_ok else 'bad'
        M.remote_size = lambda m, path: self.fake_size(path)
        M.ctl = self.fake_ctl
        M.deploy_tools = lambda m: True
        M.put_file = lambda m, data, remote, mode_bits='644': True
        M.freeze_screen = lambda mid: None
        M.friend_claude_md = lambda: FRIEND_MD

    def tearDown(self):
        (M.PROJ, ns, N.CLAUDE_HISTORY_DIR, M._notify, M.R.ssh_run, M.rsync, M.rsync_pending, M.remote_sha,
         M.remote_size, M.ctl, M.deploy_tools, M.put_file, M.freeze_screen, M.friend_claude_md) = self.saved
        M._NS.clear()
        M._NS.update(ns)
        M.MODE_FILE, cc_remote.MEMBERS_FILE, cc_remote.STATE_FILE = self.files   # пути и состояние соседних тестов не трогаем
        M._wcache.update(ts=0.0, val='dev', key=None)

    # ── подмены ──────────────────────────────────────────────────────────────
    def fake_ssh(self, m, cmd, timeout=25, inp=None):
        if 'ctl.py tg 0' in cmd:
            self.events.append(('tg0',))
        if 'cc_msg.txt' in cmd and getattr(self, 'fail_brief', False):
            return 255, ''
        if 'cc_msg.txt' in cmd:
            self.briefs.append(inp)
            self.events.append(('brief',))
            return 0, ''
        if cmd.startswith('find '):
            return 0, '\n'.join(self.prod_names)
        return 0, ''

    def fake_rsync(self, m, src, dst, to_remote, extra=()):
        self.events.append(('rsync', src, to_remote))
        if src.endswith('.jsonl'):
            self.rsync_extra.append(tuple(extra))
        if to_remote and src.endswith('.jsonl') and os.path.isfile(src):   # dev -> PROD: беседа
            with open(src, 'rb') as a, open(os.path.join(self.prod, os.path.basename(src)), 'wb') as b:
                b.write(a.read())
        if not to_remote and src.endswith('.jsonl'):   # PROD -> dev: копируем то, что лежит на «PROD» сейчас
            source = os.path.join(self.prod, os.path.basename(src))
            if os.path.isfile(source):
                with open(source, 'rb') as a, open(os.path.join(self.hist, os.path.basename(src)), 'wb') as b:
                    b.write(a.read())
        return True

    def fake_size(self, path):
        name = os.path.join(self.prod, os.path.basename(path))
        return os.path.getsize(name) + self.size_delta if os.path.isfile(name) else -1

    def fake_ctl(self, m, args, timeout=150):
        self.events.append(('ctl', args.split()[0]))
        self.ctl_args.append(args)
        if args.startswith('start') and getattr(self, 'start_fails', False):
            return {'ok': False, 'error': 'не стартовал'}
        if args.startswith('start') and getattr(self, 'resume_fails', False) and args.split()[1] != '-':
            return {'ok': False, 'error': 'exited'}   # беседу PROD не открыл, чистый старт проходит
        if args.startswith('stop') and self.on_stop:
            self.on_stop()
        return {'ok': True, 'busy': False}

    # ── вспомогательное ──────────────────────────────────────────────────────
    def write_conversation(self, folder, name, lines, ago=30):
        path = os.path.join(folder, name + '.jsonl')
        Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
        stamp = time.time() - ago
        os.utime(path, (stamp, stamp))
        return path

    def answered(self, text='вопрос владельца'):
        return [tg('1', '2026-11-07T09:20:00.000Z', text), reply('2026-11-07T09:20:10.000Z', 'r', 'ответ'),
                result('2026-11-07T09:20:11.000Z', 'r', 'sent'), say('2026-11-07T09:20:12.000Z', 'готово')]

    def unanswered(self, text='доделай правку'):
        return [say('2026-11-07T09:19:00.000Z', 'предыдущее готово'), tg('2', '2026-11-07T09:20:00.000Z', text)]

    def last_note(self):
        self.assertTrue(self.notes, 'уведомление не отправлено')
        return self.notes[-1]

    # ── dev -> PROD ──────────────────────────────────────────────────────────
    def test_to_prod_brief_carries_unfinished_work(self):
        self.write_conversation(self.hist, 'dev1', self.unanswered())
        res = M._on_job('prod', 'автопередача: у Claude DEV нет лимита', '', False)
        self.assertTrue(res['ok'])
        brief = self.briefs[-1]
        self.assertIn('=== handoff_tail.md ===', brief)
        self.assertIn('STATE: UNFINISHED', brief)
        self.assertIn('доделай правку', brief)
        self.assertIn('Продолжи с последнего шага оттуда', brief)
        self.assertNotIn('Работу сам не начинай', brief)
        self.assertTrue(M.mode()['active'])
        self.assertEqual(self.wk.stopped, 1)

    def test_to_prod_resume_takes_snapshot_before_stop(self):
        sid = '11111111-2222-3333-4444-555555555555'
        self.wk.thread_id = sid
        self.write_conversation(self.hist, sid, self.unanswered())
        res = M._on_job('prod', 'с продолжением', '', True)
        self.assertTrue(res['ok'])
        start = [a for a in self.ctl_args if a.startswith('start')][0]
        self.assertEqual(start, 'start %s 1' % sid)                      # PROD продолжает ту же беседу, а не пустую
        self.assertIn(('rsync', '%s/%s.jsonl' % (self.hist, sid), True), self.events)
        self.assertTrue(M.mode()['resume'])
        self.assertTrue(M.mode()['delivery_ok'], M.mode().get('delivery'))   # размер беседы на PROD сверен
        self.assertIn('беседа', M.mode()['delivery'])
        self.assertEqual(self.wk.stopped, 1)

    def test_to_prod_resume_of_stopped_claude_starts_clean(self):
        self.wk.thread_id = '11111111-2222-3333-4444-555555555555'
        self.wk.running = False                                          # Claude уже остановлен: беседы не видно
        self.write_conversation(self.hist, 'dev1', self.unanswered())
        res = M._on_job('prod', 'с продолжением', '', True)
        self.assertTrue(res['ok'])
        self.assertEqual([a for a in self.ctl_args if a.startswith('start')], ['start - 1'])
        self.assertFalse(M.mode()['resume'])

    SID = '11111111-2222-3333-4444-555555555555'

    def test_auto_handoff_carries_conversation_and_says_so(self):
        self.wk.thread_id = self.SID
        self.write_conversation(self.hist, self.SID, self.unanswered())
        res = M._on_job('prod', 'автопередача: лимит', '', True, auto=True)
        self.assertTrue(res['ok'])
        self.assertEqual([a for a in self.ctl_args if a.startswith('start')], ['start %s 1' % self.SID])
        self.assertIn('перенесена на этот сервер', self.briefs[-1])
        self.assertIn(('-z',), self.rsync_extra)                          # журнал беседы идёт сжатым
        self.assertTrue(M.mode()['delivery_ok'], M.mode().get('delivery'))

    def test_without_resume_brief_does_not_claim_the_conversation_moved(self):
        self.write_conversation(self.hist, 'dev1', self.unanswered())
        M._on_job('prod', 'по кнопке', '', False)
        self.assertNotIn('перенесена на этот сервер', self.briefs[-1])

    def test_oversized_conversation_is_not_moved_but_handoff_goes_on(self):
        self.wk.thread_id = self.SID
        self.write_conversation(self.hist, self.SID, self.unanswered())
        self.addCleanup(setattr, M, 'RESUME_MAX_BYTES', M.RESUME_MAX_BYTES)
        M.RESUME_MAX_BYTES = 10
        res = M._on_job('prod', 'автопередача: лимит', '', True, auto=True)
        self.assertTrue(res['ok'])
        self.assertEqual([a for a in self.ctl_args if a.startswith('start')], ['start - 1'])
        self.assertFalse(any(e[0] == 'rsync' and e[1].endswith('.jsonl') and e[2] for e in self.events))
        self.assertFalse(M.mode()['resume'])
        self.assertIn('беседа не перенесена', M.mode()['delivery'])
        self.assertNotIn('перенесена на этот сервер', self.briefs[-1])
        self.assertIn('STATE: UNFINISHED', self.briefs[-1])               # работа продолжается по карточке и хвосту

    def test_conversation_that_prod_cannot_open_falls_back_to_clean_start(self):
        self.wk.thread_id = self.SID
        self.write_conversation(self.hist, self.SID, self.unanswered())
        self.resume_fails = True
        res = M._on_job('prod', 'автопередача: лимит', '', True, auto=True)
        self.assertTrue(res['ok'])
        self.assertEqual([a for a in self.ctl_args if a.startswith('start')], ['start %s 1' % self.SID, 'start - 1'])
        self.assertTrue(M.mode()['active'])
        self.assertFalse(M.mode()['resume'])
        self.assertIn('не открылась', M.mode()['delivery'])
        self.assertNotIn('перенесена на этот сервер', self.briefs[-1])

    def test_failed_clean_start_after_failed_resume_still_returns_work_to_dev(self):
        self.wk.thread_id = self.SID
        self.write_conversation(self.hist, self.SID, self.unanswered())
        self.start_fails = True
        res = M._on_job('prod', 'автопередача: лимит', '', True, auto=True)
        self.assertFalse(res['ok'])
        self.assertFalse(M.mode()['active'])

    def test_auto_unclear_state_checks_card_instead_of_waiting_blindly(self):
        self.write_conversation(self.hist, 'dev1', [])                    # в беседе нет событий: STATE: UNKNOWN
        M._on_job('prod', 'автопередача: лимит', '', False, auto=True)
        brief = self.briefs[-1]
        self.assertIn('Сверь карточку', brief)
        self.assertIn('не начинай', brief)                                # открытого шага нет — не выдумывать работу
        self.assertNotIn('Работу сам не начинай и файлы не меняй', brief)

    def test_manual_unclear_state_still_waits_for_owner(self):
        self.write_conversation(self.hist, 'dev1', [])
        M._on_job('prod', 'по кнопке', '', False)
        self.assertIn('Работу сам не начинай', self.briefs[-1])
        self.assertNotIn('Сверь карточку', self.briefs[-1])

    def test_auto_finished_work_still_waits_for_owner(self):
        self.write_conversation(self.hist, 'dev1', self.answered())
        M._on_job('prod', 'автопередача: лимит', '', False, auto=True)
        self.assertIn('STATE: FINISHED', self.briefs[-1])
        self.assertIn('Работу сам не начинай', self.briefs[-1])           # завершённое не повторяем и нового не придумываем

    def test_to_prod_without_resume_ignores_snapshot(self):
        self.wk.thread_id = '11111111-2222-3333-4444-555555555555'
        self.write_conversation(self.hist, 'dev1', self.unanswered())
        M._on_job('prod', 'по кнопке', '', False)
        self.assertEqual([a for a in self.ctl_args if a.startswith('start')], ['start - 1'])
        self.assertFalse(any(e[0] == 'rsync' and e[1].endswith('.jsonl') and e[2] for e in self.events))

    def test_to_prod_finished_work_waits_for_owner(self):
        self.write_conversation(self.hist, 'dev1', self.answered())
        M._on_job('prod', 'по кнопке', '', False)
        brief = self.briefs[-1]
        self.assertIn('STATE: FINISHED', brief)
        self.assertIn('Работу сам не начинай', brief)

    def test_to_prod_refreshes_stale_files_before_brief(self):
        (self.project / 'owner_last.md').write_text('СТАРЫЙ ФАЙЛ')
        self.write_conversation(self.hist, 'dev1', self.answered('сегодняшний вопрос'))
        M._on_job('prod', 'по кнопке', '', False)
        self.assertIn('сегодняшний вопрос', self.briefs[-1])
        self.assertNotIn('СТАРЫЙ ФАЙЛ', self.briefs[-1])

    def test_to_prod_brief_failure_after_start_stops_prod_before_local_start(self):
        """R4-1: записка не ушла, когда Claude на PROD уже запущен: PROD гасим и Telegram там отключаем, иначе два слушателя бота."""
        self.write_conversation(self.hist, 'dev1', self.unanswered())
        self.fail_brief = True
        orig = self.wk.start_claude
        self.wk.start_claude = lambda: (self.events.append(('local_start',)), orig())[1]
        res = M._on_job('prod', 'по кнопке', '', False)
        self.assertFalse(res['ok'])
        self.assertFalse(M.mode()['active'])
        ev = self.events
        self.assertIn(('ctl', 'stop'), ev)
        self.assertIn(('tg0',), ev)
        self.assertIn(('local_start',), ev)
        self.assertLess(ev.index(('ctl', 'stop')), ev.index(('local_start',)))   # сначала гасим PROD, потом будим Claude DEV
        self.assertLess(ev.index(('tg0',)), ev.index(('local_start',)))
        self.assertEqual(self.wk.started, 1)

    def test_to_prod_failed_start_does_not_stop_prod_again(self):
        self.write_conversation(self.hist, 'dev1', self.unanswered())
        self.start_fails = True
        res = M._on_job('prod', 'по кнопке', '', False)
        self.assertFalse(res['ok'])
        self.assertNotIn(('ctl', 'stop'), self.events)
        self.assertIn(('tg0',), self.events)
        self.assertFalse(M.mode()['active'])

    def test_to_prod_check_crash_keeps_transfer_and_warns(self):
        """R4-1: записка уже у PROD, а сама проверка доставки упала (ssh): передача не откатывается, владелец получает ⚠️."""
        self.write_conversation(self.hist, 'dev1', self.unanswered())

        def boom(m, path):
            raise TimeoutError('ssh')
        M.remote_sha = boom
        res = M._on_job('prod', 'по кнопке', '', False)
        self.assertTrue(res['ok'])
        self.assertTrue(M.mode()['active'])
        self.assertNotIn(('ctl', 'stop'), self.events)    # PROD продолжает работать
        self.assertEqual(self.wk.started, 0)             # Claude DEV не будили
        self.assertFalse(M.mode()['delivery_ok'])
        self.assertIn('⚠️', self.last_note())

    def test_to_prod_success_message_lists_checks(self):
        self.write_conversation(self.hist, 'dev1', self.answered())
        M._on_job('prod', 'по кнопке', '', False)
        note = self.last_note()
        self.assertTrue(note.startswith('✅ Переход выполнен: теперь работает Claude PROD, все задачи продолжатся на нём.'), note)
        self.assertIn('Проверено:', note)
        self.assertIn('память', note)
        self.assertNotIn('родн', note.lower())
        self.assertNotIn('возвращена', note)
        self.assertTrue(M.mode()['delivery_ok'])

    def test_to_prod_warns_when_memory_not_delivered(self):
        self.write_conversation(self.hist, 'dev1', self.answered())
        self.pending = 3
        res = M._on_job('prod', 'по кнопке', '', False)
        self.assertTrue(res['ok'])
        note = self.last_note()
        self.assertTrue(note.startswith('⚠️ Переход на Claude PROD выполнен, но не всё подтверждено.'), note)
        self.assertIn('Не подтверждено: память.', note)
        self.assertFalse(M.mode()['delivery_ok'])
        self.assertTrue(M.mode()['active'])

    def test_to_prod_warns_when_rules_differ(self):
        self.write_conversation(self.hist, 'dev1', self.answered())
        self.sha_ok = False
        M._on_job('prod', 'по кнопке', '', False)
        self.assertIn('Не подтверждено: правила CLAUDE.md', self.last_note())

    def test_to_prod_warns_when_project_files_missing(self):
        (self.project / 'card.md').unlink()
        self.write_conversation(self.hist, 'dev1', self.answered())
        M._on_job('prod', 'по кнопке', '', False)
        self.assertIn('карточка, сообщения владельца и хвост беседы', self.last_note().split('Не подтверждено:')[-1])

    # ── PROD -> dev ──────────────────────────────────────────────────────────
    def go_back(self, restore=True):
        self.wk.running = False
        M._save(active=True, member='prod', tg=True, since_ts=time.time() - 3600, since=time.time() - 3600)
        return M._off_job('автовозврат: тест', False, restore)

    def test_back_uses_fresh_prod_conversation_not_stale_pointer(self):
        """Баг 07.11: указатель last-claude-session.json смотрел на старую беседу, и новый Claude получал чужие сообщения."""
        stale = self.write_conversation(self.hist, 'old0', [tg('9', '2026-11-06T10:00:00.000Z', 'старое сообщение')], ago=86400)
        (Path(self.base) / 'profile_runtime/last-claude-session.json').write_text(json.dumps(dict(history=stale)))
        self.write_conversation(self.prod, 'prod1', self.answered('вопрос с PROD'))
        self.prod_names = [os.path.join(self.hist, 'prod1.jsonl')]
        res = self.go_back()
        self.assertTrue(res['ok'])
        last = (self.project / 'owner_last.md').read_text()
        self.assertIn('вопрос с PROD', last)
        self.assertLess(last.index('старое сообщение'), last.index('вопрос с PROD'))   # свежее идёт последним, а не пропадает
        tail = (self.project / 'handoff_tail.md').read_text()
        self.assertIn('STATE: FINISHED', tail)
        self.assertIn('вопрос с PROD', tail)
        self.assertNotIn('старое сообщение', tail)   # беседа суточной давности в хвост не попадает

    def test_back_continues_unfinished_prod_work(self):
        self.write_conversation(self.prod, 'prod1', self.unanswered('закончи проверку на PROD'))
        self.prod_names = [os.path.join(self.hist, 'prod1.jsonl')]
        self.go_back()
        self.assertEqual(self.wk.handoff_tail_state(), 'unfinished')
        self.assertIn('закончи проверку на PROD', (self.project / 'handoff_tail.md').read_text())

    def test_back_copies_late_writes_after_prod_stops(self):
        """Claude на PROD мог дописать беседу уже после первого копирования: после остановки собираем ещё раз."""
        path = self.write_conversation(self.prod, 'prod1', self.answered('вопрос до остановки'))
        self.prod_names = [os.path.join(self.hist, 'prod1.jsonl')]

        def late_write():
            with open(path, 'a', encoding='utf-8') as f:
                f.write(tg('3', '2026-11-07T09:21:00.000Z', 'поздняя запись при остановке') + '\n')
        self.on_stop = late_write
        self.go_back()
        order = [e for e in self.events if e[0] in ('ctl', 'rsync')]
        stop_at = order.index(('ctl', 'stop'))
        self.assertTrue(any(e[0] == 'rsync' and e[1].endswith('prod1.jsonl') for e in order[stop_at:]), order)
        self.assertIn('поздняя запись при остановке', (self.project / 'owner_last.md').read_text())
        self.assertEqual(self.wk.handoff_tail_state(), 'unfinished')

    def test_back_success_message_and_delivery(self):
        self.write_conversation(self.prod, 'prod1', self.answered())
        self.prod_names = [os.path.join(self.hist, 'prod1.jsonl')]
        self.go_back()
        note = self.last_note()
        self.assertTrue(note.startswith('✅ Переход выполнен: теперь работает Claude DEV, все задачи продолжатся на нём.'), note)
        self.assertIn('Claude DEV получил записку', note)
        self.assertNotIn('родн', note.lower())
        self.assertNotIn('возвращена', note)
        self.assertEqual(self.wk.sync_calls, ['claude'])
        self.assertEqual(self.wk.started, 1)
        self.assertEqual(self.wk.later, [])
        self.assertFalse(M.mode()['active'])
        self.assertTrue(M.mode()['delivery_ok'])

    def test_back_warns_and_retries_when_note_not_delivered(self):
        self.write_conversation(self.prod, 'prod1', self.answered())
        self.prod_names = [os.path.join(self.hist, 'prod1.jsonl')]
        self.wk.sync_ok = False
        self.go_back()
        note = self.last_note()
        self.assertTrue(note.startswith('⚠️ Переход на Claude DEV выполнен, но не всё подтверждено.'), note)
        self.assertIn('Claude DEV получил записку', note.split('Не подтверждено:')[-1])
        self.assertEqual(self.wk.later, [('handoff_sync', ('claude',))])   # повтор позже, как и раньше

    def test_back_warns_when_conversation_size_differs(self):
        self.write_conversation(self.prod, 'prod1', self.answered())
        self.prod_names = [os.path.join(self.hist, 'prod1.jsonl')]
        self.size_delta = 5
        self.go_back()
        self.assertIn('беседа PROD скопирована', self.last_note().split('Не подтверждено:')[-1])

    def test_back_warns_when_no_conversation_found(self):
        self.go_back()
        self.assertIn('беседа PROD скопирована', self.last_note().split('Не подтверждено:')[-1])

    def test_handing_on_to_codex_does_not_claim_success_for_dev(self):
        self.write_conversation(self.prod, 'prod1', self.answered())
        self.prod_names = [os.path.join(self.hist, 'prod1.jsonl')]
        self.go_back(restore=False)
        note = self.last_note()
        self.assertTrue(note.startswith('⏹ Claude PROD остановлен'), note)
        self.assertEqual(self.wk.started, 0)
        self.assertEqual(self.wk.sync_calls, [])


if __name__ == '__main__':
    unittest.main()
