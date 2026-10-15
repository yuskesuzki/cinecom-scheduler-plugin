import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "com.yusuke.cinecom-scheduler"

  // 状態プロパティ (shell.json の entry から取得、フォールバック付き)
  property string selectedChain: String(root.setting("chain", "aeon"))
  property string selectedTheater: String(root.setting("theater", "ebetsu"))
  property real withinHours: Number(root.setting("withinHours", 3.0))
  property bool showAllDayToday: Boolean(root.setting("showAllDayToday", false))
  property bool englishMode: Boolean(root.setting("englishMode", false))
  property string selectedDate: "today" // "yesterday", "today", "tomorrow"

  property string theaterDisplayName: "江別"
  property var rawMoviesData: []
  property var moviesData: []
  property var allChains: []
  property var allTheaters: []
  property bool loading: false
  property string errorMessage: ""
  property string payloadMessage: ""
  property bool popupOpen: false
  property bool showSettingsPanel: false
  property bool chainDropdownOpen: false
  property string theaterSearchText: ""
  property string selectedMovieFilter: ""
  property bool movieFilterDropdownOpen: false

  readonly property var uniqueMovieTitles: {
    var titles = []
    if (!root.moviesData) return titles
    for (var i = 0; i < root.moviesData.length; i++) {
      var t = root.moviesData[i].title
      if (t && titles.indexOf(t) === -1) {
        titles.push(t)
      }
    }
    titles.sort(function(a, b) {
      return a.localeCompare(b, root.englishMode ? "en" : "ja")
    })
    return titles
  }

  readonly property var filteredMovies: {
    if (!root.moviesData) return []
    if (!root.selectedMovieFilter || root.selectedMovieFilter === "") {
      return root.moviesData
    }
    var list = []
    for (var i = 0; i < root.moviesData.length; i++) {
      if (root.moviesData[i].title === root.selectedMovieFilter) {
        list.push(root.moviesData[i])
      }
    }
    return list
  }

  readonly property var availableChains: [
    { id: "aeon", nameJa: "イオンシネマ", nameEn: "AEON CINEMA" },
    { id: "toho", nameJa: "TOHOシネマズ", nameEn: "TOHO CINEMAS" }
  ]

  function getChainDisplayName(chainId) {
    var cId = chainId || root.selectedChain
    for (var i = 0; i < root.availableChains.length; i++) {
      if (root.availableChains[i].id === cId) {
        return root.englishMode ? root.availableChains[i].nameEn : root.availableChains[i].nameJa
      }
    }
    return root.englishMode ? "Cinema" : "シネコン"
  }
  readonly property var filteredTheaters: {
    var list = []
    var filter = (root.theaterSearchText || "").trim().toLowerCase()
    for (var i = 0; i < root.allTheaters.length; i++) {
      var t = root.allTheaters[i]
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
  property bool showScreenModal: false
  property string currentScreenTitle: ""
  property var currentScreenFacility: null

  function showScreenDetails(screenName, facilityData) {
    currentScreenTitle = screenName
    if (facilityData) {
      currentScreenFacility = facilityData
    } else {
      currentScreenFacility = root.findScreenFacility(screenName)
    }
    showScreenModal = true
  }

  function findScreenFacility(screenName) {
    for (var i = 0; i < allTheaters.length; i++) {
      if (allTheaters[i].id === selectedTheater && allTheaters[i].facility && allTheaters[i].facility.screens) {
        var screens = allTheaters[i].facility.screens
        var numMatch = screenName.match(/\d+/)
        for (var j = 0; j < screens.length; j++) {
          var s = screens[j]
          if (s.name === screenName) return s
          if (numMatch && s.name.indexOf(numMatch[0]) !== -1) return s
        }
      }
    }
    return null
  }

  function getSeatRows(seatsObj) {
    if (!seatsObj) return []
    var rows = []
    for (var k in seatsObj) {
      if (k !== "合 計" && k !== "合計" && k !== "total" && k !== "Total") {
        rows.push({ type: k, count: seatsObj[k] })
      }
    }
    return rows
  }

  function openExternalUrl(url) {
    if (!url || typeof url !== "string") return
    var trimmed = url.trim()
    if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) return
    Qt.openUrlExternally(trimmed)
  }

  onShowSettingsPanelChanged: {
    if (showSettingsPanel) {
      Qt.callLater(function() {
        if (typeof searchInput !== "undefined" && searchInput) {
          searchInput.forceActiveFocus()
        }
      })
    } else {
      theaterSearchText = ""
      chainDropdownOpen = false
    }
  }

  readonly property string pluginDirPath: String(Qt.resolvedUrl(".")).replace(/^file:\/\//, "")
  readonly property string scriptPath: String(Qt.resolvedUrl("aeoncinema_scraper.py")).replace(/^file:\/\//, "")
  readonly property string theaterJsonPath: String(Qt.resolvedUrl("data/theaters.json")).replace(/^file:\/\//, "")
  readonly property string legacyTheaterJsonPath: String(Qt.resolvedUrl("theater.json")).replace(/^file:\/\//, "")

  // バー上の表示テキスト
  readonly property string barSummaryText: {
    if (loading) return "..."
    if (moviesData.length > 0) {
      return englishMode ? (moviesData.length + " movies") : (moviesData.length + "本")
    }
    return englishMode ? "0 movies" : "0本"
  }

  readonly property string barTooltipText: {
    var title = root.getChainDisplayName()
    var dateLabel = selectedDate === "yesterday"
      ? (englishMode ? "Yesterday" : "昨日")
      : (selectedDate === "tomorrow"
          ? (englishMode ? "Tomorrow" : "明日")
          : (showAllDayToday
              ? (englishMode ? "All day" : "終日")
              : (englishMode ? (withinHours + "h window") : (withinHours + "時間以内"))))
    return title + " - " + theaterDisplayName + " (" + dateLabel + ")"
  }

  function getTargetDateString() {
    var target = new Date()
    if (root.selectedDate === "tomorrow") {
      target.setDate(target.getDate() + 1)
    } else if (root.selectedDate === "yesterday") {
      target.setDate(target.getDate() - 1)
    }
    var y = target.getFullYear()
    var m = String(target.getMonth() + 1).padStart(2, "0")
    var d = String(target.getDate()).padStart(2, "0")
    return y + "-" + m + "-" + d
  }

  function getTargetDateFormatted() {
    var target = new Date()
    if (root.selectedDate === "tomorrow") {
      target.setDate(target.getDate() + 1)
    } else if (root.selectedDate === "yesterday") {
      target.setDate(target.getDate() - 1)
    }
    var y = target.getFullYear()
    var m = String(target.getMonth() + 1).padStart(2, "0")
    var d = String(target.getDate()).padStart(2, "0")

    if (root.englishMode) {
      var daysEn = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
      var dayNameEn = daysEn[target.getDay()]
      return y + "-" + m + "-" + d + " (" + dayNameEn + ")"
    } else {
      var daysJa = ["日", "月", "火", "水", "木", "金", "土"]
      var dayNameJa = daysJa[target.getDay()]
      return y + "年" + m + "月" + d + "日(" + dayNameJa + ")"
    }
  }

  function buildFetchCommand() {
    return [
      "python3",
      "-c",
      "import sys; sys.path.insert(0, sys.argv[1]); from scraper.cli import main; sys.exit(main(sys.argv[2:]))",
      root.pluginDirPath,
      "--chain",
      root.selectedChain || "aeon",
      "--theater",
      root.selectedTheater,
      "--date",
      root.getTargetDateString(),
      "--compact"
    ]
  }

  function applyMovieFilter() {
    var rawMovies = root.rawMoviesData || []
    var normalizedMovies = []

    // 現在時刻と抽出時間枠（今日の場合）
    var now = new Date()
    var currentMinutes = now.getHours() * 60 + now.getMinutes()
    var maxMinutes = currentMinutes + Math.round(root.withinHours * 60)

    for (var i = 0; i < rawMovies.length; i++) {
      var m = rawMovies[i]
      var title = m.movie_title || m.title || ""
      var screenings = m.screenings || m.showtimes || []
      var filteredShowtimes = []

      for (var j = 0; j < screenings.length; j++) {
        var s = screenings[j]
        var startTime = s.start_time || ""
        var endTime = s.end_time || ""
        var screenName = s.screen_name || s.screen || ""
        var tags = s.tags || s.special_badges || []
        var seatStatus = s.seat_status || "unknown"
        var bookingUrl = s.booking_url || ""

        // "today" かつ showAllDayToday でないときは withinHours 時間以内の上映枠にフィルタリング
        if (root.selectedDate === "today" && !root.showAllDayToday && startTime) {
          var parts = startTime.split(":")
          if (parts.length === 2) {
            var startMinutes = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10)
            if (startMinutes < currentMinutes || startMinutes > maxMinutes) {
              continue
            }
          }
        }

        filteredShowtimes.push({
          start_time: startTime,
          end_time: endTime,
          screen: screenName,
          special_badges: tags,
          seat_status: seatStatus,
          booking_url: bookingUrl,
          remaining_seats: s.remaining_seats !== undefined ? s.remaining_seats : null,
          total_seats: s.total_seats !== undefined ? s.total_seats : null,
          screen_facility: s.screen_facility || root.findScreenFacility(screenName)
        })
      }

      if (filteredShowtimes.length > 0) {
        normalizedMovies.push({
          movie_id: m.movie_id || m.id || "",
          title: title,
          booking_url: (m.booking_url || (filteredShowtimes[0] ? filteredShowtimes[0].booking_url : "")),
          showtimes: filteredShowtimes
        })
      }
    }

    normalizedMovies.sort(function(a, b) {
      var timeA = (a.showtimes && a.showtimes.length > 0) ? a.showtimes[0].start_time : "99:99"
      var timeB = (b.showtimes && b.showtimes.length > 0) ? b.showtimes[0].start_time : "99:99"
      if (timeA !== timeB) return timeA.localeCompare(timeB)
      return (a.title || "").localeCompare(b.title || "")
    })
    root.moviesData = normalizedMovies
  }

  // 劇場データの読み込み (Process)
  Process {
    id: fetchProcess
    running: false
    command: root.buildFetchCommand()

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.loading = false
        root.errorMessage = ""
        root.payloadMessage = ""
        try {
          var payload = JSON.parse(text)
          root.theaterDisplayName = payload.theater_name || payload.theater || root.selectedTheater
          root.rawMoviesData = payload.movies || []
          root.payloadMessage = payload.message || ""
          root.applyMovieFilter()
          console.log("[CinecomScheduler] Successfully fetched " + root.moviesData.length + " movies for " + root.theaterDisplayName + " (" + root.selectedDate + ")")
        } catch (e) {
          console.error("[CinecomScheduler] JSON parse error: " + e.message)
          root.errorMessage = root.englishMode ? "Failed to parse schedule" : "スケジュールの解析に失敗しました"
        }
      }
    }

    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (text && text.trim().length > 0) {
          console.warn("[CinecomScheduler] fetch stderr:", text.trim())
          try {
            var errPayload = JSON.parse(text)
            if (errPayload.message) {
              root.errorMessage = errPayload.message
            }
          } catch (ignored) {}
        }
      }
    }

    onExited: function(exitCode, exitStatus) {
      root.loading = false
      if (exitCode !== 0 && root.errorMessage === "") {
        root.errorMessage = root.englishMode ? "Failed to fetch schedule" : "スケジュール取得エラー"
      }
    }
  }

  function updateTheatersForCurrentChain() {
    var list = []
    if (root.allChains && root.allChains.length > 0) {
      for (var c = 0; c < root.allChains.length; c++) {
        if (root.allChains[c].id === root.selectedChain && Array.isArray(root.allChains[c].theaters)) {
          list = root.allChains[c].theaters
          break
        }
      }
    }
    root.allTheaters = list
    var found = false
    for (var i = 0; i < root.allTheaters.length; i++) {
      if (root.allTheaters[i].id === root.selectedTheater) {
        root.theaterDisplayName = root.allTheaters[i].name
        found = true
        break
      }
    }
    if (!found && root.allTheaters.length > 0) {
      root.selectedTheater = root.allTheaters[0].id
      root.theaterDisplayName = root.allTheaters[0].name
    }
  }

  // theaters.json 読み込み用 Process
  Process {
    id: loadTheatersProcess
    running: false
    command: ["cat", root.theaterJsonPath]

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var data = JSON.parse(text)
          if (Array.isArray(data)) {
            root.allChains = [{ id: "aeon", name: "イオンシネマ", theaters: data }]
          } else if (data.chains && Array.isArray(data.chains)) {
            root.allChains = data.chains
          }
          root.updateTheatersForCurrentChain()
          console.log("[CinemaPlugin] Loaded " + root.allTheaters.length + " theaters for chain: " + root.selectedChain)
        } catch (e) {
          console.warn("[CinemaPlugin] Error parsing theaters json:", e.message)
        }
      }
    }

    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (text && text.trim().length > 0) {
          console.warn("[CinemaPlugin] loadTheaters stderr:", text.trim())
        }
      }
    }

    onExited: function(exitCode, exitStatus) {
      if (exitCode !== 0 && root.allChains.length === 0) {
        console.warn("[CinemaPlugin] Failed to read " + root.theaterJsonPath + ", trying legacy path: " + root.legacyTheaterJsonPath)
        loadTheatersProcess.command = ["cat", root.legacyTheaterJsonPath]
        loadTheatersProcess.running = true
      }
    }
  }

  // 設定を config.json に同期する Process
  Process {
    id: syncConfigProcess
    running: false
    command: [
      "python3",
      root.scriptPath,
      root.selectedTheater,
      "--within-hours",
      String(root.withinHours),
      root.englishMode ? "--en" : "--lang=ja",
      "--save-config"
    ]
  }

  function refresh() {
    if (!fetchProcess.running) {
      loading = true
      fetchProcess.command = root.buildFetchCommand()
      fetchProcess.running = true
    }
  }

  function syncConfig() {
    if (root.selectedChain === "aeon" && !syncConfigProcess.running) {
      syncConfigProcess.command = [
        "python3",
        root.scriptPath,
        root.selectedTheater,
        "--within-hours",
        String(root.withinHours),
        root.englishMode ? "--en" : "--lang=ja",
        "--save-config"
      ]
      syncConfigProcess.running = true
    }
  }

  // 設定の永続化 (Omarchy shell.json + Python config.json)
  function persistSettings(newTheater, newHours, newEn, newChain, newAllDay) {
    var entry = { id: root.moduleName || "com.yusuke.cinecom-scheduler" }
    for (var k in root.settings) {
      if (k !== "id") entry[k] = root.settings[k]
    }
    if (newChain !== undefined) entry.chain = newChain
    if (newTheater !== undefined) entry.theater = newTheater
    if (newHours !== undefined) entry.withinHours = newHours
    if (newEn !== undefined) entry.englishMode = newEn
    if (newAllDay !== undefined) entry.showAllDayToday = newAllDay
    root.settings = entry
    if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function") {
      root.bar.shell.updateEntryInline(root.moduleName || "com.yusuke.cinecom-scheduler", entry)
    }
    syncConfig()
  }

  function toggleShowAllDayToday() {
    showAllDayToday = !showAllDayToday
    selectedMovieFilter = ""
    movieFilterDropdownOpen = false
    persistSettings(undefined, undefined, undefined, undefined, showAllDayToday)
    if (root.rawMoviesData && root.rawMoviesData.length > 0) {
      applyMovieFilter()
    } else {
      refresh()
    }
  }

  function selectChain(chainId) {
    if (root.selectedChain === chainId) return
    root.selectedChain = chainId
    root.rawMoviesData = []
    root.selectedMovieFilter = ""
    root.movieFilterDropdownOpen = false
    root.updateTheatersForCurrentChain()
    root.persistSettings(root.selectedTheater, undefined, undefined, chainId)
    root.refresh()
  }

  function selectTheater(id, name) {
    selectedTheater = id
    theaterDisplayName = name
    rawMoviesData = []
    selectedMovieFilter = ""
    movieFilterDropdownOpen = false
    showSettingsPanel = false
    persistSettings(id, undefined, undefined, undefined)
    refresh()
  }

  function setHours(h) {
    withinHours = h
    selectedMovieFilter = ""
    movieFilterDropdownOpen = false
    persistSettings(undefined, h, undefined)
    if (root.rawMoviesData && root.rawMoviesData.length > 0) {
      applyMovieFilter()
    } else {
      refresh()
    }
  }

  function toggleLanguage() {
    englishMode = !englishMode
    persistSettings(undefined, undefined, englishMode)
    refresh()
  }

  function open() {
    popupOpen = true
  }

  function close() {
    popupOpen = false
    movieFilterDropdownOpen = false
    chainDropdownOpen = false
  }

  function toggle() {
    if (popupOpen) {
      close()
    } else {
      open()
    }
  }

  Component.onCompleted: {
    loadTheatersProcess.running = true
    refresh()
  }

  // 15分ごとに自動更新
  Timer {
    interval: 15 * 60 * 1000
    repeat: true
    running: true
    onTriggered: root.refresh()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // バー上のボタンスロット (テキストとアイコンを含むため WidgetButton を使用)
  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "🎬 " + root.barSummaryText
    tooltipText: root.barTooltipText

    onPressed: function(mouseButton) {
      if (mouseButton === Qt.RightButton || mouseButton === Qt.MiddleButton) {
        root.refresh()
      } else {
        root.toggle()
      }
    }
  }

  // ポップアップ詳細パネル (キーボード入力対応のため KeyboardPanel を使用)
  KeyboardPanel {
    id: popup
    anchorItem: root
    bar: root.bar
    owner: root
    open: root.popupOpen
    contentWidth: popup.fittedContentWidth(Style.space(440))
    contentHeight: popup.fittedContentHeight(mainColumn.implicitHeight, Style.space(580))

    onOpenChanged: {
      if (root.popupOpen !== open) {
        root.popupOpen = open
      }
      if (!open) {
        root.showScreenModal = false
        root.showSettingsPanel = false
      }
    }

    Column {
      id: mainColumn
      width: parent.width
      spacing: Style.space(12)

      // 1. ヘッダーバー
      RowLayout {
        width: parent.width

        // タイトル & 劇場名 (クリックで劇場選択パネルを表示)
        Rectangle {
          radius: Style.space(6)
          color: titleHover.containsMouse ? Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.08) : "transparent"
          implicitWidth: titleRow.implicitWidth + Style.space(10)
          implicitHeight: titleRow.implicitHeight + Style.space(6)

          RowLayout {
            id: titleRow
            anchors.centerIn: parent
            spacing: Style.space(6)

            Text {
              text: "🎬"
              font.pixelSize: Style.font ? Style.font.title : 16
            }
            Text {
              text: root.getChainDisplayName()
              color: root.bar ? root.bar.foreground : Color.foreground
              font.pixelSize: Style.font ? Style.font.title : 16
              font.bold: true
            }
            // 劇場名バッジ
            Rectangle {
              radius: Style.space(4)
              color: root.showSettingsPanel ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.15)
              implicitWidth: theaterLabelRow.implicitWidth + Style.space(10)
              implicitHeight: theaterLabelRow.implicitHeight + Style.space(4)

              RowLayout {
                id: theaterLabelRow
                anchors.centerIn: parent
                spacing: Style.space(4)

                Text {
                  id: theaterLabel
                  text: root.theaterDisplayName
                  color: root.showSettingsPanel ? Color.background : (root.bar ? root.bar.foreground : Color.foreground)
                  font.pixelSize: Style.font ? Style.font.caption : 11
                  font.bold: true
                }
                Text {
                  text: "⚙"
                  color: root.showSettingsPanel ? Color.background : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.6)
                  font.pixelSize: Style.font ? Style.font.caption : 9
                }
              }
            }
          }

          MouseArea {
            id: titleHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              root.showSettingsPanel = true
            }
            onEntered: if (root.bar) root.bar.showTooltip(parent, root.englishMode ? "Click to configure chain, theater & hours" : "クリックして系列・劇場・抽出範囲を設定")
            onExited: if (root.bar) root.bar.hideTooltip(parent)
          }
        }

        // 劇場の公式ホームページ閲覧アイコン [HP]
        Rectangle {
          radius: Style.space(4)
          color: hpHover.containsMouse ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.1)
          border.color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.15)
          border.width: 1
          implicitWidth: hpLabel.implicitWidth + Style.space(10)
          implicitHeight: Style.space(24)

          Text {
            id: hpLabel
            anchors.centerIn: parent
            text: "[HP]"
            color: hpHover.containsMouse ? Color.background : (root.bar ? root.bar.foreground : Color.foreground)
            font.pixelSize: Style.font ? Style.font.caption : 11
            font.bold: true
          }

          MouseArea {
            id: hpHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              var url = ""
              if (root.selectedChain === "toho") {
                url = "https://hlo.tohotheater.jp/net/schedule/" + encodeURIComponent(root.selectedTheater) + "/TNPI2000J01.do"
              } else {
                url = "https://theater.aeoncinema.com/theaters/" + encodeURIComponent(root.selectedTheater) + "/"
              }
              root.openExternalUrl(url)
            }
            onEntered: if (root.bar) root.bar.showTooltip(parent, root.englishMode ? "Open theater homepage" : (root.theaterDisplayName + " の公式ホームページを開く"))
            onExited: if (root.bar) root.bar.hideTooltip(parent)
          }
        }

        Item { Layout.fillWidth: true }

        // 言語切替ボタン (JA / EN)
        Rectangle {
          radius: Style.space(4)
          color: root.englishMode ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.1)
          implicitWidth: langText.implicitWidth + Style.space(12)
          implicitHeight: Style.space(26)

          Text {
            id: langText
            anchors.centerIn: parent
            text: root.englishMode ? "EN" : "JA"
            color: root.englishMode ? Color.background : (root.bar ? root.bar.foreground : Color.foreground)
            font.pixelSize: Style.font ? Style.font.caption : 11
            font.bold: true
          }

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.toggleLanguage()
          }
        }

        // 設定トグルボタン
        Rectangle {
          radius: Style.space(4)
          color: root.showSettingsPanel ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.1)
          implicitWidth: Style.space(26)
          implicitHeight: Style.space(26)

          Text {
            anchors.centerIn: parent
            text: "⚙"
            color: root.showSettingsPanel ? Color.background : (root.bar ? root.bar.foreground : Color.foreground)
            font.pixelSize: Style.font ? Style.font.caption : 12
          }

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.showSettingsPanel = !root.showSettingsPanel
          }
        }

        // 更新ボタン
        Rectangle {
          radius: Style.space(4)
          color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.1)
          implicitWidth: Style.space(26)
          implicitHeight: Style.space(26)

          Text {
            anchors.centerIn: parent
            text: "🔄"
            color: root.bar ? root.bar.foreground : Color.foreground
            font.pixelSize: Style.font ? Style.font.caption : 12
          }

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.refresh()
          }
        }
      }

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
            property bool isSelected: root.selectedDate === modelData.id
            color: isSelected ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.08)
            border.color: isSelected ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.15)
            border.width: 1
            implicitHeight: Style.space(26)

            Text {
              anchors.centerIn: parent
              text: root.englishMode ? modelData.labelEn : modelData.labelJa
              color: parent.isSelected ? Color.background : (root.bar ? root.bar.foreground : Color.foreground)
              font.pixelSize: Style.font ? Style.font.caption : 11
              font.bold: parent.isSelected
            }

            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: {
                if (root.selectedDate !== modelData.id) {
                  root.selectedDate = modelData.id
                  root.rawMoviesData = []
                  root.selectedMovieFilter = ""
                  root.movieFilterDropdownOpen = false
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
            if (root.selectedDate === "tomorrow") {
              return root.englishMode
                ? ("Tomorrow's Showtimes (" + root.getTargetDateFormatted() + "):")
                : ("明日の上映作品一覧 (" + root.getTargetDateFormatted() + "):")
            } else {
              var dateStr = " (" + root.getTargetDateFormatted() + "):"
              if (root.showAllDayToday) {
                return root.englishMode ? ("Today's All Showtimes" + dateStr) : ("今日の上映作品一覧 (終日)" + dateStr)
              } else {
                return root.englishMode
                  ? ("Upcoming in " + root.withinHours + " hours" + dateStr)
                  : ("直近 " + root.withinHours + " 時間の上映作品" + dateStr)
              }
            }
          }
          color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.7)
          font.pixelSize: Style.font ? Style.font.caption : 12
          font.bold: true
          elide: Text.ElideRight
        }

        // 今日の場合の「終日(時系列) / 直近」切替スイッチ
        Rectangle {
          visible: root.selectedDate === "today"
          radius: Style.space(4)
          color: allDayToggleHover.containsMouse
            ? Util.alpha(Color.accent, 0.18)
            : (root.showAllDayToday ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.08))
          border.color: root.showAllDayToday ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.2)
          border.width: 1
          implicitWidth: allDayToggleTxt.implicitWidth + Style.space(12)
          implicitHeight: Style.space(22)

          RowLayout {
            anchors.centerIn: parent
            spacing: Style.space(4)

            Text {
              id: allDayToggleTxt
              text: {
                if (root.englishMode) {
                  return root.showAllDayToday ? "🕒 All Day" : ("🕒 " + root.withinHours + "h")
                } else {
                  return root.showAllDayToday ? "🕒 終日(時系列)" : ("🕒 直近" + root.withinHours + "h")
                }
              }
              color: root.showAllDayToday
                ? Color.background
                : (root.bar ? root.bar.foreground : Color.foreground)
              font.pixelSize: Style.font ? Style.font.caption : 10
              font.bold: true
            }
          }

          MouseArea {
            id: allDayToggleHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.toggleShowAllDayToday()
            onEntered: if (root.bar) {
              root.bar.showTooltip(parent, root.englishMode
                ? (root.showAllDayToday ? "Switch to upcoming hours window" : "Switch to all-day showtimes in chronological order")
                : (root.showAllDayToday ? "直近時間枠表示に切り替え" : "一日の全上映を時系列順に表示"))
            }
            onExited: if (root.bar) root.bar.hideTooltip(parent)
          }
        }

        Text {
          visible: root.loading
          text: root.englishMode ? "Loading..." : "読み込み中..."
          color: Color.accent
          font.pixelSize: Style.font ? Style.font.caption : 11
        }
      }

      // 作品名絞り込みドロップダウン (作品が1件以上ある場合のみ表示)
      Column {
        width: parent.width
        spacing: Style.space(4)
        visible: !root.loading && root.moviesData.length > 0

        // トリガーボタン
        Rectangle {
          id: movieFilterTrigger
          width: parent.width
          implicitHeight: Style.space(28)
          radius: Style.space(4)
          color: movieTriggerHover.containsMouse || root.movieFilterDropdownOpen
            ? Util.alpha(Color.accent, 0.12)
            : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.06)
          border.color: root.movieFilterDropdownOpen
            ? Color.accent
            : (root.selectedMovieFilter !== "" ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.18))
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
                if (root.selectedMovieFilter === "") {
                  return root.englishMode
                    ? ("All Movies (" + root.moviesData.length + ")")
                    : ("すべての作品 (" + root.moviesData.length + "本)")
                }
                return root.selectedMovieFilter
              }
              color: root.selectedMovieFilter !== "" ? Color.accent : (root.bar ? root.bar.foreground : Color.foreground)
              font.pixelSize: Style.font ? Style.font.caption : 11
              font.bold: root.selectedMovieFilter !== ""
              elide: Text.ElideRight
            }

            // クリアボタン (個別作品選択時のみ表示)
            Rectangle {
              visible: root.selectedMovieFilter !== ""
              radius: Style.space(3)
              color: clearMovieHover.containsMouse ? Util.alpha(Color.accent, 0.2) : "transparent"
              implicitWidth: Style.space(18)
              implicitHeight: Style.space(18)

              Text {
                anchors.centerIn: parent
                text: "✕"
                color: clearMovieHover.containsMouse ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.6)
                font.pixelSize: Style.font ? Style.font.caption : 10
              }

              MouseArea {
                id: clearMovieHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                  root.selectedMovieFilter = ""
                  root.movieFilterDropdownOpen = false
                }
              }
            }

            Text {
              text: root.movieFilterDropdownOpen ? "▲" : "▼"
              color: root.movieFilterDropdownOpen ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.5)
              font.pixelSize: Style.font ? Style.font.caption : 9
            }
          }

          MouseArea {
            id: movieTriggerHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              root.movieFilterDropdownOpen = !root.movieFilterDropdownOpen
            }
          }
        }

        // 展開時の選択肢リスト (スクロール対応)
        Rectangle {
          id: movieFilterListCard
          width: parent.width
          visible: root.movieFilterDropdownOpen
          radius: Style.space(4)
          color: root.bar ? root.bar.background : Color.background
          border.color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.2)
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
                property bool isSelected: root.selectedMovieFilter === ""
                color: {
                  if (isSelected) return Color.accent
                  if (allHover.containsMouse) return Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.08)
                  return "transparent"
                }

                RowLayout {
                  anchors.fill: parent
                  anchors.leftMargin: Style.space(8)
                  anchors.rightMargin: Style.space(8)
                  spacing: Style.space(6)

                  Text {
                    Layout.fillWidth: true
                    text: root.englishMode ? ("All Movies (" + root.moviesData.length + ")") : ("すべての作品 (" + root.moviesData.length + "本)")
                    color: allMoviesOption.isSelected ? Color.background : (root.bar ? root.bar.foreground : Color.foreground)
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
                    root.selectedMovieFilter = ""
                    root.movieFilterDropdownOpen = false
                  }
                }
              }

              // 2. 各作品の項目
              Repeater {
                model: root.uniqueMovieTitles

                delegate: Rectangle {
                  id: movieOptionItem
                  width: parent.width
                  implicitHeight: Style.space(26)
                  radius: Style.space(3)
                  property bool isSelected: root.selectedMovieFilter === modelData
                  color: {
                    if (isSelected) return Color.accent
                    if (optHover.containsMouse) return Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.08)
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
                      color: movieOptionItem.isSelected ? Color.background : (root.bar ? root.bar.foreground : Color.foreground)
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
                      root.selectedMovieFilter = modelData
                      root.movieFilterDropdownOpen = false
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
        visible: root.errorMessage !== ""
        text: root.errorMessage
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
          visible: !root.loading && root.filteredMovies.length === 0 && root.errorMessage === ""

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
                if (root.payloadMessage) return root.payloadMessage
                if (root.moviesData.length > 0 && root.selectedMovieFilter !== "") {
                  return root.englishMode ? "No showtimes for selected movie" : "選択した作品の上映枠はありません"
                }
                if (root.selectedDate === "tomorrow") {
                  return root.englishMode ? "No showtimes available for tomorrow" : "明日の上映作品はありません"
                } else if (root.showAllDayToday) {
                  return root.englishMode ? "No showtimes available today" : "今日の上映作品はありません"
                } else {
                  return root.englishMode ? "No upcoming showtimes within window" : "直近の上映作品はありません"
                }
              }
              color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.6)
              font.pixelSize: Style.font ? Style.font.body : 12
            }
          }
        }

        Column {
          id: movieColumn
          width: parent.width
          spacing: Style.space(8)

          Repeater {
            model: root.filteredMovies

            delegate: Rectangle {
              width: movieColumn.width
              radius: Style.space(6)
              color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.05)
              border.color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.1)
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

                  Text {
                    Layout.fillWidth: true
                    text: modelData.title
                    color: root.bar ? root.bar.foreground : Color.foreground
                    font.pixelSize: Style.font ? Style.font.body : 13
                    font.bold: true
                    wrapMode: Text.WordWrap
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
                      text: root.englishMode ? "🎟️ Book" : "🎟️ 予約購入"
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
                        root.openExternalUrl(modelData.booking_url)
                      }
                      onEntered: if (root.bar) root.bar.showTooltip(parent, root.englishMode ? "Book ticket on official Watatheatre site" : "ワタシアター予約購入ページを開く")
                      onExited: if (root.bar) root.bar.hideTooltip(parent)
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
                      color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.12)
                      implicitWidth: timeTxt.implicitWidth + Style.space(8)
                      implicitHeight: Style.space(20)

                      Text {
                        id: timeTxt
                        anchors.centerIn: parent
                        text: modelData.start_time + " 〜 " + modelData.end_time
                        color: root.bar ? root.bar.foreground : Color.foreground
                        font.pixelSize: Style.font ? Style.font.caption : 11
                        font.bold: true
                      }
                    }

                    // スクリーン名 (クリックで設備・座席詳細ポップアップ)
                    Rectangle {
                      radius: Style.space(3)
                      color: screenHover.containsMouse ? Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.12) : "transparent"
                      implicitWidth: screenTxt.implicitWidth + Style.space(6)
                      implicitHeight: Style.space(20)

                      Text {
                        id: screenTxt
                        anchors.centerIn: parent
                        text: modelData.screen
                        color: screenHover.containsMouse ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.8)
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
                        onEntered: if (root.bar) root.bar.showTooltip(parent, root.englishMode ? ("Click to view details for " + modelData.screen) : (modelData.screen + " の設備・座席詳細を表示"))
                        onExited: if (root.bar) root.bar.hideTooltip(parent)
                      }
                    }

                    // 特殊設備バッジ ("[IMAX]", "[4DX]", "[VIVE AUDIO]", "[Dolby Atmos]", "[THX]")
                    Repeater {
                      model: modelData.special_badges || []

                      delegate: Rectangle {
                        radius: Style.space(3)
                        color: Util.alpha(Color.accent, 0.18)
                        border.color: Util.alpha(Color.accent, 0.5)
                        border.width: 1
                        implicitWidth: badgeTxt.implicitWidth + Style.space(6)
                        implicitHeight: Style.space(18)

                        Text {
                          id: badgeTxt
                          anchors.centerIn: parent
                          text: "[" + modelData + "]"
                          color: Color.accent
                          font.pixelSize: Style.font ? Style.font.caption : 10
                          font.bold: true
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
                            return root.englishMode ? ("Seats: " + seats) : ("残 " + seats)
                          }
                          var st = modelData.seat_status
                          if (st === "available") return root.englishMode ? "◎ Avail" : "◎ 空席あり"
                          if (st === "few") return root.englishMode ? "△ Few" : "△ 残少"
                          if (st === "full") return root.englishMode ? "✕ Full" : "✕ 満席"
                          if (st === "unsold") return root.englishMode ? "- Unsold" : "- 販売前"
                          return ""
                        }
                        color: root.bar ? root.bar.foreground : Color.foreground
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
                          root.openExternalUrl(modelData.booking_url)
                        }
                        onEntered: if (root.bar) root.bar.showTooltip(parent, root.englishMode ? ("Book ticket for " + modelData.start_time) : (modelData.start_time + " のチケットを予約購入"))
                        onExited: if (root.bar) root.bar.hideTooltip(parent)
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

    // スクリーン設備詳細モーダル (半透明オーバーレイ + 詳細カード)
    Rectangle {
      id: screenModalOverlay
      visible: root.showScreenModal
      anchors.fill: parent
      color: Util.alpha(Color.background, 0.85)
      z: 50

      MouseArea {
        anchors.fill: parent
        onClicked: root.showScreenModal = false
      }

      Rectangle {
        id: screenModalCard
        anchors.centerIn: parent
        width: Math.min(parent.width - Style.space(28), Style.space(380))
        implicitHeight: modalColumn.implicitHeight + Style.space(28)
        radius: Style.space(8)
        color: (typeof Color.surface !== "undefined" && Color.surface) ? Color.surface : (root.bar ? root.bar.background : Color.background)
        border.color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.15)
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
                text: root.currentScreenTitle || (root.currentScreenFacility ? root.currentScreenFacility.name : "")
                color: root.bar ? root.bar.foreground : Color.foreground
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
                color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.7)
                font.pixelSize: Style.font ? Style.font.caption : 12
                font.bold: true
              }

              MouseArea {
                id: closeModalHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.showScreenModal = false
              }
            }
          }

          // 区切り線
          Rectangle {
            width: parent.width
            height: 1
            color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.1)
          }

          // 2. 設備 (Features)
          Column {
            width: parent.width
            spacing: Style.space(6)

            Text {
              text: root.englishMode ? "Features & Audio" : "設備・音響"
              color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.7)
              font.pixelSize: Style.font ? Style.font.caption : 11
              font.bold: true
            }

            Flow {
              width: parent.width
              spacing: Style.space(6)

              Repeater {
                model: (root.currentScreenFacility && root.currentScreenFacility.features && root.currentScreenFacility.features.length > 0) ? root.currentScreenFacility.features : []

                delegate: Rectangle {
                  radius: Style.space(4)
                  color: {
                    var name = String(modelData)
                    if (name.indexOf("IMAX") !== -1 || name.indexOf("4DX") !== -1 || name.indexOf("Dolby") !== -1 || name.indexOf("THX") !== -1 || name.indexOf("VIVE") !== -1) {
                      return Util.alpha(Color.accent, 0.25)
                    }
                    return Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.08)
                  }
                  border.color: {
                    var name = String(modelData)
                    if (name.indexOf("IMAX") !== -1 || name.indexOf("4DX") !== -1 || name.indexOf("Dolby") !== -1 || name.indexOf("THX") !== -1 || name.indexOf("VIVE") !== -1) {
                      return Util.alpha(Color.accent, 0.6)
                    }
                    return Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.15)
                  }
                  border.width: 1
                  implicitWidth: featTxt.implicitWidth + Style.space(10)
                  implicitHeight: Style.space(22)

                  Text {
                    id: featTxt
                    anchors.centerIn: parent
                    text: modelData
                    color: root.bar ? root.bar.foreground : Color.foreground
                    font.pixelSize: Style.font ? Style.font.caption : 11
                    font.bold: true
                  }
                }
              }

              Text {
                visible: !root.currentScreenFacility || !root.currentScreenFacility.features || root.currentScreenFacility.features.length === 0
                text: root.englishMode ? "Standard Screen (No special equipment)" : "標準設備"
                color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.5)
                font.pixelSize: Style.font ? Style.font.caption : 11
              }
            }
          }

          // 区切り線
          Rectangle {
            width: parent.width
            height: 1
            color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.1)
          }

          // 3. 座席種類と席数
          Column {
            width: parent.width
            spacing: Style.space(6)

            RowLayout {
              width: parent.width
              Text {
                text: root.englishMode ? "Seat Breakdown" : "座席種類と席数"
                color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.7)
                font.pixelSize: Style.font ? Style.font.caption : 11
                font.bold: true
              }
              Item { Layout.fillWidth: true }
              Text {
                text: {
                  var total = (root.currentScreenFacility && root.currentScreenFacility.total_seats) ? root.currentScreenFacility.total_seats : "-"
                  return root.englishMode ? ("Total: " + total + " seats") : ("総座席数: " + total + "席")
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
                model: root.getSeatRows(root.currentScreenFacility ? root.currentScreenFacility.seats : null)

                delegate: Rectangle {
                  width: parent.width
                  implicitHeight: Style.space(22)
                  radius: Style.space(4)
                  color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.05)

                  RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Style.space(8)
                    anchors.rightMargin: Style.space(8)

                    Text {
                      text: modelData.type
                      color: root.bar ? root.bar.foreground : Color.foreground
                      font.pixelSize: Style.font ? Style.font.caption : 11
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                      text: modelData.count + (root.englishMode ? " seats" : " 席")
                      color: root.bar ? root.bar.foreground : Color.foreground
                      font.pixelSize: Style.font ? Style.font.caption : 11
                      font.bold: true
                    }
                  }
                }
              }

              Text {
                visible: !root.currentScreenFacility || !root.currentScreenFacility.seats
                text: root.englishMode ? "Seat breakdown unavailable" : "座席内訳情報がありません"
                color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.5)
                font.pixelSize: Style.font ? Style.font.caption : 11
              }
            }
          }

          // 4. 公式座席図リンク
          Rectangle {
            visible: Boolean(root.currentScreenFacility && root.currentScreenFacility.seat_map_url)
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
                text: root.englishMode ? "View Official Seat Map" : "公式座席図を開く"
                color: root.bar ? root.bar.foreground : Color.foreground
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
                if (root.currentScreenFacility && root.currentScreenFacility.seat_map_url) {
                  root.openExternalUrl(root.currentScreenFacility.seat_map_url)
                }
              }
            }
          }
        }
      }
    }

    // 設定モーダルポップアップ (系列・劇場・抽出時間範囲の選択)
    Rectangle {
      id: settingsModalOverlay
      visible: root.showSettingsPanel
      anchors.fill: parent
      color: Util.alpha(Color.background, 0.85)
      z: 60

      MouseArea {
        anchors.fill: parent
        onClicked: {
          root.showSettingsPanel = false
          root.chainDropdownOpen = false
        }
      }

      Rectangle {
        id: settingsModalCard
        anchors.centerIn: parent
        width: Math.min(parent.width - Style.space(24), Style.space(400))
        implicitHeight: settingsModalCol.implicitHeight + Style.space(28)
        radius: Style.space(8)
        color: (typeof Color.surface !== "undefined" && Color.surface) ? Color.surface : (root.bar ? root.bar.background : Color.background)
        border.color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.18)
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
                text: root.englishMode ? "Theater Settings" : "劇場・抽出設定"
                color: root.bar ? root.bar.foreground : Color.foreground
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
                color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.7)
                font.pixelSize: Style.font ? Style.font.caption : 12
                font.bold: true
              }

              MouseArea {
                id: closeSettingsHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                  root.showSettingsPanel = false
                  root.chainDropdownOpen = false
                }
              }
            }
          }

          // 区切り線
          Rectangle {
            width: parent.width
            height: 1
            color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.1)
          }

          // 2. シネコン系列選択
          Column {
            width: parent.width
            spacing: Style.space(4)

            Text {
              text: root.englishMode ? "Select Cinema Chain:" : "シネコン系列を選択:"
              color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.8)
              font.pixelSize: Style.font ? Style.font.caption : 11
              font.bold: true
            }

            // セレクトボックス (トリガーボタン)
            Rectangle {
              id: chainSelectTrigger
              width: parent.width
              implicitHeight: Style.space(30)
              radius: Style.space(4)
              color: chainTriggerHover.containsMouse || root.chainDropdownOpen
                ? Util.alpha(Color.accent, 0.12)
                : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.08)
              border.color: root.chainDropdownOpen
                ? Color.accent
                : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.25)
              border.width: 1

              RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Style.space(10)
                anchors.rightMargin: Style.space(10)
                spacing: Style.space(6)

                Text {
                  Layout.fillWidth: true
                  text: root.getChainDisplayName()
                  color: root.bar ? root.bar.foreground : Color.foreground
                  font.pixelSize: Style.font ? Style.font.caption : 12
                  font.bold: true
                  elide: Text.ElideRight
                }

                Text {
                  text: root.chainDropdownOpen ? "▲" : "▼"
                  color: root.chainDropdownOpen ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.6)
                  font.pixelSize: Style.font ? Style.font.caption : 10
                }
              }

              MouseArea {
                id: chainTriggerHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                  root.chainDropdownOpen = !root.chainDropdownOpen
                }
              }
            }

            // 展開時の選択肢
            Rectangle {
              id: chainDropdownList
              width: parent.width
              visible: root.chainDropdownOpen
              radius: Style.space(4)
              color: (typeof Color.surface !== "undefined" && Color.surface) ? Color.surface : (root.bar ? root.bar.background : Color.background)
              border.color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.2)
              border.width: 1
              implicitHeight: chainOptionsCol.implicitHeight + Style.space(4)

              Column {
                id: chainOptionsCol
                width: parent.width
                anchors.top: parent.top
                anchors.topMargin: Style.space(2)
                spacing: 0

                Repeater {
                  model: root.availableChains

                  delegate: Rectangle {
                    id: chainOptionItem
                    width: parent.width
                    implicitHeight: Style.space(28)
                    radius: Style.space(3)
                    property bool isSelected: root.selectedChain === modelData.id
                    color: {
                      if (isSelected) return Color.accent
                      if (optionHover.containsMouse) return Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.08)
                      return "transparent"
                    }

                    RowLayout {
                      anchors.fill: parent
                      anchors.leftMargin: Style.space(10)
                      anchors.rightMargin: Style.space(10)
                      spacing: Style.space(6)

                      Text {
                        Layout.fillWidth: true
                        text: root.englishMode ? modelData.nameEn : modelData.nameJa
                        color: chainOptionItem.isSelected
                          ? Color.background
                          : (root.bar ? root.bar.foreground : Color.foreground)
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
                        root.chainDropdownOpen = false
                        root.selectChain(modelData.id)
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
              text: root.englishMode ? "Select Theater:" : "劇場を選択:"
              color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.8)
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
                placeholderText: root.englishMode ? "Filter theaters..." : "劇場名・地域で絞り込み..."
                font.pixelSize: Style.font ? Style.font.caption : 12
                verticalPadding: Style.space(4)
                horizontalPadding: Style.space(8)
                text: root.theaterSearchText
                onTextChanged: root.theaterSearchText = text.trim().toLowerCase()
              }

              Rectangle {
                visible: searchInput.text !== ""
                radius: Style.space(4)
                color: clearHover.containsMouse ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.1)
                implicitWidth: Style.space(26)
                implicitHeight: Style.space(26)

                Text {
                  anchors.centerIn: parent
                  text: "✕"
                  color: clearHover.containsMouse ? Color.background : (root.bar ? root.bar.foreground : Color.foreground)
                  font.pixelSize: Style.font ? Style.font.caption : 11
                }

                MouseArea {
                  id: clearHover
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: {
                    searchInput.text = ""
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
                  model: root.filteredTheaters

                  delegate: Rectangle {
                    id: theaterChip
                    radius: Style.space(4)
                    property bool isSelected: modelData.id === root.selectedTheater
                    color: isSelected ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.1)
                    implicitWidth: chipLabel.implicitWidth + Style.space(10)
                    implicitHeight: Style.space(22)

                    Text {
                      id: chipLabel
                      anchors.centerIn: parent
                      text: modelData.name
                      color: theaterChip.isSelected ? Color.background : (root.bar ? root.bar.foreground : Color.foreground)
                      font.pixelSize: Style.font ? Style.font.caption : 11
                    }

                    MouseArea {
                      anchors.fill: parent
                      cursorShape: Qt.PointingHandCursor
                      onClicked: root.selectTheater(modelData.id, modelData.name)
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
            visible: root.selectedDate === "today"

            Text {
              text: root.englishMode ? "Within:" : "抽出範囲:"
              color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.8)
              font.pixelSize: Style.font ? Style.font.caption : 11
              font.bold: true
            }

            Repeater {
              model: [1, 2, 3, 5]
              delegate: Rectangle {
                radius: Style.space(4)
                property bool isCurrent: Math.round(root.withinHours) === modelData
                color: isCurrent ? Color.accent : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.1)
                implicitWidth: hourLabel.implicitWidth + Style.space(10)
                implicitHeight: Style.space(24)

                Text {
                  id: hourLabel
                  anchors.centerIn: parent
                  text: root.englishMode ? (modelData + "h") : (modelData + "時間")
                  color: parent.isCurrent ? Color.background : (root.bar ? root.bar.foreground : Color.foreground)
                  font.pixelSize: Style.font ? Style.font.caption : 11
                  font.bold: true
                }

                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.setHours(modelData)
                }
              }
            }
          }

          Text {
            text: root.englishMode ? "✓ Settings are automatically saved" : "✓ 設定は自動的に保持・保存されます"
            color: Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.5)
            font.pixelSize: Style.font ? Style.font.caption : 10
          }
        }
      }
    }
  }
}
