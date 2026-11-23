from datetime import date
import io
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
import urllib.error

from scraper.models import SeatStatus
from scraper.providers import PROVIDER_REGISTRY, get_provider
from scraper.providers.uscinemas import (
    UsCinemasProvider,
    map_uscinemas_seat_status,
    normalize_uscinemas_screen_name,
    parse_uscinemas_schedule_html,
    validate_uscinemas_booking_url,
)
from scraper.providers.forum import (
    ForumCinemaProvider,
    map_forum_seat_status,
    normalize_forum_screen_name,
    parse_forum_schedule_html,
)
from scraper.providers.kinocinema import (
    KinoCinemaProvider,
    map_kinocinema_seat_status,
    normalize_kinocinema_screen_name,
    parse_kinocinema_schedule_html,
    resolve_kinocinema_dates,
    validate_kinocinema_booking_url,
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


class TestPhase3ProviderRegistry(unittest.TestCase):
    """uscinemas / forum / kinocinema のレジストリ・マスタ・セキュリティ統合テスト"""

    def test_phase3_providers_registered_with_expected_counts(self):
        expected = [
            ("uscinemas", UsCinemasProvider, 6, "kisarazu", "USシネマ木更津"),
            ("forum", ForumCinemaProvider, 7, "solaris", "ソラリス"),
            ("kinocinema", KinoCinemaProvider, 6, "shinjuku", "kino cinéma新宿"),
        ]
        for chain_id, cls, count, sample_tid, sample_name in expected:
            self.assertIn(chain_id, PROVIDER_REGISTRY)
            provider = get_provider(chain_id)
            self.assertIsInstance(provider, cls)
            self.assertEqual(len(provider._load_theaters_master()), count)
            self.assertEqual(provider.get_theater_name(sample_tid), sample_name)

    def test_rejects_malicious_and_unregistered_theater_ids(self):
        for chain in ("uscinemas", "forum", "kinocinema"):
            provider = get_provider(chain)
            with self.assertRaises(UnsafeUrlError):
                provider.fetch_movies("../etc/passwd", date(2026, 11, 23))
            with self.assertRaises(RuntimeError):
                provider.fetch_movies("unknown_theater_id", date(2026, 11, 23))

            res = subprocess.run(
                [sys.executable, "-m", "scraper.cli", "--chain", chain, "--theater", "../bad"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 2)
            self.assertIn("security_violation", res.stderr)


class TestUsCinemasProvider(unittest.TestCase):
    """USシネマ・千葉劇場 (UsCinemasProvider) の単体テスト"""

    def test_screen_normalization_and_status_mapping(self):
        self.assertEqual(normalize_uscinemas_screen_name("01"), "シネマ1")
        self.assertEqual(normalize_uscinemas_screen_name("1"), "シネマ1")
        self.assertEqual(normalize_uscinemas_screen_name("ADMIX"), "ADMIX")
        self.assertEqual(normalize_uscinemas_screen_name("4DXシアター"), "4DX")
        self.assertEqual(normalize_uscinemas_screen_name("ＣＩＮＥＭＡ 4"), "シネマ4")

        self.assertEqual(map_uscinemas_seat_status('<img src=".../icon_01.png" alt="Vacant Seat WEB(1)">'), (SeatStatus.AVAILABLE, True))
        self.assertEqual(map_uscinemas_seat_status('<img src=".../icon_02.png" alt="Vacant Seat WEB(2)">'), (SeatStatus.FEW, True))
        self.assertEqual(map_uscinemas_seat_status('<img src=".../icon_03.png" alt="Vacant Seat WEB(3)">'), (SeatStatus.FULL, False))
        self.assertEqual(map_uscinemas_seat_status('<img src=".../icon_04.png" alt="Vacant Seat WEB(4)">'), (SeatStatus.UNSOLD, False))
        self.assertEqual(map_uscinemas_seat_status('<img class="seg-icon-img" src=".../main-show.png" />'), (SeatStatus.AVAILABLE, False))

        self.assertEqual(
            validate_uscinemas_booking_url("https://cinema-ticket.jp/cinemax/Index/001/004/255102"),
            "https://cinema-ticket.jp/cinemax/Index/001/004/255102",
        )
        self.assertEqual(validate_uscinemas_booking_url("https://evil.example.com/123"), "")
        self.assertEqual(validate_uscinemas_booking_url("http://cinema-ticket.jp/123"), "")

    def test_parse_schedule_html_multiline_and_chibagekijo(self):
        provider = UsCinemasProvider()
        kisarazu_info = provider.get_theater_info("kisarazu")
        html = """
        <table class="table">
          <thead><tr><td colspan="7"><h4 class="pull-left">【ATMOS】テスト作品A</h4><h4 class="pull-right">120分</h4></td></tr></thead>
          <tbody>
            <tr>
              <td style="text-align:center;"><span>Theater</span><h3 class="scheduleh3">ADMIX</h3></td>
              <td class="td_space ">
                <h3 class="scheduleh3">9:50</h3>
                <span class="finish-time-show">~11:50</span><br>
                <img class="vacant-icon-img" src="https://uscinemas.jp/wp-content/themes/cinemax_bootstrap/images/icon_01.png" alt="Vacant Seat WEB(1)" />
                <a href="https://cinema-ticket.jp/cinemax/Index/001/004/254985">購入</a>
              </td>
              <td class="td_space"></td>
            </tr>
            <tr>
              <td></td>
              <td class="td_space ">
                <h3 class="scheduleh3">15:30</h3>
                <span class="finish-time-show">~17:30</span><br>
                <img class="vacant-icon-img" src="https://uscinemas.jp/wp-content/themes/cinemax_bootstrap/images/icon_03.png" alt="Vacant Seat WEB(3)" />
                <a href="https://cinema-ticket.jp/cinemax/Index/001/004/254986">満席</a>
              </td>
            </tr>
          </tbody>
        </table>
        """
        movies = parse_uscinemas_schedule_html(html, date(2026, 11, 24), "kisarazu", kisarazu_info)
        self.assertEqual(len(movies), 1)
        m = movies[0]
        self.assertEqual(m.movie_title, "【ATMOS】テスト作品A")
        self.assertEqual(m.info_url, "https://uscinemas.jp/category/kisarazu/")
        self.assertEqual(len(m.screenings), 2)

        s0, s1 = m.screenings
        self.assertEqual(s0.event_id, "kisarazu_254985")
        self.assertEqual(s0.screen_name, "ADMIX")
        self.assertEqual(s0.start_time, "09:50")
        self.assertEqual(s0.end_time, "11:50")
        self.assertEqual(s0.seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(s0.booking_url, "https://cinema-ticket.jp/cinemax/Index/001/004/254985")
        self.assertIn("Dolby Atmos", s0.tags)
        self.assertIn("ADMIX", s0.tags)

        # 2行目折り返しでも ADMIX を引き継ぎ、満席は booking_url 空
        self.assertEqual(s1.event_id, "kisarazu_254986")
        self.assertEqual(s1.screen_name, "ADMIX")
        self.assertEqual(s1.seat_status, SeatStatus.FULL)
        self.assertEqual(s1.booking_url, "")

        # 千葉劇場（窓口のみ）
        cb_info = provider.get_theater_info("chibagekijo")
        cb_html = """
        <table class="table">
          <thead><tr><td colspan="7"><h4 class="pull-left">名作上映</h4></td></tr></thead>
          <tbody>
            <tr>
              <td><h3 class="scheduleh3">1</h3></td>
              <td class="td_space"><h3 class="scheduleh3">10:00</h3><span class="finish-time-show">~12:00</span><img class="seg-icon-img" src=".../main-show.png" /></td>
            </tr>
          </tbody>
        </table>
        """
        cb_movies = parse_uscinemas_schedule_html(cb_html, date(2026, 11, 24), "chibagekijo", cb_info)
        self.assertEqual(len(cb_movies), 1)
        self.assertEqual(cb_movies[0].screenings[0].screen_name, "シネマ1")
        self.assertEqual(cb_movies[0].screenings[0].seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(cb_movies[0].screenings[0].booking_url, "")

    def test_fetch_movies_mocked_and_http_404_no_leak(self):
        provider = UsCinemasProvider()
        opened_errors = []

        def fake_404(req, timeout=15):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            err = urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
            opened_errors.append(err)
            raise err

        try:
            with patch("urllib.request.urlopen", side_effect=fake_404):
                with self.assertRaises(RuntimeError):
                    provider.fetch_movies("kisarazu", date(2026, 11, 24))
        finally:
            for err in opened_errors:
                err.close()


class TestForumProvider(unittest.TestCase):
    """フォーラムシネマネットワーク (ForumCinemaProvider) の単体テスト"""

    def test_status_mapping_and_screen_normalization(self):
        self.assertEqual(map_forum_seat_status('<a class="purchase-dialog__trigger purchase vacancy">購入する</a>'), (SeatStatus.AVAILABLE, True))
        self.assertEqual(map_forum_seat_status('<a class="purchase-dialog__trigger purchase little">残りわずか</a>'), (SeatStatus.FEW, True))
        self.assertEqual(map_forum_seat_status('<a class="purchase soldout">満席</a>'), (SeatStatus.FULL, False))
        self.assertEqual(map_forum_seat_status('<a class="purchase soldout">販売終了</a>'), (SeatStatus.UNSOLD, False))
        self.assertEqual(map_forum_seat_status('<a class="purchase notsale">販売前</a>'), (SeatStatus.UNSOLD, False))

        self.assertEqual(normalize_forum_screen_name("フォーラム 2"), "フォーラム2")
        self.assertEqual(normalize_forum_screen_name("ソラリス ３"), "ソラリス3")

    def test_parse_forum_html_and_solaris_query_url(self):
        provider = ForumCinemaProvider()
        solaris_info = provider.get_theater_info("solaris")
        html = """
        <div class="oneday-schedule">
          <section class="oneday--movie-list js-accordion">
            <h2 class="oneday--movie-name js-accordion-title">テスト作品（4DX）<br class="sp-only"><span></span></h2>
            <div class="movie-info--content">
              <div class="movie-info--left">
                <a href="https://forum-movie.net/yamagata/movie/7680"><img src="x.jpg"></a>
              </div>
              <div class="movie-info--right">
                <ul class="timetable">
                  <li>
                    <span class="start-time digit">9:40</span>
                    <span class="end-time digit">11:35</span>
                    <span class="movie-info-theater-block"><span class="movie-info-theater">ソラリス1</span></span>
                    <span class="purchase-block"><a class="purchase-dialog__trigger purchase vacancy" href="#dialog_6afbb9e16bc49fc6e35f5f0b">購入する</a></span>
                    <div class="purchase-dialog" id="dialog_6afbb9e16bc49fc6e35f5f0b">
                      <a href="#purchase-guide" data-purchase-url="https://login.member.forum-movie.net/purchase/guest?eventId=6afbb9e16bc49fc6e35f5f0b">ログインせずに購入する</a>
                    </div>
                  </li>
                  <li>
                    <span class="start-time digit">14:00</span>
                    <span class="end-time digit">15:55</span>
                    <span class="movie-info-theater-block"><span class="movie-info-theater">ソラリス2</span></span>
                    <span class="purchase-block"><a class="purchase soldout">販売終了</a></span>
                  </li>
                </ul>
              </div>
            </div>
          </section>
        </div>
        """

        requested_urls = []

        def fake_urlopen(req, timeout=15):
            requested_urls.append(req.full_url if hasattr(req, "full_url") else str(req))
            return _FakeHttpResponse(html.encode("utf-8"))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            movies = provider.fetch_movies("solaris", date(2026, 11, 24))

        self.assertEqual(len(requested_urls), 1)
        self.assertIn("https://forum-movie.net/yamagata/by-date?", requested_urls[0])
        self.assertIn("date=2026-11-24", requested_urls[0])
        self.assertIn("theater_id=5", requested_urls[0])

        self.assertEqual(len(movies), 1)
        m = movies[0]
        self.assertEqual(m.movie_id, "7680")
        self.assertEqual(m.info_url, "https://forum-movie.net/yamagata/movie/7680")
        s0, s1 = m.screenings
        self.assertEqual(s0.screen_name, "ソラリス1")
        self.assertEqual(s0.start_time, "09:40")
        self.assertEqual(s0.seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(
            s0.booking_url,
            "https://login.member.forum-movie.net/purchase/guest?eventId=6afbb9e16bc49fc6e35f5f0b",
        )
        self.assertEqual(s1.seat_status, SeatStatus.UNSOLD)
        self.assertEqual(s1.booking_url, "")

        # yamagata は theater_id=4 を付与すること
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            provider.fetch_movies("yamagata", date(2026, 11, 24))
        self.assertIn("theater_id=4", requested_urls[1])

    def test_forum_http_404_no_leak(self):
        provider = ForumCinemaProvider()
        opened_errors = []

        def fake_404(req, timeout=15):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            err = urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
            opened_errors.append(err)
            raise err

        try:
            with patch("urllib.request.urlopen", side_effect=fake_404):
                with self.assertRaises(RuntimeError):
                    provider.fetch_movies("sendai", date(2026, 11, 24))
        finally:
            for err in opened_errors:
                err.close()


class TestKinoCinemaProvider(unittest.TestCase):
    """キノシネマ (KinoCinemaProvider) の単体テスト"""

    def test_dates_year_rollover_statuses_and_booking_url(self):
        md_list = [(12, 30), (12, 31), (1, 1), (1, 2)]
        self.assertEqual(
            resolve_kinocinema_dates(md_list, date(2026, 12, 30)),
            [date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 2)],
        )

        self.assertEqual(map_kinocinema_seat_status("schedule__btn -available"), (SeatStatus.AVAILABLE, True))
        self.assertEqual(map_kinocinema_seat_status("schedule__btn -few"), (SeatStatus.FEW, True))
        self.assertEqual(map_kinocinema_seat_status("schedule__btn -sold"), (SeatStatus.FULL, False))
        self.assertEqual(map_kinocinema_seat_status("schedule__btn -offline"), (SeatStatus.AVAILABLE, False))
        self.assertEqual(map_kinocinema_seat_status("schedule__btn -past"), (SeatStatus.UNSOLD, False))

        self.assertEqual(
            normalize_kinocinema_screen_name('THEATER 1 <span class="schedule__screen-sheat">294席</span>'),
            "THEATER 1",
        )
        self.assertEqual(
            normalize_kinocinema_screen_name('シアター １ <span class="schedule__screen-sheat">85席</span>'),
            "シアター1",
        )
        self.assertEqual(
            validate_kinocinema_booking_url("https://app.eigaland.com/booking?&scheduleId=6afc0359c134b873ddb9cb85"),
            "https://app.eigaland.com/booking?scheduleId=6afc0359c134b873ddb9cb85",
        )
        self.assertEqual(validate_kinocinema_booking_url("https://evil.example.com/booking?id=1"), "")

    def test_parse_kinocinema_schedule_html_balanced_tabs(self):
        provider = KinoCinemaProvider()
        shinjuku_info = provider.get_theater_info("shinjuku")
        html = """
        <ul class="schedule__day-list">
          <li class="schedule__day-btn -current"><button><span class="schedule__month">11/</span><span class="schedule__date">23</span></button></li>
          <li class="schedule__day-btn"><button><span class="schedule__month">11/</span><span class="schedule__date">24</span></button></li>
        </ul>
        <div class="schedule__container">
          <div class="schedule__item">
            <div class="schedule__movie">
              <h4 class="schedule__title"><a href="/shinjuku/movie/movie-detail/477">初日作品</a></h4>
              <div class="schedule__screen">
                <h5 class="schedule__screen-name">THEATER 1 <span class="schedule__screen-sheat">294席</span></h5>
                <ul class="schedule__time-selecter">
                  <li class="schedule__btn -past"><div class="schedule__btn-inner"><em class="schedule__start-time">10:00</em><span class="schedule__end-time">- 12:00</span></div></li>
                </ul>
              </div>
            </div>
          </div>
          <div class="schedule__item">
            <div class="schedule__movie">
              <h4 class="schedule__title"><span class="schedule__icon"><span class="icon-new">NEW</span></span><a href="/shinjuku/movie/movie-detail/468">翌日テスト作品</a></h4>
              <div class="schedule__screen">
                <h5 class="schedule__screen-name">THEATER 1 <span class="schedule__screen-sheat">294席</span></h5>
                <ul class="schedule__time-selecter">
                  <li class="schedule__btn -available"><a href="https://app.eigaland.com/booking?&scheduleId=6afff38338e49b746133f165"><div class="schedule__btn-inner"><em class="schedule__start-time">15:30</em><span class="schedule__end-time">- 18:30</span></div></a></li>
                  <li class="schedule__btn -offline"><div class="schedule__btn-inner"><em class="schedule__start-time">19:00</em><span class="schedule__end-time">- 21:00</span></div></li>
                  <li class="schedule__btn -empty"></li>
                </ul>
              </div>
            </div>
          </div>
        </div>
        """
        movies = parse_kinocinema_schedule_html(
            html=html,
            target_date=date(2026, 11, 24),
            theater_id="shinjuku",
            theater_info=shinjuku_info,
            reference_date=date(2026, 11, 23),
        )
        self.assertEqual(len(movies), 1)
        m = movies[0]
        self.assertEqual(m.movie_id, "468")
        self.assertEqual(m.movie_title, "翌日テスト作品")
        self.assertEqual(m.info_url, "https://kinocinema.jp/shinjuku/movie/movie-detail/468")
        self.assertEqual(len(m.screenings), 2)

        s0, s1 = m.screenings
        self.assertEqual(s0.screen_name, "THEATER 1")
        self.assertEqual(s0.start_time, "15:30")
        self.assertEqual(s0.end_time, "18:30")
        self.assertEqual(s0.seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(s0.booking_url, "https://app.eigaland.com/booking?scheduleId=6afff38338e49b746133f165")

        self.assertEqual(s1.seat_status, SeatStatus.AVAILABLE)
        self.assertEqual(s1.booking_url, "")

        # タブにない日付は空
        self.assertEqual(
            parse_kinocinema_schedule_html(html, date(2026, 12, 1), "shinjuku", shinjuku_info, date(2026, 11, 23)),
            [],
        )

    def test_kinocinema_http_404_no_leak(self):
        provider = KinoCinemaProvider()
        opened_errors = []

        def fake_404(req, timeout=15):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            err = urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
            opened_errors.append(err)
            raise err

        try:
            with patch("urllib.request.urlopen", side_effect=fake_404):
                with self.assertRaises(RuntimeError):
                    provider.fetch_movies("shinjuku", date(2026, 11, 24))
        finally:
            for err in opened_errors:
                err.close()


if __name__ == "__main__":
    unittest.main()
