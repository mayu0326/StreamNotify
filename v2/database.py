# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v2 データベース管理

SQLite データベースの操作を行う。
マルチプロセスアクセス対策：タイムアウト + リトライ
"""

import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("AppLogger")
post_logger = logging.getLogger("PostLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

DB_PATH = "data/video_list.db"
DB_TIMEOUT = 10
DB_RETRY_MAX = 3


class Database:
    """SQLite データベースを管理するクラス"""

    _instance = None
    _initialized: bool = False

    def __new__(cls, db_path=DB_PATH):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path=DB_PATH):
        """
        初期化

        Args:
            db_path: データベースファイルのパス
        """
        if hasattr(self, "_initialized") and self._initialized:
            return
        self.db_path = db_path
        self.is_first_run = not Path(db_path).exists()
        self._ensure_directory()
        self._init_db()
        self._migrate_schema()
        self._initialized = True

    def _ensure_directory(self):
        """ディレクトリを作成"""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)

    def _get_connection(self):
        """タイムアウト付きで DB 接続を取得"""
        conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        """データベースとテーブルを初期化"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    video_url TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    channel_name TEXT,
                    posted_to_bluesky INTEGER DEFAULT 0,
                    selected_for_post INTEGER DEFAULT 0,
                    scheduled_at TEXT,
                    posted_at TEXT,
                    thumbnail_url TEXT,
                    content_type TEXT DEFAULT 'video',
                    live_status TEXT,
                    is_premiere INTEGER DEFAULT 0,
                    image_mode TEXT,
                    image_filename TEXT,
                    source TEXT DEFAULT 'youtube',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"DB 初期化エラー: {e}")
            raise

    def _migrate_schema(self):
        """既存 DB のスキーマをマイグレーション"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("PRAGMA table_info(videos)")
            columns = {row[1] for row in cursor.fetchall()}

            required_columns = {
                "selected_for_post": "INTEGER DEFAULT 0",
                "scheduled_at": "TEXT",
                "posted_at": "TEXT",
                "thumbnail_url": "TEXT",
                "content_type": "TEXT DEFAULT 'video'",
                "live_status": "TEXT",
                "is_premiere": "INTEGER DEFAULT 0",
                "image_mode": "TEXT",
                "image_filename": "TEXT",
                "source": "TEXT DEFAULT 'youtube'",
            }

            migration_needed = False

            for col_name, col_def in required_columns.items():
                if col_name not in columns:
                    logger.info(f"🔄 カラムを追加します: {col_name}")
                    try:
                        cursor.execute(
                            f"ALTER TABLE videos ADD COLUMN {col_name} {col_def}"
                        )
                        migration_needed = True
                    except sqlite3.OperationalError as e:
                        logger.warning(
                            f"カラム追加スキップ（既に存在？）: {col_name} - {e}"
                        )

            # 既存データのsourceカラムが空欄のものを自動補完

            try:
                updated_count = 0
                # YouTube: video_idが11桁英数字
                cursor.execute(
                    "UPDATE videos SET source='youtube' "
                    "WHERE (source IS NULL OR source='') AND LENGTH(video_id)=11 AND video_id GLOB '[A-Za-z0-9]*'"
                )
                updated_count += cursor.rowcount

                conn.commit()
                if updated_count > 0:
                    logger.info(
                        f"✅ 既存データのsourceカラムを自動補完しました ({updated_count}件)"
                    )
            except Exception as e:
                logger.warning(f"既存データのsourceカラム補完処理に失敗しました: {e}")

            if migration_needed:
                conn.commit()
                logger.info("✅ DB スキーマのマイグレーションが完了しました")

            conn.close()

        except Exception as e:
            logger.error(f"スキーママイグレーションエラー: {e}")
            raise

    def insert_video(
        self,
        video_id,
        title,
        video_url,
        published_at,
        channel_name="",
        thumbnail_url="",
        content_type="video",
        live_status: Optional[str] = None,
        is_premiere=False,
        source="youtube",
    ):
        """
        動画情報を挿入（リトライ付き）
        """
        for attempt in range(DB_RETRY_MAX):
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT INTO videos (video_id, title, video_url, published_at, channel_name, thumbnail_url, 
                                        content_type, live_status, is_premiere, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        video_id,
                        title,
                        video_url,
                        published_at,
                        channel_name,
                        thumbnail_url,
                        content_type,
                        live_status,
                        1 if is_premiere else 0,
                        source,
                    ),
                )

                conn.commit()
                conn.close()
                logger.info(f"動画を保存しました: {title}")
                return True

            except sqlite3.IntegrityError:
                conn.close()
                logger.debug(f"動画は既に保存されています: {video_id}")
                return False

            except sqlite3.OperationalError as e:
                conn.close()
                if "locked" in str(e).lower() and attempt < DB_RETRY_MAX - 1:
                    logger.debug(
                        f"DB ロック中。{attempt + 1}/{DB_RETRY_MAX} リトライします..."
                    )
                    time.sleep(0.5)
                    continue
                else:
                    logger.error(f"DB エラー: {e}")
                    return False

            except Exception as e:
                logger.error(f"動画の保存に失敗しました: {e}")
                return False

        return False

    def get_unposted_videos(self):
        """未投稿の動画を取得"""
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM videos WHERE posted_to_bluesky = 0
                ORDER BY published_at DESC
            """)

            videos = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return videos

        except Exception as e:
            logger.error(f"未投稿動画の取得に失敗しました: {e}")
            return []

    def get_selected_videos(self):
        """投稿選択された未投稿動画を取得（スケジュール順）"""
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM videos 
                WHERE selected_for_post = 1 AND posted_to_bluesky = 0
                  AND (scheduled_at IS NULL OR scheduled_at <= datetime('now'))
                ORDER BY scheduled_at, published_at
                LIMIT 1
            """)

            result = cursor.fetchone()
            conn.close()
            return dict(result) if result else None

        except Exception as e:
            logger.error(f"選択動画の取得に失敗しました: {e}")
            return None

    def get_all_videos(self):
        """全動画を取得（GUI 用）- すべてのカラムを返す"""
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, video_id, published_at, title, posted_to_bluesky, 
                       selected_for_post, scheduled_at, posted_at, video_url, channel_name, thumbnail_url,
                       content_type, live_status, is_premiere, source, image_mode, image_filename
                FROM videos
                ORDER BY published_at DESC
            """)

            videos = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return videos

        except Exception as e:
            logger.error(f"全動画の取得に失敗しました: {e}")
            return []

    def mark_as_posted(self, video_id):
        """動画を投稿済みにマーク"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            posted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                """
                UPDATE videos SET posted_to_bluesky = 1, posted_at = ? WHERE video_id = ?
            """,
                (posted_at, video_id),
            )

            conn.commit()
            conn.close()
            post_logger.info(
                f"投稿済みフラグを更新しました: {video_id} (投稿日時: {posted_at})"
            )
            return True

        except Exception as e:
            logger.error(f"投稿済みフラグの更新に失敗しました: {e}")
            return False

    def update_selection(
        self,
        video_id,
        selected: bool,
        scheduled_at: Optional[str] = None,
        image_mode: Optional[str] = None,
        image_filename: Optional[str] = None,
    ):
        """動画の投稿選択状態・予約日時・画像指定を更新"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 動的にSQLを組み立て（後方互換: 画像指定がなければ従来通り）
            sql = "UPDATE videos SET selected_for_post = ?, scheduled_at = ?"
            params = [1 if selected else 0, scheduled_at]
            if image_mode is not None:
                sql += ", image_mode = ?"
                params.append(image_mode)
            if image_filename is not None:
                sql += ", image_filename = ?"
                params.append(image_filename)
            sql += " WHERE video_id = ?"
            params.append(video_id)

            cursor.execute(sql, params)
            conn.commit()
            conn.close()
            # ログはGUI層で出力するため、ここでは出力しない
            return True

        except Exception as e:
            logger.error(f"動画の選択状態の更新に失敗: {e}")
            return False

    def update_thumbnail_url(self, video_id: str, thumbnail_url: str) -> bool:
        """サムネイルURLを更新"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE videos
                SET thumbnail_url = ?
                WHERE video_id = ?
                """,
                (thumbnail_url, video_id),
            )

            conn.commit()
            conn.close()
            logger.info(f"✅ サムネイルURL更新: {video_id} -> {thumbnail_url}")
            return True
        except Exception as e:
            logger.error(f"サムネイルURL更新に失敗: {video_id} - {e}")
            return False

    def get_videos_without_image(self):
        """画像が設定されていない動画を取得（サムネイルURLがある動画のみ）"""
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, video_id, title, source, thumbnail_url, image_mode, image_filename
                FROM videos
                WHERE thumbnail_url IS NOT NULL 
                  AND thumbnail_url != ''
                  AND (image_filename IS NULL OR image_filename = '')
                ORDER BY published_at DESC
            """)

            videos = [dict(row) for row in cursor.fetchall()]
            conn.close()
            logger.info(f"📊 画像なし動画: {len(videos)}件")
            return videos

        except Exception as e:
            logger.error(f"画像なし動画の取得に失敗: {e}")
            return []

    def update_image_info(
        self, video_id: str, image_mode: str, image_filename: str
    ) -> bool:
        """動画の画像情報を更新"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE videos 
                SET image_mode = ?, image_filename = ?
                WHERE video_id = ?
            """,
                (image_mode, image_filename, video_id),
            )

            conn.commit()
            conn.close()
            logger.info(f"✅ 画像情報更新: {video_id} → {image_filename}")
            return True

        except Exception as e:
            logger.error(f"画像情報の更新に失敗: {video_id} - {e}")
            return False

    def delete_video(self, video_id: str) -> bool:
        """動画をDBから削除"""
        for attempt in range(DB_RETRY_MAX):
            try:
                conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
                conn.commit()
                conn.close()

                return True

            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < DB_RETRY_MAX - 1:
                    logger.debug(
                        f"DB ロック中。{attempt + 1}/{DB_RETRY_MAX} リトライします..."
                    )
                    time.sleep(0.5)
                    continue
                else:
                    logger.error(f"動画削除に失敗: {video_id} - {e}")
                    return False

            except Exception as e:
                logger.error(f"動画削除エラー: {video_id} - {e}")
                return False

        return False

    def delete_videos_batch(self, video_ids: list) -> int:
        """複数の動画をDBから削除

        Args:
            video_ids: 削除対象の動画ID リスト

        Returns:
            削除した数
        """
        deleted_count = 0
        for video_id in video_ids:
            if self.delete_video(video_id):
                deleted_count += 1

        return deleted_count


def get_database(db_path=DB_PATH) -> Database:
    """データベースオブジェクトを取得"""
    return Database(db_path)
