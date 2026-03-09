#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube API レスポンス詳細確認

D5fDvRBf6vk の詳細情報を取得して、プレミア公開と配信予定枠の区別を調査
"""

import sys
from pathlib import Path
from dotenv import load_dotenv
import json

# v2 パスを追加
sys.path.insert(0, str(Path(__file__).parent.parent / "v2"))

# settings.env から環境変数を読み込み
env_path = Path(__file__).parent.parent / "v2" / "settings.env"
load_dotenv(env_path)

from plugins.youtube_api_plugin import YouTubeAPIPlugin


def main():
    """メイン処理"""
    video_id = "D5fDvRBf6vk"

    print("\n" + "=" * 80)
    print(f"🔍 YouTube API レスポンス詳細確認：{video_id}")
    print("=" * 80 + "\n")

    # API プラグインを初期化
    plugin = YouTubeAPIPlugin()

    if not plugin.is_available():
        print("❌ YouTube API プラグインが利用不可です")
        return 1

    # 動画詳細を取得
    details = plugin._fetch_video_detail(video_id)

    if not details:
        print(f"❌ 動画詳細取得失敗: {video_id}")
        return 1

    # 重要なフィールドを表示
    print("📋 API レスポンス詳細:\n")

    snippet = details.get("snippet", {})
    status = details.get("status", {})
    live = details.get("liveStreamingDetails", {})

    print("【snippet】")
    print(f"  title: {snippet.get('title')}")
    print(f"  liveBroadcastContent: {snippet.get('liveBroadcastContent')}")
    print()

    print("【status】")
    print(f"  uploadStatus: {status.get('uploadStatus')}")
    print(f"  privacyStatus: {status.get('privacyStatus')}")
    print()

    print("【liveStreamingDetails】")
    if live:
        print(f"  scheduledStartTime: {live.get('scheduledStartTime')}")
        print(f"  actualStartTime: {live.get('actualStartTime')}")
        print(f"  actualEndTime: {live.get('actualEndTime')}")
        print(f"  concurrentViewers: {live.get('concurrentViewers')}")
    else:
        print("  [空のオブジェクト]")
    print()

    # 分類結果
    print("【分類結果】")
    classification = YouTubeAPIPlugin._classify_video_core(details)
    content_type, live_status, is_premiere = classification

    result_str = f"{content_type}"
    if live_status:
        result_str += f" ({live_status})"
    if is_premiere:
        result_str += " [プレミア]"

    print(f"  分類: {result_str}")
    print(f"  詳細: {classification}")
    print()

    # プレミア判定ロジック詳細
    print("【プレミア判定ロジック】")
    print(f"  uploadStatus == 'processed': {status.get('uploadStatus') == 'processed'}")
    print(
        f"  broadcast_type in ('live', 'upcoming'): {snippet.get('liveBroadcastContent') in ('live', 'upcoming')}"
    )
    print(f"  liveStreamingDetails exists: {bool(live)}")
    print(f"  is_premiere: {is_premiere}")
    print()

    # 全データを JSON で表示
    print("【全データ（JSON）】")
    print(json.dumps(details, indent=2, ensure_ascii=False))

    print("=" * 80 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
