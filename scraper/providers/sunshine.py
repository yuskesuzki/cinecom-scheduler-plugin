from datetime import date, datetime, timezone, timedelta
import json
import time
from typing import List, Dict, Any, Optional
import urllib.parse
import urllib.request
import concurrent.futures

from ..models import MovieSchedule, Screening, SeatStatus
from ..sanitizer import sanitize_identifier, build_safe_url, UnsafeUrlError
from .base import BaseCinemaProvider

JST = timezone(timedelta(hours=9))

SPECIAL_TAG_PATTERNS = [
    ("IMAX", "IMAX"),
    ("DOLBY ATMOS", "Dolby Atmos"),
    ("DOLBY", "Dolby"),
    ("BESTIA", "BESTIA"),
    ("4DX", "4DX"),
    ("SCREENX", "ScreenX"),
    ("SCREEN X", "ScreenX"),
    ("DTS:X", "DTS:X"),
    ("SCULPTED SURROUND", "Sculpted Surround"),
    ("プレミアム", "プレミアム"),
    ("レーザー", "レーザー"),
]


def extract_special_tags(*text_sources: Optional[str]) -> List[str]:
    """スクリーン名、作品名等から特殊上映タグを抽出する"""
    tags = []
    combined = " ".join([s for s in text_sources if s]).upper()
    for pattern, label in SPECIAL_TAG_PATTERNS:
        if pattern in combined and label not in tags:
            tags.append(label)
    # 冗長タグの整理 (例: Dolby Atmos がある場合は単なる Dolby を除外)
    if "Dolby Atmos" in tags or "Dolby Cinema" in tags:
        if "Dolby" in tags:
            tags.remove("Dolby")
    return tags


def map_sunshine_seat_status(remaining: Optional[int], maximum: Optional[int]) -> SeatStatus:
    """
    シネマサンシャインの残席数と定員から SeatStatus を判定する。
    - remaining == 0: 満席 (FULL)
    - remaining <= 15 または 残り15%以下: 残りわずか (FEW)
    - それ以外 (残席あり): 空席あり (AVAILABLE)
    """
    if remaining is None:
        return SeatStatus.UNKNOWN
    if remaining <= 0:
        return SeatStatus.FULL
    if maximum and maximum > 0:
        ratio = remaining / maximum
        if remaining <= 15 or ratio <= 0.15:
            return SeatStatus.FEW
    elif remaining <= 15:
        return SeatStatus.FEW
    return SeatStatus.AVAILABLE


def parse_sunshine_time(dt_str: str) -> str:
    """ISO 8601日時文字列をJSTの HH:MM 形式に変換する"""
    if not dt_str:
        return ""
    try:
        if dt_str.endswith("Z"):
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        elif len(dt_str) >= 5 and (dt_str[-5] in ("+", "-") and dt_str[-3] != ":"):
            dt = datetime.fromisoformat(dt_str[:-2] + ":" + dt_str[-2:])
        else:
            dt = datetime.fromisoformat(dt_str)
        return dt.astimezone(JST).strftime("%H:%M")
    except Exception:
        return ""


class CinemaSunshineProvider(BaseCinemaProvider):
    """
    シネマサンシャイン向けスケジュール取得Provider
    公式API:
      - 全体スケジュールインデックス: https://www.cinemasunshine.co.jp/schedule/data/schedule.json?v={ts}
      - 上映回詳細: https://www.cinemasunshine.co.jp/schedule/data/{movieId}/{smartTheaterNo}/{YYYYMMDD}.json?v={ts}
    """

    CHAIN_ID: str = "sunshine"
    BASE_INDEX_URL: str = "https://www.cinemasunshine.co.jp/schedule/data/schedule.json"
    BOOKING_TRANSACTION_BASE_URL: str = (
        "https://transaction.ticket-cinemasunshine.com/projects/sskts-production/purchase/transaction/"
    )

    def __init__(self, timeout: int = 15):
        super().__init__(timeout=timeout)

    def get_smart_theater_no(self, theater_id: str) -> str:
        """劇場マスタから smart_theater_no (例: '020') を取得する"""
        info = self.get_theater_info(theater_id)
        return str(info.get("smart_theater_no") or info.get("code") or theater_id)

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        シネマサンシャイン用予約URLの安全な構築。
        イベントID（例: '02027649020261016622050'）をサニタイズして
        https://transaction.ticket-cinemasunshine.com/projects/sskts-production/purchase/transaction/{event_id}
        を生成する。
        """
        safe_event_id = sanitize_identifier(event_id)
        base_url = f"{self.BOOKING_TRANSACTION_BASE_URL}{safe_event_id}"
        return build_safe_url(base_url, query_params=extra_params)

    def _fetch_json(self, url: str) -> Any:
        headers = {
            "User-Agent": self.default_headers["User-Agent"],
            "Accept": "application/json, text/plain, */*",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content = resp.read().decode("utf-8")
                return json.loads(content)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            raise RuntimeError(f"HTTPエラーが発生しました: {e.code} {e.reason}") from e
        except Exception as e:
            raise RuntimeError(f"データ取得に失敗しました ({url}): {e}") from e

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        smart_theater_no = self.get_smart_theater_no(safe_theater)
        date_str = target_date.strftime("%Y%m%d")
        now_ts = int(time.time())

        # 1. スケジュールインデックスを取得
        index_url = f"{self.BASE_INDEX_URL}?v={now_ts}"
        index_data = self._fetch_json(index_url)
        if not index_data or not isinstance(index_data, dict):
            return []

        # 2. 対象劇場・対象日付の上映がある movieId 一覧を抽出
        target_movie_ids: List[str] = []
        for movie_id, theaters_map in index_data.items():
            if not isinstance(theaters_map, dict):
                continue
            if smart_theater_no in theaters_map:
                dates_map = theaters_map[smart_theater_no]
                if isinstance(dates_map, dict) and date_str in dates_map:
                    target_movie_ids.append(str(movie_id))

        if not target_movie_ids:
            return []

        # 3. 各映画の詳細JSONを並行取得
        def fetch_movie_detail(m_id: str) -> Optional[Dict[str, Any]]:
            safe_m_id = sanitize_identifier(m_id)
            safe_theater_no = sanitize_identifier(smart_theater_no)
            detail_url = (
                f"https://www.cinemasunshine.co.jp/schedule/data/"
                f"{safe_m_id}/{safe_theater_no}/{date_str}.json?v={now_ts}"
            )
            return self._fetch_json(detail_url)

        movie_details: Dict[str, Any] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(target_movie_ids))) as executor:
            future_to_id = {
                executor.submit(fetch_movie_detail, m_id): m_id for m_id in target_movie_ids
            }
            for future in concurrent.futures.as_completed(future_to_id):
                m_id = future_to_id[future]
                try:
                    res = future.result()
                    if res and isinstance(res, dict):
                        movie_details[m_id] = res
                except Exception:
                    continue

        # 4. MovieSchedule リストを組み立て
        movies: List[MovieSchedule] = []

        for m_id, time_slots in movie_details.items():
            movie_title_ja = ""
            movie_title_en = ""
            screenings: List[Screening] = []

            for time_key, branches in time_slots.items():
                if not isinstance(branches, dict):
                    continue
                for branch_code, event in branches.items():
                    if not isinstance(event, dict):
                        continue

                    # タイトル情報の取得
                    name_info = event.get("name") or {}
                    if not movie_title_ja:
                        movie_title_ja = (name_info.get("ja") or "").strip()
                    if not movie_title_en:
                        movie_title_en = (name_info.get("en") or "").strip()

                    # 上映時間の取得
                    start_iso = event.get("startDate") or ""
                    end_iso = event.get("endDate") or ""
                    start_time = parse_sunshine_time(start_iso)
                    end_time = parse_sunshine_time(end_iso)

                    if not start_time:
                        continue

                    # スクリーン名
                    loc_info = event.get("location") or {}
                    loc_name_info = loc_info.get("name") or {}
                    screen_name = loc_name_info.get("ja") or "スクリーン未定"

                    # 残席ステータス判定
                    rem_cap = event.get("remainingAttendeeCapacity")
                    max_cap = event.get("maximumAttendeeCapacity")
                    seat_status = map_sunshine_seat_status(rem_cap, max_cap)

                    # 特殊上映タグ抽出
                    desc_info = event.get("description") or {}
                    desc_ja = desc_info.get("ja") or ""
                    tags = extract_special_tags(screen_name, movie_title_ja, desc_ja)

                    # 予約URL
                    event_id = str(event.get("id") or "")
                    booking_url = ""
                    if event_id:
                        try:
                            booking_url = self.build_booking_url(
                                theater_id=safe_theater,
                                event_id=event_id,
                            )
                        except UnsafeUrlError:
                            booking_url = ""

                    screenings.append(
                        Screening(
                            event_id=event_id or f"{m_id}-{start_time}",
                            screen_name=screen_name,
                            start_time=start_time,
                            end_time=end_time,
                            seat_status=seat_status,
                            booking_url=booking_url,
                            tags=tags,
                        )
                    )

            if screenings and movie_title_ja:
                screenings.sort(key=lambda s: s.start_time)
                movies.append(
                    MovieSchedule(
                        movie_id=m_id,
                        movie_title=movie_title_ja,
                        screenings=screenings,
                        movie_title_en=movie_title_en if movie_title_en else None,
                    )
                )

        movies.sort(
            key=lambda m: (
                m.screenings[0].start_time if m.screenings else "99:99",
                m.movie_title.lower(),
            )
        )
        return movies
