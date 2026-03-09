# -*- coding: utf-8 -*-

"""
Websubサーバー HTTP API クライアント - WebSub データ取得用（HTTP 経由）

本番サーバー (https://webhook.neco-server.net) の HTTP API を使用して、
WebSub で集積されたビデオデータを取得する。

API エンドポイント:
  - GET /videos?channel_id=...&limit=...
  - レスポンス: {"channel_id": "...", "count": N, "items": [...]}
"""

import logging
import os
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


class ProductionServerAPIClient:
    """本番サーバーの HTTP API を使用してデータを取得するクライアント"""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 10.0):
        """
        初期化

        Args:
            base_url: 本番サーバーのベース URL
                    - https://webhook.neco-server.net
                    - http://192.168.100.14:8000
                    - None: 環境変数 WEBSUB_BASE_URL または自動判定
            timeout: HTTP リクエストタイムアウト（秒）
        """
        if base_url is None:
            base_url = os.getenv("WEBSUB_BASE_URL", "https://webhook.neco-server.net")

        # URL の末尾 / を除去
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._verify_connection()

    def _verify_connection(self):
        """本番サーバーへの接続を検証"""
        try:
            # ★ 改善: /health ヘルスチェック用エンドポイントでテスト
            url = f"{self.base_url}/health"
            logger.debug(f"🔍 Websubサーバー HTTP API 接続テスト: {url}")
            response = requests.get(url, timeout=self.timeout)

            if response.status_code == 200:
                logger.info(f"✅ Websubサーバー HTTP API 接続成功: {self.base_url}")
            else:
                logger.warning(
                    f"⚠️ Websubサーバー HTTP API 応答コード: {response.status_code}"
                )
                logger.warning(f"   テスト URL: {url}")
                logger.warning(
                    f"   レスポンス: {response.text[:200] if response.text else '(empty)'}"
                )

        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ 本番サーバー接続失敗: {e}")
            logger.error(f"   URL: {self.base_url}")
            raise
        except Exception as e:
            logger.error(f"❌ 本番サーバー接続テストエラー: {e}")
            raise

    def verify_connection(self) -> bool:
        """
        本番サーバーへの接続を確認（公開メソッド）

        Returns:
            bool: 接続成功時 True、失敗時 False
        """
        try:
            url = f"{self.base_url}/health"
            response = requests.get(url, timeout=self.timeout)
            is_connected = response.status_code == 200

            if is_connected:
                logger.debug(f"✅ センターサーバー接続確認: OK")
            else:
                logger.warning(
                    f"⚠️ センターサーバー接続確認: ステータス {response.status_code}"
                )

            return is_connected

        except Exception as e:
            logger.warning(f"⚠️ センターサーバー接続確認失敗: {e}")
            return False

    def get_websub_videos(
        self, channel_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        本番サーバーから WebSub ビデオを取得

        Args:
            channel_id: YouTube チャンネル ID
            limit: 取得件数上限

        Returns:
            ビデオ情報の辞書リスト
        """
        try:
            url = f"{self.base_url}/videos"
            params: Dict[str, Any] = {"channel_id": channel_id, "limit": limit}

            logger.debug(
                f"📥 Websubサーバー HTTP API リクエスト: {url} params={params}"
            )
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()
            items = data.get("items", [])

            logger.debug(
                f"📥 Websubサーバー HTTP API から {len(items)} 件のビデオを取得"
            )

            return items

        except requests.exceptions.HTTPError as e:
            logger.error(f"❌ HTTP エラー: {e.response.status_code} - {e}")
            logger.error(f"   リクエスト URL: {e.response.request.url}")
            logger.error(
                f"   レスポンス: {e.response.text[:300] if e.response.text else '(empty)'}"
            )
            return []
        except requests.exceptions.Timeout:
            logger.error(f"❌ リクエストタイムアウト: {self.timeout}秒")
            return []
        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ 接続エラー: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ ビデオ取得エラー: {e}")
            return []

    def get_channel_stats(self, channel_id: str) -> Dict[str, Any]:
        """
        チャンネル別の統計情報を取得

        Args:
            channel_id: YouTube チャンネル ID

        Returns:
            統計情報の辞書
                - channel_id: チャンネル ID
                - count: ビデオ件数
                - items: ビデオリスト（最大 limit 件）
        """
        try:
            url = f"{self.base_url}/videos"
            params: Dict[str, Any] = {"channel_id": channel_id, "limit": 1}  # 統計のみなので 1 件取得

            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()
            stats = {
                "channel_id": data.get("channel_id"),
                "count": data.get("count", 0),
            }

            logger.info(f"📊 チャンネル統計: {channel_id} → {stats['count']} 件")

            return stats

        except Exception as e:
            logger.error(f"❌ 統計取得エラー: {e}")
            return {}

    def health_check(self) -> bool:
        """
        本番サーバーのヘルスチェック

        Returns:
            正常な場合 True、異常な場合 False
        """
        try:
            url = f"{self.base_url}/health"
            response = requests.get(url, timeout=5.0)

            if response.status_code == 200:
                logger.debug("✅ 本番サーバー ヘルスチェック: OK")
                return True
            else:
                logger.warning(f"⚠️ ヘルスチェック応答: {response.status_code}")
                return False

        except Exception as e:
            logger.debug(f"⚠️ ヘルスチェックエラー（無視）: {e}")
            return False

    def register_websub_client(
        self,
        clientid: str,
        channelid: str,
        callbackurl: str,
    ) -> bool:
        """
        WebSub サーバーの /register に購読登録を投げる。
        成功したら True、失敗したら False を返す。
        """

        # 環境変数から client 用 API キーを取得
        client_api_key = os.getenv("WEBSUB_CLIENT_API_KEY")
        if not client_api_key:
            logger.error(
                "WebSub register skipped: WEBSUB_CLIENT_API_KEY is not set "
                f"(client_id={clientid})"
            )
            return False

        try:
            url = f"{self.base_url}/register"
            payload = {
                "client_id": clientid,
                "channel_id": channelid,
                "callback_url": callbackurl,
            }
            headers = {
                "X-Client-API-Key": client_api_key,
            }

            logger.debug(f"WebSub register: url={url} payload={payload}")
            response = requests.post(
                url, json=payload, headers=headers, timeout=self.timeout
            )
            # 4xx/5xx のときに例外を出す
            response.raise_for_status()

            # FastAPI 側は {"status": "ok"} を返している想定 [file:22][file:21]
            data = response.json()
            status = data.get("status")
            if status == "ok":
                logger.debug("WebSub register: success")
                return True
            else:
                logger.warning(f"WebSub register: unexpected response: {data}")
                return False

        except requests.exceptions.HTTPError as e:
            logger.error(f"WebSub register HTTP {e.response.status_code} - {e}")
            logger.error(f"URL: {e.response.request.url}")
            logger.error(e.response.text[:300] if e.response.text else "empty")
            return False
        except requests.exceptions.Timeout:
            logger.error(f"WebSub register timeout: {self.timeout}")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error(f"WebSub register connection error: {e}")
            return False
        except Exception as e:
            logger.error(f"WebSub register error: {e}")
            return False


# ===== シングルトンインスタンス管理 =====

_production_api_client_instance = None


def get_production_api_client(base_url: Optional[str] = None) -> ProductionServerAPIClient:
    """
    ProductionServerAPIClient のシングルトンインスタンスを取得

    Args:
        base_url: Websubサーバー HTTP API のベース URL（省略可）

    Returns:
        ProductionServerAPIClient インスタンス
    """
    global _production_api_client_instance

    if _production_api_client_instance is None:
        try:
            _production_api_client_instance = ProductionServerAPIClient(
                base_url=base_url
            )
        except Exception as e:
            logger.error(f"❌ ProductionServerAPIClient 初期化エラー: {e}")
            raise

    return _production_api_client_instance
