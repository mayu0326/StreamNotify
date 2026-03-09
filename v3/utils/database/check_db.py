#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3

conn = sqlite3.connect("data/video_list.db")
conn.row_factory = sqlite3.Row

cursor = conn.cursor()
cursor.execute("SELECT video_id, title, channel_name, source FROM videos WHERE source='niconico'")

for row in cursor.fetchall():
    print(f"Video ID: {row['video_id']}")
    print(f"Title: {row['title']}")
    print(f"Channel Name: {row['channel_name']}")
    print(f"Source: {row['source']}")
    print()

conn.close()
