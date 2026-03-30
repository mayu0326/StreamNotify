# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v3 設定ファイル同期

settings.env.example から新しい設定項目を検出して、
settings.env に自動的に挿入するモジュール。

既存設定とコメント行は一切編集しないため、
純粋に不足項目のみを適切なセクションに挿入する。
"""

import os
import logging
from pathlib import Path
from typing import Tuple, List, Dict

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


def _extract_key_from_line(line: str) -> str:
    """
    1行から設定キー（=の左側）を抽出する

    Args:
        line: 設定ファイルの1行

    Returns:
        キー名。コメント行や空行の場合は空文字列
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return ""

    if "=" in line:
        key = line.split("=", 1)[0].strip()
        return key

    return ""


def _read_keys_from_file(file_path: str) -> Tuple[set, dict]:
    """
    .envファイルから設定キーを抽出する

    Args:
        file_path: ファイルパス

    Returns:
        (キーセット, キー→行番号の辞書)のタプル
    """
    keys = set()
    key_line_map = {}

    if not os.path.exists(file_path):
        return keys, key_line_map

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                key = _extract_key_from_line(line)
                if key:
                    keys.add(key)
                    key_line_map[key] = line_no
    except Exception as e:
        logger.warning(f"⚠️ ファイル読み込みエラー '{file_path}': {e}")

    return keys, key_line_map


def _read_file_with_sections(file_path: str) -> List[Tuple[str, str]]:
    """
    ファイルを行単位で読み込む（セクション情報も保持）

    Args:
        file_path: ファイルパス

    Returns:
        (行内容, セクション名) のリスト
        セクション名はセクションヘッダーが出現するまで""
    """
    lines = []
    current_section = ""

    if not os.path.exists(file_path):
        return lines

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                # セクションヘッダーを検出（# ===== ... ===== 形式）
                stripped = line.strip()
                if stripped.startswith("# =====") and stripped.endswith("====="):
                    current_section = stripped

                lines.append((line.rstrip("\n\r"), current_section))
    except Exception as e:
        logger.warning(f"⚠️ ファイル読み込みエラー '{file_path}': {e}")

    return lines


def _find_insertion_point(
    existing_lines: List[Tuple[str, str]],
    example_lines: List[Tuple[str, str]],
    new_key: str
) -> Tuple[int, str]:
    """
    新規キーを挿入すべき位置を見つける

    settings.env.example での該当キーの位置を基準に、
    settings.env での挿入位置を決定する

    Args:
        existing_lines: settings.env の行リスト（行内容, セクション名）
        example_lines: settings.env.example の行リスト
        new_key: 新規キー名

    Returns:
        (挿入位置（行インデックス）, セクション名) のタプル
    """
    # example から new_key のインデックスを見つける
    new_key_index_in_example = -1

    for idx, (line, _) in enumerate(example_lines):
        key = _extract_key_from_line(line)
        if key == new_key:
            new_key_index_in_example = idx
            break

    if new_key_index_in_example < 0:
        # キーが見つからない場合は末尾に挿入
        return len(existing_lines), ""

    # example で new_key より前にある設定キーを見つける（直前のものを探す）
    prev_key_in_example = None
    for idx in range(new_key_index_in_example - 1, -1, -1):
        line, _ = example_lines[idx]
        key = _extract_key_from_line(line)
        if key:
            prev_key_in_example = key
            break

    # example で new_key より後ろにある設定キーを見つける（直後のものを探す）
    next_key_in_example = None
    for idx in range(new_key_index_in_example + 1, len(example_lines)):
        line, _ = example_lines[idx]
        key = _extract_key_from_line(line)
        if key:
            next_key_in_example = key
            break

    # existing で prev_key または next_key を見つけて、挿入位置を決定
    for idx, (line, _) in enumerate(existing_lines):
        key = _extract_key_from_line(line)

        # 次のキーが既に existing に存在すれば、その前に挿入
        if next_key_in_example and key == next_key_in_example:
            return idx, ""

        # 前のキーが見つかれば、その直後に挿入候補
        if prev_key_in_example and key == prev_key_in_example:
            # 次のループで位置を確定させるため、候補を覚えておく
            continue

    # 前のキーの直後に挿入
    for idx, (line, _) in enumerate(existing_lines):
        key = _extract_key_from_line(line)
        if prev_key_in_example and key == prev_key_in_example:
            # prev_key の直後の位置を見つける
            for search_idx in range(idx + 1, len(existing_lines)):
                next_line, _ = existing_lines[search_idx]
                next_key = _extract_key_from_line(next_line)
                # 次の設定キーが見つかるまで進める、またはセクションの変わり目で止める
                if next_key or next_line.strip().startswith("# ====="):
                    return search_idx, ""
            # セクション内に他に項目がなければセクション末尾に挿入
            return idx + 1, ""

    # いずれにも該当しない場合は末尾に挿入
    return len(existing_lines), ""


def _extract_key_block_from_example(
    example_lines: List[Tuple[str, str]],
    new_key: str
) -> List[str]:
    """
    settings.env.example から新規キーに関連する行を抽出

    新規キーの直前のコメント行もまとめて取得する
    （ユーザーに説明情報を提供するため）

    Args:
        example_lines: settings.env.example の行リスト
        new_key: 新規キー名

    Returns:
        抽出された行のリスト（コメント + 設定行）
    """
    lines_to_insert = []
    key_found = False

    # example で new_key を見つける
    for idx, (line, _) in enumerate(example_lines):
        key = _extract_key_from_line(line)
        if key == new_key:
            key_found = True
            lines_to_insert.append(line)
            break

    if not key_found:
        # キーが見つからない場合は、そのまま返す
        return [f"{new_key}="]

    # new_key の直前のコメント行（複数行可）を探す
    comment_start = -1
    for idx in range(len(example_lines) - 1, -1, -1):
        line, _ = example_lines[idx]
        key = _extract_key_from_line(line)

        if key == new_key:
            # new_key 手前の行から遡る
            search_start = idx - 1
            while search_start >= 0:
                prev_line, _ = example_lines[search_start]
                prev_key = _extract_key_from_line(prev_line)

                # コメント行か空行か、前の設定キーに到達したかで判定
                if prev_line.strip() == "" or prev_line.strip().startswith("#"):
                    comment_start = search_start
                    search_start -= 1
                else:
                    break
            break

    # コメント行を先頭に追加
    if comment_start >= 0:
        comment_lines = [example_lines[i][0] for i in range(comment_start, idx)]
        lines_to_insert = comment_lines + lines_to_insert

    return lines_to_insert


def sync_settings_env(
    settings_env: str = "settings.env",
    example_file: str = "settings.env.example"
) -> bool:
    """
    settings.env を settings.env.example と同期

    - settings.env.example に存在し、settings.env に存在しないキーを挿入
    - 不足キーは同一セクション内の適切な位置に挿入
    - コメント行（説明）も一緒に挿入
    - 既存設定は一切編集しない

    Args:
        settings_env: settings.env ファイルパス（デフォルト: v3/settings.env）
        example_file: settings.env.example ファイルパス（デフォルト: v3/settings.env.example）

    Returns:
        同期が実行されたか（新規項目があるか）
    """
    # ファイルパスの存在確認
    if not os.path.exists(example_file):
        logger.warning(f"⚠️ '{example_file}' が見つかりません。スキップします。")
        return False

    # settings.env に存在するキーを抽出
    existing_keys, _ = _read_keys_from_file(settings_env)

    # settings.env.example から不足キーを抽出
    example_keys, _ = _read_keys_from_file(example_file)
    missing_keys = example_keys - existing_keys

    if not missing_keys:
        logger.debug("✅ settings.env は最新です。追加すべき項目はありません。")
        return False

    # セクション情報付きで行を読み込む
    existing_lines = _read_file_with_sections(settings_env)
    example_lines = _read_file_with_sections(example_file)

    # 不足キーごとに挿入位置を特定してテンプレートを作成
    insertions = []  # (挿入位置, 挿入する行リスト) のリスト

    for new_key in sorted(missing_keys):
        # 挿入すべき行を example から取得
        lines_to_insert = _extract_key_block_from_example(example_lines, new_key)

        # 挿入位置を特定
        insert_pos, target_section = _find_insertion_point(existing_lines, example_lines, new_key)

        insertions.append((insert_pos, lines_to_insert))

    # 挿入位置が大きい順にソート（後ろから挿入することで位置ズレを回避）
    insertions.sort(reverse=True, key=lambda x: x[0])

    # settings.env に不足項目を挿入
    try:
        # メモリ上で編集してからファイルに書き込む
        updated_lines = [line for line, _ in existing_lines]

        for insert_pos, lines_to_insert in insertions:
            # 挿入位置を調整（末尾の場合）
            if insert_pos >= len(updated_lines):
                # ファイル末尾に挿入
                if updated_lines and updated_lines[-1] != "":
                    updated_lines.append("")
                updated_lines.extend(lines_to_insert)
            else:
                # 指定位置に挿入
                for i, line in enumerate(lines_to_insert):
                    updated_lines.insert(insert_pos + i, line)

        # ファイルに書き込む
        with open(settings_env, "w", encoding="utf-8") as f:
            for line in updated_lines:
                f.write(f"{line}\n")

        logger.info(f"✅ settings.env を更新しました。{len(missing_keys)} 個の新規項目を追加しました。")
        return True

    except Exception as e:
        logger.error(f"❌ settings.env の更新に失敗しました: {e}")
        return False


if __name__ == "__main__":
    # スタンドアロン実行用（デバッグ）
    import sys

    # ログ設定
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # v3 ディレクトリで実行されることを想定
    settings_env_path = "settings.env"
    example_file_path = "settings.env.example"

    sync_result = sync_settings_env(settings_env_path, example_file_path)
    sys.exit(0 if sync_result is not None else 1)
