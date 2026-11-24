from abc import ABC, abstractmethod
from datetime import date
from typing import List, Dict, Optional
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from ..models import MovieSchedule, TheaterScheduleResponse
from ..sanitizer import UnsafeUrlError, build_safe_url, sanitize_identifier


DEFAULT_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class BaseCinemaProvider(ABC):
    """全シネコンProviderの抽象基底クラス"""

    CHAIN_ID: str = ""
    BASE_BOOKING_URL: str = ""

    def __init__(
        self,
        timeout: int = 15,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.timeout = timeout
        self.default_headers = dict(headers or DEFAULT_HEADERS)
        self._theaters_cache: Optional[Dict[str, dict]] = None

    def _fetch_html(
        self,
        url: str,
        encoding: str = "utf-8",
        context: str = "",
        data: Optional[bytes] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        ignore_404: bool = True,
    ) -> str:
        """URLからHTML/テキストを取得する（404かつignore_404時は空文字列、その他エラーは RuntimeError）。"""
        headers = dict(self.default_headers)
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, data=data, headers=headers)
        label = self.CHAIN_ID or "cinema"
        ctx = f", {context}" if context else ""
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode(encoding, errors="replace")
        except urllib.error.HTTPError as e:
            code, reason = e.code, e.reason
            e.close()
            if ignore_404 and code == 404:
                return ""
            raise RuntimeError(
                f"{label} スケジュール取得に失敗しました (HTTP {code} {reason}{ctx})"
            ) from e
        except Exception as e:
            ctx_prefix = f"({context}) " if context else ""
            raise RuntimeError(
                f"{label} スケジュール取得に失敗しました {ctx_prefix}: {e}"
            ) from e

    def _load_theaters_master(self) -> Dict[str, dict]:
        """data/theaters/{CHAIN_ID}.json (または data/theaters.json) から自チェーンの劇場マスタを読み込む"""
        if self._theaters_cache is not None:
            return self._theaters_cache

        base_dir = Path(__file__).resolve().parents[2] / "data"

        # 1. チェーン個別ファイル (data/theaters/{chain_id}.json) を優先読み込み
        chain_path = base_dir / "theaters" / f"{self.CHAIN_ID}.json"
        if chain_path.exists():
            try:
                with chain_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                self._theaters_cache = {
                    t["id"]: t for t in data.get("theaters", [])
                }
                return self._theaters_cache
            except Exception:
                pass

        # 2. 従来の統合マスタ (data/theaters.json) から読み込み (フォールバック)
        master_path = base_dir / "theaters.json"
        if master_path.exists():
            try:
                with master_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                for chain in data.get("chains", []):
                    if chain.get("id") == self.CHAIN_ID:
                        self._theaters_cache = {
                            t["id"]: t for t in chain.get("theaters", [])
                        }
                        return self._theaters_cache
            except Exception:
                pass

        self._theaters_cache = {}
        return self._theaters_cache

    def get_theater_info(self, theater_id: str) -> dict:
        """theater_id から劇場マスタ情報（code, name等）を取得する"""
        safe_id = sanitize_identifier(theater_id)
        theaters = self._load_theaters_master()
        return theaters.get(safe_id, {"id": safe_id, "code": safe_id, "name": safe_id})

    def get_theater_name(self, theater_id: str) -> str:
        return self.get_theater_info(theater_id).get("name", theater_id)

    @abstractmethod
    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        """
        シネコン固有のAPI/HTMLからデータを取得し、MovieScheduleのリストに変換して返す。
        """
        pass

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        sanitizer を経由して安全な予約URLを生成する共通ヘルパー。
        BASE_BOOKING_URL が空（オンライン予約非対応の独立系館・ミニシアター等）の場合は空文字を返す。
        シネコン固有のURL構造がある場合はサブクラスでオーバーライドしつつ、
        内部で必ず sanitize_identifier と build_safe_url を使用する。
        """
        safe_theater = sanitize_identifier(theater_id)
        if not self.BASE_BOOKING_URL:
            return ""

        safe_event = sanitize_identifier(event_id)

        params = {"theater": safe_theater, "event": safe_event}
        if extra_params:
            params.update(extra_params)

        return build_safe_url(self.BASE_BOOKING_URL, query_params=params)

    def build_same_host_info_url(
        self,
        base_url: str,
        raw_href: Optional[str],
        fallback: str = "",
    ) -> str:
        """
        base_url と同一ホストの HTTPS 作品詳細URLを検証・再構築し、
        不正・欠損時は fallback（未指定時は base_url）へフォールバックする。
        """
        resolved_fallback = fallback or base_url or ""
        if not base_url or not raw_href or not isinstance(raw_href, str):
            return resolved_fallback

        joined = urllib.parse.urljoin(base_url.rstrip("/") + "/", raw_href.strip())
        parsed = urllib.parse.urlparse(joined)
        expected_host = (urllib.parse.urlparse(base_url).hostname or "").lower()

        if (
            not expected_host
            or parsed.scheme != "https"
            or (parsed.hostname or "").lower() != expected_host
        ):
            return resolved_fallback

        segments = [seg for seg in parsed.path.split("/") if seg]
        if not segments:
            return resolved_fallback

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
            return resolved_fallback

    def resolve_movie_info_url(
        self, theater_id: str, raw_href: Optional[str]
    ) -> str:
        """
        劇場マスタの base_url / official_url を用いて同一ホストの作品詳細URLを検証・解決する。
        """
        theater_info = self.get_theater_info(theater_id)
        base_url = theater_info.get("base_url") or ""
        fallback = theater_info.get("official_url") or base_url
        return self.build_same_host_info_url(base_url, raw_href, fallback=fallback)

    def get_schedule_response(
        self, theater_id: str, target_date: date
    ) -> TheaterScheduleResponse:
        """CLIから呼び出されるテンプレートメソッド"""
        safe_theater_id = sanitize_identifier(theater_id)
        movies = self.fetch_movies(safe_theater_id, target_date)
        return TheaterScheduleResponse(
            chain_id=self.CHAIN_ID,
            theater_id=safe_theater_id,
            theater_name=self.get_theater_name(safe_theater_id),
            target_date=target_date.isoformat(),
            movies=movies,
        )
