# -*- coding: utf-8 -*-

"""
StreamNotify - v3 メインスクリプト

特定の YouTube チャンネルの新着動画を RSS で監視し、
DB に収集。投稿対象は GUI で選択。
収集モード時は投稿なし。

GUI はマルチスレッドで動作（メインループは継続）
"""

import gc
import os
import signal
import sys
import threading
import time
import tkinter as tk
from datetime import datetime

# バージョン情報
from app_version import get_version_info

# アセットマネージャ
from asset_manager import get_asset_manager

# 設定
from config import OperationMode

# GUI クラスをインポート
from gui_v3 import StreamNotifyGUI

# ロギング設定
from logging_config import setup_logging

# プラグインマネージャ関連
from plugin_manager import PluginManager

# ★ 新: スケジューラ管理（v3.2.0）
from schedule_manager import BatchScheduleManager

from typing import Any, Dict, List, Optional, Tuple, cast

logger: Any = None  # グローバル変数として後で初期化
gui_instance: Optional[StreamNotifyGUI] = (
    None  # GUI インスタンスをグローバルで保持（プラグイン判定後のリロード用）
)

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


def run_gui(db, plugin_manager, stop_event, bluesky_core=None):
    """GUI をスレッドで実行 (プラグイン対応)"""
    global gui_instance

    root = tk.Tk()
    gui_instance = StreamNotifyGUI(root, db, plugin_manager, bluesky_core=bluesky_core)

    def on_closing():
        logger.info("管理画面が閉じられたためアプリケーションを終了します...")
        stop_event.set()

        # GUI インスタンスの参照をクリア
        global gui_instance
        try:
            # GUI オブジェクトの明示的なクリーンアップ
            if gui_instance and hasattr(gui_instance, "cleanup"):
                gui_instance.cleanup()
            gui_instance = None
        except:
            pass

        # tkinter オブジェクトの破棄
        try:
            root.quit()  # mainloop をクリアに終了（destroy ではなく）
        except:
            pass

    root.protocol("WM_DELETE_WINDOW", on_closing)

    try:
        root.mainloop()
    except Exception as e:
        if logger:
            logger.debug(f"GUI mainloop エラー（無視）: {e}")
    finally:
        # スレッド終了時の最終クリーンアップ
        try:
            root.destroy()
        except:
            pass

        # グローバル参照をクリア
        gui_instance = None


def signal_handler(signum, frame):
    """シグナルハンドラ"""
    if logger:
        logger.info("\n[INFO] 管理画面が閉じられたためアプリケーションを終了します...")
    sys.exit(0)


def main():
    """メインエントリポイント (v3: プラグインアーキテクチャ対応)"""
    global logger
    global gui_instance

    # バージョン情報をコンソールに出力
    print(f"StreamNotify {get_version_info()}")

    try:
        # v3.2.0+ config_sync logic removed
        pass

        from config import get_config

        config = get_config("settings.env")
        logger = setup_logging(debug_mode=config.debug_mode)
        logger.info(f"StreamNotify {get_version_info()}")
        logger.info(f"動作モードは: {config.operation_mode} に設定されています。")

        # ★ 設定ログ出力（初期化時に1回だけ）
        config._log_operation_mode()
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

    # ★ 新: 削除済み動画除外リストを初期化
    try:
        from deleted_video_cache import get_deleted_video_cache

        deleted_cache = get_deleted_video_cache()
        total_deleted = deleted_cache.get_deleted_count()
        if total_deleted > 0:
            logger.info(
                f"🔒 除外動画リストから削除済み動画 {total_deleted} 件を読み込みました"
            )
        else:
            logger.debug("除外動画リストはクリア状態です")
    except ImportError:
        logger.warning("deleted_video_cache モジュールが見つかりません")
    except Exception as e:
        logger.error(f"除外動画リストの初期化に失敗しました: {e}")

    # ★ 新: YouTubeVideoClassifier を初期化
    try:
        from youtube_core.youtube_video_classifier import get_video_classifier

        classifier = get_video_classifier(api_key=config.youtube_api_key)
        logger.info("✅ YouTube動画分類器を初期化しました")
    except Exception as e:
        logger.warning(f"⚠️ YouTube動画分類器の初期化に失敗しました: {e}")
        classifier = None

    # ★ 新: LiveModule を初期化
    try:
        from plugins.youtube.live_module import get_live_module

        live_module = get_live_module(
            db=db, plugin_manager=None
        )  # plugin_manager は後で注入
        logger.info("✅ YouTubeLiveモジュールを初期化しました")
    except Exception as e:
        logger.warning(f"⚠️ YouTubeLiveモジュールの初期化に失敗しました: {e}")
        live_module = None

    # ★ 【v3.2.0】新: Live スケジューラーを初期化
    live_scheduler = None
    try:
        from plugins.youtube.live_scheduler import get_live_scheduler

        live_scheduler = get_live_scheduler(
            database=db,
            classifier=classifier,
            live_module=live_module,
        )
        if live_scheduler:
            logger.info("✅ Live スケジューラーを初期化しました")
        else:
            logger.warning("⚠️ Live スケジューラーの初期化に失敗しました")
    except ImportError:
        logger.debug(
            "ℹ️ Live スケジューラーのインポートに失敗しました（APScheduler が必要です）"
        )
    except Exception as e:
        logger.warning(f"⚠️ Live スケジューラーの初期化中にエラー: {e}")

    # ===== YouTube フィード取得モード分岐 =====
    try:
        if config.youtube_feed_mode == "websub":
            # WebSub モード（Websubサーバー HTTP API 経由）
            logger.info("[YouTube] YouTube WebSub の取得を準備しています...")
            try:
                from youtube_core.youtube_websub import get_youtube_websub

                yt_rss = get_youtube_websub(config.youtube_channel_id)

                # ★ 【v3.2.0】WebSub サーバー接続確認
                health_check = yt_rss.health_check()
                if not health_check:
                    raise Exception("WebSub サーバーに接続できません")

                logger.info("[YouTube] WebSub の取得準備を完了しました")
            except (ImportError, Exception) as e:
                if isinstance(e, ImportError):
                    logger.warning(
                        "[YouTube] youtube_websub モジュールが見つかりません。RSS モードにフォールバックします。"
                    )
                else:
                    logger.warning(
                        f"[YouTube] WebSub 接続失敗: {e}。RSS モードにフォールバックします。"
                    )
                config.youtube_feed_mode = "poll"
                from youtube_core.youtube_rss import get_youtube_rss

                yt_rss = get_youtube_rss(config.youtube_channel_id)
                logger.info("[YouTube] RSS の取得準備を完了しました")
        else:
            # RSS ポーリング モード（デフォルト）
            logger.info("[YouTube] YouTubeRSS の取得を準備しています...")
            from youtube_core.youtube_rss import get_youtube_rss

            yt_rss = get_youtube_rss(config.youtube_channel_id)
            logger.info("[YouTube] RSS の取得準備を完了しました")
    except Exception as e:
        logger.error(f"[YouTube] フィード取得の初期化に失敗しました: {e}")
        sys.exit(1)

    plugin_manager = PluginManager(plugins_dir="plugins")
    loaded_names = set()

    # ★ 新: LiveModule に plugin_manager を注入
    if live_module:
        live_module.set_plugin_manager(plugin_manager)
        logger.debug("✅ LiveModule に PluginManager を注入しました")

    # Asset マネージャーの初期化（プラグイン導入時に資源を配置）
    asset_manager = get_asset_manager()
    logger.info("📦 Asset マネージャーを初期化しました")

    # ★ プラグイン自動検出（discover_plugins でフィルタリング済み）
    auto_plugins = plugin_manager.discover_plugins()
    for plugin_name, plugin_path in auto_plugins:
        # 除外リスト（明示的にロード）
        if plugin_name in ("bluesky_plugin", "niconico_plugin", "youtube_api_plugin"):
            continue

        if plugin_name in loaded_names:
            continue

        plugin_manager.load_plugin(plugin_name, plugin_path)
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
            "youtube_api_plugin",
            os.path.join("plugins", "youtube", "youtube_api_plugin.py"),
        )
        plugin_manager.enable_plugin("youtube_api_plugin")
        asset_manager.deploy_plugin_assets("youtube_api_plugin")
    except Exception as e:
        logger.debug(f"YouTubeAPI プラグインのロード失敗: {e}")

    # GUI インスタンスがあれば自動リロード
    if gui_instance:
        try:
            logger.debug("🔄 プラグイン判定後、GUI を再読込します...")
            gui_instance.refresh_data()
            logger.info("✅ GUI を自動更新しました")
        except Exception as e:
            logger.debug(f"⚠️ GUI 自動更新に失敗（無視）: {e}")

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
        from bluesky_core import BlueskyMinimalPoster

        bluesky_core = BlueskyMinimalPoster(
            config.bluesky_username,
            config.bluesky_password,
            dry_run=not config.bluesky_post_enabled,
        )
        logger.info(
            f"✅ Bluesky コア機能を初期化しました（テキスト投稿 + URLリンク化）"
        )
    except Exception as e:
        logger.warning(f"⚠️  Bluesky コア機能の初期化に失敗しました: {e}")
        bluesky_core = None

    # Bluesky 拡張機能プラグイン（画像添付・テンプレート）をロード
    # プラグインがない場合でも、コア機能（テキスト投稿）は引き続き利用可能
    bluesky_plugin_available = False
    try:
        from plugins.bluesky_plugin import BlueskyImagePlugin

        bluesky_image_plugin = BlueskyImagePlugin(
            config.bluesky_username,
            config.bluesky_password,
            dry_run=not config.bluesky_post_enabled,
            minimal_poster=bluesky_core,
        )
        plugin_manager.loaded_plugins["bluesky_image_plugin"] = bluesky_image_plugin
        plugin_manager.enable_plugin("bluesky_image_plugin")
        asset_manager.deploy_plugin_assets("bluesky_plugin")
        bluesky_plugin_available = True
        logger.info(
            f"✅ Bluesky 拡張機能プラグインを有効化しました（画像添付機能: 有効）"
        )
    except Exception as e:
        logger.warning(f"⚠️  Bluesky 拡張機能プラグインの導入に失敗しました: {e}")
        logger.info(f"ℹ️ Bluesky投稿機能をコア機能のみで起動します。(プラグイン未導入)")

    if config.niconico_plugin_exists:
        try:
            from plugins.niconico_plugin import NiconicoPlugin

            niconico_plugin = NiconicoPlugin(
                user_id=config.niconico_user_id,
                poll_interval=config.niconico_poll_interval_minutes,
                db=db,
                user_name=os.getenv("NICONICO_USER_NAME"),
            )
            plugin_manager.loaded_plugins["niconico_plugin"] = niconico_plugin

            if niconico_plugin.is_available():
                logger.info(
                    "[ニコニコ連携] 有効なユーザーIDを確認しました。連携機能を有効化します。"
                )
                plugin_manager.enable_plugin("niconico_plugin")
                asset_manager.deploy_plugin_assets("niconico_plugin")
                niconico_plugin.start_monitoring()
            else:
                logger.info(
                    "[ニコニコ連携] ユーザーIDが有効でないため連携機能を無効化します。"
                )
        except Exception as e:
            logger.warning(
                f"[ニコニコ連携] 初期化エラー: {type(e).__name__}: {e}", exc_info=True
            )
    else:
        logger.info(
            "ニコニコプラグインが導入されていないため、ニコニコ関連機能は無効化されます。"
        )

    stop_event = threading.Event()
    gui_thread = threading.Thread(
        target=run_gui, args=(db, plugin_manager, stop_event, bluesky_core), daemon=True
    )
    gui_thread.start()
    logger.info("✅ アプリケーションの起動が完了しました。 管理画面を開きます。")

    polling_count = 0
    last_post_time: Optional[datetime] = None
    autopost_warning_shown = False  # セーフモード警告フラグ
    safe_mode_enabled = False  # セーフモード有効フラグ（仕様 5.3）

    # ★ 新: スケジュール管理マネージャーを初期化（v3.2.0）
    schedule_mgr = BatchScheduleManager(db)
    logger.info("✅ バッチスケジュール管理を初期化しました")

    # ★ 新: セーフモード起動判定（仕様 5.3）
    # 起動時に posted_to_bluesky=0 かつ posted_at IS NOT NULL の件数をチェック
    # これは「投稿マーク自体がリセットされた」異常を検知する
    if config.operation_mode == OperationMode.AUTOPOST:
        try:
            import sqlite3

            conn = sqlite3.connect(db.db_path, timeout=10)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM videos WHERE posted_to_bluesky = 0 AND posted_at IS NOT NULL"
            )
            reset_count = cursor.fetchone()[0]
            conn.close()

            if reset_count > 0:
                safe_mode_enabled = True
                logger.error(
                    f"❌ セーフモード起動: posted_to_bluesky の大量リセットを検知（{reset_count} 件）"
                )
                logger.warning(
                    f"⚠️  AUTOPOST は抑止されます。DB の状態を確認して、手動リセットしてください。"
                )
        except Exception as e:
            logger.warning(f"セーフモード判定エラー（続行）: {e}")

    try:
        while not stop_event.is_set():
            polling_count += 1
            logger.info(f"\n=== ポーリング #{polling_count} ===")
            logger.info(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            # ===== YouTube フィード取得モード分岐 =====
            # サムネイル取得マネージャーの初期化（両モード共通）
            from thumbnails.youtube_thumb_utils import get_youtube_thumb_manager

            thumb_mgr = get_youtube_thumb_manager()

            if config.youtube_feed_mode == "websub":
                logger.info("[YouTube] WebSub から情報を取得しています...")
                # WebSub: ProductionServerAPI 経由で動画情報を取得
                from youtube_core.youtube_websub import YouTubeWebSub

                yt_websub = YouTubeWebSub(config.youtube_channel_id)
                # ★ 修正: classifier と live_module を渡す
                saved_count, live_count = yt_websub.save_to_db(
                    db, classifier=classifier, live_module=live_module
                )
                logger.info(
                    f"[YouTube] WebSub DB保存完了: {saved_count} 件（Live登録: {live_count} 件）"
                )

                # ★ 重要: WebSub から取得した動画のサムネイルを処理
                # 新規動画は thumb_mgr.ensure_websub_images で即座に処理
                # 既存動画でサムネイル未保存のものは youtube_thumb_backfill で自動補完
                websub_videos = yt_websub.fetch_feed()
                logger.debug(
                    f"[YouTube] WebSub fetch_feed() 完了: {len(websub_videos)} 件"
                )

                if saved_count > 0:
                    # ケース1: 新規動画あり → 新規動画のサムネイルを処理
                    logger.info(
                        f"[YouTube] 取得した {saved_count} 個の新規動画のサムネイルを処理しています..."
                    )
                    thumb_saved = thumb_mgr.ensure_websub_images(websub_videos)
                    logger.info(
                        f"[YouTube] 新規動画のサムネイル処理完了: {thumb_saved} 件"
                    )
                else:
                    # ケース2: 新規動画なし → 既存動画でサムネイル未保存のものを補完
                    videos_without_images = db.get_videos_without_image()

                    if videos_without_images:
                        logger.info(
                            f"[YouTube] サムネイル未保存の既存動画を検出: {len(videos_without_images)} 件"
                        )
                        logger.info(
                            f"[YouTube] youtube_thumb_backfill により自動補完します..."
                        )

                        try:
                            # 既存スクリプトの関数を直接呼び出してサムネイル補完
                            from thumbnails.youtube_thumb_backfill import (
                                backfill_youtube,
                            )

                            backfill_youtube(dry_run=False)
                        except Exception as e:
                            logger.warning(f"⚠️ サムネイル補完処理に失敗しました: {e}")
            else:
                logger.info("[YouTube] YouTubeRSS から情報を取得しています...")
                # RSS ポーリング: RSS フェッチ・DB 保存・画像自動処理を一体実行
                # ★ 修正: classifier と live_module を渡す
                from youtube_core.youtube_rss import YouTubeRSS

                yt_rss = YouTubeRSS(config.youtube_channel_id)
                saved_count, live_count = yt_rss.save_to_db(
                    db, classifier=classifier, live_module=live_module
                )
                logger.info(
                    f"[YouTube] RSS DB保存完了: {saved_count} 件（Live登録: {live_count} 件）"
                )

                # ★ サムネイル処理：fetch_and_ensure_images の結果をマージ
                thumb_mgr.fetch_and_ensure_images(config.youtube_channel_id)

            # ★ 新: Live ポーリング（Live関連動画の状態遷移を検知・自動投稿）
            if live_module:
                logger.info("[YouTube] Live動画をポーリング中...")
                try:
                    polled_count = live_module.poll_lives()
                    if polled_count > 0:
                        logger.info(
                            f"✅ Live ポーリング完了: {polled_count} 件を処理しました"
                        )
                    else:
                        logger.debug("ℹ️ Live ポーリング: 状態遷移なし")
                except Exception as e:
                    logger.error(f"❌ Live ポーリングエラー: {e}")

            if config.is_collect_mode:
                logger.info("[モード] 収集モード のため、投稿処理をスキップします。")
                # ★ collect モード: 初回ポーリング後に自動終了
                logger.info(
                    "✅ 初回ポーリング完了。collect モードのため、アプリケーションを自動終了します。"
                )
                raise KeyboardInterrupt()
            elif config.operation_mode == OperationMode.SELFPOST:
                # === SELFPOST モード（手動投稿がメイン＋LIVE自動投稿）===
                logger.info(
                    "[モード] SELFPOST モード。投稿対象を GUI から設定してください。"
                )

                # ★ 【新規】SELFPOST モード時に LIVE 関連動画を自動投稿
                # schedule/archive/live/completed で selected_for_post=1 のものを投稿
                if plugin_manager:
                    try:
                        # LIVE 関連動画（自動選択済み）を取得
                        live_videos = db.get_all_videos()
                        live_videos = [
                            v
                            for v in live_videos
                            if v.get("content_type")
                            in ("schedule", "archive", "live", "completed")
                            and v.get("selected_for_post") == 1
                            and v.get("posted_to_bluesky") == 0
                        ]

                        if live_videos:
                            logger.info(
                                f"📤 SELFPOST時のLIVE自動投稿: {len(live_videos)}件"
                            )
                            for video in live_videos:
                                try:
                                    results = (
                                        plugin_manager.post_video_with_all_enabled(
                                            video
                                        )
                                    )
                                    if any(results.values()):
                                        db.mark_as_posted(video["video_id"])
                                        logger.info(
                                            f"✅ LIVE動画を投稿しました: {video['title'][:50]}"
                                        )
                                    else:
                                        logger.warning(
                                            f"⚠️ LIVE動画の投稿失敗: {video['video_id']}"
                                        )
                                except Exception as e:
                                    logger.error(
                                        f"❌ LIVE動画投稿エラー: {video['video_id']} - {e}"
                                    )
                        else:
                            logger.debug("ℹ️ SELFPOST時のLIVE自動投稿: 対象動画なし")
                    except Exception as e:
                        logger.warning(f"⚠️ SELFPOST LIVE自動投稿処理エラー: {e}")
            elif config.operation_mode == OperationMode.AUTOPOST:
                # === AUTOPOST モード（完全自動投稿）===
                logger.info("[モード] AUTOPOST モード。自動投稿ロジックを実行します。")

                # ★ セーフモードチェック（仕様 5.3）
                if safe_mode_enabled:
                    logger.error("❌ セーフモード中: AUTOPOST は抑止されています。")
                    continue

                # 安全弁 1: 未投稿大量検知
                unposted_count = db.count_unposted_in_lookback(
                    config.autopost_lookback_minutes
                )
                if unposted_count >= config.autopost_unposted_threshold:
                    logger.error(
                        f"❌ 安全弁 1 発動: LOOKBACK 時間内に未投稿動画が {unposted_count} 件存在（閾値: {config.autopost_unposted_threshold} 件）"
                    )
                    logger.warning(
                        f"⚠️  設定エラーまたはデバッグ誤爆の可能性があります。AUTOPOST を起動抑止します。"
                    )
                    if not autopost_warning_shown:
                        # GUI にポップアップで通知（可能な場合）
                        autopost_warning_shown = True
                    continue  # このポーリングをスキップ

                # 安全弁解除
                autopost_warning_shown = False

                now = datetime.now()

                # ★ 新: スケジュール済み動画の投稿チェック（v3.2.0）
                scheduled_video = schedule_mgr.get_next_scheduled_video()
                if scheduled_video:
                    logger.info(
                        f"📅 スケジュール投稿を実行: {scheduled_video['title']}"
                    )
                    try:
                        results = plugin_manager.post_video_with_all_enabled(
                            scheduled_video
                        )
                        if any(results.values()):
                            db.mark_as_posted(scheduled_video["video_id"])
                            # スケジュール情報をクリア（投稿完了）
                            db.update_selection(
                                scheduled_video["video_id"],
                                selected=False,
                                scheduled_at=None,
                            )
                            last_post_time = now
                            logger.info(f"✅ スケジュール投稿成功。")
                        else:
                            logger.error(
                                f"❌ スケジュール投稿失敗: {scheduled_video['title']}"
                            )
                    except Exception as e:
                        logger.error(f"❌ スケジュール投稿エラー: {e}")
                else:
                    # 従来の投稿ロジック（selected_for_post）
                    # 投稿間隔チェック
                    should_post = (
                        last_post_time is None
                        or (now - cast(datetime, last_post_time)).total_seconds()
                        >= config.autopost_interval_minutes * 60
                    )

                    if should_post:
                        # 動画種別フィルタリング付きで候補を取得
                        candidates = db.get_autopost_candidates(config)

                        if candidates:
                            # 最初の候補を選択（優先度順）
                            selected_video = candidates[0]
                            logger.info(
                                f"🤖 AUTOPOST 対象を発見: {selected_video['title']}"
                            )

                            # 重複チェック（念のため）
                            if db.is_duplicate_post(selected_video["video_id"]):
                                logger.warning(
                                    f"⚠️  この動画は既に投稿済みです（{selected_video['title']}）"
                                )
                                continue

                            # プラグイン実行
                            results = plugin_manager.post_video_with_all_enabled(
                                selected_video
                            )
                            success = any(results.values())

                            if success:
                                # DB を投稿済みにマーク
                                db.mark_as_posted(selected_video["video_id"])
                                last_post_time = now
                                logger.info(
                                    f"✅ AUTOPOST 成功。次の投稿は {config.autopost_interval_minutes} 分後です。"
                                )
                            else:
                                logger.error(
                                    f"❌ AUTOPOST 投稿失敗: {selected_video['title']}"
                                )
                        else:
                            logger.info("🤖 AUTOPOST: 投稿対象動画がありません。")
                    else:
                        elapsed = (now - cast(datetime, last_post_time)).total_seconds() / 60
                        remaining = config.autopost_interval_minutes - elapsed
                        logger.info(
                            f"🤖 AUTOPOST: 投稿間隔制限中。次の投稿まで約 {remaining:.1f} 分待機。"
                        )

            # ★ 新: YouTube Live 動的ポーリング間隔に対応（v3.2.0+ 改訂版）
            # live_module が有効な場合は、キャッシュ状態に応じた動的間隔を計算
            # NO_LIVE 時は 0（ポーリングロジック休止）を返す
            next_live_poll_interval = config.poll_interval_minutes
            if live_module:
                try:
                    next_live_poll_interval = (
                        live_module.get_next_poll_interval_minutes()
                    )
                    if next_live_poll_interval == 0:
                        # NO_LIVE 時：ポーリングロジック休止（RSS/WebSub のみで OK）
                        logger.info(
                            "🔄 YouTube Live ポーリング: 休止中（LIVE 関連動画なし）"
                        )
                    else:
                        logger.info(
                            f"🔄 次の Live ポーリングまで {next_live_poll_interval} 分待機中..."
                        )
                except Exception as e:
                    logger.warning(
                        f"⚠️  動的ポーリング間隔決定エラー（デフォルト使用）: {e}"
                    )
                    next_live_poll_interval = config.poll_interval_minutes

            # 待機時間を計算（次回 RSS/WebSub ポーリングの時刻）
            logger.info(
                f"次のポーリング（RSS/WebSub）まで {config.poll_interval_minutes} 分待機中..."
            )
            # 待機中も stop_event をチェック（1秒間隔）
            for _ in range(config.poll_interval_minutes * 60):
                if stop_event.is_set():
                    raise KeyboardInterrupt()
                time.sleep(1)

    except KeyboardInterrupt:
        if "niconico_plugin" in plugin_manager.loaded_plugins:
            try:
                niconico_plugin = plugin_manager.loaded_plugins.get("niconico_plugin")
                if niconico_plugin and niconico_plugin.is_available():
                    logger.debug("[ニコニコプラグイン] 監視停止中...")
                    niconico_plugin.stop_monitoring()
            except Exception as plugin_error:
                logger.debug(f"[ニコニコプラグイン停止] エラー: {plugin_error}")

        # ★ 【v3.2.0】Live スケジューラーをシャットダウン
        # Live Scheduler shutdown logic removed (v3.2.0)

        logger.info("🛑 アプリケーションをシャットダウン中...")
        stop_event.set()
        gui_instance = None  # GUI インスタンスをクリア
        gui_thread.join(timeout=5)  # GUI スレッドの終了を待つ（最大5秒）
        gc.collect()  # 強制ガベージコレクション
        sys.exit(0)
    except Exception as e:
        logger.error(f"[予期せぬエラー] {type(e).__name__}: {e}", exc_info=True)
        if "niconico_plugin" in plugin_manager.loaded_plugins:
            try:
                niconico_plugin = plugin_manager.loaded_plugins.get("niconico_plugin")
                if niconico_plugin and niconico_plugin.is_available():
                    logger.debug("[ニコニコプラグイン] 監視停止中...")
                    niconico_plugin.stop_monitoring()
            except Exception as plugin_error:
                logger.debug(f"[ニコニコプラグイン停止] エラー: {plugin_error}")
        logger.info("🛑 アプリケーションをシャットダウン中...")
        stop_event.set()
        gui_instance = None  # GUI インスタンスをクリア
        gui_thread.join(timeout=5)  # GUI スレッドの終了を待つ（最大5秒）
        gc.collect()  # 強制ガベージコレクション
        sys.exit(1)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    if sys.platform.startswith("win"):
        signal.signal(signal.SIGBREAK, signal_handler)
    main()
