#!/usr/bin/env python3
"""
イオンシネマの公式Webサイトから劇場一覧および各劇場のスクリーン設備情報（facility）を
スクレイピングし、theater.json を生成・更新するスクリプト。
"""

import argparse
import concurrent.futures
import json
import re
import sys
import urllib.request
from typing import Any, Dict, List, Optional


THEATER_LIST_URL = "https://www.aeoncinema.com/theater/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_theater_list() -> List[Dict[str, Any]]:
    """全国の劇場一覧（都道府県別）を取得する。"""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    req = urllib.request.Request(THEATER_LIST_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8")

    # 都道府県ごとのセクションを抽出
    h2_matches = list(re.finditer(r'<h2 class="c-area__name">(.*?)</h2>', html))
    theaters = []
    seen_ids = set()

    for i, m in enumerate(h2_matches):
        start = m.end()
        end = h2_matches[i + 1].start() if i + 1 < len(h2_matches) else len(html)
        area_name = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        sec_html = html[start:end]

        pattern = (
            r'data-theater-id=["\']([^"\']+)["\']\s+'
            r'data-theater-name=["\']([^"\']+)["\'][^>]*>.*?<h3>(.*?)</h3>'
        )
        matches = re.findall(pattern, sec_html, re.DOTALL)

        for tid, tname, tjp in matches:
            clean_name = re.sub(r"<[^>]+>", "", tjp).strip()
            if tname not in seen_ids:
                seen_ids.add(tname)
                theaters.append({
                    "id": tname,
                    "name": clean_name,
                    "theater_id": tid,
                    "area": area_name,
                    "url": f"https://theater.aeoncinema.com/theaters/{tname}/",
                })

    return theaters


def parse_facility_html(html: str, theater_id: str) -> Dict[str, Any]:
    """
    https://www.aeoncinema.com/[劇場id]/facility/ のHTMLを解析し、
    各スクリーン設備情報および劇場全体サービス情報を抽出する。
    """
    # 座席図モーダルから画像URLを抽出
    seat_maps: Dict[str, str] = {}
    for m in re.finditer(
        r'<div[^>]+data-modal=\"(modal_seat_\d+)\"[^>]*>.*?<img[^>]+src=\"([^\"]+)\"',
        html,
        re.DOTALL,
    ):
        img_url = m.group(2).strip()
        if img_url.startswith("/"):
            img_url = "https://theater.aeoncinema.com" + img_url
        seat_maps[m.group(1)] = img_url

    # 各スクリーン情報のパース
    screen_parts = html.split('<div class="p-facility__screenList c-accordion">')[1:]
    screens: List[Dict[str, Any]] = []

    for part in screen_parts:
        content = part.split("</section>")[0]

        # スクリーン名 (例: "1スクリーン", "IMAXレーザー")
        label_m = re.search(r'<span class="c-accordion__label">([^<]+)</span>', content)
        name = label_m.group(1).strip() if label_m else ""

        # スクリーン設備タグ (data-chip)
        chips = re.findall(r'data-chip="([^"]+)"', content)
        seen_chips = set()
        features = [c for c in chips if not (c in seen_chips or seen_chips.add(c))]

        # 座席図URL
        modal_m = re.search(r'data-modal="(modal_seat_\d+)"', content)
        seat_map_url = seat_maps.get(modal_m.group(1)) if modal_m else None

        # 座席内訳テーブル
        seats: Dict[str, Any] = {}
        total_seats: Optional[int] = None
        for row in re.finditer(r"<tr>\s*<th>([^<]+)</th>\s*<td>([^<]+)</td>\s*</tr>", content):
            th = row.group(1).strip()
            td = row.group(2).strip()
            num_m = re.search(r"(\d+)", td)
            val = int(num_m.group(1)) if num_m else td
            seats[th] = val
            if ("合" in th and "計" in th) or th == "合計":
                if isinstance(val, int):
                    total_seats = val

        screens.append({
            "name": name,
            "features": features,
            "total_seats": total_seats,
            "seats": seats,
            "seat_map_url": seat_map_url,
        })

    # 劇場全体サービス紹介セクション (id="facility")
    services: List[Dict[str, Any]] = []
    facility_section = html.split('id="facility"')
    if len(facility_section) > 1:
        section_html = facility_section[1].split('id="screen"')[0]
        blocks = section_html.split('<div class="p-facility__block">')[1:]
        for b in blocks:
            pic_m = re.search(r'<div class="p-facility__picture">(.*?)</div>', b, re.DOTALL)
            screen_note = ""
            if pic_m:
                span_m = re.search(r"<span>([^<]+)</span>", pic_m.group(1))
                if span_m:
                    screen_note = span_m.group(1).strip()

            name_m = re.search(r'<p class="p-facility__name">([^<]+)', b)
            name = name_m.group(1).strip() if name_m else ""

            lead_m = re.search(r'<p class="p-facility__lead">([^<]+)', b)
            lead = lead_m.group(1).strip() if lead_m else ""

            if name:
                item: Dict[str, Any] = {"name": name}
                if screen_note:
                    item["screen"] = screen_note
                if lead:
                    item["description"] = lead
                services.append(item)

    return {
        "url": f"https://www.aeoncinema.com/{theater_id}/facility/",
        "screens": screens,
        "theater_services": services,
    }


def fetch_facility_for_theater(theater_id: str) -> Optional[Dict[str, Any]]:
    """指定された劇場のスクリーン設備ページを取得・解析する。"""
    url = f"https://www.aeoncinema.com/{theater_id}/facility/"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")
            return parse_facility_html(html, theater_id)
    except Exception as e:
        print(f"[{theater_id}] 施設情報の取得に失敗しました: {e}", file=sys.stderr)
        return None


def attach_facilities_to_theaters(
    theaters: List[Dict[str, Any]], max_workers: int = 5
) -> List[Dict[str, Any]]:
    """全劇場に並列で facility 情報を取得・付加する。"""
    total = len(theaters)
    print(f"全 {total} 劇場のスクリーン設備情報（facility）を取得中 (並列数: {max_workers})...")

    def worker(t: Dict[str, Any]) -> tuple[str, Optional[Dict[str, Any]]]:
        tid = t["id"]
        return tid, fetch_facility_for_theater(tid)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_theater = {executor.submit(worker, t): t for t in theaters}
        done_count = 0
        facility_map: Dict[str, Optional[Dict[str, Any]]] = {}

        for future in concurrent.futures.as_completed(future_to_theater):
            done_count += 1
            tid, facility = future.result()
            facility_map[tid] = facility
            if done_count % 10 == 0 or done_count == total:
                print(f"進捗: {done_count}/{total} 劇場完了")

    for t in theaters:
        tid = t["id"]
        t["facility"] = facility_map.get(tid)

    return theaters


def generate_theater_json(
    output_path: str = "theater.json",
    with_facility: bool = True,
    max_workers: int = 5,
) -> List[Dict[str, Any]]:
    """全国の劇場一覧とスクリーン設備情報を取得して theater.json を生成・保存する。"""
    print(f"劇場一覧を取得中: {THEATER_LIST_URL} ...")
    theaters = fetch_theater_list()
    print(f"取得完了: {len(theaters)} 劇場")

    if with_facility:
        attach_facilities_to_theaters(theaters, max_workers=max_workers)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(theaters, f, ensure_ascii=False, indent=2)

    print(f"'{output_path}' に保存しました。")
    return theaters


def update_existing_theater_json_facilities(
    target_path: str = "theater.json", max_workers: int = 5
) -> List[Dict[str, Any]]:
    """既存の theater.json を読み込み、facility 属性のみをスクレイピングして追記・保存する。"""
    with open(target_path, "r", encoding="utf-8") as f:
        theaters = json.load(f)

    print(f"既存の '{target_path}' ({len(theaters)} 劇場) の facility 情報を更新します。")
    attach_facilities_to_theaters(theaters, max_workers=max_workers)

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(theaters, f, ensure_ascii=False, indent=2)

    print(f"'{target_path}' を更新しました。")
    return theaters


def main():
    parser = argparse.ArgumentParser(
        description="イオンシネマ劇場一覧およびスクリーン設備情報（facility）を取得して theater.json を更新します。"
    )
    parser.add_argument(
        "-o", "--output",
        default="theater.json",
        help="出力先JSONファイルパス (デフォルト: theater.json)",
    )
    parser.add_argument(
        "--only-facility",
        action="store_true",
        help="既存の theater.json に facility 属性のみを追加・更新する",
    )
    parser.add_argument(
        "--no-facility",
        action="store_true",
        help="facility 情報の取得をスキップし、劇場一覧のみ取得する",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=5,
        help="施設情報取得の並列スレッド数 (デフォルト: 5)",
    )

    args = parser.parse_args()

    if args.only_facility:
        update_existing_theater_json_facilities(
            target_path=args.output, max_workers=args.workers
        )
    else:
        generate_theater_json(
            output_path=args.output,
            with_facility=not args.no_facility,
            max_workers=args.workers,
        )


if __name__ == "__main__":
    main()
