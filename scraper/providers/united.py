from datetime import date, datetime, timezone, timedelta
import html as html_lib
import json
import re
from typing import List, Dict, Any, Optional
import urllib.parse
import urllib.request

from ..models import MovieSchedule, Screening, SeatStatus
from ..sanitizer import sanitize_identifier, build_safe_url, UnsafeUrlError
from .base import BaseCinemaProvider

JST = timezone(timedelta(hours=9))

SPECIAL_TAG_PATTERNS = [
    ("IMAX", "IMAX"),
    ("4DX3D", "4DX 3D"),
    ("4DX2D", "4DX"),
    ("4DX", "4DX"),
    ("SCREENX", "ScreenX"),
    ("SCREEN X", "ScreenX"),
    ("3D", "3D"),
    ("DOLBY ATMOS", "Dolby Atmos"),
    ("DOLBY", "Dolby"),
    ("FLEXOUND", "FLEXOUND"),
    ("爆音", "爆音"),
    ("轟音", "轟音"),
    ("特別興行", "特別興行"),
    ("応援上映", "応援上映"),
]


def extract_special_tags(*text_sources: Optional[str]) -> List[str]:
    """スクリーン名や作品タイトルから特殊上映タグを抽出する"""
    tags = []
    combined = " ".join([s for s in text_sources if s]).upper()
    for pattern, label in SPECIAL_TAG_PATTERNS:
        if pattern in combined and label not in tags:
            tags.append(label)
    return tags


def map_united_seat_status(symbol: Optional[str], has_booking_link: bool) -> SeatStatus:
    """
    ユナイテッド・シネマの座席ステータス記号（alt属性）を共通 SeatStatus に変換する。
    - [○] / ○ : AVAILABLE
    - [△] / △ : FEW
    - [✕] / [×] / × : FULL
    - [□] / □ : 窓口販売のみ、または販売前/販売終了 (UNSOLD / AVAILABLE depending on link)
    """
    if not symbol:
        return SeatStatus.AVAILABLE if has_booking_link else SeatStatus.UNKNOWN

    s = symbol.strip()
    if "○" in s:
        return SeatStatus.AVAILABLE
    elif "△" in s:
        return SeatStatus.FEW
    elif "✕" in s or "×" in s:
        return SeatStatus.FULL
    elif "□" in s:
        return SeatStatus.AVAILABLE if has_booking_link else SeatStatus.UNSOLD
    return SeatStatus.AVAILABLE if has_booking_link else SeatStatus.UNKNOWN


class UnitedCinemaProvider(BaseCinemaProvider):
    """ユナイテッド・シネマ（ローソン・ユナイテッドシネマ）のスケジュール取得Provider"""

    CHAIN_ID = "united"
    BASE_URL = "https://www.unitedcinemas.jp"
    BASE_BOOKING_URL = "https://www.unitedcinemas.jp/all/cc.php"

    def __init__(self, timeout: int = 15):
        super().__init__(timeout=timeout)
        self.default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _fetch_daily_html(self, theater_id: str, target_date: date) -> str:
        """指定日の daily.php HTML を取得する"""
        date_str = target_date.strftime("%Y-%m-%d")
        url = f"{self.BASE_URL}/{theater_id}/daily.php?date={date_str}"
        req = urllib.request.Request(url, headers=self.default_headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read()
            return raw.decode("shift_jis", errors="replace")

    def _build_safe_booking_url(self, raw_href: Optional[str]) -> Optional[str]:
        """相対パスの予約リンクを検証・安全な絶対URL化する"""
        if not raw_href:
            return None

        unescaped = html_lib.unescape(raw_href).strip()
        parsed = urllib.parse.urlparse(unescaped)

        # 外部ホストへの不正リダイレクト防止（相対パスまたはunitedcinemas.jpのみ許可）
        if parsed.netloc and parsed.netloc != "www.unitedcinemas.jp":
            return None

        # /all/cc.php?tc=... を想定
        qs = urllib.parse.parse_qs(parsed.query)
        params: Dict[str, str] = {}
        for k, vals in qs.items():
            if vals and vals[0]:
                try:
                    params[sanitize_identifier(k)] = sanitize_identifier(vals[0])
                except UnsafeUrlError:
                    return None

        if not params:
            return None

        try:
            return build_safe_url(self.BASE_BOOKING_URL, query_params=params)
        except UnsafeUrlError:
            return None

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        """
        ユナイテッド・シネマの daily.php をパースし、MovieScheduleのリストを構築する。
        """
        html = self._fetch_daily_html(theater_id, target_date)
        date_str = target_date.strftime("%Y-%m-%d")

        theater_info = self.get_theater_info(theater_id)
        fac_screens = theater_info.get("facility", {}).get("screens") or []
        # スクリーン番号によるマッピング辞書を作成 (例: "1" -> screen_dict)
        screen_fac_map = {}
        for s in fac_screens:
            s_name = s.get("name", "")
            s_num = re.search(r"(\d+)", s_name)
            if s_num:
                screen_fac_map[s_num.group(1)] = s

        # 作品ごとに分割 (<li class="clearfix ...">...</li>)
        # ※ 4DXやIMAXの作品は class="clearfix fourdx " や class="clearfix imax " になるため正規表現で分割
        blocks = re.split(r'<li\s+class=["\'][^"\']*clearfix[^"\']*["\']', html)[1:]
        movie_schedules: List[MovieSchedule] = []

        for b in blocks:
            # 作品タイトル
            m_title = re.search(r'<span class="movieTitle">(.*?)</span>', b, re.DOTALL)
            if not m_title:
                continue

            title_a = re.search(r'<a[^>]*>(.*?)</a>', m_title.group(1), re.DOTALL)
            if not title_a:
                continue

            clean_title = re.sub(r'<[^>]+>', '', title_a.group(1)).strip()
            if not clean_title:
                continue

            # 作品ID (film.php?film=22476 等から抽出)
            href_film = title_a.group(0)
            film_m = re.search(r'film=(\d+)', href_film)
            movie_id = film_m.group(1) if film_m else re.sub(r'[^A-Za-z0-9_]', '', clean_title)

            # 年齢制限 (PG12, R15+ 等)
            rating_m = re.search(r'alt=["\'](PG\d+|R\d+\+?)["\']', m_title.group(1))
            rating = rating_m.group(1) if rating_m else None

            # スケジュールリスト (<ul class="tl">...</ul>)
            tl_idx = b.find('<ul class="tl">')
            if tl_idx == -1:
                continue

            tl_html = b[tl_idx:]
            screen_groups = tl_html.split('<p class="screenNumber">')[1:]
            screenings: List[Screening] = []

            for sg in screen_groups:
                # スクリーン名
                sc_m = re.search(r'alt=["\']([^"\']+)["\']', sg)
                screen_raw = sc_m.group(1) if sc_m else ""
                screen_num_m = re.search(r'(\d+)', screen_raw)
                screen_name = f"スクリーン{screen_num_m.group(1)}" if screen_num_m else (screen_raw or "メインスクリーン")

                # 上映時間 (<li class="startTime">...</li>, <li class="endTime">...</li>)
                times = re.findall(
                    r'<li class="startTime">([^<]+)</li>\s*<li class="endTime">([^<]+)</li>',
                    sg,
                )
                uol_icons = re.findall(r'<li class="uolIcon">(.*?)</li>', sg, re.DOTALL)

                for idx, (st, et) in enumerate(times):
                    start_time_str = st.strip()
                    end_time_str = et.replace("〜", "").strip()

                    uol = uol_icons[idx] if idx < len(uol_icons) else ""
                    alt_m = re.search(r'alt=["\']\[([^\]]+)\]["\']', uol)
                    seat_symbol = alt_m.group(1) if alt_m else ""
                    href_m = re.search(r'href=["\']([^"\']+)["\']', uol)
                    raw_href = href_m.group(1) if href_m else None

                    booking_url = self._build_safe_booking_url(raw_href)
                    seat_status = map_united_seat_status(seat_symbol, bool(booking_url))

                    # 施設マスタからの設備タグを結合
                    fac_features = []
                    if screen_num_m and screen_num_m.group(1) in screen_fac_map:
                        fac_features = screen_fac_map[screen_num_m.group(1)].get("features", [])

                    special_tags = extract_special_tags(clean_title, screen_name, *fac_features)

                    # event_id を生成（stやscパラメータがあれば使用、無ければ時刻組み合わせ）
                    event_id = f"{movie_id}_{screen_name}_{start_time_str.replace(':', '')}"
                    if raw_href:
                        st_m = re.search(r'st=(\d+)', raw_href)
                        sc_m_code = re.search(r'sc=(\d+)', raw_href)
                        if st_m and sc_m_code:
                            event_id = f"{sc_m_code.group(1)}_{st_m.group(1)}"

                    screening = Screening(
                        event_id=event_id,
                        screen_name=screen_name,
                        start_time=start_time_str,
                        end_time=end_time_str,
                        seat_status=seat_status,
                        booking_url=booking_url or "",
                        tags=special_tags,
                    )
                    screenings.append(screening)

            if screenings:
                movie_schedules.append(
                    MovieSchedule(
                        movie_id=movie_id,
                        movie_title=clean_title,
                        screenings=screenings,
                    )
                )

        return movie_schedules
