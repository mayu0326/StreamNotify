import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ルートディレクトリ (v4フォルダの1つ上)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
V4_DIR = BASE_DIR / "v4"
ENV_FILE = V4_DIR / "settings.env"


class Settings(BaseSettings):
    # General Settings
    app_theme: str = "dark"  # "light", "dark", "system"
    app_mode: str = "selfpost"  # "selfpost", "autopost", "dry_run", "collect"
    debug_mode: bool = False  # デバッグモード
    timezone: str = "Asia/Tokyo"  # タイムゾーン設定

    # Account Settings
    ## Bluesky Account
    bluesky_username: str = ""
    bluesky_password: str = ""

    ## Twitch Account (not used in v4)
    # twitch_username: str = ""
    # twitch_password: str = ""
    # twitch_client_id: str = ""
    # twitch_client_secret: str = ""

    ## YouTube Account
    youtube_channel_id: str = ""
    youtube_api_key: str = ""  # YouTubeDataAPI(v3) キー
    youtube_feed_mode: str = "websub"  # "websub" or "poll"（poll 時はセンターサーバー非使用）
    # 起動時に main がセット。WebSub 不通で RSS フォールバック中は True（.env では通常未設定）
    youtube_websub_fallback_active: bool = False

    ## Niconico Account
    niconico_user_id: str = ""
    niconico_user_name: str = ""  # ニコニコユーザー名
    niconico_monitor_interval: int = 60  # ニコニコ監視間隔 (秒)

    # Webhook Settings
    use_local_server: bool = False  # ローカル開発用サーバーへの強制接続フラグ

    ## Center Server Settings
    center_server_url: str = "https://webhook.neco-server.net"

    # Local Server Settings
    host: str = "127.0.0.1"
    port: int = 20000

    ## WebSub Client Settings
    websub_client_id: str = "default_client"
    websub_client_api_key: str = ""  # X-Client-API-Key として使用
    websub_callback_base_url: str = "http://localhost:20000"
    websub_lease_seconds: int = 432000  # WebSub購読期間 (秒) - デフォルト5日

    # センター経由の Bluesky OAuth（DPoP・トークン委譲）。False のときは常にアプリパスワード経路。
    bluesky_oauth_via_center_enabled: bool = False

    # Post Settings
    ## Post Protection Settings
    prevent_duplicate_posts: bool = False
    youtube_dedup_enabled: bool = True
    bluesky_post_enabled: bool = False

    ## Autopost Settings
    autopost_statuses: list[str] = [""]  # 自動投稿対象ステータス (live, upcoming, archive)
    autopost_interval_minutes: int = 5
    autopost_lookback_minutes: int = 30
    autopost_missed_detection_threshold: int = 10  # 未投稿動画の大量検知閾値
    autopost_include_normal: bool = True
    autopost_include_premiere: bool = True

    ## YouTube Live Selfpost Live Autopilot Settings
    youtube_live_auto_post_schedule: bool = True  # 予約枠を手動投稿
    youtube_live_auto_post_live: bool = True  # 配信中・終了を手動投稿
    youtube_live_auto_post_archive: bool = True  # アーカイブを手動投稿

    # RSS Mode Settings
    ## YouTubeLive Post Delay Settings (RSS Polling Only)
    youtube_live_post_delay: str = "immediate"  # 配信開始後、いつ投稿するか (immediate/delay_5min/delay_30min)

    ## YouTubeLive Polling Settings (RSS Polling Only)
    detect_scheduled_time: bool = True  # 配信予定時刻を検出
    youtube_monitor_interval: int = 60  # YouTube RSS監視間隔 (秒)
    live_monitor_interval: int = 60  # YouTube LIVE 監視間隔 (秒) - RSS フォールバック時のみ使用
    youtube_live_poll_interval_active: int = 15  # ACTIVE時（schedule/live）のポーリング間隔（分）
    youtube_live_poll_interval_completed_min: int = 60  # COMPLETED時の最短確認間隔（分）
    youtube_live_poll_interval_completed_max: int = 180  # COMPLETED時の最大確認間隔（分）
    youtube_live_archive_check_count_max: int = 4  # ARCHIVE化後の最大追跡回数
    youtube_live_archive_check_interval: int = 180  # ARCHIVE化後の確認間隔（分）

    # Bluesky Post Template and Image Settings
    ## Template Settings

    ### Default Template Path
    template_path: str = "templates/default/default_template.txt"  # 外部テンプレートディレクトリ (空の場合はデフォルト)

    ### YouTube Template Path
    template_youtube_new_video_path: str = "templates/youtube/yt_new_video_template.txt"
    template_youtube_schedule_path: str = "templates/youtube/yt_schedule_template.txt"
    template_youtube_online_path: str = "templates/youtube/yt_online_template.txt"
    template_youtube_offline_path: str = "templates/youtube/yt_offline_template.txt"
    template_youtube_archive_path: str = "templates/youtube/yt_archive_template.txt"

    ### Niconico Template Path
    template_nico_new_video_path: str = "templates/niconico/nico_new_video_template.txt"

    ### Twitch Template Path
    template_twitch_online_path: str = "templates/twitch/twitch_online_template.txt"
    template_twitch_offline_path: str = "templates/twitch/twitch_offline_template.txt"
    template_twitch_raid_path: str = "templates/twitch/twitch_raid_template.txt"

    ## Bluesky PostImage Settings
    ### Bluesky Default Image Path
    bluesky_image_path: str = "images/default/noimage.png"

    ### Image Processing Settings
    image_resize_target_width: int = 1200
    image_resize_target_height: int = 800
    image_output_quality_initial: int = 90
    image_size_target: int = 800 * 1024
    image_size_threshold: int = 900 * 1024
    image_size_limit: int = 1024 * 1024

    # Logging Settings
    ## GlobalLogging Level Settings
    log_level: str = "INFO"  # グローバルログレベル
    log_file_level: str = "INFO"  # ファイル出力レベル
    log_retention_days: int = 14  # ログファイル保持日数

    ## Module Logging Level Settings
    log_level_auth: str = "INFO"  # 認証モジュール
    log_level_webhook: str = "INFO"  # Webhookモジュール
    log_level_gui: str = "INFO"  # GUIモジュール
    log_level_bsky: str = "INFO"  # Blueskyモジュール
    log_level_youtube: str = "INFO"  # YouTubeモジュール
    log_level_niconico: str = "INFO"  # Niconicoモジュール
    log_level_twitch: str = "INFO"  # Twitchモジュール
    log_level_thumbnails: str = "INFO"  # サムネイルモジュール
    log_level_post_error: str = "ERROR"  # 投稿エラーモジュール
    log_level_post: str = "INFO"  # 投稿モジュール

    # Paths
    base_dir: Path = BASE_DIR
    v4_dir: Path = V4_DIR
    data_dir: Path = V4_DIR / "data"

    def uses_center_server(self) -> bool:
        """
        True のときのみセンターサーバーへ接続する（YouTube WebSub / Twitch EventSub / Bluesky OAuth・DPoP 等）。
        poll モード、または websub でも WebSub 不通で RSS フォールバック中は False（poll と同様の機能制限）。
        """
        if str(self.youtube_feed_mode or "poll").strip().lower() != "websub":
            return False
        return not bool(getattr(self, "youtube_websub_fallback_active", False))

    def bluesky_center_oauth_available(self) -> bool:
        """センターに Bluesky OAuth ルートが有効なときのみ True（凍結中は False）。"""
        return self.uses_center_server() and bool(self.bluesky_oauth_via_center_enabled)

    @model_validator(mode="after")
    def override_local_server(self):
        if self.use_local_server:
            self.center_server_url = "http://localhost:8080"
        return self

    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"  # v3用の余計な環境変数は無視
    )

    def reload_settings(self):
        """Reload settings from .env file"""
        preserved_fallback = bool(getattr(self, "youtube_websub_fallback_active", False))
        new_settings = Settings()
        for key, value in new_settings.model_dump().items():
            setattr(self, key, value)
        # ランタイムのみのフラグ（フォールバック中）は .env に無いため維持する
        self.youtube_websub_fallback_active = preserved_fallback


def get_settings() -> Settings:
    return Settings()


# シングルトンとしてエクスポート
settings = get_settings()
