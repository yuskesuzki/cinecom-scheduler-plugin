.pragma library

// 共通シネコン系列定義（表示名・横断検索短縮バッジ）
var AVAILABLE_CHAINS = [
  { id: "aeon", nameJa: "イオンシネマ", nameEn: "AEON CINEMA", badgeJa: "イオンシネマ", badgeEn: "Aeon" },
  { id: "toho", nameJa: "TOHOシネマズ", nameEn: "TOHO CINEMAS", badgeJa: "TOHOシネマズ", badgeEn: "TOHO" },
  { id: "united", nameJa: "ユナイテッド・シネマ", nameEn: "UNITED CINEMAS", badgeJa: "ユナイテッド", badgeEn: "United" },
  { id: "sunshine", nameJa: "シネマサンシャイン", nameEn: "CINEMA SUNSHINE", badgeJa: "サンシャイン", badgeEn: "Sunshine" },
  { id: "tjoy", nameJa: "T・ジョイ", nameEn: "T-JOY", badgeJa: "T・ジョイ", badgeEn: "T-JOY" },
  { id: "109cinemas", nameJa: "109シネマズ", nameEn: "109 CINEMAS", badgeJa: "109シネマズ", badgeEn: "109" },
  { id: "smt", nameJa: "MOVIX・ピカデリー", nameEn: "MOVIX / Piccadilly", badgeJa: "MOVIX", badgeEn: "MOVIX" },
  { id: "korona", nameJa: "コロナワールド", nameEn: "KORONA WORLD", badgeJa: "コロナ", badgeEn: "Korona" },
  { id: "ttcg", nameJa: "テアトルシネマグループ", nameEn: "TTCG", badgeJa: "テアトル", badgeEn: "TTCG" },
  { id: "uscinemas", nameJa: "USシネマ・千葉劇場", nameEn: "US CINEMAS", badgeJa: "USシネマ", badgeEn: "US Cinemas" },
  { id: "forum", nameJa: "フォーラムシネマネットワーク", nameEn: "FORUM CINEMA", badgeJa: "フォーラム", badgeEn: "Forum" },
  { id: "kinocinema", nameJa: "キノシネマ", nameEn: "kino cinéma", badgeJa: "キノシネマ", badgeEn: "kino cinéma" },
  { id: "other", nameJa: "共同経営・その他", nameEn: "Joint / Other", badgeJa: "共同", badgeEn: "Joint" }
];

// 外部ブラウザ遷移を許可する公式シネコンドメイン一覧 (scraper/sanitizer.py の ALLOWED_DOMAINS と同期)
var ALLOWED_CINEMA_DOMAINS = [
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
  "cinemasunshine.co.jp",
  "tjoy.jp",
  "tjoy.co.jp",
  "109cinemas.net",
  "cinema.109cinemas.net",
  "www.smt-cinema.com",
  "smt-cinema.com",
  "memberlogin.smart.smt-cinema.jp",
  "ticket.smt-cinema.com",
  "www.osakastationcitycinema.com",
  "ticket.osakastationcitycinema.com",
  "www.parkscinema.com",
  "ticket.parkscinema.com",
  "www.cinemafrontier.net",
  "www.midland-sq-cinema.jp",
  "ticket.midlandcinema.jp",
  "www.oscinemas.net",
  "cinema.korona.co.jp",
  "login.member.korona.co.jp",
  "reserve.smart-theater.com",
  "ttcg.jp",
  "ttcg-yurakucho.cineticket.jp",
  "ttcg-shibuya.cineticket.jp",
  "ttcg-shinjuku.cineticket.jp",
  "ttcg-omori.cineticket.jp",
  "ttcg-umeda.cineticket.jp",
  "ttcg-kobe.cineticket.jp",
  "uscinemas.jp",
  "cinema-ticket.jp",
  "forum-movie.net",
  "login.member.forum-movie.net",
  "kinocinema.jp",
  "app.eigaland.com"
];

function findChainEntry(chainId) {
  for (var i = 0; i < AVAILABLE_CHAINS.length; i++) {
    if (AVAILABLE_CHAINS[i].id === chainId) {
      return AVAILABLE_CHAINS[i];
    }
  }
  return null;
}

function getChainDisplayName(chainId, englishMode) {
  var entry = findChainEntry(chainId);
  if (entry) {
    return englishMode ? entry.nameEn : entry.nameJa;
  }
  return englishMode ? "Cinema" : "シネコン";
}

function getChainBadgeLabel(chainId, englishMode) {
  var entry = findChainEntry(chainId);
  if (entry) {
    return englishMode ? entry.badgeEn : entry.badgeJa;
  }
  return englishMode ? "Aeon" : "イオンシネマ";
}

function buildTheaterHomepageUrl(chainId, theaterId, theaterObj) {
  if (theaterObj && theaterObj.official_url) {
    return theaterObj.official_url;
  }
  var encoded = encodeURIComponent(theaterId || "");
  if (chainId === "toho") {
    return "https://hlo.tohotheater.jp/net/schedule/" + encoded + "/TNPI2000J01.do";
  }
  if (chainId === "united") {
    return "https://www.unitedcinemas.jp/" + encoded + "/index.html";
  }
  if (chainId === "sunshine") {
    return "https://www.cinemasunshine.co.jp/theater/" + encoded + "/";
  }
  if (chainId === "tjoy") {
    return "https://tjoy.jp/" + encoded;
  }
  if (chainId === "109cinemas") {
    return "https://109cinemas.net/" + encoded + "/";
  }
  if (chainId === "smt") {
    return "https://www.smt-cinema.com/site/" + encoded + "/";
  }
  if (chainId === "korona") {
    return "https://cinema.korona.co.jp/theaters/" + encoded + "/";
  }
  if (chainId === "ttcg") {
    return "https://ttcg.jp/" + encoded + "/";
  }
  if (chainId === "uscinemas") {
    return "https://uscinemas.jp/category/" + encoded + "/";
  }
  if (chainId === "forum") {
    var forumSlug = (theaterId === "solaris") ? "yamagata" : encoded;
    return "https://forum-movie.net/" + forumSlug;
  }
  if (chainId === "kinocinema") {
    return "https://kinocinema.jp/" + encoded + "/";
  }
  return "https://theater.aeoncinema.com/theaters/" + encoded + "/";
}

function validateExternalUrl(url) {
  if (!url || typeof url !== "string") {
    return { ok: false, reason: "empty", value: "" };
  }
  var trimmed = url.trim();
  if (!trimmed) {
    return { ok: false, reason: "empty", value: "" };
  }
  if (!trimmed.startsWith("https://")) {
    return { ok: false, reason: "non_https", value: trimmed };
  }
  var hostMatch = trimmed.match(/^https:\/\/([^\/:]+)/i);
  if (!hostMatch || !hostMatch[1]) {
    return { ok: false, reason: "malformed", value: trimmed };
  }
  var hostname = hostMatch[1].toLowerCase();
  for (var i = 0; i < ALLOWED_CINEMA_DOMAINS.length; i++) {
    if (ALLOWED_CINEMA_DOMAINS[i] === hostname) {
      return { ok: true, url: trimmed, hostname: hostname };
    }
  }
  return { ok: false, reason: "unauthorized_domain", value: hostname };
}

function normalizeScreenText(str) {
  if (!str) return "";
  return str.replace(/[！-～]/g, function(c) {
    return String.fromCharCode(c.charCodeAt(0) - 0xFEE0);
  }).replace(/　/g, " ").replace(/\s+/g, " ").trim();
}

function extractScreenNumber(str) {
  var norm = normalizeScreenText(str);
  var m = norm.match(/(?:シアター|screen|スクリーン|cinema|シネマ)\s*(\d+)/i) || norm.match(/\b(\d+)\b/) || norm.match(/(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

function findTheaterById(theaters, theaterId) {
  if (!Array.isArray(theaters)) return null;
  for (var i = 0; i < theaters.length; i++) {
    if (theaters[i] && theaters[i].id === theaterId) {
      return theaters[i];
    }
  }
  return null;
}

function findScreenFacility(theaterObj, screenName) {
  if (!theaterObj || !theaterObj.facility || !Array.isArray(theaterObj.facility.screens)) {
    return null;
  }

  var screens = theaterObj.facility.screens;
  var normTarget = normalizeScreenText(screenName).toLowerCase();
  var targetNum = extractScreenNumber(screenName);

  // 1. 完全一致・正規化一致
  for (var j = 0; j < screens.length; j++) {
    var s = screens[j];
    var normS = normalizeScreenText(s.name).toLowerCase();
    if (normS === normTarget) return s;
  }

  // 2. スクリーン番号の一致
  if (targetNum !== null) {
    for (var j2 = 0; j2 < screens.length; j2++) {
      var s2 = screens[j2];
      var sNum = extractScreenNumber(s2.name);
      if (sNum !== null && sNum === targetNum) return s2;
    }
  }

  // 3. 特殊設備キーワード一致 (IMAX, 4DX, BESTIA, Dolby Cinema, プラチナ等)
  for (var j3 = 0; j3 < screens.length; j3++) {
    var s3 = screens[j3];
    var normS3 = normalizeScreenText(s3.name).toLowerCase();
    if (normTarget.indexOf("imax") !== -1 && normS3.indexOf("imax") !== -1) return s3;
    if (normTarget.indexOf("4dx") !== -1 && normS3.indexOf("4dx") !== -1) return s3;
    if ((normTarget.indexOf("dolby cinema") !== -1 || normTarget.indexOf("dolbycinema") !== -1) && normS3.indexOf("dolby cinema") !== -1) return s3;
    if (normTarget.indexOf("プラチナ") !== -1 && normS3.indexOf("プラチナ") !== -1) return s3;
    if (normTarget.indexOf("bestia") !== -1 && normS3.indexOf("bestia") !== -1) {
      if (targetNum === null) return s3;
    }
  }

  return null;
}

function getSeatRows(seatsObj) {
  if (!seatsObj) return [];
  var rows = [];
  for (var k in seatsObj) {
    if (k !== "合 計" && k !== "合計" && k !== "total" && k !== "Total") {
      rows.push({ type: k, count: seatsObj[k] });
    }
  }
  return rows;
}

function getMovieDisplayTitle(movie, englishMode) {
  if (!movie) return "";
  if (englishMode && movie.movie_title_en) {
    return movie.movie_title_en;
  }
  return movie.title || "";
}

function toEnglishScreen(screenName) {
  if (!screenName) return "";
  var norm = normalizeScreenText(screenName);
  var m = norm.match(/スクリーン\s*(\d+)/);
  if (m) {
    return "Screen " + m[1];
  }
  if (/シアター\s*\d+/.test(norm)) {
    return norm.replace(/シアター\s*(\d+)/, "Theater $1");
  }
  if (norm.indexOf("未定") !== -1) {
    return "TBD";
  }
  return screenName;
}

function getScreenDisplayName(screenName, englishMode) {
  if (!screenName) return "";
  if (englishMode) {
    return toEnglishScreen(screenName);
  }
  return screenName;
}

function resolveTargetDate(dateKey, baseDate) {
  var target = baseDate ? new Date(baseDate.getTime()) : new Date();
  if (dateKey === "tomorrow") {
    target.setDate(target.getDate() + 1);
  } else if (dateKey === "yesterday") {
    target.setDate(target.getDate() - 1);
  }
  return target;
}

function formatDateIso(dateKey, baseDate) {
  var target = resolveTargetDate(dateKey, baseDate);
  var y = target.getFullYear();
  var m = String(target.getMonth() + 1).padStart(2, "0");
  var d = String(target.getDate()).padStart(2, "0");
  return y + "-" + m + "-" + d;
}

function formatDateDisplay(dateKey, englishMode, baseDate) {
  var target = resolveTargetDate(dateKey, baseDate);
  var y = target.getFullYear();
  var m = String(target.getMonth() + 1).padStart(2, "0");
  var d = String(target.getDate()).padStart(2, "0");

  if (englishMode) {
    var daysEn = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    return y + "-" + m + "-" + d + " (" + daysEn[target.getDay()] + ")";
  }
  var daysJa = ["日", "月", "火", "水", "木", "金", "土"];
  return y + "年" + m + "月" + d + "日(" + daysJa[target.getDay()] + ")";
}

function extractUniqueMovieTitles(moviesData, englishMode) {
  var titles = [];
  if (!moviesData) return titles;
  for (var i = 0; i < moviesData.length; i++) {
    var t = getMovieDisplayTitle(moviesData[i], englishMode);
    if (t && titles.indexOf(t) === -1) {
      titles.push(t);
    }
  }
  titles.sort(function(a, b) {
    return a.localeCompare(b, englishMode ? "en" : "ja");
  });
  return titles;
}

function filterMoviesByTitle(moviesData, selectedMovieFilter, englishMode) {
  if (!moviesData) return [];
  if (!selectedMovieFilter || selectedMovieFilter === "") {
    return moviesData;
  }
  var list = [];
  for (var i = 0; i < moviesData.length; i++) {
    var m = moviesData[i];
    var t = getMovieDisplayTitle(m, englishMode);
    if (t === selectedMovieFilter || m.title === selectedMovieFilter) {
      list.push(m);
    }
  }
  return list;
}

function normalizeAndFilterMovies(rawMovies, options) {
  var movies = rawMovies || [];
  var opts = options || {};
  var selectedDate = opts.selectedDate || "today";
  var showAllDayToday = Boolean(opts.showAllDayToday);
  var withinHours = opts.withinHours !== undefined ? opts.withinHours : 3.0;
  var theaterObj = opts.theaterObj || null;
  var now = opts.now || new Date();

  var currentMinutes = now.getHours() * 60 + now.getMinutes();
  var maxMinutes = currentMinutes + Math.round(withinHours * 60);
  var normalizedMovies = [];

  for (var i = 0; i < movies.length; i++) {
    var m = movies[i];
    var title = m.movie_title || m.title || "";
    var screenings = m.screenings || m.showtimes || [];
    var filteredShowtimes = [];

    for (var j = 0; j < screenings.length; j++) {
      var s = screenings[j];
      var startTime = s.start_time || "";
      var endTime = s.end_time || "";
      var screenName = s.screen_name || s.screen || "";
      var tags = s.tags || s.special_badges || [];
      var seatStatus = s.seat_status || "unknown";
      var bookingUrl = s.booking_url || "";

      // "today" かつ showAllDayToday でないときは withinHours 時間以内の上映枠にフィルタリング
      if (selectedDate === "today" && !showAllDayToday && startTime) {
        var parts = startTime.split(":");
        if (parts.length === 2) {
          var startMinutes = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
          if (startMinutes < currentMinutes || startMinutes > maxMinutes) {
            continue;
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
        screen_facility: s.screen_facility || findScreenFacility(theaterObj, screenName)
      });
    }

    if (filteredShowtimes.length > 0) {
      normalizedMovies.push({
        movie_id: m.movie_id || m.id || "",
        title: title,
        movie_title_en: m.movie_title_en || null,
        info_url: m.info_url || "",
        booking_url: (m.booking_url || (filteredShowtimes[0] ? filteredShowtimes[0].booking_url : "")),
        showtimes: filteredShowtimes
      });
    }
  }

  normalizedMovies.sort(function(a, b) {
    var timeA = (a.showtimes && a.showtimes.length > 0) ? a.showtimes[0].start_time : "99:99";
    var timeB = (b.showtimes && b.showtimes.length > 0) ? b.showtimes[0].start_time : "99:99";
    if (timeA !== timeB) return timeA.localeCompare(timeB);
    return (a.title || "").localeCompare(b.title || "");
  });

  return normalizedMovies;
}
