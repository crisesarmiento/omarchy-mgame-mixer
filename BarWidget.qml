import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// Ícono de headset en la barra. Toda la lógica de audio vive acá; Panel.qml
// solo dibuja. El estado sale de `mgame.py status` (pactl), no del modelo de
// PipeWire de Quickshell, para no tocar nodos que PipeWire puede borrar en
// pleno reinicio de audio. Cada acción es un argv: nada se arma como texto de shell.
BarWidget {
  id: root
  moduleName: "csarmiento.mgame-mixer"

  Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

  readonly property string helperPath: Qt.resolvedUrl("mgame.py").toString().replace(/^file:\/\//, "")

  readonly property var outKeys: ["game", "chat", "sampler", "system"]
  readonly property var inKeys: ["in_stream", "in_alt", "in_chat", "in_sampler"]
  readonly property var validPairs: ["FL FR", "FC LFE", "RL RR", "SL SR"]

  // Par de canales de cada canal; salen de la configuración del widget.
  function pairSetting(name, fallback) {
    var p = String(setting(name, fallback))
    return validPairs.indexOf(p) >= 0 ? p : fallback
  }
  readonly property var wantedPairs: ({
    game: pairSetting("outGame", "FL FR"),
    chat: pairSetting("outChat", "FC LFE"),
    sampler: pairSetting("outSampler", "RL RR"),
    system: pairSetting("outSystem", "SL SR"),
    in_stream: pairSetting("inStream", "FL FR"),
    in_alt: pairSetting("inAlt", "FC LFE"),
    in_chat: pairSetting("inChat", "RL RR"),
    in_sampler: pairSetting("inSampler", "SL SR")
  })
  readonly property string pairsArg: {
    var keys = outKeys.concat(inKeys)
    var list = []
    for (var i = 0; i < keys.length; i++) list.push(wantedPairs[keys[i]])
    return list.join(",")
  }

  function emptyNode() { return { present: false, volume: 0, muted: false } }
  property var mixer: ({
    outs: { game: emptyNode(), chat: emptyNode(), sampler: emptyNode(), system: emptyNode() },
    ins: { in_stream: emptyNode(), in_alt: emptyNode(), in_chat: emptyNode(), in_sampler: emptyNode() },
    mic: emptyNode(), defaultOut: "", defaultIn: "", streams: [],
    pairs: {}, installedPairs: {}, configExists: false, micConfExists: false,
    micState: { enabled: true, preset: "natural", custom: false, vad: 50, ratio: 2, presence: 2 },
    samples: [], pads: { "1A": {}, "1B": {}, "2A": {}, "2B": {} }, padsConfigured: false, sampleDir: "",
    hw: { mic_mute: null, game_mute: null, chat_mute: null, sampler_mute: null, main_alt_mute: null, page: null, bank: null },
    activeSet: "1A", hwSetKnown: false,
    listener: { enabled: false, active: false, installed: false }
  })
  property bool busy: false

  readonly property bool splitReady: {
    for (var i = 0; i < outKeys.length; i++) if (!mixer.outs[outKeys[i]].present) return false
    for (var j = 0; j < inKeys.length; j++) if (!mixer.ins[inKeys[j]].present) return false
    return true
  }
  readonly property bool micReady: !!mixer.mic.present
  readonly property bool pairMismatch: {
    var inst = mixer.installedPairs || {}
    var keys = outKeys.concat(inKeys)
    for (var i = 0; i < keys.length; i++) if (inst[keys[i]] !== wantedPairs[keys[i]]) return true
    return false
  }
  // Falta algo: algún sink/fuente, la cadena del mic, o los pares elegidos no coinciden con lo instalado.
  readonly property bool needsSetup: !splitReady || !micReady || pairMismatch
  readonly property bool pairOnly: splitReady && micReady && pairMismatch

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  // Headset (Nerd Font)
  readonly property string icon: "󰋎"

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  function ingest(text) {
    var raw = String(text || "").trim()
    if (!raw) return
    try {
      var parsed = JSON.parse(raw)
      if (parsed && parsed.outs && parsed.ins && parsed.mic) root.mixer = parsed
    } catch (e) {}
  }

  function refresh() {
    if (statusProc.running) return
    statusProc.command = ["python3", root.helperPath, "status", root.pairsArg]
    statusProc.running = true
  }

  function settleRefresh() { settleTimer.restart() }

  function run(args) {
    Quickshell.execDetached(["python3", root.helperPath].concat(args))
    settleRefresh()
  }

  function clone(obj) { return JSON.parse(JSON.stringify(obj)) }

  function nodeGroup(next, key) {
    if (key === "mic") return null
    return next.outs[key] ? next.outs : next.ins
  }

  function patchNode(key, fields) {
    var next = clone(root.mixer)
    var target = key === "mic" ? next.mic : nodeGroup(next, key)[key]
    for (var f in fields) target[f] = fields[f]
    root.mixer = next
  }

  // Los sliders mandan muchos valores por segundo; se juntan y se envía el último.
  property var pendingVolume: ({})
  function setVolume(key, fraction) {
    var pct = Math.round(Math.max(0, Math.min(1, fraction)) * 100)
    pendingVolume[key] = pct
    patchNode(key, { volume: pct })
    volumeTimer.restart()
  }

  function toggleMute(key) {
    var node = key === "mic" ? root.mixer.mic : nodeGroup(root.mixer, key)[key]
    patchNode(key, { muted: !node.muted })
    run(["mute", key])
  }

  function setDefault(key) {
    var next = clone(root.mixer)
    if (outKeys.indexOf(key) >= 0) next.defaultOut = key
    else next.defaultIn = key
    root.mixer = next
    run(["default", key])
  }

  function moveStream(id, key) {
    var next = clone(root.mixer)
    for (var i = 0; i < next.streams.length; i++)
      if (next.streams[i].id === id) next.streams[i].route = key
    root.mixer = next
    run(["move", String(Math.floor(Number(id))), key])
  }

  function installConfig() {
    if (root.busy) return
    root.busy = true
    installProc.command = ["python3", root.helperPath, "install", root.pairsArg]
    installProc.running = true
  }

  // ---- Micrófono ----
  function patchMic(fields) {
    var next = clone(root.mixer)
    for (var f in fields) next.micState[f] = fields[f]
    root.mixer = next
  }

  function micPreset(name) {
    if (name === "off") patchMic({ enabled: false })
    else patchMic({ enabled: true, preset: name, custom: false })
    run(["mic-preset", name])
  }

  function micEnable(on) {
    patchMic({ enabled: on })
    run(["mic-enable", on ? "on" : "off"])
  }

  property var pendingMic: ({})
  function micSet(key, value) {
    var fields = { custom: true }
    fields[key] = value
    patchMic(fields)
    pendingMic[key] = value
    micTimer.restart()
  }

  // ---- Sampler ----
  function samplePlay(pad, set) { run(["sample-play", String(pad), String(set)]) }
  function samplePreview(file) { run(["sample-preview", String(file)]) }
  function sampleStop() { run(["sample-stop"]) }
  function sampleClear(pad, set) {
    var next = clone(root.mixer)
    if (next.pads[set]) delete next.pads[set][String(pad)]
    root.mixer = next
    run(["sample-clear", String(pad), String(set)])
  }
  function sampleAssign(pad, file, set) {
    var next = clone(root.mixer)
    if (!next.pads[set]) next.pads[set] = {}
    next.pads[set][String(pad)] = String(file)
    root.mixer = next
    run(["sample-assign", String(pad), String(file), String(set)])
  }
  // El listener de los pads físicos corre como servicio systemd --user.
  function setListener(on) {
    var next = clone(root.mixer)
    next.listener.enabled = on
    next.listener.active = on
    root.mixer = next
    run([on ? "listener-enable" : "listener-disable"])
    settleTimer.interval = 1200
    settleTimer.restart()
  }

  // ---- Equipo (SysEx): lee device.json vía `dev-state` y escribe con `dev-*` ----
  // Todo es opcional: si el helper no responde, devOk queda en false y el panel
  // muestra "equipo no disponible" en vez de fallar.
  property var dev: null
  property bool devOk: false
  property string devError: ""
  property bool devRefreshing: false
  property double devHoldUntil: 0
  property var ledData: null
  property var ledPresets: []
  readonly property string ledFilePath: Qt.resolvedUrl("data/leds.json").toString().replace(/^file:\/\//, "")

  function ingestDev(text) {
    if (Date.now() < root.devHoldUntil) return
    var raw = String(text || "").trim()
    var parsed = null
    try { parsed = JSON.parse(raw) } catch (e) {}
    if (!parsed || typeof parsed !== "object") {
      root.devOk = false
      root.devError = ""
      return
    }
    if (parsed.ok === false) {
      root.devOk = false
      root.devError = String(parsed.error || "")
      return
    }
    root.dev = parsed
    root.devOk = true
    root.devError = ""
  }

  function refreshDev() {
    if (devProc.running) return
    devProc.command = ["python3", root.helperPath, "dev-state"]
    devProc.running = true
  }

  // Pide los valores al equipo (tarda hasta 2 s).
  function devRefreshFromDevice() {
    if (devForceProc.running) return
    root.devRefreshing = true
    devForceProc.command = ["python3", root.helperPath, "dev-state", "--refresh"]
    devForceProc.running = true
  }

  function loadDevStatic() {
    if (!ledFileProc.running && !root.ledData) {
      ledFileProc.command = ["cat", root.ledFilePath]
      ledFileProc.running = true
    }
    if (!presetsProc.running && root.ledPresets.length === 0) {
      presetsProc.command = ["python3", root.helperPath, "dev-led-presets"]
      presetsProc.running = true
    }
  }

  // Cola serializada de escrituras: un solo proceso a la vez, en orden.
  // Las mutaciones nuevas (apps, perfiles) van en la misma cola que `dev-*`,
  // con tag distinto, para que un profile-load no pise un dev-gain. Un error
  // de apps o perfiles no marca el equipo como caído.
  property var devQueue: []
  property bool devWriting: false
  property bool devWriteOutDone: false
  property bool devWriteExitDone: false
  property string devWriteText: ""
  property int devWriteCode: 0
  property string devWriteTag: "dev"
  property var devWriteArgs: []

  function holdDev(ms) {
    root.devHoldUntil = Math.max(root.devHoldUntil, Date.now() + ms)
  }

  function devQueueKey(args) {
    return args[0] === "dev-gain" ? "gain:" + args[1] + ":" + args[2] : ""
  }

  function devRun(args, tag) {
    holdDev(700)
    var q = root.devQueue
    var key = devQueueKey(args)
    var itemTag = tag || "dev"
    if (key !== "") {
      for (var i = 0; i < q.length; i++) {
        if (q[i].key === key) { q[i].args = args; q[i].tag = itemTag; pumpDev(); return }
      }
    } else if (q.length > 0 && q[q.length - 1].key === ""
               && JSON.stringify(q[q.length - 1].args) === JSON.stringify(args)) {
      pumpDev()
      return
    }
    q.push({ key: key, args: args, tag: itemTag })
    pumpDev()
  }

  // Descarta ganancias pendientes de un destino/origen (p. ej. antes de un toggle).
  function dropQueuedGain(dest, src) {
    var key = "gain:" + dest + ":" + src
    root.devQueue = root.devQueue.filter(function(e) { return e.key !== key })
  }

  function pumpDev() {
    if (root.devWriting) return
    if (root.devQueue.length === 0) return
    var next = root.devQueue.shift()
    root.devWriting = true
    root.devWriteOutDone = false
    root.devWriteExitDone = false
    root.devWriteText = ""
    root.devWriteCode = 0
    root.devWriteTag = next.tag || "dev"
    root.devWriteArgs = next.args || []
    root.devHoldUntil = Date.now() + 600000
    devWriteProc.command = ["python3", root.helperPath].concat(next.args)
    devWriteProc.running = true
  }

  function finishDevWrite() {
    if (!root.devWriteOutDone || !root.devWriteExitDone) return
    var err = ""
    var raw = String(root.devWriteText || "").trim()
    var parsed = null
    try { parsed = JSON.parse(raw) } catch (e) {}
    var tag = root.devWriteTag || "dev"
    if (tag === "dev") {
      if (!parsed || typeof parsed !== "object") {
        err = root.devWriteCode !== 0 ? "dev write failed (exit " + root.devWriteCode + ")" : "dev write: unparsable output"
      } else if (parsed.ok === false) {
        err = String(parsed.error || "dev write failed")
      } else if (root.devWriteCode !== 0) {
        err = "dev write failed (exit " + root.devWriteCode + ")"
      }
      if (err !== "") {
        root.devOk = false
        root.devError = err
      }
    } else {
      var fallback = tag === "apps" ? strings.t("apps.unavailable") : strings.t("profiles.unavailable")
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) err = fallback
      else if (parsed.ok === false) err = String(parsed.error || fallback)
      else if (parsed.ok !== true || root.devWriteCode !== 0) err = fallback
      root.finishExtra(tag, parsed, err, root.devWriteArgs)
    }
    root.devWriting = false
    if (root.devQueue.length > 0) {
      pumpDev()
    } else {
      root.devHoldUntil = Date.now() + 700
      devSettleTimer.restart()
    }
  }

  function patchDev(fn) {
    if (!root.dev) return
    var next = clone(root.dev)
    fn(next)
    root.dev = next
  }

  function gainOf(dest, src) {
    var g = root.dev && root.dev.gain && root.dev.gain[dest] ? root.dev.gain[dest][src] : null
    return typeof g === "number" ? g : -1
  }

  property var pendingGain: ({})
  property var lastGain: ({})

  function setGain(dest, src, value) {
    var v = Math.round(Math.max(0, Math.min(127, value)))
    patchDev(function(d) {
      if (!d.gain) d.gain = {}
      if (!d.gain[dest]) d.gain[dest] = {}
      d.gain[dest][src] = v
    })
    holdDev(700)
    pendingGain[dest + ":" + src] = v
    gainTimer.restart()
  }

  function toggleRoute(dest, src) {
    var key = dest + ":" + src
    var cur = gainOf(dest, src)
    if (cur < 0) return
    delete pendingGain[key]
    dropQueuedGain(dest, src)
    if (cur > 0) {
      lastGain[key] = cur
      patchDev(function(d) { d.gain[dest][src] = 0 })
      devRun(["dev-route", dest, src, "off"])
    } else {
      var back = lastGain[key] || 115
      patchDev(function(d) { d.gain[dest][src] = back })
      devRun(["dev-route", dest, src, "on"])
    }
  }

  function routingPreset(name) {
    devRun(["dev-routing-preset", name])
    devSettleTimer.interval = 1200
    devSettleTimer.restart()
  }

  function setPhantom(on) {
    patchDev(function(d) { d.phantom = on ? 1 : 0 })
    devRun(["dev-phantom", on ? "on" : "off"])
  }

  function setLed(control, active, idle) {
    var mode = root.dev && root.dev.leds && root.dev.leds[control] ? root.dev.leds[control].mode : null
    patchDev(function(d) {
      if (!d.leds) d.leds = {}
      if (!d.leds[control]) d.leds[control] = {}
      d.leds[control].active = active
      d.leds[control].idle = idle
    })
    var args = ["dev-led", control, String(active), String(idle)]
    if (typeof mode === "number") args.push(String(mode))
    devRun(args)
  }

  function applyLedPreset(name) {
    devRun(["dev-led-preset", name])
    devSettleTimer.interval = 1200
    devSettleTimer.restart()
  }

  // ---- FX (solo lectura), apps y perfiles ----
  // Lecturas: dev-fx-presets, dev-fx, dev-fx-preset, apps-rules, profile-list.
  // Van con el poll de dev-state. No hay botón que mande un get.
  // Mutaciones, misma cola que dev-*:
  //   apps-rule-set MATCH FIELD SINK
  //   apps-rule-del MATCH FIELD
  //   apps-watch-enable | apps-watch-disable
  //   apps-apply
  //   profile-save | profile-delete | profile-load NAME
  // MATCH y NAME van como un solo argv (pueden tener espacios).
  // El panel no llama a apps-watch.
  property var fxPresets: ({ voice: [], mic: [] })
  property bool fxPresetsSeen: false
  property string fxError: ""
  property bool fxDown: false
  property var fxNow: []
  property bool fxNowSeen: false
  property string fxNowError: ""
  property bool fxNowDown: false
  property var fxDetail: null
  property string fxDetailError: ""
  property bool fxDetailDown: false
  property string fxDetailKind: ""
  property string fxDetailName: ""
  property bool fxDetailLoading: false
  property string fxDetailWantedKind: ""
  property string fxDetailWantedName: ""
  property string fxDetailFlightKind: ""
  property string fxDetailFlightName: ""
  property bool fxDetailGotStdout: false

  property var appRules: []
  property bool appRulesSeen: false
  property string appsError: ""
  property bool appsDown: false
  property bool appsWatch: false
  property bool appsWatchActive: false
  property double appsWatchHoldUntil: 0
  property bool appsWatchWanted: false
  property bool appsApplying: false
  property int appsMoved: -1
  property int appsSkipped: -1
  property int appsFailed: -1
  property bool appsApplyBare: false
  property string appsApplyError: ""

  property var profileNames: []
  property bool profilesSeen: false
  property string profilesError: ""
  property bool profilesDown: false
  property var profileResult: null
  property string profileResultError: ""
  property string profileAction: ""
  property string profileResultName: ""
  property bool profileBusy: false
  property string profileBusyAction: ""

  signal appsAdded()

  function parseRead(text) {
    var raw = String(text || "").trim()
    var parsed = null
    try { parsed = JSON.parse(raw) } catch (e) {}
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null
    return parsed
  }

  function nameList(value) {
    if (!Array.isArray(value)) return []
    var out = []
    for (var i = 0; i < value.length; i++) {
      if (typeof value[i] === "string" && value[i] !== "") out.push(value[i])
      else if (value[i] && value[i].name) out.push(String(value[i].name))
    }
    return out
  }

  function refreshFx() {
    if (!fxPresetsProc.running) {
      fxPresetsProc.command = ["python3", root.helperPath, "dev-fx-presets"]
      fxPresetsProc.running = true
    }
    if (!fxNowProc.running) {
      fxNowProc.command = ["python3", root.helperPath, "dev-fx"]
      fxNowProc.running = true
    }
  }

  function markReadError(parsed, errorKey, setDown, setError) {
    if (parsed && parsed.ok === false) {
      setDown(false)
      setError(String(parsed.error || strings.t(errorKey)))
      return
    }
    setDown(true)
    setError("")
  }

  function ingestFxPresets(text) {
    var parsed = root.parseRead(text)
    if (!parsed || parsed.ok !== true) {
      root.markReadError(parsed, "fx.unavailable", function(v) { root.fxDown = v }, function(v) { root.fxError = v })
      return
    }
    root.fxPresets = { voice: root.nameList(parsed.voice), mic: root.nameList(parsed.mic) }
    root.fxPresetsSeen = true
    root.fxError = ""
    root.fxDown = false
  }

  function fxScalar(value) {
    if (value === null || value === undefined) return ""
    if (typeof value !== "object") return String(value)
    try { return JSON.stringify(value) } catch (e) { return "" }
  }

  function pushFxRow(out, label, value, labeled) {
    var shown = root.fxScalar(value)
    if (shown.length > 160) shown = shown.slice(0, 157) + "…"
    if (shown === "" && !label) return
    out.push({ label: label || "", value: shown, labeled: !!labeled })
  }

  function walkFx(node, out, inherited) {
    if (node === null || node === undefined) return
    if (typeof node !== "object") {
      root.pushFxRow(out, inherited || "", node, false)
      return
    }
    if (Array.isArray(node)) {
      for (var i = 0; i < node.length; i++) root.walkFx(node[i], out, inherited)
      return
    }
    var label = node.label ? String(node.label) : (node.name ? String(node.name) : "")
    var id = node.id ? String(node.id) : (node.param ? String(node.param) : "")
    var shown = label || inherited || id
    var nested = node.params || node.knobs || node.blocks || node.controls || node.items
    if (nested) {
      root.walkFx(nested, out, shown || inherited)
      return
    }
    if ("value" in node || "values" in node || "raw" in node) {
      var val = ("value" in node) ? node.value : (("values" in node) ? node.values : node.raw)
      root.pushFxRow(out, shown, val, label !== "")
      return
    }
    var keys = Object.keys(node)
    for (var k = 0; k < keys.length; k++) {
      var key = keys[k]
      if (key === "ok" || key === "error" || key === "label" || key === "name" || key === "id" || key === "param") continue
      var child = node[key]
      if (child && typeof child === "object") root.walkFx(child, out, shown || key)
      else root.pushFxRow(out, shown || key, child, label !== "")
    }
  }

  function ingestFxNow(text) {
    var parsed = root.parseRead(text)
    if (!parsed || parsed.ok !== true) {
      root.markReadError(parsed, "fx.unavailable", function(v) { root.fxNowDown = v }, function(v) { root.fxNowError = v })
      return
    }
    var out = []
    if (parsed.blocks || parsed.knob || parsed.knobs || parsed.family0105) {
      if (parsed.knob) root.walkFx(parsed.knob, out, "")
      if (parsed.knobs) root.walkFx(parsed.knobs, out, "")
      if (parsed.family0105) root.walkFx(parsed.family0105, out, "")
      if (parsed.blocks) root.walkFx(parsed.blocks, out, "")
    } else {
      var src = parsed.fx || parsed.effects || parsed
      root.walkFx(src, out, "")
    }
    root.fxNow = out
    root.fxNowSeen = true
    root.fxNowError = ""
    root.fxNowDown = false
  }

  function loadFxPreset(kind, name) {
    if (kind !== "voice" && kind !== "mic") return
    root.fxDetailKind = kind
    root.fxDetailName = String(name || "")
    root.fxDetail = null
    root.fxDetailError = ""
    root.fxDetailDown = false
    root.fxDetailLoading = true
    root.fxDetailWantedKind = kind
    root.fxDetailWantedName = String(name || "")
    if (fxDetailProc.running) return
    root.startFxDetail()
  }

  function startFxDetail() {
    if (fxDetailProc.running || root.fxDetailWantedKind === "") return
    var kind = root.fxDetailWantedKind
    var name = root.fxDetailWantedName
    root.fxDetailWantedKind = ""
    root.fxDetailWantedName = ""
    root.fxDetailFlightKind = kind
    root.fxDetailFlightName = name
    root.fxDetailGotStdout = false
    fxDetailProc.command = ["python3", root.helperPath, "dev-fx-preset", kind, name]
    fxDetailProc.running = true
  }

  function ingestFxDetail(text) {
    root.fxDetailGotStdout = true
    var kind = root.fxDetailFlightKind
    var name = root.fxDetailFlightName
    if (root.fxDetailKind !== kind || root.fxDetailName !== name) return
    if (root.fxDetailWantedKind !== "") return
    var parsed = root.parseRead(text)
    root.fxDetailLoading = false
    if (!parsed || parsed.ok !== true) {
      root.fxDetail = null
      root.markReadError(parsed, "fx.unavailable", function(v) { root.fxDetailDown = v }, function(v) { root.fxDetailError = v })
      return
    }
    root.fxDetail = parsed.preset && typeof parsed.preset === "object" ? parsed.preset : parsed
    root.fxDetailError = ""
    root.fxDetailDown = false
  }

  function refreshApps() {
    if (appsProc.running) return
    appsProc.command = ["python3", root.helperPath, "apps-rules"]
    appsProc.running = true
  }

  function asRules(value) {
    if (!Array.isArray(value)) return []
    var out = []
    for (var i = 0; i < value.length; i++) {
      var row = value[i]
      var match = ""
      var field = ""
      var sink = ""
      if (Array.isArray(row)) {
        match = String(row[0] || "")
        field = String(row[1] || "")
        sink = String(row[2] || "")
      } else if (row && typeof row === "object") {
        match = String(row.match || row.text || row.pattern || "")
        field = String(row.field || row.on || "")
        sink = String(row.sink || row.output || row.dest || "")
      }
      out.push({ match: match, field: field, sink: sink })
    }
    return out
  }

  function watchFrom(parsed) {
    if (!parsed || typeof parsed !== "object") return null
    var w = parsed.watch || parsed.watcher || null
    if (w && typeof w === "object" && (("enabled" in w) || ("active" in w))) {
      return { enabled: w.enabled === true, active: w.active === true }
    }
    if (("enabled" in parsed) || ("watching" in parsed)) {
      return { enabled: parsed.enabled === true || parsed.watching === true, active: parsed.active === true }
    }
    return null
  }

  function ingestApps(text) {
    var parsed = root.parseRead(text)
    if (!parsed || parsed.ok !== true) {
      root.markReadError(parsed, "apps.unavailable", function(v) { root.appsDown = v }, function(v) { root.appsError = v })
      return
    }
    root.appRules = root.asRules(parsed.rules)
    root.appRulesSeen = true
    root.appsError = ""
    root.appsDown = false
    if (Date.now() >= root.appsWatchHoldUntil) {
      var w = root.watchFrom(parsed)
      if (w) {
        root.appsWatch = w.enabled
        root.appsWatchActive = w.active
      }
    }
  }

  function addAppRule(match, field, sink) {
    var text = String(match || "").replace(/^\s+|\s+$/g, "")
    if (text === "" || text.length > 80) return
    if (["binary", "name", "both"].indexOf(field) < 0) return
    if (["game", "chat", "sampler", "system"].indexOf(sink) < 0) return
    root.devRun(["apps-rule-set", text, field, sink], "apps")
  }

  function removeAppRule(match, field) {
    var text = String(match || "")
    if (text === "" || ["binary", "name", "both"].indexOf(field) < 0) return
    root.devRun(["apps-rule-del", text, String(field)], "apps")
  }

  function setAppsWatch(on) {
    root.appsWatch = !!on
    root.appsWatchWanted = !!on
    root.appsWatchHoldUntil = Date.now() + 2000
    root.devRun([on ? "apps-watch-enable" : "apps-watch-disable"], "apps")
  }

  function applyApps() {
    if (root.appsApplying) return
    root.appsApplying = true
    root.appsMoved = -1
    root.appsSkipped = -1
    root.appsFailed = -1
    root.appsApplyBare = false
    root.appsApplyError = ""
    root.devRun(["apps-apply"], "apps")
  }

  function countOf(value) {
    if (typeof value === "number" && isFinite(value)) return value
    if (Array.isArray(value)) return value.length
    return -1
  }

  function refreshProfiles() {
    if (profilesProc.running) return
    profilesProc.command = ["python3", root.helperPath, "profile-list"]
    profilesProc.running = true
  }

  function profileNameOk(name) {
    return /^[A-Za-z0-9][A-Za-z0-9 _-]{0,40}$/.test(String(name || ""))
  }

  function asProfileNames(value) {
    var list = root.nameList(value)
    var out = []
    for (var i = 0; i < list.length; i++) {
      if (list[i].charAt(0) === "_") continue
      out.push(list[i])
    }
    return out
  }

  function ingestProfiles(text) {
    var parsed = root.parseRead(text)
    if (!parsed || parsed.ok !== true) {
      root.markReadError(parsed, "profiles.unavailable", function(v) { root.profilesDown = v }, function(v) { root.profilesError = v })
      return
    }
    var list = parsed.profiles || parsed.names || []
    root.profileNames = root.asProfileNames(list)
    root.profilesSeen = true
    root.profilesError = ""
    root.profilesDown = false
  }

  function beginProfile(action, name) {
    root.profileBusy = true
    root.profileBusyAction = action
    root.profileAction = action
    root.profileResultName = name
    root.profileResult = null
    root.profileResultError = ""
  }

  function saveProfile(name) {
    if (!root.profileNameOk(name)) return
    root.beginProfile("profile-save", name)
    root.devRun(["profile-save", name], "profiles")
  }

  function deleteProfile(name) {
    if (!name || String(name).charAt(0) === "_") return
    root.beginProfile("profile-delete", name)
    root.devRun(["profile-delete", name], "profiles")
  }

  function loadProfile(name) {
    if (!name || String(name).charAt(0) === "_") return
    root.beginProfile("profile-load", name)
    root.devRun(["profile-load", name], "profiles")
  }

  function finishExtra(tag, parsed, err, args) {
    try {
      if (tag === "apps") root.finishApps(parsed, err, args)
      else if (tag === "profiles") root.finishProfiles(parsed, err, args)
    } catch (e) {
      if (tag === "apps") root.appsError = String(e)
      else root.profilesError = String(e)
    }
  }

  function finishApps(parsed, err, args) {
    var cmd = args && args.length ? String(args[0]) : ""
    if (cmd === "apps-watch-enable" || cmd === "apps-watch-disable") {
      if (err !== "") {
        root.appsWatch = !root.appsWatchWanted
        root.appsWatchHoldUntil = 0
        root.appsError = err
        return
      }
      var w = root.watchFrom(parsed)
      if (w) {
        root.appsWatch = w.enabled
        root.appsWatchActive = w.active
      }
      root.appsError = ""
      root.refreshApps()
      return
    }
    if (cmd === "apps-apply") {
      root.appsApplying = false
      root.appsApplyError = err
      root.appsMoved = parsed ? root.countOf(parsed.moved) : -1
      root.appsSkipped = parsed ? root.countOf(parsed.skipped) : -1
      root.appsFailed = parsed ? root.countOf(parsed.failed) : -1
      root.appsApplyBare = root.appsMoved < 0 && root.appsSkipped < 0 && root.appsFailed < 0 && err === ""
      root.refresh()
      return
    }
    if (err !== "") {
      root.appsError = err
      return
    }
    root.appsError = ""
    if (cmd === "apps-rule-set") root.appsAdded()
    root.refreshApps()
  }

  function finishProfiles(parsed, err, args) {
    var cmd = args && args.length ? String(args[0]) : ""
    root.profileAction = cmd || root.profileAction
    root.profileResult = parsed
    root.profileResultError = err
    root.profileBusy = false
    if (cmd === "profile-load") {
      root.refresh()
      root.refreshApps()
    }
    root.refreshProfiles()
  }

  function openSampleDir() {
    Quickshell.execDetached(["python3", root.helperPath, "ensure-dirs"])
    openDirTimer.restart()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: { injectPanel(); refresh() }
  Component.onCompleted: {
    Quickshell.execDetached(["python3", root.helperPath, "ensure-dirs"])
    refresh()
  }

  Process {
    id: statusProc
    stdout: StdioCollector { onStreamFinished: root.ingest(text) }
  }

  Process {
    id: installProc
    onExited: {
      root.busy = false
      settleTimer.interval = 2500
      settleTimer.restart()
    }
  }

  Timer {
    id: pollTimer
    interval: root.opened ? 1200 : 10000
    repeat: true
    running: true
    onTriggered: {
      root.refresh()
      if (root.opened) {
        root.refreshDev()
        root.refreshFx()
        root.refreshApps()
        root.refreshProfiles()
      }
    }
  }

  Process {
    id: devProc
    stdout: StdioCollector { onStreamFinished: root.ingestDev(text) }
  }

  Process {
    id: devWriteProc
    stdout: StdioCollector {
      onStreamFinished: {
        root.devWriteText = text
        root.devWriteOutDone = true
        root.finishDevWrite()
      }
    }
    onExited: (exitCode, exitStatus) => {
      root.devWriteCode = exitCode
      root.devWriteExitDone = true
      root.finishDevWrite()
    }
  }

  Process {
    id: devForceProc
    stdout: StdioCollector {
      onStreamFinished: {
        root.devRefreshing = false
        root.devHoldUntil = 0
        root.ingestDev(text)
      }
    }
    onExited: root.devRefreshing = false
  }

  Process {
    id: ledFileProc
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var parsed = JSON.parse(String(text || ""))
          if (parsed && parsed.controls) root.ledData = parsed
        } catch (e) {}
      }
    }
  }

  Process {
    id: presetsProc
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var parsed = JSON.parse(String(text || ""))
          if (parsed && parsed.ok !== false && Array.isArray(parsed.presets)) root.ledPresets = parsed.presets
        } catch (e) {}
      }
    }
  }

  Process {
    id: fxPresetsProc
    stdout: StdioCollector { onStreamFinished: root.ingestFxPresets(text) }
  }

  Process {
    id: fxNowProc
    stdout: StdioCollector { onStreamFinished: root.ingestFxNow(text) }
  }

  Process {
    id: fxDetailProc
    stdout: StdioCollector { onStreamFinished: root.ingestFxDetail(text) }
    onExited: function(code, status) {
      if (!root.fxDetailGotStdout) root.ingestFxDetail("")
      if (root.fxDetailWantedKind !== "") root.startFxDetail()
    }
  }

  Process {
    id: appsProc
    stdout: StdioCollector { onStreamFinished: root.ingestApps(text) }
  }

  Process {
    id: profilesProc
    stdout: StdioCollector { onStreamFinished: root.ingestProfiles(text) }
  }

  Timer {
    id: devSettleTimer
    interval: 800
    onTriggered: {
      if (root.devWriting || root.devQueue.length > 0) { restart(); return }
      interval = 800; root.devHoldUntil = 0; root.refreshDev()
    }
  }

  Timer {
    id: gainTimer
    interval: 100
    onTriggered: {
      var pending = root.pendingGain
      root.pendingGain = ({})
      for (var k in pending) {
        var parts = k.split(":")
        root.devRun(["dev-gain", parts[0], parts[1], String(pending[k])])
      }
    }
  }

  Timer {
    id: settleTimer
    interval: 180
    onTriggered: { interval = 180; root.refresh() }
  }

  Timer {
    id: openDirTimer
    interval: 250
    onTriggered: if (root.mixer.sampleDir) Quickshell.execDetached(["xdg-open", root.mixer.sampleDir])
  }

  Timer {
    id: volumeTimer
    interval: 70
    onTriggered: {
      var pending = root.pendingVolume
      root.pendingVolume = ({})
      for (var key in pending) root.run(["volume", key, String(pending[key])])
    }
  }

  Timer {
    id: micTimer
    interval: 160
    onTriggered: {
      var pending = root.pendingMic
      root.pendingMic = ({})
      for (var key in pending) root.run(["mic-set", key, String(pending[key])])
    }
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  IpcHandler {
    target: "csarmiento.mgame-mixer"

    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function tab(name: string): void {
      if (panelLoader.item && ["mixer", "mic", "sampler", "routing", "lights", "device", "fx", "apps", "profiles"].indexOf(name) >= 0) panelLoader.item.tab = name
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.icon
    active: root.opened
    opacity: root.splitReady ? 1.0 : 0.55
    tooltipText: root.splitReady ? strings.t("title") : strings.t("subtitle.setup")
    onPressed: function(b) { root.toggle() }
  }
}
