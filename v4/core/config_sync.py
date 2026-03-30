import os
import logging
from pathlib import Path
from typing import List, Tuple, Set

logger = logging.getLogger("v4.config_sync")

def sync_config(env_path: Path, example_path: Path) -> bool:
    """Add missing keys from example to actual .env without breaking comments."""
    if not example_path.exists():
        return False

    if not env_path.exists():
        # Just copy if doesn't exist
        import shutil
        shutil.copy2(example_path, env_path)
        return True

    existing_keys = _get_keys(env_path)
    example_lines = example_path.read_text(encoding="utf-8").splitlines()
    example_keys = _get_keys(example_path)

    missing_keys = example_keys - existing_keys
    if not missing_keys:
        return False

    logger.info(f"🔄 Syncing config: adding {len(missing_keys)} new keys to .env")

    env_lines = env_path.read_text(encoding="utf-8").splitlines()

    # Simple strategy: append missing keys with their comments to the end
    # (v3 has complex insertion, v4 keeps it robust by appending)
    new_lines = []
    for key in sorted(missing_keys):
        # Extract block from example
        block = _extract_block(example_lines, key)
        new_lines.extend([""] + block)

    with open(env_path, "a", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")

    return True

def _get_keys(path: Path) -> Set[str]:
    keys = set()
    if not path.exists(): return keys
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys

def _extract_block(lines: List[str], key: str) -> List[str]:
    block = []
    key_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            key_idx = i
            break

    if key_idx == -1: return []

    # Backtrack comments
    start_idx = key_idx
    while start_idx > 0:
        prev = lines[start_idx-1].strip()
        if prev.startswith("#") or not prev:
            start_idx -= 1
        else:
            break

    return lines[start_idx : key_idx+1]
