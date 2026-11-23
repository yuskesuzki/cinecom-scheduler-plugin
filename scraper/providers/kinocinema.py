from datetime import date
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
from .html_utils import (
    clean_text,
    extract_balanced_elements,
    extract_special_tags,
    normalize_screen_name,
    pad_hhmm,
)


_SCHEDULE_ITEM_RE = re.compile(
    r'<div\b[^>]*class="[^"]*\bschedule__item\b[^"]*"[^>]*>',
    re.I,
)
_MOVIE_BOX_RE = re.compile(
    r'<div\b[^>]*class="[^"]*\bschedule__movie\b[^"]*"[^>]*>',
    re.I,
)
_SCREEN_BOX_RE = re.compile(
    r'<div\b[^>]*class="[^"]*\bschedule__screen\b[^"]*"[^>]*>',
    re.I,
)
_BTN_LI_RE = re.compile(
    r'<li\b[^>]*class="([^"]*\bschedule__btn\b[^"]*)"[^>]*>(.*?)</li>',
    re.S | re.I,
)


def resolve_kinocinema_dates(
    md_list: List[Tuple[int, int]],
    reference_date: date,
) -> List[Optional[date]]:
    """キノシネマの日付ボタン ((month, day), ...) を年末年始跨ぎを含めて date 配列へ復元する。"""
    if not md_list:
        return []

    first_month = md_list[0][0]
    current_year = reference_date.year
    if reference_date.month == 12 and first_month == 1:
        current_year += 1
    elif reference_date.month == 1 and first_month == 12:
        current_year -= 1

    resolved: List[Optional[date]] = []
    prev_month: Optional[int] = None
    for month, day in md_list:
        if prev_month is not None and month < prev_month:
            current_year += 1
        prev_month = month
        try:
            resolved.append(date(current_year, month, day))
        except ValueError:
            resolved.append(None)
    return resolved


def map_kinocinema_seat_status(btn_classes: str) -> Tuple[SeatStatus, bool]:
    """キノシネマの schedule__btn クラス文字列から (SeatStatus, ネット購入可否) を判定する。"""
    tokens = set(str(btn_classes or "").lower().split())
    if "-available" in tokens:
        return SeatStatus.AVAILABLE, True
    if "-few" in tokens:
        return SeatStatus.FEW, True
    if "-sold" in tokens:
        return SeatStatus.FULL, False
    if "-offline" in tokens:
        return SeatStatus.AVAILABLE, False
    if "-past" in tokens:
        return SeatStatus.UNSOLD, False
    return SeatStatus.UNKNOWN, False


def normalize_kinocinema_screen_name(raw_name: str) -> str:
    """キノシネマのスクリーン名から座席数<span>等を除去して統一表記へ正規化する。"""
    cleaned_html = re.sub(r"<span\b[^>]*>.*?</span>", " ", str(raw_name or ""), flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", cleaned_html)
    text = unicodedata.normalize("NFKC", text)
    normalized = normalize_screen_name(text)
    if re.fullmatch(r"THEATER\s+0*(\d+)", normalized, re.I):
        num = int(re.search(r"\d+", normalized).group(0))
        return f"THEATER {num}"
    return normalized


def validate_kinocinema_booking_url(raw_url: str) -> str:
    """キノシネマの予約URL (https://app.eigaland.com/...) を検証・正規化して返す。"""
    cleaned = str(raw_url or "").strip()
    if not cleaned:
        return ""
    try:
        parsed = urlparse(cleaned)
        if parsed.scheme != "https" or parsed.hostname != "app.eigaland.com":
            return ""
        base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        query_items = dict(parse_qsl(parsed.query, keep_blank_values=False)) if parsed.query else None
        return build_safe_url(base_url, query_params=query_items)
    except (ValueError, UnsafeUrlError):
        return ""


def _extract_day_tab_md_list(html: str) -> List[Tuple[int, int]]:
    md_list: List[Tuple[int, int]] = []
    for btn_html in re.findall(
        r'<li\b[^>]*class="[^"]*\bschedule__day-btn\b[^"]*"[^>]*>(.*?)</li>',
        html,
        re.S | re.I,
    ):
        txt = clean_text(re.sub(r"<[^>]+>", "", btn_html))
        m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", txt)
        if m:
            md_list.append((int(m.group(1)), int(m.group(2))))
    return md_list


def parse_kinocinema_schedule_html(
    html: str,
    target_date: date,
    theater_id: str,
    theater_info: Optional[Dict[str, Any]] = None,
    reference_date: Optional[date] = None,
) -> List[MovieSchedule]:
    """キノシネマの劇場トップHTMLから対象日の映画スケジュールを抽出する。"""
    if not html:
        return []

    safe_theater = sanitize_identifier(theater_id)
    info = theater_info or {}
    fac_screens = (info.get("facility") or {}).get("screens")

    md_list = _extract_day_tab_md_list(html)
    ref = reference_date or date.today()
    resolved_dates = resolve_kinocinema_dates(md_list, ref)

    target_idx: Optional[int] = None
    for idx, d in enumerate(resolved_dates):
        if d == target_date:
            target_idx = idx
            break
    if target_idx is None:
        return []

    day_containers = extract_balanced_elements(html, "div", _SCHEDULE_ITEM_RE)
    if target_idx >= len(day_containers):
        return []

    _container_attr, day_html = day_containers[target_idx]
    date_compact = target_date.strftime("%Y%m%d")

    movies: List[MovieSchedule] = []
    movie_boxes = extract_balanced_elements(day_html, "div", _MOVIE_BOX_RE)

    for _mb_attr, mb_html in movie_boxes:
        h4_m = re.search(
            r'<h4\b[^>]*class="[^"]*\bschedule__title\b[^"]*"[^>]*>(.*?)</h4>',
            mb_html,
            re.S | re.I,
        )
        if not h4_m:
            continue
        h4_inner = h4_m.group(1)

        movie_id = f"{safe_theater}_m{len(movies) + 1}"
        info_url: Optional[str] = None
        a_m = re.search(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', h4_inner, re.S | re.I)
        if a_m:
            href = a_m.group(1).strip()
            title = clean_text(re.sub(r"<[^>]+>", " ", a_m.group(2)))
            id_m = re.search(r"/movie-detail/(\d+)", href)
            if id_m:
                movie_id = id_m.group(1)
            full_info = href if href.startswith("https://") else f"https://kinocinema.jp{href}"
            try:
                info_url = build_safe_url(full_info)
            except UnsafeUrlError:
                info_url = None
        else:
            title_clean_html = re.sub(
                r'<span\b[^>]*class="[^"]*\bschedule__icon\b[^"]*"[^>]*>.*?</span>',
                " ",
                h4_inner,
                flags=re.S | re.I,
            )
            title = clean_text(re.sub(r"<[^>]+>", " ", title_clean_html))

        if not title:
            continue
        if not info_url:
            try:
                info_url = build_safe_url(info.get("official_url") or f"https://kinocinema.jp/{safe_theater}/")
            except UnsafeUrlError:
                info_url = None

        screenings: List[Screening] = []
        screen_boxes = extract_balanced_elements(mb_html, "div", _SCREEN_BOX_RE)

        for _sb_attr, sb_html in screen_boxes:
            h5_m = re.search(
                r'<h5\b[^>]*class="[^"]*\bschedule__screen-name\b[^"]*"[^>]*>(.*?)</h5>',
                sb_html,
                re.S | re.I,
            )
            screen_name = normalize_kinocinema_screen_name(h5_m.group(1)) if h5_m else "シアター未定"
            scr_fac = match_screen_facility(screen_name, fac_screens)
            features = list(scr_fac.get("features", [])) if scr_fac else []
            tags = extract_special_tags(title, screen_name, *features)

            for btn_classes, btn_body in _BTN_LI_RE.findall(sb_html):
                if "-empty" in btn_classes.lower().split():
                    continue
                st_m = re.search(
                    r'<em\b[^>]*class="[^"]*\bschedule__start-time\b[^"]*"[^>]*>(.*?)</em>',
                    btn_body,
                    re.S | re.I,
                )
                if not st_m:
                    continue
                start_raw = clean_text(re.sub(r"<[^>]+>", " ", st_m.group(1)))
                if not re.match(r"^\d{1,2}:\d{2}$", start_raw):
                    continue
                start_time = pad_hhmm(start_raw)

                en_m = re.search(
                    r'<span\b[^>]*class="[^"]*\bschedule__end-time\b[^"]*"[^>]*>(.*?)</span>',
                    btn_body,
                    re.S | re.I,
                )
                end_time = "--:--"
                if en_m:
                    end_raw = clean_text(re.sub(r"<[^>]+>", " ", en_m.group(1))).lstrip("-~～〜 ")
                    if re.match(r"^\d{1,2}:\d{2}$", end_raw):
                        end_time = pad_hhmm(end_raw)

                seat_status, can_book = map_kinocinema_seat_status(btn_classes)
                booking_url = ""
                ev_id = f"{movie_id}_{date_compact}_{start_time.replace(':', '')}_{screen_name}"
                link_m = re.search(r'<a\b[^>]*href="([^"]+)"', btn_body, re.I)
                if link_m:
                    raw_href = link_m.group(1).strip()
                    sid_m = re.search(r"scheduleId=([A-Za-z0-9_.-]+)", raw_href)
                    if sid_m:
                        ev_id = sid_m.group(1)
                    if can_book:
                        booking_url = validate_kinocinema_booking_url(raw_href)

                screenings.append(
                    Screening(
                        event_id=ev_id,
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
        movies.append(
            MovieSchedule(
                movie_id=str(movie_id),
                movie_title=title,
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


class KinoCinemaProvider(BaseCinemaProvider):
    """キノシネマ (kino cinéma) スケジュールプロバイダ"""

    CHAIN_ID: str = "kinocinema"
    BASE_BOOKING_URL: str = "https://app.eigaland.com/booking"

    def __init__(self, timeout: int = 15):
        super().__init__(timeout=timeout)

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        safe_theater = sanitize_identifier(theater_id)
        return build_safe_url(f"https://kinocinema.jp/{safe_theater}/")

    def _fetch_schedule_html(self, safe_theater: str) -> str:
        url = build_safe_url(f"https://kinocinema.jp/{safe_theater}/")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            code, reason = e.code, e.reason
            e.close()
            if code in (403, 404):
                raise RuntimeError(
                    f"キノシネマ '{safe_theater}' のスケジュールが見つかりませんでした (HTTP {code})。"
                ) from e
            raise RuntimeError(f"HTTPエラーが発生しました: {code} {reason}") from e
        except Exception as e:
            raise RuntimeError(f"スケジュールデータの取得に失敗しました: {e}") from e

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        if safe_theater not in self._load_theaters_master():
            raise RuntimeError(
                f"劇場コード '{safe_theater}' はキノシネマ劇場マスタに登録されていません。"
            )
        theater_info = self.get_theater_info(safe_theater)
        html = self._fetch_schedule_html(safe_theater)
        return parse_kinocinema_schedule_html(
            html=html,
            target_date=target_date,
            theater_id=safe_theater,
            theater_info=theater_info,
        )
