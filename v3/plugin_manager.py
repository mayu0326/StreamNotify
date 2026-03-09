# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - プラグインマネージャー

プラグインの動的な読み込み、管理、実行を担当します。
"""

import os
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
__license__ = "GPLv3"


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

        Returns:
            List[Tuple[str, str]]: (プラグイン名, ファイルパス) のリスト
        """
        if not self.plugins_dir.exists():
            logger.warning(f"プラグインディレクトリが存在しません: {self.plugins_dir}")
            return []

        plugins = []
        for file_path in self.plugins_dir.glob("*.py"):
            if file_path.name.startswith("_"):
                continue
            plugin_name = file_path.stem
            plugins.append((plugin_name, str(file_path)))
            logger.info(f"📦 プラグイン検出: {plugin_name} ({file_path})")

        return plugins

    def load_plugin(self, plugin_name: str, plugin_path: str) -> Optional[NotificationPlugin]:
        """
        プラグインを動的に読み込む

        Args:
            plugin_name: プラグイン名
            plugin_path: プラグインファイルのパス

        Returns:
            NotificationPlugin: ロードされたプラグイン、失敗時は None
        """
        try:
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
                    if (isinstance(attr, type) and
                        issubclass(attr, NotificationPlugin) and
                        attr is not NotificationPlugin and
                        attr.__module__ == plugin_name):  # このモジュール内で定義されたクラスのみ
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(f"🔍 発見したクラス: {attr.__name__} in {plugin_name}")
                        plugin_class = attr
                        break

                if plugin_class is None:
                    logger.error(f"❌ プラグイン {plugin_name}: NotificationPlugin を実装したクラスが見つかりません")
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
            logger.error(f"❌ プラグイン {plugin_name} のロード失敗: {e}", exc_info=True)
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
                logger.info(f"✅ プラグイン有効化完了: {plugin.get_name()} v{plugin.get_version()}")
                return True
            else:
                logger.warning(f"⚠️  プラグイン {plugin_name} は利用不可です")
                return False
        except Exception as e:
            logger.error(f"❌ プラグイン {plugin_name} の有効化失敗: {e}", exc_info=True)
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
            logger.error(f"❌ プラグイン {plugin_name} の無効化エラー: {e}", exc_info=True)
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
        return self.enabled_plugins.get(plugin_name) or self.loaded_plugins.get(plugin_name)

    def post_video_with_all_enabled(self, video: dict, dry_run: bool = False) -> Dict[str, bool]:
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
                if hasattr(plugin, 'set_dry_run'):
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
                    post_logger.debug(f"{plugin_name}: ℹ️ スキップまたは既存 (video_id={video_id})")
            except Exception as e:
                post_error_logger.error(f"❌ プラグイン {plugin_name} でのポスト失敗: {e}", exc_info=True)
                results[plugin_name] = False

        return results
