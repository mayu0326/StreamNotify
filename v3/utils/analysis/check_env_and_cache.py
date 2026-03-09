#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
キャッシュと環境変数の確認
"""
import sys
sys.path.insert(0, 'v2')
import os
from pathlib import Path

# キャッシュファイルを確認
cache_file = Path('v3/data/youtube_channel_cache.json')
print(f"キャッシュファイル存在: {cache_file.exists()}")
if cache_file.exists():
    with open(cache_file, 'r', encoding='utf-8') as f:
        print(f.read())
else:
    print("(キャッシュファイルが見つかりません)")

# 環境変数を確認
print(f"\n環境変数:")
print(f"YOUTUBE_CHANNEL_ID: {os.getenv('YOUTUBE_CHANNEL_ID')}")
print(f"YOUTUBE_API_KEY: {bool(os.getenv('YOUTUBE_API_KEY'))}")

# settings.env から読み込み
from config import get_config
config = get_config('v2/settings.env')
print(f"\nconfig から取得:")
print(f"YOUTUBE_CHANNEL_ID: {config.youtube_channel_id}")
