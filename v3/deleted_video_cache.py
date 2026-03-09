# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - 削除済み動画除外リスト管理

削除済み動画の ID をサービス別に JSON ファイルで管理。
新着動画検出時にこのリストをチェック。

削除除外動画リストは以下のように構成されます:
{
    "youtube": ["video_id1", "video_id2"],
    "niconico": ["sm12345678"],
    "twitch": ["...]
}
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv3"

# グローバル キャッシュインスタンス
_deleted_video_cache = None


class DeletedVideoCache:
    """削除済み動画キャッシュ管理"""

    def __init__(self, cache_file: str = "data/deleted_videos.json"):
        """
        初期化

        Args:
            cache_file: 除外動画リスト JSON ファイルのパス
        """
        self.cache_file = Path(cache_file)
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.data = {}
        self._load()

    def _load(self) -> None:
        """JSON ファイルから読み込み"""
        if not self.cache_file.exists():
            logger.debug(f"除外動画リスト JSON が存在しません。新規作成します: {self.cache_file}")
            self._create_default()
            self._save()
            return

        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            logger.info(f"✅ 除外動画リストを読み込みました: {self.cache_file}")
        except json.JSONDecodeError as e:
            logger.error(f"❌ 除外動画リスト JSON の形式エラー: {e}")
            logger.warning("除外動画リスト JSON をリセットします")
            self._create_default()
            self._save()
        except Exception as e:
            logger.error(f"❌ 除外動画リスト読み込みエラー: {e}")
            self._create_default()

    def _save(self) -> bool:
        """JSON ファイルに保存"""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            logger.debug(f"✅ 除外動画リストを保存しました: {self.cache_file}")
            return True
        except Exception as e:
            logger.error(f"❌ 除外動画リスト保存エラー: {e}")
            return False

    def _create_default(self) -> None:
        """デフォルト構造を作成"""
        self.data = {
            "youtube": [],
            "niconico": [],
            "twitch": [],
        }
        logger.debug("除外動画リストをリセットしました")

    def is_deleted(self, video_id: str, source: str = "youtube") -> bool:
        """
        動画 ID が除外動画リストに含まれているか

        Args:
            video_id: チェック対象の動画 ID
            source: サービス名（"youtube", "niconico" など）

        Returns:
            True: 除外動画リストに含まれている（削除済み）
            False: 除外動画リストに含まれていない
        """
        source_lower = source.lower()
        if source_lower not in self.data:
            return False

        is_blacklisted = video_id in self.data[source_lower]
        if is_blacklisted:
            logger.debug(f"⏭️ 除外動画リスト確認: {video_id} (source: {source})")
        return is_blacklisted

    def add_deleted_video(self, video_id: str, source: str = "youtube") -> bool:
        """
        除外動画リストに ID を追加

        Args:
            video_id: 追加対象の動画 ID
            source: サービス名

        Returns:
            成功の可否
        """
        source_lower = source.lower()

        # サービスキーがなければ作成
        if source_lower not in self.data:
            self.data[source_lower] = []

        # 重複チェック
        if video_id in self.data[source_lower]:
            logger.debug(f"既に除外動画リスト登録済みです: {video_id} (source: {source})")
            return True

        # リストに追加
        self.data[source_lower].append(video_id)
        logger.info(f"✅ 除外動画リストに追加しました: {video_id} (source: {source})")

        # 保存
        return self._save()

    def remove_deleted_video(self, video_id: str, source: str = "youtube") -> bool:
        """
        除外動画リストから ID を削除

        Args:
            video_id: 削除対象の動画 ID
            source: サービス名

        Returns:
            成功の可否
        """
        source_lower = source.lower()

        if source_lower not in self.data:
            logger.debug(f"サービス '{source}' は除外動画リストに存在しません")
            return False

        if video_id not in self.data[source_lower]:
            logger.debug(f"動画 ID '{video_id}' は除外動画リスト登録されていません")
            return False

        # リストから削除
        self.data[source_lower].remove(video_id)
        logger.info(f"🗑️ 除外動画リストから削除しました: {video_id} (source: {source})")

        # 保存
        return self._save()

    def get_deleted_count(self, source: Optional[str] = None) -> int:
        """
        削除済み動画数を取得

        Args:
            source: サービス名（None の場合は全体）

        Returns:
            削除済み動画数
        """
        if source is None:
            # 全サービスの合計
            return sum(len(ids) for ids in self.data.values())

        source_lower = source.lower()
        return len(self.data.get(source_lower, []))

    def clear_all_deleted(self) -> bool:
        """全除外動画リストをクリア"""
        try:
            self._create_default()
            self._save()
            logger.info("✅ 除外動画リストをクリアしました")
            return True
        except Exception as e:
            logger.error(f"❌ 除外動画リストクリアエラー: {e}")
            return False

    def get_deleted_videos(self, source: Optional[str] = None) -> dict:
        """
        除外動画リストの内容を取得

        Args:
            source: サービス名（None の場合は全体）

        Returns:
            除外動画リストデータ
        """
        if source is None:
            return dict(self.data)

        source_lower = source.lower()
        return {source_lower: self.data.get(source_lower, [])}


def get_deleted_video_cache(cache_file: str = "data/deleted_videos.json") -> DeletedVideoCache:
    """グローバル キャッシュインスタンスを取得（シングルトン）"""
    global _deleted_video_cache
    if _deleted_video_cache is None:
        _deleted_video_cache = DeletedVideoCache(cache_file)
    return _deleted_video_cache
