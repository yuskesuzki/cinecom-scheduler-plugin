from datetime import date
import io
import unittest
from unittest.mock import patch
import urllib.error

import scraper.cli
from scraper.models import MovieSchedule, SeatStatus, TheaterScheduleResponse
from scraper.providers import get_provider
from scraper.providers.base import BaseCinemaProvider
from scraper.providers.other import (
    ADAPTER_REGISTRY,
    CinemaFrontierProvider,
    OsCinemasProvider,
    OtherCinemaProvider,
    SmtLegacyProvider,
    clean_cinema_frontier_title,
    map_cinema_frontier_seat_status,
    map_oscinemas_seat_status,
    map_smt_legacy_seat_status,
    normalize_cinema_frontier_screen_name,
    parse_cinema_frontier_schedule_html,
    parse_oscinemas_schedule_html,
    parse_smt_legacy_schedule_html,
)


class TestOtherCinemaProvider(unittest.TestCase):
    def test_other_provider_registration_and_cli_security(self):
        provider = get_provider("other")
        self.assertIsInstance(provider, OtherCinemaProvider)
        self.assertEqual(provider.CHAIN_ID, "other")

        with patch("sys.argv", ["scraper.cli", "--chain", "other", "--theater", "oscc;malicious"]):
            with patch("sys.stderr"):
                exit_code = scraper.cli.main()
                self.assertEqual(exit_code, 2)

    def test_adapter_registry_and_dispatch(self):
        self.assertIn("smt_legacy", ADAPTER_REGISTRY)
        self.assertIn("cinema_frontier", ADAPTER_REGISTRY)
        self.assertIn("oscinemas", ADAPTER_REGISTRY)
        self.assertIs(ADAPTER_REGISTRY["smt_legacy"], SmtLegacyProvider)
        self.assertIs(ADAPTER_REGISTRY["cinema_frontier"], CinemaFrontierProvider)
        self.assertIs(ADAPTER_REGISTRY["oscinemas"], OsCinemasProvider)
        for cls in ADAPTER_REGISTRY.values():
            self.assertTrue(issubclass(cls, BaseCinemaProvider))

        provider = OtherCinemaProvider()
        oscc_info, oscc_provider = provider._resolve_provider("oscc")
        self.assertEqual(oscc_info["adapter"], "smt_legacy")
        self.assertIsInstance(oscc_provider, SmtLegacyProvider)

        namba_info, namba_provider = provider._resolve_provider("namba")
        self.assertEqual(namba_info["adapter"], "smt_legacy")
        self.assertIs(namba_provider, oscc_provider)

        cf_info, cf_provider = provider._resolve_provider("sapporo_cf")
        self.assertEqual(cf_info["adapter"], "cinema_frontier")
        self.assertIsInstance(cf_provider, CinemaFrontierProvider)

        m1_info, m1_provider = provider._resolve_provider("midland_sq")
        self.assertEqual(m1_info["adapter"], "smt_legacy")
        self.assertIs(m1_provider, oscc_provider)

        m2_info, m2_provider = provider._resolve_provider("midland_sq2")
        self.assertEqual(m2_info["adapter"], "smt_legacy")
        self.assertIs(m2_provider, oscc_provider)

        for os_tid in ("os_mint_kobe", "os_harborland"):
            os_info, os_provider = provider._resolve_provider(os_tid)
            self.assertEqual(os_info["adapter"], "oscinemas")
            self.assertIsInstance(os_provider, OsCinemasProvider)

    def test_unsupported_adapter_raises_value_error(self):
        provider = OtherCinemaProvider()
        with patch.object(
            provider,
            "get_theater_info",
            return_value={"id": "unknown_mini", "adapter": "nonexistent_adapter"},
        ):
            with self.assertRaises(ValueError):
                provider.fetch_movies("unknown_mini", date(2026, 11, 22))
            with self.assertRaises(ValueError):
                provider.build_booking_url("unknown_mini", "ev1")
            with self.assertRaises(ValueError):
                provider.build_movie_info_url("unknown_mini", "/movie/1")
            with self.assertRaises(ValueError):
                provider.get_schedule_response("unknown_mini", date(2026, 11, 22))

    def test_base_provider_default_booking_url_for_non_booking_minitheater(self):
        class MiniTheaterProvider(BaseCinemaProvider):
            CHAIN_ID = "other"
            ADAPTER_ID = "mini_theater"

            def fetch_movies(self, theater_id, target_date):
                return [
                    MovieSchedule(
                        movie_id="mini_1",
                        movie_title="独立系上映作品",
                        screenings=[],
                        info_url=self.resolve_movie_info_url(theater_id, "/movies/mini_1"),
                    )
                ]

        class CustomResponseMiniProvider(MiniTheaterProvider):
            def get_schedule_response(self, theater_id, target_date):
                resp = super().get_schedule_response(theater_id, target_date)
                return TheaterScheduleResponse(
                    chain_id=resp.chain_id,
                    theater_id=resp.theater_id,
                    theater_name=f"{resp.theater_name}(カスタム)",
                    target_date=resp.target_date,
                    movies=resp.movies,
                )

        fake_theater = {
            "id": "sapporo_mini",
            "name": "札幌ミニシアター",
            "adapter": "mini_theater",
            "base_url": "https://www.cinemafrontier.net",
            "official_url": "https://www.cinemafrontier.net/cgi-bin/pc/index.cgi",
        }
        provider = OtherCinemaProvider(
            adapter_registry={"mini_theater": MiniTheaterProvider}
        )
        with patch.object(
            provider, "_load_theaters_master", return_value={"sapporo_mini": fake_theater}
        ):
            # 予約非対応ミニシアター向け Provider ではデフォルトが空文字を返すこと
            self.assertEqual(provider.build_booking_url("sapporo_mini", "ev1"), "")
            movies = provider.fetch_movies("sapporo_mini", date(2026, 11, 22))
            self.assertEqual(len(movies), 1)
            self.assertEqual(
                movies[0].info_url,
                "https://www.cinemafrontier.net/movies/mini_1",
            )
            self.assertEqual(
                provider.build_movie_info_url("sapporo_mini", "https://evil.example.com/x"),
                "https://www.cinemafrontier.net/cgi-bin/pc/index.cgi",
            )
            resp = provider.get_schedule_response("sapporo_mini", date(2026, 11, 22))
            self.assertEqual(resp.chain_id, "other")
            self.assertEqual(resp.theater_id, "sapporo_mini")
            self.assertEqual(resp.theater_name, "札幌ミニシアター")
            self.assertEqual(len(resp.movies), 1)

        custom_provider = OtherCinemaProvider(
            adapter_registry={"mini_theater": CustomResponseMiniProvider}
        )
        with patch.object(
            custom_provider,
            "_load_theaters_master",
            return_value={"sapporo_mini": fake_theater},
        ):
            custom_resp = custom_provider.get_schedule_response(
                "sapporo_mini", date(2026, 11, 22)
            )
            self.assertEqual(custom_resp.theater_name, "札幌ミニシアター(カスタム)")

    def test_package_reexports(self):
        import scraper.providers.other as other_pkg
        from scraper.providers.other.cinema_frontier import (
            parse_cinema_frontier_schedule_html as direct_cf_parse,
        )
        from scraper.providers.other.oscinemas import (
            parse_oscinemas_schedule_html as direct_os_parse,
        )
        from scraper.providers.other.smt_legacy import (
            parse_smt_legacy_schedule_html as direct_smt_parse,
        )

        self.assertIs(other_pkg.parse_cinema_frontier_schedule_html, direct_cf_parse)
        self.assertIs(other_pkg.parse_oscinemas_schedule_html, direct_os_parse)
        self.assertIs(other_pkg.parse_smt_legacy_schedule_html, direct_smt_parse)
        for name in other_pkg.__all__:
            self.assertTrue(hasattr(other_pkg, name), f"Missing export: {name}")
        for removed in (
            "BaseOtherStrategy",
            "STRATEGY_REGISTRY",
            "SmtLegacyStrategy",
            "CinemaFrontierStrategy",
            "OsCinemasStrategy",
        ):
            self.assertFalse(hasattr(other_pkg, removed), f"Unexpected legacy export: {removed}")

    def test_other_helpers(self):
        self.assertEqual(
            clean_cinema_frontier_title("[字幕]アザー・マミー[R15+]<span>R15+</span>"),
            "[字幕]アザー・マミー[R15+]",
        )
        self.assertEqual(
            clean_cinema_frontier_title("呪いのスマホ（PG12）<span>PG12</span>"),
            "呪いのスマホ（PG12）",
        )
        self.assertEqual(normalize_cinema_frontier_screen_name("スクリーン０５"), "スクリーン5")
        self.assertEqual(normalize_cinema_frontier_screen_name("スクリーン１０"), "スクリーン10")

        self.assertEqual(map_smt_legacy_seat_status("01.png", "余裕あり"), SeatStatus.AVAILABLE)
        self.assertEqual(map_smt_legacy_seat_status("02.png", "残りわずか"), SeatStatus.FEW)
        self.assertEqual(map_smt_legacy_seat_status("03.png", "販売終了"), SeatStatus.UNSOLD)
        self.assertEqual(map_smt_legacy_seat_status("04.png", "販売前"), SeatStatus.UNSOLD)
        self.assertEqual(map_smt_legacy_seat_status("03.png", "満席"), SeatStatus.FULL)

        self.assertEqual(map_cinema_frontier_seat_status("item status1", "購入する"), SeatStatus.AVAILABLE)
        self.assertEqual(map_cinema_frontier_seat_status("item status2", "購入する"), SeatStatus.FEW)
        self.assertEqual(map_cinema_frontier_seat_status("item status3", "販売終了"), SeatStatus.UNSOLD)
        self.assertEqual(map_cinema_frontier_seat_status("item status4", "窓口販売のみ"), SeatStatus.UNSOLD)
        self.assertEqual(map_cinema_frontier_seat_status("item status3", "満席"), SeatStatus.FULL)

    def test_other_movie_info_urls(self):
        other = OtherCinemaProvider()
        self.assertEqual(
            other.build_movie_info_url(
                "oscc",
                "https://www.osakastationcitycinema.com/site/oscc/detail.html?cinemaid=A0004785",
            ),
            "https://www.osakastationcitycinema.com/site/oscc/detail.html?cinemaid=A0004785",
        )
        self.assertEqual(
            other.build_movie_info_url("namba", "https://evil.example.com/bad"),
            "https://www.parkscinema.com/site/namba/",
        )
        self.assertEqual(
            other.build_movie_info_url("sapporo_cf", "/cgi-bin/pc/ttl/det.cgi?ttc=55406"),
            "https://www.cinemafrontier.net/cgi-bin/pc/ttl/det.cgi?ttc=55406",
        )
        self.assertEqual(
            other.build_movie_info_url("sapporo_cf", "https://evil.example.com/bad"),
            "https://www.cinemafrontier.net/cgi-bin/pc/index.cgi",
        )

    def test_parse_smt_legacy_schedule_html(self):
        oscc_html = """
        <div class="scheduleBox">
          <div class="MvTtl clearfix">
            <div class="MovieTitle1">
              <h2><a href="https://www.osakastationcitycinema.com/site/oscc/detail.html?cinemaid=T0032222&type=0100&screendate=20261122">テスト映画【Dolby Atmos】</a><span><img src="../../images/icon/txt04.gif" alt="NEW"></span></h2>
            </div>
            <div class="totalTime"><p>（本編：100分）</p></div>
          </div>
          <table>
            <tr>
              <th rowspan="100"><a href="https://www.osakastationcitycinema.com/site/oscc/detail.html?cinemaid=T0032222">img</a></th>
              <td>
                <p>スクリーン１</p>
                <table><tr><td><img src="../../images/icon/03.png" alt="販売終了"></td><td><span class="strong fontXL">9:10</span><br>～11:00</td></tr></table>
              </td>
              <td onclick="var win = window.open('https://ticket.osakastationcitycinema.com/ticket/f0100.do?th=1071&mo=49424&sd=20261122&pe=4&sc=11&fl=0', 'purchase');win.focus();">
                <p>スクリーン１１</p>
                <table><tr><td><img src="../../images/icon/02.png" alt="残りわずか"></td><td><span class="strong fontXL">13:30</span><br>～15:20</td></tr></table>
              </td>
              <td>&nbsp;</td>
            </tr>
          </table>
        </div>
        """
        provider = OtherCinemaProvider()
        movies = parse_smt_legacy_schedule_html(
            html=oscc_html,
            theater_id="oscc",
            base_url="https://www.osakastationcitycinema.com",
            ticket_host="ticket.osakastationcitycinema.com",
            booking_url_builder=provider.build_booking_url,
            info_url_builder=provider.build_movie_info_url,
        )
        self.assertEqual(len(movies), 1)
        m = movies[0]
        self.assertEqual(m.movie_id, "T0032222")
        self.assertEqual(len(m.screenings), 2)
        s0, s1 = m.screenings
        self.assertEqual(s0.screen_name, "スクリーン1")
        self.assertEqual(s0.start_time, "09:10")
        self.assertEqual(s0.end_time, "11:00")
        self.assertEqual(s0.seat_status, SeatStatus.UNSOLD)
        self.assertEqual(s0.booking_url, "")
        self.assertEqual(s0.tags, ["Dolby Atmos"])
        self.assertEqual(s1.screen_name, "スクリーン11")
        self.assertEqual(s1.seat_status, SeatStatus.FEW)
        self.assertEqual(
            s1.booking_url,
            "https://ticket.osakastationcitycinema.com/ticket/f0100.do?th=1071&mo=49424&sd=20261122&pe=4&sc=11&fl=0",
        )

        namba_html = """
        <div class="scheduleBox">
          <div class="MvTtl clearfix">
            <div class="MovieTitle1">
              <h2><a href="https://www.parkscinema.com/site/namba/detail.html?cinemaid=T0032379">テスト映画C</a></h2>
            </div>
          </div>
          <table>
            <tr>
              <th rowspan="100">img</th>
              <td onclick="var win = window.open('https://ticket.parkscinema.com/ticket/f0100.do?th=1070&mo=49440&sd=20261122&pe=4&sc=09&fl=0', 'purchase');">
                <p>シアター９</p>
                <table><tr><td><img src="../../images/icon/01.png" alt="余裕あり"></td><td><span>15:35</span>～17:40</td></tr></table>
              </td>
              <td>
                <p>シアター１</p>
                <table><tr><td><img src="../../images/icon/04.png" alt="販売前"></td><td><span>19:00</span>～21:05</td></tr></table>
              </td>
            </tr>
          </table>
        </div>
        """
        n_movies = parse_smt_legacy_schedule_html(
            html=namba_html,
            theater_id="namba",
            base_url="https://www.parkscinema.com",
            ticket_host="ticket.parkscinema.com",
            booking_url_builder=provider.build_booking_url,
            info_url_builder=provider.build_movie_info_url,
        )
        self.assertEqual(len(n_movies), 1)
        ns0, ns1 = n_movies[0].screenings
        self.assertEqual(ns0.screen_name, "シアター9")
        self.assertEqual(ns0.seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(
            ns0.booking_url,
            "https://ticket.parkscinema.com/ticket/f0100.do?th=1070&mo=49440&sd=20261122&pe=4&sc=09&fl=0",
        )
        self.assertEqual(ns1.seat_status, SeatStatus.UNSOLD)
        self.assertEqual(ns1.booking_url, "")

        # 404時は空リスト
        http_404 = urllib.error.HTTPError(
            "https://www.osakastationcitycinema.com/404",
            404,
            "Not Found",
            {},
            io.BytesIO(b""),
        )
        try:
            with patch("urllib.request.urlopen", side_effect=http_404):
                self.assertEqual(provider.fetch_movies("oscc", date(2026, 12, 31)), [])
        finally:
            http_404.close()

    def test_parse_cinema_frontier_schedule_html(self):
        cf_html = """
        <div class="sc-item clearfix">
          <div class="sc-item-head clearfix">
            <h3 class="title">[字幕]テスト作品D[R15+]<span>R15+</span></h3>
            <h4 class="en-title">[Sub]Test Film D</h4>
            <a href="/cgi-bin/pc/ttl/det.cgi?ttc=55407" class="link">作品詳細</a>
          </div>
          <div class="sc-item-body clearfix">
            <div class="items clearfix">
              <div class="item status3">
                <p class="time">9:00<span>〜11:00</span></p>
                <p class="screen">スクリーン０５</p>
                <p class="status"><span class="icon"></span>販売終了</p>
              </div>
              <a href="https://www.cinemafrontier.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=55407&amp;tsc=1&amp;tssc=8&amp;ymd=2026-11-22&amp;cs=5" class="item status1">
                <p class="time">12:00<span>〜14:00</span></p>
                <p class="screen">スクリーン０８</p>
                <p class="status"><span class="icon"></span>購入する</p>
              </a>
              <a href="https://www.cinemafrontier.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=55407&amp;tsc=1&amp;tssc=7&amp;ymd=2026-11-22&amp;cs=4" class="item status2">
                <p class="time">15:45<span>〜17:45</span></p>
                <p class="screen">スクリーン０７</p>
                <p class="status"><span class="icon"></span>購入する</p>
              </a>
              <div class="item status4">
                <p class="time">19:00<span>〜21:00</span></p>
                <p class="screen">スクリーン０１</p>
                <p class="status"><span class="icon"></span>窓口販売のみ</p>
              </div>
            </div>
          </div>
        </div>
        """
        provider = OtherCinemaProvider()
        movies = parse_cinema_frontier_schedule_html(
            html=cf_html,
            theater_id="sapporo_cf",
            booking_url_builder=provider.build_booking_url,
            info_url_builder=provider.build_movie_info_url,
        )
        self.assertEqual(len(movies), 1)
        m = movies[0]
        self.assertEqual(m.movie_id, "55407")
        self.assertEqual(m.movie_title, "[字幕]テスト作品D[R15+]")
        self.assertEqual(m.movie_title_en, "[Sub]Test Film D")
        self.assertEqual(
            m.info_url,
            "https://www.cinemafrontier.net/cgi-bin/pc/ttl/det.cgi?ttc=55407",
        )
        self.assertEqual(len(m.screenings), 4)

        s0, s1, s2, s3 = m.screenings
        self.assertEqual(s0.start_time, "09:00")
        self.assertEqual(s0.screen_name, "スクリーン5")
        self.assertEqual(s0.seat_status, SeatStatus.UNSOLD)
        self.assertEqual(s0.booking_url, "")
        self.assertEqual(s0.tags, [])

        self.assertEqual(s1.screen_name, "スクリーン8")
        self.assertEqual(s1.seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(
            s1.booking_url,
            "https://www.cinemafrontier.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=55407&tsc=1&tssc=8&ymd=2026-11-22&cs=5",
        )

        self.assertEqual(s2.screen_name, "スクリーン7")
        self.assertEqual(s2.seat_status, SeatStatus.FEW)
        self.assertTrue(
            s2.booking_url.startswith(
                "https://www.cinemafrontier.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?"
            )
        )

        self.assertEqual(s3.screen_name, "スクリーン1")
        self.assertEqual(s3.seat_status, SeatStatus.UNSOLD)
        self.assertEqual(s3.booking_url, "")

        # 未公開日（sc-item 0件）時は空リスト
        empty_html = '<div class="contents"><h2 class="sc-head"><span>2026</span> 12/22 <span>(火)</span></h2></div>'
        self.assertEqual(
            parse_cinema_frontier_schedule_html(
                empty_html, "sapporo_cf", provider.build_booking_url
            ),
            [],
        )

        # status1 の <a class="item status1"> のみ1枠で sc-item-body 内に他の div.item が無いケース（ハイフン境界誤爆防止）
        single_a_html = """
        <div class="sc-item clearfix">
          <div class="sc-item-head clearfix">
            <h3 class="title">単独販売中テスト<span></span></h3>
            <a href="/cgi-bin/pc/ttl/det.cgi?ttc=55407" class="link">作品詳細</a>
          </div>
          <div class="sc-item-body clearfix">
            <div class="items clearfix">
              <a href="https://www.cinemafrontier.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=55407&amp;tsc=1&amp;tssc=8&amp;ymd=2026-11-22&amp;cs=5" class="item status1">
                <p class="time">16:00<span>〜19:15</span></p>
                <p class="screen">スクリーン０８</p>
                <p class="status"><span class="icon"></span>購入する</p>
              </a>
            </div>
          </div>
        </div>
        """
        single_movies = parse_cinema_frontier_schedule_html(
            html=single_a_html,
            theater_id="sapporo_cf",
            booking_url_builder=provider.build_booking_url,
            info_url_builder=provider.build_movie_info_url,
        )
        self.assertEqual(len(single_movies), 1)
        self.assertEqual(len(single_movies[0].screenings), 1)
        self.assertEqual(
            single_movies[0].screenings[0].booking_url,
            "https://www.cinemafrontier.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=55407&tsc=1&tssc=8&ymd=2026-11-22&cs=5",
        )

    def test_parse_midland_schedule_split_by_building(self):
        """ミッドランドスクエア シネマ(SC1〜7)とシネマ2(SC8〜14)の分離抽出と施設タグを検証"""
        provider = OtherCinemaProvider()
        midland_html = """
        <div class="scheduleBox">
          <div class="MvTtl clearfix">
            <div class="MovieTitle1">
              <h2>テスト作品E<span><img src="../images/icon/17.gif" alt="DOLBY CINEMA"></span></h2>
            </div>
            <div class="totalTime"><p>（本編：120分）</p></div>
          </div>
          <table>
            <tr>
              <td onclick="var win = window.open('https://ticket.midlandcinema.jp/ticket/f0100.do?th=0201&mo=1001&sd=20261123&pe=1&sc=05&fl=0', 'purchase');win.focus();">
                <p class="ScreenGroup1 ">Sc5　DolbyCinema</p>
                <table><tr><td><img src="../images/icon/01.png" alt="余裕あり"></td><td><span>10:30</span><br>～12:30</td></tr></table>
              </td>
              <td onclick="var win = window.open('https://ticket.midlandcinema.jp/ticket/f0100.do?th=0201&mo=1001&sd=20261123&pe=2&sc=08&fl=0', 'purchase');win.focus();">
                <p class="ScreenGroup2 ">スクリーン8【粋】鼓動　sound</p>
                <table><tr><td><img src="../images/icon/02.png" alt="残りわずか"></td><td><span>14:00</span><br>～16:00</td></tr></table>
              </td>
              <td>
                <p class="night2">スクリーン14</p>
                <table><tr><td><img src="../images/icon/03.png" alt="販売終了"></td><td><span>19:00</span><br>～21:00</td></tr></table>
              </td>
            </tr>
          </table>
        </div>
        """

        m1_movies = parse_smt_legacy_schedule_html(
            html=midland_html,
            theater_id="midland_sq",
            base_url="https://www.midland-sq-cinema.jp",
            ticket_host="ticket.midlandcinema.jp",
            booking_url_builder=provider.build_booking_url,
            info_url_builder=provider.build_movie_info_url,
            screen_min=1,
            screen_max=7,
        )
        self.assertEqual(len(m1_movies), 1)
        self.assertEqual(len(m1_movies[0].screenings), 1)
        s1 = m1_movies[0].screenings[0]
        self.assertEqual(s1.screen_name, "スクリーン5 Dolby Cinema")
        self.assertIn("Dolby Cinema", s1.tags)
        self.assertEqual(s1.seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(
            s1.booking_url,
            "https://ticket.midlandcinema.jp/ticket/f0100.do?th=0201&mo=1001&sd=20261123&pe=1&sc=05&fl=0",
        )

        m2_movies = parse_smt_legacy_schedule_html(
            html=midland_html,
            theater_id="midland_sq2",
            base_url="https://www.midland-sq-cinema.jp",
            ticket_host="ticket.midlandcinema.jp",
            booking_url_builder=provider.build_booking_url,
            info_url_builder=provider.build_movie_info_url,
            screen_min=8,
            screen_max=14,
        )
        self.assertEqual(len(m2_movies), 1)
        self.assertEqual(len(m2_movies[0].screenings), 2)
        s2_a, s2_b = m2_movies[0].screenings
        self.assertEqual(s2_a.screen_name, "スクリーン8【粋】鼓動 sound")
        self.assertEqual(s2_a.seat_status, SeatStatus.FEW)
        self.assertEqual(
            s2_a.booking_url,
            "https://ticket.midlandcinema.jp/ticket/f0100.do?th=0201&mo=1001&sd=20261123&pe=2&sc=08&fl=0",
        )
        self.assertEqual(s2_b.screen_name, "スクリーン14")
        self.assertEqual(s2_b.seat_status, SeatStatus.UNSOLD)
        self.assertEqual(s2_b.booking_url, "")

        # fetch_movies のパス組み立て・building 分離（モック）
        mock_resp = unittest.mock.MagicMock()
        mock_resp.read.return_value = midland_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            fetched = provider.fetch_movies("midland_sq", date(2026, 11, 23))
            req_url = mock_open.call_args[0][0].full_url
            self.assertEqual(
                req_url,
                "https://ticket.midlandcinema.jp/schedule/schedule/pc/s0100_0201_20261123-1.html",
            )
            self.assertEqual(len(fetched), 1)
            self.assertEqual(len(fetched[0].screenings), 1)

    def test_parse_oscinemas_schedule_and_strategy(self):
        """OSシネマズのステータス判定・HTMLパース・予約/作品URL生成・POST EUC-JP取得を検証"""
        self.assertEqual(map_oscinemas_seat_status("item", ["icon", "circle"]), SeatStatus.AVAILABLE)
        self.assertEqual(map_oscinemas_seat_status("item", ["icon", "triangle"]), SeatStatus.FEW)
        self.assertEqual(map_oscinemas_seat_status("item status2", ["icon", "hyphen"]), SeatStatus.UNSOLD)
        self.assertEqual(map_oscinemas_seat_status("item status4", ["icon"]), SeatStatus.FULL)
        self.assertEqual(map_oscinemas_seat_status("item", ["icon", "cross"]), SeatStatus.FULL)
        self.assertEqual(map_oscinemas_seat_status("item", []), SeatStatus.UNKNOWN)

        provider = OtherCinemaProvider()
        os_html = """
        <div class="com-head1 clearfix"><h3>2026年11月23日 上映作品一覧</h3></div>
        <div class="com-item-select1 clearfix">
          <div class="head">
            <h3 class="title"><a href="/cgi-bin/pc/ttl/det.cgi?ttc=15917">OSテスト作品F【IMAX】</a></h3>
          </div>
          <div class="body">
            <div class="block1 acc-body-sp1">
              <a href="/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=15917&amp;tsc=21120&amp;tssc=279&amp;ymd=2026-11-23&amp;cs=1" class="item status2">
                <div class="ds">
                  <div class="time">09:20<span class="small">〜11:45</span></div>
                  <div class="screen">スクリーン９</div>
                </div>
                <div class="icons"><span class="icon hyphen"></span></div>
              </a>
              <a href="/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=15917&amp;tsc=21120&amp;tssc=279&amp;ymd=2026-11-23&amp;cs=4" class="item">
                <div class="ds">
                  <div class="time">14:10<span class="small">〜16:35</span></div>
                  <div class="screen">スクリーン９</div>
                </div>
                <div class="icons"><span class="icon circle"></span></div>
              </a>
              <a href="/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=15917&amp;tsc=21120&amp;tssc=279&amp;ymd=2026-11-23&amp;cs=7" class="item status3">
                <div class="ds">
                  <div class="time">20:00<span class="small">〜22:25</span></div>
                  <div class="screen">スクリーン９</div>
                </div>
                <div class="icons"><span class="icon triangle"></span><span class="icon moon"></span></div>
              </a>
            </div>
          </div>
        </div>
        """

        movies = parse_oscinemas_schedule_html(
            html=os_html,
            theater_id="os_harborland",
            booking_url_builder=provider.build_booking_url,
            info_url_builder=provider.build_movie_info_url,
        )
        self.assertEqual(len(movies), 1)
        m = movies[0]
        self.assertEqual(m.movie_id, "15917")
        self.assertEqual(m.movie_title, "OSテスト作品F【IMAX】")
        self.assertEqual(m.info_url, "https://www.oscinemas.net/cgi-bin/pc/ttl/det.cgi?ttc=15917")
        self.assertEqual(len(m.screenings), 3)

        s0, s1, s2 = m.screenings
        self.assertEqual(s0.start_time, "09:20")
        self.assertEqual(s0.screen_name, "スクリーン9")
        self.assertEqual(s0.seat_status, SeatStatus.UNSOLD)
        self.assertEqual(s0.booking_url, "")
        self.assertIn("IMAX", s0.tags)

        self.assertEqual(s1.seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(
            s1.booking_url,
            "https://www.oscinemas.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=15917&tsc=21120&tssc=279&ymd=2026-11-23&cs=4",
        )
        self.assertEqual(s2.seat_status, SeatStatus.FEW)
        self.assertTrue(s2.booking_url.startswith("https://www.oscinemas.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?"))

        # POST + EUC-JP デコード検証
        mock_resp = unittest.mock.MagicMock()
        mock_resp.read.return_value = os_html.encode("euc-jp")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            fetched = provider.fetch_movies("os_mint_kobe", date(2026, 11, 23))
            req_obj = mock_open.call_args[0][0]
            self.assertEqual(req_obj.full_url, "https://www.oscinemas.net/cgi-bin/api/get-top-schedule.cgi")
            self.assertEqual(req_obj.data, b"site_c=21080&target_ymd=2026-11-23")
            self.assertEqual(len(fetched), 1)

        # 404時は空リスト
        http_404 = urllib.error.HTTPError(
            "https://www.oscinemas.net/404", 404, "Not Found", {}, io.BytesIO(b"")
        )
        try:
            with patch("urllib.request.urlopen", side_effect=http_404):
                self.assertEqual(provider.fetch_movies("os_harborland", date(2026, 12, 31)), [])
        finally:
            http_404.close()


if __name__ == "__main__":
    unittest.main()
