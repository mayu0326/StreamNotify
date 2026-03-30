# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v4 Live Scheduler

APScheduler を使用して、Live 動画の開始予定時刻 30 分前に
API を呼び出し、詳細情報を取得・DB 更新する。
YouTubeRSSWorker (ポーリング/フォールバック) で使用される。
"""

import logging
from typing import Optional
from datetime import datetime, timedelta, timezone
from threading import RLock

logger = logging.getLogger("v4.live_scheduler")

__version__ = "4.0.0"

class LiveScheduler:
    """Live 動画の開始予定時刻ベース API 取得スケジューラー"""

    def __init__(self, database=None, classifier=None, live_module=None):
        """
        Args:
            database: V3DatabaseAdapter
            classifier: YouTubeVideoClassifier instance
            live_module: LiveModule instance
        """
        self.database = database
        self.classifier = classifier
        self.live_module = live_module
        self._scheduler = None
        self._job_map = {}  # video_id -> scheduler job ID のマッピング
        self._lock = RLock()

        self._init_scheduler()

    def _init_scheduler(self):
        """APScheduler を初期化"""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.executors.pool import ThreadPoolExecutor

            executors = {"default": ThreadPoolExecutor(max_workers=2)}
            self._scheduler = BackgroundScheduler(executors=executors)

            if not self._scheduler.running:
                self._scheduler.start()
                logger.info("✅ Live Scheduler started")

        except ImportError:
            logger.error("❌ APScheduler not installed. `pip install apscheduler` required.")
            self._scheduler = None
        except Exception as e:
            logger.error(f"❌ Failed to init Live Scheduler: {e}")
            self._scheduler = None

    def schedule_api_fetch(self, video_id: str, scheduled_start_at_jst: str, title: str = "") -> bool:
        """
        開始予定時刻の 30 分前に API を呼び出し、詳細情報を取得するようスケジュール
        """
        if self._scheduler is None:
            return False

        if not scheduled_start_at_jst or not video_id:
            return False

        try:
            with self._lock:
                if video_id in self._job_map:
                    return False

                # Parse time
                try:
                    scheduled_time = datetime.fromisoformat(scheduled_start_at_jst)
                    jst_tz = timezone(timedelta(hours=9))
                    if scheduled_time.tzinfo is None:
                        scheduled_time = scheduled_time.replace(tzinfo=jst_tz)

                    fetch_time = scheduled_time - timedelta(minutes=30)
                    now = datetime.now(timezone.utc).astimezone(jst_tz)

                    if fetch_time <= now:
                        # Already passed trigger time
                        return False

                    job = self._scheduler.add_job(
                        self._fetch_and_update,
                        trigger="date",
                        run_date=fetch_time,
                        args=[video_id, title],
                        id=f"live_fetch_{video_id}",
                        replace_existing=True,
                    )

                    self._job_map[video_id] = job.id
                    logger.info(f"⏰ Scheduled API fetch for {video_id} at {fetch_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    return True

                except (ValueError, TypeError) as e:
                    logger.warning(f"Time parse error for schedule: {video_id} - {e}")
                    return False

        except Exception as e:
            logger.error(f"Schedule error: {e}")
            return False

    def cancel_schedule(self, video_id: str) -> bool:
        """スケジュールをキャンセル"""
        if self._scheduler is None:
            return False

        try:
            with self._lock:
                if video_id not in self._job_map:
                    return False

                job_id = self._job_map[video_id]
                self._scheduler.remove_job(job_id)
                del self._job_map[video_id]
                logger.info(f"🗑️ Cancelled schedule for {video_id}")
                return True
        except Exception as e:
            logger.warning(f"Cancel error: {e}")
            return False

    def _fetch_and_update(self, video_id: str, title: str = ""):
        """スケジュール実行時の処理"""
        try:
            logger.info(f"🚀 Executing scheduled API fetch: {video_id} ({title})")

            if not self.classifier or not self.database:
                return

            # Force refresh from API
            classification_result = self.classifier.classify_video(video_id, force_refresh=True)

            if not classification_result.get("success"):
                logger.warning(f"Failed to classify in scheduled job: {video_id}")
                return

            # Integrate with LiveModule
            if self.live_module:
                 res = self.live_module.register_from_classified(classification_result)
                 if res > 0:
                     logger.info(f"✅ Scheduled update applied: {video_id}")
                 else:
                     logger.info(f"ℹ️ Scheduled update no change: {video_id}")

        except Exception as e:
            logger.error(f"Error in scheduled job: {e}")

        finally:
            with self._lock:
                if video_id in self._job_map:
                    del self._job_map[video_id]

    def shutdown(self):
        """Shutdown scheduler"""
        if self._scheduler and self._scheduler.running:
            try:
                self._scheduler.shutdown(wait=True)
                logger.info("Live Scheduler shutdown")
            except Exception as e:
                logger.error(f"Shutdown error: {e}")

_instance = None
_lock = RLock()

def get_live_scheduler(database=None, classifier=None, live_module=None) -> Optional[LiveScheduler]:
    global _instance
    if _instance:
        return _instance
    with _lock:
        if _instance is None:
            _instance = LiveScheduler(database, classifier, live_module)
        return _instance
