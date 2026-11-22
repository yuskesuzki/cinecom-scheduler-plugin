from datetime import date
import re
from typing import Callable, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request

from ..models import MovieSchedule, Screening, SeatStatus
from ..sanitizer import UnsafeUrlError, build_safe_url, sanitize_identifier
from .base import BaseCinemaProvider
from .smt import (
    _FULLWIDTH_TRANS,
    _clean_text,
    _extract_balanced_elements,
    _get_attr,
    _pad_hhmm,
    clean_smt_movie_title,
    extract_special_tags,
    normalize_smt_screen_name,
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
    return _clean_text(without_spans)


def normalize_cinema_frontier_screen_name(raw_name: str) -> str:
    """
    札幌シネマフロンティアのスクリーン名を正規化する。
    例: 'スクリーン０５' -> 'スクリーン5'
    """
    cleaned = _clean_text(raw_name).translate(_FULLWIDTH_TRANS)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "シアター未定"

    m = re.fullmatch(r"(スクリーン|シアター)\s*0*(\d+)", cleaned)
    if m:
        return f"{m.group(1)}{int(m.group(2))}"
    return cleaned


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


def parse_smt_legacy_schedule_html(
    html: str,
    theater_id: str,
    base_url: str,
    ticket_host: str,
    booking_url_builder: Callable[[str, str, Optional[Dict[str, str]]], str],
    info_url_builder: Optional[Callable[[str, Optional[str]], str]] = None,
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
    boxes = _extract_balanced_elements(html, "div", box_open_re)

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
        raw_info_href = _get_attr(a_m.group(1), "href") if a_m else None
        raw_title_html = a_m.group(2) if a_m else h2_html
        title_ja = clean_smt_movie_title(raw_title_html)
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
        outer_tables = _extract_balanced_elements(after_h2, "table", table_open_re)
        if not outer_tables:
            continue
        outer_table_html = outer_tables[0][1]
        slot_tds = _extract_balanced_elements(outer_table_html, "td", td_open_re)

        screenings: List[Screening] = []
        for slot_idx, (td_attrs, td_html) in enumerate(slot_tds, start=1):
            slot_text = _clean_text(td_html)
            if not slot_text or slot_text == "\xa0":
                continue

            t_m = re.search(
                r"(\d{1,2}:\d{2})\s*[～~〜\-ー]\s*(\d{1,2}:\d{2})",
                slot_text,
            )
            if not t_m:
                continue
            start_time = _pad_hhmm(t_m.group(1))
            end_time = _pad_hhmm(t_m.group(2))

            p_m = re.search(r"<p\b[^>]*>(.*?)</p>", td_html, re.DOTALL | re.IGNORECASE)
            screen_name = normalize_smt_screen_name(p_m.group(1) if p_m else "")

            img_m = re.search(r"<img\b([^>]*)>", td_html, re.IGNORECASE)
            icon_filename = None
            alt_text = ""
            if img_m:
                img_attrs = img_m.group(1)
                src_val = _get_attr(img_attrs, "src")
                alt_text = _get_attr(img_attrs, "alt")
                ic_m = re.search(r"/icon/([^/?#]+)", src_val)
                if ic_m:
                    icon_filename = ic_m.group(1)

            seat_status = map_smt_legacy_seat_status(icon_filename, alt_text)
            is_purchasable = seat_status in (SeatStatus.AVAILABLE, SeatStatus.FEW)

            onclick_val = _get_attr(td_attrs, "onclick")
            booking_url = ""
            event_id = ""
            if onclick_val:
                url_m = re.search(r"https://[^\s\"'()]+", onclick_val)
                if url_m:
                    parsed = urllib.parse.urlparse(url_m.group(0))
                    if (parsed.hostname or "").lower() == ticket_host.lower() and parsed.path == "/ticket/f0100.do":
                        qs = urllib.parse.parse_qs(parsed.query)
                        required_keys = ("th", "mo", "sd", "pe", "sc", "fl")
                        params = {k: (qs.get(k) or [""])[0] for k in required_keys}
                        if all(params.values()):
                            event_id = "_".join(params[k] for k in required_keys)
                            if is_purchasable:
                                try:
                                    booking_url = booking_url_builder(theater_id, event_id, params)
                                except UnsafeUrlError:
                                    booking_url = ""

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
    movie_boxes = _extract_balanced_elements(html, "div", item_box_re)

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
        title_en = _clean_text(h4_m.group(1)) if h4_m else ""

        link_m = re.search(
            r'<a\b([^>]*\bclass\s*=\s*["\'][^"\']*\blink\b[^"\']*["\'][^>]*)>',
            box_html,
            re.IGNORECASE,
        )
        raw_info_href = _get_attr(link_m.group(1), "href") if link_m else None

        movie_id = ""
        if raw_info_href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_info_href).query)
            movie_id = (qs.get("ttc") or [""])[0]
        if not movie_id:
            movie_id = f"cf_movie_{box_idx}"

        info_url = info_url_builder(theater_id, raw_info_href) if info_url_builder else None

        items_divs = _extract_balanced_elements(box_html, "div", items_open_re)
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
            time_txt = _clean_text(time_m.group(1))
            t_m = re.search(r"(\d{1,2}:\d{2})\s*[～~〜\-ー]\s*(\d{1,2}:\d{2})", time_txt)
            if not t_m:
                continue
            start_time = _pad_hhmm(t_m.group(1))
            end_time = _pad_hhmm(t_m.group(2))

            scr_m = re.search(
                r'<p\b[^>]*class=["\'][^"\']*\bscreen\b[^"\']*["\'][^>]*>(.*?)</p>',
                slot_inner,
                re.DOTALL | re.IGNORECASE,
            )
            screen_name = normalize_cinema_frontier_screen_name(scr_m.group(1) if scr_m else "")

            st_m = re.search(
                r'<p\b[^>]*class=["\'][^"\']*\bstatus\b[^"\']*["\'][^>]*>(.*?)</p>',
                slot_inner,
                re.DOTALL | re.IGNORECASE,
            )
            status_text = _clean_text(st_m.group(1)) if st_m else ""
            slot_class = _get_attr(slot_attrs, "class")
            seat_status = map_cinema_frontier_seat_status(slot_class, status_text)
            is_purchasable = seat_status in (SeatStatus.AVAILABLE, SeatStatus.FEW)

            raw_href = _get_attr(slot_attrs, "href") if tag_type == "a" else ""
            booking_url = ""
            event_id = ""
            if raw_href:
                parsed = urllib.parse.urlparse(raw_href)
                host_ok = (not parsed.netloc) or ((parsed.hostname or "").lower() == "www.cinemafrontier.net")
                if host_ok and parsed.path == "/cgi-bin/pc/resv/resv_shw_ppt.cgi":
                    qs = urllib.parse.parse_qs(parsed.query)
                    required_keys = ("ttc", "tsc", "tssc", "ymd", "cs")
                    params = {k: (qs.get(k) or [""])[0] for k in required_keys}
                    if all(params.values()):
                        event_id = f"{params['ttc']}_{params['tssc']}_{params['cs']}"
                        if is_purchasable:
                            try:
                                booking_url = booking_url_builder(theater_id, event_id, params)
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


class OtherCinemaProvider(BaseCinemaProvider):
    """
    共同経営・独立系劇場（other）向け統合 Provider。
    現在は以下の3館（2種類のアダプター）に対応:
      - smt_legacy: 大阪ステーションシティシネマ (oscc), なんばパークスシネマ (namba)
      - cinema_frontier: 札幌シネマフロンティア (sapporo_cf)
    """

    CHAIN_ID: str = "other"

    def __init__(self, timeout: int = 15):
        super().__init__(timeout=timeout)
        self.default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _fetch_html(self, url: str, encoding: str, context: str) -> str:
        req = urllib.request.Request(url, headers=self.default_headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode(encoding, errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""
            raise RuntimeError(
                f"共同経営・その他 スケジュール取得に失敗しました ({context}, HTTP {e.code} {e.reason})"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"共同経営・その他 スケジュール取得に失敗しました ({context}): {e}"
            ) from e

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        safe_theater = sanitize_identifier(theater_id)
        info = self.get_theater_info(safe_theater)
        adapter = info.get("adapter")

        if adapter == "smt_legacy":
            ticket_host = info.get("ticket_host") or ""
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

        if adapter == "cinema_frontier":
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

        raise ValueError(f"Unsupported adapter '{adapter}' for theater '{safe_theater}'")

    def build_movie_info_url(
        self, theater_id: str, raw_href: Optional[str]
    ) -> str:
        safe_theater = sanitize_identifier(theater_id)
        info = self.get_theater_info(safe_theater)
        base_url = info.get("base_url") or ""
        fallback = info.get("official_url") or base_url

        if not raw_href or not isinstance(raw_href, str):
            return fallback

        joined = urllib.parse.urljoin(base_url + "/", raw_href.strip())
        parsed = urllib.parse.urlparse(joined)
        expected_host = (urllib.parse.urlparse(base_url).hostname or "").lower()

        if parsed.scheme != "https" or (parsed.hostname or "").lower() != expected_host:
            return fallback

        segments = [seg for seg in parsed.path.split("/") if seg]
        if not segments:
            return fallback

        try:
            safe_segments = [sanitize_identifier(seg) for seg in segments]
            qs = urllib.parse.parse_qs(parsed.query)
            safe_params: Dict[str, str] = {}
            for k, vals in qs.items():
                if vals and vals[0] != "":
                    safe_params[sanitize_identifier(k)] = sanitize_identifier(vals[0])

            trailing = "/" if parsed.path.endswith("/") else ""
            target_url = f"https://{expected_host}/" + "/".join(safe_segments) + trailing
            return build_safe_url(target_url, query_params=safe_params or None)
        except UnsafeUrlError:
            return fallback

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        info = self.get_theater_info(safe_theater)
        adapter = info.get("adapter")
        code = str(info.get("code") or "").strip()
        if not code:
            raise ValueError(f"Theater '{safe_theater}' has no theater code")

        if adapter == "smt_legacy":
            base_url = info.get("base_url") or ""
            ticket_host = info.get("ticket_host") or ""
            date_str = target_date.strftime("%Y%m%d")
            safe_code = sanitize_identifier(code)
            url = build_safe_url(
                base_url,
                path_segments=["schedule", "pc", f"s0100_{safe_code}_{date_str}.html"],
            )
            html = self._fetch_html(url, encoding="utf-8", context=safe_theater)
            return parse_smt_legacy_schedule_html(
                html=html,
                theater_id=safe_theater,
                base_url=base_url,
                ticket_host=ticket_host,
                booking_url_builder=self.build_booking_url,
                info_url_builder=self.build_movie_info_url,
            )

        if adapter == "cinema_frontier":
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
                info_url_builder=self.build_movie_info_url,
            )

        raise ValueError(f"Unsupported adapter '{adapter}' for theater '{safe_theater}'")
