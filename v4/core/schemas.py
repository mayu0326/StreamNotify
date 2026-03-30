from datetime import datetime
from typing import List, Optional, Any
from pydantic import BaseModel, Field, ConfigDict, model_validator

class VideoBase(BaseModel):
    video_id: str
    channel_id: Optional[str] = None
    title: Optional[str] = None
    video_url: Optional[str] = None
    published_at: Optional[datetime] = None
    channel_name: Optional[str] = None
    service: str = "youtube"

    # Status
    video_status: str = "upload"  # schedule, live, archive, premiere, upload
    is_premiere: bool = False

    # Live Details
    scheduled_start_time: Optional[datetime] = None
    actual_start_time: Optional[datetime] = None
    actual_end_time: Optional[datetime] = None

    # Metadata
    duration_seconds: Optional[int] = None
    tags: Optional[List[str]] = None

class Video(VideoBase):
    """
    Center Server (/videos response & Webhook payload) model
    """
    id: Optional[int] = None
    created_at: Optional[datetime] = None

    # Cache management
    cached_at: Optional[datetime] = None
    is_updated_since: Optional[datetime] = None

class VideoListResponse(BaseModel):
    """GET /videos のレスポンス（videos または一部サーバーの items に対応）"""

    model_config = ConfigDict(extra="ignore")

    channel_id: str
    count: int = 0
    videos: List[Video] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_list_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if "videos" not in out and "items" in out:
            out["videos"] = out["items"]
        if out.get("count") is None and "total_count" in out:
            out["count"] = out["total_count"]
        v = out.get("videos")
        if out.get("count") is None and isinstance(v, list):
            out["count"] = len(v)
        if out.get("count") is None:
            out["count"] = 0
        return out


class TwitchBroadcastListResponse(BaseModel):
    """GET /client/twitch/broadcasts のレスポンス（行はセンター Twitch DB に近い dict のまま）。"""

    model_config = ConfigDict(extra="ignore")

    status: str = "ok"
    broadcaster_user_id: str = ""
    count: int = 0
    broadcasts: List[Any] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_broadcast_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        b = out.get("broadcasts")
        if out.get("count") is None and isinstance(b, list):
            out["count"] = len(b)
        if out.get("count") is None:
            out["count"] = 0
        return out


class WebhookPayload(BaseModel):
    """
    Payload received from Center Server via POST /webhook
    """
    type: str = "video_update"  # video_update, channel_update etc.
    data: Any
    timestamp: datetime = Field(default_factory=datetime.utcnow)
