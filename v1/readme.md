# Streamnotify on Bluesky (v1)

特定の YouTube チャンネルの新着動画を検知し、指定した Bluesky アカウントに自動投稿する常駐ボットです。

## 機能概要

- YouTube チャンネル 1 件の新着動画を RSS で監視
- 新着動画情報をローカル DB（SQLite）に保存
- 未投稿動画を Bluesky に自動投稿（テンプレート対応）
- 投稿履歴を CSV に記録

## 動作環境

- OS
  - Windows 10 以降
  - Debian/Ubuntu 系 Linux
- 必要ソフトウェア
  - Python 3.10 以上
- データベース
  - SQLite（標準ライブラリ `sqlite3` を使用）

## インストール

```
git clone <このリポジトリのURL>
cd <リポジトリディレクトリ>

# 仮想環境の作成（任意だが推奨）
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / WSL
source .venv/bin/activate

pip install -r requirements.txt
```

## 設定

1. `settings.env.example` をコピーして `settings.env` を作成します。

```
cp settings.env.example settings.env
```

2. `settings.env` を編集し、次の項目を設定します。

- `YOUTUBE_CHANNEL_ID`
  - 監視対象の YouTube チャンネル ID
- `BLUESKY_USERNAME`
  - Bluesky のハンドル（例: `yourname.bsky.social`）
- `BLUESKY_PASSWORD`
  - Bluesky のアプリパスワード
- `POLL_INTERVAL_MINUTES`
  - RSS をポーリングする間隔（5〜30 の整数、分単位）

> 注意: `settings.env` には個人の ID やパスワードを記載するため、公開リポジトリには含めないでください。

## 使い方

```
# 仮想環境を有効にした状態で
python main.py
```

- 起動中は `POLL_INTERVAL_MINUTES` ごとに YouTube RSS を取得し、新着動画を検知します。
- 新着動画は `data/youtube_notify.db` に保存されます。
- Bluesky への投稿履歴は `logs/post_history.csv` に追記されます。

停止する場合は、ターミナルで `Ctrl + C` を押してください。

## ディレクトリ構成

- `main_v1.py`
  - アプリケーションのエントリポイント
- `config.py`
  - 設定読み込み・バリデーション
- `database.py`
  - SQLite 操作（動画データの保存・取得）
- `youtube_rss.py`
  - YouTube RSS の取得・パース
- `bluesky_v1.py` / `bluesky_plugin.py`
  - Bluesky への投稿処理とテンプレート処理
- `data/`
  - SQLite DB ファイル（`youtube_notify.db`）
- `logs/`
  - 投稿履歴 CSV, ログファイル
- `docs/`
  - 設計メモ（例: `v1_design.md`）

## 制限事項（v1）

- 監視対象は 1 つの YouTube チャンネルのみ
- ライブ配信・アーカイブの判別は行わず、RSS に出てくる「動画」を一律で扱う。
- Twitch / ニコニコ連携、Discord 通知、GUI、Dockerは未対応です。

## ライセンス

**このリポジトリ全体は GPLv2 です。詳細はルートの LICENSE を参照してください。**

本アプリケーションは GPL License v2 で提供されます。

## 開発・貢献

- 作者: まゆにゃ（@mayu0326）
- Issue / PR 歓迎です。

将来的には、Twitch やニコニコ対応、Docker 対応、GUI などをプラグインとして追加していくことを想定しています。
```
