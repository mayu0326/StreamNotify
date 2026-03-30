import asyncio
import aiohttp
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from .config import settings
from .schemas import VideoListResponse, TwitchBroadcastListResponse

logger = logging.getLogger("v4.websub_client")

# 購読リースがこの秒数未満なら起動時に再登録する（1日）
LEASE_RENEW_THRESHOLD_SECONDS = 86400
# WebSub 登録失敗時のリトライ
REGISTER_RETRY_ATTEMPTS = 3
REGISTER_RETRY_DELAY_SEC = 2


class WebSubClient:
    def __init__(self):
        # 末尾スラッシュ付き URL だと `/videos` 結合で `//videos` になりサーバーが 404 になるため正規化する
        raw = (settings.center_server_url or "").strip()
        self.base_url = raw.rstrip("/") if raw else ""
        self.api_key = settings.websub_client_api_key
        self.client_id = settings.websub_client_id
        logger.info(f"Initialized WebSubClient with base_url: {self.base_url}, client_id: {self.client_id}")

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Client-API-Key": self.api_key
        }
        return headers

    async def get_client_health(self, channel_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        GET /clienthealth で購読状態（lease_expires_at / lease_remaining_seconds）を取得。
        サーバーが clienthealth を実装していない場合は None を返す。
        """
        if not self.api_key or not self.base_url:
            return None
        url = f"{self.base_url}/clienthealth"
        params: Dict[str, str] = {"client_id": self.client_id}
        if channel_id:
            params["channel_id"] = channel_id
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=self._get_headers()) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 404:
                        return None
                    logger.warning(f"Clienthealth returned {resp.status}")
                    return None
        except Exception as e:
            logger.debug(f"Clienthealth not available: {e}")
            return None

    async def ensure_lease_and_register_if_needed(self, channel_id: str) -> bool:
        """
        起動時用: clienthealth で購読を確認し、期限切れや残り少なければ POST /register で再登録する。
        clienthealth が使えない場合は何もしない（True を返す）。
        """
        health = await self.get_client_health(channel_id=channel_id)
        if not health or health.get("status") != "ok":
            return True  # サーバーが clienthealth 未実装など
        subs: List[Dict[str, Any]] = health.get("subscriptions") or []
        for sub in subs:
            if sub.get("channel_id") != channel_id:
                continue
            remaining = sub.get("lease_remaining_seconds")
            if remaining is None:
                # サーバーが lease を返していない（古い）場合は再登録して更新させる
                logger.info(f"WebSub lease info missing for {channel_id}, re-registering.")
                return await self.register_client(channel_id)
            if remaining < LEASE_RENEW_THRESHOLD_SECONDS:
                logger.info(
                    f"WebSub lease for {channel_id} expires in {remaining}s (< {LEASE_RENEW_THRESHOLD_SECONDS}), re-registering."
                )
                return await self.register_client(channel_id)
            logger.info(f"WebSub subscription for {channel_id} OK (lease_remaining={remaining}s)")
            return True
        # 購読レコードが無い（未登録）
        logger.info(f"No WebSub subscription for {channel_id}, registering.")
        return await self.register_client(channel_id)

    async def register_client(self, channel_id: str, youtube_api_key: Optional[str] = None) -> bool:
        """
        Register this client to Center Server for a specific channel.
        POST /register. Retries on connection error or 5xx (up to REGISTER_RETRY_ATTEMPTS).
        """
        if not self.api_key or not self.base_url:
            logger.warning("Missing API Key or Center Server URL. Skipping registration.")
            return False

        url = f"{self.base_url}/register"
        payload = {
            "client_id": self.client_id,
            "channel_id": channel_id,
            "callback_url": f"{(settings.websub_callback_base_url or '').strip().rstrip('/')}/webhook",
            "youtube_api_key": youtube_api_key
        }

        last_error: Optional[Exception] = None
        for attempt in range(1, REGISTER_RETRY_ATTEMPTS + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, headers=self._get_headers()) as resp:
                        if resp.status == 200:
                            logger.info(f"Successfully registered client {self.client_id} for channel {channel_id}")
                            return True
                        text = await resp.text()
                        if 500 <= resp.status < 600 and attempt < REGISTER_RETRY_ATTEMPTS:
                            logger.warning(
                                f"WebSub register attempt {attempt} got {resp.status}, retrying in {REGISTER_RETRY_DELAY_SEC}s..."
                            )
                            await asyncio.sleep(REGISTER_RETRY_DELAY_SEC)
                            last_error = Exception(f"HTTP {resp.status}: {text[:200]}")
                            continue
                        logger.error(f"Failed to register client: {resp.status} - {text}")
                        return False
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                last_error = e
                if attempt < REGISTER_RETRY_ATTEMPTS:
                    logger.warning(
                        f"Connection error during registration (attempt {attempt}): {e}. Retrying in {REGISTER_RETRY_DELAY_SEC}s..."
                    )
                    await asyncio.sleep(REGISTER_RETRY_DELAY_SEC)
                else:
                    logger.error(f"Connection error during registration after {REGISTER_RETRY_ATTEMPTS} attempts: {e}")
                    return False
        if last_error:
            logger.error(f"WebSub register failed after retries: {last_error}")
        return False

    @staticmethod
    def _http_detail_from_body(text: str):
        try:
            return json.loads(text).get("detail")
        except Exception:
            return None

    async def _fetch_youtube_videos_legacy(
        self, channel_id: str, since: Optional[datetime] = None
    ) -> VideoListResponse:
        """GET /videos（非推奨）— センターが /client/youtube/videos 未配備のときのフォールバック。"""
        url = f"{self.base_url}/videos"
        params: Dict[str, Any] = {
            "channel_id": channel_id,
            "client_id": self.client_id,
            "limit": 50,
        }
        if since:
            params["since"] = since.isoformat()
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=self._get_headers()) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.warning(
                        "Using deprecated GET /videos; upgrade center for GET /client/youtube/videos"
                    )
                    return VideoListResponse.model_validate(data)
                text = await resp.text()
                logger.error(
                    "Legacy GET /videos failed: %s body=%s", resp.status, text[:300]
                )
                raise Exception(f"Center Server Error: {resp.status}")

    async def _fetch_twitch_broadcasts_legacy(
        self, broadcaster_user_id: str, since: Optional[datetime] = None
    ) -> TwitchBroadcastListResponse:
        """GET /twitch/broadcasts（非推奨）— センターが /client/twitch/broadcasts 未配備のときのフォールバック。"""
        url = f"{self.base_url}/twitch/broadcasts"
        params: Dict[str, Any] = {
            "broadcaster_user_id": broadcaster_user_id,
            "client_id": self.client_id,
            "limit": 50,
        }
        if since:
            params["since"] = since.isoformat()
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=self._get_headers()) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.warning(
                        "Using deprecated GET /twitch/broadcasts; upgrade center for GET /client/twitch/broadcasts"
                    )
                    return TwitchBroadcastListResponse.model_validate(data)
                text = await resp.text()
                logger.error(
                    "Legacy GET /twitch/broadcasts failed: %s body=%s",
                    resp.status,
                    text[:300],
                )
                raise Exception(f"Center Server Error: {resp.status}")

    async def fetch_youtube_videos(
        self, channel_id: str, since: Optional[datetime] = None
    ) -> VideoListResponse:
        """GET /client/youtube/videos — YouTube 専用プル同期。"""
        url = f"{self.base_url}/client/youtube/videos"
        params: Dict[str, Any] = {
            "channel_id": channel_id,
            "client_id": self.client_id,
            "limit": 50,
        }
        if since:
            params["since"] = since.isoformat()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=self._get_headers()) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return VideoListResponse.model_validate(data)
                    if resp.status == 404:
                        text = await resp.text()
                        detail = self._http_detail_from_body(text)
                        # ルート未登録など Starlette 既定は "Not Found" — 空扱いにすると同期が黙って止まる
                        if detail == "channel not found":
                            logger.info("Center has no channel DB for %s", channel_id)
                            return VideoListResponse(
                                channel_id=channel_id, count=0, videos=[]
                            )
                        logger.warning(
                            "GET /client/youtube/videos returned 404 (detail=%r); trying legacy /videos",
                            detail,
                        )
                        return await self._fetch_youtube_videos_legacy(channel_id, since=since)
                    logger.error("Error fetching YouTube videos: %s", resp.status)
                    raise Exception(f"Center Server Error: {resp.status}")
        except Exception as e:
            logger.error("Connection error fetching YouTube videos: %s", e)
            raise e

    async def fetch_twitch_broadcasts(
        self, broadcaster_user_id: str, since: Optional[datetime] = None
    ) -> TwitchBroadcastListResponse:
        """GET /client/twitch/broadcasts — Twitch 専用プル同期。"""
        url = f"{self.base_url}/client/twitch/broadcasts"
        params: Dict[str, Any] = {
            "broadcaster_user_id": broadcaster_user_id,
            "client_id": self.client_id,
            "limit": 50,
        }
        if since:
            params["since"] = since.isoformat()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=self._get_headers()) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return TwitchBroadcastListResponse.model_validate(data)
                    if resp.status == 404:
                        text = await resp.text()
                        detail = self._http_detail_from_body(text)
                        if detail == "broadcaster not found":
                            logger.info(
                                "Center has no Twitch DB for broadcaster %s",
                                broadcaster_user_id,
                            )
                            return TwitchBroadcastListResponse(
                                broadcaster_user_id=broadcaster_user_id,
                                count=0,
                                broadcasts=[],
                            )
                        logger.warning(
                            "GET /client/twitch/broadcasts returned 404 (detail=%r); trying legacy /twitch/broadcasts",
                            detail,
                        )
                        return await self._fetch_twitch_broadcasts_legacy(
                            broadcaster_user_id, since=since
                        )
                    logger.error("Error fetching Twitch broadcasts: %s", resp.status)
                    raise Exception(f"Center Server Error: {resp.status}")
        except Exception as e:
            logger.error("Connection error fetching Twitch broadcasts: %s", e)
            raise e

    async def fetch_videos(self, channel_id: str, since: Optional[datetime] = None) -> VideoListResponse:
        """後方互換: `fetch_youtube_videos` と同じ。"""
        return await self.fetch_youtube_videos(channel_id, since=since)
