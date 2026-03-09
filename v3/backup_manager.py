# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v3.1.0 Backup Manager

DB、設定、テンプレートをZIP形式でバックアップ・復元する機能を提供。
"""

import shutil
import zipfile
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv3"


class BackupManager:
    """バックアップと復元を管理するクラス"""

    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir)
        self.backup_dir = self.base_dir / "backup"
        self.data_dir = self.base_dir / "data"
        self.templates_dir = self.base_dir / "templates"
        self.images_dir = self.base_dir / "images"
        self.settings_file = self.base_dir / "settings.env"

        # バックアップディレクトリの作成
        self.backup_dir.mkdir(exist_ok=True)

    def create_backup(
        self, include_images: bool = False, exclude_secrets: bool = False
    ) -> Tuple[bool, str]:
        """
        現在の状態をZIPファイルにバックアップ

        Args:
            include_images: 画像フォルダを含めるか
            exclude_secrets: (未実装) APIキーなどを除外するか

        Returns:
            (成功フラグ, メッセージ/パス)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"streamnotify_backup_{timestamp}.zip"
        backup_path = self.backup_dir / backup_filename

        try:
            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                # 1. データベース
                if self.data_dir.exists():
                    for file in self.data_dir.glob("*.db"):
                        zipf.write(file, arcname=f"data/{file.name}")
                    # json (除外リストなど) も含める
                    for file in self.data_dir.glob("*.json"):
                        zipf.write(file, arcname=f"data/{file.name}")

                # 2. 設定ファイル
                if self.settings_file.exists():
                    # TODO: exclude_secrets が True の場合の処理 (今回は単純コピー)
                    zipf.write(self.settings_file, arcname="settings.env")

                # 3. テンプレート
                if self.templates_dir.exists():
                    for file in self.templates_dir.rglob("*"):
                        if file.is_file():
                            zipf.write(
                                file,
                                arcname=f"templates/{file.relative_to(self.templates_dir)}",
                            )

                # 4. 画像 (オプション)
                if include_images and self.images_dir.exists():
                    for file in self.images_dir.rglob("*"):
                        if file.is_file():
                            zipf.write(
                                file,
                                arcname=f"images/{file.relative_to(self.images_dir)}",
                            )

            logger.info(f"✅ バックアップ作成完了: {backup_path}")
            return True, str(backup_path)

        except Exception as e:
            logger.error(f"❌ バックアップ作成エラー: {e}")
            return False, str(e)

    def restore_backup(self, backup_zip_path: str) -> Tuple[bool, str]:
        """
        ZIPファイルから復元

        Args:
            backup_zip_path: バックアップZIPファイルのパス

        Returns:
            (成功フラグ, メッセージ)
        """
        backup_zip = Path(backup_zip_path)
        if not backup_zip.exists():
            return False, "バックアップファイルが見つかりません"

        # 復元前の自動バックアップ (フェイルセーフ)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        restore_point_dir = self.backup_dir / f"restore_point_{timestamp}"

        try:
            # 現在のファイルを一時退避
            self._create_restore_point(restore_point_dir)

            # ZIPを展開して上書き
            with zipfile.ZipFile(backup_zip, "r") as zipf:
                zipf.extractall(self.base_dir)

            logger.info(f"✅ 復元完了: {backup_zip_path}")
            return True, "復元が完了しました。アプリケーションを再起動してください。"

        except Exception as e:
            logger.error(f"❌ 復元エラー: {e}")
            # エラー時は復元ポイントから戻すことを試みる (簡易実装ではログのみ)
            logger.warning(
                f"⚠️ 復元ポイント {restore_point_dir} からの手動復旧が必要な場合があります"
            )
            return False, str(e)

    def _create_restore_point(self, target_dir: Path):
        """復元前の現在状態を退避"""
        target_dir.mkdir(parents=True, exist_ok=True)

        # 主要ファイルをコピー
        if self.settings_file.exists():
            shutil.copy2(self.settings_file, target_dir / "settings.env")

        if self.data_dir.exists():
            shutil.copytree(self.data_dir, target_dir / "data", dirs_exist_ok=True)

        # テンプレートなども必要なら退避 (今回は最小限)

    def get_backup_list(self) -> List[Path]:
        """バックアップファイル一覧を取得 (新しい順)"""
        if not self.backup_dir.exists():
            return []

        backups = list(self.backup_dir.glob("*.zip"))
        backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return backups


if __name__ == "__main__":
    # テスト実行
    mgr = BackupManager()
    print("Backup Manager Test")
    # success, path = mgr.create_backup()
    # print(f"Backup Result: {success}, {path}")
