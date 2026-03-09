# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v2 Bluesky プラグイン

Bluesky へのポスト機能を提供。
HTTP API で直接 Rich Text をポスト。
Rich Text Facet: https://docs.bsky.app/docs/advanced-guides/post-richtext
画像埋め込み: https://docs.bsky.app/docs/advanced-guides/posts
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from plugin_interface import NotificationPlugin

logger = logging.getLogger("AppLogger")
post_logger = logging.getLogger("PostLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

__version__ = "1.0.0"


# --- 最小限投稿API ---
class BlueskyMinimalPoster:
    """Bluesky最小限投稿クラス（API本体）"""

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.access_token = None
        self.did = None
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("🔍 BlueskyMinimalPoster init: username=%s", self.username)
        self._login()

    def _login(self):
        try:
            auth_url = "https://bsky.social/xrpc/com.atproto.server.createSession"
            auth_data = {"identifier": self.username, "password": self.password}
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("🔍 Bluesky login request: %s", auth_url)
            response = requests.post(auth_url, json=auth_data, timeout=30)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "🔍 Bluesky login response status: %s", response.status_code
                )
            response.raise_for_status()
            session_data = response.json()
            self.access_token = session_data.get("accessJwt")
            self.did = session_data.get("did")
            if self.access_token and self.did:
                logger.info(f"✅ Bluesky にログインしました: {self.username}")
            else:
                logger.error("❌ アクセストークンまたは DID が取得できませんでした")
                raise Exception("No access token or DID")
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Bluesky ログイン失敗: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ ログイン処理エラー: {e}")
            raise

    def _build_facets_for_url(self, text: str) -> Optional[list]:
        """
        テキストから URL を検出して Facet を構築

        Bluesky Rich Text Facet: https://docs.bsky.app/docs/advanced-guides/post-richtext

        Args:
            text: ポスト本文

        Returns:
            Facet リスト、URL がない場合は None
        """
        pattern = r"https?://[^\s]+"
        facets = []

        for match in re.finditer(pattern, text):
            url = match.group(0)

            # UTF-8 バイト位置を計算
            byte_start = len(text[: match.start()].encode("utf-8"))
            byte_end = len(text[: match.end()].encode("utf-8"))

            facet = {
                "index": {"byteStart": byte_start, "byteEnd": byte_end},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
            }
            facets.append(facet)
            post_logger.info(f"  🔗 URL 検出: {url}")
            post_logger.info(f"     バイト位置: {byte_start} - {byte_end}")

        return facets if facets else None

    def post_video_minimal(self, video: dict) -> bool:
        """最小限の動画投稿API（テキストのみ）"""
        try:
            # デバッグ: 受け取ったフィールドを確認
            post_logger.debug(f"🔍 post_video_minimal に受け取ったフィールド:")
            post_logger.debug(f"   source: {video.get('source')}")
            post_logger.debug(f"   image_mode: {video.get('image_mode')}")
            post_logger.debug(f"   image_filename: {video.get('image_filename')}")

            title = video.get("title", "【新着動画】")
            video_url = video.get("video_url", "")
            channel_name = video.get("channel_name", "")
            published_at = video.get("published_at", "")
            source = video.get("source", "youtube").lower()

            if not video_url:
                logger.error("❌ video_url が見つかりません")
                return False

            # source に応じたテンプレートを生成
            if source == "youtube":
                post_text = f"{title}\n\n🎬 {channel_name}\n📅 {published_at[:10]}\n\n{video_url}"

            post_logger.info(f"投稿内容:\n{post_text}")
            post_logger.info(f"文字数: {len(post_text)} / 300")
            post_logger.info(f"バイト数: {len(post_text.encode('utf-8'))}")

            # Facet構築（省略可）
            facets = None
            embed = None  # 画像埋め込みはコア機能から削除
            created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            # Facet を構築（URL をリンク化）
            post_logger.info("📍 Facet を構築しています...")
            facets = self._build_facets_for_url(post_text)

            if not self.access_token or not self.did:
                logger.error("❌ アクセストークンまたは DID が初期化されていません")
                return False
            post_url = "https://bsky.social/xrpc/com.atproto.repo.createRecord"
            post_record = {
                "$type": "app.bsky.feed.post",
                "text": post_text,
                "createdAt": created_at,
            }

            # Facet がある場合のみ追加
            if facets:
                post_record["facets"] = facets

            # 画像が含まれる場合のみ追加
            if embed:
                post_record["embed"] = embed

            post_data = {
                "repo": self.did,
                "collection": "app.bsky.feed.post",
                "record": post_record,
            }
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            }

            post_logger.info(
                f"📍 投稿: text={len(post_text)} 文字, facets={len(facets) if facets else 0} 個, 画像={bool(embed)}"
            )
            if facets:
                post_logger.info(f"   facets: {[f['index'] for f in facets]}")

            response = requests.post(
                post_url, json=post_data, headers=headers, timeout=30
            )
            response.raise_for_status()
            response_data = response.json()
            uri = response_data.get("uri", "unknown")

            if facets:
                post_logger.info(f"✅ Bluesky に投稿しました（リンク化）: {uri}")
                logger.info(f"✅ Bluesky に投稿しました（リンク化）: {uri}")
            else:
                post_logger.info(f"✅ Bluesky に投稿しました（リンクなし）: {uri}")
                logger.info(f"✅ Bluesky に投稿しました（リンクなし）: {uri}")

            return True
        except Exception as e:
            logger.error(f"投稿処理中にエラーが発生しました: {e}", exc_info=True)
            return False
