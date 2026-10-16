from datetime import date, datetime, timezone, timedelta
import json
import re
import time
from typing import List, Dict, Any, Optional
import urllib.parse
import urllib.request

from ..models import MovieSchedule, Screening, SeatStatus
from ..sanitizer import sanitize_identifier, build_safe_url, UnsafeUrlError
from .base import BaseCinemaProvider

JST = timezone(timedelta(hours=9))

SPECIAL_TAG_PATTERNS = [
    ("IMAX", "IMAX"),
    ("DOLBY CINEMA", "Dolby Cinema"),
    ("DOLBY ATMOS", "Dolby Atmos"),
    ("DOLBY", "Dolby"),
    ("ATMOS", "Atmos"),
    ("TCX", "TCX"),
    ("MX4D", "MX4D"),
    ("4D", "4D"),
    ("SCREEN X", "SCREEN X"),
    ("SCREENX", "SCREEN X"),
    ("DTS:X", "DTS:X"),
    ("轟音", "轟音"),
    ("プレミアム", "プレミアム"),
]


def extract_special_tags(*text_sources: Optional[str]) -> List[str]:
    """スクリーン名、作品名、アイコン文字列等から特殊上映タグを抽出する"""
    tags = []
    combined = " ".join([s for s in text_sources if s]).upper()
    for pattern, label in SPECIAL_TAG_PATTERNS:
        if pattern in combined and label not in tags:
            tags.append(label)
    # 冗長タグの整理 (例: Dolby Atmos/Cinema がある場合は単なる Dolby/Atmos を除外、MX4D がある場合は 4D を除外)
    if "Dolby Cinema" in tags or "Dolby Atmos" in tags:
        if "Dolby" in tags:
            tags.remove("Dolby")
        if "Atmos" in tags:
            tags.remove("Atmos")
    if "MX4D" in tags or "4DX" in tags:
        if "4D" in tags:
            tags.remove("4D")
    return tags


def map_toho_seat_status(unsold_status: Optional[str]) -> SeatStatus:
    """
    TOHOシネマズの unsoldSeatStatus を共通 SeatStatus に変換する。
    - 'A': 余裕あり (◎) -> AVAILABLE
    - 'B': 残り半分 (○) -> AVAILABLE
    - 'C': 残りわずか (△) -> FEW
    - 'D': 売り切れ (✕) -> FULL
    - 'G': 販売期間外 / 対象外 (-) -> UNSOLD
    """
    if not unsold_status:
        return SeatStatus.UNKNOWN
    status = unsold_status.upper().strip()
    if status in ("A", "B"):
        return SeatStatus.AVAILABLE
    elif status == "C":
        return SeatStatus.FEW
    elif status == "D":
        return SeatStatus.FULL
    elif status in ("G", "E", "F"):
        return SeatStatus.UNSOLD
    return SeatStatus.UNKNOWN


class TohoCinemaProvider(BaseCinemaProvider):
    """
    TOHOシネマズ向けスケジュール取得Provider
    公式API: https://api2.tohotheater.jp/api/schedule/v2/schedule/{theater_cd}/TNPI3050J05
    """

    CHAIN_ID: str = "toho"
    API_BASE_URL: str = "https://api2.tohotheater.jp/api/schedule/v2/schedule"
    BOOKING_BASE_URL_FORMAT: str = "https://hlo.tohotheater.jp/net/ticket/{site_cd}/TNPI2040J03.do"

    def __init__(self, timeout: int = 15):
        super().__init__(timeout=timeout)

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        TOHOシネマズ用チケット予約・詳細URLの安全な構築。
        theater_id (site_cd): 3桁の劇場コード (例: '089')
        event_id: pf_no または識別番号
        extra_params: jyoei_date, gekijyo_cd, screen_cd, sakuhin_cd など
        """
        safe_site = sanitize_identifier(theater_id)
        safe_pf = sanitize_identifier(event_id)

        query: Dict[str, str] = {
            "site_cd": safe_site,
            "pf_no": safe_pf,
        }
        if extra_params:
            for k, v in extra_params.items():
                if v is not None and v != "":
                    query[k] = sanitize_identifier(str(v))

        base_url = f"https://hlo.tohotheater.jp/net/ticket/{safe_site}/TNPI2040J03.do"
        return build_safe_url(base_url, query_params=query)

    def build_movie_info_url(self, movie_code: str, theater_id: Optional[str] = None) -> Optional[str]:
        """TOHOシネマズの作品詳細URL (https://hlo.tohotheater.jp/net/movie/TNPI3060J01.do?sakuhin_cd={mcode}) を生成する"""
        if movie_code:
            try:
                safe_mcode = sanitize_identifier(movie_code)
                return build_safe_url(
                    "https://hlo.tohotheater.jp/net/movie/TNPI3060J01.do",
                    query_params={"sakuhin_cd": safe_mcode},
                )
            except UnsafeUrlError:
                pass
        if theater_id:
            try:
                safe_theater = sanitize_identifier(theater_id)
                return build_safe_url(f"https://hlo.tohotheater.jp/net/schedule/{safe_theater}/TNPI2000J01.do")
            except UnsafeUrlError:
                pass
        return None

    def _fetch_schedule_raw(self, theater_code: str, target_date: date) -> Dict[str, Any]:
        """api2.tohotheater.jp からスケジュールJSONを取得する"""
        safe_code = sanitize_identifier(theater_code)
        date_str = target_date.strftime("%Y%m%d")
        now_ts = int(time.time())

        url = (
            f"{self.API_BASE_URL}/{safe_code}/TNPI3050J05"
            f"?__type__=json&vg_cd={safe_code}&show_day={date_str}&isMember=&enter_kbn=&_dc={now_ts}"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://hlo.tohotheater.jp/net/schedule/{safe_code}/TNPI2000J01.do",
            "Origin": "https://hlo.tohotheater.jp",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content = resp.read().decode("utf-8")
                return json.loads(content)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise RuntimeError(
                    f"TOHOシネマズ劇場コード '{safe_code}' のデータが見つかりませんでした (HTTP {e.code})。"
                ) from e
            raise RuntimeError(f"HTTPエラーが発生しました: {e.code} {e.reason}") from e
        except Exception as e:
            raise RuntimeError(f"TOHOシネマズスケジュール取得に失敗しました: {e}") from e

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        raw_data = self._fetch_schedule_raw(safe_theater, target_date)

        data_list = raw_data.get("data", [])
        if not data_list:
            return []

        # 通常 data[0].list に劇場のリストが入っている
        theater_container = data_list[0]
        theater_items = theater_container.get("list", [])
        if not theater_items:
            return []

        # 指定劇場の映画リスト (通常 index 0)
        target_theater_data = theater_items[0]
        raw_movies = target_theater_data.get("list", [])
        if not raw_movies:
            return []

        date_str = target_date.strftime("%Y%m%d")
        movies: List[MovieSchedule] = []

        for m in raw_movies:
            movie_title = (m.get("name") or "").strip()
            movie_code = str(m.get("code") or m.get("mcode") or "")
            if not movie_title:
                continue

            screenings: List[Screening] = []
            for item in m.get("list", []):
                showing_start = (item.get("showingStart") or "").strip()
                showing_end = (item.get("showingEnd") or "").strip()
                if not showing_start:
                    continue

                screen_info = item.get("screen", {})
                screen_name = screen_info.get("name") or "スクリーン未定"
                screen_code = str(screen_info.get("code") or "")
                theater_sub_cd = str(screen_info.get("theaterCd") or "")
                pf_no = str(item.get("code") or "")

                unsold_seat_info = item.get("unsoldSeatInfo") or {}
                unsold_status = unsold_seat_info.get("unsoldSeatStatus")
                seat_status = map_toho_seat_status(unsold_status)

                # 特殊上映タグ抽出
                icon_names = [
                    screen_info.get("iconNm1"),
                    screen_info.get("iconNm2"),
                    screen_info.get("iconNm3"),
                    m.get("ename"),
                ]
                tags = extract_special_tags(screen_name, movie_title, *icon_names)

                # 安全な予約URL生成
                booking_url = ""
                if pf_no and movie_code:
                    try:
                        extra = {
                            "jyoei_date": date_str,
                            "sakuhin_cd": movie_code,
                        }
                        if theater_sub_cd:
                            extra["gekijyo_cd"] = theater_sub_cd
                        if screen_code:
                            extra["screen_cd"] = screen_code

                        booking_url = self.build_booking_url(
                            theater_id=safe_theater,
                            event_id=pf_no,
                            extra_params=extra,
                        )
                    except UnsafeUrlError:
                        booking_url = ""

                screenings.append(
                    Screening(
                        event_id=pf_no or f"{movie_code}-{showing_start}",
                        screen_name=screen_name,
                        start_time=showing_start,
                        end_time=showing_end,
                        seat_status=seat_status,
                        booking_url=booking_url,
                        tags=tags,
                    )
                )

            if screenings:
                screenings.sort(key=lambda s: s.start_time)
                info_url = self.build_movie_info_url(movie_code, safe_theater)
                movies.append(
                    MovieSchedule(
                        movie_id=movie_code or sanitize_identifier(movie_title[:32]),
                        movie_title=movie_title,
                        screenings=screenings,
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
