#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube Live 分類ロジック - API クォータ計算

本番 DB の全動画に対してロジックを適用した場合の API コスト見積もり
"""

import sys
import sqlite3
from pathlib import Path

# v3 パスを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "v3"))


def main():
    """メイン処理"""
    db_path = Path(__file__).parent.parent.parent / "v3" / "data" / "video_list.db"

    print("\n" + "=" * 80)
    print("📊 YouTube Data API クォータ計算")
    print("=" * 80 + "\n")

    if not db_path.exists():
        print(f"❌ DB が見つかりません: {db_path}")
        return 1

    # DB から統計情報を取得
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        # 全動画数
        cursor.execute("SELECT COUNT(*) FROM videos")
        total_videos = cursor.fetchone()[0]

        # プラットフォーム別統計
        cursor.execute(
            "SELECT source, COUNT(*) as count FROM videos GROUP BY source ORDER BY count DESC"
        )
        platform_stats = cursor.fetchall()

        # YouTube 動画のみカウント
        cursor.execute(
            "SELECT COUNT(*) FROM videos WHERE source LIKE '%youtube%' OR source = 'YouTube'"
        )
        youtube_count = cursor.fetchone()[0]

        print("【DB 統計情報】\n")
        print(f"✅ 全動画数: {total_videos} 件")
        print(f"✅ YouTube 動画: {youtube_count} 件")
        print()

        print("【プラットフォーム別】\n")
        for source, count in platform_stats:
            percentage = (count / total_videos * 100) if total_videos > 0 else 0
            print(f"  {source:<15} {count:>5} 件 ({percentage:>5.1f}%)")
        print()

        # API コスト計算
        print("【API コスト計算】\n")

        # videos.list: 1 ユニット/動画
        videos_list_cost = youtube_count
        print("videos.list（動画詳細取得）:")
        print(f"  YouTube 動画数: {youtube_count} 件")
        print("  1 動画 = 1 ユニット")
        print(f"  小計: {videos_list_cost} ユニット")
        print()

        # チャンネルID解決（初回のみ）
        channels_cost = 1
        print("channels.list（チャンネルID解決）:")
        print("  初回アクセス時のみ: 1 ユニット")
        print(f"  小計: {channels_cost} ユニット")
        print()

        # 合計
        total_cost = videos_list_cost + channels_cost
        daily_quota = 10000
        usage_rate = total_cost / daily_quota * 100

        print("【合計 API コスト】\n")
        print(f"  videos.list: {videos_list_cost} ユニット")
        print(f"  channels.list: {channels_cost} ユニット")
        print("  ────────────────────")
        print(f"  合計: {total_cost} ユニット")
        print()

        # クォータ判定
        print("【日次クォータ（10,000ユニット）との比較】\n")
        print(f"  使用量: {total_cost} ユニット")
        print(f"  利用可能: {daily_quota} ユニット")
        print(f"  残余: {daily_quota - total_cost} ユニット")
        print(f"  使用率: {usage_rate:.2f}%")
        print()

        if total_cost <= daily_quota:
            print("✅ クォータ内！【安全】")
            print(f"   {daily_quota - total_cost} ユニットの余裕があります")
        else:
            print("❌ クォータ超過！【要注意】")
            print(f"   {total_cost - daily_quota} ユニット不足しています")
        print()

        # 推奨実行タイミング
        print("【推奨実行タイミング】\n")

        if total_cost <= daily_quota * 0.5:
            print("✅ 【推奨】 毎日実行可能")
            print("   クォータの 50% 以下のため、安全に毎日実行できます")
        elif total_cost <= daily_quota * 0.8:
            print("⚠️  【注意】 1日1回程度")
            print("   クォータの 50%-80% のため、1日1回の実行が安全です")
        else:
            print("❌ 【警告】 複数回実行は不可")
            print(
                "   クォータの 80% 以上のため、複数回実行すると超過の可能性があります"
            )
        print()

        # API 効率分析
        print("【API 効率分析】\n")
        print(
            f"効率: {youtube_count} 動画 / {total_cost} ユニット = {youtube_count / total_cost:.2f} 動画/ユニット"
        )
        print()

        print("=" * 80 + "\n")

        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
