# -*- coding: utf-8 -*-
"""
YouTube Thumbnail Backfill Tool (v4 Port)
"""

import argparse
import logging
import sys

# v4 imports
from v4.core.assets.image_manager import get_image_manager, get_youtube_thumbnail_url
from v4.gui.adapter import V3DatabaseAdapter

logger = logging.getLogger("v4.thumbnails.youtube")

def backfill_youtube(dry_run: bool = True, limit: int | None = None):
    """YouTube動画のサムネイルを一括補完"""
    db = V3DatabaseAdapter()
    img = get_image_manager()

    try:
        videos = db.get_all_videos()
    except Exception as e:
        logger.error(f"Failed to get videos from DB: {e}")
        return

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

        thumb_url = get_youtube_thumbnail_url(video_id)
        if not thumb_url:
            logger.warning(f"[WARNING] サムネURL取得不可: {video_id}")
            failed += 1
            continue

        if not dry_run:
            if hasattr(db, 'update_thumbnail_url'):
                try:
                    ok = db.update_thumbnail_url(video_id, thumb_url)
                    if ok: updated_thumb += 1
                except Exception as e:
                    logger.error(f"DB update failed: {e}")

        if v.get("image_filename"):
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
            if hasattr(db, 'update_image_info'):
                try:
                    db.update_image_info(video_id, image_mode="import", image_filename=filename)
                except Exception as e:
                    logger.error(f"DB update image failed: {e}")
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

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    dry_run = not args.execute
    backfill_youtube(dry_run=dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
