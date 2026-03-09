#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DB 状態確認スクリプト
"""
import sys
sys.path.insert(0, 'v2')

from database import get_database

db = get_database('v3/data/video_list.db')
conn = db._get_connection()
c = conn.cursor()

# テーブル情報
c.execute("SELECT COUNT(*) FROM videos")
total = c.fetchone()[0]
print(f'Total videos in DB: {total}')

# source ごとの集計
c.execute("SELECT source, COUNT(*) as count FROM videos GROUP BY source")
print('\nBy source:')
for row in c.fetchall():
    print(f'  {row[0]}: {row[1]}')

# YouTube のサンプル
print('\nYouTube video samples:')
c.execute("SELECT video_id, title, source, content_type FROM videos WHERE source = 'YouTube' LIMIT 5")
for row in c.fetchall():
    print(f'  {row[0]} | {row[1][:30]} | {row[2]} | {row[3]}')

# source が NULL の確認
print('\nVideos with NULL source:')
c.execute("SELECT COUNT(*) FROM videos WHERE source IS NULL")
null_count = c.fetchone()[0]
print(f'  Count: {null_count}')

if null_count > 0:
    c.execute("SELECT video_id, title, content_type FROM videos WHERE source IS NULL LIMIT 3")
    for row in c.fetchall():
        print(f'    {row[0]} | {row[1][:30]} | {row[2]}')

conn.close()
