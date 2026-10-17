import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "components"

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
  property string theaterSearchText: ""
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

  readonly property var uniqueMovieTitles: {
    var titles = []
    if (!root.moviesData) return titles
    for (var i = 0; i < root.moviesData.length; i++) {
      var t = root.getMovieDisplayTitle(root.moviesData[i])
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
      var m = root.moviesData[i]
      var t = root.getMovieDisplayTitle(m)
      if (t === root.selectedMovieFilter || m.title === root.selectedMovieFilter) {
        list.push(m)
      }
    }
    return list
  }

  readonly property var availableChains: [
    { id: "aeon", nameJa: "イオンシネマ", nameEn: "AEON CINEMA" },
    { id: "toho", nameJa: "TOHOシネマズ", nameEn: "TOHO CINEMAS" },
    { id: "united", nameJa: "ユナイテッド・シネマ", nameEn: "UNITED CINEMAS" },
    { id: "sunshine", nameJa: "シネマサンシャイン", nameEn: "CINEMA SUNSHINE" }
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

  function normalizeScreenText(str) {
    if (!str) return ""
    return str.replace(/[！-～]/g, function(c) {
      return String.fromCharCode(c.charCodeAt(0) - 0xFEE0)
    }).replace(/　/g, " ").replace(/\s+/g, " ").trim()
  }

  function extractScreenNumber(str) {
    var norm = root.normalizeScreenText(str)
    var m = norm.match(/(?:シアター|screen|スクリーン|cinema|シネマ)\s*(\d+)/i) || norm.match(/\b(\d+)\b/) || norm.match(/(\d+)/)
    return m ? parseInt(m[1], 10) : null
  }

  function findScreenFacility(screenName) {
    var theaterObj = null
    for (var i = 0; i < root.allTheaters.length; i++) {
      if (root.allTheaters[i].id === root.selectedTheater) {
        theaterObj = root.allTheaters[i]
        break
      }
    }
    if (!theaterObj || !theaterObj.facility || !Array.isArray(theaterObj.facility.screens)) {
      return null
    }

    var screens = theaterObj.facility.screens
    var normTarget = root.normalizeScreenText(screenName).toLowerCase()
    var targetNum = root.extractScreenNumber(screenName)

    // 1. 完全一致・正規化一致
    for (var j = 0; j < screens.length; j++) {
      var s = screens[j]
      var normS = root.normalizeScreenText(s.name).toLowerCase()
      if (normS === normTarget) return s
    }

    // 2. スクリーン番号の一致
    if (targetNum !== null) {
      for (var j = 0; j < screens.length; j++) {
        var s = screens[j]
        var sNum = root.extractScreenNumber(s.name)
        if (sNum !== null && sNum === targetNum) return s
      }
    }

    // 3. 特殊設備キーワード一致 (IMAX, 4DX, BESTIA等)
    for (var j = 0; j < screens.length; j++) {
      var s = screens[j]
      var normS = root.normalizeScreenText(s.name).toLowerCase()
      if (normTarget.indexOf("imax") !== -1 && normS.indexOf("imax") !== -1) return s
      if (normTarget.indexOf("4dx") !== -1 && normS.indexOf("4dx") !== -1) return s
      if (normTarget.indexOf("bestia") !== -1 && normS.indexOf("bestia") !== -1) {
        if (targetNum === null) return s
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

  function getMovieDisplayTitle(movie) {
    if (!movie) return ""
    if (root.englishMode && movie.movie_title_en) {
      return movie.movie_title_en
    }
    return movie.title || ""
  }

  function toEnglishScreen(screenName) {
    if (!screenName) return ""
    var m = screenName.match(/スクリーン\s*(\d+)/)
    if (m) {
      return "Screen " + m[1]
    }
    if (screenName.indexOf("未定") !== -1) {
      return "TBD"
    }
    return screenName
  }

  function getScreenDisplayName(screenName) {
    if (!screenName) return ""
    if (root.englishMode) {
      return toEnglishScreen(screenName)
    }
    return screenName
  }

  // 外部ブラウザ遷移を許可する公式シネコンドメイン一覧 (二重防御)
  readonly property var allowedCinemaDomains: [
    "cinema.aeoncinema.com",
    "reserve.aeoncinema.com",
    "login.watatheatre.aeoncinema.com",
    "theater.aeoncinema.com",
    "www.aeoncinema.com",
    "hlo.tohotheater.jp",
    "www.tohotheater.jp",
    "www.unitedcinemas.jp",
    "transaction.ticket-cinemasunshine.com",
    "ticket-cinemasunshine.com",
    "www.cinemasunshine.co.jp",
    "cinemasunshine.co.jp"
  ]

  function openExternalUrl(url) {
    if (!url || typeof url !== "string") return
    var trimmed = url.trim()
    if (!trimmed.startsWith("https://")) {
      console.warn("[CinecomScheduler] Blocked unsafe non-https URL:", trimmed)
      return
    }

    // ホスト名の抽出
    var hostMatch = trimmed.match(/^https:\/\/([^\/:]+)/i)
    if (!hostMatch || !hostMatch[1]) {
      console.warn("[CinecomScheduler] Blocked malformed URL:", trimmed)
      return
    }

    var hostname = hostMatch[1].toLowerCase()
    var isAllowed = false
    for (var i = 0; i < root.allowedCinemaDomains.length; i++) {
      if (root.allowedCinemaDomains[i] === hostname) {
        isAllowed = true
        break
      }
    }

    if (!isAllowed) {
      console.warn("[CinecomScheduler] Blocked URL with unauthorized domain:", hostname)
      return
    }

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
      "--mode=theater",
      "--chain=" + (root.selectedChain || "aeon"),
      "--theater=" + root.selectedTheater,
      "--date=" + root.getTargetDateString(),
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
          movie_title_en: m.movie_title_en || null,
          info_url: m.info_url || "",
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

  function buildSearchDateString(dateVal) {
    var target = new Date()
    if (dateVal === "tomorrow") {
      target.setDate(target.getDate() + 1)
    }
    var y = target.getFullYear()
    var m = String(target.getMonth() + 1).padStart(2, "0")
    var d = String(target.getDate()).padStart(2, "0")
    return y + "-" + m + "-" + d
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
    contentHeight: popup.fittedContentHeight(mainColumn.implicitHeight, Style.space(580))

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
              var url = ""
              if (root.selectedChain === "toho") {
                url = "https://hlo.tohotheater.jp/net/schedule/" + encodeURIComponent(root.selectedTheater) + "/TNPI2000J01.do"
              } else if (root.selectedChain === "united") {
                url = "https://www.unitedcinemas.jp/" + encodeURIComponent(root.selectedTheater) + "/index.html"
              } else if (root.selectedChain === "sunshine") {
                url = "https://www.cinemasunshine.co.jp/theater/" + encodeURIComponent(root.selectedTheater) + "/"
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
      visible: root.showSettingsPanel
      bar: root.bar
      englishMode: root.englishMode
      selectedChain: root.selectedChain
      selectedTheater: root.selectedTheater
      withinHours: root.withinHours
      selectedDate: root.selectedDate
      chainDropdownOpen: root.chainDropdownOpen
      theaterSearchText: root.theaterSearchText
      availableChains: root.availableChains
      filteredTheaters: root.filteredTheaters

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
