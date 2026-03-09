# -*- coding: utf-8 -*-

"""
StreamNotify on Bluesky- v1 YouTube RSS 管理

YouTube チャンネルの RSS を取得・パースして DB に反映する。
"""

import logging
from typing import Dict, List

import feedparser
import requests

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

YOUTUBE_RSS_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


class YouTubeRSS:
    """YouTube RSS 取得・管理クラス"""

    def __init__(self, channel_id: str):
        """
        初期化

        Args:
            channel_id: YouTube チャンネル ID
        """
        self.channel_id = channel_id
        self.rss_url = YOUTUBE_RSS_URL_TEMPLATE.format(channel_id=channel_id)

    def fetch_feed(self) -> List[Dict]:
        """
        RSS フィードを取得・パース

        Returns:
            新着動画のリスト（最新順）
        """
        try:
            logger.debug(f"RSS を取得します: {self.rss_url}")
            feed = feedparser.parse(self.rss_url)

            if feed.status != 200 and feed.bozo:
                logger.warning(f"RSS 取得に警告がありました: {feed.bozo_exception}")

            videos = []
            for entry in feed.entries[:10]:  # 最新 10 件まで
                video = {
                    "video_id": entry.yt_videoid,
                    "title": entry.title,
                    "video_url": entry.link,
                    "published_at": entry.published,
                    "channel_name": entry.author if hasattr(entry, "author") else "",
                }
                videos.append(video)

            logger.info(f"RSS から {len(videos)} 個の動画を取得しました")
            return videos

        except Exception as e:
            logger.error(f"RSS 取得に失敗しました: {e}")
            return []

    def save_to_db(self, database):
        """
        RSS から取得した動画を DB に保存

        Args:
            database: Database オブジェクト

        Returns:
            保存された動画数
        """
        videos = self.fetch_feed()
        saved_count = 0

        for video in videos:
            if database.insert_video(
                video_id=video["video_id"],
                title=video["title"],
                video_url=video["video_url"],
                published_at=video["published_at"],
                channel_name=video["channel_name"],
            ):
                saved_count += 1

        return saved_count


def get_youtube_rss(channel_id: str) -> YouTubeRSS:
    """YouTube RSS オブジェクトを取得"""
    return YouTubeRSS(channel_id)
