#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
デバッグ用スクリプト: DB から投稿実績を削除

指定した video_id の以下をリセット：
- posted_to_bluesky フラグ（0 にリセット）
- posted_at（NULL にクリア）

使用方法:
  # 単一の動画をリセット
  python reset_post_flag.py <video_id>

  # 複数の動画をリセット
  python reset_post_flag.py <video_id1> <video_id2> ...

  # 全ての動画をリセット
  python reset_post_flag.py --all

例:
  python reset_post_flag.py sm45414087
  python reset_post_flag.py "abc123xyz" "def456uvw"
  python reset_post_flag.py --all

注意:
  - アプリケーション起動中に実行しないこと（DB ロック）
  - バックアップを取ってから実行することを推奨
"""

import sys
from pathlib import Path

# v3 ディレクトリをパスに追加
v3_path = Path(__file__).parent.parent.parent / "v3"
sys.path.insert(0, str(v3_path))

import sqlite3
from datetime import datetime

# DB パス
DB_PATH = v3_path / "data" / "video_list.db"

def reset_post_flag(video_id: str) -> bool:
    """
    指定した video_id の投稿実績をリセット

    Args:
        video_id: リセット対象の video_id

    Returns:
        成功時 True、失敗時 False
    """
    if not DB_PATH.exists():
        print(f"❌ DB ファイルが見つかりません: {DB_PATH}")
        return False

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()

        # 既存データを確認
        cursor.execute(
            "SELECT video_id, title, posted_to_bluesky, posted_at FROM videos WHERE video_id = ?",
            (video_id,)
        )
        row = cursor.fetchone()

        if not row:
            print(f"❌ video_id '{video_id}' は DB に見つかりません")
            conn.close()
            return False

        existing_video_id, title, posted_flag, posted_at = row

        print(f"\n📋 現在の状態:")
        print(f"   video_id: {existing_video_id}")
        print(f"   title: {title}")
        print(f"   posted_to_bluesky: {posted_flag} (0=未投稿, 1=投稿済み)")
        print(f"   posted_at: {posted_at}")

        # 確認
        response = input(f"\n⚠️  このレコードをリセットしますか？ [y/N]: ").strip().lower()
        if response != 'y':
            print("❌ キャンセルしました")
            conn.close()
            return False

        # リセット実行
        cursor.execute(
            "UPDATE videos SET posted_to_bluesky = 0, posted_at = NULL WHERE video_id = ?",
            (video_id,)
        )
        conn.commit()

        print(f"\n✅ リセット完了: {video_id}")
        print(f"   posted_to_bluesky: 1 → 0")
        print(f"   posted_at: {posted_at} → NULL")

        conn.close()
        return True

    except sqlite3.OperationalError as e:
        print(f"❌ DB アクセスエラー（DB がロックされている可能性）: {e}")
        return False
    except Exception as e:
        print(f"❌ エラー: {e}")
        return False

def reset_multiple(video_ids: list) -> bool:
    """
    複数の video_id をリセット

    Args:
        video_ids: リセット対象の video_id リスト

    Returns:
        全て成功時 True
    """
    success_count = 0
    failed_count = 0

    for video_id in video_ids:
        if reset_post_flag(video_id):
            success_count += 1
        else:
            failed_count += 1
        print()

    print(f"\n📊 結果: 成功 {success_count} 件、失敗 {failed_count} 件")
    return failed_count == 0

def reset_all_videos() -> bool:
    """
    全ての動画の投稿実績をリセット

    Returns:
        成功時 True、失敗時 False
    """
    if not DB_PATH.exists():
        print(f"❌ DB ファイルが見つかりません: {DB_PATH}")
        return False

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()

        # 全動画の投稿状態を確認
        cursor.execute("""
            SELECT COUNT(*), SUM(CASE WHEN posted_to_bluesky = 1 THEN 1 ELSE 0 END)
            FROM videos
        """)
        total_count, posted_count = cursor.fetchone()
        posted_count = posted_count or 0

        if total_count == 0:
            print("❌ DB に動画データがありません")
            conn.close()
            return False

        print(f"\n📊 全動画の投稿状態:")
        print(f"   全体: {total_count} 件")
        print(f"   投稿済み: {posted_count} 件")
        print(f"   未投稿: {total_count - posted_count} 件")

        # リセット対象の動画を表示
        cursor.execute("""
            SELECT video_id, title, posted_at
            FROM videos
            WHERE posted_to_bluesky = 1
            ORDER BY posted_at DESC
            LIMIT 10
        """)
        posted_videos = cursor.fetchall()

        if posted_videos:
            print(f"\n📝 投稿済み動画（最新 10 件）:")
            for i, (vid, title, posted_at) in enumerate(posted_videos, 1):
                print(f"   {i}. [{vid}] {title[:30]}... (投稿日: {posted_at})")
            if posted_count > 10:
                print(f"   ... ほか {posted_count - 10} 件")

        # 確認
        print(f"\n⚠️  投稿済み {posted_count} 件をすべてリセットしますか？")
        response = input("   本当にリセットしますか？ [y/N]: ").strip().lower()
        if response != 'y':
            print("❌ キャンセルしました")
            conn.close()
            return False

        # 最終確認
        response = input("   💥 本当にリセットしますか？（戻すことはできません） [yes/no]: ").strip().lower()
        if response != 'yes':
            print("❌ キャンセルしました")
            conn.close()
            return False

        # リセット実行
        cursor.execute(
            "UPDATE videos SET posted_to_bluesky = 0, posted_at = NULL WHERE posted_to_bluesky = 1"
        )
        conn.commit()
        affected = cursor.rowcount

        print(f"\n✅ 一括リセット完了")
        print(f"   {affected} 件のレコードをリセットしました")
        print(f"   posted_to_bluesky: 1 → 0")
        print(f"   posted_at: (各値) → NULL")

        conn.close()
        return True

    except sqlite3.OperationalError as e:
        print(f"❌ DB アクセスエラー（DB がロックされている可能性）: {e}")
        return False
    except Exception as e:
        print(f"❌ エラー: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n使用例:")
        print("  python reset_post_flag.py sm45414087")
        print("  python reset_post_flag.py abc123xyz def456uvw  # 複数指定可")
        print("  python reset_post_flag.py --all  # 全て一括リセット")
        sys.exit(1)

    # --all フラグをチェック
    if sys.argv[1] == "--all":
        success = reset_all_videos()
        sys.exit(0 if success else 1)

    video_ids = sys.argv[1:]

    if len(video_ids) == 1:
        success = reset_post_flag(video_ids[0])
        sys.exit(0 if success else 1)
    else:
        success = reset_multiple(video_ids)
        sys.exit(0 if success else 1)
