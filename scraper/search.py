"""
地域（都道府県・地方）および作品名によるシネコン横断上映スケジュール検索
"""
import concurrent.futures
import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

JST = timezone(timedelta(hours=9))

from .area import get_theaters_by_area
from .models import (
    CrossTheaterScreening,
    CrossTheaterSearchResponse,
    MovieSchedule,
    SeatStatus,
)
from .providers import get_provider
from .sanitizer import sanitize_identifier


def clean_query_title(text: str) -> str:
    """検索照合用に作品タイトルから上映方式タグや記号・空白を除去・正規化する"""
    if not text:
        return ""
    t = re.sub(r"[\s　]+", "", text)
    t = re.sub(r"（[^）]+）|\([^\)]+\)|【[^】]+】|\[[^\]]+\]|※.*$", "", t)
    t = re.sub(
        r"(IMAX|4DX|BESTIA|Dolby|ATMOS|ScreenX|レーザー|3D|2D|字幕|吹替|通常版|応援上映|リマスター|先行上映|R15\+|R18\+|PG12|G)+",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"[/・\-_]+", "", t)
    return t.lower()


def is_movie_match(movie_title: str, query_title: str) -> bool:
    """
    劇場の作品タイトルが検索クエリと一致（または部分一致）するか判定する
    """
    cleaned_query = clean_query_title(query_title)
    if not cleaned_query:
        return False

    cleaned_title = clean_query_title(movie_title)
    if not cleaned_title:
        return False

    # 1. 完全一致
    if cleaned_query == cleaned_title:
        return True

    # 2. クエリが2文字以上の場合の部分一致
    if len(cleaned_query) >= 2 and (cleaned_query in cleaned_title or cleaned_title in cleaned_query):
        return True

    return False


def search_cross_theater(
    title: str,
    area: str,
    target_date: date,
    after_time: Optional[str] = None,
    max_workers: int = 12,
    timeout: int = 15,
) -> CrossTheaterSearchResponse:
    """
    指定された地域内の全チェーン劇場から、指定作品の上映スケジュールを並行取得して時刻順に集約する。
    after_time が指定されている場合（"HH:MM" 形式）、その時刻以降に開始される上映回のみに絞り込む。
    """
    target_theaters = get_theaters_by_area(area)
    if not target_theaters:
        return CrossTheaterSearchResponse(
            query_title=title,
            area=area,
            target_date=target_date.isoformat(),
            total_screenings=0,
            screenings=[],
        )

    # after_time の正規化 ("H:MM" -> "0H:MM")
    normalized_after_time: Optional[str] = None
    if after_time:
        at = after_time.strip()
        if len(at) == 4 and at[1] == ":":
            at = "0" + at
        normalized_after_time = at

    # 各劇場のスケジュールを並行フェッチ
    def fetch_theater_movies(t_info: dict) -> List[tuple[dict, MovieSchedule]]:
        c_id = t_info["chain_id"]
        t_id = t_info["theater_id"]
        try:
            provider = get_provider(c_id)
            movies = provider.fetch_movies(t_id, target_date)
            # マッチする映画のみ抽出
            matched = []
            for m in movies:
                if is_movie_match(m.movie_title, title):
                    matched.append((t_info, m))
            return matched
        except Exception:
            return []

    screenings_all: List[CrossTheaterScreening] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(target_theaters))) as executor:
        futures = [executor.submit(fetch_theater_movies, t) for t in target_theaters]
        for f in concurrent.futures.as_completed(futures):
            try:
                matched_pairs = f.result()
                for t_info, movie in matched_pairs:
                    for s in movie.screenings:
                        st = s.start_time or ""
                        if len(st) == 4 and st[1] == ":":
                            st = "0" + st
                        et = s.end_time or ""
                        if len(et) == 4 and et[1] == ":":
                            et = "0" + et

                        # after_time フィルタ（指定時刻より前の回はスキップ）
                        if normalized_after_time and st and st < normalized_after_time:
                            continue

                        screenings_all.append(
                            CrossTheaterScreening(
                                chain_id=t_info["chain_id"],
                                theater_id=t_info["theater_id"],
                                theater_name=t_info["theater_name"],
                                screen_name=s.screen_name,
                                start_time=st,
                                end_time=et,
                                seat_status=s.seat_status,
                                booking_url=s.booking_url,
                                movie_title=movie.movie_title,
                                tags=s.tags,
                                info_url=movie.info_url,
                            )
                        )
            except Exception:
                continue

    def sort_key(s: CrossTheaterScreening):
        t = s.start_time or "99:99"
        if len(t) == 4 and t[1] == ":":
            t = "0" + t
        return (t, s.theater_name)

    # 上映開始時刻順でソート（同じ時刻なら劇場名順）
    screenings_all.sort(key=sort_key)

    return CrossTheaterSearchResponse(
        query_title=title,
        area=area,
        target_date=target_date.isoformat(),
        total_screenings=len(screenings_all),
        screenings=screenings_all,
    )
