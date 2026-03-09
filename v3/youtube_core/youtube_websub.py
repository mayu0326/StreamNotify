# -*- coding: utf-8 -*-

"""
StreamNotify - v3 YouTube WebSub 管理（Webhook版）

WebSub（Webhook）経由で本番サーバーから動画情報を取得・DB に保存する。
（画像処理は thumbnails/youtube_thumb_utils.py の YouTubeThumbPlugin で管理）

★ v3.2.0+ WebSub版：RSS の代わりに ProductionServerAPIClient を使用
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from image_manager import get_youtube_thumbnail_url

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


class YouTubeWebSub:
    """YouTube WebSub 取得・管理クラス（ProductionServerAPIClient を使用）"""

    def __init__(self, channel_id: str):
        """
        初期化

        Args:
            channel_id: YouTube チャンネル ID
        """
        self.channel_id = channel_id
        self._api_client = None
        self._websub_registered = False  # WebSub 登録済みフラグ

    def _get_api_client(self):
        """ProductionServerAPIClient を取得（遅延初期化）"""
        if self._api_client is None:
            try:
                from production_server_api_client import get_production_api_client

                self._api_client = get_production_api_client()
            except ImportError as e:
                logger.warning(
                    f"[WARN] ProductionServerAPIClient のインポート失敗: {e}"
                )
                return None
            except Exception as e:
                logger.warning(f"[WARN] ProductionServerAPIClient の初期化失敗: {e}")
                return None
        return self._api_client

    def health_check(self) -> bool:
        """
        ★ 【v3.2.0】WebSub サーバー接続確認

        ProductionServerAPIClient が利用可能かチェック

        Returns:
            bool: WebSub サーバーに接続可能な場合 True、不可の場合 False
        """
        try:
            api_client = self._get_api_client()
            if api_client is None:
                logger.warning(
                    "[WARN] WebSub health check 失敗: ProductionServerAPIClient が利用不可"
                )
                return False

            # API クライアントが正常に初期化されているか確認
            # （簡易版：オブジェクトが存在するかだけを確認）
            if hasattr(api_client, "get_websub_videos"):
                logger.debug(
                    "[SUCCESS] WebSub health check 成功: ProductionServerAPIClient は正常に動作しています"
                )
                return True
            else:
                logger.warning(
                    "⚠️ WebSub health check 失敗: ProductionServerAPIClient に get_websub_videos メソッドがありません"
                )
                return False

        except Exception as e:
            logger.warning(f"[WARN] WebSub health check エラー: {e}")
            return False

    def _ensure_websub_registered(self):
        """
        必要なら WebSub サーバーの /register に購読登録を 1 回だけ投げる。

        - settings.env / 環境変数 から:
          - WEBSUB_CLIENT_ID
          - WEBSUB_CALLBACK_URL
          を読み込む前提。
        """
        if self._websub_registered:
            return

        import os

        clientid = os.getenv("WEBSUB_CLIENT_ID")
        callbackurl = os.getenv("WEBSUB_CALLBACK_URL")

        if not clientid or not callbackurl:
            logger.warning(
                "⚠️ WebSub register をスキップ: "
                "WEBSUBCLIENTID または WEBSUBCALLBACKURL が未設定です"
            )
            return

        api_client = self._get_api_client()
        if api_client is None:
            logger.error(
                "[FAILURE] WebSub register をスキップ: ProductionServerAPIClient が利用不可です"
            )
            return

        # ProductionServerAPIClient 側の /register 呼び出しメソッドを利用
        try:
            ok = api_client.register_websub_client(
                clientid=clientid,
                channelid=self.channel_id,
                callbackurl=callbackurl,
            )
        except AttributeError:
            # メソッドがまだ実装されていないなど
            logger.error(
                "❌ WebSub register 失敗: register_websub_client メソッドが見つかりません"
            )
            return

        if ok:
            # debugモードに応じたログ出力
            debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
            if debug_mode:
                logger.info(
                    f"[SUCCESS] WebSub register 成功: clientid={clientid}, "
                    f"channelid={self.channel_id}, callbackurl={callbackurl}"
                )
            self._websub_registered = True
        else:
            logger.warning(
                "⚠️ WebSub register が失敗しました（ログを確認してください）"
            )

    def fetch_feed(self) -> List[Dict]:
        """
        WebSub（ProductionServerAPI）からビデオ情報を取得・パース

        Returns:
            新着動画のリスト（最新順）
        """
        try:
            # まず WebSub 登録を保証する（成功すれば以降の呼び出しではスキップ）
            self._ensure_websub_registered()

            api_client = self._get_api_client()
            if api_client is None:
                logger.error(
                    "[FAILURE] ProductionServerAPIClient が利用不可（WebSub経由の取得失敗）"
                )
                return []

            youtube_logger = logging.getLogger("YouTubeLogger")
            logger.debug(
                f"📡 WebSub から動画情報を取得します（チャンネル: {self.channel_id}）"
            )

            # ProductionServerAPI から動画を取得
            items = api_client.get_websub_videos(
                channel_id=self.channel_id,
                limit=15,  # 最新 15 件まで
            )

            if not items:
                youtube_logger.debug("[INFO] WebSub から動画情報を取得できませんでした")
                return []

            videos = []
            for item in items:
                try:
                    # API レスポンスから必要な情報を抽出
                    video_id = item.get("video_id", "")
                    title = item.get("title", "（タイトル不明）")
                    video_url = (
                        item.get("video_url")
                        or item.get("url")
                        or f"https://www.youtube.com/watch?v={video_id}"
                    )
                    published_at = item.get("published_at", "")
                    channel_name = item.get("channel_name", "")

                    # ★ v3.2.0: WebSub から取得した channel_name が空の場合、フォールバックで取得
                    # （API 呼び出しを最小化するため、API に頼らず自動生成フォールバック）
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
                                    f"✅ WebSub の channel_name が空だったため、チャンネル ID からフォールバック: {channel_name}"
                                )
                        except Exception as e:
                            logger.debug(
                                f"⚠️ チャンネル ID からのフォールバック失敗: {e}"
                            )

                    if not video_id:
                        logger.warning(
                            f"⚠️ video_id が不正です。アイテムをスキップします: {item}"
                        )
                        continue

                    # ★ 重要: WebSub から取得した published_at は JST 形式（またはUTC）
                    # 形式を統一するため、必要に応じて JST に変換
                    published_at_jst = self._ensure_jst_format(published_at)

                    # ★ 重要: サムネイル URL を取得
                    thumbnail_url = get_youtube_thumbnail_url(video_id)
                    if not thumbnail_url:
                        logger.warning(
                            f"⚠️ WebSub {video_id}: サムネイル URL が取得できませんでした"
                        )
                    else:
                        logger.debug(f"✅ WebSub {video_id}: サムネイル URL 取得完了")

                    video = {
                        "video_id": video_id,
                        "title": title,
                        "video_url": video_url,
                        "published_at": published_at_jst,
                        "channel_name": channel_name,
                        "thumbnail_url": thumbnail_url,
                    }
                    videos.append(video)
                    logger.debug(
                        f"[WebSub parse] {video_id}: video辞書作成完了 - thumbnail_url: {thumbnail_url}"
                    )

                except Exception as e:
                    logger.warning(f"⚠️ WebSub アイテムのパース失敗: {e}")
                    continue

            youtube_logger.info(f"📡 WebSub から {len(videos)} 個の動画を取得しました")
            # ★ デバッグ: 各動画の thumbnail_url を確認
            for v in videos[:3]:  # 最初の 3 件
                logger.debug(
                    f"[WebSub fetch_feed] {v.get('video_id')}: thumbnail_url = {v.get('thumbnail_url')}"
                )
            return videos

        except Exception as e:
            logger.error(f"[FAILURE] WebSub 取得に失敗しました: {e}")
            return []

    def _ensure_jst_format(self, published_at: str) -> str:
        """
        published_at を JST 形式に統一

        Args:
            published_at: 日時文字列（UTC またはISO形式）

        Returns:
            JST 形式の日時文字列
        """
        if not published_at:
            return ""

        try:
            # 既に JST 形式か確認（+09:00 または Z でなければ JST と仮定）
            if "+09:00" in published_at or published_at.endswith("+9:00"):
                return published_at

            # UTC → JST 変換
            utc_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            jst_time = utc_time.astimezone(timezone(timedelta(hours=9))).replace(
                tzinfo=None
            )
            published_at_jst = jst_time.isoformat()
            logger.debug(
                f"📡 WebSub 日時を JST に変換: {published_at} → {published_at_jst}"
            )
            return published_at_jst

        except Exception as e:
            logger.warning(f"⚠️ WebSub 日時の JST 変換失敗、元の値を使用: {e}")
            return published_at

    def save_to_db(self, database, classifier=None, live_module=None) -> tuple:
        """
        WebSub から取得した動画を DB に保存

        ⚠️ NOTE: 新規動画の画像ダウンロード・保存は
        thumbnails/youtube_thumb_utils.py の YouTubeThumbPlugin で実行されます。

        ★ v3.2.0+ YouTube API優先: WebSub登録後、YouTube API で最新情報を確認し、
           scheduledStartTime が存在する場合は上書きします。

        ★ v3.2.0+ YouTubeVideoClassifier + LiveModule 統合:
           - YouTubeVideoClassifier で動画を分類（schedule/live/completed/archive vs 通常動画）
           - Live関連 → LiveModule.register_from_classified() で登録
           - 通常動画 → 既存処理で続行

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

        youtube_logger.info(
            f"[YouTube WebSub] 取得した {len(videos)} 個の動画を DB に照合しています..."
        )

        # 除外動画リストを取得
        try:
            from deleted_video_cache import get_deleted_video_cache

            deleted_cache = get_deleted_video_cache()
        except ImportError:
            youtube_logger.warning("deleted_video_cache モジュールが見つかりません")
            deleted_cache = None

        # ★ 新: 重複排除ロジック（video_id + タイトル + live_status + チャンネル名 の4つが同じ場合のみ）
        # v3.2.0+: 同じ動画の完全な重複を検出（4つの条件すべてが同じケースはレア）
        # 理由：video_id が異なれば別の動画、live_status が異なれば別のイベント状態
        try:
            from config import get_config

            config = get_config("settings.env")
            youtube_dedup_enabled = getattr(
                config, "youtube_dedup_enabled", True
            )  # デフォルト: True
        except Exception:
            youtube_dedup_enabled = True  # エラー時はデフォルト有効

        # 動画をグループ化（video_id + タイトル + live_status + チャンネル名）
        video_groups: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = {}
        for video in videos:
            # グループキー：video_id + タイトル + live_status + チャンネル名
            group_key = (
                video.get("video_id", ""),
                video.get("title", ""),
                video.get("live_status", "none"),  # デフォルト: "none"
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
                        f"live_status={live_status}, channel={channel_name} → "
                        f"{len(group_videos)}件中1件を使用"
                    )
        else:
            # 重複排除無効の場合、すべての動画を処理
            filtered_videos = videos
            if not youtube_dedup_enabled:
                youtube_logger.debug(
                    f"ℹ️ 重複排除が無効のため、{len(videos)}件すべてを処理します"
                )

        youtube_logger.debug(f"[SUCCESS] 重複排除後の動画数: {len(filtered_videos)}件")

        # YouTube API プラグインを取得（API有効時のみ）
        youtube_api_plugin = None
        try:
            from plugin_manager import get_plugin_manager

            plugin_mgr = get_plugin_manager()
            youtube_api_plugin = plugin_mgr.get_plugin("youtube_api_plugin")
            if youtube_api_plugin and youtube_api_plugin.is_available():
                youtube_logger.debug(
                    "✅ YouTube API プラグイン が利用可能です（WebSub の情報を API で確認します）"
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
            for video in filtered_videos:
                # ★ 【v3.2.0】新規動画のみを処理
                # 既存動画は処理をスキップし、API 呼び出しを削減
                existing_video = database.get_video_by_id(video["video_id"])
                if existing_video:
                    youtube_logger.debug(
                        f"ℹ️ 既存動画のため、スキップします: {video['title']}"
                    )
                    existing_count += 1
                    continue  # 既存動画は詳細情報の再取得をしない（クォータ削減）

                # 除外動画リスト確認
                if deleted_cache and deleted_cache.is_deleted(
                    video["video_id"], source="youtube"
                ):
                    youtube_logger.info(
                        f"⏭️ 除外動画リスト登録済みのため、スキップします: {video['title']}"
                    )
                    blacklist_skip_count += 1
                    continue

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
                                    api_scheduled_start_time = api_published_at_jst
                                    youtube_logger.info(
                                        f"📡 API確認: scheduledStartTime を使用（UTC→JST変換）:"
                                        f" {api_published_at} → {api_published_at_jst}"
                                    )
                                except Exception as e:
                                    api_scheduled_start_time = api_published_at
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
                                    api_scheduled_start_time = api_published_at_jst
                                    youtube_logger.info(
                                        f"📡 API確認: actualStartTime を使用（UTC→JST変換）:"
                                        f" {api_published_at} → {api_published_at_jst}"
                                    )
                                except Exception as e:
                                    api_scheduled_start_time = api_published_at
                                    youtube_logger.warning(
                                        f"⚠️ UTC→JST変換失敗、元の値を使用: {e}"
                                    )
                            elif snippet.get("publishedAt"):
                                api_published_at = snippet["publishedAt"]
                                youtube_logger.debug(
                                    f"📡 API確認: publishedAt を使用: {api_published_at}"
                                )
                    except Exception as e:
                        youtube_logger.debug(f"⚠️ YouTube API での詳細取得失敗: {e}")

                # ★ 重要: 先に分類を行い、Live 系か通常動画か判定
                # これにより、Live系は通常の insert_video をスキップ、LiveModule に任せられる
                video_type = None
                classification_result = None

                if classifier and live_module:
                    try:
                        classification_result = classifier.classify_video(
                            video["video_id"]
                        )
                        if classification_result.get("success"):
                            video_type = classification_result.get("type")
                            youtube_logger.debug(
                                f"[VIDEO] 動画を分類: {video.get('title')} (type={video_type})Sync"
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
                                    f"✅ Live動画をLiveModuleで登録完了: {video_type}（通常動画処理はスキップ）"
                                )
                        except Exception as e:
                            youtube_logger.error(
                                f"❌ Live動画の LiveModule 登録失敗: {e}"
                            )
                else:
                    # 通常動画（video / premiere）のみ、通常の insert_video を実行
                    final_published_at = (
                        api_scheduled_start_time
                        if api_scheduled_start_time
                        else video["published_at"]
                    )

                    is_new = database.insert_video(
                        video_id=video["video_id"],
                        title=video["title"],
                        video_url=video["video_url"],
                        published_at=final_published_at,
                        channel_name=video["channel_name"],
                        thumbnail_url=thumbnail_url,
                        source="youtube",
                    )
                    if is_new:
                        saved_count += 1
                        youtube_logger.debug(
                            f"[YouTube WebSub] 新規動画を保存: {video['title']} (type={video_type})"
                        )
                    else:
                        youtube_logger.debug(
                            f"[YouTube WebSub] 既存動画です: {video['title']}"
                        )

            summary = f"[SUCCESS] 保存完了: 新規 {saved_count}, 既存 {existing_count}"
            if live_registered_count > 0:
                summary += f", Live登録 {live_registered_count}"
            if blacklist_skip_count > 0:
                summary += f", 除外動画リスト {blacklist_skip_count}"

            if saved_count > 0 or live_registered_count > 0:
                youtube_logger.info(summary)
            elif blacklist_skip_count > 0:
                youtube_logger.info(summary)
            else:
                youtube_logger.info(f"ℹ️ 新着動画はありません")

        finally:
            # ロガーを元に戻す
            db_module.logger = original_logger

        summary = f"新規 {saved_count} 件 / 既存 {existing_count} 件"
        if live_registered_count > 0:
            summary += f" / Live登録 {live_registered_count} 件"
        if blacklist_skip_count > 0:
            summary += f" / 除外 {blacklist_skip_count} 件"
        youtube_logger.info(f"[YouTube WebSub] 保存結果: {summary}")

        return (saved_count, live_registered_count)



def get_youtube_websub(channel_id: str) -> YouTubeWebSub:
    """YouTubeWebSub インスタンスを取得するヘルパー"""
    return YouTubeWebSub(channel_id)
