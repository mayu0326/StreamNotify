# StreamNotify - v3

YouTube チャンネルの新着動画を Bluesky に自動投稿するアプリケーションです。
（Twitch の対応はプラグインで拡張予定）

## 概要

- 特定の YouTube チャンネルの新着動画を RSS で監視し、Bluesky に自動投稿する常駐ボットです。
- 設定ファイルで簡単にカスタマイズでき、将来的にはプラグインで  
複数の配信プラットフォームに対応予定です。

## 主な機能

- **YouTube 監視 (RSS/WebSub)**: 指定チャンネルの新着動画を自動検出（リアルタイムプッシュ通知対応）
- **Bluesky 自動投稿**: 動画情報を指定フォーマットで Bluesky へ投稿（リッチテキスト・画像添付対応）
- **ローカル DB**: SQLite で動画情報・投稿状態を管理（重複投稿防止機能付き）
- **Tkinter GUI**: 動画一覧表示・手動投稿・統計表示に加え、  
**統合設定GUI**および**バックアップ機能**を搭載
- **プラグイン拡張**: ニコニコ / YouTube Live / ロギング拡張などに対応
- **テンプレートカスタマイズ**: Jinja2 テンプレートにより柔軟な投稿形式のカスタマイズが可能

---

## 🚀 クイックスタート

まずはバニラ状態（コア機能のみ）で試してみてください。慣れてきたらプラグインで拡張できます。

<details>
<summary>ここをクリックして詳細を表示</summary>

### 1. クローン＆セットアップ

```bash
git clone https://git.neco-server.net/mayuneco/Streamnotify_on_Bluesky
```

#### 仮想環境作成
```bash
python -m venv .venv
```

#### 仮想環境有効化
- **Windows**:
```bash
.venv/bin/activate
```
- **Linux/WSL**:
```bash
source venv/bin/activate
```

#### パッケージ インストール
```bash
pip install -r requirements.txt
```

### 2. 設定ファイルをコピーして編集

```bash
cp settings.env.example settings.env
```
#### テキストエディタで settings.env を開き、以下4つを設定(最小設定)：
```bash
# - YOUTUBE_CHANNEL_ID: YouTubeチャンネルID（UC から始まる）
# - BLUESKY_USERNAME: Blueskyハンドル（例: yourname.bsky.social）
# - BLUESKY_PASSWORD: Blueskyアプリパスワード（Web版設定から生成）
# - POLL_INTERVAL_MINUTES: 監視間隔（分、最小値5）
```

### 3. 起動

```bash
cd v3
python main_v3.py
```

GUI が起動し、YouTube RSS から新着動画を取得して表示します。
GUI から動画を選択して「投稿」ボタンを押すと Bluesky へ投稿されます。

> ℹ️ **GUI の動作**
> - GUI を最小化しても、バックグラウンドで動作を続けます。
> - GUI を完全に閉じる（ウィンドウのバツボタンをクリック）と、アプリケーションは終了します。

### 注意事項

- 初回起動時は、データベースの作成と接続確認のため、テストモードで起動します。  
テスト完了後、自動的にアプリが終了されますので、終了されるまでそのままお待ちください。
- 終了後、再度 `python main_v3.py` を実行すると、以降はそのまま使用できます。

</details>

---

## プロジェクト構成
- 本バージョンのフォルサ構成は以下の通りとなっています。
- 一部のファイル（dataディレクトリ内のファイル）及びフォルダ（data、logs、image、template）は、  
初回起動時に自動生成されます。

<details>
<summary>ここをクリックして詳細を表示</summary>

  ```
v3/
├── app_version.py          # バージョン情報管理
├── asset_manager.py        # アセット（テンプレート・画像）の自動配備・管理
├── backup_manager.py       # データベース・設定のバックアップ/復元
├── bluesky_core.py         # Bluesky HTTP API 本体（ログイン・投稿・Facet構築）
├── config.py               # 設定読み込み・バリデーション
├── config_sync.py          # 設定ファイルの自動同期・更新
├── database.py             # SQLite 操作＆DB正規化
├── deleted_video_cache.py   # 削除済み動画除外リスト管理
├── gui_v3.py               # GUI フレーム統合（動画選択・投稿・統計表示）
├── image_manager.py        # 画像ダウンロード・保存・リトライ
├── image_processor.py      # 画像リサイズ・最適化（Bluesky 推奨サイズ対応）
├── logging_config.py       # ロギング統合設定
├── main_v3.py              # アプリケーションのエントリポイント
├── plugin_interface.py     # NotificationPlugin 抽象基底クラス
├── plugin_manager.py       # プラグイン自動検出・読み込み・管理
├── production_server_api_client.py # 本番サーバー API クライアント（WebSub 対応）
├── requirements.txt        # Python パッケージ依存関係
├── settings.env            # 設定ファイル（要作成、Git管理外）
├── settings.env.example    # 設定ファイルのサンプル
├── template_editor_dialog.py # テンプレート編集用 GUI
├── template_utils.py       # Jinja2 テンプレート処理エンジン
├── unified_settings_window.py # 統合設定ウィンドウ（GUIで設定編集）
├── utils_v3.py             # 共通ユーティリティ関数
│
├── youtube_core/           # YouTube 関連コアモジュール
│   ├── youtube_rss.py          # YouTube RSS/WebSub 取得・パース
│   ├── youtube_video_classifier.py # 動画分類（通常/ショート/ライブ等）判定
│   ├── youtube_dedup_priority.py # 重複排除ロジック
│   ├── youtube_websub.py        # WebSub サポート
│   └── __init__.py
│
├── plugins/                # プラグインディレクトリ
│   ├── bluesky_plugin.py       # Bluesky 投稿プラグイン実装
│   ├── youtube/                # YouTube 関連プラグイン・モジュール
│   │   ├── youtube_api_plugin.py   # YouTube Data API 連携
│   │   ├── live_module.py          # YouTube ライブ/アーカイブ判定ロジック
│   │   └── live_scheduler.py       # ライブ監視スケジューラ
│   ├── niconico_plugin.py      # ニコニコ動画 RSS 監視プラグイン
│   └── logging_plugin.py       # ロギング統合管理プラグイン
│
│
├── thumbnails/            # サムネイル・画像処理モジュール
│   ├── __init__.py             # Niconico OGP URL 取得
│   ├── image_re_fetch_module.py # サムネイル再ダウンロード・DB更新
│   ├── niconico_ogp_utils.py   # Niconico OGP 取得ユーティリティ
│   ├── niconico_ogp_backfill.py # Niconico OGP バックフィル処理
│   ├── youtube_thumb_utils.py  # YouTube サムネイル取得ユーティリティ
│   └── youtube_thumb_backfill.py # YouTube サムネイルバックフィル処理
│
├── data/                   # データベース・キャッシュ
│   └── video_list.db           # SQLite データベース
│
├── logs/                   # ログファイル出力ディレクトリ
│   ├── app.log                 # アプリケーション一般ログ
│   ├── error.log               # エラーログ（バニラ）
│   ├── post.log                # Bluesky 投稿ログ（プラグイン導入時）
│   ├── post_error.log          # 投稿エラーログ（プラグイン導入時）
│   ├── audit.log               # 監査ログ（プラグイン導入時）
│   ├── gui.log                 # GUI 操作ログ（プラグイン導入時）
│   ├── thumbnails.log          # サムネイル処理ログ（プラグイン導入時）
│   ├── youtube.log             # YouTube 監視ログ（プラグイン導入時）
│   ├── niconico.log            # ニコニコ監視ログ（プラグイン導入時）
│   └── tunnel.log              # トンネル接続ログ（プラグイン導入時）
│
├── images/                 # 投稿用画像ディレクトリ（プラグイン導入時）
│   ├── default/
│   │   └── noimage.png         # デフォルト画像（画像未設定時）
│   ├── YouTube/                # YouTube 動画サムネイル保存先
│   └── Niconico/               # ニコニコ動画サムネイル保存先
│
├── templates/              # 投稿テンプレート
│   ├── youtube/
│   │   ├── yt_new_video_template.txt    # 新着動画投稿用
│   │   ├── yt_online_template.txt       # YouTube 配信開始用（プラグイン時）
│   │   └── yt_offline_template.txt      # YouTube 配信終了用（プラグイン時）
│   └── niconico/
│       └── nico_new_video_template.txt  # ニコニコ新着動画投稿用（プラグイン時）
│
├── Asset/                  # プラグイン用テンプレート・画像保管所
│   │                       # 全サービス・全プラグイン用テンプレート/画像を保管
│   │                       # プラグイン導入時に必要なファイルを本番ディレクトリに自動コピー
│
├── docs/                   # 設計ドキュメント
│   ├── Guides/                    # ユーザーガイド・使い方
│   │   ├── SETTINGS_OVERVIEW.md          # 設定項目一覧
│   │   ├── TEMPLATE_GUIDE.md             # テンプレートガイド
│   │   ├── GUI_USER_MANUAL.md            # GUI ユーザーマニュアル
│   │   └── ...                           # 各種セットアップガイド
│   ├── References/                # 参考資料
│   │   ├── FUTURE_ROADMAP_v3.md          # 将来ロードマップ
│   │   ├── ModuleList_v3.md              # 全モジュール一覧
│   │   ├── DEVELOPMENT_GUIDELINES.md     # 開発ガイドライン
│   │   └── INITIAL_CONCEPT.md            # 初期構想
│   ├── Technical/                 # 技術資料（アーキテクチャ・仕様）
│   │   ├── ARCHITECTURE_AND_DESIGN.md    # ★ メインドキュメント
│   │   ├── PLUGIN_SYSTEM.md              # プラグインシステム仕様
│   │   ├── TEMPLATE_SYSTEM.md            # テンプレートエンジン仕様
│   │   ├── DEBUG_DRY_RUN_GUIDE.md        # デバッグ・動作確認ガイド
│   │   ├── IMAGE_RESIZE_GUIDE.md         # 画像処理・リサイズ仕様
│   │   ├── YouTube/                      # YouTube 関連の詳細技術仕様
│   │   │   ├── YOUTUBE_API_CACHING_IMPLEMENTATION.md
│   │   │   └── ...
│   │   ├── VIDEO/                        # 動画管理に関連する技術仕様
│   │   │   └── DELETED_VIDEO_CACHE.md
│   │   └── ...
│
│
└── __pycache__/            # Python キャッシュ（Git 管理外）
```

</details>

---

## 必要な環境

- **OS**: Windows 10 以降、または Debian/Ubuntu 系 Linux
- **Python**: 3.13 以上
- **アカウント**: YouTube チャンネル、Bluesky アカウント

---

## 詳細なインストール

<details>
  <summary>ここをクリックして詳細を表示</summary>

### 1. リポジトリをクローン

```bash
git clone https://git.neco-server.net/mayuneco/Streamnotify_on_Bluesky
cd Streamnotify_on_Bluesky/v3
```

### 2. 仮想環境を作成（推奨）

```bash
python -m venv .venv
```

#### 仮想環境の有効化
- Windows

```bash
.venv\Scripts\activate
```

- Linux / WSL / macOS

```bash
source .venv/bin/activate
```

### 3. 依存パッケージをインストール

```bash
pip install -r requirements.txt
```

### 4. 設定ファイルを作成

```bash
cp settings.env.example settings.env
```

### 5. `settings.env` を編集して必須項目を設定

以下の 4 つの項目は必須です：

| 項目 | 説明 | 例 |
|-----|------|-----|
| `YOUTUBE_CHANNEL_ID` | 監視対象の YouTube チャンネル ID（UC から始まる） | `UCxxxxxxxxxxxxxxxx` |
| `BLUESKY_USERNAME` | Bluesky のハンドル名 | `yourname.bsky.social` |
| `BLUESKY_PASSWORD` | Bluesky のアプリパスワード | `xxxx-xxxx-xxxx-xxxx` |
| `POLL_INTERVAL_MINUTES` | ポーリング間隔（分、最小値 5） | `10` |

その他のオプション設定については、`settings.env` 内のコメント、または [Streamnotify v3 設定項目一覧](/v3/docs/Guides/SETTINGS_OVERVIEW.md) を参照してください。

</details>

---

## 使用方法

### アプリケーションの起動

```bash
cd v3
python main_v3.py
```

<details>
  <summary>ここをクリックして詳細を表示</summary>

### 基本的な動き

1. **RSS 取得**: `POLL_INTERVAL_MINUTES` ごとに YouTube RSS フィードを取得
2. **新着検出**: DB と比較して新着動画を検出
3. **DB 保存**: 新着動画をローカル DB に保存
4. **GUI 表示**: Tkinter GUI で動画一覧を表示
5. **手動投稿**: GUI から動画を選択して Bluesky に投稿
6. **ログ記録**: 投稿結果をログファイルに記録

### 動作の詳細

- 起動中は `POLL_INTERVAL_MINUTES` ごとに YouTube RSS を取得し、新着動画を検知します。
- 新着動画は `data/video_list.db` に保存されます。
- **バニラ状態**: `BLUESKY_POST_ENABLED=true` かつ `APP_MODE=auto_post` で Bluesky へ自動投稿されます。
- **プラグイン導入時**: 自動投稿ロジックが拡張され、テンプレート・画像処理などが追加されます。
- Bluesky への投稿履歴ログ:
  - **バニラ状態**: `logs/app.log` に投稿結果を記録
  - **プラグイン導入時**: `logs/post.log` に投稿成功、`logs/post_error.log` にエラーを記録
- アプリケーションログは `logs/app.log` に記録されます。

### 停止方法

- 停止する場合は、GUI ウィンドウのバツボタンで閉じるか、ターミナルで `Ctrl + C` を押してください。

### GUI の主な機能

- **動画一覧表示**: DB に保存されている動画を Treeview で表示
- **動画選択**: チェックボックスで投稿対象を選択
- **投稿実行**: 選択動画を Bluesky に投稿
- **ドライラン**: 投稿をシミュレート（実際には投稿しない）
- **プラグイン状態**: 導入済みプラグイン一覧を表示

</details>

---

## プラグインについて

<details>
  <summary>ここをクリックして詳細を表示</summary>

### バニラ状態（プラグイン未導入）

コア機能のみ動作：

- YouTube RSS 監視（通常動画のみ）
- Bluesky への投稿
- ローカル DB 管理
- 基本的なログ出力

### プラグイン導入時

以下のプラグインを導入することで機能を拡張できます：

| プラグイン | 機能 | 状態 |
|-----------|------|------|
| `youtube_live_plugin` | YouTube ライブ配信・アーカイブの判定 | ✅ 2.1.0 実装完了 (2025-12-18) |
| `niconico_plugin` | ニコニコ動画 RSS 監視 | ✅ 2.1.0 実装完了 (2025-12-18) |
| `youtube_api_plugin` | YouTube Data API 連携（詳細情報取得） | ✅ v3.2.0 実装完了 |
| `logging_plugin` | ロギング統合管理 | ✅ v3.2.0 実装完了 |


プラグイン導入時に必要なテンプレートファイルと画像は、`Asset/` ディレクトリから自動配置されます。

</details>

---

## Assetディレクトリとテンプレート・画像管理

- `Asset/` ディレクトリに全サービス・全プラグイン用のテンプレート・画像を保管します。
- **起動時に自動配置**: アプリケーション起動時（`main_v3.py` 実行時）、必要なテンプレート・画像が  \
 `Asset/` から本番ディレクトリに自動コピーされます。
- **既存ファイル保護**: 既に存在するファイルは上書きされません（ユーザーの手動編集を保護）。
- **詳細な配置ログ**: ログ（`logs/app.log`）に配置されたファイル一覧が記録されます。

### Asset ディレクトリ構成

<details>
  <summary>ここをクリックして詳細を表示</summary>

```
Asset/
├── templates/
│   ├── default/          # デフォルト用テンプレート
│   ├── youtube/          # YouTube 関連テンプレート
│   ├── niconico/         # ニコニコ関連テンプレート
│   └── twitch/           # Twitch 関連テンプレート（将来予定）
├── images/
│   └── default/          # デフォルト画像
└── README.md             # Asset ディレクトリの説明
```

</details>

---

## ドキュメント

詳細な情報は以下をご覧ください：

### 🔧 **Technical/** - 技術資料（開発者向け）
- [**アーキテクチャと設計方針**](/v3/docs/Technical/ARCHITECTURE_AND_DESIGN.md) - システム構成、プラグインアーキテクチャ、データベース設計
- [**プラグインシステム**](/v3/docs/Technical/PLUGIN_SYSTEM.md) - プラグイン開発方法、Rich Text Facet、画像処理
- [**テンプレートシステム**](/v3/docs/Technical/TEMPLATE_SYSTEM.md) - テンプレートファイルの仕様・使用方法
- [**除外動画リスト管理**](/v3/docs/Technical/VIDEO/DELETED_VIDEO_CACHE.md) - 削除済み動画の再送防止機能
- [**Rich Text Facet 仕様**](/v3/docs/Technical/RICHTEXT_FACET_SPECIFICATION.md) - URL・ハッシュタグリンク化の技術仕様
- [**AssetManager 統合ガイド**](/v3/docs/Technical/ASSET_MANAGER_INTEGRATION_v3.md) - Asset 自動配置・プラグイン連携
- [**YouTube API キャッシング**](/v3/docs/Technical/YouTube/YOUTUBE_API_CACHING_IMPLEMENTATION.md) - YouTube Data API 連携とキャッシュ仕様
- [**デバッグ・動作確認ガイド**](/v3/docs/Technical/DEBUG_DRY_RUN_GUIDE.md) - トラブルシューティング・デバッグ方法
- [**画像リサイズ仕様**](/v3/docs/Technical/IMAGE_RESIZE_GUIDE.md) - 画像処理・リサイズロジック
- [**設定ファイル同期仕様**](/v3/docs/Technical/Integrated/11_CONFIG_SYNC_SPEC.md) - 設定項目の自動マージ仕様
- [**サムネイル管理仕様**](/v3/docs/Technical/Integrated/12_THUMBNAIL_MANAGEMENT_SPEC.md) - バックフィル・再取得ロジック
- [**プラグイン実装詳細**](/v3/docs/Technical/Integrated/13_PLUGIN_IMPLEMENTATION_DETAILS.md) - Bluesky/Niconico 公開仕様
- [**一括投稿予約仕様**](/v3/docs/Technical/Integrated/14_BATCH_SCHEDULE_SPEC.md) - 予約キュー管理仕様

### 📖 **Guides/** - ユーザーガイド・使い方
- [**バージョン別機能比較ガイド**](/v3/docs/Guides/VERSION_COMPARISON_V3.md) - バージョンごとの機能差分・移行メリット
- [**v3.2.0 機能詳細ガイド**](/v3/docs/Guides/FEATURES_V3_2_0.md) - 設定GUI・一括予約・統計・API最適化
- [**WebSub 導入ガイド**](/v3/docs/Guides/WEBSUB_GUIDE.md) - リアルタイムプッシュ通知の導入
- [**v3.1.0 機能詳細ガイド**](/v3/docs/Guides/FEATURES_V3_1_0.md) - GUIフィルタ・検索・バックアップ機能
- [**v3.0.0 機能詳細ガイド**](/v3/docs/Guides/FEATURES_V3_0_0.md) - 基盤刷新・マルチテンプレート・重複排除
- [**設定項目一覧**](/v3/docs/Guides/SETTINGS_OVERVIEW.md) - 環境変数・設定項目の詳細
- [**テンプレート作成ガイド**](/v3/docs/Guides/TEMPLATE_GUIDE.md) - カスタムテンプレートの作り方
    - [テンプレート変数リファレンス](/v3/docs/Guides/TEMPLATE_VARIABLES.md)
    - [テンプレート記法ガイド](/v3/docs/Guides/TEMPLATE_NOTATION.md)
- [**アセットマネージャーガイド**](/v3/docs/Guides/ASSET_MANAGER_GUIDE.md) - テンプレート自動配備
- [**設定同期ガイド**](/v3/docs/Guides/CONFIG_SYNC_GUIDE.md) - 設定の自動更新と使い方
- [**サムネイル管理ガイド**](/v3/docs/Guides/THUMBNAIL_MANAGEMENT_GUIDE.md) - 画像トラブル時の解決法
- [**削除済みキャッシュガイド**](/v3/docs/Guides/DELETED_VIDEO_CACHE_GUIDE.md) - 二重投稿防止の仕組み

### 📑 **References/** - 参考資料
- [**将来ロードマップ**](/v3/docs/References/FUTURE_ROADMAP_v3.md) - v3+ の計画概要
- [**モジュール一覧**](/v3/docs/References/ModuleList_v3.md) - 全コンポーネントの説明
- [**開発ガイドライン**](v3/docs/References/DEVELOPMENT_GUIDELINES.md) - コーディング規約・設計思想
- [**初期構想案**](/v3/docs/References/INITIAL_CONCEPT.md) - YouTube新着動画appの初期構想

---

## 設定ファイルについて

設定は `settings.env` で管理されます。テキストエディタで直接編集してください。

**注意**: `settings.env` には個人の ID・パスワード・API キーを記載するため、Git による公開リポジトリには含めないでください（`.gitignore` で除外済み）。

設定編集後は、アプリケーションを再起動して反映させます。

---

## トラブルシューティング

### YouTube RSS が取得できない

- YouTube サーバーの状態を確認してください
- インターネット接続を確認してください
- チャンネル ID が `UC` で始まっているか確認してください

### Bluesky に投稿できない

- `settings.env` でユーザー名とアプリパスワードが正しいか確認してください
- Bluesky のアプリパスワードは Web 版の設定画面から生成する必要があります
- `logs/app.log` でエラーメッセージを確認してください

## ライセンス

このプロジェクトは **GPL License v2** で提供されます。詳細は [LICENSE](../../LICENSE) を参照してください。

---

## サポート

質問や問題がある場合は、GitHub の Issue セクションで報告してください。

---

**最終更新**: 2026-02-19
