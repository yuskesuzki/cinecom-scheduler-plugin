import json
import unittest
from datetime import date
from unittest.mock import patch

from scraper.sanitizer import sanitize_identifier, build_safe_url, UnsafeUrlError
from scraper.models import SeatStatus, Screening, MovieSchedule, TheaterScheduleResponse
from scraper.providers import get_provider
from scraper.providers.aeon import AeonCinemaProvider
import scraper.cli


class TestScraperPackage(unittest.TestCase):
    def test_sanitizer_valid(self):
        self.assertEqual(sanitize_identifier("ebetsu"), "ebetsu")
        self.assertEqual(sanitize_identifier("event-123_45.ok"), "event-123_45.ok")

    def test_sanitizer_invalid(self):
        with self.assertRaises(UnsafeUrlError):
            sanitize_identifier("ebetsu;id")
        with self.assertRaises(UnsafeUrlError):
            sanitize_identifier("ebetsu' OR '1'='1")
        with self.assertRaises(UnsafeUrlError):
            sanitize_identifier("")
        with self.assertRaises(UnsafeUrlError):
            sanitize_identifier("a" * 65)
        with self.assertRaises(UnsafeUrlError):
            sanitize_identifier("../etc/passwd")
        with self.assertRaises(UnsafeUrlError):
            sanitize_identifier("foo..bar")
        with self.assertRaises(UnsafeUrlError):
            sanitize_identifier("--help")
        with self.assertRaises(UnsafeUrlError):
            sanitize_identifier(".hidden")

    def test_build_safe_url(self):
        url = build_safe_url(
            "https://login.watatheatre.aeoncinema.com/auth",
            query_params={"eventId": "6ac49670691a0d4b99b984c2"},
        )
        self.assertEqual(
            url,
            "https://login.watatheatre.aeoncinema.com/auth?eventId=6ac49670691a0d4b99b984c2",
        )

    def test_build_safe_url_domain_rejection(self):
        with self.assertRaises(UnsafeUrlError):
            build_safe_url("https://malicious-site.com/auth")

    def test_aeon_provider_booking_url_safety(self):
        provider = AeonCinemaProvider()
        url = provider.build_booking_url("ebetsu", "6ac49670691a0d4b99b984c2")
        self.assertTrue(url.startswith("https://login.watatheatre.aeoncinema.com/auth?eventId="))

        with self.assertRaises(UnsafeUrlError):
            provider.build_booking_url("ebetsu", "6ac49670;rm -rf /")

    def test_models_to_json(self):
        resp = TheaterScheduleResponse(
            chain_id="aeon",
            theater_id="ebetsu",
            theater_name="江別",
            target_date="2026-10-15",
            movies=[
                MovieSchedule(
                    movie_id="m1",
                    movie_title="テスト映画",
                    screenings=[
                        Screening(
                            event_id="ev1",
                            screen_name="スクリーン1",
                            start_time="10:00",
                            end_time="12:00",
                            seat_status=SeatStatus.AVAILABLE,
                            booking_url="https://login.watatheatre.aeoncinema.com/auth?eventId=ev1",
                            tags=["IMAX"],
                        )
                    ],
                )
            ],
        )
        compact_json = resp.to_json(indent=None)
        self.assertIn('"seat_status": "available"', compact_json)
        self.assertIn('"tags": ["IMAX"]', compact_json)

    @patch("sys.argv", ["scraper.cli", "--chain", "aeon", "--theater", "ebetsu;malicious"])
    def test_cli_injection_exit_code_2(self):
        with patch("sys.stderr"):
            exit_code = scraper.cli.main()
            self.assertEqual(exit_code, 2)

    def test_toho_provider_registration(self):
        from scraper.providers.toho import TohoCinemaProvider
        provider = get_provider("toho")
        self.assertIsInstance(provider, TohoCinemaProvider)
        info = provider.get_theater_info("089")
        self.assertEqual(info.get("name"), "TOHOシネマズ すすきの")

    def test_toho_booking_url_safety(self):
        from scraper.providers.toho import TohoCinemaProvider
        provider = TohoCinemaProvider()
        url = provider.build_booking_url(
            theater_id="089",
            event_id="6",
            extra_params={"jyoei_date": "20261015", "sakuhin_cd": "029750"}
        )
        self.assertTrue(url.startswith("https://hlo.tohotheater.jp/net/ticket/089/TNPI2040J03.do"))
        self.assertIn("pf_no=6", url)
        self.assertIn("sakuhin_cd=029750", url)

        with self.assertRaises(UnsafeUrlError):
            provider.build_booking_url("089", "6;calc")

    @patch("sys.argv", ["scraper.cli", "--chain", "toho", "--theater", "089;malicious"])
    def test_toho_cli_injection_exit_code_2(self):
        with patch("sys.stderr"):
            exit_code = scraper.cli.main()
            self.assertEqual(exit_code, 2)

    def test_united_provider_registration(self):
        from scraper.providers.united import UnitedCinemaProvider
        provider = get_provider("united")
        self.assertIsInstance(provider, UnitedCinemaProvider)
        info = provider.get_theater_info("sapporo")
        self.assertEqual(info.get("name"), "ローソン・ユナイテッドシネマ札幌")

    def test_united_booking_url_safety(self):
        from scraper.providers.united import UnitedCinemaProvider
        provider = UnitedCinemaProvider()
        safe_href = "/all/cc.php?tc=004&amp;sd=20261015&amp;sc=010&amp;st=20261015194000&amp;mc=25278"
        url = provider._build_safe_booking_url(safe_href)
        self.assertIsNotNone(url)
        self.assertTrue(url.startswith("https://www.unitedcinemas.jp/all/cc.php?"))
        self.assertIn("tc=004", url)
        self.assertIn("st=20261015194000", url)

        # 悪意あるリンクの検証
        malicious_href = "javascript:alert(1)"
        self.assertIsNone(provider._build_safe_booking_url(malicious_href))

        malicious_href_domain = "https://evil.com/all/cc.php?tc=004"
        self.assertIsNone(provider._build_safe_booking_url(malicious_href_domain))

    @patch("sys.argv", ["scraper.cli", "--chain", "united", "--theater", "sapporo;malicious"])
    def test_united_cli_injection_exit_code_2(self):
        with patch("sys.stderr"):
            exit_code = scraper.cli.main()
            self.assertEqual(exit_code, 2)


    def test_sunshine_provider_registration(self):
        from scraper.providers.sunshine import CinemaSunshineProvider
        provider = get_provider("sunshine")
        self.assertIsInstance(provider, CinemaSunshineProvider)
        info = provider.get_theater_info("gdcs")
        self.assertEqual(info.get("name"), "グランドシネマサンシャイン 池袋")
        self.assertEqual(info.get("smart_theater_no"), "020")

    def test_sunshine_booking_url_safety(self):
        from scraper.providers.sunshine import CinemaSunshineProvider
        provider = CinemaSunshineProvider()
        url = provider.build_booking_url(
            theater_id="gdcs",
            event_id="02027649020261016622050",
        )
        self.assertEqual(
            url,
            "https://transaction.ticket-cinemasunshine.com/projects/sskts-production/purchase/transaction/02027649020261016622050",
        )

        with self.assertRaises(UnsafeUrlError):
            provider.build_booking_url("gdcs", "02027649;calc")

    @patch("sys.argv", ["scraper.cli", "--chain", "sunshine", "--theater", "gdcs;malicious"])
    def test_sunshine_cli_injection_exit_code_2(self):
        with patch("sys.stderr"):
            exit_code = scraper.cli.main()
            self.assertEqual(exit_code, 2)

    def test_info_urls(self):
        from scraper.providers.toho import TohoCinemaProvider
        from scraper.providers.sunshine import CinemaSunshineProvider
        from scraper.providers.united import UnitedCinemaProvider
        from scraper.providers.aeon import AeonCinemaProvider

        # TOHO
        toho = TohoCinemaProvider()
        toho_url = toho.build_movie_info_url("028639")
        self.assertEqual(
            toho_url,
            "https://hlo.tohotheater.jp/net/movie/TNPI3060J01.do?sakuhin_cd=028639",
        )

        # Sunshine with mocked CMS cache
        sunshine = CinemaSunshineProvider()
        sunshine._movie_cms_cache = [{"id": 2433, "title": "テスト作品"}]
        sunshine_url = sunshine.get_movie_info_url("テスト作品", "gdcs")
        self.assertEqual(
            sunshine_url,
            "https://www.cinemasunshine.co.jp/movies/2433/?theater=",
        )

        # United safe movie url
        safe_url = build_safe_url("https://www.unitedcinemas.jp/makuhari/film.php", query_params={"film": "22516"})
        self.assertEqual(safe_url, "https://www.unitedcinemas.jp/makuhari/film.php?film=22516")

        # Aeon movie url
        aeon = AeonCinemaProvider()
        aeon_url = aeon.build_movie_info_url(identifier="2000059", theater_id="makuhari")
        self.assertEqual(aeon_url, "https://www.aeoncinema.com/cinema2/all/movie/2000059/")

        # Aeon fallback to theater url
        aeon_fallback = aeon.build_movie_info_url(identifier=None, theater_id="makuhari")
        self.assertEqual(aeon_fallback, "https://theater.aeoncinema.com/theaters/makuhari/")


if __name__ == "__main__":
    unittest.main()


