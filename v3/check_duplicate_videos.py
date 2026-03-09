#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sqlite3

conn = sqlite3.connect("data/video_list.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 重複の可能性がある動画を確認（同じtitle+channel_nameで複数行があるもの）
cursor.execute("""
SELECT title, channel_name, COUNT(*) as cnt, GROUP_CONCAT(video_id, ',') as video_ids,
       GROUP_CONCAT(content_type, ',') as content_types,
       GROUP_CONCAT(live_status, ',') as live_statuses,
       GROUP_CONCAT(CAST(is_premiere AS TEXT), ',') as premieres
FROM videos
WHERE source = 'youtube'
GROUP BY title, channel_name
HAVING cnt > 1
ORDER BY cnt DESC
LIMIT 20
""")

rows = cursor.fetchall()
print("=== YouTubeの重複登録されている動画 ===\n")

if not rows:
    print("重複登録はありません ✅\n")
else:
    for row in rows:
        print(f"タイトル: {row['title'][:60]}")
        print(f"  登録数: {row['cnt']}")
        print(f"  video_ids: {row['video_ids']}")
        print(f"  content_types: {row['content_types']}")
        print(f"  live_statuses: {row['live_statuses']}")
        print(f"  premieres: {row['premieres']}")
        print()

# 同じvideo_idで複数のlive_statusを持つケースを確認
print("=== 同じvideo_idで複数のlive_statusを持つケース ===\n")
cursor.execute("""
SELECT video_id, title, COUNT(*) as cnt,
       GROUP_CONCAT(DISTINCT live_status) as live_statuses,
       GROUP_CONCAT(DISTINCT content_type) as content_types
FROM videos
WHERE source = 'youtube'
GROUP BY video_id
HAVING cnt > 1
ORDER BY cnt DESC
LIMIT 20
""")

rows = cursor.fetchall()
if not rows:
    print("同一video_idの重複はありません ✅\n")
else:
    for row in rows:
        print(f"Video ID: {row['video_id']}")
        print(f"  タイトル: {row['title'][:60]}")
        print(f"  登録数: {row['cnt']}")
        print(f"  live_statuses: {row['live_statuses']}")
        print(f"  content_types: {row['content_types']}")
        print()

conn.close()
