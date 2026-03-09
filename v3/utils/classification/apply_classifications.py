#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【テスト・初期設定専用スクリプト】

キャッシュからの分類結果を本番 DB に適用
修正された分類ロジック（System 1-7）を使用

⚠️  注意: 本番運用では youtube_api_plugin.py に分類ロジックが含まれているため、
このスクリプトは初期データの投入・テスト目的のみで使用してください。
"""

import json
import sqlite3
from pathlib import Path
from collections import defaultdict
from datetime import datetime


def _classify_video_core(details):
    """修正後の分類ロジック（System 1-7）"""
    snippet = details.get("snippet", {})
    status = details.get("status", {})
    live = details.get("liveStreamingDetails", {})

    # System 1: liveBroadcastContent で補助判定
    broadcast_type = snippet.get("liveBroadcastContent", "none")

    # System 3: プレミア公開判定
    is_premiere = False
    if live:
        if status.get("uploadStatus") == "processed" and broadcast_type in ("live", "upcoming"):
            is_premiere = True

        # System 2: ライブの時間的状態判定（タイムスタンプが最優先）
        if live.get("actualEndTime"):
            # 配信が終了している → アーカイブ
            return "archive", "completed", is_premiere
        elif live.get("actualStartTime"):
            # 配信が開始しているが終了していない → 配信中
            return "live", "live", is_premiere
        elif live.get("scheduledStartTime"):
            # 配信がスケジュール済み → 予定中
            return "live", "upcoming", is_premiere

    # System 4: liveStreamingDetails がない、または上記条件に当てはまらない場合
    # → broadcast_type で補助判定
    if broadcast_type == "live":
        return "live", "live", is_premiere
    elif broadcast_type == "upcoming":
        return "live", "upcoming", is_premiere
    elif broadcast_type == "completed":
        # System 7: completed ケース
        return "archive", "completed", is_premiere

    # System 5: デフォルト → 通常動画
    return "video", None, False


def load_cache():
    """キャッシュから動画情報を読み込む"""
    cache_file = Path("v3/data/youtube_video_detail_cache.json")

    print(f"📂 キャッシュ読み込み中: {cache_file}")
    try:
        with open(cache_file, "r", encoding="utf-8-sig") as f:
            cache_data = json.load(f)
    except UnicodeDecodeError:
        with open(cache_file, "r", encoding="utf-8") as f:
            cache_data = json.load(f)

    # キャッシュの形式: {video_id: {data: {...}}, ...}
    videos = {}
    if isinstance(cache_data, dict):
        for video_id, entry in cache_data.items():
            data = entry.get("data", {})
            if data:
                videos[video_id] = data

    print(f"✅ {len(videos)} 件をロード")
    return videos


def classify_videos(videos):
    """動画を分類"""
    print(f"\n🔍 分類処理中...")

    classifications = {}
    results = defaultdict(list)

    for video_id, data in videos.items():
        try:
            content_type, live_status, is_premiere = _classify_video_core(data)
            classifications[video_id] = {
                "content_type": content_type,
                "live_status": live_status,
                "is_premiere": is_premiere,
                "broadcast_type": data.get("snippet", {}).get("liveBroadcastContent", "none"),
                "classified_at": datetime.now().isoformat()
            }

            results[content_type].append({
                "video_id": video_id,
                "title": data.get("snippet", {}).get("title", ""),
                "live_status": live_status
            })
        except Exception as e:
            print(f"❌ 分類エラー {video_id}: {e}")

    # 結果表示
    print("\n" + "=" * 60)
    print("📊 分類結果")
    print("=" * 60)
    print(f"✅ 通常動画 (video): {len(results['video'])} 件")
    print(f"🔴 配信中・予定中 (live): {len(results['live'])} 件")
    print(f"📹 アーカイブ (archive): {len(results['archive'])} 件")
    print(f"合計: {len(classifications)} 件")
    print()

    # ライブステータスの内訳
    if results["live"]:
        live_details = defaultdict(int)
        for item in results["live"]:
            live_details[item["live_status"]] += 1
        print("ライブステータス内訳:")
        for status, count in sorted(live_details.items()):
            print(f"  - {status}: {count} 件")
        print()

    return classifications, results


def update_database(classifications):
    """本番 DB を更新"""
    db_file = Path("v3/data/video_list.db")

    if not db_file.exists():
        print(f"❌ DB ファイルが見つかりません: {db_file}")
        return False

    print(f"\n📝 DB 更新中: {db_file}")

    try:
        conn = sqlite3.connect(str(db_file), timeout=10)
        cursor = conn.cursor()

        # 既存のカラムを確認
        cursor.execute("PRAGMA table_info(videos)")
        columns = {col[1] for col in cursor.fetchall()}

        # classification_type と broadcast_status カラムが存在するか確認
        if "classification_type" not in columns:
            print("⚠️  classification_type カラムを追加")
            cursor.execute("""
                ALTER TABLE videos
                ADD COLUMN classification_type TEXT DEFAULT 'video'
            """)

        if "broadcast_status" not in columns:
            print("⚠️  broadcast_status カラムを追加")
            cursor.execute("""
                ALTER TABLE videos
                ADD COLUMN broadcast_status TEXT
            """)

        # 分類結果を DB に適用
        updated = 0
        for video_id, classification in classifications.items():
            cursor.execute("""
                UPDATE videos
                SET classification_type = ?,
                    broadcast_status = ?
                WHERE video_id = ?
            """, (
                classification["content_type"],
                classification["live_status"],
                video_id
            ))
            if cursor.rowcount > 0:
                updated += 1

        conn.commit()
        conn.close()

        print(f"✅ DB 更新完了: {updated} 件")
        return True

    except Exception as e:
        print(f"❌ DB 更新エラー: {e}")
        return False


def main():
    print("=" * 60)
    print("🚀 キャッシュから分類結果を本番 DB に適用")
    print("=" * 60)
    print()

    # キャッシュを読み込む
    videos = load_cache()
    if not videos:
        print("❌ キャッシュが空です")
        return

    # 分類処理
    classifications, results = classify_videos(videos)

    # DB に適用
    if update_database(classifications):
        print("\n✅ 全ての処理が完了しました！")
        print(f"\n📊 最終結果:")
        print(f"  - 通常動画: {len(results['video'])} 件")
        print(f"  - 配信: {len(results['live'])} 件")
        print(f"  - アーカイブ: {len(results['archive'])} 件")
    else:
        print("\n❌ DB 更新に失敗しました")


if __name__ == "__main__":
    main()
