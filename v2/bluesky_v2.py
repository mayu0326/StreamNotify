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
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Dict, List

import requests
from plugin_interface import NotificationPlugin
from image_manager import get_image_manager

logger = logging.getLogger("AppLogger")
post_logger = logging.getLogger("PostLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

__version__ = "2.1.0"


# --- 最小限投稿API ---
class BlueskyMinimalPoster:
    """Bluesky最小限投稿クラス（API本体）"""

    def __init__(self, username: str, password: str, config=None):
        self.username = username
        self.password = password
        self.config = config
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

    def _upload_blob(
        self, img_data: bytes, content_type: str = "image/jpeg"
    ) -> Optional[dict]:
        """
        画像データをアップロードして Blob を取得
        """
        try:
            upload_url = "https://bsky.social/xrpc/com.atproto.repo.uploadBlob"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": content_type,
            }

            response = requests.post(
                upload_url, data=img_data, headers=headers, timeout=60
            )
            response.raise_for_status()
            blob_data = response.json().get("blob")
            return blob_data

        except Exception as e:
            logger.error(f"❌ 画像のアップロードに失敗しました: {e}")
            return None

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

    def post_video_minimal(self, video: dict, dry_run: bool = False) -> bool:
        """
        最小限の動画投稿API（テキストのみ）

        Args:
            video: 動画情報の項目
            dry_run: True の場合、実際には投稿せずログ出力のみ行う
        """
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

            # --- Embed 構築 ---
            embed: Optional[Dict[str, Any]] = None
            attach_image = video.get("attach_image", True)
            use_card = video.get("use_card", 1)  # 1 or 0
            image_filename = video.get("image_filename")

            # v2.1.0: 画像パスの解決を一新 (image_manager の仕様に合わせる)
            site = video.get("source", "YouTube")
            # 内部的には YouTube だがフォルダ名は YouTube
            if site.lower() == "youtube":
                site = "YouTube"

            image_path = None
            if image_filename:
                # 優先順位 1: images/{site}/import/{filename}
                path_import = os.path.join("images", site, "import", image_filename)
                # 優先順位 2: images/{site}/autopost/{filename}
                path_autopost = os.path.join("images", site, "autopost", image_filename)
                # 優先順位 3: 旧仕様互換 data/img/{filename} (もしあれば)
                path_legacy = os.path.join("data", "img", image_filename)

                if os.path.exists(path_import):
                    image_path = path_import
                elif os.path.exists(path_autopost):
                    image_path = path_autopost
                elif os.path.exists(path_legacy):
                    image_path = path_legacy

            # --- 画像処理ロジック (v2.1.0) ---
            processed_image_data = None
            if image_path:
                post_logger.info(f"🔄 投稿用画像を処理しています: {image_path}")
                try:
                    from image_manager import get_image_manager

                    im = get_image_manager(config=self.config)

                    with open(image_path, "rb") as f:
                        raw_data = f.read()

                    # リサイズ (アスペクト比パターン別、拡大なし)
                    resized_data = im.resize_image(raw_data, use_logger=post_logger)
                    if resized_data:
                        # 最適化 (段階的圧縮)
                        processed_image_data = im.optimize_image(
                            resized_data, use_logger=post_logger
                        )

                    if not processed_image_data:
                        post_logger.error(
                            "❌ 画像のリサイズまたは最適化に失敗しました（1MB超過等の制限）"
                        )
                except Exception as e:
                    post_logger.error(
                        f"❌ 画像処理中に予期せぬエラーが発生しました: {e}"
                    )

            # 1. 画像添付
            if attach_image and processed_image_data:
                post_logger.info(f"🖼️ 画像を添付しています...")
                if not dry_run:
                    blob = self._upload_blob(processed_image_data)
                else:
                    blob = {
                        "$type": "blob",
                        "ref": "DRY_RUN",
                        "mimeType": "image/jpeg",
                        "size": len(processed_image_data),
                    }

                if blob:
                    embed = {
                        "$type": "app.bsky.embed.images",
                        "images": [{"alt": title, "image": blob}],
                    }
                    post_logger.info("✅ 画像をアップロードしました")
            elif attach_image and image_filename:
                if not processed_image_data:
                    post_logger.warning(
                        f"⚠️ 画像処理に失敗したため添付をスキップします: {image_filename}"
                    )
                else:
                    post_logger.warning(
                        f"⚠️ 画像ファイルが見つからないため添付をスキップします: {image_filename}"
                    )

            # 2. リンクカード（画像がない場合、または画像添付がOFFでカードがONの場合）
            if not embed and use_card:
                post_logger.info("📇 リンクカードを構築しています...")
                # サムネイルがある場合はそれをカードの画像としてアップロード
                card_thumb_blob = None
                if processed_image_data:
                    if not dry_run:
                        card_thumb_blob = self._upload_blob(processed_image_data)
                    else:
                        card_thumb_blob = {
                            "$type": "blob",
                            "ref": "DRY_RUN_CARD",
                            "mimeType": "image/jpeg",
                            "size": len(processed_image_data),
                        }

                embed = {
                    "$type": "app.bsky.embed.external",
                    "external": {
                        "uri": video_url,
                        "title": title,
                        "description": f"🎬 {channel_name} - {source.capitalize()}",
                        "thumb": card_thumb_blob,
                    },
                }
                if card_thumb_blob:
                    post_logger.info("✅ カード画像をアップロードしました")
                else:
                    post_logger.info("ℹ️ 画像なしのリンクカードを構築しました")

            created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            post_url = "https://bsky.social/xrpc/com.atproto.repo.createRecord"
            post_record: Dict[str, Any] = {
                "$type": "app.bsky.feed.post",
                "text": post_text,
                "createdAt": created_at,
            }

            # Facet を構築（URL をリンク化）
            facets = self._build_facets_for_url(post_text)
            if facets:
                post_record["facets"] = facets

            # Embed をセット
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

            if facets:
                post_logger.info(
                    f"📍 投稿: text={len(post_text)} 文字, facets={len(facets) if facets else 0} 個, 画像={bool(embed)}"
                )
            if facets:
                post_logger.info(f"   facets: {[f['index'] for f in facets]}")

            # --- ドライラン対応 ---
            if dry_run:
                post_logger.info(
                    "🧪 [DRY RUN] 投稿をシミュレーションしました（実際には送信されません）"
                )
                logger.info("🧪 [DRY RUN] 投稿をシミュレーションしました")
                return True

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
            if dry_run:
                logger.error(f"🧪 [DRY RUN] シミュレーション中にエラー: {e}")
                return False
            logger.error(f"投稿処理中にエラーが発生しました: {e}", exc_info=True)
            return False
