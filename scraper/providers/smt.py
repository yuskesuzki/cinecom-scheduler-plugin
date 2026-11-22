from datetime import date
import html as html_lib
import re
from typing import Callable, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request

from ..models import MovieSchedule, Screening, SeatStatus
from ..sanitizer import UnsafeUrlError, build_safe_url, sanitize_identifier
from .base import BaseCinemaProvider

_FULLWIDTH_TRANS = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ－＿：～（）　",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz-_~:() ",
)

_LEGACY_INNER_ID_RE = re.compile(
    r"^\d+_(\d+)_(\d+)_(\d{8})_([A-Za-z0-9-]+)_([A-Za-z0-9-]+)_([A-Za-z0-9-]+)$"
)


def _clean_text(raw_html: str) -> str:
    """HTML片からタグを除去し、実体参照デコードおよび空白正規化を行う。"""
    no_tags = re.sub(r"<[^>]+>", " ", raw_html or "")
    return re.sub(r"\s+", " ", html_lib.unescape(no_tags)).strip()


def _pad_hhmm(time_str: str) -> str:
    """'8:05' のような時刻文字列を '08:05' にゼロ埋め正規化する。"""
    parts = time_str.strip().split(":")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}:{parts[1]}"
    return time_str.strip()


def clean_smt_movie_title(raw_title: str) -> str:
    """
    SMT作品タイトルから末尾の本編時間表記（例: '（本編：135分）'）を取り除く。
    """
    cleaned = _clean_text(raw_title)
    cleaned = re.sub(
        r"\s*[（(]\s*本編\s*[：:]\s*[0-9０-９]+>?\s*分\s*[）)]\s*$",
        "",
        cleaned,
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_smt_screen_name(raw_name: str) -> str:
    """
    SMTのスクリーン名を正規化する。
    - 'シアター５' -> 'シアター5'
    - 'DolbyCinema' / 'DOLBY CINEMA' -> 'Dolby Cinema'
    - 'シアター'（東劇）や 'プラチナ'（新宿）はそのまま保持
    """
    cleaned = _clean_text(raw_name)
    if not cleaned:
        return "シアター未定"

    normalized = cleaned.translate(_FULLWIDTH_TRANS)
    normalized = re.sub(r"\s*\[[^\]]*\]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return "シアター未定"

    if re.fullmatch(r"dolby\s*cinema", normalized, re.IGNORECASE):
        return "Dolby Cinema"

    m = re.fullmatch(r"(シアター|スクリーン)\s*(\d+)", normalized)
    if m:
        return f"{m.group(1)}{m.group(2)}"

    return normalized


def extract_special_tags(*text_sources: Optional[str]) -> List[str]:
    """
    SMTの作品タイトル・タグ・スクリーン名・回テキストから特殊設備タグのみ抽出する。
    (NEW, LAST, レイトショー, 特別興行, 特別料金, バリアフリー, 字幕, 吹替, 2D は除外)
    """
    tags: List[str] = []
    texts = [s for s in text_sources if s]
    if not texts:
        return tags

    combined = " ".join(texts).translate(_FULLWIDTH_TRANS)
    combined_upper = combined.upper()
    combined_compact = re.sub(r"\s+", "", combined_upper)

    if re.search(r"IMAX.{0,4}(?:レーザー|LASER)", combined_upper):
        tags.append("IMAXレーザー")
    elif "IMAX" in combined_upper:
        tags.append("IMAX")

    if "DOLBYCINEMA" in combined_compact:
        tags.append("Dolby Cinema")
    if "DOLBYATMOS" in combined_compact:
        tags.append("Dolby Atmos")

    if "ULTRA4DX" in combined_compact:
        tags.append("ULTRA 4DX")
    elif "4DX" in combined_upper:
        tags.append("4DX")

    if "MX4D" in combined_compact:
        tags.append("MX4D")
    if "SCREENX" in combined_compact:
        tags.append("ScreenX")
    if "爆音" in combined:
        tags.append("爆音")
    if "轟音" in combined:
        tags.append("轟音")
    if re.search(r"(?:^|[^A-Z0-9]|4DX|IMAX)3D(?![A-Z0-9])", combined_upper):
        tags.append("3D")

    return tags


def map_smt_seat_status(status_class: Optional[str], label_text: str) -> SeatStatus:
    """
    SMTの空き状況クラス（ok/few/ng/before）およびラベルテキストを SeatStatus へ変換する。
    """
    classes = set((status_class or "").lower().split())
    txt = (label_text or "").strip()

    if "ok" in classes:
        return SeatStatus.AVAILABLE
    if "few" in classes:
        return SeatStatus.FEW
    if "before" in classes:
        return SeatStatus.UNSOLD
    if "ng" in classes:
        if any(kw in txt for kw in ("満席", "売切", "売り切れ")):
            return SeatStatus.FULL
        return SeatStatus.UNSOLD

    if "余裕" in txt or "◎" in txt:
        return SeatStatus.AVAILABLE
    if "わずか" in txt or "△" in txt:
        return SeatStatus.FEW
    if any(kw in txt for kw in ("満席", "売切", "売り切れ")):
        return SeatStatus.FULL
    if any(kw in txt for kw in ("販売終了", "販売前", "終了", "－")):
        return SeatStatus.UNSOLD
    return SeatStatus.UNKNOWN


def _extract_balanced_elements(
    html: str,
    tag_name: str,
    open_tag_pattern: re.Pattern,
) -> List[tuple[str, str]]:
    """
    ネストした同種タグ（例: <section>, <div class="block">）に対して、
    開始タグ属性文字列と内部HTMLのペアを安定抽出する。
    """
    tag_re = re.compile(rf"<(/?){tag_name}\b([^>]*)>", re.IGNORECASE)
    results: List[tuple[str, str]] = []
    pos = 0

    while True:
        start_m = open_tag_pattern.search(html, pos)
        if not start_m:
            break

        attr_str = start_m.group(1) if start_m.lastindex else ""
        content_start = start_m.end()
        depth = 1
        end_pos = len(html)

        for tag_m in tag_re.finditer(html, content_start):
            is_close = tag_m.group(1) == "/"
            if is_close:
                depth -= 1
                if depth == 0:
                    results.append((attr_str, html[content_start : tag_m.start()]))
                    pos = tag_m.end()
                    break
            else:
                depth += 1
        else:
            results.append((attr_str, html[content_start:end_pos]))
            break

    return results


def _get_attr(attr_str: str, attr_name: str) -> str:
    """タグ属性文字列から指定属性の値を抽出する。"""
    m = re.search(
        rf'\b{re.escape(attr_name)}\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
        attr_str,
        re.IGNORECASE,
    )
    if not m:
        return ""
    return html_lib.unescape(m.group(1) if m.group(1) is not None else (m.group(2) or "")).strip()


def parse_smt_schedule_html(
    html: str,
    theater_slug: str,
    theater_code: str,
    booking_url_builder: Callable[[str, str, Optional[Dict[str, str]]], str],
    info_url_builder: Optional[Callable[[Optional[str], str], Optional[str]]] = None,
) -> List[MovieSchedule]:
    """
    SMTの日別スケジュールHTML断片（s0100_{code}_{YYYYMMDD}_schedule_daily_movie_area.html）
    をパースして MovieSchedule のリストを返す。
    """
    movies: List[MovieSchedule] = []
    if not html or not html.strip():
        return movies

    # 外側 <section class="daily"> ではなく、各作品の <section class="{mo} {cinemaid}"> を抽出
    section_open_re = re.compile(
        r'<section\b([^>]*\bclass\s*=\s*["\'](?!daily\b)[^"\']+["\'][^>]*)>',
        re.IGNORECASE,
    )
    sections = _extract_balanced_elements(html, "section", section_open_re)

    block_open_re = re.compile(
        r'<div\b([^>]*\bclass\s*=\s*["\'][^"\']*\bblock\b[^"\']*["\'][^>]*)>',
        re.IGNORECASE,
    )

    for sec_idx, (sec_attrs, sec_html) in enumerate(sections, start=1):
        sec_class = _get_attr(sec_attrs, "class")
        class_tokens = sec_class.split()

        detail_m = re.search(
            r'<p[^>]*class=["\'][^"\']*detailLink[^"\']*["\'][^>]*>.*?href=["\']([^"\']+)["\']',
            sec_html,
            re.DOTALL | re.IGNORECASE,
        )
        raw_detail_href = detail_m.group(1) if detail_m else None

        movie_id = ""
        if class_tokens and re.fullmatch(r"[A-Za-z0-9_-]+", class_tokens[0]):
            movie_id = class_tokens[0]
        elif raw_detail_href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_detail_href).query)
            movie_id = (qs.get("mo") or qs.get("cinemaid") or [""])[0]
        if not movie_id:
            movie_id = f"smt_movie_{sec_idx}"

        h2_m = re.search(r"<h2\b[^>]*>(.*?)</h2>", sec_html, re.DOTALL | re.IGNORECASE)
        if not h2_m:
            continue
        h2_html = h2_m.group(1)

        en_m = re.search(
            r'<span[^>]*class=["\'][^"\']*enLabel[^"\']*["\'][^>]*>(.*?)</span>',
            h2_html,
            re.DOTALL | re.IGNORECASE,
        )
        title_en = _clean_text(en_m.group(1)) if en_m else ""
        h2_ja_only = re.sub(
            r'<span[^>]*class=["\'][^"\']*enLabel[^"\']*["\'][^>]*>.*?</span>',
            "",
            h2_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        title_ja = clean_smt_movie_title(h2_ja_only)
        if not title_ja:
            continue

        info_url = info_url_builder(raw_detail_href, theater_slug) if info_url_builder else None

        movie_tag_m = re.search(
            r'<p[^>]*class=["\'][^"\']*tag[^"\']*["\'][^>]*>(.*?)</p>',
            sec_html,
            re.DOTALL | re.IGNORECASE,
        )
        movie_tag_text = _clean_text(movie_tag_m.group(1)) if movie_tag_m else ""

        blocks = _extract_balanced_elements(sec_html, "div", block_open_re)
        screenings: List[Screening] = []

        for blk_idx, (_, blk_html) in enumerate(blocks, start=1):
            h3_m = re.search(r"<h3\b[^>]*>(.*?)</h3>", blk_html, re.DOTALL | re.IGNORECASE)
            screen_name = normalize_smt_screen_name(h3_m.group(1) if h3_m else "")

            inner_m = re.search(
                r'<div\b([^>]*\bclass\s*=\s*["\'][^"\']*\binner\b[^"\']*["\'][^>]*)>',
                blk_html,
                re.IGNORECASE,
            )
            inner_attrs = inner_m.group(1) if inner_m else ""
            inner_class = _get_attr(inner_attrs, "class")
            inner_id = _get_attr(inner_attrs, "id")
            data_event_id = _get_attr(inner_attrs, "data-event-id")

            time_m = re.search(
                r'<p[^>]*class=["\'][^"\']*time[^"\']*["\'][^>]*>(.*?)</p>',
                blk_html,
                re.DOTALL | re.IGNORECASE,
            )
            if not time_m:
                continue
            time_text = _clean_text(time_m.group(1))
            t_match = re.search(r"(\d{1,2}:\d{2})\s*[～~〜\-ー]?\s*(\d{1,2}:\d{2})", time_text)
            if not t_match:
                continue
            start_time = _pad_hhmm(t_match.group(1))
            end_time = _pad_hhmm(t_match.group(2))

            p_text_m = re.search(
                r'<p[^>]*class=["\'][^"\']*text[^"\']*["\'][^>]*>(.*?)</p>',
                blk_html,
                re.DOTALL | re.IGNORECASE,
            )
            slot_text = _clean_text(p_text_m.group(1)) if p_text_m else ""

            sheet_m = re.search(
                r'<span\b([^>]*\bclass\s*=\s*["\'][^"\']*\bsheet\b[^"\']*["\'][^>]*)>(.*?)</span>',
                blk_html,
                re.DOTALL | re.IGNORECASE,
            )
            sheet_class = _get_attr(sheet_m.group(1), "class") if sheet_m else inner_class
            sheet_label = _clean_text(sheet_m.group(2)) if sheet_m else slot_text
            seat_status = map_smt_seat_status(sheet_class or inner_class, sheet_label or slot_text)

            is_purchasable = seat_status in (SeatStatus.AVAILABLE, SeatStatus.FEW)
            booking_url = ""
            event_id = ""
            legacy_match = _LEGACY_INNER_ID_RE.match(inner_id)

            if data_event_id:
                event_id = data_event_id
                if is_purchasable:
                    try:
                        booking_url = booking_url_builder(theater_slug, data_event_id, None)
                    except UnsafeUrlError:
                        booking_url = ""
            elif legacy_match:
                event_id = inner_id
                if is_purchasable:
                    legacy_params = {
                        "th": legacy_match.group(1),
                        "mo": legacy_match.group(2),
                        "sd": legacy_match.group(3),
                        "pe": legacy_match.group(4),
                        "sc": legacy_match.group(5),
                        "fl": legacy_match.group(6),
                    }
                    try:
                        booking_url = booking_url_builder(theater_slug, inner_id, legacy_params)
                    except UnsafeUrlError:
                        booking_url = ""
            else:
                event_id = f"{movie_id}_{blk_idx}_{start_time.replace(':', '')}"

            tags = extract_special_tags(title_ja, movie_tag_text, screen_name, slot_text)

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


class SmtCinemaProvider(BaseCinemaProvider):
    """
    松竹マルチプレックスシアターズ（SMT / MOVIX・ピカデリー・東劇 全23直営館）向けスケジュール取得Provider
    スケジュールHTML: https://www.smt-cinema.com/html/site/pc/schedule/s0100_{code}_{YYYYMMDD}_schedule_daily_movie_area.html
    """

    CHAIN_ID: str = "smt"
    BASE_URL: str = "https://www.smt-cinema.com"
    SMART_BOOKING_URL: str = "https://memberlogin.smart.smt-cinema.jp/purchase/guest"
    LEGACY_BOOKING_URL: str = "https://ticket.smt-cinema.com/ticket/f0100.do"

    def __init__(self, timeout: int = 15):
        super().__init__(timeout=timeout)
        self.default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _fetch_schedule_html(self, theater_code: str, target_date: date) -> str:
        """指定劇場コード・日付のスケジュールHTML断片を取得する（404時は空文字）。"""
        safe_code = sanitize_identifier(str(theater_code))
        date_str = target_date.strftime("%Y%m%d")
        url = build_safe_url(
            self.BASE_URL,
            path_segments=[
                "html",
                "site",
                "pc",
                "schedule",
                f"s0100_{safe_code}_{date_str}_schedule_daily_movie_area.html",
            ],
        )

        req = urllib.request.Request(url, headers=self.default_headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""
            raise RuntimeError(
                f"SMT スケジュール取得に失敗しました (code={safe_code}, HTTP {e.code} {e.reason})"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"SMT スケジュール取得に失敗しました (code={safe_code}): {e}"
            ) from e

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        SMTの予約URL（Smart Theaterゲスト購入URL / レガシーチケット購入URL）を安全に構築する。
        """
        sanitize_identifier(theater_id)
        legacy_keys = ("th", "mo", "sd", "pe", "sc", "fl")

        if extra_params and all(extra_params.get(k) for k in legacy_keys):
            query = {
                k: sanitize_identifier(str(extra_params[k]))
                for k in legacy_keys
            }
            return build_safe_url(self.LEGACY_BOOKING_URL, query_params=query)

        legacy_m = _LEGACY_INNER_ID_RE.match(event_id or "")
        if legacy_m:
            query = {
                "th": sanitize_identifier(legacy_m.group(1)),
                "mo": sanitize_identifier(legacy_m.group(2)),
                "sd": sanitize_identifier(legacy_m.group(3)),
                "pe": sanitize_identifier(legacy_m.group(4)),
                "sc": sanitize_identifier(legacy_m.group(5)),
                "fl": sanitize_identifier(legacy_m.group(6)),
            }
            return build_safe_url(self.LEGACY_BOOKING_URL, query_params=query)

        safe_event_id = sanitize_identifier(event_id)
        return build_safe_url(
            self.SMART_BOOKING_URL,
            query_params={"eventId": safe_event_id},
        )

    def build_movie_info_url(
        self,
        raw_href: Optional[str],
        theater_slug: str,
    ) -> Optional[str]:
        """SMT公式サイトの作品詳細URLを検証・構築する。"""
        safe_slug = sanitize_identifier(theater_slug)
        fallback = build_safe_url(f"{self.BASE_URL}/site/{safe_slug}/")

        if not raw_href or not isinstance(raw_href, str):
            return fallback

        unescaped = html_lib.unescape(raw_href).strip()
        if not unescaped or "javascript:" in unescaped.lower():
            return fallback

        parsed = urllib.parse.urlparse(unescaped)
        if parsed.scheme and parsed.scheme != "https":
            return fallback
        if parsed.netloc and (parsed.hostname or "").lower() != "www.smt-cinema.com":
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
            target_url = f"{self.BASE_URL}/" + "/".join(safe_segments) + trailing
            return build_safe_url(target_url, query_params=safe_params or None)
        except UnsafeUrlError:
            return fallback

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        safe_theater = sanitize_identifier(theater_id)
        theater_info = self.get_theater_info(safe_theater)
        theater_code = str(theater_info.get("code") or "").strip()
        if not theater_code:
            raise ValueError(f"Theater '{safe_theater}' has no SMT theater code")

        html = self._fetch_schedule_html(theater_code, target_date)
        return parse_smt_schedule_html(
            html=html,
            theater_slug=safe_theater,
            theater_code=theater_code,
            booking_url_builder=self.build_booking_url,
            info_url_builder=self.build_movie_info_url,
        )
