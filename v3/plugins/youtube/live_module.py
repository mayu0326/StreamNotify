# -*- coding: utf-8 -*-

"""
YouTube Live モジュール

YouTubeVideoClassifier の結果に基づいて、
- Schedule（スケジュール）
- Live（配信中）
- Completed（配信終了）
- Archive（ライブアーカイブ）

の4つの状態を一元管理し、状態遷移と自動投稿を処理する。

設計方針：
- キャッシュは最小化（状態遷移の検知と投稿判定が主目的）
- DB スキーマは既存の content_type / live_status を再利用
- PluginManager 経由で Bluesky 投稿を実行
- 戻り値は処理件数（int）で統一して、テスト・デバッグを容易化
"""

import logging
import os
from typing import Dict, Any, Optional
from datetime import datetime

from database import Database
from config import get_config, OperationMode

logger = logging.getLogger("AppLogger")

# 動画種別定義（YouTubeVideoClassifier と統一）
VIDEO_TYPE_SCHEDULE = "schedule"
VIDEO_TYPE_LIVE = "live"
VIDEO_TYPE_COMPLETED = "completed"
VIDEO_TYPE_ARCHIVE = "archive"

# Live ステータス定義
LIVE_STATUS_UPCOMING = "upcoming"
LIVE_STATUS_LIVE = "live"
LIVE_STATUS_COMPLETED = "completed"


class LiveModule:
    """
    YouTube Live 管理モジュール

    YouTubeVideoClassifier の分類結果を受け取り、
    DB 登録、状態遷移検知、自動投稿を一元処理する。

    ★ v3.3.0 改訂：複雑なポーリング追跡戦略に対応
    - completed のみ時：1～3時間毎に確認
    - archive化後：元completed動画について3時間毎に最大4回確認
    - LIVE なし時：判定ロジック休止（RSS/WebSubから新規動画まで待機）
    """

    def __init__(self, db: Optional[Database] = None, plugin_manager=None):
        """
        初期化

        Args:
            db: Database インスタンス（Noneの場合は自動取得）
            plugin_manager: PluginManager インスタンス（自動投稿用）
        """
        self.db = db or self._get_db()
        self.plugin_manager = plugin_manager
        self.config = get_config("settings.env")

        # ★ メモリ内追跡情報（アプリケーション実行中のみ保持）
        # {video_id: {"last_poll_time": float, "archive_check_count": int}}
        self.archive_tracking = {}

        logger.debug("📝 Live追跡情報マップを初期化しました")

    def _get_db(self) -> Database:
        """Database シングルトンを取得"""
        from database import get_database
        return get_database()

    def register_from_classified(self, result: Dict[str, Any]) -> int:
        """
        YouTubeVideoClassifier の分類結果を受け取り、DB に登録

        Args:
            result: YouTubeVideoClassifier.classify_video() の戻り値
                   {
                       "success": bool,
                       "video_id": str,
                       "type": str,  # "schedule", "live", "completed", "archive"
                       "title": str,
                       "description": str,
                       "thumbnail_url": str,
                       "published_at": str,
                       "live_status": str or None,
                       "representative_time_utc": str,  # ★ 【新】基準時刻（UTC）
                       ...
                   }

        Returns:
            int: 登録・更新した件数（0 = 何もしなかった、1 = 登録・更新した）
        """
        if not result.get("success"):
            logger.debug(f"⏭️  分類失敗（登録スキップ）: {result.get('error')}")
            return 0

        video_id = result.get("video_id")
        video_type = result.get("type")

        # Live 関連以外はスキップ
        if video_type not in [VIDEO_TYPE_SCHEDULE, VIDEO_TYPE_LIVE, VIDEO_TYPE_COMPLETED, VIDEO_TYPE_ARCHIVE]:
            logger.debug(f"⏭️  非Live動画（登録スキップ）: {video_type}")
            return 0

        # ★ 【重要】既存チェック: 同じ video_id が既に DB に存在する場合
        try:
            existing = self.db.get_video_by_id(video_id)
            if existing:
                # ★ 【新】既存動画の場合、コンテンツタイプが異なれば更新
                existing_type = existing.get('content_type')
                if existing_type != video_type:
                    # 分類結果が前回と異なる場合は更新
                    logger.info(
                        f"🔄 Live動画の分類更新: {video_id} "
                        f"(既存: {existing_type} → 新規: {video_type})"
                    )
                    # 以下の処理で更新を行う（登録スキップしない）
                else:
                    # 分類結果が同じ場合はスキップ
                    logger.debug(
                        f"⏭️  既存のLive動画で分類に変更なし: {video_id} "
                        f"(type={existing_type}, status={existing.get('live_status')})"
                    )
                    return 0
        except Exception as e:
            logger.warning(f"⚠️ 既存チェック中にエラー（続行）: {video_id} - {e}")
            # エラー時は続行して登録を試みる（DB エラーなど）

        # 基本情報を抽出
        title = result.get("title", "【ライブ】")
        channel_name = result.get("channel_name", "")
        published_at = result.get("published_at", "")
        thumbnail_url = result.get("thumbnail_url", "")
        is_premiere = result.get("is_premiere", False)

        # ★ 【新】基準時刻（UTC）を取得
        representative_time_utc = result.get("representative_time_utc")

        # ★ 【重要】representative_time_utc を JST に変換（スケジュール時は開始予定時刻）
        representative_time_jst = None
        if representative_time_utc:
            try:
                from utils_v3 import format_datetime_filter
                representative_time_jst = format_datetime_filter(representative_time_utc, fmt="%Y-%m-%d %H:%M:%S")
                logger.debug(f"📡 representative_time_utc を JST に変換: {representative_time_utc} → {representative_time_jst}")
            except Exception as e:
                logger.warning(f"⚠️ representative_time_utc の変換失敗: {e}")
                # 失敗時は published_at を使用
                representative_time_jst = None

        # ★ 【重要】DB 登録時の published_at の決定ロジック
        # スケジュール（type="schedule"）: 開始予定時刻（JST）
        # LIVE 配信中（type="live"）: actualStartTime（配信開始時刻）（JST）
        # アーカイブ（type="archive"）: actualEndTime（配信終了時刻）（JST）
        # その他（通常動画など）: 公開日時（JST）
        if video_type == VIDEO_TYPE_SCHEDULE and representative_time_jst:
            # スケジュール動画: 開始予定時刻（JST変換済み）を使用
            db_published_at = representative_time_jst
            logger.info(f"   📅 スケジュール動画: 開始予定時刻（JST）を使用: {db_published_at}")
        elif video_type == VIDEO_TYPE_LIVE and representative_time_jst:
            # LIVE 配信中: 配信開始時刻（JST）を使用
            db_published_at = representative_time_jst
            logger.info(f"   ⏱️  LIVE 配信中: 配信開始時刻（JST）を使用: {db_published_at}")
        elif video_type == VIDEO_TYPE_ARCHIVE and representative_time_jst:
            # アーカイブ: 配信終了時刻（JST）を使用
            db_published_at = representative_time_jst
            logger.info(f"   ⏱️  アーカイブ: 配信終了時刻（JST）を使用: {db_published_at}")
        else:
            # それ以外（通常動画など）: 公開日時を使用（YouTubeAPI は UTC で返すため、環境変数 TIMEZONE で指定されたタイムゾーンに変換）
            db_published_at = published_at
            if db_published_at:
                try:
                    from utils_v3 import format_datetime_filter
                    # fmt="%Y-%m-%d %H:%M:%S" で日時形式（タイムゾーン情報なし、T をスペースに置き換え）で返す
                    db_published_at = format_datetime_filter(db_published_at, fmt="%Y-%m-%d %H:%M:%S")
                    logger.debug(f"📡 published_at を変換: {published_at} → {db_published_at}")
                except Exception as e:
                    logger.warning(f"⚠️ published_at の変換失敗、元の値を使用: {e}")
                    # 失敗時は元の値を使用

        # video_url を構築
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        # 動画種別ごとの live_status マッピング
        # （YouTubeVideoClassifier の分類結果をそのまま使用）
        live_status_map = {
            VIDEO_TYPE_SCHEDULE: LIVE_STATUS_UPCOMING,
            VIDEO_TYPE_LIVE: LIVE_STATUS_LIVE,
            VIDEO_TYPE_COMPLETED: LIVE_STATUS_COMPLETED,
            VIDEO_TYPE_ARCHIVE: None  # アーカイブは live_status=None
        }
        live_status = live_status_map.get(video_type)

        # ★ 【新】既存動画の場合と新規の場合で処理を分ける
        is_update = existing is not None

        if is_update:
            # 【既存動画更新】コンテンツタイプが変わった場合のみ更新
            logger.info(f"🔄 Live動画を更新します: {title} (type={video_type}, status={live_status})")
            try:
                # update_video_status() を使用して type と status を更新
                self.db.update_video_status(
                    video_id=video_id,
                    content_type=video_type,
                    live_status=live_status
                )
                # published_at を更新（スケジュール時は開始予定時刻）
                self.db.update_published_at(video_id, db_published_at)

                logger.info(f"✅ Live動画を更新しました: {title}")
                logger.info(f"   新content_type: {video_type}")
                logger.info(f"   新live_status: {live_status}")
                success = True
            except Exception as e:
                logger.error(f"❌ Live動画の更新に失敗しました: {video_id} - {e}")
                success = False
        else:
            # 【新規登録】
            logger.info(f"📝 Live動画を登録します: {title} (type={video_type}, status={live_status})")

            try:
                success = self.db.insert_video(
                    video_id=video_id,
                    title=title,
                    video_url=video_url,
                    published_at=db_published_at,  # ★ スケジュール時は開始予定時刻（JST）、その他は公開日時
                    channel_name=channel_name,
                    thumbnail_url=thumbnail_url,
                    content_type=video_type,
                    live_status=live_status,
                    is_premiere=is_premiere,
                    source="youtube",
                    skip_dedup=True,  # LIVE は重複排除をスキップ（複数登録可）
                    # ★ 【新】基準時刻を保存
                    representative_time_utc=representative_time_utc,
                    representative_time_jst=representative_time_jst
                )

                if success:
                    logger.info(f"✅ Live動画を登録しました: {title}")
                    logger.info(f"   representative_time_utc: {representative_time_utc}")
                    logger.info(f"   representative_time_jst: {representative_time_jst}")

                    # ★ 【重要】SELFPOST モード時に Live 関連動画を自動選択
                    # SELFPOST では、スケジュール、配信開始、配信終了、アーカイブは自動投稿対象
                    if self.config.operation_mode == OperationMode.SELFPOST:
                        try:
                            self.db.update_selection(video_id, selected=True)
                            logger.info(f"📌 自動選択フラグを設定しました: {video_id}")
                        except Exception as e:
                            logger.warning(f"⚠️ 自動選択フラグ設定失敗（続行）: {video_id} - {e}")

                    return 1
                else:
                    logger.debug(f"⏭️  既に登録済み（スキップ）: {video_id}")
                    return 0

            except Exception as e:
                logger.error(f"❌ Live動画の登録に失敗しました: {video_id} - {e}")
                return 0

    def get_next_poll_interval_minutes(self) -> int:
        """
        次回のポーリング間隔を決定（動的ポーリング間隔戦略 v3.3.0+ 改訂版）

        複雑な3段階戦略：
        1. ACTIVE（schedule/live あり）: 短い固定間隔
        2. COMPLETED（completed のみ）: 1～3時間毎（段階的に拡大）
        3. NO_LIVE（いずれもなし）: ポーリングロジック休止（次回は RSS/WebSub 次第）
           → RSS/WebSub から新規動画がくるまで判定ロジックは実行しない

        Returns:
            int: 次回ポーリングまでの待機分数（分単位）、
                 または 0（ポーリング不要）
        """
        import time

        try:
            # DB から Live 関連動画の状態を確認
            all_videos = self.db.get_all_videos()
            live_videos = [
                v for v in all_videos
                if v.get("content_type") in [VIDEO_TYPE_SCHEDULE, VIDEO_TYPE_LIVE, VIDEO_TYPE_COMPLETED, VIDEO_TYPE_ARCHIVE]
            ]

            # ACTIVE か COMPLETED か NO_LIVE かを判定
            has_schedule_or_live = any(
                v.get("content_type") in [VIDEO_TYPE_SCHEDULE, VIDEO_TYPE_LIVE]
                for v in live_videos
            )
            has_completed_only = any(
                v.get("content_type") == VIDEO_TYPE_COMPLETED
                for v in live_videos
            ) and not has_schedule_or_live

            # 判定結果に基づいて間隔を決定
            if has_schedule_or_live:
                # ACTIVE: schedule または live 状態がある
                interval = self.config.youtube_live_poll_interval_active
                logger.debug(f"🔄 次回ポーリング間隔: {interval} 分（ACTIVE: schedule/live あり）")
                return interval

            elif has_completed_only:
                # COMPLETED のみ: 1～3時間毎（段階的に拡大）
                # archive化前の動画を追跡して確認間隔を拡大
                current_time = time.time()
                min_interval = self.config.youtube_live_poll_interval_completed_min
                max_interval = self.config.youtube_live_poll_interval_completed_max

                # 追跡中の completed 動画の最長未確認時間を計算
                max_age_minutes = 0
                for video in live_videos:
                    if video.get("content_type") == VIDEO_TYPE_COMPLETED:
                        video_id = video.get("video_id")
                        if video_id in self.archive_tracking:
                            last_poll = self.archive_tracking[video_id]["last_poll_time"]
                            age_minutes = (current_time - last_poll) / 60
                            max_age_minutes = max(max_age_minutes, age_minutes)

                # 未確認時間に基づいて次回間隔を決定（段階的に拡大）
                if max_age_minutes < min_interval:
                    # 初回：最短間隔で確認
                    interval = min_interval
                else:
                    # 段階的に最大間隔まで拡大（1時間 → 2時間 → 3時間）
                    elapsed_hours = max_age_minutes / 60
                    if elapsed_hours < 2:
                        interval = min(max_interval, int(min_interval * 1.5))
                    elif elapsed_hours < 4:
                        interval = int((min_interval + max_interval) / 2)
                    else:
                        interval = max_interval

                logger.debug(f"🔄 次回ポーリング間隔: {interval} 分（COMPLETED: completed のみ、段階拡大）")
                return interval

            else:
                # NO_LIVE: LIVE 関連動画がない
                # ★ 判定ロジック休止：RSS/WebSub から新規動画がくるまで待機
                # RSS/WebSub からの新規取得は独立して動作しているため、
                # Live ポーリング自体をスキップしても問題なし
                logger.debug(f"🔄 次回ポーリング: 休止（NO_LIVE: LIVE 関連動画なし、RSS/WebSub 次第）")
                # 判定ロジックを休止する場合は非常に長い間隔を返す
                # または 0 を返して呼び出し側で判断させる
                return 0  # 0 = ポーリング不要（RSS/WebSub のみで OK）

        except Exception as e:
            logger.warning(f"⚠️  ポーリング間隔決定エラー（デフォルト使用）: {e}")
            # デフォルト: ACTIVE 間隔を使用
            return self.config.youtube_live_poll_interval_active

    def poll_lives(self) -> int:
        """
        登録済みの Live 動画をポーリング

        処理内容：
        1. DB から Live 関連の全動画を取得
        2. 各動画の現在の状態を分類器で確認
        3. 状態遷移を検知して、以下の3つのイベントを検出・処理
           - 配信開始イベント: schedule/video → live
           - 配信終了イベント: live → completed
           - アーカイブ公開イベント: completed → archive
        4. 各イベントごとに DB 更新と自動投稿を実行

        Returns:
            int: 処理した件数（イベントを検知して処理した動画数）
        """
        try:
            # DB から Live 関連の全動画を取得
            # （content_type が "schedule", "live", "completed", "archive" のいずれか）
            all_videos = self.db.get_all_videos()
            live_videos = [
                v for v in all_videos
                if v.get("content_type") in [VIDEO_TYPE_SCHEDULE, VIDEO_TYPE_LIVE, VIDEO_TYPE_COMPLETED, VIDEO_TYPE_ARCHIVE]
            ]

            if not live_videos:
                logger.debug("ℹ️  ポーリング対象の Live 動画がありません")
                return 0

            logger.info(f"🔄 {len(live_videos)} 件の Live 動画をポーリング中...")

            processed_count = 0
            from youtube_core.youtube_video_classifier import get_video_classifier

            classifier = get_video_classifier(api_key=os.getenv("YOUTUBE_API_KEY"))

            for video in live_videos:
                video_id = video.get("video_id")
                if not video_id:
                    continue

                # 非 YouTube ID（Niconico など）をスキップ
                if not self._is_youtube_video_id(video_id):
                    continue

                # YouTube API で最新の状態を確認
                try:
                    result = classifier.classify_video(video_id)
                except Exception as e:
                    logger.debug(f"⏭️  分類エラー（スキップ）: {video_id} - {e}")
                    continue

                if not result.get("success"):
                    logger.debug(f"⏭️  分類失敗（スキップ）: {video_id}")
                    continue

                current_type = result.get("type")
                current_live_status = result.get("live_status")
                old_type = video.get("content_type")
                old_live_status = video.get("live_status")

                # ★ イベント検知: 複数の状態遷移パターンをチェック
                event_handled = False

                # イベント1: 配信開始 (schedule/video → live)
                if old_type in [VIDEO_TYPE_SCHEDULE, "video"] and current_type == VIDEO_TYPE_LIVE:
                    logger.info(f"🎬 【配信開始イベント】 {video_id}")
                    logger.info(f"   旧: type={old_type}, status={old_live_status}")
                    logger.info(f"   新: type={current_type}, status={current_live_status}")
                    self._on_live_started(video, result)
                    processed_count += 1
                    event_handled = True

                # イベント2: 配信終了 (live → completed または live → archive)
                # ★ 修正: completed だけでなく archive も含める (API のタイミングで completed を経由しないことあり)
                elif old_type == VIDEO_TYPE_LIVE and current_type in [VIDEO_TYPE_COMPLETED, VIDEO_TYPE_ARCHIVE]:
                    logger.info(f"🎬 【配信終了イベント】 {video_id}")
                    logger.info(f"   旧: type={old_type}, status={old_live_status}")
                    logger.info(f"   新: type={current_type}, status={current_live_status}")
                    self._on_live_ended(video, result, current_type, current_live_status)
                    processed_count += 1
                    event_handled = True

                # イベント3: アーカイブ公開 (completed → archive)
                # ★ 注意: _on_live_ended で既に archive に遷移した場合は処理済み
                elif old_type == VIDEO_TYPE_COMPLETED and current_type == VIDEO_TYPE_ARCHIVE:
                    logger.info(f"🎬 【アーカイブ公開イベント】 {video_id}")
                    logger.info(f"   旧: type={old_type}, status={old_live_status}")
                    logger.info(f"   新: type={current_type}, status={current_live_status}")
                    self._on_archive_available(video, result)
                    processed_count += 1
                    event_handled = True

                # イベント以外の状態遷移（表記揃えなど）
                if not event_handled and (current_type != old_type or current_live_status != old_live_status):
                    logger.info(f"📝 状態更新（イベントなし）: {video_id}")
                    logger.info(f"   旧: type={old_type}, status={old_live_status}")
                    logger.info(f"   新: type={current_type}, status={current_live_status}")
                    # DB を更新するが、自動投稿はしない
                    self.db.update_video_status(video_id, current_type, current_live_status)

            # ★ 新: 追跡情報の更新（completed と archive の状態管理）
            import time
            current_time = time.time()

            for video in live_videos:
                video_id = video.get("video_id")
                current_type = video.get("content_type")

                if current_type == VIDEO_TYPE_COMPLETED:
                    # COMPLETED 状態: 確認時刻を記録
                    if video_id not in self.archive_tracking:
                        self.archive_tracking[video_id] = {"last_poll_time": current_time, "archive_check_count": 0}
                    else:
                        self.archive_tracking[video_id]["last_poll_time"] = current_time

                elif current_type == VIDEO_TYPE_ARCHIVE:
                    # ARCHIVE 状態: 元 COMPLETED だった動画を最大4回まで追跡
                    if video_id in self.archive_tracking:
                        check_count = self.archive_tracking[video_id]["archive_check_count"]
                        if check_count < self.config.youtube_live_archive_check_count_max:
                            self.archive_tracking[video_id]["last_poll_time"] = current_time
                            self.archive_tracking[video_id]["archive_check_count"] = check_count + 1
                            logger.debug(f"📡 ARCHIVE 追跡: {video_id} ({check_count + 1}/{self.config.youtube_live_archive_check_count_max})")
                        else:
                            # 最大回数に達したため追跡終了
                            del self.archive_tracking[video_id]
                            logger.debug(f"✅ ARCHIVE 追跡終了: {video_id}（最大{self.config.youtube_live_archive_check_count_max}回に達した）")
                    else:
                        # 初回 ARCHIVE 認識時
                        self.archive_tracking[video_id] = {"last_poll_time": current_time, "archive_check_count": 1}
                        logger.debug(f"📡 ARCHIVE 追跡開始: {video_id}")

                elif current_type not in [VIDEO_TYPE_SCHEDULE, VIDEO_TYPE_LIVE]:
                    # LIVE 関連以外の状態：追跡を削除
                    if video_id in self.archive_tracking:
                        del self.archive_tracking[video_id]

            logger.info(f"✅ Live ポーリング完了: {processed_count} 件のイベントを処理しました")
            logger.debug(f"📝 現在の追跡中動画数: {len(self.archive_tracking)}")
            return processed_count

        except Exception as e:
            logger.error(f"❌ Live ポーリング中にエラーが発生しました: {e}")
            return 0

    def _should_autopost_live(self, content_type: str, live_status: Optional[str]) -> bool:
        """
        Live 動画の自動投稿判定

        APP_MODE に応じて自動的に判定ロジックを切り替える：
        - AUTOPOST モード: YOUTUBE_LIVE_AUTO_POST_MODE で判定
        - SELFPOST/その他: YOUTUBE_LIVE_AUTO_POST_SCHEDULE/LIVE/ARCHIVE フラグで判定

        Args:
            content_type: コンテンツ種別（"schedule", "live", "completed", "archive"）
            live_status: ライブステータス（"upcoming", "live", "completed", None）

        Returns:
            bool: 投稿すべき場合 True、投稿スキップすべき場合 False
        """
        try:
            # APP_MODE に基づいて使用するフラグを決定
            if self.config.operation_mode == OperationMode.AUTOPOST:
                # AUTOPOST モード: 統合モード値を使用
                mode = self.config.youtube_live_autopost_mode
                logger.debug(f"🔍 AUTOPOST モード: mode={mode}")

                # テーブル仕様 v1.0 セクション 4.2 参照
                if mode == "off":
                    return False
                elif mode == "all":
                    return content_type in [VIDEO_TYPE_SCHEDULE, VIDEO_TYPE_LIVE, VIDEO_TYPE_COMPLETED, VIDEO_TYPE_ARCHIVE]
                elif mode == "schedule":
                    return content_type == VIDEO_TYPE_SCHEDULE and live_status == LIVE_STATUS_UPCOMING
                elif mode == "live":
                    return content_type == VIDEO_TYPE_LIVE and live_status in (LIVE_STATUS_LIVE, LIVE_STATUS_COMPLETED)
                elif mode == "archive":
                    return content_type == VIDEO_TYPE_ARCHIVE
                else:
                    logger.warning(f"⚠️  無効な mode: {mode}")
                    return False
            else:
                # SELFPOST/DRY_RUN/COLLECT モード: 個別フラグで判定
                if content_type == VIDEO_TYPE_SCHEDULE:
                    return self.config.youtube_live_auto_post_schedule
                elif content_type == VIDEO_TYPE_LIVE:
                    return self.config.youtube_live_auto_post_live
                elif content_type == VIDEO_TYPE_COMPLETED or content_type == VIDEO_TYPE_ARCHIVE:
                    return self.config.youtube_live_auto_post_archive
                else:
                    return False

        except AttributeError as e:
            logger.warning(f"⚠️  自動投稿フラグが未設定（デフォルト=False）: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ 自動投稿判定エラー: {e}")
            return False

    def _is_youtube_video_id(self, video_id: str) -> bool:
        """
        YouTube 動画 ID 形式の検証

        YouTube 動画 ID は 11 文字の英数字（A-Z, a-z, 0-9, -, _）
        Niconico ID など他形式は False を返す

        Args:
            video_id: 検証対象の ID

        Returns:
            True: YouTube 形式, False: 他の形式
        """
        import re
        return bool(re.match(r"^[A-Za-z0-9_-]{11}$", video_id))

    def _on_live_started(self, video: Dict[str, Any], result: Dict[str, Any]) -> None:
        """
        配信開始イベントハンドラ

        schedule/video → live への状態遷移を処理

        Args:
            video: DB から取得した既存の動画情報
            result: YouTubeVideoClassifier.classify_video() の戻り値
        """
        video_id = video.get("video_id")
        title = video.get("title", "【ライブ配信開始】")

        try:
            # ★ DB を更新
            self.db.update_video_status(video_id, VIDEO_TYPE_LIVE, LIVE_STATUS_LIVE)
            logger.info(f"✅ DB更新: {video_id} → type=live, status=live")

            # ★ 自動投稿判定
            should_post = self._should_autopost_live(VIDEO_TYPE_LIVE, LIVE_STATUS_LIVE)
            if not should_post:
                logger.debug(f"⏭️  配信開始の自動投稿スキップ（設定により）: {video_id}")
                return

            # ★ 自動投稿: classification_type を "live" にセットして投稿
            logger.info(f"📤 配信開始イベントを自動投稿します: {title}")
            video_copy = dict(video)
            video_copy["classification_type"] = "live"  # テンプレート selection に使用
            video_copy["content_type"] = VIDEO_TYPE_LIVE
            video_copy["live_status"] = LIVE_STATUS_LIVE

            if self.plugin_manager:
                try:
                    results = self.plugin_manager.post_video_with_all_enabled(video_copy)
                    if any(results.values()):
                        self.db.mark_as_posted(video_id)
                        logger.info(f"✅ 配信開始イベントの自動投稿に成功しました: {video_id}")
                    else:
                        logger.warning(f"⚠️  配信開始イベントの自動投稿に失敗しました: {video_id}")
                except Exception as e:
                    logger.error(f"❌ 配信開始イベント投稿エラー: {video_id} - {e}")
            else:
                logger.warning(f"⚠️  plugin_manager が初期化されていません（投稿スキップ）")

        except Exception as e:
            logger.error(f"❌ 配信開始イベントハンドラエラー: {video_id} - {e}")

    def _on_live_ended(self, video: Dict[str, Any], result: Dict[str, Any],
                       current_type: str = None, current_live_status: Optional[str] = None) -> None:
        """
        配信終了イベントハンドラ

        live → completed または live → archive への状態遷移を処理

        Args:
            video: DB から取得した既存の動画情報
            result: YouTubeVideoClassifier.classify_video() の戻り値
            current_type: 現在の type (poll_lives から渡される、デフォルトは VIDEO_TYPE_COMPLETED)
            current_live_status: 現在の live_status (poll_lives から渡される)

        処理フロー:
        1. DB を current_type に更新
        2. classification_type を "completed" にセットして自動投稿
        3. もし current_type == "archive" なら、_on_archive_available も続けて呼ぶ
        """
        # 互換性のため、current_type が指定されていなければ VIDEO_TYPE_COMPLETED を使用
        if current_type is None:
            current_type = VIDEO_TYPE_COMPLETED
        if current_live_status is None:
            current_live_status = LIVE_STATUS_COMPLETED

        video_id = video.get("video_id")
        title = video.get("title", "【ライブ配信終了】")

        try:
            # ★ DB を更新
            self.db.update_video_status(video_id, current_type, current_live_status)
            logger.info(f"✅ DB更新: {video_id} → type={current_type}, status={current_live_status}")

            # ★ 自動投稿判定
            should_post = self._should_autopost_live(current_type, current_live_status)
            if not should_post:
                logger.debug(f"⏭️  配信終了の自動投稿スキップ（設定により）: {video_id}")
                # もし current_type == archive なら、ここでも _on_archive_available は呼ばない
                return

            # ★ 自動投稿: classification_type を "completed" にセットして投稿
            logger.info(f"📤 配信終了イベントを自動投稿します: {title}")
            video_copy = dict(video)
            video_copy["classification_type"] = "completed"  # テンプレート selection に使用
            video_copy["content_type"] = current_type
            video_copy["live_status"] = current_live_status

            if self.plugin_manager:
                try:
                    results = self.plugin_manager.post_video_with_all_enabled(video_copy)
                    if any(results.values()):
                        self.db.mark_as_posted(video_id)
                        logger.info(f"✅ 配信終了イベントの自動投稿に成功しました: {video_id}")
                    else:
                        logger.warning(f"⚠️  配信終了イベントの自動投稿に失敗しました: {video_id}")
                except Exception as e:
                    logger.error(f"❌ 配信終了イベント投稿エラー: {video_id} - {e}")
            else:
                logger.warning(f"⚠️  plugin_manager が初期化されていません（投稿スキップ）")

            # ★ 【新規】current_type が archive の場合、アーカイブ公開イベントも処理
            if current_type == VIDEO_TYPE_ARCHIVE:
                logger.info(f"🎬 【続: アーカイブ公開イベント】 {video_id} (配信終了の時点でアーカイブ化)")
                self._on_archive_available(video, result)

        except Exception as e:
            logger.error(f"❌ 配信終了イベントハンドラエラー: {video_id} - {e}")

    def _on_archive_available(self, video: Dict[str, Any], result: Dict[str, Any]) -> None:
        """
        アーカイブ公開イベントハンドラ

        completed → archive への状態遷移を処理

        Args:
            video: DB から取得した既存の動画情報
            result: YouTubeVideoClassifier.classify_video() の戻り値
        """
        video_id = video.get("video_id")
        title = video.get("title", "【ライブアーカイブ公開】")

        try:
            # ★ DB を更新
            self.db.update_video_status(video_id, VIDEO_TYPE_ARCHIVE, None)  # archive は live_status=None
            logger.info(f"✅ DB更新: {video_id} → type=archive, status=None")

            # ★ 自動投稿判定
            should_post = self._should_autopost_live(VIDEO_TYPE_ARCHIVE, None)
            if not should_post:
                logger.debug(f"⏭️  アーカイブ公開の自動投稿スキップ（設定により）: {video_id}")
                return

            # ★ 自動投稿: classification_type を "archive" にセットして投稿
            logger.info(f"📤 アーカイブ公開イベントを自動投稿します: {title}")
            video_copy = dict(video)
            video_copy["classification_type"] = "archive"  # テンプレート selection に使用
            video_copy["content_type"] = VIDEO_TYPE_ARCHIVE
            video_copy["live_status"] = None

            if self.plugin_manager:
                try:
                    results = self.plugin_manager.post_video_with_all_enabled(video_copy)
                    if any(results.values()):
                        self.db.mark_as_posted(video_id)
                        logger.info(f"✅ アーカイブ公開イベントの自動投稿に成功しました: {video_id}")
                    else:
                        logger.warning(f"⚠️  アーカイブ公開イベントの自動投稿に失敗しました: {video_id}")
                except Exception as e:
                    logger.error(f"❌ アーカイブ公開イベント投稿エラー: {video_id} - {e}")
            else:
                logger.warning(f"⚠️  plugin_manager が初期化されていません（投稿スキップ）")

        except Exception as e:
            logger.error(f"❌ アーカイブ公開イベントハンドラエラー: {video_id} - {e}")

    def set_plugin_manager(self, pm) -> None:
        """
        PluginManager を注入（自動投稿用）

        Args:
            pm: PluginManager インスタンス
        """
        self.plugin_manager = pm
        logger.debug(f"✅ LiveModule に PluginManager を注入しました")


def get_live_module(db: Optional[Database] = None, plugin_manager=None) -> LiveModule:
    """
    LiveModule インスタンスを取得（シングルトンパターン推奨）

    Args:
        db: Database インスタンス
        plugin_manager: PluginManager インスタンス

    Returns:
        LiveModule インスタンス
    """
    return LiveModule(db=db, plugin_manager=plugin_manager)
