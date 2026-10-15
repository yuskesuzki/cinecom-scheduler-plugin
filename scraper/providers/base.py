from abc import ABC, abstractmethod
from datetime import date
from typing import List, Dict, Optional
import json
from pathlib import Path
from ..models import MovieSchedule, TheaterScheduleResponse
from ..sanitizer import build_safe_url, sanitize_identifier


class BaseCinemaProvider(ABC):
    """全シネコンProviderの抽象基底クラス"""

    CHAIN_ID: str = ""
    BASE_BOOKING_URL: str = ""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.default_headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) CinemaSchedulePlugin/1.0"
        }
        self._theaters_cache: Optional[Dict[str, dict]] = None

    def _load_theaters_master(self) -> Dict[str, dict]:
        """data/theaters.json から自チェーンの劇場マスタを読み込む"""
        if self._theaters_cache is not None:
            return self._theaters_cache

        master_path = Path(__file__).resolve().parents[2] / "data" / "theaters.json"
        if not master_path.exists():
            self._theaters_cache = {}
            return self._theaters_cache

        with master_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        for chain in data.get("chains", []):
            if chain.get("id") == self.CHAIN_ID:
                self._theaters_cache = {
                    t["id"]: t for t in chain.get("theaters", [])
                }
                return self._theaters_cache

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
        シネコン固有のURL構造がある場合はサブクラスでオーバーライドしつつ、
        内部で必ず sanitize_identifier と build_safe_url を使用する。
        """
        safe_theater = sanitize_identifier(theater_id)
        safe_event = sanitize_identifier(event_id)

        params = {"theater": safe_theater, "event": safe_event}
        if extra_params:
            params.update(extra_params)

        return build_safe_url(self.BASE_BOOKING_URL, query_params=params)

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
