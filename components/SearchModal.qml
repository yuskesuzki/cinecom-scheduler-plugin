import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import qs.Commons
import qs.Ui

Rectangle {
  id: rootSearchModal
  visible: false
  anchors.fill: parent
  color: Util.alpha(Color.background, 0.85)
  z: 70

  property var bar: null
  property bool englishMode: false

  // フォーム入力値
  property string queryTitle: ""
  property string queryArea: "東京都"
  property string queryDate: "today"       // "today" or "tomorrow"
  property string queryRange: "after"      // "all" (終日) or "after" (現在の時間以降)
  property string queryTheater: ""

  // UI状態
  property bool areaDropdownOpen: false

  // 選択肢定義
  readonly property var areaOptions: [
    "東京都", "神奈川県", "埼玉県", "千葉県", "大阪府", "京都府", "兵庫県", "愛知県",
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "新潟県", "富山県", "石川県", "福井県",
    "山梨県", "長野県", "岐阜県", "静岡県", "三重県", "滋賀県", "奈良県",
    "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県",
    "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県", "熊本県",
    "大分県", "宮崎県", "鹿児島県", "沖縄県",
    "関東", "近畿", "中部", "東北", "中国・四国", "九州・沖縄"
  ]

  signal searchRequested(string title, string area, string dateVal, string rangeVal, string theaterVal)
  signal closed()

  function executeSearch() {
    var trimmedTitle = queryTitle.trim()
    if (!trimmedTitle) return
    areaDropdownOpen = false
    rootSearchModal.searchRequested(
      trimmedTitle,
      queryArea,
      queryDate,
      queryRange,
      queryTheater.trim()
    )
    rootSearchModal.closed()
  }

  onVisibleChanged: {
    if (visible) {
      areaDropdownOpen = false
      Qt.callLater(function() {
        if (typeof titleInput !== "undefined" && titleInput) {
          titleInput.forceActiveFocus()
        }
      })
    } else {
      areaDropdownOpen = false
    }
  }

  MouseArea {
    anchors.fill: parent
    onClicked: {
      if (rootSearchModal.areaDropdownOpen) {
        rootSearchModal.areaDropdownOpen = false
      } else {
        rootSearchModal.closed()
      }
    }
  }

  Rectangle {
    id: searchModalCard
    anchors.centerIn: parent
    width: Math.min(parent.width - Style.space(24), Style.space(420))
    implicitHeight: searchModalCol.implicitHeight + Style.space(28)
    radius: Style.space(8)
    color: (typeof Color.surface !== "undefined" && Color.surface) ? Color.surface : (rootSearchModal.bar ? rootSearchModal.bar.background : Color.background)
    border.color: Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.18)
    border.width: 1

    MouseArea {
      anchors.fill: parent
      onClicked: function(mouse) {
        if (rootSearchModal.areaDropdownOpen) {
          rootSearchModal.areaDropdownOpen = false
        }
        mouse.accepted = true
      }
    }

    Column {
      id: searchModalCol
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
            text: "🔍"
            font.pixelSize: Style.font ? Style.font.title : 16
          }
          Text {
            text: rootSearchModal.englishMode ? "Cross-Theater Search" : "作品・地域横断検索"
            color: rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.title : 15
            font.bold: true
          }
        }

        Item { Layout.fillWidth: true }

        Rectangle {
          radius: Style.space(4)
          color: closeHover.containsMouse ? Util.alpha(Color.accent, 0.2) : "transparent"
          implicitWidth: Style.space(24)
          implicitHeight: Style.space(24)

          Text {
            anchors.centerIn: parent
            text: "✕"
            color: Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.7)
            font.pixelSize: Style.font ? Style.font.caption : 12
            font.bold: true
          }

          MouseArea {
            id: closeHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: rootSearchModal.closed()
          }
        }
      }

      // 区切り線
      Rectangle {
        width: parent.width
        height: 1
        color: Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.1)
      }

      // 2. 作品名入力（必須）
      Column {
        width: parent.width
        spacing: Style.space(4)

        RowLayout {
          spacing: Style.space(4)
          Text {
            text: rootSearchModal.englishMode ? "Movie Title" : "作品名"
            color: rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.caption : 11
            font.bold: true
          }
          Text {
            text: rootSearchModal.englishMode ? "(Required)" : "(必須)"
            color: Color.accent
            font.pixelSize: Style.font ? Style.font.caption : 10
            font.bold: true
          }
        }

        RowLayout {
          width: parent.width
          spacing: Style.space(6)

          TextField {
            id: titleInput
            Layout.fillWidth: true
            placeholderText: rootSearchModal.englishMode ? "Enter movie title (e.g. Gundam, Haikyu)..." : "作品名を入力 (例: ガンダム, ハイキュー)..."
            font.pixelSize: Style.font ? Style.font.caption : 12
            verticalPadding: Style.space(5)
            horizontalPadding: Style.space(8)
            text: rootSearchModal.queryTitle
            onTextChanged: rootSearchModal.queryTitle = text

            onAccepted: {
              if (rootSearchModal.queryTitle.trim().length > 0) {
                rootSearchModal.executeSearch()
              }
            }
          }

          Rectangle {
            visible: titleInput.text !== ""
            radius: Style.space(4)
            color: clearTitleHover.containsMouse ? Color.accent : Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.1)
            implicitWidth: Style.space(26)
            implicitHeight: Style.space(26)

            Text {
              anchors.centerIn: parent
              text: "✕"
              color: clearTitleHover.containsMouse ? Color.background : (rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground)
              font.pixelSize: Style.font ? Style.font.caption : 11
            }

            MouseArea {
              id: clearTitleHover
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: {
                titleInput.text = ""
                rootSearchModal.queryTitle = ""
                titleInput.forceActiveFocus()
              }
            }
          }
        }
      }

      // 3. 地域選択ドロップダウン（必須）
      Column {
        width: parent.width
        spacing: Style.space(4)
        z: 10

        RowLayout {
          spacing: Style.space(4)
          Text {
            text: rootSearchModal.englishMode ? "Region / Area" : "地域"
            color: rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.caption : 11
            font.bold: true
          }
          Text {
            text: rootSearchModal.englishMode ? "(Required)" : "(必須)"
            color: Color.accent
            font.pixelSize: Style.font ? Style.font.caption : 10
            font.bold: true
          }
        }

        // ドロップダウントリガー
        Rectangle {
          id: areaTrigger
          width: parent.width
          implicitHeight: Style.space(30)
          radius: Style.space(4)
          color: areaTriggerHover.containsMouse || rootSearchModal.areaDropdownOpen
            ? Util.alpha(Color.accent, 0.12)
            : Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.08)
          border.color: rootSearchModal.areaDropdownOpen
            ? Color.accent
            : Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.25)
          border.width: 1

          RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Style.space(10)
            anchors.rightMargin: Style.space(10)
            spacing: Style.space(6)

            Text {
              text: "📍"
              font.pixelSize: Style.font ? Style.font.caption : 11
            }

            Text {
              Layout.fillWidth: true
              text: rootSearchModal.queryArea || (rootSearchModal.englishMode ? "Select region" : "地域を選択")
              color: rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground
              font.pixelSize: Style.font ? Style.font.caption : 12
              font.bold: true
              elide: Text.ElideRight
            }

            Text {
              text: rootSearchModal.areaDropdownOpen ? "▲" : "▼"
              color: rootSearchModal.areaDropdownOpen ? Color.accent : Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.6)
              font.pixelSize: Style.font ? Style.font.caption : 10
            }
          }

          MouseArea {
            id: areaTriggerHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              rootSearchModal.areaDropdownOpen = !rootSearchModal.areaDropdownOpen
            }
          }
        }

        // ドロップダウンリスト
        Rectangle {
          id: areaDropdownList
          width: parent.width
          visible: rootSearchModal.areaDropdownOpen
          radius: Style.space(4)
          color: (typeof Color.surface !== "undefined" && Color.surface) ? Color.surface : (rootSearchModal.bar ? rootSearchModal.bar.background : Color.background)
          border.color: Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.25)
          border.width: 1
          implicitHeight: Math.min(Style.space(180), areaOptionsCol.implicitHeight + Style.space(6))
          clip: true

          Flickable {
            anchors.fill: parent
            contentHeight: areaOptionsCol.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            Column {
              id: areaOptionsCol
              width: parent.width

              Repeater {
                model: rootSearchModal.areaOptions

                delegate: Rectangle {
                  id: areaOptionItem
                  width: areaOptionsCol.width
                  implicitHeight: Style.space(26)
                  property bool isSelected: rootSearchModal.queryArea === modelData
                  color: {
                    if (isSelected) return Color.accent
                    if (optHover.containsMouse) return Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.08)
                    return "transparent"
                  }

                  RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Style.space(10)
                    anchors.rightMargin: Style.space(10)

                    Text {
                      Layout.fillWidth: true
                      text: modelData
                      color: areaOptionItem.isSelected
                        ? Color.background
                        : (rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground)
                      font.pixelSize: Style.font ? Style.font.caption : 11
                      font.bold: areaOptionItem.isSelected
                    }

                    Text {
                      visible: areaOptionItem.isSelected
                      text: "✓"
                      color: Color.background
                      font.pixelSize: Style.font ? Style.font.caption : 11
                      font.bold: true
                    }
                  }

                  MouseArea {
                    id: optHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                      rootSearchModal.queryArea = modelData
                      rootSearchModal.areaDropdownOpen = false
                    }
                  }
                }
              }
            }
          }
        }
      }

      // 4. 日付選択（必須・ラジオボタンスタイル）
      Column {
        width: parent.width
        spacing: Style.space(4)

        RowLayout {
          spacing: Style.space(4)
          Text {
            text: rootSearchModal.englishMode ? "Date" : "日付"
            color: rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.caption : 11
            font.bold: true
          }
          Text {
            text: rootSearchModal.englishMode ? "(Required)" : "(必須)"
            color: Color.accent
            font.pixelSize: Style.font ? Style.font.caption : 10
            font.bold: true
          }
        }

        RowLayout {
          width: parent.width
          spacing: Style.space(6)

          Repeater {
            model: [
              { id: "today",    labelJa: "本日", labelEn: "Today" },
              { id: "tomorrow", labelJa: "明日", labelEn: "Tomorrow" }
            ]

            delegate: Rectangle {
              Layout.fillWidth: true
              radius: Style.space(4)
              property bool isSelected: rootSearchModal.queryDate === modelData.id
              color: isSelected ? Color.accent : Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.08)
              border.color: isSelected ? Color.accent : Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.18)
              border.width: 1
              implicitHeight: Style.space(28)

              RowLayout {
                anchors.centerIn: parent
                spacing: Style.space(6)

                // ラジオボタンアイコン
                Rectangle {
                  width: Style.space(12)
                  height: Style.space(12)
                  radius: Style.space(6)
                  color: "transparent"
                  border.color: parent.parent.isSelected ? Color.background : Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.5)
                  border.width: 1.5

                  Rectangle {
                    anchors.centerIn: parent
                    width: Style.space(6)
                    height: Style.space(6)
                    radius: Style.space(3)
                    visible: parent.parent.parent.isSelected
                    color: Color.background
                  }
                }

                Text {
                  text: rootSearchModal.englishMode ? modelData.labelEn : modelData.labelJa
                  color: parent.parent.isSelected ? Color.background : (rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground)
                  font.pixelSize: Style.font ? Style.font.caption : 11
                  font.bold: parent.parent.isSelected
                }
              }

              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: rootSearchModal.queryDate = modelData.id
              }
            }
          }
        }
      }

      // 5. 表示範囲選択（任意・ラジオボタンスタイル）
      Column {
        width: parent.width
        spacing: Style.space(4)

        RowLayout {
          spacing: Style.space(4)
          Text {
            text: rootSearchModal.englishMode ? "Time Window" : "表示範囲"
            color: rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.caption : 11
            font.bold: true
          }
          Text {
            text: rootSearchModal.englishMode ? "(Optional)" : "(任意)"
            color: Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.5)
            font.pixelSize: Style.font ? Style.font.caption : 10
          }
        }

        RowLayout {
          width: parent.width
          spacing: Style.space(6)

          Repeater {
            model: [
              { id: "all",   labelJa: "終日",           labelEn: "All Day" },
              { id: "after", labelJa: "現在の時間以降", labelEn: "Upcoming From Now" }
            ]

            delegate: Rectangle {
              Layout.fillWidth: true
              radius: Style.space(4)
              property bool isSelected: rootSearchModal.queryRange === modelData.id
              color: isSelected ? Color.accent : Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.08)
              border.color: isSelected ? Color.accent : Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.18)
              border.width: 1
              implicitHeight: Style.space(28)

              RowLayout {
                anchors.centerIn: parent
                spacing: Style.space(6)

                Rectangle {
                  width: Style.space(12)
                  height: Style.space(12)
                  radius: Style.space(6)
                  color: "transparent"
                  border.color: parent.parent.isSelected ? Color.background : Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.5)
                  border.width: 1.5

                  Rectangle {
                    anchors.centerIn: parent
                    width: Style.space(6)
                    height: Style.space(6)
                    radius: Style.space(3)
                    visible: parent.parent.parent.isSelected
                    color: Color.background
                  }
                }

                Text {
                  text: rootSearchModal.englishMode ? modelData.labelEn : modelData.labelJa
                  color: parent.parent.isSelected ? Color.background : (rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground)
                  font.pixelSize: Style.font ? Style.font.caption : 11
                  font.bold: parent.parent.isSelected
                }
              }

              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: rootSearchModal.queryRange = modelData.id
              }
            }
          }
        }
      }

      // 6. 劇場名入力（任意）
      Column {
        width: parent.width
        spacing: Style.space(4)

        RowLayout {
          spacing: Style.space(4)
          Text {
            text: rootSearchModal.englishMode ? "Theater Filter" : "劇場名"
            color: rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.caption : 11
            font.bold: true
          }
          Text {
            text: rootSearchModal.englishMode ? "(Optional)" : "(任意)"
            color: Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.5)
            font.pixelSize: Style.font ? Style.font.caption : 10
          }
        }

        RowLayout {
          width: parent.width
          spacing: Style.space(6)

          TextField {
            id: theaterInput
            Layout.fillWidth: true
            placeholderText: rootSearchModal.englishMode ? "e.g. Shinjuku, Toyosu..." : "劇場名で絞り込み (例: 新宿, 豊洲)..."
            font.pixelSize: Style.font ? Style.font.caption : 12
            verticalPadding: Style.space(5)
            horizontalPadding: Style.space(8)
            text: rootSearchModal.queryTheater
            onTextChanged: rootSearchModal.queryTheater = text

            onAccepted: {
              if (rootSearchModal.queryTitle.trim().length > 0) {
                rootSearchModal.executeSearch()
              }
            }
          }

          Rectangle {
            visible: theaterInput.text !== ""
            radius: Style.space(4)
            color: clearTheaterHover.containsMouse ? Color.accent : Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.1)
            implicitWidth: Style.space(26)
            implicitHeight: Style.space(26)

            Text {
              anchors.centerIn: parent
              text: "✕"
              color: clearTheaterHover.containsMouse ? Color.background : (rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground)
              font.pixelSize: Style.font ? Style.font.caption : 11
            }

            MouseArea {
              id: clearTheaterHover
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: {
                theaterInput.text = ""
                rootSearchModal.queryTheater = ""
                theaterInput.forceActiveFocus()
              }
            }
          }
        }
      }

      // 7. アクションボタンバー (キャンセル / 検索実行)
      RowLayout {
        width: parent.width
        spacing: Style.space(8)

        Item { Layout.fillWidth: true }

        // キャンセルボタン
        Rectangle {
          radius: Style.space(4)
          color: cancelHover.containsMouse ? Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.15) : "transparent"
          border.color: Util.alpha(rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground, 0.2)
          border.width: 1
          implicitWidth: cancelTxt.implicitWidth + Style.space(16)
          implicitHeight: Style.space(30)

          Text {
            id: cancelTxt
            anchors.centerIn: parent
            text: rootSearchModal.englishMode ? "Cancel" : "キャンセル"
            color: rootSearchModal.bar ? rootSearchModal.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.caption : 11
          }

          MouseArea {
            id: cancelHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: rootSearchModal.closed()
          }
        }

        // 検索ボタン
        Rectangle {
          property bool canSearch: rootSearchModal.queryTitle.trim().length > 0 && rootSearchModal.queryArea.trim().length > 0
          radius: Style.space(4)
          color: canSearch
            ? (searchSubmitHover.containsMouse ? Qt.lighter(Color.accent, 1.1) : Color.accent)
            : Util.alpha(Color.accent, 0.3)
          implicitWidth: searchSubmitTxt.implicitWidth + Style.space(20)
          implicitHeight: Style.space(30)

          Text {
            id: searchSubmitTxt
            anchors.centerIn: parent
            text: rootSearchModal.englishMode ? "🔍 Search" : "🔍 検索する"
            color: Color.background
            font.pixelSize: Style.font ? Style.font.caption : 12
            font.bold: true
          }

          MouseArea {
            id: searchSubmitHover
            anchors.fill: parent
            hoverEnabled: parent.canSearch
            cursorShape: parent.canSearch ? Qt.PointingHandCursor : Qt.ForbiddenCursor
            onClicked: {
              if (parent.canSearch) {
                rootSearchModal.executeSearch()
              }
            }
          }
        }
      }
    }
  }
}
