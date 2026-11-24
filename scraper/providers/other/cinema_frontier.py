from datetime import date
import re
from typing import Callable, Dict, List, Optional
import urllib.parse

from ...models import MovieSchedule, Screening, SeatStatus
from ...sanitizer import UnsafeUrlError, build_safe_url, sanitize_identifier
from ..base import BaseCinemaProvider
from ..html_utils import (
    FULLWIDTH_TRANS,
    clean_text,
    extract_balanced_elements,
    extract_special_tags,
    get_attr,
    pad_hhmm,
)


def clean_cinema_frontier_title(raw_h3_html: str) -> str:
    """
    札幌シネマフロンティアの作品タイトルHTMLから末尾の重複レイティング<span>
    （例: <span>PG12</span>, <span>R15+</span>）のみを除去し、元タイトル文字列を保持する。
    """
    without_spans = re.sub(
        r"<span\b[^>]*>.*?</span>",
        "",
        raw_h3_html or "",
        flags=re.DOTALL | re.IGNORECASE,
    )
    return clean_text(without_spans)


def normalize_cinema_frontier_screen_name(raw_name: str) -> str:
    """
    札幌シネマフロンティアのスクリーン名を正規化する。
    例: 'スクリーン０５' -> 'スクリーン5'
    """
    cleaned = clean_text(raw_name).translate(FULLWIDTH_TRANS)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "シアター未定"

    m = re.fullmatch(r"(スクリーン|シアター)\s*0*(\d+)", cleaned)
    if m:
        return f"{m.group(1)}{int(m.group(2))}"
    return cleaned


def map_cinema_frontier_seat_status(
    status_class: Optional[str], status_text: str
) -> SeatStatus:
    """
    札幌シネマフロンティアのクラス名（status1..status4）およびテキストから
    SeatStatus を判定する（status4 窓口販売のみは UNSOLD 扱い）。
    """
    classes = set((status_class or "").lower().split())
    txt = (status_text or "").strip()

    if any(kw in txt for kw in ("満席", "売切", "売り切れ")):
        return SeatStatus.FULL
    if "status1" in classes:
        return SeatStatus.AVAILABLE
    if "status2" in classes:
        return SeatStatus.FEW
    if "status3" in classes or "status4" in classes:
        return SeatStatus.UNSOLD

    if "販売中" in txt or "余裕" in txt or "購入する" in txt:
        return SeatStatus.AVAILABLE
    if "わずか" in txt:
        return SeatStatus.FEW
    if any(kw in txt for kw in ("販売終了", "販売前", "窓口", "対象外")):
        return SeatStatus.UNSOLD
    return SeatStatus.UNKNOWN


def parse_cinema_frontier_schedule_html(
    html: str,
    theater_id: str,
    booking_url_builder: Callable[[str, str, Optional[Dict[str, str]]], str],
    info_url_builder: Optional[Callable[[str, Optional[str]], str]] = None,
) -> List[MovieSchedule]:
    """
    札幌シネマフロンティアのスケジュールHTML（det.cgi）をパースして
    MovieSchedule のリストを返す。
    """
    movies: List[MovieSchedule] = []
    if not html or not html.strip():
        return movies

    item_box_re = re.compile(
        r'<div\b([^>]*\bclass\s*=\s*(?:"[^"]*(?<![-\w])sc-item(?![-\w])[^"]*"|\'[^\']*(?<![-\w])sc-item(?![-\w])[^\']*\')[^>]*)>',
        re.IGNORECASE,
    )
    movie_boxes = extract_balanced_elements(html, "div", item_box_re)

    items_open_re = re.compile(
        r'<div\b([^>]*\bclass\s*=\s*(?:"[^"]*(?<![-\w])items(?![-\w])[^"]*"|\'[^\']*(?<![-\w])items(?![-\w])[^\']*\')[^>]*)>',
        re.IGNORECASE,
    )
    slot_re = re.compile(
        r'<(a|div)\b([^>]*\bclass\s*=\s*(?:"[^"]*(?<![-\w])item(?![-\w])[^"]*"|\'[^\']*(?<![-\w])item(?![-\w])[^\']*\')[^>]*)>(.*?)</\1>',
        re.DOTALL | re.IGNORECASE,
    )

    for box_idx, (_, box_html) in enumerate(movie_boxes, start=1):
        h3_m = re.search(
            r'<h3\b[^>]*class=["\'][^"\']*\btitle\b[^"\']*["\'][^>]*>(.*?)</h3>',
            box_html,
            re.DOTALL | re.IGNORECASE,
        )
        if not h3_m:
            continue
        title_ja = clean_cinema_frontier_title(h3_m.group(1))
        if not title_ja:
            continue

        h4_m = re.search(
            r'<h4\b[^>]*class=["\'][^"\']*\ben-title\b[^"\']*["\'][^>]*>(.*?)</h4>',
            box_html,
            re.DOTALL | re.IGNORECASE,
        )
        title_en = clean_text(h4_m.group(1)) if h4_m else ""

        link_m = re.search(
            r'<a\b([^>]*\bclass\s*=\s*["\'][^"\']*\blink\b[^"\']*["\'][^>]*)>',
            box_html,
            re.IGNORECASE,
        )
        raw_info_href = get_attr(link_m.group(1), "href") if link_m else None

        movie_id = ""
        if raw_info_href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_info_href).query)
            movie_id = (qs.get("ttc") or [""])[0]
        if not movie_id:
            movie_id = f"cf_movie_{box_idx}"

        info_url = info_url_builder(theater_id, raw_info_href) if info_url_builder else None

        items_divs = extract_balanced_elements(box_html, "div", items_open_re)
        slots_scope = "\n".join(inner for _, inner in items_divs) if items_divs else box_html

        screenings: List[Screening] = []
        for slot_idx, slot_m in enumerate(slot_re.finditer(slots_scope), start=1):
            tag_type = slot_m.group(1).lower()
            slot_attrs = slot_m.group(2)
            slot_inner = slot_m.group(3)

            time_m = re.search(
                r'<p\b[^>]*class=["\'][^"\']*\btime\b[^"\']*["\'][^>]*>(.*?)</p>',
                slot_inner,
                re.DOTALL | re.IGNORECASE,
            )
            if not time_m:
                continue
            time_txt = clean_text(time_m.group(1))
            t_m = re.search(r"(\d{1,2}:\d{2})\s*[～~〜\-ー]\s*(\d{1,2}:\d{2})", time_txt)
            if not t_m:
                continue
            start_time = pad_hhmm(t_m.group(1))
            end_time = pad_hhmm(t_m.group(2))

            scr_m = re.search(
                r'<p\b[^>]*class=["\'][^"\']*\bscreen\b[^"\']*["\'][^>]*>(.*?)</p>',
                slot_inner,
                re.DOTALL | re.IGNORECASE,
            )
            screen_name = normalize_cinema_frontier_screen_name(
                scr_m.group(1) if scr_m else ""
            )

            st_m = re.search(
                r'<p\b[^>]*class=["\'][^"\']*\bstatus\b[^"\']*["\'][^>]*>(.*?)</p>',
                slot_inner,
                re.DOTALL | re.IGNORECASE,
            )
            status_text = clean_text(st_m.group(1)) if st_m else ""
            slot_class = get_attr(slot_attrs, "class")
            seat_status = map_cinema_frontier_seat_status(slot_class, status_text)
            is_purchasable = seat_status in (SeatStatus.AVAILABLE, SeatStatus.FEW)

            raw_href = get_attr(slot_attrs, "href") if tag_type == "a" else ""
            booking_url = ""
            event_id = ""
            if raw_href:
                parsed = urllib.parse.urlparse(raw_href)
                host_ok = (not parsed.netloc) or (
                    (parsed.hostname or "").lower() == "www.cinemafrontier.net"
                )
                if host_ok and parsed.path == "/cgi-bin/pc/resv/resv_shw_ppt.cgi":
                    qs = urllib.parse.parse_qs(parsed.query)
                    required_keys = ("ttc", "tsc", "tssc", "ymd", "cs")
                    params = {k: (qs.get(k) or [""])[0] for k in required_keys}
                    if all(params.values()):
                        event_id = f"{params['ttc']}_{params['tssc']}_{params['cs']}"
                        if is_purchasable:
                            try:
                                booking_url = booking_url_builder(
                                    theater_id, event_id, params
                                )
                            except UnsafeUrlError:
                                booking_url = ""

            if not event_id:
                event_id = f"{movie_id}_{slot_idx}_{start_time.replace(':', '')}"

            tags = extract_special_tags(title_ja, screen_name)
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


class CinemaFrontierProvider(BaseCinemaProvider):
    """札幌シネマフロンティア（det.cgi / EUC-JP）向け Provider。"""

    CHAIN_ID: str = "other"
    ADAPTER_ID: str = "cinema_frontier"

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        sanitize_identifier(theater_id)
        cf_keys = ("ttc", "tsc", "tssc", "ymd", "cs")
        params = dict(extra_params or {})
        if not all(params.get(k) for k in cf_keys):
            parts = (event_id or "").split("_")
            if len(parts) == 5:
                params = dict(zip(cf_keys, parts))
        if not all(params.get(k) for k in cf_keys):
            raise UnsafeUrlError("Missing Cinema Frontier booking parameters")
        query = {k: sanitize_identifier(str(params[k])) for k in cf_keys}
        return build_safe_url(
            "https://www.cinemafrontier.net/cgi-bin/pc/resv/resv_shw_ppt.cgi",
            query_params=query,
        )

    def fetch_movies(
        self, theater_id: str, target_date: date
    ) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        theater_info = self.get_theater_info(safe_theater)
        code = str(theater_info.get("code") or "").strip()
        if not code:
            raise ValueError(f"Theater '{safe_theater}' has no theater code")

        safe_code = sanitize_identifier(code)
        date_dash = target_date.strftime("%Y-%m-%d")
        url = build_safe_url(
            "https://www.cinemafrontier.net/cgi-bin/pc/site/det.cgi",
            query_params={"tsc": safe_code, "ymd": date_dash},
        )
        html = self._fetch_html(url, encoding="euc-jp", context=safe_theater)
        return parse_cinema_frontier_schedule_html(
            html=html,
            theater_id=safe_theater,
            booking_url_builder=self.build_booking_url,
            info_url_builder=self.resolve_movie_info_url,
        )
