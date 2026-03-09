#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本番 DB の全動画をキャッシュに保存してから終了
"""

import sys

sys.path.insert(0, "v3")

from config import get_config

config = get_config("v3/settings.env")

from database import get_database
from plugins.youtube_api_plugin import YouTubeAPIPlugin

print("=" * 80)
print("本番 DB の動画詳細をキャッシュに保存")
print("=" * 80)

# DB から全YouTube動画を取得
db = get_database("v3/data/video_list.db")
conn = db._get_connection()
c = conn.cursor()
c.execute('SELECT video_id FROM videos WHERE source = "youtube"')
video_ids = [row[0] for row in c.fetchall()]
conn.close()

print(f"対象: {len(video_ids)} 件の YouTube 動画\n")

# プラグイン初期化
api_plugin = YouTubeAPIPlugin()

if not api_plugin.is_available():
    print("❌ YouTube API プラグインが利用可能ではありません")
    sys.exit(1)

print("✅ YouTube API プラグインが利用可能です\n")

# バッチで取得してキャッシュに保存
print("🔄 バッチ取得でキャッシュを構築中...\n")
batch_size = 50
total_units_consumed = 0

for i in range(0, len(video_ids), batch_size):
    batch = video_ids[i : i + batch_size]
    print(
        f"バッチ {i//batch_size + 1}: {len(batch)} 件を処理 ({i+1}-{min(i+batch_size, len(video_ids))}/{len(video_ids)})"
    )

    initial_cost = api_plugin.daily_cost
    api_plugin.fetch_video_details_batch(batch)
    batch_cost = api_plugin.daily_cost - initial_cost
    total_units_consumed += batch_cost
    print(f"  API コスト: {batch_cost} ユニット\n")

print("=" * 80)
print(f"✅ キャッシュ構築完了")
print(f"  キャッシュサイズ: {len(api_plugin.video_detail_cache)} 件")
print(f"  合計 API コスト: {total_units_consumed} ユニット")
print("=" * 80)

# キャッシュを保存
print("\n💾 キャッシュをファイルに保存中...")
api_plugin._save_video_detail_cache()

print("✅ キャッシュを保存しました")
print(f"   ファイル: v3/data/youtube_video_detail_cache.json")

# 統計情報表示
from pathlib import Path

cache_file = Path("v3/data/youtube_video_detail_cache.json")
if cache_file.exists():
    file_size = cache_file.stat().st_size
    print(f"   ファイルサイズ: {file_size:,} bytes ({file_size / 1024:.1f} KB)")
    print(f"\n次回以降、このキャッシュが利用されます！")
    print(
        f"API コスト削減: {len(api_plugin.video_detail_cache)} 件 × 1 ユニット = {len(api_plugin.video_detail_cache)} ユニット節約可能 ✅"
    )
