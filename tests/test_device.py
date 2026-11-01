import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mgame  # noqa: E402
import mgame_device as md  # noqa: E402
import mgame_proto as p  # noqa: E402

LEDS = {
    "pad_1": {"param": 0x01030C00, "n": 3, "label": "Pad 1"},
    "mic_mute": {"param": 0x01030100, "n": 3, "label": "Mic"},
    "bar_0": {"param": 0x01010000, "n": 4, "label": "Bar"},
}
LEDS_JSON = {"controls": {
    "pad_1": {"param": "01030C00", "label": "Pad 1"},
    "mic_mute": {"param": "01030100", "label": "Mic"},
    "bar_0": {"param": "01010000", "label": "Bar"},
}}


def msg(hex_str):
    m = p.parse(p.from_hex(hex_str))
    assert m is not None, hex_str
    return m


def fresh():
    return md.DeviceState(LEDS)


class IngestTest(unittest.TestCase):
    def test_gain_effective_phantom_latch_led(self):
        d = fresh()
        d.ingest(msg("F0 00 01 05 42 00 01 00 00 00 44 73 00 00 00 00 F7"))
        self.assertEqual(d.gain["stream"]["mic"], 115)
        d.ingest(msg("F0 00 01 05 42 00 01 00 00 03 00 01 00 00 00 33 F7"))
        self.assertEqual(d.phantom, 1)
        d.ingest(msg("F0 00 01 05 42 00 01 02 01 02 01 00 00 00 00 31 F7"))
        self.assertIs(d.buttons["mic_mute"], False)
        d.ingest(msg("F0 00 01 05 42 00 03 00 0C 03 01 00 00 00 00 01 00 00 00 34 00 00 00 70 F7"))
        self.assertEqual(d.leds["pad_1"], {"param": "01030C00", "mode": 0, "active": 1, "idle": 52})

    def test_gain_addressing(self):
        d = fresh()
        known, changed = d.ingest(p.parse(p.build_set(0x44000000 + 5 * 0x100 + 8, [42])))
        self.assertTrue(known and changed)
        self.assertEqual(d.gain["phones"]["sampler"], 42)
        d.ingest(p.parse(p.build_set(0x44010000 + 2 * 0x100 + 10, [7])))
        self.assertEqual(d.effective["alt"]["system"], 7)
        # fuera de rango / impar -> raw, no gain
        known, _ = d.ingest(p.parse(p.build_set(0x44000600, [1])))
        self.assertFalse(known)
        self.assertIn("44000600", d.raw)

    def test_mute_vector(self):
        d = fresh()
        d.ingest(msg("F0 00 01 05 42 00 02 00 00 02 44 00 00 00 00 00 00 00 00 70 F7"))
        self.assertTrue(all(v == [] for v in d.muted.values()))
        d.ingest(msg("F0 00 01 05 42 00 02 00 00 02 44 03 03 03 03 03 03 01 01 5C F7"))
        for dest in md.DESTS:
            self.assertEqual(d.muted[dest], ["mic", "game"])
        d.ingest(msg("F0 00 01 05 42 00 02 00 00 02 44 28 28 28 28 28 28 00 00 00 F7"))
        self.assertEqual(d.muted["phones"], ["aux", "system"])
        d.ingest(msg("F0 00 01 05 42 00 02 00 00 02 44 17 17 17 17 17 17 01 01 64 F7"))
        self.assertEqual(d.muted["main"], ["mic", "game", "chat", "sampler"])

    def test_mute_vector_per_dest_bytes(self):
        d = fresh()
        d.ingest(p.parse(p.build_set(md.MUTE_VECTOR, [0x04030201, 0x00002010])))
        self.assertEqual(d.muted["stream"], ["mic"])
        self.assertEqual(d.muted["chat"], ["game"])
        self.assertEqual(d.muted["alt"], ["mic", "game"])
        self.assertEqual(d.muted["sampler"], ["chat"])
        self.assertEqual(d.muted["main"], ["sampler"])
        self.assertEqual(d.muted["phones"], ["system"])

    def test_mute_map_matches_imute_masks(self):
        d = fresh()
        for param, mask, expect in ((0x01040008, 0x02020202, ["game"]), (0x0104000C, 0x04040404, ["chat"]),
                                    (0x01040010, 0x10101010, ["sampler"]), (0x01040014, 0x28282828, ["aux", "system"])):
            d.ingest(p.parse(p.build_set(param, [mask])))
        self.assertEqual(d.mute_map, {"game_mute": ["game"], "chat_mute": ["chat"],
                                      "sampler_mute": ["sampler"], "main_alt_mute": ["aux", "system"]})

    def test_buttons_and_hw(self):
        d = fresh()
        self.assertEqual(d.hw()["page"], None)
        for param, val in ((0x0102010E, 0), (0x01020112, 1), (0x01020110, 1), (0x0102010C, 1)):
            d.ingest(p.parse(p.build_set(param, [val])))
        hw = d.hw()
        self.assertEqual(hw["page"], 2)
        self.assertEqual(hw["bank"], "B")
        self.assertIs(hw["main_alt_mute"], True)
        self.assertIsNone(hw["mic_mute"])
        d.ingest(p.parse(p.build_set(0x0102010E, [1])))
        self.assertEqual(d.hw()["page"], 1)

    def test_unknown_goes_raw_and_unknown_led_param(self):
        d = fresh()
        known, changed = d.ingest(msg("F0 00 01 05 42 00 02 00 00 02 44 00 00 00 00 00 00 00 00 70 F7"))
        self.assertTrue(known)
        known, changed = d.ingest(p.parse(p.build_set(0x01030D00, [0, 2, 52])))  # no está en LEDS
        self.assertFalse(known)
        self.assertEqual(d.raw["01030D00"], [0, 2, 52])

    def test_led_array_values(self):
        d = fresh()
        d.ingest(p.parse(p.build_set(0x01010000, [1, 2, 3, 4])))
        self.assertEqual(d.leds["bar_0"]["values"], [1, 2, 3, 4])

    def test_set_leds_migrates_raw(self):
        d = md.DeviceState({})
        d.ingest(p.parse(p.build_set(0x01030C00, [0, 3, 53])))
        self.assertIn("01030C00", d.raw)
        d.set_leds(LEDS)
        self.assertNotIn("01030C00", d.raw)
        self.assertEqual(d.leds["pad_1"]["active"], 3)

    def test_gets_ignored(self):
        d = fresh()
        self.assertEqual(d.ingest(p.parse(p.build_get(0x44000000, 1))), (False, False))
        self.assertEqual(d.ingest(None), (False, False))

    def test_changed_flag_and_save(self):
        d = fresh()
        fr = p.parse(p.build_set(0x44000000, [9]))
        self.assertEqual(d.ingest(fr), (True, True))
        self.assertEqual(d.ingest(fr), (True, False))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "device.json")
            self.assertTrue(d.save(path, changed=True, now=100.0))
            self.assertFalse(d.save(path, changed=False, now=100.1))   # latido aún no
            self.assertTrue(d.save(path, changed=False, now=100.5))
            data = json.load(open(path))
            self.assertEqual(data["gain"]["stream"]["mic"], 9)
            self.assertFalse(os.path.exists(path + ".tmp"))
            for key in ("connected", "updated", "phantom", "gain", "effective", "muted",
                        "buttons", "muteMap", "leds", "raw"):
                self.assertIn(key, data)

    def test_frames_from_dump(self):
        text = "F0 00 01 05 42 00 01 00 00 03 00 01 00 00 00 33 F7\n F0 00 01 05 42 00 01 02\n01 02 01 00 00 00 00 31 F7\n"
        frames = md.frames_from_dump(text)
        self.assertEqual(len(frames), 2)
        self.assertEqual(p.parse(frames[1]).param_id, 0x01020102)


class RefreshTest(unittest.TestCase):
    def test_refresh_frames(self):
        frames = md.refresh_frames(LEDS)
        msgs = [p.parse(f) for f in frames]
        self.assertTrue(all(m is not None and m.kind == "get" for m in msgs))
        params = [(m.param_id, m.sub) for m in msgs]
        self.assertEqual(params[0], (0x01020200, 1))
        self.assertIn((0x44020000, 2), params)
        self.assertIn((0x00030000, 1), params)
        self.assertEqual(sum(1 for q, _ in params if q & 0xFFFF0000 == 0x44000000), 36)
        self.assertEqual(sum(1 for q, _ in params if q & 0xFFFF0000 == 0x44010000), 36)
        for q in (0x01020102, 0x01020106, 0x01020108, 0x0102010A, 0x0102010C, 0x0102010E, 0x01020110, 0x01020112,
                  0x01040008, 0x0104000C, 0x01040010, 0x01040014):
            self.assertIn((q, 1), params)
        self.assertIn((0x01030C00, 3), params)
        self.assertIn((0x01010000, 4), params)
        self.assertEqual(frames[0], p.from_hex("F0 00 01 05 42 02 01 00 02 02 01 30 F7"))

    def test_send_frames_paced(self):
        sent, naps = [], []
        md.send_frames([b"a", b"b", b"c"], sent.append, gap=0.01, sleep=naps.append)
        self.assertEqual(sent, [b"a", b"b", b"c"])
        self.assertEqual(naps, [0.01] * 3)


class AtomicWriteTest(unittest.TestCase):
    def test_single_implementation(self):
        self.assertIs(mgame.atomic_write, md.atomic_write)

    def test_concurrent_writers_never_clobber_or_tear(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "f.json")
            errors = []

            def writer(i):
                try:
                    for j in range(25):
                        md.atomic_write(path, json.dumps({"w": i, "j": j, "pad": "x" * 2000}))
                except Exception as exc:  # pragma: no cover
                    errors.append(exc)
            threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            self.assertEqual(json.load(open(path))["pad"], "x" * 2000)
            self.assertEqual(os.listdir(os.path.dirname(path)), ["f.json"])   # sin temporales sueltos

    def test_failure_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.json")
            with mock.patch.object(md.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    md.atomic_write(path, "x")
            self.assertEqual(os.listdir(tmp), [])


class AllowlistTest(unittest.TestCase):
    def test_allowed(self):
        self.assertTrue(md.is_write_allowed(0x44000000, 1))
        self.assertTrue(md.is_write_allowed(0x44000000 + 5 * 0x100 + 10, 1))
        self.assertTrue(md.is_write_allowed(0x00030000, 1))
        self.assertTrue(md.is_write_allowed(0x01030C00, 3, LEDS))
        self.assertTrue(md.is_write_allowed(0x01010000, 4, LEDS))

    def test_refused(self):
        for param, n in ((0x44010000, 1),        # efectivo: solo lectura
                         (0x44020000, 2),        # vector de mute
                         (0x44000000, 2),        # N incorrecto
                         (0x44000600, 1),        # destino 6
                         (0x44000001, 1),        # fuente impar
                         (0x4400000C, 1),        # fuente 6
                         (0x00030000, 2),
                         (0x5F000000, 1), (0x50000000, 16), (0x41000000, 11), (0x01040300, 4),
                         (0x01020102, 1), (0x01020002, 1), (0x0102020C, 1),
                         (0x01030C00, 3),        # LED sin mapa
                         (0x01030D00, 3)):
            self.assertFalse(md.is_write_allowed(param, n), hex(param))
        self.assertFalse(md.is_write_allowed(0x01030C00, 4, LEDS))   # n distinto del mapa
        self.assertFalse(md.is_write_allowed(0x01030D00, 3, LEDS))   # param fuera del mapa
        self.assertFalse(md.is_write_allowed("44000000", 1))

    def test_led_index_bounds(self):
        def leds(param, n):
            return {"x": {"param": param, "n": n}}
        self.assertTrue(md.is_write_allowed(0x01010800, 4, leds(0x01010800, 4)))
        self.assertFalse(md.is_write_allowed(0x01010900, 4, leds(0x01010900, 4)))
        self.assertTrue(md.is_write_allowed(0x01032000, 3, leds(0x01032000, 3)))
        self.assertFalse(md.is_write_allowed(0x01032100, 3, leds(0x01032100, 3)))
        for param, n in ((0x01010900, 4), (0x01032100, 3), (0x0101FF00, 4)):
            with self.assertRaises(md.DevError):
                md.parse_leds({"controls": {"x": {"param": "%08X" % param, "n": n}}})
        md.parse_leds({"controls": {"x": {"param": "01032000", "n": 3}}})

    def test_real_leds_json_still_valid(self):
        self.assertTrue(md.load_leds(os.path.join(os.path.dirname(md.__file__), "data", "leds.json")))

    def test_leds_json_cannot_open_dangerous_ids(self):
        with self.assertRaises(md.DevError):
            md.parse_leds({"controls": {"x": {"param": "5F000000"}}})
        with self.assertRaises(md.DevError):
            md.parse_leds({"controls": {"x": {"param": "01030C01"}}})
        # aunque entrara a mano en el mapa, la familia se vuelve a comprobar
        self.assertFalse(md.is_write_allowed(0x5F000000, 3, {"x": {"param": 0x5F000000, "n": 3}}))

    def test_checked_set(self):
        with self.assertRaises(md.DevError):
            md.checked_set(0x44010000, [1])
        frame = md.checked_set(0x44000000, [115])
        self.assertEqual(frame, p.from_hex("F0 00 01 05 42 00 01 00 00 00 44 73 00 00 00 00 F7"))


class BuildTest(unittest.TestCase):
    def test_gain(self):
        param, vals = md.build_gain("phones", "sampler", "42")
        self.assertEqual((param, vals), (0x44000508, [42]))
        frame = md.checked_set(param, vals)
        m = p.parse(frame)
        self.assertEqual((m.param_id, m.values), (0x44000508, [42]))
        for bad in (("nope", "mic", "1"), ("stream", "nope", "1"), ("stream", "mic", "128"),
                    ("stream", "mic", "-1"), ("stream", "mic", "1.5"), ("stream", "mic", ""),
                    ("stream", "mic", "0x10"), ("stream", "mic", " 5")):
            with self.assertRaises(md.DevError, msg=str(bad)):
                md.build_gain(*bad)

    def test_phantom_frames_match_docs(self):
        param, vals = md.build_phantom("on")
        self.assertEqual(md.checked_set(param, vals),
                         p.from_hex("F0 00 01 05 42 00 01 00 00 03 00 01 00 00 00 33 F7"))
        param, vals = md.build_phantom("off")
        self.assertEqual(md.checked_set(param, vals),
                         p.from_hex("F0 00 01 05 42 00 01 00 00 03 00 00 00 00 00 34 F7"))
        with self.assertRaises(md.DevError):
            md.build_phantom("maybe")

    def test_led_frame_matches_docs(self):
        param, vals = md.build_led("pad_1", 2, 0x34, 0x00010000, LEDS)
        frame = md.checked_set(param, vals, LEDS)
        self.assertEqual(frame, p.from_hex(
            "F0 00 01 05 42 00 03 00 0C 03 01 00 00 01 00 02 00 00 00 34 00 00 00 6E F7"))

    def test_led_validation(self):
        for bad in ((200, 1, 0), (1, 128, 0), (1, 1, 0x80), (1, 1, 0x00800000), (1, 1, -1), (1, 1, True)):
            with self.assertRaises(md.DevError, msg=str(bad)):
                md.build_led("pad_1", bad[0] if bad[0] != 200 else 200, bad[1], bad[2], LEDS)
        with self.assertRaises(md.DevError):
            md.build_led("nope", 1, 1, 0, LEDS)
        with self.assertRaises(md.DevError):
            md.build_led("bar_0", 1, 1, 0, LEDS)   # array N=4, no es un LED de botón


class PresetTest(unittest.TestCase):
    def test_routing_preset_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.json")
            row = {s: 115 for s in md.SRCS}
            json.dump({"default": {d: row for d in md.DESTS}}, open(path, "w"))
            items = md.load_routing_preset("default", path)
            self.assertEqual(len(items), 36)
            self.assertTrue(all(md.is_write_allowed(it[2], 1) for it in items))
            with self.assertRaises(md.DevError):
                md.load_routing_preset("no_chat_to_stream", path)   # falta en el archivo
            with self.assertRaises(md.DevError):
                md.load_routing_preset("../etc", path)
            with self.assertRaises(md.DevError):
                md.load_routing_preset("default", os.path.join(tmp, "missing.json"))

    def test_led_presets(self):
        with tempfile.TemporaryDirectory() as tmp:
            json.dump({"name": "Red", "leds": {"pad_1": {"mode": 65536, "active": 2, "idle": 52},
                                                "ghost": {"mode": 0, "active": 1, "idle": 1}}},
                      open(os.path.join(tmp, "Red.json"), "w"))
            self.assertEqual(list(md.list_led_presets(tmp)), ["Red"])
            items, skipped = md.load_led_preset("Red", LEDS, tmp)
            self.assertEqual(items, [("pad_1", 0x01030C00, [65536, 2, 52])])
            self.assertEqual(skipped, ["ghost"])
            with self.assertRaises(md.DevError):
                md.load_led_preset("../Red", LEDS, tmp)
            json.dump({"name": "Bad", "leds": {"pad_1": {"mode": 0, "active": 300, "idle": 1}}},
                      open(os.path.join(tmp, "Bad.json"), "w"))
            with self.assertRaises(md.DevError):
                md.load_led_preset("Bad", LEDS, tmp)


class CliTest(unittest.TestCase):
    """dev-* con amidi simulado: nada toca el hardware."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.sent = []
        os.makedirs(os.path.join(t, "led_presets"))
        json.dump(LEDS_JSON, open(os.path.join(t, "leds.json"), "w"))
        row = {s: 115 for s in md.SRCS}
        json.dump({"default": {d: row for d in md.DESTS}}, open(os.path.join(t, "routing.json"), "w"))
        json.dump({"name": "Red", "leds": {"pad_1": {"mode": 65536, "active": 2, "idle": 52}}},
                  open(os.path.join(t, "led_presets", "Red.json"), "w"))
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(md, "LEDS_PATH", os.path.join(t, "leds.json")))
        stack.enter_context(mock.patch.object(md, "LED_PRESET_DIR", os.path.join(t, "led_presets")))
        stack.enter_context(mock.patch.object(md, "ROUTING_PATH", os.path.join(t, "routing.json")))
        stack.enter_context(mock.patch.object(md, "DEVICE_PATH", os.path.join(t, "device.json")))
        stack.enter_context(mock.patch.object(mgame, "STATE_PATH", os.path.join(t, "state.json")))
        stack.enter_context(mock.patch.object(mgame, "find_rawmidi", lambda: "hw:9,9,9"))
        stack.enter_context(mock.patch.object(mgame, "amidi_send", lambda port, frame: self.sent.append((port, frame))))
        self.real_batch = mgame.amidi_send_batch
        stack.enter_context(mock.patch.object(
            mgame, "amidi_send_batch", lambda port, frames: self.sent.extend((port, f) for f in frames)))
        stack.enter_context(mock.patch.object(mgame, "WRITE_GAP", 0))
        self.addCleanup(self.tmp.cleanup)

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mgame.dev_main(argv[0], list(argv[1:]))
        return code, json.loads(out.getvalue())

    def device_json(self, **kw):
        d = md.DeviceState(LEDS)
        for dest, src, v in kw.get("gains", []):
            d.gain[dest][src] = v
        d.save(os.path.join(self.tmp.name, "device.json"))

    def test_gain(self):
        code, res = self.run_cli("dev-gain", "stream", "mic", "115")
        self.assertEqual((code, res["ok"]), (0, True))
        self.assertEqual(self.sent, [("hw:9,9,9", p.from_hex("F0 00 01 05 42 00 01 00 00 00 44 73 00 00 00 00 F7"))])

    def test_invalid_args_send_nothing(self):
        for argv in (("dev-gain", "stream", "mic", "300"), ("dev-gain", "bogus", "mic", "1"),
                     ("dev-gain", "stream", "mic"), ("dev-route", "stream", "mic", "maybe"),
                     ("dev-phantom", "dim"), ("dev-led", "pad_1", "999", "1"),
                     ("dev-led", "ghost", "1", "1"), ("dev-led", "bar_0", "1", "1"),
                     ("dev-led", "pad_1", "1", "1", "128"), ("dev-routing-preset", "evil"),
                     ("dev-led-preset", "../Red"), ("dev-state", "--nope"), ("dev-gain",)):
            code, res = self.run_cli(*argv)
            self.assertEqual(code, 1, argv)
            self.assertFalse(res["ok"], argv)
            self.assertIn("error", res)
        self.assertEqual(self.sent, [])

    def test_main_unknown_dev_command(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            mgame.main(["mgame.py", "dev-format-flash"])
        self.assertEqual(cm.exception.code, 1)
        self.assertFalse(json.loads(out.getvalue())["ok"])

    def test_phantom(self):
        code, res = self.run_cli("dev-phantom", "off")
        self.assertEqual(code, 0)
        self.assertEqual(self.sent[0][1], p.from_hex("F0 00 01 05 42 00 01 00 00 03 00 00 00 00 00 34 F7"))

    def test_led(self):
        code, res = self.run_cli("dev-led", "pad_1", "2", "52", "65536")
        self.assertEqual((code, res["ok"]), (0, True))
        self.assertEqual(self.sent[0][1], p.from_hex(
            "F0 00 01 05 42 00 03 00 0C 03 01 00 00 01 00 02 00 00 00 34 00 00 00 6E F7"))

    def test_led_keeps_current_mode(self):
        d = md.DeviceState(LEDS)
        d.ingest(p.parse(p.build_set(0x01030C00, [0x00010000, 1, 1])))
        d.save(os.path.join(self.tmp.name, "device.json"))
        self.run_cli("dev-led", "pad_1", "2", "52")
        self.assertEqual(p.parse(self.sent[0][1]).values, [0x00010000, 2, 52])

    def test_led_missing_data_file(self):
        os.remove(md.LEDS_PATH)
        code, res = self.run_cli("dev-led", "pad_1", "2", "52")
        self.assertEqual((code, res["ok"]), (1, False))
        self.assertEqual(self.sent, [])

    def test_led_presets(self):
        code, res = self.run_cli("dev-led-presets")
        self.assertEqual((code, res), (0, {"ok": True, "presets": ["Red"]}))
        code, res = self.run_cli("dev-led-preset", "Red")
        self.assertEqual((code, res["ok"], res["count"]), (0, True, 1))
        self.assertEqual(len(self.sent), 1)

    def test_led_mode_must_be_known(self):
        for mode in ("1", "4294967295", "128"):
            code, res = self.run_cli("dev-led", "pad_1", "2", "52", mode)
            self.assertEqual((code, res["ok"]), (1, False), mode)
        self.assertEqual(self.sent, [])
        self.assertEqual(md.known_led_modes(), frozenset({65536}))
        code, _ = self.run_cli("dev-led", "pad_1", "2", "52", "65536")
        self.assertEqual(code, 0)

    def test_presets_use_one_amidi_call(self):
        calls = []

        def fake_run(*argv, timeout=5):
            calls.append(argv)
            return mock.Mock(returncode=0, stderr="")
        with mock.patch.object(mgame, "run", fake_run), \
                mock.patch.object(mgame, "amidi_send_batch", self.real_batch):
            code, res = self.run_cli("dev-routing-preset", "default")
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)               # 36 tramas <= 64: una sola llamada
        argv = calls[0]
        self.assertEqual(argv[:4], ("amidi", "-p", "hw:9,9,9", "-S"))
        words = argv[4].split(" ")
        self.assertEqual(len(words), 36)
        self.assertTrue(all(w.startswith("F0") and w.endswith("F7") for w in words))

    def test_batch_chunks_at_limit(self):
        calls = []

        def fake_run(*argv, timeout=5):
            calls.append(argv)
            return mock.Mock(returncode=0, stderr="")
        frames = [p.build_get(0x44000000 + i * 2, 1) for i in range(6)] * 25   # 150 tramas
        with mock.patch.object(mgame, "run", fake_run):
            self.assertTrue(mgame.amidi_send_batch_quiet("hw:1,0,0", frames))
        self.assertEqual([len(c[4].split(" ")) for c in calls], [64, 64, 22])

    def test_batch_failure_raises(self):
        with mock.patch.object(mgame, "run", lambda *a, **k: mock.Mock(returncode=1, stderr="busy")):
            with self.assertRaises(SystemExit):
                self.real_batch("hw:1,0,0", [p.build_get(0x44000000, 1)])

    def test_routing_preset(self):
        code, res = self.run_cli("dev-routing-preset", "default")
        self.assertEqual((code, res["ok"], res["count"]), (0, True, 36))
        self.assertEqual(len(self.sent), 36)
        self.assertEqual(len({p.parse(f).param_id for _, f in self.sent}), 36)
        mem = json.load(open(mgame.STATE_PATH))["routeMemory"]
        self.assertEqual(mem["phones"]["system"], 115)
        code, res = self.run_cli("dev-routing-preset", "no_chat_to_stream")  # falta en el archivo
        self.assertEqual(code, 1)

    def test_route_off_on_remembers_gain(self):
        self.device_json(gains=[("chat", "game", 90)])
        code, res = self.run_cli("dev-route", "chat", "game", "off")
        self.assertEqual(code, 0)
        self.assertEqual(p.parse(self.sent[-1][1]).values, [0])
        self.assertEqual(p.parse(self.sent[-1][1]).param_id, 0x44000102)
        self.assertEqual(json.load(open(mgame.STATE_PATH))["routeMemory"]["chat"]["game"], 90)
        self.run_cli("dev-route", "chat", "game", "on")
        self.assertEqual(p.parse(self.sent[-1][1]).values, [90])
        self.run_cli("dev-route", "stream", "aux", "on")   # sin memoria -> 115
        self.assertEqual(p.parse(self.sent[-1][1]).values, [115])

    def test_route_off_when_already_zero_keeps_memory(self):
        json.dump({"routeMemory": {"chat": {"game": 64}}}, open(mgame.STATE_PATH, "w"))
        self.device_json(gains=[("chat", "game", 0)])
        self.run_cli("dev-route", "chat", "game", "off")
        self.assertEqual(json.load(open(mgame.STATE_PATH))["routeMemory"]["chat"]["game"], 64)

    def test_save_state_preserves_route_memory(self):
        json.dump({"routeMemory": {"chat": {"game": 64}}}, open(mgame.STATE_PATH, "w"))
        mgame.save_state(mgame.load_state())
        saved = json.load(open(mgame.STATE_PATH))
        self.assertEqual(saved["routeMemory"], {"chat": {"game": 64}})
        self.assertIn("mic", saved)

    def test_remember_gains_merges_foreign_keys(self):
        json.dump({"mic": {"enabled": False}, "foreign": 7, "routeMemory": {"chat": {"game": 64}}},
                  open(mgame.STATE_PATH, "w"))
        mgame.remember_gains([("stream", "mic", 100)])
        saved = json.load(open(mgame.STATE_PATH))
        self.assertEqual(saved["foreign"], 7)
        self.assertEqual(saved["mic"], {"enabled": False})
        self.assertEqual(saved["routeMemory"], {"chat": {"game": 64}, "stream": {"mic": 100}})

    def test_dev_state_reads_file(self):
        self.device_json()
        code, res = self.run_cli("dev-state")
        self.assertEqual((code, res["ok"]), (0, True))
        self.assertIn("gain", res)

    def test_dev_state_without_file_is_unknown_not_error(self):
        code, res = self.run_cli("dev-state")
        self.assertEqual(code, 0)
        self.assertIsNone(res["phantom"])
        self.assertFalse(res["connected"])

    def test_amidi_failure_becomes_json_error(self):
        def boom(port, frame):
            raise SystemExit("amidi no pudo enviar")
        with mock.patch.object(mgame, "amidi_send", boom):
            code, res = self.run_cli("dev-gain", "stream", "mic", "1")
        self.assertEqual((code, res["ok"]), (1, False))

    def test_dev_state_direct_read_mocked_amidi(self):
        """Sin listener: se leen las respuestas con `amidi -d` (simulado)."""
        dump = "\n".join(p.to_hex(p.build_set(par, vals)) for par, vals in (
            (0x44000000, [115]), (0x00030000, [1]), (0x44020000, [0x03030303, 0x01010303]),
            (0x01030C00, [0, 1, 52]))) + "\n"

        class FakeRx:
            stderr = io.StringIO("")

            def poll(self):
                return None

            def communicate(self, timeout=None):
                return dump, ""

        with mock.patch.object(mgame, "listener_state", lambda: {"active": False}), \
                mock.patch.object(mgame.subprocess, "Popen", lambda *a, **k: FakeRx()), \
                mock.patch.object(mgame, "amidi_send_quiet", lambda port, f: True), \
                mock.patch.object(mgame, "REFRESH_GAP", 0), \
                mock.patch.object(mgame.time, "sleep", lambda s: None):
            code, res = self.run_cli("dev-state", "--refresh")
        self.assertEqual((code, res["ok"]), (0, True))
        self.assertEqual(res["gain"]["stream"]["mic"], 115)
        self.assertEqual(res["phantom"], 1)
        self.assertEqual(res["muted"]["stream"], ["mic", "game"])
        self.assertEqual(res["leds"]["pad_1"]["idle"], 52)
        self.assertTrue(res["connected"])
        self.assertTrue(os.path.exists(md.DEVICE_PATH))


if __name__ == "__main__":
    unittest.main()
