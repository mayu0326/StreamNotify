# -*- coding: utf-8 -*-

import logging
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from v4.core.config import settings

def setup_logging():
    """Configure logging based on settings.

    Can be called multiple times (e.g., when settings are changed at runtime).
    Clears existing handlers before reconfiguring to avoid duplicates.
    """

    root_logger = logging.getLogger()

    # Clear existing handlers to avoid duplicates when called multiple times
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Global Level
    global_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Root Logger Config
    root_logger.setLevel(global_level)

    # Formatter
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File Handler
    log_dir = settings.v4_dir / "logs"
    if not log_dir.exists():
        log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_dir / "v4_app.log",
        maxBytes=10*1024*1024, # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Module Specific Levels
    _set_module_level("v4.core.websub_client", settings.log_level_youtube)
    _set_module_level("v4.core.niconico.niconico_worker", settings.log_level_niconico)
    _set_module_level("v4.domain.notifications.twitch", settings.log_level_twitch)
    _set_module_level("v4.gui", settings.log_level_gui)
    _set_module_level("v4.core.bluesky.bluesky_client", settings.log_level_bsky)
    _set_module_level("v4.core.auth", settings.log_level_auth)
    _set_module_level("v4.webhook", settings.log_level_webhook)
    _set_module_level("v4.core.assets.asset_manager", settings.log_level_gui)

    logging.getLogger("v4.logging_config").info(f"Logging initialized with global level: {settings.log_level}")

def _set_module_level(logger_name: str, level_str: str):
    if level_str:
        level = getattr(logging, level_str.upper(), None)
        if level is not None:
            logging.getLogger(logger_name).setLevel(level)
