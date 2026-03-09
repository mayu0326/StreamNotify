# -*- coding: utf-8 -*-
"""OGP関連ユーティリティ（ニコニコ）"""

import logging

import requests
from bs4 import BeautifulSoup


# ★ v3.2.0: ロギングプラグイン導入時はThumbnailsLogger、未導入時はAppLoggerにフォールバック
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
        if og_image:
            content = og_image.get("content")
            if isinstance(content, list):
                content = content[0]
            if isinstance(content, str):
                logger.info(f"[SUCCESS] OGP取得完了: {video_id} -> {content}")
                return content
        logger.warning(f"[WARN] OGPメタタグが見つかりません: {video_id}")
    except Exception as e:
        logger.error(f"[ERROR] OGP取得エラー: {video_id} - {e}")
    return None
