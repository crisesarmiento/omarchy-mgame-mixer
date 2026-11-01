"""Perfiles con pactl y amidi simulados. Nada toca el hardware ni systemctl."""
import contextlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mgame  # noqa: E402
import mgame_device as md  # noqa: E402
import mgame_lock  # noqa: E402
import mgame_profiles  # noqa: E402
import mgame_proto  # noqa: E402

VOL_KEYS = ("game", "chat", "sampler", "system", "mic")


def full_gains(value):
    return {dest: {src: value for src in md.SRCS} for dest in md.DESTS}


def volumes(pct=40, mute_game=False):
    out = {key: {"pct": pct, "mute": False} for key in VOL_KEYS}
    out["game"]["mute"] = mute_game
    return out


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.tmp.name
        os.makedirs(os.path.join(t, "cfg"))
        os.makedirs(os.path.join(t, "led_presets"))
        self.sent = []
        self.chunks = []
        self.pactl_calls = []
        self.dev_port_calls = 0
        self.pactl_fail = False
        self.fail_chunk = None
        self.live = True
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(mgame, "CFG_DIR", os.path.join(t, "cfg")))
        stack.enter_context(mock.patch.object(mgame, "STATE_PATH", os.path.join(t, "cfg", "state.json")))
        stack.enter_context(mock.patch.object(mgame, "MIC_CONF", os.path.join(t, "mic.conf")))
        stack.enter_context(mock.patch.object(md, "DEVICE_PATH", os.path.join(t, "device.json")))
        stack.enter_context(mock.patch.object(md, "LED_PRESET_DIR", os.path.join(t, "led_presets")))
        stack.enter_context(mock.patch.object(mgame, "pactl", self._pactl))
        stack.enter_context(mock.patch.object(mgame, "pactl_json", self._pactl_json))
        stack.enter_context(mock.patch.object(mgame, "apply_mic_live", self._live))
        stack.enter_context(mock.patch.object(mgame, "dev_port", self._dev_port))
        stack.enter_context(mock.patch.object(mgame, "find_rawmidi", lambda: "hw:9,9,9"))
        stack.enter_context(mock.patch.object(mgame, "amidi_send_batch_quiet", self._batch))
        stack.enter_context(mock.patch.object(mgame, "amidi_send", self._forbid_amidi))
        stack.enter_context(mock.patch.object(mgame, "amidi_send_batch", self._forbid_amidi))
        stack.enter_context(mock.patch.object(mgame, "WRITE_GAP", 0))
        stack.enter_context(mock.patch.object(mgame, "run", self._forbid_run))
        stack.enter_context(mock.patch.object(mgame.subprocess, "Popen", self._forbid_run))

    def _forbid_run(self, *args, **kwargs):
        raise AssertionError(f"subprocess inesperado: {args!r}")

    def _forbid_amidi(self, *args, **kwargs):
        raise AssertionError("amidi no debe llamarse por este camino")

    def _dev_port(self):
        self.dev_port_calls += 1
        return "hw:9,9,9"

    def _live(self, params):
        return self.live

    def _batch(self, port, frames, size=None, pause=0.0):
        self.chunks.append(list(frames))
        if self.fail_chunk and len(self.chunks) == self.fail_chunk:
            return False
        self.sent.extend(frames)
        return True

    def _pactl(self, *args):
        self.pactl_calls.append(args)
        if self.pactl_fail and args and str(args[0]).startswith("set-"):
            return mock.Mock(returncode=1, stdout="", stderr="fail")
        return mock.Mock(returncode=0, stdout="", stderr="")

    def _node(self, name, pct=100, mute=False):
        value = int(round(pct / 100 * 65536))
        return {"name": name, "mute": mute, "index": 1,
                "volume": {"front-left": {"value": value}, "front-right": {"value": value}}}

    def _pactl_json(self, *args):
        if args == ("list", "sinks"):
            return [self._node(mgame.NODE_NAMES[key]) for key in mgame.OUT_KEYS]
        if args == ("list", "sources"):
            return [self._node(mgame.NODE_NAMES["mic"])]
        return []

    def write_profile(self, name, **overrides):
        data = {
            "version": 1,
            "volumes": volumes(),
            "mic": {"enabled": True, "preset": "natural", "overrides": {}},
            "rules": [{"match": "firefox", "field": "binary", "sink": "game"}],
            "gains": None,
            "ledPreset": None,
            "deviceUpdated": 1700000000.0,
        }
        data.update(overrides)
        directory = os.path.join(mgame.CFG_DIR, "profiles")
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, name + ".json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return data

    def undo_path(self):
        return os.path.join(mgame.CFG_DIR, "profiles", "_before-restore.json")

    def tearDown(self):
        for frame in self.sent:
            msg = mgame_proto.parse(frame)
            self.assertIsNotNone(msg)
            self.assertNotEqual(msg.param_id, 0x00030000)
            self.assertNotEqual(msg.param_id, md.PHANTOM)
            self.assertEqual(msg.param_id & 0xFFFF0000, md.GAIN_BASE)
            self.assertTrue(md.is_write_allowed(msg.param_id, msg.count or 1))
            self.assertNotIn(msg.param_id & 0xFFFF0000, (0x44010000, 0x41000000, 0x50000000))

    def test_bad_gain_rule_sink_and_unknown_led_touch_nothing(self):
        cases = []
        gains = full_gains(80)
        gains["alt"]["aux"] = 200
        cases.append({"gains": gains})
        gains = full_gains(80)
        gains["stream"]["system"] = True
        cases.append({"gains": gains})
        gains = full_gains(80)
        gains["main"]["mic"] = False
        cases.append({"gains": gains})
        gains = full_gains(80)
        del gains["phones"]["system"]
        cases.append({"gains": gains})
        bad_vol = volumes()
        del bad_vol["game"]
        bad_vol["phones"] = {"pct": 40, "mute": False}
        cases.append({"volumes": bad_vol})
        cases.append({"rules": [{"match": "", "field": "name", "sink": "game"}]})
        cases.append({"rules": [{"match": "x", "field": "path", "sink": "game"}]})
        cases.append({"rules": [{"match": "x", "field": "name", "sink": "phones"}]})
        cases.append({"ledPreset": "Nope"})
        for index, overrides in enumerate(cases):
            self.pactl_calls.clear()
            self.sent.clear()
            self.chunks.clear()
            self.dev_port_calls = 0
            self.write_profile(f"Bad{index}", **overrides)
            res = mgame_profiles.load_profile(f"Bad{index}")
            self.assertFalse(res["ok"], overrides)
            self.assertEqual(self.pactl_calls, [], overrides)
            self.assertEqual(self.sent, [], overrides)
            self.assertEqual(self.dev_port_calls, 0, overrides)
            self.assertFalse(os.path.exists(self.undo_path()), overrides)
            self.assertNotIn("applied", json.dumps(res))

    def test_unknown_led_preset_rejected(self):
        self.write_profile("Night", ledPreset="Nope")
        res = mgame_profiles.load_profile("Night")
        self.assertFalse(res["ok"])
        self.assertEqual(self.pactl_calls, [])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.dev_port_calls, 0)
        self.assertFalse(os.path.exists(self.undo_path()))

    def test_linux_failure_does_not_send_frames(self):
        self.write_profile("Night", gains=full_gains(80))
        self.pactl_fail = True
        res = mgame_profiles.load_profile("Night")
        self.assertFalse(res["ok"])
        self.assertEqual(res.get("step"), "volumes")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.chunks, [])
        self.assertEqual(self.dev_port_calls, 0)
        self.assertTrue(self.pactl_calls)
        flat = [arg for call in self.pactl_calls for arg in call]
        self.assertNotIn("toggle", flat)
        self.assertFalse(os.path.exists(os.path.join(mgame.CFG_DIR, "app-rules.json")))

    def test_mic_live_false_stops_before_device(self):
        json.dump({"routeMemory": {"chat": {"game": 64}}}, open(mgame.STATE_PATH, "w"))
        self.write_profile("Night", gains=full_gains(80), ledPreset=None)
        self.live = False
        res = mgame_profiles.load_profile("Night")
        self.assertFalse(res["ok"])
        self.assertIs(res["mic"]["live"], False)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.dev_port_calls, 0)
        self.assertFalse(os.path.exists(os.path.join(mgame.CFG_DIR, "app-rules.json")))
        self.assertNotIn("applied", json.dumps(res))
        saved = json.load(open(mgame.STATE_PATH))
        self.assertEqual(saved["routeMemory"], {"chat": {"game": 64}})

    def test_gains_null_skips_device_and_does_not_invent_115(self):
        json.dump({"routeMemory": {"chat": {"game": 64}}, "ledPreset": "Keep"}, open(mgame.STATE_PATH, "w"))
        self.write_profile("Night", gains=None, ledPreset=None)
        with mock.patch.object(mgame, "dev_port", side_effect=AssertionError("no debía abrir el dispositivo")):
            res = mgame_profiles.load_profile("Night")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["gains"], "skipped")
        self.assertEqual(res["ledPreset"], "skipped")
        self.assertIs(res["mic"]["live"], True)
        self.assertEqual(self.sent, [])
        self.assertEqual(res["deviceUpdated"], 1700000000.0)
        self.assertIsInstance(res["age"], float)
        self.assertGreater(res["age"], 0)
        self.assertNotIn("applied", json.dumps(res))
        self.assertNotIn("115", json.dumps(res))
        saved = json.load(open(mgame.STATE_PATH))
        self.assertEqual(saved["routeMemory"], {"chat": {"game": 64}})
        self.assertEqual(saved["ledPreset"], "Keep")
        self.assertFalse(os.path.exists(md.DEVICE_PATH))

    def test_gains_sent_are_allowlisted_and_null_led_skips(self):
        self.write_profile("Night", gains=full_gains(80), ledPreset=None)
        res = mgame_profiles.load_profile("Night")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["gains"], "sent 36/36")
        self.assertEqual(res["ledPreset"], "skipped")
        self.assertNotIn("applied", json.dumps(res))
        self.assertEqual(len(self.sent), 36)
        self.assertEqual([len(chunk) for chunk in self.chunks], [16, 16, 4])
        self.assertEqual(len({mgame_proto.parse(frame).param_id for frame in self.sent}), 36)
        for frame in self.sent:
            self.assertEqual(mgame_proto.parse(frame).values, [80])
        flat = [arg for call in self.pactl_calls for arg in call]
        self.assertNotIn("toggle", flat)
        self.assertIn(("set-sink-mute", mgame.NODE_NAMES["game"], "0"), self.pactl_calls)
        self.assertIn(("set-source-mute", mgame.NODE_NAMES["mic"], "0"), self.pactl_calls)

    def test_restore_mute_is_absolute(self):
        self.write_profile("Night", volumes=volumes(pct=40, mute_game=True))
        res = mgame_profiles.load_profile("Night")
        self.assertTrue(res["ok"], res)
        self.assertIn(("set-sink-mute", mgame.NODE_NAMES["game"], "1"), self.pactl_calls)
        self.assertIn(("set-sink-volume", mgame.NODE_NAMES["game"], "40%"), self.pactl_calls)
        flat = [arg for call in self.pactl_calls for arg in call]
        self.assertNotIn("toggle", flat)

    def test_partial_gain_send_stops(self):
        self.write_profile("Night", gains=full_gains(80), ledPreset=None)
        self.fail_chunk = 2
        res = mgame_profiles.load_profile("Night")
        self.assertFalse(res["ok"])
        self.assertEqual(res["gains"], "sent 16/36")
        self.assertEqual(len(self.sent), 16)
        self.assertNotIn("applied", json.dumps(res))
        self.assertNotIn("ledPreset", res)  # no llegó al paso de LEDs

    def test_second_load_while_lock_held_returns_busy(self):
        self.write_profile("Night", gains=full_gains(80))
        held = mgame_lock.acquire(mgame_profiles.restore_target(), blocking=True)
        try:
            res = mgame_profiles.load_profile("Night")
        finally:
            held.release()
        self.assertEqual(res, {"ok": False, "error": "busy"})
        self.assertEqual(self.pactl_calls, [])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.dev_port_calls, 0)

    def test_save_state_preserves_route_memory(self):
        json.dump({"routeMemory": {"chat": {"game": 64}}, "ledPreset": "Keep", "foreign": 7},
                  open(mgame.STATE_PATH, "w"))
        mgame.save_state(mgame.load_state())
        saved = json.load(open(mgame.STATE_PATH))
        self.assertEqual(saved["routeMemory"], {"chat": {"game": 64}})
        self.assertEqual(saved["ledPreset"], "Keep")
        self.assertEqual(saved["foreign"], 7)
        self.assertIn("mic", saved)

    def test_save_incomplete_gains_are_null_not_115(self):
        device = md.empty_state_dict()
        device["updated"] = 50.0
        device["phantom"] = 1
        json.dump(device, open(md.DEVICE_PATH, "w"))
        json.dump({"ledPreset": "Red", "routeMemory": {"chat": {"game": 9}}}, open(mgame.STATE_PATH, "w"))
        res = mgame_profiles.save_profile("Night")
        self.assertTrue(res["ok"], res)
        self.assertIsNone(res["gains"])
        self.assertIsNone(res["ledPreset"])
        self.assertEqual(self.dev_port_calls, 0)
        text = open(os.path.join(mgame.CFG_DIR, "profiles", "Night.json"), encoding="utf-8").read()
        self.assertNotIn("115", text)
        self.assertNotIn("phantom", text)
        self.assertNotIn("fx", text)
        saved = json.loads(text)
        self.assertIsNone(saved["gains"])
        self.assertEqual(saved["deviceUpdated"], 50.0)
        self.assertEqual(json.load(open(mgame.STATE_PATH))["routeMemory"], {"chat": {"game": 9}})

    def test_save_keeps_zero_gain(self):
        device = md.empty_state_dict()
        gains = full_gains(0)
        gains["stream"]["mic"] = 80
        device["gain"] = gains
        device["updated"] = 10
        json.dump(device, open(md.DEVICE_PATH, "w"))
        res = mgame_profiles.save_profile("Zero")
        self.assertTrue(res["ok"], res)
        saved = json.load(open(os.path.join(mgame.CFG_DIR, "profiles", "Zero.json")))
        self.assertEqual(saved["gains"]["phones"]["system"], 0)
        self.assertEqual(saved["gains"]["stream"]["mic"], 80)
        self.assertNotIn(115, {cell for row in saved["gains"].values() for cell in row.values()})

    def test_list_hides_underscore_and_save_delete_reject_it(self):
        self.write_profile("Night")
        self.write_profile("_before-restore")
        self.assertEqual(mgame_profiles.list_profiles(), ["Night"])
        self.assertFalse(mgame_profiles.save_profile("_before-restore")["ok"])
        self.assertFalse(mgame_profiles.delete_profile("_before-restore")["ok"])
        self.assertTrue(os.path.exists(self.undo_path()))
        self.assertTrue(mgame_profiles.delete_profile("Night")["ok"])
        self.assertEqual(mgame_profiles.list_profiles(), [])

    def test_dev_led_preset_records_name_without_dropping_route_memory(self):
        json.dump({"routeMemory": {"chat": {"game": 64}}}, open(mgame.STATE_PATH, "w"))
        with mock.patch.object(md, "load_leds", return_value={}), \
                mock.patch.object(md, "load_led_preset", return_value=([("pad_1", 1, [0, 1, 1])], [])), \
                mock.patch.object(md, "checked_set", return_value=b""), \
                mock.patch.object(mgame, "amidi_send_batch", lambda port, frames: None), \
                mock.patch.object(mgame, "dev_port", return_value="hw:9,9,9"):
            res = mgame.dev_dispatch("dev-led-preset", ["Red"])
        self.assertTrue(res["ok"])
        saved = json.load(open(mgame.STATE_PATH))
        self.assertEqual(saved["ledPreset"], "Red")
        self.assertEqual(saved["routeMemory"], {"chat": {"game": 64}})
        self.assertEqual(self.sent, [])

    def test_null_led_preset_skips_step(self):
        self.write_profile("Night", ledPreset=None, gains=None)
        res = mgame_profiles.load_profile("Night")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["ledPreset"], "skipped")
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
