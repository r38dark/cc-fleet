"""The panel has one Claude label and keeps routing and console data intact."""
import unittest

import cc_labels


class ClaudeNameTests(unittest.TestCase):
    def test_product_labels(self):
        self.assertEqual(
            cc_labels.text("Claude DEV · Claude на PROD · Claude TPROD · Настройки PROD · PROD Full"),
            "Claude · Claude · Claude · Настройки Claude · Full",
        )

    def test_display_does_not_change_routing_identity(self):
        self.assertEqual(
            cc_labels.finish({"prod": {"id": "prod", "name": "Claude PROD"}, "slot": "DEV"}),
            {"prod": {"id": "prod", "name": "Claude"}, "slot": "DEV"},
        )

    def test_html_keeps_existing_routing_attributes(self):
        self.assertEqual(
            cc_labels.finish(b'<button data-s="prod">Claude PROD</button>', "text/html"),
            b'<button data-s="prod">Claude</button>',
        )

    def test_installed_handler_preserves_session_text_and_does_not_add_label_settings(self):
        class Handler:
            def _send(self, code, body, ctype="application/json"):
                return body

        notes = []
        namespace = {"H": Handler, "tg_notify": notes.append}
        cc_labels.install(namespace)
        handler = namespace["H"]()
        handler.path = "/api/console?s=prod"
        self.assertEqual(handler._send(200, {"text": "Claude PROD"}), {"text": "Claude PROD"})
        self.assertNotIn("do_POST", namespace["H"].__dict__)
        namespace["tg_notify"]("Подключён Claude PROD")
        self.assertEqual(notes, ["Подключён Claude"])
