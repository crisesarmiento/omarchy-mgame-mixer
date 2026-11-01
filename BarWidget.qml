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

  // Cola serializada de escrituras `dev-*`: un solo proceso a la vez, en orden.
  property var devQueue: []
  property bool devWriting: false
  property bool devWriteOutDone: false
  property bool devWriteExitDone: false
  property string devWriteText: ""
  property int devWriteCode: 0

  function holdDev(ms) {
    root.devHoldUntil = Math.max(root.devHoldUntil, Date.now() + ms)
  }

  function devQueueKey(args) {
    return args[0] === "dev-gain" ? "gain:" + args[1] + ":" + args[2] : ""
  }

  function devRun(args) {
    holdDev(700)
    var q = root.devQueue
    var key = devQueueKey(args)
    if (key !== "") {
      for (var i = 0; i < q.length; i++) {
        if (q[i].key === key) { q[i].args = args; pumpDev(); return }
      }
    } else if (q.length > 0 && q[q.length - 1].key === ""
               && JSON.stringify(q[q.length - 1].args) === JSON.stringify(args)) {
      pumpDev()
      return
    }
    q.push({ key: key, args: args })
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
      if (root.opened) root.refreshDev()
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
      if (panelLoader.item && ["mixer", "mic", "sampler", "routing", "lights", "device"].indexOf(name) >= 0) panelLoader.item.tab = name
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
