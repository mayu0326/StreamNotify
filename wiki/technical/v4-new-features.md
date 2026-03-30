# StreamNotify v4：v3 から増えた機能

このページは、StreamNotify v3 から v4 で追加された主な機能を「何ができるか／どう使うか」の観点でまとめます。

---

## 関連ソースファイル

- 起動・フォールバック：`v4/main_v4.py`
- センターAPIクライアント：`v4/core/websub_client.py`
- Webhook受信：`v4/core/webhook_server.py`
- センター同期とGUIアダプタ：`v4/gui/adapter.py`
- Twitch Event（センター経由）：`v4/domain/notifications/twitch/client.py`
- GUIボタン：`v4/gui/components/toolbar.py`, `v4/gui/app.py`
- 設定UIの無効化条件：`v4/gui/views/settings_view.py`
- 投稿関連の設定項目例：`v4/settings.env.example`

---

## 1. センター経由の「YouTube WebSub」運用（websub モード）

v4 では `YOUTUBE_FEED_MODE` を `websub` にすると、YouTube 側の通知はセンター経由で処理されます。

- 起動時にセンター疎通・リース（購読期限）・登録状態を確認します
- センターへ到達できない場合は RSS ワーカーへフォールバックします

関連コード/挙動の根拠：

- `YOUTUBE_FEED_MODE=websub` の分岐とフォールバック：`v4/main_v4.py`
- リース確認/登録：`v4/core/websub_client.py`（`ensure_lease_and_register_if_needed()`）
- フォールバック中のUI制御：`v4/main_v4.py` および `v4/gui/app.py`

---

## 2. ローカル Webhook サーバ（センター→クライアント通知）

v4 はバックグラウンドで Webhook サーバを起動し、センターからの通知を受け取ってローカル DB を更新します。

- エンドポイント：`POST /webhook`
- 受信時：署名ヘッダー（`X-Hub-Signature`）の検証を行う（設定値が空の場合は挙動要確認）
- 受信イベント種別に応じて
  - 動画更新系（`video_update`, `youtube_video`, `new_video`）→ `save_video_update` で DB 更新
  - Twitch イベント系（`twitch_event`, `twitch_notification`）→ Twitch ハンドラへ振り分け

関連コード/挙動の根拠：

- Webhookサーバ：`v4/core/webhook_server.py`

---

## 3. Twitch EventSub（センター経由）対応

`YOUTUBE_FEED_MODE=websub` かつフォールバックでない場合、起動時にセンターへ依頼して Twitch の購読状態を整えます。

- `TwitchClient.ensure_eventsub()` を起動時に実行
- WebSub 再接続でフォールバックを解除した場合にも、再度 ensure を実行します

関連コード/挙動の根拠：

- Twitch ensure 起動：`v4/main_v4.py`
- 再接続後の再実行：`v4/gui/adapter.py`（`retry_websub_and_lift_fallback()`）
- 実処理：`v4/domain/notifications/twitch/client.py`

---

## 4. フォールバック復帰（WebSub 再接続ボタン）

センターへ到達できない場合、v4 は RSS フォールバックに切り替えます。このとき UI は次のように切り替わります。

- `YOUTUBE_FEED_MODE=websub` を選んでいても、フォールバック中は RSS 系ボタンが表示される
- フォールバック中は WebSub 再接続ボタン（`🔌 WebSubに再接続`）が表示される

ユーザー操作：

1. `🔌 WebSubに再接続` を押す
2. 成功するとセンター機能が再有効化され、必要に応じて再同期/再確保が行われます

関連コード/挙動の根拠：

- フォールバック/ボタン表示：`v4/main_v4.py`, `v4/gui/components/toolbar.py`, `v4/gui/app.py`
- フォールバック解除と再確保：`v4/gui/adapter.py`

---

## 5. GUIからの「センター同期」を Refresh に統合

v4 の `🔄 再読込` は、センターモード時にローカルへデータ同期を行います。

- `YOUTUBE_FEED_MODE=websub` のときだけ `sync_with_server()` が走る
- YouTube と Twitch の差分（`since` 相当）をセンターから取得し、ローカル DB（`client_v4.db`）へ upsert

関連コード/挙動の根拠：

- Refresh呼び出し：`v4/gui/app.py`（`refresh_data()`）
- センター同期：`v4/gui/adapter.py`（`sync_with_server()`）
- DB upsert：`v4/core/database.py`

---

## 6. ニコニコ動画 worker（設定がある場合のみ）

`NICONICO_USER_ID` が設定されていると、ニコニコ動画の収集ワーカー（バックグラウンド）が起動します。

関連コード/挙動の根拠：

- ニコニコ worker 起動：`v4/main_v4.py`

---

## 7. GUI機能の強化（投稿運用の導線）

v4 のツールバーには、v3 から強化された運用導線として次が含まれます。

- テンプレート編集：`📝 テンプレート`（種類の切替と保存、プレビュー）
- 投稿予約（一括スケジュール）：`📅 一括スケジュール`
- 予約一覧の確認：`📅 投稿予定一覧`
- 投稿対象の画像割当：`🖼️ 画像設定`
- 投稿/削除の一括操作：`📤 投稿`, `🗑️ 一括削除`

関連コード/挙動の根拠：

- ボタン定義：`v4/gui/components/toolbar.py`
- テンプレート編集 UI：`v4/gui/views/template_editor_view.py`

---

## 8. 投稿（Bluesky）はアプリパスワード経路で動作する

本ページでは、リリース時点でドキュメント対象とする Bluesky 投稿は「アプリパスワード（`BLUESKY_USERNAME` / `BLUESKY_PASSWORD`）」経路のみを扱います。

運用上のポイント：

- `APP_MODE` により
  - `selfpost`: GUIで選択したものを手動投稿
  - `autopost`: 動作モードに応じて自動投稿（対象ステータス等は設定値に依存）
  - `dry_run`: 投稿を実行せずログ/確認のみにする
  - `collect`: 収集寄りの区分（設定で選んだときのみ。v3 のように DB 未作成時に自動で collect へ切り替わる処理は v4 にない）
  が切り替わります
- 重複投稿防止
  - `PREVENT_DUPLICATE_POSTS`
  - `YOUTUBE_DEDUP_ENABLED`

関連コード/挙動の根拠：

- 設定キー：`v4/settings.env.example`
- 起動時の worker/GUI/モード分岐：`v4/main_v4.py`

---

## 次に読むべきページ

- `wiki/technical/v4-overview-and-usage.md`（起動・設定・UI操作の全体）
- `wiki/technical/v3-v4-comparison.md`（v3 との比較）

