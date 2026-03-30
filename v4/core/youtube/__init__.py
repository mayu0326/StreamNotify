# -*- coding: utf-8 -*-

"""
YouTube Core - YouTube 共通ユーティリティライブラリ

このパッケージは、YouTube RSS/WebSub/キャッシュ/重複判定といった
プラグイン共通で使用されるコアユーティリティを提供します。

**プラグインシステムと異なり、これは NotificationPlugin インターフェースを
実装せず、通常の Python ライブラリとして import されます。**

モジュール:
  - live_module: YouTube Live 状態管理・自動投稿
  - live_scheduler: YouTube Live スケジュール管理
  - youtube_api_client: YouTube API クライアント
  - youtube_dedup_priority: YouTube 優先度ベース重複排除ロジック
  - youtube_rss: YouTube RSS フィード取得・パース・DB保存
  - youtube_video_classifier: YouTube 動画分類
"""

__version__ = "1.0.0"
__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"
