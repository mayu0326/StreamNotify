import asyncio
import logging
import feedparser
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Any

from v4.core.database import SessionLocal, upsert_video
from v4.core.config import settings
from v4.core.config import settings
from v4.gui.adapter import V3DatabaseAdapter

logger = logging.getLogger("v4.niconico_worker")

class NiconicoRSSWorker:
    """Worker to poll Niconico RSS for new videos with user name detection"""
    def __init__(self, user_id: str, interval_min: int = 15):
        self.user_id = user_id
        self.interval_sec = interval_min * 60
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

        # NiconicoClient を使用 (v4 Native)
        from v4.core.niconico.niconico_client import get_niconico_client
        self.client = get_niconico_client(user_id)

        logger.info(f"NiconicoRSSWorker initialized for user {user_id}")

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"NiconicoRSSWorker started for user {self.user_id}")

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NiconicoRSSWorker stopped")

    async def _loop(self):
        while self.is_running:
            try:
                await self.poll()
            except Exception as e:
                logger.error(f"Error in Niconico fallback loop: {e}", exc_info=True)
            await asyncio.sleep(self.interval_sec)

    async def poll(self):
        url = f"https://www.nicovideo.jp/user/{self.user_id}/video?rss=2.0"
        logger.info(f"Polling Niconico RSS: {url}")

        # feedparser is sync, but we run in async loop (can wrap in thread if needed)
        feed = feedparser.parse(url)

        if not feed.entries:
            logger.info("No entries found in Niconico RSS")
            return

        # ユーザー名を取得（キャッシング付き）
        user_name = self.client.get_user_name()
        logger.info(f"[ニコニコ] ユーザー名取得完了: {user_name}")

        db = SessionLocal()
        try:
            for entry in feed.entries[:5]: # Process latest 5
                video_data = self._parse_entry(entry, user_name)
                if video_data:
                    upsert_video(db, video_data)
            db.commit()
        finally:
            db.close()

    def _parse_entry(self, entry: Dict[str, Any], user_name: str = None) -> Optional[Dict[str, Any]]:
        link = entry.get("link", "")
        # Extract video ID (smXXXX)
        match = re.search(r'watch/([a-z]{2}\d+)', link)
        if not match:
            return None

        video_id = match.group(1)

        # Parse date
        pub_date = entry.get("published")
        published_at = None
        if pub_date:
            try:
                published_at = parsedate_to_datetime(pub_date)
            except:
                published_at = datetime.utcnow()

        # ユーザー名を使用（引数で指定されたものを優先、なければRSSの author から取得）
        channel_name = user_name or entry.get("author", "Niconico User")

        return {
            "video_id": video_id,
            "channel_id": self.user_id,
            "service": "niconico",
            "title": entry.get("title"),
            "video_url": link,
            "published_at": published_at,
            "channel_name": channel_name,
            "video_status": "upload"
        }
