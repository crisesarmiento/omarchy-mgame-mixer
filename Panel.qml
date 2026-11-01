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
  readonly property bool sinksReady: hostWidget ? hostWidget.sinksReady : false
  readonly property bool needsSetup: hostWidget ? hostWidget.needsSetup : false
  readonly property bool pairMismatch: hostWidget ? hostWidget.pairMismatch : false
  readonly property bool busy: hostWidget ? hostWidget.busy : false
  readonly property var streams: mixer && mixer.streams ? mixer.streams.slice(0, 12) : []

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

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(420))
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
        spacing: Style.space(14)

        PanelHero {
          width: parent.width
          title: strings.t("title")
          meta: root.sinksReady ? strings.t("subtitle.ok") : strings.t("subtitle.setup")
          foreground: root.foreground
          fontFamily: root.fontFamily
          iconOpacity: root.sinksReady ? 1.0 : 0.6
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

        PanelSeparator { foreground: root.foreground }

        // ---- Aviso de configuración ----
        Column {
          visible: root.needsSetup
          width: parent.width
          spacing: Style.space(10)

          Text {
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            text: root.pairMismatch
              ? strings.t("setup.mismatch").arg(root.hostWidget.chatPair).arg(root.mixer.installedPair)
              : strings.t("setup.missing")
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
            iconText: "󰕾"
            text: root.busy
              ? strings.t("setup.working")
              : (root.pairMismatch ? strings.t("setup.apply") : strings.t("setup.install"))
            foreground: root.foreground
            fontFamily: root.fontFamily
            bordered: true
            onClicked: if (root.hostWidget) root.hostWidget.installConfig()
          }
        }

        PanelSeparator { visible: root.needsSetup && root.sinksReady; foreground: root.foreground }

        // ---- Canales ----
        Column {
          visible: root.sinksReady
          width: parent.width
          spacing: Style.space(16)

          ChannelStrip { channel: "game"; glyph: "󰊴" }
          ChannelStrip { channel: "chat"; glyph: "󰍩" }
        }

        PanelSeparator { visible: root.sinksReady; foreground: root.foreground }

        // ---- Apps ----
        Column {
          visible: root.sinksReady
          width: parent.width
          spacing: Style.space(8)

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
  }

  // Un canal: ícono (mute) · nombre · % · slider · "usar como salida".
  component ChannelStrip: Column {
    id: strip
    property string channel: "game"
    property string glyph: ""
    readonly property var state: root.mixer ? root.mixer.sinks[channel] : null
    readonly property bool muted: !!state && state.muted
    readonly property real volume: state ? state.volume / 100 : 0
    readonly property bool isDefault: !!root.mixer && root.mixer.default === channel

    width: parent.width
    spacing: Style.space(6)

    Row {
      width: parent.width
      spacing: Style.space(8)

      Text {
        id: stripIcon
        textFormat: Text.PlainText
        text: strip.muted ? "󰝟" : strip.glyph
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        width: Style.space(24)
        horizontalAlignment: Text.AlignHCenter
        anchors.verticalCenter: parent.verticalCenter
        opacity: strip.muted ? 0.5 : 1.0

        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: root.hostWidget.toggleMute(strip.channel)
        }
      }

      Text {
        textFormat: Text.PlainText
        text: strings.t("channel." + strip.channel)
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
        width: parent.width - stripIcon.width - stripPct.width - Style.space(16)
        elide: Text.ElideRight
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        id: stripPct
        textFormat: Text.PlainText
        text: Commons.I18n.formatNumber(Math.round((slider.dragging ? slider.liveValue : strip.volume) * 100)) + "%"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        width: Style.space(40)
        horizontalAlignment: Text.AlignRight
        anchors.verticalCenter: parent.verticalCenter
        opacity: strip.muted ? 0.5 : 1.0
      }
    }

    PanelSlider {
      id: slider
      bar: root.bar
      width: parent.width
      minimum: 0
      maximum: 1
      step: 0.05
      value: strip.volume
      opacity: strip.muted ? 0.5 : 1.0
      onMoved: function(v) { root.hostWidget.setVolume(strip.channel, v) }
      onRightClicked: root.hostWidget.toggleMute(strip.channel)
    }

    Button {
      active: strip.isDefault
      text: strip.isDefault ? strings.t("default.current") : strings.t("default.set")
      iconText: strip.isDefault ? "󰄬" : ""
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      bordered: true
      onClicked: if (!strip.isDefault) root.hostWidget.setDefault(strip.channel)
    }
  }

  // Una app: nombre · [Game] [Chat]. `route` marca dónde suena hoy.
  component StreamRow: Item {
    id: row
    property int streamId: 0
    property string streamName: ""
    property string route: "other"

    width: parent.width
    implicitHeight: Math.max(nameText.implicitHeight, gameBtn.implicitHeight) + Style.space(4)

    Text {
      id: nameText
      textFormat: Text.PlainText
      text: row.streamName
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      elide: Text.ElideRight
      anchors.left: parent.left
      anchors.right: gameBtn.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      opacity: row.route === "other" ? 0.7 : 1.0
    }

    Button {
      id: gameBtn
      text: strings.t("channel.game")
      selected: row.route === "game"
      bordered: true
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      anchors.right: chatBtn.left
      anchors.rightMargin: Style.space(6)
      anchors.verticalCenter: parent.verticalCenter
      onClicked: root.hostWidget.moveStream(row.streamId, "game")
    }

    Button {
      id: chatBtn
      text: strings.t("channel.chat")
      selected: row.route === "chat"
      bordered: true
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      onClicked: root.hostWidget.moveStream(row.streamId, "chat")
    }
  }
}
