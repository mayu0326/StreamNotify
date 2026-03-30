"""
OAuth クライアント側実装 (v4)

ユーザーのローカル PC で動作し、ブラウザを開いて認証フローを開始。
センターサーバー経由で取得した認証コードを捕捉し、完了処理を行う。
"""

import asyncio
import logging
import socket
import webbrowser
import time
from threading import Thread, Event
from typing import Optional, Dict, Any
import requests

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn

from .config import settings

logger = logging.getLogger("v4.core.auth")


def _find_available_port(preferred: int, max_attempts: int = 10) -> int:
    """指定ポートから空きポートを探す。occupied なら +1 ずつ試行。"""
    for offset in range(max_attempts):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port found in range {preferred}–{preferred + max_attempts - 1}")


class OAuthFlowManager:
    """OAuth 認証フロー管理クラス"""

    _received_code: Optional[str] = None
    _auth_error: Optional[str] = None
    _auth_complete = False
    _server_started = False

    @classmethod
    def receive_callback(
        cls,
        service: str,
        code: str = None,
        status: str = None,
        handle: str = None,
        error: str = None,
        error_description: str = None,
    ):
        """外部（WebhookServerなど）から認証結果を受け取る"""
        logger.info(
            f"[OAuth] Callback received for {service}: code={code}, status={status}, handle={handle}, "
            f"error={error}, error_description={error_description}"
        )

        if error or status == "error":
            parts = [error or "oauth_error"]
            if error_description:
                try:
                    from urllib.parse import unquote

                    parts.append(unquote(error_description))
                except Exception:
                    parts.append(error_description)
            cls._auth_error = ": ".join(parts)
            cls._received_code = None
            cls._auth_complete = True
            logger.error(f"[OAuth] {service} OAuth failed: {cls._auth_error}")
            return

        cls._auth_error = None
        if service == "bsky" and status == "success":
            if handle:
                cls._received_code = handle
            else:
                cls._received_code = "success"
        elif code:
            cls._received_code = code

        if cls._received_code:
            cls._auth_complete = True
            logger.info(f"[OAuth] {service} authentication complete signal received")

    @classmethod
    def start_oauth_flow(
        cls,
        service_name: str,
        local_port: int = 8000,
        timeout: int = 300,
        handle: Optional[str] = None
    ) -> Optional[str]:
        """
        OAuth フローを開始し、認証コードを待機する。
        ユーザーの PC 上で一時的な Web サーバーを起動し、リダイレクトを受け取る。
        ポート競合を自動回避し、uvicorn.Server を使ったシャットダウンをサポートする。
        """
        cls._received_code = None
        cls._auth_error = None
        cls._auth_complete = False
        cls._server_started = False

        sn = (service_name or "").lower()
        if sn in ("bsky", "bluesky"):
            if not settings.bluesky_center_oauth_available():
                logger.error(
                    "[OAuth] Bluesky のセンター OAuth は無効です（凍結中）。"
                    " アプリパスワードで Bluesky 投稿を行ってください。"
                )
                return None
        elif sn == "twitch" and not settings.uses_center_server():
            logger.error(
                "[OAuth] youtube_feed_mode=poll（または WebSub フォールバック）のため"
                " センター経由の Twitch 連携は開始できません。取得モードを websub にしてください。"
            )
            return None

        # ポート競合を自動回避
        try:
            actual_port = _find_available_port(local_port)
        except RuntimeError as e:
            logger.error(f"[OAuth] {e}")
            return None

        if actual_port != local_port:
            logger.warning(f"[OAuth] Port {local_port} busy, using {actual_port} instead")

        # ローカルサーバーの定義
        app = FastAPI()
        server_ready_event = Event()
        server_instance: Optional[uvicorn.Server] = None

        @app.on_event("startup")
        async def _on_startup():
            cls._server_started = True
            server_ready_event.set()

        @app.get("/auth/callback")
        async def callback_endpoint(request: Request):
            params = request.query_params
            service = params.get("service")
            code = params.get("code")
            status = params.get("status")
            handle_param = params.get("handle")
            err = params.get("error")
            err_desc = params.get("error_description")

            cls.receive_callback(service, code, status, handle_param, err, err_desc)

            # 認証完了後にサーバーをシャットダウン
            if server_instance:
                server_instance.should_exit = True

            if err or status == "error":
                import html as html_module
                from urllib.parse import unquote

                raw_msg = unquote(err_desc or err or "OAuth error")
                msg = html_module.escape(raw_msg)
                return HTMLResponse(content=f"""
            <html>
                <body style='font-family: sans-serif; text-align: center; padding-top: 50px;'>
                    <h1 style='color: #c00;'>Authentication failed</h1>
                    <p>{msg}</p>
                    <p>Close this window and try linking again from the app (do not double-click Authorize).</p>
                    <script>setTimeout(function(){{window.close();}}, 5000);</script>
                </body>
            </html>
            """)
            return HTMLResponse(content="""
            <html>
                <body style='font-family: sans-serif; text-align: center; padding-top: 50px;'>
                    <h1 style='color: green;'>Authentication Successful!</h1>
                    <p>You can close this window and return to the application.</p>
                    <script>setTimeout(function(){window.close();}, 3000);</script>
                </body>
            </html>
            """)

        def _run_server():
            nonlocal server_instance
            config = uvicorn.Config(app, host="127.0.0.1", port=actual_port, log_level="warning")
            server_instance = uvicorn.Server(config)
            try:
                server_instance.run()
            except Exception as e:
                logger.error(f"[OAuth] Local callback server error: {e}")
                server_ready_event.set()  # ブロック解除

        server_thread = Thread(target=_run_server, daemon=True)
        server_thread.start()

        # サーバー起動完了を最大5秒待機
        if not server_ready_event.wait(timeout=5):
            logger.error("[OAuth] Local callback server failed to start within 5 seconds")
            return None

        if not cls._server_started:
            logger.error("[OAuth] Local callback server startup event was not fired")
            return None

        logger.info(f"[OAuth] Local callback server ready on port {actual_port}")

        # ブラウザでセンターサーバーのログイン URL を開く
        from urllib.parse import quote, urlencode

        base_url = settings.center_server_url.rstrip("/")
        if service_name.lower() in ("bsky", "bluesky"):
            if not handle:
                logger.error("Bluesky login requires a handle")
                print("❌ Error: Bluesky requires a handle parameter.")
                return None
            login_url = (
                f"{base_url}/auth/bsky/login"
                f"?handle={handle}&client_id={settings.websub_client_id}&port={actual_port}"
            )
        else:
            # redirect_uri に service パラメータを含め、URL エンコードして送る
            # 例: http://localhost:8001/auth/callback?service=twitch → URL エンコード
            redirect_uri = f"http://localhost:{actual_port}/auth/callback?service={service_name}"
            login_url = (
                f"{base_url}/auth/{service_name}/login"
                f"?redirect_uri={quote(redirect_uri, safe='')}"
            )

        logger.info(f"[OAuth] Opening browser: {login_url}")
        try:
            webbrowser.open(login_url)
        except Exception as e:
            logger.error(f"[OAuth] Failed to open browser: {e}")
            print(f"⚠️  Failed to open browser. Please open this URL manually:\n{login_url}")

        # コールバックを受け取るまで待機
        start_time = time.time()
        while not cls._auth_complete:
            if time.time() - start_time > timeout:
                logger.error("[OAuth] Timeout waiting for auth callback")
                if server_instance:
                    server_instance.should_exit = True
                break
            time.sleep(0.5)

        if cls._auth_error:
            logger.error("[OAuth] %s", cls._auth_error)
            if server_instance:
                server_instance.should_exit = True
            return None

        return cls._received_code

    @classmethod
    def complete_twitch_flow(cls, code: str) -> bool:
        """Twitch の最終処理: コンテンツサーバー等へのトークン保存依頼"""
        # クライアント側で直接トークン交換する場合 (設計書により異なるが、一旦スタブ)
        logger.info(f"Twitch OAuth flow completed locally. Code: {code[:10]}...")
        # 実際にはここで OAuth 完了の API をセンターサーバーに叩くか、ローカルでトークン交換を行う
        return True

    @classmethod
    def complete_bsky_flow(cls, code: str) -> bool:
        """Bluesky の最終処理"""
        logger.info("Bluesky OAuth flow completed.")
        return True
