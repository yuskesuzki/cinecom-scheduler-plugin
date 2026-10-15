#!/usr/bin/env python3
"""
イオンシネマ 上映スケジュールスクレイパー

指定した劇場・日付の上映スケジュール（映画タイトル、上映時間、スクリーン、空席状況等）を取得します。
イオンシネマのWebサイト内部で使用されている公式データAPIエンドポイントから最新のJSONデータを直接取得するため、
高速・軽量かつヘッドレスブラウザ不要で動作します。

使用例:
  python3 aeoncinema_scraper.py "https://theater.aeoncinema.com/theaters/ebetsu/?date=20261012"
  python3 aeoncinema_scraper.py ebetsu --date 20261012
  python3 aeoncinema_scraper.py ebetsu --format json
  python3 aeoncinema_scraper.py ebetsu --timetable
"""

import argparse
import csv
from datetime import datetime, timezone, timedelta
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# 日本時間 (JST: UTC+9)
JST = timezone(timedelta(hours=9))
THEATER_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "theater.json")
DEFAULT_CONFIG_DIR = os.path.expanduser("~/.config/aeoncinema-plugin")
DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_CONFIG_DIR, "config.json")


def get_default_config() -> Dict[str, Any]:
    return {
        "theater": "ebetsu",
        "within_hours": 3.0,
        "english_mode": False,
        "format": "text",
    }


def load_user_config(config_path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """設定ファイルを読み込む。存在しない場合はデフォルト設定を返す。"""
    config = get_default_config()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_data = json.load(f)
                if isinstance(user_data, dict):
                    config.update(user_data)
        except Exception as e:
            print(f"警告: 設定ファイルの読み込みに失敗しました ({e})。デフォルト設定を使用します。", file=sys.stderr)
    return config


def save_user_config(config: Dict[str, Any], config_path: str = DEFAULT_CONFIG_PATH) -> None:
    """設定ファイルを保存する。"""
    os.makedirs(os.path.dirname(os.path.abspath(config_path)), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def load_allowed_theaters(json_path: str = THEATER_JSON_PATH) -> List[Dict[str, Any]]:
    """
    theater.json から許可された劇場一覧を読み込む。
    ファイルが存在しない場合は自動生成を試みる。
    """
    if not os.path.exists(json_path):
        try:
            from update_theaters import generate_theater_json
            print(f"'{json_path}' が見つからないため、公式ページから自動生成します...", file=sys.stderr)
            return generate_theater_json(json_path)
        except Exception as e:
            raise RuntimeError(
                f"劇場一覧ファイル '{json_path}' が見つからず、自動生成にも失敗しました: {e}\n"
                f"先に 'python3 update_theaters.py' を実行してください。"
            ) from e

    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_allowed_theater(
    query: str, allowed_theaters: List[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    ユーザーの入力 (ID, 劇場名, 劇場コード) から一致する劇場オブジェクトを検索する。
    完全一致を優先し、見つからない場合は部分一致する候補リストを返す。
    返り値: (マッチした劇場 または None, 類似候補リスト)
    """
    q = query.strip().lower()
    q_norm = q.replace("イオンシネマ", "").replace("シアタス", "").strip()

    # 1. 完全一致 (id, theater_id, name)
    for t in allowed_theaters:
        t_name = t["name"].lower()
        if (
            t["id"].lower() == q
            or t["theater_id"] == q
            or t_name == q
            or t_name == q_norm
            or t_name == f"イオンシネマ{q_norm}"
        ):
            return t, []

    # 2. 部分一致候補
    candidates = []
    for t in allowed_theaters:
        t_id = t["id"].lower()
        t_name = t["name"].lower()
        if q_norm and (q_norm in t_name or q_norm in t_id or t_name in q_norm):
            candidates.append(t)

    if len(candidates) == 1:
        return candidates[0], []

    return None, candidates


def format_theater_list(theaters: List[Dict[str, Any]]) -> str:
    """劇場一覧をエリア別に見やすく整形する"""
    areas: Dict[str, List[Dict[str, Any]]] = {}
    for t in theaters:
        area = t.get("area", "その他")
        areas.setdefault(area, []).append(t)

    lines = [
        "============================================================",
        f" 検索対象 許可劇場一覧 (全{len(theaters)}劇場)",
        " (https://www.aeoncinema.com/theater/ より取得)",
        "============================================================",
    ]

    for area, t_list in areas.items():
        theater_names = ", ".join([f"{t['name']} ({t['id']})" for t in t_list])
        lines.append(f"【{area} ({len(t_list)})】 {theater_names}")

    lines.append("-" * 60)
    lines.append("※ 劇場の指定には、英字ID (例: ebetsu) または 日本語名 (例: 江別) が使用できます。")
    return "\n".join(lines)


def parse_target_url(target: str) -> tuple[str, Optional[str]]:
    """
    指定されたURLまたは劇場識別子から (theater_id, date) を抽出する。
    
    例:
      - "https://theater.aeoncinema.com/theaters/ebetsu/?date=20261012" -> ("ebetsu", "20261012")
      - "ebetsu" -> ("ebetsu", None)
    """
    if "://" in target or "/" in target:
        parsed = urllib.parse.urlparse(target)
        # パスから劇場名を抽出 (例: /theaters/ebetsu/)
        match = re.search(r"/theaters/([^/?#]+)", parsed.path)
        theater = match.group(1) if match else target.strip("/").split("/")[-1]
        
        # クエリパラメータから date を抽出
        query_params = urllib.parse.parse_qs(parsed.query)
        date_param = query_params.get("date", [None])[0]
        return theater, date_param
    
    return target, None


def fetch_schedule_json(theater: str) -> Dict[str, Any]:
    """
    指定劇場のスケジュールJSONを取得する。
    CloudFrontの古いキャッシュを回避するため、キャッシュバスター（クエリパラメータ v）を付与する。
    """
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    url = f"https://theater.aeoncinema.com/schedule/v2/data/{theater}/schedule.json?v={now_str}"
    
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://theater.aeoncinema.com/theaters/{theater}/",
        "Accept": "application/json, text/plain, */*",
    }
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content)
    except urllib.error.HTTPError as e:
        if e.code == 404 or e.code == 403:
            raise RuntimeError(
                f"劇場コード '{theater}' のスケジュールデータが見つかりませんでした (HTTP {e.code})。"
                f"劇場IDが正しいかご確認ください。"
            ) from e
        raise RuntimeError(f"HTTPエラーが発生しました: {e.code} {e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"スケジュールデータの取得に失敗しました: {e}") from e


SPECIAL_BADGES = ["IMAX", "4DX", "VIVE AUDIO", "Dolby Atmos", "THX"]


def detect_special_badges(
    features: List[str],
    screen_name: str,
    extra_texts: Optional[List[str]] = None,
) -> List[str]:
    """
    スクリーン設備タグ、スクリーン名、作品名などから、特殊設備バッジ
    ('IMAX', '4DX', 'VIVE AUDIO', 'Dolby Atmos', 'THX') を抽出する。
    """
    badges = []
    targets = list(features) + [screen_name] + (extra_texts or [])
    for badge in SPECIAL_BADGES:
        b_norm = badge.upper().replace(" ", "")
        for t in targets:
            if not t:
                continue
            t_norm = t.upper().replace(" ", "").replace("ATOMOS", "ATMOS")
            if b_norm in t_norm:
                if badge not in badges:
                    badges.append(badge)
                break
    return badges



def match_screen_facility(
    screen_str: str, screens: Optional[List[Dict[str, Any]]]
) -> Optional[Dict[str, Any]]:
    """スクリーン名（例: 'スクリーン7'）から theater.json の該当スクリーン設備情報を検索する。"""
    if not screens:
        return None
    # 1. 完全一致
    for s in screens:
        if s.get("name") == screen_str:
            return s
    # 2. 数字抽出一致 (例: 'スクリーン7' と '7スクリーン')
    num_m = re.search(r"\d+", screen_str)
    if num_m:
        t_num = num_m.group(0)
        for s in screens:
            s_num = re.search(r"\d+", s.get("name", ""))
            if s_num and s_num.group(0) == t_num:
                return s
    # 3. 部分一致
    for s in screens:
        s_name = s.get("name", "")
        if s_name and (s_name in screen_str or screen_str in s_name):
            return s
    return None


def build_safe_booking_url(event_id: Any) -> Optional[str]:
    """
    ワタシアターのイベントIDを安全に検証・URLエンコードし、予約URLを生成する。
    英数字、ハイフン、アンダースコア（1〜64文字）のみを許可し、悪意あるシェル構文や記号を拒絶する。
    """
    if not event_id or not isinstance(event_id, str):
        return None
    trimmed = event_id.strip()
    if not re.match(r"^[a-zA-Z0-9_\-]{1,64}$", trimmed):
        return None
    safe_id = urllib.parse.quote(trimmed, safe="")
    return f"https://login.watatheatre.aeoncinema.com/auth?eventId={safe_id}"


def to_english_screen(screen_name: str) -> str:
    """スクリーン名を英語表記（例: 'Screen 1'）に変換する"""
    m = re.search(r"スクリーン\s*(\d+)", screen_name)
    if m:
        return f"Screen {m.group(1)}"
    if "未定" in screen_name:
        return "TBD"
    return screen_name


def parse_schedule_for_date(
    raw_data: Dict[str, Any],
    date_str: str,
    lang: str = "ja",
    facility_screens: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    指定日のスケジュールデータをパースして、作品ごとの上映情報リストを作成する。
    lang='en' の場合は英語タイトル（未設定時は日本語タイトル）および英語表記のスクリーン名を優先して設定する。
    facility_screens が渡された場合は各スクリーンに合致する設備情報および特殊設備バッジを付与する。
    """
    day_schedules = raw_data.get(date_str)
    if not day_schedules:
        return []

    movies: List[Dict[str, Any]] = []

    for group_id, events in day_schedules.items():
        if not events:
            continue
        
        first_event = events[0]
        title_ja = (
            first_event.get("name", {}).get("ja")
            or first_event.get("superEvent", {}).get("name", {}).get("ja")
            or "名称未設定"
        )
        title_en = (
            first_event.get("name", {}).get("en")
            or first_event.get("superEvent", {}).get("name", {}).get("en")
            or ""
        )

        display_title = (title_en if title_en else title_ja) if lang == "en" else title_ja

        showtimes: List[Dict[str, Any]] = []
        for ev in events:
            # ISO 8601 UTC 文字列を JST に変換
            start_iso = ev.get("startDate", "")
            end_iso = ev.get("endDate", "")
            
            if start_iso:
                start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(JST)
                start_time = start_dt.strftime("%H:%M")
            else:
                start_time = "--:--"

            if end_iso:
                end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00")).astimezone(JST)
                end_time = end_dt.strftime("%H:%M")
            else:
                end_time = "--:--"

            screen_name_raw = ev.get("location", {}).get("name", {}).get("ja", "スクリーン未定")
            screen_name = to_english_screen(screen_name_raw) if lang == "en" else screen_name_raw

            screen_fac = match_screen_facility(screen_name_raw, facility_screens)
            features = screen_fac.get("features", []) if screen_fac else []
            special_badges = detect_special_badges(
                features, screen_name_raw, extra_texts=[title_ja, title_en]
            )

            max_capacity = ev.get("maximumAttendeeCapacity")
            rem_capacity = ev.get("remainingAttendeeCapacity")

            event_id = ev.get("id") or ev.get("offers", {}).get("itemOffered", {}).get("id")
            booking_url = build_safe_booking_url(event_id)

            showtimes.append({
                "start_time": start_time,
                "end_time": end_time,
                "start_datetime": start_dt.isoformat() if start_iso else None,
                "end_datetime": end_dt.isoformat() if end_iso else None,
                "screen": screen_name,
                "special_badges": special_badges,
                "screen_facility": screen_fac,
                "remaining_seats": rem_capacity,
                "total_seats": max_capacity,
                "event_id": event_id,
                "booking_url": booking_url,
            })

        # 開始時刻順にソート
        showtimes.sort(key=lambda s: s["start_time"])

        first_booking_url = None
        for st in showtimes:
            if st.get("booking_url"):
                first_booking_url = st["booking_url"]
                break

        movies.append({
            "title": display_title,
            "title_ja": title_ja,
            "title_en": title_en,
            "booking_url": first_booking_url,
            "showtimes": showtimes,
        })

    # 各作品の中で最も早い上映開始時刻順にソート (開始時刻が同一の場合はタイトル順)
    movies.sort(
        key=lambda m: (
            m["showtimes"][0]["start_time"] if m.get("showtimes") else "99:99",
            m["title"].lower(),
        )
    )
    return movies


def filter_upcoming_movies(
    movies: List[Dict[str, Any]],
    base_time: datetime,
    within_hours: float = 3.0,
) -> List[Dict[str, Any]]:
    """
    指定した基準時刻（base_time）以降、かつ within_hours 時間以内に上映開始する作品を抽出する。
    """
    limit_time = base_time + timedelta(hours=within_hours)
    filtered_movies: List[Dict[str, Any]] = []

    for m in movies:
        matching_showtimes = []
        for s in m["showtimes"]:
            start_dt_str = s.get("start_datetime")
            if not start_dt_str:
                continue
            start_dt = datetime.fromisoformat(start_dt_str)
            if base_time <= start_dt <= limit_time:
                matching_showtimes.append(s)

        if matching_showtimes:
            movie_copy = dict(m)
            movie_copy["showtimes"] = matching_showtimes
            filtered_movies.append(movie_copy)

    filtered_movies.sort(
        key=lambda m: (
            m["showtimes"][0]["start_time"] if m.get("showtimes") else "99:99",
            m["title"].lower(),
        )
    )
    return filtered_movies


def format_text(
    theater: str,
    date_str: str,
    movies: List[Dict[str, Any]],
    filter_info: Optional[str] = None,
    lang: str = "ja",
) -> str:
    """映画タイトルごとに上映時間をグループ化したテキスト形式"""
    formatted_date = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}" if len(date_str) == 8 else date_str
    if lang == "en":
        lines = [
            f"============================================================",
            f" AEON CINEMA [{theater}] Showtimes ({formatted_date})",
        ]
        if filter_info:
            lines.append(f" [Filter: {filter_info}]")
        lines.append(f" Total Movies: {len(movies)}")
        lines.append(f"============================================================")

        if not movies:
            lines.append("\n* No showtimes found matching the criteria.")
            return "\n".join(lines)

        for m in movies:
            lines.append(f"\n■ {m['title']}")
            for s in m["showtimes"]:
                seat_info = ""
                if s["remaining_seats"] is not None and s["total_seats"] is not None:
                    seat_info = f" [Seats: {s['remaining_seats']}/{s['total_seats']}]"
                badge_str = " " + " ".join(f"[{b}]" for b in s.get("special_badges", [])) if s.get("special_badges") else ""
                lines.append(f"   - {s['start_time']} - {s['end_time']}  ({s['screen']}{badge_str}){seat_info}")

        return "\n".join(lines)

    lines = [
        f"============================================================",
        f" イオンシネマ【{theater}】上映スケジュール ({formatted_date})",
    ]
    if filter_info:
        lines.append(f" [抽出条件: {filter_info}]")
    lines.append(f" 上映作品数: {len(movies)} 作品")
    lines.append(f"============================================================")

    if not movies:
        lines.append("\n※ 条件に一致する上映作品はありませんでした。")
        return "\n".join(lines)

    for m in movies:
        lines.append(f"\n■ {m['title']}")
        for s in m["showtimes"]:
            seat_info = ""
            if s["remaining_seats"] is not None and s["total_seats"] is not None:
                seat_info = f" [残席: {s['remaining_seats']}/{s['total_seats']}]"
            badge_str = " " + " ".join(f"[{b}]" for b in s.get("special_badges", [])) if s.get("special_badges") else ""
            lines.append(f"   ・ {s['start_time']} 〜 {s['end_time']}  ({s['screen']}{badge_str}){seat_info}")

    return "\n".join(lines)


def format_timetable(
    theater: str,
    date_str: str,
    movies: List[Dict[str, Any]],
    filter_info: Optional[str] = None,
    lang: str = "ja",
) -> str:
    """開始時刻順のタイムテーブル形式"""
    formatted_date = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}" if len(date_str) == 8 else date_str
    all_slots = []
    for m in movies:
        for s in m["showtimes"]:
            badge_str = " " + " ".join(f"[{b}]" for b in s.get("special_badges", [])) if s.get("special_badges") else ""
            all_slots.append({
                "title": m["title"],
                "start_time": s["start_time"],
                "end_time": s["end_time"],
                "screen": f"{s['screen']}{badge_str}",
                "remaining_seats": s["remaining_seats"],
                "total_seats": s["total_seats"],
            })

    all_slots.sort(key=lambda x: (x["start_time"], x["screen"]))

    if lang == "en":
        lines = [
            f"============================================================",
            f" AEON CINEMA [{theater}] Timetable ({formatted_date})",
        ]
        if filter_info:
            lines.append(f" [Filter: {filter_info}]")
        lines.append(f" Total Showtimes: {len(all_slots)}")
        lines.append(f"============================================================")

        if not all_slots:
            lines.append("* No showtimes found matching the criteria.")
            return "\n".join(lines)

        lines.extend([
            f"{'Time':<15} | {'Screen':<10} | {'Title'}",
            "-" * 60,
        ])

        for slot in all_slots:
            time_str = f"{slot['start_time']} - {slot['end_time']}"
            lines.append(f"{time_str:<15} | {slot['screen']:<10} | {slot['title']}")

        return "\n".join(lines)

    lines = [
        f"============================================================",
        f" イオンシネマ【{theater}】タイムテーブル順 ({formatted_date})",
    ]
    if filter_info:
        lines.append(f" [抽出条件: {filter_info}]")
    lines.append(f" 上映回数: {len(all_slots)} 回")
    lines.append(f"============================================================")

    if not all_slots:
        lines.append("※ 条件に一致する上映作品はありませんでした。")
        return "\n".join(lines)

    lines.extend([
        f"{'開始〜終了':<15} | {'スクリーン':<10} | {'タイトル'}",
        "-" * 60,
    ])

    for slot in all_slots:
        time_str = f"{slot['start_time']}〜{slot['end_time']}"
        lines.append(f"{time_str:<15} | {slot['screen']:<10} | {slot['title']}")

    return "\n".join(lines)


def format_csv(movies: List[Dict[str, Any]], lang: str = "ja") -> str:
    """CSV形式"""
    output = io.StringIO()
    writer = csv.writer(output)
    if lang == "en":
        writer.writerow(["Title", "Start Time", "End Time", "Screen", "Available Seats", "Total Seats"])
    else:
        writer.writerow(["タイトル", "開始時刻", "終了時刻", "スクリーン", "残席数", "総座席数"])

    for m in movies:
        for s in m["showtimes"]:
            writer.writerow([
                m["title"],
                s["start_time"],
                s["end_time"],
                s["screen"],
                s["remaining_seats"] if s["remaining_seats"] is not None else "",
                s["total_seats"] if s["total_seats"] is not None else "",
            ])
    return output.getvalue()


def normalize_date(date_str: Optional[str]) -> Optional[str]:
    """
    様々な形式の日付文字列を 'YYYYMMDD' 形式に正規化する。
    例:
      - '20261013' -> '20261013'
      - '2026-10-13' -> '20261013'
      - '2026/10/13' -> '20261013'
      - 'today', '今日' -> 当日
      - 'tomorrow', '明日' -> 翌日
    """
    if not date_str:
        return None
    s = date_str.strip()
    if s.lower() in ("yesterday", "昨日"):
        return (datetime.now(JST) - timedelta(days=1)).strftime("%Y%m%d")
    if s.lower() in ("today", "今日"):
        return datetime.now(JST).strftime("%Y%m%d")
    if s.lower() in ("tomorrow", "明日"):
        return (datetime.now(JST) + timedelta(days=1)).strftime("%Y%m%d")
    digits = re.sub(r"\D", "", s)
    if len(digits) == 8:
        return digits
    return s


def parse_base_time(base_time_str: Optional[str], default_date: str) -> datetime:
    """基準日時文字列をパースする (未指定時は target_date の現在時刻 JST)"""
    now = datetime.now(JST)
    year = int(default_date[:4])
    month = int(default_date[4:6])
    day = int(default_date[6:8])

    if not base_time_str:
        return datetime(year, month, day, now.hour, now.minute, now.second, tzinfo=JST)

    base_time_str = base_time_str.strip()
    # "HH:MM" 形式の場合
    if re.match(r"^\d{1,2}:\d{2}$", base_time_str):
        h, m = map(int, base_time_str.split(":"))
        return datetime(year, month, day, h, m, tzinfo=JST)

    # "YYYY-MM-DD HH:MM" などの場合
    try:
        dt = datetime.fromisoformat(base_time_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return dt
    except Exception:
        pass

    raise ValueError(
        f"基準日時の形式が正しくありません: '{base_time_str}' (例: '21:00' または '2026-10-12 21:00')"
    )


def main():
    default_url = "https://theater.aeoncinema.com/theaters/ebetsu/?date=20261012"
    
    parser = argparse.ArgumentParser(
        description="イオンシネマの上映スケジュール（映画タイトル・上映時間）を取得するスクリプト"
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="劇場URL、劇場ID、または日付 (例: 'ebetsu', '20261013', 'https://...')",
    )
    parser.add_argument(
        "date_arg",
        nargs="?",
        default=None,
        help="対象日 (YYYYMMDD形式、例: 20261013。第2引数として指定可能)",
    )
    parser.add_argument(
        "-d", "--date",
        dest="date",
        help="対象日 (例: 20261013, 2026-10-13, 2026/10/13, 今日, 明日)",
    )
    parser.add_argument(
        "-u", "--upcoming",
        action="store_true",
        help="現在時刻以降、指定時間以内（デフォルト3時間以内）に上映開始する作品のみを抽出",
    )
    parser.add_argument(
        "--within-hours",
        type=float,
        default=None,
        help="--upcoming モード時に対象とする上映開始までの時間（時間単位、未指定時は保存設定または 3.0）",
    )
    parser.add_argument(
        "-t", "--time", "--base-time",
        dest="base_time",
        help="基準時刻 (例: '21:00' または '2026-10-12 21:00'。未指定時は現在時刻)",
    )
    parser.add_argument(
        "--lang",
        choices=["ja", "en"],
        default=None,
        help="表示言語 (ja: 日本語, en: 英語, デフォルト: 保存設定または ja)",
    )
    parser.add_argument(
        "--en", "--english",
        action="store_true",
        dest="english",
        help="英語表記モード (--lang en と同等)",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["text", "json", "csv", "timetable"],
        default="text",
        help="出力フォーマット (text: タイトル別テキスト, timetable: 時刻順, json: JSON形式, csv: CSV形式)",
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_file",
        help="出力先ファイルパス (省略時は標準出力)",
    )
    parser.add_argument(
        "--config-file",
        default=DEFAULT_CONFIG_PATH,
        help=f"設定ファイルパス (デフォルト: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--save-config",
        action="store_true",
        help="指定した設定（劇場、直近時間、言語等）を設定ファイルに保存する",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="保存されている設定内容を表示する",
    )
    parser.add_argument(
        "--list-dates",
        action="store_true",
        help="公開されている全日程の一覧のみを表示する",
    )
    parser.add_argument(
        "-l", "--list-theaters",
        action="store_true",
        help="許可されている全劇場の一覧（theater.json）を表示する",
    )
    parser.add_argument(
        "--update-theaters",
        action="store_true",
        help="公式劇場一覧ページから theater.json を再取得・更新する",
    )
    parser.add_argument(
        "--theater-file",
        default=THEATER_JSON_PATH,
        help=f"劇場一覧JSONファイルのパス (デフォルト: {THEATER_JSON_PATH})",
    )

    args = parser.parse_args()

    # 設定ファイルの読み込み
    user_config = load_user_config(args.config_file)

    # 設定表示モード
    if args.show_config:
        print(f"設定ファイル: {args.config_file}")
        print(json.dumps(user_config, ensure_ascii=False, indent=2))
        return

    # 表示言語の決定 (引数指定 > 保存設定 > ja)
    if args.english or args.lang == "en":
        lang = "en"
    elif args.lang == "ja":
        lang = "ja"
    else:
        lang = "en" if user_config.get("english_mode", False) else "ja"

    within_hours = (
        args.within_hours
        if args.within_hours is not None
        else float(user_config.get("within_hours", 3.0))
    )

    # 劇場一覧の更新モード
    if args.update_theaters:
        from update_theaters import generate_theater_json
        generate_theater_json(args.theater_file)
        return

    # 許可された劇場一覧をロード
    try:
        allowed_theaters = load_allowed_theaters(args.theater_file)
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    # 劇場一覧の表示モード
    if args.list_theaters:
        print(format_theater_list(allowed_theaters))
        return

    # 引数から劇場と日付を解決
    input_target = args.target
    input_date = args.date or args.date_arg
    default_theater = user_config.get("theater", "ebetsu")

    # target が日付指定（8桁数字や '明日' 等）である場合
    # 例: `python3 aeoncinema_scraper.py 20261013`
    normalized_target_as_date = normalize_date(input_target)
    if input_target and normalized_target_as_date and (len(normalized_target_as_date) == 8 and normalized_target_as_date.isdigit()):
        theater_query = default_theater
        extracted_date = normalized_target_as_date
    elif input_target:
        theater_query, extracted_date = parse_target_url(input_target)
    else:
        theater_query, extracted_date = default_theater, None

    # 劇場の制限チェック (theater.json に含まれるか検証)
    theater_obj, candidates = find_allowed_theater(theater_query, allowed_theaters)
    if not theater_obj:
        print(
            f"エラー: 劇場 '{theater_query}' は許可された劇場一覧 ({os.path.basename(args.theater_file)}) に含まれていません。\n"
            f"※ 検索対象は https://www.aeoncinema.com/theater/ に掲載されている劇場に制限されています。",
            file=sys.stderr,
        )
        if candidates:
            sugs = ", ".join([f"{c['name']} (ID: {c['id']})" for c in candidates[:5]])
            print(f"もしかして: {sugs} ですか？", file=sys.stderr)
        print("利用可能な劇場一覧は '--list-theaters' で確認できます。", file=sys.stderr)
        sys.exit(1)

    theater = theater_obj["id"]
    theater_name_en = theater_obj["id"].capitalize()
    if lang == "en":
        theater_display = f"{theater_name_en} ({theater})"
    else:
        theater_display = f"{theater_obj['name']} ({theater})"

    # 設定の保存モード
    if args.save_config:
        new_config = {
            "theater": theater,
            "within_hours": within_hours,
            "english_mode": (lang == "en"),
            "format": args.format,
        }
        save_user_config(new_config, args.config_file)
        if lang == "en":
            print(f"Configuration saved to {args.config_file}:")
        else:
            print(f"設定を {args.config_file} に保存しました:")
        print(json.dumps(new_config, ensure_ascii=False, indent=2))

    target_date = normalize_date(input_date) or normalize_date(extracted_date)

    # スケジュールJSONを取得
    try:
        raw_data = fetch_schedule_json(theater)
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    available_dates = sorted(raw_data.keys())

    # 日程一覧のみを表示するモード
    if args.list_dates:
        print(f"劇場 '{theater_display}' で公開されている日程一覧:")
        for d in available_dates:
            print(f"  - {d[:4]}/{d[4:6]}/{d[6:]} ({d})")
        return

    # 日付の決定
    today_str = datetime.now(JST).strftime("%Y%m%d")
    if not target_date:
        if args.upcoming:
            target_date = today_str
        elif today_str in raw_data:
            target_date = today_str
        elif available_dates:
            target_date = available_dates[0]
        else:
            print(f"エラー: 劇場 '{theater}' の利用可能な上映日程がありません。", file=sys.stderr)
            sys.exit(1)

    # データのパース (theater.json のスクリーン設備情報を連携)
    fac_screens = theater_obj.get("facility", {}).get("screens") if theater_obj else None
    movies = parse_schedule_for_date(raw_data, target_date, lang=lang, facility_screens=fac_screens)

    filter_info: Optional[str] = None
    if args.upcoming:
        try:
            base_time = parse_base_time(args.base_time, target_date)
        except ValueError as e:
            print(f"エラー: {e}", file=sys.stderr)
            sys.exit(1)

        limit_time = base_time + timedelta(hours=within_hours)

        # 日付をまたぐ場合は翌日の上映データもマージ
        next_date = limit_time.strftime("%Y%m%d")
        if next_date != target_date and next_date in raw_data:
            next_movies = parse_schedule_for_date(
                raw_data, next_date, lang=lang, facility_screens=fac_screens
            )
            # 同一タイトルの映画があれば showtimes を結合、なければ追加
            movies_by_title = {m["title"]: m for m in movies}
            for nm in next_movies:
                if nm["title"] in movies_by_title:
                    movies_by_title[nm["title"]]["showtimes"].extend(nm["showtimes"])
                else:
                    movies.append(nm)

        # 指定時間以内の作品にフィルタリング
        movies = filter_upcoming_movies(movies, base_time, within_hours)
        if lang == "en":
            filter_info = (
                f"From {base_time.strftime('%Y/%m/%d %H:%M')} to {limit_time.strftime('%H:%M')} "
                f"(starts within {within_hours} hours)"
            )
        else:
            filter_info = (
                f"基準時刻 {base_time.strftime('%Y/%m/%d %H:%M')} 〜 {limit_time.strftime('%H:%M')} "
                f"({within_hours}時間以内に開始)"
            )

    if not movies and not args.upcoming:
        if args.format == "json":
            result_payload = {
                "theater": theater,
                "theater_name": theater_name_en if lang == "en" else theater_obj["name"],
                "area": theater_obj.get("area", ""),
                "date": target_date,
                "language": lang,
                "movies": [],
                "available_dates": available_dates,
                "message": (
                    f"No showtimes found for {target_date}."
                    if lang == "en"
                    else f"{target_date} の上映スケジュールは見つかりませんでした。"
                ),
            }
            result_text = json.dumps(result_payload, ensure_ascii=False, indent=2)
            if args.output_file:
                with open(args.output_file, "w", encoding="utf-8") as f:
                    f.write(result_text + "\n")
            else:
                print(result_text)
            return

        if lang == "en":
            print(
                f"Warning: No showtimes found for {target_date}.\n"
                f"Available dates: {', '.join(available_dates)}",
                file=sys.stderr,
            )
        else:
            print(
                f"警告: {target_date} の上映スケジュールは見つかりませんでした。\n"
                f"現在公開されている日程: {', '.join(available_dates)}",
                file=sys.stderr,
            )
        sys.exit(1)

    # フォーマット生成
    if args.format == "json":
        result_payload = {
            "theater": theater,
            "theater_name": theater_name_en if lang == "en" else theater_obj["name"],
            "area": theater_obj.get("area", ""),
            "date": target_date,
            "language": lang,
            "movies": movies,
        }
        if filter_info:
            result_payload["filter"] = filter_info
        result_text = json.dumps(result_payload, ensure_ascii=False, indent=2)
    elif args.format == "csv":
        result_text = format_csv(movies, lang=lang)
    elif args.format == "timetable":
        result_text = format_timetable(theater_display, target_date, movies, filter_info=filter_info, lang=lang)
    else:
        result_text = format_text(theater_display, target_date, movies, filter_info=filter_info, lang=lang)

    # 出力
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(result_text)
            f.write("\n")
        print(f"結果を {args.output_file} に保存しました。")
    else:
        print(result_text)


if __name__ == "__main__":
    main()
