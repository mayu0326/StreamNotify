# -*- coding: utf-8 -*-

"""
v4 アセット自動配置マネージャー
Asset/ ディレクトリからテンプレート・画像を自動配置する機能を提供。
"""

import os
import shutil
import logging
from pathlib import Path
from v4.core.config import settings

logger = logging.getLogger("v4.core.asset_manager")

class AssetManager:
    """Asset ディレクトリからファイルを自動配置・同期"""

    def __init__(self, asset_dir="Asset"):
        self.base_dir = settings.v4_dir
        self.asset_dir = settings.v4_dir / asset_dir

        self.templates_src = self.asset_dir / "templates"
        self.images_src = self.asset_dir / "images"

        self.templates_dest = self.base_dir / "templates"
        self.images_dest = self.base_dir / "images"

    def _ensure_dest_dir(self, dest_path: Path) -> bool:
        try:
            if not dest_path.exists():
                dest_path.mkdir(parents=True, exist_ok=True)
                logger.debug(f"ディレクトリを作成しました: {dest_path}")
            return True
        except Exception as e:
            logger.warning(f"ディレクトリ作成失敗 {dest_path}: {e}")
            return False

    def _copy_file(self, src: Path, dest: Path) -> int:
        """ファイルをコピー（既存ファイルは上書きしない）"""
        try:
            if dest.exists():
                return 0

            self._ensure_dest_dir(dest.parent)
            shutil.copy2(src, dest)
            logger.debug(f"✅ ファイルをコピーしました: {src.name} -> {dest}")
            return 1
        except Exception as e:
            logger.warning(f"ファイルコピー失敗 {src} -> {dest}: {e}")
            return -1

    def deploy_all(self) -> dict:
        """すべてのテンプレート・画像をコピー"""
        logger.debug("🚀 アセットの自動配置を開始します...")

        counts = {"templates": 0, "images": 0}

        # Deploy Templates
        if self.templates_src.exists():
            for service in ["default", "youtube", "niconico", "twitch"]:
                src_service = self.templates_src / service
                dest_service = self.templates_dest / service
                if src_service.exists():
                    for item in src_service.rglob("*.txt"):
                        rel_path = item.relative_to(src_service)
                        if self._copy_file(item, dest_service / rel_path) == 1:
                            counts["templates"] += 1

        # Deploy Images
        if self.images_src.exists():
            for item in self.images_src.rglob("*"):
                if item.is_file():
                    rel_path = item.relative_to(self.images_src)
                    if self._copy_file(item, self.images_dest / rel_path) == 1:
                        counts["images"] += 1

        total_deployed = sum(counts.values())
        if total_deployed > 0:
            logger.info(f"✅ アセット配置完了: テンプレート {counts['templates']} 個、画像 {counts['images']} 個")
        else:
            logger.debug("アセットの自動配置: 新規ファイルのコピーはありませんでした。")

        return counts

def sync_assets():
    """便利関数: アセット同期を実行"""
    manager = AssetManager()
    return manager.deploy_all()
