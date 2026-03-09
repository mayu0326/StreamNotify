# -*- coding: utf-8 -*-
"""
Stream notify on Bluesky - v2 ロギング拡張プラグイン

旧版の高機能なロギング設定を提供するプラグイン。
- 複数ロガー（AppLogger, YouTubeLogger）
- TimedRotatingFileHandler（日次ローテーション）
- 環境変数ベースのログレベル制御
"""

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# 親ディレクトリのplugin_interfaceをインポート
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from plugin_interface import NotificationPlugin

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

# シングルトン用キャッシュ
_logging_plugin_cache: Dict[str, Any] = {}


class FlushTimedRotatingFileHandler(TimedRotatingFileHandler):
    """flush付きハンドラ（即座にディスクに書き込み、改行コードはLF統一）"""

    def _open(self):
        """ファイルを開く際に改行コードをLFに統一"""
        # newline='' で自動的なCRLF変換を防ぐ
        if self.encoding is None:
            stream = open(self.baseFilename, self.mode, newline="")
        else:
            stream = open(
                self.baseFilename, self.mode, encoding=self.encoding, newline=""
            )
        return stream

    def emit(self, record):
        """ログレコードを出力（改行コードはLFに統一）"""
        try:
            msg = self.format(record)
            stream = self.stream
            # 改行コードをLFに統一（CRLFを避ける）
            msg = msg.replace("\r\n", "\n")
            stream.write(msg + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)


class LoggingPlugin(NotificationPlugin):
    """ロギング拡張プラグイン（旧版の高機能ロギング設定を提供）"""

    def __init__(self, env_path: Optional[str] = None):
        """
        初期化

        Args:
            env_path: 環境変数ファイルのパス（Noneの場合は自動検出）
        """
        self.env_path = env_path or self._find_env_file()
        self.configured = False
        self.loggers: Dict[str, Any] = {}

    def _find_env_file(self) -> str:
        """環境変数ファイルを検出"""
        # v2ディレクトリのsettings.envを優先
        candidates = [
            Path(__file__).parent.parent / "settings.env",
            Path(__file__).parent.parent.parent / "settings.env",
            Path.cwd() / "settings.env",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return "settings.env"  # デフォルト

    def configure_logging(self):
        """ロギングを設定（旧版のconfigure_loggingを移植）"""
        global _logging_plugin_cache

        if self.configured and _logging_plugin_cache:
            return _logging_plugin_cache

        # ルートロガーをクリア（既存のハンドラーを削除）
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(logging.WARNING)
        root_logger.propagate = False

        # 環境変数を読み込む
        load_dotenv(dotenv_path=self.env_path)

        # logsディレクトリがなければ作成
        os.makedirs("logs", exist_ok=True)

        # ログレベルや保管日数の設定
        LOG_LEVEL_CONSOLE = os.getenv("LOG_LEVEL_CONSOLE", "INFO").upper()

        # DEBUG_MODE を確認し、デフォルトのログレベルを決定
        debug_mode = os.getenv("DEBUG_MODE", "false").strip().lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
        default_file_level = "DEBUG" if debug_mode else "INFO"

        env_log_level_file = os.getenv("LOG_LEVEL_FILE", "").upper()

        if not env_log_level_file:
            LOG_LEVEL_FILE = default_file_level
        else:
            # DEBUG_MODE=false なのに LOG_LEVEL_FILE=DEBUG が設定されている場合は INFO に強制変更
            if not debug_mode and env_log_level_file == "DEBUG":
                LOG_LEVEL_FILE = "INFO"
            else:
                LOG_LEVEL_FILE = env_log_level_file

        LEVEL_MAP = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        log_level_console = LEVEL_MAP.get(LOG_LEVEL_CONSOLE, logging.INFO)
        log_level_file = LEVEL_MAP.get(LOG_LEVEL_FILE, logging.DEBUG)

        # 個別ロガーのログレベル設定（環境変数で指定されていればデフォルト値をオーバーライド）
        log_level_app = LEVEL_MAP.get(
            os.getenv("LOG_LEVEL_APP", "").upper(), log_level_file
        )
        log_level_thumbnails_env = os.getenv("LOG_LEVEL_THUMBNAILS", "").upper()
        log_level_thumbnails = (
            LEVEL_MAP.get(log_level_thumbnails_env, log_level_file)
            if log_level_thumbnails_env
            else log_level_file
        )
        log_level_youtube = LEVEL_MAP.get(
            os.getenv("LOG_LEVEL_YOUTUBE", "").upper(), log_level_file
        )

        # ログの保管日数を取得（デフォルト14日）
        try:
            log_retention_days_str = os.getenv("LOG_RETENTION_DAYS", "14")
            log_retention_days = int(log_retention_days_str)
            if log_retention_days <= 0:
                print(
                    f"Warning: LOG_RETENTION_DAYS value '{log_retention_days_str}' is not positive. Defaulting to 14 days."
                )
                log_retention_days = 14
        except ValueError:
            print(
                f"Warning: Invalid LOG_RETENTION_DAYS value '{os.getenv('LOG_RETENTION_DAYS')}'. Defaulting to 14 days."
            )
            log_retention_days = 14

        # アプリケーション用ロガーの作成
        logger = logging.getLogger("AppLogger")
        logger.setLevel(log_level_app)
        logger.propagate = False
        logger.handlers.clear()

        error_format = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        # 一般ログファイル（app.log）のハンドラ - DEBUG と INFO を出力
        class DebugAndInfoFilter(logging.Filter):
            def filter(self, record):
                return record.levelno in (logging.DEBUG, logging.INFO)

        info_file_handler = FlushTimedRotatingFileHandler(
            "logs/app.log",
            when="D",
            interval=1,
            backupCount=log_retention_days,
            encoding="utf-8",
        )
        info_file_handler.setLevel(logging.DEBUG)  # DEBUG レベル以上を受け付ける
        info_file_handler.addFilter(
            DebugAndInfoFilter()
        )  # DEBUG と INFO のみをフィルタリング
        info_file_handler.setFormatter(error_format)
        logger.addHandler(info_file_handler)

        # エラーログファイル（error.log）のハンドラ - WARNING 以上のレベルのみ
        class WarningAndAboveFilter(logging.Filter):
            def filter(self, record):
                return record.levelno >= logging.WARNING

        error_file_handler = FlushTimedRotatingFileHandler(
            "logs/error.log",
            when="D",
            interval=1,
            backupCount=log_retention_days,
            encoding="utf-8",
        )
        error_file_handler.setLevel(
            logging.WARNING
        )  # WARNING 以上のレベルのみ受け付ける
        error_file_handler.addFilter(
            WarningAndAboveFilter()
        )  # WARNING 以上のみをフィルタリング
        error_file_handler.setFormatter(error_format)
        logger.addHandler(error_file_handler)

        # コンソール出力用ハンドラ
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level_console)
        console_handler.setFormatter(error_format)
        logger.addHandler(console_handler)

        app_logger_handlers = [info_file_handler, error_file_handler, console_handler]

        # サムネイル関連ロガー               # サムネイル再取得専用ロガーの設定
        thumbnails_logger = logging.getLogger("ThumbnailsLogger")
        thumbnails_logger.setLevel(log_level_thumbnails)
        thumbnails_logger.handlers.clear()
        thumbnails_format = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        thumbnails_file_handler = FlushTimedRotatingFileHandler(
            "logs/thumbnails.log",
            when="D",
            interval=1,
            backupCount=log_retention_days,
            encoding="utf-8",
        )
        thumbnails_file_handler.setLevel(log_level_thumbnails)
        thumbnails_file_handler.setFormatter(thumbnails_format)
        thumbnails_logger.addHandler(thumbnails_file_handler)

        # YouTube専用ロガー
        youtube_logger = logging.getLogger("YouTubeLogger")
        youtube_logger.setLevel(log_level_youtube)
        youtube_logger.propagate = False  # app.logへの伝播を防止
        youtube_logger.handlers.clear()
        yt_file_handler = FlushTimedRotatingFileHandler(
            "logs/youtube.log",
            when="D",
            interval=1,
            backupCount=log_retention_days,
            encoding="utf-8",
        )
        yt_file_handler.setLevel(log_level_file)
        yt_file_handler.setFormatter(error_format)
        youtube_logger.addHandler(yt_file_handler)

        # GUI専用ロガー
        gui_logger = logging.getLogger("GUILogger")
        gui_logger.setLevel(logging.INFO)
        gui_logger.propagate = False  # app.logへの伝播を防止
        gui_logger.handlers.clear()
        gui_file_handler = FlushTimedRotatingFileHandler(
            "logs/gui.log",
            when="D",
            interval=1,
            backupCount=log_retention_days,
            encoding="utf-8",
        )
        gui_file_handler.setLevel(logging.INFO)
        gui_file_handler.setFormatter(error_format)
        gui_logger.addHandler(gui_file_handler)

        # 投稿エラー専用ロガー
        post_error_logger = logging.getLogger("PostErrorLogger")
        post_error_logger.setLevel(logging.WARNING)
        post_error_logger.propagate = False  # app.logへの伝播を防止
        post_error_logger.handlers.clear()
        post_error_file_handler = FlushTimedRotatingFileHandler(
            "logs/post_error.log",
            when="D",
            interval=1,
            backupCount=log_retention_days,
            encoding="utf-8",
        )
        post_error_file_handler.setLevel(logging.WARNING)
        post_error_file_handler.setFormatter(error_format)
        post_error_logger.addHandler(post_error_file_handler)

        # 投稿ログ専用ロガー（成功・失敗含む）
        post_logger = logging.getLogger("PostLogger")
        post_logger.setLevel(logging.DEBUG)
        post_logger.propagate = False  # app.logへの伝播を防止
        post_logger.handlers.clear()
        post_file_handler = FlushTimedRotatingFileHandler(
            "logs/post.log",
            when="D",
            interval=1,
            backupCount=log_retention_days,
            encoding="utf-8",
        )
        post_file_handler.setLevel(logging.DEBUG)
        post_file_handler.setFormatter(error_format)
        post_logger.addHandler(post_file_handler)

        # キャッシュに保存
        _logging_plugin_cache = {
            "logger": logger,
            "app_logger_handlers": app_logger_handlers,
            "thumbnails_logger": thumbnails_logger,
            "youtube_logger": youtube_logger,
            "gui_logger": gui_logger,
            "post_error_logger": post_error_logger,
            "post_logger": post_logger,
        }

        self.loggers = _logging_plugin_cache
        self.configured = True

        return _logging_plugin_cache

    def is_available(self) -> bool:
        """プラグインが利用可能かどうか（常に利用可能）"""
        return True

    def post_video(self, video: Dict[str, Any]) -> bool:
        """
        動画情報をポスト（このプラグインはログ設定専用なので何もしない）

        Args:
            video: 動画情報

        Returns:
            bool: 常にTrue（ポスト機能は持たない）
        """
        # ロギングプラグインはポスト機能を持たないため、常にTrueを返す
        return True

    def get_name(self) -> str:
        """プラグイン名を取得"""
        return "ロギング設定拡張プラグイン"

    def get_version(self) -> str:
        """バージョンを取得"""
        return "2.0.0"

    def get_description(self) -> str:
        """プラグインの説明を取得"""
        return "旧版の高機能なロギング設定を提供（複数ロガー、日次ローテーション、環境変数制御）"

    def apply_debug_mode(self):
        """全ロガーのログレベルをDEBUGに設定"""
        # ルートロガーをDEBUGに設定（ハンドラーのレベルは変更しない）
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        # 全ロガー（AppLogger, YouTubeLogger など）をDEBUGに設定
        # ★重要★ ハンドラーレベルは変更しない（ハンドラーごとに出力対象が定義されているため）
        for logger_name in [
            "AppLogger",
            "PostLogger",
            "YouTubeLogger",
            "ImageLogger",
            "GUILogger",
            "WebhookLogger",
        ]:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.DEBUG)  # ロガーのレベルのみをDEBUGに変更

        # コンソール出力は通常のDEBUG出力を許可
        app_logger = logging.getLogger("AppLogger")

        # DEBUGログはコンソール出力のみ（ファイルには出さない）
        app_logger.debug("🔍 デバッグモードが有効になりました")

    def on_enable(self) -> None:
        """プラグインが有効になった時の処理"""
        self.configure_logging()
        logger = logging.getLogger("AppLogger")
        logger.info(f"✅ {self.get_name()} v{self.get_version()} が有効化されました")

    def on_disable(self) -> None:
        """プラグインが無効になった時の処理"""
        logger = logging.getLogger("AppLogger")
        logger.info(f"⛔ {self.get_name()} が無効化されました")


def get_logging_plugin(env_path: Optional[str] = None) -> LoggingPlugin:
    """ロギングプラグインを取得"""
    return LoggingPlugin(env_path)
