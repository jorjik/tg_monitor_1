import os
from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int = 0) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


API_ID: int = _int_env("API_ID")
API_HASH: str = os.getenv("API_HASH", "")
PHONE: str = os.getenv("PHONE", "")
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_USER_ID: int = _int_env("ADMIN_USER_ID")
DB_PATH: str = os.getenv("DB_PATH", "data/monitor.db")
SESSION_PATH: str = os.getenv("SESSION_PATH", "data/userbot_session")
SESSION_STRING: str = os.getenv("SESSION_STRING", "").strip()
