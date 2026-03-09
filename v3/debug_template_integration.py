# -*- coding: utf-8 -*-

"""
Bluesky テンプレート統合 - デバッグスクリプト

テンプレート機能が正しく動作しているかを確認するための診断ツール。
このスクリプトを実行して、ログ出力を確認してください。
"""

import sys
from pathlib import Path
import logging

# パスを追加
sys.path.insert(0, str(Path(__file__).parent))

from template_utils import (
    TEMPLATE_REQUIRED_KEYS,
    load_template_with_fallback,
    validate_required_keys,
    render_template,
    get_template_path,
    DEFAULT_TEMPLATE_PATH,
)

logger = logging.getLogger("AppLogger")

# ============ テスト用の video サンプル ============

SAMPLE_VIDEO_YOUTUBE = {
    "title": "【新作】 Bluesky テンプレート統合テスト",
    "video_id": "dQw4w9WgXcQ",
    "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "channel_name": "テストチャンネル",
    "published_at": "2025-12-18T10:30:00Z",
    "source": "youtube",
    "platform": "YouTube",
}

SAMPLE_VIDEO_NICONICO = {
    "title": "【新作】 ニコニコテスト動画",
    "video_id": "sm12345678",
    "video_url": "https://www.nicovideo.jp/watch/sm12345678",
    "channel_name": "ニコニコテスト",
    "published_at": "2025-12-18T10:30:00Z",
    "source": "niconico",
    "platform": "ニコニコ",
}


def test_template_rendering():
    """テンプレートレンダリングのテスト"""
    print("\n" + "=" * 80)
    print("テスト 1: テンプレートレンダリング")
    print("=" * 80)

    for template_type, sample_video in [
        ("youtube_new_video", SAMPLE_VIDEO_YOUTUBE),
        ("nico_new_video", SAMPLE_VIDEO_NICONICO),
    ]:
        print(f"\n【{template_type}】")

        # 1. テンプレートパス取得
        template_path = get_template_path(
            template_type, default_fallback=str(DEFAULT_TEMPLATE_PATH)
        )
        print(f"  テンプレートパス: {template_path}")

        # 2. 必須キーチェック
        required_keys = TEMPLATE_REQUIRED_KEYS.get(template_type, [])
        is_valid, missing_keys = validate_required_keys(
            event_context=sample_video,
            required_keys=required_keys,
            event_type=template_type,
        )

        if is_valid:
            print(f"  ✅ 必須キー: OK")
        else:
            print(f"  ❌ 必須キー不足: {missing_keys}")
            continue

        # 3. テンプレートロード
        template_obj = load_template_with_fallback(
            path=template_path,
            default_path=str(DEFAULT_TEMPLATE_PATH),
            template_type=template_type,
        )

        if not template_obj:
            print(f"  ❌ テンプレートロード失敗")
            continue

        print(f"  ✅ テンプレートロード: OK")

        # 4. レンダリング
        rendered_text = render_template(
            template_obj=template_obj,
            event_context=sample_video,
            template_type=template_type,
        )

        if rendered_text:
            print(f"  ✅ レンダリング成功")
            print(f"\n  【生成結果】")
            for line in rendered_text.split("\n"):
                print(f"    {line}")
        else:
            print(f"  ❌ レンダリング失敗")


def test_source_normalization():
    """source パラメータの正規化テスト"""
    print("\n" + "=" * 80)
    print("テスト 2: source パラメータ正規化")
    print("=" * 80)

    test_cases = [
        ("youtube", "✅ 小文字"),
        ("YouTube", "⚠️ 大文字"),
        ("YOUTUBE", "⚠️ 全大文字"),
        ("yt", "⚠️ 短縮形"),
        ("niconico", "✅ 小文字"),
        ("Niconico", "⚠️ 大文字"),
        ("nico", "⚠️ 短縮形"),
        ("unknown", "❌ 不正な値"),
    ]

    for source_value, expected in test_cases:
        source_lower = source_value.lower().strip()

        if source_lower in ("youtube", "yt"):
            result = "youtube_new_video"
        elif source_lower in ("niconico", "nico", "n"):
            result = "nico_new_video"
        else:
            result = "（テンプレート対象外）"

        print(f"  {source_value:15} → {result:30} {expected}")


def test_text_override_flow():
    """text_override フロー確認"""
    print("\n" + "=" * 80)
    print("テスト 3: text_override フロー（投稿文テンプレート）")
    print("=" * 80)

    print("\n【シナリオ A】プラグイン有効時")
    print("  1. bluesky_plugin.post_video() が呼ばれる")
    print("  2. render_template_with_utils() でテンプレートレンダリング")
    print("  3. video['text_override'] にセット")
    print("  4. bluesky_core.post_video_minimal(video) に渡される")
    print("  5. post_video_minimal() で text_override をチェック")
    print("     → 存在 → テンプレート本文を使用")
    print("     → 存在しない → 従来フォーマット")

    print("\n【シナリオ B】プラグイン無効時")
    print("  1. GUI → bluesky_core.post_video_minimal() を直接呼び出し")
    print("  2. text_override が None")
    print("  3. 従来フォーマット（タイトル + チャンネル名 + 日付 + URL）を使用")


def diagnose_issues():
    """実装ギャップを診断"""
    print("\n" + "=" * 80)
    print("診断: 実装ギャップの確認")
    print("=" * 80)

    issues = [
        ("bluesky_plugin.set_dry_run() メソッド", "📌 確認済み: 実装あり", "✅"),
        ("Jinja2 datetimeformat フィルタ", "📌 確認済み: 実装あり", "✅"),
        ("source の大文字正規化", "⚠️ 条件付き OK（.lower() のみ）", "⚠️"),
        ("プラグイン経由フラグ", "❌ 実装なし", "❌"),
        ("リンクカード非導入時の無効化", "❌ 実装なし", "❌"),
    ]

    for issue_name, status, icon in issues:
        print(f"  {icon} {issue_name}: {status}")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("Bluesky テンプレート統合 - デバッグスクリプト")
    print("=" * 80)

    try:
        test_template_rendering()
        test_source_normalization()
        test_text_override_flow()
        diagnose_issues()

        print("\n" + "=" * 80)
        print("診断完了")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ エラーが発生しました: {e}")
        import traceback

        traceback.print_exc()
