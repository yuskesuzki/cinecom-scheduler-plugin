from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request

from ...models import MovieSchedule
from ...sanitizer import UnsafeUrlError, build_safe_url, sanitize_identifier

DEFAULT_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class BaseOtherStrategy(ABC):
    """
    共同経営・独立系劇場（other）向けのスクレイピング Strategy 基底クラス。
    各配信システムまたは単館ごとにサブクラス化し、STRATEGY_REGISTRY に登録する。
    """

    ADAPTER_ID: str = ""

    def __init__(
        self,
        timeout: int = 15,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.timeout = timeout
        self.default_headers = dict(headers or DEFAULT_HEADERS)

    def _fetch_html(
        self, url: str, encoding: str = "utf-8", context: str = ""
    ) -> str:
        """URLからHTMLを取得する（404時は空文字列、その他エラーは RuntimeError）。"""
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

    @abstractmethod
    def fetch_movies(
        self, theater_info: Dict[str, Any], target_date: date
    ) -> List[MovieSchedule]:
        """指定劇場情報と日付に対するスケジュール一覧を取得・パースする。"""

    def build_booking_url(
        self,
        theater_info: Dict[str, Any],
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        座席予約購入URLを構築する。
        オンライン予約を持たない独立系館・ミニシアターでは空文字を返す。
        """
        return ""

    def build_movie_info_url(
        self, theater_info: Dict[str, Any], raw_href: Optional[str]
    ) -> str:
        """
        劇場の公式サイトドメイン（theater_info['base_url']）と一致する
        HTTPS作品詳細URLを検証・再構築し、不正・欠損時は official_url へフォールバックする。
        """
        base_url = theater_info.get("base_url") or ""
        fallback = theater_info.get("official_url") or base_url

        if not raw_href or not isinstance(raw_href, str):
            return fallback

        joined = urllib.parse.urljoin(base_url + "/", raw_href.strip())
        parsed = urllib.parse.urlparse(joined)
        expected_host = (urllib.parse.urlparse(base_url).hostname or "").lower()

        if (
            not expected_host
            or parsed.scheme != "https"
            or (parsed.hostname or "").lower() != expected_host
        ):
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
