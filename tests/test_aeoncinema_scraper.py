import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import aeoncinema_scraper
from aeoncinema_scraper import (
    JST,
    parse_target_url,
    normalize_date,
    parse_base_time,
    load_allowed_theaters,
    find_allowed_theater,
    format_theater_list,
    parse_schedule_for_date,
    filter_upcoming_movies,
    format_text,
    format_timetable,
    format_csv,
    to_english_screen,
    detect_special_badges,
    match_screen_facility,
    build_safe_booking_url,
    fetch_schedule_json,
    main,
)

# テスト用ダミーシアター一覧
MOCK_ALLOWED_THEATERS = [
    {
        "id": "ebetsu",
        "name": "江別",
        "theater_id": "81005",
        "area": "北海道",
        "url": "https://theater.aeoncinema.com/theaters/ebetsu/",
    },
    {
        "id": "otaru",
        "name": "小樽",
        "theater_id": "81024",
        "area": "北海道",
        "url": "https://theater.aeoncinema.com/theaters/otaru/",
    },
    {
        "id": "chofu",
        "name": "シアタス調布",
        "theater_id": "81084",
        "area": "東京",
        "url": "https://theater.aeoncinema.com/theaters/chofu/",
    },
]

# テスト用ダミースケジュールJSON (UTC)
MOCK_SCHEDULE_DATA = {
    "20261012": {
        "movie_grp_1": [
            {
                "id": "event_1",
                "name": {"ja": "映画A", "en": "Movie A"},
                "startDate": "2026-10-11T23:00:00.000Z",  # JST: 2026-10-12 08:00
                "endDate": "2026-10-12T01:00:00.000Z",    # JST: 2026-10-12 10:00
                "doorTime": "2026-10-11T22:45:00.000Z",
                "maximumAttendeeCapacity": 100,
                "remainingAttendeeCapacity": 50,
                "location": {"branchCode": "01", "name": {"ja": "スクリーン1"}},
                "offers": {"itemOffered": {"id": "ev_test_1"}},
            },
            {
                "id": "event_2",
                "name": {"ja": "映画A", "en": "Movie A"},
                "startDate": "2026-10-12T04:00:00.000Z",  # JST: 2026-10-12 13:00
                "endDate": "2026-10-12T06:00:00.000Z",    # JST: 2026-10-12 15:00
                "doorTime": "2026-10-12T03:45:00.000Z",
                "maximumAttendeeCapacity": 100,
                "remainingAttendeeCapacity": 10,
                "location": {"branchCode": "01", "name": {"ja": "スクリーン1"}},
                "offers": {"itemOffered": {"id": "ev_test_2"}},
            },
        ],
        "movie_grp_2": [
            {
                "id": "event_3",
                "name": {"ja": "映画B", "en": "Movie B"},
                "startDate": "2026-10-12T01:30:00.000Z",  # JST: 2026-10-12 10:30
                "endDate": "2026-10-12T03:30:00.000Z",    # JST: 2026-10-12 12:30
                "maximumAttendeeCapacity": 150,
                "remainingAttendeeCapacity": 80,
                "location": {"branchCode": "02", "name": {"ja": "スクリーン2"}},
                "offers": {"itemOffered": {"id": "ev_test_3"}},
            }
        ],
    }
}


class TestAeonCinemaScraper(unittest.TestCase):

    # 1. URLパース
    def test_parse_target_url(self):
        # 完全なURL
        theater, date = parse_target_url("https://theater.aeoncinema.com/theaters/ebetsu/?date=20261012&foo=bar")
        self.assertEqual(theater, "ebetsu")
        self.assertEqual(date, "20261012")

        # クエリパラメータなしのURL
        theater, date = parse_target_url("https://theater.aeoncinema.com/theaters/chofu/")
        self.assertEqual(theater, "chofu")
        self.assertIsNone(date)

        # パスのみ
        theater, date = parse_target_url("/theaters/otaru/")
        self.assertEqual(theater, "otaru")
        self.assertIsNone(date)

        # 単なるID文字列
        theater, date = parse_target_url("ebetsu")
        self.assertEqual(theater, "ebetsu")
        self.assertIsNone(date)

    # 2. 日付正規化
    def test_normalize_date(self):
        self.assertEqual(normalize_date("20261013"), "20261013")
        self.assertEqual(normalize_date("2026-10-13"), "20261013")
        self.assertEqual(normalize_date("2026/10/13"), "20261013")

        yesterday_str = (datetime.now(JST) - timedelta(days=1)).strftime("%Y%m%d")
        today_str = datetime.now(JST).strftime("%Y%m%d")
        tomorrow_str = (datetime.now(JST) + timedelta(days=1)).strftime("%Y%m%d")

        self.assertEqual(normalize_date("yesterday"), yesterday_str)
        self.assertEqual(normalize_date("昨日"), yesterday_str)
        self.assertEqual(normalize_date("today"), today_str)
        self.assertEqual(normalize_date("今日"), today_str)
        self.assertEqual(normalize_date("tomorrow"), tomorrow_str)
        self.assertEqual(normalize_date("明日"), tomorrow_str)

        self.assertIsNone(normalize_date(None))
        self.assertEqual(normalize_date("invalid"), "invalid")

    # 3. 基準時刻パース
    def test_parse_base_time(self):
        # 時刻のみ (HH:MM)
        dt = parse_base_time("14:30", "20261012")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 10)
        self.assertEqual(dt.day, 12)
        self.assertEqual(dt.hour, 14)
        self.assertEqual(dt.minute, 30)
        self.assertEqual(dt.tzinfo, JST)

        # 日時指定 (YYYY-MM-DD HH:MM)
        dt2 = parse_base_time("2026-10-13 18:00", "20261012")
        self.assertEqual(dt2.year, 2026)
        self.assertEqual(dt2.month, 10)
        self.assertEqual(dt2.day, 13)
        self.assertEqual(dt2.hour, 18)
        self.assertEqual(dt2.minute, 0)

        # 未指定時は target_date の当日時刻
        now = datetime.now(JST)
        dt_default = parse_base_time(None, "20261015")
        self.assertEqual(dt_default.year, 2026)
        self.assertEqual(dt_default.month, 10)
        self.assertEqual(dt_default.day, 15)
        self.assertEqual(dt_default.hour, now.hour)

        # 不正な書式
        with self.assertRaises(ValueError):
            parse_base_time("99:99", "20261012")

    # 4. 劇場の検索と制限
    def test_find_allowed_theater(self):
        # 英字ID完全一致
        t, c = find_allowed_theater("ebetsu", MOCK_ALLOWED_THEATERS)
        self.assertIsNotNone(t)
        self.assertEqual(t["id"], "ebetsu")

        # 日本語名完全一致
        t, c = find_allowed_theater("江別", MOCK_ALLOWED_THEATERS)
        self.assertIsNotNone(t)
        self.assertEqual(t["id"], "ebetsu")

        # 接頭辞「イオンシネマ」付き
        t, c = find_allowed_theater("イオンシネマ江別", MOCK_ALLOWED_THEATERS)
        self.assertIsNotNone(t)
        self.assertEqual(t["id"], "ebetsu")

        # 劇場コード一致
        t, c = find_allowed_theater("81084", MOCK_ALLOWED_THEATERS)
        self.assertIsNotNone(t)
        self.assertEqual(t["id"], "chofu")

        # 部分一致 (「調布」 -> 「シアタス調布」)
        t, c = find_allowed_theater("調布", MOCK_ALLOWED_THEATERS)
        self.assertIsNotNone(t)
        self.assertEqual(t["id"], "chofu")

        # 存在しない劇場
        t, c = find_allowed_theater("shinjuku", MOCK_ALLOWED_THEATERS)
        self.assertIsNone(t)
        self.assertEqual(c, [])

    def test_format_theater_list(self):
        output = format_theater_list(MOCK_ALLOWED_THEATERS)
        self.assertIn("北海道", output)
        self.assertIn("江別 (ebetsu)", output)
        self.assertIn("東京", output)
        self.assertIn("シアタス調布 (chofu)", output)

    # 5. スケジュールJSONのパース
    def test_parse_schedule_for_date(self):
        movies = parse_schedule_for_date(MOCK_SCHEDULE_DATA, "20261012")
        self.assertEqual(len(movies), 2)

        movie_a = next(m for m in movies if m["title"] == "映画A")
        self.assertEqual(len(movie_a["showtimes"]), 2)

        # JST時刻の変換検証 (08:00〜10:00)
        st1 = movie_a["showtimes"][0]
        self.assertEqual(st1["start_time"], "08:00")
        self.assertEqual(st1["end_time"], "10:00")
        self.assertEqual(st1["screen"], "スクリーン1")
        self.assertEqual(st1["remaining_seats"], 50)
        self.assertEqual(st1["total_seats"], 100)
        self.assertEqual(st1["event_id"], "event_1")
        self.assertEqual(
            st1["booking_url"],
            "https://login.watatheatre.aeoncinema.com/auth?eventId=event_1",
        )
        self.assertEqual(
            movie_a["booking_url"],
            "https://login.watatheatre.aeoncinema.com/auth?eventId=event_1",
        )

        # 最速上映開始時刻順にソートされることの検証 (映画A: 08:00 < 映画B: 10:30)
        self.assertEqual(movies[0]["title"], "映画A")
        self.assertEqual(movies[1]["title"], "映画B")

        # 逆順データ (タイトルはZが後だが上映時間はZが早い場合)
        mock_custom_data = {
            "20261012": {
                "grp_a": [{
                    "id": "e_a",
                    "name": {"ja": "映画A"},
                    "startDate": "2026-10-12T01:00:00.000Z",  # JST: 10:00
                    "endDate": "2026-10-12T03:00:00.000Z",
                }],
                "grp_z": [{
                    "id": "e_z",
                    "name": {"ja": "映画Z"},
                    "startDate": "2026-10-11T23:30:00.000Z",  # JST: 08:30
                    "endDate": "2026-10-12T01:30:00.000Z",
                }],
            }
        }
        sorted_movies = parse_schedule_for_date(mock_custom_data, "20261012")
        self.assertEqual([m["title"] for m in sorted_movies], ["映画Z", "映画A"])

        # 存在しない日付
        empty_movies = parse_schedule_for_date(MOCK_SCHEDULE_DATA, "20990101")
        self.assertEqual(empty_movies, [])

    # 6. 直近映画フィルタリング (filter_upcoming_movies)
    def test_filter_upcoming_movies(self):
        movies = parse_schedule_for_date(MOCK_SCHEDULE_DATA, "20261012")

        # 基準時刻: 2026-10-12 09:00, 3時間以内 (09:00〜12:00 開始)
        base_time = datetime(2026, 10, 12, 9, 0, tzinfo=JST)
        filtered = filter_upcoming_movies(movies, base_time, within_hours=3.0)

        # 映画Aの 08:00回 (過去) は除外、13:00回 (3時間超) も除外
        # 映画Bの 10:30回 (範囲内) のみが該当するはず
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title"], "映画B")
        self.assertEqual(len(filtered[0]["showtimes"]), 1)
        self.assertEqual(filtered[0]["showtimes"][0]["start_time"], "10:30")

    # 7. 各フォーマッタの検証
    def test_format_text(self):
        movies = parse_schedule_for_date(MOCK_SCHEDULE_DATA, "20261012")
        text = format_text("江別 (ebetsu)", "20261012", movies)
        self.assertIn("イオンシネマ【江別 (ebetsu)】上映スケジュール", text)
        self.assertIn("■ 映画A", text)
        self.assertIn("08:00 〜 10:00", text)
        self.assertIn("[残席: 50/100]", text)

    def test_format_timetable(self):
        movies = parse_schedule_for_date(MOCK_SCHEDULE_DATA, "20261012")
        table = format_timetable("江別 (ebetsu)", "20261012", movies)
        self.assertIn("タイムテーブル順", table)
        self.assertIn("08:00〜10:00", table)
        self.assertIn("10:30〜12:30", table)
        self.assertIn("映画B", table)

    def test_format_csv(self):
        movies = parse_schedule_for_date(MOCK_SCHEDULE_DATA, "20261012")
        csv_text = format_csv(movies)
        self.assertIn("タイトル,開始時刻,終了時刻,スクリーン,残席数,総座席数", csv_text)
        self.assertIn("映画A,08:00,10:00,スクリーン1,50,100", csv_text)

    # 8. fetch_schedule_json (モック通信)
    @patch("urllib.request.urlopen")
    def test_fetch_schedule_json(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(MOCK_SCHEDULE_DATA).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        data = fetch_schedule_json("ebetsu")
        self.assertIn("20261012", data)

    # 9. CLI/main 統合テスト
    @patch("aeoncinema_scraper.fetch_schedule_json")
    @patch("aeoncinema_scraper.load_allowed_theaters")
    def test_main_cli_success(self, mock_load, mock_fetch):
        mock_load.return_value = MOCK_ALLOWED_THEATERS
        mock_fetch.return_value = MOCK_SCHEDULE_DATA

        # 江別の20261012を取得
        test_args = ["aeoncinema_scraper.py", "ebetsu", "--date", "20261012"]
        with patch.object(sys, "argv", test_args):
            with patch("sys.stdout", new=io.StringIO()) as fake_out:
                main()
                output = fake_out.getvalue()
                self.assertIn("イオンシネマ【江別 (ebetsu)】上映スケジュール", output)
                self.assertIn("映画A", output)

    @patch("aeoncinema_scraper.load_allowed_theaters")
    def test_main_cli_invalid_theater_exit(self, mock_load):
        mock_load.return_value = MOCK_ALLOWED_THEATERS

        test_args = ["aeoncinema_scraper.py", "shinjuku"]
        with patch.object(sys, "argv", test_args):
            with patch("sys.stderr", new=io.StringIO()) as fake_err:
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 1)
    # 10. 英語対応テスト
    def test_to_english_screen(self):
        self.assertEqual(to_english_screen("スクリーン1"), "Screen 1")
        self.assertEqual(to_english_screen("スクリーン 5"), "Screen 5")
        self.assertEqual(to_english_screen("スクリーン未定"), "TBD")
        self.assertEqual(to_english_screen("IMAX"), "IMAX")

    def test_parse_schedule_for_date_english(self):
        movies = parse_schedule_for_date(MOCK_SCHEDULE_DATA, "20261012", lang="en")
        movie_a = next(m for m in movies if m["title_ja"] == "映画A")
        self.assertEqual(movie_a["title"], "Movie A")
        self.assertEqual(movie_a["showtimes"][0]["screen"], "Screen 1")

    def test_format_text_english(self):
        movies = parse_schedule_for_date(MOCK_SCHEDULE_DATA, "20261012", lang="en")
        text = format_text("Ebetsu (ebetsu)", "20261012", movies, lang="en")
        self.assertIn("AEON CINEMA [Ebetsu (ebetsu)] Showtimes", text)
        self.assertIn("■ Movie A", text)
        self.assertIn("08:00 - 10:00  (Screen 1) [Seats: 50/100]", text)

    @patch("aeoncinema_scraper.fetch_schedule_json")
    @patch("aeoncinema_scraper.load_allowed_theaters")
    def test_main_cli_english(self, mock_load, mock_fetch):
        mock_load.return_value = MOCK_ALLOWED_THEATERS
        mock_fetch.return_value = MOCK_SCHEDULE_DATA

        test_args = ["aeoncinema_scraper.py", "ebetsu", "--date", "20261012", "--en"]
        with patch.object(sys, "argv", test_args):
            with patch("sys.stdout", new=io.StringIO()) as fake_out:
                main()
                output = fake_out.getvalue()
                self.assertIn("AEON CINEMA [Ebetsu (ebetsu)] Showtimes", output)
    # 10. 設定の保存・読み込み (config persistence)
    def test_config_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_cfg = os.path.join(tmpdir, "config.json")
            # 存在しない場合はデフォルト
            cfg = aeoncinema_scraper.load_user_config(tmp_cfg)
            self.assertEqual(cfg["theater"], "ebetsu")
            self.assertEqual(cfg["within_hours"], 3.0)
            self.assertFalse(cfg["english_mode"])

            # 保存
            new_cfg = {
                "theater": "chofu",
                "within_hours": 2.5,
                "english_mode": True,
                "format": "timetable",
            }
            aeoncinema_scraper.save_user_config(new_cfg, tmp_cfg)
            self.assertTrue(os.path.exists(tmp_cfg))

            # 再読み込み
            loaded = aeoncinema_scraper.load_user_config(tmp_cfg)
            self.assertEqual(loaded["theater"], "chofu")
            self.assertEqual(loaded["within_hours"], 2.5)
            self.assertTrue(loaded["english_mode"])

    @patch("aeoncinema_scraper.fetch_schedule_json")
    @patch("aeoncinema_scraper.load_allowed_theaters")
    def test_main_cli_save_and_show_config(self, mock_load, mock_fetch):
        mock_load.return_value = MOCK_ALLOWED_THEATERS
        mock_fetch.return_value = MOCK_SCHEDULE_DATA

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_cfg = os.path.join(tmpdir, "config.json")

            # --save-config のテスト
            test_args = [
                "aeoncinema_scraper.py", "chofu",
                "--within-hours", "2",
                "--en",
                "--save-config",
                "--config-file", tmp_cfg,
            ]
            with patch.object(sys, "argv", test_args):
                with patch("sys.stdout", new=io.StringIO()) as fake_out:
                    main()
                    self.assertTrue(os.path.exists(tmp_cfg))

            # --show-config のテスト
            test_args_show = ["aeoncinema_scraper.py", "--show-config", "--config-file", tmp_cfg]
            with patch.object(sys, "argv", test_args_show):
                with patch("sys.stdout", new=io.StringIO()) as fake_out_show:
                    main()
                    out = fake_out_show.getvalue()
                    self.assertIn('"theater": "chofu"', out)
                    self.assertIn('"within_hours": 2.0', out)
                    self.assertIn('"english_mode": true', out)

    @patch("aeoncinema_scraper.fetch_schedule_json", return_value=MOCK_SCHEDULE_DATA)
    @patch("aeoncinema_scraper.load_allowed_theaters", return_value=MOCK_ALLOWED_THEATERS)
    def test_main_json_format_no_movies(self, mock_load, mock_fetch):
        # 存在しない日付 (20990101) で --format json
        test_args = ["aeoncinema_scraper.py", "ebetsu", "-d", "20990101", "--format", "json"]
        with patch.object(sys, "argv", test_args):
            with patch("sys.stdout", new=io.StringIO()) as fake_out:
                main()
                data = json.loads(fake_out.getvalue())
                self.assertEqual(data["theater"], "ebetsu")
                self.assertEqual(data["movies"], [])
                self.assertIn("message", data)

    def test_detect_special_badges(self):
        # 1. 設備タグから検出
        badges = detect_special_badges(["4DX", "3-D", "トリプルエアシールド"], "スクリーン6")
        self.assertEqual(badges, ["4DX"])

        # 2. スクリーン名から検出
        badges_imax = detect_special_badges(["トリプルエアシールド"], "IMAXレーザー")
        self.assertEqual(badges_imax, ["IMAX"])

        # 3. タイトルから検出 (Dolby Atmos, Dolby Atomos)
        badges_atmos = detect_special_badges([], "スクリーン2", extra_texts=["オッペンハイマー (Dolby Atomos版)"])
        self.assertEqual(badges_atmos, ["Dolby Atmos"])

        # 4. THX, VIVE AUDIO
        badges_thx = detect_special_badges(["THX"], "スクリーン7")
        self.assertEqual(badges_thx, ["THX"])
        badges_vive = detect_special_badges(["VIVE AUDIO"], "スクリーン8")
        self.assertEqual(badges_vive, ["VIVE AUDIO"])

    def test_match_screen_facility(self):
        screens = [
            {"name": "1スクリーン", "features": ["トリプルエアシールド"]},
            {"name": "6スクリーン", "features": ["4DX"]},
            {"name": "IMAXレーザー", "features": ["IMAX"]},
        ]
        # 完全一致
        self.assertEqual(match_screen_facility("IMAXレーザー", screens)["name"], "IMAXレーザー")
        # 数字一致 ("スクリーン6" -> "6スクリーン")
        self.assertEqual(match_screen_facility("スクリーン6", screens)["name"], "6スクリーン")
        self.assertEqual(match_screen_facility("スクリーン1", screens)["name"], "1スクリーン")
        # 一致なし
        self.assertIsNone(match_screen_facility("スクリーン99", screens))

    def test_build_safe_booking_url(self):
        # 1. 正常なID (16進数ハッシュや英数字)
        valid_id = "6ac3b68aaf7191571136985e"
        url = build_safe_booking_url(valid_id)
        self.assertEqual(url, f"https://login.watatheatre.aeoncinema.com/auth?eventId={valid_id}")

        # 2. ハイフンやアンダースコアを含むID
        self.assertIsNotNone(build_safe_booking_url("ev-123_abc"))

        # 3. コマンドインジェクション攻撃文字列（シングルクォート、セミコロン、パイプなど）を拒絶
        self.assertIsNone(build_safe_booking_url("ev' ; rm -rf ~ ; echo '"))
        self.assertIsNone(build_safe_booking_url("ev`whoami`"))
        self.assertIsNone(build_safe_booking_url("ev$(id)"))
        self.assertIsNone(build_safe_booking_url("ev | cat /etc/passwd"))

        # 4. スペース、改行、不正文字
        self.assertIsNone(build_safe_booking_url("ev 123"))
        self.assertIsNone(build_safe_booking_url("ev\n123"))
        self.assertIsNone(build_safe_booking_url("ev<script>"))

        # 5. 空文字、None、型不正
        self.assertIsNone(build_safe_booking_url(""))
        self.assertIsNone(build_safe_booking_url("   "))
        self.assertIsNone(build_safe_booking_url(None))
        self.assertIsNone(build_safe_booking_url(12345))

        # 6. 長すぎるID (64文字超)
        self.assertIsNone(build_safe_booking_url("a" * 65))


if __name__ == "__main__":
    unittest.main()

