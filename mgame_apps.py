"""Reglas de enrutado y planificación del watcher de apps.

No importa el módulo del dispositivo y no llama a amidi. El watcher solo habla
con pactl. Si pactl subscribe muere, el proceso sale con código distinto de
cero: el reinicio lo hace systemd (Restart=on-failure, RestartSec=2), no un
sleep acá adentro.
"""
import json
import os
import re
import subprocess
import sys

import mgame_lock

FIELDS = ("binary", "name", "both")
SINKS = ("game", "chat", "sampler", "system")
# Mismos node.name que mgame.NODE_NAMES. El watcher no importa mgame: ese import
# arrastraría el módulo del dispositivo.
SINK_NODES = {
    "game": "mgame_game", "chat": "mgame_chat",
    "sampler": "mgame_sampler", "system": "mgame_system",
}
MATCH_MAX = 80
SUBSCRIBE_ARGV = ["stdbuf", "-oL", "pactl", "subscribe"]
_EVENT = re.compile(r"^Event '([a-z]+)' on ([a-z0-9-]+) #(\d+)\s*$")
_SKIP_NODE_PREFIXES = ("mgame_", "pw-play")


def _host():
    """mgame ya cargado (tests, panel). El servicio apps-watch no lo importa."""
    return sys.modules.get("mgame")


def rules_path():
    host = _host()
    cfg = host.CFG_DIR if host is not None else os.path.join(os.path.expanduser("~"), ".config", "mgame-mixer")
    return os.path.join(cfg, "app-rules.json")


def _control(text):
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in text)


def validate_match(match):
    """1..80 caracteres tras strip, sin controles. Vacío se rechaza: matchearía todo."""
    if not isinstance(match, str):
        raise ValueError("match inválido")
    match = match.strip()
    if not match or len(match) > MATCH_MAX or _control(match):
        raise ValueError("match inválido")
    return match


def validate_rule(rule):
    if not isinstance(rule, dict) or set(rule) != {"match", "field", "sink"}:
        raise ValueError("regla inválida")
    field, sink = rule.get("field"), rule.get("sink")
    if field not in FIELDS:
        raise ValueError("field inválido")
    if sink not in SINKS:
        raise ValueError("sink inválido")
    return {"match": validate_match(rule.get("match")), "field": field, "sink": sink}


def validate_rules(data):
    if not isinstance(data, dict) or set(data) != {"rules"} or not isinstance(data.get("rules"), list):
        raise ValueError("app-rules.json inválido")
    return [validate_rule(rule) for rule in data["rules"]]


def _basename(props):
    binary = props.get("application.process.binary") or ""
    if not isinstance(binary, str):
        return ""
    return os.path.basename(binary)


def skipped_props(props):
    """Antes de matchear: un node mgame_* o pw-play no entra a las reglas.

    Así una regla "pw" no se lleva el sampler (pw-play). También se salta si el
    binario es pw-play, por si el node.name no trae ese prefijo.
    """
    if not isinstance(props, dict):
        return True
    node = props.get("node.name") or ""
    if not isinstance(node, str):
        node = str(node)
    if node.startswith(_SKIP_NODE_PREFIXES):
        return True
    return _basename(props) == "pw-play" or node == "pw-play"


def _haystack(props, field):
    base = _basename(props)
    name = props.get("application.name") or ""
    if not isinstance(name, str):
        name = ""
    if field == "binary":
        return (base,)
    if field == "name":
        return (name,)
    return (base, name)


def rule_matches(rule, props):
    needle = rule["match"].casefold()
    return any(needle in hay.casefold() for hay in _haystack(props, rule["field"]))


def first_sink(rules, props):
    """Primer match, o None. No mira streams que hay que saltear."""
    if skipped_props(props):
        return None
    for rule in rules:
        if rule_matches(rule, props):
            return rule["sink"]
    return None


def _sink_name(si, by_index):
    sink = si.get("sink")
    if isinstance(sink, dict):
        return sink.get("name") or ""
    if isinstance(sink, str) and not sink.isdigit():
        return sink
    return by_index.get(sink, "")


def _node_name(sink):
    host = _host()
    if host is not None:
        return host.NODE_NAMES[sink]
    return SINK_NODES[sink]


class Watcher:
    """Plan: pase completo, o Event 'new' en sink-input. 'change' no mueve nada.

    Un move fallido queda cacheado por id hasta el Event 'remove'. No se reintenta
    en cada evento.
    """

    def __init__(self, rules):
        self.rules = [dict(rule) for rule in rules]
        self.failed = set()

    def set_rules(self, rules):
        self.rules = [dict(rule) for rule in rules]

    def note_failure(self, sid):
        self.failed.add(int(sid))

    def consider(self, inputs, sinks, only_id=None):
        by_index = {item.get("index"): item.get("name", "") for item in sinks or []}
        moves = []
        for si in inputs or []:
            sid = si.get("index")
            if isinstance(sid, bool) or not isinstance(sid, int):
                continue
            if only_id is not None and sid != only_id:
                continue
            if sid in self.failed:
                continue
            props = si.get("properties") or {}
            sink = first_sink(self.rules, props)
            if sink is None:
                continue
            if _sink_name(si, by_index) == _node_name(sink):
                continue
            moves.append((sid, sink))
        return moves

    def full_pass(self, inputs, sinks):
        return self.consider(inputs, sinks, only_id=None)

    def on_line(self, line, inputs, sinks):
        parsed = parse_event(line)
        if parsed is None:
            return []
        kind, obj, idx = parsed
        if obj != "sink-input":
            return []
        if kind == "remove":
            self.failed.discard(idx)
            return []
        if kind != "new":
            return []
        return self.consider(inputs, sinks, only_id=idx)


def parse_event(line):
    if not isinstance(line, str):
        return None
    match = _EVENT.match(line.strip())
    if not match:
        return None
    return match.group(1), match.group(2), int(match.group(3))


class RulesState:
    """Carga de reglas para el watcher.

    Archivo ausente: sin reglas, y se loguea una sola vez.
    JSON o validación rotos: se conservan las últimas reglas buenas y se loguea.
    Nunca se pasa en silencio a "sin reglas" si ya había una lista válida.
    """

    def __init__(self, path=None):
        self.path = path
        self.rules = []
        self.had_good = False
        self._missing_logged = False
        self._last_err = None

    def load(self):
        path = self.path or rules_path()
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
        except FileNotFoundError:
            if not self._missing_logged:
                print("app-rules.json no existe: sin reglas", file=sys.stderr)
                self._missing_logged = True
            self.rules = []
            self.had_good = False
            self._last_err = None
            return [], None
        except OSError as exc:
            return self._invalid(f"app-rules.json ilegible: {exc}")
        try:
            cleaned = validate_rules(json.loads(raw))
        except ValueError as exc:
            return self._invalid(f"app-rules.json inválido: {exc}")
        self.rules = cleaned
        self.had_good = True
        self._missing_logged = False
        self._last_err = None
        return [dict(rule) for rule in cleaned], None

    def _invalid(self, msg):
        if msg != self._last_err:
            print(msg, file=sys.stderr)
            self._last_err = msg
        if self.had_good:
            return [dict(rule) for rule in self.rules], msg
        self.rules = []
        return [], msg


def _read_rules(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return [], None
    except (OSError, ValueError) as exc:
        return None, f"app-rules.json inválido: {exc}"
    try:
        return validate_rules(data), None
    except ValueError as exc:
        return None, str(exc)


def _write_rules_file(path, rules):
    host = _host()
    if host is None:
        import mgame as host  # no es el watcher: hace falta atomic_write
    text = json.dumps({"rules": rules}, indent=2, ensure_ascii=False) + "\n"
    host.atomic_write(path, text)


def read_rules(path=None):
    """Lectura de un comando (no del watcher): un archivo inválido es error, no lista vacía."""
    return _read_rules(path or rules_path())


def replace_rules(rules, path=None):
    path = path or rules_path()
    cleaned = validate_rules({"rules": rules})
    with mgame_lock.exclusive(path):
        _write_rules_file(path, cleaned)
    return cleaned


def update_rules(mutator, path=None):
    """Lee, modifica y reemplaza en atómico bajo el lock. No pisa un archivo inválido."""
    path = path or rules_path()
    with mgame_lock.exclusive(path):
        current, err = _read_rules(path)
        if err:
            return None, err
        try:
            updated = mutator(current)
            cleaned = validate_rules({"rules": updated})
        except ValueError as exc:
            return None, str(exc)
        _write_rules_file(path, cleaned)
    return cleaned, None


def cmd_rules(args):
    if args:
        return {"ok": False, "error": "uso: apps-rules"}
    rules, err = read_rules()
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "rules": rules}


def cmd_rule_set(args):
    if len(args) != 3:
        return {"ok": False, "error": "uso: apps-rule-set MATCH FIELD SINK"}
    try:
        rule = validate_rule({"match": args[0], "field": args[1], "sink": args[2]})
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    def mutate(current):
        kept = [item for item in current if not (item["match"] == rule["match"] and item["field"] == rule["field"])]
        kept.append(rule)
        return kept

    rules, err = update_rules(mutate)
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "rule": rule, "rules": rules}


def cmd_rule_del(args):
    if len(args) != 2:
        return {"ok": False, "error": "uso: apps-rule-del MATCH FIELD"}
    try:
        match = validate_match(args[0])
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if args[1] not in FIELDS:
        return {"ok": False, "error": "field inválido"}

    found = {"ok": False}

    def mutate(current):
        kept = []
        for item in current:
            if item["match"] == match and item["field"] == args[1]:
                found["ok"] = True
                continue
            kept.append(item)
        if not found["ok"]:
            raise ValueError("regla inexistente")
        return kept

    rules, err = update_rules(mutate)
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "rules": rules}


def pactl(*args):
    host = _host()
    if host is not None:
        return host.pactl(*args)
    return subprocess.run(("pactl",) + tuple(args), capture_output=True, text=True, timeout=5)


def pactl_json(*args):
    host = _host()
    if host is not None:
        return host.pactl_json(*args)
    res = pactl("--format=json", *args)
    try:
        data = json.loads(res.stdout) if res.returncode == 0 else []
    except (ValueError, AttributeError):
        return []
    return data


def list_inputs_and_sinks():
    inputs = pactl_json("list", "sink-inputs")
    sinks = pactl_json("list", "sinks")
    return inputs if isinstance(inputs, list) else [], sinks if isinstance(sinks, list) else []


def move_stream(sid, sink):
    """Mismo argv que `move`: pactl move-sink-input ID mgame_<sink>. Sin shell."""
    if sink not in SINK_NODES:
        return False
    try:
        res = pactl("move-sink-input", str(int(sid)), _node_name(sink))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False
    return res.returncode == 0


def apply_moves(moves, watcher=None):
    moved, failed = [], []
    for sid, sink in moves:
        if move_stream(sid, sink):
            moved.append({"id": sid, "sink": sink})
        else:
            failed.append({"id": sid, "sink": sink})
            if watcher is not None:
                watcher.note_failure(sid)
            print(f"no se pudo mover el sink-input {sid} a {sink}", file=sys.stderr)
    return moved, failed


def cmd_apply(args):
    """Un pase completo, un move por vez. No toma lock contra el watcher."""
    if args:
        return {"ok": False, "error": "uso: apps-apply"}
    rules, err = read_rules()
    if err:
        return {"ok": False, "error": err}
    inputs, sinks = list_inputs_and_sinks()
    moves = Watcher(rules).full_pass(inputs, sinks)
    moved, failed = apply_moves(moves)
    res = {"ok": not failed, "moved": moved, "failed": failed}
    if failed:
        res["error"] = "algunos movimientos fallaron"
    return res


def _run_watch(lines, state, graph):
    """Un pase al arrancar y después solo Event 'new'. Sin sleep."""
    rules, _err = state.load()
    watcher = Watcher(rules)
    inputs, sinks = graph()
    apply_moves(watcher.full_pass(inputs, sinks), watcher)
    for line in lines:
        parsed = parse_event(line)
        if parsed is None or parsed[1] != "sink-input":
            continue
        kind, _obj, idx = parsed
        if kind == "remove":
            watcher.failed.discard(idx)
            continue
        if kind != "new":
            continue
        rules, _err = state.load()
        watcher.set_rules(rules)
        inputs, sinks = graph()
        apply_moves(watcher.consider(inputs, sinks, only_id=idx), watcher)
    return watcher


def watch():
    """Largo. No es para el panel. Sale distinto de cero si pactl muere. No reintenta."""
    try:
        proc = subprocess.Popen(SUBSCRIBE_ARGV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, bufsize=1)
    except OSError as exc:
        print(f"no se pudo arrancar pactl: {exc}", file=sys.stderr)
        print(json.dumps({"ok": False, "error": "pactl no arrancó"}))
        raise SystemExit(1)
    code = 1
    try:
        if proc.stdout is None:
            raise SystemExit(1)
        _run_watch(proc.stdout, RulesState(), list_inputs_and_sinks)
    finally:
        if proc.poll() is None:
            proc.kill()
        code = proc.wait()
    raise SystemExit(code if code else 1)
