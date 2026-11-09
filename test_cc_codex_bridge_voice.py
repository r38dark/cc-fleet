"""Optional voice replies: local synthesis, Telegram delivery and text fallback."""
import contextlib
import http.server
import io
import json
import threading
import unittest
from unittest.mock import Mock, patch

import cc_codex_bridge as br
from test_cc_codex_bridge import Base


class VoiceSettings(Base):
    def test_opt_in_default(self):
        self.assertFalse(br.load()["voice_enabled"])
        self.assertEqual(br.load()["voice_speaker"], "aidar")

    def test_save_voice_and_preserve_on_unrelated_save(self):
        with patch.object(br.BRIDGE, "sync"):
            self.assertTrue(br.save({"voice_enabled": True, "voice_speaker": "aidar"})[0])
            self.assertTrue(br.save({"task_rights": "read"})[0])
        self.assertTrue(br.load()["voice_enabled"])
        self.assertEqual(br.public()["voice_speaker"], "aidar")
        self.assertTrue(br.public()["voice_enabled"])

    def test_invalid_settings_leave_config_unchanged(self):
        before = br.load()
        for settings in ({"voice_enabled": "false"}, {"voice_speaker": "unknown"}):
            self.assertFalse(br.save(settings)[0])
            self.assertEqual(br.load(), before)


class VoiceReplies(Base):
    def setUp(self):
        super().setUp()
        self.s = br.load()
        self.s.update(voice_enabled=True, voice_speaker="aidar")
        self.tts = self.enterContext(patch.object(br, "synthesize_voice", return_value=b"OggSvoice"))
        self.voice = self.enterContext(patch.object(br, "tg_voice"))
        self.images = self.enterContext(patch.object(br, "answer_images", return_value=("Текст ответа.", [])))

    def test_text_then_fresh_male_voice(self):
        events = []
        original = br.BRIDGE.send
        def send(text, s):
            events.append("text")
            return original(text, s)
        def synth(text, speaker):
            events.append("synthesis")
            return b"OggSfresh"
        self.tts.side_effect = synth
        self.voice.side_effect = lambda *args: events.append("voice")
        act = Mock()
        with patch.object(br.BRIDGE, "send", side_effect=send):
            self.assertTrue(br.BRIDGE.send_answer("input", act, self.s))
        self.assertEqual(events, ["text", "synthesis", "voice"])
        self.tts.assert_called_once_with("Текст ответа.", "aidar")
        self.voice.assert_called_once_with(self.s["token"], self.s["chat_id"], b"OggSfresh")
        self.assertEqual([c.args[0] for c in act.set.call_args_list], ["record_voice", "upload_voice", "typing"])

    def test_disabled_keeps_text_only(self):
        self.s["voice_enabled"] = False
        self.assertTrue(br.BRIDGE.send_answer("input", s=self.s))
        self.assertEqual(self.sent, ["Текст ответа."])
        self.tts.assert_not_called()
        self.voice.assert_not_called()

    def test_image_only_does_not_synthesize(self):
        self.images.return_value = ("", [("sample.png", b"png", "image/png")])
        with patch.object(br, "tg_photo") as photo:
            self.assertTrue(br.BRIDGE.send_answer("input", s=self.s))
        photo.assert_called_once()
        self.tts.assert_not_called()

    def test_text_failure_preserves_retry_without_voice(self):
        with patch.object(br.BRIDGE, "send", return_value=False):
            self.assertFalse(br.BRIDGE.send_answer("input", s=self.s))
        self.tts.assert_not_called()

    def test_synthesis_failure_keeps_delivered_text_and_restores_indicator(self):
        self.tts.side_effect = TimeoutError("do not log service details")
        act = Mock()
        with patch.object(br, "log") as log:
            self.assertTrue(br.BRIDGE.send_answer("input", act, self.s))
        self.assertEqual(self.sent[0], "Текст ответа.")
        self.assertIn("голосовое", self.sent[1])
        self.voice.assert_not_called()
        self.assertEqual(act.set.call_args.args, ("typing",))
        self.assertNotIn("service details", str(log.call_args))

    def test_voice_failure_does_not_retry_delivered_answer(self):
        self.voice.side_effect = br.TgError(500, "do not log a token URL")
        with patch.object(br, "log") as log:
            self.assertTrue(br.BRIDGE.send_answer("input", s=self.s))
        self.assertEqual(len(self.sent), 2)
        self.assertNotIn("token URL", str(log.call_args))


class VoiceTransport(unittest.TestCase):
    def test_real_loopback_speech_contract(self):
        seen = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OggSgenerated")
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with patch.object(br, "TTS_API", f"http://127.0.0.1:{server.server_port}/speak"):
                self.assertEqual(br.synthesize_voice("Привет.", "aidar"), b"OggSgenerated")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        self.assertEqual(seen, [("/speak", {"text": "Привет.", "voice": "aidar"})])

    def test_rejects_invalid_or_oversized_speech(self):
        for data, limit in ((b'{"error":"failed"}', 100), (b"OggSoversized", 5)):
            opener = Mock()
            opener.open.return_value = contextlib.closing(io.BytesIO(data))
            with patch.object(br.urllib.request, "build_opener", return_value=opener), patch.object(br, "VOICE_MAX_BYTES", limit):
                with self.assertRaises(ValueError):
                    br.synthesize_voice("Привет.", "aidar")

    def test_unsupported_voice_never_calls_service(self):
        with patch.object(br.urllib.request, "build_opener") as opener:
            with self.assertRaises(ValueError):
                br.synthesize_voice("Привет.", "unknown")
        opener.assert_not_called()

    def test_multipart_voice_and_receipt(self):
        result = {"voice": {"file_id": "fake"}, "chat": {"id": 100200300}, "from": {"id": 123456}}
        with patch.object(br, "_tg_open", return_value={"ok": True, "result": result}) as request:
            br.tg_voice("123456:fake", "100200300", b"OggStest")
        req, timeout = request.call_args.args
        self.assertTrue(req.full_url.endswith("/sendVoice"))
        self.assertIn(b'name="voice"; filename="reply.ogg"', req.data)
        self.assertIn(b"Content-Type: audio/ogg", req.data)
        self.assertIn(b"OggStest", req.data)
        self.assertEqual(timeout, 60)

    def test_rejects_wrong_target_sender_and_document(self):
        for result in (
            {"voice": {"file_id": "x"}, "chat": {"id": 999}, "from": {"id": 123456}},
            {"voice": {"file_id": "x"}, "chat": {"id": 100200300}, "from": {"id": 999}},
            {"document": {"file_id": "x"}, "chat": {"id": 100200300}, "from": {"id": 123456}},
            {"voice": {"file_id": "x"}, "audio": {}, "chat": {"id": 100200300}, "from": {"id": 123456}},
        ):
            with patch.object(br, "_tg_open", return_value={"ok": True, "result": result}):
                with self.assertRaises(br.TgError):
                    br.tg_voice("123456:fake", "100200300", b"OggStest")


if __name__ == "__main__":
    unittest.main()
