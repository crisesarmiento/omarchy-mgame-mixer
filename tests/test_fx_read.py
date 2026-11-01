"""Lecturas de FX. No abre device.json real y no manda MIDI."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mgame_device as md  # noqa: E402
import mgame_fx  # noqa: E402

LIVE = [909090901, 909090902, 909090903, 909090904]

MIN_FX = {
    "knob": {
        "param": "01040300",
        "n": 4,
        "words": [{"name": "target", "meaning": "x", "confidence": "observed"}],
        "live": LIVE,
    },
    "blocks": [{
        "param": "41000000",
        "n": 1,
        "role": "vocal",
        "when": "always",
        "writable": True,
    }],
    "family0105": {
        "params": [{
            "id": "01050000",
            "n": 1,
            "writable": True,
            "role": "no enviar",
        }],
    },
    "apply": {"voicePresetSends": ["41000000"], "neverSend": ["01020002"]},
}


def _no_live(testcase, obj, live):
    testcase.assertNotEqual(obj, live)
    if isinstance(obj, dict):
        for value in obj.values():
            _no_live(testcase, value, live)
    elif isinstance(obj, list):
        for value in obj:
            _no_live(testcase, value, live)


class RealFxReadTest(unittest.TestCase):
    def test_list_includes_chef_and_default(self):
        res = mgame_fx.fx_presets()
        self.assertTrue(res["ok"])
        self.assertIn("Chef", res["voice"])
        self.assertIn("Default", res["mic"])
        self.assertEqual(res["voice"], sorted(res["voice"]))
        self.assertEqual(res["mic"], sorted(res["mic"]))
        for name in res["voice"] + res["mic"]:
            self.assertIsInstance(name, str)
            self.assertNotIn("/", name)
            self.assertNotIn("..", name)

    def test_preset_by_listed_name(self):
        voice = mgame_fx.fx_preset("voice", "Chef")
        self.assertEqual(voice["kind"], "voice")
        self.assertEqual(voice["preset"]["name"], "Chef")
        self.assertIn("effects", voice["preset"])
        mic = mgame_fx.fx_preset("mic", "Default")
        self.assertEqual(mic["kind"], "mic")
        self.assertEqual(mic["preset"]["name"], "Default")
        with self.assertRaises(md.DevError):
            mgame_fx.fx_preset("voice", "Default")
        with self.assertRaises(md.DevError):
            mgame_fx.fx_preset("mic", "Chef")
        with self.assertRaises(md.DevError):
            mgame_fx.fx_preset("led", "Chef")
        with self.assertRaises(md.DevError):
            mgame_fx.fx_preset("voice", "No Such Preset")

    def test_raw_key_upper_and_lower_match(self):
        # 01040300 no tiene A-F: hex8 y el archivo son el mismo texto.
        for key in ("01040300", "01040300".lower()):
            state = mgame_fx.fx_state({"raw": {key: [1, 2, 3, 4]}})
            self.assertEqual(state["knob"]["values"], [1, 2, 3, 4])
            self.assertEqual(state["knob"]["source"], "device")
            self.assertEqual(state["knob"]["param"], "01040300")
        # Los params de fábrica son dígitos: upper y lower son el mismo texto.
        # La diferencia de caja se prueba con 0A0B0C0D en el catálogo temporal.
        for key in ("41000000", "41000000".lower()):
            state = mgame_fx.fx_state({"raw": {key: [9]}})
            match = [b for b in state["blocks"] if b["param"].upper() == "41000000"]
            self.assertEqual(match[0]["values"], [9])
            self.assertEqual(match[0]["source"], "device")
            self.assertIs(match[0]["writable"], False)

    def test_missing_raw_values_null(self):
        for device in (None, {}, {"raw": None}, {"connected": True, "raw": {}}):
            state = mgame_fx.fx_state(device)
            self.assertIsNone(state["knob"]["values"])
            self.assertEqual(state["knob"]["source"], "absent")
            self.assertIs(state["knob"]["sysexSafe"], True)
            self.assertTrue(state["blocks"])
            for block in state["blocks"]:
                self.assertIsNone(block["values"])
                self.assertEqual(block["source"], "absent")
                self.assertIs(block["writable"], False)
            self.assertIsNone(state["family0105"]["values"])
            self.assertEqual(state["family0105"]["source"], "absent")
            self.assertIs(state["family0105"]["writable"], False)
            self.assertNotIn("01050000", [b["param"] for b in state["blocks"]])

    def test_knob_live_is_not_device_values(self):
        with open(os.path.join(mgame_fx.DATA_DIR, "fx.json"), encoding="utf-8") as fh:
            live = json.load(fh)["knob"]["live"]
        self.assertIsInstance(live, list)
        self.assertNotEqual(live, [1, 2, 3, 4])
        for device in (None, {"raw": {}}):
            state = mgame_fx.fx_state(device)
            self.assertIsNone(state["knob"]["values"])
            self.assertNotIn("live", state["knob"])
            _no_live(self, state, live)
        other = mgame_fx.fx_state({"raw": {"01040300": [1, 2, 3, 4]}})
        self.assertEqual(other["knob"]["values"], [1, 2, 3, 4])
        _no_live(self, other, live)

    def test_high_byte_sets_sysex_safe_false(self):
        state = mgame_fx.fx_state({"raw": {"41000000": [1, 0x80, 3]}})
        block = next(b for b in state["blocks"] if b["param"].upper() == "41000000")
        self.assertEqual(block["values"], [1, 0x80, 3])
        self.assertIs(block["sysexSafe"], False)
        safe = mgame_fx.fx_state({"raw": {"41000000": [0x7F]}})
        block = next(b for b in safe["blocks"] if b["param"].upper() == "41000000")
        self.assertIs(block["sysexSafe"], True)
        wide = mgame_fx.fx_state({"raw": {"41000000": [0x7F0000]}})
        block = next(b for b in wide["blocks"] if b["param"].upper() == "41000000")
        self.assertEqual(block["values"], [0x7F0000])
        self.assertIs(block["sysexSafe"], True)
        knob = mgame_fx.fx_state({"raw": {"01040300": [0x80, 0, 0, 0]}})
        self.assertEqual(knob["knob"]["values"], [0x80, 0, 0, 0])
        self.assertIs(knob["knob"]["sysexSafe"], False)
        fam = mgame_fx.fx_state({"raw": {"01050000": [0x80]}})
        self.assertEqual(fam["family0105"]["values"], [0x80])
        self.assertIs(fam["family0105"]["sysexSafe"], False)
        self.assertIs(fam["family0105"]["writable"], False)

    def test_result_is_json_and_not_frames(self):
        for obj in (
            mgame_fx.fx_presets(),
            mgame_fx.fx_preset("voice", "Chef"),
            mgame_fx.fx_state(None),
            mgame_fx.fx_state({"raw": {"01040300": [0x80]}}),
        ):
            self.assertIsInstance(obj, dict)
            self.assertNotIn("frames", obj)
            self.assertNotIn("apply", obj)
            json.dumps(obj)

    def test_source_does_not_send(self):
        path = os.path.join(os.path.dirname(__file__), "..", "mgame_fx.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        for word in ("amidi", "checked_set", "build_set", "build_get", "send_frames", "subprocess"):
            self.assertNotIn(word, src)
        self.assertIs(mgame_fx.DevError, md.DevError)


class IsolatedFxReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = self.tmp.name
        stack = mock.patch.object(mgame_fx, "DATA_DIR", self.data)
        self.addCleanup(stack.stop)
        stack.start()
        os.makedirs(os.path.join(self.data, "voice_presets"))
        os.makedirs(os.path.join(self.data, "mic_presets"))

    def write_fx(self, doc=None):
        with open(os.path.join(self.data, "fx.json"), "w", encoding="utf-8") as fh:
            json.dump(MIN_FX if doc is None else doc, fh)

    def write_preset(self, kind, filename, doc):
        folder = "voice_presets" if kind == "voice" else "mic_presets"
        with open(os.path.join(self.data, folder, filename), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

    def test_non_string_name_ignored(self):
        self.write_preset("voice", "a.json", {"name": "Alpha"})
        self.write_preset("voice", "b.json", {"name": 1})
        self.write_preset("voice", "c.json", {"name": None})
        self.write_preset("voice", "d.json", {"name": ["Chef"]})
        self.write_preset("voice", "e.json", {"marker": "sin nombre"})
        self.write_preset("mic", "ok.json", {"name": "Default"})
        with open(os.path.join(self.data, "voice_presets", "broken.json"), "w", encoding="utf-8") as fh:
            fh.write("{")
        res = mgame_fx.fx_presets()
        self.assertEqual(res["voice"], ["Alpha"])
        self.assertEqual(res["mic"], ["Default"])

    def test_lookup_uses_name_field_not_filename(self):
        self.write_preset("voice", "weird.json", {"name": "Chef", "marker": "by-field"})
        self.assertEqual(mgame_fx.fx_presets()["voice"], ["Chef"])
        got = mgame_fx.fx_preset("voice", "Chef")
        self.assertEqual(got["preset"]["marker"], "by-field")
        self.assertEqual(got["kind"], "voice")
        with self.assertRaises(md.DevError):
            mgame_fx.fx_preset("voice", "weird")
        with self.assertRaises(md.DevError):
            mgame_fx.fx_preset("voice", "weird.json")

    def test_path_traversal_name_rejected(self):
        secret = os.path.join(self.data, "secret.json")
        with open(secret, "w", encoding="utf-8") as fh:
            json.dump({"name": "secret", "pwned": True}, fh)
        self.write_preset("voice", "Chef.json", {"name": "Chef", "marker": "inside"})
        opened = []
        real_open = open

        def tracking(path, *args, **kwargs):
            opened.append(os.path.abspath(path))
            return real_open(path, *args, **kwargs)

        names = (
            "../secret",
            "../secret.json",
            "..\\secret",
            "/etc/passwd",
            "Chef/../../secret.json",
            "voice_presets/../secret.json",
            "..",
            ".",
        )
        with mock.patch("builtins.open", tracking):
            for name in names:
                with self.subTest(name=name):
                    with self.assertRaises(md.DevError):
                        mgame_fx.fx_preset("voice", name)
            good = mgame_fx.fx_preset("voice", "Chef")
        self.assertEqual(good["preset"]["marker"], "inside")
        self.assertNotIn("pwned", good["preset"])
        self.assertNotIn(os.path.abspath(secret), opened)
        with self.assertRaises(md.DevError):
            mgame_fx.fx_preset("voice", "secret")

    def test_live_not_copied_and_writable_false(self):
        self.write_fx()
        missing = mgame_fx.fx_state(None)
        self.assertIsNone(missing["knob"]["values"])
        self.assertEqual(missing["knob"]["source"], "absent")
        self.assertNotIn("live", missing["knob"])
        _no_live(self, missing, LIVE)
        present = mgame_fx.fx_state({"raw": {"01040300": [1, 2, 3, 4]}})
        self.assertEqual(present["knob"]["values"], [1, 2, 3, 4])
        self.assertNotEqual(present["knob"]["values"], LIVE)
        _no_live(self, present, LIVE)
        self.assertIs(present["blocks"][0]["writable"], False)
        self.assertIs(present["family0105"]["writable"], False)
        self.assertEqual(present["family0105"]["id"], "01050000")
        self.assertNotIn("01050000", [b["param"] for b in present["blocks"]])
        self.assertNotIn("apply", present)
        self.assertNotIn("voicePresetSends", present)

    def test_case_and_high_byte_on_temp_catalog(self):
        self.write_fx()
        for key in ("01040300", "01040300".lower()):
            state = mgame_fx.fx_state({"raw": {key: [4, 5, 6, 7]}})
            self.assertEqual(state["knob"]["values"], [4, 5, 6, 7])
            self.assertEqual(state["knob"]["source"], "device")
        lower = mgame_fx.fx_state({"raw": {"41000000": [0x80]}})
        self.assertEqual(lower["blocks"][0]["values"], [0x80])
        self.assertEqual(lower["blocks"][0]["source"], "device")
        self.assertIs(lower["blocks"][0]["sysexSafe"], False)
        self.assertIs(lower["blocks"][0]["writable"], False)
        upper = mgame_fx.fx_state({"raw": {"41000000": [0x7F]}})
        self.assertEqual(upper["blocks"][0]["values"], [0x7F])
        self.assertIs(upper["blocks"][0]["sysexSafe"], True)
        # 01040300 no tiene A-F. Este param sí, y tiene que matchear igual.
        doc = json.loads(json.dumps(MIN_FX))
        doc["blocks"].append({
            "param": "0A0B0C0D", "n": 1, "role": "caja", "when": "always", "writable": True,
        })
        self.write_fx(doc)
        for key in ("0A0B0C0D", "0a0b0c0d", "0A0b0C0d"):
            state = mgame_fx.fx_state({"raw": {key: [0x11]}})
            match = [b for b in state["blocks"] if b["param"].upper() == "0A0B0C0D"]
            self.assertEqual(match[0]["values"], [0x11], key)
            self.assertEqual(match[0]["source"], "device")
            self.assertIs(match[0]["writable"], False)

    def test_device_string_is_not_a_path(self):
        sneak = os.path.join(self.data, "sneak.json")
        with open(sneak, "w", encoding="utf-8") as fh:
            json.dump({"raw": {"01040300": [9, 9, 9, 9]}, "pwned": True}, fh)
        self.write_fx()
        with self.assertRaises(md.DevError):
            mgame_fx.fx_state(sneak)
        with self.assertRaises(md.DevError):
            mgame_fx.fx_state(["raw"])

    def test_bad_catalog(self):
        with self.assertRaises(md.DevError):
            mgame_fx.fx_state(None)
        with open(os.path.join(self.data, "fx.json"), "w", encoding="utf-8") as fh:
            fh.write("{")
        with self.assertRaises(md.DevError):
            mgame_fx.fx_state({})


class CliReadTest(unittest.TestCase):
    def test_dev_fx_does_not_send(self):
        import mgame
        with mock.patch.object(mgame, "amidi_send", side_effect=AssertionError("send")), \
             mock.patch.object(mgame, "amidi_send_batch", side_effect=AssertionError("batch")), \
             mock.patch.object(mgame, "dev_port", side_effect=AssertionError("port")):
            listed = mgame.dev_fx("dev-fx-presets", [])
            one = mgame.dev_fx("dev-fx-preset", ["voice", "Chef"])
            state = mgame.dev_fx("dev-fx", [])
        self.assertIn("Chef", listed["voice"])
        self.assertIn("Default", listed["mic"])
        self.assertEqual(one["preset"]["name"], "Chef")
        self.assertIs(state["knob"]["writable"] if "writable" in state["knob"] else False, False)
        self.assertTrue(all(block["writable"] is False for block in state["blocks"]))
        with self.assertRaises(md.DevError):
            mgame.dev_fx("dev-fx-preset", ["voice", "../fx.json"])


if __name__ == "__main__":
    unittest.main()
