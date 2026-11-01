"""Reglas y planificación del watcher. pactl subscribe va simulado: no prueba el subscribe en vivo."""
import ast
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mgame  # noqa: E402
import mgame_apps  # noqa: E402
import mgame_lock  # noqa: E402

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def rule(match, field, sink):
    return {"match": match, "field": field, "sink": sink}


def stream(index, name, binary, sink, node=None):
    return {
        "index": index,
        "sink": sink,
        "properties": {
            "node.name": name if node is None else node,
            "application.name": name,
            "application.process.binary": binary,
        },
    }


FIREFOX = {
    "node.name": "Firefox",
    "application.name": "Mozilla Firefox",
    "application.process.binary": "/usr/lib/firefox/firefox",
}


class RulesTest(unittest.TestCase):
    def test_empty_match_rejected(self):
        for match in ("", "  ", "\t", "a" * 81, "foo\nbar", "foo\x00bar"):
            with self.assertRaises(ValueError, msg=repr(match)):
                mgame_apps.validate_match(match)
            with self.assertRaises(ValueError, msg=repr(match)):
                mgame_apps.validate_rule(rule(match, "name", "game"))
        self.assertEqual(mgame_apps.validate_match("  firefox  "), "firefox")
        self.assertEqual(len(mgame_apps.validate_match("a" * 80)), 80)

    def test_closed_field_and_sink(self):
        for field in ("path", "app", "binary ", "Binary", ""):
            with self.assertRaises(ValueError, msg=field):
                mgame_apps.validate_rule(rule("firefox", field, "game"))
        for sink in ("phones", "stream", "mic", "Game", "main", ""):
            with self.assertRaises(ValueError, msg=sink):
                mgame_apps.validate_rule(rule("firefox", "name", sink))
        for field in mgame_apps.FIELDS:
            for sink in mgame_apps.SINKS:
                cleaned = mgame_apps.validate_rule(rule("firefox", field, sink))
                self.assertEqual(cleaned["field"], field)
                self.assertEqual(cleaned["sink"], sink)
        with self.assertRaises(ValueError):
            mgame_apps.validate_rule({"match": "firefox", "field": "name", "sink": "game", "extra": 1})

    def test_binary_is_basename_and_first_match_wins(self):
        binary = [rule("firefox", "binary", "game")]
        self.assertEqual(mgame_apps.first_sink(binary, FIREFOX), "game")
        self.assertIsNone(mgame_apps.first_sink([rule("lib", "binary", "game")], FIREFOX))
        self.assertIsNone(mgame_apps.first_sink([rule("usr", "binary", "chat")], FIREFOX))
        self.assertEqual(mgame_apps.first_sink([rule("mozilla", "name", "chat")], FIREFOX), "chat")
        self.assertIsNone(mgame_apps.first_sink([rule("chrome", "name", "game")], FIREFOX))
        self.assertEqual(mgame_apps.first_sink([rule("FIREFOX", "both", "sampler")], FIREFOX), "sampler")
        both = [rule("fire", "binary", "chat"), rule("fox", "binary", "game")]
        self.assertEqual(mgame_apps.first_sink(both, FIREFOX), "chat")

    def test_mgame_and_pw_play_skipped_before_rules(self):
        rules = [rule("pw", "both", "sampler"), rule("fire", "name", "game"), rule("mgame", "binary", "chat")]
        skipped = [
            stream(1, "pw-play", "/usr/bin/pw-play", 0, node="pw-play"),
            stream(2, "sample", "/usr/bin/pw-play", 0, node="alsa_playback"),
            stream(3, "Firefox", "/usr/bin/firefox", 0, node="pw-play-99"),
            stream(4, "Firefox", "/usr/lib/firefox/firefox", 0, node="mgame_sampler"),
            stream(5, "Firefox", "/usr/bin/something", 0, node="mgame_game"),
        ]
        sinks = [{"index": 0, "name": "mgame_chat"}]
        plan = mgame_apps.Watcher(rules)
        self.assertEqual(plan.full_pass(skipped, sinks), [])
        for item in skipped:
            self.assertIsNone(mgame_apps.first_sink(rules, item["properties"]))
        kept = stream(9, "Mozilla Firefox", "/usr/lib/firefox/firefox", 0)
        self.assertEqual(plan.full_pass(skipped + [kept], sinks), [(9, "game")])

    def test_plan_ignores_change_acts_on_new_and_full_pass(self):
        rules = [rule("firefox", "name", "game")]
        plan = mgame_apps.Watcher(rules)
        inputs = [stream(7, "Mozilla Firefox", "/usr/lib/firefox/firefox", 0)]
        sinks = [{"index": 0, "name": "mgame_chat"}, {"index": 1, "name": mgame.NODE_NAMES["game"]}]
        self.assertEqual(plan.on_line("Event 'change' on sink-input #7", inputs, sinks), [])
        self.assertEqual(plan.on_line("Event 'new' on sink #7", inputs, sinks), [])
        self.assertEqual(plan.on_line("Event 'new' on sink-input #7", inputs, sinks), [(7, "game")])
        self.assertEqual(plan.full_pass(inputs, sinks), [(7, "game")])
        already = [stream(7, "Mozilla Firefox", "/usr/lib/firefox/firefox", 1)]
        self.assertEqual(plan.full_pass(already, sinks), [])
        self.assertEqual(plan.on_line("Event 'new' on sink-input #7", already, sinks), [])

    def test_failed_move_cache_until_remove(self):
        rules = [rule("firefox", "name", "game")]
        plan = mgame_apps.Watcher(rules)
        inputs = [stream(7, "Mozilla Firefox", "/usr/lib/firefox/firefox", 0)]
        sinks = [{"index": 0, "name": "mgame_chat"}]
        self.assertEqual(plan.full_pass(inputs, sinks), [(7, "game")])
        plan.note_failure(7)
        self.assertEqual(plan.full_pass(inputs, sinks), [])
        self.assertEqual(plan.on_line("Event 'new' on sink-input #7", inputs, sinks), [])
        self.assertEqual(plan.on_line("Event 'change' on sink-input #7", inputs, sinks), [])
        self.assertIn(7, plan.failed)
        plan.on_line("Event 'remove' on sink-input #7", inputs, sinks)
        self.assertNotIn(7, plan.failed)
        self.assertEqual(plan.full_pass(inputs, sinks), [(7, "game")])

    def test_invalid_rules_keep_last_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "app-rules.json")
            json.dump({"rules": [rule("firefox", "binary", "game")]}, open(path, "w"))
            state = mgame_apps.RulesState(path)
            good, err = state.load()
            self.assertIsNone(err)
            self.assertEqual(good, [rule("firefox", "binary", "game")])
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            err_buf = io.StringIO()
            with contextlib.redirect_stderr(err_buf):
                kept, err = state.load()
            self.assertIsNotNone(err)
            self.assertEqual(kept, good)
            self.assertNotEqual(kept, [])
            self.assertIn("inválido", err_buf.getvalue())
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"rules": [rule("", "name", "game")]}, fh)
            with contextlib.redirect_stderr(io.StringIO()):
                kept, err = state.load()
            self.assertEqual(kept, good)
            self.assertTrue(state.had_good)

    def test_missing_rules_logged_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = mgame_apps.RulesState(os.path.join(tmp, "missing.json"))
            err_buf = io.StringIO()
            with contextlib.redirect_stderr(err_buf):
                self.assertEqual(state.load()[0], [])
                self.assertEqual(state.load()[0], [])
            self.assertEqual(err_buf.getvalue().count("no existe"), 1)

    def test_module_does_not_import_device_or_call_amidi(self):
        text = open(mgame_apps.__file__, encoding="utf-8").read()
        self.assertNotIn("mgame_device", text)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("mgame_device", alias.name)
                    self.assertNotIn("amidi", alias.name)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn("mgame_device", node.module or "")
            if isinstance(node, ast.Attribute) and node.attr == "sleep":
                self.fail("el watcher no debe dormir")
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value == "amidi":
                        self.fail("llamada a amidi")
        self.assertEqual(mgame_apps.SUBSCRIBE_ARGV, ["stdbuf", "-oL", "pactl", "subscribe"])
        self.assertEqual(mgame_apps.SINK_NODES, {key: mgame.NODE_NAMES[key] for key in mgame_apps.SINKS})
        src = open(os.path.join(REPO, "mgame.py"), encoding="utf-8").read()
        self.assertLess(src.find('sys.argv[1] == "apps-watch"'), src.find("from mgame_device import atomic_write"))

    def test_importing_apps_module_does_not_load_device(self):
        """El módulo del watcher no carga mgame ni el dispositivo."""
        env = os.environ.copy()
        env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-c",
             "import mgame_apps, sys\n"
             "mgame_apps.rules_path()\n"
             "bad = [n for n in ('mgame', 'mgame_device') if n in sys.modules]\n"
             "raise SystemExit(0 if not bad else 1)"],
            cwd=REPO, env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_watch_loop_startup_new_and_failed_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "app-rules.json")
            json.dump({"rules": [rule("firefox", "name", "game")]}, open(path, "w"))
            state = mgame_apps.RulesState(path)
            inputs = [stream(7, "Mozilla Firefox", "/usr/lib/firefox/firefox", 0)]
            sinks = [{"index": 0, "name": "mgame_chat"}]
            moves = []

            def fake_move(sid, sink):
                moves.append((sid, sink))
                return False

            lines = [
                "Event 'change' on sink-input #7\n",
                "Event 'new' on sink-input #7\n",
                "Event 'remove' on sink-input #7\n",
                "Event 'new' on sink-input #7\n",
            ]
            with mock.patch.object(mgame_apps, "move_stream", fake_move):
                mgame_apps._run_watch(lines, state, lambda: (inputs, sinks))
            # pase inicial (falla y cachea), 'change' y 'new' no reintentan, remove libera, último new sí
            self.assertEqual(moves, [(7, "game"), (7, "game")])

    def test_unit_text(self):
        text = mgame.apps_unit_text("/tmp/mgame.py")
        self.assertIn("ExecStart=/usr/bin/python3 -u /tmp/mgame.py apps-watch\n", text)
        self.assertIn("Restart=on-failure\n", text)
        self.assertIn("RestartSec=2\n", text)
        self.assertNotIn("RestartSec=5", text)
        self.assertNotIn("amidi", text)


class AppsCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls = []
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(mgame, "CFG_DIR", self.tmp.name))
        stack.enter_context(mock.patch.object(mgame, "pactl", self._pactl))
        self.inputs, self.sinks = [], []
        stack.enter_context(mock.patch.object(mgame, "pactl_json", self._pactl_json))

    def _pactl(self, *args):
        self.calls.append(args)
        return mock.Mock(returncode=0, stdout="", stderr="")

    def _pactl_json(self, *args):
        if args == ("list", "sink-inputs"):
            return self.inputs
        if args == ("list", "sinks"):
            return self.sinks
        return []

    def test_rule_set_rejects_empty_and_closed_sets(self):
        for args in (["", "name", "game"], ["  ", "binary", "chat"], ["firefox", "path", "game"],
                     ["firefox", "name", "phones"], ["firefox", "name"]):
            res = mgame_apps.cmd_rule_set(args)
            self.assertFalse(res["ok"], args)
        self.assertFalse(os.path.exists(mgame_apps.rules_path()))
        res = mgame_apps.cmd_rule_set(["firefox", "binary", "game"])
        self.assertTrue(res["ok"])
        res = mgame_apps.cmd_rules([])
        self.assertEqual(res["rules"], [rule("firefox", "binary", "game")])

    def test_apply_skips_pw_play_and_moves_one_at_a_time(self):
        mgame_apps.cmd_rule_set(["firefox", "name", "game"])
        self.inputs = [
            stream(3, "pw-play", "/usr/bin/pw-play", 0, node="pw-play"),
            stream(7, "Mozilla Firefox", "/usr/lib/firefox/firefox", 0),
            stream(8, "Mozilla Firefox", "/usr/lib/firefox/firefox", 1),
        ]
        self.sinks = [{"index": 0, "name": "mgame_chat"}, {"index": 1, "name": mgame.NODE_NAMES["game"]}]
        res = mgame_apps.cmd_apply([])
        self.assertTrue(res["ok"])
        moves = [call for call in self.calls if call and call[0] == "move-sink-input"]
        self.assertEqual(moves, [("move-sink-input", "7", mgame.NODE_NAMES["game"])])

    def test_main_dispatches_json(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                mgame.main(["mgame.py", "apps-rules"])
        self.assertEqual(cm.exception.code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["rules"], [])
        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["watch"]["enabled"], bool)
        self.assertIsInstance(payload["watch"]["active"], bool)

    def test_watch_mocked_subscribe_exits_nonzero(self):
        """No prueba pactl subscribe en vivo: el proceso hijo va simulado."""
        class Fake:
            stdout = io.StringIO("Event 'change' on sink-input #1\n")

            def poll(self):
                return None

            def kill(self):
                self.killed = True

            def wait(self):
                return 1

        with mock.patch.object(mgame_apps.subprocess, "Popen", return_value=Fake()) as popen, \
                mock.patch.object(mgame_apps, "list_inputs_and_sinks", return_value=([], [])):
            with self.assertRaises(SystemExit) as cm:
                mgame_apps.watch()
        self.assertEqual(popen.call_args[0][0], mgame_apps.SUBSCRIBE_ARGV)
        self.assertNotEqual(cm.exception.code, 0)
        self.assertEqual(popen.call_args.kwargs.get("bufsize"), 1)


class LockTest(unittest.TestCase):
    def test_nonblocking_acquire_returns_busy(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "state.json")
            held = mgame_lock.acquire(target, blocking=True)
            try:
                self.assertEqual(mgame_lock.acquire(target, blocking=False), "busy")
            finally:
                held.release()
            again = mgame_lock.acquire(target, blocking=False)
            self.assertNotEqual(again, "busy")
            again.release()
            self.assertTrue(os.path.exists(target + ".lock"))
            self.assertFalse(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
