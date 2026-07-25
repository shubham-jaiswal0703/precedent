"""Environment + VideoDB connection handling."""
import os
from functools import lru_cache
from pathlib import Path

import videodb
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"

load_dotenv(PROJECT_ROOT / ".env")


@lru_cache(maxsize=1)
def get_connection() -> "videodb.client.Connection":
    api_key = os.environ.get("VIDEO_DB_API_KEY")
    if not api_key:
        raise RuntimeError("VIDEO_DB_API_KEY not set (see .env.example)")
    return videodb.connect(api_key=api_key)
