from fastapi import FastAPI, HTTPException, Request, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime
import logging
import html as html_module
import urllib.parse
import hmac
import hashlib

from .config import settings
from .schemas import WebhookPayload
from .database import get_db, init_db, VideoModel

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("v4.webhook")

app = FastAPI(title="StreamNotify Client v4 Webhook Server")

# CORS: ブラウザ等からの API 呼び出しを許可（必要に応じて origins を制限可能）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    logger.info("Starting up Client Webhook Server...")
    init_db()

def save_video_update(payload: WebhookPayload, db: Session):
    """
    受信した動画情報をDBに保存または更新
    """
    video_data = payload.data

    # data が dict の場合（WebhookPayload.data: Any に変更したため）
    # Video モデルに変換する（Video.model_validate(video_data) は pydantic v2）
    # ここでは既存ロジックに合わせて簡易的に扱う
    is_dict = isinstance(video_data, dict)

    vid = video_data.get("video_id") if is_dict else video_data.video_id

    if not vid:
        logger.warning("Received video update without video_id")
        return

    existing = db.query(VideoModel).filter(VideoModel.video_id == vid).first()

    # 辞書からモデルダンプ相当を取得
    dump_data = video_data if is_dict else video_data.model_dump(exclude={"id", "created_at"})
    # VideoModel のフィールドのみ抽出
    valid_fields = {k: v for k, v in dump_data.items() if hasattr(VideoModel, k) and k != "id"}

    if existing:
        # Update
        status = video_data.get("video_status") if is_dict else video_data.video_status
        logger.info(f"Updating video {vid}: status={status}")

        for key, value in valid_fields.items():
            setattr(existing, key, value)

        updated_since = video_data.get("is_updated_since") if is_dict else video_data.is_updated_since
        existing.is_updated_since = updated_since or datetime.utcnow()
    else:
        # Insert
        status = video_data.get("video_status") if is_dict else video_data.video_status
        logger.info(f"New video received {vid}: status={status}")
        new_video = VideoModel(**valid_fields)
        db.add(new_video)

    db.commit()

    db.commit()

async def verify_signature(request: Request):
    """
    受信したWebhookの署名 (HMAC-SHA256) を検証するDependency
    """
    signature = request.headers.get("X-Hub-Signature")
    if not signature:
        logger.warning("Missing X-Hub-Signature header")
        raise HTTPException(status_code=403, detail="Missing signature")

    if settings.websub_client_api_key == "":
        # 開発中 or キー未設定時は検証スキップ (またはエラーにするポリシー次第)
        # 本番運用を想定してエラーログを出すが、ローカルテスト用にスキップも考慮
        logger.warning("WEBSUB_CLIENT_API_KEY is not configured. Signature verification skipped.")
        return

    try:
        # sha256=... 形式からハッシュ部分を抽出
        if not signature.startswith("sha256="):
            raise HTTPException(status_code=403, detail="Invalid signature format")

        expected_prefix_len = len("sha256=")
        received_digest = signature[expected_prefix_len:]

        body = await request.body()
        secret = settings.websub_client_api_key.encode('utf-8')

        computed_digest = hmac.new(
            secret,
            body,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed_digest, received_digest):
            logger.warning(f"Signature mismatch! Computed: {computed_digest}, Received: {received_digest}")
            raise HTTPException(status_code=403, detail="Invalid signature")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during signature verification: {e}")
        raise HTTPException(status_code=403, detail="Signature verification failed")

@app.post("/webhook", dependencies=[Depends(verify_signature)])

async def webhook_handler(
    payload: WebhookPayload,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Center Server からの通知を受信
    TODO: 将来的にはヘッダー署名検証 (HMAC) を実装
    """
    # 安全に ID を取得してログ出力
    vid = getattr(payload.data, "video_id", None)
    if not vid and isinstance(payload.data, dict):
        vid = payload.data.get("video_id") or payload.data.get("id")

    logger.info(f"Received webhook: {payload.type} for video {vid}")

    # 処理をバックグラウンドに回す (Center Serverへのレスポンスを早くするため)
    # イベントタイプに応じた処理
    if payload.type in ("video_update", "youtube_video", "new_video"):
        # YouTube / Generic Video Update
        background_tasks.add_task(save_video_update, payload, db)

    elif payload.type in ("twitch_event", "twitch_notification"):
        # Twitch EventSub
        from v4.domain.notifications.twitch.event_handler import handle_twitch_event
        # WebhookPayload.data をそのまま渡す (dict expected)
        # handle_twitch_event は内部で DB セッションを独自に作成しているため、
        # ここでは payload の中身だけ渡す形にするか、
        # あるいは handle_twitch_event を改修して db セッションを受け取るようにするのが効率的だが
        # 現状の event_handler.py 実装に合わせて payload 全体を渡す（非同期関数として呼び出す）。

        # handle_twitch_event は async def なので await する必要があるが
        # ここは background_tasks なので、async 関数をラップするか、run_in_executor する必要がある。
        # FastAPI の BackgroundTasks は async 関数も受け付ける。

        # payload.data (dict) をそのまま渡す
        event_data = payload.data
        if isinstance(event_data, dict):
            background_tasks.add_task(handle_twitch_event, event_data)
        else:
            logger.warning(f"Twitch event payload data is not a dict: {type(event_data)}")

    else:
        logger.warning(f"Unknown webhook type: {payload.type}")

    return {"status": "ok", "received_at": datetime.utcnow()}

@app.get("/health")
def health_check():
    return {"status": "ok", "mode": settings.youtube_feed_mode}

@app.get("/auth/callback")
async def auth_callback(
    service: str,
    code: str = None,
    status: str = None,
    handle: str = None,
    error: str = None,
    error_description: str = None,
):
    """
    OAuth プロバイダーからのリダイレクトを受信 (中心サーバーからのリダイレクト用)
    """
    from .auth_client import OAuthFlowManager
    from fastapi.responses import HTMLResponse

    logger.info(
        f"Received OAuth callback for {service}: code={code}, status={status}, handle={handle}, "
        f"error={error}, error_description={error_description}"
    )

    OAuthFlowManager.receive_callback(service, code, status, handle, error, error_description)

    if error or status == "error":
        raw = error_description or error or "OAuth error"
        try:
            msg = html_module.escape(urllib.parse.unquote(raw))
        except Exception:
            msg = html_module.escape(raw)
        return HTMLResponse(
            f"""
        <html>
            <head><title>認証エラー</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                <h1 style="color:#c00;">連携に失敗しました</h1>
                <p>{msg}</p>
                <p>アプリに戻り、<strong>承認は一度だけ</strong>押して再度お試しください。</p>
                <script>setTimeout(function(){{window.close();}}, 5000);</script>
            </body>
        </html>
        """
        )

    return HTMLResponse(f"""
        <html>
            <head>
                <title>認証成功</title>
                <style>
                    body {{ font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #f0f2f5; }}
                    .container {{ text-align: center; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
                    h1 {{ color: #1a73e8; }}
                    .service {{ font-weight: bold; color: #333; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>✅ 認証成功！</h1>
                    <p><span class="service">{service.upper()}</span> の連携が完了しました。</p>
                    <p>アプリに戻って操作を続けてください。</p>
                    <script>setTimeout(window.close, 3000);</script>
                </div>
            </body>
        </html>
    """)
