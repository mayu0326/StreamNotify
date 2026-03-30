import asyncio
import logging
import re
import httpx
from datetime import datetime, timezone, timedelta
import io
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

BLUESKY_POST_RETRY_ATTEMPTS = 3
BLUESKY_POST_RETRY_DELAY_SEC = 2
from v4.core.config import settings
from v4.core.assets.image_processor import resize_image

logger = logging.getLogger("v4.bluesky")

class BlueskyClient:
    """
    Async Bluesky Client for v4.
    Simple and robust implementation focusing on rich text and basic embedding.
    """
    def __init__(self, dry_run: bool = False):
        self.base_url = "https://bsky.social/xrpc"
        self.username = settings.bluesky_username
        self.password = settings.bluesky_password
        self.dry_run = dry_run or not settings.bluesky_post_enabled
        self.access_token: Optional[str] = None
        self.did: Optional[str] = None

        if self.dry_run:
            logger.info("🧪 Bluesky Client initialized in DRY-RUN mode.")

    async def get_account_status(self) -> Optional[Dict[str, Any]]:
        """
        Check authentication status with Center Server.
        Returns: { "status": "connected", "handle": "...", "did": "..." } or None
        """
        if not settings.bluesky_center_oauth_available():
            logger.debug("get_account_status skipped (Bluesky center OAuth disabled or poll mode)")
            return None

        try:
            # Center Server のステータス確認エンドポイント
            # 注: 本来は認証ヘッダーが必要だが、Desktop App のコンテキストでは
            # ローカルのCookieや、OAuth直後のタイミングでの呼び出しを想定
            # 現状の webhook_app 実装では JWT Authorization header が必要 (/bsky/status)
            # しかし、クライアントはJWTを持っていないため、
            # 本来は token endpoint で取得したアクセストークンを使うべきだが、
            # 今回のスコープでは「認証成功リダイレクトを受け取ったら成功」とみなして
            # サーバー側が "default" アカウントとして認識している情報を返すような仕組みが必要。
            # いったん、サーバーの /auth/bsky/status を叩いてみる。

            url = f"{settings.center_server_url.rstrip('/')}/auth/bsky/status"
            headers = {
                "X-Client-Id": settings.websub_client_id,
                "X-Client-Api-Key": settings.websub_client_api_key
            }
            # 秘密情報はログに出さない（先頭数文字のマスクでも推測リスクがあるため）
            key_state = "set" if settings.websub_client_api_key else "missing"
            logger.info(
                "Checking Bluesky status. URL: %s, ClientID: %s, APIKey: %s",
                url,
                settings.websub_client_id,
                key_state,
            )

            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=5.0)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 401:
                    logger.warning(f"Bluesky account status: Unauthorized (not connected). Response: {resp.text}")
                    return {"status": "disconnected"}
                else:
                    logger.warning(f"Failed to check Bluesky status: {resp.status_code}")
                    return None
        except Exception as e:
            logger.error(f"Error checking Bluesky status from server: {e}")
            return None

    async def disconnect(self) -> bool:
        """
        Request the Center Server to remove the linked account.
        """
        if not settings.bluesky_center_oauth_available():
            logger.debug("Bluesky disconnect: center Bluesky API skipped (OAuth frozen or poll mode)")
            return True

        try:
            url = f"{settings.center_server_url.rstrip('/')}/auth/bsky/account"
            headers = {
                "X-Client-Id": settings.websub_client_id,
                "X-Client-Api-Key": settings.websub_client_api_key
            }
            logger.info(f"Requesting Bluesky disconnect from server: {url}")

            async with httpx.AsyncClient() as client:
                resp = await client.delete(url, headers=headers, timeout=5.0)

                if resp.status_code == 200:
                    logger.info("✅ Server-side account disconnected successfully.")
                    return True
                else:
                    logger.warning(f"Server-side disconnect failed (may already be disconnected): {resp.status_code} - {resp.text}")
                    # Even if server fails (e.g. already deleted), we usually want to proceed with local cleanup
                    return True
        except Exception as e:
            logger.error(f"Error during server disconnect request: {e}")
            # Network error etc. We still return True to allow local cleanup?
            # Ideally we want to be clean, but local cleanup is priority for user experience.
            return True

    async def login(self) -> bool:
        if self.dry_run:
            return True

        if not self.username or not self.password:
            logger.error("❌ Bluesky credentials not configured.")
            return False

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}/com.atproto.server.createSession",
                    json={"identifier": self.username, "password": self.password},
                    timeout=10.0
                )
                resp.raise_for_status()
                data = resp.json()
                self.access_token = data.get("accessJwt")
                self.did = data.get("did")
                logger.info(f"✅ Logged into Bluesky as {self.username}")
                return True
        except Exception as e:
            logger.error(f"❌ Bluesky login failed: {e}")
            return False

    def _build_facets(self, text: str) -> List[Dict[str, Any]]:
        """Build facets for links and hashtags."""
        facets = []

        # Link detection
        url_pattern = r'https?://[^\s]+'
        for match in re.finditer(url_pattern, text):
            url = match.group(0)
            byte_start = len(text[:match.start()].encode('utf-8'))
            byte_end = len(text[:match.end()].encode('utf-8'))
            facets.append({
                "index": {"byteStart": byte_start, "byteEnd": byte_end},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]
            })

        # Hashtag detection
        hashtag_pattern = r'(?:^|\s)(#[^\s#]+)'
        for match in re.finditer(hashtag_pattern, text):
            full_match = match.group(0)
            tag_with_hash = match.group(1)
            tag_name = tag_with_hash[1:]

            offset_in_match = len(full_match) - len(tag_with_hash)
            byte_start = len(text[:match.start() + offset_in_match].encode('utf-8'))
            byte_end = len(text[:match.start() + offset_in_match + len(tag_with_hash)].encode('utf-8'))

            facets.append({
                "index": {"byteStart": byte_start, "byteEnd": byte_end},
                "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag_name}]
            })

        return facets

    async def _get_server_token(self, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """
        センターサーバーからアクセストークンとアカウント情報を取得する。

        Args:
            force_refresh: True の場合、サーバーに明示的なリフレッシュを要求する

        Returns:
            {"access_token": ..., "pds_url": ..., "did": ..., "handle": ...} or None
        """
        try:
            url = f"{settings.center_server_url.rstrip('/')}/auth/bsky/token"
            headers = {
                "X-Client-Id": settings.websub_client_id,
                "X-Client-Api-Key": settings.websub_client_api_key,
            }
            params = {"force_refresh": "1"} if force_refresh else {}
            # センターがトークンリフレッシュ（DPoP 再試行含む）で数十秒かかることがあるため長めに取る
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=headers, params=params, timeout=75.0)
                if resp.status_code == 200:
                    return resp.json()
                else:
                    logger.warning(f"Failed to get server token: {resp.status_code} {resp.text}")
                    return None
        except Exception as e:
            logger.error("Error fetching server token: %s", e or type(e).__name__)
            return None

    @staticmethod
    def _parse_token_expiry_utc(token_data: Dict[str, Any]) -> Optional[datetime]:
        """
        トークン期限をUTC datetimeで返す。
        サーバー実装差異を吸収するため複数キーに対応:
        - expires_at / token_expires_at (ISO8601、センターは同一値)
        - exp (unix epoch秒)
        - expires_in (残秒, 現在時刻基準)
        """
        if not token_data:
            return None

        expires_at = token_data.get("expires_at") or token_data.get("token_expires_at")
        if isinstance(expires_at, str) and expires_at:
            try:
                # "Z" -> +00:00 へ正規化
                dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass

        exp = token_data.get("exp")
        if isinstance(exp, (int, float)):
            try:
                return datetime.fromtimestamp(float(exp), tz=timezone.utc)
            except Exception:
                pass

        expires_in = token_data.get("expires_in")
        if isinstance(expires_in, (int, float)):
            try:
                return datetime.now(timezone.utc) + timedelta(seconds=float(expires_in))
            except Exception:
                pass

        return None

    async def ensure_server_token_fresh_on_startup(self, refresh_window_seconds: int = 600) -> bool:
        """
        起動時の事前チェック:
        - 期限情報が取得できる場合、残りが refresh_window_seconds 未満なら force_refresh する。
        - 期限情報が無い場合はチェック不能として True を返す（投稿時の401リフレッシュに委ねる）。
        """
        if not settings.bluesky_center_oauth_available():
            logger.debug("ensure_server_token_fresh_on_startup skipped (Bluesky center OAuth off or poll mode)")
            return True

        token_data = await self._get_server_token(force_refresh=False)
        if not token_data or not token_data.get("access_token"):
            logger.warning("Bluesky token startup check: token unavailable.")
            return False

        if token_data.get("refresh_attempted") and token_data.get("refresh_succeeded") is False:
            logger.warning(
                "Bluesky: center refresh failed (e.g. client-metadata not reachable by Bluesky). "
                "Token in DB may be expired; set BSKY_OAUTH_PUBLIC_BASE_URL on server if using an alternate public hostname."
            )

        expiry_utc = self._parse_token_expiry_utc(token_data)
        if not expiry_utc:
            logger.debug("Bluesky token startup check: expiry not provided by server; skip pre-refresh.")
            return True

        now_utc = datetime.now(timezone.utc)
        remaining_sec = (expiry_utc - now_utc).total_seconds()
        if remaining_sec >= refresh_window_seconds:
            logger.info(
                "Bluesky token startup check: token is healthy (remaining=%ss).",
                int(remaining_sec),
            )
            return True

        logger.info(
            "Bluesky token startup check: token near expiry (remaining=%ss), force refresh.",
            int(remaining_sec),
        )
        refreshed = await self._get_server_token(force_refresh=True)
        if not refreshed or not refreshed.get("access_token"):
            logger.warning("Bluesky token startup refresh: failed (no token in response).")
            return False

        if refreshed.get("refresh_attempted") and refreshed.get("refresh_succeeded") is False:
            logger.warning(
                "Bluesky token startup refresh: server kept stored token (Bluesky refresh failed). "
                "Fix public reachability of client-metadata / jwks, or set BSKY_OAUTH_PUBLIC_BASE_URL on center."
            )
            return True

        logger.info("Bluesky token startup refresh: success.")
        return True

    async def _get_server_sign(
        self,
        method: str,
        url: str,
        access_token: str,
        nonce: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """
        センターサーバーに DPoP Proof の生成を依頼する。
        access_token を渡すことでサーバー側が RFC 9449 の ath クレームを付与する。
        nonce が指定された場合はそれも DPoP Proof に含める（Bluesky nonce チャレンジ対応）。
        """
        try:
            sign_url = f"{settings.center_server_url.rstrip('/')}/auth/bsky/sign"
            headers = {
                "X-Client-Id": settings.websub_client_id,
                "X-Client-Api-Key": settings.websub_client_api_key,
            }
            payload: Dict[str, Any] = {
                "method": method,
                "url": url,
                "access_token": access_token,
            }
            if nonce:
                payload["nonce"] = nonce

            async with httpx.AsyncClient() as client:
                resp = await client.post(sign_url, json=payload, headers=headers, timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    dpop = data.get("dpop") or (data.get("headers") or {}).get("DPoP")
                    if dpop:
                        return {"DPoP": dpop}
                    return {}
                else:
                    logger.warning(f"Failed to get server signature: {resp.status_code} {resp.text}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching server signature: {e}")
            return None

    async def post_via_oauth(
        self,
        text: str,
        image_path: Optional[str] = None,
        resize_small_images: bool = True,
    ) -> bool:
        """
        Try to post using Server-Side OAuth (Priority Mode).
        Returns True if successful, False if failed (should trigger fallback).

        Bluesky の OAuth アクセストークンは PDS 専用のため、リクエスト先は
        bsky.social の固定 URL ではなく account["pds_url"] を使う必要がある。
        """
        logger.info("🚀 Attempting to post via OAuth Priority Mode...")

        # 1. トークンとアカウント情報を取得
        token_data = await self._get_server_token()
        if not token_data or not token_data.get("access_token"):
            logger.warning("⚠️ OAuth Mode: Could not get access token (Server down or not linked?). Falling back.")
            return False

        access_token: str = token_data["access_token"]
        pds_url: str = token_data.get("pds_url", "https://bsky.social").rstrip("/")
        pds_xrpc = f"{pds_url}/xrpc"

        if token_data.get("did"):
            self.did = token_data["did"]

        # トークンリフレッシュ試行フラグ（PDS から token_expired を受け取った場合）
        _token_refreshed = False

        try:
            # 2. 画像アップロード（PDS の uploadBlob エンドポイントを使用）
            embed = None
            if image_path:
                blob_data = await self.upload_image_oauth(
                    image_path,
                    access_token,
                    pds_url=pds_url,
                    resize_small_images=resize_small_images,
                )
                if blob_data:
                    blob, width, height = blob_data
                    embed = {
                        "$type": "app.bsky.embed.images",
                        "images": [{
                            "image": blob,
                            "alt": "Posted from StreamNotify v4 (OAuth)",
                            "aspectRatio": {"width": width, "height": height}
                        }]
                    }
                else:
                    logger.error("❌ OAuth Mode: Image upload failed. Aborting OAuth attempt.")
                    return False

            # 3. レコード構築
            facets = self._build_facets(text)
            created_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

            post_record: Dict[str, Any] = {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": created_at,
            }
            if facets:
                post_record["facets"] = facets
            if embed:
                post_record["embed"] = embed

            # 4. DID の確認
            if not self.did:
                status = await self.get_account_status()
                if status and status.get("did"):
                    self.did = status["did"]
                else:
                    logger.error("❌ OAuth Mode: Missing DID.")
                    return False

            # 5. createRecord（PDS URL を使用 / DPoP-Nonce チャレンジ自動リトライ）
            create_url = f"{pds_xrpc}/com.atproto.repo.createRecord"
            logger.info(f"[OAuth] createRecord → url={create_url} repo(DID)={self.did}")
            request_body = {
                "repo": self.did,
                "collection": "app.bsky.feed.post",
                "record": post_record,
            }

            for attempt in range(3):  # 0: 初回, 1: nonce リトライ, 2: token refresh リトライ
                nonce = getattr(self, "_dpop_nonce", None)
                dpop_headers = await self._get_server_sign("POST", create_url, access_token, nonce=nonce)
                if not dpop_headers:
                    logger.error("❌ OAuth Mode: Failed to get DPoP signature.")
                    return False

                req_headers = {
                    "Authorization": f"DPoP {access_token}",
                    "Content-Type": "application/json",
                }
                req_headers.update(dpop_headers)

                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        create_url,
                        json=request_body,
                        headers=req_headers,
                        timeout=15.0,
                    )

                # エラーレスポンスを常にログ出力（診断用）
                if not resp.is_success:
                    new_nonce = resp.headers.get("DPoP-Nonce")
                    resp_body = resp.text[:500]
                    logger.warning(
                        f"⚠️ OAuth createRecord {resp.status_code}: {resp_body} "
                        f"| DPoP-Nonce: {new_nonce or '(none)'} "
                        f"| attempt={attempt}"
                    )

                    # トークン期限切れ・無効（401）→ 先に force_refresh してリトライ（nonce より優先）
                    body_lower = resp_body.lower()
                    token_invalid = (
                        "expired" in body_lower
                        or "invalid_token" in body_lower
                        or ("exp" in body_lower and "claim" in body_lower)
                        or "timestamp check failed" in body_lower
                    )
                    if resp.status_code == 401 and not _token_refreshed and token_invalid:
                        logger.info("[OAuth] Token expired or invalid, requesting force refresh from server...")
                        new_token_data = await self._get_server_token(force_refresh=True)
                        if not new_token_data or not new_token_data.get("access_token"):
                            logger.error("[OAuth] force_refresh returned no token; aborting OAuth post.")
                            return False
                        # センターサーバー（v4-websub-server）が返す場合: リフレッシュ成否を明示
                        if (
                            new_token_data.get("refresh_attempted") is True
                            and new_token_data.get("refresh_succeeded") is False
                        ):
                            logger.error(
                                "[OAuth] Center server refresh failed (refresh_succeeded=false). "
                                "Check center logs for [token refresh] or re-link Bluesky."
                            )
                            return False
                        new_tok = new_token_data["access_token"]
                        if new_tok != access_token:
                            access_token = new_tok
                            _token_refreshed = True
                            self._dpop_nonce = None
                            continue
                        # トークン文字列が同じ＝サーバーが「失敗時は保存済みを返す」挙動の可能性が高い
                        if new_token_data.get("refresh_succeeded") is True:
                            logger.warning(
                                "[OAuth] force_refresh reported success but access_token unchanged; "
                                "retrying createRecord with cleared DPoP nonce."
                            )
                            _token_refreshed = True
                            self._dpop_nonce = None
                            continue
                        logger.error(
                            "[OAuth] force_refresh returned the same token string and no refresh_succeeded flag; "
                            "assuming refresh did not update token. Re-link Bluesky or update center server."
                        )
                        return False

                    # AT Protocol: DPoP-Nonce チャレンジ（400 or 401）→ nonce を更新してリトライ
                    if resp.status_code in (400, 401) and new_nonce:
                        old_nonce = getattr(self, "_dpop_nonce", None)
                        self._dpop_nonce = new_nonce
                        if old_nonce != new_nonce:
                            continue

                    resp.raise_for_status()

                resp.raise_for_status()
                data = resp.json()
                logger.info(f"✅ [OAuth] Successfully posted to Bluesky: {data.get('uri')}")
                return True

            return False

        except Exception as e:
            logger.warning(f"⚠️ OAuth Mode failed with exception: {e}. Falling back...")
            return False

    def _prepare_image_payload(
        self,
        image_path: str,
        resize_small_images: bool = True,
    ) -> Optional[Tuple[bytes, str, int, int]]:
        """
        画像アップロード用のバイナリ/メタ情報を準備する。
        - resize_small_images=True: v4既存の resize_image() を使用（JPEG化）
        - resize_small_images=False: 元画像バイナリをそのまま使用
        """
        try:
            if resize_small_images:
                processed_data = resize_image(image_path)
                if not processed_data:
                    return None
                from PIL import Image as PILImage
                img = PILImage.open(io.BytesIO(processed_data))
                width, height = img.size
                return processed_data, "image/jpeg", width, height

            src = Path(image_path)
            if not src.exists():
                return None
            data = src.read_bytes()

            mime_type = "image/jpeg"
            width, height = 1000, 1000
            try:
                from PIL import Image as PILImage
                img = PILImage.open(io.BytesIO(data))
                width, height = img.size
                fmt = (img.format or "").upper()
                if fmt == "PNG":
                    mime_type = "image/png"
                elif fmt == "WEBP":
                    mime_type = "image/webp"
                elif fmt == "GIF":
                    mime_type = "image/gif"
                else:
                    mime_type = "image/jpeg"
            except Exception:
                # PIL で判定できない場合は拡張子ベースで推定
                suffix = src.suffix.lower()
                if suffix == ".png":
                    mime_type = "image/png"
                elif suffix == ".webp":
                    mime_type = "image/webp"
                elif suffix == ".gif":
                    mime_type = "image/gif"
                else:
                    mime_type = "image/jpeg"

            return data, mime_type, width, height
        except Exception as e:
            logger.error(f"❌ Image payload preparation failed: {e}")
            return None

    async def upload_image_oauth(
        self,
        image_path: str,
        access_token: str,
        pds_url: str = "https://bsky.social",
        resize_small_images: bool = True,
    ) -> Optional[Tuple[Dict[str, Any], int, int]]:
        """Resize and upload image using OAuth token (DPoP). PDS URL を指定して正しいエンドポイントに送信する。"""
        try:
            prepared = self._prepare_image_payload(image_path, resize_small_images=resize_small_images)
            if not prepared:
                return None
            processed_data, mime_type, width, height = prepared

            logger.info(
                "OAuth image upload mode: %s",
                "optimized" if resize_small_images else "original",
            )

            upload_url = f"{pds_url.rstrip('/')}/xrpc/com.atproto.repo.uploadBlob"
            nonce = getattr(self, "_dpop_nonce", None)
            dpop_headers = await self._get_server_sign("POST", upload_url, access_token, nonce=nonce)
            if not dpop_headers:
                return None

            req_headers = {
                "Authorization": f"DPoP {access_token}",
                "Content-Type": mime_type,
            }
            req_headers.update(dpop_headers)

            async with httpx.AsyncClient() as client:
                resp = await client.post(upload_url, content=processed_data, headers=req_headers, timeout=20.0)
                if resp.status_code in (400, 401):
                    new_nonce = resp.headers.get("DPoP-Nonce")
                    if new_nonce:
                        self._dpop_nonce = new_nonce
                        logger.info("[OAuth] DPoP-Nonce for uploadBlob, retrying...")
                        dpop_h2 = await self._get_server_sign("POST", upload_url, access_token, nonce=new_nonce)
                        if dpop_h2:
                            req_headers.update(dpop_h2)
                            resp = await client.post(upload_url, content=processed_data, headers=req_headers, timeout=20.0)
                resp.raise_for_status()
                blob = resp.json().get("blob")
                return blob, width, height
        except Exception as e:
            logger.error(f"❌ [OAuth] Image upload failed: {e}")
            return None

    async def post(
        self,
        text: str,
        image_path: Optional[str] = None,
        dry_run: Optional[bool] = None,
        resize_small_images: bool = True,
    ) -> bool:
        """
        Post a message to Bluesky.
        Tries OAuth Priority Mode first, then falls back to Password Auth.
        """
        is_dry_run = dry_run if dry_run is not None else self.dry_run

        if is_dry_run:
            logger.info(f"[DRY RUN] Would post: {text}" + (f" with image: {image_path}" if image_path else ""))
            return True

        # 1. OAuth（センター経由 DPoP）— フラグ ON かつ websub センター利用時のみ
        if settings.bluesky_center_oauth_available():
            if await self.post_via_oauth(text, image_path, resize_small_images=resize_small_images):
                return True
            logger.info("🔄 Switching to Fallback Mode (Password Auth)...")
        else:
            logger.debug(
                "Bluesky post: OAuth/center path skipped (frozen/disabled or poll mode); using app password."
            )

        # 2. Fallback Mode (Legacy) with retry
        if not self.access_token:
            if not await self.login():
                return False

        last_error: Optional[Exception] = None
        for attempt in range(1, BLUESKY_POST_RETRY_ATTEMPTS + 1):
            try:
                embed = None
                if image_path:
                    blob_data = await self.upload_image(
                        image_path,
                        resize_small_images=resize_small_images,
                    )
                    if blob_data:
                        blob, width, height = blob_data
                        embed = {
                            "$type": "app.bsky.embed.images",
                            "images": [{
                                "image": blob,
                                "alt": "Posted from StreamNotify v4",
                                "aspectRatio": {"width": width, "height": height}
                            }]
                        }

                facets = self._build_facets(text)
                created_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
                post_record = {
                    "$type": "app.bsky.feed.post",
                    "text": text,
                    "createdAt": created_at,
                }
                if facets:
                    post_record["facets"] = facets
                if embed:
                    post_record["embed"] = embed

                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{self.base_url}/com.atproto.repo.createRecord",
                        json={
                            "repo": self.did,
                            "collection": "app.bsky.feed.post",
                            "record": post_record
                        },
                        headers={"Authorization": f"Bearer {self.access_token}"},
                        timeout=15.0
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    logger.info(f"✅ [Fallback] Successfully posted to Bluesky: {data.get('uri')}")
                    return True
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e
                if attempt < BLUESKY_POST_RETRY_ATTEMPTS:
                    logger.warning(f"[Fallback] Attempt {attempt} failed ({e}), retrying in {BLUESKY_POST_RETRY_DELAY_SEC}s...")
                    await asyncio.sleep(BLUESKY_POST_RETRY_DELAY_SEC)
                else:
                    logger.error(f"❌ [Fallback] Failed after {BLUESKY_POST_RETRY_ATTEMPTS} attempts: {e}")
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500 and attempt < BLUESKY_POST_RETRY_ATTEMPTS:
                    last_error = e
                    logger.warning(f"[Fallback] Server error {e.response.status_code}, retrying in {BLUESKY_POST_RETRY_DELAY_SEC}s...")
                    await asyncio.sleep(BLUESKY_POST_RETRY_DELAY_SEC)
                else:
                    logger.error(f"❌ [Fallback] Failed to post to Bluesky: {e}")
                    return False
            except Exception as e:
                logger.error(f"❌ [Fallback] Failed to post to Bluesky: {e}")
                return False

        if last_error:
            logger.error(f"❌ [Fallback] Failed to post to Bluesky after retries: {last_error}")
        return False

    async def upload_image(
        self,
        image_path: str,
        resize_small_images: bool = True,
    ) -> Optional[Tuple[Dict[str, Any], int, int]]:
        """Resize and upload an image to Bluesky (Legacy Password Auth)."""
        try:
            prepared = self._prepare_image_payload(image_path, resize_small_images=resize_small_images)
            if not prepared:
                return None
            processed_data, mime_type, width, height = prepared

            logger.info(
                "Fallback image upload mode: %s",
                "optimized" if resize_small_images else "original",
            )

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}/com.atproto.repo.uploadBlob",
                    content=processed_data,
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": mime_type
                    },
                    timeout=20.0
                )
                resp.raise_for_status()
                blob = resp.json().get("blob")
                return blob, width, height
        except Exception as e:
            logger.error(f"❌ Image upload failed: {e}")
            return None
