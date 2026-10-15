import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import update_theaters


SAMPLE_THEATER_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div class="c-areas">
    <h2 class="c-area__name">北海道</h2>
    <div class="c-area__theaters">
      <a href="#" class="c-area__theater js_reserve_area" data-theater-id="81005" data-theater-name="ebetsu">
        <div class="c-area__inner">
          <h3>江別</h3>
        </div>
      </a>
      <a href="#" class="c-area__theater js_reserve_area" data-theater-id="81024" data-theater-name="otaru">
        <div class="c-area__inner">
          <h3>小樽</h3>
        </div>
      </a>
      <!-- 重複のテスト用 -->
      <a href="#" class="c-area__theater js_reserve_area" data-theater-id="81005" data-theater-name="ebetsu">
        <div class="c-area__inner">
          <h3>江別</h3>
        </div>
      </a>
    </div>

    <h2 class="c-area__name">東京</h2>
    <div class="c-area__theaters">
      <a href="#" class="c-area__theater js_reserve_area" data-theater-id="81084" data-theater-name="chofu">
        <div class="c-area__inner">
          <h3>シアタス調布</h3>
        </div>
      </a>
    </div>
  </div>
</body>
</html>
"""


class TestUpdateTheaters(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_fetch_theater_list(self, mock_urlopen):
        # HTTPレスポンスをモック
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_THEATER_HTML.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        theaters = update_theaters.fetch_theater_list()

        # 重複が排除され、3劇場が抽出されているか
        self.assertEqual(len(theaters), 3)

        # 各劇場のフィールドを検証
        ebetsu = next(t for t in theaters if t["id"] == "ebetsu")
        self.assertEqual(ebetsu["name"], "江別")
        self.assertEqual(ebetsu["theater_id"], "81005")
        self.assertEqual(ebetsu["area"], "北海道")
        self.assertEqual(ebetsu["url"], "https://theater.aeoncinema.com/theaters/ebetsu/")

        otaru = next(t for t in theaters if t["id"] == "otaru")
        self.assertEqual(otaru["name"], "小樽")
        self.assertEqual(otaru["theater_id"], "81024")
        self.assertEqual(otaru["area"], "北海道")

        chofu = next(t for t in theaters if t["id"] == "chofu")
        self.assertEqual(chofu["name"], "シアタス調布")
        self.assertEqual(chofu["theater_id"], "81084")
        self.assertEqual(chofu["area"], "東京")

    @patch("update_theaters.fetch_theater_list")
    def test_generate_theater_json(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "id": "ebetsu",
                "name": "江別",
                "theater_id": "81005",
                "area": "北海道",
                "url": "https://theater.aeoncinema.com/theaters/ebetsu/",
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_json = os.path.join(tmpdir, "theater.json")
            result = update_theaters.generate_theater_json(tmp_json, with_facility=False)

            self.assertEqual(len(result), 1)
            self.assertTrue(os.path.exists(tmp_json))

            with open(tmp_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data[0]["id"], "ebetsu")
            self.assertEqual(data[0]["name"], "江別")

    def test_parse_facility_html(self):
        sample_facility_html = """
        <div class="c-modal" data-modal="modal_seat_0">
          <div class="c-modal__body">
            <img src="https://theater.aeoncinema.com/uploads/theaters/seatmap/1005/01.gif" alt="">
          </div>
        </div>
        <section class="p-facility__facilitys" id="facility">
          <div class="p-facility__block">
            <div class="p-facility__picture">
              <span>3・7番スクリーン導入</span>
            </div>
            <p class="p-facility__name">デジタル3D</p>
            <p class="p-facility__lead">臨場感あふれる3D映像体験。</p>
          </div>
        </section>
        <section class="p-facility__screens" id="screen">
          <div class="p-facility__screenLists">
            <div class="p-facility__screenList c-accordion">
              <label class="c-accordion__header">
                <span class="c-accordion__label">1スクリーン</span>
              </label>
              <div class="c-accordion__body">
                <div class="p-facility__chip">
                  <span data-chip="アップグレードシート">アップグレードシート</span>
                  <span data-chip="トリプルエアシールド">トリプルエアシールド</span>
                </div>
                <div class="p-facility__detail">
                  <a href="#" data-modal="modal_seat_0">座席図</a>
                </div>
                <div class="p-facility__tables">
                  <table>
                    <tr><th>通常座席</th><td>300席</td></tr>
                    <tr><th>アップグレードシート</th><td>10席</td></tr>
                    <tr><th>合 計</th><td>310席</td></tr>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </section>
        """
        facility = update_theaters.parse_facility_html(sample_facility_html, "ebetsu")
        self.assertEqual(facility["url"], "https://www.aeoncinema.com/ebetsu/facility/")
        self.assertEqual(len(facility["screens"]), 1)
        screen = facility["screens"][0]
        self.assertEqual(screen["name"], "1スクリーン")
        self.assertEqual(screen["features"], ["アップグレードシート", "トリプルエアシールド"])
        self.assertEqual(screen["total_seats"], 310)
        self.assertEqual(screen["seats"]["通常座席"], 300)
        self.assertEqual(screen["seat_map_url"], "https://theater.aeoncinema.com/uploads/theaters/seatmap/1005/01.gif")

        self.assertEqual(len(facility["theater_services"]), 1)
        service = facility["theater_services"][0]
        self.assertEqual(service["name"], "デジタル3D")
        self.assertEqual(service["screen"], "3・7番スクリーン導入")


if __name__ == "__main__":
    unittest.main()

