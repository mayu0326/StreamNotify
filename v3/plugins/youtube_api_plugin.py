# -*- coding: utf-8 -*-
"""
YouTube Data API プラグイン（クォータ対応版）

- UC 以外のチャンネル識別子（ユーザー名/ハンドル）を API で解決・キャッシュ
- 動画詳細取得（ライブ/アーカイブ判定用メタデータ、バッチ対応）
- NotificationPlugin 準拠で DB へ保存
- APIコスト管理: 429対応・レート制限・コスト監視

クォータ仕様（YouTube Data API v3）
- 1日10,000ユニット
- forUsername/channels.list: 1ユニット
- search.list（ハンドル検索）: 100ユニット
- videos.list（詳細取得）: 1ユニット（最大50件/リクエスト）
"""
import os
import logging
import time
import json
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path
import requests

from plugin_interface import NotificationPlugin
from database import Database
from image_manager import get_youtube_thumbnail_url

logger = logging.getLogger("AppLogger")

API_BASE = "https://www.googleapis.com/youtube/v3"

# キャッシュファイルのパス（絶対パス対応）
_SCRIPT_DIR = Path(__file__).parent.parent  # v3/ ディレクトリ
CHANNEL_ID_CACHE_FILE = str(_SCRIPT_DIR / "data" / "youtube_channel_cache.json")
VIDEO_DETAIL_CACHE_FILE = str(_SCRIPT_DIR / "data" / "youtube_video_detail_cache.json")
CACHE_EXPIRY_DAYS = 7  # キャッシュの有効期限（日数）


class YouTubeAPIPlugin(NotificationPlugin):
    """YouTube Data API 連携プラグイン（クォータ対応）"""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return

        # 設定から読み込み（環境変数の前に config から読み込みを試みる）
        try:
            from config import get_config
            config = get_config("settings.env")
            self.api_key = config.youtube_api_key or os.getenv("YOUTUBE_API_KEY", "")
            self.channel_identifier = config.youtube_channel_id or os.getenv("YOUTUBE_CHANNEL_ID", "")
        except Exception:
            # フォールバック: 環境変数から直接読み込み
            self.api_key = os.getenv("YOUTUBE_API_KEY", "")
            self.channel_identifier = os.getenv("YOUTUBE_CHANNEL_ID", "")

        self.api_key = self.api_key.strip()
        self.channel_identifier = self.channel_identifier.strip()

        self.db = Database()
        self.channel_id: Optional[str] = None
        self.session = requests.Session()

        # APIコスト管理
        self.daily_quota = 10000
        self.daily_cost = 0
        self.last_request_time = 0
        self.request_interval = 0.5  # 秒（リクエスト間最小間隔）

        # ビデオ詳細キャッシュ
        self.video_detail_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_timestamps: Dict[str, float] = {}

        # キャッシュ読み込み
        self._load_channel_cache()
        self._load_video_detail_cache()

        # チャンネルID解決（キャッシュからまず確認）
        if self.api_key and self.channel_identifier:
            self.channel_id = self._resolve_channel_id(self.channel_identifier)
            if self.channel_id:
                # UC形式またはAPIで解決済み
                if self.channel_identifier.startswith("UC"):
                    logger.info(f"✅ YouTube API: UC形式IDのためAPIアクセスは不要です: {self.channel_id}")
                else:
                    logger.info(f"✅ YouTube API: チャンネルIDを解決しました: {self.channel_id}")
            else:
                logger.warning("⚠️ YouTube API: チャンネルIDの解決に失敗しました。UC形式のID、または有効な API キーを確認してください.")
        self._initialized = True

    def is_available(self) -> bool:
        return bool(self.api_key and self.channel_id)

    def get_name(self) -> str:
        return "YouTubeAPI 連携プラグイン"

    def get_version(self) -> str:
        return "0.2.0"

    def get_description(self) -> str:
        return "YouTube Data API でチャンネル解決と動画詳細取得を行うプラグイン（クォータ対応）"

    def post_video(self, video: Dict[str, Any]) -> bool:
        """動画情報を取得し、分類結果付きで DB に保存"""
        video_id = video.get("video_id") or video.get("id")
        if not video_id:
            logger.error("❌ YouTube API: video_id が指定されていません")
            return False

        # YouTube ID 形式の検証（Niconico など他形式のスキップ）
        if not self._is_valid_youtube_video_id(video_id):
            logger.debug(f"⏭️ YouTube API: YouTube 形式ではない video_id をスキップ: {video_id}")
            return True  # エラーではなく「対応不可」として True を返す

        details = self._fetch_video_detail(video_id)
        if not details:
            logger.error(f"❌ YouTube API: 動画詳細取得に失敗しました: {video_id}")
            return False

        content_type, live_status, is_premiere = self._classify_video(details)

        snippet = details.get("snippet", {})
        title = video.get("title") or snippet.get("title", "【新着動画】")
        channel_name = video.get("channel_name") or snippet.get("channelTitle", "")
        published_at = video.get("published_at") or snippet.get("publishedAt", "")
        video_url = video.get("video_url") or f"https://www.youtube.com/watch?v={video_id}"

        # サムネイル URL を取得（複数品質から最適なものを選択）
        thumbnail_url = get_youtube_thumbnail_url(video_id)
        if not thumbnail_url:
            # フォールバック: API から取得したもの
            thumbnail_url = snippet.get("thumbnails", {}).get("high", {}).get("url", "")

        return self.db.insert_video(
            video_id=video_id,
            title=title,
            video_url=video_url,
            published_at=published_at,
            channel_name=channel_name,
            thumbnail_url=thumbnail_url,
            content_type=content_type,
            live_status=live_status,
            is_premiere=is_premiere,
        )

    # --- キャッシュ機構 ---
    def _load_channel_cache(self) -> None:
        """チャンネルID解決結果をキャッシュから読み込み"""
        try:
            cache_path = Path(CHANNEL_ID_CACHE_FILE)
            if cache_path.exists():
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                    identifier_key = f"channel_identifier:{self.channel_identifier}"
                    if identifier_key in cache:
                        self.channel_id = cache[identifier_key]
                        logger.info(f"📦 チャンネルIDをキャッシュから読み込みました: {self.channel_id}")
        except Exception as e:
            logger.warning(f"⚠️ チャンネルキャッシュ読み込みエラー: {e}")

    def _save_channel_cache(self) -> None:
        """チャンネルID解決結果をキャッシュに保存"""
        try:
            cache_path = Path(CHANNEL_ID_CACHE_FILE)
            cache_path.parent.mkdir(exist_ok=True)

            cache = {}
            if cache_path.exists():
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)

            identifier_key = f"channel_identifier:{self.channel_identifier}"
            cache[identifier_key] = self.channel_id

            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)

            logger.info(f"💾 チャンネルIDをキャッシュに保存しました")
        except Exception as e:
            logger.error(f"❌ チャンネルキャッシュ保存エラー: {e}")

    # --- ビデオ詳細キャッシュ機構 ---
    def _load_video_detail_cache(self) -> None:
        """ビデオ詳細をキャッシュから読み込み"""
        try:
            cache_path = Path(VIDEO_DETAIL_CACHE_FILE)
            if cache_path.exists():
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                    # { video_id: { "data": {...}, "timestamp": 1234567890.0 } }
                    for video_id, entry in cache_data.items():
                        self.video_detail_cache[video_id] = entry.get("data", {})
                        self.cache_timestamps[video_id] = entry.get("timestamp", 0)

                logger.info(f"📦 ビデオ詳細キャッシュを読み込みました: {len(self.video_detail_cache)} 件")
        except Exception as e:
            logger.warning(f"⚠️ ビデオ詳細キャッシュ読み込みエラー: {e}")

    def _save_video_detail_cache(self) -> None:
        """ビデオ詳細キャッシュをファイルに保存"""
        try:
            cache_path = Path(VIDEO_DETAIL_CACHE_FILE)
            cache_path.parent.mkdir(exist_ok=True)

            cache_data = {}
            for video_id, details in self.video_detail_cache.items():
                cache_data[video_id] = {
                    "data": details,
                    "timestamp": self.cache_timestamps.get(video_id, time.time())
                }

            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

            logger.debug(f"💾 ビデオ詳細キャッシュを保存しました: {len(cache_data)} 件")
        except Exception as e:
            logger.error(f"❌ ビデオ詳細キャッシュ保存エラー: {e}")

    def _is_cache_valid(self, timestamp: float) -> bool:
        """キャッシュの有効性を確認（有効期限チェック）"""
        expiry_seconds = CACHE_EXPIRY_DAYS * 24 * 60 * 60
        return (time.time() - timestamp) < expiry_seconds

    def _get_cached_video_detail(self, video_id: str) -> Optional[Dict[str, Any]]:
        """キャッシュからビデオ詳細を取得（有効期限チェック付き）"""
        if video_id in self.video_detail_cache:
            timestamp = self.cache_timestamps.get(video_id, 0)
            if self._is_cache_valid(timestamp):
                logger.debug(f"📦 キャッシュから取得: {video_id}")
                return self.video_detail_cache[video_id]
            else:
                # 期限切れなので削除
                logger.debug(f"🗑️ キャッシュが期限切れ: {video_id}")
                del self.video_detail_cache[video_id]
                del self.cache_timestamps[video_id]
        return None

    def _cache_video_detail(self, video_id: str, details: Dict[str, Any]) -> None:
        """ビデオ詳細をキャッシュに保存"""
        self.video_detail_cache[video_id] = details
        self.cache_timestamps[video_id] = time.time()

    def update_video_detail_cache(self, video_id: str, video_details: dict):
        """動画詳細キャッシュを更新"""
        self.video_detail_cache[video_id] = video_details
        self.cache_timestamps[video_id] = time.time()
        self._save_video_detail_cache()

    def clear_video_detail_cache(self) -> None:
        """ビデオ詳細キャッシュをクリア"""
        self.video_detail_cache.clear()
        self.cache_timestamps.clear()
        logger.info(f"✅ ビデオ詳細キャッシュをクリアしました")

    # --- レート制限・リクエスト管理 ---
    def _throttle_request(self) -> None:
        """リクエスト間隔を制御（スロットリング）"""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.request_interval:
            sleep_time = self.request_interval - elapsed
            logger.debug(f"⏳ API レート制限: {sleep_time:.2f}秒待機")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def _check_quota(self, cost: int) -> bool:
        """コスト超過を事前チェック"""
        if self.daily_cost + cost > self.daily_quota:
            logger.error(f"❌ 日次クォータ超過予測: 現在 {self.daily_cost}/{self.daily_quota} ユニット使用済み。"
                         f"追加 {cost} ユニット必要ですが、超過します")
            return False
        return True

    def _record_cost(self, cost: int, operation: str) -> None:
        """APIコストを記録・ログ出力"""
        self.daily_cost += cost
        logger.info(f"💰 API コスト: {operation} = {cost}ユニット (累計: {self.daily_cost}/{self.daily_quota})")

        if self.daily_cost >= self.daily_quota * 0.8:
            logger.warning(f"⚠️ 日次クォータが 80% に到達しました。使用済み: {self.daily_cost}/{self.daily_quota}")

    # --- API通信（エラーハンドリング・バックオフ付き） ---
    def _get(self, path: str, params: Dict[str, Any], expected_cost: int, operation: str, max_retries: int = 3) -> Optional[Dict[str, Any]]:
        """
        API呼び出し（エクスポーネンシャルバックオフ対応）

        Args:
            path: エンドポイント
            params: クエリパラメータ
            expected_cost: 予想コスト（ユニット）
            operation: 操作名（ログ出力用）
            max_retries: リトライ上限

        Returns:
            JSONレスポンス、失敗時は None
        """
        if not self._check_quota(expected_cost):
            return None

        params_with_key = {**params, "key": self.api_key}
        url = f"{API_BASE}/{path}"

        for attempt in range(max_retries):
            try:
                self._throttle_request()

                logger.debug(f"🔌 API リクエスト開始: {operation} (試行 {attempt + 1}/{max_retries})")
                resp = self.session.get(url, params=params_with_key, timeout=15)

                # 429: Over Quota または Rate Limit
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    logger.warning(f"⏸️ 429 Rate Limit 受信: {retry_after}秒待機後リトライ")

                    if attempt < max_retries - 1:
                        time.sleep(retry_after)
                        continue
                    else:
                        logger.error(f"❌ {operation}: リトライ上限に達しました")
                        return None

                resp.raise_for_status()
                self._record_cost(expected_cost, operation)
                logger.debug(f"✅ API リクエスト成功: {operation}")
                return resp.json()

            except requests.exceptions.Timeout:
                logger.warning(f"⏱️ タイムアウト: {operation} (試行 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    backoff = 2 ** attempt  # 1, 2, 4秒
                    logger.info(f"⏳ {backoff}秒待機後リトライ...")
                    time.sleep(backoff)
                else:
                    logger.error(f"❌ {operation}: タイムアウトで最終失敗")
                    return None

            except requests.exceptions.RequestException as e:
                logger.error(f"❌ API エラー ({operation}): {e}")
                if attempt < max_retries - 1:
                    backoff = 2 ** attempt
                    logger.info(f"⏳ {backoff}秒待機後リトライ...")
                    time.sleep(backoff)
                else:
                    return None

        return None

    # --- チャンネルID解決 ---
    def _resolve_channel_id(self, identifier: str) -> Optional[str]:
        """
        UC以外のユーザー名/ハンドルを API で UCxx... に解決

        キャッシュ先読み後、forUsername APIで解決・キャッシュ保存
        （search.list は高コストのため未使用）
        """
        if identifier.startswith("UC"):
            return identifier

        # キャッシュから確認
        if self.channel_id:
            return self.channel_id

        logger.info(f"🔍 チャンネルID解決開始: {identifier}")

        # forUsername で解決（1ユニット）
        data = self._get(
            "channels",
            {"part": "id", "forUsername": identifier},
            expected_cost=1,
            operation=f"forUsername: {identifier}"
        )
        if data:
            items = data.get("items", [])
            if items:
                channel_id = items[0].get("id")
                if channel_id:
                    self.channel_id = channel_id
                    self._save_channel_cache()
                    return channel_id

        # forUsername で見つからない場合はエラー（search.list は使用しない）
        logger.error(f"❌ チャンネルID解決失敗: {identifier}（チャンネルIDが正しくありません）")
        return None

    # --- 動画詳細取得 ---
    def _fetch_video_detail(self, video_id: str) -> Optional[Dict[str, Any]]:
        """単一動画の詳細を取得（キャッシュ優先、1ユニット）"""
        # まずキャッシュを確認
        cached = self._get_cached_video_detail(video_id)
        if cached:
            return cached

        # キャッシュなし→API から取得
        data = self._get(
            "videos",
            {
                "part": "snippet,contentDetails,liveStreamingDetails,status",
                "id": video_id,
                "maxResults": 1,
            },
            expected_cost=1,
            operation=f"video detail: {video_id}"
        )
        items = data.get("items", []) if data else []
        if items:
            details = items[0]
            # キャッシュに保存
            self._cache_video_detail(video_id, details)
            return details

        return None

    def fetch_video_details_batch(self, video_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        最大50件の動画詳細をバッチ取得（キャッシュ優先、1ユニット）

        Args:
            video_ids: 動画IDのリスト（最大50件）

        Returns:
            {video_id: details} の辞書
        """
        if not video_ids:
            return {}

        results = {}
        to_fetch = []

        # キャッシュから取得可能な分を抽出
        for video_id in video_ids:
            cached = self._get_cached_video_detail(video_id)
            if cached:
                results[video_id] = cached
            else:
                to_fetch.append(video_id)

        if not to_fetch:
            logger.debug(f"📦 全動画がキャッシュから取得されました: {len(results)} 件")
            return results

        logger.debug(f"🔍 キャッシュ外の動画を API から取得: {len(to_fetch)} 件")

        # 50件ずつ分割してAPI取得
        for i in range(0, len(to_fetch), 50):
            batch = to_fetch[i:i+50]
            batch_str = ",".join(batch)

            data = self._get(
                "videos",
                {
                    "part": "snippet,contentDetails,liveStreamingDetails,status",
                    "id": batch_str,
                    "maxResults": 50,
                },
                expected_cost=1,
                operation=f"batch video details: {len(batch)} 件"
            )

            if data:
                for item in data.get("items", []):
                    video_id = item.get("id")
                    if video_id:
                        results[video_id] = item
                        # キャッシュに保存
                        self._cache_video_detail(video_id, item)

        return results

    # --- ID 検証 ---
    def _is_valid_youtube_video_id(self, video_id: str) -> bool:
        """
        YouTube 動画ID 形式の検証

        YouTube 動画ID は 11 文字の英数字（A-Z, a-z, 0-9, -, _）
        例: dQw4w9WgXcQ

        Niconico ID（sm45414087）など他形式は False を返す

        Args:
            video_id: 検証対象の ID

        Returns:
            True: YouTube 形式, False: 他の形式（Niconico など）
        """
        import re
        # YouTube 動画ID: 11 文字、A-Za-z0-9-_
        if re.match(r'^[A-Za-z0-9_-]{11}$', video_id):
            return True
        return False

    # --- 分類ロジック（コア・共通部分） ---
    @staticmethod
    def _classify_video_core(details: Dict[str, Any]) -> Tuple[str, Optional[str], bool]:
        """
        ★ System コメント 1-7 分類仕様 ★

        動画の種別と時間的状態を判別する共通コア実装
        YouTube API プラグイン・YouTube Live プラグイン両者から呼び出し

        【System 1】liveBroadcastContent の値による第一判定
        - "none"      → 通常動画（content_type="video"）
        - "live"      → ライブ配信関連
        - "upcoming"  → 予定配信
        - "completed" → 過去配信

        【System 2】liveStreamingDetails フィールドの検査順序
        - actualEndTime あり    → 配信終了（"archive", "completed"）
        - actualStartTime あり  → 配信中（"live", "live"）
        - scheduledStartTime あり → 予定中（"live", "upcoming"）

        【System 3】プレミア公開判定（is_premiere フラグ）
        - uploadStatus == "processed" かつ broadcast_type が "live" or "upcoming"
        - → プレミア配信である可能性

        【System 4】liveStreamingDetails 無し時の代替判定
        - broadcast_type を直接参照して判定

        【System 5】エッジケース
        - status.uploadStatus が "uploaded" → 未処理の状態
        - snippet フィールドが不完全 → デフォルト値で処理

        【System 6】戻り値の構造
        Returns: (content_type, live_status, is_premiere)
            - content_type: "video", "live", "archive" のいずれか
            - live_status: None (通常動画), "upcoming", "live", "completed"
            - is_premiere: bool (プレミア公開フラグ)

        【System 7】アーカイブ判定（追加ロジック）
        - 従来は actualEndTime で判定していたが、API が返さないケースがある
        - broadcast_type == "completed" の場合もアーカイブと判定
        - uploadStatus == "processed" かつ broadcast_type == "completed"
        - → 配信完了状態のライブ配信（ライブアーカイブ）

        Args:
            details: API の videos.list で取得した動画詳細辞書

        Returns:
            (content_type, live_status, is_premiere)
        """
        snippet = details.get("snippet", {})
        status = details.get("status", {})
        live = details.get("liveStreamingDetails", {})

        # System 1: liveBroadcastContent で補助判定
        broadcast_type = snippet.get("liveBroadcastContent", "none")

        # System 3: プレミア公開判定
        is_premiere = False
        if live:
            if status.get("uploadStatus") == "processed" and broadcast_type in ("live", "upcoming"):
                is_premiere = True

            # ★ 重要: broadcast_type が "none" でも liveStreamingDetails がある場合
            # System 2: ライブの時間的状態判定（タイムスタンプが最優先）
            if live.get("actualEndTime"):
                # 配信が終了している → アーカイブ
                return "archive", "completed", is_premiere
            elif live.get("actualStartTime"):
                # 配信が開始しているが終了していない → 配信中
                return "live", "live", is_premiere
            elif live.get("scheduledStartTime"):
                # 配信がスケジュール済み → 予定中
                return "live", "upcoming", is_premiere

        # System 4: liveStreamingDetails がない、または上記条件に当てはまらない場合
        # → broadcast_type で補助判定
        if broadcast_type == "live":
            return "live", "live", is_premiere
        elif broadcast_type == "upcoming":
            return "live", "upcoming", is_premiere
        elif broadcast_type == "completed":
            # System 7: completed ケース
            return "archive", "completed", is_premiere

        # System 5: デフォルト → 通常動画
        return "video", None, False

    def _classify_video(self, details: Dict[str, Any]) -> Tuple[str, Optional[str], bool]:
        """
        動画の種別と状態を判別（content_type, live_status, is_premiere）

        ⚠️ このメソッドは _classify_video_core() へ委譲（後方互換性のためラッパー保持）

        Returns:
            (content_type, live_status, is_premiere)
        """
        return self._classify_video_core(details)

    def on_enable(self) -> None:
        """プラグイン有効化時"""
        logger.info(f"   日次クォータ: {self.daily_quota} ユニット")

    def on_disable(self) -> None:
        """プラグイン無効化時"""
        logger.info(f"⛔ プラグイン無効化: {self.get_name()}")
        logger.info(f"   本日の API コスト: {self.daily_cost}/{self.daily_quota} ユニット")
        # 終了時にキャッシュを保存
        self._save_video_detail_cache()

    def poll_and_update_cache(self):
        """ポーリングごとにキャッシュを更新"""
        for video_id, video_details in self.video_detail_cache.items():
            # APIから最新情報を取得（仮の関数名: fetch_video_details）
            updated_details = self.fetch_video_details(video_id)
            if updated_details:
                self.update_video_detail_cache(video_id, updated_details)


def get_plugin():
    """PluginManager から取得するためのヘルパー"""
    return YouTubeAPIPlugin()
