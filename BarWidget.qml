import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "components"
import "components/CinemaUtils.js" as CinemaUtils

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
  readonly property string theaterShortName: {
    var name = root.theaterDisplayName || ""
    if (name.length > 5) {
      return name.slice(-5)
    }
    return name
  }
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
  property string selectedMovieFilter: ""
  property bool movieFilterDropdownOpen: false

  // 横断検索関連の状態プロパティ
  property bool showSearchModal: false
  property string activeView: "theater" // "theater" or "search"
  property bool searchLoading: false
  property string searchErrorMessage: ""
  property var searchResults: []
  property var searchParams: ({
    title: "",
    area: "東京都",
    date: "today",
    range: "after",
    theater: ""
  })

  readonly property var uniqueMovieTitles: CinemaUtils.extractUniqueMovieTitles(root.moviesData, root.englishMode)

  readonly property var filteredMovies: CinemaUtils.filterMoviesByTitle(root.moviesData, root.selectedMovieFilter, root.englishMode)

  readonly property var availableChains: CinemaUtils.AVAILABLE_CHAINS

  function getChainDisplayName(chainId) {
    return CinemaUtils.getChainDisplayName(chainId || root.selectedChain, root.englishMode)
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

  function normalizeScreenText(str) {
    return CinemaUtils.normalizeScreenText(str)
  }

  function extractScreenNumber(str) {
    return CinemaUtils.extractScreenNumber(str)
  }

  function findCurrentTheater() {
    return CinemaUtils.findTheaterById(root.allTheaters, root.selectedTheater)
  }

  function findScreenFacility(screenName) {
    return CinemaUtils.findScreenFacility(root.findCurrentTheater(), screenName)
  }

  function getSeatRows(seatsObj) {
    return CinemaUtils.getSeatRows(seatsObj)
  }

  function getMovieDisplayTitle(movie) {
    return CinemaUtils.getMovieDisplayTitle(movie, root.englishMode)
  }

  function toEnglishScreen(screenName) {
    return CinemaUtils.toEnglishScreen(screenName)
  }

  function getScreenDisplayName(screenName) {
    return CinemaUtils.getScreenDisplayName(screenName, root.englishMode)
  }

  // 外部ブラウザ遷移を許可する公式シネコンドメイン一覧 (二重防御)
  readonly property var allowedCinemaDomains: CinemaUtils.ALLOWED_CINEMA_DOMAINS

  function openExternalUrl(url) {
    var res = CinemaUtils.validateExternalUrl(url)
    if (!res.ok) {
      if (res.reason === "non_https") {
        console.warn("[CinecomScheduler] Blocked unsafe non-https URL:", res.value)
      } else if (res.reason === "malformed") {
        console.warn("[CinecomScheduler] Blocked malformed URL:", res.value)
      } else if (res.reason === "unauthorized_domain") {
        console.warn("[CinecomScheduler] Blocked URL with unauthorized domain:", res.value)
      }
      return
    }
    Qt.openUrlExternally(res.url)
  }

  onShowSettingsPanelChanged: {
    if (!showSettingsPanel) {
      chainDropdownOpen = false
    }
  }

  readonly property string pluginDirPath: String(Qt.resolvedUrl(".")).replace(/^file:\/\//, "")
  readonly property string theaterJsonPath: String(Qt.resolvedUrl("data/theaters.json")).replace(/^file:\/\//, "")

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
    return CinemaUtils.formatDateIso(root.selectedDate)
  }

  function getTargetDateFormatted() {
    return CinemaUtils.formatDateDisplay(root.selectedDate, root.englishMode)
  }

  function buildFetchCommand() {
    return [
      "python3",
      "-c",
      "import sys; sys.path.insert(0, sys.argv[1]); from scraper.cli import main; sys.exit(main(sys.argv[2:]))",
      root.pluginDirPath,
      "--mode=theater",
      "--chain=" + (root.selectedChain || "aeon"),
      "--theater=" + root.selectedTheater,
      "--date=" + root.getTargetDateString(),
      "--compact"
    ]
  }

  function applyMovieFilter() {
    root.moviesData = CinemaUtils.normalizeAndFilterMovies(root.rawMoviesData, {
      selectedDate: root.selectedDate,
      showAllDayToday: root.showAllDayToday,
      withinHours: root.withinHours,
      theaterObj: root.findCurrentTheater()
    })
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

  function buildSearchDateString(dateVal) {
    return CinemaUtils.formatDateIso(dateVal)
  }

  function startCrossTheaterSearch(title, area, dateVal, rangeVal, theaterVal) {
    searchParams = {
      title: title,
      area: area,
      date: dateVal,
      range: rangeVal,
      theater: theaterVal
    }
    activeView = "search"
    searchLoading = true
    searchErrorMessage = ""
    searchResults = []

    var cmd = [
      "python3",
      "-c",
      "import sys; sys.path.insert(0, sys.argv[1]); from scraper.cli import main; sys.exit(main(sys.argv[2:]))",
      root.pluginDirPath,
      "--mode=search",
      "--title=" + title,
      "--area=" + area,
      "--date=" + buildSearchDateString(dateVal),
      "--compact"
    ]

    if (rangeVal === "after") {
      cmd.push("--after=now")
    }

    if (theaterVal && theaterVal.trim().length > 0) {
      cmd.push("--theater=" + theaterVal.trim())
    }

    // 既に別の検索が実行中の場合は中断して新しい条件で実行
    if (searchProcess.running) {
      searchProcess.running = false
    }

    searchProcess.command = cmd
    searchProcess.running = true
  }

  // 横断検索実行プロセス
  Process {
    id: searchProcess
    running: false

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.searchLoading = false
        root.searchErrorMessage = ""
        try {
          var payload = JSON.parse(text)
          root.searchResults = payload.screenings || []
          console.log("[CinecomScheduler] Search finished with " + root.searchResults.length + " screenings.")
        } catch (e) {
          console.error("[CinecomScheduler] Search JSON parse error: " + e.message)
          root.searchErrorMessage = root.englishMode ? "Failed to parse search results" : "検索結果の解析に失敗しました"
        }
      }
    }

    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (text && text.trim().length > 0) {
          console.warn("[CinecomScheduler] search stderr:", text.trim())
          try {
            var errPayload = JSON.parse(text)
            if (errPayload.message) {
              root.searchErrorMessage = errPayload.message
            }
          } catch (ignored) {}
        }
      }
    }

    onExited: function(exitCode, exitStatus) {
      root.searchLoading = false
      if (exitCode !== 0 && root.searchErrorMessage === "") {
        root.searchErrorMessage = root.englishMode ? "Search request failed" : "横断検索に失敗しました"
      }
    }
  }

  property var chainTheatersCache: ({})

  function getChainJsonPath(chainId) {
    var cId = chainId || root.selectedChain
    return String(Qt.resolvedUrl("data/theaters/" + cId + ".json")).replace(/^file:\/\//, "")
  }

  function applyTheaters(theaters) {
    root.allTheaters = Array.isArray(theaters) ? theaters : []
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

  function loadTheatersForChain(chainId) {
    var cId = chainId || root.selectedChain
    if (root.chainTheatersCache && root.chainTheatersCache[cId]) {
      root.applyTheaters(root.chainTheatersCache[cId])
      return
    }

    if (loadTheatersProcess.running) {
      return
    }
    loadTheatersProcess.targetChain = cId
    loadTheatersProcess.command = ["cat", root.getChainJsonPath(cId)]
    loadTheatersProcess.running = true
  }

  function updateTheatersForCurrentChain() {
    root.loadTheatersForChain(root.selectedChain)
  }

  // theaters/{chain}.json (または data/theaters.json) 読み込み用 Process
  Process {
    id: loadTheatersProcess
    running: false
    property string targetChain: root.selectedChain
    command: ["cat", root.getChainJsonPath(root.selectedChain)]

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var data = JSON.parse(text)
          var theaters = []
          if (Array.isArray(data)) {
            theaters = data
          } else if (data.theaters && Array.isArray(data.theaters)) {
            theaters = data.theaters
          } else if (data.chains && Array.isArray(data.chains)) {
            // 従来の統合 theaters.json から読み込まれた場合のフォールバック
            for (var c = 0; c < data.chains.length; c++) {
              if (data.chains[c].id === loadTheatersProcess.targetChain) {
                theaters = data.chains[c].theaters || []
                break
              }
            }
          }
          var cache = Object.assign({}, root.chainTheatersCache)
          cache[loadTheatersProcess.targetChain] = theaters
          root.chainTheatersCache = cache
          if (root.selectedChain === loadTheatersProcess.targetChain) {
            root.applyTheaters(theaters)
          }
          console.log("[CinemaPlugin] Loaded " + theaters.length + " theaters for chain: " + loadTheatersProcess.targetChain)
        } catch (e) {
          console.warn("[CinemaPlugin] Error parsing theaters json for chain " + loadTheatersProcess.targetChain + ":", e.message)
          if (loadTheatersProcess.command[1] !== root.theaterJsonPath) {
            console.log("[CinemaPlugin] Falling back to unified theaters.json")
            loadTheatersProcess.command = ["cat", root.theaterJsonPath]
            loadTheatersProcess.running = true
          }
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
  }

  function refresh() {
    if (!fetchProcess.running) {
      loading = true
      fetchProcess.command = root.buildFetchCommand()
      fetchProcess.running = true
    }
  }

  // 設定の永続化 (Omarchy shell.json)
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
    root.loadTheatersForChain(chainId)
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
    if (root.rawMoviesData && root.rawMoviesData.length > 0) {
      applyMovieFilter()
    } else {
      refresh()
    }
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
    root.loadTheatersForChain(root.selectedChain)
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
    readonly property real activeModalHeight: {
      if (root.showSettingsPanel) return settingsModal.contentPreferredHeight
      if (root.showSearchModal) return searchModal.contentPreferredHeight
      if (root.showScreenModal) return screenModal.contentPreferredHeight
      return 0
    }
    contentHeight: popup.fittedContentHeight(
      Math.max(mainColumn.implicitHeight, activeModalHeight),
      Math.max(Style.space(580), activeModalHeight + (popup.verticalContentInset || Style.space(32)))
    )

    onOpenChanged: {
      if (root.popupOpen !== open) {
        root.popupOpen = open
      }
      if (!open) {
        root.showScreenModal = false
        root.showSettingsPanel = false
        root.showSearchModal = false
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
              textFormat: Text.PlainText
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
                  text: root.theaterShortName
                  textFormat: Text.PlainText
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
            onEntered: if (root.bar) root.bar.showTooltip(parent, root.englishMode ? (root.theaterDisplayName + " - Click to configure") : (root.theaterDisplayName + " (クリックして設定変更)"))
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
              root.openExternalUrl(
                CinemaUtils.buildTheaterHomepageUrl(
                  root.selectedChain,
                  root.selectedTheater,
                  root.findCurrentTheater()
                )
              )
            }
            onEntered: if (root.bar) root.bar.showTooltip(parent, root.englishMode ? "Open theater homepage" : (root.theaterDisplayName + " の公式ホームページを開く"))
            onExited: if (root.bar) root.bar.hideTooltip(parent)
          }
        }

        Item { Layout.fillWidth: true }

        // 検索ボタン (横断検索モーダルを開く)
        Rectangle {
          radius: Style.space(4)
          color: root.showSearchModal ? Color.accent : (searchBtnHover.containsMouse ? Util.alpha(Color.accent, 0.2) : Util.alpha(root.bar ? root.bar.foreground : Color.foreground, 0.1))
          implicitWidth: searchBtnTxt.implicitWidth + Style.space(12)
          implicitHeight: Style.space(26)

          RowLayout {
            anchors.centerIn: parent
            spacing: Style.space(4)

            Text {
              text: "🔍"
              font.pixelSize: Style.font ? Style.font.caption : 10
            }

            Text {
              id: searchBtnTxt
              text: root.englishMode ? "Search" : "検索"
              color: root.showSearchModal ? Color.background : (root.bar ? root.bar.foreground : Color.foreground)
              font.pixelSize: Style.font ? Style.font.caption : 11
              font.bold: true
            }
          }

          MouseArea {
            id: searchBtnHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              root.showSettingsPanel = false
              root.showSearchModal = !root.showSearchModal
            }
            onEntered: if (root.bar) root.bar.showTooltip(parent, root.englishMode ? "Search movies across cinema chains" : "作品・地域でシネコン横断検索")
            onExited: if (root.bar) root.bar.hideTooltip(parent)
          }
        }

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
            onClicked: {
              root.showSearchModal = false
              root.showSettingsPanel = !root.showSettingsPanel
            }
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
            onClicked: {
              if (root.activeView === "search" && root.searchParams && root.searchParams.title) {
                root.startCrossTheaterSearch(
                  root.searchParams.title,
                  root.searchParams.area,
                  root.searchParams.date,
                  root.searchParams.range,
                  root.searchParams.theater
                )
              } else {
                root.refresh()
              }
            }
          }
        }
      }

      // 2. 上映スケジュール表示ビュー (通常表示モード)
      MovieScheduleView {
        visible: root.activeView === "theater"
        bar: root.bar
        englishMode: root.englishMode
        selectedDate: root.selectedDate
        withinHours: root.withinHours
        showAllDayToday: root.showAllDayToday
        loading: root.loading
        errorMessage: root.errorMessage
        payloadMessage: root.payloadMessage
        moviesData: root.moviesData
        filteredMovies: root.filteredMovies
        uniqueMovieTitles: root.uniqueMovieTitles
        selectedMovieFilter: root.selectedMovieFilter
        movieFilterDropdownOpen: root.movieFilterDropdownOpen

        getTargetDateFormatted: root.getTargetDateFormatted
        getMovieDisplayTitle: root.getMovieDisplayTitle
        getScreenDisplayName: root.getScreenDisplayName
        openExternalUrl: root.openExternalUrl

        onDateChanged: function(newDate) {
          root.selectedDate = newDate
          root.rawMoviesData = []
          root.selectedMovieFilter = ""
          root.movieFilterDropdownOpen = false
          root.refresh()
        }
        onToggleAllDayRequested: root.toggleShowAllDayToday()
        onMovieFilterChanged: function(filter) {
          root.selectedMovieFilter = filter
        }
        onScreenDetailsRequested: function(screenName, facilityData) {
          root.showScreenDetails(screenName, facilityData)
        }
      }

      // 3. 作品検索結果表示ビュー (検索結果モード)
      SearchResultView {
        visible: root.activeView === "search"
        bar: root.bar
        englishMode: root.englishMode
        loading: root.searchLoading
        errorMessage: root.searchErrorMessage
        queryTitle: root.searchParams ? (root.searchParams.title || "") : ""
        queryArea: root.searchParams ? (root.searchParams.area || "") : ""
        queryDate: root.searchParams ? (root.searchParams.date || "today") : "today"
        queryRange: root.searchParams ? (root.searchParams.range || "after") : "after"
        queryTheater: root.searchParams ? (root.searchParams.theater || "") : ""
        rawScreenings: root.searchResults

        openExternalUrl: root.openExternalUrl

        onBackToScheduleRequested: {
          root.activeView = "theater"
        }
        onRerunSearchRequested: {
          root.showSearchModal = true
        }
      }
    }

    // スクリーン設備詳細モーダル
    ScreenModal {
      id: screenModal
      visible: root.showScreenModal
      bar: root.bar
      englishMode: root.englishMode
      currentScreenTitle: root.currentScreenTitle
      currentScreenFacility: root.currentScreenFacility

      getScreenDisplayName: root.getScreenDisplayName
      getSeatRows: root.getSeatRows
      openExternalUrl: root.openExternalUrl

      onClosed: root.showScreenModal = false
    }

    // 設定モーダルポップアップ
    SettingsModal {
      id: settingsModal
      visible: root.showSettingsPanel
      bar: root.bar
      englishMode: root.englishMode
      selectedChain: root.selectedChain
      selectedTheater: root.selectedTheater
      withinHours: root.withinHours
      selectedDate: root.selectedDate
      chainDropdownOpen: root.chainDropdownOpen
      availableChains: root.availableChains
      allTheaters: root.allTheaters

      getChainDisplayName: root.getChainDisplayName

      onChainSelected: function(chainId) { root.selectChain(chainId) }
      onTheaterSelected: function(theaterId, theaterName) { root.selectTheater(theaterId, theaterName) }
      onHoursSelected: function(hours) { root.setHours(hours) }
      onClosed: {
        root.showSettingsPanel = false
        root.chainDropdownOpen = false
      }
    }

    // 作品横断検索モーダルポップアップ
    SearchModal {
      id: searchModal
      visible: root.showSearchModal
      bar: root.bar
      englishMode: root.englishMode
      queryTitle: root.searchParams ? (root.searchParams.title || "") : ""
      queryArea: root.searchParams ? (root.searchParams.area || "東京都") : "東京都"
      queryDate: root.searchParams ? (root.searchParams.date || "today") : "today"
      queryRange: root.searchParams ? (root.searchParams.range || "after") : "after"
      queryTheater: root.searchParams ? (root.searchParams.theater || "") : ""

      onSearchRequested: function(title, area, dateVal, rangeVal, theaterVal) {
        root.startCrossTheaterSearch(title, area, dateVal, rangeVal, theaterVal)
      }
      onClosed: {
        root.showSearchModal = false
      }
    }
  }
}
