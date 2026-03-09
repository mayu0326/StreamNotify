# -*- coding: utf-8 -*-

"""
YouTube Core - YouTube 共通ユーティリティライブラリ

このパッケージは、YouTube RSS/WebSub/キャッシュ/重複判定といった
プラグイン共通で使用されるコアユーティリティを提供します。

**プラグインシステムと異なり、これは NotificationPlugin インターフェースを
実装せず、通常の Python ライブラリとして import されます。**

モジュール:
  - youtube_rss: YouTube RSS フィード取得・パース・DB保存
  - youtube_websub: YouTube WebSub (PubSubHubbub) 対応
  - youtube_dedup_priority: YouTube 優先度ベース重複排除ロジック
"""

__version__ = "1.0.0"
__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"
