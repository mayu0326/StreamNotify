#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
キャッシュと環境変数の確認
"""

import os
import sys
from pathlib import Path

# v2 パスを追加
sys.path.insert(0, "v2")

from config import get_config  # noqa: E402

# キャッシュファイルを確認
cache_file = Path("v3/data/youtube_channel_cache.json")
print(f"キャッシュファイル存在: {cache_file.exists()}")
if cache_file.exists():
    with open(cache_file, "r", encoding="utf-8") as f:
        print(f.read())
else:
    print("(キャッシュファイルが見つかりません)")

# 環境変数を確認
print("\n環境変数:")
print(f"YOUTUBE_CHANNEL_ID: {os.getenv('YOUTUBE_CHANNEL_ID')}")
print(f"YOUTUBE_API_KEY: {bool(os.getenv('YOUTUBE_API_KEY'))}")

# settings.env から読み込み
config = get_config("v2/settings.env")
print("\nconfig から取得:")
print(f"YOUTUBE_CHANNEL_ID: {config.youtube_channel_id}")
