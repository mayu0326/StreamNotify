#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
テンプレート読み込みプロセスの詳細デバッグ
"""

import os
import sys
from pathlib import Path

# v3 ディレクトリを sys.path に追加
sys.path.insert(0, str(Path(__file__).parent))

# 環境変数を確認
print("=" * 60)
print("【システム環境変数】")
print("=" * 60)
print(
    f"TEMPLATE_YOUTUBE_NEW_VIDEO_PATH = {os.getenv('TEMPLATE_YOUTUBE_NEW_VIDEO_PATH')}"
)
print()

# settings.env を直接読む
print("=" * 60)
print("【settings.env の内容（テンプレート関連）】")
print("=" * 60)
settings_path = Path(__file__).parent / "settings.env"
print(f"settings.env path: {settings_path}")
print(f"exists: {settings_path.exists()}")
print()

if settings_path.exists():
    with open(settings_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "TEMPLATE_" in line and not line.startswith("#"):
                print(line)
print()

# _get_env_var_from_file() を直接テスト
print("=" * 60)
print("【_get_env_var_from_file() テスト】")
print("=" * 60)

from template_utils import _get_env_var_from_file

result = _get_env_var_from_file("settings.env", "TEMPLATE_YOUTUBE_NEW_VIDEO_PATH")
print(f"_get_env_var_from_file('settings.env', 'TEMPLATE_YOUTUBE_NEW_VIDEO_PATH')")
print(f"  Result: {result}")
print()

# get_template_path() を直接テスト
print("=" * 60)
print("【get_template_path() テスト】")
print("=" * 60)

from template_utils import get_template_path

template_path = get_template_path(
    "youtube_new_video", default_fallback="templates/youtube/yt_new_video_template.txt"
)
print(f"get_template_path('youtube_new_video', default_fallback=...)")
print(f"  Result: {template_path}")

# テンプレートファイルが存在するか確認
if template_path:
    full_path = Path(template_path)
    print(f"  Full path: {full_path}")
    print(f"  Exists: {full_path.exists()}")

    # 相対パスから絶対パスへ
    if not full_path.is_absolute():
        abs_path = Path(__file__).parent / template_path
        print(f"  Absolute path: {abs_path}")
        print(f"  Absolute exists: {abs_path.exists()}")
print()

# load_template_with_fallback() をテスト
print("=" * 60)
print("【load_template_with_fallback() テスト】")
print("=" * 60)

from template_utils import load_template_with_fallback

template_obj = load_template_with_fallback(
    path=template_path,
    default_path="templates/youtube/yt_new_video_template.txt",
    template_type="youtube_new_video",
)
print(f"load_template_with_fallback(path={template_path}, ...)")
print(f"  Result type: {type(template_obj)}")
print(f"  Result is None: {template_obj is None}")

if template_obj:
    print(f"  Template name: {template_obj.name}")
    print(f"  Template object: {template_obj}")
else:
    print("  ❌ テンプレート読み込み失敗")
