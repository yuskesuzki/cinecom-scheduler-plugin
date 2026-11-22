import html as html_lib
import re
from typing import List, Optional, Tuple

FULLWIDTH_TRANS = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ－＿：～（）　",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz-_~:() ",
)


def clean_text(raw_html: str) -> str:
    """HTML片からタグを除去し、実体参照デコードおよび空白正規化を行う。"""
    no_tags = re.sub(r"<[^>]+>", " ", raw_html or "")
    return re.sub(r"\s+", " ", html_lib.unescape(no_tags)).strip()


def pad_hhmm(time_str: str) -> str:
    """'8:05' のような時刻文字列を '08:05' にゼロ埋め正規化する。"""
    parts = time_str.strip().split(":")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}:{parts[1]}"
    return time_str.strip()


def strip_runtime_suffix(raw_title: str) -> str:
    """
    作品タイトル末尾の本編時間表記（例: '（本編：135分）'）を取り除く。
    """
    cleaned = clean_text(raw_title)
    cleaned = re.sub(
        r"\s*[（(]\s*本編\s*[：:]\s*[0-9０-９]+>?\s*分\s*[）)]\s*$",
        "",
        cleaned,
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_screen_name(raw_name: str) -> str:
    """
    スクリーン名を正規化する。
    - 'シアター５' -> 'シアター5'
    - 'DolbyCinema' / 'DOLBY CINEMA' -> 'Dolby Cinema'
    - 'スクリーン1 [4階]' -> 'スクリーン1'
    - 'シアター'（東劇）や 'プラチナ'（新宿）はそのまま保持
    """
    cleaned = clean_text(raw_name)
    if not cleaned:
        return "シアター未定"

    normalized = cleaned.translate(FULLWIDTH_TRANS)
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
    作品タイトル・タグ・スクリーン名・回テキストから特殊設備タグのみ抽出する。
    (NEW, LAST, レイトショー, 特別興行, 特別料金, バリアフリー, 字幕, 吹替, 2D は除外)
    """
    tags: List[str] = []
    texts = [s for s in text_sources if s]
    if not texts:
        return tags

    combined = " ".join(texts).translate(FULLWIDTH_TRANS)
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


def extract_balanced_elements(
    html: str,
    tag_name: str,
    open_tag_pattern: re.Pattern,
) -> List[Tuple[str, str]]:
    """
    ネストした同種タグ（例: <section>, <div class="block">, <table>, <td>）に対して、
    開始タグ属性文字列と内部HTMLのペアを安定抽出する。
    """
    tag_re = re.compile(rf"<(/?){tag_name}\b([^>]*)>", re.IGNORECASE)
    results: List[Tuple[str, str]] = []
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


def get_attr(attr_str: str, attr_name: str) -> str:
    """タグ属性文字列から指定属性の値を抽出する。"""
    m = re.search(
        rf'\b{re.escape(attr_name)}\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
        attr_str,
        re.IGNORECASE,
    )
    if not m:
        return ""
    return html_lib.unescape(
        m.group(1) if m.group(1) is not None else (m.group(2) or "")
    ).strip()
