import os
import logging
import requests
import io
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from v4.core.config import settings

logger = logging.getLogger("v4.images")

class ImageManager:
    """Enhanced image management port from v3 to v4.
    サムネイルキャッシュは v4/images/{YouTube|Niconico|Twitch}/autopost に保存される。
    """
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or settings.v4_dir / "images"
        self._ensure_directories()

    def _ensure_directories(self):
        """Create necessary directory structure"""
        # Site specific directories
        for site in ["YouTube", "Niconico", "Twitch"]:
            for mode in ["import", "autopost"]:
                (self.base_dir / site / mode).mkdir(parents=True, exist_ok=True)
        (self.base_dir / "default").mkdir(parents=True, exist_ok=True)

    def get_youtube_thumbnail_url(self, video_id: str) -> str:
        """Construct best quality YouTube thumbnail URL"""
        return f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"

    def download_thumbnail(self, url: str, site: str, video_id: str, mode: str = "autopost") -> Optional[str]:
        """Download and save thumbnail with proper extension"""
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.content

            ext = self._detect_extension(data)
            filename = f"{video_id}.{ext}"
            save_path = self.base_dir / site / mode / filename

            with open(save_path, "wb") as f:
                f.write(data)

            logger.info(f"✅ Thumbnail saved: {save_path}")
            return filename
        except Exception as e:
            logger.error(f"Failed to download image from {url}: {e}")
            return None

    def _detect_extension(self, data: bytes) -> str:
        if data.startswith(b'\x89PNG'): return "png"
        if data.startswith(b'\xFF\xD8\xFF'): return "jpg"
        if data.startswith(b'GIF8'): return "gif"
        if b'WEBP' in data[:20]: return "webp"
        return "jpg"

    def delete_images_for_video(self, site: str, video_id: str):
        """Clean up all images related to a video ID"""
        count = 0
        for mode in ["import", "autopost"]:
            dir_path = self.base_dir / site / mode
            if not dir_path.exists(): continue

            for f in dir_path.glob(f"{video_id}.*"):
                try:
                    f.unlink()
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete {f}: {e}")
        if count > 0:
            logger.info(f"🗑️ Cleaned up {count} images for video {video_id}")

    def list_import_images(self, site: str) -> List[str]:
        dir_path = self.base_dir / site / "import"
        if not dir_path.exists(): return []
        return [f.name for f in dir_path.iterdir() if f.is_file()]

# Singleton
image_manager = ImageManager()
