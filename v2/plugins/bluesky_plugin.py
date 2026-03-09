# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - Bluesky 画像添付拡張プラグイン

Bluesky への画像添付機能を提供する拡張プラグイン。
bluesky_core.py のコア機能（投稿・Facet・認証・ドライラン）とは独立。
"""

import logging
import sys
import re
from pathlib import Path
import os
from typing import Optional, Tuple, List, Dict, Any

# PIL (Pillow) をインポート
from PIL import Image

# 親ディレクトリをパスに追加（image_manager.pyをインポートするため）
sys.path.insert(0, str(Path(__file__).parent.parent))
from image_manager import get_image_manager
from bluesky_core import BlueskyMinimalPoster
import image_processor

logger = logging.getLogger("AppLogger")
post_logger = logging.getLogger("PostLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


# settings.env から値を取得する簡易関数
def get_env_setting(key: str, default: str | None = None) -> str | None:
    env_path = Path(__file__).parent.parent / "settings.env"
    if not env_path.exists():
        # カレントディレクトリも探す（開発環境用）
        env_path = Path("settings.env")

    if not env_path.exists():
        return default
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == key:
                        return v.strip()
    except Exception as e:
        logger.warning(f"⚠️ 設定ファイル読み込み失敗: {e}")
    return default


# ============ 画像リサイズ設定（環境変数から読み込み） ============
def _load_image_resize_config():
    """環境変数から画像リサイズ設定を読み込む

    Returns:
        dict: 画像リサイズ設定
    """
    try:
        config = {
            "target_width": int(get_env_setting("IMAGE_RESIZE_TARGET_WIDTH") or "1280"),
            "target_height": int(
                get_env_setting("IMAGE_RESIZE_TARGET_HEIGHT") or "800"
            ),
            "quality_initial": int(
                get_env_setting("IMAGE_OUTPUT_QUALITY_INITIAL") or "90"
            ),
            "size_target": int(get_env_setting("IMAGE_SIZE_TARGET") or "800000"),
            "size_threshold": int(get_env_setting("IMAGE_SIZE_THRESHOLD") or "900000"),
            "size_limit": int(get_env_setting("IMAGE_SIZE_LIMIT") or "1000000"),
        }
        logger.debug(f"🔧 画像リサイズ設定を環境変数から読み込み: {config}")
        return config
    except ValueError as e:
        logger.warning(f"⚠️ 画像リサイズ設定の値が無効: {e}")
        # デフォルト値で返す
        return {
            "target_width": 1280,
            "target_height": 800,
            "quality_initial": 90,
            "size_target": 800_000,
            "size_threshold": 900_000,
            "size_limit": 1_000_000,
        }


# 画像処理ロジックは image_processor モジュールで実装


from plugin_interface import NotificationPlugin


class BlueskyImagePlugin(NotificationPlugin):
    """Bluesky 画像添付拡張プラグイン（オプション機能）

    このプラグインは削除しても Bluesky への投稿は動作します。
    ただし、画像添付機能は無効になります。
    """

    def __init__(
        self,
        username: str,
        password: str,
        dry_run: bool = False,
        minimal_poster: BlueskyMinimalPoster = None,
    ):
        # 既存の BlueskyMinimalPoster が渡された場合は再ログインを避ける
        self.minimal_poster = (
            minimal_poster
            if minimal_poster
            else BlueskyMinimalPoster(username, password, dry_run)
        )
        self.dry_run = dry_run
        # 画像管理クラスのインスタンスを取得
        self.image_manager = get_image_manager()
        # デフォルト画像パスを設定ファイルから取得
        self.default_image_path = get_env_setting("BLUESKY_IMAGE_PATH")

    def set_dry_run(self, dry_run: bool):
        """ドライランモードを設定"""
        self.dry_run = dry_run
        if hasattr(self.minimal_poster, "set_dry_run"):
            self.minimal_poster.set_dry_run(dry_run)
        post_logger.info(f"🧪 Bluesky プラグイン dry_run={dry_run}")

    def post_video(self, video: dict) -> bool:
        """
        動画を投稿（画像添付機能付き）

        この post_video は main_v2.py から呼び出されません。
        プラグインマネージャー経由で実行される場合にのみ使用されます。
        """
        # GUI から use_image フラグが指定されている場合は優先
        use_image = video.get("use_image", True)  # デフォルトは画像添付
        resize_small_images = video.get(
            "resize_small_images", True
        )  # デフォルトはリサイズ有効

        post_logger.info(
            f"🔍 post_video 開始: use_image={use_image}, resize_small_images={resize_small_images}, image_filename={video.get('image_filename')}"
        )

        # DBに画像ファイルが登録されている場合、そのファイルを優先して使用
        image_filename = video.get("image_filename")
        image_mode = video.get("image_mode")
        source = video.get("source", "YouTube").lower()
        video = dict(video)  # 元の辞書を変更しないようコピー
        embed = None

        # use_image=False の場合は画像添付を強制的にスキップ
        if not use_image:
            post_logger.info(f"🔗 GUI設定により、リンクカード投稿モード")
            video["use_link_card"] = True
            video["embed"] = None
        elif image_filename and image_filename.strip():
            # ファイル名から完全パスを構築
            image_path = self._resolve_image_path(image_filename, image_mode, source)
            post_logger.info(f"💾 DB登録済み画像を使用: {image_filename}")
            video["image_source"] = "database"
            # 画像ファイルをアップロードして embed を取得
            if image_path and Path(image_path).exists():
                result = self._upload_blob(
                    image_path, resize_small_images=resize_small_images
                )
                if result:
                    blob, width, height = result
                    embed = self._build_image_embed(blob, width, height)
                    post_logger.info(f"✅ 画像埋め込みの準備完了")
            else:
                post_logger.warning(
                    f"⚠️ 画像ファイルが見つかりません: {image_filename} (検索パス: {image_path})"
                )
        else:
            # 画像未指定時はデフォルト画像を利用
            if self.default_image_path and Path(self.default_image_path).exists():
                post_logger.info(f"🖼️ デフォルト画像を使用: {self.default_image_path}")
                video["image_filename"] = str(self.default_image_path)
                video["image_source"] = "default"
                # デフォルト画像をアップロードして embed を取得
                result = self._upload_blob(
                    str(self.default_image_path),
                    resize_small_images=resize_small_images,
                )
                if result:
                    blob, width, height = result
                    embed = self._build_image_embed(blob, width, height)
                    post_logger.info(f"✅ デフォルト画像埋め込みの準備完了")
            elif self.default_image_path:
                post_logger.warning(
                    f"⚠️ デフォルト画像が見つかりません: {self.default_image_path}"
                )

        # embed が取得できた場合は video に追加
        if embed:
            video["embed"] = embed
            video["use_link_card"] = False  # 画像を優先（リンクカードは無効化）
            post_logger.info(f"🖼️ 画像埋め込み: {embed}")
        else:
            # 画像がない場合、リンクカード機能を有効化
            video["use_link_card"] = True  # リンクカード機能を有効化
            post_logger.info(f"🔗 リンクカード機能を有効化します（画像なし）")

        # ============ テンプレートレンダリング（新着動画投稿用） ============
        # YouTube / ニコニコの新着動画投稿時にテンプレートを使用
        source = video.get("source", "youtube").lower()
        live_status = video.get("live_status")
        rendered = ""

        # live_status ベースのテンプレート選択（優先度高）
        if source == "youtube" and live_status:
            if live_status == "live":
                # ライブ開始テンプレート
                rendered = self.render_template_with_utils("youtube_online", video)
                if rendered:
                    video["text_override"] = rendered
                    post_logger.info(
                        f"✅ テンプレートを使用して本文を生成しました: youtube_online"
                    )
                else:
                    post_logger.debug(
                        f"ℹ️ youtube_online テンプレート未使用またはレンダリング失敗（従来フォーマットを使用）"
                    )
            elif live_status == "completed":
                # ライブ終了テンプレート
                rendered = self.render_template_with_utils("youtube_offline", video)
                if rendered:
                    video["text_override"] = rendered
                    post_logger.info(
                        f"✅ テンプレートを使用して本文を生成しました: youtube_offline"
                    )
                else:
                    post_logger.debug(
                        f"ℹ️ youtube_offline テンプレート未使用またはレンダリング失敗（従来フォーマットを使用）"
                    )
        elif not rendered:
            # live_status がない場合は従来ロジック
            if source == "youtube":
                # YouTube 新着動画用テンプレート
                rendered = self.render_template_with_utils("youtube_new_video", video)
                if rendered:
                    video["text_override"] = rendered
                    post_logger.info(
                        f"✅ テンプレートを使用して本文を生成しました: youtube_new_video"
                    )
                else:
                    post_logger.debug(
                        f"ℹ️ youtube_new_video テンプレート未使用またはレンダリング失敗（従来フォーマットを使用）"
                    )
            elif source in ("niconico", "nico"):
                # ニコニコ新着動画用テンプレート
                rendered = self.render_template_with_utils("nico_new_video", video)
                if rendered:
                    video["text_override"] = rendered
                    post_logger.info(
                        f"✅ テンプレートを使用して本文を生成しました: nico_new_video"
                    )
                else:
                    post_logger.debug(
                        f"ℹ️ nico_new_video テンプレート未使用またはレンダリング失敗（従来フォーマットを使用）"
                    )

        # 最終的に minimal_poster で投稿
        post_logger.info(
            f"📊 最終投稿設定: use_link_card={video.get('use_link_card')}, embed={bool(embed)}, text_override={bool(video.get('text_override'))}"
        )
        return self.minimal_poster.post_video_minimal(video)

    def is_available(self) -> bool:
        # minimal_posterの認証状態で判定（DRY RUN時は常にTrue）
        if self.minimal_poster.dry_run:
            return True
        return (
            self.minimal_poster.access_token is not None
            and self.minimal_poster.did is not None
        )

    def get_name(self) -> str:
        return "Bluesky 機能拡張プラグイン"

    def get_version(self) -> str:
        return "1.1.0"

    def get_description(self) -> str:
        return "Bluesky への画像添付と投稿テンプレート機能を拡張（オプション）"

    def on_enable(self) -> None:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "🔍 BlueskyPlugin on_enable: dry_run=%s, token=%s, did=%s",
                self.minimal_poster.dry_run,
                bool(getattr(self.minimal_poster, "access_token", None)),
                bool(getattr(self.minimal_poster, "did", None)),
            )
        # プラグイン有効化のINFOログはPluginManager側で出力するため、ここではDEBUGのみ

    def on_disable(self) -> None:
        logger.info(f"⛔ プラグイン無効化: {self.get_name()}")

    # ============ ファイルパス解決機能 ============

    def _resolve_image_path(
        self,
        image_filename: Optional[str],
        image_mode: Optional[str] = None,
        source: str = "youtube",
    ) -> Optional[str]:
        """
        画像ファイル名から完全パスを構築

        Args:
            image_filename: 画像ファイル名（\"video_id.jpg\" など）
            image_mode: 画像モード（\"import\" など）
            source: ソース名（\"youtube\" \"niconico\" など）

        Returns:
            完全パス、見つからない場合は None
        """
        if not image_filename:
            return None

        # ソース名を正規化
        if source.lower() in ("youtube", "yt"):
            site_dir = "YouTube"
        elif source.lower() in ("niconico", "nico"):
            site_dir = "Niconico"
        elif source.lower() == "twitch":
            site_dir = "Twitch"
        else:
            site_dir = "YouTube"

        # モードを正規化（デフォルトは \"import\"）
        if not image_mode:
            image_mode = "import"

        # パスを構築
        base_path = Path("images") / site_dir / image_mode / image_filename
        return str(base_path)

    # ============ 画像アップロード機能（拡張機能） ============

    def _upload_blob(
        self, file_path: str, resize_small_images: bool = True
    ) -> Optional[Tuple[Dict[str, Any], Optional[int], Optional[int]]]:
        """
        画像をBlob としてアップロード

        Bluesky API: com.atproto.repo.uploadBlob
        参照: https://docs.bsky.app/docs/api/com-atproto-repo-upload-blob

        処理フロー:
        1. 画像ファイルを読み込む
        2. resize_small_images=True の場合、_resize_image() で自動リサイズ・最適化
        3. resize_small_images=False の場合、元の画像をそのまま使用
        4. Bluesky API にアップロード

        Args:
            file_path: 画像ファイルパス
            resize_small_images: 画像をリサイズするか（Falseの場合はオリジナル画像を使用）

        Returns:
            blob メタデータ、失敗時は None
        """
        try:
            # DRY RUN モード時はダミーの blob を返す
            if self.dry_run:
                post_logger.info(
                    f"🧪 [DRY RUN] 画像アップロード（スキップ）: {file_path}"
                )
                dummy_blob = {
                    "$type": "blob",
                    "mimeType": "image/jpeg",
                    "size": 1000,
                    "link": {"$link": "bafkreidummy"},
                }
                return (dummy_blob, 1200, 627)  # ★ tuple を返す

            if not Path(file_path).exists():
                post_logger.warning(f"⚠️ 画像ファイルが見つかりません: {file_path}")
                return None

            # ========== 元画像の情報を取得してログ出力 ==========
            file_size_bytes = Path(file_path).stat().st_size

            try:
                img = Image.open(file_path)
                original_width, original_height = img.size
                original_format = img.format or "Unknown"
                aspect_ratio = (
                    original_width / original_height if original_height > 0 else 1.0
                )

                post_logger.info(
                    f"📊 【元画像情報】\n"
                    f"  ファイル: {Path(file_path).name}\n"
                    f"  パス: {file_path}\n"
                    f"  ファイルサイズ: {file_size_bytes / 1024:.1f}KB\n"
                    f"  解像度: {original_width}×{original_height}px\n"
                    f"  フォーマット: {original_format}\n"
                    f"  アスペクト比: {aspect_ratio:.2f}"
                )
            except Exception as e:
                post_logger.warning(f"⚠️ 元画像情報の取得失敗: {e}")
                post_logger.info(
                    f"📊 【元画像情報】ファイルサイズ: {file_size_bytes / 1024:.1f}KB"
                )

            # ========== 変換判定ロジックをログ出力 ==========
            post_logger.info(
                f"🔍 【変換判定】resize_small_images={resize_small_images}"
            )

            # ========== 画像処理 ==========
            if resize_small_images:
                # リサイズして最適化
                post_logger.info(f"✅ 判定結果: 画像をリサイズ・最適化します")
                post_logger.info(f"📏 リサイズ処理開始...")
                image_data = image_processor.resize_image(file_path)
                if image_data is None:
                    # リサイズ失敗 → この投稿では画像添付をスキップ
                    post_logger.error(
                        f"❌ 画像リサイズ失敗のため、この投稿では画像添付をスキップします"
                    )
                    return None
                mime_type = "image/jpeg"

                # リサイズ後の画像情報を取得
                try:
                    from PIL import Image as PILImage
                    import io

                    resized_img = PILImage.open(io.BytesIO(image_data))
                    resized_width, resized_height = resized_img.size
                    post_logger.info(
                        f"   リサイズ後の解像度: {resized_width}×{resized_height}px"
                    )
                except Exception as e:
                    post_logger.warning(f"⚠️ リサイズ後の解像度取得失敗: {e}")
                    resized_width = None
                    resized_height = None

                # 変換後の情報をログ出力
                post_logger.info(
                    f"✅ 【変換後の画像情報】\n"
                    f"  ファイルサイズ: {file_size_bytes / 1024:.1f}KB → {len(image_data) / 1024:.1f}KB\n"
                    f"  圧縮率: {(1 - len(image_data) / file_size_bytes) * 100:.1f}%\n"
                    f"  フォーマット: {original_format} → JPEG\n"
                    f"  バイナリサイズ: {len(image_data)} bytes"
                )
            else:
                # オリジナル画像をそのまま使用
                post_logger.info(
                    f"✅ 判定結果: オリジナル画像をそのまま使用します（リサイズなし）"
                )
                post_logger.info(f"📷 オリジナル画像のまま処理継続...")
                with open(file_path, "rb") as f:
                    image_data = f.read()

                # MIME タイプを判定
                try:
                    img = Image.open(file_path)
                    img_format = img.format or "JPEG"
                    mime_type = f"image/{img_format.lower()}"
                    resized_width, resized_height = img.size  # オリジナルの解像度
                except:
                    mime_type = "image/jpeg"
                    resized_width = None
                    resized_height = None

                # 変換なしの情報をログ出力
                post_logger.info(
                    f"✅ 【処理後の画像情報】\n"
                    f"  ファイルサイズ: {len(image_data) / 1024:.1f}KB（変換なし）\n"
                    f"  フォーマット: {mime_type}\n"
                    f"  バイナリサイズ: {len(image_data)} bytes"
                )

            # アクセストークンが存在することを確認
            if not self.minimal_poster.access_token:
                post_logger.error(
                    f"❌ Bluesky認証に失敗しています。画像はアップロードできません"
                )
                return None

            upload_url = "https://bsky.social/xrpc/com.atproto.repo.uploadBlob"
            headers = {
                "Authorization": f"Bearer {self.minimal_poster.access_token}",
                "Content-Type": mime_type,
            }

            import requests

            response = requests.post(
                upload_url, data=image_data, headers=headers, timeout=30
            )
            response.raise_for_status()

            result = response.json()
            blob = result.get("blob")

            if blob:
                post_logger.info(
                    f"✅ 画像アップロード成功: {blob.get('mimeType')} ({len(image_data)} bytes)"
                )

                # aspRatioはblobではなく、_build_image_embedで設定
                # ここでは (blob, width, height) のtupleを返す
                return (blob, resized_width, resized_height)
            else:
                post_logger.warning(f"⚠️ Blob メタデータが返されませんでした")
                return None

        except Exception as e:
            post_logger.warning(f"⚠️ 画像アップロード失敗: {e}")
            return None

    def _get_mime_type(self, file_path: str) -> str:
        """ファイル拡張子から MIME タイプを判定"""
        ext = Path(file_path).suffix.lower()
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        return mime_types.get(ext, "image/jpeg")  # デフォルトは JPEG

    def _build_image_embed(
        self,
        blob: Optional[Dict[str, Any]],
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Blob メタデータから画像埋め込み（embed）オブジェクトを構築

        Bluesky API: app.bsky.embed.images
        参照: https://docs.bsky.app/docs/advanced-guides/posts
        aspectRatio: https://atproto.blue/en/latest/atproto/atproto_client.models.app.bsky.embed.defs.html

        Args:
            blob: uploadBlob で返されたメタデータ
            width: 画像の幅（ピクセル）- aspectRatio設定用
            height: 画像の高さ（ピクセル）- aspectRatio設定用

        Returns:
            embed オブジェクト
        """
        if not blob:
            return None

        image_obj = {"image": blob, "alt": "Posted image"}

        # ★ aspectRatio を設定（Blueskyクライアントの正確な画像表示用）
        if width and height:
            image_obj["aspectRatio"] = {"width": width, "height": height}
            post_logger.debug(f"📐 AspectRatio を設定: {width}×{height}")

        return {"$type": "app.bsky.embed.images", "images": [image_obj]}

    def _download_image(self, url: str) -> Optional[str]:
        """
        URL から画像をダウンロード

        Args:
            url: 画像 URL

        Returns:
            ダウンロードしたファイルパス、失敗時は None
        """
        try:
            import tempfile
            import requests

            response = requests.get(url, timeout=10)
            response.raise_for_status()

            # ファイルサイズチェック
            if len(response.content) > 1_000_000:
                post_logger.warning(
                    f"⚠️ ダウンロード画像が大きすぎます: {len(response.content)} bytes"
                )
                return None

            # 拡張子を URL から推定
            from urllib.parse import urlparse

            parsed = urlparse(url)
            path = parsed.path

            # クエリ文字列を削除
            if "?" in url:
                path = url.split("?")[0]

            ext = Path(path).suffix or ".jpg"

            # 一時ファイルに保存
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(response.content)
                tmp_path = tmp.name

            post_logger.info(f"✅ 画像ダウンロード成功: {len(response.content)} bytes")
            return tmp_path

        except Exception as e:
            post_logger.warning(f"⚠️ 画像ダウンロード失敗: {e}")
            return None

    # ============ 画像取得・テンプレート機能 ============

    # 画像取得は ImageManager に委譲（後方互換性のため残す）
    def _get_image_bytes(
        self,
        site: Optional[str] = None,
        mode: Optional[str] = None,
        filename: Optional[str] = None,
        url: Optional[str] = None,
    ) -> Optional[bytes]:
        """画像データを取得（ImageManagerを使用）"""
        return self.image_manager.get_image_bytes(
            site=site, mode=mode, filename=filename, url=url
        )

    # ============ テンプレート機能 ============

    def _render_template(self, template_path: str, context: dict) -> str:
        """Jinja2 テンプレートをレンダリング"""
        try:
            from jinja2 import Environment
            from utils_v2 import format_datetime_filter

            with open(template_path, encoding="utf-8") as f:
                template_str = f.read()
            env = Environment(autoescape=True)
            env.filters["datetimeformat"] = format_datetime_filter
            template = env.from_string(template_str)
            return template.render(**context)
        except Exception as e:
            logger.error(f"❌ テンプレートレンダリング失敗: {e}")
            return ""

    # ============ テンプレート処理統合（新規: v2.1.0+） ============

    def render_template_with_utils(
        self, template_type: str, event_context: dict
    ) -> str:
        """
        テンプレート共通関数（template_utils.py）を使用してレンダリング。

        この方法は、テンプレート仕様の一元管理と検証を実現します。

        Args:
            template_type: テンプレート種別（例: "youtube_new_video"）
            event_context: 投稿イベント情報

        Returns:
            レンダリング済みテキスト、失敗時は空文字列

        ログ出力:
            - 成功時: DEBUG レベル
            - 必須キー不足: WARNING レベル
            - 失敗時: ERROR レベル

        例:
            rendered = plugin.render_template_with_utils(
                "youtube_new_video",
                {"title": "新作", "video_id": "abc123", ...}
            )
        """
        try:
            from template_utils import (
                load_template_with_fallback,
                validate_required_keys,
                render_template,
                get_template_path,
                TEMPLATE_REQUIRED_KEYS,
                DEFAULT_TEMPLATE_PATH,
            )

            # 1. テンプレートパスを取得（環境変数から、またはデフォルト）
            template_path = get_template_path(
                template_type, default_fallback=str(DEFAULT_TEMPLATE_PATH)
            )
            post_logger.debug(
                f"🔍 テンプレートパス取得: {template_type} → {template_path}"
            )

            # 2. テンプレートをロード（失敗時はフォールバック）
            post_logger.debug(
                f"🔍 load_template_with_fallback 呼び出し: path={template_path}, default_path={DEFAULT_TEMPLATE_PATH}"
            )
            template_obj = load_template_with_fallback(
                path=template_path,
                default_path=str(DEFAULT_TEMPLATE_PATH),
                template_type=template_type,
            )
            post_logger.debug(
                f"🔍 load_template_with_fallback 結果: {template_obj is not None}"
            )

            if not template_obj:
                post_logger.error(
                    f"❌ テンプレート読み込み失敗: {template_type} (path={template_path})"
                )
                return ""

            # 3. 必須キーをチェック
            required_keys = TEMPLATE_REQUIRED_KEYS.get(template_type, [])
            is_valid, missing_keys = validate_required_keys(
                event_context=event_context,
                required_keys=required_keys,
                event_type=template_type,
            )

            if not is_valid:
                post_logger.warning(
                    f"⚠️ 必須キー不足（{template_type}）: {missing_keys}"
                )
                # 必須キーがない場合はデフォルトテンプレートで試す
                template_obj = load_template_with_fallback(
                    path=str(DEFAULT_TEMPLATE_PATH),
                    default_path=None,
                    template_type=template_type,
                )
                if not template_obj:
                    post_logger.error(f"❌ デフォルトテンプレートもロード失敗")
                    return ""

            # 4. レンダリング実行
            rendered_text = render_template(
                template_obj=template_obj,
                event_context=event_context,
                template_type=template_type,
            )

            if rendered_text:
                post_logger.debug(f"✅ テンプレートレンダリング成功: {template_type}")
                return rendered_text
            else:
                post_logger.error(f"❌ テンプレートレンダリング失敗: {template_type}")
                return ""

        except ImportError as e:
            post_logger.error(f"❌ template_utils インポート失敗: {e}")
            return ""

        except Exception as e:
            post_logger.error(f"❌ テンプレート処理予期しないエラー: {e}")
            return ""


def get_bluesky_plugin(
    username: str, password: str, dry_run: bool = False
) -> BlueskyImagePlugin:
    """Bluesky 画像添付拡張プラグインを取得"""
    return BlueskyImagePlugin(username, password, dry_run)
