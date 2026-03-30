# -*- coding: utf-8 -*-

"""
YouTube Live Module (v4 Port)

YouTubeVideoClassifier の結果に基づいて、
- Schedule（スケジュール）
- Live（配信中）
- Completed（配信終了）
- Archive（ライブアーカイブ）

の4つの状態を一元管理し、状態遷移と自動投稿を処理する。
PluginManagerの代わりに直接BlueskyClientとTemplatesを使用する。
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from v4.core.assets.image_manager import get_image_manager
from v4.core.bluesky.bluesky_client import BlueskyClient

# v4 Imports
from v4.core.config import settings
from v4.core.templates.templates import templates
from v4.core.utils_v4 import format_datetime_filter
from v4.core.youtube.youtube_api_client import get_youtube_api_client

logger = logging.getLogger("v4.live_module")

# Video Types
VIDEO_TYPE_SCHEDULE = "schedule"
VIDEO_TYPE_LIVE = "live"
VIDEO_TYPE_COMPLETED = "completed"
VIDEO_TYPE_ARCHIVE = "archive"

# Live Status
LIVE_STATUS_UPCOMING = "upcoming"
LIVE_STATUS_LIVE = "live"
LIVE_STATUS_COMPLETED = "completed"


class LiveModule:
    """
    YouTube Live Management Module
    """

    def __init__(self, db):
        """
        Args:
            db: V3DatabaseAdapter instance
        """
        self.db = db
        # v4 uses internal clients instead of plugin manager
        self.bsky = BlueskyClient()
        self.image_manager = get_image_manager()
        self.api_client = get_youtube_api_client()

        # Memory tracking
        self.archive_tracking = {}
        logger.debug("📝 Live tracking map initialized")

    def _should_autopost_live(self, video_type: str) -> bool:
        """
        判定ロジック:
        - Mode=AUTOPOST: youtube_live_autopost_mode設定に基づく ("all", "live", "schedule", "archive", "off")
        - Mode=SELFPOST/Other: 個別の auto_post_xxx フラグに基づく
        """
        mode = settings.app_mode.lower()
        if mode == "autopost":
            # 新しい設定: autopost_statuses (list) を使用
            # デフォルト: ["upcoming", "live", "archive"]
            target_statuses = [s.lower() for s in getattr(settings, "autopost_statuses", [])]

            # 状態マッピング
            # VIDEO_TYPE_SCHEDULE ("schedule") -> "upcoming" (or "schedule")
            # VIDEO_TYPE_LIVE ("live") -> "live"
            # VIDEO_TYPE_COMPLETED ("completed") -> "live" (配信終了も"live"カテゴリとして扱う)
            # VIDEO_TYPE_ARCHIVE ("archive") -> "archive"

            check_key = None
            if video_type == VIDEO_TYPE_SCHEDULE:
                check_key = "upcoming"
            elif video_type == VIDEO_TYPE_LIVE:
                check_key = "live"
            elif video_type == VIDEO_TYPE_COMPLETED:
                check_key = "live"
            elif video_type == VIDEO_TYPE_ARCHIVE:
                check_key = "archive"

            # "schedule" キーワードも互換性のため許容
            if video_type == VIDEO_TYPE_SCHEDULE and "schedule" in target_statuses:
                return True

            if check_key and check_key in target_statuses:
                return True

            return False
        else:
            # SelfPost or others
            if video_type == VIDEO_TYPE_SCHEDULE:
                return getattr(settings, "auto_post_schedule", False)
            if video_type == VIDEO_TYPE_LIVE:
                return getattr(settings, "auto_post_live", False)
            if video_type == VIDEO_TYPE_ARCHIVE:
                return getattr(settings, "auto_post_archive", False)
            return False

    async def _perform_v4_post(self, video_id: str, video_type: str, video_data: Dict[str, Any]) -> bool:
        """
        v4仕様の投稿実行ロジック
        Template -> Image -> BskyClient
        """
        try:
            # 1. Template Selection
            template_name = ""
            if video_type == VIDEO_TYPE_SCHEDULE:
                template_name = "youtube/yt_schedule_template"
            elif video_type == VIDEO_TYPE_LIVE:
                template_name = "youtube/yt_online_template"
            elif video_type == VIDEO_TYPE_COMPLETED:
                template_name = "youtube/yt_offline_template"
            elif video_type == VIDEO_TYPE_ARCHIVE:
                template_name = "youtube/yt_archive_template"

            if not template_name:
                logger.warning(f"No template for type {video_type}")
                return False

            # 2. Render Check (Dry run render)
            # v3 templates expect 'title', 'video_url' etc as top level variables.
            text = templates.render(template_name, video_data)
            if not text:
                logger.warning(f"Template render failed or empty for {template_name}")
                return False

            logger.info(f"📝 Posting for {video_id} ({video_type}): {text[:30]}...")

            # 3. Image Preparation
            image_path = None
            thumbnail_url = video_data.get("thumbnail_url")
            if thumbnail_url:
                filename = self.image_manager.download_and_save_thumbnail(
                    thumbnail_url=thumbnail_url, site="YouTube", video_id=video_id, mode="import"  # or 'live'?
                )
                if filename:
                    # Resolve absolute path from ImageManager logic if needed.
                    image_path = os.path.abspath(f"images/YouTube/import/{filename}")
                    if not os.path.exists(image_path):
                        pass

            # 4. Post using BlueskyClient
            success = await self.bsky.post(text=text, image_path=image_path)

            if success:
                logger.info(f"✅ Auto-posted: {video_id} ({video_type})")
                # Mark as posted
                self.db.mark_as_posted(video_id)
                return True
            else:
                logger.error(f"❌ Auto-post failed: {video_id}")
                return False

        except Exception as e:
            logger.error(f"❌ Error in _perform_v4_post: {e}")
            return False

    def _sync_post_wrapper(self, video_id, video_type, video_data):
        """Wrapper to call async post from sync context"""
        try:
            asyncio.run(self._perform_v4_post(video_id, video_type, video_data))
        except Exception as e:
            logger.error(f"Async loop error: {e}")

    def register_from_classified(self, result: Dict[str, Any]) -> int:
        """
        Register classified video to DB.
        """
        if not result or not result.get("success"):
            return 0

        video_id = result.get("video_id")
        video_type = result.get("type")

        # Check existing
        existing = None
        try:
            existing = self.db.get_video_by_id(video_id)
        except Exception:
            pass

        title = result.get("title", "【Live】")
        published_at = result.get("published_at", "")
        channel_name = result.get("channel_name", "")
        thumbnail_url = result.get("thumbnail_url", "")
        is_premiere = result.get("is_premiere", False)

        representative_time_utc = result.get("representative_time_utc")
        representative_time_jst = None
        if representative_time_utc:
            # JST に変換し、「T」をスペースに置き換え（%Y-%m-%d %H:%M:%S フォーマット）
            representative_time_jst = format_datetime_filter(representative_time_utc, fmt="%Y-%m-%d %H:%M:%S")

        db_published_at = published_at
        if representative_time_jst and video_type in [VIDEO_TYPE_SCHEDULE, VIDEO_TYPE_LIVE, VIDEO_TYPE_ARCHIVE]:
            db_published_at = representative_time_jst

        video_url = f"https://www.youtube.com/watch?v={video_id}"

        live_status_map = {
            VIDEO_TYPE_SCHEDULE: LIVE_STATUS_UPCOMING,
            VIDEO_TYPE_LIVE: LIVE_STATUS_LIVE,
            VIDEO_TYPE_COMPLETED: LIVE_STATUS_COMPLETED,
            VIDEO_TYPE_ARCHIVE: None,
        }
        live_status = live_status_map.get(video_type)

        is_update = existing is not None
        success = False

        if is_update:
            existing_type = existing.get("content_type")
            if existing_type != video_type:
                # Update
                self.db.update_video_status(video_id, video_type, live_status)
                self.db.update_published_at(video_id, db_published_at)
                logger.info(f"✅ Live video updated: {title} ({video_type})")
                success = True
            else:
                return 0
        else:
            # Insert
            res = self.db.insert_video(
                video_id=video_id,
                title=title,
                video_url=video_url,
                published_at=db_published_at,
                channel_name=channel_name,
                thumbnail_url=thumbnail_url,
                content_type=video_type,
                live_status=live_status,
                is_premiere=is_premiere,
                source="youtube",
                skip_dedup=True,
                representative_time_utc=representative_time_utc,
                representative_time_jst=representative_time_jst,
            )
            if res:
                logger.info(f"✅ Live video registered: {title} ({video_type})")
                if settings.app_mode == "selfpost":
                    self.db.update_selection(video_id, selected=True)
                success = True

        if success:
            # Autopost Check for Schedule
            if not is_update and video_type == VIDEO_TYPE_SCHEDULE:
                if self._should_autopost_live(VIDEO_TYPE_SCHEDULE):
                    video_data = {
                        "video_id": video_id,
                        "title": title,
                        "video_url": video_url,
                        "published_at": db_published_at,
                        "channel_name": channel_name,
                        "thumbnail_url": thumbnail_url,
                        "type": video_type,
                    }
                    self._sync_post_wrapper(video_id, VIDEO_TYPE_SCHEDULE, video_data)

        return 1 if success else 0

    def get_next_poll_interval_minutes(self) -> int:
        try:
            all_videos = self.db.get_all_videos()
            live_videos = [
                v
                for v in all_videos
                if v.get("content_type") in [VIDEO_TYPE_SCHEDULE, VIDEO_TYPE_LIVE, VIDEO_TYPE_COMPLETED, VIDEO_TYPE_ARCHIVE]
            ]
            if any(v.get("content_type") in [VIDEO_TYPE_SCHEDULE, VIDEO_TYPE_LIVE] for v in live_videos):
                return getattr(settings, "youtube_live_poll_interval_active", 15)
            if live_videos:
                return getattr(settings, "youtube_live_poll_interval_completed_min", 60)
            return 0
        except Exception:
            return getattr(settings, "youtube_live_poll_interval_active", 15)

    def poll_lives(self) -> int:
        """
        Poll registered live videos using Batch API Fetch.
        """
        try:
            all_videos = self.db.get_all_videos()
            live_videos = [
                v
                for v in all_videos
                if v.get("content_type") in [VIDEO_TYPE_SCHEDULE, VIDEO_TYPE_LIVE, VIDEO_TYPE_COMPLETED, VIDEO_TYPE_ARCHIVE]
            ]

            if not live_videos:
                return 0

            # 1. Collect IDs
            live_ids = [v.get("video_id") for v in live_videos if v.get("video_id")]
            if not live_ids:
                return 0

            processed = 0

            # 2. Batch Fetch Details (Force Refresh for Polling)
            # Use chunks if > 50 (fetch_video_details_batch handles chunking internally)
            details_map = self.api_client.fetch_video_details_batch(live_ids, force_refresh=True)

            from v4.core.youtube.youtube_video_classifier import get_video_classifier

            classifier = get_video_classifier(api_key=settings.youtube_api_key)

            for video in live_videos:
                video_id = video.get("video_id")
                if video_id not in details_map:
                    continue

                # 3. Classify using fetched result
                try:
                    result = classifier.classify_from_details(video_id, details_map[video_id])
                except Exception:
                    continue

                if not result.get("success"):
                    continue

                current_type = result.get("type")
                current_live_status = result.get("live_status")
                old_type = video.get("content_type")

                if old_type != current_type:
                    logger.info(f"🔄 State change: {video_id} {old_type} -> {current_type}")
                    self.db.update_video_status(video_id, current_type, current_live_status)
                    processed += 1

                    # Autopost Trigger
                    if self._should_autopost_live(current_type):
                        # Prepare video data (merge with result)
                        video_data = video.copy()
                        video_data.update({"type": current_type, "live_status": current_live_status})
                        self._sync_post_wrapper(video_id, current_type, video_data)

            return processed
        except Exception as e:
            logger.error(f"Poll lives error: {e}")
            return 0


def get_live_module(db=None) -> LiveModule:
    return LiveModule(db=db)
