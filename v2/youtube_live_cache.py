# -*- coding: utf-8 -*-

"""
YouTubeLive キャッシュ管理モジュール

ライブ配信の状態をキャッシュとして JSON で管理し、
ポーリング結果と組み合わせて本番 DB を更新するための機構を提供
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv3"

CACHE_DIR = Path("data")
CACHE_FILE = CACHE_DIR / "youtube_live_cache.json"


class YouTubeLiveCache:
    """YouTubeLive キャッシュ管理"""

    def __init__(self):
        """初期化"""
        self._ensure_cache_dir()
        self.cache_data = self._load_cache()

    def _ensure_cache_dir(self):
        """キャッシュディレクトリを作成"""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _load_cache(self) -> Dict[str, Any]:
        """キャッシュファイルを読み込む"""
        try:
            if CACHE_FILE.exists():
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.debug(f"✅ LIVE キャッシュを読み込みました: {len(data)} 件")
                return data
            else:
                logger.debug(
                    "ℹ️ LIVE キャッシュファイルが見つかりません（新規作成します）"
                )
                return {}
        except Exception as e:
            logger.error(f"❌ LIVE キャッシュ読み込みエラー: {e}")
            return {}

    def _save_cache(self) -> bool:
        """キャッシュファイルを保存"""
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cache_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"❌ LIVE キャッシュ保存エラー: {e}")
            return False

    def add_live_video(
        self,
        video_id: str,
        db_data: Dict[str, Any],
        api_data: Dict[str, Any],
    ) -> bool:
        """
        ライブ動画をキャッシュに追加

        DB から取得したデータと API で確認したデータを組み合わせて保存

        Args:
            video_id: 動画 ID
            db_data: DB から取得したデータ（title, channel_name など）
            api_data: API から取得したデータ（liveStreamingDetails など）

        Returns:
            保存成功フラグ
        """
        try:
            # キャッシュエントリを構築
            cache_entry = {
                "video_id": video_id,
                "db_data": db_data,
                "api_data": api_data,
                "cached_at": datetime.now().isoformat(),
                "status": "live",  # 初期状態
                "poll_count": 0,
                "last_polled_at": None,
            }

            self.cache_data[video_id] = cache_entry
            self._save_cache()

            logger.info(f"✅ LIVE キャッシュに追加: {video_id}")
            return True

        except Exception as e:
            logger.error(f"❌ キャッシュ追加エラー ({video_id}): {e}")
            return False

    def update_live_video(
        self,
        video_id: str,
        api_data: Dict[str, Any],
    ) -> bool:
        """
        キャッシュ内の動画データを更新（ポーリング結果を反映）

        Args:
            video_id: 動画 ID
            api_data: 最新の API データ

        Returns:
            更新成功フラグ
        """
        try:
            if video_id not in self.cache_data:
                logger.warning(f"⚠️ キャッシュに見つかりません: {video_id}")
                return False

            cache_entry = self.cache_data[video_id]
            cache_entry["api_data"] = api_data
            cache_entry["poll_count"] = cache_entry.get("poll_count", 0) + 1
            cache_entry["last_polled_at"] = datetime.now().isoformat()

            self._save_cache()

            logger.debug(
                f"✅ キャッシュ更新: {video_id} (ポーリング: {cache_entry['poll_count']} 回)"
            )
            return True

        except Exception as e:
            logger.error(f"❌ キャッシュ更新エラー ({video_id}): {e}")
            return False

    def mark_as_ended(self, video_id: str) -> bool:
        """
        キャッシュ内の動画をライブ終了状態に更新

        Args:
            video_id: 動画 ID

        Returns:
            更新成功フラグ
        """
        try:
            if video_id not in self.cache_data:
                logger.warning(f"⚠️ キャッシュに見つかりません: {video_id}")
                return False

            cache_entry = self.cache_data[video_id]
            cache_entry["status"] = "ended"
            cache_entry["ended_at"] = datetime.now().isoformat()

            self._save_cache()

            logger.info(f"✅ キャッシュを終了状態に更新: {video_id}")
            return True

        except Exception as e:
            logger.error(f"❌ キャッシュ終了状態更新エラー ({video_id}): {e}")
            return False

    def remove_live_video(self, video_id: str) -> bool:
        """
        キャッシュからライブ動画を削除

        Args:
            video_id: 動画 ID

        Returns:
            削除成功フラグ
        """
        try:
            if video_id in self.cache_data:
                del self.cache_data[video_id]
                self._save_cache()
                logger.info(f"✅ キャッシュから削除: {video_id}")
                return True
            return False

        except Exception as e:
            logger.error(f"❌ キャッシュ削除エラー ({video_id}): {e}")
            return False

    def get_live_video(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        キャッシュからライブ動画を取得

        Args:
            video_id: 動画 ID

        Returns:
            キャッシュエントリ、または None（見つからない場合）
        """
        return self.cache_data.get(video_id)

    def get_all_live_videos(self) -> List[Dict[str, Any]]:
        """
        キャッシュ内のすべてのライブ動画を取得

        Returns:
            キャッシュエントリのリスト
        """
        return list(self.cache_data.values())

    def get_live_videos_by_status(self, status: str) -> List[Dict[str, Any]]:
        """
        ステータスでフィルタして取得

        Args:
            status: フィルタ対象のステータス ("live", "ended")

        Returns:
            フィルタ後のリスト
        """
        return [
            entry for entry in self.cache_data.values() if entry.get("status") == status
        ]

    def clear_ended_videos(self) -> int:
        """
        キャッシュから終了済み動画を削除

        Returns:
            削除した件数
        """
        try:
            ended_videos = self.get_live_videos_by_status("ended")
            count = 0

            for entry in ended_videos:
                video_id = entry.get("video_id")
                if isinstance(video_id, str) and self.remove_live_video(video_id):
                    count += 1

            logger.info(f"✅ 終了済み動画をキャッシュから削除: {count} 件")
            return count

        except Exception as e:
            logger.error(f"❌ キャッシュ削除エラー: {e}")
            return 0

    def get_cache_size(self) -> int:
        """キャッシュ内の動画数を取得"""
        return len(self.cache_data)


def get_youtube_live_cache() -> YouTubeLiveCache:
    """YouTubeLive キャッシュインスタンスを取得"""
    return YouTubeLiveCache()
