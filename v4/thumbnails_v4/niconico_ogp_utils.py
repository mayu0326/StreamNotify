# -*- coding: utf-8 -*-
"""OGP関連ユーティリティ（ニコニコ）"""

import requests
from bs4 import BeautifulSoup
import logging

# ★ v3.4.0: ロギングプラグイン導入時はThumbnailsLogger、未導入時はAppLoggerにフォールバック
def _get_logger():
    """ロギングプラグイン対応のロガー取得（ThumbnailsLogger優先、未導入時はAppLogger）"""
    thumbnails_logger = logging.getLogger("ThumbnailsLogger")
    # ThumbnailsLogger にハンドラーが存在する = プラグイン導入時
    if thumbnails_logger.handlers:
        return thumbnails_logger
    # プラグイン未導入時は AppLogger にフォールバック
    return logging.getLogger("AppLogger")

logger = _get_logger()


def get_niconico_ogp_url(video_id: str) -> str | None:
    """ニコニコ動画のOGPサムネイルURLを取得（1280x720）"""
    if not video_id:
        return None

    video_url = f"https://www.nicovideo.jp/watch/{video_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        resp = requests.get(video_url, headers=headers, timeout=15)
        resp.raise_for_status()
        resp.encoding = "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            ogp_url = og_image.get("content")
            logger.debug(f"[OGP取得] {video_id} -> {ogp_url}")
            return ogp_url
        logger.warning(f"[OGP取得失敗] OGPメタタグが見つかりません: {video_id}")
    except Exception as e:
        logger.warning(f"[OGP取得失敗] {video_id}: {e}")
    return None
