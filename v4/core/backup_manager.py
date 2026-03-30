# -*- coding: utf-8 -*-

"""
v4 バックアップ管理マネージャー
データベース、設定、テンプレート、画像を一括バックアップ・復元する機能を提供。
"""

import os
import shutil
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from v4.core.config import settings

logger = logging.getLogger("v4.core.backup_manager")

class BackupManager:
    """システムデータの一括バックアップと復元"""

    def __init__(self, backup_dir="backups"):
        self.base_dir = settings.base_dir
        self.v4_dir = settings.v4_dir
        self.backup_dir = self.v4_dir / backup_dir
        self._ensure_dir(self.backup_dir)

    def _ensure_dir(self, path: Path):
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)

    def create_backup(self, include_images=False, include_env=True, include_api_keys=False, include_passwords=False) -> Optional[Path]:
        """現在のデータをZIPアーカイブにバックアップ

        Args:
            include_images (bool): 画像フォルダを含めるか
            include_env (bool): 設定ファイルを含めるか
            include_api_keys (bool): APIキーを含めるか (Falseの場合はマスク)
            include_passwords (bool): パスワードを含めるか (Falseの場合はマスク)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = self.backup_dir / f"backup_v4_{timestamp}.zip"

        # 一時ファイルのリスト（クリーンアップ用）
        temp_files = []

        try:
            with zipfile.ZipFile(backup_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 1. Database
                db_path = settings.data_dir / "client_v4.db"
                if db_path.exists():
                    zf.write(db_path, "client_v4.db")

                for fname in ("youtube_channel_cache.json", "youtube_video_detail_cache.json"):
                    cache_path = settings.data_dir / fname
                    if cache_path.exists():
                        zf.write(cache_path, f"v4/data/{fname}")

                # 2. Templates
                template_dir = self.v4_dir / "templates"
                if template_dir.exists():
                    for item in template_dir.rglob("*"):
                        if item.is_file():
                            zf.write(item, item.relative_to(self.base_dir))

                # 3. Settings (Optional with Security Filters)
                if include_env:
                    env_file = self.v4_dir / "settings.env"
                    if env_file.exists():
                        if include_api_keys and include_passwords:
                            # フィルタなしでそのまま追加
                            zf.write(env_file, "v4/settings.env")
                        else:
                            # フィルタリング適用
                            filtered_env_path = self.backup_dir / f"settings_filtered_{timestamp}.env"
                            self._create_filtered_env(env_file, filtered_env_path, include_api_keys, include_passwords)
                            zf.write(filtered_env_path, "v4/settings.env")
                            temp_files.append(filtered_env_path)

                # 4. Images (Optional) — v4/images（ZIP 内は v4/images/...）
                if include_images:
                    image_dir = self.v4_dir / "images"
                    if image_dir.exists():
                        for item in image_dir.rglob("*"):
                            if item.is_file():
                                zf.write(item, item.relative_to(self.base_dir))

            logger.info(f"✅ バックアップを作成しました: {backup_file.name}")
            return backup_file

        except Exception as e:
            logger.error(f"❌ バックアップ作成失敗: {e}")
            if backup_file.exists():
                backup_file.unlink()
            return None

        finally:
            # 一時ファイルの削除
            for tf in temp_files:
                try:
                    if tf.exists():
                        tf.unlink()
                except Exception as e:
                    logger.warning(f"一時ファイル削除失敗: {e}")

    def _create_filtered_env(self, source_path: Path, dest_path: Path, include_keys: bool, include_passwords: bool):
        """設定ファイルを読み込み、機密情報をマスクして保存"""

        # マスク対象のキー定義
        API_KEYS = {'YOUTUBE_API_KEY', 'WEBSUB_CLIENT_API_KEY', 'TWITCH_CLIENT_ID', 'TWITCH_CLIENT_SECRET'}
        PASSWORDS = {'BLUESKY_PASSWORD', 'NICONICO_PASSWORD', 'DB_PASSWORD'}
        # ※ DB_PASSWORD等は現状ないかもしれないが念のため

        lines = []
        with open(source_path, 'r', encoding='utf-8') as f_in:
            for line in f_in:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    lines.append(line)
                    continue

                key, value = line.split('=', 1)
                key = key.strip()

                # APIキーのフィルタリング
                if not include_keys and key in API_KEYS:
                    lines.append(f"{key}=") # 空にするか、'<REDACTED>'にするか。ここでは空文字
                # パスワードのフィルタリング
                elif not include_passwords and key in PASSWORDS:
                    lines.append(f"{key}=")
                else:
                    lines.append(line)

        with open(dest_path, 'w', encoding='utf-8') as f_out:
            f_out.write("\n".join(lines))

    def restore_backup(self, backup_zip_path: Path) -> Tuple[bool, str]:
        """バックアップファイルからデータを復元"""
        backup_zip_path = Path(backup_zip_path)
        if not backup_zip_path.exists():
            return False, "バックアップファイルが見つかりません"

        # バックアップのバックアップ（念のため）
        try:
            current_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            auto_backup = self.create_backup(include_images=False, include_env=True)
            if auto_backup:
                logger.info(f"復元前の自動バックアップを作成しました: {auto_backup}")
        except Exception as e:
            logger.warning(f"復元前の自動バックアップに失敗: {e}")

        # 復元処理
        temp_extract_dir = self.backup_dir / "temp_extract"
        if temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir)
        temp_extract_dir.mkdir(exist_ok=True)

        try:
            with zipfile.ZipFile(backup_zip_path, 'r') as zf:
                zf.extractall(temp_extract_dir)

            # 1. Database (client_v4.db)
            db_source = temp_extract_dir / "client_v4.db"
            if db_source.exists():
                db_dest = settings.data_dir / "client_v4.db"
                # DB接続を閉じる確証がないため、shutil.copy2 で上書き試行
                shutil.copy2(db_source, db_dest)
                logger.info("Database restored.")

            settings.data_dir.mkdir(parents=True, exist_ok=True)
            for fname in ("youtube_channel_cache.json", "youtube_video_detail_cache.json"):
                cache_src = temp_extract_dir / "v4" / "data" / fname
                if cache_src.exists():
                    shutil.copy2(cache_src, settings.data_dir / fname)
                    logger.info("YouTube API cache restored: %s", fname)

            # 2. Templates (v4/templates)
            tpl_source = temp_extract_dir / "v4" / "templates"
            # ZIP構造によっては v4/templates ではなく templates 直下かもしれない
            if not tpl_source.exists() and (temp_extract_dir / "templates").exists():
                 tpl_source = temp_extract_dir / "templates"

            if tpl_source.exists():
                tpl_dest = self.v4_dir / "templates"
                if tpl_dest.exists():
                    shutil.rmtree(tpl_dest)
                shutil.copytree(tpl_source, tpl_dest)
                logger.info("Templates restored.")

            # 3. Settings (v4/settings.env)
            env_source = temp_extract_dir / "v4" / "settings.env"
            if env_source.exists():
                env_dest = self.v4_dir / "settings.env"
                if env_dest.exists():
                    # 既存の設定を少し読んでAPIキーなどがないか確認したほうがいいかもしれないが
                    # 今回は上書き
                    pass
                shutil.copy2(env_source, env_dest)
                logger.info("Settings restored.")

            # 4. Images（v4/images。旧 ZIP はリポジトリ直下 images/ のみの場合あり）
            img_source = temp_extract_dir / "v4" / "images"
            if not img_source.exists():
                img_source = temp_extract_dir / "images"
            if img_source.exists():
                img_dest = self.v4_dir / "images"
                # 画像はマージするか、置換するか... 置換が無難
                if img_dest.exists():
                    # 全削除は怖いので上書きコピー
                    pass
                else:
                    img_dest.mkdir()

                # copytree with dirs_exist_ok=True (Python 3.8+)
                shutil.copytree(img_source, img_dest, dirs_exist_ok=True)
                logger.info("Images restored.")

            return True, "復元が完了しました。\n設定を反映するため、アプリケーションを再起動してください。"

        except Exception as e:
            logger.error(f"復元エラー: {e}")
            return False, f"復元中にエラーが発生しました: {e}"
        finally:
            # クリーンアップ
            if temp_extract_dir.exists():
                shutil.rmtree(temp_extract_dir)

    def list_backups(self) -> list:
        """作成済みのバックアップ一覧を取得"""
        if not self.backup_dir.exists():
            return []
        backups = sorted(self.backup_dir.glob("*.zip"), key=os.path.getmtime, reverse=True)
        return backups

def run_backup():
    """便利関数: デフォルト設定でバックアップを実行"""
    manager = BackupManager()
    return manager.create_backup()

def run_restore(zip_path: str):
    """便利関数: 復元実行"""
    manager = BackupManager()
    return manager.restore_backup(Path(zip_path))
