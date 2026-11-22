from datetime import date
import html as html_lib
import http.cookiejar
import json
import re
import threading
import time
from typing import Callable, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request

from ..models import MovieSchedule, Screening, SeatStatus
from ..sanitizer import UnsafeUrlError, build_safe_url, sanitize_identifier
from .base import BaseCinemaProvider

# 全角英数字・記号から半角への変換テーブル (シアター名正規化用)
_FULLWIDTH_TRANS = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ－＿　",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz-_ ",
)

SPECIAL_TAG_PATTERNS = [
    ("IMAXレーザー", "IMAXレーザー"),
    ("IMAX LASER", "IMAXレーザー"),
    ("IMAX", "IMAX"),
    ("DOLBY CINEMA", "Dolby Cinema"),
    ("DOLBY ATMOS", "Dolby Atmos"),
    ("SCREENX", "ScreenX"),
    ("SCREEN X", "ScreenX"),
    ("MX4D", "MX4D"),
    ("4DX", "4DX"),
    ("T-LEX", "T-LEX"),
]


def normalize_tjoy_screen_name(raw_name: str) -> str:
    """T・ジョイのスクリーン名（例: 'シアター８'）の英数字・空白を半角正規化する。"""
    if not raw_name:
        return "シアター未定"
    normalized = html_lib.unescape(raw_name).translate(_FULLWIDTH_TRANS)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or "シアター未定"


def extract_special_tags(*text_sources: Optional[str]) -> List[str]:
    """
    作品バッジ、作品タイトル、スケジュール上のシアター名から特殊上映設備タグを抽出する。
    (字幕・吹替・2D・年齢区分・バリアフリーは含めない)
    """
    tags: List[str] = []
    texts = [s for s in text_sources if s]
    if not texts:
        return tags

    combined = " ".join(texts)
    combined_upper = combined.upper()
    combined_compact = re.sub(r"\s+", "", combined_upper)

    for pattern, label in SPECIAL_TAG_PATTERNS:
        p_upper = pattern.upper()
        p_compact = re.sub(r"\s+", "", p_upper)
        if p_upper in combined_upper or p_compact in combined_compact:
            if label not in tags:
                tags.append(label)

    # 3D 判定（他語中の誤爆を防ぎつつ "4DX3D" や "3D" に対応）
    if re.search(r"(?:^|[^A-Z0-9]|4DX|IMAX)3D(?![A-Z0-9])", combined_upper):
        if "3D" not in tags:
            tags.append("3D")

    # 冗長タグ整理 (IMAXレーザーがあれば IMAX を除く)
    if "IMAXレーザー" in tags and "IMAX" in tags:
        tags.remove("IMAX")

    return tags


def map_tjoy_seat_status(
    status_text: str,
    icon_filename: Optional[str],
    has_booking_link: bool,
) -> SeatStatus:
    """
    T・ジョイのステータス文字列およびアイコン画像名から SeatStatus を判定する。
    - icon_label3.png (◎ 空席に余裕あり) / icon_label2.png (○ 空席あり) -> AVAILABLE
    - icon_label4.png (△ 空席がわずか) -> FEW
    - icon_label5.png (× 満席) / '満席' -> FULL
    - icon_label1.png (ー) / '終了' / '販売終了' / '販売対象外' -> UNSOLD
    """
    txt = (status_text or "").strip()
    icon = (icon_filename or "").strip()

    if "満席" in txt or icon == "icon_label5.png":
        return SeatStatus.FULL
    if "終了" in txt or "販売対象外" in txt or icon == "icon_label1.png":
        return SeatStatus.UNSOLD
    if icon == "icon_label4.png":
        return SeatStatus.FEW
    if icon in ("icon_label2.png", "icon_label3.png"):
        return SeatStatus.AVAILABLE
    return SeatStatus.AVAILABLE if has_booking_link else SeatStatus.UNKNOWN


def _pad_hhmm(time_str: str) -> str:
    """'9:30' のような1桁時表記を '09:30' に揃える（24時超えはそのまま保持）。"""
    t = time_str.strip()
    if len(t) == 4 and t[1] == ":":
        return "0" + t
    return t


def _strip_tags(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def parse_tjoy_schedule_html(
    html_str: str,
    theater_slug: str,
    booking_url_builder: Callable[[Optional[str]], str],
    info_url_builder: Callable[[str, Optional[str]], Optional[str]],
) -> List[MovieSchedule]:
    """T・ジョイの scheduleGetHtmlApi レスポンスHTMLをパースし MovieSchedule リストを返す。"""
    if not html_str:
        return []

    sections = re.findall(
        r'<section\s+class=["\'][^"\']*section-container[^"\']*["\'][^>]*>(.*?)</section>',
        html_str,
        re.DOTALL,
    )
    if not sections:
        return []

    movies: List[MovieSchedule] = []

    for sec in sections:
        title_m = re.search(
            r'<h5[^>]*class=["\'][^"\']*js-title-film[^"\']*["\'][^>]*>(.*?)</h5>',
            sec,
            re.DOTALL,
        )
        if not title_m:
            continue

        title_ja = _strip_tags(title_m.group(1))
        if not title_ja:
            continue

        # 日本語タイトル直後の <span> から英語タイトルを取得
        after_h5 = sec[title_m.end():]
        en_m = re.match(r"\s*<span>(.*?)</span>", after_h5, re.DOTALL)
        title_en = _strip_tags(en_m.group(1)) if en_m else ""

        # 作品詳細コード (cinema_detail/{code})
        detail_m = re.search(
            r'window\.location\.href\s*=\s*[\'"](/([^/\'"]+)/cinema_detail/([A-Za-z0-9_-]+))[\'"]',
            sec,
        )
        cinema_code = detail_m.group(3) if detail_m else None

        if cinema_code:
            movie_id = cinema_code
        else:
            target_m = re.search(
                r'data-target=["\']#(?:tab-)?film-([A-Za-z0-9_-]+)["\']',
                sec,
            )
            movie_id = (
                target_m.group(1)
                if target_m
                else (re.sub(r"[^A-Za-z0-9_-]", "", title_ja[:32]) or "movie")
            )

        info_url = info_url_builder(theater_slug, cinema_code)

        # 作品レベルのバッジ (重複除去)
        raw_badges = re.findall(
            r'<span[^>]*class=["\'][^"\']*lb-icon[^"\']*["\'][^>]*>(.*?)</span>',
            sec,
            re.DOTALL,
        )
        badge_texts = list(dict.fromkeys(_strip_tags(b) for b in raw_badges if _strip_tags(b)))

        # 上映枠リスト
        li_blocks = re.findall(
            r'<li\s+class=["\'][^"\']*schedule-box[^"\']*["\'][^>]*>(.*?)</li>',
            sec,
            re.DOTALL,
        )
        screenings: List[Screening] = []

        for idx, li in enumerate(li_blocks):
            tn_m = re.search(
                r'<div\s+class=["\'][^"\']*theater-name[^"\']*["\'][^>]*>.*?<a[^>]*>(.*?)</a>',
                li,
                re.DOTALL,
            )
            screen_name = normalize_tjoy_screen_name(
                re.sub(r"<[^>]+>", "", tn_m.group(1)) if tn_m else ""
            )

            tm_m = re.search(
                r'<p\s+class=["\'][^"\']*schedule-time[^"\']*["\'][^>]*>(.*?)</p>',
                li,
                re.DOTALL,
            )
            tm_txt = (
                re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", tm_m.group(1)))).strip()
                if tm_m
                else ""
            )
            t_match = re.search(r"(\d{1,2}:\d{2})\s*[～〜~\-]\s*(\d{1,2}:\d{2})", tm_txt)
            if not t_match:
                continue

            start_time = _pad_hhmm(t_match.group(1))
            end_time = _pad_hhmm(t_match.group(2))

            st_m = re.search(
                r'<p[^>]*class=["\'][^"\']*schedule-status[^"\']*["\'][^>]*>(.*?)</p>',
                li,
                re.DOTALL,
            )
            st_inner = st_m.group(1) if st_m else ""
            status_text = re.sub(
                r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", st_inner))
            ).strip()
            ic_m = re.search(r"(icon_label\d+\.png)", st_inner)
            icon_filename = ic_m.group(1) if ic_m else None

            href_m = re.search(
                r'onclick=(?:"[^"]*location\.href\s*=\s*\'([^\']+)\'[^"]*"|\'[^\']*location\.href\s*=\s*"([^"]+)"[^\']*\')',
                li,
            )
            raw_path = (href_m.group(1) or href_m.group(2)) if href_m else None
            if raw_path and "javascript:" in raw_path.lower():
                raw_path = None

            booking_url = booking_url_builder(raw_path) if raw_path else ""
            seat_status = map_tjoy_seat_status(status_text, icon_filename, bool(booking_url))

            ev_m = re.search(r"/reservation/index/(\d+)/", raw_path or "")
            event_id = ev_m.group(1) if ev_m else f"{movie_id}_{idx}_{start_time.replace(':', '')}"

            tags = extract_special_tags(title_ja, screen_name, *badge_texts)

            screenings.append(
                Screening(
                    event_id=event_id,
                    screen_name=screen_name,
                    start_time=start_time,
                    end_time=end_time,
                    seat_status=seat_status,
                    booking_url=booking_url,
                    tags=tags,
                )
            )

        if screenings:
            screenings.sort(key=lambda s: s.start_time)
            movies.append(
                MovieSchedule(
                    movie_id=movie_id,
                    movie_title=title_ja,
                    screenings=screenings,
                    movie_title_en=title_en or None,
                    info_url=info_url,
                )
            )

    movies.sort(
        key=lambda m: (
            m.screenings[0].start_time if m.screenings else "99:99",
            m.movie_title.lower(),
        )
    )
    return movies


class TJOYSessionError(RuntimeError):
    """T・ジョイのセッション/CSRF取得エラー"""


class TJoyCinemaProvider(BaseCinemaProvider):
    """
    T・ジョイ（東映ジョイ・エンタテインメント運営20館）向けスケジュール取得Provider
    公式API: POST https://tjoy.jp/theaterTop/scheduleGetHtmlApi
    """

    CHAIN_ID: str = "tjoy"
    BASE_URL: str = "https://tjoy.jp"
    BASE_BOOKING_URL: str = "https://tjoy.jp"
    API_SCHEDULE_URL: str = "https://tjoy.jp/theaterTop/scheduleGetHtmlApi"

    # 横断検索の並列実行時にも1セッションを安全に再利用するクラスレベルキャッシュ
    _session_lock = threading.Lock()
    _cached_opener: Optional[urllib.request.OpenerDirector] = None
    _cached_csrf_token: Optional[str] = None
    _session_expires_at: float = 0.0
    SESSION_TTL_SECONDS: float = 300.0

    def __init__(self, timeout: int = 15):
        super().__init__(timeout=timeout)
        self.default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _get_session(
        self,
        bootstrap_slug: str,
        force_refresh: bool = False,
    ) -> tuple[urllib.request.OpenerDirector, str]:
        """スレッドセーフに CookieJar 付き opener と CSRF トークンを取得・キャッシュする。"""
        safe_slug = sanitize_identifier(bootstrap_slug)
        now = time.monotonic()

        with self._session_lock:
            if (
                not force_refresh
                and self.__class__._cached_opener is not None
                and self.__class__._cached_csrf_token
                and now < self.__class__._session_expires_at
            ):
                return self.__class__._cached_opener, self.__class__._cached_csrf_token

            cj = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            opener.addheaders = [("User-Agent", self.default_headers["User-Agent"])]

            # 軽量な施設ページ (/facilities) で Cookie と CSRF トークンを取得
            bootstrap_urls = [
                f"{self.BASE_URL}/{safe_slug}/facilities",
                f"{self.BASE_URL}/{safe_slug}",
            ]
            csrf_token = ""
            last_err: Optional[Exception] = None

            for url in bootstrap_urls:
                try:
                    req = urllib.request.Request(url, headers=self.default_headers)
                    with opener.open(req, timeout=self.timeout) as resp:
                        html_text = resp.read().decode("utf-8", errors="replace")
                    m = re.search(
                        r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']',
                        html_text,
                    )
                    if not m:
                        m = re.search(
                            r'<input[^>]+id=["\']csrfToken["\'][^>]+value=["\']([^"\']+)["\']',
                            html_text,
                        )
                    if m and m.group(1):
                        csrf_token = m.group(1).strip()
                        break
                except Exception as e:
                    last_err = e
                    continue

            if not csrf_token:
                raise TJOYSessionError(
                    f"T・ジョイのCSRFトークン取得に失敗しました ({safe_slug}): {last_err}"
                )

            self.__class__._cached_opener = opener
            self.__class__._cached_csrf_token = csrf_token
            self.__class__._session_expires_at = time.monotonic() + self.SESSION_TTL_SECONDS
            return opener, csrf_token

    def get_tjoy_theater_id(self, theater_id: str) -> str:
        """劇場スラッグから T・ジョイ内部の数値 theaterId (例: '140') を解決する。"""
        safe_theater = sanitize_identifier(theater_id)
        info = self.get_theater_info(safe_theater)
        tid = info.get("tjoy_theater_id")
        if tid:
            return sanitize_identifier(str(tid))

        # マスタ未登録スラッグに対するフォールバック取得
        url = f"{self.BASE_URL}/{safe_theater}"
        req = urllib.request.Request(url, headers=self.default_headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                html_text = resp.read().decode("utf-8", errors="replace")
            m = re.search(
                r'<input[^>]+(?:id=["\']theaterId["\'][^>]+value=["\'](\d+)["\']|value=["\'](\d+)["\'][^>]+id=["\']theaterId["\'])',
                html_text,
            )
            if m:
                found = m.group(1) or m.group(2)
                if found:
                    return sanitize_identifier(found)
        except Exception as e:
            raise RuntimeError(
                f"T・ジョイ劇場 '{safe_theater}' の theaterId 解決に失敗しました: {e}"
            ) from e

        raise RuntimeError(f"T・ジョイ劇場 '{safe_theater}' の theaterId が見つかりません。")

    def _post_schedule_api(
        self,
        tjoy_theater_id: str,
        target_date: date,
        referer_slug: str,
    ) -> str:
        """scheduleGetHtmlApi を呼び出してスケジュールHTML断片を取得する（403時は1回リトライ）。"""
        safe_tid = sanitize_identifier(tjoy_theater_id)
        safe_slug = sanitize_identifier(referer_slug)
        date_str = target_date.strftime("%Y-%m-%d")

        for attempt in range(2):
            opener, csrf_token = self._get_session(safe_slug, force_refresh=(attempt > 0))
            payload = urllib.parse.urlencode(
                {
                    "data": json.dumps({"date": date_str, "theaterId": safe_tid}),
                    "_csrfToken": csrf_token,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                self.API_SCHEDULE_URL,
                data=payload,
                headers={
                    "User-Agent": self.default_headers["User-Agent"],
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{self.BASE_URL}/{safe_slug}",
                },
                method="POST",
            )
            try:
                with opener.open(req, timeout=self.timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                if e.code == 403 and attempt == 0:
                    continue
                raise RuntimeError(
                    f"T・ジョイ スケジュール取得に失敗しました (HTTP {e.code} {e.reason})"
                ) from e
            except Exception as e:
                raise RuntimeError(f"T・ジョイ スケジュール取得に失敗しました: {e}") from e

        return ""

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        T・ジョイ用予約URLを安全に構築する。
        """
        safe_theater = sanitize_identifier(theater_id)
        safe_event = sanitize_identifier(event_id)
        segments = [safe_theater, "reservation", "index", safe_event]
        query_params: Dict[str, str] = {}

        if extra_params:
            for key in ("cinema_code", "screen_no", "date"):
                val = extra_params.get(key)
                if val:
                    segments.append(sanitize_identifier(str(val)))
            for k, v in extra_params.items():
                if k not in ("cinema_code", "screen_no", "date") and v is not None and v != "":
                    query_params[sanitize_identifier(k)] = sanitize_identifier(str(v))

        return build_safe_url(
            self.BASE_URL,
            path_segments=segments,
            query_params=query_params or None,
        )

    def _build_safe_booking_url(self, raw_path: Optional[str]) -> str:
        """HTML内の予約相対パス（または tjoy.jp URL）を検証し安全な絶対URLを生成する。"""
        if not raw_path or not isinstance(raw_path, str):
            return ""
        unescaped = html_lib.unescape(raw_path).strip()
        if not unescaped or "javascript:" in unescaped.lower():
            return ""

        parsed = urllib.parse.urlparse(unescaped)
        if parsed.scheme and parsed.scheme != "https":
            return ""
        if parsed.netloc and parsed.netloc.lower() != "tjoy.jp":
            return ""

        segments = [seg for seg in parsed.path.split("/") if seg]
        if "reservation" not in segments or len(segments) < 4:
            return ""

        try:
            safe_segments = [sanitize_identifier(seg) for seg in segments]
            qs = urllib.parse.parse_qs(parsed.query)
            safe_params: Dict[str, str] = {}
            for k, vals in qs.items():
                if vals and vals[0]:
                    safe_params[sanitize_identifier(k)] = sanitize_identifier(vals[0])
            return build_safe_url(
                self.BASE_URL,
                path_segments=safe_segments,
                query_params=safe_params or None,
            )
        except UnsafeUrlError:
            return ""

    def build_movie_info_url(
        self,
        theater_slug: str,
        cinema_code: Optional[str] = None,
    ) -> Optional[str]:
        """T・ジョイの公式作品詳細URL (https://tjoy.jp/{slug}/cinema_detail/{code}) を生成する。"""
        try:
            safe_slug = sanitize_identifier(theater_slug)
            if cinema_code:
                safe_code = sanitize_identifier(cinema_code)
                return build_safe_url(
                    self.BASE_URL,
                    path_segments=[safe_slug, "cinema_detail", safe_code],
                )
            return build_safe_url(self.BASE_URL, path_segments=[safe_slug])
        except UnsafeUrlError:
            return None

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        tjoy_tid = self.get_tjoy_theater_id(safe_theater)
        html_fragment = self._post_schedule_api(
            tjoy_theater_id=tjoy_tid,
            target_date=target_date,
            referer_slug=safe_theater,
        )
        return parse_tjoy_schedule_html(
            html_str=html_fragment,
            theater_slug=safe_theater,
            booking_url_builder=self._build_safe_booking_url,
            info_url_builder=self.build_movie_info_url,
        )
