import asyncio
import logging
from typing import Optional

from v4.core.config import settings
from v4.core.youtube.youtube_rss import get_youtube_rss
from v4.core.youtube.live_module import get_live_module
from v4.core.youtube.live_scheduler import get_live_scheduler
from v4.core.youtube.youtube_video_classifier import get_video_classifier
from v4.core.youtube.youtube_api_client import get_youtube_api_client
from v4.gui.adapter import V3DatabaseAdapter

logger = logging.getLogger("v4.youtube_worker")

class YouTubeRSSWorker:
    """
    Worker to poll YouTube RSS for new videos.
    Supports dynamic polling intervals based on LiveModule state.
    Integrates LiveScheduler for JIT API fetching (Poll/Fallback mode only).
    """
    def __init__(self, channel_id: str, default_interval_min: int = 10):
        self.channel_id = channel_id
        self.default_interval_sec = default_interval_min * 60
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

        # Initialize components using V3DatabaseAdapter
        self.db_adapter = V3DatabaseAdapter()
        self.rss = get_youtube_rss(channel_id)

        # Classifier & LiveModule for advanced features
        self.classifier = None
        try:
            self.classifier = get_video_classifier(api_key=settings.youtube_api_key)
        except Exception as e:
            logger.warning(f"Failed to init VideoClassifier: {e}")

        self.live_module = None
        try:
            self.live_module = get_live_module(db=self.db_adapter)
        except Exception as e:
            logger.warning(f"Failed to init LiveModule: {e}")

        # LiveScheduler (Optimized JIT Fetching)
        self.live_scheduler = None
        try:
            self.live_scheduler = get_live_scheduler(
                database=self.db_adapter,
                classifier=self.classifier,
                live_module=self.live_module
            )
        except Exception as e:
            logger.warning(f"Failed to init LiveScheduler: {e}")

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"YouTubeRSSWorker started for channel {self.channel_id}")

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Shutdown scheduler if exists
        if self.live_scheduler:
            self.live_scheduler.shutdown()

        # Save API caches
        try:
            get_youtube_api_client().close()
        except Exception as e:
            logger.error(f"Failed to close API client: {e}")

        logger.info("YouTubeRSSWorker stopped")

    async def _loop(self):
        while self.is_running:
            try:
                await self.poll()
            except Exception as e:
                logger.error(f"Error in YouTube RSS loop: {e}", exc_info=True)

            # Dynamic Interval Calculation
            interval = self.default_interval_sec
            if self.live_module:
                try:
                    # LiveModule returns minutes
                    dynamic_min = self.live_module.get_next_poll_interval_minutes()
                    if dynamic_min > 0:
                        interval = dynamic_min * 60
                        logger.debug(f"Dynamic polling interval set to {dynamic_min} min")
                    elif dynamic_min == 0:
                        # 0 means "no live to track", fallback to default RSS interval
                         interval = self.default_interval_sec
                except Exception as e:
                    logger.warning(f"Failed to get dynamic interval: {e}")

            await asyncio.sleep(interval)

    async def poll(self):
        # We need to run sync blocking operations in a thread
        loop = asyncio.get_running_loop()

        # 1. RSS Poll & Save
        # This handles saving new videos and detecting type (if classifier enabled)
        await loop.run_in_executor(None, self._sync_rss_poll)

        # 2. Live Module Poll (Event detection: start/end/archive)
        if self.live_module:
            await loop.run_in_executor(None, self._sync_live_poll)

        # 3. Scheduler Maintenance (Schedule API fetch for UPCOMING videos)
        if self.live_scheduler and self.live_module:
            await loop.run_in_executor(None, self._sync_scheduler_maintenance)

    def _sync_rss_poll(self):
        """Blocking RSS poll"""
        try:
            # save_to_db arguments: database, classifier=None, live_module=None
            saved, live_reg = self.rss.save_to_db(
                self.db_adapter,
                classifier=self.classifier,
                live_module=self.live_module
            )
            if saved > 0 or live_reg > 0:
                logger.info(f"RSS Poll: Saved {saved} new, {live_reg} live registered")
        except Exception as e:
            logger.error(f"RSS Poll failed: {e}")

    def _sync_live_poll(self):
        """Blocking Live/Event poll"""
        try:
             count = self.live_module.poll_lives()
             if count > 0:
                 logger.info(f"Live Poll: Processed {count} events")
        except Exception as e:
            logger.error(f"Live Poll failed: {e}")

    def _sync_scheduler_maintenance(self):
        """
        Check for 'schedule' videos and register them to LiveScheduler.
        This runs only when Worker is polling (Poll mode or Fallback).
        """
        try:
            all_videos = self.db_adapter.get_all_videos()
            # Filter for UPCOMING (schedule) videos
            upcoming_videos = [v for v in all_videos if v.get("content_type") == "schedule"]

            for v in upcoming_videos:
                video_id = v.get("video_id")
                # Use published_at as JST start time (LiveModule sets this)
                start_time_jst = v.get("published_at")
                title = v.get("title", "")

                if video_id and start_time_jst:
                    self.live_scheduler.schedule_api_fetch(video_id, start_time_jst, title)

        except Exception as e:
            logger.error(f"Scheduler maintenance failed: {e}")
