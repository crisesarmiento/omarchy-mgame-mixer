"""Guardar y restaurar un perfil: volúmenes, mic, reglas, ganancias y preset de LEDs.

Sin phantom, sin FX, sin pares de canales y sin inventar 115. No hace --refresh.
El restore toma un flock no bloqueante; si está ocupado, {"ok": false, "error": "busy"}.
"""
import json
import math
import os
import re
import time

import mgame
import mgame_apps
import mgame_device as md
import mgame_lock
import mgame_proto

USER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,40}$")
UNDO_NAME = "_before-restore"
VOL_KEYS = ("game", "chat", "sampler", "system", "mic")
PROFILE_KEYS = {"version", "volumes", "mic", "rules", "gains", "ledPreset", "deviceUpdated"}
MIC_KEYS = {"enabled", "preset", "overrides"}
VOL_ITEM_KEYS = {"pct", "mute"}
GAIN_CHUNK = 16
SCHEMA = 1


class ProfileError(Exception):
    pass


class LinuxError(Exception):
    pass


class DeviceSendError(Exception):
    def __init__(self, sent, message):
        self.sent = sent
        super().__init__(message)


def profiles_dir():
    return os.path.join(mgame.CFG_DIR, "profiles")


def restore_target():
    """Recurso cuyo `.lock` toma el restore (no bloqueante)."""
    return os.path.join(mgame.CFG_DIR, "profile-restore")


def check_name(name, for_load=False):
    if for_load and name == UNDO_NAME:
        return name
    if not isinstance(name, str) or name.startswith("_") or not USER_NAME.fullmatch(name):
        raise ProfileError("nombre inválido")
    return name


def profile_path(name, for_load=False):
    name = check_name(name, for_load=for_load)
    base = name + ".json"
    if os.path.basename(base) != base:
        raise ProfileError("nombre inválido")
    return os.path.join(profiles_dir(), base)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def age_of(updated, now=None):
    if not _is_num(updated):
        return None
    now = time.time() if now is None else now
    return round(now - float(updated), 3)


def _meta(updated):
    return {"deviceUpdated": updated if _is_num(updated) else None, "age": age_of(updated)}


def validate_volumes(volumes):
    if not isinstance(volumes, dict) or set(volumes) != set(VOL_KEYS):
        raise ProfileError("volúmenes inválidos")
    out = {}
    for key in VOL_KEYS:
        item = volumes[key]
        if not isinstance(item, dict) or set(item) != VOL_ITEM_KEYS:
            raise ProfileError(f"volumen inválido: {key}")
        pct, mute = item.get("pct"), item.get("mute")
        if not _is_int(pct) or not 0 <= pct <= 150:
            raise ProfileError(f"pct fuera de rango: {key}")
        if not isinstance(mute, bool):
            raise ProfileError(f"mute inválido: {key}")
        out[key] = {"pct": pct, "mute": mute}
    return out


def validate_mic(mic):
    if not isinstance(mic, dict) or set(mic) != MIC_KEYS:
        raise ProfileError("mic inválido")
    enabled, preset, overrides = mic.get("enabled"), mic.get("preset"), mic.get("overrides")
    if not isinstance(enabled, bool):
        raise ProfileError("mic.enabled inválido")
    if preset not in mgame.PRESETS:
        raise ProfileError("mic.preset inválido")
    if not isinstance(overrides, dict):
        raise ProfileError("mic.overrides inválido")
    if set(overrides) - set(mgame.OVERRIDE_RANGES):
        raise ProfileError("mic.overrides inválido")
    cleaned = {}
    for key, (lo, hi) in mgame.OVERRIDE_RANGES.items():
        if key not in overrides:
            continue
        val = overrides[key]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not lo <= val <= hi:
            raise ProfileError(f"mic.overrides.{key} fuera de rango")
        cleaned[key] = int(val) if key == "vad" else val
    return {"enabled": enabled, "preset": preset, "overrides": cleaned}


def validate_gains(gains):
    """Las 36 celdas, enteros 0..127 (no bool), o null. No se inventa 115."""
    if gains is None:
        return None
    if not isinstance(gains, dict) or set(gains) != set(md.DESTS):
        raise ProfileError("ganancias inválidas")
    out = {}
    for dest in md.DESTS:
        row = gains[dest]
        if not isinstance(row, dict) or set(row) != set(md.SRCS):
            raise ProfileError(f"ganancias incompletas: {dest}")
        out[dest] = {}
        for src in md.SRCS:
            val = row[src]
            if not _is_int(val) or not 0 <= val <= 127:
                raise ProfileError(f"ganancia inválida: {dest}/{src}")
            out[dest][src] = val
    return out


def validate_led(name):
    if name is None:
        return None
    if not isinstance(name, str) or not name or name not in md.list_led_presets():
        raise ProfileError("ledPreset desconocido")
    return name


def validate_profile(data):
    if not isinstance(data, dict):
        raise ProfileError("perfil inválido")
    if "phantom" in data or "fx" in data or "pairs" in data:
        raise ProfileError("el perfil no puede incluir phantom, fx ni pares")
    if set(data) != PROFILE_KEYS:
        raise ProfileError("perfil inválido")
    if type(data.get("version")) is not int or data.get("version") != SCHEMA:
        raise ProfileError("versión de perfil inválida")
    updated = data.get("deviceUpdated")
    if updated is not None and not _is_num(updated):
        raise ProfileError("deviceUpdated inválido")
    try:
        rules = mgame_apps.validate_rules({"rules": data.get("rules")})
    except ValueError as exc:
        raise ProfileError(str(exc))
    return {
        "version": SCHEMA,
        "volumes": validate_volumes(data.get("volumes")),
        "mic": validate_mic(data.get("mic")),
        "rules": rules,
        "gains": validate_gains(data.get("gains")),
        "ledPreset": validate_led(data.get("ledPreset")),
        "deviceUpdated": None if updated is None else updated,
    }


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def capture_gains():
    """Lee device.json. Si falta una celda, gains es null. Nunca --refresh ni 115 inventado."""
    data = md.load_device_json()
    updated = data.get("updated")
    if not _is_num(updated):
        updated = None
    gain = data.get("gain")
    if not isinstance(gain, dict):
        return None, updated
    out = {}
    for dest in md.DESTS:
        row = gain.get(dest)
        if not isinstance(row, dict):
            return None, updated
        out[dest] = {}
        for src in md.SRCS:
            val = row.get(src)
            if not _is_int(val) or not 0 <= val <= 127:
                return None, updated
            out[dest][src] = val
    return out, updated


def capture_led():
    """Solo el nombre que dev-led-preset dejó en state.json, y solo si el preset sigue existiendo."""
    name = mgame.load_json(mgame.STATE_PATH, {}).get("ledPreset")
    if not isinstance(name, str) or not name:
        return None
    return name if name in md.list_led_presets() else None


def capture_mic():
    mic = mgame.load_state()["mic"]
    return {"enabled": bool(mic["enabled"]), "preset": mic["preset"], "overrides": dict(mic["overrides"])}


def capture_rules():
    rules, err = mgame_apps.read_rules()
    if err:
        raise ProfileError(err)
    return rules


def _node_map(kind):
    devs = mgame.pactl_json("list", "sinks" if kind == "sink" else "sources")
    if not isinstance(devs, list):
        raise LinuxError("pactl no devolvió la lista de nodos")
    return {item.get("name"): item for item in devs if isinstance(item, dict)}


def read_volumes():
    sinks = _node_map("sink")
    sources = _node_map("source")
    out = {}
    for key in VOL_KEYS:
        kind = mgame.KIND[key]
        node = mgame.NODE_NAMES[key]
        match = (sinks if kind == "sink" else sources).get(node)
        if match is None:
            raise LinuxError(f"nodo ausente: {node}")
        state = mgame.node_state(match)
        pct = state["volume"]
        if not _is_int(pct) or not 0 <= pct <= 150:
            raise LinuxError(f"volumen fuera de rango: {key}")
        out[key] = {"pct": pct, "mute": bool(state["muted"])}
    return out


def capture_live():
    volumes = read_volumes()
    with mgame_lock.exclusive(mgame.STATE_PATH):
        mic = capture_mic()
        led = capture_led()
    rules = capture_rules()
    gains, updated = capture_gains()
    return {
        "version": SCHEMA,
        "volumes": volumes,
        "mic": mic,
        "rules": rules,
        "gains": gains,
        "ledPreset": led,
        "deviceUpdated": updated,
    }


def _write_profile(path, data):
    md.atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def save_profile(name):
    try:
        path = profile_path(name)
        data = validate_profile(capture_live())
    except ProfileError as exc:
        return {"ok": False, "error": str(exc)}
    except LinuxError as exc:
        return {"ok": False, "error": str(exc)}
    _write_profile(path, data)
    return {"ok": True, "name": name, "gains": None if data["gains"] is None else "saved",
            "ledPreset": data["ledPreset"], "deviceUpdated": data["deviceUpdated"],
            "age": age_of(data["deviceUpdated"])}


def list_profiles():
    try:
        names = os.listdir(profiles_dir())
    except FileNotFoundError:
        return []
    out = []
    for filename in names:
        if not filename.endswith(".json"):
            continue
        name = filename[:-5]
        if name.startswith("_") or not USER_NAME.fullmatch(name):
            continue
        out.append(name)
    return sorted(out, key=str.lower)


def delete_profile(name):
    try:
        path = profile_path(name)
    except ProfileError as exc:
        return {"ok": False, "error": str(exc)}
    if not os.path.isfile(path):
        return {"ok": False, "error": "perfil inexistente"}
    os.remove(path)
    return {"ok": True, "name": name}


def _load_file(name):
    path = profile_path(name, for_load=True)
    try:
        data = _read_json(path)
    except FileNotFoundError:
        raise ProfileError("perfil inexistente")
    except (OSError, ValueError):
        raise ProfileError("perfil inválido")
    return validate_profile(data)


def _apply_volumes(volumes):
    """Volumen absoluto y mute 0/1. El comando mute del CLI alterna; acá no."""
    sinks = _node_map("sink")
    sources = _node_map("source")
    for key in VOL_KEYS:
        kind = mgame.KIND[key]
        node = mgame.NODE_NAMES[key]
        if node not in (sinks if kind == "sink" else sources):
            raise LinuxError(f"nodo ausente: {node}")
        pct = volumes[key]["pct"]
        mute = volumes[key]["mute"]
        vol = mgame.pactl(f"set-{kind}-volume", node, f"{pct}%")
        if vol.returncode != 0:
            raise LinuxError(f"pactl volume {key}")
        mut = mgame.pactl(f"set-{kind}-mute", node, "1" if mute else "0")
        if mut.returncode != 0:
            raise LinuxError(f"pactl mute {key}")


def _apply_mic(mic):
    state = mgame.load_state()
    state["mic"] = {"enabled": mic["enabled"], "preset": mic["preset"], "overrides": dict(mic["overrides"])}
    mgame.save_state(state)
    params = mgame.mic_params(state)
    mgame.atomic_write(mgame.MIC_CONF, mgame.render_mic_conf(params))
    return bool(mgame.apply_mic_live(params))


def _gain_frames(gains):
    """Solo params de ganancia, por el camino allowlisted. Nunca phantom."""
    frames = []
    for dest in md.DESTS:
        for src in md.SRCS:
            param, vals = md.build_gain(dest, src, str(gains[dest][src]))
            if param == md.PHANTOM or (param & 0xFFFF0000) != md.GAIN_BASE:
                raise ProfileError("param fuera de ganancias")
            frames.append(md.checked_set(param, vals))
    if len(frames) != 36:
        raise ProfileError("ganancias incompletas")
    return frames


def _send_chunks(port, frames):
    """Lotes de 16, 30 ms (WRITE_GAP) entre lotes. Devuelve cuántas tramas salieron."""
    sent = 0
    chunks = md.chunked(frames, GAIN_CHUNK)
    for index, chunk in enumerate(chunks):
        if index and mgame.WRITE_GAP:
            time.sleep(mgame.WRITE_GAP)
        if not mgame.amidi_send_batch_quiet(port, chunk, GAIN_CHUNK, 0):
            break
        sent += len(chunk)
    return sent


def _send_gains(gains):
    if gains is None:
        return "skipped", None
    frames = _gain_frames(gains)
    try:
        port = mgame.dev_port()
    except md.DevError as exc:
        raise DeviceSendError(0, str(exc))
    sent = _send_chunks(port, frames)
    report = f"sent {sent}/36"
    if sent != 36:
        raise DeviceSendError(sent, report)
    return report, port


def _frame_param(frame):
    msg = mgame_proto.parse(frame)
    if msg is None:
        raise ProfileError("trama inválida")
    return msg.param_id


def _send_led(name, port):
    if name is None:
        return "skipped"
    leds = md.load_leds()
    items, _skipped = md.load_led_preset(name, leds)
    if port is None:
        port = mgame.dev_port()
    frames = []
    for _control, param, vals in items:
        if param == md.PHANTOM or (param & 0xFFFF0000) == md.GAIN_BASE:
            raise ProfileError("el preset de LEDs no puede escribir ganancias ni phantom")
        frame = md.checked_set(param, vals, leds)
        if _frame_param(frame) != param:
            raise ProfileError("trama de LED inválida")
        frames.append(frame)
    sent = _send_chunks(port, frames)
    if sent != len(frames):
        raise DeviceSendError(sent, "no se pudo enviar el preset de LEDs")
    mgame.note_led_preset(name)
    return "ok"


def load_profile(name):
    try:
        check_name(name, for_load=True)
    except ProfileError as exc:
        return {"ok": False, "error": str(exc)}
    held = mgame_lock.acquire(restore_target(), blocking=False)
    if held == "busy":
        return {"ok": False, "error": "busy"}
    try:
        return _load_locked(name)
    finally:
        held.release()


def _load_locked(name):
    try:
        profile = _load_file(name)
    except ProfileError as exc:
        updated = None
        try:
            raw = _read_json(profile_path(name, for_load=True))
            if isinstance(raw, dict) and _is_num(raw.get("deviceUpdated")):
                updated = raw["deviceUpdated"]
        except (OSError, ValueError, ProfileError):
            pass
        res = {"ok": False, "error": str(exc)}
        res.update(_meta(updated))
        return res

    meta = _meta(profile["deviceUpdated"])
    try:
        undo = validate_profile(capture_live())
    except (ProfileError, LinuxError) as exc:
        res = {"ok": False, "error": str(exc), "step": "undo"}
        res.update(meta)
        return res
    _write_profile(profile_path(UNDO_NAME, for_load=True), undo)

    base = {"ok": False, "name": name, "undo": UNDO_NAME}
    base.update(meta)
    try:
        _apply_volumes(profile["volumes"])
    except LinuxError as exc:
        base["error"] = str(exc)
        base["step"] = "volumes"
        return base

    try:
        live = _apply_mic(profile["mic"])
    except (OSError, ProfileError) as exc:
        base["error"] = str(exc)
        base["step"] = "mic"
        base["mic"] = {"live": False}
        return base
    if not live:
        base["error"] = "el mic en vivo falló"
        base["step"] = "mic"
        base["mic"] = {"live": False}
        return base

    try:
        mgame_apps.replace_rules(profile["rules"])
    except (OSError, ValueError) as exc:
        base["error"] = str(exc)
        base["step"] = "rules"
        base["mic"] = {"live": True}
        return base

    try:
        gains_report, port = _send_gains(profile["gains"])
    except DeviceSendError as exc:
        base["error"] = str(exc)
        base["step"] = "gains"
        base["mic"] = {"live": True}
        base["gains"] = f"sent {exc.sent}/36"
        return base
    except (md.DevError, ProfileError, OSError) as exc:
        base["error"] = str(exc)
        base["step"] = "gains"
        base["mic"] = {"live": True}
        base["gains"] = "sent 0/36"
        return base

    try:
        led_report = _send_led(profile["ledPreset"], port)
    except (md.DevError, ProfileError, OSError, DeviceSendError) as exc:
        base["error"] = str(exc)
        base["step"] = "ledPreset"
        base["mic"] = {"live": True}
        base["gains"] = gains_report
        base["ledPreset"] = "failed"
        return base

    return {"ok": True, "name": name, "undo": UNDO_NAME, "mic": {"live": True},
            "gains": gains_report, "ledPreset": led_report, **meta}


def cmd_list(args):
    if args:
        return {"ok": False, "error": "uso: profile-list"}
    return {"ok": True, "profiles": list_profiles()}


def cmd_save(args):
    if len(args) != 1:
        return {"ok": False, "error": "uso: profile-save NAME"}
    return save_profile(args[0])


def cmd_load(args):
    if len(args) != 1:
        return {"ok": False, "error": "uso: profile-load NAME"}
    return load_profile(args[0])


def cmd_delete(args):
    if len(args) != 1:
        return {"ok": False, "error": "uso: profile-delete NAME"}
    return delete_profile(args[0])
