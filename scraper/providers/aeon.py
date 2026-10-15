from datetime import date, datetime, timezone, timedelta
import json
import re
from typing import List, Dict, Any, Optional
import urllib.parse
import urllib.request

from ..models import MovieSchedule, Screening, SeatStatus
from ..sanitizer import sanitize_identifier, build_safe_url, UnsafeUrlError
from .base import BaseCinemaProvider

JST = timezone(timedelta(hours=9))
SPECIAL_BADGES = ["IMAX", "4DX", "VIVE AUDIO", "Dolby Atmos", "THX"]


def detect_special_badges(
    features: List[str],
    screen_name: str,
    extra_texts: Optional[List[str]] = None,
) -> List[str]:
    badges = []
    targets = list(features) + [screen_name] + (extra_texts or [])
    for badge in SPECIAL_BADGES:
        b_norm = badge.upper().replace(" ", "")
        for t in targets:
            if not t:
                continue
            t_norm = t.upper().replace(" ", "").replace("ATOMOS", "ATMOS")
            if b_norm in t_norm:
                if badge not in badges:
                    badges.append(badge)
                break
    return badges


def match_screen_facility(
    screen_str: str, screens: Optional[List[Dict[str, Any]]]
) -> Optional[Dict[str, Any]]:
    if not screens:
        return None
    for s in screens:
        if s.get("name") == screen_str:
            return s
    num_m = re.search(r"\d+", screen_str)
    if num_m:
        t_num = num_m.group(0)
        for s in screens:
            s_num = re.search(r"\d+", s.get("name", ""))
            if s_num and s_num.group(0) == t_num:
                return s
    for s in screens:
        s_name = s.get("name", "")
        if s_name and (s_name in screen_str or screen_str in s_name):
            return s
    return None


def determine_seat_status(rem_capacity: Optional[int], max_capacity: Optional[int]) -> SeatStatus:
    if rem_capacity is None:
        return SeatStatus.UNKNOWN
    if rem_capacity == 0:
        return SeatStatus.FULL
    if max_capacity and max_capacity > 0:
        ratio = rem_capacity / max_capacity
        if ratio <= 0.15 or rem_capacity <= 15:
            return SeatStatus.FEW
    elif rem_capacity <= 15:
        return SeatStatus.FEW
    return SeatStatus.AVAILABLE


class AeonCinemaProvider(BaseCinemaProvider):
    CHAIN_ID: str = "aeon"
    BASE_BOOKING_URL: str = "https://login.watatheatre.aeoncinema.com/auth"

    def __init__(self, timeout: int = 15):
        super().__init__(timeout=timeout)

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        safe_event = sanitize_identifier(event_id)
        params = {"eventId": safe_event}
        if extra_params:
            for k, v in extra_params.items():
                params[sanitize_identifier(k)] = str(v)
        return build_safe_url(self.BASE_BOOKING_URL, query_params=params)

    def _fetch_schedule_raw(self, theater: str) -> Dict[str, Any]:
        safe_theater = sanitize_identifier(theater)
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        url = f"https://theater.aeoncinema.com/schedule/v2/data/{safe_theater}/schedule.json?v={now_str}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://theater.aeoncinema.com/theaters/{safe_theater}/",
            "Accept": "application/json, text/plain, */*",
        }

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content = resp.read().decode("utf-8")
                return json.loads(content)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise RuntimeError(
                    f"劇場コード '{safe_theater}' のスケジュールデータが見つかりませんでした (HTTP {e.code})。"
                ) from e
            raise RuntimeError(f"HTTPエラーが発生しました: {e.code} {e.reason}") from e
        except Exception as e:
            raise RuntimeError(f"スケジュールデータの取得に失敗しました: {e}") from e

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        date_str = target_date.strftime("%Y%m%d")

        theater_info = self.get_theater_info(safe_theater)
        fac_screens = theater_info.get("facility", {}).get("screens")

        raw_data = self._fetch_schedule_raw(safe_theater)
        day_schedules = raw_data.get(date_str)
        if not day_schedules:
            return []

        movies: List[MovieSchedule] = []

        for group_id, events in day_schedules.items():
            if not events:
                continue

            first_event = events[0]
            title = (
                first_event.get("name", {}).get("ja")
                or first_event.get("superEvent", {}).get("name", {}).get("ja")
                or "名称未設定"
            )
            movie_id = (
                first_event.get("superEvent", {}).get("id")
                or group_id
            )

            screenings: List[Screening] = []
            for ev in events:
                start_iso = ev.get("startDate", "")
                end_iso = ev.get("endDate", "")

                if start_iso:
                    start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(JST)
                    start_time = start_dt.strftime("%H:%M")
                else:
                    start_time = "--:--"

                if end_iso:
                    end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00")).astimezone(JST)
                    end_time = end_dt.strftime("%H:%M")
                else:
                    end_time = "--:--"

                screen_name = ev.get("location", {}).get("name", {}).get("ja", "スクリーン未定")

                screen_fac = match_screen_facility(screen_name, fac_screens)
                features = screen_fac.get("features", []) if screen_fac else []
                special_badges = detect_special_badges(
                    features, screen_name, extra_texts=[title]
                )

                max_capacity = ev.get("maximumAttendeeCapacity")
                rem_capacity = ev.get("remainingAttendeeCapacity")
                seat_status = determine_seat_status(rem_capacity, max_capacity)

                raw_event_id = ev.get("id") or ev.get("offers", {}).get("itemOffered", {}).get("id") or ""
                # 安全な booking_url の生成（イベントIDのサニタイズと安全なURLビルダーの強制）
                booking_url = ""
                if raw_event_id:
                    try:
                        booking_url = self.build_booking_url(safe_theater, str(raw_event_id))
                    except UnsafeUrlError:
                        booking_url = ""

                screenings.append(
                    Screening(
                        event_id=str(raw_event_id),
                        screen_name=screen_name,
                        start_time=start_time,
                        end_time=end_time,
                        seat_status=seat_status,
                        booking_url=booking_url,
                        tags=special_badges,
                    )
                )

            screenings.sort(key=lambda s: s.start_time)

            movies.append(
                MovieSchedule(
                    movie_id=str(movie_id),
                    movie_title=title,
                    screenings=screenings,
                )
            )

        movies.sort(
            key=lambda m: (
                m.screenings[0].start_time if m.screenings else "99:99",
                m.movie_title.lower(),
            )
        )
        return movies
