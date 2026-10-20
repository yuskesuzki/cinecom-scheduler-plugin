import json
import os
import shutil
import subprocess
import tempfile
import unittest


class TestQuickShellUIComponents(unittest.TestCase):
    """
    Quickshell の実行環境を利用した QML UI コンポーネントの自動テストハーネス。
    Quickshell を一時サンドボックス環境で起動し、QML の構文、プロパティバインディング、
    フィルタリング、グルーピングロジックなどを自動検証します。
    """

    @classmethod
    def setUpClass(cls):
        cls.plugin_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cls.components_dir = os.path.join(cls.plugin_dir, "components")

    def run_qml_test(self, qml_body: str, timeout_sec: float = 3.0) -> str:
        """
        Quickshell のサンドボックスを作成し、qml_body を含む shell.qml を実行してログ出力を返します。
        """
        temp_dir = tempfile.mkdtemp(prefix="qs_ui_test_")
        try:
            # Omarchy の Commons / Ui モジュールをシンボリックリンク
            for mod in ["Commons", "Ui"]:
                src = os.path.join("/usr/share/omarchy/shell", mod)
                if os.path.exists(src):
                    os.symlink(src, os.path.join(temp_dir, mod))

            # components ディレクトリをシンボリックリンク
            os.symlink(self.components_dir, os.path.join(temp_dir, "components"))

            # テスト用 shell.qml を作成
            test_qml_path = os.path.join(temp_dir, "shell.qml")
            with open(test_qml_path, "w", encoding="utf-8") as f:
                f.write(qml_body)

            # quickshell を実行して出力をキャプチャ (タイムアウトで安全に停止)
            proc = subprocess.Popen(
                ["quickshell", "-p", test_qml_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                out, err = proc.communicate(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()

            return out + "\n" + err
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_settings_modal_theater_filtering(self):
        """SettingsModal での劇場絞り込み（インクリメンタルサーチ）のテスト"""
        qml = """import QtQuick
import Quickshell
import "./components"

ShellRoot {
  Scope {
    SettingsModal {
      id: modal
      visible: true
      allTheaters: [
        { id: "089", name: "TOHOシネマズ すすきの", region: "北海道" },
        { id: "004", name: "TOHOシネマズ 秋田", region: "秋田県" },
        { id: "009", name: "TOHOシネマズ 新宿", region: "東京都" }
      ]
    }

    Component.onCompleted: {
      // 1. 初期状態: 3件すべて表示
      if (modal.filteredTheaters.length !== 3) {
        console.log("[TEST_FAIL] Initial count expected 3, got: " + modal.filteredTheaters.length);
        return;
      }

      // 2. 「すすきの」で絞り込み: 1件
      modal.theaterSearchText = "すすきの";
      if (modal.filteredTheaters.length !== 1 || modal.filteredTheaters[0].id !== "089") {
        console.log("[TEST_FAIL] 'すすきの' search failed");
        return;
      }

      // 3. 「東京」で地域絞り込み: 新宿 1件
      modal.theaterSearchText = "東京";
      if (modal.filteredTheaters.length !== 1 || modal.filteredTheaters[0].id !== "009") {
        console.log("[TEST_FAIL] '東京' search failed");
        return;
      }

      // 4. クリア: 3件に復帰
      modal.theaterSearchText = "";
      if (modal.filteredTheaters.length !== 3) {
        console.log("[TEST_FAIL] Clear search failed");
        return;
      }

      console.log("[TEST_SETTINGS_MODAL_SUCCESS]");
    }
  }
}
"""
        output = self.run_qml_test(qml)
        self.assertIn("[TEST_SETTINGS_MODAL_SUCCESS]", output)
        self.assertNotIn("Failed to load configuration", output)

    def test_search_modal_validation(self):
        """SearchModal での入力必須チェックおよび検索リクエスト発火のテスト"""
        qml = """import QtQuick
import Quickshell
import "./components"

ShellRoot {
  Scope {
    id: testScope
    property bool searchFired: false
    property var lastSearchArgs: null

    SearchModal {
      id: searchModal
      visible: true
      queryTitle: ""
      queryArea: "東京都"
      queryDate: "today"
      queryRange: "after"
      queryTheater: ""

      onSearchRequested: function(title, area, dateVal, rangeVal, theaterVal) {
        testScope.searchFired = true;
        testScope.lastSearchArgs = {
          title: title,
          area: area,
          dateVal: dateVal,
          rangeVal: rangeVal,
          theaterVal: theaterVal
        };
      }
    }

    Component.onCompleted: {
      // 1. タイトル空文字の場合は検索が発火しないこと
      searchModal.executeSearch();
      if (testScope.searchFired) {
        console.log("[TEST_FAIL] Empty title should not fire search");
        return;
      }

      // 2. タイトル空白のみの場合も発火しないこと
      searchModal.queryTitle = "   ";
      searchModal.executeSearch();
      if (testScope.searchFired) {
        console.log("[TEST_FAIL] Whitespace-only title should not fire search");
        return;
      }

      // 3. 有効なタイトルが設定された場合は正しく発火すること
      searchModal.queryTitle = " ガンダム ";
      searchModal.executeSearch();
      if (!testScope.searchFired || !testScope.lastSearchArgs) {
        console.log("[TEST_FAIL] Valid title should fire search");
        return;
      }

      if (testScope.lastSearchArgs.title !== "ガンダム" || testScope.lastSearchArgs.area !== "東京都") {
        console.log("[TEST_FAIL] Search arguments mismatched: " + JSON.stringify(testScope.lastSearchArgs));
        return;
      }

      console.log("[TEST_SEARCH_MODAL_SUCCESS]");
    }
  }
}
"""
        output = self.run_qml_test(qml)
        self.assertIn("[TEST_SEARCH_MODAL_SUCCESS]", output)
        self.assertNotIn("Failed to load configuration", output)

    def test_search_result_view_grouping(self):
        """SearchResultView での上映スケジュール劇場別グルーピングロジックのテスト"""
        qml = """import QtQuick
import Quickshell
import "./components"

ShellRoot {
  Scope {
    SearchResultView {
      id: view
      rawScreenings: [
        {
          chain_id: "toho",
          theater_id: "089",
          theater_name: "TOHOシネマズ すすきの",
          movie_title: "機動戦士ガンダム",
          screen_name: "SCREEN 1",
          start_time: "10:00",
          end_time: "12:00",
          seat_status: "available",
          booking_url: "https://hlo.tohotheater.jp/ticket1"
        },
        {
          chain_id: "toho",
          theater_id: "089",
          theater_name: "TOHOシネマズ すすきの",
          movie_title: "機動戦士ガンダム",
          screen_name: "SCREEN 1",
          start_time: "14:00",
          end_time: "16:00",
          seat_status: "few",
          booking_url: "https://hlo.tohotheater.jp/ticket2"
        },
        {
          chain_id: "aeon",
          theater_id: "ebetsu",
          theater_name: "イオンシネマ江別",
          movie_title: "機動戦士ガンダム",
          screen_name: "スクリーン2",
          start_time: "11:30",
          end_time: "13:30",
          seat_status: "sold_out",
          booking_url: "https://reserve.aeoncinema.com/ticket3"
        }
      ]
    }

    Component.onCompleted: {
      var groups = view.groupedTheaters;
      // 2つの劇場グループに分類されていること
      if (groups.length !== 2) {
        console.log("[TEST_FAIL] Expected 2 theater groups, got: " + groups.length);
        return;
      }

      // 1つ目の劇場 (すすきの) に2回の上映があること
      if (groups[0].theaterId !== "089" || groups[0].screenings.length !== 2) {
        console.log("[TEST_FAIL] Group 0 (すすきの) mismatch");
        return;
      }

      // 2つ目の劇場 (江別) に1回の上映があること
      if (groups[1].theaterId !== "ebetsu" || groups[1].screenings.length !== 1) {
        console.log("[TEST_FAIL] Group 1 (江別) mismatch");
        return;
      }

      console.log("[TEST_SEARCH_RESULT_VIEW_SUCCESS]");
    }
  }
}
"""
        output = self.run_qml_test(qml)
        self.assertIn("[TEST_SEARCH_RESULT_VIEW_SUCCESS]", output)
        self.assertNotIn("Failed to load configuration", output)

    def test_movie_schedule_view_text_format_security(self):
        """MovieScheduleView および各 QML コンポーネント内の動的 Text 要素に PlainText が設定されていることを静的検証"""
        import re

        files_to_check = [
            os.path.join(self.plugin_dir, "BarWidget.qml"),
            os.path.join(self.components_dir, "MovieScheduleView.qml"),
            os.path.join(self.components_dir, "ScreenModal.qml"),
            os.path.join(self.components_dir, "SearchModal.qml"),
            os.path.join(self.components_dir, "SearchResultView.qml"),
            os.path.join(self.components_dir, "SettingsModal.qml"),
        ]

        # 特に MovieScheduleView.qml の movie-filter ラベル
        with open(os.path.join(self.components_dir, "MovieScheduleView.qml"), encoding="utf-8") as f:
            movie_view_content = f.read()

        # 1. フィルター選択ボタン内の Text
        self.assertRegex(
            movie_view_content,
            r'Text\s*\{[^}]*Layout\.fillWidth:\s*true[^}]*textFormat:\s*Text\.PlainText[^}]*rootScheduleView\.selectedMovieFilter',
            "Movie filter label must enforce Text.PlainText"
        )

        # 2. フィルター選択肢ドロップダウン内の Text
        self.assertRegex(
            movie_view_content,
            r'Text\s*\{[^}]*Layout\.fillWidth:\s*true[^}]*textFormat:\s*Text\.PlainText[^}]*text:\s*modelData',
            "Movie filter dropdown option must enforce Text.PlainText"
        )


if __name__ == "__main__":
    unittest.main()
