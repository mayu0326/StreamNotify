# -*- coding: utf-8 -*-
"""
Stream notify on Bluesky - v3 画像再取得ツール

データベース内の画像が設定されていない動画について、
thumbnail_urlから画像を再ダウンロードして保存します。

使い方:
    # ドライラン（更新なし、ログのみ）
    python -m thumbnails.image_re_fetch_module

    # 実行（実際にダウンロード）
    python -m thumbnails.image_re_fetch_module --execute

オプション:
    --execute   : 実際にダウンロードを実行
    --verbose   : 詳細ログを表示
"""


import sys
import logging
import os
from pathlib import Path

# v3ルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

# ログディレクトリを事前に作成
Path("logs").mkdir(exist_ok=True)

from database import get_database
from image_manager import get_image_manager, get_youtube_thumbnail_url
from .niconico_ogp_utils import get_niconico_ogp_url

# ThumbnailsLogger（logging_plugin.pyで設定管理）
logger = logging.getLogger("ThumbnailsLogger")

def redownload_missing_images(dry_run: bool = False):
    """
    画像が設定されていない動画のサムネイルを再ダウンロード

    Args:
        dry_run: Trueの場合、実際のダウンロードは行わず、対象のみ表示
    """
    db = get_database()
    img_manager = get_image_manager()

    # 画像なし動画を取得
    videos = db.get_videos_without_image()
    
    if not videos:
        logger.info("✅ すべての動画に画像が設定されています")
        return

    logger.info(f"📊 画像なし動画: {len(videos)}件")
    print(f"\n{'='*60}")
    print(f"画像未設定の動画: {len(videos)}件")
    print(f"{'='*60}\n")

    success_count = 0
    skip_count = 0
    error_count = 0

    for i, video in enumerate(videos, 1):
        video_id = video["video_id"]
        title = video["title"]
        source = (video["source"] or "youtube").lower()
        thumbnail_url = video["thumbnail_url"]

        # YouTube は最新の高品質サムネイルを再取得
        if source == "youtube":
            best_url = get_youtube_thumbnail_url(video_id)
            if best_url:
                thumbnail_url = best_url
                logger.info(f"✅ YouTube サムネイル再取得: {video_id}")
        
        # ニコニコはOGPから最新URLを再取得して利用
        elif source == "niconico":
            ogp_url = get_niconico_ogp_url(video_id)
            if ogp_url:
                thumbnail_url = ogp_url
                logger.info(f"✅ ニコニコ OGP 再取得: {video_id}")

        print(f"[{i}/{len(videos)}] {title}")
        print(f"  ID: {video_id}")
        print(f"  Source: {source}")
        print(f"  URL: {thumbnail_url}")

        if dry_run:
            print(f"  → [DRY RUN] ダウンロード対象\n")
            continue

        # サムネイルをダウンロード
        filename = img_manager.download_and_save_thumbnail(
            thumbnail_url=thumbnail_url,
            site=source.capitalize(),
            video_id=video_id,
            mode="autopost"
        )

        if filename:
            # データベースを更新
            success = db.update_image_info(
                video_id=video_id,
                image_mode="autopost",
                image_filename=filename
            )
            
            if success:
                print(f"  ✅ 成功: {filename}\n")
                success_count += 1
            else:
                print(f"  ⚠️ ダウンロード成功、DB更新失敗\n")
                error_count += 1
        else:
            print(f"  ❌ ダウンロード失敗\n")
            error_count += 1

    # サマリー表示
    print(f"\n{'='*60}")
    print("処理結果:")
    print(f"  成功: {success_count}件")
    print(f"  スキップ: {skip_count}件")
    print(f"  失敗: {error_count}件")
    print(f"{'='*60}\n")

    if dry_run:
        print("※ DRY RUN モードで実行されました。実際の変更は行われていません。")
        print("  実行するには --execute オプションを使用してください。\n")


def main():
    """メイン処理"""
    import argparse

    parser = argparse.ArgumentParser(
        description="データベース内の画像未設定動画のサムネイルを再ダウンロード"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="実際にダウンロードを実行（指定しない場合はDRY RUN）"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="詳細ログを表示"
    )

    args = parser.parse_args()


    # --verbose指定時はDEBUGを優先
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    dry_run = not args.execute

    if dry_run:
        print("\n" + "="*60)
        print("DRY RUN モード - 変更は行われません")
        print("="*60 + "\n")
    

    try:
        redownload_missing_images(dry_run=dry_run)
    except KeyboardInterrupt:
        print("\n\n⚠️ ユーザーによって中断されました")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ エラーが発生しました: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

