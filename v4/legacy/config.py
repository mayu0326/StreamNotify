# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v3 設定管理

.env から設定を読み込み、バリデーションを行う。
"""

import os
import logging
from dotenv import load_dotenv
from pathlib import Path

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

DB_PATH = "data/video_list.db"


class OperationMode:
    """動作モードの定義"""
    SELFPOST = "selfpost"       # SELFPOST モード（人間が操作する完全手動投稿モード）
    AUTOPOST = "autopost"       # AUTOPOST モード（人間の介入を一切行わない完全自動投稿モード）
    DRY_RUN = "dry_run"         # ドライランモード（デバッグ用途・投稿機能オフ）
    COLLECT = "collect"         # 収集モード（RSS取得のみ・投稿機能オフ）

    # 後方互換性のため旧名を定義
    NORMAL = SELFPOST
    AUTO_POST = AUTOPOST


class Config:
    """アプリケーション設定を管理するクラス"""

    def __init__(self, env_path=".env"):
        """
        初期化

        Args:
            env_path: settings.env ファイルのパス
        """
        load_dotenv(env_path, override=True)
        self.validate()

    def validate(self):
        """設定値をバリデーション"""

        # YouTube チャンネル ID
        self.youtube_channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()

        # YouTubeAPI連携プラグイン導入フラグ（importlibで自動判定＋APIキー必須）
        try:
            import importlib.util
            # ★ v3.2.0以降: youtube_api_plugin は plugins/youtube/ に移動
            plugin_exists = (importlib.util.find_spec("plugins.youtube.youtube_api_plugin") is not None or
                            importlib.util.find_spec("plugins.youtube.youtube_api_plugin") is not None)
        except Exception:
            plugin_exists = False

        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        self.youtube_api_plugin_exists = plugin_exists

        if plugin_exists:
            if self.youtube_api_key:
                self.youtube_api_plugin_enabled = True
            else:
                self.youtube_api_plugin_enabled = False
        else:
            self.youtube_api_plugin_enabled = False
            logger.info("[YouTubeAPI]プラグインが導入されていません。")

        if not self.youtube_channel_id:
            logger.error("YOUTUBE_CHANNEL_ID が未設定です。settings.env を確認してください。")
            raise ValueError("YOUTUBE_CHANNEL_ID is required")

        # YouTubeAPI未導入時（バリデーション段階ではINFOのみ出力。WARNINGはmain_v3で出力）
        if not plugin_exists:
            logger.info("[YouTubeAPI]プラグイン未導入のため、UCから始まるIDのみ利用可能です。")
            if not self.youtube_channel_id.startswith("UC"):
                logger.error(f"[YouTubeAPI]プラグイン未導入のため、現在のID: {self.youtube_channel_id}は利用不可能です。")
                raise ValueError("YouTubeAPI未導入時はUCから始まるIDのみ許可されます。設定を確認してください。")

        # Bluesky ユーザー名
        self.bluesky_username = os.getenv("BLUESKY_USERNAME", "").strip()
        if not self.bluesky_username:
            logger.error("BLUESKY_USERNAME が未設定です。settings.env を確認してください。")
            raise ValueError("BLUESKY_USERNAME is required")

        # Bluesky アプリパスワード
        self.bluesky_password = os.getenv("BLUESKY_PASSWORD", "").strip()
        if not self.bluesky_password:
            logger.error("BLUESKY_PASSWORD が未設定です。settings.env を確認してください。")
            raise ValueError("BLUESKY_PASSWORD is required")

        # ===== YouTube フィード取得モード（RSS ポーリング vs WebSub） =====
        self.youtube_feed_mode = os.getenv("YOUTUBE_FEED_MODE", "poll").strip().lower()

        # バリデーション
        if self.youtube_feed_mode not in ("poll", "websub"):
            logger.warning(f"YOUTUBE_FEED_MODE が無効です: {self.youtube_feed_mode}。'poll' に設定します。")
            self.youtube_feed_mode = "poll"

        if self.youtube_feed_mode == "poll":
            logger.debug("📡 YouTube フィード取得モード: RSS ポーリング")
        elif self.youtube_feed_mode == "websub":
            logger.debug("📡 YouTube フィード取得モード: WebSub（Websubサーバー HTTP API 経由）")
        # ★ hybridモードはコメントアウト（不使用）

        # ポーリング間隔（RSS とWebSub で異なる範囲）
        if self.youtube_feed_mode == "websub":
            # WebSub モード: 3〜30分（自前インフラなので短い間隔も可能）
            try:
                self.poll_interval_minutes = int(os.getenv("YOUTUBE_WEBSUB_POLL_INTERVAL_MINUTES", 5))
                if self.poll_interval_minutes < 3 or self.poll_interval_minutes > 30:
                    logger.warning(f"WebSub ポーリング間隔が範囲外です (3〜30): {self.poll_interval_minutes}。5分に設定します。")
                    self.poll_interval_minutes = 5
                logger.debug(f"📡 WebSub ポーリング間隔: {self.poll_interval_minutes} 分")
            except ValueError:
                logger.warning("YOUTUBE_WEBSUB_POLL_INTERVAL_MINUTES が無効です。5分に設定します。")
                self.poll_interval_minutes = 5
        else:
            # RSS ポーリング モード: 10〜60分（外部サーバーなので長めの間隔）
            try:
                self.poll_interval_minutes = int(os.getenv("YOUTUBE_RSS_POLL_INTERVAL_MINUTES", 10))
                if self.poll_interval_minutes < 10 or self.poll_interval_minutes > 60:
                    logger.warning(f"RSS ポーリング間隔が範囲外です (10〜60): {self.poll_interval_minutes}。10分に設定します。")
                    self.poll_interval_minutes = 10
                logger.debug(f"📡 RSS ポーリング間隔: {self.poll_interval_minutes} 分")
            except ValueError:
                logger.warning("YOUTUBE_RSS_POLL_INTERVAL_MINUTES が無効です。10分に設定します。")
                self.poll_interval_minutes = 10

        # Bluesky 投稿フラグ（デフォルト: False = ドライラン）
        post_enabled_str = os.getenv("BLUESKY_POST_ENABLED", "false").strip().lower()
        self.bluesky_post_enabled = post_enabled_str in ("true", "1", "yes", "on")

        # 重複投稿防止オプション（デフォルト: False）
        duplicate_prevention_str = os.getenv("PREVENT_DUPLICATE_POSTS", "false").strip().lower()
        self.prevent_duplicate_posts = duplicate_prevention_str in ("true", "1", "yes", "on")

        # YouTube重複排除オプション（デフォルト: True）
        # 同じタイトル+チャンネルの動画は優先度ベースで管理（v3.3.1実装）
        youtube_dedup_str = os.getenv("YOUTUBE_DEDUP_ENABLED", "true").strip().lower()
        self.youtube_dedup_enabled = youtube_dedup_str in ("true", "1", "yes", "on")
        if self.youtube_dedup_enabled:
            logger.info("✅ YouTube重複排除: 有効（優先度ベース管理）")
        else:
            logger.info("ℹ️ YouTube重複排除: 無効（すべての動画を登録）")

        # デバッグモード（デフォルト: False）
        debug_mode_str = os.getenv("DEBUG_MODE", "false").strip().lower()
        self.debug_mode = debug_mode_str in ("true", "1", "yes", "on")

        # 動作モードの判定
        db_exists = Path(DB_PATH).exists()
        app_mode_str = os.getenv("APP_MODE", "selfpost").strip().lower()

        # 後方互換性：old名を新名にマップ
        if app_mode_str == "normal":
            app_mode_str = OperationMode.SELFPOST
        elif app_mode_str == "auto_post":
            app_mode_str = OperationMode.AUTOPOST

        # 動作モードの決定ロジック（仕様 v1.0）
        # SELFPOST / AUTOPOST は排他的
        if not db_exists or app_mode_str == OperationMode.COLLECT:
            self.operation_mode = OperationMode.COLLECT
        elif app_mode_str == OperationMode.DRY_RUN:
            self.operation_mode = OperationMode.DRY_RUN
        elif app_mode_str == OperationMode.AUTOPOST:
            # AUTOPOST は Bluesky 投稿が有効化されている場合のみ
            if self.bluesky_post_enabled:
                self.operation_mode = OperationMode.AUTOPOST
            else:
                logger.warning("AUTOPOST モードが指定されていますが、BLUESKY_POST_ENABLED=true に設定してください。SELFPOST モードで起動します。")
                self.operation_mode = OperationMode.SELFPOST
        elif app_mode_str == OperationMode.SELFPOST or not self.bluesky_post_enabled:
            self.operation_mode = OperationMode.SELFPOST
        else:
            # デフォルトは SELFPOST モード
            self.operation_mode = OperationMode.SELFPOST

        # 後方互換性のため is_collect_mode を保持
        self.is_collect_mode = (self.operation_mode == OperationMode.COLLECT)

        # タイムゾーン（オプション）
        self.timezone = os.getenv("TIMEZONE", "system")

        # ニコニコプラグイン導入有無を検出
        try:
            import importlib.util
            self.niconico_plugin_exists = importlib.util.find_spec("plugins.niconico_plugin") is not None
        except Exception:
            self.niconico_plugin_exists = False

        # ニコニコユーザーID（オプション）
        self.niconico_user_id = os.getenv("NICONICO_USER_ID", "").strip()
        if self.niconico_plugin_exists:
            if self.niconico_user_id:
                logger.debug("有効なユーザーIDが設定されています。")
                logger.debug("ニコニコ連携機能を有効化しました。")
            else:
                logger.debug("有効なユーザーIDが設定されていません。")
                logger.debug("ニコニコ連携機能を無効化しました。")
        else:
            # バリデーション段階ではDEBUGレベルで抑制
            logger.debug("ニコニコプラグインが導入されていません。RSS取得のみで動作します。")

        # ニコニコポーリング間隔（分）
        try:
            self.niconico_poll_interval_minutes = int(os.getenv("NICONICO_POLL_INTERVAL", "10"))
            if self.niconico_poll_interval_minutes < 5 or self.niconico_poll_interval_minutes > 60:
                logger.warning(f"ニコニコポーリング間隔が範囲外です (5〜60): {self.niconico_poll_interval_minutes}。10分に設定します。")
                self.niconico_poll_interval_minutes = 10
        except ValueError:
            logger.warning("NICONICO_POLL_INTERVAL が無効です。10分に設定します。")
            self.niconico_poll_interval_minutes = 10

        # ★ 新: YouTube Live 動的ポーリング間隔（v3.4.0+ 改訂版）
        # キャッシュの状態に応じてポーリング間隔を自動調整
        # 新要件: completedのみ時は1～3時間毎、archive化後は最大4回まで3時間毎確認

        # ACTIVE（schedule/live あり）：固定短間隔
        try:
            self.youtube_live_poll_interval_active = int(os.getenv("YOUTUBE_LIVE_POLL_INTERVAL_ACTIVE", 15))
            if self.youtube_live_poll_interval_active < 1 or self.youtube_live_poll_interval_active > 60:
                logger.warning(f"YouTube Live ACTIVE ポーリング間隔が範囲外です (1〜60): {self.youtube_live_poll_interval_active}。5分に設定します。")
                self.youtube_live_poll_interval_active = 5
            logger.debug(f"📡 YouTube Live ACTIVE ポーリング間隔: {self.youtube_live_poll_interval_active} 分（schedule/live 状態時）")
        except ValueError:
            logger.warning("YOUTUBE_LIVE_POLL_INTERVAL_ACTIVE が無効です。5分に設定します。")
            self.youtube_live_poll_interval_active = 5

        # COMPLETED のみ時：最短1時間、最大3時間
        try:
            self.youtube_live_poll_interval_completed_min = int(os.getenv("YOUTUBE_LIVE_POLL_INTERVAL_COMPLETED_MIN", 60))
            if self.youtube_live_poll_interval_completed_min < 30 or self.youtube_live_poll_interval_completed_min > 180:
                logger.warning(f"YouTube Live COMPLETED 最短間隔が範囲外です (30〜180分): {self.youtube_live_poll_interval_completed_min}。60分に設定します。")
                self.youtube_live_poll_interval_completed_min = 60
            logger.debug(f"📡 YouTube Live COMPLETED 最短間隔: {self.youtube_live_poll_interval_completed_min} 分")
        except ValueError:
            logger.warning("YOUTUBE_LIVE_POLL_INTERVAL_COMPLETED_MIN が無効です。60分に設定します。")
            self.youtube_live_poll_interval_completed_min = 60

        try:
            self.youtube_live_poll_interval_completed_max = int(os.getenv("YOUTUBE_LIVE_POLL_INTERVAL_COMPLETED_MAX", 180))
            if self.youtube_live_poll_interval_completed_max < 30 or self.youtube_live_poll_interval_completed_max > 180:
                logger.warning(f"YouTube Live COMPLETED 最大間隔が範囲外です (30〜180分): {self.youtube_live_poll_interval_completed_max}。180分に設定します。")
                self.youtube_live_poll_interval_completed_max = 180
            if self.youtube_live_poll_interval_completed_max < self.youtube_live_poll_interval_completed_min:
                logger.warning(f"YouTube Live COMPLETED 最大間隔が最短間隔より小さいです。調整します。")
                self.youtube_live_poll_interval_completed_max = self.youtube_live_poll_interval_completed_min
            logger.debug(f"📡 YouTube Live COMPLETED 最大間隔: {self.youtube_live_poll_interval_completed_max} 分")
        except ValueError:
            logger.warning("YOUTUBE_LIVE_POLL_INTERVAL_COMPLETED_MAX が無効です。180分に設定します。")
            self.youtube_live_poll_interval_completed_max = 180

        # ARCHIVE 化後の追跡回数：最大4回、間隔3時間
        try:
            self.youtube_live_archive_check_count_max = int(os.getenv("YOUTUBE_LIVE_ARCHIVE_CHECK_COUNT_MAX", 4))
            if self.youtube_live_archive_check_count_max < 1 or self.youtube_live_archive_check_count_max > 10:
                logger.warning(f"YouTube Live ARCHIVE 追跡回数が範囲外です (1〜10): {self.youtube_live_archive_check_count_max}。4に設定します。")
                self.youtube_live_archive_check_count_max = 4
            logger.debug(f"📡 YouTube Live ARCHIVE 追跡回数: 最大 {self.youtube_live_archive_check_count_max} 回")
        except ValueError:
            logger.warning("YOUTUBE_LIVE_ARCHIVE_CHECK_COUNT_MAX が無効です。4に設定します。")
            self.youtube_live_archive_check_count_max = 4

        try:
            self.youtube_live_archive_check_interval = int(os.getenv("YOUTUBE_LIVE_ARCHIVE_CHECK_INTERVAL", 180))
            if self.youtube_live_archive_check_interval < 30 or self.youtube_live_archive_check_interval > 480:
                logger.warning(f"YouTube Live ARCHIVE 確認間隔が範囲外です (30〜480分): {self.youtube_live_archive_check_interval}。180分に設定します。")
                self.youtube_live_archive_check_interval = 180
            logger.debug(f"📡 YouTube Live ARCHIVE 確認間隔: {self.youtube_live_archive_check_interval} 分")
        except ValueError:
            logger.warning("YOUTUBE_LIVE_ARCHIVE_CHECK_INTERVAL が無効です。180分に設定します。")
            self.youtube_live_archive_check_interval = 180

        # ===== AUTOPOST 固有の環境変数（仕様 v1.0） =====

        # AUTOPOST 投稿間隔（分）
        try:
            self.autopost_interval_minutes = int(os.getenv("AUTOPOST_INTERVAL_MINUTES", "5"))
            if self.autopost_interval_minutes < 1 or self.autopost_interval_minutes > 60:
                logger.warning(f"AUTOPOST 間隔が範囲外です (1〜60): {self.autopost_interval_minutes}。5分に設定します。")
                self.autopost_interval_minutes = 5
        except ValueError:
            logger.warning("AUTOPOST_INTERVAL_MINUTES が無効です。5分に設定します。")
            self.autopost_interval_minutes = 5

        # AUTOPOST LOOKBACK 時間窓（分）
        try:
            self.autopost_lookback_minutes = int(os.getenv("AUTOPOST_LOOKBACK_MINUTES", "30"))
            if self.autopost_lookback_minutes < 5 or self.autopost_lookback_minutes > 1440:
                logger.warning(f"AUTOPOST LOOKBACK が範囲外です (5〜1440): {self.autopost_lookback_minutes}。30分に設定します。")
                self.autopost_lookback_minutes = 30
        except ValueError:
            logger.warning("AUTOPOST_LOOKBACK_MINUTES が無効です。30分に設定します。")
            self.autopost_lookback_minutes = 30

        # AUTOPOST 未投稿大量検知閾値（件数）
        try:
            self.autopost_unposted_threshold = int(os.getenv("AUTOPOST_UNPOSTED_THRESHOLD", "20"))
            if self.autopost_unposted_threshold < 1 or self.autopost_unposted_threshold > 1000:
                logger.warning(f"AUTOPOST 閾値が範囲外です (1〜1000): {self.autopost_unposted_threshold}。20件に設定します。")
                self.autopost_unposted_threshold = 20
        except ValueError:
            logger.warning("AUTOPOST_UNPOSTED_THRESHOLD が無効です。20件に設定します。")
            self.autopost_unposted_threshold = 20

        # AUTOPOST 動画種別フィルタ
        autopost_include_normal = os.getenv("AUTOPOST_INCLUDE_NORMAL", "true").strip().lower()
        self.autopost_include_normal = autopost_include_normal in ("true", "1", "yes", "on")

        autopost_include_shorts = os.getenv("AUTOPOST_INCLUDE_SHORTS", "false").strip().lower()
        self.autopost_include_shorts = autopost_include_shorts in ("true", "1", "yes", "on")

        autopost_include_member_only = os.getenv("AUTOPOST_INCLUDE_MEMBER_ONLY", "false").strip().lower()
        self.autopost_include_member_only = autopost_include_member_only in ("true", "1", "yes", "on")

        autopost_include_premiere = os.getenv("AUTOPOST_INCLUDE_PREMIERE", "true").strip().lower()
        self.autopost_include_premiere = autopost_include_premiere in ("true", "1", "yes", "on")

        # YouTube Live AUTOPOST モード（新統合環境変数、後方互換性あり）
        self.youtube_live_autopost_mode = os.getenv("YOUTUBE_LIVE_AUTO_POST_MODE", "").strip().lower()

        # 旧環境変数からのマッピング（後方互換性）
        if not self.youtube_live_autopost_mode:
            auto_post_start = os.getenv("YOUTUBE_LIVE_AUTO_POST_START", "true").lower() == "true"
            auto_post_end = os.getenv("YOUTUBE_LIVE_AUTO_POST_END", "true").lower() == "true"

            if auto_post_start and auto_post_end:
                self.youtube_live_autopost_mode = "live"
            elif auto_post_start and not auto_post_end:
                self.youtube_live_autopost_mode = "schedule"
            else:
                self.youtube_live_autopost_mode = "off"

        # バリデーション
        valid_modes = {"all", "schedule", "live", "archive", "off"}
        if self.youtube_live_autopost_mode not in valid_modes:
            logger.warning(f"YOUTUBE_LIVE_AUTO_POST_MODE が無効です: {self.youtube_live_autopost_mode}。'off' に設定します。")
            self.youtube_live_autopost_mode = "off"

        # YouTube Live 個別フラグ（SELFPOST モード向け、モード値と併用可能）
        youtube_live_auto_post_schedule = os.getenv("YOUTUBE_LIVE_AUTO_POST_SCHEDULE", "true").strip().lower()
        self.youtube_live_auto_post_schedule = youtube_live_auto_post_schedule in ("true", "1", "yes", "on")

        youtube_live_auto_post_live = os.getenv("YOUTUBE_LIVE_AUTO_POST_LIVE", "true").strip().lower()
        self.youtube_live_auto_post_live = youtube_live_auto_post_live in ("true", "1", "yes", "on")

        youtube_live_auto_post_archive = os.getenv("YOUTUBE_LIVE_AUTO_POST_ARCHIVE", "true").strip().lower()
        self.youtube_live_auto_post_archive = youtube_live_auto_post_archive in ("true", "1", "yes", "on")

    def _log_operation_mode(self):
        """現在の動作モードをログに出力"""
        mode_descriptions = {
            OperationMode.SELFPOST: "SELFPOST（人間が操作する完全手動投稿モード）",
            OperationMode.AUTOPOST: "AUTOPOST（人間の介入を一切行わない完全自動投稿モード）",
            OperationMode.DRY_RUN: "ドライランモード（デバッグ用途・投稿機能オフ）",
            OperationMode.COLLECT: "収集モード（RSS取得のみ・投稿機能オフ）"
        }

        # Bluesky投稿機能の状態を判定
        if self.operation_mode in (OperationMode.COLLECT, OperationMode.DRY_RUN):
            post_status = "無効"
        elif self.bluesky_post_enabled:
            post_status = "有効"
        else:
            post_status = "無効"

        # デバッグモードの状態
        debug_status = "有効" if self.debug_mode else "無効"

        logger.info("=" * 60)
        logger.info(f"動作モード: {mode_descriptions.get(self.operation_mode, self.operation_mode)}")
        logger.info(f"Bluesky投稿機能: {post_status}")
        logger.info(f"重複投稿防止: {'有効' if self.prevent_duplicate_posts else '無効'}")
        logger.info(f"デバッグモード: {debug_status}")
        logger.info("=" * 60)

        # モード別の詳細説明
        if self.operation_mode == OperationMode.COLLECT:
            logger.warning("📦 RSS を取得して DB に保存するだけです。Bluesky への投稿は行いません。")
        elif self.operation_mode == OperationMode.DRY_RUN:
            logger.warning("🧪 デバッグモードです。投稿のシミュレーションのみ行い、実際には投稿しません。")
        elif self.operation_mode == OperationMode.SELFPOST:
            logger.info("👤 投稿対象をGUIから設定し、手動で投稿を行ってください。")
        elif self.operation_mode == OperationMode.AUTOPOST:
            logger.info("🤖 自動投稿モード。人間の介入なく自動投稿が実行されます。GUI投稿操作は無効化されます。")


# グローバルキャッシュ（シングルトンパターン）
_config_cache = {}

def get_config(env_path="settings.env") -> Config:
    """設定オブジェクトを取得（キャッシング機構付き）

    初回呼び出し時に Config を生成し、以降は同じインスタンスを返す。
    これにより、複数箇所から get_config() が呼ばれても、
    ログの重複出力を防ぐことができる。
    """
    if env_path not in _config_cache:
        _config_cache[env_path] = Config(env_path)
    return _config_cache[env_path]
