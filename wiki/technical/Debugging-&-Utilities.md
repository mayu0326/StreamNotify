# デバッグとユーティリティ (Debugging & Utilities)

関連ソースファイル
- [v2/thumbnails/niconico_ogp_backfill.py](https://github.com/mayu0326/test/blob/abdd8266/v2/thumbnails/niconico_ogp_backfill.py)
- [v2/thumbnails/youtube_thumb_backfill.py](https://github.com/mayu0326/test/blob/abdd8266/v2/thumbnails/youtube_thumb_backfill.py)
- [v3/thumbnails/niconico_ogp_backfill.py](https://github.com/mayu0326/test/blob/abdd8266/v3/thumbnails/niconico_ogp_backfill.py)
- [v3/thumbnails/youtube_thumb_backfill.py](https://github.com/mayu0326/test/blob/abdd8266/v3/thumbnails/youtube_thumb_backfill.py)
- [v3/utils/DEBUGGING_UTILITIES.md](https://github.com/mayu0326/test/blob/abdd8266/v3/utils/DEBUGGING_UTILITIES.md)
- [v3/utils/database/reset_post_flag.py](https://github.com/mayu0326/test/blob/abdd8266/v3/utils/database/reset_post_flag.py)

このページでは、StreamNotify v3 に同梱されているデバッグおよびユーティリティスクリプトについて説明します。これらのツールは、データベース、API キャッシュ、および動画分類状態のオフラインでの検査、修復、および分析をサポートします。これらはアプリケーションの通常の実行プロセスには含まれず、**アプリケーションを停止した状態で個別に実行する**ことを目的としたスタンドアロン・スクリプトです。

各種スクリプトの詳細については、以下を参照してください。

- [データベースとキャッシュのユーティリティ](./Database-&-Cache-Utilities.md) — `database/` および `cache/` サブディレクトリ内のスクリプト
- [サムネイル取得ツール](./Thumbnail-Backfill-Tools.md) — `niconico_ogp_backfill.py` および `youtube_thumb_backfill.py`

---

## ディレクトリ構造

すべてのユーティリティスクリプトは `v3/utils/` 下にあり、機能ごとに 4 つのサブディレクトリに整理されています。

```
v3/utils/
├── database/          # DB の検査と修復
├── cache/             # API キャッシュの管理
├── classification/    # 動画分類の監査と更新
└── analysis/          # API クォータや環境の検証
```

---

## 安全に関する一般的なガイドライン

`v3/utils/` 内のすべてのスクリプトに共通する前提条件です。これらに違反すると、データベースの破損やデータの損失を招く可能性があります。

| 規則 | 理由 |
| :--- | :--- |
| **アプリ起動中に実行しない** | SQLite は一度に 1 つの書き込みしか許可しません。アプリ起動中は接続が保持されているため、スクリプト側でエラーが発生したり、ロック競合が起きたりします。 |
| **実行前に DB をバックアップする** | フラグのリセットや分類の適用などのスクリプトは、元に戻せない更新処理を行います。 |
| **settings.env を確認する** | YouTube API を呼び出すスクリプトは、`YOUTUBE_API_KEY` が設定されている必要があります。 |
| **クォータを確認する** | API を叩くスクリプトはクォータ（割当）を消費します。事前に `calculate_api_quota.py` でコストを見積もることを推奨します。 |

---

## サブカテゴリ別の役割

### 1. `database/` — DB の検査と修復
`v3/data/video_list.db` を直接読み書きします。
- `reset_post_flag.py`: 指定した動画の「投稿済み」フラグをリセットします。
- `restore_db_from_backup.py`: バックアップファイルから DB を復元します。
- その他、読込専用の各種検査スクリプトが含まれます。

### 2. `cache/` — YouTube API キャッシュ管理
`v3/data/youtube_video_detail_cache.json` を管理します。
- `build_video_cache.py`: DB 内の全動画情報を一括取得してキャッシュを構築します。
- `check_cache_file.py`: キャッシュの有効性や件数を確認します。

### 3. `classification/` — 動画分類の監査
YouTube 動画の種別（ライブ、アーカイブ、予約枠など）の分類状態を調整します。
- 分類ロジックを変更した後に、既存の DB レコードを一括で再分類する場合などに使用します。

### 4. `analysis/` — API と環境の検証
設定ファイルの整合性や、YouTube API の挙動を個別調査するためのツール群です。
- `calculate_api_quota.py`: 現在の DB 規模から、API ユニットの消費予測を算出します。
- `inspect_video_api_response.py`: 特定の動画に対する生のリクエスト結果を出力します。

---

## サムネイル取得ツール (Thumbnail Backfill)
`v3/thumbnails/` ディレクトリにあり、既存の動画レコードに対して遡及的にサムネイルを取得します。
- `niconico_ogp_backfill.py`: ニコニコ動画の OGP 画像を取得。
- `youtube_thumb_backfill.py`: YouTube の動画サムネイルを最適解像度で取得。

これらのスクリプトはデフォルトで **テスト実行（Dry-run）** となっており、実際に書き込むには `--execute` オプションが必要です。