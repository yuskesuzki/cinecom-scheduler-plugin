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

    def test_109cinemas_provider_registration(self):
        from scraper.providers.cinemas109 import Cinemas109Provider
        provider = get_provider("109cinemas")
        self.assertIsInstance(provider, Cinemas109Provider)
        kiba = provider.get_theater_info("kiba")
        self.assertEqual(kiba.get("name"), "109シネマズ木場")
        self.assertEqual(kiba.get("theater_code"), "20")
        shinjuku = provider.get_theater_info("premiumshinjuku")
        self.assertEqual(shinjuku.get("name"), "109シネマズプレミアム新宿")
        self.assertEqual(shinjuku.get("theater_code"), "X1")

    def test_109cinemas_booking_url_safety(self):
        from scraper.providers.cinemas109 import Cinemas109Provider
        provider = Cinemas109Provider()
        raw = "https://cinema.109cinemas.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=53555&amp;tsc=20&amp;tssc=20&amp;ymd=2026-11-22&amp;cs=&amp;stt=1505"
        safe_url = provider._build_safe_booking_url(raw)
        self.assertTrue(safe_url.startswith("https://cinema.109cinemas.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?"))
        self.assertIn("ttc=53555", safe_url)
        self.assertIn("cs=", safe_url)

        self.assertEqual(provider._build_safe_booking_url("javascript:alert(1)"), "")
        self.assertEqual(
            provider._build_safe_booking_url("https://evil.com/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=53555"),
            "",
        )
        with self.assertRaises(UnsafeUrlError):
            provider.build_booking_url("20", "53555;calc")

    @patch("sys.argv", ["scraper.cli", "--chain", "109cinemas", "--theater", "kiba;malicious"])
    def test_109cinemas_cli_injection_exit_code_2(self):
        with patch("sys.stderr"):
            exit_code = scraper.cli.main()
            self.assertEqual(exit_code, 2)

    def test_109cinemas_parse_regular_and_grandexe(self):
        from scraper.providers.cinemas109 import Cinemas109Provider

        # 通常館HTML: </li> 閉じタグ省略、複数 <ul>（シアター7 + グランドEXE）、全ステータス、外部短縮URL
        sample_html = """
        <article id="m2879278" class="mg53555 imax">
          <header>
            <a href="https://109cinemas.net/movies/5764.html" target="_top">
              <h2>魔法使いの夜[IMAXレーザー][字幕][ODS]</h2>
              <p lang="en">WITCH ON THE HOLY NIGHT</p>
            </a>
          </header>
          <ul class="timetable">
            <li class="theatre">
              <a href="/futakotamagawa/seat/theater-7.gif">シアター<span class="theatre-num">7</span></a>
              IMAXレーザー SAION
              <br><small>130分</small>
            <li class=""><time class="start">9:10</time>~<time class="end">11:30</time>
              <div class="close">販売終了</div>
            <li class="check_date">
              <a href="https://cinema.109cinemas.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=53557&amp;tsc=T1&amp;tssc=T7&amp;ymd=2026-11-22&amp;cs=&amp;stt=1505">
                <time class="start">15:05</time>~<time class="end">17:25</time>
                <div class="available">購入</div>
              </a>
            <li class="check_date">
              <a href="https://cinema.109cinemas.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=53557&amp;tsc=T1&amp;tssc=T7&amp;ymd=2026-11-22&amp;cs=&amp;stt=2050">
                <time class="start">20:50</time>~<time class="end">23:10</time>
                <span class="late">[L]</span>
                <div class="remaining">残りわずか</div>
              </a>
          </ul>
          <ul class="timetable">
            <li class="theatre">
              <a href="/futakotamagawa/seat/theater-grandexe.gif"><span class="theatre-num long-name">グランドEXE</span></a>
              IMAXレーザー
            <li class="check_date">
              <a href="https://cinema.109cinemas.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=53557&amp;tsc=T1&amp;tssc=T8&amp;ymd=2026-11-22&amp;cs=&amp;stt=1505">
                <time class="start">15:05</time>~<time class="end">17:25</time>
                <div class="member">会員先行</div>
              </a>
            <li class="">
              <time class="start">22:00</time>~<time class="end">24:20</time>
              <div class="soldout">売り切れ</div>
          </ul>
        </article>
        <article id="m9990001" class="mg99901">
          <header>
            <a href="https://x.gd/J1ok2" target="_top">
              <h2>キッズイベント映画[2D]</h2>
            </a>
          </header>
          <ul class="timetable">
            <li class="theatre">
              <a href="/futakotamagawa/seat/theater-10.gif">シアター<span class="theatre-num">10</span></a>
              ULTRA 4DX KIDS CINEMA
            <li class="check_date">
              <a href="https://cinema.109cinemas.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=99901&amp;tsc=T1&amp;tssc=T10&amp;ymd=2026-11-22&amp;cs=&amp;stt=1100">
                <time class="start">11:00</time>~<time class="end">12:30</time>
                <div class="presale">先行販売</div>
              </a>
            <li class="">
              <time class="start">14:00</time>~<time class="end">15:30</time>
              <div class="others">販売開始前</div>
          </ul>
        </article>
        """

        provider = Cinemas109Provider()
        with patch.object(provider, "_fetch_schedule_html", return_value=sample_html):
            movies = provider.fetch_movies("futakotamagawa", date(2026, 11, 22))

        self.assertEqual(len(movies), 2)

        m0 = movies[0]
        self.assertEqual(m0.movie_id, "2879278")
        self.assertEqual(m0.movie_title, "魔法使いの夜[IMAXレーザー][字幕][ODS]")
        self.assertEqual(m0.movie_title_en, "WITCH ON THE HOLY NIGHT")
        self.assertEqual(m0.info_url, "https://109cinemas.net/movies/5764.html")
        self.assertEqual(len(m0.screenings), 5)

        # 時刻ゼロ埋め、グランドEXE枠の保持、各ステータス
        self.assertEqual(m0.screenings[0].start_time, "09:10")
        self.assertEqual(m0.screenings[0].screen_name, "シアター7")
        self.assertEqual(m0.screenings[0].seat_status, SeatStatus.UNSOLD)
        self.assertEqual(m0.screenings[0].tags, ["IMAXレーザー", "SAION"])

        # 15:05 は シアター7 と グランドEXE の2枠が存在すること
        slots_1505 = [s for s in m0.screenings if s.start_time == "15:05"]
        self.assertEqual(len(slots_1505), 2)
        self.assertEqual(slots_1505[0].screen_name, "グランドEXE")
        self.assertEqual(slots_1505[0].seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(slots_1505[0].event_id, "53557_T8_1505")
        self.assertEqual(slots_1505[1].screen_name, "シアター7")
        self.assertEqual(slots_1505[1].seat_status, SeatStatus.AVAILABLE)

        self.assertEqual(m0.screenings[3].seat_status, SeatStatus.FEW)
        self.assertEqual(m0.screenings[4].seat_status, SeatStatus.FULL)
        self.assertEqual(m0.screenings[4].booking_url, "")

        # 外部短縮URL拒否 & フォールバック、ULTRA 4DX / KIDS CINEMA、presale / others
        m1 = movies[1]
        self.assertEqual(m1.info_url, "https://109cinemas.net/futakotamagawa/")
        self.assertEqual(m1.screenings[0].seat_status, SeatStatus.FEW)
        self.assertEqual(m1.screenings[0].tags, ["ULTRA 4DX", "KIDS CINEMA"])
        self.assertEqual(m1.screenings[1].seat_status, SeatStatus.UNSOLD)

    def test_109cinemas_parse_premium_shinjuku(self):
        from scraper.providers.cinemas109 import Cinemas109Provider

        # プレミアム新宿HTML: HTMLコメント内 4DXScreen の偽タグ混入、.seets / .a_seet / .s_seet の3重構造、24時超え
        sample_html = """
        <article id="m2877260" data-film-id="2877260" class="mg53555 53555">
          <header>
            <a href="/premiumshinjuku/movies.html?id=5764" target="_top">
              <h2>魔法使いの夜</h2>
              <p lang="en">WITCH ON THE HOLY NIGHT</p>
            </a>
          </header>
          <ul class="timetable" data-screen-name="theater-2">
            <li class="theatre">
              <a class="screen-img" href="/premiumshinjuku/seat/theater-2.gif">THEATER
                <span class="theatre-num">2</span>
              </a>
              <!-- <a href="/premiumshinjuku/seat/screen-7.png">シアター<span>7</span></a>4DXScreen<br> -->
              2D
              <br><small>130min</small>
            </li>
            <li class="check_date" data-date="202611222425">
              <span class="seets">
                <a href="https://cinema.109cinemas.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=53555&amp;tsc=X1&amp;tssc=X4&amp;ymd=2026-11-22&amp;cs=&amp;stt=2425">
                  <time class="start">24:25</time>~<time class="end">26:45</time>
                  <div class="available">購入</div>
                </a>
              </span>
              <span class="a_seet">
                <a href="https://cinema.109cinemas.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=53555&amp;tsc=X1&amp;tssc=X4&amp;ymd=2026-11-22&amp;cs=&amp;stt=2425">
                  <time class="start">24:25</time>~<time class="end">26:45</time>
                  <div class="available">購入</div>
                </a>
              </span>
              <span class="s_seet">
                <a href="">
                  <time class="start">24:25</time>~<time class="end">26:45</time>
                  <div class="soldout">売り切れ</div>
                </a>
              </span>
            </li>
          </ul>
        </article>
        """

        provider = Cinemas109Provider()
        with patch.object(provider, "_fetch_schedule_html", return_value=sample_html):
            movies = provider.fetch_movies("premiumshinjuku", date(2026, 11, 22))

        self.assertEqual(len(movies), 1)
        m = movies[0]
        self.assertEqual(m.info_url, "https://109cinemas.net/premiumshinjuku/movies.html?id=5764")
        # a_seet / s_seet が重複しないため 1枠のみ
        self.assertEqual(len(m.screenings), 1)
        s = m.screenings[0]
        self.assertEqual(s.screen_name, "シアター2")
        self.assertEqual(s.start_time, "24:25")
        self.assertEqual(s.end_time, "26:45")
        self.assertEqual(s.seat_status, SeatStatus.AVAILABLE)
        # コメント内 4DXScreen による偽タグが混入しないこと
        self.assertEqual(s.tags, [])

    def test_smt_provider_registration_and_cli_security(self):
        from unittest.mock import patch
        from scraper.providers import get_provider
        from scraper.providers.smt import SmtCinemaProvider
        from scraper.cli import main as cli_main

        provider = get_provider("smt")
        self.assertIsInstance(provider, SmtCinemaProvider)
        self.assertEqual(provider.CHAIN_ID, "smt")

        # 不正なシアターID文字列が CLI 境界で終了コード 2 で拒否されること
        with patch("sys.argv", ["scraper.cli", "--chain", "smt", "--theater", "shinjuku;malicious"]):
            with patch("sys.stderr"):
                exit_code = cli_main()
                self.assertEqual(exit_code, 2)

    def test_smt_helpers(self):
        from scraper.providers.smt import (
            clean_smt_movie_title,
            extract_special_tags,
            map_smt_seat_status,
            normalize_smt_screen_name,
        )

        # タイトルの本編時間表記のみ除去
        self.assertEqual(
            clean_smt_movie_title("MET LV 26‐27｢ﾓｰﾂｧﾙﾄ≪ｺｼﾞ･ﾌｧﾝ･ﾄｩｯﾃ≫｣（本編：231分）"),
            "MET LV 26‐27｢ﾓｰﾂｧﾙﾄ≪ｺｼﾞ･ﾌｧﾝ･ﾄｩｯﾃ≫｣",
        )
        self.assertEqual(clean_smt_movie_title("テスト映画 (本編:95分)"), "テスト映画")

        # スクリーン名正規化
        self.assertEqual(normalize_smt_screen_name("シアター５"), "シアター5")
        self.assertEqual(normalize_smt_screen_name("DOLBY CINEMA [4階]"), "Dolby Cinema")
        self.assertEqual(normalize_smt_screen_name("DolbyCinema"), "Dolby Cinema")
        self.assertEqual(normalize_smt_screen_name("シアター"), "シアター")
        self.assertEqual(normalize_smt_screen_name("プラチナ"), "プラチナ")

        # 特殊設備タグ抽出（対象外除外・重複なし）
        self.assertEqual(
            extract_special_tags(
                "【DolbyCinema字幕】マイケル",
                "特別興行 NEW LAST バリアフリー 2D",
                "DolbyCinema",
                "レイトショー 特別料金 吹替",
            ),
            ["Dolby Cinema"],
        )
        self.assertEqual(
            extract_special_tags("テスト【IMAXレーザー3D】", "Dolby Atmos 爆音 轟音"),
            ["IMAXレーザー", "Dolby Atmos", "爆音", "轟音", "3D"],
        )
        self.assertEqual(
            extract_special_tags("作品", "ULTRA 4DX MX4D ScreenX"),
            ["ULTRA 4DX", "MX4D", "ScreenX"],
        )

        # 座席ステータス変換
        self.assertEqual(map_smt_seat_status("sheet ok", "◎余裕あり"), SeatStatus.AVAILABLE)
        self.assertEqual(map_smt_seat_status("sheet few", "△残りわずか"), SeatStatus.FEW)
        self.assertEqual(map_smt_seat_status("sheet ng", "×販売終了"), SeatStatus.UNSOLD)
        self.assertEqual(map_smt_seat_status("sheet ng", "×満席"), SeatStatus.FULL)
        self.assertEqual(map_smt_seat_status("sheet ng", "売切"), SeatStatus.FULL)
        self.assertEqual(map_smt_seat_status("sheet before", "－販売前"), SeatStatus.UNSOLD)

    def test_parse_smt_schedule_html_smart_theater(self):
        from scraper.providers.smt import SmtCinemaProvider, parse_smt_schedule_html

        html = """
        <section class="daily" data-smart-theater="1">
          <section class="49425 T0032612">
            <div class="list">
              <div class="movieTitle">
                <div class="inner clearfix">
                  <h2>
                    テスト映画Ａ（本編：135分）
                    <span class="enLabel">Test Movie A</span>
                  </h2>
                  <p class="tag">
                    <span>特別興行</span>
                    <span class="new">NEW</span>
                    <span class="last">LAST</span>
                    <span>バリアフリー</span>
                  </p>
                </div>
              </div>
              <div class="theaterList clearfix">
                <div class="image matchHeight">
                  <p class="detailLink">
                    <a href="/site/shinjuku/movie/detail/?cinemaid=T0032612&mo=49425&type=0">作品詳細</a>
                  </p>
                </div>
                <div class="select matchHeight clearfix">
                  <div class="block few">
                    <h3><a href="javascript:void(0)" class="T1051S05">シアター５</a></h3>
                    <div class="inner few" id="0_1051_49425_20261122_6afadfd3d0c12b3a11ab044d_05_0" data-event-id="6afadfd3d0c12b3a11ab044d">
                      <p class="time"><span>8:05～</span> 10:20</p>
                      <p class="text"><span class="sheet few">△残りわずか</span> レイトショー</p>
                    </div>
                  </div>
                  <div class="block ok">
                    <h3><a href="javascript:void(0)">プラチナ</a></h3>
                    <div class="inner ok" id="0_1051_49425_20261122_6afadfd3d0c12b3a11ab044e_01_1" data-event-id="6afadfd3d0c12b3a11ab044e">
                      <p class="time"><span>13:00～</span> 15:15</p>
                      <p class="text"><span class="sheet ok">◎余裕あり</span> 特別料金</p>
                    </div>
                  </div>
                  <div class="block ng">
                    <h3><a href="javascript:void(0)">DolbyCinema</a></h3>
                    <div class="inner ng" id="0_1051_49425_20261122_6afadfd3d0c12b3a11ab044f_11_0" data-event-id="6afadfd3d0c12b3a11ab044f">
                      <p class="time"><span>18:00～</span> 20:15</p>
                      <p class="text"><span class="sheet ng">×販売終了</span></p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </section>
        """
        provider = SmtCinemaProvider()
        movies = parse_smt_schedule_html(
            html=html,
            theater_slug="shinjuku",
            theater_code="1051",
            booking_url_builder=provider.build_booking_url,
            info_url_builder=provider.build_movie_info_url,
        )
        self.assertEqual(len(movies), 1)
        m = movies[0]
        self.assertEqual(m.movie_id, "49425")
        self.assertEqual(m.movie_title, "テスト映画Ａ")
        self.assertEqual(m.movie_title_en, "Test Movie A")
        self.assertEqual(
            m.info_url,
            "https://www.smt-cinema.com/site/shinjuku/movie/detail/?cinemaid=T0032612&mo=49425&type=0",
        )
        self.assertEqual(len(m.screenings), 3)

        s0, s1, s2 = m.screenings
        self.assertEqual(s0.screen_name, "シアター5")
        self.assertEqual(s0.start_time, "08:05")
        self.assertEqual(s0.end_time, "10:20")
        self.assertEqual(s0.seat_status, SeatStatus.FEW)
        self.assertEqual(
            s0.booking_url,
            "https://memberlogin.smart.smt-cinema.jp/purchase/guest?eventId=6afadfd3d0c12b3a11ab044d",
        )
        self.assertEqual(s0.tags, [])

        self.assertEqual(s1.screen_name, "プラチナ")
        self.assertEqual(s1.seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(
            s1.booking_url,
            "https://memberlogin.smart.smt-cinema.jp/purchase/guest?eventId=6afadfd3d0c12b3a11ab044e",
        )

        self.assertEqual(s2.screen_name, "Dolby Cinema")
        self.assertEqual(s2.seat_status, SeatStatus.UNSOLD)
        self.assertEqual(s2.booking_url, "")
        self.assertEqual(s2.tags, ["Dolby Cinema"])

    def test_parse_smt_schedule_html_legacy_theater_and_404(self):
        from datetime import date
        from unittest.mock import patch
        import urllib.error
        from scraper.providers.smt import SmtCinemaProvider, parse_smt_schedule_html

        html = """
        <section class="daily">
          <section class="49480 A0004792">
            <div class="list">
              <div class="movieTitle">
                <div class="inner clearfix">
                  <h2>【DolbyCinema字幕】テスト映画Ｂ（本編：128分）</h2>
                  <p class="tag"><span>特別興行</span></p>
                </div>
              </div>
              <div class="theaterList clearfix">
                <div class="image matchHeight">
                  <p class="detailLink"><a href="/site/marunouchi/movie/detail/?cinemaid=A0004792&mo=49480&type=0">作品詳細</a></p>
                </div>
                <div class="select matchHeight clearfix">
                  <div class="block ok">
                    <h3><a href="javascript:void(0)" class="T1052S03">Dolby Cinema</a></h3>
                    <div class="inner ok" id="0_1052_49480_20261122_4_03_0">
                      <p class="time"><span>17:55～</span> 20:03</p>
                      <p class="text"><span class="sheet ok">◎余裕あり</span></p>
                    </div>
                  </div>
                  <div class="block ng">
                    <h3><a href="javascript:void(0)" class="T1052S01">シアター１</a></h3>
                    <div class="inner ng" id="0_1052_49480_20261122_5_01_0">
                      <p class="time"><span>20:30～</span> 22:38</p>
                      <p class="text"><span class="sheet ng">×満席</span></p>
                    </div>
                  </div>
                  <div class="block before">
                    <h3><a href="javascript:void(0)" class="T1052S02">シアター２</a></h3>
                    <div class="inner before" id="0_1052_49480_20261122_6_02_0">
                      <p class="time"><span>21:00～</span> 23:08</p>
                      <p class="text"><span class="sheet before">－販売前</span></p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </section>
        """
        provider = SmtCinemaProvider()
        movies = parse_smt_schedule_html(
            html=html,
            theater_slug="marunouchi",
            theater_code="1052",
            booking_url_builder=provider.build_booking_url,
            info_url_builder=provider.build_movie_info_url,
        )
        self.assertEqual(len(movies), 1)
        m = movies[0]
        self.assertEqual(m.movie_title, "【DolbyCinema字幕】テスト映画Ｂ")
        self.assertEqual(len(m.screenings), 3)
        s_ok, s_full, s_before = m.screenings
        self.assertEqual(
            s_ok.booking_url,
            "https://ticket.smt-cinema.com/ticket/f0100.do?th=1052&mo=49480&sd=20261122&pe=4&sc=03&fl=0",
        )
        self.assertEqual(s_ok.tags, ["Dolby Cinema"])
        self.assertEqual(s_full.seat_status, SeatStatus.FULL)
        self.assertEqual(s_full.booking_url, "")
        self.assertEqual(s_before.seat_status, SeatStatus.UNSOLD)
        self.assertEqual(s_before.booking_url, "")

        # 404時は空リストを返すこと
        http_404 = urllib.error.HTTPError("https://www.smt-cinema.com/404", 404, "Not Found", {}, None)
        with patch("urllib.request.urlopen", side_effect=http_404):
            self.assertEqual(provider.fetch_movies("marunouchi", date(2026, 12, 31)), [])

    def test_info_urls(self):
        from scraper.providers.toho import TohoCinemaProvider
        from scraper.providers.sunshine import CinemaSunshineProvider
        from scraper.providers.united import UnitedCinemaProvider
        from scraper.providers.aeon import AeonCinemaProvider
        from scraper.providers.tjoy import TJoyCinemaProvider
        from scraper.providers.cinemas109 import Cinemas109Provider
        from scraper.providers.smt import SmtCinemaProvider

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

        # 109 Cinemas movie url & fallback
        c109 = Cinemas109Provider()
        self.assertEqual(
            c109.build_movie_info_url("https://109cinemas.net/movies/5764.html", "kiba"),
            "https://109cinemas.net/movies/5764.html",
        )
        self.assertEqual(
            c109.build_movie_info_url("/premiumshinjuku/movies.html?id=5764", "premiumshinjuku"),
            "https://109cinemas.net/premiumshinjuku/movies.html?id=5764",
        )
        self.assertEqual(
            c109.build_movie_info_url("https://x.gd/J1ok2", "kiba"),
            "https://109cinemas.net/kiba/",
        )

        # SMT movie url & fallback
        smt = SmtCinemaProvider()
        self.assertEqual(
            smt.build_movie_info_url("/site/shinjuku/movie/detail/?cinemaid=T0032612&mo=49425&type=0", "shinjuku"),
            "https://www.smt-cinema.com/site/shinjuku/movie/detail/?cinemaid=T0032612&mo=49425&type=0",
        )
        self.assertEqual(
            smt.build_movie_info_url("https://evil.example.com/phishing", "shinjuku"),
            "https://www.smt-cinema.com/site/shinjuku/",
        )

    def test_parse_aeon_facility_html_cleaned_schema(self):
        """fetch_theaters.parse_aeon_facility_html がクリーンなスキーマとスクリーン名・サイズを抽出することを検証"""
        import importlib.util
        from pathlib import Path

        script_path = (
            Path(__file__).resolve().parents[1]
            / ".agents"
            / "skills"
            / "update-theaters"
            / "scripts"
            / "fetch_theaters.py"
        )
        spec = importlib.util.spec_from_file_location("fetch_theaters_mod", script_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        sample_html = """
        <section id="facility">
          <div class="p-facility__block">
            <p class="p-facility__name">トリプルエアシールド</p>
            <p class="p-facility__lead">説明文</p>
          </div>
        </section>
        <section id="screen">
          <div class="p-facility__screenList c-accordion">
            <label class="c-accordion__header"><input type="checkbox">
              <span class="c-accordion__label">1スクリーン<small>(10.8m×6.0m)</small></span>
            </label>
            <div class="c-accordion__body">
              <span data-chip="デジタル 7.1ch">デジタル 7.1ch</span>
              <span data-chip="トリプルエアシールド">トリプルエアシールド</span>
              <a data-modal="modal_seat_1">座席表</a>
              <div class="p-facility__table">
                <p>座席数</p>
                <table>
                  <tr><th>通常座席</th><td>154席</td></tr>
                  <tr><th>車椅子用スペース</th><td>2席</td></tr>
                  <tr><th>合 計</th><td>156席</td></tr>
                </table>
              </div>
              <div class="p-facility__table">
                <p>スペック詳細</p>
                <table>
                  <tr><th>ステージスピーカー</th><td>JBL C222</td></tr>
                  <tr><th>プロセッサー</th><td>QSC DCP300</td></tr>
                </table>
              </div>
            </div>
          </section>
          <div data-modal="modal_seat_1"><img src="/uploads/theaters/seatmap/1033/01.gif"></div>
        </section>
        """
        result = mod.parse_aeon_facility_html(sample_html, "itabashi")
        self.assertEqual(set(result.keys()), {"screens"})
        self.assertEqual(len(result["screens"]), 1)

        scr = result["screens"][0]
        self.assertEqual(scr["name"], "1スクリーン")
        self.assertEqual(scr.get("screen_size"), "10.8m×6.0m")
        self.assertEqual(scr["features"], ["デジタル 7.1ch"])
        self.assertEqual(scr["total_seats"], 156)
        self.assertEqual(scr["seats"], {"通常座席": 154, "車椅子用スペース": 2})
        self.assertEqual(
            scr.get("seat_map_url"),
            "https://theater.aeoncinema.com/uploads/theaters/seatmap/1033/01.gif",
        )

    def test_aeon_theaters_json_schema_cleanliness(self):
        """data/theaters/aeon.json と data/theaters.json がスリム化・整合性要件を満たすことを検証"""
        from pathlib import Path

        data_dir = Path(__file__).resolve().parents[1] / "data"
        with (data_dir / "theaters" / "aeon.json").open("r", encoding="utf-8") as f:
            aeon = json.load(f)
        with (data_dir / "theaters.json").open("r", encoding="utf-8") as f:
            master = json.load(f)

        theaters = aeon.get("theaters", [])
        self.assertGreaterEqual(len(theaters), 95)

        forbidden_t_keys = {"theater_id", "code", "url"}
        forbidden_f_keys = {"url", "theater_services"}

        for t in theaters:
            self.assertFalse(forbidden_t_keys & set(t.keys()), f"Forbidden theater keys in {t.get('id')}")
            self.assertTrue(t.get("area"), f"Missing area in {t.get('id')}")
            fac = t.get("facility")
            self.assertIsInstance(fac, dict, f"Missing facility in {t.get('id')}")
            self.assertFalse(forbidden_f_keys & set(fac.keys()), f"Forbidden facility keys in {t.get('id')}")
            screens = fac.get("screens") or []
            self.assertGreater(len(screens), 0, f"Empty screens in {t.get('id')}")
            for s in screens:
                self.assertTrue(s.get("name"), f"Empty screen name in {t.get('id')}")
                self.assertNotIn("トリプルエアシールド", s.get("features") or [])
                seats = s.get("seats") or {}
                for k, v in seats.items():
                    self.assertNotIn(k, ("合 計", "合計"))
                    self.assertIsInstance(v, int, f"Non-int seat entry {k}={v} in {t.get('id')}")

        master_aeon = next((c for c in master.get("chains", []) if c.get("id") == "aeon"), None)
        self.assertEqual(master_aeon, aeon)


if __name__ == "__main__":
    unittest.main()


