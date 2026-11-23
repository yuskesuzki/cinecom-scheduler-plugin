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
    pad_hhmm,
)


_TABLE_OPEN_RE = re.compile(r'<table\b[^>]*class="[^"]*\btable\b[^"]*"[^>]*>', re.I)


def normalize_uscinemas_screen_name(raw_name: str) -> str:
    """USシネマ・千葉劇場のスクリーン名を正規化する。"""
    text = unicodedata.normalize("NFKC", str(raw_name or ""))
    text = clean_text(text)
    if not text:
        return "シネマ未定"

    if re.fullmatch(r"0*(\d+)", text):
        return f"シネマ{int(text)}"

    m_cin = re.fullmatch(r"(?:CINEMA|シネマ)\s*0*(\d+)", text, re.I)
    if m_cin:
        return f"シネマ{int(m_cin.group(1))}"

    if text.upper() == "4DXシアター" or text.upper() == "4DX":
        return "4DX"

    return text


def map_uscinemas_seat_status(cell_html: str) -> Tuple[SeatStatus, bool]:
    """USシネマのアイコン/画像情報から (SeatStatus, ネット購入可否) を判定する。"""
    lower = str(cell_html or "").lower()
    if "icon_01.png" in lower or "web(1)" in lower:
        return SeatStatus.AVAILABLE, True
    if "icon_02.png" in lower or "web(2)" in lower:
        return SeatStatus.FEW, True
    if "icon_03.png" in lower or "web(3)" in lower:
        return SeatStatus.FULL, False
    if "icon_04.png" in lower or "web(4)" in lower:
        return SeatStatus.UNSOLD, False
    # 千葉劇場などオンライン予約アイコンがない場合は窓口上映として AVAILABLE / URLなし
    return SeatStatus.AVAILABLE, False


def validate_uscinemas_booking_url(raw_url: str) -> str:
    """USシネマの予約URL (https://cinema-ticket.jp/...) を検証して返す。"""
    cleaned = str(raw_url or "").strip()
    if not cleaned:
        return ""
    try:
        parsed = urlparse(cleaned)
        if parsed.scheme != "https" or parsed.hostname != "cinema-ticket.jp":
            return ""
        base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True)) if parsed.query else None
        return build_safe_url(base_url, query_params=query_params)
    except (ValueError, UnsafeUrlError):
        return ""


def _extract_uscinemas_tags(*sources: Optional[str]) -> List[str]:
    tags = extract_special_tags(*sources)
    combined = " ".join(s for s in sources if s).upper()
    if "ADMIX" in combined and "ADMIX" not in tags:
        tags.append("ADMIX")
    return tags


def parse_uscinemas_schedule_html(
    html: str,
    target_date: date,
    theater_id: str,
    theater_info: Optional[Dict[str, Any]] = None,
) -> List[MovieSchedule]:
    """USシネマ・千葉劇場の劇場カテゴリHTMLから対象日の映画スケジュールを抽出する。"""
    if not html:
        return []

    safe_theater = sanitize_identifier(theater_id)
    info = theater_info or {}
    fac_screens = (info.get("facility") or {}).get("screens")
    date_compact = target_date.strftime("%Y%m%d")

    try:
        info_url = build_safe_url(info.get("official_url") or f"https://uscinemas.jp/category/{safe_theater}/")
    except UnsafeUrlError:
        info_url = None

    tables = extract_balanced_elements(html, "table", _TABLE_OPEN_RE)
    movies: List[MovieSchedule] = []
    title_counts: Dict[str, int] = {}

    for _attr, table_body in tables:
        thead_m = re.search(r"<thead\b[^>]*>(.*?)</thead>", table_body, re.S | re.I)
        if not thead_m:
            continue
        title_m = re.search(
            r'<h4\b[^>]*class="[^"]*\bpull-left\b[^"]*"[^>]*>(.*?)</h4>',
            thead_m.group(1),
            re.S | re.I,
        )
        if not title_m:
            continue
        title = clean_text(re.sub(r"<[^>]+>", " ", title_m.group(1)))
        if not title:
            continue

        tbody_m = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", table_body, re.S | re.I)
        tbody_html = tbody_m.group(1) if tbody_m else table_body

        screenings: List[Screening] = []
        current_raw_screen = ""
        current_screen = "シネマ未定"

        for tr_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", tbody_html, re.S | re.I):
            tds = re.findall(r"<td\b([^>]*)>(.*?)</td>", tr_html, re.S | re.I)
            if not tds:
                continue

            for idx, (td_attr, td_body) in enumerate(tds):
                is_td_space = bool(re.search(r'\bclass="[^"]*\btd_space\b', td_attr, re.I))
                if idx == 0 and not is_td_space:
                    scr_m = re.search(
                        r'<h3\b[^>]*class="[^"]*\bscheduleh3\b[^"]*"[^>]*>(.*?)</h3>',
                        td_body,
                        re.S | re.I,
                    )
                    if scr_m:
                        raw_scr_txt = clean_text(re.sub(r"<[^>]+>", " ", scr_m.group(1)))
                        if raw_scr_txt:
                            current_raw_screen = raw_scr_txt
                            current_screen = normalize_uscinemas_screen_name(raw_scr_txt)
                    continue

                if not td_body.strip():
                    continue

                start_m = re.search(
                    r'<h3\b[^>]*class="[^"]*\bscheduleh3\b[^"]*"[^>]*>(.*?)</h3>',
                    td_body,
                    re.S | re.I,
                )
                if not start_m:
                    continue
                start_raw = clean_text(re.sub(r"<[^>]+>", " ", start_m.group(1)))
                if not re.match(r"^\d{1,2}:\d{2}$", start_raw):
                    continue
                start_time = pad_hhmm(start_raw)

                end_m = re.search(
                    r'<span\b[^>]*class="[^"]*\bfinish-time-show\b[^"]*"[^>]*>(.*?)</span>',
                    td_body,
                    re.S | re.I,
                )
                end_time = "--:--"
                if end_m:
                    end_raw = clean_text(re.sub(r"<[^>]+>", " ", end_m.group(1))).lstrip("~～〜- ")
                    if re.match(r"^\d{1,2}:\d{2}$", end_raw):
                        end_time = pad_hhmm(end_raw)

                seat_status, can_book = map_uscinemas_seat_status(td_body)
                booking_url = ""
                ev_suffix = f"{date_compact}_{start_time.replace(':', '')}_{current_screen}"
                href_m = re.search(
                    r'<a\b[^>]*href="([^"]*cinema-ticket\.jp[^"]*)"',
                    td_body,
                    re.I,
                )
                if href_m:
                    raw_href = href_m.group(1).strip()
                    id_m = re.search(r"/(\d+)/?(?:[?#].*)?$", raw_href)
                    if id_m:
                        ev_suffix = id_m.group(1)
                    if can_book:
                        booking_url = validate_uscinemas_booking_url(raw_href)

                scr_fac = match_screen_facility(current_screen, fac_screens)
                features = list(scr_fac.get("features", [])) if scr_fac else []
                tags = _extract_uscinemas_tags(title, current_raw_screen, current_screen, *features)

                screenings.append(
                    Screening(
                        event_id=f"{safe_theater}_{ev_suffix}",
                        screen_name=current_screen,
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
        cnt = title_counts.get(title, 0) + 1
        title_counts[title] = cnt
        movie_id = f"{safe_theater}_m{len(movies) + 1}" if cnt == 1 else f"{safe_theater}_m{len(movies) + 1}_{cnt}"

        movies.append(
            MovieSchedule(
                movie_id=movie_id,
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


class UsCinemasProvider(BaseCinemaProvider):
    """USシネマ・千葉劇場 (US CINEMAS) スケジュールプロバイダ"""

    CHAIN_ID: str = "uscinemas"
    BASE_BOOKING_URL: str = "https://cinema-ticket.jp/"

    def __init__(self, timeout: int = 15):
        super().__init__(timeout=timeout)

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        safe_theater = sanitize_identifier(theater_id)
        return build_safe_url(f"https://uscinemas.jp/category/{safe_theater}/")

    def _fetch_schedule_html(self, safe_theater: str, target_date: date) -> str:
        date_str = target_date.strftime("%Y-%m-%d")
        url = build_safe_url(
            f"https://uscinemas.jp/category/{safe_theater}/",
            query_params={"date": date_str},
        )
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
                    f"劇場コード '{safe_theater}' のスケジュールが見つかりませんでした (HTTP {code})。"
                ) from e
            raise RuntimeError(f"HTTPエラーが発生しました: {code} {reason}") from e
        except Exception as e:
            raise RuntimeError(f"スケジュールデータの取得に失敗しました: {e}") from e

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        if safe_theater not in self._load_theaters_master():
            raise RuntimeError(
                f"劇場コード '{safe_theater}' はUSシネマ・千葉劇場マスタに登録されていません。"
            )
        theater_info = self.get_theater_info(safe_theater)
        html = self._fetch_schedule_html(safe_theater, target_date)
        return parse_uscinemas_schedule_html(
            html=html,
            target_date=target_date,
            theater_id=safe_theater,
            theater_info=theater_info,
        )
