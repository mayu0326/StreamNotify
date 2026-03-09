# Change Log

All notable changes to this project will be documented in this file.

## [v1.0.0] - 2025-12-15

### 初期リリース

#### 概要
- Streamnotify on Bluesky の最初のバージョンをリリースしました。
- YouTube チャンネルの新着動画を Bluesky に自動投稿する基本機能を提供。

#### 主な機能

**YouTube RSS フィード取得**
- 指定した YouTube チャンネルの新着動画を定期的に取得。
- 動画タイトル、URL、公開日時を取得可能。

**Bluesky 投稿機能**
- YouTube の新着動画情報を Bluesky に投稿。
- 投稿内容は固定フォーマットで構成。

**ログ機能**
- 投稿履歴をローカルに記録。
- エラー発生時のデバッグ情報を出力。

#### 注意事項
- 本バージョンは基本機能のみを提供しており、拡張性は限定的です。
- プラグインアーキテクチャは次期バージョンで導入予定です。
