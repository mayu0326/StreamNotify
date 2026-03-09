"""
画像処理モジュール

Blueskyへの投稿用に画像をリサイズ・最適化する機能を提供します。
単体テストを想定して設計されています。
"""

import logging
from pathlib import Path
from PIL import Image
import io
from typing import Optional, Any, Dict

# ログ設定
# モジュール独立実行時は __main__、bluesky_plugin から呼び出されときは PostLogger を使用
logger = logging.getLogger(__name__)

# Bluesky投稿時用のロガーを追加
post_logger = logging.getLogger("PostLogger")

# 画像処理の設定
_IMAGE_CONFIG = {
    "quality_initial": 90,  # 初期JPEG品質
    "size_threshold": 900 * 1024,  # ファイルサイズ閾値（900KB）
    "size_limit": 1024 * 1024,  # ファイルサイズ上限（1MB）
}

# Blueskyの推奨画像サイズ（アスペクト比別）
# 参考: https://docs.bsky.app/docs/advanced-guides/image-handling
_RECOMMENDED_SIZES = {
    "portrait": (800, 1000),  # 縦長 (4:5) - アスペクト比 < 0.8
    "square": (1000, 1000),  # 正方形 (1:1) - 0.8 ≤ アスペクト比 ≤ 1.25
    "landscape": (
        1200,
        627,
    ),  # 横長 (16:9) - アスペクト比 > 1.25 ★ 1200x627は1000x563の代替案
}


def resize_image(
    file_path: str, config: Optional[Dict[str, Any]] = None
) -> Optional[bytes]:
    """
    画像をリサイズして最適化

    処理フロー:
    1. 元画像の情報を取得（解像度・フォーマット・ファイルサイズ）
    2. アスペクト比に応じて推奨サイズにリサイズ
       - 縦長 (アスペクト比 < 0.8): 800×1000px (4:5)
       - 正方形 (0.8 ≤ アスペクト比 ≤ 1.25): 1000×1000px (1:1)
       - 横長 (アスペクト比 > 1.25): 1200×627px (16:9) ★ Bluesky推奨代替案
       - 例: 1920×1080 → 1200×627
       - 例: 1080×1920 → 800×1000
       - 例: 1500×1500 → 1000×1000
    3. JPEG品質で出力
    4. ファイルサイズ確認 → 閾値超過なら品質低下して再圧縮
    5. 最終的に上限超過ならNoneを返す

    Args:
        file_path: 画像ファイルパス
        config: 画像処理設定辞書（省略時は _IMAGE_CONFIG を使用）

    Returns:
        リサイズ・最適化済みの JPEG バイナリ、失敗時は None
    """
    try:
        if config is None:
            config = _IMAGE_CONFIG

        if not Path(file_path).exists():
            logger.warning(f"⚠️ 画像ファイルが見つかりません: {file_path}")
            return None

        # ========== 元画像の情報取得 ==========
        with open(file_path, "rb") as f:
            original_data = f.read()
        original_size_bytes = len(original_data)

        img = Image.open(file_path)
        original_width, original_height = img.size
        original_format = img.format or "Unknown"

        aspect_ratio = original_width / original_height if original_height > 0 else 1.0

        post_logger.debug(
            f"📏 元画像: {original_width}×{original_height} ({original_format}, {original_size_bytes / 1024:.1f}KB, アスペクト比: {aspect_ratio:.2f})"
        )

        # ========== アスペクト比に応じたリサイズ処理 ==========
        if aspect_ratio < 0.8:
            # 縦長画像 (4:5)
            target_w, target_h = _RECOMMENDED_SIZES["portrait"]
            post_logger.debug(
                f"🔄 縦長画像（アスペクト比 {aspect_ratio:.2f}）: {target_w}×{target_h}px にリサイズ"
            )
        elif aspect_ratio <= 1.25:
            # 正方形〜やや横長 (1:1)
            target_w, target_h = _RECOMMENDED_SIZES["square"]
            post_logger.debug(
                f"🔄 正方形/やや横長（アスペクト比 {aspect_ratio:.2f}）: {target_w}×{target_h}px にリサイズ"
            )
        else:
            # 横長画像 (16:9)
            target_w, target_h = _RECOMMENDED_SIZES["landscape"]
            post_logger.debug(
                f"🔄 横長画像（アスペクト比 {aspect_ratio:.2f}）: {target_w}×{target_h}px にリサイズ"
            )

        resized_img = _resize_to_target(img, target_w, target_h)

        resized_width, resized_height = resized_img.size
        post_logger.debug(f"   リサイズ後: {resized_width}×{resized_height}")

        # ========== JPEG 出力（初期品質） ==========
        jpeg_data: Optional[bytes] = _encode_jpeg(
            resized_img, config["quality_initial"]
        )
        if jpeg_data is None:
            return None

        current_size_bytes = len(jpeg_data)
        post_logger.debug(
            f"   JPEG品質{config['quality_initial']}: {current_size_bytes / 1024:.1f}KB"
        )

        # ========== ファイルサイズチェック＆品質調整 ==========
        if current_size_bytes > config["size_threshold"]:
            # 閾値超過 → 品質を段階的に下げて再圧縮
            post_logger.info(
                f"⚠️ ファイルサイズが {config['size_threshold'] / 1024:.0f}KB を超過: {current_size_bytes / 1024:.1f}KB"
            )
            jpeg_data = _optimize_image_quality(resized_img, config)

            if jpeg_data is None:
                post_logger.error(
                    f"❌ ファイルサイズの最適化に失敗しました（{config['size_limit']}バイト超過）"
                )
                return None

            current_size_bytes = len(jpeg_data)

        # ========== 最終チェック ==========
        if current_size_bytes > config["size_limit"]:
            post_logger.error(
                f"❌ 最終的なファイルサイズが上限を超えています: {current_size_bytes / 1024:.1f}KB"
            )
            return None

        # ========== ログ出力 ==========
        post_logger.info(
            f"✅ 画像リサイズ完了: {original_width}×{original_height} ({original_size_bytes / 1024:.1f}KB) "
            f"→ {resized_width}×{resized_height} ({current_size_bytes / 1024:.1f}KB)"
        )

        return jpeg_data

    except Exception as e:
        post_logger.error(f"❌ 画像リサイズ失敗: {e}")
        return None


def resize_to_aspect_ratio(img, target_width: int, target_height: int):
    """
    アスペクト比を指定値に寄せて縮小+中央トリミング

    ターゲットのアスペクト比に合わせるため、元画像が相対的に横長ならば幅を基準に縮小し、
    縦長ならば高さを基準に縮小してから中央トリミングを行う

    Args:
        img: PIL Image オブジェクト
        target_width: ターゲット幅
        target_height: ターゲット高さ

    Returns:
        トリミング後の PIL Image オブジェクト
    """
    original_width, original_height = img.size

    # ターゲットのアスペクト比
    target_ratio = target_width / target_height

    # 元画像のアスペクト比
    current_ratio = original_width / original_height

    if current_ratio > target_ratio:
        # 元画像がターゲットより横長 → 幅を基準に縮小（高さがターゲット以下になる）
        new_width = target_width
        new_height = int(target_width / current_ratio)
    else:
        # 元画像がターゲットより縦長 → 高さを基準に縮小（幅がターゲット以下になる）
        new_height = target_height
        new_width = int(target_height * current_ratio)

    # 縮小
    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # 中央トリミング
    left = (new_width - target_width) // 2
    top = (new_height - target_height) // 2
    right = left + target_width
    bottom = top + target_height

    img_cropped = img_resized.crop((left, top, right, bottom))

    return img_cropped


def _resize_to_target(img, target_width: int, target_height: int):
    """
    ターゲットサイズにリサイズ（アスペクト比を維持しながらアスペクト比調整）

    元画像のアスペクト比とターゲットのアスペクト比が異なる場合、
    アスペクト比を変えずにターゲットサイズに合わせます。
    トリミングは行わず、アスペクト比に基づいて収まるようにリサイズします。

    処理方針:
    - 元画像がターゲットより横長 → 幅を基準に計算
    - 元画像がターゲットより縦長 → 高さを基準に計算
    - 最終的なサイズはターゲット以下になります

    Args:
        img: PIL Image オブジェクト
        target_width: ターゲット幅
        target_height: ターゲット高さ

    Returns:
        リサイズ後の PIL Image オブジェクト
    """
    original_width, original_height = img.size
    original_ratio = original_width / original_height
    target_ratio = target_width / target_height

    if original_ratio > target_ratio:
        # 元画像がターゲットより横長 → 幅をターゲット幅に合わせる
        new_width = target_width
        # 高さはターゲット値から逆算（推奨サイズと一致させる）
        new_height = target_height
    else:
        # 元画像がターゲットより縦長 → 高さをターゲット高さに合わせる
        new_height = target_height
        # 幅はターゲット値から逆算（推奨サイズと一致させる）
        new_width = target_width

    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    return img_resized


def _resize_to_max_long_side(img, max_long_side: int):
    """
    [非推奨] 長辺を max_long_side 以下にリサイズ

    このメソッドは互換性のために残されています。
    新しい実装では _resize_to_target を使用してください。
    """
    width, height = img.size
    max_current = max(width, height)

    if max_current <= max_long_side:
        return img

    scale = max_long_side / max_current
    new_width = int(width * scale)
    new_height = int(height * scale)

    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    return img_resized


def _encode_jpeg(img, quality: int) -> bytes:
    """
    PIL Image を JPEG でエンコードしてバイナリを返す

    Args:
        img: PIL Image オブジェクト
        quality: JPEG品質（1-95）

    Returns:
        JPEG バイナリ
    """
    # RGBに変換（PNG等のアルファチャネルを削除）
    if img.mode in ("RGBA", "LA", "P"):
        # 白背景で合成
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def _optimize_image_quality(
    img: Image.Image, config: Dict[str, Any]
) -> Optional[bytes]:
    """
    画像の品質を段階的に下げて再圧縮（ファイルサイズを上限未満に）

    Args:
        img: PIL Image オブジェクト
        config: 画像処理設定辞書（size_limitを含む）

    Returns:
        最適化された JPEG バイナリ、失敗時は None
    """
    # 品質を段階的に下げてテスト: 85, 75, 65, 55, 50
    quality_levels = [85, 75, 65, 55, 50]

    for quality in quality_levels:
        jpeg_data = _encode_jpeg(img, quality)
        size_bytes = len(jpeg_data)

        logger.debug(f"   JPEG品質{quality}: {size_bytes / 1024:.1f}KB")

        if size_bytes <= config["size_limit"]:
            logger.info(
                f"✅ 品質{quality}で {config['size_limit'] / 1024:.0f}KB 以下に圧縮: {size_bytes / 1024:.1f}KB"
            )
            return jpeg_data

    # すべての品質レベルでも上限を超えた
    logger.error(
        f"❌ 品質{quality_levels[-1]}でも {config['size_limit'] / 1024:.0f}KB を超えています"
    )
    return None


# テスト用コマンドラインツール
if __name__ == "__main__":
    import sys
    import argparse

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="画像処理モジュール テスト")
    parser.add_argument("image_file", help="入力画像ファイルパス")
    parser.add_argument("--output", "-o", help="出力ファイルパス（指定時のみ保存）")
    parser.add_argument(
        "--max-long-side",
        type=int,
        default=1000,
        help="長辺の最大値（デフォルト: 1000）",
    )
    parser.add_argument(
        "--quality", type=int, default=90, help="初期JPEG品質（デフォルト: 90）"
    )

    args = parser.parse_args()

    # カスタム設定
    custom_config = _IMAGE_CONFIG.copy()
    custom_config["max_long_side"] = args.max_long_side
    custom_config["quality_initial"] = args.quality

    # 画像処理
    result = resize_image(args.image_file, config=custom_config)

    if result:
        logger.info(f"処理成功: {len(result)} バイト")

        if args.output:
            with open(args.output, "wb") as f:
                f.write(result)
            logger.info(f"出力ファイル: {args.output}")
    else:
        logger.error("処理失敗")
        sys.exit(1)
