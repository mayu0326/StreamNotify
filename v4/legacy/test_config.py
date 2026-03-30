import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR.parent))

from v4.core.config import settings
print(f"CENTER_SERVER_URL: {settings.CENTER_SERVER_URL}")
print(f"ENV_FILE used: {settings.model_config.get('env_file')}")
import os
print(f"ENV Var CENTER_SERVER_URL: {os.environ.get('CENTER_SERVER_URL')}")
