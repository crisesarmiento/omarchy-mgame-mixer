import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mgame_proto as p  # noqa: E402

# (hex, param, values) — capturadas del dispositivo real
GOLDEN = [
    ("F0 00 01 05 42 00 01 1C 01 02 01 00 00 00 00 17 F7", 0x0102011C, [0]),
    ("F0 00 01 05 42 00 01 1C 01 02 01 01 00 00 00 16 F7", 0x0102011C, [1]),
    ("F0 00 01 05 42 00 01 00 00 02 00 00 00 02 00 33 F7", 0x00020000, [0x00020000]),
    ("F0 00 01 05 42 00 01 0C 02 02 01 00 00 00 00 26 F7", 0x0102020C, [0]),
    ("F0 00 01 05 42 00 01 00 00 08 41 00 00 73 00 7B F7", 0x41080000, [0x00730000]),
    # multivalor (sysex.log)
    ("F0 00 01 05 42 00 02 00 00 02 44 03 03 03 03 03 03 01 01 5C F7",
     0x44020000, [0x03030303, 0x01010303]),
    ("F0 00 01 05 42 00 04 00 03 04 01 02 00 00 41 7F 00 00 00 1D 00 00 00 31 00 00 00 1C F7",
     0x01040300, [0x41000002, 0x7F, 0x1D, 0x31]),
    ("F0 00 01 05 42 00 06 00 00 07 41 01 7F 01 52 19 50 02 38 34 02 13 7F 00 00 00 00 02 46 00 32 0E 00 3C 50 18 F7",
     0x41070000, None),
    ("F0 00 01 05 42 00 0B 00 00 00 41 07 00 10 00 40 40 7F 00 27 00 34 10 00 00 20 00 3F 00 34 00 00 00 20 00 3F 00 34 00 00 00 20 00 3F 00 34 00 00 00 20 00 3F 00 34 00 1F F7",
     0x41000000, None),
    # byte 5 = 0x01 (log real)
    ("F0 00 01 05 42 01 0A 01 00 00 41 40 40 7F 00 28 00 34 10 00 00 20 00 3F 00 34 00 00 00 20 00 3F 00 34 00 00 00 20 00 3F 00 34 00 00 00 20 00 3F 00 34 00 34 F7",
     0x41000001, None),
]


class TestProto(unittest.TestCase):
    def test_golden_parse_and_rebuild(self):
        for hx, param, values in GOLDEN:
            with self.subTest(hx=hx):
                frame = p.from_hex(hx)
                m = p.parse(frame)
                self.assertIsNotNone(m)
                self.assertEqual(m.kind, "set")
                self.assertEqual(m.param_id, param)
                if values is not None:
                    self.assertEqual(m.values, values)
                self.assertEqual(len(m.values), m.count)
                self.assertEqual(p.build_set(m.param_id, m.values, m.variant), frame)
                self.assertEqual(p.to_hex(frame), hx)

    def test_get_roundtrip(self):
        f = p.build_get(0x0102011C)
        self.assertEqual(len(f), 13)
        m = p.parse(f)
        self.assertEqual((m.kind, m.param_id, m.sub), ("get", 0x0102011C, 0))
        self.assertEqual(p.parse(p.build_get(0x0102011C, 3)).sub, 3)

    def test_checksum_vector(self):
        frame = p.from_hex("F0 00 01 05 42 00 01 1C 01 02 01 01 00 00 00 16 F7")
        self.assertEqual(p.checksum(frame[1:-2]), 0x16)

    def test_bad_checksum(self):
        self.assertIsNone(p.parse(p.from_hex("F0 00 01 05 42 00 01 1C 01 02 01 01 00 00 00 17 F7")))

    def test_bad_length(self):
        self.assertIsNone(p.parse(p.from_hex("F0 00 01 05 42 00 02 1C 01 02 01 01 00 00 00 16 F7")))
        self.assertIsNone(p.parse(p.from_hex("F0 00 01 05 42 00 01 1C 01 02 01 01 00 00 16 F7")))

    def test_bad_header_and_terminator(self):
        self.assertIsNone(p.parse(p.from_hex("F0 00 01 05 43 00 01 1C 01 02 01 01 00 00 00 16 F7")))
        self.assertIsNone(p.parse(p.from_hex("F0 00 01 05 42 00 01 1C 01 02 01 01 00 00 00 16 00")))

    def test_high_bytes_rejected(self):
        with self.assertRaises(ValueError):
            p.build_set(0x80, [0])
        with self.assertRaises(ValueError):
            p.build_set(1, [0x80000000])
        with self.assertRaises(ValueError):
            p.build_get(0x80)
        self.assertEqual(len(p.build_get(0x100)), 13)  # 00 01 00 00 cabe en 7 bits

    def test_bad_hex(self):
        with self.assertRaises(ValueError):
            p.from_hex("F0 ZZ")


if __name__ == "__main__":
    unittest.main()
