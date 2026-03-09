#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
プラグインからのテンプレート読み込みをシミュレート
"""

import os
import sys
from pathlib import Path

# ★ プラグイン内からのインポートをシミュレート
# plugins/ ディレクトリから実行された場合
original_cwd = os.getcwd()
print(f"元のカレントディレクトリ: {original_cwd}")
print()

# v3 ディレクトリを sys.path に追加
v3_dir = Path(__file__).parent
sys.path.insert(0, str(v3_dir))

print(f"sys.path[0]: {sys.path[0]}")
print()

# template_utils をインポート
from template_utils import (
    get_template_path,
    load_template_with_fallback,
    DEFAULT_TEMPLATE_PATH,
)

print("=" * 60)
print("【テンプレート読み込みテスト（プラグイン経由）】")
print("=" * 60)

template_type = "youtube_new_video"

# 1. テンプレートパスを取得
template_path = get_template_path(
    template_type, default_fallback=str(DEFAULT_TEMPLATE_PATH)
)
print(f"1. get_template_path('{template_type}')")
print(f"   Result: {template_path}")
print(f"   Current dir: {os.getcwd()}")
print()

# 2. テンプレートをロード
print(f"2. load_template_with_fallback(path={template_path}, ...)")
print(f"   Current dir: {os.getcwd()}")

template_obj = load_template_with_fallback(
    path=template_path,
    default_path=str(DEFAULT_TEMPLATE_PATH),
    template_type=template_type,
)

print(f"   Result: {template_obj}")
print(f"   Is None: {template_obj is None}")
print()

if template_obj:
    print("✅ テンプレート読み込み成功")
    # サンプルコンテキストでレンダリング
    sample_context = {
        "title": "テスト動画",
        "video_id": "test123",
        "video_url": "https://www.youtube.com/watch?v=test123",
        "channel_name": "テストチャンネル",
        "published_at": "2025-12-18T04:00:00+09:00",
    }

    try:
        rendered = template_obj.render(sample_context)
        print("レンダリング結果:")
        print(rendered)
    except Exception as e:
        print(f"❌ レンダリング失敗: {e}")
else:
    print("❌ テンプレート読み込み失敗")
