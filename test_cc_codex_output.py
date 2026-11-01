"""Исходящие картинки: настоящий HTTP multipart к локальной заглушке, без Telegram."""
import base64
import email
import email.policy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import cc_codex_bridge as br
import test_cc_codex_bridge as support


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=")
JPEG = b"\xff\xd8\xff\xe0test image\xff\xd9"
IMAGE_NOTE = br.image_output_note


class Output(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = Path(self.tmp.name) / "work"
        self.cwd.mkdir()
        self.box = self.cwd / "outbox"
        self.box.mkdir()
        self.s = dict(br.DEFAULTS, mode="self", access="write", workdir=str(self.cwd),
                      token="123456:LOCAL_TEST_ONLY", chat_id="100200300")
        self.bot = br.Bridge()
        self.requests, self.logs = [], []
        self.failed_method = ""
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                method = self.path.rsplit("/", 1)[-1]
                body = self.rfile.read(int(self.headers["Content-Length"]))
                ctype = self.headers["Content-Type"]
                if ctype.startswith("multipart/"):
                    message = email.message_from_bytes(
                        ("Content-Type: " + ctype + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body,
                        policy=email.policy.default)
                    data = {p.get_param("name", header="content-disposition"): p for p in message.iter_parts()}
                else:
                    data = json.loads(body)
                owner.requests.append((method, data))
                failed = method == owner.failed_method
                self.send_response(400 if failed else 200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                result = {"ok": False, "error_code": 400, "description": "test failure"} if failed else {"ok": True, "result": {}}
                self.wfile.write(json.dumps(result).encode())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        for name, value in (("load", lambda: self.s), ("TG_API", "http://127.0.0.1:%d" % self.server.server_port),
                            ("log", self.logs.append)):
            p = patch.object(br, name, value)
            p.start()
            self.addCleanup(p.stop)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def put(self, name="shot.png", data=PNG):
        path = self.box / name
        path.write_bytes(data)
        return path

    def methods(self):
        return [m for m, _ in self.requests]

    def test_png_and_jpeg_are_uploaded_unchanged_after_text(self):
        self.put()
        self.put("other.jpg", JPEG)
        self.bot.send_answer("Проверил\n![Рамка](outbox/shot.png)\n![Другое](outbox/other.jpg)")
        self.assertEqual(self.methods(), ["sendMessage", "sendDocument", "sendDocument"])
        text = self.requests[0][1]["text"]
        self.assertIn("Проверил", text)
        self.assertIn("📎 Рамка", text)
        self.assertNotIn("outbox/", text)
        for (_, parts), expected, name in zip(self.requests[1:], (PNG, JPEG), ("shot.png", "other.jpg")):
            self.assertEqual(parts["chat_id"].get_content().strip(), self.s["chat_id"])
            self.assertEqual(parts["document"].get_filename(), name)
            self.assertEqual(hashlib.sha256(parts["document"].get_payload(decode=True)).digest(), hashlib.sha256(expected).digest())

    def test_absolute_sandbox_and_spaces_and_duplicate(self):
        path = self.put("my shot.png")
        self.bot.send_answer(f"![Скрин](<sandbox:{path}>)\n![Ещё](<outbox/my shot.png>)")
        self.assertEqual(self.methods().count("sendDocument"), 1)
        self.assertEqual(self.requests[-1][1]["document"].get_filename(), "my_shot.png")

    def test_examples_remote_and_service_messages_are_not_attachments(self):
        self.put()
        text = "Пример\n```markdown\n![](outbox/shot.png)\n```\n![Сайт](https://example.org/a.png)\n"
        self.bot.send_answer(text)
        self.assertEqual(self.methods(), ["sendMessage"])
        self.assertEqual(self.requests[0][1]["text"], text.strip())
        self.bot.send("![](outbox/shot.png)")
        self.assertEqual(self.methods(), ["sendMessage", "sendMessage"])

    def test_outside_symlink_missing_fifo_and_disguised_files_are_refused(self):
        outside = self.cwd / "secret.png"
        outside.write_bytes(PNG)
        (self.box / "link.png").symlink_to(outside)
        self.put("fake.png", b"private text")
        os.mkfifo(self.box / "pipe.png")
        for ref in ("outbox/../secret.png", str(outside), "outbox/link.png", "outbox/missing.png", "outbox/pipe.png", "outbox/fake.png"):
            with self.subTest(ref=ref):
                self.requests.clear()
                self.bot.send_answer(f"Ответ\n![]({ref})")
                self.assertEqual(self.methods(), ["sendMessage"])
                self.assertIn("⚠️", self.requests[0][1]["text"])

    def test_outbox_symlink_is_refused(self):
        self.box.rmdir()
        other = self.cwd / "other"
        other.mkdir()
        (other / "shot.png").write_bytes(PNG)
        self.box.symlink_to(other, target_is_directory=True)
        self.bot.send_answer("Ответ\n![](outbox/shot.png)")
        self.assertEqual(self.methods(), ["sendMessage"])
        self.assertIn("⚠️", self.requests[0][1]["text"])

    def test_limits_and_no_empty_message(self):
        for n in range(6):
            self.put(f"{n}.png")
        self.bot.send_answer("\n".join(f"![](outbox/{n}.png)" for n in range(6)))
        self.assertEqual(self.methods().count("sendDocument"), br.OUT_MAX_FILES)
        self.assertIn("⚠️", self.requests[0][1]["text"])
        self.requests.clear()
        with patch.object(br, "OUT_MAX_BYTES", 8):
            self.bot.send_answer("![](outbox/0.png)")
        self.assertEqual(self.methods(), ["sendMessage"])
        self.requests.clear()
        self.bot.send_answer("")
        self.assertEqual(self.requests, [])

    def test_upload_failure_keeps_text_and_masks_errors(self):
        self.put()
        self.failed_method = "sendDocument"
        self.bot.send_answer("Весь ответ\n![](outbox/shot.png)")
        self.assertEqual(self.methods(), ["sendMessage", "sendDocument", "sendMessage"])
        self.assertIn("Весь ответ", self.requests[0][1]["text"])
        self.assertIn("Не удалось", self.requests[-1][1]["text"])
        with patch.object(br, "tg_document", side_effect=OSError("http://host/bot" + self.s["token"])):
            self.bot.send_answer("Ответ\n![](outbox/shot.png)")
        self.assertNotIn(self.s["token"], str(self.logs))
        self.assertNotIn("/bot", str(self.logs))

    def test_text_failure_does_not_send_unexplained_files(self):
        self.put()
        self.failed_method = "sendMessage"
        self.bot.send_answer("Ответ\n![](outbox/shot.png)")
        self.assertEqual(self.methods(), ["sendMessage"])

    def test_ask_codex_uses_uploads_and_chat_action(self):
        self.put()
        with patch.object(br, "run_codex", return_value=("Ответ\n![](outbox/shot.png)", "test")):
            action = unittest.mock.Mock()
            self.bot.ask_codex("покажи скриншот", action)
        self.assertEqual(self.methods(), ["sendMessage", "sendDocument"])
        self.assertIn(unittest.mock.call("upload_document"), action.set.call_args_list)
        self.assertEqual(action.set.call_args_list[-1], unittest.mock.call("typing"))

    def test_output_dir_respects_existing_sandbox(self):
        self.assertEqual(br.output_dir(self.s), str(self.box))
        self.assertIn(str(self.box), IMAGE_NOTE(self.s))
        self.s["access"] = "read"
        self.assertEqual(IMAGE_NOTE(self.s), "")
        self.s.update(mode="mediator", exchange=str(self.cwd / "exchange"))
        self.assertEqual(br.output_dir(self.s), str(self.cwd / "exchange" / "outbox"))

    def test_workspace_symlink_accepts_alias_and_real_image_paths(self):
        path = self.put()
        alias = self.cwd.parent / "alias"
        alias.symlink_to(self.cwd, target_is_directory=True)
        self.s["workdir"] = str(alias)
        self.bot.send_answer(f"![]({alias}/outbox/shot.png)\n![]({path})")
        self.assertEqual(self.methods().count("sendDocument"), 1)

    def test_profile_change_during_run_uses_original_settings(self):
        self.put()
        original = dict(self.s)

        def answer(*args):
            self.s = dict(self.s, token="", chat_id="", workdir=str(self.cwd.parent / "other"))
            return "Ответ\n![](outbox/shot.png)", "test"

        with patch.object(br, "run_codex", side_effect=answer):
            self.bot.ask_codex("скриншот", unittest.mock.Mock())
        self.assertEqual(self.methods(), ["sendMessage", "sendDocument"])
        self.assertEqual(self.requests[1][1]["chat_id"].get_content().strip(), original["chat_id"])


class OutputHints(support.Base):
    def test_hint_goes_to_exec_and_console_without_changing_permissions(self):
        self.image_note_patch.stop()
        self.say("покажи скриншот")
        argv = self.runs()[0]["argv"]
        self.assertIn("![подпись](outbox/имя.png)", argv[-1])
        self.assertIn(os.path.join(self.ex, "outbox"), argv[-1])
        self.assertEqual(argv[argv.index("-s") + 1], "workspace-write")
        self.assertNotIn("--add-dir", argv)
        console = support.FakeConsole()
        br.CONSOLE = console
        self.say("ещё скриншот")
        self.assertIn("![подпись](outbox/имя.png)", console.asked[0])


if __name__ == "__main__":
    unittest.main()
