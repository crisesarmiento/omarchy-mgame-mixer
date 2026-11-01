#!/usr/bin/env python3
"""Helper del plugin M-Game Mixer.

Todo se invoca con argv (nunca por shell) y los valores se validan contra
listas cerradas, así que ningún texto externo termina interpretado como comando.

  mgame.py status [PAR]            JSON con el estado de los sinks y las apps
  mgame.py volume game|chat PCT    volumen 0-150
  mgame.py mute game|chat          alterna mute
  mgame.py default game|chat       lo deja como salida por defecto
  mgame.py move ID game|chat       mueve una app (sink-input) a Game o Chat
  mgame.py install PAR             escribe la config y reinicia PipeWire
"""
import json
import os
import re
import subprocess
import sys

SINKS = {"game": "mgame_game", "chat": "mgame_chat"}
PAIRS = ("FC LFE", "RL RR", "SL SR")
DEFAULT_PAIR = "FC LFE"
FALLBACK_TARGET = "alsa_output.usb-M-Audio_M-Game_RGB_Dual_Streaming_Port-01.analog-surround-71"
CONF_NAME = "50-mgame-split.conf"
CONF_DIR = os.path.join(os.path.expanduser("~"), ".config", "pipewire", "pipewire.conf.d")
CONF_PATH = os.path.join(CONF_DIR, CONF_NAME)


def pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5)


def pactl_json(*args):
    try:
        out = pactl("--format=json", *args)
        return json.loads(out.stdout) if out.returncode == 0 else []
    except Exception:
        return []


def find_target(sinks):
    for s in sinks:
        name = s.get("name", "")
        if name.startswith("alsa_output.usb-M-Audio_M-Game"):
            return name
    return FALLBACK_TARGET


def render_conf(pair, target):
    if pair not in PAIRS:
        raise ValueError("par de canales inválido")
    return f"""# M-Audio M-Game RGB Dual: divide la salida USB de 8 canales en sinks estéreo virtuales.
# Generado por el plugin csarmiento.mgame-mixer (par de Chat: {pair}).
context.modules = [
  {{ name = libpipewire-module-loopback
    args = {{
      node.description = "M-Game Game"
      capture.props  = {{ node.name = "mgame_game"  media.class = "Audio/Sink" audio.position = [ FL FR ] }}
      playback.props = {{ node.name = "mgame_game.out" audio.position = [ FL FR ]
                         target.object = "{target}"
                         stream.dont-remix = true node.passive = true }}
    }}
  }}
  {{ name = libpipewire-module-loopback
    args = {{
      node.description = "M-Game Chat"
      capture.props  = {{ node.name = "mgame_chat"  media.class = "Audio/Sink" audio.position = [ FL FR ] }}
      playback.props = {{ node.name = "mgame_chat.out" audio.position = [ {pair} ]
                         target.object = "{target}"
                         stream.dont-remix = true node.passive = true }}
    }}
  }}
]
"""


def installed_pair():
    try:
        with open(CONF_PATH, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return ""
    m = re.search(r'mgame_chat\.out"\s+audio\.position\s*=\s*\[\s*([A-Z]+\s+[A-Z]+)\s*\]', text)
    return re.sub(r"\s+", " ", m.group(1)) if m else ""


def sink_state(sink):
    vols = sink.get("volume") or {}
    pct = 0
    for ch in vols.values():
        pct = max(pct, int(round(ch.get("value", 0) / 65536 * 100)))
    return {"present": True, "volume": pct, "muted": bool(sink.get("mute"))}


def status(wanted_pair):
    sinks = pactl_json("list", "sinks")
    inputs = pactl_json("list", "sink-inputs")
    default = pactl("get-default-sink").stdout.strip()
    by_index = {s.get("index"): s.get("name", "") for s in sinks}
    out = {"sinks": {}, "default": "", "streams": [], "installedPair": installed_pair(),
           "wantedPair": wanted_pair, "configExists": os.path.exists(CONF_PATH)}
    for key, name in SINKS.items():
        match = next((s for s in sinks if s.get("name") == name), None)
        out["sinks"][key] = sink_state(match) if match else {"present": False, "volume": 0, "muted": False}
    for key, name in SINKS.items():
        if default == name:
            out["default"] = key
    for si in inputs:
        props = si.get("properties") or {}
        node_name = props.get("node.name", "")
        if node_name.startswith("mgame_") or props.get("module-loopback.args") is not None:
            continue
        label = props.get("application.name") or props.get("media.name") or node_name or "?"
        target = by_index.get(si.get("sink"), "")
        route = next((k for k, n in SINKS.items() if n == target), "other")
        out["streams"].append({"id": int(si["index"]), "name": str(label)[:80], "route": route})
    return out


def sink_arg(value):
    if value not in SINKS:
        raise SystemExit("sink inválido")
    return SINKS[value]


def install(pair):
    if pair not in PAIRS:
        raise SystemExit("par inválido")
    target = find_target(pactl_json("list", "sinks"))
    os.makedirs(CONF_DIR, exist_ok=True)
    tmp = CONF_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(render_conf(pair, target))
    os.replace(tmp, CONF_PATH)
    subprocess.run(["systemctl", "--user", "restart", "pipewire", "pipewire-pulse", "wireplumber"], timeout=30)


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    cmd, args = argv[1], argv[2:]
    if cmd == "status":
        pair = args[0] if args and args[0] in PAIRS else DEFAULT_PAIR
        print(json.dumps(status(pair)))
    elif cmd == "volume" and len(args) == 2:
        pct = max(0, min(150, int(args[1])))
        pactl("set-sink-volume", sink_arg(args[0]), f"{pct}%")
    elif cmd == "mute" and len(args) == 1:
        pactl("set-sink-mute", sink_arg(args[0]), "toggle")
    elif cmd == "default" and len(args) == 1:
        pactl("set-default-sink", sink_arg(args[0]))
    elif cmd == "move" and len(args) == 2:
        pactl("move-sink-input", str(int(args[0])), sink_arg(args[1]))
    elif cmd == "install" and len(args) == 1:
        install(args[0])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
