from datetime import date
import re
from typing import Any, Callable, Dict, List, Optional, Sequence
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
)
from .base import BaseOtherStrategy

_BOOKING_KEYS = ("ttc", "tsc", "tssc", "ymd", "cs")


def map_oscinemas_seat_status(
    item_classes: str, icon_classes: Sequence[str]
) -> SeatStatus:
    """
    OSシネマズの上映枠要素クラスおよびアイコンクラス一覧から SeatStatus を判定する。
    """
    item_tokens = {tok.lower() for tok in (item_classes or "").split() if tok}
    icon_tokens = {
        tok.lower()
        for cls_str in (icon_classes or [])
        for tok in str(cls_str).split()
        if tok
    }

    if icon_tokens & {"cross", "batsu", "full", "soldout"}:
        return SeatStatus.FULL
    if "status2" in item_tokens or "hyphen" in icon_tokens:
        return SeatStatus.UNSOLD
    if "status4" in item_tokens:
        return SeatStatus.FULL
    if "triangle" in icon_tokens:
        return SeatStatus.FEW
    if "circle" in icon_tokens:
        return SeatStatus.AVAILABLE
    return SeatStatus.UNKNOWN


def parse_oscinemas_schedule_html(
    html: str,
    theater_id: str,
    booking_url_builder: Callable[[str, str, Optional[Dict[str, str]]], str],
    info_url_builder: Optional[Callable[[str, Optional[str]], str]] = None,
) -> List[MovieSchedule]:
    """
    OSシネマズ schedule API (/cgi-bin/api/get-top-schedule.cgi) が返す
    HTML 断片（EUC-JPデコード済み）をパースして MovieSchedule のリストを返す。
    """
    movies: List[MovieSchedule] = []
    if not html or not html.strip():
        return movies

    box_open_re = re.compile(
        r'<div\b([^>]*\bclass\s*=\s*(?:"[^"]*(?<![-\w])com-item-select1(?![-\w])[^"]*"|\'[^\']*(?<![-\w])com-item-select1(?![-\w])[^\']*\')[^>]*)>',
        re.IGNORECASE,
    )
    boxes = extract_balanced_elements(html, "div", box_open_re)

    slot_a_re = re.compile(
        r'<a\b([^>]*\bclass\s*=\s*(?:"[^"]*(?<![-\w])item(?![-\w])[^"]*"|\'[^\']*(?<![-\w])item(?![-\w])[^\']*\')[^>]*)>',
        re.IGNORECASE,
    )
    slot_div_re = re.compile(
        r'<div\b([^>]*\bclass\s*=\s*(?:"[^"]*(?<![-\w])item(?![-\w])[^"]*"|\'[^\']*(?<![-\w])item(?![-\w])[^\']*\')[^>]*)>',
        re.IGNORECASE,
    )

    for box_idx, (_, box_html) in enumerate(boxes, start=1):
        h3_m = re.search(
            r'<h3\b[^>]*\bclass\s*=\s*(?:"[^"]*(?<![-\w])title(?![-\w])[^"]*"|\'[^\']*(?<![-\w])title(?![-\w])[^\']*\')[^>]*>(.*?)</h3>',
            box_html,
            re.DOTALL | re.IGNORECASE,
        )
        if not h3_m:
            continue
        h3_html = h3_m.group(1)

        title_link_m = re.search(
            r"<a\b([^>]*)>(.*?)</a>",
            h3_html,
            re.DOTALL | re.IGNORECASE,
        )
        raw_info_href = get_attr(title_link_m.group(1), "href") if title_link_m else None
        title_ja = clean_text(title_link_m.group(2) if title_link_m else h3_html)
        if not title_ja:
            continue

        movie_id = ""
        if raw_info_href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_info_href).query)
            movie_id = (qs.get("ttc") or [""])[0]
        if not movie_id:
            movie_id = f"{theater_id}_movie_{box_idx}"

        info_url = info_url_builder(theater_id, raw_info_href) if info_url_builder else None

        body_html = box_html[h3_m.end() :]
        slot_elements = extract_balanced_elements(body_html, "a", slot_a_re)
        slot_elements.extend(extract_balanced_elements(body_html, "div", slot_div_re))

        screenings: List[Screening] = []
        for slot_idx, (item_attrs, item_html) in enumerate(slot_elements, start=1):
            time_m = re.search(
                r'<div\b[^>]*\bclass\s*=\s*(?:"[^"]*\btime\b[^"]*"|\'[^\']*\btime\b[^\']*\')[^>]*>(.*?)</div>',
                item_html,
                re.DOTALL | re.IGNORECASE,
            )
            if not time_m:
                continue
            time_text = clean_text(time_m.group(1))
            t_m = re.search(r"(\d{1,2}:\d{2})\s*[～~〜\-ー]\s*(\d{1,2}:\d{2})", time_text)
            if not t_m:
                continue
            start_time = pad_hhmm(t_m.group(1))
            end_time = pad_hhmm(t_m.group(2))

            scr_m = re.search(
                r'<div\b[^>]*\bclass\s*=\s*(?:"[^"]*\bscreen\b[^"]*"|\'[^\']*\bscreen\b[^\']*\')[^>]*>(.*?)</div>',
                item_html,
                re.DOTALL | re.IGNORECASE,
            )
            screen_name = normalize_screen_name(scr_m.group(1) if scr_m else "")

            item_classes = get_attr(item_attrs, "class")
            icon_classes = [
                cls_d or cls_s
                for cls_d, cls_s in re.findall(
                    r'<span\b[^>]*\bclass\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
                    item_html,
                    re.IGNORECASE,
                )
                if "icon" in (cls_d or cls_s).lower().split()
            ]
            seat_status = map_oscinemas_seat_status(item_classes, icon_classes)

            item_tokens = {tok.lower() for tok in item_classes.split() if tok}
            is_purchasable = (
                seat_status in (SeatStatus.AVAILABLE, SeatStatus.FEW)
                and "status2" not in item_tokens
                and "status4" not in item_tokens
            )

            raw_href = get_attr(item_attrs, "href")
            booking_url = ""
            event_id = ""
            if raw_href:
                parsed = urllib.parse.urlparse(raw_href)
                host = (parsed.hostname or "").lower()
                if (
                    host in ("", "www.oscinemas.net")
                    and parsed.path == "/cgi-bin/pc/resv/resv_shw_ppt.cgi"
                ):
                    qs = urllib.parse.parse_qs(parsed.query)
                    params = {k: (qs.get(k) or [""])[0] for k in _BOOKING_KEYS}
                    if all(params.values()):
                        event_id = "_".join(params[k] for k in _BOOKING_KEYS)
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


class OsCinemasStrategy(BaseOtherStrategy):
    """
    OSシネマズ（ミント神戸・神戸ハーバーランド）向け Strategy。
    """

    ADAPTER_ID: str = "oscinemas"

    def build_booking_url(
        self,
        theater_info: Dict[str, Any],
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        base_url = theater_info.get("base_url") or "https://www.oscinemas.net"
        params = dict(extra_params or {})
        if not all(params.get(k) for k in _BOOKING_KEYS):
            parts = (event_id or "").split("_")
            if len(parts) == len(_BOOKING_KEYS):
                params = dict(zip(_BOOKING_KEYS, parts))
        if not all(params.get(k) for k in _BOOKING_KEYS):
            raise UnsafeUrlError("Missing OS Cinemas booking parameters")

        query = {k: sanitize_identifier(str(params[k])) for k in _BOOKING_KEYS}
        return build_safe_url(
            f"{base_url}/cgi-bin/pc/resv/resv_shw_ppt.cgi",
            query_params=query,
        )

    def fetch_movies(
        self, theater_info: Dict[str, Any], target_date: date
    ) -> List[MovieSchedule]:
        theater_id = theater_info["id"]
        base_url = theater_info.get("base_url") or "https://www.oscinemas.net"
        code = str(theater_info.get("code") or "").strip()
        if not code:
            raise ValueError(f"Theater '{theater_id}' has no theater code")

        safe_code = sanitize_identifier(code)
        api_url = build_safe_url(
            base_url,
            path_segments=["cgi-bin", "api", "get-top-schedule.cgi"],
        )
        referer = build_safe_url(
            base_url,
            path_segments=["cgi-bin", "pc", "site", "det.cgi"],
            query_params={"tsc": safe_code},
        )
        post_body = urllib.parse.urlencode(
            {"site_c": safe_code, "target_ymd": target_date.isoformat()}
        ).encode("ascii")

        headers = dict(self.default_headers)
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Referer"] = referer

        req = urllib.request.Request(api_url, data=post_body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                html = resp.read().decode("euc-jp", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                html = ""
            else:
                raise RuntimeError(
                    f"共同経営・その他 スケジュール取得に失敗しました ({theater_id}, HTTP {e.code} {e.reason})"
                ) from e
        except Exception as e:
            raise RuntimeError(
                f"共同経営・その他 スケジュール取得に失敗しました ({theater_id}): {e}"
            ) from e

        return parse_oscinemas_schedule_html(
            html=html,
            theater_id=theater_id,
            booking_url_builder=lambda _tid, ev, params=None: self.build_booking_url(
                theater_info, ev, params
            ),
            info_url_builder=lambda _tid, href: self.build_movie_info_url(
                theater_info, href
            ),
        )
