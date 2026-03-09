#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本番 DB のアーカイブ分類確認スクリプト
"""

from database import get_database

db = get_database("v3/data/video_list.db")
conn = db._get_connection()
c = conn.cursor()

print("=" * 80)
print("本番 DB の分類結果サマリー")
print("=" * 80)

# コンテンツタイプ別の集計
print("\n📊 コンテンツタイプ別集計:")
c.execute(
    'SELECT content_type, COUNT(*) as count FROM videos WHERE source = "YouTube" GROUP BY content_type'
)
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]} 件")

# ライブステータス別の集計
print("\n📊 ライブステータス別集計:")
c.execute(
    'SELECT live_status, COUNT(*) as count FROM videos WHERE source = "YouTube" GROUP BY live_status'
)
for row in c.fetchall():
    status = row[0] if row[0] else "(通常動画)"
    print(f"  {status}: {row[1]} 件")

# プレミア公開フラグ別の集計
print("\n📊 プレミア公開フラグ別集計:")
c.execute(
    'SELECT is_premiere, COUNT(*) as count FROM videos WHERE source = "YouTube" GROUP BY is_premiere'
)
for row in c.fetchall():
    flag = "プレミア公開" if row[0] else "通常配信"
    print(f"  {flag}: {row[1]} 件")

# archive に分類された動画の詳細
print("\n🎬 Archive に分類された動画:")
c.execute(
    'SELECT video_id, title, live_status, is_premiere FROM videos WHERE content_type = "archive" ORDER BY published_at DESC LIMIT 10'
)
rows = c.fetchall()
if rows:
    for i, row in enumerate(rows, 1):
        premiere = "✓プレミア" if row[3] else "✗"
        print(f"  {i}. {row[0]} | {row[1][:40]} | status={row[2]} | {premiere}")
else:
    print("  (archive に分類された動画なし)")

# live に分類された動画の詳細
print("\n🎬 Live に分類された動画（最新5件）:")
c.execute(
    'SELECT video_id, title, live_status, is_premiere FROM videos WHERE content_type = "live" ORDER BY published_at DESC LIMIT 5'
)
rows = c.fetchall()
if rows:
    for i, row in enumerate(rows, 1):
        premiere = "✓プレミア" if row[3] else "✗"
        print(f"  {i}. {row[0]} | {row[1][:40]} | status={row[2]} | {premiere}")
else:
    print("  (live に分類された動画なし)")

conn.close()
