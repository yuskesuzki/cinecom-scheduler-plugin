"""
都道府県および地方区分と全チェーン劇場のマッピング・解決モジュール
"""
from typing import Dict, List, Optional, Set
from pathlib import Path
import json
import re

# 47都道府県の標準名称
PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"
]

# 地方ブロックと都道府県の対応
REGION_TO_PREFECTURES: Dict[str, List[str]] = {
    "北海道": ["北海道"],
    "東北": ["青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"],
    "関東": ["茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"],
    "中部": ["新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県"],
    "近畿": ["三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"],
    "中国": ["鳥取県", "島根県", "岡山県", "広島県", "山口県"],
    "四国": ["徳島県", "香川県", "愛媛県", "高知県"],
    "中国・四国": ["鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県"],
    "九州": ["福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県"],
    "九州・沖縄": ["福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"],
}

# ユナイテッド・シネマ各劇場の都道府県マッピング
UNITED_THEATER_PREFECTURES: Dict[str, str] = {
    "sapporo": "北海道",
    "asahikawa": "北海道",
    "ogawara": "宮城県",
    "mito": "茨城県",
    "tsukuba": "茨城県",
    "ashikaga": "栃木県",
    "maebashi": "群馬県",
    "urawa": "埼玉県",
    "minamifuruya": "埼玉県",
    "chichibu": "埼玉県",
    "kasukabe": "埼玉県",
    "iruma": "埼玉県",
    "niza": "埼玉県",
    "satte": "埼玉県",
    "wakaba": "埼玉県",
    "kamisato": "埼玉県",
    "makuhari": "千葉県",
    "matsudo": "千葉県",
    "toyosu": "東京都",
    "ygc": "東京都",
    "toshimaen": "東京都",
    "minatomirai": "神奈川県",
    "hiratsuka": "神奈川県",
    "niigata": "新潟県",
    "kanazawa": "石川県",
    "toyohashi": "愛知県",
    "okazaki": "愛知県",
    "inazawa": "愛知県",
    "agui": "愛知県",
    "otsu": "滋賀県",
    "kishiwada": "大阪府",
    "kashihara": "奈良県",
    "imabari": "愛媛県",
    "kokura": "福岡県",
    "canalcity": "福岡県",
    "fukuokamomochi": "福岡県",
    "nakama": "福岡県",
    "hisayama": "福岡県",
    "nagasaki": "長崎県",
    "urasoe": "沖縄県",
}

# シネマサンシャイン各劇場の都道府県マッピング
SUNSHINE_THEATER_PREFECTURES: Dict[str, str] = {
    "gdcs": "東京都",
    "heiwajima": "東京都",
    "yukarigaoka": "千葉県",
    "misato": "埼玉県",
    "tsuchiura": "茨城県",
    "lalaportnumazu": "静岡県",
    "kahoku": "石川県",
    "yamatokoriyama": "奈良県",
    "shimonoseki": "山口県",
    "kinuyama": "愛媛県",
    "shigenobu": "愛媛県",
    "masaki": "愛媛県",
    "kitajima": "徳島県",
    "iizuka": "福岡県",
    "aira": "鹿児島県",
    "tomakomai": "北海道",
}


def normalize_prefecture(name: str) -> Optional[str]:
    """
    任意の入力（例: '東京', '東京都', 'tokyo' 等）を標準の都道府県名（例: '東京都'）に変換する。
    """
    if not name or not isinstance(name, str):
        return None
    cleaned = name.strip()
    if not cleaned:
        return None

    # 完全一致
    if cleaned in PREFECTURES:
        return cleaned

    # '都', '府', '県' が抜けている場合の補完 (例: '東京' -> '東京都', '京都' -> '京都府')
    # ※ 'cleaned in pref' は '京都' が '東京都' に部分一致してしまうため、pref.startswith(cleaned) のみとする
    for pref in PREFECTURES:
        if pref.startswith(cleaned):
            return pref

    return None


def resolve_target_prefectures(area_query: str) -> List[str]:
    """
    地域クエリ（例: '東京都', '東京', '関東', '関西' 等）から該当する都道府県名のリストを返す。
    """
    if not area_query:
        return []
    cleaned = area_query.strip()

    # 1. 都道府県名の場合
    pref = normalize_prefecture(cleaned)
    if pref:
        return [pref]

    # 2. 地方名の場合（例: '関東', '近畿', '九州' 等）
    for reg, prefs in REGION_TO_PREFECTURES.items():
        if reg in cleaned or cleaned in reg:
            return prefs

    return []


def get_theater_prefecture(chain_id: str, theater: dict) -> Optional[str]:
    """
    劇場オブジェクトから都道府県名を解決する。
    """
    t_id = theater.get("id", "")
    if chain_id == "united":
        return UNITED_THEATER_PREFECTURES.get(t_id)
    if chain_id == "sunshine":
        return SUNSHINE_THEATER_PREFECTURES.get(t_id)

    # toho: 'region' に '東京都' や '大阪府' が入っている
    if chain_id == "toho":
        reg = theater.get("region") or ""
        return normalize_prefecture(reg)

    # aeon: 'area' に '東京' や '大阪' が入っている
    if chain_id == "aeon":
        area = theater.get("area") or ""
        return normalize_prefecture(area)

    return None


def get_theaters_by_area(
    area_query: str,
    theater_query: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    指定された地域（都道府県名または地方名）に合致する全チェーンの劇場一覧を返す。
    theater_query が指定されている場合、劇場の地域名・劇場名・IDであいまい絞り込みを行う。
    戻り値: [{'chain_id': 'toho', 'theater_id': '009', 'theater_name': 'TOHOシネマズ 新宿', 'prefecture': '東京都'}, ...]
    """
    target_prefs = set(resolve_target_prefectures(area_query))
    if not target_prefs:
        return []

    norm_theater_q = theater_query.strip().lower() if theater_query else None

    base_dir = Path(__file__).resolve().parents[1] / "data" / "theaters"
    chains = ["aeon", "toho", "united", "sunshine"]
    results = []

    for chain_id in chains:
        chain_file = base_dir / f"{chain_id}.json"
        if not chain_file.exists():
            continue
        try:
            with open(chain_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for t in data.get("theaters", []):
                pref = get_theater_prefecture(chain_id, t)
                if pref and pref in target_prefs:
                    t_name = t.get("name", t["id"])
                    t_id = t["id"]
                    # theater_query 絞り込み（劇場名、劇場ID、または地域名に部分一致）
                    if norm_theater_q:
                        if (
                            norm_theater_q not in t_name.lower()
                            and norm_theater_q not in t_id.lower()
                        ):
                            continue

                    results.append({
                        "chain_id": chain_id,
                        "theater_id": t_id,
                        "theater_name": t_name,
                        "prefecture": pref,
                    })
        except Exception:
            continue

    return results
