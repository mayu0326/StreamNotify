# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v4 YouTube RSS Manager

YouTube チャンネルの RSS を取得・パース・DB に保存する。
（画像処理は v4/image_manager.py で管理）
"""

import feedparser
import logging
import requests
import sqlite3
from typing import List, Dict
from datetime import datetime, timedelta, timezone

# v4 Imports
from v4.core.assets.image_manager import get_youtube_thumbnail_url
from v4.core.config import settings
from v4.core.utils_v4 import format_datetime_filter
from v4.core.youtube.youtube_api_client import get_youtube_api_client


logger = logging.getLogger("v4.youtube_rss")

YOUTUBE_RSS_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

# feedparser のデフォルト取得だと YouTube 側で弾かれたり、軽い XML 警告だけ出ることがある
_YOUTUBE_RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
}


class YouTubeRSS:
    """YouTube RSS 取得・管理クラス"""

    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        self.rss_url = YOUTUBE_RSS_URL_TEMPLATE.format(channel_id=channel_id)
        self.api_client = get_youtube_api_client()

    def fetch_feed(self) -> List[Dict]:
        """RSS フィードを取得・パース"""
        try:
            logger.debug(f"RSS を取得します: {self.rss_url}")
            resp = requests.get(
                self.rss_url,
                headers=_YOUTUBE_RSS_HEADERS,
                timeout=30,
            )
            if not resp.ok:
                logger.warning(
                    "RSS HTTP エラー: status=%s url=%s",
                    resp.status_code,
                    self.rss_url,
                )
                return []
            feed = feedparser.parse(resp.content)

            if feed.bozo:
                if feed.entries:
                    logger.debug(
                        "RSS: パーサ警告あり（entries は取得済み）: %s",
                        feed.bozo_exception,
                    )
                else:
                    logger.warning(
                        "RSS 取得に警告がありました: %s",
                        feed.bozo_exception,
                    )

            videos = []
            for entry in feed.entries[:15]:  # 最新 15 件まで
                # RSS published_at is UTC
                rss_published_at = entry.published

                # UTC → JST 変換（format_datetime_filter を使用し、「T」をスペースに置き換え）
                try:
                    published_at_jst = format_datetime_filter(rss_published_at, fmt="%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    logger.warning(f"⚠️ RSS 日時の JST 変換失敗: {e}")
                    published_at_jst = rss_published_at

                channel_name = entry.author if hasattr(entry, "author") else ""

                # Channel name fallback (Simplified for v4)
                if not channel_name:
                    if settings.youtube_channel_id:
                         channel_name = f"Channel ({settings.youtube_channel_id[:8]}...)"

                video = {
                    "video_id": entry.yt_videoid,
                    "title": entry.title,
                    "video_url": entry.link,
                    "published_at": published_at_jst,
                    "channel_name": channel_name,
                }
                videos.append(video)

            return videos

        except Exception as e:
            logger.error(f"RSS 取得に失敗しました: {e}")
            return []

    def save_to_db(self, database, classifier=None, live_module=None) -> tuple:
        """
        RSS から取得した動画を DB に保存 (Batch Processing)
        Args:
            database: V3DatabaseAdapter (or compatible)
            classifier: YouTubeVideoClassifier instance
            live_module: LiveModule instance
        """
        videos = self.fetch_feed()
        saved_count = 0
        live_registered_count = 0

        if not videos:
            return (0, 0)

        # 1. Batch API Fetch (if classifier enabled)
        details_map = {}
        if classifier:
            video_ids = [v["video_id"] for v in videos]
            # Batch fetch (Use cache unless force refreshed elsewhere, RSS is usually cache-safe for static info,
            # but for Live status we trust cache expiry logic in Client)
            details_map = self.api_client.fetch_video_details_batch(video_ids)

        for video in videos:
            video_id = video["video_id"]

            # Check existence
            existing_video = database.get_video_by_id(video_id)
            if existing_video:
                continue

            thumbnail_url = get_youtube_thumbnail_url(video_id)

            # Classify using batch result
            video_type = "video"
            classification_result = None

            if classifier and video_id in details_map:
                try:
                    # Use fetched details directly
                    classification_result = classifier.classify_from_details(video_id, details_map[video_id])
                    if classification_result.get("success"):
                        video_type = classification_result.get("type")
                except Exception as e:
                    logger.warning(f"Classifier error: {e}")

            # Live Module Hand-off
            if video_type in ["schedule", "live", "completed", "archive"] and live_module:
                 try:
                     res = live_module.register_from_classified(classification_result)
                     if res > 0:
                         live_registered_count += res
                         continue # Handled by LiveModule
                 except Exception as e:
                     logger.error(f"LiveModule register failed: {e}")

            # Normal Insert
            final_published_at = video["published_at"]
            representative_time_utc = None

            if classification_result and classification_result.get("success"):
                 representative_time_utc = classification_result.get("representative_time_utc")

            # Insert via Adapter
            is_new = database.insert_video(
                video_id=video_id,
                title=video["title"],
                video_url=video["video_url"],
                published_at=final_published_at,
                channel_name=video["channel_name"],
                thumbnail_url=thumbnail_url,
                source="youtube",
                representative_time_utc=representative_time_utc,
                representative_time_jst=final_published_at
            )

            if is_new:
                saved_count += 1
                logger.info(f"New video saved: {video['title']}")

        return (saved_count, live_registered_count)

def get_youtube_rss(channel_id: str) -> YouTubeRSS:
    return YouTubeRSS(channel_id)
