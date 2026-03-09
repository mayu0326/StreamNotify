# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v3 画像管理モジュール

サムネイル画像の取得・管理機能を提供。
GUI、プラグイン、その他のモジュールから共通利用可能。
"""

import os
import logging
import requests
from pathlib import Path
from typing import Optional, Tuple, List
import io

# Pillowはオプション（画像情報取得機能で使用）
try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logging.warning("⚠️ Pillow (PIL) がインストールされていません。画像情報取得機能は制限されます。")

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv3"

__version__ = "1.0.0"


def get_youtube_thumbnail_url(video_id: str) -> Optional[str]:
    """
    YouTube のサムネイル URL を複数品質から取得
    
    複数の品質レベルを試行し、最初に取得できた URL を返す。
    API 呼び出しは不要で、HTTP ステータスコードで品質確認。
    
    優先度: maxres (1280x720) → sd (640x480) → hq (480x360) → 
            mq (320x180) → default (120x90)
    
    Args:
        video_id: YouTube 動画 ID
        
    Returns:
        サムネイル URL、取得失敗時は None
    """
    if not video_id:
        return None
    
    base = f"https://i.ytimg.com/vi/{video_id}"
    candidates = [
        "maxresdefault.jpg",  # 1280x720 - 最高品質
        "sddefault.jpg",      # 640x480
        "hqdefault.jpg",      # 480x360
        "mqdefault.jpg",      # 320x180
        "default.jpg",        # 120x90 - 常に存在
    ]
    
    for name in candidates:
        url = f"{base}/{name}"
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                logger.debug(f"✅ YouTube サムネイル取得: {video_id} -> {name}")
                return url
        except Exception as e:
            logger.debug(f"⚠️ YouTube サムネイル試行失敗: {name} - {e}")
            continue
    
    logger.warning(f"⚠️ YouTube サムネイル取得失敗: {video_id}")
    return None


class ImageManager:
    """画像管理クラス"""

    def __init__(self, base_dir: str = "images"):
        """
        初期化

        Args:
            base_dir: 画像ディレクトリのベースパス
        """
        self.base_dir = Path(base_dir)
        self._ensure_directories()

    def _ensure_directories(self):
        """必要なディレクトリを作成"""
        # デフォルトディレクトリ
        (self.base_dir / "default").mkdir(parents=True, exist_ok=True)
        
        # サイト別ディレクトリ
        for site in ["YouTube", "Niconico", "Twitch"]:
            (self.base_dir / site / "import").mkdir(parents=True, exist_ok=True)
            (self.base_dir / site / "autopost").mkdir(parents=True, exist_ok=True)

    def get_image_bytes(
        self,
        site: Optional[str] = None,
        mode: Optional[str] = None,
        filename: Optional[str] = None,
        url: Optional[str] = None
    ) -> Optional[bytes]:
        """
        画像データを取得

        優先順位:
        1. import モード: images/{site}/import/{filename}
        2. autopost モード: images/{site}/autopost/{filename}
        3. URL モード: リモートURLからダウンロード
        4. フォールバック: images/default/noimage.png

        Args:
            site: サイト名 (YouTube, Niconico, Twitch)
            mode: 取得モード (import, autopost)
            filename: ファイル名
            url: 画像URL

        Returns:
            画像データ（bytes）、取得失敗時は None
        """
        # 1. import モード
        if site and mode == 'import' and filename:
            path = self.base_dir / site / 'import' / filename
            image_data = self._read_local_file(path)
            if image_data:
                logger.info(f"✅ import画像取得: {path}")
                return image_data

        # 2. autopost モード
        if site and mode == 'autopost' and filename:
            path = self.base_dir / site / 'autopost' / filename
            image_data = self._read_local_file(path)
            if image_data:
                logger.info(f"✅ autopost画像取得: {path}")
                return image_data

        # 3. URL モード
        if url:
            image_data = self._download_from_url(url)
            if image_data:
                logger.info(f"✅ URL画像取得: {url}")
                return image_data

        # 4. フォールバック
        return self._get_default_image()

    def _read_local_file(self, path: Path) -> Optional[bytes]:
        """ローカルファイルから画像を読み込み"""
        try:
            if path.is_file():
                with open(path, 'rb') as f:
                    return f.read()
        except Exception as e:
            logger.warning(f"⚠️ ローカル画像の読み込み失敗: {path} - {e}")
        return None

    def _download_from_url(self, url: str, timeout: int = 10) -> Optional[bytes]:
        """URLから画像をダウンロード"""
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            logger.info(f"✅ 画像ダウンロード成功: {len(response.content)} bytes")
            return response.content
        except Exception as e:
            logger.warning(f"⚠️ 画像ダウンロード失敗: {url} - {e}")
        return None

    def _get_default_image(self) -> Optional[bytes]:
        """デフォルト画像を取得"""
        default_path = self.base_dir / "default" / "noimage.png"
        try:
            with open(default_path, 'rb') as f:
                logger.info(f"✅ デフォルト画像を使用: {default_path}")
                return f.read()
        except Exception as e:
            logger.error(f"❌ デフォルト画像の読み込み失敗: {e}")
        return None

    def save_image_from_url(
        self,
        url: str,
        site: str,
        mode: str = "import",
        filename: Optional[str] = None
    ) -> Optional[str]:
        """
        URLから画像をダウンロードして保存

        Args:
            url: 画像URL
            site: サイト名
            mode: 保存モード (import, autopost)
            filename: 保存ファイル名（省略時は自動生成）

        Returns:
            保存されたファイル名、失敗時は None
        """
        image_data = self._download_from_url(url)
        if not image_data:
            return None

        if not filename:
            # URLから拡張子を推測
            ext = self._detect_image_extension(image_data)
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{site}_{timestamp}.{ext}"

        save_path = self.base_dir / site / mode / filename
        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(image_data)
            logger.info(f"✅ 画像保存成功: {save_path}")
            return filename
        except Exception as e:
            logger.error(f"❌ 画像保存失敗: {save_path} - {e}")
        return None

    def _detect_image_extension(self, image_data: bytes) -> str:
        """画像データから拡張子を推測"""
        if not PIL_AVAILABLE:
            # Pillowがない場合は先頭バイトから推測
            if image_data.startswith(b'\x89PNG'):
                return "png"
            elif image_data.startswith(b'\xFF\xD8\xFF'):
                return "jpg"
            elif image_data.startswith(b'GIF87a') or image_data.startswith(b'GIF89a'):
                return "gif"
            elif image_data.startswith(b'RIFF') and b'WEBP' in image_data[:20]:
                return "webp"
            return "png"
        
        try:
            img = Image.open(io.BytesIO(image_data))
            return img.format.lower() if img.format else "png"
        except:
            return "png"

    def list_images(self, site: str, mode: str = "import") -> List[str]:
        """
        指定ディレクトリ内の画像ファイル一覧を取得

        Args:
            site: サイト名
            mode: モード (import, autopost)

        Returns:
            ファイル名のリスト
        """
        dir_path = self.base_dir / site / mode
        if not dir_path.exists():
            return []

        try:
            image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
            files = [
                f.name for f in dir_path.iterdir()
                if f.is_file() and f.suffix.lower() in image_extensions
            ]
            return sorted(files)
        except Exception as e:
            logger.error(f"❌ 画像一覧取得失敗: {dir_path} - {e}")
        return []

    def delete_image(self, site: str, mode: str, filename: str) -> bool:
        """
        画像ファイルを削除

        Args:
            site: サイト名
            mode: モード (import, autopost)
            filename: ファイル名

        Returns:
            削除成功時 True
        """
        file_path = self.base_dir / site / mode / filename
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"✅ 画像削除成功: {file_path}")
                return True
            else:
                logger.warning(f"⚠️ 画像ファイルが見つかりません: {file_path}")
        except Exception as e:
            logger.error(f"❌ 画像削除失敗: {file_path} - {e}")
        return False

    def get_image_info(self, site: str, mode: str, filename: str) -> Optional[dict]:
        """
        画像ファイルの情報を取得

        Args:
            site: サイト名
            mode: モード
            filename: ファイル名

        Returns:
            画像情報の辞書（サイズ、形式、ファイルサイズなど）
        """
        file_path = self.base_dir / site / mode / filename
        if not file_path.exists():
            return None

        try:
            file_size = file_path.stat().st_size
            
            if not PIL_AVAILABLE:
                # Pillowがない場合は基本情報のみ
                return {
                    "filename": filename,
                    "path": str(file_path),
                    "width": None,
                    "height": None,
                    "format": file_path.suffix.lstrip('.').upper(),
                    "mode": None,
                    "file_size": file_size,
                    "file_size_mb": round(file_size / (1024 * 1024), 2)
                }
            
            with Image.open(file_path) as img:
                return {
                    "filename": filename,
                    "path": str(file_path),
                    "width": img.width,
                    "height": img.height,
                    "format": img.format,
                    "mode": img.mode,
                    "file_size": file_size,
                    "file_size_mb": round(file_size / (1024 * 1024), 2)
                }
        except Exception as e:
            logger.error(f"❌ 画像情報取得失敗: {file_path} - {e}")
        return None

    def validate_image(self, image_data: bytes, max_size_mb: float = 1.0) -> Tuple[bool, str]:
        """
        画像データを検証

        Args:
            image_data: 画像データ
            max_size_mb: 最大ファイルサイズ（MB）

        Returns:
            (検証結果, エラーメッセージ)
        """
        if not image_data:
            return False, "画像データが空です"

        # サイズチェック
        size_mb = len(image_data) / (1024 * 1024)
        if size_mb > max_size_mb:
            return False, f"ファイルサイズが大きすぎます ({size_mb:.2f}MB > {max_size_mb}MB)"

        if not PIL_AVAILABLE:
            # Pillowがない場合は基本的なバイナリチェックのみ
            if image_data.startswith(b'\x89PNG') or \
               image_data.startswith(b'\xFF\xD8\xFF') or \
               image_data.startswith(b'GIF') or \
               (image_data.startswith(b'RIFF') and b'WEBP' in image_data[:20]):
                return True, "OK"
            return False, "不明な画像形式です"

        # 形式チェック（Pillow使用）
        try:
            img = Image.open(io.BytesIO(image_data))
            img.verify()
            return True, "OK"
        except Exception as e:
            return False, f"無効な画像形式です: {e}"

    def resize_image(
        self,
        site: str,
        mode: str,
        filename: str,
        max_width: int = 1920,
        max_height: int = 1080,
        output_filename: Optional[str] = None
    ) -> Optional[str]:
        """
        画像をリサイズ（アスペクト比を維持）

        Args:
            site: サイト名
            mode: モード
            filename: 元ファイル名
            max_width: 最大幅
            max_height: 最大高さ
            output_filename: 出力ファイル名（省略時は元ファイルを上書き）

        Returns:
            リサイズ後のファイル名、失敗時は None
        """
        if not PIL_AVAILABLE:
            logger.error("❌ Pillowがインストールされていないため、リサイズできません")
            return None

        input_path = self.base_dir / site / mode / filename
        if not input_path.exists():
            logger.error(f"❌ ファイルが見つかりません: {input_path}")
            return None

        try:
            with Image.open(input_path) as img:
                # EXIFの向き情報を適用
                img = ImageOps.exif_transpose(img)
                
                # リサイズが必要か確認
                if img.width <= max_width and img.height <= max_height:
                    logger.info(f"✅ リサイズ不要: {img.width}x{img.height}")
                    return filename

                # アスペクト比を維持してリサイズ
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                
                output_name = output_filename or filename
                output_path = self.base_dir / site / mode / output_name
                
                # 保存
                img.save(output_path, optimize=True, quality=85)
                logger.info(f"✅ リサイズ成功: {img.width}x{img.height} → {output_path}")
                return output_name

        except Exception as e:
            logger.error(f"❌ リサイズ失敗: {input_path} - {e}")
        return None

    def convert_to_format(
        self,
        site: str,
        mode: str,
        filename: str,
        target_format: str = "PNG",
        output_filename: Optional[str] = None
    ) -> Optional[str]:
        """
        画像を指定形式に変換

        Args:
            site: サイト名
            mode: モード
            filename: 元ファイル名
            target_format: 変換先形式 (PNG, JPEG, WEBP)
            output_filename: 出力ファイル名（省略時は自動生成）

        Returns:
            変換後のファイル名、失敗時は None
        """
        if not PIL_AVAILABLE:
            logger.error("❌ Pillowがインストールされていないため、変換できません")
            return None

        input_path = self.base_dir / site / mode / filename
        if not input_path.exists():
            logger.error(f"❌ ファイルが見つかりません: {input_path}")
            return None

        try:
            with Image.open(input_path) as img:
                # RGBAモードの場合、JPEGに変換する際はRGBに変換
                if target_format.upper() == "JPEG" and img.mode in ("RGBA", "LA", "P"):
                    rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                    img = rgb_img

                # 出力ファイル名を生成
                if not output_filename:
                    stem = input_path.stem
                    ext = target_format.lower()
                    if ext == "jpeg":
                        ext = "jpg"
                    output_filename = f"{stem}.{ext}"

                output_path = self.base_dir / site / mode / output_filename
                
                # 保存オプション
                save_kwargs = {"format": target_format.upper()}
                if target_format.upper() == "JPEG":
                    save_kwargs["quality"] = 85
                    save_kwargs["optimize"] = True
                elif target_format.upper() == "PNG":
                    save_kwargs["optimize"] = True
                elif target_format.upper() == "WEBP":
                    save_kwargs["quality"] = 85

                img.save(output_path, **save_kwargs)
                logger.info(f"✅ 変換成功: {target_format} → {output_path}")
                return output_filename

        except Exception as e:
            logger.error(f"❌ 変換失敗: {input_path} - {e}")
        return None

    def create_thumbnail(
        self,
        site: str,
        mode: str,
        filename: str,
        thumb_size: Tuple[int, int] = (320, 180),
        output_suffix: str = "_thumb"
    ) -> Optional[str]:
        """
        サムネイル画像を生成

        Args:
            site: サイト名
            mode: モード
            filename: 元ファイル名
            thumb_size: サムネイルサイズ (幅, 高さ)
            output_suffix: 出力ファイル名の接尾辞

        Returns:
            サムネイルファイル名、失敗時は None
        """
        if not PIL_AVAILABLE:
            logger.error("❌ Pillowがインストールされていないため、サムネイル生成できません")
            return None

        input_path = self.base_dir / site / mode / filename
        if not input_path.exists():
            logger.error(f"❌ ファイルが見つかりません: {input_path}")
            return None

        try:
            with Image.open(input_path) as img:
                # EXIFの向き情報を適用
                img = ImageOps.exif_transpose(img)
                
                # サムネイル生成
                img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
                
                # 出力ファイル名を生成
                stem = input_path.stem
                ext = input_path.suffix
                output_filename = f"{stem}{output_suffix}{ext}"
                output_path = self.base_dir / site / mode / output_filename
                
                img.save(output_path, optimize=True, quality=85)
                logger.info(f"✅ サムネイル生成成功: {thumb_size} → {output_path}")
                return output_filename

        except Exception as e:
            logger.error(f"❌ サムネイル生成失敗: {input_path} - {e}")
        return None

    def optimize_image(
        self,
        site: str,
        mode: str,
        filename: str,
        max_file_size_kb: int = 1024,
        output_filename: Optional[str] = None
    ) -> Optional[str]:
        """
        画像を最適化（ファイルサイズを削減）

        Args:
            site: サイト名
            mode: モード
            filename: 元ファイル名
            max_file_size_kb: 目標ファイルサイズ（KB）
            output_filename: 出力ファイル名（省略時は元ファイルを上書き）

        Returns:
            最適化後のファイル名、失敗時は None
        """
        if not PIL_AVAILABLE:
            logger.error("❌ Pillowがインストールされていないため、最適化できません")
            return None

        input_path = self.base_dir / site / mode / filename
        if not input_path.exists():
            logger.error(f"❌ ファイルが見つかりません: {input_path}")
            return None

        try:
            with Image.open(input_path) as img:
                # EXIFの向き情報を適用
                img = ImageOps.exif_transpose(img)
                
                output_name = output_filename or filename
                output_path = self.base_dir / site / mode / output_name
                
                # 品質を調整しながら保存
                quality = 85
                while quality > 50:
                    buffer = io.BytesIO()
                    img.save(buffer, format=img.format or "PNG", quality=quality, optimize=True)
                    size_kb = len(buffer.getvalue()) / 1024
                    
                    if size_kb <= max_file_size_kb:
                        with open(output_path, 'wb') as f:
                            f.write(buffer.getvalue())
                        logger.info(f"✅ 最適化成功: {size_kb:.1f}KB (品質: {quality}) → {output_path}")
                        return output_name
                    
                    quality -= 5

                # 最小品質でも目標サイズを超える場合は警告
                logger.warning(f"⚠️ 目標サイズ {max_file_size_kb}KB に到達できませんでした（現在: {size_kb:.1f}KB）")
                with open(output_path, 'wb') as f:
                    f.write(buffer.getvalue())
                return output_name

        except Exception as e:
            logger.error(f"❌ 最適化失敗: {input_path} - {e}")
        return None

    def download_and_save_thumbnail(
        self,
        thumbnail_url: str,
        site: str,
        video_id: str,
        mode: str = "autopost"
    ) -> Optional[str]:
        """
        サムネイルURLから画像をダウンロードして保存

        Args:
            thumbnail_url: サムネイルURL
            site: サイト名 (YouTube, Niconico, Twitch)
            video_id: 動画ID（ファイル名に使用）
            mode: 保存モード (autopost, import)

        Returns:
            保存されたファイル名、失敗時は None
        """
        if not thumbnail_url:
            logger.warning("⚠️ サムネイルURLが指定されていません")
            return None

        # 動画IDをサニタイズ（ファイル名として不適切な文字を除去）
        safe_video_id = "".join(c for c in video_id if c.isalnum() or c in "-_")
        
        # ファイル名を生成（拡張子は自動検出）
        filename = f"{safe_video_id}.tmp"
        
        # 画像をダウンロード
        result = self.save_image_from_url(thumbnail_url, site, mode, filename)
        
        if result:
            # 拡張子を正しく付け直す
            temp_path = self.base_dir / site / mode / result
            if temp_path.exists():
                image_data = temp_path.read_bytes()
                
                # 画像の検証
                is_valid, error_msg = self.validate_image(image_data, max_size_mb=10.0)
                if not is_valid:
                    logger.error(f"❌ ダウンロードしたファイルは有効な画像ではありません: {error_msg}")
                    temp_path.unlink()  # 無効なファイルを削除
                    return None
                
                ext = self._detect_image_extension(image_data)
                final_filename = f"{safe_video_id}.{ext}"
                final_path = self.base_dir / site / mode / final_filename
                
                # 既存があれば上書き
                if final_path.exists():
                    try:
                        final_path.unlink()
                    except Exception as e:
                        logger.warning(f"⚠️ 既存ファイルの削除に失敗: {final_path} - {e}")
                
                # ファイル名を変更
                temp_path.rename(final_path)
                logger.info(f"✅ サムネイル保存完了: {final_path}")
                return final_filename
        
        return None


# シングルトンインスタンス
_image_manager_instance = None


def get_image_manager() -> ImageManager:
    """ImageManagerのシングルトンインスタンスを取得"""
    global _image_manager_instance
    if _image_manager_instance is None:
        _image_manager_instance = ImageManager()
    return _image_manager_instance

