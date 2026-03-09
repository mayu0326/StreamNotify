# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - プラグインインターフェース

プラグインが実装すべきインターフェース（抽象基底クラス）を定義します。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


class NotificationPlugin(ABC):
    """
    通知プラグインの基底クラス

    すべての通知プラグインはこのインターフェースを実装する必要があります。
    """

    @abstractmethod
    def __init__(self, *args, **kwargs):
        """
        プラグインの初期化

        Args:
            *args: 可変長の位置引数
            **kwargs: 可変長のキーワード引数
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        プラグインが利用可能かどうかを判定

        Returns:
            bool: 利用可能な場合 True、そうでない場合 False
        """
        pass

    @abstractmethod
    def post_video(self, video: Dict[str, Any]) -> bool:
        """
        動画情報を通知先にポスト

        Args:
            video: 動画情報
                - title: 動画タイトル
                - video_id: 動画ID
                - video_url: 動画URL
                - published_at: 公開日時
                - channel_name: チャンネル名
                - その他のメタデータ

        Returns:
            bool: ポスト成功時 True、失敗時 False
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """
        プラグイン名を取得

        Returns:
            str: プラグイン名
        """
        pass

    @abstractmethod
    def get_version(self) -> str:
        """
        プラグインのバージョンを取得

        Returns:
            str: バージョン文字列
        """
        pass

    def get_description(self) -> str:
        """
        プラグインの説明を取得（オプション）

        Returns:
            str: プラグインの説明
        """
        return "プラグインの説明は未設定です"

    def on_enable(self) -> None:
        """
        プラグインが有効になった時に呼ばれる（オプション）
        """
        pass

    def on_disable(self) -> None:
        """
        プラグインが無効になった時に呼ばれる（オプション）
        """
        pass
