from datetime import date
import html as html_lib
import re
from typing import Callable, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request

from ..models import MovieSchedule, Screening, SeatStatus
from ..sanitizer import UnsafeUrlError, build_safe_url, sanitize_identifier
from .base import BaseCinemaProvider

# 全角英数字・記号から半角への変換テーブル (シアター名・設備名正規化用)
_FULLWIDTH_TRANS = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ－＿　",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz-_ ",
)


def normalize_109_screen_name(raw_name: str) -> str:
    """
    109シネマズのスクリーン名を正規化する。
    - 'THEATER 2', 'シアター 8', 'シアター１' -> 'シアター2', 'シアター8', 'シアター1'
    - 'グランドEXE' -> 'グランドEXE'
    """
    if not raw_name:
        return "シアター未定"
    normalized = html_lib.unescape(raw_name).translate(_FULLWIDTH_TRANS)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return "シアター未定"

    m = re.search(r"(?:シアター|THEATER)\s*(\d+)", normalized, re.IGNORECASE)
    if m:
        return f"シアター{m.group(1)}"
    return normalized


def extract_special_tags(*text_sources: Optional[str]) -> List[str]:
    """
    作品タイトルおよびスクリーン設備表示から特殊上映タグを抽出する。
    (字幕・吹替・2D・ODS・[L]等は含めない)
    """
    tags: List[str] = []
    texts = [s for s in text_sources if s]
    if not texts:
        return tags

    combined = " ".join(texts).translate(_FULLWIDTH_TRANS)
    combined_upper = combined.upper()
    combined_compact = re.sub(r"\s+", "", combined_upper)

    if re.search(r"IMAX.{0,4}(?:レーザー|LASER)", combined_upper):
        tags.append("IMAXレーザー")
    elif "IMAX" in combined_upper:
        tags.append("IMAX")

    if "ULTRA4DX" in combined_compact:
        tags.append("ULTRA 4DX")
    elif "4DX" in combined_upper:
        tags.append("4DX")

    if "SCREENX" in combined_compact:
        tags.append("ScreenX")
    if "DOLBYATMOS" in combined_compact:
        tags.append("Dolby Atmos")
    if "SAION" in combined_upper:
        tags.append("SAION")
    if "KIDSCINEMA" in combined_compact:
        tags.append("KIDS CINEMA")
    if "MASTERIMAGE3D" in combined_compact or re.search(
        r"(?:^|[^A-Z0-9]|4DX|IMAX)3D(?![A-Z0-9])", combined_upper
    ):
        tags.append("3D")

    return tags


def map_109_seat_status(
    status_class: Optional[str],
    status_text: str,
    has_booking_link: bool,
) -> SeatStatus:
    """
    109シネマズのステータスdivクラスおよびテキストから SeatStatus を判定する。
    - available / member -> AVAILABLE
    - remaining / presale -> FEW
    - soldout / 売り切れ / 満席 -> FULL
    - close / others / 販売終了 / 販売開始前 / 終了 -> UNSOLD
    """
    classes = set((status_class or "").lower().split())
    txt = (status_text or "").strip()

    if "soldout" in classes or "売り切れ" in txt or "満席" in txt:
        return SeatStatus.FULL
    if (
        "close" in classes
        or "others" in classes
        or "販売終了" in txt
        or "販売開始前" in txt
        or "終了" in txt
    ):
        return SeatStatus.UNSOLD
    if "remaining" in classes or "presale" in classes or "残りわずか" in txt:
        return SeatStatus.FEW
    if "available" in classes or "member" in classes:
        return SeatStatus.AVAILABLE
    return SeatStatus.AVAILABLE if has_booking_link else SeatStatus.UNKNOWN


def _pad_hhmm(time_str: str) -> str:
    """'9:30' のような1桁時表記を '09:30' に揃える（24時超えはそのまま保持）。"""
    t = time_str.strip()
    if len(t) == 4 and t[1] == ":":
        return "0" + t
    return t


def _strip_tags(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_109_schedule_html(
    html_str: str,
    theater_slug: str,
    booking_url_builder: Callable[[Optional[str]], str],
    info_url_builder: Callable[[Optional[str], str], Optional[str]],
) -> List[MovieSchedule]:
    """
    109シネマズ（通常18館およびプレミアム新宿）の日別スケジュールHTMLをパースし
    MovieSchedule のリストを返す。
    """
    if not html_str:
        return []

    # プレミアム新宿の仕様メモコメント（4DXScreen 等）による偽タグ防止のため必ず最初に除去
    clean_html = re.sub(r"<!--.*?-->", "", html_str, flags=re.DOTALL)

    articles = re.findall(r"<article([^>]*)>(.*?)</article>", clean_html, re.DOTALL)
    if not articles:
        return []

    movies: List[MovieSchedule] = []

    for art_idx, (attrs, art_body) in enumerate(articles):
        id_m = (
            re.search(r'id=["\']m(\d+)["\']', attrs)
            or re.search(r'data-film-id=["\'](\d+)["\']', attrs)
            or re.search(r'\bmg([A-Za-z0-9]+)\b', attrs)
        )
        movie_id = id_m.group(1) if id_m else f"m{art_idx}"

        header_m = re.search(r"<header>(.*?)</header>", art_body, re.DOTALL)
        header_html = header_m.group(1) if header_m else art_body

        h2_m = re.search(r"<h2[^>]*>(.*?)</h2>", header_html, re.DOTALL)
        if not h2_m:
            continue
        title_ja = _strip_tags(h2_m.group(1))
        if not title_ja:
            continue

        en_m = re.search(r'<p[^>]*lang=["\']en["\'][^>]*>(.*?)</p>', header_html, re.DOTALL)
        title_en = _strip_tags(en_m.group(1)) if en_m else ""

        info_a_m = re.search(r'<a[^>]+href=["\']([^"\']+)["\']', header_html)
        raw_info_href = info_a_m.group(1).strip() if info_a_m else None
        info_url = info_url_builder(raw_info_href, theater_slug)

        ul_blocks = re.findall(
            r'<ul[^>]*class=["\'][^"\']*timetable[^"\']*["\'][^>]*>(.*?)</ul>',
            art_body,
            re.DOTALL,
        )

        screenings: List[Screening] = []

        for ul_idx, ul_body in enumerate(ul_blocks):
            # 通常館は </li> 閉じタグが省略されているため <li で分割して処理
            li_parts = re.split(r"<li\b", ul_body)[1:]
            screen_name = "シアター未定"
            screen_format_text = ""

            for li_idx, li_part in enumerate(li_parts):
                if re.match(r'^[^>]*class=["\'][^"\']*\btheatre\b', li_part):
                    a_m = re.search(r"<a[^>]*>(.*?)</a>", li_part, re.DOTALL)
                    raw_screen = re.sub(r"<[^>]+>", " ", a_m.group(1)) if a_m else ""
                    screen_name = normalize_109_screen_name(raw_screen)
                    screen_format_text = _strip_tags(li_part)
                    continue

                # プレミアム新宿は <span class="seets"> (CLASS A|S 合算) のみを抽出して重複を防ぐ
                seets_m = re.search(
                    r'<span[^>]*class=["\'][^"\']*\bseets\b[^"\']*["\'][^>]*>(.*?)</span>',
                    li_part,
                    re.DOTALL,
                )
                slot_html = seets_m.group(1) if seets_m else li_part

                st_m = re.search(r'<time[^>]*class=["\']start["\'][^>]*>([^<]+)</time>', slot_html)
                if not st_m:
                    continue
                start_time = _pad_hhmm(st_m.group(1))

                et_m = re.search(r'<time[^>]*class=["\']end["\'][^>]*>([^<]+)</time>', slot_html)
                end_time = _pad_hhmm(et_m.group(1)) if et_m else ""

                div_m = re.search(r'<div[^>]*class=["\']([^"\']+)["\'][^>]*>(.*?)</div>', slot_html, re.DOTALL)
                status_class = div_m.group(1) if div_m else ""
                status_text = _strip_tags(div_m.group(2)) if div_m else ""

                href_m = re.search(r'<a[^>]+href=["\']([^"\']+)["\']', slot_html)
                raw_booking_href = href_m.group(1).strip() if href_m else None
                booking_url = booking_url_builder(raw_booking_href) if raw_booking_href else ""

                seat_status = map_109_seat_status(status_class, status_text, bool(booking_url))

                event_id = ""
                if booking_url:
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(booking_url).query)
                    ttc = (qs.get("ttc") or [""])[0]
                    tssc = (qs.get("tssc") or [""])[0]
                    stt = (qs.get("stt") or [""])[0]
                    if ttc and tssc and stt:
                        event_id = f"{ttc}_{tssc}_{stt}"
                if not event_id:
                    event_id = f"{movie_id}_{ul_idx}_{li_idx}_{start_time.replace(':', '')}"

                tags = extract_special_tags(title_ja, screen_format_text)

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
            screenings.sort(key=lambda s: (s.start_time, s.screen_name))
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


class Cinemas109Provider(BaseCinemaProvider):
    """
    109シネマズ（全19館：通常18館 + 109シネマズプレミアム新宿）向けスケジュール取得Provider
    公式HTML: https://109cinemas.net/{slug}/schedules/{YYYYMMDD}.html
    """

    CHAIN_ID: str = "109cinemas"
    BASE_URL: str = "https://109cinemas.net"
    BASE_BOOKING_URL: str = "https://cinema.109cinemas.net/cgi-bin/pc/resv/resv_shw_ppt.cgi"

    def __init__(self, timeout: int = 15):
        super().__init__(timeout=timeout)
        self.default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _fetch_schedule_html(
        self,
        theater_slug: str,
        target_date: date,
        theater_code: Optional[str] = None,
    ) -> str:
        """指定劇場・日付のスケジュールHTMLを取得する（404時は空文字列を返す）。"""
        safe_slug = sanitize_identifier(theater_slug)
        date_str = target_date.strftime("%Y%m%d")
        url = f"{self.BASE_URL}/{safe_slug}/schedules/{date_str}.html"
        if theater_code and safe_slug != "premiumshinjuku":
            safe_code = sanitize_identifier(str(theater_code))
            url = f"{url}?theater_code={safe_code}"

        req = urllib.request.Request(url, headers=self.default_headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""
            raise RuntimeError(
                f"109シネマズ スケジュール取得に失敗しました ({safe_slug}, HTTP {e.code} {e.reason})"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"109シネマズ スケジュール取得に失敗しました ({safe_slug}): {e}"
            ) from e

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        109シネマズ予約URLを安全に構築する。
        """
        safe_theater = sanitize_identifier(theater_id)
        safe_event = sanitize_identifier(event_id)
        query: Dict[str, str] = {
            "ttc": safe_event,
            "tsc": safe_theater,
        }
        if extra_params:
            for k, v in extra_params.items():
                safe_k = sanitize_identifier(k)
                if v is None or v == "":
                    query[safe_k] = ""
                else:
                    query[safe_k] = sanitize_identifier(str(v))
        return build_safe_url(self.BASE_BOOKING_URL, query_params=query)

    def _build_safe_booking_url(self, raw_href: Optional[str]) -> str:
        """HTML内の予約URLを検証・再構築する（不正ホスト・スキームは空文字を返す）。"""
        if not raw_href or not isinstance(raw_href, str):
            return ""
        unescaped = html_lib.unescape(raw_href).strip()
        if not unescaped or "javascript:" in unescaped.lower():
            return ""

        parsed = urllib.parse.urlparse(unescaped)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != "cinema.109cinemas.net":
            return ""
        if parsed.path != "/cgi-bin/pc/resv/resv_shw_ppt.cgi":
            return ""

        try:
            qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            safe_params: Dict[str, str] = {}
            for k, vals in qs.items():
                safe_k = sanitize_identifier(k)
                val = vals[0] if vals else ""
                safe_params[safe_k] = sanitize_identifier(val) if val != "" else ""
            if not safe_params:
                return ""
            return build_safe_url(self.BASE_BOOKING_URL, query_params=safe_params)
        except UnsafeUrlError:
            return ""

    def build_movie_info_url(
        self,
        raw_href: Optional[str],
        theater_slug: str,
    ) -> Optional[str]:
        """
        109シネマズの公式作品詳細URLを検証・構築する。
        外部短縮URL (https://x.gd/... 等) は拒否して劇場トップURLへフォールバックする。
        """
        safe_slug = sanitize_identifier(theater_slug)
        fallback = build_safe_url(f"{self.BASE_URL}/{safe_slug}/")

        if not raw_href or not isinstance(raw_href, str):
            return fallback

        unescaped = html_lib.unescape(raw_href).strip()
        if not unescaped or "javascript:" in unescaped.lower():
            return fallback

        parsed = urllib.parse.urlparse(unescaped)
        if parsed.scheme and parsed.scheme != "https":
            return fallback
        if parsed.netloc and (parsed.hostname or "").lower() != "109cinemas.net":
            return fallback

        segments = [seg for seg in parsed.path.split("/") if seg]
        if not segments:
            return fallback

        try:
            safe_segments = [sanitize_identifier(seg) for seg in segments]
            qs = urllib.parse.parse_qs(parsed.query)
            safe_params: Dict[str, str] = {}
            for k, vals in qs.items():
                if vals and vals[0]:
                    safe_params[sanitize_identifier(k)] = sanitize_identifier(vals[0])

            trailing = "/" if parsed.path.endswith("/") else ""
            target_url = f"{self.BASE_URL}/" + "/".join(safe_segments) + trailing
            return build_safe_url(target_url, query_params=safe_params or None)
        except UnsafeUrlError:
            return fallback

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        theater_info = self.get_theater_info(safe_theater)
        theater_code = theater_info.get("theater_code")
        html_str = self._fetch_schedule_html(
            theater_slug=safe_theater,
            target_date=target_date,
            theater_code=theater_code,
        )
        return parse_109_schedule_html(
            html_str=html_str,
            theater_slug=safe_theater,
            booking_url_builder=self._build_safe_booking_url,
            info_url_builder=self.build_movie_info_url,
        )
