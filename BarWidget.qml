import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// Ícono de headset en la barra. Toda la lógica de audio vive acá; Panel.qml
// solo dibuja. El estado sale de `mgame.py status` (pactl), no del modelo de
// PipeWire de Quickshell, para no tocar nodos que PipeWire puede borrar en
// pleno reinicio de audio.
BarWidget {
  id: root
  moduleName: "csarmiento.mgame-mixer"

  Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

  readonly property string helperPath: Qt.resolvedUrl("mgame.py").toString().replace(/^file:\/\//, "")
  readonly property var validPairs: ["FC LFE", "RL RR", "SL SR"]
  readonly property string chatPair: {
    var p = String(setting("chatPair", "FC LFE"))
    return validPairs.indexOf(p) >= 0 ? p : "FC LFE"
  }

  property var mixer: ({
    sinks: { game: { present: false, volume: 0, muted: false }, chat: { present: false, volume: 0, muted: false } },
    default: "", streams: [], installedPair: "", wantedPair: "FC LFE", configExists: false
  })
  property bool busy: false

  readonly property bool sinksReady: !!mixer.sinks.game.present && !!mixer.sinks.chat.present
  readonly property bool pairMismatch: sinksReady && mixer.installedPair !== "" && mixer.installedPair !== chatPair
  readonly property bool needsSetup: !sinksReady || pairMismatch

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  // Glifos Nerd Font (headset, mute, volumen)
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
      if (parsed && parsed.sinks && parsed.sinks.game && parsed.sinks.chat) root.mixer = parsed
    } catch (e) {}
  }

  function refresh() {
    if (statusProc.running) return
    statusProc.command = ["python3", root.helperPath, "status", root.chatPair]
    statusProc.running = true
  }

  function settleRefresh() { settleTimer.restart() }

  // Cada acción es un argv; ningún valor se interpola en una línea de shell.
  function run(args) {
    Quickshell.execDetached(["python3", root.helperPath].concat(args))
    settleRefresh()
  }

  function patchSink(key, fields) {
    var next = JSON.parse(JSON.stringify(root.mixer))
    for (var f in fields) next.sinks[key][f] = fields[f]
    root.mixer = next
  }

  // Los sliders mandan muchos valores por segundo; se juntan y se envía el último.
  property var pendingVolume: ({})
  function setVolume(key, fraction) {
    var pct = Math.round(Math.max(0, Math.min(1, fraction)) * 100)
    pendingVolume[key] = pct
    patchSink(key, { volume: pct })
    volumeTimer.restart()
  }

  function toggleMute(key) {
    patchSink(key, { muted: !root.mixer.sinks[key].muted })
    run(["mute", key])
  }

  function setDefault(key) {
    var next = JSON.parse(JSON.stringify(root.mixer))
    next.default = key
    root.mixer = next
    run(["default", key])
  }

  function moveStream(id, key) {
    run(["move", String(Math.floor(Number(id))), key])
  }

  function installConfig() {
    if (root.busy) return
    root.busy = true
    installProc.command = ["python3", root.helperPath, "install", root.chatPair]
    installProc.running = true
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: { injectPanel(); refresh() }
  Component.onCompleted: refresh()

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
    onTriggered: root.refresh()
  }

  Timer {
    id: settleTimer
    interval: 180
    onTriggered: { interval = 180; root.refresh() }
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
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.icon
    active: root.opened
    opacity: root.sinksReady ? 1.0 : 0.55
    tooltipText: root.sinksReady ? strings.t("title") : strings.t("subtitle.setup")
    onPressed: function(b) { root.toggle() }
  }
}
