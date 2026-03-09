# -*- coding: utf-8 -*-

"""
StreamNotify v3 - Bluesky コア機能（内部ライブラリ）

【重要】このモジュールはプラグイン層からのみ利用されます。
直接呼び出しは行わないでください。画像添付機能はプラグイン層で実装されます。

Bluesky へのポスト機能を提供。
HTTP API で直接 Rich Text をポスト。
Rich Text Facet: https://docs.bsky.app/docs/advanced-guides/post-richtext
画像埋め込み: https://docs.bsky.app/docs/advanced-guides/posts
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("AppLogger")
post_logger = logging.getLogger("PostLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

__version__ = "1.0.1"


# --- 最小限投稿API ---
class BlueskyMinimalPoster:
    """Bluesky最小限投稿クラス（API本体）"""

    def __init__(self, username: str, password: str, dry_run: bool = False):
        self.username = username
        self.password = password
        self.dry_run = dry_run
        self.access_token = None
        self.did = None
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "🔍 BlueskyMinimalPoster init: username=%s, dry_run=%s",
                self.username,
                self.dry_run,
            )
        if dry_run:
            logger.info(
                "🧪 BlueSky投稿機能はオフになっています。DRYRUNモードに切り替えました。"
            )
        else:
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

    def set_dry_run(self, dry_run: bool):
        """ドライランモードを設定"""
        self.dry_run = dry_run
        post_logger.info(f"🧪 BlueskyMinimalPoster dry_run={dry_run}")

    def _build_facets_for_url(self, text: str) -> Optional[List[Dict[str, Any]]]:
        """
        テキストから URL とハッシュタグを検出して Facet を構築

        Bluesky Rich Text Facet: https://docs.bsky.app/docs/advanced-guides/post-richtext

        Args:
            text: ポスト本文

        Returns:
            Facet リスト、URL/ハッシュタグがない場合は None
        """
        facets = []

        # ============ URL facet の検出 ============
        url_pattern = r"https?://[^\s]+"
        for match in re.finditer(url_pattern, text):
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

        # ============ ハッシュタグ facet の検出 ============
        # パターン: 単語境界または行頭または空白 + # + 連続する非空白文字（空白と#以外）
        # マルチバイト文字も対応
        hashtag_pattern = r"(?:^|\s)(#[^\s#]+)"

        for match in re.finditer(hashtag_pattern, text):
            full_match = match.group(0)  # 前の空白or行頭を含む
            tag_with_hash = match.group(1)  # #タグ部分のみ

            # タグ名（#を除く）
            tag_name = tag_with_hash[1:]  # # を削除

            # バイト位置計算：フルマッチの中で#の開始位置を見つける
            # フルマッチが空白で始まる場合、その空白分をオフセット
            offset_in_match = len(full_match) - len(tag_with_hash)

            byte_start = len(text[: match.start() + offset_in_match].encode("utf-8"))
            byte_end = len(
                text[: match.start() + offset_in_match + len(tag_with_hash)].encode(
                    "utf-8"
                )
            )

            facet = {
                "index": {"byteStart": byte_start, "byteEnd": byte_end},
                "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag_name}],
            }
            facets.append(facet)
            post_logger.info(
                f"  #️⃣  ハッシュタグ検出: {tag_with_hash} (タグ: {tag_name})"
            )
            post_logger.info(f"     バイト位置: {byte_start} - {byte_end}")

        return facets if facets else None

    def post_video_minimal(self, video: dict) -> bool:
        """最小限の動画投稿API（テキスト + オプション画像埋め込み）"""
        post_data: Dict[str, Any] = {}
        try:
            # デバッグ: 受け取ったフィールドを確認
            post_logger.debug(f"🔍 post_video_minimal に受け取ったフィールド:")
            post_logger.debug(f"   source: {video.get('source')}")
            post_logger.debug(f"   image_mode: {video.get('image_mode')}")
            post_logger.debug(f"   image_filename: {video.get('image_filename')}")
            post_logger.debug(f"   embed: {bool(video.get('embed'))}")
            post_logger.debug(f"   text_override: {bool(video.get('text_override'))}")

            # text_override がある場合は優先（テンプレートレンダリング済み）
            text_override = video.get("text_override")

            title = video.get("title", "【新着動画】")
            video_url = video.get("video_url", "")
            channel_name = video.get("channel_name", "")
            published_at = video.get("published_at", "")
            source = video.get("source", "youtube").lower()

            if not video_url:
                logger.error("❌ video_url が見つかりません")
                return False

            # source に応じたテンプレートを生成
            if text_override:
                # プラグイン側でテンプレートから生成した本文を優先
                post_text = text_override
                post_logger.info(f"📝 テンプレート生成済みの本文を使用します")
            elif source == "niconico":
                post_text = f"{title}\n\n📅 {published_at[:10]}\n\n{video_url}"
            else:
                # YouTube（デフォルト）
                post_text = f"{title}\n\n🎬 {channel_name}\n📅 {published_at[:10]}\n\n{video_url}"

            post_logger.info(f"投稿内容:\n{post_text}")
            post_logger.info(f"文字数: {len(post_text)} / 300")
            post_logger.info(f"バイト数: {len(post_text.encode('utf-8'))}")

            # Facet構築（省略可）
            facets = None
            # video辞書から embed を取得（プラグインが設定した場合）
            embed = video.get("embed", None)
            # ★ プラグイン経由フラグを取得（デフォルト: True）
            via_plugin = video.get("via_plugin", True)
            # use_link_card フラグを取得（デフォルト: True - プラグイン有効時のみ使用）
            use_link_card = video.get("use_link_card", True)
            created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            # Facet を構築（URL をリンク化）
            post_logger.info("📍 Facet を構築しています...")
            facets = self._build_facets_for_url(post_text)

            # === 条件分岐: embed の決定 ===
            # embed フィールドは Union 型（1種類のみ）
            if embed:
                # パターン2: プラグイン有効 + 画像ありの場合
                post_logger.info("🖼️ 画像 embed を使用します（リンクカード無効化）")
                use_link_card = False  # リンクカードは使用しない
            elif use_link_card and video_url and via_plugin:
                # ★ リンクカードはプラグイン機能 - プラグイン経由のときのみ構築
                post_logger.info("🔗 リンクカード embed を構築しています...")
                embed = self._build_external_embed(video_url)
                if embed:
                    post_logger.info("[SUCCESS] リンクカード embed を追加します")
                else:
                    post_logger.info(
                        "[INFO] リンクカード embed は無視されます（画像なし）"
                    )

            if self.dry_run:
                logger.info(f"[DRY RUN] Bluesky ポスト\n{post_text}")
                return True
            if not self.access_token or not self.did:
                logger.error(
                    "[ERROR] アクセストークンまたは DID が初期化されていません"
                )
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
                f"[INFO] 投稿: text={len(post_text)} 文字, facets={len(facets) if facets else 0} 個, 画像={bool(embed)}"
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
                post_logger.info(f"[SUCCESS] Bluesky に投稿しました（リンク化）: {uri}")
                logger.info(f"[SUCCESS] Bluesky に投稿しました（リンク化）: {uri}")
            else:
                post_logger.info(
                    f"[SUCCESS] Bluesky に投稿しました（リンクなし）: {uri}"
                )
                logger.info(f"[SUCCESS] Bluesky に投稿しました（リンクなし）: {uri}")

            return True
        except Exception as e:
            logger.error(
                f"[ERROR] Bluesky API エラー: {e.response.status_code if hasattr(e, 'response') else 'unknown'} - {e.response.text if hasattr(e, 'response') else str(e)}"
            )
            post_logger.error(
                f"[ERROR] Bluesky API エラー: {e.response.status_code if hasattr(e, 'response') else 'unknown'} - {e.response.text if hasattr(e, 'response') else str(e)}"
            )
            logger.error(
                f"投稿リクエストボディ: {json.dumps(post_data, indent=2, default=str)}",
                exc_info=False,
            )
            return False
            logger.error(f"投稿処理中にエラーが発生しました: {e}", exc_info=True)
            return False

    # ============ リンクカード機能（OGP 取得） ============

    def _fetch_ogp_data(self, url: str) -> Optional[Dict[str, Any]]:
        """
        URL から OGP（Open Graph Protocol）メタデータを取得

        Args:
            url: 対象 URL

        Returns:
            {"title": str, "description": str, "image_url": str or None}
        """
        try:
            post_logger.info(f"📋 OGP データを取得しています: {url}")

            # タイムアウト設定して HTML を取得
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()

            # HTML をパース
            try:
                from bs4 import BeautifulSoup
            except ImportError:
                post_logger.warning(
                    "⚠️ BeautifulSoup がインストールされていません。OGP 取得をスキップします"
                )
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # OGP タグを抽出
            og_title = soup.find("meta", property="og:title")
            og_desc = soup.find("meta", property="og:description")
            og_image = soup.find("meta", property="og:image")

            # フォールバック: og:title がない場合は title タグを使用
            if not og_title:
                title_tag = soup.find("title")
                title = str(title_tag.string) if title_tag and title_tag.string else "No title"
            else:
                title_raw = og_title.get("content", "No title")
                title = title_raw[0] if isinstance(title_raw, list) else (title_raw or "No title")

            description_raw = og_desc.get("content", "") if og_desc else ""
            description = description_raw[0] if isinstance(description_raw, list) else (description_raw or "")

            image_url_raw = og_image.get("content", None) if og_image else None
            image_url = image_url_raw[0] if isinstance(image_url_raw, list) else image_url_raw

            # 相対 URL を絶対 URL に変換
            if image_url and "://" not in image_url:
                from urllib.parse import urljoin

                image_url = urljoin(url, image_url)

            ogp_data = {
                "title": title[:100],  # 最大 100 文字
                "description": description[:256],  # 最大 256 文字
                "image_url": image_url,
            }

            post_logger.info(f"✅ OGP 取得成功: title={title[:30]}...")
            return ogp_data

        except Exception as e:
            post_logger.warning(f"⚠️ OGP 取得失敗: {e}")
            return None

    def _upload_ogp_image_blob(self, image_url: str) -> Optional[Dict[str, Any]]:
        """
        OGP 画像を Blob としてアップロード

        Args:
            image_url: 画像 URL

        Returns:
            blob メタデータ、失敗時は None
        """
        try:
            if self.dry_run:
                post_logger.info(
                    f"🧪 [DRY RUN] 画像アップロード（スキップ）: {image_url}"
                )
                return {
                    "$type": "blob",
                    "mimeType": "image/jpeg",
                    "size": 1000,
                    "link": {"$link": "bafkreidummy"},
                }

            post_logger.info(f"📥 OGP 画像をダウンロード中: {image_url}")

            # 画像をダウンロード
            img_resp = requests.get(image_url, timeout=10)
            img_resp.raise_for_status()

            # ファイルサイズチェック（1MB 制限）
            if len(img_resp.content) > 1_000_000:
                post_logger.warning(
                    f"⚠️ OGP 画像が大きすぎます: {len(img_resp.content)} bytes > 1MB"
                )
                return None

            # MIME Type を取得
            mime_type = img_resp.headers.get("Content-Type", "image/jpeg")

            # アクセストークン確認
            if not self.access_token:
                post_logger.warning(
                    f"⚠️ 認証トークンがありません。OGP 画像をアップロードできません"
                )
                return None

            # Blob としてアップロード
            upload_url = "https://bsky.social/xrpc/com.atproto.repo.uploadBlob"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": mime_type,
            }

            upload_resp = requests.post(
                upload_url, data=img_resp.content, headers=headers, timeout=30
            )
            upload_resp.raise_for_status()

            result = upload_resp.json()
            blob = result.get("blob")

            if blob:
                post_logger.info(
                    f"✅ OGP 画像アップロード成功: {blob.get('mimeType')} ({len(img_resp.content)} bytes)"
                )
                return blob
            else:
                post_logger.warning(f"⚠️ Blob メタデータが返されませんでした")
                return None

        except Exception as e:
            post_logger.warning(f"⚠️ OGP 画像アップロード失敗: {e}")
            return None

    def _build_external_embed(self, url: str) -> Optional[Dict[str, Any]]:
        """
        リンクカード（外部 embed）を構築

        OGP データを取得して、リンクカードを構築します。
        Bluesky API: app.bsky.embed.external
        参照: https://docs.bsky.app/docs/advanced-guides/posts

        Args:
            url: 対象 URL

        Returns:
            embed オブジェクト、失敗時は None
        """
        try:
            ogp_data = self._fetch_ogp_data(url)
            if not ogp_data:
                post_logger.warning(
                    f"⚠️ OGP データが取得できませんでした。リンクカードなしで投稿します"
                )
                return None

            # リンクカード基本情報
            embed: Dict[str, Any] = {
                "$type": "app.bsky.embed.external",
                "external": {
                    "uri": url,
                    "title": ogp_data["title"],
                    "description": ogp_data["description"],
                },
            }

            # 画像がある場合、アップロード
            if ogp_data.get("image_url"):
                blob = self._upload_ogp_image_blob(ogp_data["image_url"])
                if blob:
                    embed["external"]["thumb"] = blob
                    post_logger.info(f"✅ リンクカード画像を追加しました")

            post_logger.info(f"✅ リンクカード embed を構築しました")
            return embed

        except Exception as e:
            post_logger.warning(f"⚠️ リンクカード構築失敗: {e}")
            return None
