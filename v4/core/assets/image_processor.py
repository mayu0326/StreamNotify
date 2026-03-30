import logging
from pathlib import Path
from PIL import Image
import io
from typing import Optional, Any
from v4.core.config import settings

logger = logging.getLogger("v4.image_processor")

# Blueskyの推奨画像サイズ（アスペクト比別）
_RECOMMENDED_SIZES = {
    "portrait": (800, 1000),     # 縦長 (4:5)
    "square": (1000, 1000),      # 正方形 (1:1)
}

def resize_image(image_input: Any, config: dict = None) -> Optional[bytes]:
    """
    画像をリサイズして最適化（v3ロジック準拠）
    """
    try:
        # settings から設定をロード、引数 config があれば優先
        size_limit = config.get("size_limit", settings.image_size_limit) if config else settings.image_size_limit
        size_threshold = config.get("size_threshold", settings.image_size_threshold) if config else settings.image_size_threshold
        quality_initial = config.get("quality_initial", settings.image_output_quality_initial) if config else settings.image_output_quality_initial

        if isinstance(image_input, (str, Path)):
            if not Path(image_input).exists():
                return None
            img = Image.open(image_input)
        else:
            img = Image.open(io.BytesIO(image_input))

        # 基本情報の取得
        width, height = img.size

        # 1. アスペクト比判定とリサイズ
        # デフォルト（横長）は settings から取得
        target_w = settings.image_resize_target_width
        target_h = settings.image_resize_target_height

        aspect = width / height
        if aspect < 0.8:
            target_w, target_h = _RECOMMENDED_SIZES["portrait"]
        elif aspect <= 1.25:
            target_w, target_h = _RECOMMENDED_SIZES["square"]

        # 2. リサイズ実行
        img.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)

        # 3. 段階的圧縮 (1MB制限対応)
        quality = quality_initial
        while quality >= 10:
            buffer = io.BytesIO()
            # モード変換
            if img.mode in ('RGBA', 'LA', 'P'):
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                proc_img = bg
            else:
                proc_img = img.convert('RGB') if img.mode != 'RGB' else img

            proc_img.save(buffer, format='JPEG', quality=quality, optimize=True)
            data = buffer.getvalue()

            if len(data) <= size_limit:
                if len(data) > size_threshold and quality > 10:
                    quality -= 5 # 閾値に近い場合はさらに少し下げる
                    continue
                return data

            quality -= 10

        logger.error(f"❌ 最大限の圧縮を行いましたが、{size_limit} bytes 制限を下回ることができませんでした。")
        return None

    except Exception as e:
        logger.error(f"❌ 画像リサイズ失敗: {e}")
        return None
