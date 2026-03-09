# -*- coding: utf-8 -*-

"""
YouTube サムネイル画像管理ユーティリティ

YouTube RSS フェッチ後の画像自動ダウンロード・保存を管理
（RSS フェッチ・パース・DB 保存は youtube_rss.py で管理）

Niconico の niconico_ogp_utils.py に相当する内部モジュール
"""

import logging
import sys
import os

# 親ディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from youtube_rss import YouTubeRSS
from image_manager import get_image_manager
from database import get_database

logger = logging.getLogger("AppLogger")


class YouTubeThumbManager:
    """YouTube RSS サムネイル管理ユーティリティ（内部モジュール）"""

    def __init__(self):
        """
        初期化
        """
        self.db = get_database()
        self.image_manager = get_image_manager()

    def ensure_image_download(self, video_id: str, thumbnail_url: str) -> bool:
        """
        YouTube 動画のサムネイル画像をダウンロード・保存し、DB を更新する。
        （Niconico の _ensure_image_download() に相当）

        Args:
            video_id: YouTube 動画 ID
            thumbnail_url: ダウンロード対象のサムネイル URL

        Returns:
            bool: 成功時 True、失敗時 False
        """
        try:
            youtube_logger = logging.getLogger("YouTubeLogger")

            # image_manager と database のロガーを一時的に YouTubeLogger に変更
            import image_manager as im_module
            import database as db_module
            
            original_im_logger = im_module.logger
            original_db_logger = db_module.logger
            im_module.logger = youtube_logger
            db_module.logger = youtube_logger

            try:
                # 画像をダウンロード・保存
                filename = self.image_manager.download_and_save_thumbnail(
                    thumbnail_url=thumbnail_url,
                    site="YouTube",
                    video_id=video_id,
                    mode="import",
                )

                if filename:
                    # DB の image_info を更新（db_module.logger がまだ YouTubeLogger）
                    self.db.update_image_info(
                        video_id=video_id,
                        image_mode="import",
                        image_filename=filename,
                    )
                    youtube_logger.info(f"[自動画像取得] {video_id} -> {filename}")
                    return True
                else:
                    youtube_logger.warning(f"[自動画像取得失敗] {video_id}: 画像ダウンロード失敗")
                    return False
            finally:
                # ロガーを元に戻す
                im_module.logger = original_im_logger
                db_module.logger = original_db_logger

        except Exception as e:
            youtube_logger = logging.getLogger("YouTubeLogger")
            youtube_logger.warning(f"[自動画像取得エラー] {video_id}: {e}")
            return False

    def fetch_and_ensure_images(self, channel_id: str) -> int:
        """
        YouTube チャンネルの RSS をフェッチして DB に保存し、
        新規動画の画像を自動ダウンロード・保存する。

        Args:
            channel_id: YouTube チャンネル ID

        Returns:
            int: 新規に保存された動画数
        """
        youtube_logger = logging.getLogger("YouTubeLogger")

        try:
            youtube_logger.debug(f"[YouTube RSS] フェッチ中: channel_id={channel_id}")

            # RSS をフェッチ・パース・DB 保存（youtube_rss.py で実行）
            yt_rss = YouTubeRSS(channel_id)
            saved_count = yt_rss.save_to_db(self.db)

            # 新規動画の画像をダウンロード・保存
            if saved_count > 0:
                # DB から全動画を取得して、新規追加分のみ処理
                all_videos = self.db.get_all_videos()
                
                # RSS から取得した動画 ID のセットを作成
                rss_videos = yt_rss.fetch_feed()
                rss_video_ids = {v["video_id"] for v in rss_videos}
                
                # DB の動画の中で、RSS に含まれ、YouTube かつ画像なしの動画を処理
                for video in all_videos:
                    if video["video_id"] not in rss_video_ids:
                        continue  # RSS に含まれていない
                    
                    if (video.get("source") or "").lower() != "youtube":
                        continue  # YouTube ではない
                    
                    thumbnail_url = video.get("thumbnail_url", "")
                    image_filename = video.get("image_filename", "")
                    
                    youtube_logger.debug(
                        f"[自動画像処理] {video['video_id']}: "
                        f"thumbnail_url={'あり' if thumbnail_url else 'なし'}, "
                        f"image_filename={'あり' if image_filename else 'なし'}"
                    )
                    
                    # サムネイル URL があり、画像ファイルがない場合のみダウンロード
                    if thumbnail_url and not image_filename:
                        self.ensure_image_download(video["video_id"], thumbnail_url)

            return saved_count

        except Exception as e:
            youtube_logger.error(
                f"[YouTube RSS] エラー (channel_id={channel_id}): {e}",
                exc_info=True,
            )
            return 0


# シングルトンインスタンス
_youtube_thumb_manager = None


def get_youtube_thumb_manager() -> YouTubeThumbManager:
    """YouTubeThumbManager のシングルトンインスタンスを取得"""
    global _youtube_thumb_manager
    if _youtube_thumb_manager is None:
        _youtube_thumb_manager = YouTubeThumbManager()
    return _youtube_thumb_manager
