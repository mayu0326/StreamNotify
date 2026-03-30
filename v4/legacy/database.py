# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v3 データベース管理

SQLite データベースの操作を行う。
マルチプロセスアクセス対策：タイムアウト + リトライ
"""

import sqlite3
import logging
import os
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

# バリデーション用の許可リスト（v3.3.0: 5カテゴリ対応）
# - "video": 通常動画
# - "archive": LIVE終了後のアーカイブ
# - "schedule": LIVE予約枠（upcoming）
# - "live": LIVE配信中
# - "completed": LIVE配信終了
VALID_CONTENT_TYPES = {"video", "archive", "schedule", "live", "completed", "none"}
VALID_LIVE_STATUSES = {None, "none", "upcoming", "live", "completed"}


class Database:
    """SQLite データベースを管理するクラス"""

    _instance = None

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
        if hasattr(self, '_initialized') and self._initialized:
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

    def _validate_content_type(self, content_type: str) -> str:
        """content_type を検証し、正規化する

        Args:
            content_type: 検証する content_type の値

        Returns:
            正規化されたcontent_type（デフォルト値は "video"）

        対応値:
            - "video": 通常動画
            - "archive": LIVE終了後のアーカイブ
            - "schedule": LIVE予約枠（upcoming）
            - "live": LIVE配信中
            - "completed": LIVE配信終了
        """
        if content_type not in VALID_CONTENT_TYPES:
            logger.warning(f"⚠️ 不正な content_type: '{content_type}' → デフォルト値 'video' に置き換えます")
            return "video"
        return content_type

    def _validate_live_status(self, live_status, content_type: str) -> object:
        """live_status を検証し、正規化する

        Args:
            live_status: 検証する live_status の値
            content_type: 対応する content_type

        Returns:
            正規化された live_status
        """
        if live_status not in VALID_LIVE_STATUSES:
            logger.warning(f"⚠️ 不正な live_status: '{live_status}' → None に置き換えます")
            return None

        # content_type="video" で live_status が null 以外の場合は警告
        if content_type == "video" and live_status is not None:
            logger.warning(f"⚠️ content_type='video' で live_status='{live_status}' が設定されています。content_type != 'live' の場合は live_status=None を推奨します")

        return live_status

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
                    is_short INTEGER DEFAULT 0,
                    is_members_only INTEGER DEFAULT 0,
                    image_mode TEXT,
                    image_filename TEXT,
                    source TEXT DEFAULT 'youtube',
                    representative_time_utc TEXT,
                    representative_time_jst TEXT,
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

            # AUTOPOST 動画種別フラグ（仕様 v1.0）
            if "is_short" not in columns:
                logger.info("🔄 カラムを追加します: is_short")
                cursor.execute("ALTER TABLE videos ADD COLUMN is_short INTEGER DEFAULT 0")

            if "is_members_only" not in columns:
                logger.info("🔄 カラムを追加します: is_members_only")
                cursor.execute("ALTER TABLE videos ADD COLUMN is_members_only INTEGER DEFAULT 0")

            if "classification_type" not in columns:
                logger.info("🔄 カラムを追加します: classification_type")
                cursor.execute("ALTER TABLE videos ADD COLUMN classification_type TEXT")

            if "broadcast_status" not in columns:
                logger.info("🔄 カラムを追加します: broadcast_status")
                cursor.execute("ALTER TABLE videos ADD COLUMN broadcast_status TEXT")

            # Representative time カラム（v3.3.1+: 動画種別ごとに基準時刻を切り替える）
            if "representative_time_utc" not in columns:
                logger.info("🔄 カラムを追加します: representative_time_utc")
                cursor.execute("ALTER TABLE videos ADD COLUMN representative_time_utc TEXT")

            if "representative_time_jst" not in columns:
                logger.info("🔄 カラムを追加します: representative_time_jst")
                cursor.execute("ALTER TABLE videos ADD COLUMN representative_time_jst TEXT")

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"スキーママイグレーションエラー: {e}")
            raise

    def insert_video(self, video_id, title, video_url, published_at, channel_name="", thumbnail_url="", content_type="video", live_status=None, is_premiere=False, source="youtube", skip_dedup=False, representative_time_utc=None, representative_time_jst=None):
        """
        動画情報を挿入（リトライ付き、YouTube重複排除対応）

        Args:
            video_id: 動画ID
            title: タイトル
            video_url: 動画URL
            published_at: 公開日時
            channel_name: チャンネル名
            thumbnail_url: サムネイルURL
            content_type: コンテンツ種別（"video"/"live"/"archive"/"none"）
            live_status: ライブ配信状態（null/"none"/"upcoming"/"live"/"completed"）
            is_premiere: プレミア配信フラグ
            source: 配信元（"youtube"/"niconico"など）
            skip_dedup: 重複排除をスキップするか（手動追加時 True）
            representative_time_utc: 基準時刻（UTC）
            representative_time_jst: 基準時刻（JST）
        """
        # バリデーション
        content_type = self._validate_content_type(content_type)
        live_status = self._validate_live_status(live_status, content_type)

        # YouTube動画の重複チェック（簡略版）
        # ★ skip_dedup=True なら重複チェックをスキップ（手動追加時の強制挿入）
        if not skip_dedup and source == "youtube":
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                # 同じ video_id が既に存在するかチェック
                cursor.execute("""
                    SELECT id FROM videos WHERE source='youtube' AND video_id=?
                """, (video_id,))

                existing = cursor.fetchone()
                conn.close()

                if existing:
                    # 同一 video_id は既存レコードを更新（重複登録を防止）
                    logger.debug(f"⏭️ YouTube動画の重複登録を検出: video_id={video_id}")
                    return False

            except Exception as e:
                logger.warning(f"重複チェック処理でエラー: {e}")
                # エラー時は続行して挿入を試みる

        for attempt in range(DB_RETRY_MAX):
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO videos (video_id, title, video_url, published_at, channel_name, thumbnail_url, content_type, live_status, is_premiere, source, representative_time_utc, representative_time_jst)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (video_id, title, video_url, published_at, channel_name, thumbnail_url, content_type, live_status, 1 if is_premiere else 0, source, representative_time_utc, representative_time_jst))

                conn.commit()
                conn.close()
                logger.info(f"動画を保存しました: {title}")
                return True

            except sqlite3.IntegrityError as ie:
                conn.close()
                logger.debug(f"重複登録を検出（スキップ）: video_id={video_id}")
                return False

            except sqlite3.OperationalError as e:
                conn.close()
                if "locked" in str(e).lower() and attempt < DB_RETRY_MAX - 1:
                    logger.debug(f"DB ロック中。{attempt + 1}/{DB_RETRY_MAX} リトライします...")
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

    def get_video_by_id(self, video_id: str) -> Optional[dict]:
        """
        video_id で動画を取得

        Args:
            video_id: 動画ID

        Returns:
            dict: 動画情報（見つからない場合は None）
        """
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM videos WHERE video_id = ?
            """, (video_id,))

            row = cursor.fetchone()
            conn.close()

            return dict(row) if row else None

        except Exception as e:
            logger.error(f"動画の取得に失敗しました（video_id={video_id}）: {e}")
            return None

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
                       content_type, live_status, is_premiere, source, image_mode, image_filename,
                       classification_type, broadcast_status
                FROM videos
                ORDER BY published_at DESC
            """)

            videos = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return videos

        except Exception as e:
            logger.error(f"全動画の取得に失敗しました: {e}")
            return []

    def count_unposted_in_lookback(self, lookback_minutes: int) -> int:
        """
        LOOKBACK 時間窓内の未投稿動画数をカウント（AUTOPOST 起動抑止判定用）

        Args:
            lookback_minutes: 何分さかのぼるか

        Returns:
            int: 件数
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # published_at >= now - lookback_minutes AND posted_to_bluesky = 0
            cursor.execute("""
                SELECT COUNT(*) FROM videos
                WHERE posted_to_bluesky = 0
                  AND published_at >= datetime('now', ? || ' minutes')
            """, (f"-{lookback_minutes}",))

            count = cursor.fetchone()[0]
            conn.close()
            return count

        except Exception as e:
            logger.error(f"未投稿動画カウント に失敗しました: {e}")
            return 0

    def get_autopost_candidates(self, config) -> list:
        """
        AUTOPOST の投稿対象となる動画をフィルタリングして取得

        Args:
            config: Config オブジェクト（AUTOPOST 環境変数を含む）

        Returns:
            List[Dict]: 条件を満たす動画リスト
        """
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 基本 WHERE 条件
            where_clauses = [
                "posted_to_bluesky = 0",
                f"published_at >= datetime('now', '-{config.autopost_lookback_minutes} minutes')"
            ]

            # 動画種別フィルタ（仕様 v1.0 セクション 3）
            type_conditions = []

            if config.autopost_include_normal:
                type_conditions.append("(is_short = 0 AND is_members_only = 0 AND is_premiere = 0)")

            if config.autopost_include_shorts:
                type_conditions.append("(is_short = 1)")

            if config.autopost_include_member_only:
                type_conditions.append("(is_members_only = 1)")

            if config.autopost_include_premiere:
                type_conditions.append("(is_premiere = 1)")

            # どの種別も有効でない場合は空リスト
            if not type_conditions:
                return []

            type_filter = " OR ".join(type_conditions)
            where_clauses.append(f"({type_filter})")

            # DELETE された動画を除外
            deleted_ids = []
            from deleted_video_cache import get_deleted_video_cache
            try:
                deleted_cache = get_deleted_video_cache()
                deleted_ids = deleted_cache.get_deleted_video_ids()
                if deleted_ids:
                    placeholders = ",".join("?" * len(deleted_ids))
                    where_clauses.append(f"video_id NOT IN ({placeholders})")
                    logger.debug(f"除外動画リスト: {len(deleted_ids)} 件を除外フィルタに適用")
            except ImportError:
                logger.debug("deleted_video_cache モジュールが見つかりません")
            except AttributeError as ae:
                logger.warning(f"⚠️ get_deleted_video_ids() 呼び出しエラー: {ae}")
            except Exception as e:
                logger.warning(f"⚠️ 除外動画リスト取得エラー: {e}")

            where_clause = " AND ".join(where_clauses)

            cursor.execute(f"""
                SELECT * FROM videos
                WHERE {where_clause}
                ORDER BY published_at DESC
            """, deleted_ids)

            videos = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return videos

        except Exception as e:
            logger.error(f"AUTOPOST 対象取得に失敗: {e}")
            return []

    def get_videos_by_live_status(self, live_status: str):
        """
        指定された live_status の動画を取得

        Args:
            live_status: "upcoming" / "live" / "completed"

        Returns:
            List[Dict]: 該当する動画情報リスト
        """
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM videos WHERE live_status = ?
                ORDER BY published_at DESC
                """,
                (live_status,)
            )
            videos = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return videos
        except Exception as e:
            logger.error(f"live_status={live_status} の動画取得に失敗: {e}")
            return []

    def get_videos_by_content_type(self, content_type: str):
        """
        指定された content_type の動画を取得

        Args:
            content_type: "video" / "archive" / "schedule" / "live" / "completed" / "none"

        Returns:
            List[Dict]: 該当する動画情報リスト
        """
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM videos WHERE content_type = ?
                ORDER BY published_at DESC
                """,
                (content_type,)
            )
            videos = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return videos
        except Exception as e:
            logger.error(f"content_type={content_type} の動画取得に失敗: {e}")
            return []

    def mark_as_posted(self, video_id):
        """動画を投稿済みにマーク（selected_for_post フラグを外す）"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            posted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                UPDATE videos SET posted_to_bluesky = 1, posted_at = ?, selected_for_post = 0 WHERE video_id = ?
            """, (posted_at, video_id))

            conn.commit()
            conn.close()
            post_logger.info(f"投稿済みフラグを更新しました: {video_id} (投稿日時: {posted_at})")
            return True

        except Exception as e:
            logger.error(f"投稿済みフラグの更新に失敗しました: {e}")
            return False

    def is_duplicate_post(self, video_id: str) -> bool:
        """
        重複投稿かどうかをチェック

        同じ動画がすでに投稿されている場合は True を返す

        Args:
            video_id: 動画ID

        Returns:
            bool: 重複投稿の場合 True、初回投稿の場合 False
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) FROM videos
                WHERE video_id = ? AND posted_to_bluesky = 1
            """, (video_id,))

            count = cursor.fetchone()[0]
            conn.close()

            is_duplicate = count > 0
            if is_duplicate:
                logger.warning(f"⚠️ 重複投稿検知: この動画は既に投稿済みです（{video_id}）")

            return is_duplicate

        except Exception as e:
            logger.error(f"重複チェック中にエラーが発生: {e}")
            return False

    def update_selection(self, video_id, selected: bool, scheduled_at: str = None, image_mode: str = None, image_filename: str = None):
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

    def update_image_info(self, video_id: str, image_mode: str, image_filename: str) -> bool:
        """動画の画像情報を更新"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE videos
                SET image_mode = ?, image_filename = ?
                WHERE video_id = ?
            """, (image_mode, image_filename, video_id))

            conn.commit()
            conn.close()
            logger.info(f"✅ 画像情報更新: {video_id} → {image_filename}")
            return True

        except Exception as e:
            logger.error(f"画像情報の更新に失敗: {video_id} - {e}")
            return False

    def update_video_status(self, video_id: str, content_type: str = None, live_status = None) -> bool:
        """動画のコンテンツ種別とライブ配信状態を更新

        Args:
            video_id: 動画ID
            content_type: コンテンツ種別
            live_status: ライブ配信状態

        Returns:
            更新成功フラグ
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 更新対象のカラムを動的に組み立て
            update_parts = []
            params = []

            if content_type is not None:
                content_type = self._validate_content_type(content_type)
                update_parts.append("content_type = ?")
                params.append(content_type)

            if live_status is not None or content_type is not None:
                # content_typeが指定されていない場合は、既存の値を取得
                if content_type is None:
                    cursor.execute("SELECT content_type FROM videos WHERE video_id = ?", (video_id,))
                    row = cursor.fetchone()
                    content_type = row[0] if row else "video"

                live_status = self._validate_live_status(live_status, content_type)
                update_parts.append("live_status = ?")
                params.append(live_status)

            if not update_parts:
                return True

            params.append(video_id)
            sql = f"UPDATE videos SET {', '.join(update_parts)} WHERE video_id = ?"
            cursor.execute(sql, params)

            conn.commit()
            conn.close()
            logger.info(f"✅ 動画ステータス更新: {video_id} (content_type={content_type}, live_status={live_status})")
            return True

        except Exception as e:
            logger.error(f"動画ステータス更新に失敗: {video_id} - {e}")
            return False

    def update_published_at(self, video_id: str, published_at: str) -> bool:
        """
        ★ YouTube API 優先: 既存動画の published_at を API データで上書き

        RSS で登録された動画の published_at を、YouTube API から取得した
        scheduledStartTime（より正確な配信予定時刻）で上書きする。

        ⚠️ **重要**: このメソッドは LIVE 動画の配信予定日時精度を決定する。
                 絶対に失敗してはいけない。

        Args:
            video_id: 動画ID
            published_at: 更新後の published_at（ISO 8601形式）

        Returns:
            更新成功フラグ
        """
        if not video_id or not published_at:
            logger.error(f"❌ update_published_at: 必須パラメータが不足しています（video_id={video_id}, published_at={published_at}）")
            return False

        for attempt in range(DB_RETRY_MAX):
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                # 現在の値を取得
                cursor.execute("SELECT published_at FROM videos WHERE video_id = ?", (video_id,))
                row = cursor.fetchone()
                if not row:
                    logger.debug(f"⚠️ 動画が見つかりません: {video_id}")
                    conn.close()
                    return False

                old_published_at = row[0]

                # published_at を更新
                cursor.execute("""
                    UPDATE videos SET published_at = ? WHERE video_id = ?
                """, (published_at, video_id))

                affected_rows = cursor.rowcount
                conn.commit()
                conn.close()

                if affected_rows == 0:
                    logger.error(f"❌ 動画更新に失敗（ロー数=0）: {video_id}")
                    return False

                if old_published_at != published_at:
                    logger.info(f"✅ [★重要] published_at を API データで更新: {video_id}")
                    logger.info(f"   旧: {old_published_at}")
                    logger.info(f"   新: {published_at}")
                else:
                    logger.debug(f"ℹ️ published_at は変わっていません（既に同じ値）: {video_id}")

                return True

            except sqlite3.OperationalError as e:
                conn.close()
                if "locked" in str(e).lower() and attempt < DB_RETRY_MAX - 1:
                    logger.debug(f"DB ロック中。{attempt + 1}/{DB_RETRY_MAX} リトライします...")
                    time.sleep(0.5)
                    continue
                else:
                    logger.error(f"❌ DB エラー（published_at 更新失敗）: {video_id} - {e}")
                    return False

            except Exception as e:
                logger.error(f"❌ published_at 更新に予期しないエラー: {video_id} - {e}")
                return False

        logger.error(f"❌ published_at 更新に失敗（リトライ上限）: {video_id}")
        return False

    def update_video_metadata(self, video_id: str, **metadata) -> bool:
        """
        ★ API から取得したメタデータを更新

        タイトル、説明、サムネイル URL などの動画メタデータを更新します。

        Args:
            video_id: 動画ID
            **metadata: 更新するカラム名と値（例: title="新タイトル", thumbnail_url="..."）

        Returns:
            更新成功フラグ
        """
        if not video_id or not metadata:
            return False

        # 有効なカラムのみを許可
        valid_columns = {
            "title", "channel_name", "thumbnail_url", "is_premiere",
            "is_short", "is_members_only"
        }
        update_data = {k: v for k, v in metadata.items() if k in valid_columns and v is not None}

        if not update_data:
            return False

        for attempt in range(DB_RETRY_MAX):
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                # 更新 SQL を動的に構築
                set_clause = ", ".join([f"{col} = ?" for col in update_data.keys()])
                values = list(update_data.values()) + [video_id]

                sql = f"UPDATE videos SET {set_clause} WHERE video_id = ?"
                cursor.execute(sql, values)

                affected_rows = cursor.rowcount
                conn.commit()
                conn.close()

                if affected_rows == 0:
                    logger.debug(f"⚠️ 対象の動画が見つかりません: {video_id}")
                    return False

                # 更新内容をログ出力
                for col, val in update_data.items():
                    if isinstance(val, str) and len(val) > 50:
                        logger.info(f"✅ {col} を更新: {video_id} → {val[:50]}...")
                    else:
                        logger.info(f"✅ {col} を更新: {video_id} → {val}")

                return True

            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < DB_RETRY_MAX - 1:
                    logger.debug(f"DB ロック中。{attempt + 1}/{DB_RETRY_MAX} リトライします...")
                    time.sleep(0.5)
                    continue
                else:
                    logger.error(f"❌ DB エラー（メタデータ更新失敗）: {video_id} - {e}")
                    return False

            except Exception as e:
                logger.error(f"❌ メタデータ更新に予期しないエラー: {video_id} - {e}")
                return False

        logger.error(f"❌ メタデータ更新に失敗（リトライ上限）: {video_id}")
        return False

    def delete_video(self, video_id: str) -> dict:
        """動画をDBから削除（除外動画リスト連携付き・画像情報付き返却）

        返却される辞書で、呼び出し元（GUI）が画像ファイルの削除を判断できるようにする。

        Returns:
            {
                "success": bool,           # 削除成功フラグ
                "image_filename": str,     # 削除対象の画像ファイル名
                "source": str,             # 配信元（youtube / niconico など）
            }
        """
        result = {
            "success": False,
            "image_filename": None,
            "source": "youtube"
        }

        for attempt in range(DB_RETRY_MAX):
            try:
                conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # 削除前に video_id, source, image_filename, image_mode を取得
                cursor.execute(
                    "SELECT source, image_filename, image_mode FROM videos WHERE video_id = ?",
                    (video_id,)
                )
                row = cursor.fetchone()

                if row:
                    result["source"] = row["source"] or "youtube"
                    result["image_filename"] = row["image_filename"]  # None でも OK（呼び出し元で判定）

                # DB から削除
                cursor.execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
                conn.commit()
                conn.close()

                result["success"] = True

                # ★ 新: 除外動画リストに追加
                try:
                    from deleted_video_cache import get_deleted_video_cache
                    cache = get_deleted_video_cache()
                    cache.add_deleted_video(video_id, source=result["source"])
                except ImportError:
                    logger.warning("deleted_video_cache モジュールが見つかりません")
                except Exception as e:
                    logger.error(f"除外動画リスト登録エラー: {video_id} - {e}")

                logger.info(f"✅ 動画を削除しました: {video_id}")
                return result

            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < DB_RETRY_MAX - 1:
                    logger.debug(f"DB ロック中。{attempt + 1}/{DB_RETRY_MAX} リトライします...")
                    time.sleep(0.5)
                    continue
                else:
                    logger.error(f"動画削除に失敗: {video_id} - {e}")
                    return result

            except Exception as e:
                logger.error(f"動画削除エラー: {video_id} - {e}")
                return result

        logger.error(f"動画削除に失敗（リトライ上限）: {video_id}")
        return result

    def delete_videos_batch(self, video_ids: list) -> dict:
        """複数の動画をDBから削除

        Args:
            video_ids: 削除対象の動画ID リスト

        Returns:
            {
                "deleted_count": int,                    # 削除成功件数
                "deleted_videos": [                      # 削除されたビデオの情報
                    {
                        "video_id": str,
                        "image_filename": str or None,
                        "source": str
                    },
                    ...
                ]
            }
        """
        deleted_videos = []

        for video_id in video_ids:
            result = self.delete_video(video_id)
            if result["success"]:
                deleted_videos.append({
                    "video_id": video_id,
                    "image_filename": result["image_filename"],
                    "source": result["source"]
                })

        return {
            "deleted_count": len(deleted_videos),
            "deleted_videos": deleted_videos
        }

    def get_video(self, video_id: str) -> Optional[dict]:
        """
        指定動画IDの情報を取得（schedule_manager.py 用）

        Args:
            video_id: 動画ID

        Returns:
            動画情報（dict）またはNone
        """
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,))
            result = cursor.fetchone()
            conn.close()

            return dict(result) if result else None

        except Exception as e:
            logger.error(f"❌ 動画情報取得失敗: {e}")
            return None

    def update_selection_batch(
        self, video_ids: list, selected: bool, scheduled_at: str = None
    ) -> dict:
        """
        複数の動画の投稿選択状態を一括更新

        Args:
            video_ids: 動画IDのリスト
            selected: 選択状態
            scheduled_at: 予約日時（オプション）

        Returns:
            {
                "success_count": int,
                "failed_count": int,
                "failed_videos": [video_id, ...]
            }
        """
        success_count = 0
        failed_videos = []

        for video_id in video_ids:
            try:
                if not self.update_selection(video_id, selected, scheduled_at):
                    failed_videos.append(video_id)
                else:
                    success_count += 1
            except Exception as e:
                logger.error(f"❌ 一括更新失敗 {video_id}: {e}")
                failed_videos.append(video_id)

        return {
            "success_count": success_count,
            "failed_count": len(failed_videos),
            "failed_videos": failed_videos,
        }


def get_database(db_path=DB_PATH) -> Database:
    """データベースオブジェクトを取得"""
    return Database(db_path)
