# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v3 YouTube Live スケジューラー機構

★ 【v3.3.3】新機能：開始予定時刻付近のみ API を呼び出す

APScheduler を使用して、Live 動画の開始予定時刻 30 分前に
API を呼び出し、詳細情報を取得・DB 更新する。

RSS・WebSub 両モード対応。
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from threading import RLock

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"
__version__ = "3.3.3"


class LiveScheduler:
    """Live 動画の開始予定時刻ベース API 取得スケジューラー"""

    def __init__(self, database=None, classifier=None, live_module=None):
        """
        初期化

        Args:
            database: Database オブジェクト
            classifier: YouTubeVideoClassifier インスタンス
            live_module: LiveModule インスタンス
        """
        self.database = database
        self.classifier = classifier
        self.live_module = live_module
        self._scheduler = None
        self._job_map = {}  # video_id -> scheduler job ID のマッピング
        self._lock = RLock()  # スレッドセーフティ

        self._init_scheduler()

    def _init_scheduler(self):
        """APScheduler を初期化"""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.date import DateTrigger
            from apscheduler.executors.pool import ThreadPoolExecutor

            # バックグラウンドスケジューラーを作成
            # max_workers=2: 同時実行タスク数を制限（API クォータ保護）
            executors = {"default": ThreadPoolExecutor(max_workers=2)}

            self._scheduler = BackgroundScheduler(executors=executors)

            # 既に開始している場合はスキップ
            if not self._scheduler.running:
                self._scheduler.start()
                logger.info("✅ Live スケジューラー を開始しました")

        except ImportError:
            logger.error(
                "❌ APScheduler がインストールされていません。"
                "`pip install apscheduler` を実行してください。"
            )
            self._scheduler = None
        except Exception as e:
            logger.error(f"❌ Live スケジューラーの初期化に失敗しました: {e}")
            self._scheduler = None

    def schedule_api_fetch(
        self,
        video_id: str,
        scheduled_start_at_jst: str,
        title: str = "",
    ) -> bool:
        """
        ★ 【v3.3.3】Live 動画の API 取得をスケジュール

        開始予定時刻の 30 分前に API を呼び出し、詳細情報を取得する。

        Args:
            video_id: YouTube 動画 ID
            scheduled_start_at_jst: 開始予定時刻（JST、ISO 形式）
            title: 動画タイトル（ログ用）

        Returns:
            bool: スケジュール成功時 True、失敗時 False
        """
        if self._scheduler is None:
            logger.warning(f"⚠️ Live スケジューラーが初期化されていません（スケジュール失敗）: {video_id}")
            return False

        if not scheduled_start_at_jst or not video_id:
            logger.warning(f"⚠️ スケジュール対象外（時刻情報不足）: {video_id}")
            return False

        try:
            with self._lock:
                # 既にスケジュール済みの場合はスキップ
                if video_id in self._job_map:
                    logger.debug(f"ℹ️ 既にスケジュール済み（スキップ）: {video_id}")
                    return False

                # 開始予定時刻を解析
                try:
                    # ISO 形式から datetime へ
                    scheduled_time = datetime.fromisoformat(scheduled_start_at_jst)

                    # JST → UTC に変換（30分前の計算用）
                    jst_tz = timezone(timedelta(hours=9))
                    if scheduled_time.tzinfo is None:
                        scheduled_time = scheduled_time.replace(tzinfo=jst_tz)

                    # 30分前の時刻を計算
                    fetch_time = scheduled_time - timedelta(minutes=30)

                    # 既に過ぎている場合はスケジュール不可
                    now = datetime.now(timezone.utc).astimezone(jst_tz)
                    if fetch_time <= now:
                        logger.info(
                            f"ℹ️ 開始予定時刻が既に過ぎています（スケジュール不可）: "
                            f"{video_id} (scheduled={scheduled_start_at_jst}, fetch_time={fetch_time})"
                        )
                        return False

                    # ジョブをスケジュール
                    job = self._scheduler.add_job(
                        self._fetch_and_update,
                        trigger="date",
                        run_date=fetch_time,
                        args=[video_id, title],
                        id=f"live_fetch_{video_id}",
                        replace_existing=True,
                    )

                    self._job_map[video_id] = job.id

                    logger.info(
                        f"✅ Live API 取得をスケジュール: {video_id} ({title}) "
                        f"→ {fetch_time.strftime('%Y-%m-%d %H:%M:%S JST')} に実行"
                    )

                    return True

                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"⚠️ 時刻解析エラー（スケジュール失敗）: {video_id} - {e}"
                    )
                    return False

        except Exception as e:
            logger.error(f"❌ Live API スケジュール中にエラー: {e}")
            return False

    def cancel_schedule(self, video_id: str) -> bool:
        """
        ★ 【v3.3.3】Live 動画の API 取得スケジュールをキャンセル

        Args:
            video_id: YouTube 動画 ID

        Returns:
            bool: キャンセル成功時 True
        """
        if self._scheduler is None:
            return False

        try:
            with self._lock:
                if video_id not in self._job_map:
                    return False

                job_id = self._job_map[video_id]
                self._scheduler.remove_job(job_id)
                del self._job_map[video_id]

                logger.info(f"✅ Live API スケジュールをキャンセル: {video_id}")
                return True

        except Exception as e:
            logger.warning(f"⚠️ Live API スケジュールのキャンセル中にエラー: {e}")
            return False

    def _fetch_and_update(self, video_id: str, title: str = ""):
        """
        ★ 【v3.3.3】スケジュール時刻に実行される処理

        API から最新の動画詳細を取得し、DB を更新する。

        Args:
            video_id: YouTube 動画 ID
            title: 動画タイトル（ログ用）
        """
        youtube_logger = logging.getLogger("YouTubeLogger")

        try:
            youtube_logger.info(f"⏱️ Live API 定時取得を実行: {video_id} ({title})")

            if not self.classifier or not self.database:
                youtube_logger.warning(
                    f"⚠️ Live API 取得失敗（必要なモジュール未初期化）: {video_id}"
                )
                return

            # API から詳細情報を取得
            classification_result = self.classifier.classify_video(
                video_id, force_refresh=True  # 更新が必要なので強制更新
            )

            if not classification_result.get("success"):
                youtube_logger.warning(
                    f"⚠️ Live 分類エラー: {video_id} - {classification_result.get('error')}"
                )
                return

            # Live 関連動画をモジュールに登録
            if self.live_module:
                live_result = self.live_module.register_from_classified(classification_result)
                if live_result > 0:
                    youtube_logger.info(
                        f"✅ Live 詳細情報を更新: {video_id} (type={classification_result.get('type')})"
                    )
                else:
                    youtube_logger.debug(f"ℹ️ Live 動画の登録/更新なし: {video_id}")

        except Exception as e:
            youtube_logger.error(f"❌ Live API 取得中にエラー: {e}")

        finally:
            # スケジュール済みマップからジョブを削除
            with self._lock:
                if video_id in self._job_map:
                    del self._job_map[video_id]

    def shutdown(self):
        """スケジューラーをシャットダウン"""
        if self._scheduler and self._scheduler.running:
            try:
                self._scheduler.shutdown(wait=True)
                logger.info("✅ Live スケジューラー をシャットダウンしました")
            except Exception as e:
                logger.warning(f"⚠️ Live スケジューラーのシャットダウン中にエラー: {e}")

    def get_version(self) -> str:
        """バージョン情報を返す"""
        return f"LiveScheduler/{__version__}"


# グローバル インスタンス（シングルトン）
_live_scheduler_instance = None
_live_scheduler_lock = RLock()


def get_live_scheduler(
    database=None, classifier=None, live_module=None
) -> Optional[LiveScheduler]:
    """
    ★ 【v3.3.3】Live スケジューラーのシングルトンインスタンスを取得

    初回呼び出し時に初期化される。

    Args:
        database: Database オブジェクト（初回初期化時のみ使用）
        classifier: YouTubeVideoClassifier インスタンス（初回初期化時のみ使用）
        live_module: LiveModule インスタンス（初回初期化時のみ使用）

    Returns:
        LiveScheduler インスタンス、または None（初期化失敗時）
    """
    global _live_scheduler_instance

    if _live_scheduler_instance is not None:
        return _live_scheduler_instance

    try:
        with _live_scheduler_lock:
            if _live_scheduler_instance is None:
                _live_scheduler_instance = LiveScheduler(
                    database=database,
                    classifier=classifier,
                    live_module=live_module,
                )
            return _live_scheduler_instance
    except Exception as e:
        logger.error(f"❌ Live スケジューラーのインスタンス化に失敗しました: {e}")
        return None
