# アーキテクチャ (Architecture)

関連ソースファイル
- [v1/docs/SETUP_GUIDE_v1.md](https://github.com/mayu0326/test/blob/abdd8266/v1/docs/SETUP_GUIDE_v1.md)
- [v2/CONTRIBUTING.md](https://github.com/mayu0326/test/blob/abdd8266/v2/CONTRIBUTING.md)
- [v2/docs/Technical/ARCHITECTURE_AND_DESIGN.md](https://github.com/mayu0326/test/blob/abdd8266/v2/docs/Technical/ARCHITECTURE_AND_DESIGN.md)
- [v3/docs/CONTRIBUTING.md](https://github.com/mayu0326/test/blob/abdd8266/v3/docs/CONTRIBUTING.md)
- [v3/docs/References/ModuleList_v3.md](https://github.com/mayu0326/test/blob/abdd8266/v3/docs/References/ModuleList_v3.md)
- [v3/docs/Technical/Archive/ARCHITECTURE_AND_DESIGN.md](https://github.com/mayu0326/test/blob/abdd8266/v3/docs/Technical/Archive/ARCHITECTURE_AND_DESIGN.md)
- [v3/readme_v3.md](https://github.com/mayu0326/test/blob/abdd8266/v3/readme_v3.md)
- [wiki/Getting-Started-Setup.md](https://github.com/mayu0326/test/blob/abdd8266/wiki/Getting-Started-Setup.md)

このページでは、StreamNotify v3 の「コア領域（Core）」と「拡張領域（Extensions）」に分かれた 2 階層アーキテクチャ、アプリケーションの起動シーケンス、および `main_v3.py` におけるメイン処理ループについて説明します。また、コアモジュール同士やプラグインレイヤーとの相互作用についても解説します。

個別のコンポーネントの詳細については、子ページである [コアモジュール](./Core-Modules.md)、[プラグインシステム](./Plugin-System.md)、[データベースと削除済み動画キャッシュ](./Database-&-Deleted-Video-Cache.md) を参照してください。YouTube ライブの 4 層検出アーキテクチャについては、[YouTube ライブ検出](./YouTube-Live-Detection.md) を参照してください。

---

## 設計原則: コア vs. 拡張

StreamNotify は機能を以下の 2 つの階層に分離しています。

| 階層 | 場所 | 主な責務 |
| :--- | :--- | :--- |
| **コア領域 (Core)** | `v3/*.py`<br>`v3/youtube_core/` | RSS 取得、SQLite ストレージ、Bluesky 投稿(基礎)、GUI、設定ロード |
| **拡張領域 (Extensions)** | `v3/plugins/` | YouTube Data API、ニコニコ動画 RSS、画像処理、ロギング管理 |

コア領域は、特定のプラグインがなくても独立して動作可能です。プラグインは `plugin_interface.py` で定義された `NotificationPlugin` 抽象インターフェースを実装し、起動時に `plugin_manager.py` によって発見、ロード、有効化されます。プラグインはコア機能を拡張しますが、コアの責務を肩代わりすることはありません。

情報源: [v3/docs/Technical/Archive/ARCHITECTURE_AND_DESIGN.md (L22-70)](https://github.com/mayu0326/test/blob/abdd8266/v3/docs/Technical/Archive/ARCHITECTURE_AND_DESIGN.md#L22-L70)

---

## コンポーネント・マップ

**図: トップレベルコンポーネントとソースファイル**

```mermaid
flowchart LR
    EP["main_v3.py"] --> CFG["config.py"]
    EP --> DB["database.py"]
    EP --> YT["youtube_core/"]
    EP --> PM["plugin_manager.py"]
    PM --> PL["plugins/"]
    EP --> BS["bluesky_core.py"]
    EP --> GUI["gui_v3.py"]
    EP --> AST["asset_manager.py"]
```

---

## 起動シーケンス (Startup Sequence)

`main_v3.py` は、メインのポーリングループに入る前に、固定された順序で初期化を実行します。

**図: main_v3.py 起動シーケンス**

```mermaid
sequenceDiagram
    participant M as "main_v3.py"
    participant C as "config.py"
    participant D as "database.py"
    participant V as "deleted_video_cache.py"
    participant Y as "video_classifier.py"
    participant P as "plugin_manager.py"
    participant B as "bluesky_core.py"
    participant G as "gui_v3.py"

    Note over M: 起動
    M->>C: get_config (設定ロード)
    M->>D: get_database (DB接続)
    M->>V: get_deleted_video_cache (キャッシュ読込)
    M->>Y: get_video_classifier (分類器初期化)
    M->>P: PluginManager 初期化
    M->>P: discover_plugins (プラグイン探索)
    M->>P: load & enable plugins (ロード・有効化)
    M->>B: BlueskyMinimalPoster (投稿機能準備)
    M->>G: StreamNotifyGUI (GUI起動)
    Note right of G: 別スレッドで実行
    Note over M: ポーリングループ開始
```

---

## 基本処理ループ (Main Polling Loop)

起動後、`main_v3.py` は設定された間隔 (`YOUTUBE_RSS_POLL_INTERVAL_MINUTES`) でポーリングを行います。各イテレーション（繰り返し）は以下の判定フローに従います。

**図: メインポーリング処理の流れ — RSS 取得から投稿まで**

```mermaid
flowchart TD
    START["ポーリング間隔経過"] --> FETCH["YouTubeRSS.fetch_feed<br>(RSS取得)"]
    FETCH --> NEW{新着動画あり?}
    NEW -- "いいえ" --> SLEEP["待機 (スリープ)"]
    NEW -- "はい" --> SAVE["save_to_db<br>(DB保存)"]
    SAVE --> DB_INS["sqlite3 挿入"]
    DB_INS --> MODE{APP_MODE<br>による分岐}
    MODE -- "collect" --> SLEEP
    MODE -- "dry_run" --> DRY["シミュレート投稿<br>(ログのみ出力)"]
    DRY --> SLEEP
    MODE -- "autopost" --> AUTO["安全確認後に自動投稿"]
    AUTO --> POST["プラグイン経由で投稿"]
    MODE -- "selfpost" --> SELF["手動選択待ち"]
    SELF --> POST
    POST --> DB_UPD["DB更新 (postedフラグ)"]
    DB_UPD --> SLEEP
```

---

## モジュールの責務

### コアモジュール (Core Modules)
| モジュール名 | クラス / エントリポイント | 主な責務 |
| :--- | :--- | :--- |
| `main_v3.py` | `main()` | アプリの入り口。起動シーケンスとポーリングループの所有。 |
| `config.py` | `get_config()` | `settings.env` の読み込みと全変数のバリデーション。 |
| `database.py` | `get_database()` | SQLite (`video_list.db`) への CRUD 操作と値の正規化。 |
| `deleted_video_cache.py` | `get_deleted_video_cache()` | 削除済み動画の再検出を防ぐための JSON キャッシュ管理。 |
| `youtube_core/youtube_rss.py` | `YouTubeRSS` | RSS の取得、時間変換 (UTC→JST)、重複除外。 |
| `youtube_core/youtube_video_classifier.py` | `YouTubeVideoClassifier` | 動画を種別 (コンテンツタイプ) やライブ状態に分類。 |
| `bluesky_core.py` | `BlueskyMinimalPoster` | AT Protocol のセッション管理、投稿 API 呼び出し。 |
| `asset_manager.py` | `get_asset_manager()` | デフォルトのテンプレートや画像を配置（上書きせず維持）。 |
| `plugin_manager.py` | `PluginManager` | プラグインの自動発見、ライフサイクル管理、呼び出し。 |

### 拡張プラグイン (Extension Plugins)
| プラグイン名 | クラス名 | 主な責務 |
| :--- | :--- | :--- |
| `bluesky_plugin.py` | `BlueskyImagePlugin` | テンプレート適用、画像縮小、投稿のルーティング。 |
| `youtube_api_plugin.py` | `YouTubeAPIPlugin` | YouTube Data API v3 通信、クォータ(制限)管理。 |
| `live_module.py` | `YouTubeLivePlugin` | ライブ配信状態の継続的な追跡。 |
| `niconico_plugin.py` | `NiconicoPlugin` | ニコニコ動画 RSS の取得と動画情報の抽出。 |

---

## プラグイン呼び出しパス (Plugin Dispatch Path)

動画の投稿が必要になると、`main_v3.py` や `gui_v3.py` は `PluginManager.post_video_with_all_enabled()` を呼び出します。このメソッドが有効な全プラグインに対して繰り返し処理を行います。

**図: PluginManager を通じた投稿のディスパッチ**

```mermaid
flowchart TD
    M["main_v3.py<br>または gui_v3.py"] --> PM["PluginManager<br>.post_video_with_all_enabled()"]
    PM --> BS_PL["BlueskyImagePlugin<br>.post_video()"]
    PM --> NI_PL["NiconicoPlugin<br>.post_video()"]
    
    BS_PL --> TEMP["template_utils.py<br>レンダリング"]
    BS_PL --> IMG["image_processor.py<br>リサイズ"]
    BS_PL --> BS_CORE["bluesky_core.py<br>createRecord API"]
    
    BS_CORE --> API["Bluesky API"]
```

---

## GUI とコア領域の相互作用

- `gui_v3.py` (`StreamNotifyGUI`) は、メインのポーリングループとは**別のスレッド**で動作します。DB やプラグインの参照を受け取りますが、ポーリングループ自体を制御することはありません。
- `unified_settings_window.py` は `settings.env` を直接編集します。変更を反映させるには、アプリケーションの再起動が必要です。
- `template_editor_dialog.py` は `template_utils.py` を呼び出し、リアルタイムな Jinja2 プレビューを実現しています。

---

## ディレクトリ構造の概要

```
v3/
├── main_v3.py                  # アプリの入り口、メインループ
├── config.py                   # 設定ローダー
├── database.py                 # SQLite アクセス
├── plugin_manager.py           # プラグインのライフサイクル管理
├── bluesky_core.py             # Bluesky 通信
├── template_utils.py           # テンプレートレンダリング
├── youtube_core/               # YouTube 専用処理
├── plugins/                    # 拡張プラグイン群
├── data/
│   ├── video_list.db           # データベース本体
│   └── deleted_videos.json     # 削除済みキャッシュ
├── templates/                  # 配信されたテンプレート(編集可能)
├── Asset/                      # 編集されないソースアセット
└── logs/                       # ログディレクトリ
```