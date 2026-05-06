import os
from dotenv import load_dotenv

load_dotenv()

API_ID: int = int(os.getenv("API_ID", "0"))
API_HASH: str = os.getenv("API_HASH", "")
PHONE: str = os.getenv("PHONE", "")
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))
DB_PATH: str = os.getenv("DB_PATH", "data/monitor.db")
SESSION_PATH: str = os.getenv("SESSION_PATH", "data/userbot_session")
SESSION_STRING: str = os.getenv("SESSION_STRING", "").strip()
