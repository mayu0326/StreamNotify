#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bluesky_plugin.py 内の render_template_with_utils() を直接テスト
"""

import sys
from pathlib import Path
import logging

# v3 ディレクトリを sys.path に追加
v3_dir = Path(__file__).parent
sys.path.insert(0, str(v3_dir))
plugins_dir = v3_dir / "plugins"
sys.path.insert(0, str(plugins_dir))

# ロギング設定
logging.basicConfig(level=logging.DEBUG, format="[%(levelname)s] %(name)s: %(message)s")

# PluginInterfaceをインポート
from plugins.bluesky_plugin import BlueskyImagePlugin

# ロガー
logger = logging.getLogger("AppLogger")
post_logger = logging.getLogger("PostLogger")

print("=" * 60)
print("【BlueskyPlugin.render_template_with_utils() テスト】")
print("=" * 60)
print()

# プラグインインスタンスを作成
plugin = BlueskyImagePlugin(username="test@example.com", password="test_password")

# テストコンテキスト
event_context = {
    "title": "【Twitch同時配信】テスト動画",
    "video_id": "test12345",
    "video_url": "https://www.youtube.com/watch?v=test12345",
    "channel_name": "テストチャンネル",
    "published_at": "2025-12-18T04:00:00+09:00",
}

print(f"プラグイン: {plugin.get_name()} v{plugin.get_version()}")
print(f"利用可能: {plugin.is_available()}")
print()

print("テストコンテキスト:")
for k, v in event_context.items():
    print(f"  {k}: {v}")
print()

# テンプレートレンダリングを実行
print("render_template_with_utils() を呼び出し...")
print()

result = plugin.render_template_with_utils("youtube_new_video", event_context)

print()
print("=" * 60)
print("【結果】")
print("=" * 60)
print(f"Result type: {type(result)}")
print(f"Result length: {len(result)}")
print()

if result:
    print("✅ レンダリング成功:")
    print()
    print(result)
else:
    print("❌ レンダリング失敗（空文字列）")
