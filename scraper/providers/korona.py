import concurrent.futures
from datetime import date, datetime, timezone
import json
from typing import Any, Callable, Dict, List, Optional
import urllib.error
import urllib.request

from ..models import MovieSchedule, Screening, SeatStatus
from ..sanitizer import UnsafeUrlError, build_safe_url, sanitize_identifier
from .aeon import JST, determine_seat_status, match_screen_facility
from .base import BaseCinemaProvider
from .html_utils import clean_text, extract_special_tags, normalize_screen_name


def _parse_utc_iso(iso_str: str) -> Optional[datetime]:
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        dt = datetime.fromisoformat(iso_str.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def determine_korona_seat_status(
    ev: Dict[str, Any],
    now_utc: Optional[datetime] = None,
) -> SeatStatus:
    """コロナワールド (SmartTheater形式) のイベント情報から座席空き状況を判定する。"""
    now = now_utc or datetime.now(timezone.utc)
    offers = ev.get("offers") or {}

    valid_from = _parse_utc_iso(
        offers.get("validFrom") or offers.get("availabilityStarts") or ""
    )
    if valid_from and now < valid_from:
        return SeatStatus.UNSOLD

    valid_through = _parse_utc_iso(offers.get("validThrough") or "")
    if valid_through and now > valid_through:
        return SeatStatus.UNSOLD

    rem_cap = _coerce_optional_int(ev.get("remainingAttendeeCapacity"))
    max_cap = _coerce_optional_int(ev.get("maximumAttendeeCapacity"))
    return determine_seat_status(rem_cap, max_cap)


def normalize_korona_screen_name(raw_name: str) -> str:
    """コロナワールドのスクリーン名を正規化する。"""
    if not raw_name or not str(raw_name).strip():
        return "スクリーン未定"
    cleaned = normalize_screen_name(raw_name)
    return "スクリーン未定" if cleaned == "シアター未定" else (cleaned or "スクリーン未定")


def parse_korona_work_schedule(
    work_json: Dict[str, Any],
    theater_info: Dict[str, Any],
    booking_builder: Callable[[str], str],
    info_url: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> Dict[str, MovieSchedule]:
    """
    コロナワールドの 1作品×1日分 JSON ({HHMM: {scrCode: event_obj}}) を解析し、
    movie_id ごとの MovieSchedule マップを返す。
    """
    fac_screens = (theater_info.get("facility") or {}).get("screens")
    movies_by_id: Dict[str, MovieSchedule] = {}
    seen_event_keys: Dict[str, set] = {}

    if not isinstance(work_json, dict):
        return movies_by_id

    for _hhmm, screen_map in work_json.items():
        if not isinstance(screen_map, dict):
            continue
        for scr_code, ev in screen_map.items():
            if not isinstance(ev, dict):
                continue

            name_obj = ev.get("name") or {}
            super_ev = ev.get("superEvent") or {}
            super_name_obj = super_ev.get("name") or {}
            work_perf = super_ev.get("workPerformed") or ev.get("workPerformed") or {}

            title = clean_text(
                name_obj.get("ja") or super_name_obj.get("ja") or ""
            ) or "名称未設定"
            title_en = clean_text(
                name_obj.get("en") or super_name_obj.get("en") or ""
            ) or None
            movie_id = str(
                super_ev.get("id")
                or work_perf.get("identifier")
                or title
            )

            start_dt = _parse_utc_iso(ev.get("startDate") or "")
            end_dt = _parse_utc_iso(ev.get("endDate") or "")
            start_time = start_dt.astimezone(JST).strftime("%H:%M") if start_dt else "--:--"
            end_time = end_dt.astimezone(JST).strftime("%H:%M") if end_dt else "--:--"

            loc = ev.get("location") or {}
            raw_screen = ((loc.get("name") or {}).get("ja")) or str(scr_code)
            screen_name = normalize_korona_screen_name(raw_screen)

            screen_fac = match_screen_facility(screen_name, fac_screens)
            features = list(screen_fac.get("features", [])) if screen_fac else []
            desc_ja = (super_ev.get("description") or {}).get("ja") or ""
            tags = extract_special_tags(title, screen_name, desc_ja, *features)

            seat_status = determine_korona_seat_status(ev, now_utc=now_utc)
            raw_event_id = str(
                ev.get("id")
                or (ev.get("offers") or {}).get("itemOffered", {}).get("id")
                or ""
            ).strip()

            booking_url = ""
            if raw_event_id and seat_status not in (SeatStatus.FULL, SeatStatus.UNSOLD):
                try:
                    booking_url = booking_builder(raw_event_id)
                except UnsafeUrlError:
                    booking_url = ""

            if movie_id not in movies_by_id:
                movies_by_id[movie_id] = MovieSchedule(
                    movie_id=movie_id,
                    movie_title=title,
                    screenings=[],
                    movie_title_en=title_en,
                    info_url=info_url,
                )
                seen_event_keys[movie_id] = set()

            dedup_key = raw_event_id or f"{screen_name}|{start_time}|{end_time}"
            if dedup_key in seen_event_keys[movie_id]:
                continue
            seen_event_keys[movie_id].add(dedup_key)

            movies_by_id[movie_id].screenings.append(
                Screening(
                    event_id=raw_event_id,
                    screen_name=screen_name,
                    start_time=start_time,
                    end_time=end_time,
                    seat_status=seat_status,
                    booking_url=booking_url,
                    tags=tags,
                )
            )

    return movies_by_id


class KoronaCinemaProvider(BaseCinemaProvider):
    """コロナワールド (Korona World) スケジュールプロバイダ"""

    CHAIN_ID: str = "korona"
    BASE_SCHEDULE_URL: str = "https://cinema.korona.co.jp/schedule/data"
    BASE_BOOKING_URL: str = "https://login.member.korona.co.jp/purchase/guest"

    def __init__(self, timeout: int = 15, max_workers: int = 8):
        super().__init__(timeout=timeout)
        self.max_workers = max_workers

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

    def build_movie_info_url(
        self,
        theater_id: str,
        theater_info: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        safe_theater = sanitize_identifier(theater_id)
        official_url = (theater_info or {}).get("official_url")
        target = official_url or f"https://cinema.korona.co.jp/theaters/{safe_theater}/"
        try:
            return build_safe_url(target)
        except UnsafeUrlError:
            return None

    def _build_headers(self, safe_theater: str) -> Dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://cinema.korona.co.jp/theaters/{safe_theater}/",
            "Accept": "application/json, text/plain, */*",
        }

    def _fetch_schedule_index(self, safe_theater: str) -> Dict[str, Any]:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        url = f"{self.BASE_SCHEDULE_URL}/schedule.json?v={ts}"
        req = urllib.request.Request(url, headers=self._build_headers(safe_theater))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            code, reason = e.code, e.reason
            e.close()
            if code in (403, 404):
                raise RuntimeError(
                    f"コロナワールドのスケジュールインデックスが見つかりませんでした (HTTP {code})。"
                ) from e
            raise RuntimeError(f"HTTPエラーが発生しました: {code} {reason}") from e
        except Exception as e:
            raise RuntimeError(f"スケジュールインデックスの取得に失敗しました: {e}") from e

    def _fetch_work_schedule(
        self,
        work_id: str,
        branch_code: str,
        date_str: str,
        safe_theater: str,
        ts: str,
    ) -> Optional[Dict[str, Any]]:
        safe_work = sanitize_identifier(work_id)
        safe_branch = sanitize_identifier(branch_code)
        safe_date = sanitize_identifier(date_str)
        url = f"{self.BASE_SCHEDULE_URL}/{safe_work}/{safe_branch}/{safe_date}.json?v={ts}"
        req = urllib.request.Request(url, headers=self._build_headers(safe_theater))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content = resp.read().decode("utf-8").strip()
                return json.loads(content) if content else None
        except urllib.error.HTTPError as e:
            code = e.code
            e.close()
            if code == 404:
                return None
            raise RuntimeError(f"作品スケジュール取得HTTPエラー ({safe_work}): {code}") from e

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        if safe_theater not in self._load_theaters_master():
            raise RuntimeError(
                f"劇場コード '{safe_theater}' はコロナワールド劇場マスタに登録されていません。"
            )
        theater_info = self.get_theater_info(safe_theater)
        raw_code = str(theater_info.get("code") or "").strip()
        if not raw_code:
            raise RuntimeError(
                f"劇場コード '{safe_theater}' に対応する branchCode (code) が劇場マスタにありません。"
            )
        branch_code = sanitize_identifier(raw_code)
        date_str = target_date.strftime("%Y%m%d")

        index_data = self._fetch_schedule_index(safe_theater)
        work_ids: List[str] = []
        if isinstance(index_data, dict):
            for work_id, branch_map in index_data.items():
                if not isinstance(branch_map, dict):
                    continue
                dates_map = branch_map.get(branch_code)
                if isinstance(dates_map, dict) and date_str in dates_map:
                    work_ids.append(str(work_id))

        if not work_ids:
            return []

        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        info_url = self.build_movie_info_url(safe_theater, theater_info)

        def booking_builder(event_id: str) -> str:
            return self.build_booking_url(safe_theater, event_id)

        merged_movies: Dict[str, MovieSchedule] = {}
        seen_events: Dict[str, set] = {}
        workers = min(self.max_workers, len(work_ids))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            future_map = {
                executor.submit(
                    self._fetch_work_schedule,
                    wid,
                    branch_code,
                    date_str,
                    safe_theater,
                    ts,
                ): wid
                for wid in work_ids
            }
            for future in concurrent.futures.as_completed(future_map):
                work_json = future.result()
                if not work_json:
                    continue
                parsed_map = parse_korona_work_schedule(
                    work_json=work_json,
                    theater_info=theater_info,
                    booking_builder=booking_builder,
                    info_url=info_url,
                )
                for mid, m_sched in parsed_map.items():
                    if mid not in merged_movies:
                        merged_movies[mid] = m_sched
                        seen_events[mid] = {
                            s.event_id or f"{s.screen_name}|{s.start_time}|{s.end_time}"
                            for s in m_sched.screenings
                        }
                    else:
                        for sc in m_sched.screenings:
                            key = sc.event_id or f"{sc.screen_name}|{sc.start_time}|{sc.end_time}"
                            if key not in seen_events[mid]:
                                seen_events[mid].add(key)
                                merged_movies[mid].screenings.append(sc)

        movies = [m for m in merged_movies.values() if m.screenings]
        for m in movies:
            m.screenings.sort(key=lambda s: s.start_time)
        movies.sort(
            key=lambda m: (
                m.screenings[0].start_time if m.screenings else "99:99",
                m.movie_title.lower(),
            )
        )
        return movies
