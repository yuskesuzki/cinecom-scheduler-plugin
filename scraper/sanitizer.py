import re
from typing import Dict, Optional, Set, List
from urllib.parse import urlparse, urlencode, quote, urlunparse


# 予約URL・作品詳細URLとして許可するシネコン公式ドメインのホワイトリスト
ALLOWED_DOMAINS: Set[str] = {
    "cinema.aeoncinema.com",
    "reserve.aeoncinema.com",
    "login.watatheatre.aeoncinema.com",
    "theater.aeoncinema.com",
    "www.aeoncinema.com",
    "hlo.tohotheater.jp",
    "www.tohotheater.jp",
    "www.unitedcinemas.jp",
    "transaction.ticket-cinemasunshine.com",
    "ticket-cinemasunshine.com",
    "www.cinemasunshine.co.jp",
    "cinemasunshine.co.jp",
}

# 制御文字の検出パターン
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


class UnsafeUrlError(ValueError):
    """安全性チェックに失敗した識別子またはURLに対する例外"""
    pass


def sanitize_identifier(raw_id: str, max_length: int = 64) -> str:
    """
    外部APIから取得した event_id や theater_code を検証する。
    英数字・ハイフン・アンダースコア・ドットのみを許容し、
    パストラバーサル（..）や先頭ハイフン、シェルメタ文字を含む場合は例外を送出する。
    """
    if not raw_id or not isinstance(raw_id, str) or len(raw_id) > max_length:
        raise UnsafeUrlError(f"Invalid identifier length or type: {raw_id!r}")
    if ".." in raw_id or raw_id.startswith("-") or raw_id.startswith("."):
        raise UnsafeUrlError(f"Unsafe sequence in identifier: {raw_id!r}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", raw_id):
        raise UnsafeUrlError(f"Unsafe characters detected in identifier: {raw_id!r}")
    return raw_id


def build_safe_url(
    base_url: str,
    path_segments: Optional[List[str]] = None,
    query_params: Optional[Dict[str, str]] = None,
) -> str:
    """
    安全な予約URLを構築する。
    - スキームは https のみ許可
    - ホスト名は ALLOWED_DOMAINS に含まれるもののみ許可
    - パスとクエリパラメータはすべてパーセントエンコード
    """
    if not base_url or _CONTROL_CHARS_RE.search(base_url):
        raise UnsafeUrlError("Base URL is empty or contains control characters.")

    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise UnsafeUrlError(f"Only 'https' scheme is allowed, got: {parsed.scheme!r}")

    if parsed.hostname not in ALLOWED_DOMAINS:
        raise UnsafeUrlError(f"Domain not in allowlist: {parsed.hostname!r}")

    if path_segments:
        base_path = parsed.path.rstrip("/")
        encoded_segments = [quote(str(seg), safe="") for seg in path_segments]
        full_path = f"{base_path}/" + "/".join(encoded_segments)
    else:
        full_path = parsed.path or "/"

    encoded_query = urlencode(query_params, doseq=True) if query_params else parsed.query

    safe_url = urlunparse((
        "https",
        parsed.netloc,
        full_path,
        "",
        encoded_query,
        "",
    ))
    return safe_url
