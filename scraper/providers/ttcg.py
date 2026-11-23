from datetime import date
import json
import re
from typing import Any, Dict, List, Optional, Tuple
import unicodedata
import urllib.error
from urllib.parse import parse_qsl, urlparse, urlunparse
import urllib.request

from ..models import MovieSchedule, Screening, SeatStatus
from ..sanitizer import UnsafeUrlError, build_safe_url, sanitize_identifier
from .aeon import match_screen_facility
from .base import BaseCinemaProvider
from .html_utils import clean_text, extract_special_tags, pad_hhmm


TTCG_STATUS_MAP: Dict[str, Tuple[SeatStatus, bool]] = {
    "0": (SeatStatus.AVAILABLE, True),   # ○ 購入
    "1": (SeatStatus.AVAILABLE, False),  # ○ 窓口
    "2": (SeatStatus.FEW, True),         # △ 購入
    "4": (SeatStatus.FEW, False),        # △ 窓口
    "5": (SeatStatus.FULL, False),       # × 満席
    "6": (SeatStatus.UNSOLD, False),     # 受付終了 / 未販売
}


def map_ttcg_seat_status(raw_code: Any) -> Tuple[SeatStatus, bool]:
    """TTCG の available ステータスコードを (SeatStatus, ネット予約可否) に変換する。"""
    code = str(raw_code).strip() if raw_code is not None else ""
    return TTCG_STATUS_MAP.get(code, (SeatStatus.UNKNOWN, False))


def normalize_ttcg_screen_name(raw_name: str) -> str:
    """TTCG の半角カナ・odessa付き・座席券等のスクリーン名を統一形式へ正規化する。"""
    text = unicodedata.normalize("NFKC", str(raw_name or ""))
    text = re.sub(r"odessa", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*座席表\s*$", "", text)
    text = clean_text(text)

    if not text or text == "座席券":
        return "シアター1"
    if text == "シアター":
        return "シアター1"
    if text == "シネマ":
        return "シネマ1"

    m = re.fullmatch(r"(シアター|シネマ|キネカ)\s*(\d+)", text)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return text


def _format_ttcg_time(hour_val: Any, min_val: Any, fallback_hhmm: Any = None) -> str:
    try:
        if hour_val is not None and min_val is not None:
            hh = int(str(hour_val).strip())
            mm = int(str(min_val).strip())
            return pad_hhmm(f"{hh:02d}:{mm:02d}")
    except ValueError:
        pass
    fb = str(fallback_hhmm or "").strip()
    if len(fb) == 4 and fb.isdigit():
        return pad_hhmm(f"{fb[:2]}:{fb[2:]}")
    return "--:--"


def _extract_ttcg_tags(*sources: Optional[str]) -> List[str]:
    tags = extract_special_tags(*sources)
    combined = " ".join(s for s in sources if s).lower()
    if "odessa" in combined and "odessa" not in tags:
        tags.append("odessa")
    return tags


def validate_ttcg_booking_url(raw_url: str, ticket_host: Optional[str] = None) -> str:
    """TTCG JSON内の予約URLを検証し、安全なHTTPS URLのみ返す。"""
    cleaned = str(raw_url or "").strip()
    if not cleaned:
        return ""
    try:
        parsed = urlparse(cleaned)
        if parsed.scheme != "https":
            return ""
        if ticket_host and parsed.hostname != ticket_host:
            return ""
        base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True)) if parsed.query else None
        return build_safe_url(base_url, query_params=query_params)
    except (ValueError, UnsafeUrlError):
        return ""


def _resolve_movie_meta(movie_entries: Any, target_date: date) -> Dict[str, Any]:
    if not isinstance(movie_entries, list) or not movie_entries:
        return {}
    for entry in movie_entries:
        if not isinstance(entry, dict):
            continue
        try:
            y = int(entry.get("date_year", -1))
            m = int(entry.get("date_month", -1))
            d = int(entry.get("date_day", -1))
            if (y, m, d) == (target_date.year, target_date.month, target_date.day):
                return entry
        except (TypeError, ValueError):
            continue
    return movie_entries[0] if isinstance(movie_entries[0], dict) else {}


def parse_ttcg_schedule_json(
    raw_data: Dict[str, Any],
    target_date: date,
    theater_id: str,
    theater_info: Optional[Dict[str, Any]] = None,
) -> List[MovieSchedule]:
    """TTCG JSON (/data/{code}.js) から対象日の映画スケジュールを抽出する。"""
    if not isinstance(raw_data, dict):
        return []

    dates_list = raw_data.get("dates") or []
    target_movie_codes: Optional[List[str]] = None
    for d_entry in dates_list:
        if not isinstance(d_entry, dict):
            continue
        try:
            y = int(d_entry.get("date_year", -1))
            m = int(d_entry.get("date_month", -1))
            d = int(d_entry.get("date_day", -1))
            if (y, m, d) == (target_date.year, target_date.month, target_date.day):
                target_movie_codes = [str(mc) for mc in (d_entry.get("movie") or []) if mc]
                break
        except (TypeError, ValueError):
            continue

    if not target_movie_codes:
        return []

    safe_theater = sanitize_identifier(theater_id)
    date_str = target_date.strftime("%Y-%m-%d")
    info = theater_info or {}
    fac_screens = (info.get("facility") or {}).get("screens")
    ticket_host = info.get("ticket_host")

    movies_dict = raw_data.get("movies") or {}
    screens_dict = raw_data.get("screens") or {}

    schedules: List[MovieSchedule] = []

    for mc in target_movie_codes:
        meta = _resolve_movie_meta(movies_dict.get(mc), target_date)
        title = clean_text(meta.get("name") or meta.get("cname") or "") or "名称未設定"
        title_en = clean_text(meta.get("ename") or "") or None
        movie_code = str(meta.get("movie_code") or mc).strip()

        try:
            safe_mc = sanitize_identifier(movie_code)
            info_url = build_safe_url(f"https://ttcg.jp/{safe_theater}/movie/{safe_mc}.html")
        except UnsafeUrlError:
            try:
                info_url = build_safe_url(info.get("official_url") or f"https://ttcg.jp/{safe_theater}/")
            except UnsafeUrlError:
                info_url = None

        scr_blocks = screens_dict.get(f"{mc}-{date_str}") or []
        screenings: List[Screening] = []

        for scr_block in scr_blocks:
            if not isinstance(scr_block, dict):
                continue
            raw_scr_name = str(scr_block.get("name") or "")
            screen_name = normalize_ttcg_screen_name(raw_scr_name)
            screen_fac = match_screen_facility(screen_name, fac_screens)
            features = list(screen_fac.get("features", [])) if screen_fac else []

            for slot in scr_block.get("time") or []:
                if not isinstance(slot, dict):
                    continue
                start_time = _format_ttcg_time(
                    slot.get("start_time_hour"),
                    slot.get("start_time_minute"),
                    slot.get("start_time"),
                )
                end_time = _format_ttcg_time(
                    slot.get("end_time_hour"),
                    slot.get("end_time_minute"),
                    slot.get("end_time"),
                )
                seat_status, can_book = map_ttcg_seat_status(slot.get("available"))
                booking_url = (
                    validate_ttcg_booking_url(slot.get("url") or "", ticket_host=ticket_host)
                    if can_book
                    else ""
                )
                tags = _extract_ttcg_tags(
                    title,
                    raw_scr_name,
                    screen_name,
                    meta.get("comment"),
                    *features,
                )
                event_id = f"{movie_code}_{target_date.strftime('%Y%m%d')}_{start_time.replace(':', '')}_{screen_name}"

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

        if not screenings:
            continue

        screenings.sort(key=lambda s: s.start_time)
        schedules.append(
            MovieSchedule(
                movie_id=movie_code,
                movie_title=title,
                screenings=screenings,
                movie_title_en=title_en,
                info_url=info_url,
            )
        )

    schedules.sort(
        key=lambda m: (
            m.screenings[0].start_time if m.screenings else "99:99",
            m.movie_title.lower(),
        )
    )
    return schedules


class TtcgCinemaProvider(BaseCinemaProvider):
    """テアトルシネマグループ (TTCG) スケジュールプロバイダ"""

    CHAIN_ID: str = "ttcg"
    BASE_BOOKING_URL: str = "https://ttcg.jp/"

    def __init__(self, timeout: int = 15):
        super().__init__(timeout=timeout)

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        safe_theater = sanitize_identifier(theater_id)
        return build_safe_url(f"https://ttcg.jp/{safe_theater}/")

    def _fetch_schedule_raw(self, safe_data_code: str, safe_theater: str) -> Dict[str, Any]:
        url = f"https://ttcg.jp/data/{safe_data_code}.js"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://ttcg.jp/{safe_theater}/",
            "Accept": "application/json, text/plain, */*",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            code, reason = e.code, e.reason
            e.close()
            if code in (403, 404):
                raise RuntimeError(
                    f"劇場コード '{safe_theater}' (data: {safe_data_code}) のスケジュールが見つかりませんでした (HTTP {code})。"
                ) from e
            raise RuntimeError(f"HTTPエラーが発生しました: {code} {reason}") from e
        except Exception as e:
            raise RuntimeError(f"スケジュールデータの取得に失敗しました: {e}") from e

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        if safe_theater not in self._load_theaters_master():
            raise RuntimeError(
                f"劇場コード '{safe_theater}' はテアトルシネマグループ劇場マスタに登録されていません。"
            )
        theater_info = self.get_theater_info(safe_theater)
        data_code = str(theater_info.get("data_code") or safe_theater).strip()
        safe_data_code = sanitize_identifier(data_code)
        raw_data = self._fetch_schedule_raw(safe_data_code, safe_theater)
        return parse_ttcg_schedule_json(
            raw_data=raw_data,
            target_date=target_date,
            theater_id=safe_theater,
            theater_info=theater_info,
        )
