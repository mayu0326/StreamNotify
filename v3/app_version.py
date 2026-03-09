# -*- coding: utf-8 -*-

"""
StreamNotify on Bluesky v3 - バージョン情報

セマンティックバージョニングを採用
- major: 大規模な機能追加・API変更
- minor: 機能追加（後方互換性あり）
- patch: バグ修正
"""

__version__ = "3.0.0"
__release_date__ = "2025-12-18"
__status__ = "development"  # development / alpha / beta / stable
__author__ = "mayuneco(mayunya)"
__license__ = "GPLv3"

# CI/CD で自動設定される（Git タグ作成時）
__git_commit__ = ""
__git_branch__ = ""


def get_version_info() -> str:
    """
    フォーマット済みのバージョン情報を返す

    Returns:
        str: "v3.1.0 (2025-12-17) [development]"
    """
    version_str = f"v{__version__} ({__release_date__})"
    if __status__ != "stable":
        version_str += f" [{__status__}]"
    return version_str


def get_full_version_info() -> dict:
    """
    詳細なバージョン情報を辞書で返す

    Returns:
        dict: バージョン情報を含む辞書
    """
    return {
        "version": __version__,
        "release_date": __release_date__,
        "status": __status__,
        "author": __author__,
        "license": __license__,
        "git_commit": __git_commit__,
        "git_branch": __git_branch__,
        "formatted": get_version_info()
    }
