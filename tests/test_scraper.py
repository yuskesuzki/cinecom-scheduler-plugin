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

    def test_tjoy_provider_registration(self):
        from scraper.providers.tjoy import TJoyCinemaProvider
        provider = get_provider("tjoy")
        self.assertIsInstance(provider, TJoyCinemaProvider)
        info = provider.get_theater_info("shinjuku_wald9")
        self.assertEqual(info.get("name"), "新宿バルト9")
        self.assertEqual(info.get("tjoy_theater_id"), "140")

    def test_tjoy_booking_url_safety(self):
        from scraper.providers.tjoy import TJoyCinemaProvider
        provider = TJoyCinemaProvider()
        safe_url = provider._build_safe_booking_url(
            "/shinjuku_wald9/reservation/index/2292510/C5012060/6/2026-11-23?type=film"
        )
        self.assertEqual(
            safe_url,
            "https://tjoy.jp/shinjuku_wald9/reservation/index/2292510/C5012060/6/2026-11-23?type=film",
        )
        self.assertEqual(provider._build_safe_booking_url("javascript:void(0);"), "")
        self.assertEqual(
            provider._build_safe_booking_url("https://evil.com/shinjuku_wald9/reservation/index/1/2/3/2026-11-23"),
            "",
        )
        with self.assertRaises(UnsafeUrlError):
            provider.build_booking_url("shinjuku_wald9", "2292510;calc")

    @patch("sys.argv", ["scraper.cli", "--chain", "tjoy", "--theater", "shinjuku_wald9;malicious"])
    def test_tjoy_cli_injection_exit_code_2(self):
        with patch("sys.stderr"):
            exit_code = scraper.cli.main()
            self.assertEqual(exit_code, 2)

    def test_tjoy_parse_schedule_html(self):
        from scraper.providers.tjoy import TJoyCinemaProvider

        sample_html = """
        <section class="section-container bg-white">
            <div class="card-header film-item" data-target="#tab-film-0">
                <span class="badge lb-icon lb-rate-dolby">Dolby Atmos</span>
                <span class="badge lb-icon lb-rate-dub">字幕</span>
                <span class="badge lb-icon">PG12</span>
                <h5 class="js-title-film">【DolbyAtmos】魔法使いの夜</h5>
                <span>Witch on The Holy Night</span>
            </div>
            <div class="panel">
                <div class="card-body" id="tab-film-0">
                    <a onclick="window.location.href='/shinjuku_wald9/cinema_detail/C5012060'">作品詳細</a>
                    <ul>
                        <li class="schedule-box">
                            <div class="theater-name"><a>シアター６</a></div>
                            <div onclick="location.href ='/shinjuku_wald9/reservation/index/2292510/C5012060/6/2026-11-23?type=film'">
                                <p class="schedule-time">9:30 <span>～ 11:40</span></p>
                                <p class="schedule-status"><span>予約/購入</span><img src="/img/front/images/icon/icon_label3.png"></p>
                            </div>
                        </li>
                        <li class="schedule-box">
                            <div class="theater-name"><a>シアター８</a></div>
                            <div onclick="location.href ='/shinjuku_wald9/reservation/index/2292511/C5012060/8/2026-11-23?type=film'">
                                <p class="schedule-time">14:00 <span>～ 16:10</span></p>
                                <p class="schedule-status"><span>予約/購入</span><img src="/img/front/images/icon/icon_label2.png"></p>
                            </div>
                        </li>
                        <li class="schedule-box">
                            <div class="theater-name"><a>シアター８</a></div>
                            <div onclick="location.href ='/shinjuku_wald9/reservation/index/2292512/C5012060/8/2026-11-23?type=film'">
                                <p class="schedule-time">18:00 <span>～ 20:10</span></p>
                                <p class="schedule-status"><span>購入</span><img src="/img/front/images/icon/icon_label4.png"></p>
                            </div>
                        </li>
                        <li class="schedule-box disable">
                            <div class="theater-name"><a>シアター８</a></div>
                            <div onclick="javascript:void(0);">
                                <p class="schedule-time">24:10 <span>～ 26:20</span></p>
                                <p class="schedule-status"><span>満席</span><img src="/img/front/images/icon/icon_label5.png"></p>
                            </div>
                        </li>
                    </ul>
                </div>
            </div>
        </section>
        <section class="section-container bg-white">
            <div class="card-header film-item" data-target="#tab-film-1">
                <span class="badge lb-icon">IMAXレーザー</span>
                <span class="badge lb-icon">SCREENX with Dolby Atmos</span>
                <span class="badge lb-icon">吹替</span>
                <span class="badge lb-icon">2D</span>
                <h5 class="js-title-film">テスト映画【DolbyCinema】</h5>
                <span></span>
            </div>
            <div class="panel">
                <div class="card-body" id="tab-film-1">
                    <a onclick="window.location.href='/shinjuku_wald9/cinema_detail/C9999000'">作品詳細</a>
                    <ul>
                        <li class="schedule-box disable">
                            <div class="theater-name"><a>シアター７ T-LEX</a></div>
                            <div onclick="javascript:void(0);">
                                <p class="schedule-time">10:00 <span>～ 12:00</span></p>
                                <p class="schedule-status"><span>終了</span><img src="/img/front/images/icon/icon_label1.png"></p>
                            </div>
                        </li>
                        <li class="schedule-box disable">
                            <div class="theater-name"><a>シアター７ T-LEX</a></div>
                            <div onclick="javascript:void(0);">
                                <p class="schedule-time">13:00 <span>～ 15:00</span></p>
                                <p class="schedule-status"><span>販売終了</span><img src="/img/front/images/icon/icon_label1.png"></p>
                            </div>
                        </li>
                        <li class="schedule-box disable">
                            <div class="theater-name"><a>シアター７ T-LEX</a></div>
                            <div onclick="javascript:void(0);">
                                <p class="schedule-time">16:00 <span>～ 18:00</span></p>
                                <p class="schedule-status"><span>販売対象外</span><img src="/img/front/images/icon/icon_label1.png"></p>
                            </div>
                        </li>
                    </ul>
                </div>
            </div>
        </section>
        """

        provider = TJoyCinemaProvider()
        with patch.object(provider, "_post_schedule_api", return_value=sample_html):
            movies = provider.fetch_movies("shinjuku_wald9", date(2026, 11, 23))

        self.assertEqual(len(movies), 2)

        m0 = movies[0]
        self.assertEqual(m0.movie_id, "C5012060")
        self.assertEqual(m0.movie_title, "【DolbyAtmos】魔法使いの夜")
        self.assertEqual(m0.movie_title_en, "Witch on The Holy Night")
        self.assertEqual(m0.info_url, "https://tjoy.jp/shinjuku_wald9/cinema_detail/C5012060")
        self.assertEqual(len(m0.screenings), 4)

        # 時刻ゼロ埋め・深夜24時超え・シアター名半角正規化
        self.assertEqual(m0.screenings[0].start_time, "09:30")
        self.assertEqual(m0.screenings[0].end_time, "11:40")
        self.assertEqual(m0.screenings[0].screen_name, "シアター6")
        self.assertEqual(m0.screenings[0].seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(
            m0.screenings[0].booking_url,
            "https://tjoy.jp/shinjuku_wald9/reservation/index/2292510/C5012060/6/2026-11-23?type=film",
        )
        # 施設マスタ上のDolby Cinemaを誤混入させず Dolby Atmos のみ抽出、字幕・PG12は含めない
        self.assertEqual(m0.screenings[0].tags, ["Dolby Atmos"])

        self.assertEqual(m0.screenings[1].screen_name, "シアター8")
        self.assertEqual(m0.screenings[1].seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(m0.screenings[2].seat_status, SeatStatus.FEW)
        self.assertEqual(m0.screenings[3].start_time, "24:10")
        self.assertEqual(m0.screenings[3].end_time, "26:20")
        self.assertEqual(m0.screenings[3].seat_status, SeatStatus.FULL)
        self.assertEqual(m0.screenings[3].booking_url, "")

        m1 = movies[1]
        self.assertIsNone(m1.movie_title_en)
        self.assertEqual(m1.screenings[0].screen_name, "シアター7 T-LEX")
        self.assertEqual(m1.screenings[0].seat_status, SeatStatus.UNSOLD)
        self.assertEqual(m1.screenings[1].seat_status, SeatStatus.UNSOLD)
        self.assertEqual(m1.screenings[2].seat_status, SeatStatus.UNSOLD)
        self.assertIn("IMAXレーザー", m1.screenings[0].tags)
        self.assertNotIn("IMAX", m1.screenings[0].tags)
        self.assertIn("Dolby Cinema", m1.screenings[0].tags)
        self.assertIn("Dolby Atmos", m1.screenings[0].tags)
        self.assertIn("ScreenX", m1.screenings[0].tags)
        self.assertIn("T-LEX", m1.screenings[0].tags)
        self.assertNotIn("吹替", m1.screenings[0].tags)
        self.assertNotIn("2D", m1.screenings[0].tags)

    def test_info_urls(self):
        from scraper.providers.toho import TohoCinemaProvider
        from scraper.providers.sunshine import CinemaSunshineProvider
        from scraper.providers.united import UnitedCinemaProvider
        from scraper.providers.aeon import AeonCinemaProvider
        from scraper.providers.tjoy import TJoyCinemaProvider

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

        # T-Joy movie url & fallback
        tjoy = TJoyCinemaProvider()
        self.assertEqual(
            tjoy.build_movie_info_url("shinjuku_wald9", "C5012060"),
            "https://tjoy.jp/shinjuku_wald9/cinema_detail/C5012060",
        )
        self.assertEqual(
            tjoy.build_movie_info_url("shinjuku_wald9", None),
            "https://tjoy.jp/shinjuku_wald9",
        )


if __name__ == "__main__":
    unittest.main()


