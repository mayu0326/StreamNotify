# -*- coding: utf-8 -*-

"""
StreamNotify on Bluesky- v1 設定管理

settingssettingssettingssettingssettingssettings.env から設定を読み込み、バリデーションを行う。
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

DB_PATH = "data/video_list.db"


class Config:
    """アプリケーション設定を管理するクラス"""

    def __init__(self, env_path="settings.env"):
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
        if not self.youtube_channel_id:
            logger.error("YOUTUBE_CHANNEL_ID が未設定です。settings.env を確認してください。")
            raise ValueError("YOUTUBE_CHANNEL_ID is required")

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

        # ポーリング間隔
        try:
            self.poll_interval_minutes = int(os.getenv("POLL_INTERVAL_MINUTES", 10))
            if self.poll_interval_minutes < 5 or self.poll_interval_minutes > 30:
                logger.warning(f"ポーリング間隔が範囲外です (5〜30): {self.poll_interval_minutes}。10分に設定します。")
                self.poll_interval_minutes = 10
        except ValueError:
            logger.warning("POLL_INTERVAL_MINUTES が無効です。10分に設定します。")
            self.poll_interval_minutes = 10

        # Bluesky 投稿フラグ（デフォルト: False = ドライラン）
        post_enabled_str = os.getenv("BLUESKY_POST_ENABLED", "false").strip().lower()
        self.bluesky_post_enabled = post_enabled_str in ("true", "1", "yes", "on")

        # 蓄積モード判定：DB がないか、APP_MODE=collect で蓄積のみ
        db_exists = Path(DB_PATH).exists()
        app_mode = os.getenv("APP_MODE", "normal").strip().lower()

        self.is_collect_mode = (not db_exists) or (app_mode == "collect")

        if self.is_collect_mode:
            logger.warning("⚠️  蓄積モード: RSS を取得して DB に保存するだけです。Bluesky への投稿は行いません。")
        else:
            if not self.bluesky_post_enabled:
                logger.warning("⚠️  BLUESKY_POST_ENABLED=false（ドライラン モード）")
                logger.warning("   投稿対象は DB で選択して、GUI または CLI から手動で行ってください。")
            else:
                logger.info("✅ BLUESKY_POST_ENABLED=true（投稿 モード）")
                logger.info("   投稿対象は DB で選択して、5分間隔で順次投稿します。")

        # タイムゾーン（オプション）
        self.timezone = os.getenv("TIMEZONE", "system")

        logger.info(f"設定を読み込みました。ポーリング間隔: {self.poll_interval_minutes} 分")


def get_config(env_path="settings.env") -> Config:
    """設定オブジェクトを取得"""
    return Config(env_path)
