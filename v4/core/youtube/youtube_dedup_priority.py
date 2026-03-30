#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YouTube動画の重複排除ロジック

同じタイトル+チャンネル名の動画が複数ある場合、
優先度に基づいて保持すべき動画を特定する。
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

def get_video_priority(video: Dict[str, Any]) -> tuple:
    """
    動画の優先度を計算（タプル）

    返り値が大きいほど優先度が高い
    Returns: (優先度, コンテンツ種別, video_id)
    """
    content_type = video.get('content_type', 'video')
    live_status = video.get('live_status')
    is_premiere = video.get('is_premiere', 0)
    published_at_str = video.get('published_at', '')
    video_id = video.get('video_id', '')

    # プレミア公開判定用
    now = datetime.now()
    premiere_priority = 0

    if is_premiere and published_at_str:
        try:
            # published_at は ISO 8601 形式: "2025-12-18T10:30:00"
            premiere_time = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
            if premiere_time.tzinfo:
                premiere_time = premiere_time.replace(tzinfo=None)

            # 現在時刻との差分を計算
            time_diff = (premiere_time - now).total_seconds()

            if time_diff >= 0:  # 現在時刻以降
                premiere_priority = 3  # ライブと同等
            elif time_diff > -600:  # 10分以内（-600秒）
                premiere_priority = 3  # ライブと同等
            else:  # 10分以上過去
                premiere_priority = 1  # 通常動画と同等
        except Exception:
            premiere_priority = 1  # パース失敗時は通常動画扱い

    # 優先度を計算（大きいほど優先度が高い）
    # v3.3.0: 5カテゴリ対応
    # 優先度: archive(4) > schedule(3) > live(3) > completed(2) > video(1)
    if content_type == 'archive':
        priority = 4  # アーカイブ（LIVE終了後の録画）
    elif content_type == 'schedule':
        priority = 3  # 放送予約（upcoming）
    elif content_type == 'live':
        priority = 3  # 放送中
    elif content_type == 'completed':
        priority = 2  # 放送終了
    elif is_premiere and premiere_priority == 3:
        priority = 3  # プレミア公開（開始予定/近い）
    elif is_premiere and premiere_priority == 1:
        priority = 1  # プレミア公開（10分以上過去）
    else:  # video
        priority = 1  # 通常動画

    # (優先度, コンテンツ種別, video_id) を返す
    return (priority, content_type, video_id)


def should_keep_video(video: Dict[str, Any], existing_videos: List[Dict[str, Any]]) -> bool:
    """
    新しい動画を登録すべきかを判定

    同じタイトル+チャンネル名で既に登録されている動画がある場合、
    優先度を比較して判定する

    Args:
        video: 新しい動画情報
        existing_videos: 既に登録されている同じコンテンツの動画リスト

    Returns:
        True: 登録すべき（優先度が高い）
        False: 登録しない（既存の方が優先度が高い）
    """
    if not existing_videos:
        return True

    new_priority = get_video_priority(video)

    # 既存動画の中で最も優先度が高いものを取得
    max_existing_priority = max(
        get_video_priority(existing)
        for existing in existing_videos
    )

    # 新しい動画の優先度が既存の最大値よりも高い場合のみ登録
    return new_priority > max_existing_priority


def select_best_video(videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    複数の動画から最も優先度が高いものを選択

    Args:
        videos: 同じコンテンツの動画リスト（2個以上）

    Returns:
        最も優先度が高い動画
    """
    if not videos:
        return {}

    return max(videos, key=lambda v: get_video_priority(v))


# テスト用サンプルデータ
if __name__ == "__main__":
    samples = [
        {"video_id": "vid1", "content_type": "video", "live_status": None, "is_premiere": 0, "published_at": "2025-12-18T10:00:00"},
        {"video_id": "vid2", "content_type": "live", "live_status": "live", "is_premiere": 0, "published_at": "2025-12-18T11:00:00"},
        {"video_id": "vid3", "content_type": "archive", "live_status": "completed", "is_premiere": 0, "published_at": "2025-12-18T12:00:00"},
        {"video_id": "vid4", "content_type": "video", "live_status": None, "is_premiere": 1, "published_at": "2025-12-18T22:40:00"},  # 近い未来
    ]

    print("=== 優先度テスト ===")
    for sample in samples:
        priority = get_video_priority(sample)
        print(f"Video ID: {sample['video_id']}, Priority: {priority}")

    print("\n=== 最優先動画 ===")
    best = select_best_video(samples)
    print(f"Best video: {best['video_id']} (priority: {get_video_priority(best)})")
