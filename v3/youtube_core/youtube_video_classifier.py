# -*- coding: utf-8 -*-

"""
YouTube API を使った動画種別分類モジュール

YouTube Data API を使用して、動画が通常動画またはプレミア公開かを判定する。
Live関連（スケジュール、放送中、放送終了、ライブアーカイブ）は除外。
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

logger = logging.getLogger("AppLogger")

# キャッシュファイルのパス
SCRIPT_DIR = Path(__file__).parent.parent  # v3/ ディレクトリ
VIDEO_DETAIL_CACHE_FILE = str(SCRIPT_DIR / "data" / "youtube_video_detail_cache.json")
CACHE_EXPIRY_DAYS = 7  # 通常動画のキャッシュ有効期限（日数）
CACHE_EXPIRY_LIVE_MINUTES = 60  # ★ 【新】Live関連動画のキャッシュ有効期限（分数）

# YouTube Data API エンドポイント
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
VIDEOS_API_ENDPOINT = f"{YOUTUBE_API_BASE_URL}/videos"

# API レスポンスから抽出する必須フィールド
VIDEOS_PART = "snippet,liveStreamingDetails,contentDetails"

# ビデオの種別定義（v3.2.0 仕様）
VIDEO_TYPE_NORMAL = "video"  # 通常動画
VIDEO_TYPE_PREMIERE = "premiere"  # プレミア公開
VIDEO_TYPE_LIVE = "live"  # ライブ配信中
VIDEO_TYPE_SCHEDULED = "schedule"  # ライブ予定/スケジュール
VIDEO_TYPE_COMPLETED = "completed"  # ライブ終了
VIDEO_TYPE_ARCHIVE = "archive"  # ライブアーカイブ
VIDEO_TYPE_UNKNOWN = "unknown"  # 判定不可


class YouTubeVideoClassifier:
    """YouTube Data API を使った動画種別分類"""

    def __init__(self, api_key: Optional[str] = None):
        """
        初期化

        Args:
            api_key: YouTube Data API キー（Noneの場合は環境変数から取得）
        """
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        if not self.api_key:
            logger.warning("[WARN] YOUTUBE_API_KEY が設定されていません")
        self.session = requests.Session()

        # キャッシュの初期化
        self.video_detail_cache: Dict[str, Dict[str, Any]] = {}
        self._load_cache()

    def classify_video(
        self, video_id: str, force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        動画 ID から動画の種別を判定

        キャッシュを先に確認し、有効期限内ならそれを使用。
        期限切れならば API で取得してキャッシュに保存。

        ★ 【修正 v3.2.0】キャッシング戦略を統一（クォータ削減）
        - 全ての動画（通常・Live関連）に統一したキャッシュ有効期限を適用
        - Live関連でも有効期限内ならキャッシュを再利用
        - 無条件な再取得を廃止し、クォータ消費を大幅削減

        Args:
            video_id: YouTube 動画 ID（11 文字のアルファベット・数字・ハイフン・アンダースコア）
            force_refresh: True の場合、キャッシュを無視して API から再取得

        Returns:
            分類結果を含む辞書：
            {
                "success": bool,                    # API 呼び出し成功フラグ
                "video_id": str,                    # 動画 ID
                "type": str,                        # 種別（video, premiere, live, schedule, completed, archive, unknown）
                "title": str,                       # 動画タイトル
                "description": str,                 # 動画説明
                "thumbnail_url": str,               # サムネイル URL
                "is_premiere": bool,                # プレミア公開フラグ
                "is_live": bool,                    # ライブ配信関連フラグ（スケジュール含む）
                "live_status": str or None,         # ライブステータス（upcoming, live, completed）
                "is_scheduled_start_time": bool,    # scheduledStartTime が設定されているか
                "published_at": str,                # 公開日時
                "error": str or None,               # エラーメッセージ（失敗時のみ）
            }
        """
        # ★ ステップ 1: キャッシュを確認（force_refresh が True でない場合のみ）
        # ★ 【修正 v3.2.0】Live 関連でも有効期限内ならキャッシュを再利用（クォータ削減）
        if not force_refresh and video_id in self.video_detail_cache:
            cache_entry = self._get_cache_entry(video_id)
            if cache_entry:
                # キャッシュが有効 → そのまま利用（Live関連含む）
                logger.debug(f"📦 キャッシュから動画詳細を取得: {video_id}")
                video_data = cache_entry
                classified = self._classify_from_response(
                    {"success": True, "video_id": video_id, "video_data": video_data}
                )
                return classified
            else:
                # キャッシュが期限切れ → メモリキャッシュから削除
                logger.debug(f"🔄 キャッシュ期限切れ（{video_id}）: 再取得します")
                del self.video_detail_cache[video_id]

        if not self.api_key:
            return {
                "success": False,
                "video_id": video_id,
                "type": VIDEO_TYPE_UNKNOWN,
                "error": "YouTube API キーが設定されていません",
            }

        try:
            result = self._call_videos_api(video_id)
            if not result["success"]:
                return result

            # API レスポンスから種別を判定
            classified = self._classify_from_response(result)

            # ★ ステップ 2: キャッシュに保存（全ての動画タイプを対象）
            # ★ 【修正 v3.2.0】Live関連動画もキャッシュに保存（クォータ削減）
            # キャッシュ有効期限（デフォルト 7 日）内なら、状態遷移中の Live 動画でも
            # キャッシュを再利用して API 呼び出しを削減。状態が頻繁に変わる場合は
            # force_refresh=True を指定して明示的に再取得すること
            if result.get("success") and "video_data" in result:
                self.video_detail_cache[video_id] = result["video_data"]
                self._save_cache()
                logger.debug(f"💾 動画詳細をキャッシュに保存: {video_id}")

            return classified

        except Exception as e:
            logger.error(f"[FAILURE] 動画分類エラー（{video_id}）: {e}")
            return {
                "success": False,
                "video_id": video_id,
                "type": VIDEO_TYPE_UNKNOWN,
                "error": str(e),
            }

    def _call_videos_api(self, video_id: str) -> Dict[str, Any]:
        """
        YouTube Data API の videos.list を呼び出し

        Args:
            video_id: YouTube 動画 ID

        Returns:
            API 呼び出し結果
        """
        params = {"part": VIDEOS_PART, "id": video_id, "key": self.api_key}

        try:
            response = self.session.get(VIDEOS_API_ENDPOINT, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if not data.get("items"):
                return {
                    "success": False,
                    "video_id": video_id,
                    "type": VIDEO_TYPE_UNKNOWN,
                    "error": f"動画が見つかりません（video_id: {video_id}）",
                }

            video_data = data["items"][0]
            return {"success": True, "video_id": video_id, "video_data": video_data}

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ YouTube API 呼び出しエラー（{video_id}）: {e}")
            return {
                "success": False,
                "video_id": video_id,
                "type": VIDEO_TYPE_UNKNOWN,
                "error": f"API 呼び出し失敗: {str(e)}",
            }

    def _classify_from_response(self, api_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        YouTube API レスポンスから動画種別を判定

        判定ロジック（優先度順）：
        1. liveStreamingDetails が存在 → Live関連（詳細は以下で判定）
           - upcomingStartTime 存在 → schedule（予約枠）
           - actualStartTime 存在かつ actualEndTime なし → live（配信中）
           - actualEndTime 存在 → completed（配信終了）
        2. contentDetails.videoDetails.isLiveContent=true → archive（ライブアーカイブ）
        3. status.uploadStatus != "processed" → 処理中（除外推奨）
        4. liveBroadcastContent が "premiere" → premiere（プレミア公開）
        5. 上記いずれでもない → video（通常動画）

        Args:
            api_result: _call_videos_api の成功結果

        Returns:
            分類結果
        """
        video_data = api_result.get("video_data", {})
        video_id = api_result.get("video_id", "")

        # 基本情報を抽出
        snippet = video_data.get("snippet", {})
        title = snippet.get("title", "Unknown")
        description = snippet.get("description", "")
        channel_name = snippet.get("channelTitle", "")  # ★ 【新】channel_name を追加
        thumbnails = snippet.get("thumbnails", {})
        thumbnail_url = thumbnails.get("high", {}).get("url") or thumbnails.get(
            "medium", {}
        ).get("url")
        published_at = snippet.get("publishedAt", "")

        # ★ 【新】メタデータ: duration と live_broadcast_content
        content_details = video_data.get("contentDetails", {})
        duration = content_details.get(
            "duration", "PT0S"
        )  # ISO 8601 形式（例: "PT54M40S"）
        live_broadcast_content = snippet.get(
            "liveBroadcastContent", "none"
        )  # "none" / "live" / "upcoming"

        live_details = video_data.get("liveStreamingDetails", {})

        # Live関連の判定
        video_type = VIDEO_TYPE_UNKNOWN
        live_status = None
        is_live = False
        is_premiere = False
        is_scheduled_start_time = False

        # ★ 【新】基準時刻の計算用変数
        scheduled_start_time = None
        actual_start_time = None
        actual_end_time = None
        representative_time_utc = None

        # 1. liveStreamingDetails が存在 → Live関連
        if live_details:
            is_live = True

            # ★ 【新】時刻情報を取得
            scheduled_start_time = live_details.get("scheduledStartTime")
            actual_start_time = live_details.get("actualStartTime")
            actual_end_time = live_details.get("actualEndTime")

            upcoming_start = scheduled_start_time
            actual_start = actual_start_time
            actual_end = actual_end_time

            if upcoming_start and not actual_start:
                # スケジュール済みだが未開始
                video_type = VIDEO_TYPE_SCHEDULED
                live_status = "upcoming"
                is_scheduled_start_time = True
                # ★ 【新】基準時刻：scheduledStartTime
                representative_time_utc = scheduled_start_time
            elif actual_start and not actual_end:
                # 配信中
                video_type = VIDEO_TYPE_LIVE
                live_status = "live"
                # ★ 【新】基準時刻：actualStartTime
                representative_time_utc = actual_start_time
            elif actual_end:
                # ★ 【重要】actualEndTime が存在 = 配信完全終了 = 常にアーカイブ
                # liveBroadcastContent の値は関係なく、actual_end が存在すればアーカイブ
                video_type = VIDEO_TYPE_ARCHIVE
                live_status = None  # アーカイブは live_status を持たない
                # ★ 【新】基準時刻：actualEndTime
                representative_time_utc = actual_end_time
                logger.debug(
                    f"[SUCCESS] アーカイブ判定: {video_id} (actualEndTime={actual_end})"
                )
            else:
                # 判定不可だが live_details が存在
                logger.warning(
                    f"⚠️ ライブステータス判定不可（{video_id}）: {live_details}"
                )
                video_type = VIDEO_TYPE_UNKNOWN

        # 2.  liveBroadcastContent が "premiere" → プレミア公開
        elif snippet.get("liveBroadcastContent") == "premiere":
            video_type = VIDEO_TYPE_PREMIERE
            is_premiere = True
            # ★ 【新】基準時刻：published_at（プレミアも通常動画と同じ）
            representative_time_utc = published_at

        # 3. 上記いずれでもない → 通常動画
        else:
            video_type = VIDEO_TYPE_NORMAL
            # ★ 【新】基準時刻：published_at
            representative_time_utc = published_at

        return {
            "success": True,
            "video_id": video_id,
            "type": video_type,
            "title": title,
            "description": description,
            "channel_name": channel_name,  # ★ 【新】channel_name を返却
            "thumbnail_url": thumbnail_url,
            "is_premiere": is_premiere,
            "is_live": is_live,
            "live_status": live_status,
            "is_scheduled_start_time": is_scheduled_start_time,
            "published_at": published_at,
            "duration": duration,  # ★ 【新】ISO 8601 形式
            "live_broadcast_content": live_broadcast_content,  # ★ 【新】"none"/"live"/"upcoming"
            # ★ 【新】時刻情報を返却
            "scheduled_start_time": scheduled_start_time,
            "actual_start_time": actual_start_time,
            "actual_end_time": actual_end_time,
            "representative_time_utc": representative_time_utc,
            "error": None,
        }

    def is_normal_or_premiere(self, video_id: str) -> bool:
        """
        動画が「通常動画またはプレミア公開」かどうかを判定（短縮判定）

        Live関連（スケジュール、配信中、配信終了、ライブアーカイブ）は False を返す。

        Args:
            video_id: YouTube 動画 ID

        Returns:
            bool: 通常動画またはプレミア公開の場合 True、そうでない場合 False
        """
        result = self.classify_video(video_id)
        if not result.get("success", False):
            logger.warning(f"⚠️ 動画判定失敗（{video_id}）: {result.get('error')}")
            return False

        video_type = result.get("type")
        return video_type in [VIDEO_TYPE_NORMAL, VIDEO_TYPE_PREMIERE]

    def is_live_related(self, video_id: str) -> bool:
        """
        動画が Live関連（スケジュール、配信中、配信終了、ライブアーカイブ）かどうかを判定

        Args:
            video_id: YouTube 動画 ID

        Returns:
            bool: Live関連の場合 True、通常動画またはプレミア公開の場合 False
        """
        result = self.classify_video(video_id)
        if not result.get("success", False):
            logger.warning(f"⚠️ 動画判定失敗（{video_id}）: {result.get('error')}")
            return False

        return result.get("is_live", False)

    def _load_cache(self) -> None:
        """キャッシュファイルからビデオ詳細キャッシュを読み込む"""
        cache_path = Path(VIDEO_DETAIL_CACHE_FILE)
        if not cache_path.exists():
            logger.debug(f"[INFO] キャッシュファイルが見つかりません: {cache_path}")
            return

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            # キャッシュを辞書に変換（video_id をキーにする）
            for video_id, cache_entry in cache_data.items():
                if isinstance(cache_entry, dict) and "data" in cache_entry:
                    self.video_detail_cache[video_id] = cache_entry["data"]

            logger.info(
                f"[SUCCESS] ビデオ詳細キャッシュを読み込みました: {len(self.video_detail_cache)}件"
            )

        except json.JSONDecodeError as e:
            logger.error(f"❌ キャッシュファイルの解析エラー: {e}")
        except Exception as e:
            logger.error(f"❌ キャッシュ読み込みエラー: {e}")

    def _get_cache_entry(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        ★ 【新】キャッシュエントリの有効期限をチェックして取得

        有効期限チェック：
        - Live関連動画（schedule, live, completed, archive）: 60分以内
        - その他（通常動画、プレミア）: CACHE_EXPIRY_DAYS 日以内

        Args:
            video_id: YouTube 動画 ID

        Returns:
            キャッシュ内のビデオデータ（有効な場合）、または None（期限切れ）
        """
        if video_id not in self.video_detail_cache:
            return None

        video_data = self.video_detail_cache[video_id]

        # キャッシュ保存ファイルから cached_at を読み込み
        cache_path = Path(VIDEO_DETAIL_CACHE_FILE)
        if not cache_path.exists():
            # ファイルが無い場合はメモリ内キャッシュのみ使用（常に有効とみなす）
            return video_data

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            cache_entry = cache_data.get(video_id, {})
            cached_at_timestamp = cache_entry.get("cached_at")

            if not cached_at_timestamp:
                # cached_at がない古いキャッシュ形式 → 再取得
                return None

            # キャッシュ時刻からの経過時間を計算
            current_time = time.time()
            elapsed_seconds = current_time - cached_at_timestamp

            # まず、キャッシュデータから動画の type を判定して有効期限を決める
            # ※ここで簡易的に liveStreamingDetails の有無で判定
            live_details = video_data.get("liveStreamingDetails", {})
            is_live_related = bool(live_details)

            # Live関連動画は短い有効期限（60分）
            if is_live_related:
                expiry_seconds = CACHE_EXPIRY_LIVE_MINUTES * 60
                if elapsed_seconds > expiry_seconds:
                    logger.debug(
                        f"🔄 Live関連動画キャッシュ期限切れ（{video_id}）: {elapsed_seconds:.0f}秒経過"
                    )
                    return None
            else:
                # 通常動画は長い有効期限（7日）
                expiry_seconds = CACHE_EXPIRY_DAYS * 86400
                if elapsed_seconds > expiry_seconds:
                    logger.debug(
                        f"🔄 通常動画キャッシュ期限切れ（{video_id}）: {elapsed_seconds:.0f}秒経過"
                    )
                    return None

            # 有効期限内
            return video_data

        except Exception as e:
            logger.warning(
                f"⚠️ キャッシュ有効期限チェックエラー（{video_id}）: {e}. メモリキャッシュを使用します。"
            )
            # エラー時はメモリキャッシュをそのまま返す
            return video_data

    def _save_cache(self) -> None:
        """ビデオ詳細キャッシュをファイルに保存"""
        cache_path = Path(VIDEO_DETAIL_CACHE_FILE)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # 既存キャッシュを読み込む（他の処理で追加されたものを失わないため）
            existing_cache = {}
            if cache_path.exists():
                with open(cache_path, "r", encoding="utf-8") as f:
                    existing_cache = json.load(f)

            # 既存キャッシュにマージ
            for video_id, video_data in self.video_detail_cache.items():
                existing_cache[video_id] = {
                    "data": video_data,
                    "cached_at": time.time(),
                }

            # ファイルに保存
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(existing_cache, f, ensure_ascii=False, indent=2)

            logger.debug(f"💾 キャッシュを保存しました: {cache_path}")

        except Exception as e:
            logger.error(f"❌ キャッシュ保存エラー: {e}")


def get_video_classifier(api_key: Optional[str] = None) -> YouTubeVideoClassifier:
    """YouTubeVideoClassifier インスタンスを取得"""
    return YouTubeVideoClassifier(api_key=api_key)
