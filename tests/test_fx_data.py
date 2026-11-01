"""Voice-FX / mic-FX data. No hardware, no network."""
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "data", "tools"))
import convert_fx as fx  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")

DANGEROUS = (0x5F000001, 0x50000010, 0x501FFFFF, 0x01020002, 0x01020004)


def _record(local_id, values):
    body = [1, 16]
    for v in values:
        body.extend([16, 1, 7, v])
    words = [0, 0, local_id, 0] + body
    words[0] = len(words) * 4
    words[3] = (len(words) - 4) * 4
    return words


def _stream(records):
    words = [8, 0, 0]
    for rec in records:
        words.extend(rec)
    return struct.pack("<%dI" % len(words), *words)


def _walk_ints(obj, out):
    if isinstance(obj, bool):
        return
    if isinstance(obj, int):
        out.append(obj)
    elif isinstance(obj, str):
        if len(obj) == 8 and all(c in "0123456789abcdefABCDEF" for c in obj):
            out.append(int(obj, 16))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk_ints(k, out)
            _walk_ints(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_ints(v, out)


class TestFxParse(unittest.TestCase):
    def test_parse_stream_synthetic(self):
        raw = _stream([_record(307, [0x41000000, 0x7F, 0, fx.NAME_TAG])])
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(raw)
            path = f.name
        try:
            recs = fx.parse_stream(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0][0], 307)
        self.assertEqual(recs[0][2], [0x41000000, 0x7F, 0, fx.NAME_TAG])

    def test_parse_stream_rejects_bad_preamble(self):
        raw = struct.pack("<3I", 1, 0, 0)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(raw)
            path = f.name
        try:
            with self.assertRaises(ValueError):
                fx.parse_stream(path)
        finally:
            os.unlink(path)

    def test_name_and_drops(self):
        # Ogre, plus a dangerous id, a high byte, and a 0x50 preset id.
        name = struct.pack("<8s", b"T2dyZQ==")
        name_words = list(struct.unpack("<2I", name))
        values = [
            0x41000000, 0x100007,
            0x41000001, 0x80,          # byte >= 0x80, drop
            0x5F000001, 1,             # dangerous id, drop
            0x50000010, 2,             # dangerous window, drop
            0x01020002, 3,             # dangerous id, drop
            0x41040000, 0x7F,
            0, fx.NAME_TAG,
        ] + name_words + [0]
        pairs, got = fx.pairs_before_name(values)
        self.assertEqual(got, "Ogre")
        self.assertEqual(pairs, [(0x41000000, 0x100007), (0x41040000, 0x7F)])
        blocks = fx.group_blocks(pairs)
        self.assertEqual(blocks["41000000"], [0x100007])
        self.assertEqual(blocks["41040000"], [0x7F])
        self.assertNotIn("41070000", blocks)
        for pid, val in pairs:
            self.assertFalse(fx.is_dangerous(pid))
            self.assertFalse(fx.is_dangerous(val))
            self.assertTrue(fx.bytes_ok(pid) and fx.bytes_ok(val))

    def test_effects_split_on_name_not_eight(self):
        def one(name_b64, marker):
            raw = struct.pack("<8s", name_b64)
            words = list(struct.unpack("<2I", raw))
            return [0x41000000, marker, 0, fx.NAME_TAG] + words + [0, 0]

        values = one(b"T2dyZQ==", 1) + one(b"UGhvbmU=", 2)
        effects = fx.effects_from_values(values)
        self.assertEqual([e["name"] for e in effects], ["Ogre", "Phone"])
        self.assertEqual(effects[0]["blocks"]["41000000"], [1])
        self.assertEqual(effects[1]["blocks"]["41000000"], [2])

    def test_generated_json_is_safe(self):
        fx_path = os.path.join(DATA, "fx.json")
        if not os.path.isfile(fx_path):
            self.skipTest("data/fx.json not generated")
        files = [fx_path]
        for folder in ("voice_presets", "mic_presets"):
            d = os.path.join(DATA, folder)
            if not os.path.isdir(d):
                continue
            files.extend(os.path.join(d, n) for n in os.listdir(d) if n.endswith(".json"))
        self.assertGreaterEqual(len(files), 1)
        for path in files:
            with open(path) as f:
                doc = json.load(f)
            # neverSend is the denylist; those strings are not ids we emit.
            if isinstance(doc, dict) and "apply" in doc:
                doc = dict(doc)
                doc["apply"] = {k: v for k, v in doc["apply"].items() if k != "neverSend"}
            ints = []
            _walk_ints(doc, ints)
            for n in ints:
                self.assertTrue(fx.bytes_ok(n), "%s has high byte in %08X" % (path, n))
                self.assertFalse(fx.is_dangerous(n), "%s has dangerous id %08X" % (path, n))


if __name__ == "__main__":
    unittest.main()
