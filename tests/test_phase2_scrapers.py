from datetime import date, datetime, timezone
import io
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
import urllib.error

from scraper.models import SeatStatus
from scraper.providers import PROVIDER_REGISTRY, get_provider
from scraper.providers.korona import (
    KoronaCinemaProvider,
    determine_korona_seat_status,
    normalize_korona_screen_name,
    parse_korona_work_schedule,
)
from scraper.providers.ttcg import (
    TtcgCinemaProvider,
    map_ttcg_seat_status,
    normalize_ttcg_screen_name,
    parse_ttcg_schedule_json,
    validate_ttcg_booking_url,
)
from scraper.sanitizer import UnsafeUrlError


class _FakeHttpResponse:
    def __init__(self, body_bytes: bytes):
        self._body = body_bytes

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestPhase2ProviderRegistry(unittest.TestCase):
    """korona / ttcg プロバイダ登録とマスタ・セキュリティの統合テスト"""

    def test_korona_and_ttcg_registered_with_expected_counts(self):
        self.assertIn("korona", PROVIDER_REGISTRY)
        self.assertIn("ttcg", PROVIDER_REGISTRY)

        korona = get_provider("korona")
        self.assertIsInstance(korona, KoronaCinemaProvider)
        self.assertEqual(len(korona._load_theaters_master()), 11)
        self.assertEqual(korona.get_theater_name("kom"), "小牧コロナシネマワールド")
        self.assertEqual(korona.get_theater_name("laa"), "シネマワールド ららぽーと安城")

        ttcg = get_provider("ttcg")
        self.assertIsInstance(ttcg, TtcgCinemaProvider)
        self.assertEqual(len(ttcg._load_theaters_master()), 6)
        self.assertEqual(ttcg.get_theater_name("theatre_shinjuku"), "テアトル新宿")
        self.assertEqual(ttcg.get_theater_name("ttcg_umeda"), "テアトル梅田")

    def test_rejects_malicious_theater_ids_and_cli_execution(self):
        for chain in ("korona", "ttcg"):
            provider = get_provider(chain)
            with self.assertRaises(UnsafeUrlError):
                provider.fetch_movies("../etc/passwd", date(2026, 11, 23))
            with self.assertRaises(RuntimeError):
                provider.fetch_movies("unknown_theater_id", date(2026, 11, 23))

            res = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scraper.cli",
                    "--chain",
                    chain,
                    "--theater",
                    "../bad",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 2)
            self.assertIn("security_violation", res.stderr)


class TestKoronaProvider(unittest.TestCase):
    """コロナワールド (KoronaCinemaProvider) の単体テスト"""

    def test_determine_korona_seat_status_sales_window_and_capacity(self):
        now_utc = datetime(2026, 11, 23, 2, 0, tzinfo=timezone.utc)

        # 販売開始前 -> UNSOLD
        ev_before = {
            "maximumAttendeeCapacity": 100,
            "remainingAttendeeCapacity": 100,
            "offers": {
                "validFrom": "2026-11-23T03:00:00.000Z",
                "validThrough": "2026-11-24T03:00:00.000Z",
            },
        }
        self.assertEqual(determine_korona_seat_status(ev_before, now_utc), SeatStatus.UNSOLD)

        # 販売終了後 -> UNSOLD
        ev_after = {
            "maximumAttendeeCapacity": 100,
            "remainingAttendeeCapacity": 50,
            "offers": {
                "validFrom": "2026-11-20T00:00:00.000Z",
                "validThrough": "2026-11-23T01:30:00.000Z",
            },
        }
        self.assertEqual(determine_korona_seat_status(ev_after, now_utc), SeatStatus.UNSOLD)

        # 販売中 (余裕あり / わずか / 満席 / 残席不明)
        base_offers = {
            "validFrom": "2026-11-20T00:00:00.000Z",
            "validThrough": "2026-11-23T05:00:00.000Z",
        }
        self.assertEqual(
            determine_korona_seat_status(
                {"maximumAttendeeCapacity": 100, "remainingAttendeeCapacity": 60, "offers": base_offers},
                now_utc,
            ),
            SeatStatus.AVAILABLE,
        )
        self.assertEqual(
            determine_korona_seat_status(
                {"maximumAttendeeCapacity": 100, "remainingAttendeeCapacity": 10, "offers": base_offers},
                now_utc,
            ),
            SeatStatus.FEW,
        )
        self.assertEqual(
            determine_korona_seat_status(
                {"maximumAttendeeCapacity": 100, "remainingAttendeeCapacity": 0, "offers": base_offers},
                now_utc,
            ),
            SeatStatus.FULL,
        )
        self.assertEqual(
            determine_korona_seat_status({"offers": base_offers}, now_utc),
            SeatStatus.UNKNOWN,
        )

    def test_normalize_korona_screen_name(self):
        self.assertEqual(normalize_korona_screen_name("スクリーン８"), "スクリーン8")
        self.assertEqual(normalize_korona_screen_name("スクリーン４(4DX)"), "スクリーン4(4DX)")
        self.assertEqual(normalize_korona_screen_name(""), "スクリーン未定")

    def test_parse_korona_work_schedule_with_facility_tags_and_booking(self):
        provider = KoronaCinemaProvider()
        laa_info = provider.get_theater_info("laa")
        now_utc = datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc)

        work_json = {
            "1050": {
                "scr001": {
                    "id": "ev_ok_1",
                    "startDate": "2026-11-23T01:50:00.000Z",  # 10:50 JST
                    "endDate": "2026-11-23T03:40:00.000Z",    # 12:40 JST
                    "name": {"ja": "テスト映画ＩＭＡＸ", "en": "Test Film IMAX"},
                    "maximumAttendeeCapacity": 260,
                    "remainingAttendeeCapacity": 200,
                    "location": {"branchCode": "scr001", "name": {"ja": "スクリーン１"}},
                    "offers": {
                        "validFrom": "2026-11-20T00:00:00.000Z",
                        "validThrough": "2026-11-23T02:05:00.000Z",
                    },
                    "superEvent": {"id": "mv_test1", "description": {"ja": "ＩＭＡＸレーザー上映"}},
                },
                "scr002": {
                    "id": "../bad_event_id",
                    "startDate": "2026-11-23T05:00:00.000Z",  # 14:00 JST
                    "endDate": "2026-11-23T07:00:00.000Z",    # 16:00 JST
                    "name": {"ja": "テスト映画ＩＭＡＸ", "en": "Test Film IMAX"},
                    "maximumAttendeeCapacity": 100,
                    "remainingAttendeeCapacity": 0,
                    "location": {"branchCode": "scr002", "name": {"ja": "スクリーン2"}},
                    "offers": {
                        "validFrom": "2026-11-20T00:00:00.000Z",
                        "validThrough": "2026-11-23T05:15:00.000Z",
                    },
                    "superEvent": {"id": "mv_test1", "description": {"ja": ""}},
                },
            }
        }

        parsed = parse_korona_work_schedule(
            work_json=work_json,
            theater_info=laa_info,
            booking_builder=lambda eid: provider.build_booking_url("laa", eid),
            info_url="https://cinema.korona.co.jp/theaters/laa/",
            now_utc=now_utc,
        )
        self.assertIn("mv_test1", parsed)
        movie = parsed["mv_test1"]
        self.assertEqual(movie.movie_title_en, "Test Film IMAX")
        self.assertEqual(len(movie.screenings), 2)

        s0, s1 = movie.screenings
        self.assertEqual(s0.screen_name, "スクリーン1")
        self.assertEqual(s0.start_time, "10:50")
        self.assertEqual(s0.end_time, "12:40")
        self.assertEqual(s0.seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(
            s0.booking_url,
            "https://login.member.korona.co.jp/purchase/guest?eventId=ev_ok_1",
        )
        self.assertIn("IMAXレーザー", s0.tags)

        # FULL の回は booking_url 空
        self.assertEqual(s1.seat_status, SeatStatus.FULL)
        self.assertEqual(s1.booking_url, "")

    def test_fetch_movies_mocked_and_missing_work_404_ignored(self):
        provider = KoronaCinemaProvider()
        index_payload = {
            "w1": {"001": {"20261123": {"1000": []}}},
            "w_404": {"001": {"20261123": {"1200": []}}},
            "w_other": {"004": {"20261123": {"1000": []}}},
        }
        w1_payload = {
            "1000": {
                "scr004": {
                    "id": "korona_ev_99",
                    "startDate": "2026-11-23T01:00:00.000Z",
                    "endDate": "2026-11-23T03:00:00.000Z",
                    "name": {"ja": "テスト作品A"},
                    "maximumAttendeeCapacity": 56,
                    "remainingAttendeeCapacity": 30,
                    "location": {"branchCode": "scr004", "name": {"ja": "スクリーン4(4DX)"}},
                    "offers": {
                        "validFrom": "2026-01-01T00:00:00.000Z",
                        "validThrough": "2099-01-01T00:00:00.000Z",
                    },
                    "superEvent": {"id": "sup_a"},
                }
            }
        }

        opened_errors = []

        def fake_urlopen(req, timeout=15):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/schedule.json" in url:
                return _FakeHttpResponse(json.dumps(index_payload).encode("utf-8"))
            if "/w1/001/20261123.json" in url:
                return _FakeHttpResponse(json.dumps(w1_payload).encode("utf-8"))
            if "/w_404/001/20261123.json" in url:
                fp = io.BytesIO(b"")
                err = urllib.error.HTTPError(url, 404, "Not Found", {}, fp)
                opened_errors.append(err)
                raise err
            raise AssertionError(f"Unexpected URL requested: {url}")

        try:
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                movies = provider.fetch_movies("kom", date(2026, 11, 23))
                empty_day = provider.fetch_movies("kom", date(2026, 11, 29))
        finally:
            for err in opened_errors:
                err.close()

        self.assertEqual(empty_day, [])
        self.assertEqual(len(movies), 1)
        self.assertEqual(movies[0].movie_title, "テスト作品A")
        self.assertEqual(movies[0].screenings[0].screen_name, "スクリーン4(4DX)")
        self.assertIn("4DX", movies[0].screenings[0].tags)


class TestTtcgProvider(unittest.TestCase):
    """テアトルシネマグループ (TtcgCinemaProvider) の単体テスト"""

    def test_status_mapping_and_screen_normalization(self):
        self.assertEqual(map_ttcg_seat_status("0"), (SeatStatus.AVAILABLE, True))
        self.assertEqual(map_ttcg_seat_status("1"), (SeatStatus.AVAILABLE, False))
        self.assertEqual(map_ttcg_seat_status("2"), (SeatStatus.FEW, True))
        self.assertEqual(map_ttcg_seat_status("4"), (SeatStatus.FEW, False))
        self.assertEqual(map_ttcg_seat_status("5"), (SeatStatus.FULL, False))
        self.assertEqual(map_ttcg_seat_status("6"), (SeatStatus.UNSOLD, False))
        self.assertEqual(map_ttcg_seat_status("99"), (SeatStatus.UNKNOWN, False))

        self.assertEqual(normalize_ttcg_screen_name("座席券"), "シアター1")
        self.assertEqual(normalize_ttcg_screen_name("odessaｼｱﾀｰ"), "シアター1")
        self.assertEqual(normalize_ttcg_screen_name("odessa ｼｱﾀｰ1"), "シアター1")
        self.assertEqual(normalize_ttcg_screen_name("odessaｼﾈﾏ1"), "シネマ1")
        self.assertEqual(normalize_ttcg_screen_name("シネマ３"), "シネマ3")
        self.assertEqual(normalize_ttcg_screen_name("キネカ２"), "キネカ2")

    def test_validate_ttcg_booking_url_security(self):
        ok_url = "https://ttcg-shibuya.cineticket.jp/theater/sy/screen/1/select_seat_pre?date=20261123&title=13711-0"
        res = validate_ttcg_booking_url(ok_url, ticket_host="ttcg-shibuya.cineticket.jp")
        self.assertTrue(res.startswith("https://ttcg-shibuya.cineticket.jp/theater/sy/screen/1/select_seat_pre?"))
        self.assertIn("date=20261123", res)

        # HTTP・未許可ドメイン・別劇場ホストは拒否
        self.assertEqual(validate_ttcg_booking_url("http://ttcg-shibuya.cineticket.jp/foo"), "")
        self.assertEqual(validate_ttcg_booking_url("https://evil.example.com/phish"), "")
        self.assertEqual(
            validate_ttcg_booking_url(ok_url, ticket_host="ttcg-umeda.cineticket.jp"),
            "",
        )

    def test_parse_ttcg_schedule_json_and_fetch_data_code_mapping(self):
        provider = TtcgCinemaProvider()
        umeda_info = provider.get_theater_info("ttcg_umeda")

        raw_json = {
            "dates": [
                {"date_year": "2026", "date_month": "11", "date_day": "23", "movie": ["1345700"]}
            ],
            "movies": {
                "1345700": [
                    {
                        "date_year": "2026",
                        "date_month": "11",
                        "date_day": "23",
                        "name": "テスト名作映画",
                        "ename": "Test Classic",
                        "movie_code": "1345700",
                        "comment": "",
                    }
                ]
            },
            "screens": {
                "1345700-2026-11-23": [
                    {
                        "name": "シネマ１",
                        "time": [
                            {
                                "start_time_hour": "10",
                                "start_time_minute": "15",
                                "end_time_hour": "12",
                                "end_time_minute": "05",
                                "available": "0",
                                "url": "https://ttcg-umeda.cineticket.jp/theater/um/screen/1/select_seat_pre?date=20261123",
                            },
                            {
                                "start_time_hour": "15",
                                "start_time_minute": "30",
                                "end_time_hour": "17",
                                "end_time_minute": "20",
                                "available": "1",
                                "url": "https://ttcg-umeda.cineticket.jp/theater/um/screen/1/should_not_appear",
                            },
                            {
                                "start_time_hour": "19",
                                "start_time_minute": "00",
                                "end_time_hour": "20",
                                "end_time_minute": "50",
                                "available": "5",
                                "url": "",
                            },
                        ],
                    }
                ]
            },
        }

        requested_urls = []

        def fake_urlopen(req, timeout=15):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            requested_urls.append(url)
            return _FakeHttpResponse(json.dumps(raw_json).encode("utf-8"))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            movies = provider.fetch_movies("ttcg_umeda", date(2026, 11, 23))

        # テアトル梅田のみ data_code = "cinelibre_umeda" をリクエストすること
        self.assertEqual(requested_urls, ["https://ttcg.jp/data/cinelibre_umeda.js"])
        self.assertEqual(len(movies), 1)
        m = movies[0]
        self.assertEqual(m.movie_title, "テスト名作映画")
        self.assertEqual(m.movie_title_en, "Test Classic")
        self.assertEqual(m.info_url, "https://ttcg.jp/ttcg_umeda/movie/1345700.html")
        self.assertEqual(len(m.screenings), 3)

        # シネマ1 に施設特徴 odessa が付与されていること
        self.assertEqual(m.screenings[0].screen_name, "シネマ1")
        self.assertIn("odessa", m.screenings[0].tags)
        self.assertEqual(m.screenings[0].seat_status, SeatStatus.AVAILABLE)
        self.assertIn("cineticket.jp", m.screenings[0].booking_url)

        # available="1" (窓口のみ) は booking_url 空
        self.assertEqual(m.screenings[1].seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(m.screenings[1].booking_url, "")

        # available="5" (満席)
        self.assertEqual(m.screenings[2].seat_status, SeatStatus.FULL)
        self.assertEqual(m.screenings[2].booking_url, "")

        # 対象日以外
        empty = parse_ttcg_schedule_json(raw_json, date(2026, 11, 25), "ttcg_umeda", umeda_info)
        self.assertEqual(empty, [])

    def test_shinjuku_single_screen_zaseki_mapping(self):
        provider = TtcgCinemaProvider()
        shinjuku_info = provider.get_theater_info("theatre_shinjuku")
        raw_json = {
            "dates": [{"date_year": "2026", "date_month": "11", "date_day": "23", "movie": ["1369607"]}],
            "movies": {"1369607": [{"date_year": "2026", "date_month": "11", "date_day": "23", "name": "新宿テスト", "movie_code": "1369607"}]},
            "screens": {
                "1369607-2026-11-23": [
                    {
                        "name": "座席券",
                        "time": [
                            {
                                "start_time_hour": "18",
                                "start_time_minute": "00",
                                "end_time_hour": "19",
                                "end_time_minute": "45",
                                "available": "2",
                                "url": "https://ttcg-shinjuku.cineticket.jp/theater/ts/screen/1/select_seat_pre?date=20261123",
                            }
                        ],
                    }
                ]
            },
        }
        movies = parse_ttcg_schedule_json(raw_json, date(2026, 11, 23), "theatre_shinjuku", shinjuku_info)
        self.assertEqual(len(movies), 1)
        sc = movies[0].screenings[0]
        self.assertEqual(sc.screen_name, "シアター1")
        self.assertEqual(sc.seat_status, SeatStatus.FEW)
        self.assertIn("odessa", sc.tags)

    def test_ttcg_http_404_raises_runtime_error_without_leak(self):
        provider = TtcgCinemaProvider()
        opened_errors = []

        def fake_404(req, timeout=15):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            err = urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
            opened_errors.append(err)
            raise err

        try:
            with patch("urllib.request.urlopen", side_effect=fake_404):
                with self.assertRaises(RuntimeError):
                    provider.fetch_movies("human_shibuya", date(2026, 11, 23))
        finally:
            for err in opened_errors:
                err.close()


if __name__ == "__main__":
    unittest.main()
