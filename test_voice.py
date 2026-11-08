# Голос (voice/): текстовые функции сервера озвучки, команды ccfleet-say / ccfleet-say-long, установщик voice/install.sh, подключение к коду.
# Ни настоящие модели, ни сеть, ни systemd не трогаются: torch и num2words подменены заглушками, демон — маленький HTTP-сервер из теста.
# python3 -m unittest test_voice -v
import http.server
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
VOICE = os.path.join(HERE, "voice")


def load_server(voice_dir):
    """voice/server.py без torch и num2words: функции подготовки текста чистые, модели грузятся только в main."""
    torch = types.ModuleType("torch")
    n2w = types.ModuleType("num2words")
    n2w.num2words = lambda n, lang="ru", **kw: {"1": "один", "2": "два", "3": "три", "10": "десять"}.get(str(n), str(n))
    env = {"CCFLEET_VOICE_DIR": voice_dir}
    with mock.patch.dict(sys.modules, {"torch": torch, "num2words": n2w}), mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_file_location("ccfleet_voice_server_under_test", os.path.join(VOICE, "server.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    return m


class ServerText(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="voice_")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.m = load_server(self.d)

    def test_paths_and_port_come_from_environment_not_from_a_private_home(self):
        self.assertEqual(self.m.MODEL_DIR, os.path.join(self.d, "model"))
        self.assertTrue(os.path.isdir(self.m.MODEL_DIR))
        self.assertEqual(self.m.PORT, 8879)
        with mock.patch.dict(os.environ, {"CCFLEET_VOICE_PORT": "18879"}):
            self.assertEqual(load_server(self.d).PORT, 18879)
        src = open(os.path.join(VOICE, "server.py"), encoding="utf-8").read()
        self.assertNotIn("~/tts", src)
        self.assertNotIn("/root/", src)

    def test_pauses_are_explicit_ssml_breaks(self):
        ssml = self.m.to_ssml("Привет, мир — дальше")
        self.assertTrue(ssml.startswith("<speak>") and ssml.endswith("</speak>"))
        self.assertIn('<break time="180ms"/>', ssml)
        self.assertIn('<break time="280ms"/>', ssml)
        self.assertNotIn("<b>", self.m.to_ssml("<b>x</b>"))  # чужая разметка экранируется

    def test_latin_words_are_read_in_russian_and_acronyms_by_letters(self):
        text, words = self.m.transliterate_latin("Открой Telegram и GitHub")
        self.assertIn("Телеграм", text)
        self.assertIn("Гитхаб", text)
        self.assertTrue(words)
        spelled, letters = self.m.spell_acronyms("Включи VPN и DNS")
        self.assertEqual(letters, ["vpn", "dns"])
        self.assertNotIn("VPN", spelled)

    def test_long_text_is_split_on_sentence_borders(self):
        sentence = "Это одно довольно длинное предложение для проверки разбиения. "
        parts = self.m._split_for_tts(sentence * 40)
        self.assertGreater(len(parts), 2)
        self.assertTrue(all(len(p) <= self.m._TTS_CHUNK_MAX_LEN + 80 for p in parts))
        self.assertEqual("".join(parts).replace(" ", "").replace("\n", ""), (sentence * 40).replace(" ", "").strip().replace("\n", ""))

    def test_hard_e_dictionary_ships_and_loads(self):
        path = os.path.join(VOICE, "dict", "hard_e.json")
        self.assertGreater(os.path.getsize(path), 100_000)
        self.assertTrue(self.m._HARD_E_DICT)


class FakeDaemon:
    """Подставной демон озвучки: запоминает запросы, отвечает заданным кодом и телом."""

    def __init__(self, code=200, body=b"OggS-fake"):
        outer = self
        self.code, self.body, self.requests = code, body, []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                outer.requests.append((self.path, json.loads(self.rfile.read(n) or b"{}")))
                self.send_response(outer.code)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class SayCommand(unittest.TestCase):
    SAY = os.path.join(VOICE, "bin", "ccfleet-say")

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="say_")
        self.addCleanup(shutil.rmtree, self.d, True)

    def run_say(self, daemon, *args, env=None):
        e = dict(os.environ, CCFLEET_VOICE_PORT=str(daemon.port), CCFLEET_VOICE_TIMEOUT="10")
        e.update(env or {})
        return subprocess.run(["bash", self.SAY, *args], capture_output=True, text=True, env=e, timeout=60)

    def test_success_writes_the_audio_and_sends_text_and_voice(self):
        dm = FakeDaemon(200, b"OggS-audio-bytes"); self.addCleanup(dm.close)
        out = os.path.join(self.d, "a.ogg")
        r = self.run_say(dm, "Привет, мир", out, "baya")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(open(out, "rb").read(), b"OggS-audio-bytes")
        self.assertEqual(dm.requests, [("/speak", {"text": "Привет, мир", "voice": "baya"})])
        self.assertEqual(os.listdir(self.d), ["a.ogg"])  # временных файлов не осталось

    def test_default_voice_is_kseniya(self):
        dm = FakeDaemon(); self.addCleanup(dm.close)
        self.run_say(dm, "текст", os.path.join(self.d, "a.ogg"))
        self.assertEqual(dm.requests[0][1]["voice"], "kseniya")

    def test_error_is_never_written_into_the_audio_file(self):
        dm = FakeDaemon(500, "Model couldn't generate your text".encode()); self.addCleanup(dm.close)
        out = os.path.join(self.d, "a.ogg")
        open(out, "wb").write(b"old")  # старый файл не должен остаться «как будто озвучено»
        r = self.run_say(dm, "текст", out)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(os.path.exists(out))
        self.assertIn("HTTP 500", r.stderr)
        self.assertIn("Model couldn't generate", r.stderr)
        self.assertIn("systemctl status ccfleet-tts", r.stderr)
        self.assertEqual(os.listdir(self.d), [])

    def test_no_daemon_is_a_clear_error(self):
        dm = FakeDaemon(); port = dm.port; dm.close()
        out = os.path.join(self.d, "a.ogg")
        r = subprocess.run(["bash", self.SAY, "текст", out], capture_output=True, text=True, env=dict(os.environ, CCFLEET_VOICE_PORT=str(port), CCFLEET_VOICE_TIMEOUT="5"), timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(os.path.exists(out))
        self.assertIn("ccfleet-say:", r.stderr)

    def test_usage(self):
        dm = FakeDaemon(); self.addCleanup(dm.close)
        r = self.run_say(dm)
        self.assertEqual(r.returncode, 2)
        self.assertIn("Использование", r.stderr)
        self.assertEqual(dm.requests, [])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "нужен ffmpeg")
class SayLong(unittest.TestCase):
    def test_long_text_is_cut_into_chunks_and_joined(self):
        d = tempfile.mkdtemp(prefix="saylong_"); self.addCleanup(shutil.rmtree, d, True)
        beep = os.path.join(d, "beep.ogg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.5", "-c:a", "libopus", beep], check=True)
        dm = FakeDaemon(200, open(beep, "rb").read()); self.addCleanup(dm.close)
        src = os.path.join(d, "t.txt")
        open(src, "w", encoding="utf-8").write(("Предложение номер один. " * 60).strip() + "\n\n" + "Второй абзац.")
        out = os.path.join(d, "out.ogg")
        r = subprocess.run(["bash", os.path.join(VOICE, "bin", "ccfleet-say-long"), src, out, "aidar"], capture_output=True, text=True,
                           env=dict(os.environ, CCFLEET_VOICE_PORT=str(dm.port)), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreater(len(dm.requests), 2)
        self.assertTrue(all(len(q[1]["text"]) <= 520 and q[1]["voice"] == "aidar" for q in dm.requests))
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out], capture_output=True, text=True).stdout)
        self.assertGreater(dur, 0.5 * len(dm.requests) - 0.5)  # куски склеены в один файл


class Installer(unittest.TestCase):
    INSTALL = os.path.join(VOICE, "install.sh")

    def env(self, d):
        return dict(os.environ, CCFLEET_VOICE_DIR=os.path.join(d, "v"), CCFLEET_VOICE_BIN=os.path.join(d, "bin"), CCFLEET_VOICE_UNIT=os.path.join(d, "tts.service"),
                    CCFLEET_VOICE_PORT="1")

    def test_files_are_executable_and_valid_shell(self):
        for rel in ("install.sh", "bin/ccfleet-say", "bin/ccfleet-say-long", "bin/ccfleet-transcribe"):
            p = os.path.join(VOICE, rel)
            self.assertTrue(os.access(p, os.X_OK), rel)
            self.assertEqual(subprocess.run(["bash", "-n", p]).returncode, 0, rel)

    def test_check_lists_eight_steps_and_changes_nothing(self):
        d = tempfile.mkdtemp(prefix="vinst_"); self.addCleanup(shutil.rmtree, d, True)
        r = subprocess.run(["bash", self.INSTALL, "--check"], capture_output=True, text=True, env=self.env(d), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        for n in range(1, 9):
            self.assertIn("шаг %d из 8" % n, r.stdout)
        self.assertEqual(r.stdout.count("не выполнен"), r.stdout.count("⬜"))
        self.assertIn("Расшифровка", r.stdout)
        self.assertEqual(os.listdir(d), [])  # --check ничего не создаёт

    def test_help(self):
        r = subprocess.run(["bash", self.INSTALL, "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertIn("--check", r.stdout)
        self.assertIn("--remove", r.stdout)

    def test_unit_template_and_names_match_the_main_installer(self):
        unit = open(os.path.join(VOICE, "ccfleet-tts.service"), encoding="utf-8").read()
        self.assertEqual(unit.count("@VOICE_DIR@"), 5)
        self.assertIn("server.py", unit)
        self.assertIn("Restart=always", unit)
        inst = open(os.path.join(VOICE, "install.sh"), encoding="utf-8").read()
        main = open(os.path.join(HERE, "install.sh"), encoding="utf-8").read()
        # шаг 13 общего установщика ждёт ровно эти имена: команду ccfleet-say, порт 8879 /health и службу ccfleet-tts
        for name in ("ccfleet-say", "ccfleet-transcribe", "ccfleet-tts", "8879"):
            self.assertIn(name, inst)
            self.assertIn(name, main)
        self.assertIn("voice/install.sh", main)

    def test_the_end_to_end_check_is_part_of_the_steps(self):
        inst = open(os.path.join(VOICE, "install.sh"), encoding="utf-8").read()
        self.assertIn("Проверка озвучки", inst)
        self.assertIn("Проверка расшифровки", inst)
        self.assertIn("test.txt", inst)  # расшифровка читает то, что озвучила озвучка
        self.assertIn("перепроверка", inst)  # следующий шаг перепроверяет предыдущие

    def run_preload(self, fail_times):
        """preload_models из установщика с подставным Python: первые fail_times запусков загрузки падают."""
        d = tempfile.mkdtemp(prefix="vpre_"); self.addCleanup(shutil.rmtree, d, True)
        v, ra = os.path.join(d, "v"), os.path.join(d, "ruaccent")
        os.makedirs(os.path.join(v, "venv-tts", "bin")); os.makedirs(os.path.join(v, "model"))
        for sub in ("nn", "dictionary", ".cache", "koziev"):
            os.makedirs(os.path.join(ra, sub))
        open(os.path.join(v, "model", "master.zip"), "w").write("partial")
        py = os.path.join(v, "venv-tts", "bin", "python3")
        open(py, "w").write("#!/bin/bash\nif [[ \"$2\" == *dirname* ]]; then echo '%s'; exit 0; fi\n"
                            "n=$(cat '%s/count' 2>/dev/null || echo 0); echo $((n+1)) > '%s/count'\n"
                            "[ \"$n\" -lt %d ] && { echo 'ConnectionError: huggingface.co' >&2; exit 1; }\necho ok\n" % (ra, d, d, fail_times))
        os.chmod(py, 0o755)
        r = subprocess.run(["bash", "-c", 'source <(sed -n "/^info()/p;/^preload_models()/,/^}/p" "$0"); VOICE_DIR="$1"; preload_models; echo "rc=$?"', self.INSTALL, v],
                           capture_output=True, text=True, timeout=60)
        return r, ra, v

    def test_interrupted_download_leaves_no_traces_and_is_retried(self):
        r, ra, v = self.run_preload(fail_times=1)
        self.assertIn("rc=0", r.stdout)
        self.assertIn("попытка 1 из 2", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(ra, "nn")))          # пустые папки оборванной загрузки убраны
        self.assertFalse(os.path.exists(os.path.join(ra, ".cache")))
        self.assertTrue(os.path.isdir(os.path.join(ra, "koziev")))         # файлы самого пакета не тронуты
        self.assertFalse(os.path.exists(os.path.join(v, "model", "master.zip")))

    def test_two_failures_in_a_row_is_an_error(self):
        r, _, _ = self.run_preload(fail_times=2)
        self.assertIn("rc=1", r.stdout)

    def test_installer_turns_the_voice_checkbox_on_in_the_panel(self):
        d = tempfile.mkdtemp(prefix="vcfg_"); self.addCleanup(shutil.rmtree, d, True)
        cfg = os.path.join(d, "notion_ai.json")
        json.dump({"owner": "Аня", "voice": False}, open(cfg, "w"))
        r = subprocess.run(["bash", "-c", 'source <(sed -n "/^info()/p;/^enable_in_panel()/,/^}/p" "$0"); CC_LIMITS_BASE="$1"; enable_in_panel; echo rc=$?', self.INSTALL, d],
                           capture_output=True, text=True, timeout=30)
        self.assertIn("rc=0", r.stdout)
        self.assertEqual(json.load(open(cfg)), {"owner": "Аня", "voice": True})  # остальные настройки не тронуты
        empty = tempfile.mkdtemp(prefix="vcfg2_"); self.addCleanup(shutil.rmtree, empty, True)
        r = subprocess.run(["bash", "-c", 'source <(sed -n "/^info()/p;/^enable_in_panel()/,/^}/p" "$0"); CC_LIMITS_BASE="$1"; enable_in_panel; echo rc=$?', self.INSTALL, empty],
                           capture_output=True, text=True, timeout=30)
        self.assertIn("rc=0", r.stdout)                     # панели нет — ничего не создаём и не падаем
        self.assertEqual(os.listdir(empty), [])

    def test_clean_install_has_voice_off_until_it_is_installed(self):
        main = open(os.path.join(HERE, "install.sh"), encoding="utf-8").read()
        self.assertIn('"voice": os.environ.get("NAI_VOICE") == "1"', main)
        self.assertIn('NAI_VOICE="$(yes_ "$WANT_VOICE"', main)
        nai = open(os.path.join(HERE, "notion_ai", "install.sh"), encoding="utf-8").read()
        self.assertIn('"voice": False', nai)

    def test_problems_of_the_server_are_reported_with_what_to_do(self):
        d = tempfile.mkdtemp(prefix="vinst_"); self.addCleanup(shutil.rmtree, d, True)
        env = self.env(d)
        env["CCFLEET_VOICE_MIN_DISK_MB"] = "999999999"  # места «не хватает»
        probe = subprocess.run(["bash", "-c", 'source <(sed -n "/^env_problem()/,/^}/p" "$0"); VOICE_DIR="$1"; MIN_DISK_MB="$2"; MIN_RAM_MB=1; env_problem', self.INSTALL, os.path.join(d, "v"), "999999999"],
                               capture_output=True, text=True, env=env, timeout=60)
        if os.geteuid() == 0:
            self.assertIn("мало места", probe.stdout)
            self.assertIn("|", probe.stdout)  # «что не так|что делать»


class Wiring(unittest.TestCase):
    def test_notion_reply_prefers_the_installer_command_and_falls_back_to_the_old_path(self):
        from importlib.machinery import SourceFileLoader
        m = SourceFileLoader("nai_reply_voice", os.path.join(HERE, "notion_ai", "bin", "notion-ai-reply")).load_module()
        with mock.patch.object(m.os.path, "exists", side_effect=lambda p: p == "/usr/local/bin/ccfleet-say"):
            self.assertEqual(m.say_tool(), "/usr/local/bin/ccfleet-say")
        with mock.patch.object(m.os.path, "exists", side_effect=lambda p: p == "/root/tts/say.sh"):
            self.assertEqual(m.say_tool(), "/root/tts/say.sh")
        with mock.patch.object(m.os.path, "exists", return_value=False):
            self.assertEqual(m.say_tool(), "/usr/local/bin/ccfleet-say")

    def test_bridge_transcribes_with_the_installer_command_first(self):
        src = open(os.path.join(HERE, "notion_ai", "web", "notion_ai_tg.py"), encoding="utf-8").read()
        self.assertIn('"/usr/local/bin/ccfleet-transcribe", "/root/tts/transcribe.sh"', src)
        self.assertIn("subprocess.run([transcribe_tool(), path]", src)

    def test_panel_uses_the_installer_command_and_checks_it_when_asked(self):
        import cc_notion_ai as M
        self.assertEqual(M.TTS, "/usr/local/bin/ccfleet-say")
        with mock.patch("cc_notion_ai.Path") as P:
            P.side_effect = lambda p: types.SimpleNamespace(exists=lambda: p == M.TTS_LEGACY)
            self.assertEqual(M.tts_path(), M.TTS_LEGACY)  # голос поставлен вручную по-старому — панель его видит
            P.side_effect = lambda p: types.SimpleNamespace(exists=lambda: p == M.TTS)
            self.assertEqual(M.tts_path(), M.TTS)

    def test_voice_files_are_in_the_repository_and_not_ignored(self):
        need = ["install.sh", "server.py", "README.md", "ccfleet-tts.service", "dict/hard_e.json", "bin/ccfleet-say", "bin/ccfleet-say-long", "bin/ccfleet-transcribe"]
        for rel in need:
            self.assertTrue(os.path.isfile(os.path.join(VOICE, rel)), rel)
        if shutil.which("git") and os.path.isdir(os.path.join(HERE, ".git")):
            r = subprocess.run(["git", "check-ignore"] + ["voice/" + x for x in need], capture_output=True, text=True, cwd=HERE)
            self.assertEqual(r.stdout.strip(), "", "эти файлы голоса игнорируются git: " + r.stdout)


if __name__ == "__main__":
    unittest.main()
