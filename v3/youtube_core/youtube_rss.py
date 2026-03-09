# -*- coding: utf-8 -*-

"""
StreamNotify - v3 YouTube RSS 管理

YouTube チャンネルの RSS を取得・パース・DB に保存する。
（画像処理は thumbnails/youtube_thumb_utils.py の YouTubeThumbPlugin で管理）
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import feedparser
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
                # ★ 重要: RSS の published_at は UTC 形式（例: 2025-12-28T18:00:00Z）
                # これを JST に変換してから保存
                rss_published_at = entry.published

                # UTC → JST 変換
                try:
                    utc_time = datetime.fromisoformat(
                        rss_published_at.replace("Z", "+00:00")
                    )
                    jst_time = utc_time.astimezone(
                        timezone(timedelta(hours=9))
                    ).replace(tzinfo=None)
                    published_at_jst = jst_time.isoformat()
                    logger.debug(
                        f"📡 RSS 日時を JST に変換: {rss_published_at} → {published_at_jst}"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ RSS 日時の JST 変換失敗、元の値を使用: {e}")
                    published_at_jst = rss_published_at

                # ★ v3.2.0: channel_name が空の場合、キャッシュまたは API から取得
                channel_name = entry.author if hasattr(entry, "author") else ""
                if not channel_name:
                    try:
                        # YouTube API キャッシュから channelTitle を取得
                        from plugins.youtube.youtube_api_plugin import YouTubeAPIPlugin

                        api_plugin = YouTubeAPIPlugin()

                        if api_plugin.is_available():
                            # API から動画詳細を取得
                            details = api_plugin.fetch_video_detail(entry.yt_videoid)
                            if details:
                                video_info = api_plugin._extract_video_info(details)
                                channel_name = video_info.get("channel_name", "")
                                if channel_name:
                                    logger.debug(
                                        f"✅ YouTube API から channel_name を取得: {channel_name}"
                                    )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ YouTube API からの channel_name 取得失敗: {e}"
                        )

                    # API でも取得できない場合はフォールバック
                    if not channel_name:
                        try:
                            from config import get_config

                            config = get_config("settings.env")
                            channel_id = (
                                config.youtube_channel_id
                                if hasattr(config, "youtube_channel_id")
                                else ""
                            )
                            if channel_id:
                                channel_name = f"Channel ({channel_id[:8]}...)"
                                logger.debug(
                                    f"✅ RSS の channel_name が空だったため、チャンネル ID からフォールバック: {channel_name}"
                                )
                        except Exception as e:
                            logger.debug(
                                f"⚠️ チャンネル ID からのフォールバック失敗: {e}"
                            )

                video = {
                    "video_id": entry.yt_videoid,
                    "title": entry.title,
                    "video_url": entry.link,
                    "published_at": published_at_jst,  # ★ JST 変換済みの値を使用
                    "channel_name": channel_name,
                }
                videos.append(video)

            youtube_logger = logging.getLogger("YouTubeLogger")
            youtube_logger.info(f"RSS から {len(videos)} 個の動画を取得しました")
            return videos

        except Exception as e:
            logger.error(f"RSS 取得に失敗しました: {e}")
            return []

    def save_to_db(self, database, classifier=None, live_module=None) -> tuple:
        """
        RSS から取得した動画を DB に保存

        ⚠️ NOTE: 新規動画の画像ダウンロード・保存は
        thumbnails/youtube_thumb_utils.py の YouTubeThumbPlugin で実行されます。

        ★ v3.2.0+ YouTube API優先: RSS登録後、YouTube API で最新情報を確認し、
           scheduledStartTime が存在する場合は上書きします。

        ★ v3.2.0+ YouTubeVideoClassifier + LiveModule 統合:
           - YouTubeVideoClassifier で動画を分類（schedule/live/completed/archive vs 通常動画）
           - Live関連 → LiveModule.register_from_classified() で登録
           - 通常動画 → 既存処理で続行

        ★ v3.2.0+ 重複排除: video_id + タイトル + live_status + チャンネル名 が同じ場合のみ除外

        Args:
            database: Database オブジェクト
            classifier: YouTubeVideoClassifier インスタンス（オプション）
            live_module: LiveModule インスタンス（オプション）

        Returns:
            (保存された動画数, Live登録数) のタプル
        """
        videos = self.fetch_feed()
        saved_count = 0
        existing_count = 0
        blacklist_skip_count = 0
        live_registered_count = 0
        youtube_logger = logging.getLogger("YouTubeLogger")

        # ★ 新: 重複排除ロジック（video_id + タイトル + live_status + チャンネル名）
        # RSS データに video 分類から live_status を付与した後、重複排除を実行
        try:
            from config import get_config

            config = get_config("settings.env")
            youtube_dedup_enabled = getattr(
                config, "youtube_dedup_enabled", True
            )  # デフォルト: True
        except Exception:
            youtube_dedup_enabled = True  # エラー時はデフォルト有効

        youtube_logger.info(
            f"[YouTube RSS] 取得した {len(videos)} 個の動画を DB に照合しています..."
        )

        # ★ 新: 除外動画リストを取得
        try:
            from deleted_video_cache import get_deleted_video_cache

            deleted_cache = get_deleted_video_cache()
        except ImportError:
            youtube_logger.warning("deleted_video_cache モジュールが見つかりません")
            deleted_cache = None

        # ★ v3.2.0+: 重複排除処理（RSS の videos が取得された直後に実行）
        # video_id + タイトル + live_status + チャンネル名 が同じ場合のみ除外
        # NOTE: このポイントでは live_status はまだ "none" （classifier で分類される前）
        # 最終的な live_status は分類後に確定するため、フィルタリング後に分類を実行
        video_groups: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = {}
        for video in videos:
            # グループキー：video_id + タイトル + live_status + チャンネル名
            # この段階では live_status = "none"（まだ分類前）
            group_key = (
                video.get("video_id", ""),
                video.get("title", ""),
                "none",  # RSS 取得時はまだ分類前のため "none"
                video.get("channel_name", ""),
            )
            if group_key not in video_groups:
                video_groups[group_key] = []
            video_groups[group_key].append(video)

        # 重複排除を適用
        filtered_videos = []
        if youtube_dedup_enabled and len(video_groups) > 0:
            youtube_logger.debug(
                f"🔄 YouTube重複排除: {len(video_groups)}個のグループを処理中..."
            )

            for (
                video_id,
                title,
                live_status,
                channel_name,
            ), group_videos in video_groups.items():
                if len(group_videos) == 1:
                    # グループに1つだけの場合はそのまま追加
                    filtered_videos.append(group_videos[0])
                else:
                    # 複数ある場合（実質的にはレアケース）
                    # video_id + タイトル + live_status + チャンネル が完全に同じ場合は最初の1件のみ追加
                    filtered_videos.append(group_videos[0])
                    youtube_logger.info(
                        f"📊 重複検知（完全一致）: video_id={video_id}, title={title}, "
                        f"channel={channel_name} → {len(group_videos)}件中1件を使用"
                    )
        else:
            # 重複排除無効の場合、すべての動画を処理
            filtered_videos = videos
            if not youtube_dedup_enabled:
                youtube_logger.debug(
                    f"ℹ️ 重複排除が無効のため、{len(videos)}件すべてを処理します"
                )

        youtube_logger.debug(f"✅ 重複排除後の動画数: {len(filtered_videos)}件")

        # 重複排除後の動画リストで処理を続行
        videos = filtered_videos

        # ★ 新: YouTube API プラグインを取得（API有効時のみ）
        youtube_api_plugin = None
        try:
            from plugin_manager import get_plugin_manager

            plugin_mgr = get_plugin_manager()
            youtube_api_plugin = plugin_mgr.get_plugin("youtube_api_plugin")
            if youtube_api_plugin and youtube_api_plugin.is_available():
                youtube_logger.debug(
                    "✅ YouTube API プラグイン が利用可能です（RSS の情報を API で確認します）"
                )
            else:
                youtube_api_plugin = None
        except Exception as e:
            youtube_logger.debug(f"⚠️ YouTube API プラグイン未利用: {e}")

        # database モジュールのロガーを一時的に YouTubeLogger に切り替え
        import database as db_module

        original_logger = db_module.logger
        db_module.logger = youtube_logger

        try:
            for video in videos:
                # ★ 新: 除外動画リスト確認
                if deleted_cache and deleted_cache.is_deleted(
                    video["video_id"], source="youtube"
                ):
                    youtube_logger.info(
                        f"⏭️ 除外動画リスト登録済みのため、スキップします: {video['title']}"
                    )
                    blacklist_skip_count += 1
                    continue

                # ★ 【v3.2.0】新規動画のみを ID のみで登録
                # 既存動画は処理をスキップし、API 呼び出しを削減
                existing_video = database.get_video_by_id(video["video_id"])
                if existing_video:
                    youtube_logger.debug(
                        f"ℹ️ 既存動画のため、スキップします: {video['title']}"
                    )
                    continue  # 既存動画は詳細情報の再取得をしない（クォータ削減）

                # サムネイル URL を取得（多品質フォールバック）
                thumbnail_url = get_youtube_thumbnail_url(video["video_id"])

                # ★ 重要: YouTube API プラグイン を優先実行
                # API から取得した scheduledStartTime を published_at として使用
                api_published_at = None
                api_scheduled_start_time = (
                    None  # ★ 新: scheduledStartTime を別途保存（上書き判定用）
                )

                if youtube_api_plugin:
                    try:
                        details = youtube_api_plugin.fetch_video_detail(
                            video["video_id"]
                        )
                        if details:
                            live_details = details.get("liveStreamingDetails", {})
                            snippet = details.get("snippet", {})

                            # API優先: scheduledStartTime > actualStartTime > publishedAt
                            # ★ 重要: API の時刻は UTC なので、JST に変換してから使用
                            if live_details.get("scheduledStartTime"):
                                api_published_at = live_details["scheduledStartTime"]
                                # UTC から JST に変換（+9時間）
                                try:
                                    utc_time = datetime.fromisoformat(
                                        api_published_at.replace("Z", "+00:00")
                                    )
                                    jst_time = utc_time.astimezone(
                                        timezone(timedelta(hours=9))
                                    ).replace(tzinfo=None)
                                    api_published_at_jst = jst_time.isoformat()
                                    api_scheduled_start_time = (
                                        api_published_at_jst  # JST 版を保存
                                    )
                                    youtube_logger.info(
                                        f"📡 API確認: scheduledStartTime を使用（UTC→JST変換）: {api_published_at} → {api_published_at_jst}"
                                    )
                                except Exception as e:
                                    api_scheduled_start_time = (
                                        api_published_at  # 変換失敗時は元の値を使用
                                    )
                                    youtube_logger.warning(
                                        f"⚠️ UTC→JST変換失敗、元の値を使用: {e}"
                                    )
                            elif live_details.get("actualStartTime"):
                                api_published_at = live_details["actualStartTime"]
                                # UTC から JST に変換
                                try:
                                    utc_time = datetime.fromisoformat(
                                        api_published_at.replace("Z", "+00:00")
                                    )
                                    jst_time = utc_time.astimezone(
                                        timezone(timedelta(hours=9))
                                    ).replace(tzinfo=None)
                                    api_published_at_jst = jst_time.isoformat()
                                    api_scheduled_start_time = (
                                        api_published_at_jst  # JST 版を保存
                                    )
                                    youtube_logger.info(
                                        f"📡 API確認: actualStartTime を使用（UTC→JST変換）: {api_published_at} → {api_published_at_jst}"
                                    )
                                except Exception as e:
                                    api_scheduled_start_time = (
                                        api_published_at  # 変換失敗時は元の値を使用
                                    )
                                    youtube_logger.warning(
                                        f"⚠️ UTC→JST変換失敗、元の値を使用: {e}"
                                    )
                            elif snippet.get("publishedAt"):
                                api_published_at = snippet["publishedAt"]
                                youtube_logger.debug(
                                    f"📡 API確認: publishedAt を使用: {api_published_at}"
                                )
                        else:
                            youtube_logger.warning(
                                f"⚠️ API で {video['video_id']} の詳細が取得できません（RSS 日時を使用）"
                            )
                    except Exception as e:
                        youtube_logger.warning(
                            f"⚠️ API 確認処理でエラー（RSS日時を使用）: {e}"
                        )

                # ★ 重要: 先に分類を行い、Live 系か通常動画か判定
                # これにより、Live系は通常の insert_video をスキップ、LiveModule に任せられる
                # ★ 【修正 v3.2.0】既に classifier.classify_video() で API を 1 回呼び出し済み
                # → insert_video() では classifier 結果を再利用し、二重 API 呼び出しを防止
                video_type = None
                classification_result = None

                if classifier and live_module:
                    try:
                        # ★ API 呼び出し #1: 分類用（1 ユニット消費）
                        classification_result = classifier.classify_video(
                            video["video_id"]
                        )
                        if classification_result.get("success"):
                            video_type = classification_result.get("type")
                            youtube_logger.debug(
                                f"🎬 動画を分類: {video.get('title')} (type={video_type})"
                            )
                        else:
                            youtube_logger.debug(
                                f"⏭️ 分類失敗（通常動画として処理）: {video['video_id']} - {classification_result.get('error')}"
                            )
                            video_type = "video"  # デフォルトは通常動画
                    except Exception as e:
                        youtube_logger.warning(
                            f"⚠️ YouTube VideoClassifier 呼び出しエラー（通常動画として処理）: {e}"
                        )
                        video_type = "video"  # エラー時もデフォルトは通常動画

                # ★ Live 系（schedule/live/completed/archive）の場合、通常の insert は実行しない
                # LiveModule.register_from_classified() が すべて処理する
                if video_type in ["schedule", "live", "completed", "archive"]:
                    # Live 関連 → LiveModule に完全に処理させる
                    if classification_result:
                        youtube_logger.info(
                            f"🎬 Live関連動画を LiveModule に完全委譲: {video.get('title')} (type={video_type})"
                        )
                        try:
                            live_result = live_module.register_from_classified(
                                classification_result
                            )
                            if live_result > 0:
                                live_registered_count += live_result
                                youtube_logger.info(
                                    f"✅ Live動画をLiveModuleで登録完了: {video_type}（通常動画処理はスキップ、追加 API 呼び出しなし）"
                                )
                        except Exception as e:
                            youtube_logger.error(
                                f"❌ Live動画の LiveModule 登録失敗: {e}"
                            )
                else:
                    # 通常動画（video / premiere）のみ、通常の insert_video を実行
                    # ★ 【修正 v3.2.0】classification_result から分類情報を取得・再利用
                    # insert_video() 内の post_video() で再度 API を叩くことを防止
                    final_published_at = (
                        api_scheduled_start_time
                        if api_scheduled_start_time
                        else video["published_at"]
                    )

                    # ★ 【重要】YouTubeVideoClassifier から representative_time_utc を取得
                    # classification_result が成功していれば、そこから取得
                    # 失敗していれば、フォールバックで published_at を使用
                    representative_time_utc = None
                    representative_time_jst = (
                        final_published_at  # JST版は final_published_at を使用
                    )

                    if classification_result and classification_result.get("success"):
                        # classifier から representative_time_utc を取得
                        rep_time_utc = classification_result.get(
                            "representative_time_utc"
                        )
                        if rep_time_utc:
                            representative_time_utc = rep_time_utc
                            # UTC → JST に変換
                            try:
                                from utils_v3 import format_datetime_filter

                                representative_time_jst = format_datetime_filter(
                                    rep_time_utc, fmt="%Y-%m-%d %H:%M:%S"
                                )
                                youtube_logger.debug(
                                    f"📡 YouTubeVideoClassifier から representative_time を取得: {rep_time_utc} → {representative_time_jst}"
                                )
                            except Exception as e:
                                youtube_logger.warning(
                                    f"⚠️ representative_time_utc の JST 変換失敗: {e}"
                                )
                                representative_time_jst = (
                                    final_published_at  # フォールバック
                                )

                            # フォールバック: classifier が失敗したか representative_time_utc が空の場合
                            representative_time_utc = video.get(
                                "published_at"
                            )  # RSS では already JST
                            youtube_logger.debug(
                                "📡 フォールバック: RSS の published_at を representative_time として使用"
                            )

                    # ★ 注意: insert_video() 内で post_video() が呼ばれ、追加の API 呼び出しが発生する可能性があります
                    # post_video() が classification_result を参照できるようにするための準備が必要です
                    is_new = database.insert_video(
                        video_id=video["video_id"],
                        title=video["title"],
                        video_url=video["video_url"],
                        published_at=final_published_at,  # ★ API優先の日時を使用（JST 変換済み）
                        channel_name=video["channel_name"],
                        thumbnail_url=thumbnail_url,
                        source="youtube",
                        # ★ 【重要】YouTubeVideoClassifier から取得した基準時刻を保存
                        representative_time_utc=representative_time_utc,
                        representative_time_jst=representative_time_jst,
                    )

                    if is_new:
                        saved_count += 1
                        youtube_logger.debug(
                            f"[YouTube RSS] 新動画を DB に保存しました: {video['title']} (type={video_type})"
                        )
                    else:
                        youtube_logger.debug(
                            f"[YouTube RSS] 既存動画です: {video['title']}"
                        )

            summary = f"✅ 保存完了: 新規 {saved_count}, 既存 {existing_count}"
            if live_registered_count > 0:
                summary += f", Live登録 {live_registered_count}"
            if blacklist_skip_count > 0:
                summary += f", 除外動画リスト {blacklist_skip_count}"

            if saved_count > 0 or live_registered_count > 0:
                youtube_logger.info(summary)
            elif blacklist_skip_count > 0:
                youtube_logger.info(summary)
            else:
                youtube_logger.info("ℹ️ 新着動画はありません")

        finally:
            # ロガーを元に戻す
            db_module.logger = original_logger

        return (saved_count, live_registered_count)



def get_youtube_rss(channel_id: str) -> YouTubeRSS:
    """YouTube RSS オブジェクトを取得"""
    return YouTubeRSS(channel_id)
