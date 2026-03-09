# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - プラグインマネージャー

プラグインの動的な読み込み、管理、実行を担当します。
"""

import sys
import logging
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from plugin_interface import NotificationPlugin

logger = logging.getLogger("AppLogger")
post_error_logger = logging.getLogger("PostErrorLogger")
post_logger = logging.getLogger("PostLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


class PluginManager:
    """プラグインを管理するクラス"""

    def __init__(self, plugins_dir: str = "plugins"):
        """
        初期化

        Args:
            plugins_dir: プラグインディレクトリのパス
        """
        self.plugins_dir = Path(plugins_dir)
        self.loaded_plugins: Dict[str, NotificationPlugin] = {}
        self.enabled_plugins: Dict[str, NotificationPlugin] = {}

    def discover_plugins(self) -> List[Tuple[str, str]]:
        """
        プラグインディレクトリからプラグインを検出

        検出条件:
        1. ファイル名が "_" で始まらない
        2. NotificationPlugin を継承したクラスが定義されている

        検出対象:
        - plugins/*.py (ルートレベルプラグイン)
        - plugins/*/plugin_name.py (パッケージプラグイン、youtube など)

        Returns:
            List[Tuple[str, str]]: (プラグイン名, ファイルパス) のリスト
        """
        if not self.plugins_dir.exists():
            logger.warning(f"プラグインディレクトリが存在しません: {self.plugins_dir}")
            return []

        plugins = []

        # 1. ルートレベルのプラグイン (plugins/*.py)
        for file_path in self.plugins_dir.glob("*.py"):
            if file_path.name.startswith("_"):
                continue

            plugin_name = file_path.stem

            # ★ 事前チェック: NotificationPlugin を継承したクラスが定義されているか
            if not self._is_valid_plugin_file(file_path, plugin_name):
                logger.debug(
                    f"⏭️  スキップ: {plugin_name} (NotificationPlugin 非実装の内部モジュール)"
                )
                continue

            plugins.append((plugin_name, str(file_path)))
            logger.info(f"📦 プラグイン検出: {plugin_name} ({file_path})")

        # 2. サブディレクトリ内のプラグイン (plugins/*/plugin_name.py)
        # 対象: youtube/youtube_api_plugin.py など
        for subdir in self.plugins_dir.iterdir():
            if not subdir.is_dir() or subdir.name.startswith("_"):
                continue

            # サブディレクトリ内で plugins_name.py の形式を探す
            # 例: youtube/ の中で youtube_api_plugin.py
            subdir_name = subdir.name
            for file_path in subdir.glob("*.py"):
                if file_path.name.startswith("_"):
                    continue

                # プラグイン名: youtube/youtube_api_plugin.py → youtube_api_plugin
                plugin_name = file_path.stem

                # 同じ名前の file_path がルートに存在しないかチェック
                if (self.plugins_dir / f"{plugin_name}.py").exists():
                    continue

                # ★ 事前チェック: NotificationPlugin を継承したクラスが定義されているか
                if not self._is_valid_plugin_file(file_path, plugin_name):
                    logger.debug(
                        f"⏭️  スキップ: {plugin_name} (NotificationPlugin 非実装)"
                    )
                    continue

                plugins.append((plugin_name, str(file_path)))
                logger.info(f"📦 プラグイン検出: {plugin_name} ({file_path})")

        return plugins

    def _is_valid_plugin_file(self, file_path: Path, plugin_name: str) -> bool:
        """
        ファイルが有効なプラグイン実装かどうかを判定（軽量チェック）

        実装内容:
        1. ファイルをテキストで読み込む（ロードなし）
        2. "class " と "NotificationPlugin" がファイル内に存在するかを確認
        3. "class XXX(NotificationPlugin)" パターンを検出

        Args:
            file_path: ファイルパス
            plugin_name: プラグイン名

        Returns:
            bool: 有効なプラグイン実装の場合 True
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # ★ 条件: NotificationPlugin を継承したクラスが定義されている
            # 簡易判定: "class " と "NotificationPlugin" キーワードが同時に存在
            has_class_def = "class " in content
            has_notification_plugin = "NotificationPlugin" in content

            # より厳密: "class XXX(NotificationPlugin" パターンを検出
            import re

            has_plugin_class = bool(
                re.search(r"class\s+\w+\([^)]*NotificationPlugin[^)]*\)", content)
            )

            is_valid = has_class_def and has_plugin_class

            if not is_valid:
                logger.debug(
                    f"⏭️  {plugin_name}: NotificationPlugin 継承クラスが見つかりません"
                )

            return is_valid

        except Exception as e:
            logger.warning(f"⚠️  プラグイン事前チェック失敗 {plugin_name}: {e}")
            # エラー時は false として、スキップ
            return False

    def load_plugin(
        self, plugin_name: str, plugin_path: str
    ) -> Optional[NotificationPlugin]:
        """
        プラグインを動的に読み込む

        Args:
            plugin_name: プラグイン名
            plugin_path: プラグインファイルのパス

        Returns:
            NotificationPlugin: ロードされたプラグイン、失敗時は None
        """
        try:
            # ファイル存在確認
            plugin_file = Path(plugin_path)
            if not plugin_file.exists():
                logger.warning(
                    f"⏭️  プラグイン '{plugin_name}' をスキップします（ファイルが見つかりません: {plugin_path}）"
                )
                return None

            # すでに同名プラグインがロード済みなら何もしない（重複ログ防止）
            if plugin_name in self.loaded_plugins:
                return self.loaded_plugins[plugin_name]

            # モジュールをダイナミックロード
            spec = importlib.util.spec_from_file_location(plugin_name, plugin_path)
            if spec is None or spec.loader is None:
                logger.error(f"❌ プラグイン {plugin_name} のロード失敗: spec が None")
                return None

            module = importlib.util.module_from_spec(spec)
            # 完全なモジュールパスで sys.modules に登録（plugins.* パターンに対応）
            full_module_name = f"plugins.{plugin_name}"
            sys.modules[full_module_name] = module
            sys.modules[plugin_name] = module  # 短い名前でもアクセス可能に
            spec.loader.exec_module(module)

            # NotificationPlugin を実装しているクラスを探す
            # importされたクラスではなく、このモジュール内で定義されたクラスのみを対象
            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, NotificationPlugin)
                    and attr is not NotificationPlugin
                    and attr.__module__ == plugin_name
                ):  # このモジュール内で定義されたクラスのみ
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"🔍 発見したクラス: {attr.__name__} in {plugin_name}"
                        )
                    plugin_class = attr
                    break

            if plugin_class is None:
                logger.error(
                    f"❌ プラグイン {plugin_name}: NotificationPlugin を実装したクラスが見つかりません"
                )
                return None

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"🔍 インスタンス生成: {plugin_class.__name__}")

            # すでに同じクラスのインスタンスがロード済みなら再利用（シングルトン対応）
            # 既存インスタンスがあっても、必ず新しいインスタンスを生成し、
            # プラグイン名ごとに登録・ログ出力する
            plugin = plugin_class()
            self.loaded_plugins[plugin_name] = plugin
            return plugin

        except Exception as e:
            logger.error(
                f"❌ プラグイン {plugin_name} のロード失敗: {e}", exc_info=True
            )
            return None

    def load_plugins_from_directory(self) -> int:
        """
        プラグインディレクトリからすべてのプラグインをロード

        Returns:
            int: ロード成功したプラグイン数
        """
        plugins = self.discover_plugins()
        loaded_count = 0

        for plugin_name, plugin_path in plugins:
            plugin = self.load_plugin(plugin_name, plugin_path)
            if plugin:
                loaded_count += 1

        logger.info(f"✅ プラグイン有効化完了: {loaded_count}/{len(plugins)} 個成功")
        return loaded_count

    def enable_plugin(self, plugin_name: str) -> bool:
        """
        プラグインを有効化

        Args:
            plugin_name: プラグイン名

        Returns:
            bool: 成功時 True、失敗時 False
        """
        # 既に有効化済みなら何もしない（重複ログ防止）
        if plugin_name in self.enabled_plugins:
            return True

        if plugin_name not in self.loaded_plugins:
            logger.error(f"❌ プラグイン {plugin_name} は読み込まれていません")
            return False

        plugin = self.loaded_plugins[plugin_name]

        try:
            if plugin.is_available():
                self.enabled_plugins[plugin_name] = plugin
                plugin.on_enable()
                logger.info(
                    f"✅ プラグイン有効化完了: {plugin.get_name()} v{plugin.get_version()}"
                )
                return True
            else:
                logger.warning(f"⚠️  プラグイン {plugin_name} は利用不可です")
                return False
        except Exception as e:
            logger.error(
                f"❌ プラグイン {plugin_name} の有効化失敗: {e}", exc_info=True
            )
            return False

    def disable_plugin(self, plugin_name: str) -> bool:
        """
        プラグインを無効化

        Args:
            plugin_name: プラグイン名

        Returns:
            bool: 成功時 True、失敗時 False
        """
        if plugin_name not in self.enabled_plugins:
            logger.warning(f"⚠️  プラグイン {plugin_name} は有効化されていません")
            return False

        plugin = self.enabled_plugins.pop(plugin_name)

        try:
            plugin.on_disable()
            return True
        except Exception as e:
            logger.error(
                f"❌ プラグイン {plugin_name} の無効化エラー: {e}", exc_info=True
            )
            return False

    def get_enabled_plugins(self) -> Dict[str, NotificationPlugin]:
        """
        有効なプラグイン一覧を取得

        Returns:
            Dict[str, NotificationPlugin]: 有効なプラグイン
        """
        return self.enabled_plugins.copy()

    def get_loaded_plugins(self) -> Dict[str, NotificationPlugin]:
        """
        ロード済みプラグイン一覧を取得

        Returns:
            Dict[str, NotificationPlugin]: ロード済みプラグイン
        """
        return self.loaded_plugins.copy()

    def get_plugin(self, plugin_name: str) -> Optional[NotificationPlugin]:
        """
        指定されたプラグインを取得

        Args:
            plugin_name: プラグイン名

        Returns:
            NotificationPlugin: プラグイン（見つからない場合は None）
        """
        return self.enabled_plugins.get(plugin_name) or self.loaded_plugins.get(
            plugin_name
        )

    def post_video_with_all_enabled(
        self, video: dict, dry_run: bool = False
    ) -> Dict[str, bool]:
        """
        すべての有効なプラグインで動画をポスト

        Args:
            video: 動画情報
            dry_run: ドライランモード（True の場合は実際には投稿しない）

        Returns:
            Dict[str, bool]: {プラグイン名: 成功/失敗}
        """
        results = {}

        for plugin_name, plugin in self.enabled_plugins.items():
            try:
                # ★ dry_run フラグをプラグインに設定
                if hasattr(plugin, "set_dry_run"):
                    plugin.set_dry_run(dry_run)

                success = plugin.post_video(video)
                results[plugin_name] = success

                # ログ出力：成功のみ記録（False はスキップ・既存と認識）
                video_id = video.get("video_id") or video.get("id", "unknown")
                if success:
                    post_logger.info(f"{plugin_name}: ✅ 成功 (video_id={video_id})")
                else:
                    # False の場合は単なる「未処理」（スキップ・既存）として認識
                    # post_error.log には記録しない
                    post_logger.debug(
                        f"{plugin_name}: ℹ️ スキップまたは既存 (video_id={video_id})"
                    )
            except Exception as e:
                post_error_logger.error(
                    f"❌ プラグイン {plugin_name} でのポスト失敗: {e}", exc_info=True
                )
                results[plugin_name] = False

        return results


# グローバルシングルトンマネージャー
_plugin_manager_instance: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    """
    グローバルなプラグインマネージャーを取得（シングルトン）

    Returns:
        PluginManager: プラグインマネージャーインスタンス
    """
    global _plugin_manager_instance
    if _plugin_manager_instance is None:
        _plugin_manager_instance = PluginManager()
    return _plugin_manager_instance
