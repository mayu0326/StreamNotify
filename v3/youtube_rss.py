# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v3 YouTube RSS 管理

YouTube チャンネルの RSS を取得・パース・DB に保存する。
（画像処理は thumbnails/youtube_thumb_utils.py の YouTubeThumbPlugin で管理）
"""

import feedparser
import logging
import requests
from typing import List, Dict
from image_manager import get_youtube_thumbnail_url

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv3"

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
        blacklist_skip_count = 0
        youtube_logger = logging.getLogger("YouTubeLogger")

        youtube_logger.info(f"[YouTube RSS] 取得した {len(videos)} 個の動画を DB に照合しています...")

        # ★ 新: 除外動画リストを取得
        try:
            from deleted_video_cache import get_deleted_video_cache
            deleted_cache = get_deleted_video_cache()
        except ImportError:
            youtube_logger.warning("deleted_video_cache モジュールが見つかりません")
            deleted_cache = None

        # database モジュールのロガーを一時的に YouTubeLogger に切り替え
        import database as db_module
        original_logger = db_module.logger
        db_module.logger = youtube_logger

        try:
            for video in videos:
                # ★ 新: 除外動画リスト確認
                if deleted_cache and deleted_cache.is_deleted(video["video_id"], source="youtube"):
                    youtube_logger.info(f"⏭️ 除外動画リスト登録済みのため、スキップします: {video['title']}")
                    blacklist_skip_count += 1
                    continue

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
                    youtube_logger.debug(f"[YouTube RSS] New video saved to DB: {video['title']}")

            summary = f"✅ 保存完了: 新規 {saved_count}, 既存 {existing_count}"
            if blacklist_skip_count > 0:
                summary += f", 除外動画リスト {blacklist_skip_count}"

            if saved_count > 0:
                youtube_logger.info(summary)
            elif blacklist_skip_count > 0:
                youtube_logger.info(summary)
            else:
                youtube_logger.info(f"ℹ️ 新着動画はありません")

        finally:
            # ロガーを元に戻す
            db_module.logger = original_logger

        return saved_count

    def poll_videos(self):
        """RSSフィードをポーリングし、キャッシュを更新"""
        videos = self.fetch_feed()
        for video in videos:
            video_id = video['video_id']
            if video_id not in self.deleted_cache:
                self.db.insert_video(video_id, video['title'], video['video_url'], video['published_at'], video['channel_name'])
                # キャッシュ更新を追加
                self.plugin.update_video_detail_cache(video_id, video)


def get_youtube_rss(channel_id: str) -> YouTubeRSS:
    """YouTube RSS オブジェクトを取得"""
    return YouTubeRSS(channel_id)
