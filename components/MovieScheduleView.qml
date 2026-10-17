import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import qs.Commons
import qs.Ui

Column {
  id: rootScheduleView
  width: parent.width
  spacing: Style.space(12)

  // 外部から渡すプロパティ
  property var bar: null
  property bool englishMode: false
  property string selectedDate: "today"
  property real withinHours: 3.0
  property bool showAllDayToday: false
  property bool loading: false
  property string errorMessage: ""
  property string payloadMessage: ""
  property var moviesData: []
  property var filteredMovies: []
  property var uniqueMovieTitles: []
  property string selectedMovieFilter: ""
  property bool movieFilterDropdownOpen: false

  // ヘルパー関数（バインド用）
  property var getTargetDateFormatted: function() { return "" }
  property var getMovieDisplayTitle: function(m) { return "" }
  property var getScreenDisplayName: function(s) { return s }
  property var openExternalUrl: function(url) {}

  // イベント通知シグナル
  signal dateChanged(string newDate)
  signal toggleAllDayRequested()
  signal movieFilterChanged(string filter)
  signal screenDetailsRequested(string screenName, var facilityData)

  // 2. 日付切替セレクター (昨日 / 今日 / 明日)
  RowLayout {
    width: parent.width
    spacing: Style.space(6)

    Repeater {
      model: [
        { id: "today",     labelJa: "今日", labelEn: "Today" },
        { id: "tomorrow",  labelJa: "明日", labelEn: "Tomorrow" }
      ]

      delegate: Rectangle {
        Layout.fillWidth: true
        radius: Style.space(4)
        property bool isSelected: rootScheduleView.selectedDate === modelData.id
        color: isSelected ? Color.accent : Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.08)
        border.color: isSelected ? Color.accent : Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.15)
        border.width: 1
        implicitHeight: Style.space(26)

        Text {
          anchors.centerIn: parent
          text: rootScheduleView.englishMode ? modelData.labelEn : modelData.labelJa
          color: parent.isSelected ? Color.background : (rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground)
          font.pixelSize: Style.font ? Style.font.caption : 11
          font.bold: parent.isSelected
        }

        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: {
            if (rootScheduleView.selectedDate !== modelData.id) {
              rootScheduleView.selectedDate = modelData.id
              root.rawMoviesData = []
              rootScheduleView.movieFilterChanged("")
              rootScheduleView.movieFilterDropdownOpen = false
              root.refresh()
            }
          }
        }
      }
    }
  }

  // 3. 上映時間・作品一覧ヘッダー
  RowLayout {
    width: parent.width
    spacing: Style.space(8)

    Text {
      Layout.fillWidth: true
      text: {
        if (rootScheduleView.selectedDate === "tomorrow") {
          return rootScheduleView.englishMode
            ? ("Tomorrow's Showtimes (" + rootScheduleView.getTargetDateFormatted() + "):")
            : ("明日の上映作品一覧 (" + rootScheduleView.getTargetDateFormatted() + "):")
        } else {
          var dateStr = " (" + rootScheduleView.getTargetDateFormatted() + "):"
          if (rootScheduleView.showAllDayToday) {
            return rootScheduleView.englishMode ? ("Today's All Showtimes" + dateStr) : ("今日の上映作品一覧 (終日)" + dateStr)
          } else {
            return rootScheduleView.englishMode
              ? ("Upcoming in " + rootScheduleView.withinHours + " hours" + dateStr)
              : ("直近 " + rootScheduleView.withinHours + " 時間の上映作品" + dateStr)
          }
        }
      }
      color: Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.7)
      font.pixelSize: Style.font ? Style.font.caption : 12
      font.bold: true
      elide: Text.ElideRight
    }

    // 今日の場合の「終日(時系列) / 直近」切替スイッチ
    Rectangle {
      visible: rootScheduleView.selectedDate === "today"
      radius: Style.space(4)
      color: allDayToggleHover.containsMouse
        ? Util.alpha(Color.accent, 0.18)
        : (rootScheduleView.showAllDayToday ? Color.accent : Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.08))
      border.color: rootScheduleView.showAllDayToday ? Color.accent : Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.2)
      border.width: 1
      implicitWidth: allDayToggleTxt.implicitWidth + Style.space(12)
      implicitHeight: Style.space(22)

      RowLayout {
        anchors.centerIn: parent
        spacing: Style.space(4)

        Text {
          id: allDayToggleTxt
          text: {
            if (rootScheduleView.englishMode) {
              return rootScheduleView.showAllDayToday ? "🕒 All Day" : ("🕒 " + rootScheduleView.withinHours + "h")
            } else {
              return rootScheduleView.showAllDayToday ? "🕒 終日(時系列)" : ("🕒 直近" + rootScheduleView.withinHours + "h")
            }
          }
          color: rootScheduleView.showAllDayToday
            ? Color.background
            : (rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground)
          font.pixelSize: Style.font ? Style.font.caption : 10
          font.bold: true
        }
      }

      MouseArea {
        id: allDayToggleHover
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: rootScheduleView.toggleAllDayRequested()
        onEntered: if (rootScheduleView.bar) {
          rootScheduleView.bar.showTooltip(parent, rootScheduleView.englishMode
            ? (rootScheduleView.showAllDayToday ? "Switch to upcoming hours window" : "Switch to all-day showtimes in chronological order")
            : (rootScheduleView.showAllDayToday ? "直近時間枠表示に切り替え" : "一日の全上映を時系列順に表示"))
        }
        onExited: if (rootScheduleView.bar) rootScheduleView.bar.hideTooltip(parent)
      }
    }

    Text {
      visible: rootScheduleView.loading
      text: rootScheduleView.englishMode ? "Loading..." : "読み込み中..."
      color: Color.accent
      font.pixelSize: Style.font ? Style.font.caption : 11
    }
  }

  // 作品名絞り込みドロップダウン (作品が1件以上ある場合のみ表示)
  Column {
    width: parent.width
    spacing: Style.space(4)
    visible: !rootScheduleView.loading && rootScheduleView.moviesData.length > 0

    // トリガーボタン
    Rectangle {
      id: movieFilterTrigger
      width: parent.width
      implicitHeight: Style.space(28)
      radius: Style.space(4)
      color: movieTriggerHover.containsMouse || rootScheduleView.movieFilterDropdownOpen
        ? Util.alpha(Color.accent, 0.12)
        : Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.06)
      border.color: rootScheduleView.movieFilterDropdownOpen
        ? Color.accent
        : (rootScheduleView.selectedMovieFilter !== "" ? Color.accent : Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.18))
      border.width: 1

      RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Style.space(8)
        anchors.rightMargin: Style.space(8)
        spacing: Style.space(6)

        Text {
          text: "🎬"
          font.pixelSize: Style.font ? Style.font.caption : 11
        }

        Text {
          Layout.fillWidth: true
          text: {
            if (rootScheduleView.selectedMovieFilter === "") {
              return rootScheduleView.englishMode
                ? ("All Movies (" + rootScheduleView.moviesData.length + ")")
                : ("すべての作品 (" + rootScheduleView.moviesData.length + "本)")
            }
            return rootScheduleView.selectedMovieFilter
          }
          color: rootScheduleView.selectedMovieFilter !== "" ? Color.accent : (rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground)
          font.pixelSize: Style.font ? Style.font.caption : 11
          font.bold: rootScheduleView.selectedMovieFilter !== ""
          elide: Text.ElideRight
        }

        // クリアボタン (個別作品選択時のみ表示)
        Rectangle {
          visible: rootScheduleView.selectedMovieFilter !== ""
          radius: Style.space(3)
          color: clearMovieHover.containsMouse ? Util.alpha(Color.accent, 0.2) : "transparent"
          implicitWidth: Style.space(18)
          implicitHeight: Style.space(18)

          Text {
            anchors.centerIn: parent
            text: "✕"
            color: clearMovieHover.containsMouse ? Color.accent : Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.6)
            font.pixelSize: Style.font ? Style.font.caption : 10
          }

          MouseArea {
            id: clearMovieHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              rootScheduleView.movieFilterChanged("")
              rootScheduleView.movieFilterDropdownOpen = false
            }
          }
        }

        Text {
          text: rootScheduleView.movieFilterDropdownOpen ? "▲" : "▼"
          color: rootScheduleView.movieFilterDropdownOpen ? Color.accent : Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.5)
          font.pixelSize: Style.font ? Style.font.caption : 9
        }
      }

      MouseArea {
        id: movieTriggerHover
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          rootScheduleView.movieFilterDropdownOpen = !rootScheduleView.movieFilterDropdownOpen
        }
      }
    }

    // 展開時の選択肢リスト (スクロール対応)
    Rectangle {
      id: movieFilterListCard
      width: parent.width
      visible: rootScheduleView.movieFilterDropdownOpen
      radius: Style.space(4)
      color: rootScheduleView.bar ? rootScheduleView.bar.background : Color.background
      border.color: Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.2)
      border.width: 1
      implicitHeight: Math.min(Style.space(180), movieOptionsCol.implicitHeight + Style.space(6))
      clip: true

      Flickable {
        id: movieFilterFlick
        anchors.fill: parent
        anchors.margins: Style.space(2)
        contentHeight: movieOptionsCol.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height

        ScrollBar.vertical: ScrollBar {
          policy: movieFilterFlick.contentHeight > movieFilterFlick.height ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
        }

        Column {
          id: movieOptionsCol
          width: movieFilterFlick.width
          spacing: 0

          // 1. 「すべての作品」項目
          Rectangle {
            id: allMoviesOption
            width: parent.width
            implicitHeight: Style.space(26)
            radius: Style.space(3)
            property bool isSelected: rootScheduleView.selectedMovieFilter === ""
            color: {
              if (isSelected) return Color.accent
              if (allHover.containsMouse) return Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.08)
              return "transparent"
            }

            RowLayout {
              anchors.fill: parent
              anchors.leftMargin: Style.space(8)
              anchors.rightMargin: Style.space(8)
              spacing: Style.space(6)

              Text {
                Layout.fillWidth: true
                text: rootScheduleView.englishMode ? ("All Movies (" + rootScheduleView.moviesData.length + ")") : ("すべての作品 (" + rootScheduleView.moviesData.length + "本)")
                color: allMoviesOption.isSelected ? Color.background : (rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground)
                font.pixelSize: Style.font ? Style.font.caption : 11
                font.bold: allMoviesOption.isSelected
                elide: Text.ElideRight
              }

              Text {
                visible: allMoviesOption.isSelected
                text: "✓"
                color: Color.background
                font.pixelSize: Style.font ? Style.font.caption : 11
                font.bold: true
              }
            }

            MouseArea {
              id: allHover
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: {
                rootScheduleView.movieFilterChanged("")
                rootScheduleView.movieFilterDropdownOpen = false
              }
            }
          }

          // 2. 各作品の項目
          Repeater {
            model: rootScheduleView.uniqueMovieTitles

            delegate: Rectangle {
              id: movieOptionItem
              width: parent.width
              implicitHeight: Style.space(26)
              radius: Style.space(3)
              property bool isSelected: rootScheduleView.selectedMovieFilter === modelData
              color: {
                if (isSelected) return Color.accent
                if (optHover.containsMouse) return Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.08)
                return "transparent"
              }

              RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Style.space(8)
                anchors.rightMargin: Style.space(8)
                spacing: Style.space(6)

                Text {
                  Layout.fillWidth: true
                  text: modelData
                  color: movieOptionItem.isSelected ? Color.background : (rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground)
                  font.pixelSize: Style.font ? Style.font.caption : 11
                  font.bold: movieOptionItem.isSelected
                  elide: Text.ElideRight
                }

                Text {
                  visible: movieOptionItem.isSelected
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
                  rootScheduleView.movieFilterChanged(modelData)
                  rootScheduleView.movieFilterDropdownOpen = false
                }
              }
            }
          }
        }
      }
    }
  }

  // エラーメッセージ
  Text {
    width: parent.width
    visible: rootScheduleView.errorMessage !== ""
    text: rootScheduleView.errorMessage
    textFormat: Text.PlainText
    color: Color.urgent || "#ff5555"
    wrapMode: Text.WordWrap
    font.pixelSize: Style.font ? Style.font.caption : 12
  }

  // 5. 上映作品リスト
  Flickable {
    id: movieFlickable
    width: parent.width
    height: Math.min(Style.space(360), movieColumn.implicitHeight)
    contentHeight: movieColumn.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    flickableDirection: Flickable.VerticalFlick
    interactive: contentHeight > height

    ScrollBar.vertical: ScrollBar {
      policy: movieFlickable.contentHeight > movieFlickable.height ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
    }

    // 作品が0件の場合
    Item {
      width: parent.width
      height: Style.space(110)
      visible: !rootScheduleView.loading && rootScheduleView.filteredMovies.length === 0 && rootScheduleView.errorMessage === ""

      Column {
        anchors.centerIn: parent
        spacing: Style.space(6)
        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          text: "🎬"
          font.pixelSize: 24
        }
        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          text: {
            if (rootScheduleView.payloadMessage) return rootScheduleView.payloadMessage
            if (rootScheduleView.moviesData.length > 0 && rootScheduleView.selectedMovieFilter !== "") {
              return rootScheduleView.englishMode ? "No showtimes for selected movie" : "選択した作品の上映枠はありません"
            }
            if (rootScheduleView.selectedDate === "tomorrow") {
              return rootScheduleView.englishMode ? "No showtimes available for tomorrow" : "明日の上映作品はありません"
            } else if (rootScheduleView.showAllDayToday) {
              return rootScheduleView.englishMode ? "No showtimes available today" : "今日の上映作品はありません"
            } else {
              return rootScheduleView.englishMode ? "No upcoming showtimes within window" : "直近の上映作品はありません"
            }
          }
          color: Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.6)
          font.pixelSize: Style.font ? Style.font.body : 12
        }
      }
    }

    Column {
      id: movieColumn
      width: parent.width
      spacing: Style.space(8)

      Repeater {
        model: rootScheduleView.filteredMovies

        delegate: Rectangle {
          width: movieColumn.width
          radius: Style.space(6)
          color: Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.05)
          border.color: Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.1)
          border.width: 1
          implicitHeight: cardInner.implicitHeight + Style.space(16)

          Column {
            id: cardInner
            anchors.fill: parent
            anchors.margins: Style.space(8)
            spacing: Style.space(8)

            // 作品タイトル & 予約ボタン
            RowLayout {
              width: parent.width
              spacing: Style.space(8)

              Item {
                Layout.fillWidth: true
                implicitHeight: movieTitleTxt.implicitHeight

                Text {
                  id: movieTitleTxt
                  anchors.left: parent.left
                  anchors.right: parent.right
                  text: rootScheduleView.getMovieDisplayTitle(modelData)
                  textFormat: Text.PlainText
                  color: (titleHover.containsMouse && Boolean(modelData.info_url)) ? Color.accent : (rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground)
                  font.pixelSize: Style.font ? Style.font.body : 13
                  font.bold: true
                  font.underline: titleHover.containsMouse && Boolean(modelData.info_url)
                  wrapMode: Text.WordWrap
                }

                MouseArea {
                  id: titleHover
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Boolean(modelData.info_url) ? Qt.PointingHandCursor : Qt.ArrowCursor
                  onClicked: function(mouse) {
                    if (modelData.info_url) {
                      mouse.accepted = true
                      rootScheduleView.openExternalUrl(modelData.info_url)
                    }
                  }
                  onEntered: {
                    if (modelData.info_url && rootScheduleView.bar) {
                      var titleName = rootScheduleView.getMovieDisplayTitle(modelData)
                      rootScheduleView.bar.showTooltip(parent, rootScheduleView.englishMode ? ("Open official details for " + titleName) : ("「" + titleName + "」の作品詳細ページを開く"))
                    }
                  }
                  onExited: {
                    if (rootScheduleView.bar) {
                      rootScheduleView.bar.hideTooltip(parent)
                    }
                  }
                }
              }

              // 作品ごとのチケット予約ボタン (直近回へリンク)
              Rectangle {
                visible: Boolean(modelData.booking_url)
                radius: Style.space(4)
                color: bookBtnHover.containsMouse ? Color.accent : Util.alpha(Color.accent, 0.85)
                implicitWidth: bookBtnTxt.implicitWidth + Style.space(10)
                implicitHeight: Style.space(22)
                z: 2

                Text {
                  id: bookBtnTxt
                  anchors.centerIn: parent
                  text: rootScheduleView.englishMode ? "🎟️ Book" : "🎟️ 予約購入"
                  color: Color.background
                  font.pixelSize: Style.font ? Style.font.caption : 10
                  font.bold: true
                }

                MouseArea {
                  id: bookBtnHover
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: function(mouse) {
                    mouse.accepted = true
                    rootScheduleView.openExternalUrl(modelData.booking_url)
                  }
                  onEntered: if (rootScheduleView.bar) rootScheduleView.bar.showTooltip(parent, rootScheduleView.englishMode ? "Book ticket on official Watatheatre site" : "ワタシアター予約購入ページを開く")
                  onExited: if (rootScheduleView.bar) rootScheduleView.bar.hideTooltip(parent)
                }
              }
            }

            // 上映回リスト
            Repeater {
              model: modelData.showtimes

              delegate: RowLayout {
                width: parent.width
                spacing: Style.space(6)

                // 時間バッジ
                Rectangle {
                  radius: Style.space(4)
                  color: Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.12)
                  implicitWidth: timeTxt.implicitWidth + Style.space(8)
                  implicitHeight: Style.space(20)

                  Text {
                    id: timeTxt
                    anchors.centerIn: parent
                    text: modelData.start_time + " 〜 " + modelData.end_time
                    color: rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground
                    font.pixelSize: Style.font ? Style.font.caption : 11
                    font.bold: true
                  }
                }

                // スクリーン名 (クリックで設備・座席詳細ポップアップ)
                Rectangle {
                  radius: Style.space(3)
                  color: screenHover.containsMouse ? Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.12) : "transparent"
                  implicitWidth: screenTxt.implicitWidth + Style.space(6)
                  implicitHeight: Style.space(20)

                  Text {
                    id: screenTxt
                    anchors.centerIn: parent
                    text: rootScheduleView.getScreenDisplayName(modelData.screen)
                    textFormat: Text.PlainText
                    color: screenHover.containsMouse ? Color.accent : Util.alpha(rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground, 0.8)
                    font.pixelSize: Style.font ? Style.font.caption : 11
                    font.underline: screenHover.containsMouse
                  }

                  MouseArea {
                    id: screenHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: function(mouse) {
                      mouse.accepted = true
                      root.showScreenDetails(modelData.screen, modelData.screen_facility)
                    }
                    onEntered: if (rootScheduleView.bar) rootScheduleView.bar.showTooltip(parent, rootScheduleView.englishMode ? ("Click to view details for " + rootScheduleView.getScreenDisplayName(modelData.screen)) : (modelData.screen + " の設備・座席詳細を表示"))
                    onExited: if (rootScheduleView.bar) rootScheduleView.bar.hideTooltip(parent)
                  }
                }

                // 特殊設備バッジ欄 (1つ以上ある場合は初期状態 "..."、クリックで全表示・再クリックで折りたたみ)
                Item {
                  id: facilityBadgesContainer
                  visible: Boolean(modelData.special_badges && modelData.special_badges.length > 0)
                  property bool isExpanded: false

                  implicitHeight: Style.space(20)
                  implicitWidth: isExpanded ? expandedContainer.implicitWidth : collapsedRow.implicitWidth

                  // 未展開時: 1つ目のバッジ + (2つ以上あれば "..." バッジ)
                  Row {
                    id: collapsedRow
                    visible: !facilityBadgesContainer.isExpanded
                    spacing: Style.space(4)
                    anchors.verticalCenter: parent.verticalCenter

                    // 1つ目の設備バッジ
                    Rectangle {
                      radius: Style.space(3)
                      color: ((modelData.special_badges || []).length > 1 && firstHover.containsMouse) ? Util.alpha(Color.accent, 0.3) : Util.alpha(Color.accent, 0.18)
                      border.color: Util.alpha(Color.accent, 0.5)
                      border.width: 1
                      implicitWidth: firstBadgeTxt.implicitWidth + Style.space(6)
                      implicitHeight: Style.space(18)

                      Text {
                        id: firstBadgeTxt
                        anchors.centerIn: parent
                        text: "[" + (modelData.special_badges ? modelData.special_badges[0] : "") + "]"
                        textFormat: Text.PlainText
                        color: Color.accent
                        font.pixelSize: Style.font ? Style.font.caption : 10
                        font.bold: true
                      }

                      MouseArea {
                        id: firstHover
                        anchors.fill: parent
                        enabled: (modelData.special_badges || []).length > 1
                        hoverEnabled: true
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: function(mouse) {
                          mouse.accepted = true
                          facilityBadgesContainer.isExpanded = true
                        }
                        onEntered: if (enabled && rootScheduleView.bar) {
                          var list = (modelData.special_badges || []).join(", ")
                          rootScheduleView.bar.showTooltip(parent, rootScheduleView.englishMode ? ("Facilities: " + list + " (Click to expand)") : ("設備: " + list + " (クリックで全表示)"))
                        }
                        onExited: if (rootScheduleView.bar) rootScheduleView.bar.hideTooltip(parent)
                      }
                    }

                    // 2つ以上ある場合の "..." バッジ
                    Rectangle {
                      visible: (modelData.special_badges || []).length > 1
                      radius: Style.space(3)
                      color: dotHover.containsMouse ? Util.alpha(Color.accent, 0.3) : Util.alpha(Color.accent, 0.18)
                      border.color: Util.alpha(Color.accent, 0.5)
                      border.width: 1
                      implicitWidth: dotTxt.implicitWidth + Style.space(8)
                      implicitHeight: Style.space(18)

                      Text {
                        id: dotTxt
                        anchors.centerIn: parent
                        text: "..."
                        color: Color.accent
                        font.pixelSize: Style.font ? Style.font.caption : 11
                        font.bold: true
                      }

                      MouseArea {
                        id: dotHover
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function(mouse) {
                          mouse.accepted = true
                          facilityBadgesContainer.isExpanded = true
                        }
                        onEntered: {
                          var list = (modelData.special_badges || []).slice(1).join(", ")
                          if (rootScheduleView.bar) rootScheduleView.bar.showTooltip(parent, rootScheduleView.englishMode ? ("Other facilities: " + list + " (Click to expand)") : ("その他の設備: " + list + " (クリックで全表示)"))
                        }
                        onExited: if (rootScheduleView.bar) rootScheduleView.bar.hideTooltip(parent)
                      }
                    }
                  }

                  // 展開時: 全設備バッジ (クリックで折りたたみ)
                  Item {
                    id: expandedContainer
                    visible: facilityBadgesContainer.isExpanded
                    implicitWidth: expandedRow.implicitWidth
                    implicitHeight: Style.space(18)
                    anchors.verticalCenter: parent.verticalCenter

                    Row {
                      id: expandedRow
                      spacing: Style.space(4)
                      anchors.verticalCenter: parent.verticalCenter

                      Repeater {
                        model: modelData.special_badges || []
                        delegate: Rectangle {
                          radius: Style.space(3)
                          color: expHover.containsMouse ? Util.alpha(Color.accent, 0.3) : Util.alpha(Color.accent, 0.18)
                          border.color: Util.alpha(Color.accent, 0.5)
                          border.width: 1
                          implicitWidth: badgeTxt.implicitWidth + Style.space(6)
                          implicitHeight: Style.space(18)

                          Text {
                            id: badgeTxt
                            anchors.centerIn: parent
                            text: "[" + modelData + "]"
                            textFormat: Text.PlainText
                            color: Color.accent
                            font.pixelSize: Style.font ? Style.font.caption : 10
                            font.bold: true
                          }
                        }
                      }
                    }

                    MouseArea {
                      id: expHover
                      anchors.fill: parent
                      hoverEnabled: true
                      cursorShape: Qt.PointingHandCursor
                      onClicked: function(mouse) {
                        mouse.accepted = true
                        facilityBadgesContainer.isExpanded = false
                      }
                      onEntered: if (rootScheduleView.bar) rootScheduleView.bar.showTooltip(parent, rootScheduleView.englishMode ? "Click to collapse facilities" : "クリックで設備を折りたたむ")
                      onExited: if (rootScheduleView.bar) rootScheduleView.bar.hideTooltip(parent)
                    }
                  }
                }

                Item { Layout.fillWidth: true }

                // 残席・空き状況情報
                Rectangle {
                  visible: (modelData.seat_status && modelData.seat_status !== "unknown") || (modelData.remaining_seats !== null && modelData.remaining_seats !== undefined)
                  radius: Style.space(4)
                  color: {
                    var st = modelData.seat_status
                    if (st === "full" || modelData.remaining_seats === 0) return "#44ff4444"
                    if (st === "few" || (modelData.remaining_seats !== null && modelData.remaining_seats <= 15)) return "#44ffaa00"
                    if (st === "available") return "#3344cc44"
                    return Util.alpha(Color.accent, 0.2)
                  }
                  implicitWidth: seatTxt.implicitWidth + Style.space(8)
                  implicitHeight: Style.space(20)

                  Text {
                    id: seatTxt
                    anchors.centerIn: parent
                    text: {
                      if (modelData.remaining_seats !== null && modelData.remaining_seats !== undefined) {
                        var seats = modelData.remaining_seats + (modelData.total_seats ? ("/" + modelData.total_seats) : "")
                        return rootScheduleView.englishMode ? ("Seats: " + seats) : ("残 " + seats)
                      }
                      var st = modelData.seat_status
                      if (st === "available") return rootScheduleView.englishMode ? "◎ Avail" : "◎ 空席あり"
                      if (st === "few") return rootScheduleView.englishMode ? "△ Few" : "△ 残少"
                      if (st === "full") return rootScheduleView.englishMode ? "✕ Full" : "✕ 満席"
                      if (st === "unsold") return rootScheduleView.englishMode ? "- Unsold" : "- 販売前"
                      return ""
                    }
                    color: rootScheduleView.bar ? rootScheduleView.bar.foreground : Color.foreground
                    font.pixelSize: Style.font ? Style.font.caption : 10
                  }
                }

                // 上映回ごとのチケット予約ボタン
                Rectangle {
                  visible: Boolean(modelData.booking_url)
                  radius: Style.space(4)
                  color: stBookHover.containsMouse ? Util.alpha(Color.accent, 0.35) : Util.alpha(Color.accent, 0.15)
                  border.color: Util.alpha(Color.accent, 0.4)
                  border.width: 1
                  implicitWidth: stBookTxt.implicitWidth + Style.space(8)
                  implicitHeight: Style.space(20)
                  z: 2

                  Text {
                    id: stBookTxt
                    anchors.centerIn: parent
                    text: "🎟️"
                    font.pixelSize: Style.font ? Style.font.caption : 10
                  }

                  MouseArea {
                    id: stBookHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: function(mouse) {
                      mouse.accepted = true
                      rootScheduleView.openExternalUrl(modelData.booking_url)
                    }
                    onEntered: if (rootScheduleView.bar) rootScheduleView.bar.showTooltip(parent, rootScheduleView.englishMode ? ("Book ticket for " + modelData.start_time) : (modelData.start_time + " のチケットを予約購入"))
                    onExited: if (rootScheduleView.bar) rootScheduleView.bar.hideTooltip(parent)
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
