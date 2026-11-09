# Нужен ли ручной install.sh: поле install_since в манифесте (2.0.12)
# python3 -m unittest test_cc_update_install_since -v
import json
import os
import unittest

import cc_update as U

HERE = os.path.dirname(os.path.abspath(__file__))


class InstallRequired(unittest.TestCase):
    def test_older_than_install_since_needs_manual_install(self):
        mf = {"needs_install": True, "install_since": "2.0.8"}
        self.assertTrue(U.install_required(mf, "2.0.7"))
        self.assertTrue(U.install_required(mf, "1.29.0"))

    def test_install_since_or_newer_updates_from_the_panel(self):
        mf = {"needs_install": True, "install_since": "2.0.8"}
        for v in ("2.0.8", "2.0.12", "2.1.0", "v2.0.9"):
            self.assertFalse(U.install_required(mf, v), v)

    def test_without_install_since_the_old_flag_decides(self):
        self.assertTrue(U.install_required({"needs_install": True}, "2.0.12"))
        self.assertFalse(U.install_required({"needs_install": False}, "2.0.7"))
        self.assertFalse(U.install_required({}, "2.0.7"))

    def test_unreadable_versions_fall_back_to_the_flag(self):
        # мусор в установленной версии или в install_since не должен молча разрешать обновление без установщика
        mf = {"needs_install": True, "install_since": "2.0.8"}
        self.assertTrue(U.install_required(mf, "dev-build"))
        self.assertTrue(U.install_required(mf, ""))
        self.assertTrue(U.install_required({"needs_install": True, "install_since": "скоро"}, "2.0.12"))

    def test_apply_uses_it(self):
        # путь применения обновления обязан звать install_required, а не читать флаг напрямую
        src = open(os.path.join(HERE, "cc_update.py"), encoding="utf-8").read()
        self.assertIn("if install_required(mf, self.version):", src)
        self.assertNotIn('if mf.get("needs_install"):', src)


class ShippedManifest(unittest.TestCase):
    def test_manifest_keeps_the_flag_for_old_clients_and_names_the_installer_version(self):
        mf = json.load(open(os.path.join(HERE, "update_manifest.json"), encoding="utf-8"))
        # старые клиенты видят только needs_install: пока он true, они безопасно останавливаются на «запусти install.sh»
        self.assertTrue(mf.get("needs_install"))
        since = U.parse_ver(mf.get("install_since"))
        self.assertIsNotNone(since)
        self.assertLessEqual(since, U.parse_ver(mf["version"]))


if __name__ == "__main__":
    unittest.main()
