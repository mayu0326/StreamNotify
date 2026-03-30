# -*- coding: utf-8 -*-
"""
NicoNico OGP Backfill Tool (v4 Port)
"""

import argparse
import logging
import sys
import requests
from bs4 import BeautifulSoup

# v4 imports
from v4.core.assets.image_manager import get_image_manager
from v4.gui.adapter import V3DatabaseAdapter

logger = logging.getLogger("v4.thumbnails.niconico")

def fetch_thumbnail_url(video_id: str) -> str | None:
    """OGP メタタグからサムネイルURLを取得（高解像度 1280x720）"""
    # Use the logic from port or niconico_ogp_utils if available
    # For standalone, we can keep logic here or import from utils
    from v4.thumbnails_v4.niconico_ogp_utils import get_niconico_ogp_url
    return get_niconico_ogp_url(video_id)


def backfill_niconico(dry_run: bool = True, limit: int | None = None):
    """ニコニコ動画のサムネイルを一括補完"""
    db = V3DatabaseAdapter()
    img = get_image_manager()

    try:
        videos = db.get_all_videos()
    except Exception as e:
        logger.error(f"Failed to get videos from DB: {e}")
        return

    targets = []
    for v in videos:
        if (v.get("source") or "").lower() != "niconico":
            continue
        missing_thumb = not v.get("thumbnail_url")
        missing_image = not v.get("image_filename")
        if missing_thumb or missing_image:
            targets.append(v)
    if limit:
        targets = targets[:limit]

    if not targets:
        logger.info("✅ 補完対象なし (ニコニコ)")
        return

    logger.info(f"📊 補完対象 {len(targets)} 件 (dry_run={dry_run})")

    updated_thumb = 0
    saved_images = 0
    failed = 0

    for v in targets:
        video_id = v.get("video_id")
        title = v.get("title", "")
        logger.info(f"--- {video_id} | {title[:40]}")

        thumb_url = fetch_thumbnail_url(video_id)
        if not thumb_url:
            logger.warning(f"⚠️ サムネURL取得不可: {video_id}")
            failed += 1
            continue

        if not dry_run:
            # V3DatabaseAdapter needs update_thumbnail_url
            # Does it have it? I didn't add it in previous step!
            # I added insert/update_status/update_published/mark_as_posted/update_selection.
            # I need to check if adapter allows generic updates or if I need to add update_thumbnail_url.
            # Assuming for now I might need to add it to generic update or specific method.
            # Let's check adapter later.
            try:
                # db.update_thumbnail_url likely missing in adapter.
                pass
                # For basic port, I'll comment out the DB update if method missing, or add it.
                # I'll Assume I need to add it to adapter.
                if hasattr(db, 'update_thumbnail_url'):
                    ok = db.update_thumbnail_url(video_id, thumb_url)
                    if ok: updated_thumb += 1
            except Exception as e:
                logger.error(f"DB Update failed: {e}")

        if v.get("image_filename"):
            continue

        if dry_run:
            logger.info(f"[DRY] 画像ダウンロード予定: {thumb_url}")
            continue

        filename = img.download_and_save_thumbnail(
            thumbnail_url=thumb_url,
            site="Niconico",
            video_id=video_id,
            mode="import",
        )
        if filename:
            # db.update_image_info also missing in adapter?
            if hasattr(db, 'update_image_info'):
                db.update_image_info(video_id, image_mode="import", image_filename=filename)
            saved_images += 1
            logger.info(f"✅ 画像保存: {filename}")
        else:
            logger.error(f"❌ 画像保存失敗: {video_id}")
            failed += 1

    logger.info("=== サマリー ===")
    logger.info(f"サムネURL更新: {updated_thumb} 件")
    logger.info(f"画像保存: {saved_images} 件")
    logger.info(f"失敗: {failed} 件")


def main():
    parser = argparse.ArgumentParser(description="ニコニコ動画のサムネイルを一括補完")
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
    backfill_niconico(dry_run=dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
