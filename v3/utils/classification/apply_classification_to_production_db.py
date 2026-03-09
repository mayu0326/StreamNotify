import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

# v2 パスを追加
sys.path.insert(0, str(Path(__file__).parent.parent / "v2"))

# settings.env から環境変数を読み込み
env_path = Path(__file__).parent.parent / "v2" / "settings.env"
load_dotenv(env_path)

from plugins.youtube_api_plugin import YouTubeAPIPlugin  # noqa: E402


def classify_video(details: Dict[str, Any]) -> Optional[Tuple[str, Optional[str], bool]]:
    """分類ロジックを適用"""
    if not details:
        return None
    return YouTubeAPIPlugin()._classify_video_core(details)


def main():
    """メイン処理"""
    print("\n" + "=" * 80)
    print("🎬 YouTube Live 分類ロジック - 本番 DB 一括適用")
    print("=" * 80 + "\n")

    db_path = Path(__file__).parent.parent / "v2" / "data" / "video_list.db"
    backup_path = (
        Path(__file__).parent.parent
        / "v2"
        / "data"
        / f"video_list.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    )

    if not db_path.exists():
        print(f"❌ DB が見つかりません: {db_path}")
        return 1

    # Step 1: バックアップ作成
    print("📦 Step 1: 本番 DB をバックアップします...\n")
    shutil.copy2(db_path, backup_path)
    print(f"✅ バックアップを作成しました: {backup_path}\n")

    # Step 2: YouTube 動画を取得
    print("📋 Step 2: YouTube 動画情報を取得します...\n")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, video_id, title, source, content_type, live_status, is_premiere
        FROM videos
        WHERE source LIKE '%youtube%' OR source = 'YouTube'
        ORDER BY published_at DESC
    """)

    youtube_videos = [dict(row) for row in cursor.fetchall()]
    print(f"✅ {len(youtube_videos)} 件の YouTube 動画を取得しました\n")

    # Step 3: 分類ロジック適用
    print("🔍 Step 3: 新ロジックで分類します...\n")
    print(f"{'#':<4} {'Video ID':<15} {'現在の分類':<25} {'新分類':<25} {'変更'}")
    print("-" * 90)

    api_plugin = YouTubeAPIPlugin()

    if not api_plugin.is_available():
        print("❌ YouTube API プラグインが利用不可です")
        conn.close()
        return 1

    changes: List[Dict[str, Any]] = []
    errors: List[Tuple[str, str]] = []

    for i, video in enumerate(youtube_videos, 1):
        video_id = str(video.get("video_id", ""))
        db_id = video.get("id")

        current_type = video.get("content_type", "?")
        current_status = video.get("live_status")
        current_premiere = video.get("is_premiere")

        current_str = f"{current_type}"
        if current_status:
            current_str += f" ({current_status})"
        if current_premiere:
            current_str += " [premiere]"

        # API から詳細を取得
        try:
            details = api_plugin._fetch_video_detail(video_id)

            if details:
                classification = classify_video(details)

                if classification:
                    new_type, new_status, new_premiere = classification

                    new_str = f"{new_type}"
                    if new_status:
                        new_str += f" ({new_status})"
                    if new_premiere:
                        new_str += " [premiere]"

                    # 変更があるかチェック
                    changed = (
                        (new_type != current_type)
                        or (new_status != current_status)
                        or (new_premiere != current_premiere)
                    )
                    marker = "⚠️ " if changed else "✓ "

                    print(
                        f"{i:<4} {video_id:<15} {current_str:<25} {new_str:<25} {marker}"
                    )

                    if changed:
                        changes.append(
                            {
                                "id": db_id,
                                "video_id": video_id,
                                "old": (current_type, current_status, current_premiere),
                                "new": (new_type, new_status, new_premiere),
                            }
                        )
                else:
                    print(f"{i:<4} {video_id:<15} {current_str:<25} [分類エラー]")
                    errors.append((video_id, "分類エラー"))
            else:
                print(f"{i:<4} {video_id:<15} {current_str:<25} [API取得失敗]")
                errors.append((video_id, "API取得失敗"))

        except Exception as e:
            print(
                f"{i:<4} {video_id:<15} {current_str:<25} [例外エラー: {str(e)[:20]}...]"
            )
            errors.append((video_id, f"例外: {e}"))

    print("-" * 90)
    print()

    # Step 4: 変更を DB に反映
    print("💾 Step 4: DB に変更を反映します...\n")

    if not changes:
        print("⚠️  変更がない動画はスキップされました")
    else:
        print(f"✅ {len(changes)} 件の動画を更新します\n")

        # トランザクション開始
        try:
            for change in changes:
                new_type, new_status, new_premiere = change["new"]
                cursor.execute(
                    """
                    UPDATE videos
                    SET content_type = ?, live_status = ?, is_premiere = ?
                    WHERE id = ?
                """,
                    (new_type, new_status, new_premiere, change["id"]),
                )

            conn.commit()
            print(f"✅ DB を更新しました（{len(changes)} 件）\n")
        except Exception as e:
            conn.rollback()
            print(f"❌ DB 更新エラー: {e}\n")
            conn.close()
            return 1

    # Step 5: エラー報告
    if errors:
        print(f"⚠️  {len(errors)} 件のエラーがありました:\n")
        for video_id, error in errors:
            print(f"  ❌ {video_id}: {error}")
        print()

    conn.close()

    # Step 6: 統計表示
    print("=" * 80)
    print("📊 処理結果サマリー\n")
    print(f"✅ 処理対象: {len(youtube_videos)} 件")
    print(f"✅ 変更数: {len(changes)} 件")
    print(f"❌ エラー数: {len(errors)} 件")
    print(
        f"✅ 成功率: {((len(youtube_videos) - len(errors)) / len(youtube_videos) * 100):.1f}%"
    )
    print()
    print(f"📁 バックアップ: {backup_path}")
    print(f"📁 本番 DB: {db_path}")
    print()
    print("=" * 80 + "\n")

    if errors:
        print(f"⚠️  {len(errors)} 件のエラーがありますが、DB は更新されました")
        return 1
    else:
        print("🎉 すべての動画を正常に分類・更新しました")
        return 0


if __name__ == "__main__":
    sys.exit(main())
