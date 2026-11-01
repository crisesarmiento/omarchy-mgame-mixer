#!/usr/bin/env python3
"""Regenerate data/fx.json, data/voice_presets/*.json and data/mic_presets/*.json
from the Mac app's voice-FX and mic-FX resources.

Usage:
  convert_fx.py [--resources DIR] [--data DIR] [--asm FILE]

--resources  Mac app Resources dir
--data       output dir (default: the repo's data/ next to this script's parent)
--asm        optional objdump of the Panel binary. When the file is missing,
             asm-derived fields are marked unknown. When it is present, a failed
             scan of a required symbol is an error.

stdlib only. Input files are untrusted data; they are only parsed, never run.
Does not send MIDI.
"""
import argparse
import base64
import glob
import json
import os
import plistlib
import re
import struct

DEFAULT_RES = os.path.expanduser(
    "~/.cache/mgame-mac/root/Applications/M-Game RGB Dual.app/Contents/Resources")
DEFAULT_ASM = os.path.expanduser("~/.cache/mgame-re/full.asm")

NAME_TAG = 0x454D414E  # 'NAME' little-endian

# Block base -> (key, count). Order is the order later lanes expect.
BLOCKS = (
    (0x41000000, "41000000", 11),
    (0x41040000, "41040000", 1),
    (0x41070000, "41070000", 6),
    (0x41080000, "41080000", 1),
    (0x01040300, "01040300", 4),
)

# Present in every factory voice effect. The others are type-selected.
ALWAYS_BLOCKS = ("41000000", "41040000", "41070000", "41080000", "01040300")

# LEffects local index is not required; these are the translate immediates.
EFFECT_PARAMS = (
    0x41000000, 0x41010000, 0x41020000, 0x41030000, 0x41040000,
    0x41050000, 0x41060000, 0x41070000, 0x41080000, 0x41090000,
)

# File ids from the mic-effect property stream. Host-side; no device param.
MIC_CLASSES = (
    (290, "MA::MicHighPassFilters", "MicHighPassFilters"),
    (291, "MA::MicNoiseGate", "MicNoiseGate"),
    (294, "MA::Mic5BandPEQ", "Mic5BandPEQ"),
    (295, "MA::MicDeEsser", "MicDeEsser"),
    (296, "MA::MicCompressor", "MicCompressor"),
)

# id, xml, classes whose setters are that processor's params, name filter.
# filter is a substring the method must contain, or None for every setter.
PROCESSORS = (
    ("vocal", "VocalProcessorPresets.xml", ("MicVocalProcessor",), None),
    ("chorus", "ChorusProcessorPresets.xml",
     ("MicReverbAndChorus", "MicReverbAndChorusMix"), "Chorus"),
    ("distortion", "DistortionProcessorPresets.xml", ("MicDistortion",), None),
    ("reverb", "ReverbProcessorPresets.xml",
     ("MicReverbAndChorus", "MicReverbAndChorusMix"), "VReverb"),
)
# Shared mix setters. Both chorus and reverb preset files change the mix word;
# which editor owns these two is not isolated, so they are listed on both.
SHARED_MIX = ("DryMixLevel", "EffectEnable")

SKIP_METHODS = {"SetFromVariant", "GetAsVariant", "Set", "Get", "Compare",
                "Property", "Create"}


def parse_stream(path):
    with open(path, "rb") as f:
        d = f.read()
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


def bytes_ok(n):
    if not isinstance(n, int) or n < 0 or n > 0xFFFFFFFF:
        return False
    return all(((n >> s) & 0xFF) < 0x80 for s in (0, 8, 16, 24))


def is_dangerous(n):
    if not isinstance(n, int) or n < 0:
        return False
    if (n & 0xFFFFFF00) == 0x5F000000:
        return True
    if 0x50000000 <= n <= 0x501FFFFF:
        return True
    return n in (0x01020002, 0x01020004)


def _type7_values(raw):
    n = len(raw) // 4
    w = struct.unpack("<%dI" % n, raw[:n * 4])
    return [w[i + 3] for i in range(len(w) - 3)
            if w[i] == 16 and w[i + 1] == 1 and w[i + 2] == 7]


def decode_name(words):
    raw = b"".join(struct.pack("<I", w) for w in words).split(b"\x00", 1)[0]
    if not raw:
        raise ValueError("empty NAME")
    try:
        return base64.b64decode(raw, validate=True).decode("utf-8")
    except Exception as e:
        raise ValueError("bad NAME %r: %s" % (raw, e))


def pairs_before_name(values):
    """(param, value) pairs up to the 0, NAME marker. Drops a pair that is
    dangerous or has a byte >= 0x80. Returns (pairs, name)."""
    for i in range(0, len(values) - 1, 2):
        if values[i] == 0 and values[i + 1] == NAME_TAG:
            chunk = values[:i]
            if len(chunk) % 2:
                raise ValueError("odd word count before NAME")
            pairs = []
            for k in range(0, len(chunk), 2):
                pid, val = chunk[k], chunk[k + 1]
                if pid == 0 and val == 0:
                    continue
                if is_dangerous(pid) or is_dangerous(val) or not bytes_ok(pid) or not bytes_ok(val):
                    continue
                pairs.append((pid, val))
            name = decode_name(_name_words(values, i + 2))
            return pairs, name
    raise ValueError("NAME marker missing")


def _name_words(values, start):
    words = []
    j = start
    while j < len(values) and values[j] != 0:
        words.append(values[j])
        j += 1
    return words


def group_blocks(pairs):
    """Group kept pairs into the Q4 blocks. A missing block is omitted.
    An id that is not one of those blocks is an error: the factory files
    do not contain any other safe id, so a new one is a format change."""
    by_id = {}
    for pid, val in pairs:
        base = pid & 0xFFFFFF00
        if base == 0x01040000:
            base = 0x01040300
        known = {b[0] for b in BLOCKS}
        # 0x01040300..03 share the 0x01040300 block; the mask above keeps them.
        if pid & 0xFFFFFF00 == 0x01040000 and (pid & 0xFF) >= 0x00:
            # 0x01040300 is not 256-aligned with the other blocks.
            pass
        block_base = None
        for base_id, _key, count in BLOCKS:
            if base_id <= pid < base_id + count:
                block_base = base_id
                break
        if block_base is None:
            raise ValueError("unexpected param id %08X" % pid)
        if pid in by_id:
            raise ValueError("duplicate param id %08X" % pid)
        by_id[pid] = val
    out = {}
    for base_id, key, count in BLOCKS:
        words = [by_id[base_id + i] for i in range(count) if (base_id + i) in by_id]
        if words:
            out[key] = words
    return out


def effects_from_values(values):
    """Split a concatenated type-7 stream on NAME markers.

    The factory files are 31 slots of 8 records, not 8 effects. Only slots
    that contain a NAME are effects. Padding after the last NAME is ignored.
    """
    effects = []
    i = 0
    while i < len(values):
        found = None
        for k in range(i, len(values) - 1):
            if values[k] == 0 and values[k + 1] == NAME_TAG:
                found = k
                break
        if found is None:
            if any(values[i:]):
                raise ValueError("trailing non-zero words without NAME")
            break
        pairs, name = pairs_before_name(values[i:])
        effects.append({"index": len(effects), "name": name, "blocks": group_blocks(pairs)})
        j = found + 2
        while j < len(values) and values[j] != 0:
            j += 1
        while j < len(values) and values[j] == 0:
            j += 1
        i = j
    if not effects:
        raise ValueError("no effects")
    return effects


def convert_voice_file(path):
    recs = parse_stream(path)
    values = []
    for _lid, _inner, vals in recs:
        values.extend(vals)
    return effects_from_values(values)


def convert_mic_file(path):
    recs = parse_stream(path)
    by_id = {}
    for lid, _inner, vals in recs:
        if lid in by_id:
            raise ValueError("%s: duplicate record %d" % (path, lid))
        for v in vals:
            if not bytes_ok(v) or is_dangerous(v):
                raise ValueError("%s: record %d value not emit-safe" % (path, lid))
        by_id[lid] = vals
    if 2 not in by_id or len(by_id[2]) != 1:
        raise ValueError("%s: phantom record missing" % path)
    phantom = by_id[2][0]
    records = []
    for rid, cls, _short in MIC_CLASSES:
        if rid not in by_id:
            raise ValueError("%s: record %d missing" % (path, rid))
        records.append({"id": rid, "class": cls, "values": by_id[rid]})
    extra = set(by_id) - {2} - {rid for rid, _, _ in MIC_CLASSES}
    if extra:
        raise ValueError("%s: unexpected records %s" % (path, sorted(extra)))
    stem = os.path.basename(path).split(".", 1)[0]
    name = stem.split("-", 1)[1] if "-" in stem else stem
    return {
        "name": name,
        "source": os.path.basename(path),
        "hostSide": True,
        "phantom": phantom,
        "records": records,
    }


def _plist_entries(path):
    try:
        data = plistlib.load(open(path, "rb"))
    except Exception as e:
        raise ValueError("%s: not a plist (%s)" % (path, e))
    try:
        entries = data["2_0_1"]["Entries"]
    except Exception:
        raise ValueError("%s: missing 2_0_1/Entries" % path)
    if not entries:
        raise ValueError("%s: empty Entries" % path)
    return entries


def preset_names(path):
    names = []
    for entry in _plist_entries(path):
        try:
            raw = base64.b64decode(entry)
        except Exception as e:
            raise ValueError("%s: bad base64 (%s)" % (path, e))
        _pairs, name = pairs_before_name(_type7_values(raw))
        names.append(name)
    return names


def humanize(name):
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    return name


def _method_name(symbol):
    m = re.match(r"MA::(Mic[A-Za-z0-9]+)::((?:Set|Get)[A-Za-z0-9_]+)\(", symbol)
    if not m:
        return None
    return m.group(1), m.group(2)


# ---------------------------------------------------------------- asm
FUNC_RE = re.compile(r"^([0-9a-f]+) <(.+)>:$")
INSN_RE = re.compile(r"^([0-9a-f]+):\s+(.*)$")
CMPL_RE = re.compile(r"cmpl\s+\$(0x[0-9a-f]+|\d+),\s*%esi")
JMP_RE = re.compile(r"\bjmp\s+0x([0-9a-f]+)")
MOVL_ID_RE = re.compile(r"movl\s+\$(0x[0-9a-f]+),\s*%esi")
MOVL_EDX_RE = re.compile(r"movl\s+\$(0x[0-9a-f]+|\d+),\s*%edx")


def _imm(text):
    return int(text, 16) if text.startswith("0x") else int(text)


def scan_asm(path):
    """One pass. Returns effect N by param id, global-settings notes, and
    setter bounds keyed by (class, method)."""
    effects_fn = "APP_ENGINE::LEffects::MemberData::TranslateModuleParamValueToDeviceParamValue"
    global_fn = "APP_ENGINE::LGlobalSettings::MemberData::TranslateModuleParamValueToDeviceParamValue"
    default_fn = "APP_ENGINE::LGlobalSettings::GetParamValueDefault"
    want = {effects_fn: [], global_fn: [], default_fn: []}
    current = None
    setters = {}  # (class, method) -> list of following insn texts
    capture_setter = None
    capture_left = 0
    with open(path, errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            fm = FUNC_RE.match(line)
            if fm:
                full = fm.group(2)
                symbol = full.split("(", 1)[0]
                current = symbol if symbol in want else None
                parsed = _method_name(full)
                if parsed and parsed[1] not in SKIP_METHODS:
                    capture_setter = parsed
                    capture_left = 24
                    setters.setdefault(parsed, [])
                else:
                    capture_setter = None
                continue
            im = INSN_RE.match(line.strip())
            if current is not None and im:
                want[current].append((int(im.group(1), 16), im.group(2).strip()))
            if capture_setter is not None and im:
                setters[capture_setter].append(im.group(2).strip())
                capture_left -= 1
                if capture_left <= 0:
                    capture_setter = None
    if not want[effects_fn]:
        raise ValueError("%s: LEffects translate not found" % path)
    effect_n = _effect_counts(want[effects_fn])
    global_n, global_default = _global_settings(want[global_fn], want[default_fn])
    bounds = {}
    for (cls, method), insns in setters.items():
        bounds[(cls, method)] = _setter_max(insns)
    return {"effect_n": effect_n, "global_n": global_n,
            "global_default": global_default, "bounds": bounds}


def _effect_counts(insns):
    """param id -> N, from the translate stubs. A jmp into `movl $N, %edx`
    shares that N (0x41020000/0x41040000/0x41080000 share N=1; 0x41050000
    shares the 0x41090000 movl $7)."""
    by_addr = {addr: text for addr, text in insns}
    # The stub's esi immediate is the param; N is the next edx movl, or the
    # edx movl at the jmp target.
    out = {}
    for idx, (addr, text) in enumerate(insns):
        m = MOVL_ID_RE.search(text)
        if not m:
            continue
        pid = _imm(m.group(1))
        if pid not in EFFECT_PARAMS:
            continue
        n = None
        # look at the next instruction, then at a jmp target
        if idx + 1 < len(insns):
            nxt = insns[idx + 1][1]
            ed = MOVL_EDX_RE.search(nxt)
            if ed:
                n = _imm(ed.group(1))
            else:
                jm = JMP_RE.search(nxt)
                if jm:
                    target = by_addr.get(int(jm.group(1), 16))
                    if target:
                        ed = MOVL_EDX_RE.search(target)
                        if ed:
                            n = _imm(ed.group(1))
        if n is None:
            raise ValueError("LEffects translate: no N for %08X" % pid)
        out[pid] = n
    missing = [pid for pid in EFFECT_PARAMS if pid not in out]
    if missing:
        raise ValueError("LEffects translate missing %s" %
                         ", ".join("%08X" % p for p in missing))
    return out


def _global_settings(translate, default_fn):
    text = "\n".join(t for _a, t in translate)
    if "0x1050000" not in text:
        raise ValueError("LGlobalSettings translate has no 0x01050000")
    n = None
    for _addr, insn in translate:
        ed = MOVL_EDX_RE.search(insn)
        if ed:
            n = _imm(ed.group(1))
            break
    if n is None:
        raise ValueError("LGlobalSettings translate has no N")
    default = None
    for _addr, insn in default_fn:
        if re.search(r"movl\s+\$0xa,\s*\(%rax\)", insn):
            default = 10
            break
    return n, default


def _setter_max(insns):
    for i, text in enumerate(insns):
        m = CMPL_RE.search(text)
        if not m:
            continue
        window = " ".join(insns[i:i + 3])
        if re.search(r"\bja\b", window):
            return _imm(m.group(1))
    return None


def _params_for(proc_id, classes, name_filter, bounds, asm_ok):
    if not asm_ok:
        return []
    found = {}
    for (cls, method), mx in bounds.items():
        if cls not in classes:
            continue
        key = re.sub(r"^(Set|Get)", "", method)
        if key in SKIP_METHODS:
            continue
        if name_filter and name_filter not in key and key not in SHARED_MIX:
            continue
        if proc_id == "chorus" and key in SHARED_MIX:
            pass
        elif proc_id == "reverb" and key in SHARED_MIX:
            pass
        elif name_filter and name_filter not in key:
            continue
        # Prefer a Set bound over a Get with no bound.
        prev = found.get(key)
        if prev is None or (prev["max"] is None and mx is not None):
            found[key] = {
                "key": key,
                "label": humanize(key),
                "min": 0 if mx is not None else None,
                "max": mx,
                "unit": "",
                "deviceParam": None,
                "confidence": "inferred",
            }
    return [found[k] for k in sorted(found)]


def _mic_fields(short, bounds, asm_ok):
    if not asm_ok:
        return []
    found = {}
    for (cls, method), mx in bounds.items():
        if cls != short:
            continue
        key = re.sub(r"^(Set|Get)", "", method)
        if key in SKIP_METHODS:
            continue
        typ = "unsigned int"
        if mx is not None:
            typ = "unsigned int 0..%d" % mx
        prev = found.get(key)
        if prev is None or (prev[1] is None and mx is not None):
            found[key] = ({"name": key, "type": typ}, mx)
    return [found[k][0] for k in sorted(found)]


def _block_table(effect_n, file_n, asm_ok):
    roles = {
        "41000000": ("always",
                     "Vocal-processor words. Every VocalProcessorPresets.xml entry "
                     "changes this block and no other processor file does. "
                     "Per-byte meaning unconfirmed. The voice file is 31 slots of "
                     "8 records; NAME markers fill 4, so the eight-effect split is rejected."),
        "41040000": ("always",
                     "Distortion words. Every DistortionProcessorPresets.xml entry "
                     "changes this block and no other processor file does."),
        "41070000": ("always",
                     "Reverb and chorus words. Every ChorusProcessorPresets.xml and "
                     "ReverbProcessorPresets.xml entry changes this block. Which byte "
                     "belongs to which processor is unconfirmed."),
        "41080000": ("always",
                     "Reverb/chorus mix word. Chorus presets put the knob mask in "
                     "byte 1 (0x7F00); reverb presets put it in byte 0 (0x7F). "
                     "Not every chorus or reverb entry changes the word."),
        "41010000": ("by-type",
                     "Type-selected block. Not in the factory voice-effect files."),
        "41020000": ("by-type",
                     "In the LEffects translate table. Not in the factory files. "
                     "The earlier pass left N unknown; it is not listed there as a "
                     "type-selected write."),
        "41030000": ("by-type",
                     "Type-selected block. Not in the factory voice-effect files."),
        "41050000": ("by-type",
                     "In the LEffects translate table. Not in the factory files. "
                     "The earlier pass left N unknown."),
        "41060000": ("by-type",
                     "Type-selected block. Not in the factory voice-effect files."),
        "41090000": ("by-type",
                     "Type-selected block. Not in the factory voice-effect files."),
    }
    order = [b[1] for b in BLOCKS] + [
        "41010000", "41020000", "41030000", "41050000", "41060000", "41090000"]
    # 01040300 is the knob, not an LEffects block.
    order = [k for k in order if k != "01040300"]
    out = []
    for key in order:
        pid = int(key, 16)
        when, role = roles[key]
        if asm_ok and pid in effect_n:
            n = effect_n[pid]
            conf = "inferred" if when == "by-type" else "observed"
        elif key in file_n and file_n[key] is not None:
            n = file_n[key]
            conf = "observed"
        else:
            n = None
            conf = "unknown"
            if not asm_ok and when == "by-type":
                role = role + " N unknown without the asm."
        out.append({
            "param": key,
            "n": n,
            "when": when,
            "role": role,
            "writable": False,
            "confidence": conf,
        })
    return out


def _knob(asm_ok):
    words = [
        {"index": 0, "name": "target",
         "meaning": "Param id the knob edits. Factory voice effects use "
                    "0x41000001, 0x41000002, 0x41040000 or 0x41080000. "
                    "Vocal presets use 0x41000001/0x41000002, distortion "
                    "presets use 0x41040000, chorus and reverb presets use "
                    "0x41080000. The live word is 0x01050000, the LGlobalSettings "
                    "id, so a target outside the 0x41 family is possible.",
         "confidence": "observed"},
        {"index": 1, "name": "mask",
         "meaning": "Bits the knob changes. Voice effects use 0x7F, 0x7E or "
                    "0x7F0000; chorus presets use 0x7F00. Word 2 and word 3 "
                    "always sit inside these bits, and word 2 <= word 3. "
                    "That mask reading is not confirmed on the device.",
         "confidence": "inferred"},
        {"index": 2, "name": "low",
         "meaning": "Low end of the knob, in the same bits as word 1. "
                    "Unconfirmed.",
         "confidence": "inferred"},
        {"index": 3, "name": "high",
         "meaning": "High end of the knob, in the same bits as word 1. "
                    "Unconfirmed.",
         "confidence": "inferred"},
    ]
    if not asm_ok:
        words[1]["confidence"] = "unknown"
        words[1]["meaning"] = ("Varies (0x7F, 0x7E, 0x7F0000 in voice effects; "
                               "0x7F00 in chorus presets). Mask reading needs the asm.")
        words[2]["confidence"] = "unknown"
        words[3]["confidence"] = "unknown"
    return {
        "param": "01040300",
        "n": 4,
        "words": words,
        "live": [0x01050000, 0x7F, 4, 0x10],
    }


def _family(asm):
    if asm is None:
        return {
            "status": "unknown",
            "params": [{
                "id": "01050000",
                "n": None,
                "role": "Named by IGlobalSettings in the earlier pass. N and meaning unknown without the asm.",
                "writable": False,
                "confidence": "unknown",
            }],
        }
    role = ("LGlobalSettings local 0. Translate writes this id with N=%d. "
            % asm["global_n"])
    if asm["global_default"] is not None:
        role += "GetParamValueDefault stores %d. " % asm["global_default"]
    role += ("Meaning of the value is unknown. The live knob word 0 is this "
             "same id, so it is not a second 0x0105 param. No other 0x0105xxxx "
             "immediate is in the translate. Not marked writable.")
    return {
        "status": "partial",
        "params": [{
            "id": "01050000",
            "n": asm["global_n"],
            "role": role,
            "writable": False,
            "confidence": "inferred",
        }],
    }


def _file_block_n(presets):
    counts = {}
    for key in ALWAYS_BLOCKS:
        if key == "01040300":
            continue
        lengths = set()
        for preset in presets:
            for effect in preset["effects"]:
                block = effect["blocks"].get(key)
                if block is not None:
                    lengths.add(len(block))
        counts[key] = lengths.pop() if len(lengths) == 1 else None
    return counts


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resources", default=DEFAULT_RES)
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--data", default=os.path.dirname(here))
    ap.add_argument("--asm", default=DEFAULT_ASM)
    a = ap.parse_args()

    voice_paths = sorted(glob.glob(os.path.join(a.resources, "*.MGameRGBDualVoiceEffects")))
    mic_paths = sorted(glob.glob(os.path.join(a.resources, "*.MGameRGBDualMicEffects")))
    if len(voice_paths) != 10:
        raise SystemExit("expected 10 voice-effect files, got %d" % len(voice_paths))
    if len(mic_paths) != 7:
        raise SystemExit("expected 7 mic-effect files, got %d" % len(mic_paths))

    voice_dir = os.path.join(a.data, "voice_presets")
    mic_dir = os.path.join(a.data, "mic_presets")
    os.makedirs(voice_dir, exist_ok=True)
    os.makedirs(mic_dir, exist_ok=True)

    voice_docs = []
    for path in voice_paths:
        name = os.path.basename(path).rsplit(".", 1)[0]
        effects = convert_voice_file(path)
        doc = {"name": name, "source": os.path.basename(path), "effects": effects}
        _dump(os.path.join(voice_dir, name + ".json"), doc)
        voice_docs.append(doc)

    for path in mic_paths:
        doc = convert_mic_file(path)
        _dump(os.path.join(mic_dir, doc["name"] + ".json"), doc)

    asm = None
    if a.asm and os.path.isfile(a.asm):
        asm = scan_asm(a.asm)
    bounds = asm["bounds"] if asm else {}

    processors = []
    for pid, fn, classes, filt in PROCESSORS:
        xml = os.path.join(a.resources, fn)
        if not os.path.isfile(xml):
            raise SystemExit("missing %s" % xml)
        processors.append({
            "id": pid,
            "file": fn,
            "params": _params_for(pid, classes, filt, bounds, asm is not None),
        })

    lib = os.path.join(a.resources, "VoiceFXLibrary.xml")
    if not os.path.isfile(lib):
        raise SystemExit("missing VoiceFXLibrary.xml")
    lib_names = preset_names(lib)

    mic_records = []
    for rid, cls, short in MIC_CLASSES:
        mic_records.append({
            "id": rid,
            "class": cls,
            "deviceParam": None,
            "hostSide": True,
            "fields": _mic_fields(short, bounds, asm is not None),
        })

    fx = {
        "version": 1,
        "knob": _knob(asm is not None),
        "blocks": _block_table(asm["effect_n"] if asm else {},
                               _file_block_n(voice_docs), asm is not None),
        "family0105": _family(asm),
        "processors": processors,
        "micRecords": mic_records,
        "apply": {
            "voicePresetSends": ["41000000", "41040000", "41070000", "41080000", "01040300"],
            "neverSend": ["5F0000xx", "50000000-501FFFFF", "01020002", "01020004", "00030000"],
        },
    }
    _dump(os.path.join(a.data, "fx.json"), fx)
    print("voice presets:", len(voice_docs),
          "effects:", [len(d["effects"]) for d in voice_docs])
    print("mic presets:", len(mic_paths))
    print("library entries:", len(lib_names))
    print("asm:", "parsed" if asm else "missing")
    if asm:
        print("effect N:", " ".join("%08X=%d" % (k, v) for k, v in sorted(asm["effect_n"].items())))
        print("global N:", asm["global_n"], "default:", asm["global_default"])


if __name__ == "__main__":
    main()
