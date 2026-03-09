#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API レスポンスのブロードキャストタイプを確認
"""
import sys
sys.path.insert(0, 'v3')

from database import get_database

db = get_database('v3/data/video_list.db')
conn = db._get_connection()
c = conn.cursor()

# YouTube 動画のうち、最初の10件を取得
c.execute('SELECT video_id FROM videos WHERE source = "youtube" LIMIT 10')
video_ids = [row[0] for row in c.fetchall()]
conn.close()

print(f"確認対象: {len(video_ids)} 件")
print("=" * 80)

# プラグインをローカルスコープで使用
try:
    from plugins.youtube_api_plugin import YouTubeAPIPlugin
    api_plugin = YouTubeAPIPlugin()

    if not api_plugin.is_available():
        print("❌ YouTube API プラグインが利用可能ではありません")
        print(f"   API Key: {bool(api_plugin.api_key)}")
        print(f"   Channel ID: {bool(api_plugin.channel_id)}")
        print(f"   Channel Identifier: {api_plugin.channel_identifier}")
    else:
        print("✅ YouTube API プラグインが利用可能です")

        for video_id in video_ids:
            details = api_plugin._fetch_video_detail(video_id)
            if details:
                snippet = details.get("snippet", {})
                status = details.get("status", {})
                live = details.get("liveStreamingDetails", {})

                broadcast_type = snippet.get("liveBroadcastContent", "(未指定)")
                upload_status = status.get("uploadStatus", "(未指定)")

                print(f"\n{video_id}:")
                print(f"  liveBroadcastContent: {broadcast_type}")
                print(f"  uploadStatus: {upload_status}")
                print(f"  liveStreamingDetails: {bool(live)}")
                if live:
                    print(f"    - actualEndTime: {bool(live.get('actualEndTime'))}")
                    print(f"    - actualStartTime: {bool(live.get('actualStartTime'))}")
                    print(f"    - scheduledStartTime: {bool(live.get('scheduledStartTime'))}")
except Exception as e:
    print(f"❌ エラー: {e}")
    import traceback
    traceback.print_exc()
