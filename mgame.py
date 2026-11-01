#!/usr/bin/env python3
"""Helper del plugin M-Game Mixer.

Se invoca siempre con argv (nunca por shell). Cada valor externo se valida
contra listas cerradas o contra un patrón estricto antes de usarse.

Estado y mezcla
  status [PARES]                  JSON con todo el estado (lo lee el widget)
  volume CLAVE PCT                volumen 0-150 de un canal
  mute CLAVE                      alterna mute
  default CLAVE                   lo deja como salida/entrada por defecto
  move ID CLAVE                   mueve una app (sink-input) a una salida

Configuración de PipeWire
  install [PARES]                 escribe 50-mgame-split.conf y 51-mgame-mic.conf
                                  y reinicia pipewire, pipewire-pulse y wireplumber
  write-conf [PARES]              escribe las configs sin reiniciar nada
  render DIR [PARES]              escribe las configs en DIR (para el repo)

Procesado del micrófono
  mic-preset NOMBRE               off | natural | broadcast | noisy
  mic-set vad|ratio|presence N    ajuste fino sobre el preset
  mic-enable on|off               enciende/apaga la cadena (preset "off")

Sampler
  ensure-dirs                     crea la carpeta de samples y la config
  sample-assign PAD ARCHIVO [SET] asigna un archivo de la biblioteca (pads 1-5)
  sample-clear PAD [SET]
  sample-play PAD [SET]           reproduce lo asignado al pad
                                  SET = 1A 1B 2A 2B (página 1/2 y banco A/B); sin SET usa el activo
  sample-preview ARCHIVO          reproduce un archivo de la biblioteca
  sample-stop
  listen                          escucha la M-Game (aseqdump): pads, mutes, páginas y banco
  listener-enable                 instala y arranca el servicio systemd --user del listener
  listener-disable                lo detiene y lo desactiva

Protocolo SysEx (ver docs/protocol.md)
  decode HEX                      valida y decodifica una trama
  send-raw HEX                    valida y envía una trama a la M-Game (amidi)
  get PARAM_HEX [--sub N] [--timeout S]   pide un parámetro e imprime las respuestas

Dispositivo (JSON por stdout, ver docs/device-api.md)
  dev-state [--refresh]           estado completo (device.json); --refresh pide todo al aparato
  dev-gain DEST SRC 0..127        ganancia de una ruta del mezclador
  dev-route DEST SRC on|off       enciende/apaga una ruta (recuerda la ganancia)
  dev-routing-preset NOMBRE       default | no_chat_to_stream
  dev-phantom on|off              alimentación fantasma 48 V
  dev-led CONTROL ACTIVE IDLE [MODE]   color de un LED de botón/pad
  dev-led-presets                 lista de presets de LEDs
  dev-led-preset NOMBRE           aplica un preset de LEDs
  dev-fx                          lectura de knob y bloques (no envía nada)
  dev-fx-presets                  lista de presets de voz y de mic
  dev-fx-preset voice|mic NAME    contenido de un preset (no lo aplica)

Apps (JSON por stdout; apps-watch es el servicio, no el panel)
  apps-rules                      lista las reglas de enrutado
  apps-rule-set MATCH FIELD SINK  agrega o reemplaza una regla
  apps-rule-del MATCH FIELD       borra una regla
  apps-apply                      aplica las reglas una vez (pase completo)
  apps-watch                      vigila sink-inputs nuevos (no lo llama el panel)
  apps-watch-enable               instala y arranca mgame-mixer-apps.service
  apps-watch-disable              lo detiene y lo desactiva

Perfiles (JSON por stdout)
  profile-list                    nombres (oculta los que empiezan con _)
  profile-save NAME               guarda volúmenes, mic, reglas, ganancias y LED
  profile-load NAME               restaura un perfil (o _before-restore)
  profile-delete NAME             borra un perfil (rechaza un _ inicial)

PARES = ocho pares separados por coma, en este orden:
  game,chat,sampler,system,in_stream,in_alt,in_chat,in_sampler
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

import mgame_lock

HOME = os.path.expanduser("~")
CONF_DIR = os.path.join(HOME, ".config", "pipewire", "pipewire.conf.d")
SPLIT_CONF = os.path.join(CONF_DIR, "50-mgame-split.conf")
MIC_CONF = os.path.join(CONF_DIR, "51-mgame-mic.conf")
CFG_DIR = os.path.join(HOME, ".config", "mgame-mixer")
STATE_PATH = os.path.join(CFG_DIR, "state.json")
PADS_PATH = os.path.join(CFG_DIR, "pads.json")
SAMPLE_DIR = os.path.join(HOME, ".local", "share", "mgame-mixer", "samples")
LOG_DIR = os.path.join(HOME, ".local", "state", "mgame-mixer")
SYSEX_LOG = os.path.join(LOG_DIR, "sysex.log")
PID_DIR = os.path.join(LOG_DIR, "pids")
SHIPPED_PADS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "pads.json")
UNIT_NAME = "mgame-mixer-pads.service"
UNIT_PATH = os.path.join(HOME, ".config", "systemd", "user", UNIT_NAME)
APPS_UNIT_NAME = "mgame-mixer-apps.service"
APPS_UNIT_PATH = os.path.join(HOME, ".config", "systemd", "user", APPS_UNIT_NAME)
SEQ_CLIENT = "M-Game RGB Dual Streaming Port"
BUTTONS_PATH = os.path.join(CFG_DIR, "buttons.json")
SHIPPED_BUTTONS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "buttons.json")
HW_PATH = os.path.join(LOG_DIR, "hw.json")
SETS = ("1A", "1B", "2A", "2B")  # página (1/2) y banco (A = apagado, B = encendido)
MUTE_BUTTONS = ("mic_mute", "game_mute", "chat_mute", "sampler_mute", "main_alt_mute")
BUTTON_NAMES = MUTE_BUTTONS + ("sample_page_1", "sample_page_2", "bank_switch")

HW_OUT_FALLBACK = "alsa_output.usb-M-Audio_M-Game_RGB_Dual_Streaming_Port-01.analog-surround-71"
HW_IN_FALLBACK = "alsa_input.usb-M-Audio_M-Game_RGB_Dual_Streaming_Port-01.analog-surround-71"

ALL_PAIRS = ("FL FR", "FC LFE", "RL RR", "SL SR")
OUT_KEYS = ("game", "chat", "sampler", "system")
IN_KEYS = ("in_stream", "in_alt", "in_chat", "in_sampler")
PAIR_KEYS = OUT_KEYS + IN_KEYS
DEFAULT_PAIRS = dict(zip(PAIR_KEYS, ("FL FR", "FC LFE", "RL RR", "SL SR") * 2))

DESCRIPTIONS = {
    "game": "M-Game Game", "chat": "M-Game Chat",
    "sampler": "M-Game Sampler", "system": "M-Game System",
    "in_stream": "M-Game Stream (in)", "in_alt": "M-Game Alt (in)",
    "in_chat": "M-Game Chat (in)", "in_sampler": "M-Game Sampler (in)",
}
NODE_NAMES = {
    "game": "mgame_game", "chat": "mgame_chat",
    "sampler": "mgame_sampler", "system": "mgame_system",
    "in_stream": "mgame_in_stream", "in_alt": "mgame_in_alt",
    "in_chat": "mgame_in_chat", "in_sampler": "mgame_in_sampler",
    "mic": "mgame_mic_processed",
}
KIND = {k: "sink" for k in OUT_KEYS}
KIND.update({k: "source" for k in IN_KEYS})
KIND["mic"] = "source"

SAMPLE_EXTS = (".wav", ".flac", ".ogg", ".opus", ".mp3")
PADS = ("1", "2", "3", "4", "5")

# --------------------------------------------------------------------------
# Presets del micrófono. dB salvo que se indique otra unidad.
#   vad: umbral de voz de RNNoise (0-99), grace: ms que sigue abierto
#   hpf: pasa-altos (Hz), mud/presence/air: ganancia de EQ
#   thr/ratio/atk/rel/makeup: compresor. comp=False lo deja en bypass
#   gate: reducción en dB cuando está cerrado (None = sin gate), gate_thr: umbral
# --------------------------------------------------------------------------
PRESETS = {
    "off": dict(dry=1, vad=0, grace=500, hpf=20, mud=0, presence=0, air=0,
                comp=False, thr=-18, ratio=1, atk=10, rel=150, makeup=0,
                gate=None, gate_thr=-50),
    "natural": dict(dry=0, vad=50, grace=300, hpf=80, mud=-1, presence=2, air=0,
                    comp=True, thr=-20, ratio=2, atk=15, rel=150, makeup=2,
                    gate=None, gate_thr=-50),
    "broadcast": dict(dry=0, vad=60, grace=250, hpf=90, mud=-3, presence=4, air=2,
                      comp=True, thr=-24, ratio=4, atk=8, rel=120, makeup=5,
                      gate=None, gate_thr=-50),
    "noisy": dict(dry=0, vad=85, grace=200, hpf=120, mud=-3, presence=3, air=0,
                  comp=True, thr=-22, ratio=3, atk=8, rel=120, makeup=4,
                  gate=18, gate_thr=-45),
}
OVERRIDE_RANGES = {"vad": (0, 99), "ratio": (1, 10), "presence": (-6, 9)}


def db_lin(db):
    return round(10 ** (db / 20.0), 6)


# ------------------------------- utilidades --------------------------------
def run(*args, timeout=5):
    return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)


def pactl(*args):
    return run("pactl", *args)


def pactl_json(*args):
    try:
        out = pactl("--format=json", *args)
        return json.loads(out.stdout) if out.returncode == 0 else []
    except Exception:
        return []


# apps-watch sale antes de importar el dispositivo. El resto de los comandos
# necesita atomic_write, y tiene que ser el mismo objeto que mgame_device.atomic_write.
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "apps-watch":
    import mgame_apps
    if len(sys.argv) > 2:
        print(json.dumps({"ok": False, "error": "uso: apps-watch"}))
        raise SystemExit(1)
    mgame_apps.watch()
    raise SystemExit(1)


from mgame_device import atomic_write  # noqa: E402  (única implementación, temporal único)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def parse_pairs(arg):
    pairs = dict(DEFAULT_PAIRS)
    if not arg:
        return pairs
    parts = [p.strip() for p in arg.split(",")]
    if len(parts) == len(PAIR_KEYS) and all(p in ALL_PAIRS for p in parts):
        pairs = dict(zip(PAIR_KEYS, parts))
    return pairs


def pairs_arg(pairs):
    return ",".join(pairs[k] for k in PAIR_KEYS)


def find_hw(kind):
    prefix = "alsa_output.usb-M-Audio_M-Game" if kind == "sink" else "alsa_input.usb-M-Audio_M-Game"
    for dev in pactl_json("list", "sinks" if kind == "sink" else "sources"):
        name = dev.get("name", "")
        if name.startswith(prefix) and not name.endswith(".monitor"):
            return name
    return HW_OUT_FALLBACK if kind == "sink" else HW_IN_FALLBACK


# ------------------------------- estado ------------------------------------
def load_state():
    state = load_json(STATE_PATH, {})
    mic = state.get("mic") if isinstance(state.get("mic"), dict) else {}
    preset = mic.get("preset") if mic.get("preset") in PRESETS and mic.get("preset") != "off" else "natural"
    overrides = {}
    for key, (lo, hi) in OVERRIDE_RANGES.items():
        val = (mic.get("overrides") or {}).get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            overrides[key] = max(lo, min(hi, val))
    raw_pads = state.get("pads") if isinstance(state.get("pads"), dict) else {}
    pads = {s: {} for s in SETS}
    if any(k in PADS for k in raw_pads):  # formato viejo: un solo juego de 5 pads
        pads["1A"] = {k: v for k, v in raw_pads.items() if k in PADS and isinstance(v, str)}
    for s in SETS:
        group = raw_pads.get(s)
        if isinstance(group, dict):
            pads[s] = {k: v for k, v in group.items() if k in PADS and isinstance(v, str)}
    return {"mic": {"enabled": bool(mic.get("enabled", True)), "preset": preset, "overrides": overrides},
            "pads": pads}


def save_state(state):
    with mgame_lock.exclusive(STATE_PATH):
        merged = load_json(STATE_PATH, {})  # conserva claves ajenas (p. ej. routeMemory)
        merged.update(state)
        atomic_write(STATE_PATH, json.dumps(merged, indent=2, ensure_ascii=False) + "\n")


def note_led_preset(name):
    """dev-led-preset lo registra al tener éxito. Mezcla; no borra routeMemory."""
    save_state({"ledPreset": name})


def mic_params(state):
    mic = state["mic"]
    if not mic["enabled"]:
        return dict(PRESETS["off"])
    params = dict(PRESETS[mic["preset"]])
    params.update(mic["overrides"])
    return params


# ------------------------------- configs -----------------------------------
def render_split_conf(pairs, hw_out, hw_in):
    out = ["# M-Audio M-Game RGB Dual: divide la salida y la entrada USB de 8 canales.",
           "# Generado por el plugin io.github.crisesarmiento.mgame-mixer; no lo edites a mano.",
           "# mgame-pairs: " + pairs_arg(pairs),
           "context.modules = ["]
    for key in OUT_KEYS:
        name = NODE_NAMES[key]
        out.append(f"""  {{ name = libpipewire-module-loopback
    args = {{
      node.description = "{DESCRIPTIONS[key]}"
      capture.props  = {{ node.name = "{name}" media.class = "Audio/Sink" audio.position = [ FL FR ] }}
      playback.props = {{ node.name = "{name}.out" audio.position = [ {pairs[key]} ]
                         target.object = "{hw_out}"
                         stream.dont-remix = true node.passive = true }}
    }}
  }}""")
    for key in IN_KEYS:
        name = NODE_NAMES[key]
        out.append(f"""  {{ name = libpipewire-module-loopback
    args = {{
      node.description = "{DESCRIPTIONS[key]}"
      capture.props  = {{ node.name = "{name}.capture" audio.position = [ {pairs[key]} ]
                         target.object = "{hw_in}"
                         stream.dont-remix = true node.passive = true }}
      playback.props = {{ node.name = "{name}" media.class = "Audio/Source" audio.position = [ FL FR ] }}
    }}
  }}""")
    out.append("]")
    return "\n".join(out) + "\n"


# Controles de la cadena: (nodo, puerto, valor). El mismo listado sirve para
# escribir la config y para aplicar cambios en vivo con pw-cli.
def mic_controls(p):
    ctl = [
        ("rnn", "VAD Threshold (%)", int(p["vad"])),
        ("rnn", "VAD Grace Period (ms)", int(p["grace"])),
        ("rnn", "Retroactive VAD Grace (ms)", 0),
        ("rnn", "Dry Mix", int(p["dry"])),
        ("hpf", "Freq", float(p["hpf"])),
        ("hpf", "Q", 0.707),
        ("mud", "Freq", 300.0),
        ("mud", "Q", 1.0),
        ("mud", "Gain", float(p["mud"])),
        ("presence", "Freq", 3000.0),
        ("presence", "Q", 0.9),
        ("presence", "Gain", float(p["presence"])),
        ("air", "Freq", 9000.0),
        ("air", "Q", 0.707),
        ("air", "Gain", float(p["air"])),
        ("comp", "Bypass", 0 if p["comp"] else 1),
        ("comp", "Compression mode", 0),
        ("comp", "Attack threshold (G)", db_lin(p["thr"])),
        ("comp", "Ratio", float(p["ratio"])),
        ("comp", "Attack time (ms)", float(p["atk"])),
        ("comp", "Release time (ms)", float(p["rel"])),
        ("comp", "Knee (G)", 0.501196),
        ("comp", "Makeup gain (G)", db_lin(p["makeup"])),
    ]
    gate = p["gate"]
    ctl += [
        ("gate", "Bypass", 1 if gate is None else 0),
        ("gate", "Curve threshold (G)", db_lin(p["gate_thr"])),
        ("gate", "Attack (ms)", 5.0),
        ("gate", "Release (ms)", 150.0),
        ("gate", "Hold time (ms)", 50.0),
        ("gate", "Reduction (G)", db_lin(-(gate if gate is not None else 0))),
    ]
    return ctl


def fmt(v):
    return str(v) if isinstance(v, int) else repr(round(float(v), 6))


def render_mic_conf(p):
    by_node = {}
    for node, port, val in mic_controls(p):
        by_node.setdefault(node, []).append(f'"{port}" = {fmt(val)}')

    def ctl(node):
        return "{ " + " ".join(by_node[node]) + " }"

    lsp = "http://lsp-plug.in/plugins/ladspa/"
    return f"""# Cadena de procesado del micrófono (RNNoise, EQ, compresor, gate).
# Generado por el plugin io.github.crisesarmiento.mgame-mixer; no lo edites a mano.
# La entrada es la fuente "M-Game Alt (in)", mezclada a mono.
context.modules = [
  {{ name = libpipewire-module-filter-chain
    args = {{
      node.description = "M-Game Mic (processed)"
      media.name       = "M-Game Mic (processed)"
      audio.rate       = 48000
      filter.graph = {{
        nodes = [
          {{ type = ladspa name = rnn plugin = librnnoise_ladspa label = noise_suppressor_mono
            control = {ctl("rnn")} }}
          {{ type = builtin name = hpf label = bq_highpass control = {ctl("hpf")} }}
          {{ type = builtin name = mud label = bq_peaking control = {ctl("mud")} }}
          {{ type = builtin name = presence label = bq_peaking control = {ctl("presence")} }}
          {{ type = builtin name = air label = bq_highshelf control = {ctl("air")} }}
          {{ type = ladspa name = comp plugin = lsp-plugins-ladspa label = "{lsp}compressor_mono"
            control = {ctl("comp")} }}
          {{ type = ladspa name = gate plugin = lsp-plugins-ladspa label = "{lsp}gate_mono"
            control = {ctl("gate")} }}
        ]
        links = [
          {{ output = "rnn:Output"      input = "hpf:In" }}
          {{ output = "hpf:Out"         input = "mud:In" }}
          {{ output = "mud:Out"         input = "presence:In" }}
          {{ output = "presence:Out"    input = "air:In" }}
          {{ output = "air:Out"         input = "comp:Input" }}
          {{ output = "comp:Output"     input = "gate:Input" }}
        ]
        inputs  = [ "rnn:Input" ]
        outputs = [ "gate:Output" ]
      }}
      capture.props = {{
        node.name = "mgame_mic.capture"
        target.object = "{NODE_NAMES['in_alt']}"
        audio.position = [ MONO ]
        node.passive = true
      }}
      playback.props = {{
        node.name = "{NODE_NAMES['mic']}"
        media.class = "Audio/Source"
        audio.position = [ MONO ]
      }}
    }}
  }}
]
"""


def write_confs(pairs):
    atomic_write(SPLIT_CONF, render_split_conf(pairs, find_hw("sink"), find_hw("source")))
    atomic_write(MIC_CONF, render_mic_conf(mic_params(load_state())))


def installed_pairs():
    try:
        with open(SPLIT_CONF, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"# mgame-pairs: (.+)$", line.strip())
                if m:
                    parts = [p.strip() for p in m.group(1).split(",")]
                    if len(parts) == len(PAIR_KEYS) and all(p in ALL_PAIRS for p in parts):
                        return dict(zip(PAIR_KEYS, parts))
    except OSError:
        pass
    return {}


def install(pairs):
    write_confs(pairs)
    subprocess.run(["systemctl", "--user", "restart", "pipewire", "pipewire-pulse", "wireplumber"], timeout=30)


# ----------------------- aplicar el mic en vivo ----------------------------
def mic_node_id():
    """Id del nodo del filter-chain que acepta Props con params, o None."""
    try:
        dump = json.loads(run("pw-dump", timeout=5).stdout)
    except Exception:
        return None
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        info = obj.get("info") or {}
        props = info.get("props") or {}
        if not str(props.get("node.name", "")).startswith("mgame_mic"):
            continue
        for entry in (info.get("params") or {}).get("Props", []) or []:
            params = entry.get("params") if isinstance(entry, dict) else None
            if isinstance(params, list) and any(isinstance(x, str) and x.startswith("rnn:") for x in params):
                return int(obj["id"])
    return None


def apply_mic_live(params):
    node = mic_node_id()
    if node is None:
        return False
    items = " ".join(f'"{n}:{p}" {fmt(v)}' for n, p, v in mic_controls(params))
    res = run("pw-cli", "s", str(node), "Props", "{ params = [ " + items + " ] }")
    return res.returncode == 0


def mic_commit(state):
    save_state(state)
    params = mic_params(state)
    atomic_write(MIC_CONF, render_mic_conf(params))
    apply_mic_live(params)


# ------------------------------- sampler -----------------------------------
def ensure_dirs():
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    os.makedirs(CFG_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(PADS_PATH):
        try:
            with open(SHIPPED_PADS, encoding="utf-8") as fh:
                text = fh.read()
            json.loads(text)
        except (OSError, ValueError):
            text = json.dumps({"client": SEQ_CLIENT, "pads": {p: {"press": ""} for p in PADS}}, indent=2) + "\n"
        atomic_write(PADS_PATH, text)
    if not os.path.exists(BUTTONS_PATH):
        try:
            with open(SHIPPED_BUTTONS, encoding="utf-8") as fh:
                text = fh.read()
            json.loads(text)
        except (OSError, ValueError):
            text = json.dumps({"buttons": {}}) + "\n"
        atomic_write(BUTTONS_PATH, text)


def list_samples():
    try:
        names = [n for n in os.listdir(SAMPLE_DIR)
                 if n.lower().endswith(SAMPLE_EXTS) and len(n) <= 120
                 and os.path.isfile(os.path.join(SAMPLE_DIR, n))]
    except OSError:
        return []
    return sorted(names, key=str.lower)[:200]


def sample_path(name):
    if not isinstance(name, str) or not name or os.path.basename(name) != name or name.startswith("-"):
        raise SystemExit("archivo inválido")
    if not name.lower().endswith(SAMPLE_EXTS):
        raise SystemExit("extensión no permitida")
    path = os.path.realpath(os.path.join(SAMPLE_DIR, name))
    if os.path.dirname(path) != os.path.realpath(SAMPLE_DIR) or not os.path.isfile(path):
        raise SystemExit("el archivo no está en la biblioteca")
    return path


def pid_alive_pwplay(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            argv = fh.read().split(b"\0")
        return argv[0].endswith(b"pw-play") or (len(argv) > 1 and argv[1].endswith(b"pw-play"))
    except OSError:
        return False


def kill_slot(slot):
    """Corta lo que esté sonando en ese slot (pad o preview) para reiniciarlo."""
    pidfile = os.path.join(PID_DIR, slot + ".pid")
    try:
        with open(pidfile, encoding="utf-8") as fh:
            pid = int(fh.read().strip())
        if pid_alive_pwplay(pid):
            os.kill(pid, 15)
    except (OSError, ValueError):
        pass


def play_file(path, slot):
    kill_slot(slot)
    proc = subprocess.Popen(["pw-play", "--target", NODE_NAMES["sampler"], path],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    os.makedirs(PID_DIR, exist_ok=True)
    atomic_write(os.path.join(PID_DIR, slot + ".pid"), str(proc.pid))


def pad_arg(value):
    if value not in PADS:
        raise SystemExit("pad inválido (1-5)")
    return value


def set_arg(value):
    if value not in SETS:
        raise SystemExit("set inválido (1A 1B 2A 2B)")
    return value


def read_hw():
    """Estado de los botones con memoria; None = todavía no se pulsó desde que arrancó el listener."""
    hw = load_json(HW_PATH, {})
    out = {name: (hw.get(name) if isinstance(hw.get(name), bool) else None) for name in MUTE_BUTTONS}
    out["page"] = hw.get("page") if hw.get("page") in (1, 2) else None
    out["bank"] = hw.get("bank") if hw.get("bank") in ("A", "B") else None
    return out


def write_hw(hw):
    atomic_write(HW_PATH, json.dumps(hw) + "\n")


def active_set():
    hw = read_hw()
    return f"{hw['page'] or 1}{hw['bank'] or 'A'}"


def play_pad(pad, set_name=None):
    name = load_state()["pads"].get(set_name or active_set(), {}).get(pad)
    if name:
        play_file(sample_path(name), "pad" + pad)


def stop_samples():
    for slot in ["preview"] + ["pad" + p for p in PADS]:
        kill_slot(slot)


def token_ok(tokens):
    return bool(tokens) and all(re.fullmatch(r"[0-9A-F]{2}|\?\?", t) for t in tokens)


def pads_config():
    """(nombre del cliente ALSA seq, {pad: [tokens del mensaje de pulsación]})."""
    cfg = load_json(PADS_PATH, {})
    pads = cfg.get("pads") if isinstance(cfg.get("pads"), dict) else {}
    patterns = {}
    for pad in PADS:
        raw = pads.get(pad)
        if isinstance(raw, dict):
            raw = raw.get("press")
        if isinstance(raw, str):
            toks = raw.upper().split()
            if token_ok(toks):
                patterns[pad] = toks
    client = cfg.get("client") if isinstance(cfg.get("client"), str) and cfg.get("client") else SEQ_CLIENT
    return client[:80], patterns


def buttons_config():
    """{nombre: {"on": tokens, "off": tokens}} para los botones que el listener entiende."""
    cfg = load_json(BUTTONS_PATH, {})
    buttons = cfg.get("buttons") if isinstance(cfg.get("buttons"), dict) else {}
    out = {}
    for name in BUTTON_NAMES:
        spec = buttons.get(name)
        if not isinstance(spec, dict):
            continue
        entry = {}
        for state in ("on", "off"):
            raw = spec.get(state)
            toks = raw.upper().split() if isinstance(raw, str) else []
            if token_ok(toks):
                entry[state] = toks
        if entry:
            out[name] = entry
    return out


def apply_button(hw, name, on):
    if name in MUTE_BUTTONS:
        hw[name] = on
    elif name == "sample_page_1" and on:
        hw["page"] = 1
    elif name == "sample_page_2" and on:
        hw["page"] = 2
    elif name == "bank_switch":
        hw["bank"] = "B" if on else "A"


def sysex_matches(pattern, data):
    """Coincidencia por prefijo; '??' acepta cualquier byte."""
    if len(data) < len(pattern):
        return False
    return all(p == "??" or p == d for p, d in zip(pattern, data))


def resolve_port(client):
    """Busca el cliente ALSA seq por nombre (el número cambia entre arranques)."""
    try:
        out = run("aseqdump", "-l").stdout
    except Exception:
        return None
    best = None
    for line in out.splitlines():
        m = re.match(r"\s*(\d+):(\d+)\s+(.+?)\s{2,}", line)
        if not m:
            continue
        name = m.group(3).strip()
        if name == client:
            return f"{m.group(1)}:{m.group(2)}"
        if best is None and "M-Game" in name:
            best = f"{m.group(1)}:{m.group(2)}"
    return best


def log_sysex(data):
    os.makedirs(LOG_DIR, exist_ok=True)
    try:
        if os.path.getsize(SYSEX_LOG) > 100_000:
            os.truncate(SYSEX_LOG, 0)
    except OSError:
        pass
    with open(SYSEX_LOG, "a", encoding="utf-8") as fh:
        fh.write(time.strftime("%H:%M:%S ") + " ".join(data) + "\n")


REFRESH_GAP = 0.01       # s entre gets del refresco
REFRESH_QUIET = 8.0      # s tras arrancar sin loguear las tramas ya conocidas (evita llenar sysex.log)


def amidi_send_quiet(port, frame):
    import mgame_proto
    try:
        res = run("amidi", "-p", port, "-S", mgame_proto.to_hex(frame).replace(" ", ""), timeout=5)
        return res.returncode == 0
    except Exception:
        return False


def _hex_batch(frames):
    import mgame_proto
    return " ".join(mgame_proto.to_hex(f).replace(" ", "") for f in frames)


GET_CHUNK = 16           # gets por llamada a amidi en un refresco
GET_PAUSE = 0.03         # s entre lotes de gets: con un solo lote de 64 el equipo perdía alguna respuesta


def amidi_send_batch_quiet(port, frames, size=None, pause=0.0):
    """Varias tramas por llamada a amidi (-S admite mensajes concatenados). True si todas salieron."""
    import mgame_device
    ok = True
    for i, chunk in enumerate(mgame_device.chunked(frames, size or mgame_device.BATCH_LIMIT)):
        if i and pause:
            time.sleep(pause)
        try:
            res = run("amidi", "-p", port, "-S", _hex_batch(chunk), timeout=10)
            ok = ok and res.returncode == 0
        except Exception:
            ok = False
    return ok


def amidi_send_batch(port, frames):
    import mgame_device
    for chunk in mgame_device.chunked(frames):
        res = run("amidi", "-p", port, "-S", _hex_batch(chunk), timeout=10)
        if res.returncode != 0:
            raise SystemExit("amidi no pudo enviar (¿puerto ocupado?): " + res.stderr.strip()[:200])


def refresh_device(leds, gap=None):
    """Envía todos los gets para conocer el estado. Reintenta mientras el rawmidi no aparezca."""
    import mgame_device
    port = None
    for _ in range(20):
        port = find_rawmidi()
        if port:
            break
        time.sleep(0.5)
    if not port:
        return False
    amidi_send_batch_quiet(port, mgame_device.refresh_frames(leds), GET_CHUNK, GET_PAUSE)
    return True


def listen():
    import mgame_device
    import mgame_proto
    ensure_dirs()
    client, patterns = pads_config()
    if not patterns:
        print("pads.json sin patrones configurados", file=sys.stderr)
        raise SystemExit(3)
    port = resolve_port(client)
    if not port:
        print("no se encontró el puerto MIDI de la M-Game", file=sys.stderr)
        raise SystemExit(1)
    proc = subprocess.Popen(["aseqdump", "-p", port], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    ledmap = mgame_device.LedMapCache()
    ledmap.refresh()
    dev = mgame_device.DeviceState(ledmap.leds)
    dev.connected = True
    dev.save()
    hw_last = dev.hw()
    write_hw(hw_last)  # al arrancar todo es desconocido hasta que llegan las respuestas del refresco
    quiet_until = time.monotonic() + REFRESH_QUIET
    threading.Thread(target=lambda: refresh_device(ledmap.leds), daemon=True).start()
    pending, last = [], {}
    try:
        for line in proc.stdout:
            if "System exclusive" not in line:
                continue
            toks = [t.upper() for t in line.split("System exclusive", 1)[1].split()
                    if re.fullmatch(r"[0-9A-Fa-f]{2}", t)]
            data = pending + toks
            if not data or data[-1] != "F7":
                pending = data[:512]
                continue
            pending = []
            now = time.monotonic()
            _, patterns = pads_config()
            for pad, pattern in patterns.items():
                if sysex_matches(pattern, data) and now - last.get(pad, 0) > 0.05:
                    last[pad] = now
                    try:
                        play_pad(pad)
                    except (SystemExit, OSError):
                        pass
            try:
                msg = mgame_proto.parse(bytes(int(t, 16) for t in data))
            except ValueError:
                msg = None
            known = changed = False
            if msg is not None:
                if ledmap.refresh():
                    dev.set_leds(ledmap.leds)
                known, changed = dev.ingest(msg)
                dev.save(changed=changed)
                hw = dev.hw()
                if hw != hw_last:
                    hw_last = hw
                    write_hw(hw)
            if not (known and now < quiet_until):
                log_sysex(data)
    finally:
        dev.connected = False
        dev.save()
        write_hw({name: None for name in list(MUTE_BUTTONS) + ["page", "bank"]})
    raise SystemExit(1)


# ------------------------- protocolo SysEx (raw) ---------------------------
def find_rawmidi():
    """hw:X,Y,Z de la M-Game vía `amidi -l`, o None."""
    try:
        out = run("amidi", "-l").stdout
    except Exception:
        return None
    for line in out.splitlines():
        m = re.match(r"\S+\s+(hw:\d+,\d+(?:,\d+)?)\s+(.+)$", line.strip())
        if m and "M-Game RGB Dual" in m.group(2):
            return m.group(1)
    return None


def proto_frame(hex_str):
    import mgame_proto
    try:
        frame = mgame_proto.from_hex(hex_str)
    except ValueError:
        raise SystemExit("hex inválido")
    if frame[:5] != mgame_proto.HEADER:
        raise SystemExit("la trama no empieza con el header de la M-Game")
    msg = mgame_proto.parse(frame)
    if msg is None:
        raise SystemExit("trama inválida (longitud o checksum)")
    return frame, msg


def amidi_send(port, frame):
    import mgame_proto
    res = run("amidi", "-p", port, "-S", mgame_proto.to_hex(frame).replace(" ", ""), timeout=5)
    if res.returncode != 0:
        raise SystemExit("amidi no pudo enviar (¿puerto ocupado?): " + res.stderr.strip()[:200])


def cmd_decode(hex_str):
    _, msg = proto_frame(hex_str)
    print(json.dumps(msg.to_dict()))


def cmd_send_raw(hex_str):
    frame, _ = proto_frame(hex_str)
    port = find_rawmidi()
    if not port:
        raise SystemExit("no se encontró el rawmidi de la M-Game")
    amidi_send(port, frame)


def cmd_get(param_hex, sub, timeout):
    import mgame_proto
    if not re.fullmatch(r"(0x)?[0-9A-Fa-f]{1,8}", param_hex):
        raise SystemExit("param inválido (hex)")
    frame = mgame_proto.build_get(int(param_hex, 16), sub)
    port = find_rawmidi()
    if not port:
        raise SystemExit("no se encontró el rawmidi de la M-Game")
    rx = subprocess.Popen(["amidi", "-p", port, "-d", "-t", str(max(1, int(timeout)))],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.2)
    if rx.poll() is not None:
        raise SystemExit("amidi no pudo abrir el puerto para leer (¿ocupado por otro lector?): "
                         + (rx.stderr.read() or "").strip()[:200])
    amidi_send(port, frame)
    out, _ = rx.communicate(timeout=timeout + 5)
    toks = re.findall(r"\b[0-9A-F]{2}\b", out)
    cur = []
    for t in toks:
        if t == "F0":
            cur = []
        cur.append(t)
        if t == "F7":
            msg = mgame_proto.parse(bytes(int(x, 16) for x in cur))
            print(json.dumps({"raw": " ".join(cur), "msg": msg.to_dict() if msg else None}))
            cur = []


def listener_enable():
    script = os.path.realpath(__file__)
    if re.search(r"[\s%$\"'\\]", script):
        raise SystemExit("la ruta del plugin tiene caracteres no soportados por systemd")
    ensure_dirs()
    atomic_write(UNIT_PATH, f"""[Unit]
Description=M-Game Mixer: pads físicos de la M-Game disparan el sampler
After=pipewire.service

[Service]
ExecStart=/usr/bin/python3 -u {script} listen
Restart=on-failure
RestartSec=5
RestartPreventExitStatus=3

[Install]
WantedBy=default.target
""")
    run("systemctl", "--user", "daemon-reload", timeout=15)
    run("systemctl", "--user", "enable", "--now", UNIT_NAME, timeout=15)


def listener_disable():
    run("systemctl", "--user", "disable", "--now", UNIT_NAME, timeout=15)


def apps_unit_text(script):
    return f"""[Unit]
Description=M-Game Mixer: enruta las apps según app-rules.json
After=pipewire.service

[Service]
ExecStart=/usr/bin/python3 -u {script} apps-watch
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
"""


def apps_watch_enable(args):
    if args:
        return {"ok": False, "error": "uso: apps-watch-enable"}
    script = os.path.realpath(__file__)
    if re.search(r"[\s%$\"'\\]", script):
        return {"ok": False, "error": "la ruta del plugin tiene caracteres no soportados por systemd"}
    ensure_dirs()
    atomic_write(APPS_UNIT_PATH, apps_unit_text(script))
    rel = run("systemctl", "--user", "daemon-reload", timeout=15)
    if rel.returncode != 0:
        return {"ok": False, "error": "systemctl daemon-reload falló"}
    res = run("systemctl", "--user", "enable", "--now", APPS_UNIT_NAME, timeout=15)
    if res.returncode != 0:
        return {"ok": False, "error": "no se pudo activar mgame-mixer-apps.service"}
    return {"ok": True, "unit": APPS_UNIT_NAME, "watch": apps_watch_state()}


def apps_watch_disable(args):
    if args:
        return {"ok": False, "error": "uso: apps-watch-disable"}
    res = run("systemctl", "--user", "disable", "--now", APPS_UNIT_NAME, timeout=15)
    if res.returncode != 0:
        return {"ok": False, "error": "no se pudo desactivar mgame-mixer-apps.service"}
    return {"ok": True, "unit": APPS_UNIT_NAME, "watch": apps_watch_state()}


def _unit_state(name, path):
    enabled = run("systemctl", "--user", "is-enabled", name).stdout.strip() == "enabled"
    active = run("systemctl", "--user", "is-active", name).stdout.strip() == "active"
    return {"enabled": enabled, "active": active, "installed": os.path.exists(path)}


def listener_state():
    return _unit_state(UNIT_NAME, UNIT_PATH)


def apps_watch_state():
    return _unit_state(APPS_UNIT_NAME, APPS_UNIT_PATH)


# ------------------------------- status ------------------------------------
def node_state(dev):
    vols = dev.get("volume") or {}
    pct = 0
    for ch in vols.values():
        pct = max(pct, int(round(ch.get("value", 0) / 65536 * 100)))
    return {"present": True, "volume": pct, "muted": bool(dev.get("mute"))}


def status(pairs):
    sinks = pactl_json("list", "sinks")
    sources = pactl_json("list", "sources")
    inputs = pactl_json("list", "sink-inputs")
    def_sink = pactl("get-default-sink").stdout.strip()
    def_source = pactl("get-default-source").stdout.strip()
    by_index = {s.get("index"): s.get("name", "") for s in sinks}
    absent = {"present": False, "volume": 0, "muted": False}

    def lookup(devs, key):
        match = next((d for d in devs if d.get("name") == NODE_NAMES[key]), None)
        return node_state(match) if match else dict(absent)

    out = {
        "outs": {k: lookup(sinks, k) for k in OUT_KEYS},
        "ins": {k: lookup(sources, k) for k in IN_KEYS},
        "mic": lookup(sources, "mic"),
        "defaultOut": next((k for k in OUT_KEYS if NODE_NAMES[k] == def_sink), ""),
        "defaultIn": next((k for k in IN_KEYS + ("mic",) if NODE_NAMES[k] == def_source), ""),
        "streams": [],
        "pairs": pairs,
        "installedPairs": installed_pairs(),
        "configExists": os.path.exists(SPLIT_CONF),
        "micConfExists": os.path.exists(MIC_CONF),
    }
    route_names = {NODE_NAMES[k]: k for k in OUT_KEYS}
    for si in inputs:
        props = si.get("properties") or {}
        node_name = props.get("node.name", "")
        if node_name.startswith("mgame_") or props.get("module-loopback.args") is not None:
            continue
        label = props.get("application.name") or props.get("media.name") or node_name or "?"
        route = route_names.get(by_index.get(si.get("sink"), ""), "other")
        out["streams"].append({"id": int(si["index"]), "name": str(label)[:80], "route": route})

    state = load_state()
    mic = state["mic"]
    eff = mic_params(state)
    out["micState"] = {"enabled": mic["enabled"], "preset": mic["preset"], "custom": bool(mic["overrides"]),
                       "vad": eff["vad"], "ratio": eff["ratio"], "presence": eff["presence"]}
    out["samples"] = list_samples()
    out["pads"] = state["pads"]
    out["padsConfigured"] = bool(pads_config()[1])
    out["listener"] = listener_state()
    # Sin listener activo el último estado guardado ya no es confiable: se muestra como desconocido.
    unknown = {name: None for name in MUTE_BUTTONS}
    unknown.update(page=None, bank=None)
    out["hw"] = read_hw() if out["listener"]["active"] else unknown
    out["activeSet"] = active_set() if out["listener"]["active"] else "1A"
    out["hwSetKnown"] = out["hw"]["page"] is not None or out["hw"]["bank"] is not None
    out["sampleDir"] = SAMPLE_DIR
    return out


# ------------------------- control del dispositivo (dev-*) ------------------
DEV_USAGE = {
    "dev-state": "dev-state [--refresh]",
    "dev-gain": "dev-gain DEST SRC 0..127",
    "dev-route": "dev-route DEST SRC on|off",
    "dev-routing-preset": "dev-routing-preset default|no_chat_to_stream",
    "dev-phantom": "dev-phantom on|off",
    "dev-led": "dev-led CONTROL ACTIVE IDLE [MODE]",
    "dev-led-presets": "dev-led-presets",
    "dev-led-preset": "dev-led-preset NAME",
    "dev-fx": "dev-fx",
    "dev-fx-presets": "dev-fx-presets",
    "dev-fx-preset": "dev-fx-preset voice|mic NAME",
}
WRITE_GAP = 0.03
WAIT_REPLIES = 2.0


def dev_port():
    import mgame_device
    port = find_rawmidi()
    if not port:
        raise mgame_device.DevError("no se encontró el rawmidi de la M-Game")
    return port


def dev_write(port, param, values, leds=None):
    import mgame_device
    amidi_send(port, mgame_device.checked_set(param, values, leds))


def route_memory():
    mem = load_json(STATE_PATH, {}).get("routeMemory")
    return mem if isinstance(mem, dict) else {}


def remember_gains(items):
    """items = [(dest, src, valor)] con valor > 0; se guarda en state.json['routeMemory']."""
    with mgame_lock.exclusive(STATE_PATH):
        st = load_json(STATE_PATH, {})  # recarga justo antes de escribir: no perder claves ajenas
        mem = st.get("routeMemory") if isinstance(st.get("routeMemory"), dict) else {}
        for dest, src, val in items:
            row = mem.get(dest) if isinstance(mem.get(dest), dict) else {}
            row[src] = val
            mem[dest] = row
        st["routeMemory"] = mem
        atomic_write(STATE_PATH, json.dumps(st, indent=2, ensure_ascii=False) + "\n")


def dev_state(refresh):
    import mgame_device
    if not refresh:
        return {"ok": True, **mgame_device.load_device_json()}
    cache = mgame_device.LedMapCache()
    cache.refresh()
    port = dev_port()
    frames = mgame_device.refresh_frames(cache.leds)
    if listener_state()["active"]:
        try:
            before = os.stat(mgame_device.DEVICE_PATH).st_mtime_ns
        except OSError:
            before = None
        amidi_send_batch_quiet(port, frames, GET_CHUNK, GET_PAUSE)
        deadline = time.monotonic() + WAIT_REPLIES
        seen, quiet_since = None, time.monotonic()
        while time.monotonic() < deadline:
            try:
                cur = os.stat(mgame_device.DEVICE_PATH).st_mtime_ns
            except OSError:
                cur = None
            if cur != seen:
                seen, quiet_since = cur, time.monotonic()
            elif cur != before and time.monotonic() - quiet_since > 0.4:
                break
            time.sleep(0.05)
        return {"ok": True, **mgame_device.load_device_json()}
    # sin listener el puerto está libre: leemos las respuestas directamente
    est = REFRESH_GAP * len(frames) + 3
    rx = subprocess.Popen(["amidi", "-p", port, "-d", "-t", "2"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.2)
    if rx.poll() is not None:
        raise mgame_device.DevError("amidi no pudo abrir el puerto para leer: " + (rx.stderr.read() or "").strip()[:200])
    amidi_send_batch_quiet(port, frames, GET_CHUNK, GET_PAUSE)
    try:
        out, _ = rx.communicate(timeout=est + 5)
    except subprocess.TimeoutExpired:
        rx.kill()
        out, _ = rx.communicate()
    import mgame_proto
    dev = mgame_device.DeviceState(cache.leds)
    dev.connected = True
    got = 0
    for fr in mgame_device.frames_from_dump(out):
        msg = mgame_proto.parse(fr)
        if msg is not None:
            dev.ingest(msg)
            got += 1
    if not got:
        raise mgame_device.DevError("la M-Game no respondió")
    dev.save(changed=True)
    return {"ok": True, **dev.to_dict()}


def dev_route(dest, src, mode):
    import mgame_device
    if mode not in ("on", "off"):
        raise mgame_device.DevError("modo: on u off")
    param, _ = mgame_device.build_gain(dest, src, "0")
    port = dev_port()
    if mode == "off":
        cur = mgame_device.load_device_json().get("gain", {}).get(dest, {}).get(src)
        dev_write(port, param, [0])
        if isinstance(cur, int) and 0 < cur <= 127:
            remember_gains([(dest, src, cur)])
        return {"ok": True, "dest": dest, "src": src, "value": 0, "remembered": cur if cur else None}
    mem = route_memory().get(dest, {})
    val = mem.get(src) if isinstance(mem, dict) else None
    if not isinstance(val, int) or isinstance(val, bool) or not 1 <= val <= 127:
        val = mgame_device.DEFAULT_GAIN
    dev_write(port, param, [val])
    return {"ok": True, "dest": dest, "src": src, "value": val}


def dev_main(cmd, args):
    """Ejecuta un dev-*; imprime un objeto JSON y devuelve el código de salida."""
    import mgame_device
    err = mgame_device.DevError
    try:
        res = dev_dispatch(cmd, args)
    except err as exc:
        res = {"ok": False, "error": str(exc)}
    except SystemExit as exc:
        if not isinstance(exc.code, str):
            raise
        res = {"ok": False, "error": exc.code}
    except Exception as exc:  # nunca un traceback hacia el panel
        res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
    print(json.dumps(res))
    return 0 if res.get("ok") else 1


def dev_dispatch(cmd, args):
    import mgame_device as md

    def usage():
        return md.DevError("uso: " + DEV_USAGE[cmd])

    if cmd == "dev-state":
        if args not in ([], ["--refresh"]):
            raise usage()
        return dev_state(bool(args))
    if cmd == "dev-gain":
        if len(args) != 3:
            raise usage()
        param, vals = md.build_gain(*args)
        dev_write(dev_port(), param, vals)
        return {"ok": True, "dest": args[0], "src": args[1], "value": vals[0], "param": md.hex8(param)}
    if cmd == "dev-route":
        if len(args) != 3:
            raise usage()
        return dev_route(*args)
    if cmd == "dev-routing-preset":
        if len(args) != 1:
            raise usage()
        items = md.load_routing_preset(args[0])
        port = dev_port()
        frames = [md.checked_set(param, [val]) for _, _, param, val in items]
        amidi_send_batch(port, frames)
        remember_gains([(d, s, v) for d, s, _, v in items if v > 0])
        return {"ok": True, "preset": args[0], "count": len(items)}
    if cmd == "dev-phantom":
        if len(args) != 1:
            raise usage()
        param, vals = md.build_phantom(args[0])
        dev_write(dev_port(), param, vals)
        return {"ok": True, "phantom": vals[0]}
    if cmd == "dev-led":
        if len(args) not in (3, 4):
            raise usage()
        leds = md.load_leds()
        active = md.int_arg(args[1], 0, 127, "active")
        idle = md.int_arg(args[2], 0, 127, "idle")
        if len(args) == 4:
            mode = md.int_arg(args[3], 0, 0xFFFFFFFF, "mode")
            if mode not in md.known_led_modes():
                raise md.DevError("mode no reconocido (solo los de data/led_presets)")
        else:
            cur = md.load_device_json().get("leds", {}).get(args[0], {}).get("mode")
            mode = cur if isinstance(cur, int) and not isinstance(cur, bool) else 0
        param, vals = md.build_led(args[0], active, idle, mode, leds)
        dev_write(dev_port(), param, vals, leds)
        return {"ok": True, "control": args[0], "param": md.hex8(param),
                "mode": vals[0], "active": vals[1], "idle": vals[2]}
    if cmd == "dev-led-presets":
        if args:
            raise usage()
        return {"ok": True, "presets": sorted(md.list_led_presets())}
    if cmd == "dev-led-preset":
        if len(args) != 1:
            raise usage()
        leds = md.load_leds()
        items, skipped = md.load_led_preset(args[0], leds)
        port = dev_port()
        frames = [md.checked_set(param, vals, leds) for _, param, vals in items]
        amidi_send_batch(port, frames)
        note_led_preset(args[0])
        return {"ok": True, "preset": args[0], "count": len(items), "skipped": skipped}
    if cmd in ("dev-fx", "dev-fx-presets", "dev-fx-preset"):
        return dev_fx(cmd, args)
    raise md.DevError("comando desconocido")


def dev_fx(cmd, args):
    """Lectura de FX. No abre el puerto y no arma tramas."""
    import mgame_device as md
    import mgame_fx

    if cmd == "dev-fx":
        if args:
            raise md.DevError("uso: dev-fx")
        return mgame_fx.fx_state(md.load_device_json())
    if cmd == "dev-fx-presets":
        if args:
            raise md.DevError("uso: dev-fx-presets")
        return mgame_fx.fx_presets()
    if len(args) != 2:
        raise md.DevError("uso: dev-fx-preset voice|mic NAME")
    return mgame_fx.fx_preset(args[0], args[1])


# ------------------------------- CLI ---------------------------------------
def key_arg(value, allowed=None):
    allowed = allowed or tuple(NODE_NAMES)
    if value not in allowed:
        raise SystemExit("canal inválido")
    return value


def num_arg(value, lo, hi):
    try:
        n = float(value)
    except ValueError:
        raise SystemExit("número inválido")
    return max(lo, min(hi, n))


APPS_PROFILE_CMDS = (
    "apps-rules", "apps-rule-set", "apps-rule-del", "apps-apply",
    "apps-watch", "apps-watch-enable", "apps-watch-disable",
    "profile-list", "profile-save", "profile-load", "profile-delete",
)


def json_exit(fn, args):
    try:
        res = fn(args)
    except mgame_lock.LockBusy:
        res = {"ok": False, "error": "busy"}
    except SystemExit as exc:
        if not isinstance(exc.code, str):
            raise
        res = {"ok": False, "error": exc.code}
    except Exception as exc:  # nunca un traceback hacia el panel
        res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
    if not isinstance(res, dict):
        res = {"ok": False, "error": "respuesta inválida"}
    print(json.dumps(res))
    return 0 if res.get("ok") else 1


def apps_rules(args):
    import mgame_apps
    res = mgame_apps.cmd_rules(args)
    if isinstance(res, dict) and res.get("ok"):
        res["watch"] = apps_watch_state()
    return res


def apps_profiles_main(cmd, args):
    # apps-watch no debe importar el módulo de perfiles (ese sí carga el dispositivo).
    if cmd == "apps-watch":
        import mgame_apps
        if args:
            print(json.dumps({"ok": False, "error": "uso: apps-watch"}))
            return 1
        mgame_apps.watch()
        return 1
    import mgame_apps
    import mgame_profiles
    table = {
        "apps-rules": apps_rules,
        "apps-rule-set": mgame_apps.cmd_rule_set,
        "apps-rule-del": mgame_apps.cmd_rule_del,
        "apps-apply": mgame_apps.cmd_apply,
        "apps-watch-enable": apps_watch_enable,
        "apps-watch-disable": apps_watch_disable,
        "profile-list": mgame_profiles.cmd_list,
        "profile-save": mgame_profiles.cmd_save,
        "profile-load": mgame_profiles.cmd_load,
        "profile-delete": mgame_profiles.cmd_delete,
    }
    fn = table.get(cmd)
    if fn is None:
        print(json.dumps({"ok": False, "error": "comando desconocido"}))
        return 1
    return json_exit(fn, args)


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    cmd, args = argv[1], argv[2:]
    if cmd.startswith("dev-"):
        if cmd not in DEV_USAGE:
            print(json.dumps({"ok": False, "error": "comando desconocido"}))
            raise SystemExit(1)
        raise SystemExit(dev_main(cmd, args))
    if cmd in APPS_PROFILE_CMDS:
        raise SystemExit(apps_profiles_main(cmd, args))

    def need(n):
        if len(args) < n:
            raise SystemExit(__doc__)

    if cmd == "status":
        print(json.dumps(status(parse_pairs(args[0] if args else ""))))
    elif cmd == "volume":
        need(2)
        key = key_arg(args[0])
        pct = int(num_arg(args[1], 0, 150))
        pactl(f"set-{KIND[key]}-volume", NODE_NAMES[key], f"{pct}%")
    elif cmd == "mute":
        need(1)
        key = key_arg(args[0])
        pactl(f"set-{KIND[key]}-mute", NODE_NAMES[key], "toggle")
    elif cmd == "default":
        need(1)
        key = key_arg(args[0])
        pactl(f"set-default-{KIND[key]}", NODE_NAMES[key])
    elif cmd == "move":
        need(2)
        pactl("move-sink-input", str(int(args[0])), NODE_NAMES[key_arg(args[1], OUT_KEYS)])
    elif cmd == "install":
        install(parse_pairs(args[0] if args else ""))
    elif cmd == "write-conf":
        write_confs(parse_pairs(args[0] if args else ""))
    elif cmd == "render":
        need(1)
        pairs = parse_pairs(args[1] if len(args) > 1 else "")
        atomic_write(os.path.join(args[0], "50-mgame-split.conf"),
                     render_split_conf(pairs, HW_OUT_FALLBACK, HW_IN_FALLBACK))
        atomic_write(os.path.join(args[0], "51-mgame-mic.conf"), render_mic_conf(mic_params(load_state())))
    elif cmd == "mic-preset":
        need(1)
        if args[0] not in PRESETS:
            raise SystemExit("preset inválido")
        state = load_state()
        if args[0] == "off":
            state["mic"]["enabled"] = False
        else:
            state["mic"].update(preset=args[0], enabled=True, overrides={})
        mic_commit(state)
    elif cmd == "mic-set":
        need(2)
        if args[0] not in OVERRIDE_RANGES:
            raise SystemExit("ajuste inválido")
        lo, hi = OVERRIDE_RANGES[args[0]]
        state = load_state()
        val = num_arg(args[1], lo, hi)
        state["mic"]["overrides"][args[0]] = int(val) if args[0] == "vad" else round(val, 1)
        mic_commit(state)
    elif cmd == "mic-enable":
        need(1)
        if args[0] not in ("on", "off"):
            raise SystemExit("on u off")
        state = load_state()
        state["mic"]["enabled"] = args[0] == "on"
        mic_commit(state)
    elif cmd == "ensure-dirs":
        ensure_dirs()
    elif cmd == "sample-assign":
        need(2)
        pad = pad_arg(args[0])
        sample_path(args[1])
        set_name = set_arg(args[2]) if len(args) > 2 else active_set()
        state = load_state()
        state["pads"][set_name][pad] = args[1]
        save_state(state)
    elif cmd == "sample-clear":
        need(1)
        pad = pad_arg(args[0])
        set_name = set_arg(args[1]) if len(args) > 1 else active_set()
        state = load_state()
        state["pads"][set_name].pop(pad, None)
        save_state(state)
    elif cmd == "sample-play":
        need(1)
        play_pad(pad_arg(args[0]), set_arg(args[1]) if len(args) > 1 else None)
    elif cmd == "sample-preview":
        need(1)
        play_file(sample_path(args[0]), "preview")
    elif cmd == "sample-stop":
        stop_samples()
    elif cmd == "listen":
        listen()
    elif cmd == "decode":
        need(1)
        cmd_decode(" ".join(args))
    elif cmd == "send-raw":
        need(1)
        cmd_send_raw(" ".join(args))
    elif cmd == "get":
        need(1)
        sub, timeout, rest = 0, 2.0, list(args[1:])
        while rest:
            flag = rest.pop(0)
            if flag in ("--sub", "--timeout") and rest:
                val = rest.pop(0)
                try:
                    if flag == "--sub":
                        sub = int(val)
                    else:
                        timeout = max(1.0, min(30.0, float(val)))
                except ValueError:
                    raise SystemExit("número inválido")
            else:
                raise SystemExit(__doc__)
        cmd_get(args[0], sub, timeout)
    elif cmd == "listener-enable":
        listener_enable()
    elif cmd == "listener-disable":
        listener_disable()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
