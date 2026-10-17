import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import qs.Commons
import qs.Ui

Column {
  id: rootSearchResultView
  width: parent.width
  spacing: Style.space(12)

  // 外部バインド用プロパティ
  property var bar: null
  property bool englishMode: false
  property bool loading: false
  property string errorMessage: ""

  // 検索クエリ情報
  property string queryTitle: ""
  property string queryArea: ""
  property string queryDate: "today"
  property string queryRange: "after"
  property string queryTheater: ""

  // 検索結果データ (CrossTheaterSearchResponse.screenings)
  property var rawScreenings: []

  // 外部ヘルパー関数バインド
  property var openExternalUrl: function(url) {}

  // シグナル
  signal backToScheduleRequested()
  signal rerunSearchRequested()

  // 劇場ごとにグルーピングしたデータ構造
  readonly property var groupedTheaters: {
    var groups = {}
    var order = []
    if (!rootSearchResultView.rawScreenings || !Array.isArray(rootSearchResultView.rawScreenings)) {
      return []
    }

    for (var i = 0; i < rootSearchResultView.rawScreenings.length; i++) {
      var s = rootSearchResultView.rawScreenings[i]
      var key = s.chain_id + "_" + s.theater_id
      if (!groups[key]) {
        groups[key] = {
          key: key,
          chainId: s.chain_id,
          theaterId: s.theater_id,
          theaterName: s.theater_name,
          movieTitle: s.movie_title || "",
          infoUrl: s.info_url || "",
          screenings: []
        }
        order.push(key)
      } else if (!groups[key].movieTitle && s.movie_title) {
        groups[key].movieTitle = s.movie_title
      }
      if (!groups[key].infoUrl && s.info_url) {
        groups[key].infoUrl = s.info_url
      }
      groups[key].screenings.push(s)
    }

    var result = []
    for (var j = 0; j < order.length; j++) {
      var item = groups[order[j]]
      // 上映時間順にソート
      item.screenings.sort(function(a, b) {
        return (a.start_time || "").localeCompare(b.start_time || "")
      })
      result.push(item)
    }
    return result
  }

  // チェーン表示名のヘルパー
  function getChainLabel(chainId) {
    if (chainId === "toho") return rootSearchResultView.englishMode ? "TOHO" : "TOHOシネマズ"
    if (chainId === "united") return rootSearchResultView.englishMode ? "United" : "ユナイテッド"
    if (chainId === "sunshine") return rootSearchResultView.englishMode ? "Sunshine" : "サンシャイン"
    return rootSearchResultView.englishMode ? "Aeon" : "イオンシネマ"
  }

  // 1. 検索情報バー & 通常表示に戻るボタン
  Rectangle {
    width: parent.width
    radius: Style.space(6)
    color: Util.alpha(Color.accent, 0.12)
    border.color: Util.alpha(Color.accent, 0.3)
    border.width: 1
    implicitHeight: headerRow.implicitHeight + Style.space(12)

    RowLayout {
      id: headerRow
      anchors.fill: parent
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      Text {
        text: "🔍"
        font.pixelSize: Style.font ? Style.font.caption : 12
      }

      Column {
        Layout.fillWidth: true
        spacing: Style.space(2)

        RowLayout {
          spacing: Style.space(6)

          Text {
            text: rootSearchResultView.queryTitle ? ("「" + rootSearchResultView.queryTitle + "」") : ""
            textFormat: Text.PlainText
            color: Color.accent
            font.pixelSize: Style.font ? Style.font.body : 13
            font.bold: true
            elide: Text.ElideRight
            Layout.maximumWidth: Style.space(180)
          }

          Text {
            text: "• " + rootSearchResultView.queryArea
            textFormat: Text.PlainText
            color: rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.caption : 11
          }

          Text {
            text: "• " + (rootSearchResultView.queryDate === "tomorrow"
              ? (rootSearchResultView.englishMode ? "Tomorrow" : "明日")
              : (rootSearchResultView.englishMode ? "Today" : "本日"))
            color: rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.caption : 11
          }

          Text {
            visible: rootSearchResultView.queryRange === "after"
            text: "• " + (rootSearchResultView.englishMode ? "Upcoming" : "現在以降")
            color: Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.7)
            font.pixelSize: Style.font ? Style.font.caption : 10
          }
        }

        Text {
          visible: Boolean(rootSearchResultView.queryTheater)
          text: (rootSearchResultView.englishMode ? "Theater filter: " : "劇場絞り込み: ") + rootSearchResultView.queryTheater
          textFormat: Text.PlainText
          color: Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.6)
          font.pixelSize: Style.font ? Style.font.caption : 10
          elide: Text.ElideRight
        }
      }

      // 「✕ 通常表示に戻る」ボタン
      Rectangle {
        radius: Style.space(4)
        color: backHover.containsMouse ? Color.accent : Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.1)
        border.color: Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.15)
        border.width: 1
        implicitWidth: backTxt.implicitWidth + Style.space(12)
        implicitHeight: Style.space(24)

        Text {
          id: backTxt
          anchors.centerIn: parent
          text: rootSearchResultView.englishMode ? "✕ Back" : "✕ 戻る"
          color: backHover.containsMouse ? Color.background : (rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground)
          font.pixelSize: Style.font ? Style.font.caption : 11
          font.bold: true
        }

        MouseArea {
          id: backHover
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: rootSearchResultView.backToScheduleRequested()
          onEntered: if (rootSearchResultView.bar) rootSearchResultView.bar.showTooltip(parent, rootSearchResultView.englishMode ? "Back to theater schedule" : "通常の劇場上映スケジュール表示に戻る")
          onExited: if (rootSearchResultView.bar) rootSearchResultView.bar.hideTooltip(parent)
        }
      }
    }
  }

  // 2. ローディング表示
  RowLayout {
    width: parent.width
    visible: rootSearchResultView.loading
    spacing: Style.space(8)

    Text {
      text: "🔄"
      font.pixelSize: Style.font ? Style.font.caption : 12
    }
    Text {
      text: rootSearchResultView.englishMode ? "Searching theaters across region..." : "地域内のシネコン劇場を横断検索中..."
      color: Color.accent
      font.pixelSize: Style.font ? Style.font.caption : 12
    }
  }

  // 3. エラー表示
  Text {
    width: parent.width
    visible: rootSearchResultView.errorMessage !== ""
    text: rootSearchResultView.errorMessage
    textFormat: Text.PlainText
    color: Color.urgent || "#ff5555"
    wrapMode: Text.WordWrap
    font.pixelSize: Style.font ? Style.font.caption : 12
  }

  // 4. 検索結果リスト
  Flickable {
    id: searchFlickable
    width: parent.width
    height: Math.min(Style.space(380), theaterGroupCol.implicitHeight)
    contentHeight: theaterGroupCol.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    flickableDirection: Flickable.VerticalFlick
    interactive: contentHeight > height

    ScrollBar.vertical: ScrollBar {
      policy: searchFlickable.contentHeight > searchFlickable.height ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
    }

    // 0件表示
    Item {
      width: parent.width
      height: Style.space(120)
      visible: !rootSearchResultView.loading && rootSearchResultView.groupedTheaters.length === 0 && rootSearchResultView.errorMessage === ""

      Column {
        anchors.centerIn: parent
        spacing: Style.space(8)

        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          text: "🎬"
          font.pixelSize: 26
        }

        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          text: rootSearchResultView.englishMode
            ? "No showtimes found for the specified conditions"
            : "指定された条件に一致する上映回は見つかりませんでした"
          color: Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.7)
          font.pixelSize: Style.font ? Style.font.body : 12
        }

        Rectangle {
          anchors.horizontalCenter: parent.horizontalCenter
          radius: Style.space(4)
          color: retryHover.containsMouse ? Color.accent : Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.1)
          implicitWidth: retryTxt.implicitWidth + Style.space(16)
          implicitHeight: Style.space(26)

          Text {
            id: retryTxt
            anchors.centerIn: parent
            text: rootSearchResultView.englishMode ? "🔍 Change Search Conditions" : "🔍 条件を変えて再検索"
            color: retryHover.containsMouse ? Color.background : (rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground)
            font.pixelSize: Style.font ? Style.font.caption : 11
            font.bold: true
          }

          MouseArea {
            id: retryHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: rootSearchResultView.rerunSearchRequested()
          }
        }
      }
    }

    // 劇場グループリスト
    Column {
      id: theaterGroupCol
      width: parent.width
      spacing: Style.space(10)

      Repeater {
        model: rootSearchResultView.groupedTheaters

        delegate: Rectangle {
          width: theaterGroupCol.width
          radius: Style.space(6)
          color: Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.05)
          border.color: Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.12)
          border.width: 1
          implicitHeight: groupInner.implicitHeight + Style.space(16)

          Column {
            id: groupInner
            anchors.fill: parent
            anchors.margins: Style.space(8)
            spacing: Style.space(8)

            // 劇場名ヘッダー
            RowLayout {
              width: parent.width
              spacing: Style.space(6)

              // チェーン識別バッジ
              Rectangle {
                radius: Style.space(3)
                color: Color.accent
                implicitWidth: chainBadgeTxt.implicitWidth + Style.space(8)
                implicitHeight: Style.space(18)

                Text {
                  id: chainBadgeTxt
                  anchors.centerIn: parent
                  text: rootSearchResultView.getChainLabel(modelData.chainId)
                  color: Color.background
                  font.pixelSize: Style.font ? Style.font.caption : 9
                  font.bold: true
                }
              }

              Text {
                Layout.fillWidth: true
                text: modelData.theaterName
                textFormat: Text.PlainText
                color: rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground
                font.pixelSize: Style.font ? Style.font.body : 13
                font.bold: true
                elide: Text.ElideRight
              }

              // 作品公式サイトリンク（もしあれば）
              Rectangle {
                visible: Boolean(modelData.infoUrl)
                radius: Style.space(3)
                color: infoLinkHover.containsMouse ? Util.alpha(Color.accent, 0.2) : "transparent"
                border.color: Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.2)
                border.width: 1
                implicitWidth: infoLinkTxt.implicitWidth + Style.space(8)
                implicitHeight: Style.space(18)

                Text {
                  id: infoLinkTxt
                  anchors.centerIn: parent
                  text: rootSearchResultView.englishMode ? "Info" : "作品情報"
                  color: rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground
                  font.pixelSize: Style.font ? Style.font.caption : 9
                }

                MouseArea {
                  id: infoLinkHover
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: rootSearchResultView.openExternalUrl(modelData.infoUrl)
                }
              }
            }

            // 映画タイトル表示 (クリックで作品情報へ遷移)
            RowLayout {
              width: parent.width
              visible: Boolean(modelData.movieTitle)
              spacing: Style.space(6)

              Text {
                text: "🎬"
                font.pixelSize: Style.font ? Style.font.caption : 11
              }

              Text {
                id: movieTitleCardTxt
                Layout.fillWidth: true
                text: modelData.movieTitle
                textFormat: Text.PlainText
                color: (movieTitleHover.containsMouse && Boolean(modelData.infoUrl)) ? Color.accent : (rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground)
                font.pixelSize: Style.font ? Style.font.body : 12
                font.bold: true
                font.underline: movieTitleHover.containsMouse && Boolean(modelData.infoUrl)
                wrapMode: Text.WordWrap

                MouseArea {
                  id: movieTitleHover
                  anchors.fill: parent
                  hoverEnabled: Boolean(modelData.infoUrl)
                  cursorShape: Boolean(modelData.infoUrl) ? Qt.PointingHandCursor : Qt.ArrowCursor
                  onClicked: {
                    if (modelData.infoUrl) {
                      rootSearchResultView.openExternalUrl(modelData.infoUrl)
                    }
                  }
                  onEntered: if (modelData.infoUrl && rootSearchResultView.bar) rootSearchResultView.bar.showTooltip(parent, rootSearchResultView.englishMode ? "Open official movie details" : "公式作品詳細ページを開く")
                  onExited: if (rootSearchResultView.bar) rootSearchResultView.bar.hideTooltip(parent)
                }
              }
            }

            // 区切り線
            Rectangle {
              width: parent.width
              height: 1
              color: Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.08)
            }

            // 当該劇場の上映回リスト
            Repeater {
              model: modelData.screenings

              delegate: RowLayout {
                width: parent.width
                spacing: Style.space(6)

                // 上映時間バッジ
                Rectangle {
                  radius: Style.space(4)
                  color: Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.12)
                  implicitWidth: timeTxt.implicitWidth + Style.space(8)
                  implicitHeight: Style.space(20)

                  Text {
                    id: timeTxt
                    anchors.centerIn: parent
                    text: modelData.start_time + " 〜 " + (modelData.end_time || "")
                    textFormat: Text.PlainText
                    color: rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground
                    font.pixelSize: Style.font ? Style.font.caption : 11
                    font.bold: true
                  }
                }

                // スクリーン名 & 特殊設備バッジ
                RowLayout {
                  Layout.fillWidth: true
                  spacing: Style.space(4)

                  Text {
                    text: modelData.screen_name || ""
                    textFormat: Text.PlainText
                    color: Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.8)
                    font.pixelSize: Style.font ? Style.font.caption : 11
                    elide: Text.ElideRight
                    Layout.maximumWidth: Style.space(90)
                  }

                  Repeater {
                    model: modelData.tags || []

                    delegate: Rectangle {
                      radius: Style.space(3)
                      color: Util.alpha(Color.accent, 0.18)
                      border.color: Util.alpha(Color.accent, 0.35)
                      border.width: 1
                      implicitWidth: tagTxt.implicitWidth + Style.space(6)
                      implicitHeight: Style.space(16)

                      Text {
                        id: tagTxt
                        anchors.centerIn: parent
                        text: modelData
                        textFormat: Text.PlainText
                        color: Color.accent
                        font.pixelSize: Style.font ? Style.font.caption : 9
                        font.bold: true
                      }
                    }
                  }
                }

                // 空席状況バッジ
                Rectangle {
                  radius: Style.space(3)
                  implicitWidth: statusTxt.implicitWidth + Style.space(8)
                  implicitHeight: Style.space(18)
                  color: {
                    var st = modelData.seat_status
                    if (st === "available") return Util.alpha("#2ecc71", 0.18)
                    if (st === "few") return Util.alpha("#f39c12", 0.22)
                    if (st === "full") return Util.alpha(Color.urgent || "#e74c3c", 0.22)
                    return Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.1)
                  }

                  Text {
                    id: statusTxt
                    anchors.centerIn: parent
                    text: {
                      var st = modelData.seat_status
                      if (st === "available") return rootSearchResultView.englishMode ? "Available" : "◎ 空席あり"
                      if (st === "few") return rootSearchResultView.englishMode ? "Few" : "△ 残少"
                      if (st === "full") return rootSearchResultView.englishMode ? "Full" : "× 満席"
                      if (st === "unsold") return rootSearchResultView.englishMode ? "Not on sale" : "- 販売前"
                      return rootSearchResultView.englishMode ? "Unknown" : "不明"
                    }
                    color: {
                      var st = modelData.seat_status
                      if (st === "available") return "#2ecc71"
                      if (st === "few") return "#e67e22"
                      if (st === "full") return Color.urgent || "#e74c3c"
                      return Util.alpha(rootSearchResultView.bar ? rootSearchResultView.bar.foreground : Color.foreground, 0.6)
                    }
                    font.pixelSize: Style.font ? Style.font.caption : 9
                    font.bold: true
                  }
                }

                // チケット予約購入ボタン
                Rectangle {
                  visible: Boolean(modelData.booking_url) && modelData.seat_status !== "full"
                  radius: Style.space(4)
                  color: bookHover.containsMouse ? Color.accent : Util.alpha(Color.accent, 0.85)
                  implicitWidth: bookTxt.implicitWidth + Style.space(8)
                  implicitHeight: Style.space(20)

                  Text {
                    id: bookTxt
                    anchors.centerIn: parent
                    text: rootSearchResultView.englishMode ? "🎟️ Book" : "🎟️ 予約"
                    color: Color.background
                    font.pixelSize: Style.font ? Style.font.caption : 10
                    font.bold: true
                  }

                  MouseArea {
                    id: bookHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: rootSearchResultView.openExternalUrl(modelData.booking_url)
                    onEntered: if (rootSearchResultView.bar) rootSearchResultView.bar.showTooltip(parent, rootSearchResultView.englishMode ? "Open official reservation page" : "公式チケット購入ページを開く")
                    onExited: if (rootSearchResultView.bar) rootSearchResultView.bar.hideTooltip(parent)
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
