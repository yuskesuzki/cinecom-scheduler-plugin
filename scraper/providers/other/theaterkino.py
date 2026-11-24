from datetime import date, timedelta
import re
from typing import Callable, Dict, List, Optional, Set, Tuple
import unicodedata
import urllib.parse

from ...models import MovieSchedule, Screening, SeatStatus
from ...sanitizer import UnsafeUrlError, build_safe_url, sanitize_identifier
from ..base import BaseCinemaProvider
from ..html_utils import (
    clean_text,
    extract_balanced_elements,
    extract_special_tags,
    pad_hhmm,
)

_ALLOWED_THEATERKINO_HOSTS = frozenset({"theaterkino.net", "www.theaterkino.net"})
_SAKUHIN_DIV_RE = re.compile(
    r'<div\b[^>]*\bid\s*=\s*(?:"sakuhin"|\'sakuhin\'|sakuhin)(?=[\s>])[^>]*>',
    re.IGNORECASE,
)
_SAKUHIN_PHOTO_DIV_RE = re.compile(
    r'<div\b[^>]*\bid\s*=\s*(?:"sakuhinphoto"|\'sakuhinphoto\'|sakuhinphoto)(?=[\s>])[^>]*>',
    re.IGNORECASE,
)


def _strip_br_to_space(raw_html: str) -> str:
    return re.sub(r"<br\s*/?>", " ", raw_html or "", flags=re.IGNORECASE)


def parse_theaterkino_period(
    html: str, reference_date: date
) -> Optional[Tuple[date, date]]:
    """
    シアターキノ週間スケジュールHTML (<div id="days"><h2>...</h2>) から
    対象期間 (start_date, end_date) を抽出し、年またぎを含めて解決する。
    """
    if not html:
        return None

    m = re.search(
        r'<div\b[^>]*\bid\s*=\s*(?:"days"|\'days\'|days)(?=[\s>])[^>]*>.*?<h2\b[^>]*>(.*?)</h2>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None

    heading = unicodedata.normalize("NFKC", clean_text(m.group(1)))
    pm = re.search(
        r"(\d{1,2})/(\d{1,2})\s*(?:\([^)]*\))?\s*[~〜～\-⇒→]+\s*(\d{1,2})/(\d{1,2})",
        heading,
    )
    if not pm:
        return None

    sm, sd, em, ed = (int(x) for x in pm.groups())
    candidates: List[Tuple[date, date]] = []
    for year in (reference_date.year - 1, reference_date.year, reference_date.year + 1):
        end_year = year + 1 if (em, ed) < (sm, sd) else year
        try:
            start_d = date(year, sm, sd)
            end_d = date(end_year, em, ed)
        except ValueError:
            continue
        candidates.append((start_d, end_d))

    if not candidates:
        return None

    for start_d, end_d in candidates:
        if start_d <= reference_date <= end_d:
            return start_d, end_d

    return min(
        candidates,
        key=lambda pair: min(
            abs((reference_date - pair[0]).days),
            abs((reference_date - pair[1]).days),
        ),
    )


def _resolve_md_in_period(
    month: Optional[int],
    day: int,
    cur_month: int,
    period_start: date,
    period_end: date,
    md_to_date: Dict[Tuple[int, int], date],
) -> Tuple[Optional[date], int]:
    if month is not None:
        return md_to_date.get((month, day)), month

    dt = md_to_date.get((cur_month, day))
    if dt is not None:
        return dt, cur_month

    if period_end.month != cur_month:
        dt = md_to_date.get((period_end.month, day))
        if dt is not None:
            return dt, period_end.month

    if period_start.month != cur_month:
        dt = md_to_date.get((period_start.month, day))
        if dt is not None:
            return dt, period_start.month

    return None, cur_month


def expand_theaterkino_dates(
    spec_text: str, period_start: date, period_end: date
) -> Set[date]:
    """
    '11/21(土)・24(火)～27(金)' や '11/28(土)～12/4(金)' 等の日付表記を
    [period_start, period_end] 内の date 集合へ展開する。
    """
    if not spec_text or period_end < period_start:
        return set()

    text = unicodedata.normalize("NFKC", clean_text(spec_text))
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\s+", "", text)
    if not text:
        return set()

    md_to_date: Dict[Tuple[int, int], date] = {}
    cur = period_start
    while cur <= period_end:
        md_to_date[(cur.month, cur.day)] = cur
        cur += timedelta(days=1)

    result: Set[date] = set()
    cur_month = period_start.month

    for part in re.split(r"[・、,]", text):
        if not part:
            continue
        range_parts = re.split(r"[~〜～\-⇒→]+", part, maxsplit=1)
        if len(range_parts) == 2:
            left, right = range_parts
            m_left = re.match(r"^(?:(\d{1,2})/)?(\d{1,2})$", left)
            m_right = re.match(r"^(?:(\d{1,2})/)?(\d{1,2})$", right)
            if not m_left or not m_right:
                continue

            l_month = int(m_left.group(1)) if m_left.group(1) else None
            l_day = int(m_left.group(2))
            d1, cur_month = _resolve_md_in_period(
                l_month, l_day, cur_month, period_start, period_end, md_to_date
            )

            r_month = int(m_right.group(1)) if m_right.group(1) else None
            r_day = int(m_right.group(2))
            d2, cur_month = _resolve_md_in_period(
                r_month, r_day, cur_month, period_start, period_end, md_to_date
            )

            if d1 and d2 and d1 <= d2:
                d_iter = d1
                while d_iter <= d2:
                    result.add(d_iter)
                    d_iter += timedelta(days=1)
        else:
            m_single = re.match(r"^(?:(\d{1,2})/)?(\d{1,2})$", part)
            if not m_single:
                continue
            s_month = int(m_single.group(1)) if m_single.group(1) else None
            s_day = int(m_single.group(2))
            dt, cur_month = _resolve_md_in_period(
                s_month, s_day, cur_month, period_start, period_end, md_to_date
            )
            if dt:
                result.add(dt)

    return result


def _extract_theaterkino_info_href(block_html: str) -> Optional[str]:
    """作品ブロック内の説明リンクから公式ニュース/作品詳細URLを抽出する（閉じクォート欠損も許容）。"""
    # sakuhinphoto 内の共通ダミーリンク (sakuhin.html#buryugeru) は除外する
    without_photo = _SAKUHIN_PHOTO_DIV_RE.sub("", block_html)
    without_photo = re.sub(
        r'<a\b[^>]*sakuhin\.html#buryugeru[^>]*>.*?</a>',
        "",
        without_photo,
        flags=re.DOTALL | re.IGNORECASE,
    )
    href_re = re.compile(
        r'<a\b[^>]*\bhref\s*=\s*(?:"([^"<>]+)"?|\'([^\'<>]+)\'?|([^\s"\'<>]+))',
        re.IGNORECASE,
    )
    for m in href_re.finditer(without_photo):
        candidate = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if not candidate or "sakuhin.html#buryugeru" in candidate:
            continue
        parsed = urllib.parse.urlparse(candidate)
        host = (parsed.hostname or "").lower()
        if host in _ALLOWED_THEATERKINO_HOSTS or (not parsed.scheme and not host):
            return candidate
    return None


def parse_theaterkino_schedule_html(
    html: str,
    target_date: date,
    theater_id: str = "theaterkino",
    info_url_builder: Optional[Callable[[str, Optional[str]], str]] = None,
) -> List[MovieSchedule]:
    """
    シアターキノの週間スケジュールHTML (ttA.html / ttB.html) をパースし、
    target_date に対応する MovieSchedule のリストを返す。
    """
    if not html or not html.strip():
        return []

    period = parse_theaterkino_period(html, target_date)
    if not period:
        return []
    period_start, period_end = period
    if not (period_start <= target_date <= period_end):
        return []

    safe_theater = sanitize_identifier(theater_id)
    date_compact = target_date.strftime("%Y%m%d")
    blocks = extract_balanced_elements(html, "div", _SAKUHIN_DIV_RE)

    grouped: Dict[str, Dict[str, object]] = {}
    movie_seq = 0

    for _, block_html in blocks:
        ttl_m = re.search(
            r'<p\b[^>]*\bclass\s*=\s*(?:"[^"]*\bttl\b[^"]*"|\'[^\']*\bttl\b[^\']*\'|ttl\b)[^>]*>(.*?)</p>',
            block_html,
            re.DOTALL | re.IGNORECASE,
        )
        if not ttl_m:
            continue

        base_title = clean_text(_strip_br_to_space(ttl_m.group(1)))
        base_title = re.sub(r"^■\s*", "", base_title).strip()
        if not base_title:
            continue

        raw_info_href = _extract_theaterkino_info_href(block_html)
        resolved_info_url = (
            info_url_builder(safe_theater, raw_info_href) if info_url_builder else None
        )

        tables = re.findall(
            r"<table\b[^>]*>(.*?)</table>",
            block_html,
            re.DOTALL | re.IGNORECASE,
        )
        for table_html in tables:
            trs = re.findall(
                r"<tr\b[^>]*>(.*?)</tr>",
                table_html,
                re.DOTALL | re.IGNORECASE,
            )
            for row_idx in range(0, len(trs) - 1, 2):
                tds_top = re.findall(
                    r"<td\b([^>]*)>(.*?)</td>",
                    trs[row_idx],
                    re.DOTALL | re.IGNORECASE,
                )
                tds_bot = re.findall(
                    r"<td\b([^>]*)>(.*?)</td>",
                    trs[row_idx + 1],
                    re.DOTALL | re.IGNORECASE,
                )
                if not tds_top:
                    continue

                rowspan_cells: List[str] = []
                time_cells: List[str] = []
                for attr, body in tds_top:
                    if re.search(r"\browspan\s*=\s*(?:\"2\"|'2'|2\b)", attr, re.IGNORECASE):
                        rowspan_cells.append(body)
                    else:
                        time_cells.append(body)

                end_cells = [body for _, body in tds_bot]

                if len(rowspan_cells) == 0:
                    row_dates = {target_date}
                    movie_title = base_title
                elif len(rowspan_cells) == 1:
                    row_dates = expand_theaterkino_dates(
                        rowspan_cells[0], period_start, period_end
                    )
                    movie_title = base_title
                else:
                    row_dates = expand_theaterkino_dates(
                        rowspan_cells[0], period_start, period_end
                    )
                    sub_title = clean_text(_strip_br_to_space(rowspan_cells[1]))
                    if not sub_title or "上映なし" in sub_title:
                        continue
                    movie_title = f"{base_title} {sub_title}"

                if target_date not in row_dates:
                    continue

                for slot_idx, (st_html, et_html) in enumerate(
                    zip(time_cells, end_cells), start=1
                ):
                    st_text = unicodedata.normalize("NFKC", clean_text(st_html))
                    if "上映なし" in st_text:
                        continue
                    st_m = re.search(r"(\d{1,2}:\d{2})", st_text)
                    if not st_m:
                        continue

                    start_time = pad_hhmm(st_m.group(1))
                    et_text = unicodedata.normalize("NFKC", clean_text(et_html))
                    et_m = re.search(r"(?:終|終了)\s*(\d{1,2}:\d{2})", et_text)
                    end_time = pad_hhmm(et_m.group(1)) if et_m else ""

                    bucket = grouped.get(movie_title)
                    if bucket is None:
                        movie_seq += 1
                        movie_id = f"{safe_theater}_{date_compact}_m{movie_seq}"
                        bucket = {
                            "movie_id": movie_id,
                            "info_url": resolved_info_url,
                            "screenings": [],
                        }
                        grouped[movie_title] = bucket

                    screenings_list: List[Screening] = bucket["screenings"]  # type: ignore[assignment]
                    screen_name = "スクリーン未定"
                    event_id = (
                        f"{bucket['movie_id']}_{len(screenings_list) + 1}_{slot_idx}_"
                        f"{start_time.replace(':', '')}"
                    )
                    tags = extract_special_tags(movie_title, screen_name)
                    screenings_list.append(
                        Screening(
                            event_id=event_id,
                            screen_name=screen_name,
                            start_time=start_time,
                            end_time=end_time,
                            seat_status=SeatStatus.UNKNOWN,
                            booking_url="",
                            tags=tags,
                        )
                    )

    movies: List[MovieSchedule] = []
    for title, bucket in grouped.items():
        screenings_list = bucket["screenings"]  # type: ignore[assignment]
        if not screenings_list:
            continue
        screenings_list.sort(key=lambda s: (s.start_time, s.end_time))
        movies.append(
            MovieSchedule(
                movie_id=str(bucket["movie_id"]),
                movie_title=title,
                screenings=screenings_list,
                info_url=bucket["info_url"],  # type: ignore[arg-type]
            )
        )

    movies.sort(
        key=lambda m: (
            m.screenings[0].start_time if m.screenings else "99:99",
            m.movie_title.lower(),
        )
    )
    return movies


class TheaterKinoProvider(BaseCinemaProvider):
    """
    札幌シアターキノ向け Provider。
    ttA.html / ttB.html の週間HTMLタイムテーブルを取得・パースする。
    """

    CHAIN_ID: str = "other"
    ADAPTER_ID: str = "theaterkino"
    BASE_BOOKING_URL: str = ""

    def resolve_movie_info_url(
        self, theater_id: str, raw_href: Optional[str]
    ) -> str:
        theater_info = self.get_theater_info(theater_id)
        base_url = theater_info.get("base_url") or "https://theaterkino.net"
        fallback = theater_info.get("official_url") or "https://theaterkino.net/sakuhin.html"
        if not raw_href or not isinstance(raw_href, str):
            return fallback

        trimmed = raw_href.strip()
        if not trimmed or "sakuhin.html#buryugeru" in trimmed:
            return fallback

        joined = urllib.parse.urljoin(base_url.rstrip("/") + "/", trimmed)
        parsed = urllib.parse.urlparse(joined)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in _ALLOWED_THEATERKINO_HOSTS:
            return fallback

        segments = [seg for seg in parsed.path.split("/") if seg]
        try:
            safe_segments = [sanitize_identifier(seg) for seg in segments]
            qs = urllib.parse.parse_qs(parsed.query)
            safe_params: Dict[str, str] = {}
            for k, vals in qs.items():
                if vals and vals[0] != "":
                    safe_params[sanitize_identifier(k)] = sanitize_identifier(vals[0])

            if not safe_segments and not safe_params:
                return fallback

            trailing = "/" if parsed.path.endswith("/") and safe_segments else ""
            if safe_segments:
                target_url = f"https://{host}/" + "/".join(safe_segments) + trailing
            else:
                target_url = f"https://{host}/"
            return build_safe_url(target_url, query_params=safe_params or None)
        except UnsafeUrlError:
            return fallback

    def fetch_movies(
        self, theater_id: str, target_date: date
    ) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        theater_info = self.get_theater_info(safe_theater)
        base_url = theater_info.get("base_url") or "https://theaterkino.net"
        pages = theater_info.get("schedule_pages") or ["ttA.html", "ttB.html"]

        for page in pages:
            safe_page = sanitize_identifier(str(page))
            url = build_safe_url(base_url, path_segments=[safe_page])
            html = self._fetch_html(
                url,
                encoding="utf-8",
                context=f"{safe_theater}:{safe_page}",
                ignore_404=True,
            )
            if not html:
                continue
            period = parse_theaterkino_period(html, target_date)
            if period and period[0] <= target_date <= period[1]:
                return parse_theaterkino_schedule_html(
                    html=html,
                    target_date=target_date,
                    theater_id=safe_theater,
                    info_url_builder=self.resolve_movie_info_url,
                )

        return []
