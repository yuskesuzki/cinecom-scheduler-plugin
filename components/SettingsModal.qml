import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import qs.Commons
import qs.Ui

Rectangle {
  id: rootSettingsModal
  visible: false
  anchors.fill: parent
  color: Util.alpha(Color.background, 0.85)
  z: 60

  property var bar: null
  property bool englishMode: false
  property string selectedChain: "aeon"
  property string selectedTheater: ""
  property real withinHours: 3.0
  property string selectedDate: "today"
  property bool chainDropdownOpen: false
  property string theaterSearchText: ""
  property var availableChains: []
  property var allTheaters: []

  readonly property var filteredTheaters: {
    var list = []
    var filter = (rootSettingsModal.theaterSearchText || "").trim().toLowerCase()
    for (var i = 0; i < rootSettingsModal.allTheaters.length; i++) {
      var t = rootSettingsModal.allTheaters[i]
      if (!t) continue
      var areaStr = (t.region || t.area || "").toLowerCase()
      var nameStr = (t.name || "").toLowerCase()
      var idStr = (t.id || "").toLowerCase()
      if (filter === "" ||
          nameStr.indexOf(filter) !== -1 ||
          idStr.indexOf(filter) !== -1 ||
          (areaStr && areaStr.indexOf(filter) !== -1)) {
        list.push(t)
      }
    }
    return list
  }

  property var getChainDisplayName: function() { return "" }

  signal chainSelected(string chainId)
  signal theaterSelected(string theaterId, string theaterName)
  signal hoursSelected(real hours)
  signal closed()

  onVisibleChanged: {
    if (visible) {
      Qt.callLater(function() {
        if (typeof searchInput !== "undefined" && searchInput) {
          searchInput.forceActiveFocus()
        }
      })
    } else {
      if (typeof searchInput !== "undefined" && searchInput) {
        searchInput.text = ""
      }
      rootSettingsModal.theaterSearchText = ""
      rootSettingsModal.chainDropdownOpen = false
    }
  }
  MouseArea {
    anchors.fill: parent
    onClicked: rootSettingsModal.closed()
  }

  Rectangle {
    id: settingsModalCard
    anchors.centerIn: parent
    width: Math.min(parent.width - Style.space(24), Style.space(400))
    implicitHeight: settingsModalCol.implicitHeight + Style.space(28)
    radius: Style.space(8)
    color: (typeof Color.surface !== "undefined" && Color.surface) ? Color.surface : (rootSettingsModal.bar ? rootSettingsModal.bar.background : Color.background)
    border.color: Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.18)
    border.width: 1

    MouseArea {
      // カード内部クリックの伝播を防止
      anchors.fill: parent
      onClicked: function(mouse) { mouse.accepted = true }
    }

    Column {
      id: settingsModalCol
      anchors.top: parent.top
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.margins: Style.space(14)
      spacing: Style.space(12)

      // 1. ヘッダー: タイトル & ✕閉じるボタン
      RowLayout {
        width: parent.width

        RowLayout {
          spacing: Style.space(6)
          Text {
            text: "⚙"
            font.pixelSize: Style.font ? Style.font.title : 16
          }
          Text {
            text: rootSettingsModal.englishMode ? "Theater Settings" : "劇場・抽出設定"
            color: rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.title : 15
            font.bold: true
          }
        }

        Item { Layout.fillWidth: true }

        Rectangle {
          radius: Style.space(4)
          color: closeSettingsHover.containsMouse ? Util.alpha(Color.accent, 0.2) : "transparent"
          implicitWidth: Style.space(24)
          implicitHeight: Style.space(24)

          Text {
            anchors.centerIn: parent
            text: "✕"
            color: Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.7)
            font.pixelSize: Style.font ? Style.font.caption : 12
            font.bold: true
          }

          MouseArea {
            id: closeSettingsHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              rootSettingsModal.showSettingsPanel = false
              rootSettingsModal.chainDropdownOpen = false
            }
          }
        }
      }

      // 区切り線
      Rectangle {
        width: parent.width
        height: 1
        color: Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.1)
      }

      // 2. シネコン系列選択
      Column {
        width: parent.width
        spacing: Style.space(4)

        Text {
          text: rootSettingsModal.englishMode ? "Select Cinema Chain:" : "シネコン系列を選択:"
          color: Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.8)
          font.pixelSize: Style.font ? Style.font.caption : 11
          font.bold: true
        }

        // セレクトボックス (トリガーボタン)
        Rectangle {
          id: chainSelectTrigger
          width: parent.width
          implicitHeight: Style.space(30)
          radius: Style.space(4)
          color: chainTriggerHover.containsMouse || rootSettingsModal.chainDropdownOpen
            ? Util.alpha(Color.accent, 0.12)
            : Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.08)
          border.color: rootSettingsModal.chainDropdownOpen
            ? Color.accent
            : Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.25)
          border.width: 1

          RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Style.space(10)
            anchors.rightMargin: Style.space(10)
            spacing: Style.space(6)

            Text {
              Layout.fillWidth: true
              text: rootSettingsModal.getChainDisplayName()
              color: rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground
              font.pixelSize: Style.font ? Style.font.caption : 12
              font.bold: true
              elide: Text.ElideRight
            }

            Text {
              text: rootSettingsModal.chainDropdownOpen ? "▲" : "▼"
              color: rootSettingsModal.chainDropdownOpen ? Color.accent : Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.6)
              font.pixelSize: Style.font ? Style.font.caption : 10
            }
          }

          MouseArea {
            id: chainTriggerHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              rootSettingsModal.chainDropdownOpen = !rootSettingsModal.chainDropdownOpen
            }
          }
        }

        // 展開時の選択肢
        Rectangle {
          id: chainDropdownList
          width: parent.width
          visible: rootSettingsModal.chainDropdownOpen
          radius: Style.space(4)
          color: (typeof Color.surface !== "undefined" && Color.surface) ? Color.surface : (rootSettingsModal.bar ? rootSettingsModal.bar.background : Color.background)
          border.color: Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.2)
          border.width: 1
          implicitHeight: chainOptionsCol.implicitHeight + Style.space(4)

          Column {
            id: chainOptionsCol
            width: parent.width
            anchors.top: parent.top
            anchors.topMargin: Style.space(2)
            spacing: 0

            Repeater {
              model: rootSettingsModal.availableChains

              delegate: Rectangle {
                id: chainOptionItem
                width: parent.width
                implicitHeight: Style.space(28)
                radius: Style.space(3)
                property bool isSelected: rootSettingsModal.selectedChain === modelData.id
                color: {
                  if (isSelected) return Color.accent
                  if (optionHover.containsMouse) return Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.08)
                  return "transparent"
                }

                RowLayout {
                  anchors.fill: parent
                  anchors.leftMargin: Style.space(10)
                  anchors.rightMargin: Style.space(10)
                  spacing: Style.space(6)

                  Text {
                    Layout.fillWidth: true
                    text: rootSettingsModal.englishMode ? modelData.nameEn : modelData.nameJa
                    color: chainOptionItem.isSelected
                      ? Color.background
                      : (rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground)
                    font.pixelSize: Style.font ? Style.font.caption : 11
                    font.bold: chainOptionItem.isSelected
                  }

                  Text {
                    visible: chainOptionItem.isSelected
                    text: "✓"
                    color: Color.background
                    font.pixelSize: Style.font ? Style.font.caption : 11
                    font.bold: true
                  }
                }

                MouseArea {
                  id: optionHover
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: {
                    rootSettingsModal.chainDropdownOpen = false
                    rootSettingsModal.chainSelected(modelData.id)
                  }
                }
              }
            }
          }
        }
      }

      // 3. 劇場検索 & 選択
      Column {
        width: parent.width
        spacing: Style.space(6)

        Text {
          text: rootSettingsModal.englishMode ? "Select Theater:" : "劇場を選択:"
          color: Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.8)
          font.pixelSize: Style.font ? Style.font.caption : 11
          font.bold: true
        }

        // 検索ボックス
        RowLayout {
          width: parent.width
          spacing: Style.space(6)

          TextField {
            id: searchInput
            Layout.fillWidth: true
            placeholderText: rootSettingsModal.englishMode ? "Filter theaters..." : "劇場名・地域で絞り込み..."
            font.pixelSize: Style.font ? Style.font.caption : 12
            verticalPadding: Style.space(4)
            horizontalPadding: Style.space(8)
            text: rootSettingsModal.theaterSearchText
            onTextChanged: {
              rootSettingsModal.theaterSearchText = text.trim().toLowerCase()
            }
          }

          Rectangle {
            visible: searchInput.text !== ""
            radius: Style.space(4)
            color: clearHover.containsMouse ? Color.accent : Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.1)
            implicitWidth: Style.space(26)
            implicitHeight: Style.space(26)

            Text {
              anchors.centerIn: parent
              text: "✕"
              color: clearHover.containsMouse ? Color.background : (rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground)
              font.pixelSize: Style.font ? Style.font.caption : 11
            }

            MouseArea {
              id: clearHover
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: {
                searchInput.text = ""
                rootSettingsModal.theaterSearchText = ""
                searchInput.forceActiveFocus()
              }
            }
          }
        }

        // 劇場リスト (スクロール)
        Flickable {
          id: theaterFlickable
          width: parent.width
          height: Style.space(130)
          contentHeight: theaterFlow.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          flickableDirection: Flickable.VerticalFlick
          interactive: contentHeight > height

          ScrollBar.vertical: ScrollBar {
            policy: theaterFlickable.contentHeight > theaterFlickable.height ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
          }

          Flow {
            id: theaterFlow
            width: parent.width
            spacing: Style.space(4)

            Repeater {
              model: rootSettingsModal.filteredTheaters

              delegate: Rectangle {
                id: theaterChip
                radius: Style.space(4)
                property bool isSelected: modelData.id === rootSettingsModal.selectedTheater
                color: isSelected ? Color.accent : Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.1)
                implicitWidth: chipLabel.implicitWidth + Style.space(10)
                implicitHeight: Style.space(22)

                Text {
                  id: chipLabel
                  anchors.centerIn: parent
                  text: modelData.name
                  color: theaterChip.isSelected ? Color.background : (rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground)
                  font.pixelSize: Style.font ? Style.font.caption : 11
                }

                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: rootSettingsModal.theaterSelected(modelData.id, modelData.name)
                }
              }
            }
          }
        }
      }

      // 4. 時間範囲選択 (今日選択時のみ有効)
      RowLayout {
        width: parent.width
        spacing: Style.space(8)
        visible: rootSettingsModal.selectedDate === "today"

        Text {
          text: rootSettingsModal.englishMode ? "Within:" : "抽出範囲:"
          color: Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.8)
          font.pixelSize: Style.font ? Style.font.caption : 11
          font.bold: true
        }

        Repeater {
          model: [1, 2, 3, 5]
          delegate: Rectangle {
            radius: Style.space(4)
            property bool isCurrent: Math.round(rootSettingsModal.withinHours) === modelData
            color: isCurrent ? Color.accent : Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.1)
            implicitWidth: hourLabel.implicitWidth + Style.space(10)
            implicitHeight: Style.space(24)

            Text {
              id: hourLabel
              anchors.centerIn: parent
              text: rootSettingsModal.englishMode ? (modelData + "h") : (modelData + "時間")
              color: parent.isCurrent ? Color.background : (rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground)
              font.pixelSize: Style.font ? Style.font.caption : 11
              font.bold: true
            }

            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: rootSettingsModal.hoursSelected(modelData)
            }
          }
        }
      }

      Text {
        text: rootSettingsModal.englishMode ? "✓ Settings are automatically saved" : "✓ 設定は自動的に保持・保存されます"
        color: Util.alpha(rootSettingsModal.bar ? rootSettingsModal.bar.foreground : Color.foreground, 0.5)
        font.pixelSize: Style.font ? Style.font.caption : 10
      }
    }
  }
}
