# StreamNotify on Bluesky (v2)

特定の YouTube チャンネルの新着動画を検知し、指定した Bluesky アカウントに自動投稿する常駐ボットです。

## 機能概要

- YouTube チャンネル 1 件の新着動画を RSS で監視
- 新着動画情報をローカル DB（SQLite, 拡張カラム対応）に保存
- Bluesky へ自動投稿（動画情報・URL リンク化・ドライラン対応）
- 投稿履歴をログファイルに記録（バニラ: app.log、プラグイン: post.log/post_error.log）
- GUI統合（Tkinterベース、動画選択・複数選択・一括削除・投稿・統計表示・プラグイン表示）
- プラグイン自動ロード（YouTube API・ロギング拡張対応）


> ℹ️ **GUI の動作**
> - GUI を最小化しても、バックグラウンドで動作を続けます。
> - GUI を完全に閉じる（ウィンドウのバツボタンをクリック）と、アプリケーションは終了します。

## 動作環境

- **OS**
  - Windows 10 以降
  - Debian/Ubuntu 系 Linux
- **必要ソフトウェア**
  - Python 3.10 以上
- **データベース**
  - SQLite（標準ライブラリ `sqlite3` を使用）

## インストール

```bash
git clone <このリポジトリのURL>
cd <リポジトリディレクトリ>

# 仮想環境の作成（任意だが推奨）
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / WSL
source venv/bin/activate

pip install -r requirements.txt
```

## 設定

1. `settings.env.example` をコピーして `settings.env` を作成します。

```bash
# Windows (PowerShell)
Copy-Item settings.env.example settings.env

# Linux / WSL
cp settings.env.example settings.env
```

2. `settings.env` を編集し、次の項目を設定します。
※下記は最低限設定が必要な項目です。他のオプションの説明は、
`settings.env` 内のコメントを参照してください。

**必須設定項目:**
- `YOUTUBE_CHANNEL_ID` - 監視対象チャンネル ID（UC から始まる ID）
- `BLUESKY_USERNAME` - Bluesky のハンドル名
- `BLUESKY_PASSWORD` - Bluesky のアプリパスワード
- `POLL_INTERVAL_MINUTES` - ポーリング間隔（分、最小値: 5、推奨: 10）

**主要なオプション設定項目:**

**バニラ状態（プラグイン未導入時）:**
- `BLUESKY_POST_ENABLED` - Bluesky への投稿を有効にするか（true/false、デフォルト: false）
- `APP_MODE` - 動作モード（normal / auto_post / dry_run / collect）
- `TIMEZONE` - タイムゾーン設定（例: Asia/Tokyo、デフォルト: system）
- `DEBUG_MODE` - デバッグモード（true/false、デフォルト: false）

**プラグイン導入時の主なオプション設定項目:**
- `YOUTUBE_API_KEY` - YouTube Data API キー（YouTube API プラグイン用、未設定可）
- `LOG_LEVEL_CONSOLE` - コンソール出力のログレベル（ロギング拡張プラグイン用）
- `LOG_LEVEL_FILE` - ファイル出力のログレベル（ロギング拡張プラグイン用）

**動作モードの詳細:**
- `normal`: 通常モード（RSS収集＋GUI手動投稿）
- `auto_post`: 自動投稿モード（RSS収集＋自動投稿）※BLUESKY_POST_ENABLED=trueも必要
- `dry_run`: ドライランモード（投稿機能がオフのテストモード）
- `collect`: 収集モード（RSS取得のみ・投稿機能オフ）

> ⚠️ **注意**: `settings.env` には個人の ID やパスワードを記載するため、
公開リポジトリには含めないでください。

### 基本的な起動方法

```bash
# 仮想環境を有効にした状態で
python main_v2.py
```

### 動作の流れ

- 起動中は `POLL_INTERVAL_MINUTES` ごとに YouTube RSS を取得し、新着動画を検知します。
- 新着動画は `data/video_list.db` に保存されます。
- **バニラ状態**: `BLUESKY_POST_ENABLED=true` かつ `APP_MODE=auto_post` で Bluesky へ自動投稿されます。
- **プラグイン導入時**: 自動投稿ロジックが拡張され、テンプレート・画像処理などが追加されます。
- Bluesky への投稿履歴ログ:
  - **バニラ状態**: `logs/app.log` に投稿結果を記録
  - **プラグイン導入時**: `logs/post.log` に投稿成功、`logs/post_error.log` にエラーを記録
- アプリケーションログは `logs/app.log` に記録されます。

> ℹ️ **GUI と動作について**
> - **最小化した場合**: バックグラウンドで動き続けます。タスクバーのアイコンをクリックで復帰できます。
> - **バツボタンで閉じた場合**: アプリケーション完全終了。再度起動する必要があります。

### 停止方法

停止する場合は、ターミナルで `Ctrl + C` を押してください。

## ディレクトリ構成

```
.
├── main_v2.py              # アプリケーションのエントリポイント
├── config.py               # 設定読み込み・バリデーション
├── database.py             # SQLite 操作
├── youtube_rss.py          # YouTube RSS 取得・パース
├── bluesky_v2.py           # Bluesky HTTP API 本体（ログイン・投稿・Facet構築）
├── gui_v2.py               # GUI フレーム統合（動画選択・投稿・統計表示）
├── image_manager.py        # 画像ダウンロード・保存・リトライ
├── logging_config.py       # ロギング統合設定
├── plugin_interface.py     # NotificationPlugin 抽象基底クラス
├── plugin_manager.py       # プラグイン自動検出・読み込み・管理
├── utils_v2.py             # ユーティリティ関数
├── settings.env.example    # 設定ファイルのサンプル
├── settings.env            # 設定ファイル（要作成、Git管理外）
├── requirements.txt        # Python パッケージ依存関係
│
├── plugins/                # プラグインディレクトリ

│
│   ├── youtube_api_plugin.py   # YouTube Data API 連携プラグイン
│   └── logging_plugin.py       # ロギング統合管理プラグイン
│
├── thumbnails/            # サムネイル・画像処理モジュール
│   ├── __init__.py             # Niconico OGP URL 取得
│   ├── image_re_fetch_module.py # サムネイル再ダウンロード・DB更新
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
│   ├── gui.log                 # GUI 操作ログ（プラグイン導入時）
│   ├── thumbnails.log          # サムネイル処理ログ（プラグイン導入時）
│   └── youtube.log             # YouTube 監視ログ（プラグイン導入時）
│
├── images/                 # 投稿用画像ディレクトリ（プラグイン導入時）
│   ├── default/
│   │   └── noimage.png         # デフォルト画像（画像未設定時）
│   └── YouTube/                # YouTube 動画サムネイル保存先
│
├── templates/              # 投稿テンプレート（プラグイン導入時）
│   └── youtube/
│       └── yt_new_video_template.txt    # 新着動画投稿用
│
├── Asset/                  # プラグイン用テンプレート・画像保管所
│   │                       # 全サービス・全プラグイン用テンプレート/画像を保管
│   │                       # プラグイン導入時に必要なファイルを本番ディレクトリに自動コピー
│   │                       # （asset_manager.py で実装完了: 2025-12）
│
├── docs/                   # 設計ドキュメント
│   ├── ARCHITECTURE_v2.md
│   ├── ModuleList_v2.md
│   ├── v2_design.md
│   └── ...
│
└── __pycache__/            # Python キャッシュ（Git 管理外）
```

## Assetディレクトリとテンプレート・画像管理

- `Asset/` ディレクトリに全サービス・全プラグイン用のテンプレート・画像を保管します。
- **起動時に自動配置**: アプリケーション起動時（`main_v2.py` 実行時）、プラグインが読み込まれるたびに必要なテンプレート・画像が `Asset/` から本番ディレクトリに自動コピーされます。
- **既存ファイル保護**: 既に存在するファイルは上書きされません（ユーザーの手動編集を保護）。
- **詳細な配置ログ**: ログ（`logs/app.log`）に配置されたファイル一覧が記録されます。

## プラグイン導入時の自動ファイル追加

### 動作例: YouTube API プラグイン導入時
1. YouTube API プラグイン読み込み時に以下が自動コピーされます：
   - `Asset/templates/youtube/yt_new_video_template.txt` → `templates/youtube/yt_new_video_template.txt`

2. 追加済みファイルはプラグイン削除後も残ります（手動削除が必要）

### 対応プラグイン別の配置内容

| プラグイン | テンプレート | 画像 |
|-----------|-----------|------|
| `youtube_api_plugin` | `youtube/` | `youtube/` |


### Asset ディレクトリ構成

```
Asset/
├── templates/
│   ├── default/          # デフォルト用テンプレート
│   └── youtube/          # YouTube 関連テンプレート
├── images/
│   └── default/          # デフォルト画像
└── README.md             # Asset ディレクトリの説明
```

## 制限事項

### RSS方式の制限
- YouTubeの仕様により、RSSで取得可能な動画は通常動画のみです。限定公開、非公開動画は含みません。
- 初回起動後の初回取得で取得されるのは、本アプリ導入以前に公開された通常動画最大15本です。
それ以上の過去動画の遡及取得はRSSでは取得出来ません。
- ライブ配信・アーカイブの判別は不可（YouTube API プラグイン で対応可能）

### プラグイン未導入時の制限

- 監視対象にできるチャンネルはYouTube限定、かつUCから始まるチャンネルIDのみです。
- ライブ配信・プレミア公開・ショート動画・アーカイブの判別ができません（YouTube API プラグイン で対応可能）
- 詳細なログ設定（複数ロガー管理）ができません（ロギング拡張プラグイン で対応可能）
- 投稿への画像添付ができません（v2.0.0 では非対応）

### その他の非対応サービス
- Twitch（TwitchAPI連携プラグイン対応予定）
- ニコニコ生放送（対応予定なし）

## ライセンス

本アプリケーションは **GPL License v2** で提供されます。

## 開発・貢献

- **作者**: まゆにゃ（@mayu0326）
- Issue / PR 歓迎です

## トラブルシューティング

### Python のバージョンが古い
Python 3.10 以上が必要です。`python --version` で確認してください。

### モジュールのインポートエラー
仮想環境が有効になっているか確認し、`pip install -r requirements.txt` を再実行してください。

### YouTube RSS が取得できない
- YouTubeのサーバーエラーが発生していないか確認してください。
- インターネット接続を確認してください。
- チャンネルIDがUCから始まっているか確認してください。
- YouTubeAPI連携プラグインを導入している場合、APIキーが正しいか確認してください。

### Bluesky に投稿できない
- `BLUESKY_POST_ENABLED=true` が設定されているか確認してください。
- `APP_MODE=auto_post` になっているか確認してください。
- ユーザー名とアプリパスワードが正しいか確認してください。
- Bluesky のアプリパスワードは、Web 版設定画面から生成する必要があります。

- テンプレートの構文エラーがないか、適切なパスにテンプレートを配置しているか確認してください。

### 投稿が実行されない
- `BLUESKY_POST_ENABLED=true` かつ `APP_MODE=auto_post` になっているか確認してください。
- ログファイル（`logs/app.log`）を確認して、エラーメッセージがないか確認してください。
- ドライランモード・収集モードでは投稿されません。動作モードを確認してください。

### タイムゾーンがおかしい
- `TIMEZONE` 設定を確認してください。
- 日本の場合は `TIMEZONE=Asia/Tokyo` を設定してください。
- `system` に設定すると、システムのタイムゾーンが使用されます。

## ログの見方

### ログファイルの場所
ログファイルは `logs/` ディレクトリに出力されます：

**バニラ状態（プラグイン未導入時）:**
- `logs/app.log` - アプリケーション全体のログ（起動、RSS取得、投稿試行など）
- `logs/error.log` - エラーのみを記録

**プラグイン導入時:**
- `logs/app.log` - アプリケーション全体のログ
- `logs/post.log` - Bluesky 投稿成功ログ
- `logs/post_error.log` - 投稿エラーログ
- `logs/youtube.log` - YouTube RSS 監視ログ
- `logs/gui.log` - GUI 操作ログ

### ログ確認のコツ
1. **最新のログを確認する**
   ```bash
   # Windows PowerShell
   Get-Content logs/app.log -Tail 50
   
   # Linux / WSL
   tail -50 logs/app.log
   ```

2. **エラーのみを表示**
   ```bash
   # Windows PowerShell
   Select-String "ERROR|CRITICAL" logs/app.log
   
   # Linux / WSL
   grep -E "ERROR|CRITICAL" logs/app.log
   ```

3. **特定の時刻のログを確認**
   ```bash
   # 例: 2025-12-13 のログのみ表示
   Select-String "2025-12-13" logs/app.log  # Windows
   grep "2025-12-13" logs/app.log           # Linux
   ```

## Issue の出し方

問題が解決しない場合は、GitHub の Issue で報告いただけます。以下の情報があると対応が速くなります：

### Issue 報告時に含めるべき情報

1. **実行環境**
   - OS（Windows 10/11、Ubuntu 20.04 など）
   - Python バージョン（`python --version`）
   - v2 のブランチ/コミット（`git log -1 --oneline`）

2. **設定情報（センシティブ情報は除外）**
   - 動作モード（`APP_MODE` の値）
   - プラグイン導入状況（導入済みプラグイン一覧）
   - `DEBUG_MODE` が有効か

3. **問題の説明**
   - 何をしようとしたか
   - 実際に何が起きたか
   - いつから問題が発生しているか

4. **ログファイル**
   - `logs/app.log` の関連部分（最後の 50～100 行が目安）
   - エラーが発生している場合は、エラーメッセージ全体
   - **個人情報（チャンネルID、ユーザー名など）は削除してください**

5. **再現手順**
   - 問題を再現するための具体的な手順
   - 例：「GUI で『投稿実行』をクリックしたら投稿されない」

### Issue 報告のテンプレート

```markdown
## 問題の説明
[簡潔に説明してください]

## 実行環境
- OS: [例: Windows 11]
- Python: [例: 3.10.5]
- 導入プラグイン: [例: YouTube API プラグイン、ロギングプラグイン]

## 動作モード
- APP_MODE: [例: auto_post]
- DEBUG_MODE: [有効/無効]

## 再現手順
1. ...
2. ...

## ログ出力
[logs/app.log の関連部分を貼り付け]

## 期待される動作
[本来はこうなるべきという動作]
```

### Issue 報告時の注意点
- ⚠️ ログに含まれる個人情報（チャンネルID、ユーザー名など）は削除してください
- 🔒 `settings.env` の内容は絶対に共有しないでください
- 📋 複数の問題がある場合は、Issue を分けて報告してください
- ✅ 既存の Issue に同じ問題がないか確認してから報告してください
