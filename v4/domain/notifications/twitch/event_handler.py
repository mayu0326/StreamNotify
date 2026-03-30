
import logging
from typing import Dict, Any, Optional
from v4.core.database import SessionLocal, upsert_video
from v4.domain.notifications.twitch.client import TwitchClient
from v4.core.bluesky.bluesky_client import BlueskyClient
from v4.core.templates.template_utils import get_template_path, load_template_with_fallback
from v4.core.config import settings

logger = logging.getLogger("v4.twitch.handler")

async def handle_twitch_event(payload: Dict[str, Any]):
    """
    Handle incoming Twitch EventSub notifications.
    Payload is expected to be the 'event' part or the full payload depending on how WebhookServer passes it.

    Expected structure from EventSub "stream.online":
    {
        "subscription": { ... },
        "event": {
            "id": "12345",
            "broadcaster_user_id": "1337",
            "broadcaster_user_login": "cool_user",
            "broadcaster_user_name": "Cool_User",
            "type": "live",
            "started_at": "2020-07-15T18:16:11.17106713Z"
        }
    }
    """
    event = payload.get("event")
    subscription = payload.get("subscription")

    if not event:
        logger.warning("Twitch event payload missing 'event' field.")
        return

    event_type = subscription.get("type") if subscription else "stream.online" # Fallback/Assumption

    logger.info(f"Handling Twitch event: {event_type} for {event.get('broadcaster_user_name')}")

    if event_type == "stream.online":
        await _handle_stream_online(event)
    elif event_type == "stream.offline":
        await _handle_stream_offline(event)
    elif event_type in ("channel.raid", "raid"):
        await handle_channel_raid(event)
    else:
        logger.debug(f"Unhandled Twitch event type: {event_type}")

async def handle_channel_raid(event: Dict[str, Any]):
    """
    Handle channel.raid event.
    """
    from_name = event.get("from_broadcaster_user_name")
    to_name = event.get("to_broadcaster_user_name")
    to_login = event.get("to_broadcaster_user_login")
    viewers = event.get("viewers", 0)

    logger.info(f"⚔️ Raid Event: {from_name} -> {to_name} ({viewers} viewers)")

    app_mode = getattr(settings, "app_mode", "selfpost")
    if app_mode == "dry_run":
        logger.info("[DRY RUN] Skipping Bluesky post for channel.raid event.")
        return
    if not settings.bluesky_post_enabled:
        logger.info("Bluesky posting is disabled in settings. Skipping Raid post.")
        return

    # 1. Prepare Context
    context = {
        "from_broadcaster_user_name": from_name,
        "from_broadcaster_user_login": event.get("from_broadcaster_user_login"),
        "to_broadcaster_user_name": to_name,
        "to_broadcaster_user_login": to_login,
        "viewers": viewers,
        "to_stream_url": f"https://twitch.tv/{to_login}",
        "raid_url": f"https://twitch.tv/{to_login}",
        "channel_url": f"https://twitch.tv/{event.get('from_broadcaster_user_login')}",
        # Add basic broadcaster info if needed by template defaults
        "broadcaster_user_name": from_name,
        "ended_at": None
    }

    # 2. Load Template
    template_path = get_template_path("twitch_raid")
    template = load_template_with_fallback(template_path, template_type="twitch_raid")

    if not template:
        logger.error("FAILED to load twitch_raid template. Cannot post.")
        return

    # 3. Render
    try:
        message = template.render(**context)
    except Exception as e:
        logger.error(f"Failed to render Raid template: {e}")
        return

    # 4. Post
    logger.info(f"Posting Raid notification to Bluesky: {message}")
    client = BlueskyClient()
    success = await client.post(message)
    if success:
        logger.info("✅ Raid notification posted successfully.")
    else:
        logger.error("❌ Failed to post Raid notification.")

async def _handle_stream_online(event: Dict[str, Any]):
    """
    Handle stream.online event.
    Fetch stream details to get title and game, then upsert to DB.
    """
    broadcaster_id = event.get("broadcaster_user_id")
    # EventSub 'stream.online' doesn't contain title/game, only basic info.
    # We need to fetch stream info from API.

    client = TwitchClient()
    stream_info = await client.get_stream_info(broadcaster_id)

    if not stream_info:
        logger.warning(f"Could not fetch detailed stream info for {broadcaster_id}, using event data only.")
        # Fallback to event data
        video_data = {
            "service": "twitch",
            "video_id": event.get("id"), # Stream ID
            "channel_id": broadcaster_id,
            "channel_name": event.get("broadcaster_user_name"),
            "video_status": "live",
            "published_at": event.get("started_at"), # ISO string
            "actual_start_time": event.get("started_at"),
            "title": f"Twitch Stream: {event.get('broadcaster_user_name')}", # Placeholder
            "video_url": f"https://www.twitch.tv/{event.get('broadcaster_user_login')}"
        }
    else:
        # Stream info successfully fetched
        video_data = {
            "service": "twitch",
            "video_id": stream_info.get("id"),
            "channel_id": stream_info.get("user_id"),
            "channel_name": stream_info.get("user_name"),
            "video_status": "live",
            "published_at": stream_info.get("started_at"),
            "actual_start_time": stream_info.get("started_at"),
            "title": stream_info.get("title"),
            "video_url": f"https://www.twitch.tv/{stream_info.get('user_login')}",
            "tags": stream_info.get("tags"), # List[str]
        }

    # Upsert to DB
    logger.info(f"Upserting Twitch stream: {video_data['title']}")
    db = SessionLocal()
    try:
        upsert_video(db, video_data)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to save Twitch video: {e}")
        db.rollback()
    finally:
        db.close()

    # Post to Bluesky
    app_mode = getattr(settings, "app_mode", "selfpost")
    if app_mode == "dry_run":
        logger.info("[DRY RUN] Skipping Bluesky post for stream.online event.")
    elif getattr(settings, "bluesky_post_enabled", False):
        await _post_to_bluesky_stream_event(video_data, "twitch_online")
    else:
        logger.info("Bluesky posting is disabled in settings. Skipping stream.online post.")


async def _post_to_bluesky_stream_event(video_data: Dict[str, Any], template_type: str) -> None:
    """Twitch stream.online / stream.offline イベントを Bluesky に投稿する共通処理"""
    context = {
        "broadcaster_user_name": video_data.get("channel_name", ""),
        "broadcaster_user_login": video_data.get("channel_name", "").lower(),
        "title": video_data.get("title", ""),
        "stream_url": video_data.get("video_url", ""),
        "channel_url": video_data.get("video_url", ""),
        "started_at": video_data.get("actual_start_time", ""),
        "ended_at": video_data.get("actual_end_time", None),
        "game_name": video_data.get("game_name", ""),
        "tags": video_data.get("tags", []),
    }

    template_path = get_template_path(template_type)
    template = load_template_with_fallback(template_path, template_type=template_type)

    if not template:
        logger.error(f"Failed to load template '{template_type}'. Skipping Bluesky post.")
        return

    try:
        message = template.render(**context)
    except Exception as e:
        logger.error(f"Failed to render template '{template_type}': {e}")
        return

    logger.info(f"Posting Twitch {template_type} notification to Bluesky...")
    client = BlueskyClient()
    success = await client.post(message)
    if success:
        logger.info(f"✅ Twitch {template_type} notification posted successfully.")
    else:
        logger.error(f"❌ Failed to post Twitch {template_type} notification.")


async def _handle_stream_offline(event: Dict[str, Any]):
    """
    Handle stream.offline event.
    Update the latest 'live' video for this broadcaster to 'archive' status.
    """
    broadcaster_id = event.get("broadcaster_user_id")
    broadcaster_name = event.get("broadcaster_user_name")
    logger.info(f"Stream ended for {broadcaster_name} (broadcaster_id={broadcaster_id})")

    # Database session to find and update the live video
    db = SessionLocal()
    try:
        from v4.core.database import VideoModel
        from datetime import datetime

        # Find the latest 'live' video for this broadcaster
        latest_live = (
            db.query(VideoModel)
            .filter(
                VideoModel.channel_id == broadcaster_id,
                VideoModel.video_status == "live"
            )
            .order_by(VideoModel.published_at.desc())
            .first()
        )

        archived_video_data: Optional[Dict[str, Any]] = None

        if latest_live:
            logger.info(
                f"Updating stream {latest_live.video_id} for {broadcaster_name}: "
                f"status=live → archive"
            )
            latest_live.video_status = "archive"
            latest_live.actual_end_time = datetime.utcnow()
            latest_live.is_updated_since = datetime.utcnow()

            db.commit()
            logger.info(
                f"Successfully archived stream {latest_live.video_id} "
                f"(ended at {latest_live.actual_end_time})"
            )
            archived_video_data = {
                "channel_name": latest_live.channel_name,
                "title": latest_live.title,
                "video_url": latest_live.video_url,
                "actual_start_time": str(latest_live.actual_start_time) if latest_live.actual_start_time else None,
                "actual_end_time": str(latest_live.actual_end_time),
                "game_name": getattr(latest_live, "game_name", ""),
            }
        else:
            logger.warning(
                f"No active 'live' video found for broadcaster {broadcaster_id} ({broadcaster_name}). "
                f"Stream may have already been archived or no stream record exists."
            )

    except Exception as e:
        logger.error(f"Failed to update stream.offline for {broadcaster_id}: {e}")
        db.rollback()
    finally:
        db.close()

    # Post to Bluesky
    app_mode = getattr(settings, "app_mode", "selfpost")
    if app_mode == "dry_run":
        logger.info("[DRY RUN] Skipping Bluesky post for stream.offline event.")
    elif archived_video_data and getattr(settings, "bluesky_post_enabled", False):
        await _post_to_bluesky_stream_event(archived_video_data, "twitch_offline")
    elif not getattr(settings, "bluesky_post_enabled", False):
        logger.info("Bluesky posting is disabled in settings. Skipping stream.offline post.")
