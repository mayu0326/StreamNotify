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

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from database import Database
from image_manager import get_youtube_thumbnail_url
from plugin_interface import NotificationPlugin

logger = logging.getLogger("AppLogger")

API_BASE = "https://www.googleapis.com/youtube/v3"
CHANNEL_ID_CACHE_FILE = "data/youtube_channel_cache.json"


class YouTubeAPIPlugin(NotificationPlugin):
    """YouTube Data API 連携プラグイン（クォータ対応）"""

    _instance = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self.api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        self.channel_identifier = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
        self.db = Database()
        self.channel_id: Optional[str] = None
        self.session = requests.Session()

        # APIコスト管理
        self.daily_quota = 10000
        self.daily_cost = 0
        self.last_request_time: float = 0.0
        self.request_interval = 0.5  # 秒（リクエスト間最小間隔）

        # キャッシュ読み込み
        self._load_channel_cache()

        # チャンネルID解決（キャッシュからまず確認）
        if self.api_key and self.channel_identifier:
            self.channel_id = self._resolve_channel_id(self.channel_identifier)
            if self.channel_id:
                # UC形式またはAPIで解決済み
                if self.channel_identifier.startswith("UC"):
                    logger.info(
                        f"✅ YouTube API: UC形式IDのためAPIアクセスは不要です: {self.channel_id}"
                    )
                else:
                    logger.info(
                        f"✅ YouTube API: チャンネルIDを解決しました: {self.channel_id}"
                    )
            else:
                logger.warning(
                    "⚠️ YouTube API: チャンネルIDの解決に失敗しました。UC形式のID、または有効な API キーを確認してください."
                )
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

        details = self._fetch_video_detail(video_id)
        if not details:
            logger.error(f"❌ YouTube API: 動画詳細取得に失敗しました: {video_id}")
            return False

        content_type, live_status, is_premiere = self._classify_video(details)

        snippet = details.get("snippet", {})
        title = video.get("title") or snippet.get("title", "【新着動画】")
        channel_name = video.get("channel_name") or snippet.get("channelTitle", "")
        published_at = video.get("published_at") or snippet.get("publishedAt", "")
        video_url = (
            video.get("video_url") or f"https://www.youtube.com/watch?v={video_id}"
        )

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
                        logger.info(
                            f"📦 チャンネルIDをキャッシュから読み込みました: {self.channel_id}"
                        )
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

            logger.info("💾 チャンネルIDをキャッシュに保存しました")
        except Exception as e:
            logger.error(f"❌ チャンネルキャッシュ保存エラー: {e}")

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
            logger.error(
                f"❌ 日次クォータ超過予測: 現在 {self.daily_cost}/{self.daily_quota} ユニット使用済み。"
                f"追加 {cost} ユニット必要ですが、超過します"
            )
            return False
        return True

    def _record_cost(self, cost: int, operation: str) -> None:
        """APIコストを記録・ログ出力"""
        self.daily_cost += cost
        logger.info(
            f"💰 API コスト: {operation} = {cost}ユニット (累計: {self.daily_cost}/{self.daily_quota})"
        )

        if self.daily_cost >= self.daily_quota * 0.8:
            logger.warning(
                f"⚠️ 日次クォータが 80% に到達しました。使用済み: {self.daily_cost}/{self.daily_quota}"
            )

    # --- API通信（エラーハンドリング・バックオフ付き） ---
    def _get(
        self,
        path: str,
        params: Dict[str, Any],
        expected_cost: int,
        operation: str,
        max_retries: int = 3,
    ) -> Optional[Dict[str, Any]]:
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

                logger.debug(
                    f"🔌 API リクエスト開始: {operation} (試行 {attempt + 1}/{max_retries})"
                )
                resp = self.session.get(url, params=params_with_key, timeout=15)

                # 429: Over Quota または Rate Limit
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    logger.warning(
                        f"⏸️ 429 Rate Limit 受信: {retry_after}秒待機後リトライ"
                    )

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
                logger.warning(
                    f"⏱️ タイムアウト: {operation} (試行 {attempt + 1}/{max_retries})"
                )
                if attempt < max_retries - 1:
                    backoff = 2**attempt  # 1, 2, 4秒
                    logger.info(f"⏳ {backoff}秒待機後リトライ...")
                    time.sleep(backoff)
                else:
                    logger.error(f"❌ {operation}: タイムアウトで最終失敗")
                    return None

            except requests.exceptions.RequestException as e:
                logger.error(f"❌ API エラー ({operation}): {e}")
                if attempt < max_retries - 1:
                    backoff = 2**attempt
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
            operation=f"forUsername: {identifier}",
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
        logger.error(
            f"❌ チャンネルID解決失敗: {identifier}（チャンネルIDが正しくありません）"
        )
        return None

    # --- 動画詳細取得 ---
    def _fetch_video_detail(self, video_id: str) -> Optional[Dict[str, Any]]:
        """単一動画の詳細を取得（1ユニット）"""
        data = self._get(
            "videos",
            {
                "part": "snippet,contentDetails,liveStreamingDetails,status",
                "id": video_id,
                "maxResults": 1,
            },
            expected_cost=1,
            operation=f"video detail: {video_id}",
        )
        items = data.get("items", []) if data else []
        return items[0] if items else None

    def fetch_video_details_batch(
        self, video_ids: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """
        最大50件の動画詳細をバッチ取得（1ユニット）

        Args:
            video_ids: 動画IDのリスト（最大50件）

        Returns:
            {video_id: details} の辞書
        """
        if not video_ids:
            return {}

        # 50件ずつ分割
        results = {}
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i: i + 50]
            batch_str = ",".join(batch)

            data = self._get(
                "videos",
                {
                    "part": "snippet,contentDetails,liveStreamingDetails,status",
                    "id": batch_str,
                    "maxResults": 50,
                },
                expected_cost=1,
                operation=f"batch video details: {len(batch)} 件",
            )

            if data:
                for item in data.get("items", []):
                    video_id = item.get("id")
                    results[video_id] = item

        return results

    # --- 分類ロジック ---
    def _classify_video(
        self, details: Dict[str, Any]
    ) -> Tuple[str, Optional[str], bool]:
        """
        動画の種別と状態を判別（content_type, live_status, is_premiere）

        Returns:
            (content_type, live_status, is_premiere)
            - content_type: "video", "live", "archive"
            - live_status: None, "upcoming", "live", "completed"
            - is_premiere: プレミア公開フラグ
        """
        snippet = details.get("snippet", {})
        status = details.get("status", {})
        live = details.get("liveStreamingDetails", {})

        # 1. snippet.liveBroadcastContent で第一判定
        broadcast_type = snippet.get("liveBroadcastContent", "none")

        if broadcast_type == "none":
            # 通常動画
            return "video", None, False

        # 2. ライブ/プレミア判定
        is_premiere = False

        if live:
            # プレミア公開判定
            if status.get("uploadStatus") == "processed" and broadcast_type in (
                "live",
                "upcoming",
            ):
                is_premiere = True

            # ライブの時間的状態判定
            if live.get("actualEndTime"):
                return "archive", "completed", is_premiere
            elif live.get("actualStartTime"):
                return "live", "live", is_premiere
            elif live.get("scheduledStartTime"):
                return "live", "upcoming", is_premiere

        # liveStreamingDetails がない場合は broadcast_type で判定
        if broadcast_type == "live":
            return "live", "live", is_premiere
        elif broadcast_type == "upcoming":
            return "live", "upcoming", is_premiere

        return "video", None, False

    def on_enable(self) -> None:
        """プラグイン有効化時"""
        logger.info(f"   日次クォータ: {self.daily_quota} ユニット")

    def on_disable(self) -> None:
        """プラグイン無効化時"""
        logger.info(f"⛔ プラグイン無効化: {self.get_name()}")
        logger.info(
            f"   本日の API コスト: {self.daily_cost}/{self.daily_quota} ユニット"
        )


def get_plugin():
    """PluginManager から取得するためのヘルパー"""
    return YouTubeAPIPlugin()
