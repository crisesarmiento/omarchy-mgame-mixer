import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.crisesarmiento.mgame-mixer"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

  readonly property color foreground: bar ? bar.barForeground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.45)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property var mixer: hostWidget ? hostWidget.mixer : null
  readonly property var outKeys: ["game", "chat", "sampler", "system"]
  readonly property var inKeys: ["in_stream", "in_alt", "in_chat", "in_sampler"]
  readonly property var pads: [1, 2, 3, 4, 5]
  readonly property bool splitReady: hostWidget ? hostWidget.splitReady : false
  readonly property bool micReady: hostWidget ? hostWidget.micReady : false
  readonly property bool needsSetup: hostWidget ? hostWidget.needsSetup : false
  readonly property bool pairOnly: hostWidget ? hostWidget.pairOnly : false
  readonly property bool busy: hostWidget ? hostWidget.busy : false
  readonly property var streams: mixer && mixer.streams ? mixer.streams.slice(0, 16) : []
  readonly property var micState: mixer ? mixer.micState : ({ enabled: false, preset: "natural", custom: false, vad: 0, ratio: 1, presence: 0 })
  readonly property var listener: mixer ? mixer.listener : ({ enabled: false, active: false })

  // ---- Equipo (SysEx) ----
  readonly property var dev: hostWidget ? hostWidget.dev : null
  readonly property bool devOk: hostWidget ? hostWidget.devOk : false
  readonly property bool devConnected: devOk && !!dev && dev.connected === true
  readonly property var dests: ["stream", "chat", "alt", "sampler", "main", "phones"]
  readonly property var srcs: ["mic", "game", "chat", "aux", "sampler", "system"]
  readonly property color urgentColor: bar ? bar.urgent : "#e06c75"
  property string hoverCell: ""
  property string confirmPreset: ""
  property string ledEdit: ""
  property string ledSlot: "active"
  readonly property var ledControls: hostWidget && hostWidget.ledData ? hostWidget.ledData.controls : null
  readonly property var ledPalette: hostWidget && hostWidget.ledData && hostWidget.ledData.palette ? hostWidget.ledData.palette : ({})
  readonly property var paletteKeys: Object.keys(ledPalette).sort(function(a, b) { return Number(a) - Number(b) })

  function gainOf(dest, src) { return hostWidget ? hostWidget.gainOf(dest, src) : -1 }
  function isMuted(dest, src) {
    var m = dev && dev.muted ? dev.muted[dest] : null
    return !!m && m.indexOf(src) >= 0
  }
  function ledValue(control, slot) {
    var l = dev && dev.leds ? dev.leds[control] : null
    return l && typeof l[slot] === "number" ? l[slot] : -1
  }
  function paletteColor(idx) {
    var c = ledPalette[String(idx)]
    return c ? String(c) : ""
  }
  function pickLed(idx) {
    if (!root.ledEdit || !hostWidget) return
    var a = ledValue(root.ledEdit, "active")
    var i = ledValue(root.ledEdit, "idle")
    if (root.ledSlot === "active") a = idx; else i = idx
    hostWidget.setLed(root.ledEdit, a < 0 ? idx : a, i < 0 ? idx : i)
  }
  function ledLabel(control) {
    var c = ledControls ? ledControls[control] : null
    return c && c.label ? String(c.label) : control
  }

  // FX, apps y perfiles. La data vive en el widget; acá solo se elige y se confirma.
  property string confirmProfile: ""
  property string appsField: "both"
  property string appsSink: "game"
  property bool appsMatchReject: false
  property bool profileNameReject: false

  readonly property var fxVoice: hostWidget && hostWidget.fxPresets ? hostWidget.fxPresets.voice : []
  readonly property var fxMic: hostWidget && hostWidget.fxPresets ? hostWidget.fxPresets.mic : []
  readonly property var fxNowRows: hostWidget && hostWidget.fxNow ? hostWidget.fxNow : []
  readonly property var appRules: hostWidget && hostWidget.appRules ? hostWidget.appRules : []
  readonly property var profileNames: hostWidget && hostWidget.profileNames ? hostWidget.profileNames : []
  readonly property string fxPickKind: hostWidget ? hostWidget.fxDetailKind : ""
  readonly property string fxPickName: hostWidget ? hostWidget.fxDetailName : ""
  readonly property var fxDetail: hostWidget ? hostWidget.fxDetail : null
  readonly property var fxEffectLines: fxEffects(fxDetail)
  readonly property var fxRecordLines: fxRecords(fxDetail)
  readonly property var profileLineList: {
    var hw = root.hostWidget
    var parsed = hw ? hw.profileResult : null
    var err = hw ? hw.profileResultError : ""
    var action = hw ? hw.profileAction : ""
    var savedName = hw ? hw.profileResultName : ""
    return root.buildProfileLines(parsed, err, action, savedName)
  }

  function selectTab(v) {
    root.tab = v
    if (appsMatch) appsMatch.focus = false
    if (profileName) profileName.focus = false
    if (!root.hostWidget) return
    if (v === "fx") root.hostWidget.refreshFx()
    else if (v === "apps") root.hostWidget.refreshApps()
    else if (v === "profiles") root.hostWidget.refreshProfiles()
  }

  function profileNameOk(name) {
    return /^[A-Za-z0-9][A-Za-z0-9 _-]{0,40}$/.test(String(name || ""))
  }

  function submitAppRule() {
    var text = appsMatch.text.replace(/^\s+|\s+$/g, "")
    if (text === "") {
      root.appsMatchReject = true
      return
    }
    root.appsMatchReject = false
    if (root.hostWidget) root.hostWidget.addAppRule(text, root.appsField, root.appsSink)
  }

  function submitProfile() {
    var name = profileName.text
    if (!root.profileNameOk(name)) {
      root.profileNameReject = true
      return
    }
    root.profileNameReject = false
    if (root.hostWidget) root.hostWidget.saveProfile(name)
  }

  function fxRaw(value) {
    if (value === null || value === undefined) return ""
    if (!root.hostWidget) return String(value)
    var s = root.hostWidget.fxScalar(value)
    return s.length > 160 ? s.slice(0, 157) + "…" : s
  }

  function fxEffects(detail) {
    if (!detail) return []
    var list = detail.effects || null
    if (!Array.isArray(list) && detail.preset && detail.preset.effects) list = detail.preset.effects
    if (!Array.isArray(list)) return []
    var out = []
    for (var i = 0; i < list.length; i++) {
      var item = list[i]
      if (item && typeof item === "object" && item.name) out.push(String(item.name))
      else if (typeof item === "string" && item !== "") out.push(item)
      else out.push(root.fxRaw(item) || strings.t("fx.unnamed"))
    }
    return out
  }

  function fxRecords(detail) {
    if (!detail) return []
    var list = null
    if (Array.isArray(detail.records)) list = detail.records
    else if (Array.isArray(detail.mics)) list = detail.mics
    else if (Array.isArray(detail.mic)) list = detail.mic
    else if (detail.mic && typeof detail.mic === "object") list = [detail.mic]
    if (!list) return []
    var out = []
    for (var i = 0; i < list.length; i++) {
      var row = list[i]
      if (typeof row === "string") out.push(row)
      else if (row && row.name) out.push(String(row.name))
      else if (row && row.label) out.push(String(row.label))
      else out.push(strings.t("fx.unnamed") + " " + String(i + 1) + (row ? "  " + root.fxRaw(row) : ""))
    }
    return out
  }

  function profileStepLabel(key) {
    var map = {
      volumes: "profiles.step.volumes",
      sinks: "profiles.step.volumes",
      mic: "profiles.step.mic",
      rules: "profiles.step.rules",
      apps: "profiles.step.rules",
      gains: "profiles.step.gains",
      leds: "profiles.step.leds",
      led: "profiles.step.leds",
      ledPreset: "profiles.step.leds"
    }
    return map[key] ? strings.t(map[key]) : key
  }

  function micLiveFalse(value) {
    return !!(value && typeof value === "object" && value.live === false)
  }

  function gainsText(value) {
    if (value === null || value === undefined) return ""
    if (typeof value === "number") return strings.t("profiles.gainsSent").arg(value)
    if (typeof value === "string") {
      if (value === "skipped") return strings.t("profiles.gainsSkipped")
      if (value === "saved") return ""
      var pair = value.match(/(\d+)\s*\/\s*(\d+)/)
      if (pair) return strings.t("profiles.gainsSentOf").arg(pair[1]).arg(pair[2])
      var one = value.match(/(\d+)/)
      if (one && /sent/i.test(value)) return strings.t("profiles.gainsSent").arg(one[1])
      return ""
    }
    if (typeof value !== "object" || !("sent" in value)) return ""
    if (typeof value.total === "number") return strings.t("profiles.gainsSentOf").arg(value.sent).arg(value.total)
    if (typeof value.of === "number") return strings.t("profiles.gainsSentOf").arg(value.sent).arg(value.of)
    return strings.t("profiles.gainsSent").arg(value.sent)
  }

  function ledText(value) {
    if (value === null || value === "skipped") return strings.t("profiles.noLed")
    if (value === "failed") return strings.t("profiles.failed")
    if (value === "ok") return strings.t("profiles.stepOk")
    if (typeof value === "string" && value !== "") return value
    if (!value || typeof value !== "object") return ""
    if (value.preset === null || value.ledPreset === null) return strings.t("profiles.noLed")
    if (value.preset) return String(value.preset)
    if (typeof value.name === "string" && value.name !== "") return value.name
    if (value.ok === false) return String(value.error || strings.t("profiles.failed"))
    if (value.ok === true) return strings.t("profiles.stepOk")
    return ""
  }

  function stepStatus(value) {
    if (value === null || value === undefined) return strings.t("profiles.stepOk")
    if (typeof value === "string") return /applied/i.test(value) ? strings.t("profiles.stepOk") : value
    if (typeof value !== "object") return String(value)
    if (value.ok === false) return String(value.error || strings.t("profiles.failed"))
    return strings.t("profiles.stepOk")
  }

  function formatStep(key, value) {
    if (key === "gains") {
      var sent = root.gainsText(value)
      return sent || (root.profileStepLabel(key) + " · " + root.stepStatus(value))
    }
    if (key === "leds" || key === "led" || key === "ledPreset") {
      var led = root.ledText(value)
      return root.profileStepLabel(key) + " · " + (led || root.stepStatus(value))
    }
    return root.profileStepLabel(key) + " · " + root.stepStatus(value)
  }

  function stepEntries(parsed) {
    if (!parsed || typeof parsed !== "object") return []
    var order = ["volumes", "sinks", "mic", "rules", "apps", "gains", "leds", "led", "ledPreset"]
    var skip = { ok: 1, error: 1, name: 1, steps: 1, result: 1, action: 1, undo: 1, deviceUpdated: 1, age: 1, step: 1, version: 1 }
    var bag = (parsed.steps && typeof parsed.steps === "object") ? parsed.steps : parsed
    var topLevel = bag === parsed
    if (Array.isArray(bag)) {
      var fromList = []
      for (var i = 0; i < bag.length; i++) {
        var step = bag[i]
        if (!step || typeof step !== "object") continue
        var id = String(step.id || step.step || "")
        if (!id) id = String(step.name || "")
        if (!id || skip[id]) continue
        fromList.push({ key: id, value: step })
      }
      return fromList
    }
    var out = []
    var seen = {}
    for (var o = 0; o < order.length; o++) {
      if (order[o] in bag) {
        out.push({ key: order[o], value: bag[order[o]] })
        seen[order[o]] = true
      }
    }
    if (topLevel) return out
    var keys = Object.keys(bag)
    for (var k = 0; k < keys.length; k++) {
      if (seen[keys[k]] || skip[keys[k]]) continue
      out.push({ key: keys[k], value: bag[keys[k]] })
    }
    return out
  }

  function buildProfileLines(parsed, err, action, savedName) {
    var lines = []
    function add(text, urgent) {
      if (text) lines.push({ text: String(text), urgent: !!urgent })
    }
    var busy = err === "busy" || (parsed && parsed.error === "busy")
    if (busy) add(strings.t("profiles.busy"), true)
    else if (err) add(err, true)
    else if (parsed && parsed.ok === false) add(String(parsed.error || strings.t("profiles.failed")), true)
    if (!busy && !err && parsed && parsed.ok === true && action === "profile-save") {
      add(strings.t("profiles.saved").arg(savedName), false)
      if (parsed.gains === null) add(strings.t("profiles.gainsMissing"), false)
      if (parsed.ledPreset === null) add(strings.t("profiles.noLed"), false)
    }
    if (!busy && !err && parsed && parsed.ok === true && action === "profile-delete")
      add(strings.t("profiles.deleted").arg(savedName), false)
    if (action === "profile-load" && parsed && !parsed.steps) {
      root.appendLoadLines(add, parsed, err, busy)
      return lines
    }
    var saidMic = false
    var entries = (action === "profile-load" || (parsed && parsed.steps)) ? root.stepEntries(parsed) : []
    for (var i = 0; i < entries.length; i++) {
      var key = entries[i].key
      var value = entries[i].value
      if (key === "mic" && root.micLiveFalse(value)) {
        add(strings.t("profiles.micNotLive"), false)
        saidMic = true
        continue
      }
      var failed = value && typeof value === "object" && value.ok === false
      add(root.formatStep(key, value), failed)
    }
    if (!saidMic && parsed && root.micLiveFalse(parsed.mic))
      add(strings.t("profiles.micNotLive"), false)
    return lines
  }

  function appendLoadLines(add, parsed, err, busy) {
    var failedAt = parsed && parsed.step ? String(parsed.step) : ""
    var done = parsed && parsed.ok === true && !err && !busy
    var order = ["volumes", "mic", "rules", "gains", "ledPreset"]
    function passed(key) {
      if (done) return true
      var fail = order.indexOf(failedAt)
      var here = order.indexOf(key)
      return fail > 0 && here >= 0 && here < fail
    }
    if (done || passed("volumes"))
      add(root.profileStepLabel("volumes") + " · " + strings.t("profiles.stepOk"), false)
    else if (failedAt === "volumes")
      add(root.profileStepLabel("volumes") + " · " + strings.t("profiles.failed"), true)
    if (parsed && root.micLiveFalse(parsed.mic))
      add(strings.t("profiles.micNotLive"), false)
    else if (done || (parsed && parsed.mic && parsed.mic.live === true))
      add(root.profileStepLabel("mic") + " · " + strings.t("profiles.stepOk"), false)
    else if (failedAt === "mic")
      add(root.profileStepLabel("mic") + " · " + strings.t("profiles.failed"), true)
    if (done || passed("rules"))
      add(root.profileStepLabel("rules") + " · " + strings.t("profiles.stepOk"), false)
    else if (failedAt === "rules")
      add(root.profileStepLabel("rules") + " · " + strings.t("profiles.failed"), true)
    if (parsed && "gains" in parsed && parsed.gains !== undefined && parsed.gains !== null)
      add(root.formatStep("gains", parsed.gains), failedAt === "gains")
    else if (failedAt === "gains")
      add(root.profileStepLabel("gains") + " · " + strings.t("profiles.failed"), true)
    if (parsed && (parsed.ledPreset === "skipped" || parsed.ledPreset === null))
      add(strings.t("profiles.noLed"), false)
    else if (parsed && "ledPreset" in parsed)
      add(root.formatStep("ledPreset", parsed.ledPreset), parsed.ledPreset === "failed" || failedAt === "ledPreset")
    else if (failedAt === "ledPreset")
      add(root.profileStepLabel("ledPreset") + " · " + strings.t("profiles.failed"), true)
  }

  function profileWorkingText() {
    var action = root.hostWidget ? root.hostWidget.profileBusyAction : ""
    if (action === "profile-save") return strings.t("profiles.saving")
    if (action === "profile-delete") return strings.t("profiles.deleting")
    return strings.t("profiles.loading")
  }

  property string tab: "mixer"
  property int selectedPad: 1
  // Juego de pads que se está viendo/editando: página (1/2) + banco (A/B).
  // Sigue al hardware cuando este informa su página y banco.
  property string viewSet: "1A"
  readonly property string hwActiveSet: mixer && mixer.activeSet ? mixer.activeSet : "1A"
  readonly property bool hwSetKnown: !!mixer && mixer.hwSetKnown === true
  onHwActiveSetChanged: if (hwSetKnown) viewSet = hwActiveSet
  onHwSetKnownChanged: if (hwSetKnown) viewSet = hwActiveSet

  function open() {
    root.controller.show()
    if (hostWidget) {
      hostWidget.refresh()
      hostWidget.refreshDev()
      hostWidget.loadDevStatic()
      hostWidget.refreshFx()
      hostWidget.refreshApps()
      hostWidget.refreshProfiles()
    }
  }
  function close() { root.controller.hide() }
  function toggle() { if (root.opened) root.close(); else root.open() }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function nodeState(key) {
    var m = root.mixer
    if (!m) return null
    if (key === "mic") return m.mic
    return m.outs[key] || m.ins[key] || null
  }

  function isDefault(key) {
    var m = root.mixer
    if (!m) return false
    return outKeys.indexOf(key) >= 0 ? m.defaultOut === key : m.defaultIn === key
  }

  function padFile(pad) {
    var m = root.mixer
    var group = m && m.pads ? m.pads[root.viewSet] : null
    return group && group[String(pad)] ? String(group[String(pad)]) : ""
  }

  function pairOf(key) {
    return hostWidget && hostWidget.wantedPairs[key] ? hostWidget.wantedPairs[key] : ""
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(470))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: appsMatch.activeFocus || profileName.activeFocus
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(12)

        PanelHero {
          width: parent.width
          title: strings.t("title")
          meta: root.splitReady ? strings.t("subtitle.ok") : strings.t("subtitle.setup")
          foreground: root.foreground
          fontFamily: root.fontFamily
          iconOpacity: root.splitReady ? 1.0 : 0.6
          iconComponent: Component {
            Text {
              textFormat: Text.PlainText
              text: "󰋎"
              color: root.foreground
              font.pixelSize: Style.font.display
              font.family: root.fontFamily
            }
          }
        }

        // ---- Aviso de configuración ----
        Column {
          visible: root.needsSetup
          width: parent.width
          spacing: Style.space(8)

          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            text: root.pairOnly ? strings.t("setup.mismatch") : strings.t("setup.missing")
          }

          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            text: strings.t("setup.warning")
          }

          Button {
            enabled: !root.busy
            opacity: root.busy ? 0.6 : 1.0
            text: root.busy
              ? strings.t("setup.working")
              : (root.pairOnly ? strings.t("setup.apply") : strings.t("setup.install"))
            foreground: root.foreground
            fontFamily: root.fontFamily
            bordered: true
            onClicked: if (root.hostWidget) root.hostWidget.installConfig()
          }
        }

        PanelSeparator { foreground: root.foreground }

        // Nueve pestañas no entran en una fila a este ancho. Mismo control, segunda fila.
        Column {
          width: parent.width
          spacing: Style.space(6)

          ButtonGroup {
            focusable: false
            foreground: root.foreground
            fontFamily: root.fontFamily
            value: root.tab
            options: [
              { value: "mixer", label: strings.t("tab.mixer") },
              { value: "mic", label: strings.t("tab.mic") },
              { value: "sampler", label: strings.t("tab.sampler") },
              { value: "routing", label: strings.t("tab.routing") },
              { value: "lights", label: strings.t("tab.lights") },
              { value: "device", label: strings.t("tab.device") }
            ]
            onChanged: function(v) { root.selectTab(v) }
          }

          ButtonGroup {
            focusable: false
            foreground: root.foreground
            fontFamily: root.fontFamily
            value: root.tab
            options: [
              { value: "fx", label: strings.t("tab.fx") },
              { value: "apps", label: strings.t("tab.apps") },
              { value: "profiles", label: strings.t("tab.profiles") }
            ]
            onChanged: function(v) { root.selectTab(v) }
          }
        }

        // ================= Mixer =================
        Column {
          visible: root.tab === "mixer"
          width: parent.width
          spacing: Style.space(6)

          PanelSectionHeader {
            text: strings.t("mixer.outputs")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Repeater {
            model: root.outKeys
            Strip { required property string modelData; key: modelData }
          }

          Item { width: 1; height: Style.space(4) }

          PanelSectionHeader {
            text: strings.t("mixer.inputs")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Repeater {
            model: root.inKeys
            Strip { required property string modelData; key: modelData }
          }

          Item { width: 1; height: Style.space(4) }

          PanelSectionHeader {
            text: strings.t("streams.header")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Text {
            visible: root.streams.length === 0
            width: parent.width
            textFormat: Text.PlainText
            text: strings.t("streams.empty")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Flickable {
            id: appsFlick
            visible: root.streams.length > 0
            width: parent.width
            height: Math.min(appsCol.implicitHeight, Style.space(176))
            contentWidth: width
            contentHeight: appsCol.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Column {
              id: appsCol
              width: appsFlick.width
              spacing: Style.space(8)

              Repeater {
                model: root.streams
                StreamRow {
                  required property var modelData
                  streamId: modelData.id
                  streamName: String(modelData.name)
                  route: String(modelData.route)
                }
              }
            }
          }
        }

        // ---- Indicadores de hardware (solo lectura) ----
        Column {
          visible: root.tab === "mixer"
          width: parent.width
          spacing: Style.space(6)

          PanelSectionHeader {
            text: strings.t("hw.header")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Flow {
            width: parent.width
            spacing: Style.space(14)

            Repeater {
              model: ["mic_mute", "game_mute", "chat_mute", "sampler_mute", "main_alt_mute"]
              HwChip { required property string modelData; name: modelData }
            }
          }

          Text {
            visible: !root.listener.active && !root.devOk
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("hw.needListener")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
        }

        // ================= Mic =================
        Column {
          visible: root.tab === "mic"
          width: parent.width
          spacing: Style.space(10)

          Item {
            width: parent.width
            implicitHeight: Math.max(micTitle.implicitHeight, micSwitch.implicitHeight)

            Column {
              id: micTitle
              anchors.left: parent.left
              anchors.right: micSwitch.left
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: strings.t("mic.title")
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
              }
              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: strings.t("mic.hint")
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                wrapMode: Text.WordWrap
              }
            }

            ToggleSwitch {
              id: micSwitch
              checked: root.micState.enabled
              foreground: root.foreground
              accent: Color.accent
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              onToggled: root.hostWidget.micEnable(!root.micState.enabled)
            }
          }

          Text {
            visible: !root.micReady
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("mic.missing")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          PanelSectionHeader {
            text: strings.t("mic.preset") + (root.micState.custom && root.micState.enabled ? "  ·  " + strings.t("mic.custom") : "")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          ButtonGroup {
            focusable: false
            foreground: root.foreground
            fontFamily: root.fontFamily
            value: root.micState.enabled ? root.micState.preset : "off"
            options: [
              { value: "off", label: strings.t("preset.off") },
              { value: "natural", label: strings.t("preset.natural") },
              { value: "broadcast", label: strings.t("preset.broadcast") },
              { value: "noisy", label: strings.t("preset.noisy") }
            ]
            onChanged: function(v) { root.hostWidget.micPreset(v) }
          }

          PanelSectionHeader {
            text: strings.t("mic.tuning")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          ParamSlider {
            label: strings.t("mic.vad")
            value: root.micState.vad
            lo: 0; hi: 99; stepSize: 1; decimals: 0; unit: "%"
            enabled: root.micState.enabled
            onEdited: function(v) { root.hostWidget.micSet("vad", v) }
          }
          ParamSlider {
            label: strings.t("mic.ratio")
            value: root.micState.ratio
            lo: 1; hi: 10; stepSize: 0.5; decimals: 1; unit: ":1"
            enabled: root.micState.enabled
            onEdited: function(v) { root.hostWidget.micSet("ratio", v) }
          }
          ParamSlider {
            label: strings.t("mic.presence")
            value: root.micState.presence
            lo: -6; hi: 9; stepSize: 0.5; decimals: 1; unit: " dB"
            enabled: root.micState.enabled
            onEdited: function(v) { root.hostWidget.micSet("presence", v) }
          }

          PanelSectionHeader {
            text: strings.t("mic.output")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Strip { key: "mic" }
        }

        // ================= Sampler =================
        Column {
          visible: root.tab === "sampler"
          width: parent.width
          spacing: Style.space(10)

          ButtonGroup {
            focusable: false
            foreground: root.foreground
            fontFamily: root.fontFamily
            value: root.viewSet
            options: [
              { value: "1A", label: strings.t("sampler.set").arg("1").arg("A") },
              { value: "1B", label: strings.t("sampler.set").arg("1").arg("B") },
              { value: "2A", label: strings.t("sampler.set").arg("2").arg("A") },
              { value: "2B", label: strings.t("sampler.set").arg("2").arg("B") }
            ]
            onChanged: function(v) { root.viewSet = v }
          }

          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            text: root.hwSetKnown
              ? strings.t("sampler.hwset").arg(root.hwActiveSet.charAt(0)).arg(root.hwActiveSet.charAt(1))
              : strings.t("sampler.hwsetUnknown")
          }

          Row {
            id: padRow
            width: parent.width
            spacing: Style.space(6)

            Repeater {
              model: root.pads
              PadButton {
                required property int modelData
                pad: modelData
                width: (padRow.width - padRow.spacing * 4) / 5
              }
            }
          }

          Row {
            spacing: Style.space(8)

            Button {
              text: strings.t("sampler.play")
              enabled: root.padFile(root.selectedPad) !== ""
              opacity: enabled ? 1.0 : 0.5
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.hostWidget.samplePlay(root.selectedPad, root.viewSet)
            }
            Button {
              text: strings.t("sampler.clear")
              enabled: root.padFile(root.selectedPad) !== ""
              opacity: enabled ? 1.0 : 0.5
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.hostWidget.sampleClear(root.selectedPad, root.viewSet)
            }
            Button {
              text: strings.t("sampler.stop")
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.hostWidget.sampleStop()
            }
          }

          Item {
            width: parent.width
            implicitHeight: Math.max(listenText.implicitHeight, listenSwitch.implicitHeight)

            Column {
              id: listenText
              anchors.left: parent.left
              anchors.right: listenSwitch.left
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: strings.t("sampler.hwpads")
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                elide: Text.ElideRight
              }
              Text {
                width: parent.width
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                text: !root.mixer || !root.mixer.padsConfigured
                  ? strings.t("sampler.nopatterns")
                  : (root.listener.active ? strings.t("sampler.listening") : strings.t("sampler.stopped"))
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
            }

            ToggleSwitch {
              id: listenSwitch
              checked: root.listener.enabled
              foreground: root.foreground
              accent: Color.accent
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              onToggled: root.hostWidget.setListener(!root.listener.enabled)
            }
          }

          PanelSeparator { foreground: root.foreground }

          Item {
            width: parent.width
            implicitHeight: Math.max(libHeader.implicitHeight, openBtn.implicitHeight)

            PanelSectionHeader {
              id: libHeader
              text: strings.t("sampler.library")
              foreground: root.foreground
              fontFamily: root.fontFamily
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }
            Button {
              id: openBtn
              text: strings.t("sampler.openFolder")
              foreground: root.foreground
              fontFamily: root.fontFamily
              fontSize: Style.font.bodySmall
              bordered: true
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              onClicked: root.hostWidget.openSampleDir()
            }
          }

          Text {
            visible: !root.mixer || root.mixer.samples.length === 0
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("sampler.empty").arg(root.mixer ? root.mixer.sampleDir : "")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Flickable {
            id: libFlick
            visible: !!root.mixer && root.mixer.samples.length > 0
            width: parent.width
            height: Math.min(libCol.implicitHeight, Style.space(190))
            contentWidth: width
            contentHeight: libCol.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Column {
              id: libCol
              width: libFlick.width
              spacing: Style.space(4)

              Repeater {
                model: root.mixer ? root.mixer.samples : []
                SampleRow {
                  required property string modelData
                  fileName: modelData
                }
              }
            }
          }
        }

        // ================= Routing =================
        Column {
          visible: root.tab === "routing"
          width: parent.width
          spacing: Style.space(8)

          DeviceNotice { }

          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("routing.hint")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          // Cabecera de fuentes
          Row {
            id: matrixHead
            width: parent.width
            readonly property real labelW: Style.space(64)
            readonly property real cellW: (width - labelW) / 6
            Item { width: matrixHead.labelW; height: 1 }
            Repeater {
              model: root.srcs
              Text {
                required property string modelData
                width: matrixHead.cellW
                horizontalAlignment: Text.AlignHCenter
                textFormat: Text.PlainText
                text: strings.t("src." + modelData)
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                elide: Text.ElideRight
              }
            }
          }

          Repeater {
            model: root.dests
            Row {
              id: matrixRow
              required property string modelData
              width: parent.width
              Text {
                width: matrixHead.labelW
                height: Style.space(40)
                verticalAlignment: Text.AlignVCenter
                textFormat: Text.PlainText
                text: strings.t("dest." + matrixRow.modelData)
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                font.bold: true
                elide: Text.ElideRight
              }
              Repeater {
                model: root.srcs
                RouteCell {
                  required property string modelData
                  width: matrixHead.cellW
                  height: Style.space(40)
                  dest: matrixRow.modelData
                  src: modelData
                }
              }
            }
          }

          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: root.hoverCell !== "" ? root.foreground : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            text: root.hoverCell !== "" ? root.hoverCell : strings.t("routing.usage")
          }

          PanelSeparator { foreground: root.foreground }

          PanelSectionHeader {
            text: strings.t("routing.presets")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Row {
            visible: root.confirmPreset === ""
            spacing: Style.space(8)
            Button {
              text: strings.t("routing.default")
              enabled: root.devOk
              opacity: enabled ? 1.0 : 0.5
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.confirmPreset = "default"
            }
            Button {
              text: strings.t("routing.noChat")
              enabled: root.devOk
              opacity: enabled ? 1.0 : 0.5
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.confirmPreset = "no_chat_to_stream"
            }
          }

          Column {
            visible: root.confirmPreset !== ""
            width: parent.width
            spacing: Style.space(6)
            Text {
              width: parent.width
              textFormat: Text.PlainText
              wrapMode: Text.WordWrap
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              text: strings.t("routing.confirm").arg(root.confirmPreset === "default" ? strings.t("routing.default") : strings.t("routing.noChat"))
            }
            Row {
              spacing: Style.space(8)
              Button {
                text: strings.t("routing.apply")
                foreground: root.foreground
                fontFamily: root.fontFamily
                bordered: true
                selected: true
                onClicked: {
                  var name = root.confirmPreset
                  root.confirmPreset = ""
                  if (root.hostWidget) root.hostWidget.routingPreset(name)
                }
              }
              Button {
                text: strings.t("routing.cancel")
                foreground: root.foreground
                fontFamily: root.fontFamily
                bordered: true
                onClicked: root.confirmPreset = ""
              }
            }
          }
        }

        // ================= Lights =================
        Column {
          visible: root.tab === "lights"
          width: parent.width
          spacing: Style.space(8)

          DeviceNotice { }

          PanelSectionHeader {
            text: strings.t("lights.presets")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Text {
            visible: !root.hostWidget || root.hostWidget.ledPresets.length === 0
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("lights.noPresets")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Flickable {
            id: presetFlick
            visible: !!root.hostWidget && root.hostWidget.ledPresets.length > 0
            width: parent.width
            height: Math.min(presetFlow.implicitHeight, Style.space(92))
            contentWidth: width
            contentHeight: presetFlow.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Flow {
              id: presetFlow
              width: presetFlick.width
              spacing: Style.space(6)
              Repeater {
                model: root.hostWidget ? root.hostWidget.ledPresets : []
                Button {
                  required property string modelData
                  text: modelData
                  enabled: root.devOk
                  opacity: enabled ? 1.0 : 0.5
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  fontSize: Style.font.bodySmall
                  bordered: true
                  onClicked: root.hostWidget.applyLedPreset(modelData)
                }
              }
            }
          }

          PanelSeparator { foreground: root.foreground }

          Item {
            width: parent.width
            implicitHeight: Math.max(ctlHeader.implicitHeight, idleTitle.implicitHeight)

            PanelSectionHeader {
              id: ctlHeader
              text: strings.t("lights.controls")
              foreground: root.foreground
              fontFamily: root.fontFamily
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }
            Text {
              id: idleTitle
              textFormat: Text.PlainText
              text: strings.t("lights.active") + "   " + strings.t("lights.idle")
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              anchors.right: parent.right
              anchors.rightMargin: Style.space(2)
              anchors.verticalCenter: parent.verticalCenter
            }
          }

          Text {
            visible: !root.ledControls
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("lights.noData")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Flickable {
            id: ledFlick
            visible: !!root.ledControls
            width: parent.width
            height: Math.min(ledCol.implicitHeight, Style.space(176))
            contentWidth: width
            contentHeight: ledCol.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Column {
              id: ledCol
              width: ledFlick.width
              spacing: Style.space(4)
              Repeater {
                model: root.ledControls ? Object.keys(root.ledControls) : []
                Item {
                  id: ledRow
                  required property string modelData
                  width: ledCol.width
                  height: Style.space(28)
                  opacity: root.devOk ? 1.0 : 0.5

                  Text {
                    anchors.left: parent.left
                    anchors.right: idleSw.left
                    anchors.rightMargin: Style.space(8)
                    anchors.verticalCenter: parent.verticalCenter
                    textFormat: Text.PlainText
                    text: root.ledLabel(ledRow.modelData)
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: root.ledEdit === ledRow.modelData
                    elide: Text.ElideRight
                  }
                  Swatch {
                    id: idleSw
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    index: root.ledValue(ledRow.modelData, "idle")
                    selected: root.ledEdit === ledRow.modelData && root.ledSlot === "idle"
                    onClicked: { root.ledEdit = ledRow.modelData; root.ledSlot = "idle" }
                  }
                  Swatch {
                    anchors.right: idleSw.left
                    anchors.rightMargin: Style.space(10)
                    anchors.verticalCenter: parent.verticalCenter
                    index: root.ledValue(ledRow.modelData, "active")
                    selected: root.ledEdit === ledRow.modelData && root.ledSlot === "active"
                    onClicked: { root.ledEdit = ledRow.modelData; root.ledSlot = "active" }
                  }
                }
              }
            }
          }

          Column {
            visible: root.ledEdit !== "" && !!root.ledControls
            width: parent.width
            spacing: Style.space(6)

            Item {
              width: parent.width
              implicitHeight: Math.max(pickTitle.implicitHeight, pickClose.implicitHeight)
              Text {
                id: pickTitle
                anchors.left: parent.left
                anchors.right: pickClose.left
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: strings.t("lights.pick").arg(root.ledLabel(root.ledEdit)).arg(root.ledSlot === "active" ? strings.t("lights.active") : strings.t("lights.idle"))
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
              }
              Button {
                id: pickClose
                text: "✕"
                foreground: root.foreground
                fontFamily: root.fontFamily
                fontSize: Style.font.bodySmall
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                onClicked: root.ledEdit = ""
              }
            }

            Flickable {
              id: palFlick
              width: parent.width
              height: Math.min(palFlow.implicitHeight, Style.space(104))
              contentWidth: width
              contentHeight: palFlow.implicitHeight
              clip: true
              boundsBehavior: Flickable.StopAtBounds

              Flow {
                id: palFlow
                width: palFlick.width
                spacing: Style.space(4)
                Repeater {
                  model: root.paletteKeys
                  Swatch {
                    required property string modelData
                    index: Number(modelData)
                    selected: root.ledValue(root.ledEdit, root.ledSlot) === Number(modelData)
                    onClicked: root.pickLed(Number(modelData))
                  }
                }
              }
            }
          }
        }

        // ================= Device =================
        Column {
          visible: root.tab === "device"
          width: parent.width
          spacing: Style.space(10)

          Row {
            spacing: Style.space(8)
            Text {
              textFormat: Text.PlainText
              text: root.devConnected ? "\u25CF" : "\u25CC"
              color: root.devConnected ? Color.accent : (root.devOk ? root.urgentColor : root.dim)
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              anchors.verticalCenter: parent.verticalCenter
            }
            Text {
              textFormat: Text.PlainText
              text: !root.devOk ? strings.t("dev.unavailable")
                : (root.devConnected ? strings.t("dev.connected") : strings.t("dev.disconnected"))
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
              anchors.verticalCenter: parent.verticalCenter
            }
          }

          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            text: !root.devOk
              ? (root.hostWidget && root.hostWidget.devError !== "" ? root.hostWidget.devError : strings.t("dev.unavailableHint"))
              : (root.dev && typeof root.dev.updated === "number" && root.dev.updated > 0
                  ? strings.t("dev.updated").arg(Qt.formatTime(new Date(root.dev.updated * 1000), "hh:mm:ss"))
                  : strings.t("dev.neverRead"))
          }

          Row {
            spacing: Style.space(8)
            Button {
              text: root.hostWidget && root.hostWidget.devRefreshing ? strings.t("dev.refreshing") : strings.t("dev.refresh")
              enabled: !!root.hostWidget && !root.hostWidget.devRefreshing
              opacity: enabled ? 1.0 : 0.6
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.hostWidget.devRefreshFromDevice()
            }
          }

          PanelSeparator { foreground: root.foreground }

          Item {
            width: parent.width
            implicitHeight: Math.max(phText.implicitHeight, phSwitch.implicitHeight)

            Column {
              id: phText
              anchors.left: parent.left
              anchors.right: phSwitch.left
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)
              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: strings.t("dev.phantom")
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
              }
              Text {
                width: parent.width
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                text: strings.t("dev.phantomWarn")
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
            }

            ToggleSwitch {
              id: phSwitch
              checked: !!root.dev && Number(root.dev.phantom) === 1
              enabled: root.devOk && !!root.dev && (root.dev.phantom === 0 || root.dev.phantom === 1)
              opacity: enabled ? 1.0 : 0.5
              foreground: root.foreground
              accent: Color.accent
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              onToggled: root.hostWidget.setPhantom(!phSwitch.checked)
            }
          }

          Text {
            visible: !!root.dev && root.dev.phantom === null
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("dev.phantomUnknown")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        // ================= FX (solo lectura) =================
        Column {
          visible: root.tab === "fx"
          width: parent.width
          spacing: Style.space(8)

          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("fx.hint")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Text {
            visible: !!root.hostWidget && (root.hostWidget.fxError !== "" || root.hostWidget.fxDown)
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: root.hostWidget && root.hostWidget.fxError !== "" ? root.hostWidget.fxError : strings.t("fx.unavailable")
            color: root.urgentColor
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          PanelSectionHeader {
            text: strings.t("fx.voice")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Text {
            visible: !!root.hostWidget && root.hostWidget.fxPresetsSeen && root.fxVoice.length === 0
              && root.hostWidget.fxError === "" && !root.hostWidget.fxDown
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("fx.emptyVoice")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Flickable {
            id: voiceFlick
            visible: root.fxVoice.length > 0
            width: parent.width
            height: Math.min(voiceFlow.implicitHeight, Style.space(92))
            contentWidth: width
            contentHeight: voiceFlow.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Flow {
              id: voiceFlow
              width: voiceFlick.width
              spacing: Style.space(6)
              Repeater {
                model: root.fxVoice
                Button {
                  required property string modelData
                  text: modelData
                  selected: root.fxPickKind === "voice" && root.fxPickName === modelData
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  fontSize: Style.font.bodySmall
                  bordered: true
                  onClicked: if (root.hostWidget) root.hostWidget.loadFxPreset("voice", modelData)
                }
              }
            }
          }

          PanelSectionHeader {
            text: strings.t("fx.mic")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Text {
            visible: !!root.hostWidget && root.hostWidget.fxPresetsSeen && root.fxMic.length === 0
              && root.hostWidget.fxError === "" && !root.hostWidget.fxDown
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("fx.emptyMic")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Flickable {
            id: micFxFlick
            visible: root.fxMic.length > 0
            width: parent.width
            height: Math.min(micFxFlow.implicitHeight, Style.space(92))
            contentWidth: width
            contentHeight: micFxFlow.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Flow {
              id: micFxFlow
              width: micFxFlick.width
              spacing: Style.space(6)
              Repeater {
                model: root.fxMic
                Button {
                  required property string modelData
                  text: modelData
                  selected: root.fxPickKind === "mic" && root.fxPickName === modelData
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  fontSize: Style.font.bodySmall
                  bordered: true
                  onClicked: if (root.hostWidget) root.hostWidget.loadFxPreset("mic", modelData)
                }
              }
            }
          }

          Text {
            visible: root.fxPickKind === "" && (root.fxVoice.length > 0 || root.fxMic.length > 0)
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("fx.pick")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Column {
            visible: root.fxPickKind !== ""
            width: parent.width
            spacing: Style.space(6)

            Text {
              visible: !!root.hostWidget && (root.hostWidget.fxDetailError !== "" || root.hostWidget.fxDetailDown)
              width: parent.width
              textFormat: Text.PlainText
              wrapMode: Text.WordWrap
              text: root.hostWidget && root.hostWidget.fxDetailError !== "" ? root.hostWidget.fxDetailError : strings.t("fx.unavailable")
              color: root.urgentColor
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
            Text {
              visible: !!root.hostWidget && root.hostWidget.fxDetailLoading && !root.fxDetail
              width: parent.width
              textFormat: Text.PlainText
              text: strings.t("fx.loading")
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
            Text {
              visible: !!root.hostWidget && root.fxPickKind !== "" && !root.hostWidget.fxDetailLoading && !!root.fxDetail
                && root.fxEffectLines.length === 0 && root.fxRecordLines.length === 0
                && root.hostWidget.fxDetailError === "" && !root.hostWidget.fxDetailDown
              width: parent.width
              textFormat: Text.PlainText
              wrapMode: Text.WordWrap
              text: strings.t("fx.detailEmpty")
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            PanelSectionHeader {
              visible: root.fxEffectLines.length > 0
              text: strings.t("fx.effects")
              foreground: root.foreground
              fontFamily: root.fontFamily
            }
            Flickable {
              id: fxEffectFlick
              visible: root.fxEffectLines.length > 0
              width: parent.width
              height: Math.min(fxEffectCol.implicitHeight, Style.space(120))
              contentWidth: width
              contentHeight: fxEffectCol.implicitHeight
              clip: true
              boundsBehavior: Flickable.StopAtBounds
              Column {
                id: fxEffectCol
                width: fxEffectFlick.width
                spacing: Style.space(2)
                Repeater {
                  model: root.fxEffectLines
                  Text {
                    required property string modelData
                    width: parent.width
                    textFormat: Text.PlainText
                    text: modelData
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    elide: Text.ElideRight
                  }
                }
              }
            }

            PanelSectionHeader {
              visible: root.fxRecordLines.length > 0
              text: strings.t("fx.records")
              foreground: root.foreground
              fontFamily: root.fontFamily
            }
            Flickable {
              id: fxRecFlick
              visible: root.fxRecordLines.length > 0
              width: parent.width
              height: Math.min(fxRecCol.implicitHeight, Style.space(120))
              contentWidth: width
              contentHeight: fxRecCol.implicitHeight
              clip: true
              boundsBehavior: Flickable.StopAtBounds
              Column {
                id: fxRecCol
                width: fxRecFlick.width
                spacing: Style.space(2)
                Repeater {
                  model: root.fxRecordLines
                  Text {
                    required property string modelData
                    width: parent.width
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    text: modelData
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.bodySmall
                  }
                }
              }
            }
          }

          PanelSeparator { foreground: root.foreground }

          PanelSectionHeader {
            text: strings.t("fx.current")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("fx.currentHint")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
          Text {
            visible: !!root.hostWidget && (root.hostWidget.fxNowError !== "" || root.hostWidget.fxNowDown)
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: root.hostWidget && root.hostWidget.fxNowError !== "" ? root.hostWidget.fxNowError : strings.t("fx.unavailable")
            color: root.urgentColor
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Text {
            visible: !!root.hostWidget && root.hostWidget.fxNowSeen && root.fxNowRows.length === 0
              && root.hostWidget.fxNowError === "" && !root.hostWidget.fxNowDown
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("fx.noCurrent")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Flickable {
            id: fxNowFlick
            visible: root.fxNowRows.length > 0
            width: parent.width
            height: Math.min(fxNowCol.implicitHeight, Style.space(160))
            contentWidth: width
            contentHeight: fxNowCol.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
              id: fxNowCol
              width: fxNowFlick.width
              spacing: Style.space(6)
              Repeater {
                model: root.fxNowRows
                FxRow {
                  required property var modelData
                  label: String(modelData.label || "")
                  value: String(modelData.value || "")
                  labeled: modelData.labeled === true
                }
              }
            }
          }
        }

        // ================= Apps =================
        Column {
          visible: root.tab === "apps"
          width: parent.width
          spacing: Style.space(8)

          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("apps.hint")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Item {
            width: parent.width
            implicitHeight: Math.max(watchText.implicitHeight, watchSwitch.implicitHeight)

            Column {
              id: watchText
              anchors.left: parent.left
              anchors.right: watchSwitch.left
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)
              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: strings.t("apps.watch")
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                elide: Text.ElideRight
              }
              Text {
                width: parent.width
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                text: root.hostWidget && root.hostWidget.appsWatch ? strings.t("apps.watching") : strings.t("apps.stopped")
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
            }

            ToggleSwitch {
              id: watchSwitch
              checked: !!root.hostWidget && root.hostWidget.appsWatch
              foreground: root.foreground
              accent: Color.accent
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              onToggled: if (root.hostWidget) root.hostWidget.setAppsWatch(!root.hostWidget.appsWatch)
            }
          }

          Text {
            visible: !!root.hostWidget && (root.hostWidget.appsError !== "" || root.hostWidget.appsDown)
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: root.hostWidget && root.hostWidget.appsError !== "" ? root.hostWidget.appsError : strings.t("apps.unavailable")
            color: root.urgentColor
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          PanelSectionHeader {
            text: strings.t("apps.rules")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Text {
            visible: !!root.hostWidget && root.hostWidget.appRulesSeen && root.appRules.length === 0
              && root.hostWidget.appsError === "" && !root.hostWidget.appsDown
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("apps.empty")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Flickable {
            id: ruleFlick
            visible: root.appRules.length > 0
            width: parent.width
            height: Math.min(ruleCol.implicitHeight, Style.space(160))
            contentWidth: width
            contentHeight: ruleCol.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
              id: ruleCol
              width: ruleFlick.width
              spacing: Style.space(4)
              Repeater {
                model: root.appRules
                RuleRow {
                  required property var modelData
                  match: String(modelData.match || "")
                  field: String(modelData.field || "")
                  sink: String(modelData.sink || "")
                }
              }
            }
          }

          PanelSeparator { foreground: root.foreground }

          PanelSectionHeader {
            text: strings.t("apps.addHeader")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          TextField {
            id: appsMatch
            width: parent.width
            placeholderText: strings.t("apps.matchPlaceholder")
            foreground: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            maximumLength: 80
            onTextChanged: root.appsMatchReject = false
            onAccepted: root.submitAppRule()
            Keys.onEscapePressed: function(event) { focus = false; event.accepted = true }
          }
          Text {
            textFormat: Text.PlainText
            text: strings.t("apps.where")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
          }
          ButtonGroup {
            focusable: false
            foreground: root.foreground
            fontFamily: root.fontFamily
            value: root.appsField
            options: [
              { value: "binary", label: strings.t("apps.field.binary") },
              { value: "name", label: strings.t("apps.field.name") },
              { value: "both", label: strings.t("apps.field.both") }
            ]
            onChanged: function(v) { root.appsField = v }
          }
          Text {
            textFormat: Text.PlainText
            text: strings.t("apps.output")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
          }
          Row {
            id: sinkPick
            width: parent.width
            spacing: Style.space(4)
            Repeater {
              model: root.outKeys
              Button {
                required property string modelData
                width: (sinkPick.width - sinkPick.spacing * 3) / 4
                text: strings.t("node." + modelData)
                selected: root.appsSink === modelData
                bordered: true
                foreground: root.foreground
                fontFamily: root.fontFamily
                fontSize: Style.font.bodySmall
                horizontalPadding: Style.space(4)
                onClicked: root.appsSink = modelData
              }
            }
          }
          Row {
            spacing: Style.space(8)
            Button {
              text: strings.t("apps.add")
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.submitAppRule()
            }
          }
          Text {
            visible: root.appsMatchReject
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("apps.matchEmpty")
            color: root.urgentColor
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          PanelSeparator { foreground: root.foreground }

          Button {
            text: root.hostWidget && root.hostWidget.appsApplying ? strings.t("apps.applying") : strings.t("apps.apply")
            enabled: !root.hostWidget || !root.hostWidget.appsApplying
            opacity: enabled ? 1.0 : 0.6
            foreground: root.foreground
            fontFamily: root.fontFamily
            bordered: true
            onClicked: if (root.hostWidget) root.hostWidget.applyApps()
          }
          Text {
            visible: !!root.hostWidget && root.hostWidget.appsApplyError !== ""
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: root.hostWidget ? root.hostWidget.appsApplyError : ""
            color: root.urgentColor
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Text {
            visible: !!root.hostWidget && root.hostWidget.appsMoved >= 0 && root.hostWidget.appsSkipped >= 0
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("apps.result").arg(root.hostWidget ? root.hostWidget.appsMoved : 0).arg(root.hostWidget ? root.hostWidget.appsSkipped : 0)
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Text {
            visible: !!root.hostWidget && root.hostWidget.appsSkipped < 0 && root.hostWidget.appsMoved >= 0 && root.hostWidget.appsFailed >= 0
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("apps.resultFailed").arg(root.hostWidget ? root.hostWidget.appsMoved : 0).arg(root.hostWidget ? root.hostWidget.appsFailed : 0)
            color: root.hostWidget && root.hostWidget.appsFailed > 0 ? root.urgentColor : root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Text {
            visible: !!root.hostWidget && root.hostWidget.appsApplyBare
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("apps.noCounts")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
        }

        // ================= Profiles =================
        Column {
          visible: root.tab === "profiles"
          width: parent.width
          spacing: Style.space(8)

          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("profiles.hint")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          TextField {
            id: profileName
            width: parent.width
            placeholderText: strings.t("profiles.namePlaceholder")
            foreground: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            maximumLength: 41
            onTextChanged: root.profileNameReject = false
            onAccepted: root.submitProfile()
            Keys.onEscapePressed: function(event) { focus = false; event.accepted = true }
          }
          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("profiles.nameHint")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
          Row {
            spacing: Style.space(8)
            Button {
              text: strings.t("profiles.save")
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.submitProfile()
            }
          }
          Text {
            visible: root.profileNameReject
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("profiles.invalid")
            color: root.urgentColor
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Text {
            visible: !!root.hostWidget && (root.hostWidget.profilesError !== "" || root.hostWidget.profilesDown)
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: root.hostWidget && root.hostWidget.profilesError !== "" ? root.hostWidget.profilesError : strings.t("profiles.unavailable")
            color: root.urgentColor
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          PanelSectionHeader {
            text: strings.t("profiles.list")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Text {
            visible: !!root.hostWidget && root.hostWidget.profilesSeen && root.profileNames.length === 0
              && root.hostWidget.profilesError === "" && !root.hostWidget.profilesDown
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: strings.t("profiles.empty")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Flickable {
            id: profileFlick
            visible: root.profileNames.length > 0
            width: parent.width
            height: Math.min(profileCol.implicitHeight, Style.space(160))
            contentWidth: width
            contentHeight: profileCol.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
              id: profileCol
              width: profileFlick.width
              spacing: Style.space(4)
              Repeater {
                model: root.profileNames
                ProfileRow {
                  required property string modelData
                  name: modelData
                }
              }
            }
          }

          Column {
            visible: root.confirmProfile !== ""
            width: parent.width
            spacing: Style.space(6)
            Text {
              width: parent.width
              textFormat: Text.PlainText
              wrapMode: Text.WordWrap
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              text: strings.t("profiles.confirm").arg(root.confirmProfile)
            }
            Row {
              spacing: Style.space(8)
              Button {
                text: strings.t("profiles.load")
                foreground: root.foreground
                fontFamily: root.fontFamily
                bordered: true
                selected: true
                onClicked: {
                  var name = root.confirmProfile
                  root.confirmProfile = ""
                  if (root.hostWidget) root.hostWidget.loadProfile(name)
                }
              }
              Button {
                text: strings.t("routing.cancel")
                foreground: root.foreground
                fontFamily: root.fontFamily
                bordered: true
                onClicked: root.confirmProfile = ""
              }
            }
          }

          PanelSectionHeader {
            visible: root.profileLineList.length > 0 || (!!root.hostWidget && root.hostWidget.profileBusy)
            text: strings.t("profiles.result")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Text {
            visible: !!root.hostWidget && root.hostWidget.profileBusy && root.profileLineList.length === 0
            width: parent.width
            textFormat: Text.PlainText
            text: root.profileWorkingText()
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Repeater {
            model: root.profileLineList
            Text {
              required property var modelData
              width: parent.width
              textFormat: Text.PlainText
              wrapMode: Text.WordWrap
              text: modelData.text
              color: modelData.urgent ? root.urgentColor : root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
          }
        }
      }
    }
  }

  Connections {
    target: root.hostWidget
    function onAppsAdded() {
      appsMatch.text = ""
      root.appsMatchReject = false
    }
  }

  // Un canal: mute · nombre y par · slider · % · salida/entrada por defecto.
  component Strip: Item {
    id: strip
    property string key: "game"
    readonly property var st: root.nodeState(key)
    readonly property bool present: !!st && st.present
    readonly property bool muted: present && st.muted
    readonly property real volume: present ? st.volume / 100 : 0
    readonly property bool isDefault: root.isDefault(key)
    readonly property real pct: slider.dragging ? slider.liveValue : strip.volume

    width: parent.width
    implicitHeight: Style.space(38)
    opacity: present ? 1.0 : 0.4

    Text {
      id: muteIcon
      textFormat: Text.PlainText
      text: strip.muted ? "󰝟" : "󰕾"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
      width: Style.space(24)
      horizontalAlignment: Text.AlignHCenter
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      opacity: strip.muted ? 0.5 : 1.0

      MouseArea {
        anchors.fill: parent
        enabled: strip.present
        cursorShape: Qt.PointingHandCursor
        onClicked: root.hostWidget.toggleMute(strip.key)
      }
    }

    Column {
      id: nameCol
      width: Style.space(116)
      anchors.left: muteIcon.right
      anchors.leftMargin: Style.space(6)
      anchors.verticalCenter: parent.verticalCenter

      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: strings.t("node." + strip.key)
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: strip.isDefault
        elide: Text.ElideRight
      }
      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: root.pairOf(strip.key)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }

    Button {
      id: defaultBtn
      width: Style.space(30)
      text: strip.isDefault ? "●" : "○"
      tooltipText: strip.isDefault ? strings.t("default.current") : strings.t("default.set")
      active: strip.isDefault
      foreground: root.foreground
      fontFamily: root.fontFamily
      horizontalPadding: 0
      enabled: strip.present
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      onClicked: if (!strip.isDefault) root.hostWidget.setDefault(strip.key)
    }

    Text {
      id: pctText
      textFormat: Text.PlainText
      text: Commons.I18n.formatNumber(Math.round(strip.pct * 100)) + "%"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      width: Style.space(38)
      horizontalAlignment: Text.AlignRight
      anchors.right: defaultBtn.left
      anchors.rightMargin: Style.space(4)
      anchors.verticalCenter: parent.verticalCenter
      opacity: strip.muted ? 0.5 : 1.0
    }

    PanelSlider {
      id: slider
      bar: root.bar
      anchors.left: nameCol.right
      anchors.leftMargin: Style.space(8)
      anchors.right: pctText.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      minimum: 0
      maximum: 1
      step: 0.05
      enabled: strip.present
      value: strip.volume
      opacity: strip.muted ? 0.5 : 1.0
      onMoved: function(v) { root.hostWidget.setVolume(strip.key, v) }
      onRightClicked: root.hostWidget.toggleMute(strip.key)
    }
  }

  // Una app: nombre y cuatro botones de salida. `route` marca dónde suena hoy.
  component StreamRow: Column {
    id: row
    property int streamId: 0
    property string streamName: ""
    property string route: "other"

    width: parent.width
    spacing: Style.space(3)

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: row.streamName
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      elide: Text.ElideRight
      opacity: row.route === "other" ? 0.7 : 1.0
    }

    Row {
      id: routes
      width: parent.width
      spacing: Style.space(4)

      Repeater {
        model: root.outKeys
        Button {
          required property string modelData
          width: (routes.width - routes.spacing * 3) / 4
          text: strings.t("node." + modelData)
          selected: row.route === modelData
          bordered: true
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.bodySmall
          horizontalPadding: Style.space(4)
          onClicked: root.hostWidget.moveStream(row.streamId, modelData)
        }
      }
    }
  }

  // Slider con etiqueta y valor para los ajustes del micrófono.
  component ParamSlider: Column {
    id: param
    property string label: ""
    property real value: 0
    property real lo: 0
    property real hi: 1
    property real stepSize: 1
    property int decimals: 0
    property string unit: ""
    signal edited(real v)

    width: parent.width
    spacing: Style.space(2)
    opacity: enabled ? 1.0 : 0.5

    Item {
      width: parent.width
      implicitHeight: Math.max(paramLabel.implicitHeight, paramValue.implicitHeight)

      Text {
        id: paramLabel
        textFormat: Text.PlainText
        text: param.label
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        anchors.left: parent.left
      }
      Text {
        id: paramValue
        textFormat: Text.PlainText
        text: Commons.I18n.formatNumber(paramSlider.dragging ? paramSlider.liveValue : param.value, param.decimals) + param.unit
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        anchors.right: parent.right
      }
    }

    PanelSlider {
      id: paramSlider
      bar: root.bar
      width: parent.width
      minimum: param.lo
      maximum: param.hi
      step: param.stepSize
      value: param.value
      enabled: param.enabled
      onMoved: function(v) { param.edited(Math.round(v / param.stepSize) * param.stepSize) }
    }
  }

  // Aviso en línea cuando no hay respuesta del equipo.
  component DeviceNotice: Text {
    visible: !root.devOk || !root.devConnected
    width: parent.width
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    color: root.devOk ? root.dim : root.urgentColor
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    text: root.devOk ? strings.t("dev.staleNotice") : strings.t("dev.unavailableInline")
  }

  // Muestra de color de la paleta de LEDs; sin RGB conocido, el número.
  component Swatch: Rectangle {
    id: sw
    property int index: -1
    property bool selected: false
    readonly property string hex: index >= 0 ? root.paletteColor(index) : ""
    signal clicked()
    width: Style.space(22)
    height: Style.space(22)
    radius: Math.min(Style.cornerRadius, Style.space(5))
    color: hex !== "" ? hex : Qt.alpha(root.foreground, 0.1)
    border.width: selected ? 2 : 1
    border.color: selected ? root.foreground : Qt.alpha(root.foreground, 0.3)
    Text {
      visible: sw.hex === ""
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: sw.index >= 0 ? String(sw.index) : "–"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: sw.clicked()
    }
  }

  // Una celda de la matriz de ruteo: clic enciende/apaga, arrastrar o rueda ajusta la ganancia.
  component RouteCell: Item {
    id: cell
    property string dest: "stream"
    property string src: "mic"
    readonly property int g: root.gainOf(dest, src)
    readonly property bool known: g >= 0
    readonly property bool on: known && g > 0
    readonly property bool muted: root.isMuted(dest, src)
    readonly property string desc: strings.t("dest." + dest) + " ← " + strings.t("src." + src)
      + " · " + (known ? (on ? String(g) + " / 127" : strings.t("routing.off")) : "–")
      + (muted ? " · " + strings.t("routing.hwMuted") : "")

    Rectangle {
      id: face
      anchors.fill: parent
      anchors.margins: 2
      radius: Math.min(Style.cornerRadius, Style.space(6))
      color: Qt.alpha(root.foreground, area.containsMouse ? 0.12 : 0.06)
      border.width: 1
      border.color: cell.muted ? root.urgentColor : Qt.alpha(root.foreground, cell.on ? 0.3 : 0.14)
      clip: true

      Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: cell.on ? parent.height * cell.g / 127 : 0
        color: Qt.alpha(Color.accent, cell.muted ? 0.22 : 0.5)
      }
      // Marca de ganancia unidad (115)
      Rectangle {
        visible: cell.known
        anchors.left: parent.left
        anchors.right: parent.right
        y: parent.height * (1 - 115 / 127)
        height: 1
        color: Qt.alpha(root.foreground, 0.55)
      }
      Text {
        anchors.centerIn: parent
        textFormat: Text.PlainText
        text: !cell.known ? "–" : (cell.on ? String(cell.g) : strings.t("routing.offShort"))
        color: cell.on ? root.foreground : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: cell.on
        opacity: cell.muted ? 0.6 : 1.0
      }
      // Silenciado desde un botón físico
      Text {
        visible: cell.muted
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Style.space(2)
        textFormat: Text.PlainText
        text: "󰝟"
        color: root.urgentColor
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    MouseArea {
      id: area
      anchors.fill: parent
      enabled: cell.known
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      property real pressY: 0
      property int startGain: 0
      property bool moved: false
      function snap(v) { return Math.abs(v - 115) <= 3 ? 115 : v }
      onEntered: root.hoverCell = cell.desc
      onExited: root.hoverCell = ""
      onPressed: function(m) { pressY = m.y; startGain = cell.g; moved = false }
      onPositionChanged: function(m) {
        if (!pressed) return
        var dy = pressY - m.y
        if (!moved && Math.abs(dy) < 5) return
        moved = true
        var v = snap(Math.round(Math.max(0, Math.min(127, startGain + dy / (cell.height * 2.5) * 127))))
        if (v !== cell.g) root.hostWidget.setGain(cell.dest, cell.src, v)
      }
      onReleased: if (!moved) root.hostWidget.toggleRoute(cell.dest, cell.src)
      onWheel: function(w) {
        var v = Math.max(0, Math.min(127, cell.g + (w.angleDelta.y > 0 ? 4 : -4)))
        v = snap(v)
        if (v !== cell.g) root.hostWidget.setGain(cell.dest, cell.src, v)
      }
    }
    onDescChanged: if (area.containsMouse) root.hoverCell = desc
  }

  // Estado de un botón físico (mute). Solo lectura: sale del equipo (device.json) y, si no hay dato, de hw.json.
  component HwChip: Row {
    id: chip
    property string name: "mic_mute"
    readonly property var devValue: root.dev && root.dev.buttons ? root.dev.buttons[name] : null
    readonly property var hwValue: root.mixer && root.mixer.hw ? root.mixer.hw[name] : null
    readonly property var value: devValue !== null && devValue !== undefined ? devValue : hwValue
    readonly property color tint: value === true ? (root.bar ? root.bar.urgent : "#e06c75")
      : (value === false ? root.foreground : root.dim)
    spacing: Style.space(5)

    Text {
      textFormat: Text.PlainText
      text: chip.value === null || chip.value === undefined ? "\u25CC" : "\u25CF"
      color: chip.tint
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      anchors.verticalCenter: parent.verticalCenter
    }
    Text {
      textFormat: Text.PlainText
      text: strings.t("hw." + chip.name)
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      anchors.verticalCenter: parent.verticalCenter
    }
    Text {
      textFormat: Text.PlainText
      text: chip.value === true ? strings.t("hw.muted")
        : (chip.value === false ? strings.t("hw.live") : strings.t("hw.unknown"))
      color: chip.tint
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: chip.value === true
      anchors.verticalCenter: parent.verticalCenter
    }
  }

  // Pad del sampler: número y archivo asignado. Tocarlo lo selecciona y lo reproduce.
  component PadButton: Item {
    id: padItem
    property int pad: 1
    readonly property string file: root.padFile(pad)

    implicitHeight: Style.space(58)
    height: implicitHeight

    Button {
      anchors.fill: parent
      text: ""
      bordered: true
      selected: root.selectedPad === padItem.pad
      foreground: root.foreground
      fontFamily: root.fontFamily
      onClicked: {
        root.selectedPad = padItem.pad
        if (padItem.file !== "") root.hostWidget.samplePlay(padItem.pad, root.viewSet)
      }
    }

    Column {
      anchors.centerIn: parent
      width: parent.width - Style.space(8)
      spacing: Style.space(2)
      enabled: false

      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        text: Commons.I18n.formatNumber(padItem.pad)
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
      }
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        text: padItem.file !== "" ? padItem.file : "—"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideMiddle
      }
    }
  }

  // Un archivo de la biblioteca: reproducir y asignar al pad elegido.
  component SampleRow: Item {
    id: sample
    property string fileName: ""

    width: parent.width
    implicitHeight: assignBtn.implicitHeight

    Text {
      textFormat: Text.PlainText
      text: sample.fileName
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      elide: Text.ElideMiddle
      anchors.left: parent.left
      anchors.right: previewBtn.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      font.bold: root.padFile(root.selectedPad) === sample.fileName
    }

    Button {
      id: previewBtn
      text: "▶"
      tooltipText: strings.t("sampler.preview")
      foreground: root.foreground
      fontFamily: root.fontFamily
      bordered: true
      anchors.right: assignBtn.left
      anchors.rightMargin: Style.space(4)
      anchors.verticalCenter: parent.verticalCenter
      onClicked: root.hostWidget.samplePreview(sample.fileName)
    }

    Button {
      id: assignBtn
      text: strings.t("sampler.assign").arg(Commons.I18n.formatNumber(root.selectedPad))
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      bordered: true
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      onClicked: root.hostWidget.sampleAssign(root.selectedPad, sample.fileName, root.viewSet)
    }
  }

  // Lectura de un knob o bloque. Sin etiqueta, el id y el valor crudo.
  component FxRow: Column {
    id: fxRow
    property string label: ""
    property string value: ""
    property bool labeled: false

    width: parent.width
    spacing: Style.space(1)

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: fxRow.label !== "" ? fxRow.label : strings.t("fx.unnamed")
      color: fxRow.labeled ? root.foreground : root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      font.bold: fxRow.labeled
      elide: Text.ElideRight
    }
    Text {
      width: parent.width
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      text: fxRow.value
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  // Una regla: texto, dónde busca y a qué salida manda. Quitar no manda un match vacío.
  component RuleRow: Item {
    id: rule
    property string match: ""
    property string field: ""
    property string sink: ""

    width: parent.width
    implicitHeight: Math.max(ruleMatch.implicitHeight, ruleRemove.implicitHeight)

    Text {
      id: ruleMatch
      anchors.left: parent.left
      anchors.right: ruleMeta.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: rule.match
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      elide: Text.ElideRight
    }
    Text {
      id: ruleMeta
      anchors.right: ruleRemove.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: strings.t("apps.field." + rule.field, rule.field) + " · " + strings.t("node." + rule.sink, rule.sink)
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
    Button {
      id: ruleRemove
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: strings.t("apps.remove")
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      bordered: true
      onClicked: if (root.hostWidget) root.hostWidget.removeAppRule(rule.match, rule.field)
    }
  }

  // Un perfil guardado. Cargar pide confirmación; borrar no toca la alimentación fantasma.
  component ProfileRow: Item {
    id: profile
    property string name: ""

    width: parent.width
    implicitHeight: Math.max(profileLabel.implicitHeight, profileLoad.implicitHeight)

    Text {
      id: profileLabel
      anchors.left: parent.left
      anchors.right: profileLoad.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: profile.name
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      font.bold: root.confirmProfile === profile.name
      elide: Text.ElideRight
    }
    Button {
      id: profileDelete
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: strings.t("profiles.delete")
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      bordered: true
      onClicked: {
        if (root.confirmProfile === profile.name) root.confirmProfile = ""
        if (root.hostWidget) root.hostWidget.deleteProfile(profile.name)
      }
    }
    Button {
      id: profileLoad
      anchors.right: profileDelete.left
      anchors.rightMargin: Style.space(6)
      anchors.verticalCenter: parent.verticalCenter
      text: strings.t("profiles.load")
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      bordered: true
      selected: root.confirmProfile === profile.name
      onClicked: root.confirmProfile = profile.name
    }
  }
}
