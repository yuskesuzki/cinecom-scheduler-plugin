import json
import unittest
from datetime import date
from unittest.mock import patch, MagicMock

from scraper.area import (
    normalize_prefecture,
    resolve_target_prefectures,
    get_theaters_by_area,
)
from scraper.models import (
    SeatStatus,
    Screening,
    MovieSchedule,
    CrossTheaterScreening,
    CrossTheaterSearchResponse,
)
from scraper.search import clean_query_title, is_movie_match, search_cross_theater
import scraper.cli


class TestCrossTheaterSearch(unittest.TestCase):
    def test_normalize_prefecture(self):
        self.assertEqual(normalize_prefecture("東京都"), "東京都")
        self.assertEqual(normalize_prefecture("東京"), "東京都")
        self.assertEqual(normalize_prefecture("京都"), "京都府")
        self.assertEqual(normalize_prefecture("京都府"), "京都府")
        self.assertEqual(normalize_prefecture("北海道"), "北海道")
        self.assertEqual(normalize_prefecture("大阪"), "大阪府")
        self.assertEqual(normalize_prefecture("神奈川"), "神奈川県")
        self.assertIsNone(normalize_prefecture("アメリカ"))

    def test_resolve_target_prefectures(self):
        # 単一都道府県
        self.assertEqual(resolve_target_prefectures("東京都"), ["東京都"])
        self.assertEqual(resolve_target_prefectures("東京"), ["東京都"])
        # 地方ブロック
        kanto = resolve_target_prefectures("関東")
        self.assertIn("東京都", kanto)
        self.assertIn("神奈川県", kanto)
        self.assertIn("埼玉県", kanto)
        self.assertIn("千葉県", kanto)
        self.assertEqual(len(kanto), 7)

    def test_get_theaters_by_area(self):
        theaters = get_theaters_by_area("東京都")
        self.assertGreater(len(theaters), 0)
        chains = {t["chain_id"] for t in theaters}
        # 東京都には aeon, toho, united, sunshine の4チェーン全てが存在する
        self.assertIn("aeon", chains)
        self.assertIn("toho", chains)
        self.assertIn("united", chains)
        self.assertIn("sunshine", chains)
        for t in theaters:
            self.assertEqual(t["prefecture"], "東京都")

    def test_clean_query_title(self):
        self.assertEqual(clean_query_title("字幕 バイオハザード"), "バイオハザード")
        self.assertEqual(clean_query_title("バイオハザード【字幕】Dolby Atmos / R15+"), "バイオハザード")
        self.assertEqual(clean_query_title("ストリートファイター／ザ・ムービー 4DX2D（吹替）"), "ストリートファイター／ザムービー")
        self.assertEqual(clean_query_title("映画ちいかわ 人魚の島のひみつ"), "映画ちいかわ人魚の島のひみつ")

    def test_is_movie_match(self):
        self.assertTrue(is_movie_match("字幕 バイオハザード", "バイオハザード"))
        self.assertTrue(is_movie_match("バイオハザード【IMAXレーザーGT字幕】", "バイオハザード"))
        self.assertTrue(is_movie_match("映画ちいかわ 人魚の島のひみつ", "ちいかわ"))
        self.assertFalse(is_movie_match("オデュッセイア", "バイオハザード"))

    def test_search_cross_theater_mocked(self):
        mock_theaters = [
            {"chain_id": "toho", "theater_id": "t1", "theater_name": "TOHO劇場A", "prefecture": "東京都"},
            {"chain_id": "aeon", "theater_id": "a1", "theater_name": "イオン劇場B", "prefecture": "東京都"},
        ]

        def fake_provider(chain_id):
            mock_p = MagicMock()
            if chain_id == "toho":
                mock_p.fetch_movies.return_value = [
                    MovieSchedule(
                        movie_id="m1",
                        movie_title="バイオハザード（字幕版）",
                        screenings=[
                            Screening(
                                event_id="e1",
                                screen_name="スクリーン1",
                                start_time="10:00",
                                end_time="11:50",
                                seat_status=SeatStatus.AVAILABLE,
                                booking_url="https://hlo.tohotheater.jp/net/ticket/t1/test",
                            )
                        ],
                    )
                ]
            else:
                mock_p.fetch_movies.return_value = [
                    MovieSchedule(
                        movie_id="m2",
                        movie_title="字幕 バイオハザード",
                        screenings=[
                            Screening(
                                event_id="e2",
                                screen_name="スクリーン2",
                                start_time="9:30",
                                end_time="11:20",
                                seat_status=SeatStatus.FEW,
                                booking_url="https://login.watatheatre.aeoncinema.com/auth?eventId=e2",
                            )
                        ],
                    )
                ]
            return mock_p

        with patch("scraper.search.get_theaters_by_area", return_value=mock_theaters), \
             patch("scraper.search.get_provider", side_effect=fake_provider):
            resp = search_cross_theater("バイオハザード", "東京都", date(2026, 10, 17))
            self.assertEqual(resp.total_screenings, 2)
            # 時刻順ソート確認: "09:30" (イオン) が "10:00" (TOHO) より前に来ること
            self.assertEqual(resp.screenings[0].start_time, "09:30")
            self.assertEqual(resp.screenings[0].theater_name, "イオン劇場B")
            self.assertEqual(resp.screenings[1].start_time, "10:00")
            self.assertEqual(resp.screenings[1].theater_name, "TOHO劇場A")

    def test_after_time_filter(self):
        mock_theaters = [
            {"chain_id": "toho", "theater_id": "t1", "theater_name": "TOHO劇場A", "prefecture": "東京都"},
        ]

        def fake_provider(chain_id):
            mock_p = MagicMock()
            mock_p.fetch_movies.return_value = [
                MovieSchedule(
                    movie_id="m1",
                    movie_title="バイオハザード",
                    screenings=[
                        Screening(
                            event_id="e1",
                            screen_name="スクリーン1",
                            start_time="09:00",
                            end_time="11:00",
                            seat_status=SeatStatus.AVAILABLE,
                            booking_url="https://hlo.tohotheater.jp/net/ticket/t1/test1",
                        ),
                        Screening(
                            event_id="e2",
                            screen_name="スクリーン1",
                            start_time="11:30",
                            end_time="13:30",
                            seat_status=SeatStatus.AVAILABLE,
                            booking_url="https://hlo.tohotheater.jp/net/ticket/t1/test2",
                        ),
                        Screening(
                            event_id="e3",
                            screen_name="スクリーン1",
                            start_time="15:00",
                            end_time="17:00",
                            seat_status=SeatStatus.AVAILABLE,
                            booking_url="https://hlo.tohotheater.jp/net/ticket/t1/test3",
                        ),
                    ],
                )
            ]
            return mock_p

        with patch("scraper.search.get_theaters_by_area", return_value=mock_theaters), \
             patch("scraper.search.get_provider", side_effect=fake_provider):
            # 11:00 以降を指定 -> 09:00 は除外され、11:30 と 15:00 の2件が残る
            resp = search_cross_theater("バイオハザード", "東京都", date(2026, 10, 17), after_time="11:00")
            self.assertEqual(resp.total_screenings, 2)
            self.assertEqual(resp.screenings[0].start_time, "11:30")
            self.assertEqual(resp.screenings[1].start_time, "15:00")

    def test_cli_search_mode_missing_args(self):
        with patch("sys.stderr"):
            # title 欠落
            code1 = scraper.cli.main(["--mode", "search", "--area", "東京都"])
            self.assertEqual(code1, 2)
            # area 欠落
            code2 = scraper.cli.main(["--mode", "search", "--title", "ちいかわ"])
            self.assertEqual(code2, 2)

    def test_cli_search_mode_success(self):
        fake_resp = CrossTheaterSearchResponse(
            query_title="テスト作品",
            area="東京都",
            target_date="2026-10-17",
            total_screenings=1,
            screenings=[
                CrossTheaterScreening(
                    chain_id="toho",
                    theater_id="009",
                    theater_name="TOHOシネマズ 新宿",
                    screen_name="スクリーン1",
                    start_time="12:00",
                    end_time="14:00",
                    seat_status=SeatStatus.AVAILABLE,
                    booking_url="https://hlo.tohotheater.jp/net/ticket/009/test",
                    movie_title="テスト作品",
                )
            ],
        )
        with patch("scraper.search.search_cross_theater", return_value=fake_resp) as mock_search, \
             patch("builtins.print") as mock_print:
            code = scraper.cli.main([
                "--mode", "search",
                "--title", "テスト作品",
                "--area", "東京都",
                "--after", "11:30",
                "--compact"
            ])
            mock_search.assert_called_once_with(
                title="テスト作品",
                area="東京都",
                target_date=date.today(),
                after_time="11:30",
                theater=None,
            )
            mock_print.assert_called_once()
            output = mock_print.call_args[0][0]
            self.assertIn('"query_title": "テスト作品"', output)
            self.assertIn('"theater_name": "TOHOシネマズ 新宿"', output)

    def test_cli_search_mode_with_theater_filter(self):
        fake_resp = CrossTheaterSearchResponse(
            query_title="テスト作品",
            area="東京都",
            target_date="2026-10-17",
            total_screenings=1,
            screenings=[],
        )
        with patch("scraper.search.search_cross_theater", return_value=fake_resp) as mock_search, \
             patch("builtins.print"):
            code = scraper.cli.main([
                "--mode", "search",
                "--title", "テスト作品",
                "--area", "東京都",
                "--theater", "新宿",
                "--compact"
            ])
            self.assertEqual(code, 0)
            mock_search.assert_called_once_with(
                title="テスト作品",
                area="東京都",
                target_date=date.today(),
                after_time=None,
                theater="新宿",
            )

        # --theter (タイポ許容) でも同じく動作することを検証
        with patch("scraper.search.search_cross_theater", return_value=fake_resp) as mock_search, \
             patch("builtins.print"):
            code = scraper.cli.main([
                "--mode", "search",
                "--title", "テスト作品",
                "--area", "東京都",
                "--theter", "新宿",
                "--compact"
            ])
            self.assertEqual(code, 0)
            mock_search.assert_called_once_with(
                title="テスト作品",
                area="東京都",
                target_date=date.today(),
                after_time=None,
                theater="新宿",
            )


if __name__ == "__main__":
    unittest.main()
