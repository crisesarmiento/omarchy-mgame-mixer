#!/usr/bin/env python3
"""Regenerate data/leds.json (controls), data/led_presets/*.json and
data/routing_presets.json from the Mac app's preset files.

Usage:
  convert_leds.py [--resources DIR] [--data DIR] [--asm FILE]

--resources  Mac app Resources dir (default: ~/.cache/mgame-mac/root/Applications/
             M-Game RGB Dual.app/Contents/Resources)
--data       output dir (default: the repo's data/ next to this script's parent)
--asm        optional objdump of the Panel binary; when given, the 0..127 LED
             palette is re-extracted from MA::LAppEngine::InitColorArrays and
             written to leds.json. Without it the existing palette is kept.

stdlib only. Input files are untrusted data; they are only parsed, never run.
"""
import argparse
import glob
import json
import os
import re
import struct

DEFAULT_RES = os.path.expanduser(
    "~/.cache/mgame-mac/root/Applications/M-Game RGB Dual.app/Contents/Resources")

# ---------------------------------------------------------------- controls
# local id (in *.MGameRGBDualLEDs) -> (name, device param, n, label, kind)
def _controls():
    c = []
    # 10 sample slots = 2 banks x 5 pads. local id 0x78 + 8k -> 0x01030A00 + 0x100*k
    for k in range(10):
        bank, pad = divmod(k, 5)
        c.append((0x78 + 8 * k, "sample_%d" % (k + 1), 0x01030A00 + 0x100 * k, 3,
                  "Bank %d Sample %d" % (bank + 1, pad + 1), "button"))
    # mute-button LEDs (order inferred from the IMute slot order)
    for lid, nm, par, lab in ((0xCA, "mute_game", 0x01030300, "Game Mute"),
                              (0xCD, "mute_chat", 0x01030400, "Chat Mute"),
                              (0xD0, "mute_sampler", 0x01030500, "Sampler Mute"),
                              (0xD3, "mute_main_alt", 0x01030600, "Main/Alt Mute")):
        c.append((lid, nm, par, 3, lab, "button"))
    for i, (lid, par) in enumerate(((0xD6, 0x01030700), (0xDA, 0x01030900),
                                    (0xDE, 0x01031400), (0xE2, 0x01031500))):
        c.append((lid, "voice_fx_%d" % (i + 1), par, 3, "Voice FX %d" % (i + 1), "button"))
    c.append((0xF4, "mic_mute", 0x01030100, 3, "Mic Mute (mute-all)", "button"))
    c.append((0xF9, "swear", 0x01030200, 3, "Censor ($%^#*)", "button"))
    # 13 LED labels: function of each not resolved (no skin id -> label mapping found)
    lab_par = [0x01030000, 0x01030800] + [0x01031600 + 0x100 * i for i in range(11)]
    for i, par in enumerate(lab_par):
        c.append((0x105 + i, "led_label_%d" % i, par, 3, "LED label %d" % i, "button"))
    for i in range(9):
        c.append((0x112 + i, "led_array_%d" % i, 0x01010000 + 0x100 * i, 4,
                  "LED array %d" % i, "array"))
    return c

CONTROLS = _controls()

# Legacy names used by the helper (device-api.md): pad_N = param 0x01030C00 + 0x100*(N-1)
ALIASES = {"pad_%d" % (i + 1): "sample_%d" % (i + 3) for i in range(8)}

MODES = {
    "note": "Button V1 and array word 0 are packed words; the byte layout is "
            "inferred from presets, not verified on hardware.",
    "button_v1": {
        "0x00000000": {"name": "static", "confidence": "inferred",
                       "desc": "solid: active colour while pressed/lit, idle colour otherwise"},
        "0x00010000": {"name": "static (variant, byte2=1)", "confidence": "inferred"},
        "0x00020000": {"name": "rainbow (byte2=2)", "confidence": "inferred"},
        "0x00020002": {"name": "rainbow, byte0=2", "confidence": "inferred"},
    },
    "ui_effect_names": ["SOLID", "PULSE (1-4 colours)", "RAINBOW (bright/dark 1-2/default)",
                        "CHASING", "VU", "VU_WITH_PEAK", "FADER (1-2 colours, indicator, background)",
                        "GRADIENT_FADER", "CHASING_FADER", "PULSE_FADER", "RAINBOW_FADER"],
    "ui_effect_names_note": "Strings NID_LED_SETTINGS_* in the Panel; their numeric order "
                            "in the V1 word is NOT established.",
    "array_word0": {
        "note": "Words seen: 0x04|(i<<24) (Default, static), 0x02, 0x00, 0x06|(i<<24), "
                "0x140003 (Rainbow), 0x140001 (Pulse/VU on arrays 7-8), 0x1E0D38|(i<<24) "
                "(Pulse and VU, bytes 38 0D 1E = same shape as live device reading "
                "0x051E0D18). byte3 looks like a per-array index; byte0..2 effect/variant. "
                "Exact meaning unverified."},
    "colour_fields": "button V2/V3 are palette indices 0..127 (bit7 unused). Observed "
                     "V3 = V2 + 0x32 for solid colours: V2 is the dim (0x55-scaled) twin "
                     "of V3's full-brightness colour. Which of V2/V3 is shown when lit vs idle "
                     "is unverified; contract names are active=V2, idle=V3.",
}

# ---------------------------------------------------------------- parsing
def parse_stream(path):
    d = open(path, "rb").read()
    if len(d) % 4:
        raise ValueError("%s: size not multiple of 4" % path)
    w = struct.unpack("<%dI" % (len(d) // 4), d)
    if w[:3] != (8, 0, 0):
        raise ValueError("%s: bad preamble" % path)
    i, recs = 3, []
    while i < len(w):
        size = w[i] // 4
        r = w[i:i + size]
        if size < 6 or r[1] != 0 or i + size > len(w):
            raise ValueError("%s: bad record at word %d" % (path, i))
        vals = [r[j + 1] for j in range(5, len(r) - 1)
                if r[j] == 7 and r[j - 1] == 1 and r[j - 2] == 16]
        recs.append((r[2], r[3], vals))
        i += size
    return recs


def convert_led_file(path):
    recs = {lid: vals for lid, _, vals in parse_stream(path)}
    leds = {}
    for lid, name, param, n, label, kind in CONTROLS:
        vals = recs.get(lid)
        if vals is None or len(vals) != n:
            raise ValueError("%s: record %d missing or wrong length" % (path, lid))
        e = {"values": vals}
        if kind == "button":
            e.update(mode=vals[0], active=vals[1], idle=vals[2],
                     mode_bytes=[(vals[0] >> s) & 0xFF for s in (0, 8, 16, 24)])
        else:
            e["bytes"] = [(v >> s) & 0xFF for v in vals for s in (0, 8, 16, 24)]
        leds[name] = e
    return leds


def convert_routing(path):
    recs = {lid: vals for lid, _, vals in parse_stream(path)}
    dest = ["stream", "chat", "alt", "sampler", "main", "phones"]
    src = ["mic", "game", "chat", "aux", "sampler", "system"]
    out = {}
    for di, dn in enumerate(dest):
        out[dn] = {}
        for si, sn in enumerate(src):
            out[dn][sn] = recs[4 + 12 * di + 2 * si][0]
    return out


def extract_palette(asm_path):
    pal = {0: 0xFF000000, 1: 0xFF000000}
    started = False
    for line in open(asm_path, errors="replace"):
        if "<MA::LAppEngine::InitColorArrays(" in line and line.lstrip().startswith("0"):
            started = True
            continue
        if started and "<MA::LAppEngine::InitMonochromeArrays(" in line:
            break
        if started:
            m = re.search(r"movl\s+\$0x([0-9a-f]+), (?:0x([0-9a-f]+))?\(%rax\)", line)
            if m:
                pal[int(m.group(2) or "0", 16) // 4] = int(m.group(1), 16)
    if sorted(pal) != list(range(128)):
        raise ValueError("palette incomplete: %d entries" % len(pal))
    return {str(k): "#%06X" % (v & 0xFFFFFF) for k, v in sorted(pal.items())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resources", default=DEFAULT_RES)
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--data", default=os.path.dirname(here))
    ap.add_argument("--asm")
    a = ap.parse_args()

    leds_path = os.path.join(a.data, "leds.json")
    palette = None
    if a.asm:
        palette = extract_palette(a.asm)
    elif os.path.exists(leds_path):
        palette = json.load(open(leds_path)).get("palette")

    controls = {name: {"param": "%08X" % param, "n": n, "label": label, "kind": kind}
                for _, name, param, n, label, kind in CONTROLS}
    doc = {"controls": controls, "aliases": ALIASES, "palette": palette,
           "palette_source": "MA::LAppEngine::InitColorArrays (Panel), index = MIDI colour value; "
                             "0 and 1 are both black",
           "modes": MODES}
    os.makedirs(os.path.join(a.data, "led_presets"), exist_ok=True)
    with open(leds_path, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")

    names = []
    for p in sorted(glob.glob(os.path.join(a.resources, "*.MGameRGBDualLEDs"))):
        name = os.path.basename(p).rsplit(".", 1)[0]
        names.append(name)
        with open(os.path.join(a.data, "led_presets", name + ".json"), "w") as f:
            json.dump({"name": name, "leds": convert_led_file(p)}, f, indent=2)
            f.write("\n")

    routing = {}
    for key, fn in (("default", "Default"), ("no_chat_to_stream", "Default - No Chat to Stream")):
        routing[key] = convert_routing(os.path.join(a.resources, fn + ".MGameRGBDualRouting"))
    with open(os.path.join(a.data, "routing_presets.json"), "w") as f:
        json.dump(routing, f, indent=2)
        f.write("\n")
    print("presets:", len(names))


if __name__ == "__main__":
    main()
