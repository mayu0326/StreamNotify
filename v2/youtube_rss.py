# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v2 YouTube RSS 管理

YouTube チャンネルの RSS を取得・パース・DB に保存する。
（画像処理は thumbnails/youtube_thumb_utils.py の YouTubeThumbPlugin で管理）
"""

import logging
from typing import Dict, List

import feedparser
import requests
from image_manager import get_youtube_thumbnail_url

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

YOUTUBE_RSS_URL_TEMPLATE = (
    "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
)


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
            for entry in feed.entries[:15]:  # 最新 15 件まで
                video = {
                    "video_id": entry.yt_videoid,
                    "title": entry.title,
                    "video_url": entry.link,
                    "published_at": entry.published,
                    "channel_name": entry.author if hasattr(entry, "author") else "",
                }
                videos.append(video)

            youtube_logger = logging.getLogger("YouTubeLogger")
            youtube_logger.info(f"RSS から {len(videos)} 個の動画を取得しました")
            return videos

        except Exception as e:
            logger.error(f"RSS 取得に失敗しました: {e}")
            return []

    def save_to_db(self, database) -> int:
        """
        RSS から取得した動画を DB に保存

        ⚠️ NOTE: 新規動画の画像ダウンロード・保存は
        thumbnails/youtube_thumb_utils.py の YouTubeThumbPlugin で実行されます。

        Args:
            database: Database オブジェクト

        Returns:
            保存された動画数
        """
        videos = self.fetch_feed()
        saved_count = 0
        existing_count = 0
        youtube_logger = logging.getLogger("YouTubeLogger")

        youtube_logger.info(
            f"[YouTube RSS] 取得した {len(videos)} 個の動画を DB に照合しています..."
        )

        # database モジュールのロガーを一時的に YouTubeLogger に切り替え
        import database as db_module

        original_logger = db_module.logger
        db_module.logger = youtube_logger

        try:
            for video in videos:
                # サムネイル URL を取得（多品質フォールバック）
                thumbnail_url = get_youtube_thumbnail_url(video["video_id"])

                # DB に保存（既存チェックは insert_video 内で実施）
                is_new = database.insert_video(
                    video_id=video["video_id"],
                    title=video["title"],
                    video_url=video["video_url"],
                    published_at=video["published_at"],
                    channel_name=video["channel_name"],
                    thumbnail_url=thumbnail_url,
                    source="youtube",
                )

                if is_new:
                    saved_count += 1
                    youtube_logger.debug(
                        f"[YouTube RSS] New video saved to DB: {video['title']}"
                    )

            if saved_count > 0:
                youtube_logger.info(f"✅ {saved_count} 個の新着動画を保存しました")
            else:
                youtube_logger.info("ℹ️ 新着動画はありません")

        finally:
            # ロガーを元に戻す
            db_module.logger = original_logger

        return saved_count


def get_youtube_rss(channel_id: str) -> YouTubeRSS:
    """YouTube RSS オブジェクトを取得"""
    return YouTubeRSS(channel_id)
