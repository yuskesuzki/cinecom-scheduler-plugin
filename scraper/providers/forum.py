from datetime import date
import re
from typing import Any, Dict, List, Optional, Tuple
import unicodedata
import urllib.error
import urllib.request

from ..models import MovieSchedule, Screening, SeatStatus
from ..sanitizer import UnsafeUrlError, build_safe_url, sanitize_identifier
from .aeon import match_screen_facility
from .base import BaseCinemaProvider
from .html_utils import (
    clean_text,
    extract_balanced_elements,
    extract_special_tags,
    pad_hhmm,
)


_MOVIE_SECTION_RE = re.compile(
    r'<section\b[^>]*class="[^"]*\boneday--movie-list\b[^"]*"[^>]*>',
    re.I,
)
_LI_OPEN_RE = re.compile(r"<li\b[^>]*>", re.I)


def normalize_forum_screen_name(raw_name: str) -> str:
    """フォーラムシネマネットワークのスクリーン名を正規化する。"""
    text = unicodedata.normalize("NFKC", str(raw_name or ""))
    text = clean_text(text)
    if not text:
        return "スクリーン未定"
    text = re.sub(r"^(フォーラム|ソラリス|シアター|スクリーン)\s*(\d+)$", r"\1\2", text)
    return text


def map_forum_seat_status(purchase_block_html: str) -> Tuple[SeatStatus, bool]:
    """フォーラムの purchase-block HTML から (SeatStatus, ネット購入可否) を判定する。"""
    html_str = str(purchase_block_html or "")
    if not html_str.strip():
        return SeatStatus.UNKNOWN, False

    a_m = re.search(r'<a\b[^>]*class="([^"]*)"[^>]*>(.*?)</a>', html_str, re.S | re.I)
    classes_str = (a_m.group(1) if a_m else html_str).lower()
    class_tokens = set(classes_str.split())
    text = clean_text(re.sub(r"<[^>]+>", " ", a_m.group(2) if a_m else html_str))

    if "vacancy" in class_tokens:
        return SeatStatus.AVAILABLE, True
    if "little" in class_tokens:
        return SeatStatus.FEW, True
    if "notsale" in class_tokens or "販売前" in text:
        return SeatStatus.UNSOLD, False
    if "soldout" in class_tokens:
        if "満席" in text or "完売" in text:
            return SeatStatus.FULL, False
        if "販売終了" in text:
            return SeatStatus.UNSOLD, False
        return SeatStatus.FULL, False

    return SeatStatus.UNKNOWN, False


def _build_forum_guest_booking_url(event_id: str) -> str:
    safe_event = sanitize_identifier(event_id)
    return build_safe_url(
        ForumCinemaProvider.BASE_BOOKING_URL,
        query_params={"eventId": safe_event},
    )


def parse_forum_schedule_html(
    html: str,
    target_date: date,
    theater_id: str,
    theater_info: Optional[Dict[str, Any]] = None,
) -> List[MovieSchedule]:
    """フォーラム /{site_slug}/by-date?date=... のHTMLから上映スケジュールを抽出する。"""
    if not html:
        return []

    safe_theater = sanitize_identifier(theater_id)
    info = theater_info or {}
    site_slug = sanitize_identifier(str(info.get("site_slug") or safe_theater))
    fac_screens = (info.get("facility") or {}).get("screens")
    date_compact = target_date.strftime("%Y%m%d")

    movie_sections = extract_balanced_elements(html, "section", _MOVIE_SECTION_RE)
    movies: List[MovieSchedule] = []

    for _sec_attr, sec_body in movie_sections:
        h2_m = re.search(
            r'<h2\b[^>]*class="[^"]*\boneday--movie-name\b[^"]*"[^>]*>(.*?)</h2>',
            sec_body,
            re.S | re.I,
        )
        if not h2_m:
            continue
        title = clean_text(re.sub(r"<[^>]+>", " ", h2_m.group(1)))
        if not title:
            continue

        movie_id = f"{safe_theater}_m{len(movies) + 1}"
        info_url: Optional[str] = None
        movie_link_m = re.search(
            r'<a\b[^>]*href="(https://forum-movie\.net/[A-Za-z0-9_.-]+/movie/(\d+)[^"]*)"',
            sec_body,
            re.I,
        )
        if movie_link_m:
            movie_id = movie_link_m.group(2)
            try:
                info_url = build_safe_url(movie_link_m.group(1).strip())
            except UnsafeUrlError:
                info_url = None
        if not info_url:
            try:
                info_url = build_safe_url(info.get("official_url") or f"https://forum-movie.net/{site_slug}")
            except UnsafeUrlError:
                info_url = None

        ul_m = re.search(
            r'<ul\b[^>]*class="[^"]*\btimetable\b[^"]*"[^>]*>(.*?)</ul>',
            sec_body,
            re.S | re.I,
        )
        if not ul_m:
            continue

        screenings: List[Screening] = []
        li_items = extract_balanced_elements(ul_m.group(1), "li", _LI_OPEN_RE)
        for _li_attr, li_body in li_items:
            start_m = re.search(
                r'<span\b[^>]*class="[^"]*\bstart-time\b[^"]*"[^>]*>(.*?)</span>',
                li_body,
                re.S | re.I,
            )
            if not start_m:
                continue
            start_raw = clean_text(re.sub(r"<[^>]+>", " ", start_m.group(1)))
            if not re.match(r"^\d{1,2}:\d{2}$", start_raw):
                continue
            start_time = pad_hhmm(start_raw)

            end_m = re.search(
                r'<span\b[^>]*class="[^"]*\bend-time\b[^"]*"[^>]*>(.*?)</span>',
                li_body,
                re.S | re.I,
            )
            end_time = "--:--"
            if end_m:
                end_raw = clean_text(re.sub(r"<[^>]+>", " ", end_m.group(1)))
                if re.match(r"^\d{1,2}:\d{2}$", end_raw):
                    end_time = pad_hhmm(end_raw)

            scr_m = re.search(
                r'<span\b[^>]*class="[^"]*\bmovie-info-theater\b[^"]*"[^>]*>(.*?)</span>',
                li_body,
                re.S | re.I,
            )
            raw_screen = clean_text(re.sub(r"<[^>]+>", " ", scr_m.group(1))) if scr_m else ""
            screen_name = normalize_forum_screen_name(raw_screen)

            pb_m = re.search(
                r'<span\b[^>]*class="[^"]*\bpurchase-block\b[^"]*"[^>]*>(.*?)</span>\s*(?:<div\b|$)',
                li_body,
                re.S | re.I,
            )
            pb_html = pb_m.group(1) if pb_m else li_body
            seat_status, can_book = map_forum_seat_status(pb_html)

            ev_m = re.search(
                r'(?:href="#dialog_|data-purchase-url="[^"]*eventId=|eventId=)([A-Za-z0-9_.-]+)',
                li_body,
                re.I,
            )
            raw_event_id = ev_m.group(1).strip() if ev_m else ""
            event_id = raw_event_id or f"{safe_theater}_{date_compact}_{start_time.replace(':', '')}_{screen_name}"

            booking_url = ""
            if can_book and raw_event_id:
                try:
                    booking_url = _build_forum_guest_booking_url(raw_event_id)
                except UnsafeUrlError:
                    booking_url = ""

            scr_fac = match_screen_facility(screen_name, fac_screens)
            features = list(scr_fac.get("features", [])) if scr_fac else []
            tags = extract_special_tags(title, raw_screen, screen_name, *features)

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


class ForumCinemaProvider(BaseCinemaProvider):
    """フォーラムシネマネットワーク (FORUM CINEMA NETWORK) スケジュールプロバイダ"""

    CHAIN_ID: str = "forum"
    BASE_BOOKING_URL: str = "https://login.member.forum-movie.net/purchase/guest"

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

    def _fetch_schedule_html(
        self,
        site_slug: str,
        target_date: date,
        forum_tid: Optional[str] = None,
    ) -> str:
        date_str = target_date.strftime("%Y-%m-%d")
        query_params: Dict[str, str] = {"date": date_str}
        if forum_tid:
            query_params["theater_id"] = sanitize_identifier(str(forum_tid))

        url = build_safe_url(
            f"https://forum-movie.net/{site_slug}/by-date",
            query_params=query_params,
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://forum-movie.net/{site_slug}",
            "Accept": "text/html, */*; q=0.01",
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
                    f"フォーラム '{site_slug}' のスケジュールが見つかりませんでした (HTTP {code})。"
                ) from e
            raise RuntimeError(f"HTTPエラーが発生しました: {code} {reason}") from e
        except Exception as e:
            raise RuntimeError(f"スケジュールデータの取得に失敗しました: {e}") from e

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        if safe_theater not in self._load_theaters_master():
            raise RuntimeError(
                f"劇場コード '{safe_theater}' はフォーラム劇場マスタに登録されていません。"
            )
        theater_info = self.get_theater_info(safe_theater)
        site_slug = sanitize_identifier(str(theater_info.get("site_slug") or safe_theater))
        forum_tid = theater_info.get("theater_id")
        html = self._fetch_schedule_html(
            site_slug=site_slug,
            target_date=target_date,
            forum_tid=str(forum_tid) if forum_tid else None,
        )
        return parse_forum_schedule_html(
            html=html,
            target_date=target_date,
            theater_id=safe_theater,
            theater_info=theater_info,
        )
