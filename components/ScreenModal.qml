import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import qs.Commons
import qs.Ui

Rectangle {
  id: rootScreenModal
  visible: false
  anchors.fill: parent
  color: Util.alpha(Color.background, 0.85)
  z: 50

  property var bar: null
  property bool englishMode: false
  property string currentScreenTitle: ""
  property var currentScreenFacility: null

  property var getScreenDisplayName: function(name) { return name }
  property var getSeatRows: function(seats) { return [] }
  property var openExternalUrl: function(url) {}

  signal closed()

  MouseArea {
    anchors.fill: parent
    onClicked: rootScreenModal.closed()
  }

  Rectangle {
    id: screenModalCard
    anchors.centerIn: parent
    width: Math.min(parent.width - Style.space(28), Style.space(380))
    implicitHeight: modalColumn.implicitHeight + Style.space(28)
    radius: Style.space(8)
    color: (typeof Color.surface !== "undefined" && Color.surface) ? Color.surface : (rootScreenModal.bar ? rootScreenModal.bar.background : Color.background)
    border.color: Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.15)
    border.width: 1

    MouseArea {
      // カード内部クリックの伝播を防止
      anchors.fill: parent
      onClicked: function(mouse) { mouse.accepted = true }
    }

    Column {
      id: modalColumn
      anchors.top: parent.top
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.margins: Style.space(14)
      spacing: Style.space(10)

      // 1. ヘッダー: スクリーン名 & ✕ボタン
      RowLayout {
        width: parent.width

        RowLayout {
          spacing: Style.space(6)
          Text {
            text: "🎦"
            font.pixelSize: Style.font ? Style.font.title : 16
          }
          Text {
            text: rootScreenModal.getScreenDisplayName(rootScreenModal.currentScreenTitle || (rootScreenModal.currentScreenFacility ? rootScreenModal.currentScreenFacility.name : ""))
            color: rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.title : 15
            font.bold: true
          }
        }

        Item { Layout.fillWidth: true }

        Rectangle {
          radius: Style.space(4)
          color: closeModalHover.containsMouse ? Util.alpha(Color.accent, 0.2) : "transparent"
          implicitWidth: Style.space(24)
          implicitHeight: Style.space(24)

          Text {
            anchors.centerIn: parent
            text: "✕"
            color: Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.7)
            font.pixelSize: Style.font ? Style.font.caption : 12
            font.bold: true
          }

          MouseArea {
            id: closeModalHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: rootScreenModal.closed()
          }
        }
      }

      // 区切り線
      Rectangle {
        width: parent.width
        height: 1
        color: Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.1)
      }

      // 2. 設備 (Features)
      Column {
        width: parent.width
        spacing: Style.space(6)

        Text {
          text: rootScreenModal.englishMode ? "Features & Audio" : "設備・音響"
          color: Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.7)
          font.pixelSize: Style.font ? Style.font.caption : 11
          font.bold: true
        }

        Flow {
          width: parent.width
          spacing: Style.space(6)

          Repeater {
            model: (rootScreenModal.currentScreenFacility && rootScreenModal.currentScreenFacility.features && rootScreenModal.currentScreenFacility.features.length > 0) ? rootScreenModal.currentScreenFacility.features : []

            delegate: Rectangle {
              radius: Style.space(4)
              color: {
                var name = String(modelData)
                if (name.indexOf("IMAX") !== -1 || name.indexOf("4DX") !== -1 || name.indexOf("Dolby") !== -1 || name.indexOf("THX") !== -1 || name.indexOf("VIVE") !== -1) {
                  return Util.alpha(Color.accent, 0.25)
                }
                return Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.08)
              }
              border.color: {
                var name = String(modelData)
                if (name.indexOf("IMAX") !== -1 || name.indexOf("4DX") !== -1 || name.indexOf("Dolby") !== -1 || name.indexOf("THX") !== -1 || name.indexOf("VIVE") !== -1) {
                  return Util.alpha(Color.accent, 0.6)
                }
                return Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.15)
              }
              border.width: 1
              implicitWidth: featTxt.implicitWidth + Style.space(10)
              implicitHeight: Style.space(22)

              Text {
                id: featTxt
                anchors.centerIn: parent
                text: modelData
                color: rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground
                font.pixelSize: Style.font ? Style.font.caption : 11
                font.bold: true
              }
            }
          }

          // 音響情報 (sound) があればバッジ表示
          Rectangle {
            visible: Boolean(rootScreenModal.currentScreenFacility && rootScreenModal.currentScreenFacility.sound)
            radius: Style.space(4)
            color: Util.alpha(Color.accent, 0.18)
            border.color: Util.alpha(Color.accent, 0.45)
            border.width: 1
            implicitWidth: soundTxt.implicitWidth + Style.space(10)
            implicitHeight: Style.space(22)

            Text {
              id: soundTxt
              anchors.centerIn: parent
              text: "🔊 " + (rootScreenModal.currentScreenFacility ? (rootScreenModal.currentScreenFacility.sound || "") : "")
              color: rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground
              font.pixelSize: Style.font ? Style.font.caption : 11
              font.bold: true
            }
          }

          // スクリーンサイズ (screen_size) があればバッジ表示
          Rectangle {
            visible: Boolean(rootScreenModal.currentScreenFacility && rootScreenModal.currentScreenFacility.screen_size)
            radius: Style.space(4)
            color: Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.08)
            border.color: Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.15)
            border.width: 1
            implicitWidth: sizeTxt.implicitWidth + Style.space(10)
            implicitHeight: Style.space(22)

            Text {
              id: sizeTxt
              anchors.centerIn: parent
              text: "📐 " + (rootScreenModal.currentScreenFacility ? (rootScreenModal.currentScreenFacility.screen_size || "") : "")
              color: rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground
              font.pixelSize: Style.font ? Style.font.caption : 11
              font.bold: true
            }
          }

          Text {
            visible: (!rootScreenModal.currentScreenFacility || !rootScreenModal.currentScreenFacility.features || rootScreenModal.currentScreenFacility.features.length === 0) && (!rootScreenModal.currentScreenFacility || !rootScreenModal.currentScreenFacility.sound)
            text: rootScreenModal.englishMode ? "Standard Screen (No special equipment)" : "標準設備"
            color: Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.5)
            font.pixelSize: Style.font ? Style.font.caption : 11
          }
        }
      }

      // 区切り線
      Rectangle {
        width: parent.width
        height: 1
        color: Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.1)
      }

      // 3. 座席種類と席数
      Column {
        width: parent.width
        spacing: Style.space(6)

        RowLayout {
          width: parent.width
          Text {
            text: rootScreenModal.englishMode ? "Seat Breakdown" : "座席種類と席数"
            color: Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.7)
            font.pixelSize: Style.font ? Style.font.caption : 11
            font.bold: true
          }
          Item { Layout.fillWidth: true }
          Text {
            text: {
              var total = (rootScreenModal.currentScreenFacility && rootScreenModal.currentScreenFacility.total_seats) ? rootScreenModal.currentScreenFacility.total_seats : "-"
              return rootScreenModal.englishMode ? ("Total: " + total + " seats") : ("総座席数: " + total + "席")
            }
            color: Color.accent
            font.pixelSize: Style.font ? Style.font.caption : 11
            font.bold: true
          }
        }

        Column {
          width: parent.width
          spacing: Style.space(4)

          Repeater {
            model: rootScreenModal.getSeatRows(rootScreenModal.currentScreenFacility ? rootScreenModal.currentScreenFacility.seats : null)

            delegate: Rectangle {
              width: parent.width
              implicitHeight: Style.space(22)
              radius: Style.space(4)
              color: Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.05)

              RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Style.space(8)
                anchors.rightMargin: Style.space(8)

                Text {
                  text: modelData.type
                  color: rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground
                  font.pixelSize: Style.font ? Style.font.caption : 11
                }

                Item { Layout.fillWidth: true }

                Text {
                  text: modelData.count + (rootScreenModal.englishMode ? " seats" : " 席")
                  color: rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground
                  font.pixelSize: Style.font ? Style.font.caption : 11
                  font.bold: true
                }
              }
            }
          }

          Text {
            visible: !rootScreenModal.currentScreenFacility || !rootScreenModal.currentScreenFacility.seats
            text: rootScreenModal.englishMode ? "Seat breakdown unavailable" : "座席内訳情報がありません"
            color: Util.alpha(rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground, 0.5)
            font.pixelSize: Style.font ? Style.font.caption : 11
          }
        }
      }

      // 4. 公式座席図リンク
      Rectangle {
        visible: Boolean(rootScreenModal.currentScreenFacility && rootScreenModal.currentScreenFacility.seat_map_url)
        width: parent.width
        implicitHeight: Style.space(26)
        radius: Style.space(4)
        color: seatMapHover.containsMouse ? Util.alpha(Color.accent, 0.3) : Util.alpha(Color.accent, 0.15)
        border.color: Util.alpha(Color.accent, 0.4)
        border.width: 1

        RowLayout {
          anchors.centerIn: parent
          spacing: Style.space(6)
          Text {
            text: "🗺️"
            font.pixelSize: Style.font ? Style.font.caption : 11
          }
          Text {
            text: rootScreenModal.englishMode ? "View Official Seat Map" : "公式座席図を開く"
            color: rootScreenModal.bar ? rootScreenModal.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.caption : 11
            font.bold: true
          }
        }

        MouseArea {
          id: seatMapHover
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: {
            if (rootScreenModal.currentScreenFacility && rootScreenModal.currentScreenFacility.seat_map_url) {
              rootScreenModal.openExternalUrl(rootScreenModal.currentScreenFacility.seat_map_url)
            }
          }
        }
      }
    }
  }
}
