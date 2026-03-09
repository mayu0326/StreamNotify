# -*- coding: utf-8 -*-

"""
StreamNotify on Bluesky- v1 Bluesky プラグイン

Bluesky へのポスト機能を提供。
HTTP API で直接 Rich Text をポスト。
Rich Text Facet: https://docs.bsky.app/docs/advanced-guides/post-richtext
"""

import json
import logging
import re
from datetime import datetime, timezone

import requests

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


class BlueskyPlugin:
    """Bluesky に投稿するプラグイン"""

    def __init__(self, username: str, password: str, dry_run: bool = False):
        """
        初期化

        Args:
            username: Bluesky ユーザー名（@xxx.bsky.social）
            password: Bluesky アプリパスワード
            dry_run: ドライラン（実際には投稿しない）
        """
        self.username = username
        self.password = password
        self.dry_run = dry_run
        self.access_token = None
        self.did = None

        if dry_run:
            logger.info("🧪 BlueskyPlugin は DRY RUN モードで動作します。実際には投稿しません。")
        else:
            self._login()

    def _login(self):
        """Bluesky にログイン（HTTP API を使用）"""
        try:
            auth_url = "https://bsky.social/xrpc/com.atproto.server.createSession"

            auth_data = {
                "identifier": self.username,
                "password": self.password
            }

            response = requests.post(auth_url, json=auth_data, timeout=30)
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

    def _find_urls_with_byte_positions(self, text: str) -> list:
        """
        テキストから URL を抽出（バイト位置を正確に計算）

        重要: byteStart/byteEnd は UTF-8 エンコード後のバイトオフセット

        Args:
            text: テキスト

        Returns:
            [{'url': url, 'byte_start': int, 'byte_end': int}, ...]
        """
        pattern = r'https?://[^\s]+'
        urls = []

        for match in re.finditer(pattern, text):
            # UTF-8 バイト位置を計算
            # byteStart: マッチ開始のバイト位置
            # byteEnd: マッチ終了のバイト位置（排他的）
            byte_start = len(text[:match.start()].encode('utf-8'))
            byte_end = len(text[:match.end()].encode('utf-8'))

            urls.append({
                'url': match.group(),
                'byte_start': byte_start,
                'byte_end': byte_end,
            })

            logger.info(f"  🔗 URL 検出: {match.group()}")
            logger.info(f"     バイト位置: {byte_start} - {byte_end}")

        return urls

    def _build_facets(self, text: str) -> list | None:
        """
        Facet リストを構築（URL をリンク化）

        参照: https://docs.bsky.app/docs/advanced-guides/post-richtext

        Args:
            text: ポスト本文

        Returns:
            Facet の辞書リスト または None
        """
        urls = self._find_urls_with_byte_positions(text)

        if not urls:
            logger.info("  📍 URL が見つかりませんでした")
            return None

        facets = []

        for url_info in urls:
            try:
                # Facet を構築（AT Protocol 仕様）
                # 重要: $type は "app.bsky.richtext.facet#link"
                facet = {
                    "index": {
                        "byteStart": url_info['byte_start'],
                        "byteEnd": url_info['byte_end']
                    },
                    "features": [
                        {
                            "$type": "app.bsky.richtext.facet#link",
                            "uri": url_info['url']
                        }
                    ]
                }
                facets.append(facet)
                logger.info(f"  ✅ Facet 作成: bytes {url_info['byte_start']}-{url_info['byte_end']} → {url_info['url']}")
            except Exception as e:
                logger.error(f"  ❌ Facet 作成失敗: {e}")
                continue

        return facets if facets else None

    def post_video(self, video: dict) -> bool:
        """
        動画をポスト（URL をリンク化）

        Args:
            video: 動画情報
                - title: 動画タイトル
                - video_url: 動画 URL
                - published_at: 公開日時
                - channel_name: チャンネル名

        Returns:
            True: 成功、False: 失敗
        """
        try:
            title = video.get("title", "【新着動画】")
            video_url = video.get("video_url", "")
            channel_name = video.get("channel_name", "")
            published_at = video.get("published_at", "")

            if not video_url:
                logger.error("❌ video_url が見つかりません")
                return False

            # ポスト本文を構成（Bluesky は 300 文字制限）
            post_text = f"{title}\n\n🎬 {channel_name}\n📅 {published_at[:10]}\n\n{video_url}"

            logger.info(f"投稿内容:\n{post_text}")
            logger.info(f"文字数: {len(post_text)} / 300")
            logger.info(f"バイト数: {len(post_text.encode('utf-8'))}")

            if self.dry_run:
                logger.info(f"[DRY RUN] Bluesky ポスト\n{post_text}")
                return True

            # 実際に投稿
            if not self.access_token or not self.did:
                logger.error("❌ アクセストークンまたは DID が初期化されていません")
                return False

            try:
                # Facet を構築してリンク化
                logger.info("📍 Facet を構築しています...")
                facets = self._build_facets(post_text)

                # ISO 8601 形式の現在時刻
                created_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

                # AT Protocol の createRecord エンドポイントにポスト
                post_url = "https://bsky.social/xrpc/com.atproto.repo.createRecord"

                post_record = {
                    "$type": "app.bsky.feed.post",
                    "text": post_text,
                    "createdAt": created_at,
                }

                # Facet がある場合のみ追加
                if facets:
                    post_record["facets"] = facets

                post_data = {
                    "repo": self.did,
                    "collection": "app.bsky.feed.post",
                    "record": post_record
                }

                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                }

                logger.info(f"📍 投稿: text={len(post_text)} 文字, facets={len(facets) if facets else 0} 個")
                if facets:
                    logger.info(f"   facets: {[f['index'] for f in facets]}")

                response = requests.post(post_url, json=post_data, headers=headers, timeout=30)
                response.raise_for_status()

                response_data = response.json()
                uri = response_data.get("uri", "unknown")

                if facets:
                    logger.info(f"✅ Bluesky に投稿しました（リンク化）: {uri}")
                else:
                    logger.info(f"✅ Bluesky に投稿しました（リンクなし）: {uri}")

                return True

            except requests.exceptions.RequestException as e:
                logger.error(f"❌ Bluesky API エラー: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_data = e.response.json()
                        logger.error(f"   エラー詳細: {error_data}")
                    except:
                        logger.error(f"   レスポンス: {e.response.text}")
                return False
            except Exception as e:
                logger.error(f"❌ ポスト処理エラー: {e}", exc_info=True)
                return False

        except Exception as e:
            logger.error(f"投稿処理中にエラーが発生しました: {e}", exc_info=True)
            return False


def get_bluesky_plugin(username: str, password: str, dry_run: bool = False) -> BlueskyPlugin:
    """Bluesky プラグインを取得"""
    return BlueskyPlugin(username, password, dry_run)
