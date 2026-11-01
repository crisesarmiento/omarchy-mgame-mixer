"""Lectura de presets de voz/mic y del estado de FX ya guardado.

No manda MIDI. No arma tramas. sysexSafe es una marca para mostrar: un byte
>= 0x80 igual se devuelve (es una lectura), no un permiso para enviar.

El panel entra después por mgame.py. Estas funciones no leen device.json:
fx_state recibe el dict (o None). Los directorios salen de DATA_DIR.
"""
import json
import os
import re

from mgame_device import DevError

HERE = os.path.dirname(os.path.realpath(__file__))
DATA_DIR = os.path.join(HERE, "data")
KINDS = ("voice", "mic")
_DIRS = {"voice": "voice_presets", "mic": "mic_presets"}
_HEX8 = re.compile(r"^[0-9A-Fa-f]{8}$")
_FAMILY_ID = "01050000"


def _kind_dir(kind):
    return os.path.join(DATA_DIR, _DIRS[kind])


def _fx_path():
    return os.path.join(DATA_DIR, "fx.json")


def _name_unsafe(name):
    """True si no es un nombre de preset: vacío, no-string, o parece una ruta."""
    if not isinstance(name, str) or not name or name != name.strip():
        return True
    if name in (".", ".."):
        return True
    if any(ord(ch) < 32 for ch in name):
        return True
    return "/" in name or "\\" in name or ".." in name


def _check_kind(kind):
    if kind not in KINDS:
        raise DevError("tipo inválido (voice o mic)")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, UnicodeError, ValueError):
        return None


def _preset_index(kind):
    """{nombre: ruta} según el campo name. La ruta no se arma con el texto del usuario."""
    directory = _kind_dir(kind)
    if not os.path.isdir(directory):
        return {}
    root = os.path.realpath(directory)
    found = {}
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return {}
    for entry in entries:
        if not entry.endswith(".json") or entry.startswith("."):
            continue
        if os.path.basename(entry) != entry or _name_unsafe(entry):
            continue
        path = os.path.join(directory, entry)
        real = os.path.realpath(path)
        if os.path.dirname(real) != root or not os.path.isfile(real):
            continue
        data = _read_json(real)
        if not isinstance(data, dict):
            continue
        name = data.get("name")
        if _name_unsafe(name):
            continue
        found.setdefault(name, real)
    return found


def fx_presets():
    return {
        "ok": True,
        "voice": sorted(_preset_index("voice")),
        "mic": sorted(_preset_index("mic")),
    }


def fx_preset(kind, name):
    _check_kind(kind)
    if _name_unsafe(name):
        raise DevError("nombre inválido")
    path = _preset_index(kind).get(name)
    if path is None:
        raise DevError("preset inexistente")
    data = _read_json(path)
    if not isinstance(data, dict) or data.get("name") != name:
        raise DevError("preset inválido")
    return {"ok": True, "kind": kind, "preset": data}


def _load_fx():
    path = _fx_path()
    if not os.path.isfile(path):
        raise DevError("falta data/fx.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, UnicodeError):
        raise DevError("falta data/fx.json")
    except ValueError:
        raise DevError("data/fx.json no es JSON válido")
    if not isinstance(data, dict):
        raise DevError("data/fx.json inválido")
    return data


def _hex_param(value):
    if isinstance(value, str) and _HEX8.fullmatch(value):
        return value
    return None


def _as_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _lookup(raw, param):
    """Valor de device['raw'] para un param de fx.json. Mayúsculas o minúsculas."""
    if not isinstance(raw, dict) or not isinstance(param, str):
        return None
    want = param.upper()
    if not _HEX8.fullmatch(want):
        return None
    if want in raw:
        return raw[want]
    low = want.lower()
    if low in raw:
        return raw[low]
    for key, val in raw.items():
        if isinstance(key, str) and key.upper() == want:
            return val
    return None


def _word_safe(word):
    if isinstance(word, bool) or not isinstance(word, int):
        return False
    if word < 0 or word > 0xFFFFFFFF:
        return False
    return all(((word >> shift) & 0xFF) < 0x80 for shift in (0, 8, 16, 24))


def _values(raw, param):
    found = _lookup(raw, param)
    if not isinstance(found, list):
        return None, "absent", True
    values = list(found)
    return values, "device", all(_word_safe(word) for word in values)


def _text(item, key):
    val = item.get(key)
    return val if isinstance(val, str) else None


def _knob(spec, raw):
    if not isinstance(spec, dict):
        raise DevError("data/fx.json inválido")
    param = _hex_param(spec.get("param"))
    n = _as_int(spec.get("n"))
    words_in = spec.get("words", [])
    if param is None or n is None or not isinstance(words_in, list):
        raise DevError("data/fx.json inválido")
    words = []
    for item in words_in:
        if not isinstance(item, dict):
            raise DevError("data/fx.json inválido")
        words.append({
            "name": _text(item, "name"),
            "meaning": _text(item, "meaning"),
            "confidence": _text(item, "confidence"),
        })
    values, source, safe = _values(raw, param)
    # spec["live"] no es el aparato: no se copia.
    return {
        "param": param,
        "n": n,
        "words": words,
        "values": values,
        "source": source,
        "sysexSafe": safe,
    }


def _blocks(items, raw):
    if not isinstance(items, list):
        raise DevError("data/fx.json inválido")
    out = []
    for item in items:
        if not isinstance(item, dict):
            raise DevError("data/fx.json inválido")
        param = _hex_param(item.get("param"))
        n = _as_int(item.get("n"))
        if param is None or n is None:
            raise DevError("data/fx.json inválido")
        values, source, safe = _values(raw, param)
        out.append({
            "param": param,
            "n": n,
            "role": item.get("role") if isinstance(item.get("role"), str) else "",
            "when": item.get("when") if isinstance(item.get("when"), str) else "",
            "writable": False,
            "values": values,
            "source": source,
            "sysexSafe": safe,
        })
    return out


def _family(doc, raw):
    """Lectura de 0x01050000, si el catálogo la nombra. Nunca un bloque escribible."""
    fam = doc.get("family0105")
    if not isinstance(fam, dict):
        return None
    params = fam.get("params")
    if not isinstance(params, list):
        return None
    chosen = None
    for item in params:
        if not isinstance(item, dict):
            continue
        ident = _hex_param(item.get("id"))
        if ident is not None and ident.upper() == _FAMILY_ID:
            chosen = ident
            break
    if chosen is None:
        return None
    values, source, safe = _values(raw, chosen)
    return {
        "id": chosen,
        "values": values,
        "source": source,
        "writable": False,
        "sysexSafe": safe,
    }


def fx_state(device=None):
    if device is not None and not isinstance(device, dict):
        raise DevError("device inválido")
    doc = _load_fx()
    raw = device.get("raw") if isinstance(device, dict) else None
    out = {
        "ok": True,
        "knob": _knob(doc.get("knob"), raw),
        "blocks": _blocks(doc.get("blocks"), raw),
    }
    fam = _family(doc, raw)
    if fam is not None:
        out["family0105"] = fam
    return out
