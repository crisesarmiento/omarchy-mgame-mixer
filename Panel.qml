import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui

Panel {
  id: root
  moduleName: "csarmiento.mgame-mixer"
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
          onChanged: function(v) { root.tab = v }
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
      }
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
}
