# YouTube API プラグイン (YouTube API Plugin)

関連ソースファイル
- [v3/plugins/youtube/youtube_api_plugin.py](https://github.com/mayu0326/test/blob/abdd8266/v3/plugins/youtube/youtube_api_plugin.py)
- [v2/plugins/youtube_api_plugin.py](https://github.com/mayu0326/test/blob/abdd8266/v2/plugins/youtube_api_plugin.py)
- [v3/docs/Guides/YOUTUBE_SETUP_GUIDE.md](https://github.com/mayu0326/test/blob/abdd8266/v3/docs/Guides/YOUTUBE_SETUP_GUIDE.md)

このページでは、`YouTubeAPIPlugin` クラスの実装詳細について説明します。これには、チャンネル ID の解決、動画詳細の取得、動画の分類ロジック、クォータ（利用枠）の管理、およびキャッシュシステムの仕組みが含まれます。

---

## システムにおける役割

`YouTubeAPIPlugin` は、YouTube Data API v3 と通信し、以下の 2 つの主な役割を担います。

1. **メタデータの補完**: 新着動画が検出された際、API から正確なタイトル、配信時刻、サムネイル URL を取得し、データベースに保存します。
2. **ライブ監視の補助**: `YouTubeLivePlugin` から呼び出され、配信が「開始」したか「終了」したかを判定するための最新状態を取得します。

バッチ処理によるクォータ節約の詳細は [API バッチ最適化](./API-Batch-Optimization.md) を参照してください。

---

## チャンネル ID の解決

YouTube では、チャンネルの指定方法が複数（`UC` で始まる ID、カスタムハンドル `@...`、以前のユーザー名など）ありますが、API 呼び出しには `UC...` 形式の ID が必要です。

- **自動解決**: `@` 等で始まる文字列が設定されている場合、初回起動時に API を使用して `UC` ID を取得します。
- **キャッシュ**: 一度解決された ID は `data/youtube_channel_cache.json` に保存され、次回以降は API 呼び出しなしで即座に特定されます。

---

## 動画分類ロジック

API から返される `liveBroadcastContent` や `liveStreamingDetails` の情報を元に、動画を以下のいずれかに分類します。

| 分類 (Type) | 意味 |
| :--- | :--- |
| `video` | 通常のアップロード動画 |
| `schedule` | 配信前のライブ予約枠 |
| `live` | 現在配信中のライブ |
| `completed` | 配信終了直後（アーカイブ化前）の状態 |
| `archive` | 配信終了後のアーカイブ動画 |

---

## クォータ（利用枠）管理

YouTube API には 1 日あたり 10,000 ユニットという制限があります。

- **コスト**: 通常の動画詳細取得は 1 ID でも 50 ID まとめても「1 ユニット」です。
- **追跡**: `daily_cost` をカウントし、上限に近づくとログで警告を出します。
- **過負荷防止**: 同じ動画への短時間の繰り返し問い合わせを避けるため、内部でキャッシュを持っています。

---

## キャッシュシステム (youtube_video_detail_cache.json)

動画の詳細情報は、最大 **7 日間** ローカルにキャッシュされます。
- **目的**: 頻繁なライブ状態チェック（Layer 3 ポーリング）において、API クォータを消費しすぎないようにするため。
- **有効期限**: 期限が切れたキャッシュは自動的に破棄され、API から最新情報が再取得されます。

---

## v2 と v3 の主な違い
- **分類の細分化**: v2 では 3 分類でしたが、v3 では `schedule` と `completed` が追加され 5 分類になりました。
- **403 エラー対応**: v3 では、クォータが完全に枯渇した場合に API へのリクエストを即座に停止するフラグが追加されました。
- **バッチ取得**: v3 から導入され、API 呼び出し効率が劇的に向上しました。