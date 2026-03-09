# ロギングシステム (Logging System)

関連ソースファイル
- [v3/logging_config.py](https://github.com/mayu0326/test/blob/abdd8266/v3/logging_config.py)
- [v3/plugins/logging_plugin.py](https://github.com/mayu0326/test/blob/abdd8266/v3/plugins/logging_plugin.py)

StreamNotify のロギングシステムは、標準の `logging` ライブラリをベースに、プラグイン形式で高度に構成されています。複数のログチャネルを持ち、サービスごとに独立したログファイルへの書き出し、日次のローテーション、および環境変数による詳細な制御が可能です。

---

## 概要

ロギングは `LoggingPlugin` として実装されています。このプラグインは通知を送るのではなく、アプリ起動時にロギングシステム全体の設定を担当します。

**初期化フロー:**
1. アプリ起動時に `setup_logging()` が呼ばれる。
2. `LoggingPlugin` が存在すれば、その `configure_logging()` を実行。
3. プラグインがない場合は、最小限のフォールバック設定 (`logging_config.py`) を適用。

---

## ログファイルと役割

ログは `logs/` ディレクトリ配下に出力されます。用途に応じて以下のチャネルに分かれています。

| ログファイル | チャネル名 | 内容 |
| :--- | :--- | :--- |
| `app.log` | `AppLogger` | アプリケーション全体の標準的な動作ログ (DEBUG/INFOのみ) |
| `error.log` | `AppLogger` | アポートや致命的なエラー (WARNING以上) |
| `audit.log` | `AuditLogger` | 設定変更や重要な操作の監査ログ |
| `post.log` | `PostLogger` | 投稿処理の成功・失敗の記録 |
| `youtube.log` | `YouTubeLogger` | YouTube RSS/WebSub などの通信ログ |
| `niconico.log` | `NiconicoLogger` | ニコニコ動画関連の動作ログ |
| `gui.log` | `GUILogger` | GUI 上でのボタンクリック等のイベント |

---

## ログハンドラの特長 (FlushTimedRotatingFileHandler)

StreamNotify では独自のログハンドラを使用しています。
- **即時フラッシュ**: ログが出力されるたびにファイルをフラッシュし、アプリが急に終了しても最新のログが記録されるようにします。
- **日次ローテーション**: 1 日ごとに新しいファイルに切り替わり、古いログには日付が付与されます (例: `app.log.2026-02-25`)。
- **OS 非依存**: 改行コードを LF (`\n`) に固定して書き込みます。

---

## 環境変数 (settings.env)

設定画面または `settings.env` から以下の制御が可能です。

| 変数名 | デフォルト | 内容 |
| :--- | :--- | :--- |
| `DEBUG_MODE` | `false` | `true` にすると、すべてのログレベルが DEBUG になり詳細に出力されます。 |
| `LOG_LEVEL_FILE` | `DEBUG` | ファイルへの基本書き出しレベル。 |
| `LOG_RETENTION_DAYS` | 14 | 古いログファイルを何日分保持するか。 |

---

## デバッグモード (DEBUG_MODE) の挙動

`DEBUG_MODE=true` を設定すると、以下のようになります：
- 通常はログに出ない詳細な通信内容や内部処理のステップが `app.log` や各サービスログに記録されます。
- `error.log` は引き続き WARNING 以上のみを保持し、エラー情報の視認性を維持します。

---

## ログの保存先
すべてのログは `logs/` フォルダ（アプリの実行ディレクトリ直下）に保存されます。このフォルダがない場合は自動的に作成されます。