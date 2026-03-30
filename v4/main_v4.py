import uvicorn
import asyncio
import logging
import sys
import threading
import tkinter as tk
from pathlib import Path

# Add project root to python path to allow imports
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR.parent))

from v4.core.config import settings
from v4.core.webhook_server import app
from v4.gui.adapter import V3DatabaseAdapter
from v4.gui.app import StreamNotifyApp
from v4.core.niconico.niconico_worker import NiconicoRSSWorker
from v4.setup_v4 import setup_v4
from v4.core.config_sync import sync_config
from v4.core.assets.asset_manager import sync_assets
from v4.core.logging_config_split import setup_logging

logger = logging.getLogger("v4.main")

def run_server():
    """Run Uvicorn server in a separate thread"""
    try:
        # Prevent Uvicorn from capturing signals to allow Tkinter to handle exit
        config = uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info")
        server = uvicorn.Server(config)
        server.run()
    except Exception as e:
        logger.error(f"Failed to start server: {e}")

def main():
    # 0. Bootstrapping
    setup_logging()
    logger.info("Initializing environment...")
    setup_v4()

    env_file = BASE_DIR / "settings.env"
    example_file = BASE_DIR / "settings.env.example"
    if example_file.exists():
        sync_config(env_file, example_file)

    # 0a. Sync Assets
    sync_assets()

    # 0b. Bluesky センター OAuth が有効なときのみ起動時トークン確認
    if settings.bluesky_center_oauth_available():
        try:
            from v4.core.bluesky.bluesky_client import BlueskyClient

            async def ensure_bsky_token():
                client = BlueskyClient()
                await client.ensure_server_token_fresh_on_startup(refresh_window_seconds=600)

            asyncio.run(ensure_bsky_token())
        except Exception as e:
            logger.warning("Bluesky token startup check skipped or failed: %s", e)
    else:
        logger.debug(
            "Bluesky center token check skipped (poll/WebSub fallback or center Bluesky OAuth disabled)."
        )

    logger.info(f"Starting StreamNotify Client v4")

    # 1a. Start Webhook Server in Background Thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    logger.info("Background Webhook Server started.")

    # 1b. Start Niconico RSS Worker in Background Thread
    nico_id = getattr(settings, "niconico_user_id", "")
    if nico_id:
        def run_nico_worker_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            worker = NiconicoRSSWorker(nico_id)
            # We use run_until_complete for start, then run_forever for the polling loop
            # Note: worker.start() internally creates a task, so we just need the loop to run
            loop.run_until_complete(worker.start())
            try:
                loop.run_forever()
            except Exception as e:
                logger.error(f"Niconico worker loop stopped: {e}")

        threading.Thread(target=run_nico_worker_thread, daemon=True).start()
        # v3 のログ分割に寄せて、起動メッセージも niconico ロガーへ
        logging.getLogger("v4.niconico_worker").info(
            f"Niconico RSS Worker started for user: {nico_id}"
        )
    else:
        logger.info("Niconico User ID not set. RSS Worker skipped.")

    # 1c. Start YouTube Worker (Poll Mode / WebSub Fallback)
    # Check feed mode
    feed_mode = getattr(settings, "youtube_feed_mode", "poll")
    should_start_rss = False
    rss_fallback_active = False

    if feed_mode == "poll":
        should_start_rss = True
    elif feed_mode == "websub":
        # Check WebSub connectivity and lease; re-register if lease is low/expired
        from v4.core.websub_client import WebSubClient
        # We need to run async check in sync context
        async def check_websub_and_lease():
            client = WebSubClient()
            cid = getattr(settings, "youtube_channel_id", "")
            if not cid:
                return False
            # 1. clienthealth で購読期限を確認し、残り少なければ再登録
            await client.ensure_lease_and_register_if_needed(cid)
            # 2. 接続確認（fetch_videos）
            try:
                await client.fetch_videos(cid)
                return True
            except Exception as e:
                logger.warning(f"WebSub check failed: {e}")
                return False

        try:
            is_connected = asyncio.run(check_websub_and_lease())
            if not is_connected:
                logger.warning("⚠️ WebSub unreachable. Falling back to RSS Worker.")
                should_start_rss = True
                rss_fallback_active = True
            else:
                # WebSub の疎通結果は websub_client 側へ寄せる
                logging.getLogger("v4.websub_client").info(
                    "✅ WebSub connected. RSS Worker skipped."
                )
        except Exception as e:
             logger.error(f"WebSub fallback check error: {e}")
             should_start_rss = True
             rss_fallback_active = True

    # WebSub フォールバック中はセンター機能を poll と同様に制限する
    settings.youtube_websub_fallback_active = rss_fallback_active
    if rss_fallback_active and feed_mode == "websub":
        logger.warning(
            "⚠️ WebSub に接続できず RSS フォールバック中です。"
            " Twitch / WebSub / Bluesky OAuth は無効です（ツールバー『WebSubに再接続』で復帰を試せます）。"
        )

    # 1d. Twitch EventSub（センター経由。poll モードではセンターを使わないため実行しない）
    if settings.uses_center_server():
        try:
            from v4.domain.notifications.twitch.client import TwitchClient

            async def ensure_twitch_eventsub():
                return await TwitchClient().ensure_eventsub()

            asyncio.run(ensure_twitch_eventsub())
        except Exception as e:
            logger.debug("Twitch EventSub ensure skipped or failed: %s", e)
    else:
        logger.debug("Twitch EventSub ensure skipped (youtube_feed_mode=poll).")

    if should_start_rss:
        youtube_channel_id = getattr(settings, "youtube_channel_id", "")
        if youtube_channel_id:
            from v4.core.youtube.youtube_worker import YouTubeRSSWorker

            def run_youtube_worker_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                worker = YouTubeRSSWorker(youtube_channel_id)
                loop.run_until_complete(worker.start())
                try:
                    loop.run_forever()
                except Exception as e:
                    logger.error(f"YouTube worker loop stopped: {e}")

            threading.Thread(target=run_youtube_worker_thread, daemon=True).start()
            logger.info(f"YouTube RSS Worker started for channel: {youtube_channel_id}")
        else:
            logger.warning("YouTube Channel ID not set. RSS Worker skipped.")

    # 2. Init DB Adapter
    db_adapter = V3DatabaseAdapter()

    # Sync connection status（Bluesky OAuth 連携のセンター照合。poll 時はスキップ）
    if settings.uses_center_server():
        logging.getLogger("v4.twitch.client").info("Verifying client-server connection status...")
    else:
        logging.getLogger("v4.twitch.client").debug(
            "Center server features off (poll mode); skipping client-server Bluesky verify."
        )
    db_adapter.sync_connection_status()

    # 3. Start GUI (Main Thread)
    root = tk.Tk()
    show_rss_controls = (feed_mode == "poll") or rss_fallback_active
    show_websub_retry = (feed_mode == "websub") and rss_fallback_active
    app_gui = StreamNotifyApp(
        root,
        db_adapter,
        show_rss_controls=show_rss_controls,
        show_websub_retry=show_websub_retry,
    )

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"GUI Error: {e}")
    finally:
        logger.info("Shutting down...")

if __name__ == "__main__":
    main()
