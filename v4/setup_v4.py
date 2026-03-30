import os
import shutil
import logging
from pathlib import Path

# ロギング設定
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("v4.setup")

def setup_v4():
    """Deploy assets from Asset/ to v4/ and ensure directories."""
    base_dir = Path(__file__).resolve().parent.parent
    v4_dir = base_dir / "v4"
    asset_dir = v4_dir / "Asset"
    v4_data_dir = v4_dir / "data"
    images_dir = v4_dir / "images"
    legacy_marker = base_dir / "data" / ".v4_setup_done"

    logger.info("🚀 Starting StreamNotify v4 Setup...")

    v4_data_dir.mkdir(parents=True, exist_ok=True)
    marker_file = v4_data_dir / ".v4_setup_done"
    if marker_file.exists():
        logger.info("ℹ️ Setup already completed. Skipping asset deployment.")
        return
    if legacy_marker.exists():
        marker_file.touch()
        logger.info("ℹ️ Setup already completed (legacy marker). Migrated marker to v4/data.")
        return

    # 1. Ensure Directories
    dirs_to_create = [
        v4_dir / "templates" / "youtube",
        v4_dir / "templates" / "niconico",
        v4_dir / "templates" / "twitch",
        images_dir / "YouTube" / "import",
        images_dir / "Niconico" / "import",
        images_dir / "Twitch" / "import"
    ]
    for d in dirs_to_create:
        d.mkdir(parents=True, exist_ok=True)

    # 2. Deploy Templates
    template_source = asset_dir / "templates"
    if not template_source.exists():
        template_source = base_dir / "v3" / "templates"
        logger.info(f"📂 Asset/templates not found, using {template_source} instead.")

    files_deployed = 0
    if template_source.exists():
        for service in ["default", "youtube", "niconico", "twitch"]: # Added twitch and default
            src = template_source / service
            dest = v4_dir / "templates" / service
            if src.exists():
                files_deployed += _copy_new_files(src, dest)

    # 3. Deploy Default Images
    if (asset_dir / "images" / "default").exists():
        src = asset_dir / "images" / "default"
        dest = images_dir / "default"
        dest.mkdir(parents=True, exist_ok=True)
        files_deployed += _copy_new_files(src, dest)

    # 4. Initialize .env if missing
    env_example = v4_dir / "settings.env.example"
    env_real = v4_dir / "settings.env"
    if env_example.exists() and not env_real.exists():
        logger.info("📝 Creating initial settings.env from example...")
        shutil.copy2(env_example, env_real)
        files_deployed += 1

    marker_file.touch()

    if files_deployed > 0:
        logger.info(f"✨ Setup completed successfully! ({files_deployed} files processed)")
    else:
        logger.info("✨ Setup completed (no new files needed).")

def _copy_new_files(src: Path, dest: Path) -> int:
    """Copy files from src to dest only if they don't exist. Returns count of copied files."""
    count = 0
    for item in src.glob("*"):
        if item.is_file():
            target = dest / item.name
            if not target.exists():
                shutil.copy2(item, target)
                logger.debug(f"  Copied: {item.name}")
                count += 1
    return count

if __name__ == "__main__":
    setup_v4()
