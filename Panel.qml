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
    if (hostWidget) hostWidget.refresh()
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
            { value: "sampler", label: strings.t("tab.sampler") }
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
            visible: !root.listener.active
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

  // Estado de un botón físico con memoria (mute). Solo lectura: "desconocido" hasta la primera pulsación.
  component HwChip: Row {
    id: chip
    property string name: "mic_mute"
    readonly property var value: root.mixer && root.mixer.hw ? root.mixer.hw[name] : null
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
