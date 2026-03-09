#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DB をバックアップから復元
"""
import shutil
from pathlib import Path

db_path = Path('v3/data/video_list.db')
backup_path = Path('v3/data/video_list.backup_20251218_104027.db')

if backup_path.exists():
    shutil.copy(backup_path, db_path)
    print(f'✅ バックアップから復元しました')
    print(f'   Source: {backup_path}')
    print(f'   Dest:   {db_path}')
else:
    print(f'❌ バックアップが見つかりません: {backup_path}')
