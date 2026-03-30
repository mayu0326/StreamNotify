import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine, or_
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import settings


# --- Custom Types ---
class JSONType(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return value


# --- Database Setup ---
# クライアントは1つのSQLite DBですべて管理 (Center ServerのようにChannle分割はしない)
DB_PATH = settings.data_dir / "client_v4.db"
settings.data_dir.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# --- Models ---
class VideoModel(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(String, unique=True, index=True, nullable=False)
    channel_id = Column(String, index=True, nullable=True)
    service = Column(String, default="youtube", index=True)  # youtube, twitch, niconico

    title = Column(String, nullable=True)
    video_url = Column(String, nullable=True)
    published_at = Column(DateTime, nullable=True)
    channel_name = Column(String, nullable=True)

    video_status = Column(String, default="upload")
    is_premiere = Column(Boolean, default=False)

    scheduled_start_time = Column(DateTime, nullable=True)
    actual_start_time = Column(DateTime, nullable=True)
    actual_end_time = Column(DateTime, nullable=True)

    duration_seconds = Column(Integer, nullable=True)
    tags = Column(JSONType, nullable=True)

    # 投稿管理（v3 互換）
    posted_to_bluesky = Column(Boolean, default=False)
    posted_at = Column(DateTime, nullable=True)

    # 行単位の画像情報（v3 互換）
    image_mode = Column(String, nullable=True)     # "autopost" | "import" | None
    image_filename = Column(String, nullable=True)

    is_updated_since = Column(DateTime, nullable=True)
    cached_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class TwitchAccountModel(Base):
    __tablename__ = "twitch_accounts"

    id = Column(Integer, primary_key=True, index=True)
    twitch_user_id = Column(String, unique=True, index=True, nullable=False)
    twitch_username = Column(String, nullable=True)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class BlueskyAccountModel(Base):
    __tablename__ = "bsky_accounts"

    id = Column(Integer, primary_key=True, index=True)
    handle = Column(String, unique=True, index=True, nullable=False)
    did = Column(String, nullable=False)
    pds_url = Column(String, nullable=False)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    dpop_private_key = Column(Text, nullable=True)  # JSON string
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


# --- Init DB ---
def init_db():
    Base.metadata.create_all(bind=engine)
    # 既存 DB への新カラム追加（SQLite は ADD COLUMN のみサポート）
    _migrate_add_columns()


def _migrate_add_columns():
    """SQLite に未追加カラムを ADD COLUMN で追記する（冪等）。"""
    import sqlite3 as _sqlite3
    try:
        con = _sqlite3.connect(str(DB_PATH))
        cur = con.cursor()
        cur.execute("PRAGMA table_info(videos)")
        existing_cols = {row[1] for row in cur.fetchall()}
        additions = [
            ("posted_to_bluesky", "INTEGER DEFAULT 0"),
            ("posted_at", "TEXT"),
            ("image_mode", "TEXT"),
            ("image_filename", "TEXT"),
        ]
        for col_name, col_def in additions:
            if col_name not in existing_cols:
                cur.execute(f"ALTER TABLE videos ADD COLUMN {col_name} {col_def}")
        con.commit()
        con.close()
    except Exception as e:
        import logging as _log
        _log.getLogger("v4.database").warning("migrate_add_columns failed: %s", e)


# --- Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- CRUD Operations ---
def upsert_video(db: SessionLocal, video_data: Dict[str, Any]) -> VideoModel:
    """
    Insert or Update a video record.
    Matches by video_id.
    """
    video_id = video_data.get("video_id")
    if not video_id:
        raise ValueError("video_id is required for upsert")

    existing = db.query(VideoModel).filter(VideoModel.video_id == video_id).first()

    if existing:
        # Update existing
        for key, value in video_data.items():
            if key != "id" and hasattr(existing, key):
                setattr(existing, key, value)
        existing.updated_at = datetime.utcnow()
        db.add(existing)
        return existing
    else:
        # Insert new
        # Filter data to only include valid model fields
        valid_data = {k: v for k, v in video_data.items() if hasattr(VideoModel, k) and k != "id"}
        new_video = VideoModel(**valid_data)
        db.add(new_video)
        return new_video


def get_latest_video_update_time(db: SessionLocal) -> Optional[datetime]:
    """
    Get the maximum is_updated_since timestamp from videos table.
    Used for 'since' parameter in WebSub sync.
    """
    result = db.query(VideoModel.is_updated_since).order_by(VideoModel.is_updated_since.desc()).first()
    if result:
        return result[0]
    return None


def get_latest_video_update_time_for_service(db: SessionLocal, service: str) -> Optional[datetime]:
    """
    service ごとの最大 is_updated_since（差分同期で YouTube / Twitch を混ぜない）。
    youtube: service が NULL または 'youtube'。twitch: service == 'twitch'。
    """
    if service not in ("youtube", "twitch"):
        raise ValueError("service must be 'youtube' or 'twitch'")
    q = db.query(VideoModel.is_updated_since).filter(VideoModel.is_updated_since.isnot(None))
    if service == "youtube":
        q = q.filter(or_(VideoModel.service.is_(None), VideoModel.service == "youtube"))
    else:
        q = q.filter(VideoModel.service == "twitch")
    result = q.order_by(VideoModel.is_updated_since.desc()).first()
    if result:
        return result[0]
    return None


# --- OAuth Account Operations ---
def upsert_twitch_account(db: SessionLocal, account_data: Dict[str, Any]) -> TwitchAccountModel:
    twitch_user_id = account_data.get("twitch_user_id")
    existing = db.query(TwitchAccountModel).filter(TwitchAccountModel.twitch_user_id == twitch_user_id).first()

    if existing:
        for key, value in account_data.items():
            if key != "id" and hasattr(existing, key):
                setattr(existing, key, value)
        db.add(existing)
        return existing
    else:
        valid_data = {k: v for k, v in account_data.items() if hasattr(TwitchAccountModel, k) and k != "id"}
        new_account = TwitchAccountModel(**valid_data)
        db.add(new_account)
        return new_account


def upsert_bsky_account(db: SessionLocal, account_data: Dict[str, Any]) -> BlueskyAccountModel:
    handle = account_data.get("handle")
    existing = db.query(BlueskyAccountModel).filter(BlueskyAccountModel.handle == handle).first()

    if existing:
        for key, value in account_data.items():
            if key != "id" and hasattr(existing, key):
                setattr(existing, key, value)
        db.add(existing)
        return existing
    else:
        valid_data = {k: v for k, v in account_data.items() if hasattr(BlueskyAccountModel, k) and k != "id"}
        new_account = BlueskyAccountModel(**valid_data)
        db.add(new_account)
        return new_account


def get_twitch_account(db: SessionLocal) -> Optional[TwitchAccountModel]:
    # シンプルに最初のアカウントを返す（単一ユーザー想定）
    return db.query(TwitchAccountModel).first()


def delete_twitch_account(db: SessionLocal) -> bool:
    """ローカル DB から Twitch 連携情報を削除する（単一アカウント想定）。"""
    existing = db.query(TwitchAccountModel).first()
    if existing:
        db.delete(existing)
        db.commit()
        return True
    return False


def get_bsky_account(db: SessionLocal) -> Optional[BlueskyAccountModel]:
    return db.query(BlueskyAccountModel).first()


def delete_bsky_account(db: SessionLocal) -> bool:
    """
    Remove the linked Bluesky account from the local database.
    """
    existing = db.query(BlueskyAccountModel).first()
    if existing:
        db.delete(existing)
        db.commit()
        return True
    return False
