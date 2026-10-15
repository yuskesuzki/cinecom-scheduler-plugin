from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Any
import json


class SeatStatus(str, Enum):
    """座席の空き状況を表す共通ステータス"""
    AVAILABLE = "available"  # ◎ / 余裕あり
    FEW = "few"              # △ / 残りわずか
    FULL = "full"            # × / 満席
    UNSOLD = "unsold"        # - / 販売前・対象外
    UNKNOWN = "unknown"      # 取得失敗・不明


@dataclass
class Screening:
    """1回分の上映枠データ"""
    event_id: str
    screen_name: str
    start_time: str          # "HH:MM" 形式
    end_time: str            # "HH:MM" 形式
    seat_status: SeatStatus
    booking_url: str         # sanitizer検証済みの安全な予約URL
    tags: List[str] = field(default_factory=list)  # ["IMAX", "字幕", "3D"] 等


@dataclass
class MovieSchedule:
    """作品ごとの上映スケジュール"""
    movie_id: str
    movie_title: str
    screenings: List[Screening] = field(default_factory=list)


@dataclass
class TheaterScheduleResponse:
    """QML側へ返すルートJSON構造"""
    chain_id: str
    theater_id: str
    theater_name: str
    target_date: str         # "YYYY-MM-DD" 形式
    movies: List[MovieSchedule] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
