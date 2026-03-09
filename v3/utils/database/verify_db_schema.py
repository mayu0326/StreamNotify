#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI の列設定が正しく機能するか確認するテスト
"""

import sqlite3
from pathlib import Path

db_file = Path("v3/data/video_list.db")

if not db_file.exists():
    print(f"❌ DB ファイルが見つかりません: {db_file}")
    exit(1)

conn = sqlite3.connect(str(db_file), timeout=10)
cursor = conn.cursor()

# videos テーブルのスキーマを確認
print("=" * 60)
print("📊 videos テーブルのスキーマ")
print("=" * 60)
cursor.execute("PRAGMA table_info(videos)")
columns = cursor.fetchall()
for col_id, col_name, col_type, notnull, default_value, pk in columns:
    print(f"  {col_id:2d}: {col_name:30s} {col_type:10s} {'NOT NULL' if notnull else ''}")

print()
print("=" * 60)
print("📊 classification_type の分布")
print("=" * 60)

# classification_type の分布を確認
cursor.execute("""
    SELECT classification_type, COUNT(*) as count
    FROM videos
    GROUP BY classification_type
    ORDER BY count DESC
""")

results = cursor.fetchall()
for ctype, count in results:
    print(f"  {ctype or '(NULL)':15s}: {count:3d} 件")

print()
print("=" * 60)
print("📊 サンプルデータ（先頭 5 件）")
print("=" * 60)

cursor.execute("""
    SELECT video_id, source, classification_type, broadcast_status, title[:50]
    FROM videos
    LIMIT 5
""")

for row in cursor.fetchall():
    video_id, source, ctype, bstatus, title = row
    print(f"  {video_id} | {source:10s} | {ctype or 'video':7s} | {bstatus or '-':10s} | {title}")

conn.close()
print()
print("✅ 検証完了！")
