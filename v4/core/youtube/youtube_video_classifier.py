# -*- coding: utf-8 -*-

"""
YouTube API を使った動画種別分類モジュール
(YouTubeApiClient を使用)

YouTube Data API を使用して、動画が通常動画またはプレミア公開かを判定する。
Live関連（スケジュール、放送中、放送終了、ライブアーカイブ）は除外。
"""

import logging
from typing import Optional, Dict, Any, Union
from v4.core.youtube.youtube_api_client import get_youtube_api_client

logger = logging.getLogger("AppLogger")

# ビデオの種別定義（v3.3.0 仕様）
VIDEO_TYPE_NORMAL = "video"          # 通常動画
VIDEO_TYPE_PREMIERE = "premiere"      # プレミア公開
VIDEO_TYPE_LIVE = "live"              # ライブ配信中
VIDEO_TYPE_SCHEDULED = "schedule"     # ライブ予定/スケジュール
VIDEO_TYPE_COMPLETED = "completed"    # ライブ終了
VIDEO_TYPE_ARCHIVE = "archive"        # ライブアーカイブ
VIDEO_TYPE_UNKNOWN = "unknown"        # 判定不可


class YouTubeVideoClassifier:
    """YouTube Data API を使った動画種別分類"""

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: (Deprecated) Managed by YouTubeApiClient
        """
        self.api_client = get_youtube_api_client()

    def classify_video(self, video_id: str, force_refresh: bool = False) -> Dict[str, Any]:
        """
        動画 ID から動画の種別を判定 (Delegates logic to Client)
        """
        try:
            # Step 1: Fetch details (via Client which handles cache/quota)
            details = self.api_client.fetch_video_detail(video_id, force_refresh)

            if not details:
                return {
                    "success": False,
                    "video_id": video_id,
                    "type": VIDEO_TYPE_UNKNOWN,
                    "error": "Failed to fetch details (Check quota or ID)"
                }

            # Step 2: Classify
            classified = self.classify_from_details(video_id, details)
            return classified

        except Exception as e:
            logger.error(f"❌ Video classification error ({video_id}): {e}")
            return {
                "success": False,
                "video_id": video_id,
                "type": VIDEO_TYPE_UNKNOWN,
                "error": str(e)
            }

    def classify_from_details(self, video_id: str, video_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        API レスポンス(video item)から動画種別を判定 (Public)
        """
        # Dictionary structure matches API resource "video"
        snippet = video_data.get("snippet", {})
        title = snippet.get("title", "Unknown")
        description = snippet.get("description", "")
        channel_name = snippet.get("channelTitle", "")
        thumbnails = snippet.get("thumbnails", {})
        thumbnail_url = thumbnails.get("high", {}).get("url") or thumbnails.get("medium", {}).get("url")
        published_at = snippet.get("publishedAt", "")

        content_details = video_data.get("contentDetails", {})
        duration = content_details.get("duration", "PT0S")
        live_broadcast_content = snippet.get("liveBroadcastContent", "none")

        live_details = video_data.get("liveStreamingDetails", {})
        status = video_data.get("status", {})

        # Live関連の判定
        video_type = VIDEO_TYPE_UNKNOWN
        live_status = None
        is_live = False
        is_premiere = False
        is_scheduled_start_time = False

        scheduled_start_time = None
        actual_start_time = None
        actual_end_time = None
        representative_time_utc = None

        if live_details:
            is_live = True
            scheduled_start_time = live_details.get("scheduledStartTime")
            actual_start_time = live_details.get("actualStartTime")
            actual_end_time = live_details.get("actualEndTime")

            if scheduled_start_time and not actual_start_time:
                video_type = VIDEO_TYPE_SCHEDULED
                live_status = "upcoming"
                is_scheduled_start_time = True
                representative_time_utc = scheduled_start_time
            elif actual_start_time and not actual_end_time:
                video_type = VIDEO_TYPE_LIVE
                live_status = "live"
                representative_time_utc = actual_start_time
            elif actual_end_time:
                video_type = VIDEO_TYPE_ARCHIVE
                live_status = None
                representative_time_utc = actual_end_time
            else:
                # Should not happen often
                video_type = VIDEO_TYPE_UNKNOWN

        elif snippet.get("liveBroadcastContent") == "premiere":
            video_type = VIDEO_TYPE_PREMIERE
            is_premiere = True
            representative_time_utc = published_at

        else:
            video_type = VIDEO_TYPE_NORMAL
            representative_time_utc = published_at

        return {
            "success": True,
            "video_id": video_id,
            "type": video_type,
            "title": title,
            "description": description,
            "channel_name": channel_name,
            "thumbnail_url": thumbnail_url,
            "is_premiere": is_premiere,
            "is_live": is_live,
            "live_status": live_status,
            "is_scheduled_start_time": is_scheduled_start_time,
            "published_at": published_at,
            "duration": duration,
            "live_broadcast_content": live_broadcast_content,
            "scheduled_start_time": scheduled_start_time,
            "actual_start_time": actual_start_time,
            "actual_end_time": actual_end_time,
            "representative_time_utc": representative_time_utc,
            "error": None
        }

def get_video_classifier(api_key: Optional[str] = None) -> YouTubeVideoClassifier:
    return YouTubeVideoClassifier(api_key=api_key)
