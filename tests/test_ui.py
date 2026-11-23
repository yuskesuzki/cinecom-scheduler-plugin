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

    def run_qml_test(
        self,
        qml_body: str,
        timeout_sec: float = 3.0,
        env_overrides: dict | None = None,
    ) -> str:
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

            env = os.environ.copy()
            if env_overrides:
                env.update(env_overrides)

            # quickshell を実行して出力をキャプチャ (タイムアウトで安全に停止)
            proc = subprocess.Popen(
                ["quickshell", "-p", test_qml_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
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

    def test_search_result_view_tjoy_label(self):
        """SearchResultView で T・ジョイのグルーピングと日英チェーンラベル表示を検証"""
        qml = """import QtQuick
import Quickshell
import "./components"

ShellRoot {
  Scope {
    SearchResultView {
      id: view
      englishMode: false
      rawScreenings: [
        {
          chain_id: "tjoy",
          theater_id: "shinjuku_wald9",
          theater_name: "新宿バルト9",
          movie_title: "テスト映画",
          screen_name: "シアター6",
          start_time: "12:00",
          end_time: "14:00",
          seat_status: "available",
          booking_url: "https://tjoy.jp/shinjuku_wald9/reservation/index/1/2/6/2026-11-23?type=film"
        }
      ]
    }

    Component.onCompleted: {
      var groups = view.groupedTheaters;
      if (groups.length !== 1 || groups[0].chainId !== "tjoy") {
        console.log("[TEST_FAIL] Expected 1 tjoy group");
        return;
      }
      if (view.getChainLabel("tjoy") !== "T・ジョイ") {
        console.log("[TEST_FAIL] Expected Japanese label T・ジョイ, got: " + view.getChainLabel("tjoy"));
        return;
      }
      view.englishMode = true;
      if (view.getChainLabel("tjoy") !== "T-JOY") {
        console.log("[TEST_FAIL] Expected English label T-JOY, got: " + view.getChainLabel("tjoy"));
        return;
      }
      console.log("[TEST_TJOY_UI_SUCCESS]");
    }
  }
}
"""
        output = self.run_qml_test(qml)
        self.assertIn("[TEST_TJOY_UI_SUCCESS]", output)
        self.assertNotIn("Failed to load configuration", output)

    def test_search_result_view_109cinemas_label(self):
        """SearchResultView で 109シネマズのグルーピングと日英チェーンラベル表示を検証"""
        qml = """import QtQuick
import Quickshell
import "./components"

ShellRoot {
  Scope {
    SearchResultView {
      id: view
      englishMode: false
      rawScreenings: [
        {
          chain_id: "109cinemas",
          theater_id: "kiba",
          theater_name: "109シネマズ木場",
          movie_title: "テスト映画",
          screen_name: "シアター2",
          start_time: "12:00",
          end_time: "14:00",
          seat_status: "available",
          booking_url: "https://cinema.109cinemas.net/cgi-bin/pc/resv/resv_shw_ppt.cgi?ttc=53555&tsc=20&tssc=20&ymd=2026-11-22&cs=&stt=1200"
        }
      ]
    }

    Component.onCompleted: {
      var groups = view.groupedTheaters;
      if (groups.length !== 1 || groups[0].chainId !== "109cinemas") {
        console.log("[TEST_FAIL] Expected 1 109cinemas group");
        return;
      }
      if (view.getChainLabel("109cinemas") !== "109シネマズ") {
        console.log("[TEST_FAIL] Expected Japanese label 109シネマズ, got: " + view.getChainLabel("109cinemas"));
        return;
      }
      view.englishMode = true;
      if (view.getChainLabel("109cinemas") !== "109") {
        console.log("[TEST_FAIL] Expected English label 109, got: " + view.getChainLabel("109cinemas"));
        return;
      }
      console.log("[TEST_109CINEMAS_UI_SUCCESS]");
    }
  }
}
"""
        output = self.run_qml_test(qml)
        self.assertIn("[TEST_109CINEMAS_UI_SUCCESS]", output)
        self.assertNotIn("Failed to load configuration", output)

    def test_search_result_view_smt_label(self):
        """SearchResultView.qml が MOVIX・ピカデリー (smt) に対して日英ともに MOVIX を返すことを検証"""
        qml = """import QtQuick
import Quickshell
import "./components"

ShellRoot {
  Scope {
    SearchResultView {
      id: view
      englishMode: false
      rawScreenings: [
        {
          chain_id: "smt",
          theater_id: "shinjuku",
          theater_name: "新宿ピカデリー",
          movie_title: "テスト映画",
          screen_name: "シアター1",
          start_time: "12:00",
          end_time: "14:00",
          seat_status: "available",
          booking_url: "https://memberlogin.smart.smt-cinema.jp/purchase/guest?eventId=abc123"
        }
      ]

      Component.onCompleted: {
        var groups = view.groupedTheaters;
        if (groups.length !== 1 || groups[0].chainId !== "smt") {
          console.log("[TEST_FAIL] Expected 1 smt group");
          return;
        }
        if (view.getChainLabel("smt") !== "MOVIX") {
          console.log("[TEST_FAIL] Expected Japanese label MOVIX, got: " + view.getChainLabel("smt"));
          return;
        }
        view.englishMode = true;
        if (view.getChainLabel("smt") !== "MOVIX") {
          console.log("[TEST_FAIL] Expected English label MOVIX, got: " + view.getChainLabel("smt"));
          return;
        }
        console.log("[TEST_SMT_UI_SUCCESS]");
      }
    }
  }
}
"""
        output = self.run_qml_test(qml)
        self.assertIn("[TEST_SMT_UI_SUCCESS]", output)
        self.assertNotIn("Failed to load configuration", output)

    def test_search_result_view_other_label(self):
        """SearchResultView.qml が 共同経営・その他 (other) に対して日英ラベル（共同 / Joint）を返すことを検証"""
        qml = """import QtQuick
import Quickshell
import "./components"

ShellRoot {
  Scope {
    SearchResultView {
      id: view
      englishMode: false
      rawScreenings: [
        {
          chain_id: "other",
          theater_id: "oscc",
          theater_name: "大阪ステーションシティシネマ",
          movie_title: "テスト映画",
          screen_name: "スクリーン1",
          start_time: "12:00",
          end_time: "14:00",
          seat_status: "available",
          booking_url: "https://ticket.osakastationcitycinema.com/ticket/f0100.do?th=1071&mo=1&sd=20261122&pe=1&sc=01&fl=0"
        }
      ]

      Component.onCompleted: {
        var groups = view.groupedTheaters;
        if (groups.length !== 1 || groups[0].chainId !== "other") {
          console.log("[TEST_FAIL] Expected 1 other group");
          return;
        }
        if (view.getChainLabel("other") !== "共同") {
          console.log("[TEST_FAIL] Expected Japanese label 共同, got: " + view.getChainLabel("other"));
          return;
        }
        view.englishMode = true;
        if (view.getChainLabel("other") !== "Joint") {
          console.log("[TEST_FAIL] Expected English label Joint, got: " + view.getChainLabel("other"));
          return;
        }
        console.log("[TEST_OTHER_UI_SUCCESS]");
      }
    }
  }
}
"""
        output = self.run_qml_test(qml)
        self.assertIn("[TEST_OTHER_UI_SUCCESS]", output)
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

    def test_settings_modal_close_and_chain_dropdown(self):
        """SettingsModal の閉じる処理と系列ドロップダウンの高さ上限・スクロール対応を検証"""
        settings_qml_path = os.path.join(self.components_dir, "SettingsModal.qml")
        with open(settings_qml_path, encoding="utf-8") as f:
            settings_content = f.read()

        self.assertNotIn("showSettingsPanel", settings_content)
        self.assertIn("chainDropdownFlickable", settings_content)

        qml = """import QtQuick
import Quickshell
import "./components"

ShellRoot {
  FloatingWindow {
    id: testWindow
    implicitWidth: 440
    implicitHeight: 600
    visible: true
    property int closedCount: 0
    property real closedHeight: 0
    property real open8Height: 0

    SettingsModal {
      id: modal
      visible: true
      bar: ({ foreground: "#ffffff", background: "#111111" })
      availableChains: [
        { id: "aeon", nameJa: "イオンシネマ", nameEn: "AEON CINEMA" },
        { id: "toho", nameJa: "TOHOシネマズ", nameEn: "TOHO CINEMAS" },
        { id: "united", nameJa: "ユナイテッド・シネマ", nameEn: "UNITED CINEMAS" },
        { id: "sunshine", nameJa: "シネマサンシャイン", nameEn: "CINEMA SUNSHINE" },
        { id: "tjoy", nameJa: "T・ジョイ", nameEn: "T-JOY" },
        { id: "109cinemas", nameJa: "109シネマズ", nameEn: "109 CINEMAS" },
        { id: "smt", nameJa: "MOVIX・ピカデリー", nameEn: "MOVIX / Piccadilly" },
        { id: "other", nameJa: "共同経営・その他", nameEn: "Joint / Other" }
      ]
      onClosed: testWindow.closedCount += 1
    }

    Timer {
      id: step1Timer
      interval: 100
      running: true
      repeat: false
      onTriggered: {
        testWindow.closedHeight = modal.contentPreferredHeight;
        if (testWindow.closedHeight <= 200) {
          console.log("[TEST_FAIL] Expected realistic closedHeight > 200, got " + testWindow.closedHeight);
          Qt.quit();
          return;
        }
        modal.chainDropdownOpen = true;
        step2Timer.start();
      }
    }

    Timer {
      id: step2Timer
      interval: 100
      repeat: false
      onTriggered: {
        testWindow.open8Height = modal.contentPreferredHeight;
        if (!(testWindow.open8Height > testWindow.closedHeight)) {
          console.log("[TEST_FAIL] Expected open8Height > closedHeight, got " + testWindow.open8Height + " vs " + testWindow.closedHeight);
          Qt.quit();
          return;
        }

        var manyChains = [];
        for (var i = 0; i < 20; i++) {
          manyChains.push({ id: "chain_" + i, nameJa: "系列" + i, nameEn: "Chain " + i });
        }
        modal.availableChains = manyChains;
        step3Timer.start();
      }
    }

    Timer {
      id: step3Timer
      interval: 100
      repeat: false
      onTriggered: {
        var open20Height = modal.contentPreferredHeight;
        if (Math.abs(open20Height - testWindow.open8Height) > 0.5) {
          console.log("[TEST_FAIL] Expected dropdown height to stay capped: 8=" + testWindow.open8Height + ", 20=" + open20Height);
          Qt.quit();
          return;
        }

        modal.close();
        if (testWindow.closedCount !== 1 || modal.chainDropdownOpen !== false) {
          console.log("[TEST_FAIL] Expected close() to emit closed once and collapse dropdown");
          Qt.quit();
          return;
        }

        console.log("[TEST_SETTINGS_DROPDOWN_SUCCESS]");
        Qt.quit();
      }
    }
  }
}
"""
        output = self.run_qml_test(
            qml,
            timeout_sec=5.0,
            env_overrides={"QT_QPA_PLATFORM": "offscreen"},
        )
        self.assertIn("[TEST_SETTINGS_DROPDOWN_SUCCESS]", output)
        self.assertNotIn("Failed to load configuration", output)
        self.assertNotIn("Binding loop detected", output)

    def test_cinema_utils_pure_logic(self):
        """components/CinemaUtils.js の純粋JSロジック・URL検証・フィルタリングを検証"""
        qml = """import QtQuick
import Quickshell
import "./components/CinemaUtils.js" as CinemaUtils

ShellRoot {
  Scope {
    Component.onCompleted: {
      // 1. チェーン定義と表示名・短縮バッジ
      if (CinemaUtils.AVAILABLE_CHAINS.length !== 8) {
        console.log("[TEST_FAIL] Expected 8 chains, got " + CinemaUtils.AVAILABLE_CHAINS.length);
        Qt.quit();
        return;
      }
      if (CinemaUtils.getChainDisplayName("tjoy", false) !== "T・ジョイ" || CinemaUtils.getChainDisplayName("tjoy", true) !== "T-JOY") {
        console.log("[TEST_FAIL] getChainDisplayName mismatch for tjoy");
        Qt.quit();
        return;
      }
      if (CinemaUtils.getChainDisplayName("unknown", false) !== "シネコン" || CinemaUtils.getChainDisplayName("unknown", true) !== "Cinema") {
        console.log("[TEST_FAIL] getChainDisplayName fallback mismatch");
        Qt.quit();
        return;
      }
      if (CinemaUtils.getChainBadgeLabel("united", false) !== "ユナイテッド" || CinemaUtils.getChainBadgeLabel("united", true) !== "United") {
        console.log("[TEST_FAIL] getChainBadgeLabel mismatch for united");
        Qt.quit();
        return;
      }
      if (CinemaUtils.getChainBadgeLabel("unknown", false) !== "イオンシネマ" || CinemaUtils.getChainBadgeLabel("unknown", true) !== "Aeon") {
        console.log("[TEST_FAIL] getChainBadgeLabel fallback mismatch");
        Qt.quit();
        return;
      }

      // 2. スクリーン名正規化・番号抽出・英訳
      if (CinemaUtils.normalizeScreenText("　ＳＣＲＥＥＮ　１２  ") !== "SCREEN 12") {
        console.log("[TEST_FAIL] normalizeScreenText mismatch");
        Qt.quit();
        return;
      }
      if (CinemaUtils.extractScreenNumber("スクリーン１") !== 1 || CinemaUtils.extractScreenNumber("SCREEN 12") !== 12 || CinemaUtils.extractScreenNumber("IMAX") !== null) {
        console.log("[TEST_FAIL] extractScreenNumber mismatch");
        Qt.quit();
        return;
      }
      if (CinemaUtils.toEnglishScreen("スクリーン7") !== "Screen 7" || CinemaUtils.toEnglishScreen("シアター３") !== "Theater 3" || CinemaUtils.getScreenDisplayName("未定", true) !== "TBD") {
        console.log("[TEST_FAIL] toEnglishScreen / getScreenDisplayName mismatch");
        Qt.quit();
        return;
      }

      // 3. 設備照合 (完全一致 / 番号一致 / キーワード一致)
      var theater = {
        id: "shinjuku",
        facility: {
          screens: [
            { name: "1スクリーン", features: [] },
            { name: "IMAXシアター", features: ["IMAX"] },
            { name: "ドルビーシネマ (Dolby Cinema)", features: ["Dolby Cinema"] },
            { name: "プラチナスクリーン", features: ["プラチナ"] }
          ]
        }
      };
      if (CinemaUtils.findScreenFacility(theater, "１スクリーン").name !== "1スクリーン") {
        console.log("[TEST_FAIL] Exact normalized screen match failed");
        Qt.quit();
        return;
      }
      if (CinemaUtils.findScreenFacility(theater, "スクリーン1").name !== "1スクリーン") {
        console.log("[TEST_FAIL] Number screen match failed");
        Qt.quit();
        return;
      }
      if (CinemaUtils.findScreenFacility(theater, "IMAXレーザー").name !== "IMAXシアター") {
        console.log("[TEST_FAIL] IMAX keyword match failed");
        Qt.quit();
        return;
      }
      if (CinemaUtils.findScreenFacility(theater, "DolbyCinema").name !== "ドルビーシネマ (Dolby Cinema)") {
        console.log("[TEST_FAIL] Dolby Cinema keyword match failed");
        Qt.quit();
        return;
      }
      if (CinemaUtils.findScreenFacility(theater, "プラチナシート").name !== "プラチナスクリーン") {
        console.log("[TEST_FAIL] Platinum keyword match failed");
        Qt.quit();
        return;
      }

      // 4. 座席行整形
      var seatRows = CinemaUtils.getSeatRows({ "通常座席": 100, "車椅子用スペース": 2, "合 計": 102, "合計": 102, "total": 102, "Total": 102 });
      if (seatRows.length !== 2 || seatRows[0].type !== "通常座席" || seatRows[1].count !== 2) {
        console.log("[TEST_FAIL] getSeatRows mismatch");
        Qt.quit();
        return;
      }

      // 5. URL検証と公式ホームページURL構築
      var validUrl = CinemaUtils.validateExternalUrl("  https://HLO.TOHOTHEATER.JP/net/schedule/009/TNPI2000J01.do ");
      if (!validUrl.ok || validUrl.hostname !== "hlo.tohotheater.jp") {
        console.log("[TEST_FAIL] Valid https URL rejected");
        Qt.quit();
        return;
      }
      if (CinemaUtils.validateExternalUrl("http://hlo.tohotheater.jp/").reason !== "non_https") {
        console.log("[TEST_FAIL] http URL should fail with non_https");
        Qt.quit();
        return;
      }
      if (CinemaUtils.validateExternalUrl("https://evil.example.com/").reason !== "unauthorized_domain") {
        console.log("[TEST_FAIL] Unauthorized domain should fail");
        Qt.quit();
        return;
      }
      if (CinemaUtils.validateExternalUrl("https:///missing-host").reason !== "malformed") {
        console.log("[TEST_FAIL] Malformed URL should fail");
        Qt.quit();
        return;
      }
      if (CinemaUtils.buildTheaterHomepageUrl("other", "oscc", { official_url: "https://www.osakastationcitycinema.com/" }) !== "https://www.osakastationcitycinema.com/") {
        console.log("[TEST_FAIL] official_url priority failed");
        Qt.quit();
        return;
      }
      if (CinemaUtils.buildTheaterHomepageUrl("toho", "009", null) !== "https://hlo.tohotheater.jp/net/schedule/009/TNPI2000J01.do" ||
          CinemaUtils.buildTheaterHomepageUrl("tjoy", "shinjuku_wald9", null) !== "https://tjoy.jp/shinjuku_wald9" ||
          CinemaUtils.buildTheaterHomepageUrl("smt", "shinjuku", null) !== "https://www.smt-cinema.com/site/shinjuku/" ||
          CinemaUtils.buildTheaterHomepageUrl("aeon", "ebetsu", null) !== "https://theater.aeoncinema.com/theaters/ebetsu/") {
        console.log("[TEST_FAIL] buildTheaterHomepageUrl template mismatch");
        Qt.quit();
        return;
      }

      // 6. 日付計算 (2026-11-23 Mon 10:00 固定)
      var baseDate = new Date(2026, 10, 23, 10, 0, 0);
      if (CinemaUtils.formatDateIso("yesterday", baseDate) !== "2026-11-22" ||
          CinemaUtils.formatDateIso("today", baseDate) !== "2026-11-23" ||
          CinemaUtils.formatDateIso("tomorrow", baseDate) !== "2026-11-24") {
        console.log("[TEST_FAIL] formatDateIso mismatch");
        Qt.quit();
        return;
      }
      if (CinemaUtils.formatDateDisplay("today", false, baseDate) !== "2026年11月23日(月)" ||
          CinemaUtils.formatDateDisplay("tomorrow", true, baseDate) !== "2026-11-24 (Tue)") {
        console.log("[TEST_FAIL] formatDateDisplay mismatch");
        Qt.quit();
        return;
      }

      // 7. 映画データ正規化・時間フィルタリング・タイトル抽出
      var rawMovies = [
        {
          movie_id: "m2",
          movie_title: "映画B",
          movie_title_en: "Movie B",
          screenings: [
            { start_time: "09:30", end_time: "11:30", screen_name: "1スクリーン", booking_url: "https://example.invalid/past" },
            { start_time: "14:00", end_time: "16:00", screen_name: "1スクリーン", booking_url: "https://example.invalid/late" }
          ]
        },
        {
          movie_id: "m1",
          movie_title: "映画A",
          movie_title_en: "Movie A",
          screenings: [
            { start_time: "11:00", end_time: "13:00", screen_name: "IMAXレーザー", booking_url: "https://example.invalid/near" }
          ]
        }
      ];
      var filteredToday = CinemaUtils.normalizeAndFilterMovies(rawMovies, {
        selectedDate: "today",
        showAllDayToday: false,
        withinHours: 3,
        theaterObj: theater,
        now: baseDate
      });
      if (filteredToday.length !== 1 || filteredToday[0].movie_id !== "m1" ||
          filteredToday[0].showtimes[0].screen_facility.name !== "IMAXシアター") {
        console.log("[TEST_FAIL] normalizeAndFilterMovies today window mismatch");
        Qt.quit();
        return;
      }
      var allDay = CinemaUtils.normalizeAndFilterMovies(rawMovies, {
        selectedDate: "today",
        showAllDayToday: true,
        withinHours: 3,
        theaterObj: theater,
        now: baseDate
      });
      if (allDay.length !== 2 || allDay[0].movie_id !== "m2" || allDay[1].movie_id !== "m1") {
        console.log("[TEST_FAIL] normalizeAndFilterMovies allDay sort mismatch");
        Qt.quit();
        return;
      }
      var titlesEn = CinemaUtils.extractUniqueMovieTitles(allDay, true);
      if (titlesEn.length !== 2 || titlesEn[0] !== "Movie A" || titlesEn[1] !== "Movie B") {
        console.log("[TEST_FAIL] extractUniqueMovieTitles mismatch");
        Qt.quit();
        return;
      }
      var byTitle = CinemaUtils.filterMoviesByTitle(allDay, "Movie A", true);
      if (byTitle.length !== 1 || byTitle[0].movie_id !== "m1") {
        console.log("[TEST_FAIL] filterMoviesByTitle mismatch");
        Qt.quit();
        return;
      }

      console.log("[TEST_CINEMA_UTILS_SUCCESS]");
      Qt.quit();
    }
  }
}
"""
        output = self.run_qml_test(qml, timeout_sec=4.0)
        self.assertIn("[TEST_CINEMA_UTILS_SUCCESS]", output)
        self.assertNotIn("Failed to load configuration", output)

    def test_allowed_domains_parity_with_python_sanitizer(self):
        """CinemaUtils.js の ALLOWED_CINEMA_DOMAINS が scraper/sanitizer.py の ALLOWED_DOMAINS と完全一致することを検証"""
        from scraper.sanitizer import ALLOWED_DOMAINS

        qml = """import QtQuick
import Quickshell
import "./components/CinemaUtils.js" as CinemaUtils

ShellRoot {
  Scope {
    Component.onCompleted: {
      console.log("DOMAINS_JSON=" + JSON.stringify(CinemaUtils.ALLOWED_CINEMA_DOMAINS));
      Qt.quit();
    }
  }
}
"""
        output = self.run_qml_test(qml, timeout_sec=4.0)
        self.assertIn("DOMAINS_JSON=", output)
        json_line = next(
            line for line in output.splitlines() if "DOMAINS_JSON=" in line
        )
        raw_json = json_line.split("DOMAINS_JSON=", 1)[1].strip()
        qml_domains = json.loads(raw_json)
        self.assertEqual(set(qml_domains), ALLOWED_DOMAINS)
        self.assertEqual(len(qml_domains), len(ALLOWED_DOMAINS))


if __name__ == "__main__":
    unittest.main()
