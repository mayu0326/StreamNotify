# -*- coding: utf-8 -*-
"""
YouTube動画のサムネイルURLと画像を一括補完するツール。
- DB上で source='youtube' かつ thumbnail_url が空、または image_filename が空のレコードを対象
- get_youtube_thumbnail_url() で多品質フォールバック（maxresdefault → sddefault → hqdefault → mqdefault → default）
- 画像をダウンロードして images/YouTube/import に保存
- DBの thumbnail_url / image_mode / image_filename を更新

使い方:
    # ドライラン（更新なし、ログのみ）
    python -m thumbnails.youtube_thumb_backfill

    # 実行（DB更新と画像保存を行う）
    python -m thumbnails.youtube_thumb_backfill --execute

オプション:
    --limit N   : 最大 N 件に制限
    --verbose   : DEBUG ログを出力
"""

import argparse
import logging
import sys
from pathlib import Path

# v2ルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_database
from image_manager import get_image_manager, get_youtube_thumbnail_url

logger = logging.getLogger(__name__)


def backfill_youtube(dry_run: bool = True, limit: int | None = None):
    """YouTube動画のサムネイルを一括補完"""
    db = get_database()
    img = get_image_manager()

    videos = db.get_all_videos()
    targets = []
    for v in videos:
        if (v.get("source") or "").lower() != "youtube":
            continue
        missing_thumb = not v.get("thumbnail_url")
        missing_image = not v.get("image_filename")
        if missing_thumb or missing_image:
            targets.append(v)
    if limit:
        targets = targets[:limit]

    if not targets:
        logger.info("[OK] 補完対象なし (YouTube)")
        return

    logger.info(f"[SUMMARY] 補完対象 {len(targets)} 件 (dry_run={dry_run})")

    updated_thumb = 0
    saved_images = 0
    failed = 0

    for v in targets:
        video_id = v.get("video_id")
        title = v.get("title", "")
        logger.info(f"--- {video_id} | {title[:40]}")

        # バックフィル用: 既存URLにかかわらず、常に高品質URLを取得
        thumb_url = get_youtube_thumbnail_url(video_id)
        if not thumb_url:
            logger.warning(f"[WARNING] サムネURL取得不可: {video_id}")
            failed += 1
            continue

        if not dry_run:
            ok = db.update_thumbnail_url(video_id, thumb_url)
            if ok:
                updated_thumb += 1

        # 画像ダウンロード（image_filename が未設定の場合）
        if v.get("image_filename"):
            logger.debug("画像は既に設定済み、スキップ")
            continue

        if dry_run:
            logger.info(f"[DRY] 画像ダウンロード予定: {thumb_url}")
            continue

        filename = img.download_and_save_thumbnail(
            thumbnail_url=thumb_url,
            site="YouTube",
            video_id=video_id,
            mode="import",
        )
        if filename:
            db.update_image_info(video_id, image_mode="import", image_filename=filename)
            saved_images += 1
            logger.info(f"[OK] 画像保存: {filename}")
        else:
            logger.error(f"[ERROR] 画像保存失敗: {video_id}")
            failed += 1

    logger.info("=== SUMMARY ===")
    logger.info(f"サムネURL更新: {updated_thumb} 件")
    logger.info(f"画像保存: {saved_images} 件")
    logger.info(f"失敗: {failed} 件")


def main():
    parser = argparse.ArgumentParser(description="YouTube動画のサムネイルを一括補完")
    parser.add_argument("--execute", action="store_true", help="実際に更新を行う")
    parser.add_argument("--limit", type=int, default=None, help="最大処理件数")
    parser.add_argument("--verbose", action="store_true", help="DEBUGログを表示")
    args = parser.parse_args()

    # ロギング設定（UTF-8対応）
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        handlers=[handler],
    )

    dry_run = not args.execute
    backfill_youtube(dry_run=dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
