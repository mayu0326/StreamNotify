# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v3 ユーティリティ

YouTube → Bluesky 通知ボット用の共通ユーティリティ関数を提供します。
"""

from datetime import datetime, timezone
import os
import logging
import pytz
from tzlocal import get_localzone

# サムネイル関連ユーティリティ（ニコニコOGP/バックフィル）

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

# ロギング設定
util_logger = logging.getLogger("AppLogger.Utils")


def format_datetime_filter(iso_datetime_str, fmt="%Y-%m-%d %H:%M %Z"):
    """
    ISO 形式の日時文字列を指定タイムゾーン・フォーマットで整形して返す

    Args:
        iso_datetime_str: ISO 8601 形式の日時文字列（例: "2023-10-27T10:00:00Z"、"2025-09-17T19:03+0900"）
        fmt: 出力フォーマット文字列

    Returns:
        整形済みの日時文字列、またはエラー時は元の文字列
    """
    if not iso_datetime_str:
        return ""

    try:
        # ★ ニコニコ形式 '2025-09-17T19:03+0900' に対応
        # タイムゾーン形式を正規化（+0900 → +09:00）
        iso_str = iso_datetime_str.replace("Z", "+00:00")

        # タイムゾーン部分を確認して正規化
        if "+" in iso_str or "-" in iso_str.split("T")[-1]:
            # 最後の + または - を見つけてタイムゾーン部分を抽出
            if "+" in iso_str:
                parts = iso_str.rsplit("+", 1)
                tz_part = parts[1]
                if len(tz_part) == 4 and ":" not in tz_part:  # 0900 形式
                    iso_str = f"{parts[0]}+{tz_part[:2]}:{tz_part[2:]}"
            elif iso_str[-5] == "-" and ":" not in iso_str[-5:]:  # -0900 形式
                tz_part = iso_str[-4:]
                iso_str = iso_str[:-4] + f"-{tz_part[:2]}:{tz_part[2:]}"

        # ISO 形式の文字列を UTC として解釈
        dt_utc = datetime.fromisoformat(iso_str)

        # 環境変数からタイムゾーンを取得（未指定ならシステムローカル）
        target_tz_name = os.getenv("TIMEZONE", "system")
        target_tz = None

        if target_tz_name.lower() == "system":
            try:
                target_tz = get_localzone()
                if target_tz is None:
                    util_logger.warning(
                        "format_datetime_filter: tzlocal.get_localzone() が None を返しました。UTC にフォールバックします。"
                    )
                    target_tz = timezone.utc
            except Exception as e:
                util_logger.warning(
                    f"format_datetime_filter: tzlocal でシステムタイムゾーン取得エラー: {e}。UTC にフォールバックします。"
                )
                target_tz = timezone.utc
        else:
            try:
                target_tz = pytz.timezone(target_tz_name)
            except pytz.UnknownTimeZoneError:
                util_logger.warning(
                    f"format_datetime_filter: 設定のタイムゾーン '{target_tz_name}' が不明です。UTC にフォールバックします。"
                )
                target_tz = timezone.utc
            except Exception as e:
                util_logger.warning(
                    f"format_datetime_filter: pytz.timezone でエラー: '{target_tz_name}': {e}。UTC にフォールバックします。"
                )
                target_tz = timezone.utc

        dt_localized = dt_utc.astimezone(target_tz)
        return dt_localized.strftime(fmt)

    except ValueError as e:
        util_logger.error(
            f"format_datetime_filter: 日時文字列 '{iso_datetime_str}' のフォーマット '{fmt}' 変換エラー: {e}"
        )
        return iso_datetime_str
    except Exception as e:
        util_logger.error(
            f"format_datetime_filter: 予期せぬエラー: '{iso_datetime_str}': {e}"
        )
        return iso_datetime_str


def retry_on_exception(
    max_retries: int = 3, wait_seconds: float = 2, exceptions=(Exception,)
):
    """
    指定した例外が発生した場合にリトライするデコレータ

    Args:
        max_retries: 最大リトライ回数（デフォルト: 3）
        wait_seconds: リトライ間隔（秒）（デフォルト: 2）
        exceptions: リトライ対象の例外タプル

    Returns:
        デコレータ関数
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    util_logger.warning(
                        f"リトライ {attempt}/{max_retries}: 関数 {func.__name__} で例外が発生: {e}"
                    )
                    last_exception = e
                    import time

                    time.sleep(wait_seconds)

            if last_exception is not None:
                raise last_exception
            return None

        return wrapper

    return decorator


def is_valid_url(url):
    """
    文字列が有効な URL かどうかを判定する

    Args:
        url: 判定対象の文字列

    Returns:
        URL の場合は True、そうでなければ False
    """
    return isinstance(url, str) and (
        url.startswith("http://") or url.startswith("https://")
    )
