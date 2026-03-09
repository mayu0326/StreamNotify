# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v3 テンプレート処理ユーティリティ

テンプレートの読み込み、検証、レンダリングに関する共通関数と定義を提供。

この関数群は、複数のプラグイン（Bluesky、将来の他プラグイン）で再利用可能。
Vanilla 環境では、テンプレート仕様とファイル構成が整備されるため、
プラグイン実装時にこれらの関数を即座に活用できます。
"""

import os
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from jinja2 import Environment, TemplateSyntaxError

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

# ============ v3.2.0: Jinja2 動的変数フィルター ============


def _format_date_filter(value=None, format_str="%Y年%m月%d日") -> str:
    """
    現在日時を指定形式でフォーマット

    使用例: {{ current_date | format_date }}
           {{ current_date | format_date('%Y-%m-%d') }}
    """
    if value is None:
        value = datetime.now()
    elif isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return str(value)

    if isinstance(value, datetime):
        return value.strftime(format_str)
    return str(value)


def _format_datetime_filter(value=None, format_str="%Y年%m月%d日 %H:%M") -> str:
    """
    現在日時を指定形式でフォーマット（時刻含む）

    使用例: {{ current_datetime | format_datetime }}
           {{ current_datetime | format_datetime('%Y-%m-%d %H:%M:%S') }}
    """
    if value is None:
        value = datetime.now()
    elif isinstance(value, str):
        try:
            # ★ ニコニコ形式 '2025-09-17T19:03+0900' に対応
            # ISO 8601 形式で :00 がない場合は補完
            if "+" in value or value.endswith("Z"):
                # タイムゾーン形式を正規化
                if value.count("+") == 1 and ":" not in value.split("+")[1]:
                    # +0900 形式を +09:00 に変換
                    parts = value.split("+")
                    tz = parts[1]
                    if len(tz) == 4:  # 0900 → 09:00
                        value = f"{parts[0]}+{tz[:2]}:{tz[2:]}"
                elif value.count("-") >= 3:  # -09:00 形式をチェック
                    # タイムゾーンが -0900 形式の場合も同様に処理
                    if value[-5] in ["+", "-"] and ":" not in value[-5:]:
                        tz_part = value[-4:]
                        value = value[:-4] + f"{value[-5]}{tz_part[:2]}:{tz_part[2:]}"

            value = datetime.fromisoformat(value)
        except Exception as e:
            logger.debug(f"⚠️ 日時パース失敗: {value} - {e}")
            return str(value)

    if isinstance(value, datetime):
        return value.strftime(format_str)
    return str(value)


def _random_emoji_filter(emoji_list=None) -> str:
    """
    ランダムに絵文字を選択

    使用例: {{ | random_emoji }}                              （デフォルト絵文字から選択）
           {{ | random_emoji('🎬,🎥,📹') }}  （カスタム絵文字リストから選択）
    """
    if emoji_list is None:
        # デフォルト絵文字リスト
        emoji_list = ["🎬", "🎥", "📹", "✨", "🌟", "⭐", "🎯", "🎪", "🎨", "🎭"]
    elif isinstance(emoji_list, str):
        emoji_list = emoji_list.split(",")

    return random.choice(emoji_list)


def calculate_extended_time_for_event(video_dict: Dict[str, Any]) -> None:
    """
    イベント情報から拡張時刻を計算して video_dict に追加

    ★ v3.3.0: 朝早い時刻（00:00～12:00）を拡張時刻として表現

    例: published_at が 2025-12-29 03:00 の場合
    → 2025-12-29 の 27 時として表現（同日基準日 27 時）

    つまり：
    - displayed_date = 2025-12-29（DB保存日付）
    - extended_hour = 27（24 + 3）
    - テンプレート出力: 「2025年12月29日27時(2025年12月30日(火)午前3時)」

    Args:
        video_dict: 動画情報辞書（published_at を含む）

    Returns:
        None。video_dict に以下を追加:
        - extended_hour: 拡張時刻（27など、朝早い場合は 24 + 時刻）
        - extended_display_date: 拡張表示用の日付（DB保存日付）
    """
    try:
        published_at_str = video_dict.get("published_at")
        if not published_at_str:
            return

        # 日時を解析
        try:
            published_at = datetime.fromisoformat(published_at_str)
        except Exception:
            return

        hour = published_at.hour
        date = published_at.date()

        # ★ 朝早い時刻（00:00～12:00）の場合、拡張時刻として解釈
        if hour < 12:
            # 拡張時刻 = 24 + 時刻（例：27 = 24 + 3）
            extended_hour = 24 + hour
            # 表示日付は DB 保存日付（変更なし）
            extended_display_date = date.strftime("%Y-%m-%d")

            logger.debug(
                f"🔢 拡張時刻: {date} {hour:02d}:00 → {extended_display_date} {extended_hour}時"
            )
        else:
            # 正午以降の場合は通常時刻
            extended_hour = hour
            extended_display_date = date.strftime("%Y-%m-%d")
            logger.debug(f"🔢 通常時刻: {date} {hour:02d}:00")

        video_dict["extended_hour"] = extended_hour
        video_dict["extended_display_date"] = extended_display_date

    except Exception as e:
        logger.warning(f"⚠️ 拡張時刻計算エラー: {e}")


def _weekday_filter(value=None) -> str:
    """
    曜日を日本語で返す

    使用例: {{ published_at | weekday }}
    """
    if value is None:
        value = datetime.now()
    elif isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return str(value)

    if isinstance(value, datetime):
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        return weekdays[value.weekday()]
    return str(value)


# ============ v3.3.0: 24時以降の時刻正規化機能 ============


def parse_extended_time(time_str: str) -> Optional[Dict[str, Any]]:
    """
    24時以降の拡張時刻表記をパース・正規化

    入力形式:
      - "25:00" → 次の日の1:00
      - "27:30" → 次の日の3:30
      - "30:00" → 次の日の6:00
      - "14:30" → 当日の14:30（24時以下は通常通り）

    Args:
        time_str: 時刻文字列 ("HH:MM" 形式)

    Returns:
        {
            "original": "25:00",                      # 元の入力
            "normalized_24h": "01:00",                # 正規化後の24時間制表記
            "hours_24h": 1,                          # 正規化後の時（0-23）
            "minutes": 0,                            # 分
            "day_offset": 1,                         # 日付オフセット（0=当日、1=翌日など）
            "is_extended": True,                     # 24時以降フラグ
            "display_with_date": "翌日1:00時"        # 日付付き表示
        }
        パース失敗時は None
    """
    try:
        if isinstance(time_str, str):
            parts = time_str.strip().split(":")
            if len(parts) != 2:
                return None

            hours = int(parts[0])
            minutes = int(parts[1])

            # 基本検証：範囲 0-30時、分は 0-59
            if hours < 0 or hours > 30 or minutes < 0 or minutes > 59:
                logger.warning(
                    f"⚠️ 拡張時刻の範囲エラー: {time_str} (範囲: 00:00-30:00)"
                )
                return None

            # 24時以降の場合は日付をオフセット
            day_offset = 0
            hours_24h = hours

            if hours >= 24:
                day_offset = hours // 24
                hours_24h = hours % 24

            is_extended = hours >= 24

            return {
                "original": time_str,
                "normalized_24h": f"{hours_24h:02d}:{minutes:02d}",
                "hours_24h": hours_24h,
                "minutes": minutes,
                "day_offset": day_offset,
                "is_extended": is_extended,
                "display_with_date": (
                    f"{'翌日' if day_offset == 1 else f'{day_offset}日後'}{hours_24h:02d}:{minutes:02d}時"
                    if is_extended
                    else f"{hours_24h:02d}:{minutes:02d}時"
                ),
            }

    except (ValueError, IndexError):
        logger.warning(f"⚠️ 拡張時刻のパースエラー: {time_str}")
        return None

    return None


def normalize_datetime_with_extended_time(
    date_str: str, time_str: str
) -> Optional[Dict[str, Any]]:
    """
    日付と拡張時刻（24時以降）をパースして正規化

    Args:
        date_str: 日付文字列 ("YYYY-MM-DD" or ISO形式)
        time_str: 時刻文字列 ("HH:MM" 形式、24時以降対応)

    Returns:
        {
            "original_date": "2025-12-21",
            "original_time": "27:00",
            "normalized_date": "2025-12-22",            # 正規化後の日付（翌日）
            "normalized_time": "03:00",                # 正規化後の時刻（24時間制）
            "normalized_datetime": "2025-12-22T03:00", # ISO形式の日時
            "display": "2025年12月22日(月)午前3時00分", # 日本語表示（翌日！）
            "is_extended": True,                        # 24時以降フラグ
            "day_offset": 1,                           # 日付オフセット
        }
        パース失敗時は None

    例:
        入力:  2025-12-21 27:00 → 出力: 2025年12月22日午前3時00分
        入力:  2025-12-21 25:30 → 出力: 2025年12月22日午前1時30分
    """
    try:
        # 日付をパース
        if isinstance(date_str, str):
            # ISO形式や YYYY-MM-DD に対応
            if "T" in date_str:
                date_part = date_str.split("T")[0]
            else:
                date_part = date_str

            base_date = datetime.strptime(date_part, "%Y-%m-%d").date()
        else:
            return None

        # 時刻をパース
        time_info = parse_extended_time(time_str)
        if time_info is None:
            return None

        # 日付をオフセット
        normalized_date = base_date + timedelta(days=time_info["day_offset"])

        # 正規化された日時を生成
        normalized_dt = datetime.combine(
            normalized_date,
            datetime.min.time().replace(
                hour=time_info["hours_24h"], minute=time_info["minutes"]
            ),
        )

        # 日本語表示を生成
        weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]
        weekday = weekdays_jp[normalized_dt.weekday()]
        period = "午前" if time_info["hours_24h"] < 12 else "午後"
        hour_12h = (
            time_info["hours_24h"]
            if time_info["hours_24h"] <= 12
            else time_info["hours_24h"] - 12
        )
        if hour_12h == 0:
            hour_12h = 12

        display = f"{normalized_date.year}年{normalized_date.month}月{normalized_date.day}日({weekday}){period}{hour_12h}時{time_info['minutes']:02d}分"

        return {
            "original_date": date_part,
            "original_time": time_str,
            "normalized_date": str(normalized_date),
            "normalized_time": time_info["normalized_24h"],
            "normalized_datetime": normalized_dt.isoformat(),
            "display": display,
            "is_extended": time_info["is_extended"],
            "day_offset": time_info["day_offset"],
        }

    except Exception as e:
        logger.warning(f"⚠️ 日時の正規化エラー: {date_str} {time_str} - {e}")
        return None


def _extended_time_filter(value: str) -> str:
    """
    Jinja2 フィルター: 拡張時刻を正規化（24時以降対応）

    使用例:
        {{ "25:30" | extended_time }}                → "01:30"
        {{ "27:00" | extended_time_display }}        → "翌日3:00時"

    Args:
        value: 時刻文字列 ("HH:MM")

    Returns:
        正規化されたHH:MM形式の時刻
    """
    time_info = parse_extended_time(value)
    if time_info:
        return time_info["normalized_24h"]
    return str(value)


def _extended_time_display_filter(value: str) -> str:
    """
    Jinja2 フィルター: 拡張時刻を日付付き表示

    使用例:
        {{ "25:30" | extended_time_display }}        → "翌日1:30時"
        {{ "30:00" | extended_time_display }}        → "翌日6:00時"

    Args:
        value: 時刻文字列 ("HH:MM")

    Returns:
        日付付きの表示文字列
    """
    time_info = parse_extended_time(value)
    if time_info:
        return time_info["display_with_date"]
    return str(value)


def _extended_datetime_display_filter(date_str: str, time_str: str) -> str:
    """
    Jinja2 フィルター: 拡張時刻を含む日時を日本語表示

    Jinja2 では複数引数フィルターが難しいため、テンプレート内では
    以下のように使用してください：

    使用例:
        {% set normalized = normalize_extended_datetime('2025-12-21', '27:00') %}
        放送日：{{ normalized.display }}
        ({{ normalized.original_time }} → 正規化時刻: {{ normalized.normalized_time }})

    または、より簡潔に：
        放送日：{{ published_at | datetimeformat('%Y年%m月%d日') }}27時
        ({{ published_at | datetimeformat('%Y年%m月%d日') }} 午前3時) JST

    Args:
        date_str: 日付文字列 ("YYYY-MM-DD")
        time_str: 時刻文字列 ("HH:MM")

    Returns:
        正規化された日本語表示
    """
    result = normalize_datetime_with_extended_time(date_str, time_str)
    if result:
        return result["display"]
    return f"{date_str} {time_str}"


# ============ テンプレート種別ごとの required_keys 定義 ============

TEMPLATE_REQUIRED_KEYS = {
    # YouTube
    "youtube_new_video": ["title", "video_id", "video_url", "channel_name"],
    "youtube_online": ["title", "video_url", "channel_name", "live_status"],
    "youtube_offline": ["title", "channel_name", "live_status"],
    "youtube_archive": [
        "title",
        "video_url",
        "channel_name",
    ],  # ★ アーカイブテンプレート追加
    # ニコニコ
    "nico_new_video": ["title", "video_id", "video_url", "channel_name"],
    # Twitch（将来）
    "twitch_online": ["title", "stream_url", "broadcaster_user_name", "game_name"],
    "twitch_offline": ["broadcaster_user_name", "channel_url"],
    "twitch_raid": [
        "from_broadcaster_user_name",
        "to_broadcaster_user_name",
        "raid_url",
    ],
}

# ============ テンプレート種別ごとの表示可能変数（ボタン挿入用） ============

TEMPLATE_ARGS = {
    # YouTube 新着動画
    "youtube_new_video": [
        ("動画タイトル", "title"),
        ("動画 URL", "video_url"),
        ("チャンネル名", "channel_name"),
        ("投稿日", "published_at | datetimeformat('%Y年%m月%d日')"),
        ("投稿日時", "published_at | datetimeformat('%Y年%m月%d日 %H:%M')"),
    ],
    # YouTube 配信開始
    "youtube_online": [
        ("配信タイトル", "title"),
        ("配信 URL", "video_url"),
        ("チャンネル名", "channel_name"),
        ("配信開始日時(通常)", "published_at | datetimeformat('%Y年%m月%d日 %H:%M')"),
        ("配信ステータス", "live_status"),
    ],
    # YouTube 配信終了
    "youtube_offline": [
        ("配信タイトル", "title"),
        ("配信 URL", "video_url"),
        ("チャンネル名", "channel_name"),
        ("配信終了日", "published_at | datetimeformat('%Y年%m月%d日')"),
        ("配信ステータス", "live_status"),
    ],
    # YouTube スケジュール枠（★ 新規追加）
    "youtube_schedule": [
        ("スケジュール枠タイトル", "title"),
        ("配信 URL", "video_url"),
        ("チャンネル名", "channel_name"),
        (
            "予定配信開始日時(通常)",
            "published_at | datetimeformat('%Y年%m月%d日 %H:%M')",
        ),
        (
            "予定配信開始日時(拡張)",
            "format_extended_datetime_range(published_at | datetimeformat('%Y-%m-%d'), 27)",
        ),
        ("配信ステータス", "live_status"),
    ],
    # YouTube アーカイブ（★ 新規追加）
    "youtube_archive": [
        ("アーカイブタイトル", "title"),
        ("アーカイブ URL", "video_url"),
        ("チャンネル名", "channel_name"),
        ("配信日", "published_at | datetimeformat('%Y年%m月%d日')"),
    ],
    # ニコニコ 新着動画
    # ご注意: ユーザー名は自動取得（RSS > 静画API > ユーザーページ > 環境変数 > ユーザーID）
    #        取得されたユーザー名は settings.env に自動保存されます
    "nico_new_video": [
        ("動画タイトル", "title"),
        ("動画 URL", "video_url"),
        (
            "投稿者名",
            "channel_name",
        ),  # 自動取得・優先順位: RSS > 静画API > ユーザーページ > 環境変数 > ユーザーID
        ("投稿日時", "published_at | datetimeformat('%Y年%m月%d日')"),
    ],
    # Twitch 配信開始（将来）
    "twitch_online": [
        ("配信タイトル", "title"),
        ("配信者表示名", "broadcaster_user_name"),
        ("配信者ログイン名", "broadcaster_user_login"),
        ("ゲーム名", "game_name"),
        ("配信 URL", "stream_url"),
        ("配信開始日時", "started_at"),
    ],
    # Twitch 配信終了（将来）
    "twitch_offline": [
        ("配信者表示名", "broadcaster_user_name"),
        ("チャンネル URL", "channel_url"),
        ("配信終了日時", "ended_at"),
    ],
    # Twitch Raid（将来）
    "twitch_raid": [
        ("Raid 元：配信者表示名", "from_broadcaster_user_name"),
        ("Raid 先：配信者表示名", "to_broadcaster_user_name"),
        ("Raid URL", "raid_url"),
    ],
}

# ============ ユーザーに見せない内部キー（ブラックリスト） ============

TEMPLATE_VAR_BLACKLIST = {
    "youtube_new_video": {
        "is_premiere",  # プレミア判定フラグ
        "image_mode",  # 画像モード
        "image_filename",  # キャッシュ済み画像ファイル名
        "posted_at",  # DB 用
        "selected_for_post",  # DB 用
        "use_link_card",  # 内部用
        "embed",  # 内部用
        "image_source",  # 内部用
        "video_id",  # 内部用
    },
    "youtube_online": {
        "is_premiere",
        "image_mode",
        "image_filename",
        "posted_at",
        "selected_for_post",
        "use_link_card",
        "embed",
        "image_source",
        "video_id",
        "live_status",  # ライブ中には不要
    },
    "youtube_offline": {
        "image_mode",
        "image_filename",
        "posted_at",
        "selected_for_post",
        "use_link_card",
        "embed",
        "image_source",
        "video_id",
        "live_status",  # オフラインには不要
    },
    "youtube_schedule": {  # ★ スケジュール枠テンプレート追加
        "image_mode",
        "image_filename",
        "posted_at",
        "selected_for_post",
        "use_link_card",
        "embed",
        "image_source",
        "video_id",
        "live_status",  # スケジュール枠には不要
    },
    "youtube_archive": {  # ★ アーカイブテンプレート追加
        "image_mode",
        "image_filename",
        "posted_at",
        "selected_for_post",
        "use_link_card",
        "embed",
        "image_source",
        "live_status",  # アーカイブには不要
        "video_id",
    },
    "nico_new_video": {
        "image_mode",
        "image_filename",
        "posted_at",
        "selected_for_post",
        "use_link_card",
        "embed",
        "image_source",
    },
    # Twitch（将来）
    "twitch_online": {
        "image_mode",
        "image_filename",
        "use_link_card",
        "embed",
    },
    "twitch_offline": {
        "use_link_card",
        "embed",
    },
    "twitch_raid": {
        "use_link_card",
        "embed",
    },
}

# ============ デフォルトテンプレートパス ============

TEMPLATE_ROOT = Path(__file__).parent / "templates"
DEFAULT_TEMPLATE_DIR = TEMPLATE_ROOT / ".templates"
DEFAULT_TEMPLATE_PATH = DEFAULT_TEMPLATE_DIR / "default_template.txt"
FALLBACK_TEMPLATE_PATH = DEFAULT_TEMPLATE_DIR / "fallback_template.txt"

# ============ ユーティリティ関数 ============


def _get_env_var_from_file(file_path: str, env_var_name: str) -> Optional[str]:
    """
    settings.env などの設定ファイルから環境変数を読み込む（os.getenv の補完）。

    Python の os.getenv() は .env ファイルから環境変数を読み込まないため、
    ここで手動でファイルを読んで、settings.env から値を取得します。

    Args:
        file_path: 設定ファイルパス（例: "settings.env"）
        env_var_name: 環境変数名（例: "TEMPLATE_YOUTUBE_NEW_VIDEO_PATH"）

    Returns:
        環境変数の値、見つからない場合は None
    """
    try:
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            return None

        with open(file_path_obj, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    if key.strip() == env_var_name:
                        return value.strip()
    except Exception as e:
        logger.debug(f"⚠️ 設定ファイル読み込みエラー ({file_path}): {e}")

    return None


def _get_legacy_env_var_name(template_type: str) -> str:
    """
    テンプレート種別からレガシー形式の環境変数名を生成（後方互換性用）。

    Args:
        template_type: テンプレート種別（例: "youtube_new_video"）

    Returns:
        レガシー形式の環境変数名
        例: "youtube_new_video" → "BLUESKY_YT_NEW_VIDEO_TEMPLATE_PATH"
            "nico_new_video" → "BLUESKY_NICO_NEW_VIDEO_TEMPLATE_PATH"
    """
    parts = template_type.split("_")
    if len(parts) >= 2:
        service_name = parts[0]
        event_type = "_".join(parts[1:])

        # ショートカット生成
        service_short = {
            "youtube": "YT",
            "nico": "NICO",
            "niconico": "NICO",
            "twitch": "TW",
        }.get(service_name, service_name.upper())

        legacy_var = f"BLUESKY_{service_short}_{event_type.upper()}_TEMPLATE_PATH"
        return legacy_var

    return f"BLUESKY_{template_type.upper()}_TEMPLATE_PATH"


def get_template_path(
    template_type: str, env_var_name: str = None, default_fallback: str = None
) -> Optional[str]:
    """
    環境変数からテンプレートパスを取得、なければデフォルトを返す。

    Args:
        template_type: テンプレート種別（例: "youtube_new_video"）
        env_var_name: 環境変数名（省略時は自動生成）
                     例: "TEMPLATE_YOUTUBE_NEW_VIDEO_PATH" （推奨）
                         or "BLUESKY_YT_NEW_VIDEO_TEMPLATE_PATH" （レガシー）
        default_fallback: フォールバック先デフォルトパス

    Returns:
        テンプレートファイルパス（文字列）、見つからない場合は None

    環境変数の解決順序:
        1. env_var_name で明示的に指定された名前
        2. TEMPLATE_{template_type}_PATH 形式
        3. BLUESKY_*_TEMPLATE_PATH 形式（レガシー）
        4. default_fallback（指定時）
        5. 自動推論（service_short と event_type から）
    """
    # 明示的に指定された環境変数名が最優先
    if env_var_name:
        env_path = os.getenv(env_var_name)
        if env_path:
            return env_path

    # 新形式: TEMPLATE_{template_type}_PATH
    new_format_env_var = f"TEMPLATE_{template_type.upper()}_PATH"

    # ★ 修正: 複数ソースから読み込む
    # 優先度 1: os.getenv（システム環境変数）
    env_path = os.getenv(new_format_env_var)

    # 優先度 2: settings.env から直接読み込む
    if not env_path:
        env_path = _get_env_var_from_file("settings.env", new_format_env_var)
        if env_path:
            logger.debug(
                f"✅ settings.env から読み込み: {new_format_env_var} = {env_path}"
            )

    if env_path:
        return env_path

    # レガシー形式: BLUESKY_*_TEMPLATE_PATH（後方互換性）
    # 例: youtube_new_video → BLUESKY_YT_NEW_VIDEO_TEMPLATE_PATH
    legacy_format_env_var = _get_legacy_env_var_name(template_type)

    # 優先度 1: os.getenv（システム環境変数）
    env_path = os.getenv(legacy_format_env_var)

    # 優先度 2: settings.env から直接読み込む
    if not env_path:
        env_path = _get_env_var_from_file("settings.env", legacy_format_env_var)
        if env_path:
            logger.debug(
                f"✅ settings.env から読み込み（レガシー形式）: {legacy_format_env_var} = {env_path}"
            )

    if env_path:
        return env_path

    # デフォルトフォールバック
    if default_fallback:
        return default_fallback

    # ここからは推論：テンプレート種別から自動構築を試みる
    # 例: "youtube_new_video" → "templates/youtube/yt_new_video_template.txt"
    parts = template_type.split("_")
    if len(parts) >= 2:
        service_name = parts[0]
        event_type = "_".join(parts[1:])

        # ショートカット生成
        service_short = {
            "youtube": "yt",
            "nico": "nico",
            "niconico": "nico",
            "twitch": "twitch",
        }.get(service_name, service_name)

        template_filename = f"{service_short}_{event_type}_template.txt"
        template_path = TEMPLATE_ROOT / service_name / template_filename

        if template_path.exists():
            return str(template_path)

    return None


def load_template_with_fallback(
    path: str, default_path: str = None, template_type: str = "unknown"
) -> Optional[Any]:
    """
    テンプレートファイルを読み込み、失敗時はデフォルトにフォールバック。

    Args:
        path: 読み込み対象のテンプレートファイルパス
        default_path: フォールバック先のデフォルトテンプレートパス
        template_type: テンプレート種別（ログ出力用）

    Returns:
        Jinja2 Template オブジェクト、失敗時は None

    ログ出力:
        - 成功時: DEBUG レベル
        - フォールバック: WARNING レベル
        - エラー: ERROR レベル
    """
    if not path:
        logger.warning(
            f"⚠️ テンプレートパスが指定されていません（種別: {template_type}）"
        )
        path = default_path or str(DEFAULT_TEMPLATE_PATH)

    try:
        # ★ 相対パス → 絶対パス変換（TEMPLATE_ROOT 基準）
        template_path = Path(path)
        logger.debug(f"🔍 初期パス: {path}, is_absolute={template_path.is_absolute()}")
        logger.debug(
            f"   TEMPLATE_ROOT={TEMPLATE_ROOT}, TEMPLATE_ROOT.parent={TEMPLATE_ROOT.parent}"
        )

        if not template_path.is_absolute():
            # 相対パスの場合は TEMPLATE_ROOT を基準に解決
            template_path = TEMPLATE_ROOT.parent / path  # v3 ディレクトリ基準
            logger.debug(f"🔍 相対パスを絶対パスに変換: {path} → {template_path}")

        # ファイルの存在確認
        logger.debug(f"🔍 テンプレートファイル存在確認: {template_path}")
        logger.debug(f"   exists={template_path.exists()}")

        if not template_path.exists():
            logger.warning(f"⚠️ テンプレートファイルが見つかりません: {template_path}")
            if default_path:
                logger.info(
                    f"🔄 デフォルトテンプレートにフォールバック: {default_path}"
                )
                path = default_path
                # フォールバック時も相対パス → 絶対パス変換を試みる
                template_path = Path(path)
                if not template_path.is_absolute():
                    template_path = TEMPLATE_ROOT.parent / path
                    logger.debug(
                        f"🔍 フォールバック時に相対パスを絶対パスに変換: {path} → {template_path}"
                    )
                logger.debug(
                    f"🔍 フォールバック先ファイル存在確認: {template_path} (exists={template_path.exists()})"
                )
            else:
                logger.warning(f"❌ フォールバックパスも指定されていません")
                return None

        # ファイル読み込み
        logger.debug(f"🔍 ファイルを開く: {template_path}")
        with open(template_path, encoding="utf-8") as f:
            template_str = f.read()

        # Jinja2 Environment でテンプレート化
        env = Environment()
        # ★ Jinja2 ビルトインフィルターを有効化（int, upper, lower など）

        # フィルターを登録（format_datetime_filter は別途提供）
        from utils_v3 import format_datetime_filter

        env.filters["datetimeformat"] = format_datetime_filter

        # v3.2.0: 動的変数フィルターを登録
        env.filters["format_date"] = _format_date_filter
        env.filters["format_datetime"] = _format_datetime_filter
        env.filters["random_emoji"] = _random_emoji_filter
        env.filters["weekday"] = _weekday_filter

        # v3.3.0: 拡張時刻フィルターを登録
        env.filters["extended_time"] = _extended_time_filter
        env.filters["extended_time_display"] = _extended_time_display_filter

        template_obj = env.from_string(template_str)

        logger.debug(f"✅ テンプレート読み込み成功: {path} (種別: {template_type})")
        return template_obj

    except FileNotFoundError as e:
        logger.error(
            f"❌ テンプレートファイル読み込みエラー: {template_path} (path={path})"
        )
        logger.error(f"   詳細: ファイルが見つかりません - {e}")
        if default_path and path != default_path:
            logger.info(f"🔄 デフォルトテンプレートにフォールバック: {default_path}")
            return load_template_with_fallback(
                default_path, default_path=None, template_type=template_type
            )
        return None

    except TemplateSyntaxError as e:
        logger.error(f"❌ テンプレート構文エラー: {template_path} - {e}")
        return None

    except Exception as e:
        import traceback

        logger.error(
            f"❌ テンプレート読み込み予期しないエラー: {type(e).__name__}: {e}"
        )
        logger.error(f"   パス: {template_path}")
        logger.error(f"   トレースバック: {traceback.format_exc()}")
        return None


def validate_required_keys(
    event_context: dict, required_keys: List[str], event_type: str = "unknown"
) -> Tuple[bool, Optional[List[str]]]:
    """
    event_context に必須キーが存在するか検証。

    Args:
        event_context: 投稿イベント情報（辞書）
        required_keys: 必須キー一覧
        event_type: イベント種別（ログ出力用）

    Returns:
        (検証成功フラグ, 不足キー一覧)
        - 成功時: (True, None)
        - 失敗時: (False, ["key1", "key2", ...])

    ログ出力:
        - 成功時: DEBUG レベル
        - 失敗時: WARNING レベル
    """
    if not required_keys:
        logger.debug(f"✅ 必須キーなし（種別: {event_type}）")
        return True, None

    missing_keys = [
        key
        for key in required_keys
        if key not in event_context or event_context[key] is None
    ]

    if not missing_keys:
        logger.debug(
            f"✅ 必須キー検証成功（種別: {event_type}、キー数: {len(required_keys)}）"
        )
        return True, None
    else:
        logger.warning(f"⚠️ 必須キー不足（種別: {event_type}）: {missing_keys}")
        return False, missing_keys


def render_template(
    template_obj: Any, event_context: dict, template_type: str = "unknown"
) -> Optional[str]:
    """
    Jinja2 テンプレートをレンダリング。

    v3.3.0: 拡張時刻対応
    - event_context に "scheduled_at" が存在し、かつ "HH:MM" 形式の時刻文字列を含む場合
    - 自動的に以下の変数が追加される:
      - scheduled_at_normalized: 正規化された24時間制表記 ("01:00" など)
      - scheduled_at_display: 日付付き表示 ("翌日1:00時" など)
      - scheduled_at_is_extended: 24時以降フラグ

    Args:
        template_obj: Jinja2 Template オブジェクト
        event_context: 投稿イベント情報
        template_type: テンプレート種別（ログ出力用）

    Returns:
        レンダリング済みテキスト、失敗時は None

    ログ出力:
        - 成功時: DEBUG レベル
        - 失敗時: ERROR レベル

    使用例：
        event_context = {
            "title": "新作動画",
            "scheduled_at": "25:30"  # 25時30分（翌日1時30分）
        }
        rendered = render_template(template_obj, event_context)
        # テンプレート内で使用可能:
        # {{ scheduled_at }}                          → "25:30"
        # {{ scheduled_at | extended_time }}          → "01:30"
        # {{ scheduled_at | extended_time_display }}  → "翌日1:30時"
        # {{ scheduled_at_normalized }}               → "01:30"
        # {{ scheduled_at_display }}                  → "翌日1:30時"
        # {{ scheduled_at_is_extended }}              → true
        #
        # ⚠️ 重要: 日付を超える場合は翌日になります
        # 例: 2025-12-21 27:00 → 2025年12月22日午前3時00分（22日！）
    """
    if not template_obj:
        logger.error(
            f"❌ テンプレートオブジェクトが None です（種別: {template_type}）"
        )
        return None

    try:
        # ★ v3.3.0: 拡張時刻の自動処理
        context = dict(event_context)  # 元のevent_contextを保護

        if "scheduled_at" in context and isinstance(context["scheduled_at"], str):
            scheduled_at_str = context["scheduled_at"].strip()

            # "HH:MM" または "HH:MM:SS" 形式のパース試行
            time_parts = scheduled_at_str.split(":")
            if len(time_parts) >= 2:
                try:
                    # 拡張時刻をパース
                    time_info = parse_extended_time(f"{time_parts[0]}:{time_parts[1]}")
                    if time_info:
                        # event_context に拡張時刻変数を追加
                        context["scheduled_at_normalized"] = time_info["normalized_24h"]
                        context["scheduled_at_display"] = time_info["display_with_date"]
                        context["scheduled_at_is_extended"] = time_info["is_extended"]

                        if time_info["is_extended"]:
                            logger.debug(
                                f"✅ 拡張時刻を正規化: {scheduled_at_str} → {time_info['normalized_24h']} ({time_info['display_with_date']})"
                            )

                except Exception as e:
                    logger.debug(f"⚠️ 拡張時刻の処理スキップ: {e}")

        # ★ v3.3.0: テンプレート内で使用可能なカスタム関数を注入
        context["normalize_extended_datetime"] = normalize_datetime_with_extended_time

        # ★ 日付と拡張時刻の合成表示用ヘルパー関数
        def format_extended_datetime_range(
            base_date_str: str, extended_hour_or_time: Any
        ) -> str:
            """
            基準日付と拡張時刻から、日付と時刻の両方を正規化して併記

            使用例:
                {{ format_extended_datetime_range(published_at | datetimeformat('%Y-%m-%d'), 27) }}
                → "2025年12月21日27時(2025年12月22日(月)午前3時)"

                {{ format_extended_datetime_range(scheduled_start_date, scheduled_start_time_hhmm) }}
                → "2025年12月29日27:00(2025年12月30日(木)午前3時)"
            """
            try:
                # extended_hour_or_time が文字列の場合（"27:00"）と整数の場合（27）に対応
                if isinstance(extended_hour_or_time, str):
                    # "27:00" 形式の場合
                    time_parts = extended_hour_or_time.split(":")
                    extended_hour = int(time_parts[0]) if time_parts else 0
                else:
                    # 整数の場合（27）
                    extended_hour = int(extended_hour_or_time)

                logger.debug(
                    f"🔍 format_extended_datetime_range: base_date_str={base_date_str}, extended_hour={extended_hour}"
                )

                # 時刻情報から正規化
                time_info = parse_extended_time(f"{extended_hour}:00")
                if not time_info:
                    result = f"{base_date_str}{extended_hour}時"
                    logger.warning(f"⚠️ time_info パース失敗: {result}")
                    return result

                # base_date_str を datetime.date に変換（フォーマット: YYYY-MM-DD）
                from datetime import datetime as dt

                base_date = dt.strptime(base_date_str, "%Y-%m-%d").date()

                # 日付をオフセット
                from datetime import timedelta

                normalized_date = base_date + timedelta(days=time_info["day_offset"])

                # 日本語表示
                weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]
                weekday = weekdays_jp[normalized_date.weekday()]
                period = "午前" if time_info["hours_24h"] < 12 else "午後"
                hour_12h = (
                    time_info["hours_24h"]
                    if time_info["hours_24h"] <= 12
                    else time_info["hours_24h"] - 12
                )
                if hour_12h == 0:
                    hour_12h = 12

                # 元の日付も日本語に変換
                base_date_jp = f"{base_date.year}年{base_date.month}月{base_date.day}日"
                result = f"{base_date_jp}{extended_hour}時({normalized_date.year}年{normalized_date.month}月{normalized_date.day}日({weekday}){period}{hour_12h}時)"
                logger.debug(f"✅ format_extended_datetime_range 成功: {result}")
                return result
            except Exception as e:
                logger.warning(
                    f"⚠️ 拡張日時フォーマットエラー: {e} (base_date_str={base_date_str}, extended_hour_or_time={extended_hour_or_time})"
                )
                return f"{base_date_str}{extended_hour_or_time}時"

        context["format_extended_datetime_range"] = format_extended_datetime_range

        # ★ Jinja2 ビルトインフィルターをコンテキストに追加
        context["int"] = int  # int フィルター用
        context["str"] = str  # str フィルター用
        context["float"] = float  # float フィルター用

        rendered_text = template_obj.render(**context)
        logger.debug(f"✅ テンプレートレンダリング成功（種別: {template_type}）")
        return rendered_text

    except Exception as e:
        logger.error(f"❌ テンプレートレンダリングエラー（種別: {template_type}）: {e}")
        return None


def get_template_args_for_dialog(
    template_type: str, blacklist: bool = True
) -> List[Tuple[str, str]]:
    """
    テンプレート編集ダイアログ用に、表示可能な変数リストを取得。

    Args:
        template_type: テンプレート種別
        blacklist: 除外動画リストを適用するか（デフォルト: True）

    Returns:
        [(変数表示名, 変数キー), ...] のリスト
    """
    args = TEMPLATE_ARGS.get(template_type, [])

    if blacklist:
        blacklist_set = TEMPLATE_VAR_BLACKLIST.get(template_type, set())
        # ブラックリストに含まれるキーを除外
        args = [
            (display_name, key)
            for display_name, key in args
            if key not in blacklist_set
        ]

    return args


def get_sample_context(template_type: str) -> Dict[str, Any]:
    """
    テンプレート編集ダイアログのプレビュー用サンプル event_context を取得。

    Args:
        template_type: テンプレート種別

    Returns:
        サンプル event_context 辞書
    """
    # サンプルデータ集
    sample_contexts = {
        "youtube_new_video": {
            "title": "新作ゲーム実況【part 1】",
            "video_id": "dQw4w9WgXcQ",
            "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "channel_name": "〇〇チャンネル",
            "published_at": "2025-12-17T15:30:00Z",
            "platform": "YouTube",
            "source": "youtube",
            "content_type": "video",
            "live_status": None,
        },
        "youtube_online": {
            "title": "今夜は雑談配信！",
            "video_url": "https://www.youtube.com/watch?v=example",
            "channel_name": "〇〇チャンネル",
            "published_at": "2025-12-17T20:00:00Z",
            "platform": "YouTube",
            "source": "youtube",
            "content_type": "live",
            "live_status": "live",
        },
        "youtube_offline": {
            "title": "今夜は雑談配信！",
            "channel_name": "〇〇チャンネル",
            "platform": "YouTube",
            "source": "youtube",
            "content_type": "live",
            "live_status": "completed",
        },
        "nico_new_video": {
            "title": "【ゆっくり解説】最新ゲーム",
            "video_id": "sm12345678",
            "video_url": "https://www.nicovideo.jp/watch/sm12345678",
            "channel_name": "投稿者名",
            "published_at": "2025-12-17T10:00:00Z",
            "platform": "Niconico",
            "source": "niconico",
            "content_type": "video",
            "live_status": None,
        },
        "nico_online": {
            "title": "ニコ生配信中",
            "video_url": "https://live.nicovideo.jp/watch/lv1234567",
            "channel_name": "投稿者名",
            "platform": "Niconico",
            "source": "niconico",
            "content_type": "live",
            "live_status": "live",
        },
        "nico_offline": {
            "channel_name": "投稿者名",
            "title": "ニコ生配信中",
            "platform": "Niconico",
            "source": "niconico",
            "content_type": "live",
            "live_status": "completed",
        },
        # Twitch（将来）
        "twitch_online": {
            "title": "ゲーム配信開始！",
            "stream_url": "https://twitch.tv/example_user",
            "broadcaster_user_name": "配信者名",
            "broadcaster_user_login": "example_user",
            "game_name": "Just Chatting",
            "started_at": "2025-12-17T19:00:00Z",
            "platform": "Twitch",
            "source": "twitch",
            "content_type": "live",
            "live_status": "live",
        },
        "twitch_offline": {
            "broadcaster_user_name": "配信者名",
            "channel_url": "https://twitch.tv/example_user",
            "ended_at": "2025-12-17T21:30:00Z",
            "platform": "Twitch",
            "source": "twitch",
            "content_type": "live",
            "live_status": "completed",
        },
    }

    return sample_contexts.get(
        template_type,
        {
            "title": "サンプルタイトル",
            "channel_name": "サンプル投稿者",
            "video_url": "https://example.com/video",
            "platform": "Unknown",
            "source": "unknown",
            "content_type": "video",
            "live_status": None,
        },
    )


# ============ ユーザー向けプレビュー/検証関数 ============


def preview_template(
    template_type: str, template_text: str, event_context: Dict[str, Any] = None
) -> Tuple[bool, str]:
    """
    ユーザーがテンプレート編集ダイアログで入力したテンプレートをプレビュー。

    Args:
        template_type: テンプレート種別
        template_text: ユーザーが入力したテンプレートテキスト
        event_context: プレビュー用 event_context（省略時はサンプル）

    Returns:
        (成功フラグ, プレビューテキスト or エラーメッセージ)
    """
    if event_context is None:
        event_context = get_sample_context(template_type)

    try:
        env = Environment()
        from utils_v3 import format_datetime_filter

        env.filters["datetimeformat"] = format_datetime_filter

        template_obj = env.from_string(template_text)
        rendered = template_obj.render(**event_context)

        logger.debug(f"✅ プレビューレンダリング成功: {template_type}")
        return True, rendered

    except TemplateSyntaxError as e:
        error_msg = f"❌ テンプレート構文エラー (行 {e.lineno}): {e.message}"
        logger.warning(error_msg)
        return False, error_msg

    except Exception as e:
        error_msg = f"❌ プレビュー生成エラー: {str(e)}"
        logger.warning(error_msg)
        return False, error_msg


# ============ テンプレートファイル操作 ============


def save_template_file(
    template_type: str, template_text: str, output_path: str = None
) -> Tuple[bool, str]:
    """
    ユーザーが編集したテンプレートをファイルに保存。

    Args:
        template_type: テンプレート種別
        template_text: テンプレートテキスト
        output_path: 保存先パス（省略時は推論）

    Returns:
        (成功フラグ, メッセージ)
    """
    if not output_path:
        output_path = get_template_path(template_type)

    if not output_path:
        error_msg = f"❌ テンプレート保存先が決定できません（種別: {template_type}）"
        logger.error(error_msg)
        return False, error_msg

    try:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(template_text)

        success_msg = f"✅ テンプレートを保存しました: {output_path}"
        logger.info(success_msg)
        return True, success_msg

    except Exception as e:
        error_msg = f"❌ テンプレート保存エラー: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


if __name__ == "__main__":
    # ユーティリティのテスト実行
    print("Template Utils - v3.3.0")
    print("=" * 50)

    # テスト: サンプル context を表示
    for template_type in ["youtube_new_video", "nico_new_video"]:
        sample = get_sample_context(template_type)
        print(f"\n{template_type}:")
        print(f"  Sample keys: {list(sample.keys())}")

        args = get_template_args_for_dialog(template_type)
        print(f"  Display args: {len(args)} 項目")

    # テスト: 拡張時刻パース
    print("\n" + "=" * 50)
    print("✅ 拡張時刻パーステスト")
    print("=" * 50)

    test_times = ["25:00", "25:30", "27:15", "30:00", "14:30", "00:00"]
    for time_str in test_times:
        result = parse_extended_time(time_str)
        if result:
            print(f"\n入力: {time_str}")
            print(f"  正規化時刻: {result['normalized_24h']}")
            print(f"  表示: {result['display_with_date']}")
            print(f"  24時以降: {result['is_extended']}")

    # テスト: 日時正規化
    print("\n" + "=" * 50)
    print("✅ 日時正規化テスト")
    print("=" * 50)

    result = normalize_datetime_with_extended_time("2025-12-21", "25:30")
    if result:
        print(f"\n入力: 2025-12-21 25:30")
        print(f"  正規化日付: {result['normalized_date']}")
        print(f"  正規化時刻: {result['normalized_time']}")
        print(f"  日本語表示: {result['display']}")
        print(f"  日付オフセット: {result['day_offset']}日")

    print("\n" + "=" * 50)
    print("✅ template_utils.py の基本動作確認完了")
