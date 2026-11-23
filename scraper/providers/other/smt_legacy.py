from datetime import date
import re
from typing import Any, Callable, Dict, List, Optional
import urllib.parse

from ...models import MovieSchedule, Screening, SeatStatus
from ...sanitizer import UnsafeUrlError, build_safe_url, sanitize_identifier
from ..html_utils import (
    clean_text,
    extract_balanced_elements,
    extract_special_tags,
    get_attr,
    normalize_screen_name,
    pad_hhmm,
    strip_runtime_suffix,
)
from .base import BaseOtherStrategy


def map_smt_legacy_seat_status(
    icon_filename: Optional[str], alt_text: str
) -> SeatStatus:
    """
    旧世代SMTテーブル型（大阪SCシネマ・なんばパークスシネマ）の
    アイコンファイル名・altテキストから SeatStatus を判定する。
    """
    icon = (icon_filename or "").lower().strip()
    txt = (alt_text or "").strip()

    if any(kw in txt for kw in ("満席", "売切", "売り切れ")):
        return SeatStatus.FULL
    if icon == "01.png" or "余裕" in txt:
        return SeatStatus.AVAILABLE
    if icon == "02.png" or "わずか" in txt:
        return SeatStatus.FEW
    if icon in ("03.png", "04.png") or any(
        kw in txt for kw in ("販売終了", "販売前", "終了")
    ):
        return SeatStatus.UNSOLD
    return SeatStatus.UNKNOWN


def parse_smt_legacy_schedule_html(
    html: str,
    theater_id: str,
    base_url: str,
    ticket_host: str,
    booking_url_builder: Callable[[str, str, Optional[Dict[str, str]]], str],
    info_url_builder: Optional[Callable[[str, Optional[str]], str]] = None,
    screen_min: Optional[int] = None,
    screen_max: Optional[int] = None,
) -> List[MovieSchedule]:
    """
    旧世代SMTテーブル型スケジュールHTML断片（s0100_{code}_{YYYYMMDD}.html）
    をパースして MovieSchedule のリストを返す。
    """
    movies: List[MovieSchedule] = []
    if not html or not html.strip():
        return movies

    box_open_re = re.compile(
        r'<div\b([^>]*\bclass\s*=\s*(?:"[^"]*(?<![-\w])scheduleBox(?![-\w])[^"]*"|\'[^\']*(?<![-\w])scheduleBox(?![-\w])[^\']*\')[^>]*)>',
        re.IGNORECASE,
    )
    boxes = extract_balanced_elements(html, "div", box_open_re)

    table_open_re = re.compile(r"<table\b([^>]*)>", re.IGNORECASE)
    td_open_re = re.compile(r"<td\b([^>]*)>", re.IGNORECASE)

    for box_idx, (_, box_html) in enumerate(boxes, start=1):
        h2_m = re.search(r"<h2\b[^>]*>(.*?)</h2>", box_html, re.DOTALL | re.IGNORECASE)
        if not h2_m:
            continue
        h2_html = h2_m.group(1)

        a_m = re.search(
            r'<a\b([^>]*\bhref\s*=\s*["\'][^"\']+["\'][^>]*)>(.*?)</a>',
            h2_html,
            re.DOTALL | re.IGNORECASE,
        )
        raw_info_href = get_attr(a_m.group(1), "href") if a_m else None
        raw_title_html = a_m.group(2) if a_m else h2_html
        title_ja = strip_runtime_suffix(raw_title_html)
        if not title_ja:
            continue

        movie_alts = " ".join(
            a or b
            for a, b in re.findall(
                r'<img\b[^>]*alt\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
                h2_html,
                re.IGNORECASE,
            )
        )

        movie_id = ""
        if raw_info_href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_info_href).query)
            movie_id = (qs.get("cinemaid") or [""])[0]
        if not movie_id:
            movie_id = f"{theater_id}_movie_{box_idx}"

        info_url = info_url_builder(theater_id, raw_info_href) if info_url_builder else None

        # 外側スケジュールテーブル（<h2> 以降の親<table>）を取得し、直下<td>のみ走査する
        after_h2 = box_html[h2_m.end() :]
        outer_tables = extract_balanced_elements(after_h2, "table", table_open_re)
        if not outer_tables:
            continue
        outer_table_html = outer_tables[0][1]
        slot_tds = extract_balanced_elements(outer_table_html, "td", td_open_re)

        screenings: List[Screening] = []
        for slot_idx, (td_attrs, td_html) in enumerate(slot_tds, start=1):
            slot_text = clean_text(td_html)
            if not slot_text or slot_text == "\xa0":
                continue

            t_m = re.search(
                r"(\d{1,2}:\d{2})\s*[～~〜\-ー]\s*(\d{1,2}:\d{2})",
                slot_text,
            )
            if not t_m:
                continue
            start_time = pad_hhmm(t_m.group(1))
            end_time = pad_hhmm(t_m.group(2))

            p_m = re.search(r"<p\b([^>]*)>(.*?)</p>", td_html, re.DOTALL | re.IGNORECASE)
            p_attrs = p_m.group(1) if p_m else ""
            screen_name = normalize_screen_name(p_m.group(2) if p_m else "")

            img_m = re.search(r"<img\b([^>]*)>", td_html, re.IGNORECASE)
            icon_filename = None
            alt_text = ""
            if img_m:
                img_attrs = img_m.group(1)
                src_val = get_attr(img_attrs, "src")
                alt_text = get_attr(img_attrs, "alt")
                ic_m = re.search(r"/icon/([^/?#]+)", src_val)
                if ic_m:
                    icon_filename = ic_m.group(1)

            seat_status = map_smt_legacy_seat_status(icon_filename, alt_text)
            is_purchasable = seat_status in (SeatStatus.AVAILABLE, SeatStatus.FEW)

            onclick_val = get_attr(td_attrs, "onclick")
            booking_url = ""
            event_id = ""
            sc_param = ""
            if onclick_val:
                url_m = re.search(r"https://[^\s\"'()]+", onclick_val)
                if url_m:
                    parsed = urllib.parse.urlparse(url_m.group(0))
                    if (
                        (parsed.hostname or "").lower() == ticket_host.lower()
                        and parsed.path == "/ticket/f0100.do"
                    ):
                        qs = urllib.parse.parse_qs(parsed.query)
                        required_keys = ("th", "mo", "sd", "pe", "sc", "fl")
                        params = {k: (qs.get(k) or [""])[0] for k in required_keys}
                        sc_param = params.get("sc", "")
                        if all(params.values()):
                            event_id = "_".join(params[k] for k in required_keys)
                            if is_purchasable:
                                try:
                                    booking_url = booking_url_builder(
                                        theater_id, event_id, params
                                    )
                                except UnsafeUrlError:
                                    booking_url = ""

            if screen_min is not None or screen_max is not None:
                scr_num: Optional[int] = None
                if sc_param.isdigit():
                    scr_num = int(sc_param)
                else:
                    num_m = re.search(r"(\d+)", screen_name)
                    if num_m:
                        scr_num = int(num_m.group(1))
                    else:
                        p_cls = get_attr(p_attrs, "class").lower()
                        if "screengroup1" in p_cls or "night1" in p_cls:
                            scr_num = 1
                        elif "screengroup2" in p_cls or "night2" in p_cls:
                            scr_num = 8

                if screen_min is not None and (scr_num is None or scr_num < screen_min):
                    continue
                if screen_max is not None and (scr_num is None or scr_num > screen_max):
                    continue

            if not event_id:
                event_id = f"{movie_id}_{slot_idx}_{start_time.replace(':', '')}"

            tags = extract_special_tags(title_ja, movie_alts, screen_name)
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


class SmtLegacyStrategy(BaseOtherStrategy):
    """
    旧世代SMTテーブル型システム（大阪ステーションシティシネマ・なんばパークスシネマ・ミッドランドスクエア シネマ）向け Strategy。
    """

    ADAPTER_ID: str = "smt_legacy"

    def build_booking_url(
        self,
        theater_info: Dict[str, Any],
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        ticket_host = theater_info.get("ticket_host") or ""
        legacy_keys = ("th", "mo", "sd", "pe", "sc", "fl")
        params = dict(extra_params or {})
        if not all(params.get(k) for k in legacy_keys):
            parts = (event_id or "").split("_")
            if len(parts) == 6:
                params = dict(zip(legacy_keys, parts))
        if not ticket_host or not all(params.get(k) for k in legacy_keys):
            raise UnsafeUrlError("Missing SMT legacy booking parameters")
        query = {k: sanitize_identifier(str(params[k])) for k in legacy_keys}
        return build_safe_url(f"https://{ticket_host}/ticket/f0100.do", query_params=query)

    def fetch_movies(
        self, theater_info: Dict[str, Any], target_date: date
    ) -> List[MovieSchedule]:
        theater_id = theater_info["id"]
        base_url = theater_info.get("base_url") or ""
        schedule_base_url = theater_info.get("schedule_base_url") or base_url
        ticket_host = theater_info.get("ticket_host") or ""
        code = str(theater_info.get("code") or "").strip()
        if not code:
            raise ValueError(f"Theater '{theater_id}' has no theater code")

        safe_code = sanitize_identifier(code)
        date_str = target_date.strftime("%Y%m%d")
        prefix = str(theater_info.get("schedule_path_prefix") or "schedule/pc").strip("/")
        prefix_segments = [seg for seg in prefix.split("/") if seg]
        suffix = str(theater_info.get("schedule_filename_suffix") or "")
        filename = f"s0100_{safe_code}_{date_str}{suffix}.html"
        url = build_safe_url(
            schedule_base_url,
            path_segments=[*prefix_segments, filename],
        )
        html = self._fetch_html(url, encoding="utf-8", context=theater_id)
        return parse_smt_legacy_schedule_html(
            html=html,
            theater_id=theater_id,
            base_url=base_url,
            ticket_host=ticket_host,
            booking_url_builder=lambda _tid, ev, params=None: self.build_booking_url(
                theater_info, ev, params
            ),
            info_url_builder=lambda _tid, href: self.build_movie_info_url(
                theater_info, href
            ),
            screen_min=theater_info.get("screen_min"),
            screen_max=theater_info.get("screen_max"),
        )
