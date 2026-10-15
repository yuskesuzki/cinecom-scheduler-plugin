# Cinecom Scheduler / Omarchy Plugin (シネコン上映スケジュールプラグイン)

An Omarchy bar widget and lightweight Python scraper for Cinema Complex schedules, screen facilities, and seat bookings across Japan (**Aeon Cinema** & **TOHO Cinemas**).

イオンシネマ（全国99劇場）および TOHOシネマズ（全国74劇場、計173劇場）の上映スケジュール、空席状況、スクリーン設備情報（IMAX / Dolby Atmos / 4DX / ScreenX 等）、座席予約購入リンクを表示する Omarchy デスクトップ向けバーウィジェットおよび Python CLI ツールです。外部依存ライブラリなし（Python 標準ライブラリのみ）で高速・軽量に動作します。

---

## 主な特徴

- **複数シネコン対応（Providerアーキテクチャ）**:
  - 🍿 **イオンシネマ**（全99劇場）: 残席数、アップグレードシート・設備情報、公式予約リンク
  - 🎬 **TOHOシネマズ**（全74劇場）: 空席ステータス（◎空席あり / △残少 / ✕満席）、TCX・轟音・IMAX設備、公式予約リンク
- **セレクトボックスによる系列切替**:
  - ドロップダウンUIから直感的にシネコン系列を切り替え可能。今後新たな系列が追加された場合もスムーズに拡張可能。
- **軽量 & 高速**: 外部ライブラリ不要（Python 3.9以上の標準ライブラリのみで動作）。
- **直近時間フィルター & 明日の上映確認**:
  - 今日: 現在時刻から指定時間以内（1h, 2h, 3h, 5h）に上映開始する作品を動的抽出
  - 明日: 明日の全上映作品一覧（`YYYY年MM月DD日(曜日)`）を表示
- **安全な設計**:
  - セキュリティサニタイザー（外部APIから受け取ったIDやURLの安全性を検証・エスケープ）を完備。
- **スクロールバー対応**:
  - 上映作品数が多くなった場合でも、スクロールバーのドラッグやホイールで快適に閲覧可能。

---

## ディレクトリ構成

```text
cinecom-scheduler-plugin/
├── BarWidget.qml              # Omarchy 用 UI ウィジェット (QML)
├── manifest.json              # Omarchy プラグイン定義
├── data/
│   └── theaters.json          # 全シネコン劇場マスタ定義 (イオンシネマ 99館 + TOHO 74館)
├── scraper/                   # バックエンド Python パッケージ
│   ├── __init__.py
│   ├── cli.py                 # 統合CLI (python3 -m scraper.cli)
│   ├── models.py              # 共通データモデル (ScheduleResponse, Movie, Screening 等)
│   ├── sanitizer.py           # 安全なURL検証・サニタイズ
│   └── providers/             # 各シネコン向け Provider
│       ├── __init__.py        # PROVIDER_REGISTRY
│       ├── base.py            # BaseCinemaProvider (基底クラス)
│       ├── aeon.py            # AeonCinemaProvider
│       └── toho.py            # TohoCinemaProvider
├── tests/                     # ユニットテスト (全10テスト完備)
│   └── test_scraper.py
└── pyproject.toml
```

---

## CLI の使い方

プラグインのバックエンドスクレイパーは、ターミナルから単体でも実行できます。

### 1. イオンシネマのスケジュール取得

```bash
# デフォルト (イオンシネマ 江別)
python3 -m scraper.cli --chain aeon --theater ebetsu

# 指定日付・コンパクトJSON出力
python3 -m scraper.cli --chain aeon --theater ebetsu --date 2026-10-16 --compact
```

### 2. TOHOシネマズのスケジュール取得

```bash
# TOHOシネマズ すすきの
python3 -m scraper.cli --chain toho --theater 089

# TOHOシネマズ 日比谷
python3 -m scraper.cli --chain toho --theater 081 --date 2026-10-16
```

---

## テストの実行

```bash
python3 -m unittest discover tests
```

---

## ライセンス

MIT License
