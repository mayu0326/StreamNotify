#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
キャッシュファイルの確認
"""
from pathlib import Path
import json

cache_file = Path('v3/data/youtube_video_detail_cache.json')

print("=" * 80)
print("キャッシュファイル確認")
print("=" * 80)

if cache_file.exists():
    file_size = cache_file.stat().st_size
    print(f"✅ ファイルが存在します: {cache_file.absolute()}")
    print(f"   ファイルサイズ: {file_size:,} bytes ({file_size / 1024:.1f} KB)")

    with open(cache_file, 'r', encoding='utf-8') as f:
        cache_data = json.load(f)

    print(f"\n📊 キャッシュ統計:")
    print(f"   キャッシュ件数: {len(cache_data)} 件")

    # サンプル表示
    print(f"\n📋 サンプル（最初の3件）:")
    for i, (video_id, entry) in enumerate(list(cache_data.items())[:3], 1):
        title = entry.get('data', {}).get('snippet', {}).get('title', 'N/A')
        timestamp = entry.get('timestamp', 0)
        print(f"   {i}. {video_id}")
        print(f"      タイトル: {title[:50]}")
        print(f"      キャッシュ時刻: {timestamp}")
else:
    print(f"❌ ファイルが見つかりません: {cache_file.absolute()}")

print("\n" + "=" * 80)
