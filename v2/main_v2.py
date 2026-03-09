# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v2 メインスクリプト

特定の YouTube チャンネルの新着動画を RSS で監視し、
DB に収集。投稿対象は GUI で選択。
収集モード時は投稿なし。

GUI はマルチスレッドで動作（メインループは継続）
"""

import logging
import os
import signal
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta

# プラグインマネージャ関連
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from typing import Optional

# アセットマネージャ
from asset_manager import get_asset_manager

# バージョン情報
from app_version import __version__

# GUI クラスをインポート
from gui_v2 import StreamNotifyGUI

# ロギング設定
from logging_config import setup_logging
from plugin_manager import PluginManager

logger: Optional[logging.Logger] = None  # グローバル変数として後で初期化

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


def run_gui(db, plugin_manager, stop_event):
    """GUI をスレッドで実行 (プラグイン対応)"""
    root = tk.Tk()
    gui = StreamNotifyGUI(root, db, plugin_manager)

    def on_closing():
        stop_event.set()
        root.destroy()
        if logger:
            logger.info("管理画面が閉じられたためアプリケーションを終了します...")
        sys.exit(0)

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


def signal_handler(signum, frame):
    """シグナルハンドラ"""
    if logger:
        logger.info("\n[INFO] 管理画面が閉じられたためアプリケーションを終了します...")
    sys.exit(0)


def main():
    """メインエントリポイント (v2: プラグインアーキテクチャ対応)"""
    global logger

    try:
        from config import get_config

        config = get_config("settings.env")
        logger = setup_logging(debug_mode=config.debug_mode)
        logger.info("=" * 60)
        logger.info(f"StreamNotify on Bluesky v{__version__} を起動しています...")
        logger.info(f"動作モードは: {config.operation_mode} に設定されています。")
        logger.info("=" * 60)
    except Exception as e:
        print(f"設定の読み込みに失敗しました: {e}")
        sys.exit(1)

    try:
        logger.info("データベースを準備しています...")
        from database import get_database

        db = get_database()
        if db.is_first_run:
            logger.info("🆕 初回起動です。収集モードで動作します。")
        logger.info("データベースを読み込みました")
    except Exception as e:
        logger.error(f"データベースの読み込みに失敗しました: {e}")
        sys.exit(1)

    try:
        logger.info("[YouTube] YouTubeRSS の取得を準備しています...")
        from youtube_rss import get_youtube_rss

        yt_rss = get_youtube_rss(config.youtube_channel_id)
        logger.info("[YouTube] RSS の取得準備を完了しました")
    except Exception as e:
        logger.error(f"[YouTube] YouTubeRSS の取得に失敗しました: {e}")
        sys.exit(1)

    plugin_manager = PluginManager(plugins_dir="plugins")
    loaded_names = set()

    # Asset マネージャーの初期化（プラグイン導入時に資源を配置）
    asset_manager = get_asset_manager()
    logger.info("📦 Asset マネージャーを初期化しました")

    plugin_files = [
        f
        for f in os.listdir("plugins")
        if f.endswith(".py")
        and not f.startswith("_")
        and f not in ("youtube_api_plugin.py",)
    ]
    for pf in plugin_files:
        plugin_name = pf[:-3]
        if plugin_name in loaded_names:
            continue
        plugin_manager.load_plugin(plugin_name, os.path.join("plugins", pf))
        # 自動ロードされたプラグインを有効化
        plugin_manager.enable_plugin(plugin_name)

        # プラグイン別のアセット配置
        try:
            asset_manager.deploy_plugin_assets(plugin_name)
        except Exception as e:
            logger.warning(f"プラグイン '{plugin_name}' のアセット配置失敗: {e}")

        loaded_names.add(plugin_name)

    # YouTubeAPI プラグインを手動でロード・有効化
    try:
        plugin_manager.load_plugin(
            "youtube_api_plugin", os.path.join("plugins", "youtube_api_plugin.py")
        )
        plugin_manager.enable_plugin("youtube_api_plugin")
        asset_manager.deploy_plugin_assets("youtube_api_plugin")
    except Exception as e:
        logger.debug(f"YouTubeAPI プラグインのロード失敗: {e}")

    if config.youtube_api_plugin_exists:
        if config.youtube_api_plugin_enabled:
            logger.info(
                "[YouTubeAPI] 有効なAPIキーを確認しました。連携機能を有効化します。"
            )
        else:
            logger.info("[YouTubeAPI] APIキーが未設定のため連携機能を無効化します。")
    else:
        # ロギング設定後に警告を出力（error.logにも記録される）
        logger.warning(
            "[YouTubeAPI] プラグインが未導入です。UCから始まるチャンネルIDのみ利用可能です。"
        )

    # Bluesky コア機能をロード（プラグインマネージャーには登録しない - 内部ライブラリとして機能）
    try:
        from bluesky_v2 import BlueskyMinimalPoster

        bluesky_core = BlueskyMinimalPoster(
            config.bluesky_username, config.bluesky_password
        )
        logger.info("✅ Bluesky コア機能を初期化しました")
    except Exception as e:
        logger.warning(f"⚠️  Bluesky コア機能の初期化に失敗しました: {e}")
        bluesky_core = None

    stop_event = threading.Event()
    gui_thread = threading.Thread(
        target=run_gui, args=(db, plugin_manager, stop_event), daemon=True
    )
    gui_thread.start()
    logger.info("✅ アプリケーションの起動が完了しました。 管理画面を開きます。")

    polling_count = 0
    last_post_time = None
    POST_INTERVAL_MINUTES = 5

    try:
        while not stop_event.is_set():
            polling_count += 1
            logger.info(f"\n=== ポーリング #{polling_count} ===")
            logger.info(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            logger.info("[YouTube] YouTubeRSS から情報を取得しています...")
            # YouTube RSS フェッチ・DB 保存・画像自動処理
            from thumbnails.youtube_thumb_utils import get_youtube_thumb_manager

            thumb_mgr = get_youtube_thumb_manager()
            saved_count = thumb_mgr.fetch_and_ensure_images(config.youtube_channel_id)

            if config.is_collect_mode:
                logger.info("[モード] 収集モード のため、投稿処理をスキップします。")
            else:
                now = datetime.now()
                should_post = (
                    last_post_time is None
                    or (now - last_post_time).total_seconds()
                    >= POST_INTERVAL_MINUTES * 60
                )

                if should_post:
                    selected_video = db.get_selected_videos()
                    if selected_video:
                        logger.info(f" 投稿対象を発見: {selected_video['title']}")
                        results = plugin_manager.post_video_with_all_enabled(
                            selected_video
                        )
                        success = any(results.values())
                        if success:
                            db.mark_as_posted(selected_video["video_id"])
                            last_post_time = now
                            logger.info(
                                f" ✅ 投稿完了。次の投稿は {POST_INTERVAL_MINUTES} 分後です。"
                            )
                        else:
                            logger.warning(f" ❌ 投稿に失敗: {selected_video['title']}")
                    else:
                        logger.info(
                            "投稿対象となる動画が指定されていません。管理画面から設定してください。"
                        )
                else:
                    assert last_post_time is not None
                    elapsed = (now - last_post_time).total_seconds() / 60
                    remaining = POST_INTERVAL_MINUTES - elapsed
                    logger.info(
                        f" 投稿間隔制限中。次の投稿まで約 {remaining:.1f} 分待機。"
                    )

            logger.info(
                f"次のポーリングまで {config.poll_interval_minutes} 分待機中..."
            )
            # 待機中も stop_event をチェック（1秒間隔）
            for _ in range(config.poll_interval_minutes * 60):
                if stop_event.is_set():
                    raise KeyboardInterrupt()
                time.sleep(1)

    except KeyboardInterrupt:
        if logger:
            logger.info("停止シグナルを受信しました。終了します。")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    if sys.platform.startswith("win"):
        signal.signal(signal.SIGBREAK, signal_handler)
    main()
