# -*- coding: utf-8 -*-

import logging
import sys
from logging.handlers import TimedRotatingFileHandler

from v4.core.config import settings


def setup_logging():
    """
    v4 のログ出力を「ログ種別ごとに別ファイル」に分離する。

    v3 の `logs/app.log`, `logs/error.log`, `logs/gui.log`, ... の考え方に近い形で、
    - app.log / error.log（全体）
    - GUI / YouTube / Niconico / Thumbnails / Auth / Webhook / Twitch
    - post.log / post_error.log
    を出す。

    Can be called multiple times; existing handlers are cleared to avoid duplicates.
    """
    root_logger = logging.getLogger()

    # Clear existing handlers to avoid duplicates when called multiple times
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    def _level_from_str(level_str: str, default: int) -> int:
        if not level_str:
            return default
        return getattr(logging, level_str.upper(), default)

    debug_mode = bool(getattr(settings, "debug_mode", False))
    console_level = _level_from_str(getattr(settings, "log_level", "INFO"), logging.INFO)
    file_default_level = _level_from_str(
        getattr(settings, "log_file_level", "INFO"), logging.INFO
    )
    retention_days = int(getattr(settings, "log_retention_days", 14))

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)

    # Root logger: console + app/error files (no monolithic v4_app.log)
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)

    log_dir = settings.v4_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # twitch.log は「通常時でも概要1行（成功/失敗）」を出すため、クランプしない。
    # 詳細は各所で DEBUG に落とし、通常時は出ないようにする。
    twitch_level = _level_from_str(getattr(settings, "log_level_twitch", "INFO"), logging.INFO)

    # app.log / error.log (v3 互換: DEBUG/INFO=app, WARNING+=error)
    def _app_filter(record: logging.LogRecord) -> bool:
        if debug_mode:
            return record.levelno < logging.WARNING
        return logging.INFO <= record.levelno < logging.WARNING

    def _error_filter(record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING

    app_file_handler = TimedRotatingFileHandler(
        log_dir / "app.log",
        when="D",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
    )
    app_file_handler.setLevel(logging.DEBUG)
    app_file_handler.setFormatter(formatter)
    app_file_handler.addFilter(_app_filter)

    error_file_handler = TimedRotatingFileHandler(
        log_dir / "error.log",
        when="D",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
    )
    error_file_handler.setLevel(logging.WARNING)
    error_file_handler.setFormatter(formatter)
    error_file_handler.addFilter(_error_filter)

    root_logger.addHandler(app_file_handler)
    root_logger.addHandler(error_file_handler)

    def _configure_logger(logger_name: str, file_name: str, level_attr: str) -> None:
        level_str = getattr(settings, level_attr, None) or "INFO"
        level = _level_from_str(level_str, file_default_level)
        # twitch.log は上で算出した twitch_level を優先
        if logger_name in ("v4.twitch.client", "v4.twitch.handler"):
            level = twitch_level

        # app.log / error.log は root logger が担当する。
        # ここで個別ハンドラを追加すると Windows でローテーション競合しやすい。
        if file_name in ("app.log", "error.log"):
            lgr = logging.getLogger(logger_name)
            lgr.setLevel(level)
            lgr.propagate = True
            for h in lgr.handlers[:]:
                lgr.removeHandler(h)
            return

        file_handler = TimedRotatingFileHandler(
            log_dir / file_name,
            when="D",
            interval=1,
            backupCount=retention_days,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)

        lgr = logging.getLogger(logger_name)
        lgr.setLevel(level)
        lgr.propagate = False  # avoid double-writing to app/error

        for h in lgr.handlers[:]:
            lgr.removeHandler(h)
        lgr.addHandler(console_handler)
        lgr.addHandler(file_handler)

    # Module -> file routing (logger 名はコード内の logging.getLogger("...") に合わせる)
    logger_file_map: dict[str, tuple[str, str]] = {
        # GUI
        "v4.gui": ("gui.log", "log_level_gui"),
        # v4.gui.adapter は「アプリ側の同期・実行」寄りなので v3 の感覚に合わせて app.log に寄せる
        "v4.gui.adapter": ("app.log", "log_level_gui"),
        "GUILogger": ("gui.log", "log_level_gui"),
        # YouTube
        "v4.websub_client": ("youtube.log", "log_level_youtube"),
        "v4.youtube_worker": ("youtube.log", "log_level_youtube"),
        "v4.youtube_rss": ("youtube.log", "log_level_youtube"),
        "v4.youtube_api_client": ("youtube.log", "log_level_youtube"),
        "v4.live_module": ("youtube.log", "log_level_youtube"),
        "YouTubeLogger": ("youtube.log", "log_level_youtube"),
        # Niconico
        "v4.niconico_worker": ("niconico.log", "log_level_niconico"),
        "v4.core.niconico.niconico_client": ("niconico.log", "log_level_niconico"),
        "NiconicoLogger": ("niconico.log", "log_level_niconico"),
        # Thumbnails / images
        "ThumbnailsLogger": ("thumbnails.log", "log_level_thumbnails"),
        "v4.images": ("thumbnails.log", "log_level_thumbnails"),
        "v4.image_processor": ("thumbnails.log", "log_level_thumbnails"),
        "v4.thumbnails": ("thumbnails.log", "log_level_thumbnails"),
        # Auth / Webhook
        "v4.core.auth": ("auth.log", "log_level_auth"),
        "v4.webhook": ("webhook.log", "log_level_webhook"),
        # Twitch
        "v4.twitch.client": ("twitch.log", "log_level_twitch"),
        "v4.twitch.handler": ("twitch.log", "log_level_twitch"),
        # Asset manager (thumb/image related)
        "v4.core.asset_manager": ("thumbnails.log", "log_level_thumbnails"),
    }

    for logger_name, (file_name, level_attr) in logger_file_map.items():
        try:
            _configure_logger(logger_name, file_name=file_name, level_attr=level_attr)
        except Exception:
            # logging_config まわりで失敗してもアプリ起動を止めない
            continue

    # httpx ログのうち Twitch 関連（ensure-subscriptions）だけを twitch.log に寄せる
    # v3 の感覚に合わせて、Twitch 設定処理のログが twitch.log に集まるようにする
    httpx_logger = logging.getLogger("httpx")

    class _HttpxTwitchEnsureFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            try:
                msg = record.getMessage()
            except Exception:
                return False
            if "api/twitch/ensure-subscriptions" not in msg:
                return False
            # DEBUG は対象外（通常 v3 同様 INFO以上）
            if not _app_filter(record):
                return False
            return True

    try:
        # app/error への記録は root logger 側に一本化する
        httpx_logger.propagate = True
        httpx_logger.setLevel(file_default_level)
        for h in httpx_logger.handlers[:]:
            httpx_logger.removeHandler(h)

        twitch_httpx_handler = TimedRotatingFileHandler(
            log_dir / "twitch.log",
            when="D",
            interval=1,
            backupCount=retention_days,
            encoding="utf-8",
        )
        twitch_httpx_handler.setLevel(twitch_level)
        twitch_httpx_handler.setFormatter(formatter)
        twitch_httpx_handler.addFilter(_HttpxTwitchEnsureFilter())

        httpx_logger.addHandler(twitch_httpx_handler)
    except Exception:
        # httpx 側の設定は失敗しても起動を止めない
        pass

    # Posting logs: PostLogger + v4.bluesky
    post_level = _level_from_str(getattr(settings, "log_level_post", "INFO"), logging.INFO)
    post_error_level = _level_from_str(
        getattr(settings, "log_level_post_error", "ERROR"), logging.ERROR
    )

    def _post_filter_info(record: logging.LogRecord) -> bool:
        return record.levelno < post_error_level

    def _post_error_filter(record: logging.LogRecord) -> bool:
        return record.levelno >= post_error_level

    def _configure_post_logger(logger_name: str) -> None:
        logger = logging.getLogger(logger_name)
        logger.propagate = False
        for h in logger.handlers[:]:
            logger.removeHandler(h)
        logger.setLevel(min(post_level, post_error_level))

        post_handler = TimedRotatingFileHandler(
            log_dir / "post.log",
            when="D",
            interval=1,
            backupCount=retention_days,
            encoding="utf-8",
        )
        post_handler.setLevel(post_level)
        post_handler.setFormatter(formatter)
        post_handler.addFilter(_post_filter_info)

        post_error_handler = TimedRotatingFileHandler(
            log_dir / "post_error.log",
            when="D",
            interval=1,
            backupCount=retention_days,
            encoding="utf-8",
        )
        post_error_handler.setLevel(post_error_level)
        post_error_handler.setFormatter(formatter)
        post_error_handler.addFilter(_post_error_filter)

        logger.addHandler(console_handler)
        logger.addHandler(post_handler)
        logger.addHandler(post_error_handler)

    try:
        _configure_post_logger("PostLogger")
    except Exception:
        pass
    try:
        _configure_post_logger("v4.bluesky")
    except Exception:
        pass

    logging.getLogger("v4.logging_config").info(
        "Logging initialized with separated log files (app/error + module-specific)."
    )

