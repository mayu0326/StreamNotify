# -*- coding: utf-8 -*-
"""
v4 YouTube API Client
Unified client for YouTube Data API v3 interactions.
Handles:
- Quota Management (Cost tracking, 429/403 handling)
- Batch Fetching (videos.list)
- Caching (Channel ID, Video Details)
- ID Resolution (Handle -> Channel ID)
"""

import logging
import os
import time
import json
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
import requests

from v4.core.config import settings

logger = logging.getLogger("v4.youtube_api_client")

# Constants
API_BASE = "https://www.googleapis.com/youtube/v3"
VIDEOS_PART = "snippet,liveStreamingDetails,contentDetails,status"

# Cache paths: align with settings.data_dir (v4/data), same root as client_v4.db.
DATA_DIR = settings.data_dir
_LEGACY_DATA_DIR = settings.base_dir / "data"
CHANNEL_ID_CACHE_FILE = DATA_DIR / "youtube_channel_cache.json"
VIDEO_DETAIL_CACHE_FILE = DATA_DIR / "youtube_video_detail_cache.json"
_LEGACY_CHANNEL_CACHE = _LEGACY_DATA_DIR / "youtube_channel_cache.json"
_LEGACY_VIDEO_DETAIL_CACHE = _LEGACY_DATA_DIR / "youtube_video_detail_cache.json"

CACHE_EXPIRY_DAYS = 7
CACHE_EXPIRY_LIVE_MINUTES = 60

class YouTubeApiClient:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return

        self.api_key = settings.youtube_api_key
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        self.session = requests.Session()

        # Quota Management
        self.daily_quota = 10000
        self.daily_cost = 0
        self.last_request_time = 0
        self.request_interval = 0.5 # sec
        self.quota_exceeded = False

        # Caches
        self.video_detail_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_timestamps: Dict[str, float] = {}
        self.channel_id_cache: Dict[str, str] = {}

        self._load_caches()
        self._initialized = True
        logger.info("✅ YouTubeApiClient initialized")

    def _load_caches(self):
        need_persist = False

        try:
            ch_path = CHANNEL_ID_CACHE_FILE if CHANNEL_ID_CACHE_FILE.exists() else _LEGACY_CHANNEL_CACHE
            if ch_path.exists():
                with open(ch_path, "r", encoding="utf-8") as f:
                    self.channel_id_cache = json.load(f)
                if ch_path == _LEGACY_CHANNEL_CACHE:
                    need_persist = True
        except Exception as e:
            logger.warning(f"Failed to load channel cache: {e}")

        try:
            vd_path = VIDEO_DETAIL_CACHE_FILE if VIDEO_DETAIL_CACHE_FILE.exists() else _LEGACY_VIDEO_DETAIL_CACHE
            if vd_path.exists():
                with open(vd_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for vid, entry in data.items():
                        self.video_detail_cache[vid] = entry.get("data", {})
                        self.cache_timestamps[vid] = entry.get("timestamp", 0)
                if vd_path == _LEGACY_VIDEO_DETAIL_CACHE:
                    need_persist = True
        except Exception as e:
            logger.warning(f"Failed to load video cache: {e}")

        if need_persist:
            self._save_caches()

    def _save_caches(self):
        # Check permission/dir existence again just in case
        try:
            # Channel Cache
            with open(CHANNEL_ID_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.channel_id_cache, f, ensure_ascii=False, indent=2)

            # Video Detail Cache
            # TODO: Convert in-memory cache to file format
            export_data = {}
            for vid, details in self.video_detail_cache.items():
                export_data[vid] = {
                    "data": details,
                    "timestamp": self.cache_timestamps.get(vid, time.time())
                }
            with open(VIDEO_DETAIL_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Failed to save caches: {e}")

    # --- Quota & Request ---

    def _throttle(self):
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        self.last_request_time = time.time()

    def _check_quota(self, cost: int) -> bool:
        if self.quota_exceeded: return False
        if self.daily_cost + cost > self.daily_quota:
             logger.warning(f"Quota limits reached prediction ({self.daily_cost}/{self.daily_quota})")
             # We might want to allow hard stop or soft stop. For now soft log.
        return True

    def _get(self, path: str, params: Dict[str, Any], cost: int, operation: str) -> Optional[Dict]:
        if not self.api_key:
            logger.error("No API Key configured")
            return None

        if self.quota_exceeded:
            logger.warning(f"Quota exceeded, skipping {operation}")
            return None

        params["key"] = self.api_key
        url = f"{API_BASE}/{path}"

        retries = 3
        for i in range(retries):
            try:
                self._throttle()
                resp = self.session.get(url, params=params, timeout=15)

                if resp.status_code == 403:
                    # Check if quota error
                    try:
                        err = resp.json().get("error", {}).get("errors", [])
                        reason = err[0].get("reason") if err else ""
                        if reason in ["quotaExceeded", "dailyLimitExceeded"]:
                            self.quota_exceeded = True
                            logger.error("❌ Quota Exceeded! Stopping API calls.")
                            return None
                    except:
                        pass
                    logger.error(f"403 Forbidden in {operation}")
                    return None

                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 10))
                    logger.warning(f"Rate limited (429), waiting {wait}s")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                self.daily_cost += cost
                logger.debug(f"API Success: {operation} (Cost: {cost})")
                return resp.json()

            except Exception as e:
                logger.warning(f"API Attempt {i+1} failed for {operation}: {e}")
                time.sleep(2 ** i)

        return None

    # --- Public Methods ---

    def resolve_channel_identifier(self, identifier: str) -> Optional[str]:
        """Resolve handle/username to Channel ID (UC...)"""
        if identifier.startswith("UC"):
            return identifier

        cache_key = f"id:{identifier}"
        if cache_key in self.channel_id_cache:
            return self.channel_id_cache[cache_key]

        # Call API (channels list forUsername)
        # Note: 'forUsername' is deprecated but 'forHandle' is supported via 'forHandle' param in v3?
        # Actually 'forHandle' parameter exists in channels.list now.
        # Try forHandle first if starts with @, else forUsername?
        # v3 implementation used 'forUsername'.

        param_key = "forUsername"
        if identifier.startswith("@"):
             param_key = "forHandle"

        data = self._get("channels", {"part": "id", param_key: identifier}, 1, f"resolve {identifier}")
        if data and data.get("items"):
            cid = data["items"][0]["id"]
            self.channel_id_cache[cache_key] = cid
            self._save_caches() # Save immediately for ID
            return cid

        return None

    def fetch_video_details_batch(self, video_ids: List[str], force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """
        Batch fetch video details (up to 50 at a time).
        Checks cache first unless force_refresh=True.
        """
        results = {}
        to_fetch = []

        # Check cache
        current_time = time.time()
        for vid in video_ids:
            if not force_refresh and vid in self.video_detail_cache:
                timestamp = self.cache_timestamps.get(vid, 0)
                details = self.video_detail_cache[vid]

                # Expiry Logic
                # Check if live-related
                is_live_related = "liveStreamingDetails" in details
                expiry = CACHE_EXPIRY_LIVE_MINUTES * 60 if is_live_related else CACHE_EXPIRY_DAYS * 86400

                if (current_time - timestamp) < expiry:
                    results[vid] = details
                    continue

            to_fetch.append(vid)

        # Fetch remaining
        # Chunk into 50
        chunk_size = 50
        for i in range(0, len(to_fetch), chunk_size):
            chunk = to_fetch[i:i+chunk_size]
            vid_str = ",".join(chunk)

            data = self._get("videos", {"part": VIDEOS_PART, "id": vid_str, "maxResults": chunk_size}, 1, f"batch details {len(chunk)}")

            if data:
                items = data.get("items", [])
                for item in items:
                    vid = item["id"]
                    results[vid] = item
                    self.video_detail_cache[vid] = item
                    self.cache_timestamps[vid] = time.time()

        if to_fetch:
            self._save_caches()

        return results

    def fetch_video_detail(self, video_id: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        res = self.fetch_video_details_batch([video_id], force_refresh)
        return res.get(video_id)

    def close(self):
        self._save_caches()

# Singleton accessor
def get_youtube_api_client() -> YouTubeApiClient:
    return YouTubeApiClient()
