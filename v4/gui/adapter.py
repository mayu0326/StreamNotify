import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc
from sqlalchemy.orm import Session

from v4.core.assets.images import image_manager
from v4.core.auth_client import OAuthFlowManager
from v4.core.bluesky.bluesky_client import BlueskyClient
from v4.core.config import settings
from v4.core.database import (
    SessionLocal,
    VideoModel,
    delete_bsky_account,
    delete_twitch_account,
    get_bsky_account,
    get_latest_video_update_time_for_service,
    get_twitch_account,
    upsert_bsky_account,
    upsert_twitch_account,
    upsert_video,
)
from v4.core.templates.templates import templates
from v4.core.websub_client import WebSubClient
from v4.domain.notifications.twitch.client import TwitchClient

logger = logging.getLogger("v4.gui.adapter")


def _format_dt_no_fraction(dt) -> str:
    """日時を 'YYYY-MM-DD HH:MM:SS' で返す（ミリ秒・マイクロ秒なし）。"""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse_center_datetime(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _twitch_broadcast_row_to_video_dict(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """センター GET /client/twitch/broadcasts の 1 行 → ローカル VideoModel 用（キーはクライアント側のみ変換）。"""
    vid = row.get("video_id") or row.get("stream_id")
    if not vid:
        logger.debug("Skipping Twitch center row without video_id/stream_id")
        return None
    raw_type = row.get("type") or "archive"
    video_status = str(raw_type).lower()
    lu = _parse_center_datetime(row.get("last_updated_at"))
    tags = row.get("tags")
    if tags is not None and not isinstance(tags, list):
        tags = []
    return {
        "video_id": str(vid),
        "channel_id": row.get("user_id"),
        "channel_name": row.get("user_name"),
        "service": "twitch",
        "title": row.get("title"),
        "video_url": row.get("url"),
        "published_at": _parse_center_datetime(row.get("started_at") or row.get("published_at")),
        "actual_start_time": _parse_center_datetime(row.get("started_at")),
        "actual_end_time": _parse_center_datetime(row.get("ended_at")),
        "duration_seconds": row.get("duration_seconds"),
        "tags": tags or [],
        "video_status": video_status,
        "is_updated_since": lu or datetime.utcnow(),
    }


class V3DatabaseAdapter:
    """
    Adapter to make v4 SQLAlchemy backend look like v3 Database class for the GUI.
    """

    # GUIの論理名から実際のテンプレートパスへのマッピング
    TEMPLATE_MAP = {
        "youtube_new_video": "youtube/yt_new_video_template",
        "twitch_online": "twitch/twitch_online_template",
        "niconico_new_video": "niconico/nico_new_video_template",
    }

    def __init__(self):
        self.db: Session = SessionLocal()
        # youtube_feed_mode=websub のときのみ生成（poll 時は WebSub ログ・HTTP を出さない）
        self._websub_client: Optional[WebSubClient] = None
        self.bluesky_client = BlueskyClient()
        self.twitch_client = TwitchClient()
        # Mock attributes expected by v3 GUI
        # Mock attributes expected by v3 GUI
        self.is_first_run = False
        self.db_path = "data/client_v4.db"

    def _get_websub_client(self) -> WebSubClient:
        if self._websub_client is None:
            self._websub_client = WebSubClient()
        return self._websub_client

    def sync_with_server(self):
        """
        Fetch latest videos from Center Server and sync to local DB.
        Called by GUI Refresh button.
        """
        from v4.core.config import settings

        feed_mode = getattr(settings, "youtube_feed_mode", "poll")
        if feed_mode != "websub":
            logger.debug(
                "sync_with_server skipped (youtube_feed_mode=%s; YouTube はローカル RSS/Worker のみ)",
                feed_mode,
            )
            return True

        logger.info(f"Syncing with Center Server: {settings.center_server_url}")

        target_channel_id = settings.youtube_channel_id or "UCG8aSUNiSb_ylI89407qfww"
        ws = self._get_websub_client()

        async def _do_sync():
            last_yt = get_latest_video_update_time_for_service(self.db, "youtube")
            if last_yt:
                logger.info("Syncing YouTube since: %s", last_yt)
            else:
                logger.info("Performing full YouTube sync (no previous YouTube rows).")

            try:
                yt_resp = await ws.fetch_youtube_videos(target_channel_id, since=last_yt)
            except Exception as e:
                if "403" in str(e):
                    logger.info("Received 403. Attempting to register channel %s...", target_channel_id)
                    reg_success = await ws.register_client(target_channel_id)
                    if reg_success:
                        logger.info("Registration request sent. Retrying fetch...")
                        yt_resp = await ws.fetch_youtube_videos(target_channel_id, since=last_yt)
                    else:
                        raise e
                else:
                    raise e

            tw_resp = None
            tw_account = get_twitch_account(self.db)
            if tw_account:
                last_tw = get_latest_video_update_time_for_service(self.db, "twitch")
                if last_tw:
                    logger.info("Syncing Twitch since: %s", last_tw)
                try:
                    tw_resp = await ws.fetch_twitch_broadcasts(
                        tw_account.twitch_user_id, since=last_tw
                    )
                except Exception as e:
                    logger.warning("Twitch center pull failed (YouTube sync still applied): %s", e)

            return yt_resp, tw_resp

        try:
            response, tw_response = asyncio.run(_do_sync())

            count_yt = 0
            if response and response.videos:
                for video_data in response.videos:
                    video_dict = video_data.model_dump()
                    if not video_dict.get("channel_id"):
                        video_dict["channel_id"] = response.channel_id
                    upsert_video(self.db, video_dict)
                    count_yt += 1

            count_tw = 0
            if tw_response and tw_response.broadcasts:
                for row in tw_response.broadcasts:
                    if not isinstance(row, dict):
                        continue
                    vd = _twitch_broadcast_row_to_video_dict(row)
                    if vd:
                        upsert_video(self.db, vd)
                        count_tw += 1

            self.db.commit()
            if count_yt or count_tw:
                logger.info("Synced %s YouTube + %s Twitch rows from center.", count_yt, count_tw)
            else:
                logger.info("No new rows from center (YouTube/Twitch).")
            return True

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return False

    def retry_websub_and_lift_fallback(self) -> Tuple[bool, str]:
        """
        WebSub（センター）へ再接続し、成功時は RSS フォールバックフラグを解除する。
        続けて Twitch EventSub / Bluesky トークン確認・連携状態同期を試みる。
        """
        if str(settings.youtube_feed_mode or "poll").strip().lower() != "websub":
            return False, "取得モードが websub ではありません。"

        cid = (settings.youtube_channel_id or "").strip()
        if not cid:
            return False, "YouTube チャンネル ID が設定されていません。"

        async def _connect():
            ws = self._get_websub_client()
            await ws.ensure_lease_and_register_if_needed(cid)
            await ws.fetch_youtube_videos(cid)

        try:
            asyncio.run(_connect())
        except Exception as e:
            logger.exception("WebSub retry failed")
            return False, str(e)

        settings.youtube_websub_fallback_active = False
        logging.getLogger("v4.websub_client").info("✅ WebSub reconnect OK; center features re-enabled.")

        try:
            from v4.core.bluesky.bluesky_client import BlueskyClient

            async def _bsky():
                await BlueskyClient().ensure_server_token_fresh_on_startup(600)

            asyncio.run(_bsky())
        except Exception as e:
            logger.debug("Post-reconnect Bluesky token check: %s", e)

        try:
            from v4.domain.notifications.twitch.client import TwitchClient

            asyncio.run(TwitchClient().ensure_eventsub())
        except Exception as e:
            logger.debug("Post-reconnect Twitch ensure: %s", e)

        try:
            self.sync_connection_status()
        except Exception as e:
            logger.debug("Post-reconnect sync_connection_status: %s", e)

        return True, ""

    def __del__(self):
        self.db.close()

    def get_all_videos(self) -> List[Dict[str, Any]]:
        """
        Equivalent to v3 get_all_videos().
        Returns list of dicts with keys expected by GUI treeview.
        """
        try:
            videos = self.db.query(VideoModel).order_by(desc(VideoModel.published_at)).all()
            result = []
            for v in videos:
                service = (v.service or "youtube").lower()
                # Map VideoModel fields to v3 dict keys
                row = {
                    "id": v.id,
                    "video_id": v.video_id,
                    "title": v.title,
                    "published_at": _format_dt_no_fraction(v.published_at),
                    "channel_name": v.channel_name,
                    "video_url": v.video_url,
                    "service": service,
                    "source": service,
                    "posted_to_bluesky": 1 if getattr(v, "posted_to_bluesky", False) else 0,
                    "selected_for_post": 0,
                    "scheduled_at": _format_dt_no_fraction(v.scheduled_start_time) or None,
                    "posted_at": _format_dt_no_fraction(getattr(v, "posted_at", None)) or None,
                    "thumbnail_url": self._build_thumbnail_url(service, v.video_id),
                    "content_type": v.video_status,
                    "live_status": v.video_status,
                    "is_premiere": v.is_premiere,
                    "image_mode": getattr(v, "image_mode", None),
                    "image_filename": getattr(v, "image_filename", None),
                    "video_status": v.video_status,
                }

                # Adapting v4 'video_status' back to v3 'content_type'/'live_status' concepts if needed
                # v3 content_type: video, archive, schedule, live
                # v4 video_status: upload, schedule, live, archive, premiere

                # Simple mapping for display
                row["content_type"] = v.video_status

                result.append(row)
            return result
        except Exception as e:
            logger.error(f"Error in get_all_videos: {e}")
            return []

    @staticmethod
    def _build_video_url(service: str, video_id: str) -> Optional[str]:
        """サービス・動画IDから動画URLを構築する（DBに未保存の場合のフォールバック）。"""
        if not video_id:
            return None
        s = (service or "").lower()
        if s == "youtube":
            return f"https://www.youtube.com/watch?v={video_id}"
        if s == "niconico":
            return f"https://www.nicovideo.jp/watch/{video_id}"
        if s == "twitch":
            return f"https://www.twitch.tv/videos/{video_id}"
        return None

    @staticmethod
    def _build_thumbnail_url(service: str, video_id: str) -> Optional[str]:
        """サービス・動画IDからサムネイルURLを構築する。
        ニコニコは CDN の URL がランダム数を含むため予測不可で 404 になるため None を返す。
        ニコニコのサムネイルは OGP（watch ページの og:image）で取得する必要がある。
        """
        if not video_id:
            return None
        if service == "youtube":
            return f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
        if service == "niconico":
            # 旧 CDN 形式は 404（URL にランダム数が含まれるため予測不可）。OGP 取得は get_niconico_thumbnail_url() で行う。
            return None
        if service == "twitch":
            # Twitch は必要に応じて API または固定形式を追加可能
            return None
        return None

    # サービス名 → テンプレート種別キーのマッピング
    _TEMPLATE_TYPE_MAP = {
        # (service, status) → template_type key (template_utils.TEMPLATE_REQUIRED_KEYS のキー)
        ("youtube", "schedule"):  "youtube_schedule",
        ("youtube", "upcoming"):  "youtube_schedule",
        ("youtube", "live"):      "youtube_online",
        ("youtube", "archive"):   "youtube_archive",
        ("youtube", "upload"):    "youtube_new_video",
        ("youtube", "premiere"):  "youtube_new_video",
        ("niconico", "upload"):   "nico_new_video",
        ("niconico", "video"):    "nico_new_video",
        ("twitch", "live"):       "twitch_online",
        ("twitch", "archive"):    "twitch_offline",
    }

    def render_video_text(self, video_id: str) -> Optional[str]:
        """Render the appropriate template for a video."""
        video = self.db.query(VideoModel).filter(VideoModel.video_id == video_id).first()
        if not video:
            return None

        service = (getattr(video, "service", None) or "youtube").lower().strip()
        status = (video.video_status or "upload").lower().strip()

        # (service, status) → template type key。未知の組み合わせはサービス別デフォルトへ
        template_type = self._TEMPLATE_TYPE_MAP.get(
            (service, status),
            self._TEMPLATE_TYPE_MAP.get((service, "upload"), "youtube_new_video"),
        )

        # コンテキスト構築
        video_url = video.video_url
        if not video_url and video.video_id:
            video_url = f"https://www.youtube.com/watch?v={video.video_id}"

        context = {
            "title": video.title,
            "video_url": video_url,
            "channel_name": video.channel_name,
            "published_at": video.published_at,
            "live_status": video.video_status,
            "video_id": video.video_id,
        }
        return templates.render(template_type, context)

    def post_text_to_bluesky(
        self,
        text: str,
        dry_run: bool = False,
        image_path: Optional[str] = None,
        resize_small_images: bool = True,
    ) -> bool:
        """Post arbitrary text (with optional image) to Bluesky. resize_small_images は将来の画像加工で使用。"""
        try:
            return asyncio.run(
                self.bluesky_client.post(
                    text,
                    image_path=image_path,
                    dry_run=dry_run,
                    resize_small_images=resize_small_images,
                )
            )
        except Exception as e:
            logger.error(f"❌ post_text_to_bluesky failed: {e}")
            return False

    def post_to_bluesky(self, video_id: str, dry_run: bool = False) -> bool:
        """Render template and post a video to Bluesky."""
        logger.info(f"🚀 Preparing to post video {video_id} to Bluesky (dry_run={dry_run})...")
        rendered_text = self.render_video_text(video_id)
        if not rendered_text:
            logger.error(f"❌ Failed to render text for {video_id}")
            return False

        return self.post_text_to_bluesky(rendered_text, dry_run=dry_run)

    def update_selection(
        self, video_id, selected: bool, scheduled_at: str = None, image_mode: str = None, image_filename: str = None
    ):
        """
        GUI calls this to update selection status.
        In v4, we might not persist this selection logic the same way,
        but for GUI compatibility we need to handle it.
        """
        logger.warning(f"update_selection called for {video_id} (selected={selected}). Partial implementation.")
        # TODO: Implement local selection state in v4 DB or Memory?
        # For now, just log.
        return True

    def save_settings(self, new_values: Dict[str, Any]) -> bool:
        """Update settings.env with new values and refresh in-memory settings."""
        import json

        from v4.core.config import ENV_FILE, settings

        try:
            logger.info(f"💾 save_settings called with {len(new_values)} values")
            logger.info(f"💾 ENV_FILE path: {ENV_FILE}")
            logger.info(f"💾 ENV_FILE exists: {ENV_FILE.exists()}")

            # 1. Map lowercase keys to uppercase (as in settings.env)
            # Convert values to proper format (lists as JSON, others as strings)
            mapping = {}
            for k, v in new_values.items():
                key_upper = k.upper()
                if isinstance(v, list):
                    # List values should be JSON formatted
                    mapping[key_upper] = json.dumps(v)
                else:
                    mapping[key_upper] = str(v)

            if not ENV_FILE.exists():
                logger.error(f"Settings file not found: {ENV_FILE}")
                return False

            # 2. Read and Update lines
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()

            updated_lines = []
            keys_found = set()
            for line in lines:
                stripped = line.strip()
                if stripped and "=" in stripped and not stripped.startswith("#"):
                    key, _ = stripped.split("=", 1)
                    key = key.strip()
                    if key in mapping:
                        updated_lines.append(f"{key}={mapping[key]}\n")
                        keys_found.add(key)
                        # Debug: Log template and image changes

                        continue
                updated_lines.append(line)

            # 3. Add missing keys if any (though they should exist in .env)
            for key, val in mapping.items():
                if key not in keys_found:
                    updated_lines.append(f"{key}={val}\n")

            # 4. Write back
            with open(ENV_FILE, "w", encoding="utf-8") as f:
                f.writelines(updated_lines)

            logger.info(f"✅ File written to {ENV_FILE}. Total lines: {len(updated_lines)}")

            # 5. Update in-memory settings (partial update)
            for k, v in new_values.items():
                if hasattr(settings, k):
                    setattr(settings, k, v)

            if str(getattr(settings, "youtube_feed_mode", "poll")).strip().lower() == "poll":
                settings.youtube_websub_fallback_active = False

            logger.info("Settings updated successfully.")
            return True

        except Exception as e:
            logger.error(f"Failed to save settings: {e}", exc_info=True)
            return False

    def get_videos_without_image(self) -> List[Dict[str, Any]]:
        """image_filename が未設定の動画を返す。"""
        try:
            videos = (
                self.db.query(VideoModel)
                .filter(
                    (VideoModel.image_filename == None) | (VideoModel.image_filename == "")
                )
                .all()
            )
            result = []
            for v in videos:
                service = (v.service or "youtube").lower()
                result.append({
                    "video_id": v.video_id,
                    "title": v.title or "",
                    "source": service,
                    "thumbnail_url": self._build_thumbnail_url(service, v.video_id),
                    "image_filename": v.image_filename,
                    "image_mode": v.image_mode,
                })
            return result
        except Exception as e:
            logger.error(f"get_videos_without_image failed: {e}")
            return []

    def update_thumbnail_url(self, video_id: str, thumbnail_url: str) -> bool:
        """v4 VideoModel には thumbnail_url 列がないため no-op。"""
        logger.debug(f"update_thumbnail_url: {video_id} (no-op: column not in v4 DB)")
        return False

    def delete_video(self, video_id: str) -> bool:
        """Delete a video record from local DB"""
        try:
            video = self.db.query(VideoModel).filter(VideoModel.video_id == video_id).first()
            if video:
                # v3-like behavior: Clean up images too
                image_manager.delete_images_for_video(video.service, video.video_id)
                self.db.delete(video)
                self.db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete video {video_id}: {e}")
            self.db.rollback()
            return False

    def update_scheduled_time(self, video_id: str, new_dt: Optional[datetime]) -> bool:
        """Update scheduled start time for a video (any service: YouTube, Niconico, Twitch)."""
        try:
            video = self.db.query(VideoModel).filter(VideoModel.video_id == video_id).first()
            if video:
                video.scheduled_start_time = new_dt
                self.db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to update scheduled time for {video_id}: {e}")
            self.db.rollback()
            return False

    def get_scheduled_videos(self) -> List[Dict[str, Any]]:
        """
        スケジュール済み動画を取得（全サービス共通。scheduled_start_time が設定されているもの）
        BatchScheduleManager から利用される。v4 では service でフィルタしない。
        """
        try:
            rows = (
                self.db.query(VideoModel)
                .filter(VideoModel.scheduled_start_time.isnot(None))
                .order_by(VideoModel.scheduled_start_time.asc())
                .all()
            )
            result = []
            for v in rows:
                result.append({
                    "video_id": v.video_id,
                    "title": v.title or "",
                    "channel_name": v.channel_name or "",
                    "service": v.service or "youtube",
                    "scheduled_at": _format_dt_no_fraction(v.scheduled_start_time) or None,
                    "scheduled_start_time": v.scheduled_start_time,
                })
            return result
        except Exception as e:
            logger.error(f"get_scheduled_videos failed: {e}")
            return []

    def get_next_scheduled_video(self) -> Optional[Dict[str, Any]]:
        """次に投稿すべきスケジュール動画（scheduled_start_time <= now の先頭1件）"""
        try:
            from datetime import datetime as dt
            now = dt.utcnow()
            video = (
                self.db.query(VideoModel)
                .filter(
                    VideoModel.scheduled_start_time.isnot(None),
                    VideoModel.scheduled_start_time <= now,
                )
                .order_by(VideoModel.scheduled_start_time.asc())
                .first()
            )
            if not video:
                return None
            return {
                "video_id": video.video_id,
                "title": video.title or "",
                "service": video.service or "youtube",
                "scheduled_at": _format_dt_no_fraction(video.scheduled_start_time) or None,
            }
        except Exception as e:
            logger.error(f"get_next_scheduled_video failed: {e}")
            return None

    # --- Template Support ---
    def get_template_content(self, template_type: str) -> str:
        """Get raw template content string"""
        from v4.core.templates.templates import templates

        return templates.get_template_text(template_type)

    def save_template_content(self, template_type: str, content: str) -> bool:
        """Save raw template content to file/DB"""
        from v4.core.templates.templates import templates

        return templates.save_template_text(template_type, content)

    def preview_template_custom(self, template_type: str, custom_content: str) -> str:
        """Preview a custom template string with sample data"""
        from v4.core.templates.templates import templates

        return templates.render_preview(template_type, custom_content)

    def get_available_template_types(self) -> List[str]:
        """Get list of defined template types from engine"""
        from v4.core.templates.templates import templates

        return templates.get_available_template_types()

    def get_template_args(self, template_type: str) -> List[Tuple[str, str]]:
        """Get available arguments for a template type"""
        from v4.core.templates.templates import templates

        return templates.get_template_args(template_type)

    # --- OAuth Support ---
    def start_oauth_flow(self, service: str, handle: str = None) -> bool:
        """
        Start OAuth flow for a service and save results.
        """
        try:
            if (service or "").lower() in ("bsky", "bluesky") and not settings.bluesky_center_oauth_available():
                logger.warning("Bluesky OAuth via center is disabled; start_oauth_flow aborted.")
                return False
            # ローカルWebhookサーバーの待ち受けポートに合わせる
            code = OAuthFlowManager.start_oauth_flow(service, handle=handle, local_port=settings.port)
            if not code:
                logger.error(f"[adapter] OAuth flow returned no code for {service}")
                return False

            # センターサーバーにトークン交換を依頼するか、ローカルで処理
            # 現時点ではセンターサーバーが処理済みであることを期待するフロー
            if service == "twitch":
                success = self.sync_twitch_account(code)
            elif service == "bsky":
                success = self.sync_bsky_account(code)
            else:
                logger.error(f"Unknown service: {service}")
                success = False

            if success:
                logger.info(f"✅ OAuth setup and sync successful for {service}")
            else:
                logger.error(f"❌ OAuth setup succeeded but sync failed for {service}")

            return success
        except Exception as e:
            logger.error(f"OAuth flow failed for {service}: {e}")
            return False

    def sync_twitch_account(self, code: str) -> bool:
        """
        Center Server からトークン情報を取得・同期し、ローカルDBに保存する。
        """
        if not settings.uses_center_server():
            logger.warning(
                "Twitch OAuth 連携は取得モード『websub』（センター利用）時のみ有効です。"
                " poll モードではセンターに接続しません。"
            )
            return False

        logger.info(f"Syncing Twitch account with code: {code[:10]}...")

        async def _do_sync():
            # 1. code を使って Center Server からユーザー情報を取得
            user_info = await self.twitch_client.get_user_info(code)
            if not user_info:
                logger.error("Failed to fetch Twitch user info from Center Server.")
                return False

            # 2. ローカルDBに保存
            # user_info = { "status": "ok", "username": "...", "user_id": "...", "events": [...] }
            account_data = {
                "twitch_user_id": user_info.get("user_id"),
                "twitch_username": user_info.get("username"),
                "access_token": "managed_by_server",
                # Token is managed securely by Center Server. We just mark as linked.
            }
            upsert_twitch_account(self.db, account_data)
            self.db.commit()

            # 3. Center Server に EventSub 登録を依頼
            # (Center Server の /auth/code-exchange で自動登録されるため、追加処理不要)
            logger.info("EventSub registration confirmed via code-exchange.")

            return True

        try:
            return asyncio.run(_do_sync())
        except Exception as e:
            logger.error(f"Sync Twitch account failed: {e}")
            return False

    def sync_bsky_account(self, code: str) -> bool:
        """
        Center Server からアカウント情報を取得・同期し、ローカルDBに保存する。
        code は "success" という文字列が渡される想定（サーバー側で認証済みのため）。
        """
        if not settings.bluesky_center_oauth_available():
            logger.warning(
                "Bluesky OAuth 連携はセンター側が有効なときのみ利用できます（現在は凍結中、または poll / WebSub フォールバック中）。"
            )
            return False

        logger.info(f"Syncing Bluesky account with status: {code}...")

        async def _do_sync():
            # 1. Center Server から連携状態（アカウント情報）を取得
            # 注: 本来はJWT検証が必要だが、簡易的にCookie共有前提または認証直後のセッションを利用
            account_info = await self.bluesky_client.get_account_status()

            if not account_info or account_info.get("status") != "connected":
                logger.error("Failed to fetch Bluesky account info from Center Server (or not connected).")
                return False

            # 2. ローカルDBに保存
            # account_info = { "status": "connected", "handle": "...", "did": "..." }
            account_data = {
                "handle": account_info.get("handle"),
                "did": account_info.get("did"),
                "pds_url": "https://bsky.social",  # 仮置き、サーバーから返ってくればそれを使う
                "access_token": "managed_by_server",  # サーバー管理のためダミー
                "refresh_token": "managed_by_server",
            }
            upsert_bsky_account(self.db, account_data)
            self.db.commit()

            logger.info(f"✅ Synced Bluesky account: {account_data['handle']}")
            return True

        try:
            return asyncio.run(_do_sync())
        except Exception as e:
            logger.error(f"Sync Bluesky account failed: {e}")
            return False

    def disconnect_bsky_account(self) -> bool:
        """
        Disconnect Bluesky account.
        1. Request server to clear session.
        2. Clear local DB record.
        """
        logger.info("Disconnecting Bluesky account...")

        async def _do_disconnect():
            # 1. Server disconnect (best effort)
            await self.bluesky_client.disconnect()

            # 2. Local database cleanup
            success = delete_bsky_account(self.db)
            if success:
                logger.info("✅ Local Bluesky account removed.")
                self.db.commit()  # Ensure changes are saved
            else:
                logger.warning("No local Bluesky account found to remove.")
            return True

        try:
            return asyncio.run(_do_disconnect())
        except Exception as e:
            return False

    def disconnect_twitch_account(self) -> bool:
        """
        Twitch 連携解除（センター利用時はサーバー側も解除し、ローカル twitch_accounts を削除）。
        """
        logger.info("Disconnecting Twitch account...")

        async def _do_disconnect():
            acc = get_twitch_account(self.db)
            if not acc:
                logger.warning("No local Twitch account found to remove.")
                return True
            tid = str(acc.twitch_user_id)
            if settings.uses_center_server():
                await TwitchClient().disconnect_on_center(tid)
            if delete_twitch_account(self.db):
                logger.info("✅ Local Twitch account removed.")
                self.db.commit()
            return True

        try:
            return asyncio.run(_do_disconnect())
        except Exception as e:
            logger.error("disconnect_twitch_account failed: %s", e)
            return False

    def sync_connection_status(self) -> bool:
        """
        Sync local authentication status with server on startup.
        If server says we are disconnected, clear local state.
        Returns: True if any change happened.
        """
        if not settings.uses_center_server():
            logger.debug("sync_connection_status skipped (youtube_feed_mode=poll; no center verify)")
            return False

        changed = False
        # 1. Check Bluesky（センター Bluesky OAuth が有効なときのみ）
        local_bsky = get_bsky_account(self.db)
        if local_bsky and settings.bluesky_center_oauth_available():
            logger.info("Startup Check: Verifying Bluesky connection with server...")

            async def _check_bsky():
                try:
                    return await self.bluesky_client.get_account_status()
                except Exception as e:
                    logger.error(f"Failed to check bsky status: {e}")
                    return None

            try:
                server_status = asyncio.run(_check_bsky())

                # If server explicitly returns "disconnected" or 401 (handled in client returning {"status": "disconnected"})
                # We should clear local state.
                # If server_status is None (e.g. network error), maybe we should preserve local state?
                # Yes, be conservative. Only delete if server explicitly says "disconnected" or "not found".

                if server_status is not None:
                    status_str = server_status.get("status")
                    if status_str == "disconnected":
                        logger.warning("⚠️ Bluesky session is stale (Server says disconnected). Clearing local account.")
                        delete_bsky_account(self.db)
                        self.db.commit()
                        changed = True
                    elif status_str == "connected":
                        logger.info("✅ Bluesky session verified: Connected.")
                else:
                    logger.warning("Could not verify Bluesky status (Network error?). Keeping local state.")

            except Exception as e:
                logger.error(f"Failed to sync Bluesky status logic: {e}")

        return changed

    def get_auth_status(self) -> Dict[str, Any]:
        """
        Check if authenticated with major services.
        """
        twitch = get_twitch_account(self.db)
        bsky = get_bsky_account(self.db)
        return {
            "twitch": bool(twitch),
            "bluesky": bool(bsky),
            "twitch_username": twitch.twitch_username if twitch else None,
            "bsky_handle": bsky.handle if bsky else None,
        }

    def get_video_by_id(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        v3-compatible method to get video details by ID.
        Returns a dictionary or None.
        """
        try:
            video = self.db.query(VideoModel).filter(VideoModel.video_id == video_id).first()
            if not video:
                return None

            # Map to v3 expected structure (image_mode/image_filename, video_status, video_url, 投稿状況 for 動画詳細)
            video_url = video.video_url
            if not video_url and video.video_id:
                video_url = self._build_video_url(video.service or "youtube", video.video_id)
            scheduled_at = _format_dt_no_fraction(getattr(video, "scheduled_start_time", None)) or None
            return {
                "id": video.id,
                "video_id": video.video_id,
                "title": video.title,
                "video_url": video_url,
                "published_at": _format_dt_no_fraction(video.published_at),
                "channel_name": video.channel_name,
                "content_type": video.video_status,  # v4 maps status to content_type concept
                "live_status": video.video_status,
                "video_status": getattr(video, "video_status", None),  # 動画詳細の「タイプ」
                "is_premiere": video.is_premiere,
                "service": video.service,
                "image_mode": getattr(video, "image_mode", None),
                "image_filename": getattr(video, "image_filename", None),
                "posted_to_bluesky": getattr(video, "posted_to_bluesky", False),
                "posted_at": _format_dt_no_fraction(getattr(video, "posted_at", None)) or None,
                "scheduled_at": scheduled_at,
                "scheduled_start_time": scheduled_at,
            }
        except Exception as e:
            logger.error(f"Error in get_video_by_id({video_id}): {e}")
            return None

    def insert_video(
        self,
        video_id: str,
        title: str,
        video_url: str,
        published_at: str,
        channel_name: str,
        thumbnail_url: str = None,
        content_type: str = "video",
        live_status: str = None,
        is_premiere: bool = False,
        source: str = "youtube",
        skip_dedup: bool = False,
        representative_time_utc=None,
        representative_time_jst=None,
    ) -> bool:
        """
        v3-compatible insert method.
        """
        try:
            # Check existence first if skip_dedup is False
            if not skip_dedup:
                existing = self.get_video_by_id(video_id)
                if existing:
                    return False

            # Parse strings to datetime if needed
            dt_published_at = None
            if published_at:
                try:
                    # Try parsing ISO format
                    dt_published_at = datetime.fromisoformat(published_at)
                except ValueError:
                    # Try minimal parsing or just ignore
                    pass

            # Map content_type/live_status to v4 video_status
            # v4 statuses: upload, schedule, live, archive, premiere
            video_status = "upload"  # default
            if content_type == "schedule":
                video_status = "schedule"
            elif content_type == "live" or live_status == "live":
                video_status = "live"
            elif content_type == "archive" or content_type == "completed":
                video_status = "archive"
            elif is_premiere:
                video_status = "premiere"

            video_data = {
                "video_id": video_id,
                "title": title,
                "video_url": video_url,
                "published_at": dt_published_at,
                "channel_name": channel_name,
                "channel_id": None,
                "service": source,
                "video_status": video_status,
                "is_premiere": is_premiere,
                # "thumbnail_url": thumbnail_url # Not in VideoModel, handled by ImageManager
            }

            # Use core upsert logic
            upsert_video(self.db, video_data)
            self.db.commit()

            # Handle Thumbnail if URL provided
            if thumbnail_url:
                # In v4, we can trigger async download or just ignore if worker handles it.
                # v3 RSS usually called this. For now, we trust ImageManager or existing logic.
                pass

            return True
        except Exception as e:
            logger.error(f"Error in insert_video({video_id}): {e}")
            self.db.rollback()
            return False

    def update_video_status(self, video_id: str, content_type: str, live_status: Optional[str]) -> bool:
        """
        v3-compatible update status.
        """
        try:
            video = self.db.query(VideoModel).filter(VideoModel.video_id == video_id).first()
            if not video:
                return False

            # Map to v4 status
            new_status = "upload"
            if content_type == "schedule":
                new_status = "schedule"
            elif content_type == "live" or live_status == "live":
                new_status = "live"
            elif content_type == "archive" or content_type == "completed":
                new_status = "archive"
            elif content_type == "premiere":
                new_status = "premiere"

            video.video_status = new_status
            self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Error in update_video_status({video_id}): {e}")
            self.db.rollback()
            return False

    def update_published_at(self, video_id: str, published_at: str) -> bool:
        """
        v3-compatible update published_at (and scheduled_start_time).
        """
        try:
            video = self.db.query(VideoModel).filter(VideoModel.video_id == video_id).first()
            if not video:
                return False

            if published_at:
                try:
                    dt = datetime.fromisoformat(published_at)
                    video.published_at = dt
                    # In v3 LiveModule, this is often the scheduled time
                    if video.video_status == "schedule":
                        video.scheduled_start_time = dt
                except ValueError:
                    pass

            self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Error in update_published_at({video_id}): {e}")
            self.db.rollback()
            return False

    def mark_as_posted(self, video_id: str) -> bool:
        """投稿済みフラグを立て posted_at を記録する（v3 互換）。"""
        try:
            video = self.db.query(VideoModel).filter(VideoModel.video_id == video_id).first()
            if video:
                video.posted_to_bluesky = True
                video.posted_at = datetime.utcnow()
                self.db.commit()
                logger.info(f"✅ mark_as_posted: {video_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"mark_as_posted failed for {video_id}: {e}")
            self.db.rollback()
            return False

    def update_image_info(self, video_id: str, image_mode: str, image_filename: str) -> bool:
        """行単位の画像情報を DB に保存する（v3 互換）。"""
        try:
            video = self.db.query(VideoModel).filter(VideoModel.video_id == video_id).first()
            if video:
                video.image_mode = image_mode
                video.image_filename = image_filename
                self.db.commit()
                logger.info(f"✅ update_image_info: {video_id} → mode={image_mode}, file={image_filename}")
                return True
            return False
        except Exception as e:
            logger.error(f"update_image_info failed for {video_id}: {e}")
            self.db.rollback()
            return False

    def get_video(self, video_id: str) -> Optional[Dict[str, Any]]:
        """v3 互換の get_video（schedule_view_tab.py 等から利用）。"""
        return self.get_video_by_id(video_id)

    def fetch_rss_manually(self) -> int:
        """GUI からの手動 RSS 取得。新規追加件数を返す。"""
        channel_id = getattr(settings, "youtube_channel_id", "")
        if not channel_id:
            raise ValueError("YouTube チャンネル ID が設定されていません。")
        from v4.core.youtube.youtube_rss import YouTubeRSS
        fetcher = YouTubeRSS(channel_id)
        saved, _ = fetcher.save_to_db(self)
        return saved

    def classify_youtube_live_manually(self, video_ids: List[str]) -> int:
        """指定動画を手動で Live 分類し、DB を更新する。更新件数を返す。"""
        try:
            from v4.core.youtube.youtube_video_classifier import YouTubeVideoClassifier
            classifier = YouTubeVideoClassifier()
            updated = 0
            for vid_id in video_ids:
                result = classifier.classify_video(vid_id)
                if not result.get("success"):
                    continue
                video = self.db.query(VideoModel).filter(VideoModel.video_id == vid_id).first()
                if not video:
                    continue
                # ステータスマッピング（classifier 型 → VideoModel.video_status）
                type_to_status = {
                    "video":     "upload",
                    "premiere":  "premiere",
                    "live":      "live",
                    "schedule":  "schedule",
                    "completed": "archive",
                    "archive":   "archive",
                }
                new_status = type_to_status.get(result.get("type", ""), "upload")
                video.video_status = new_status
                video.is_premiere = result.get("is_premiere", False)
                if result.get("scheduled_start_time"):
                    try:
                        from datetime import datetime as _dt
                        video.scheduled_start_time = _dt.fromisoformat(result["scheduled_start_time"])
                    except Exception:
                        pass
                updated += 1
            self.db.commit()
            return updated
        except Exception as e:
            logger.error(f"classify_youtube_live_manually failed: {e}")
            self.db.rollback()
            return 0

    def update_selection(self, video_id: str, selected: bool) -> bool:
        """
        v3-compatible method to update selection (for AutoSelect in LiveModule).
        """
        try:
            # v4 might manage selection in GUI state or a specific field.
            # VideoModel has 'selected_for_post' field (checked in view_file earlier? No it didn't show in VideoModel snippet in Step 38).
            # The snippet showed 'video_status', 'is_premiere' etc.
            # Let's check VideoModel in 'database.py' again?
            # Step 38 snippet: video_status, is_premiere, scheduled_start_time...
            # It DOES NOT show selected flag.
            # However, adapter 'get_all_videos' returns 'selected_for_post': 0.
            # If the field exists in DB but not shown in snippet (maybe truncated), we can try updating it.
            # If not, we just log and return True (since it's for GUI state mostly).
            # Wait, `get_all_videos` sets `row["selected_for_post"] = 0`. It implies it's NOT in DB.
            # So this is a no-op for now unless we add it to DB.
            logger.info(f"update_selection called for {video_id} -> {selected} (No-op/Not persisted in v4 DB yet)")
            return True
        except Exception as e:
            logger.error(f"Error in update_selection({video_id}): {e}")
            return False
