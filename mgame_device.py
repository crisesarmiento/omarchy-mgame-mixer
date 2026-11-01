"""Modelo del estado de la M-Game y validación de escrituras (ver docs/device-api.md).

Solo stdlib. No hace E/S de MIDI: recibe tramas ya parseadas (mgame_proto.parse)
y devuelve tramas listas para enviar; mgame.py se encarga de amidi.
"""
import glob
import json
import os
import re
import tempfile
import time

import mgame_proto as proto

HERE = os.path.dirname(os.path.realpath(__file__))
DATA_DIR = os.path.join(HERE, "data")
LEDS_PATH = os.path.join(DATA_DIR, "leds.json")
LED_PRESET_DIR = os.path.join(DATA_DIR, "led_presets")
ROUTING_PATH = os.path.join(DATA_DIR, "routing_presets.json")
STATE_DIR = os.path.join(os.path.expanduser("~"), ".local", "state", "mgame-mixer")
DEVICE_PATH = os.path.join(STATE_DIR, "device.json")

DESTS = ("stream", "chat", "alt", "sampler", "main", "phones")
SRCS = ("mic", "game", "chat", "aux", "sampler", "system")
# bit0..5 de cada byte del vector de mute (docs/protocol.md, Q2); coincide con IMute:
# game 0x02, chat 0x04, sampler 0x10, main_alt 0x28 = aux + system.
SRC_BITS = {name: 1 << i for i, name in enumerate(SRCS)}
ROUTING_PRESET_NAMES = ("default", "no_chat_to_stream")

PHANTOM = 0x00030000
MUTE_VECTOR = 0x44020000
GAIN_BASE = 0x44000000
EFFECTIVE_BASE = 0x44010000
CONNECT_PROBE = 0x01020200
DEFAULT_GAIN = 115

LATCHES = {
    0x01020102: "mic_mute", 0x01020106: "game_mute", 0x01020108: "chat_mute",
    0x0102010A: "sampler_mute", 0x0102010C: "main_alt_mute",
    0x0102010E: "sample_page_1", 0x01020110: "bank_switch", 0x01020112: "sample_page_2",
}
MUTE_MAP = {
    0x01040008: "game_mute", 0x0104000C: "chat_mute",
    0x01040010: "sampler_mute", 0x01040014: "main_alt_mute",
}
HW_MUTES = ("mic_mute", "game_mute", "chat_mute", "sampler_mute", "main_alt_mute")
RAW_LIMIT = 512
SAVE_HEARTBEAT = 0.25  # s: sin cambios, igual se actualiza el archivo si pasó este tiempo


class DevError(Exception):
    """Error de validación o de entorno de un comando dev-*; se imprime como JSON."""


# ------------------------------- utilidades --------------------------------
def atomic_write(path, text):
    """Escritura atómica con temporal único (varios escritores a la vez no se pisan)."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=os.path.basename(path) + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def led_param_ok(p):
    """Familias de LED con su índice máximo: arrays 0x0101kk00 (k<=8), botones 0x0103kk00 (k<=0x20)."""
    if not isinstance(p, int) or p & 0xFF:
        return False
    k = (p >> 8) & 0xFF
    fam = p & 0xFFFF0000
    return (fam == 0x01010000 and k <= 8) or (fam == 0x01030000 and k <= 0x20)


def hex8(n):
    return f"{n:08X}"


def _put(container, key, value):
    if container.get(key) == value and key in container:
        return False
    container[key] = value
    return True


# ------------------------------- LEDs (data/leds.json) ----------------------
def parse_leds(data):
    """{nombre: {"param": int, "n": int, "label": str}} desde el JSON ya cargado."""
    controls = data.get("controls") if isinstance(data, dict) else None
    if not isinstance(controls, dict) or not controls:
        raise DevError("data/leds.json inválido: falta 'controls'")
    out = {}
    for name, spec in controls.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_]{1,32}", name) or not isinstance(spec, dict):
            raise DevError(f"data/leds.json: control inválido {name!r}")
        param = spec.get("param")
        if not isinstance(param, str) or not re.fullmatch(r"[0-9A-Fa-f]{8}", param):
            raise DevError(f"data/leds.json: param inválido en {name}")
        p = int(param, 16)
        family = p & 0xFFFF0000
        if family not in (0x01030000, 0x01010000) or not led_param_ok(p):
            raise DevError(f"data/leds.json: {name} fuera del rango de LEDs")
        n = spec.get("n", 3 if family == 0x01030000 else 4)
        if n not in (3, 4):
            raise DevError(f"data/leds.json: n inválido en {name}")
        out[name] = {"param": p, "n": n, "label": str(spec.get("label", name))}
    return out


def load_leds(path=None):
    path = path or LEDS_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError:
        raise DevError("falta data/leds.json")
    except ValueError:
        raise DevError("data/leds.json no es JSON válido")
    return parse_leds(data)


class LedMapCache:
    """Relee data/leds.json como mucho cada `interval` s (el archivo puede aparecer más tarde)."""

    def __init__(self, path=None, interval=2.0):
        self.path, self.interval = path, interval
        self.leds, self._stamp, self._checked = {}, None, 0.0

    def refresh(self, now=None):
        """True si el mapa cambió."""
        now = time.monotonic() if now is None else now
        if now - self._checked < self.interval:
            return False
        self._checked = now
        path = self.path or LEDS_PATH
        try:
            stamp = os.stat(path).st_mtime_ns
        except OSError:
            stamp = None
        if stamp == self._stamp:
            return False
        self._stamp = stamp
        try:
            leds = load_leds(path) if stamp is not None else {}
        except DevError:
            leds = {}
        changed = leds != self.leds
        self.leds = leds
        return changed


# ------------------------------- modelo ------------------------------------
class DeviceState:
    def __init__(self, leds=None):
        self.connected = False
        self.updated = None
        self.phantom = None
        self.gain = {d: {s: None for s in SRCS} for d in DESTS}
        self.effective = {d: {s: None for s in SRCS} for d in DESTS}
        self.muted = {d: None for d in DESTS}
        self.buttons = {name: None for name in LATCHES.values()}
        self.mute_map = {name: None for name in MUTE_MAP.values()}
        self.raw = {}
        self.leds = {}
        self._led_by_param = {}
        self._led_n = {}
        self._page = None
        self._last_save = 0.0
        self.set_leds(leds or {})

    # --- LEDs
    def set_leds(self, leds):
        old_raw = self.raw
        self._led_by_param = {info["param"]: name for name, info in leds.items()}
        self._led_n = {info["param"]: info["n"] for info in leds.values()}
        new = {}
        for name, info in leds.items():
            cur = self.leds.get(name)
            if cur is None or cur.get("param") != hex8(info["param"]):
                cur = {"param": hex8(info["param"])}
                if info["n"] == 3:
                    cur.update(mode=None, active=None, idle=None)
                else:
                    cur["values"] = None
                key = hex8(info["param"])
                if key in old_raw:  # un valor que llegó antes de conocer el mapa
                    self._store_led(cur, old_raw.pop(key))
            new[name] = cur
        self.leds = new

    @staticmethod
    def _store_led(entry, values):
        if "values" in entry:
            new = list(values)
            if entry["values"] == new:
                return False
            entry["values"] = new
            return True
        if len(values) < 3:
            return False
        new = dict(mode=values[0], active=values[1], idle=values[2])
        if all(entry.get(k) == v for k, v in new.items()):
            return False
        entry.update(new)
        return True

    # --- ingest
    def ingest(self, msg, now=None):
        """Devuelve (conocida, cambió). Solo las tramas 'set' (los gets se responden en forma set)."""
        if msg is None or msg.kind != proto.KIND_SET or not msg.values:
            return False, False
        p, v = msg.param_id, list(msg.values)
        fam = p & 0xFFFF0000
        changed, known = False, True
        if fam in (GAIN_BASE, EFFECTIVE_BASE) and ((p >> 8) & 0xFF) < 6 and not p & 1 and (p & 0xFF) < 12:
            table = self.gain if fam == GAIN_BASE else self.effective
            changed = _put(table[DESTS[(p >> 8) & 0xFF]], SRCS[(p & 0xFF) // 2], v[0])
        elif p == MUTE_VECTOR and len(v) >= 2:
            raw = b"".join(int(w).to_bytes(4, "little") for w in v[:2])
            for i, dest in enumerate(DESTS):
                names = [s for s in SRCS if raw[i] & SRC_BITS[s]]
                changed |= _put(self.muted, dest, names)
        elif p == PHANTOM:
            changed = _put(self.__dict__, "phantom", 1 if v[0] else 0)
        elif p in LATCHES:
            name = LATCHES[p]
            on = bool(v[0])
            changed = _put(self.buttons, name, on)
            if on and name == "sample_page_1":
                self._page = 1
            elif on and name == "sample_page_2":
                self._page = 2
        elif p in MUTE_MAP:
            mask = int(v[0]) & 0x7F
            changed = _put(self.mute_map, MUTE_MAP[p], [s for s in SRCS if mask & SRC_BITS[s]])
        elif p in self._led_by_param:
            changed = self._store_led(self.leds[self._led_by_param[p]], v)
        else:
            key = hex8(p)
            if key not in self.raw and len(self.raw) >= RAW_LIMIT:
                return False, False
            known = False
            changed = _put(self.raw, key, v)
        self.updated = time.time() if now is None else now
        return known, changed

    # --- vistas
    def to_dict(self):
        return {
            "connected": self.connected,
            "updated": self.updated,
            "phantom": self.phantom,
            "gain": self.gain,
            "effective": self.effective,
            "muted": self.muted,
            "buttons": self.buttons,
            "muteMap": self.mute_map,
            "leds": self.leds,
            "raw": self.raw,
        }

    def hw(self):
        """Forma histórica de hw.json (la lee el panel): mutes, página y banco."""
        out = {name: self.buttons[name] for name in HW_MUTES}
        out["page"] = self._page
        bank = self.buttons["bank_switch"]
        out["bank"] = None if bank is None else ("B" if bank else "A")
        return out

    def save(self, path=None, changed=True, now=None):
        """Escritura atómica. Sin cambios solo se reescribe como latido (cada SAVE_HEARTBEAT s)."""
        now = time.monotonic() if now is None else now
        if not changed and now - self._last_save < SAVE_HEARTBEAT:
            return False
        self._last_save = now
        atomic_write(path or DEVICE_PATH, json.dumps(self.to_dict(), separators=(",", ":")) + "\n")
        return True


def empty_state_dict(leds=None):
    return DeviceState(leds).to_dict()


def load_device_json(path=None):
    data = load_json(path or DEVICE_PATH, {})
    return data if data else empty_state_dict()


# ------------------------------- refresh -----------------------------------
def refresh_frames(leds=None):
    """Todos los gets que dejan el estado completo. Lo importante primero."""
    gets = [(CONNECT_PROBE, 1)]
    gets += [(p, 1) for p in sorted(LATCHES)]
    gets += [(MUTE_VECTOR, 2), (PHANTOM, 1)]
    gets += [(p, 1) for p in sorted(MUTE_MAP)]
    for base in (GAIN_BASE, EFFECTIVE_BASE):
        gets += [(base + d * 0x100 + s * 2, 1) for d in range(6) for s in range(6)]
    for info in (leds or {}).values():
        gets.append((info["param"], info["n"]))
    return [proto.build_get(p, n) for p, n in gets]


def send_frames(frames, send, gap=0.015, sleep=time.sleep):
    for frame in frames:
        send(frame)
        sleep(gap)


BATCH_LIMIT = 64  # tramas por llamada a amidi


def chunked(frames, size=BATCH_LIMIT):
    frames = list(frames)
    return [frames[i:i + size] for i in range(0, len(frames), size)]


def frames_from_dump(text):
    """Tramas F0..F7 completas dentro de la salida de `amidi -d`."""
    out, cur = [], None
    for tok in re.findall(r"\b[0-9A-Fa-f]{2}\b", text):
        b = int(tok, 16)
        if b == 0xF0:
            cur = [b]
        elif cur is not None:
            cur.append(b)
            if b == 0xF7:
                out.append(bytes(cur))
                cur = None
    return out


# ------------------------------- escrituras --------------------------------
def gain_param(dest_i, src_i):
    return GAIN_BASE + dest_i * 0x100 + src_i * 2


def is_write_allowed(param, n, leds=None):
    """Única puerta para escribir: ganancias (N1), phantom (N1) y LEDs de data/leds.json (su n)."""
    if not isinstance(param, int) or not isinstance(n, int):
        return False
    if param & 0xFFFF0000 == GAIN_BASE:
        return n == 1 and ((param >> 8) & 0xFF) < 6 and not param & 1 and (param & 0xFF) < 12
    if param == PHANTOM:
        return n == 1
    for info in (leds or {}).values():
        if info["param"] == param and info["n"] == n and led_param_ok(param):
            return True
    return False


def checked_set(param, values, leds=None):
    """Trama 'set' lista para enviar, o DevError si no está en la lista permitida."""
    values = list(values)
    if not is_write_allowed(param, len(values), leds):
        raise DevError(f"escritura no permitida: 0x{param:08X} N={len(values)}")
    try:
        return proto.build_set(param, values)
    except ValueError as exc:
        raise DevError(str(exc))


def name_index(value, names, what):
    if value not in names:
        raise DevError(f"{what} inválido (uno de: {' '.join(names)})")
    return names.index(value)


def int_arg(value, lo, hi, what):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,10}", value):
        raise DevError(f"{what} debe ser un entero {lo}..{hi}")
    n = int(value)
    if not lo <= n <= hi:
        raise DevError(f"{what} fuera de rango ({lo}..{hi})")
    return n


def check_7bit(n, what):
    if not isinstance(n, int) or isinstance(n, bool) or n < 0 or n > 0xFFFFFFFF \
            or any(b >= 0x80 for b in n.to_bytes(4, "little")):
        raise DevError(f"{what}: valor no apto para SysEx (bytes < 0x80)")
    return n


def build_gain(dest, src, value):
    d = name_index(dest, DESTS, "dest")
    s = name_index(src, SRCS, "src")
    v = int_arg(value, 0, 127, "ganancia") if isinstance(value, str) else int(value)
    if not 0 <= v <= 127:
        raise DevError("ganancia fuera de rango (0..127)")
    return gain_param(d, s), [v]


def build_phantom(state):
    if state not in ("on", "off"):
        raise DevError("phantom: on u off")
    return PHANTOM, [1 if state == "on" else 0]


def led_values(active, idle, mode):
    a = check_7bit(active, "active")
    i = check_7bit(idle, "idle")
    if a > 127 or i > 127:
        raise DevError("active/idle fuera de rango (0..127)")
    return [check_7bit(mode, "mode"), a, i]


def known_led_modes(directory=None):
    """Palabras 'mode' presentes en data/led_presets/*.json (únicas permitidas en dev-led)."""
    modes = set()
    for path in list_led_presets(directory).values():
        entries = load_json(path, {}).get("leds")
        for spec in (entries.values() if isinstance(entries, dict) else ()):
            m = spec.get("mode") if isinstance(spec, dict) else None
            if isinstance(m, int) and not isinstance(m, bool):
                modes.add(m)
    return frozenset(modes)


def build_led(control, active, idle, mode, leds):
    info = leds.get(control) if isinstance(control, str) else None
    if info is None:
        raise DevError("control inválido (ver data/leds.json)")
    if info["n"] != 3:
        raise DevError("ese control no es un LED de botón (N=3)")
    return info["param"], led_values(active, idle, mode)


# ------------------------------- presets -----------------------------------
def load_routing_preset(name, path=None):
    if name not in ROUTING_PRESET_NAMES:
        raise DevError(f"preset inválido (uno de: {' '.join(ROUTING_PRESET_NAMES)})")
    try:
        with open(path or ROUTING_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError:
        raise DevError("falta data/routing_presets.json")
    except ValueError:
        raise DevError("data/routing_presets.json no es JSON válido")
    preset = data.get(name) if isinstance(data, dict) else None
    if not isinstance(preset, dict):
        raise DevError(f"data/routing_presets.json no tiene '{name}'")
    out = []
    for d_i, dest in enumerate(DESTS):
        row = preset.get(dest)
        if not isinstance(row, dict):
            raise DevError(f"preset incompleto: falta {dest}")
        for s_i, src in enumerate(SRCS):
            v = row.get(src)
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 127:
                raise DevError(f"preset: {dest}/{src} debe ser 0..127")
            out.append((dest, src, gain_param(d_i, s_i), v))
    return out


def list_led_presets(directory=None):
    """{nombre: ruta} de data/led_presets/*.json."""
    out = {}
    for path in sorted(glob.glob(os.path.join(directory or LED_PRESET_DIR, "*.json"))):
        data = load_json(path, {})
        name = data.get("name") if isinstance(data.get("name"), str) else os.path.splitext(os.path.basename(path))[0]
        if name:
            out.setdefault(name, path)
    return out


def load_led_preset(name, leds, directory=None):
    """[(control, param, values)] para un preset y lista de controles omitidos."""
    presets = list_led_presets(directory)
    if name not in presets:
        raise DevError("preset de LEDs inexistente")
    data = load_json(presets[name], {})
    entries = data.get("leds")
    if not isinstance(entries, dict):
        raise DevError("preset de LEDs inválido")
    out, skipped = [], []
    for control, spec in entries.items():
        info = leds.get(control)
        if info is None or info["n"] != 3 or not isinstance(spec, dict):
            skipped.append(str(control))
            continue
        vals = [spec.get(k) for k in ("mode", "active", "idle")]
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in vals):
            raise DevError(f"preset: valores inválidos en {control}")
        out.append((control, info["param"], led_values(vals[1], vals[2], vals[0])))
    if not out:
        raise DevError("el preset no aplica a ningún control")
    return out, skipped
