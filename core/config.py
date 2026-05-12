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
SESSION_MODE: str = os.getenv("SESSION_MODE", "auto").strip().lower()
SESSION_PATH: str = os.getenv("SESSION_PATH", "data/userbot_session")
SESSION_STRING: str = os.getenv("SESSION_STRING", "").strip()
KO_FI_PAGE_URL: str = os.getenv("KO_FI_PAGE_URL", "").strip()
KO_FI_VERIFICATION_TOKEN: str = os.getenv("KO_FI_VERIFICATION_TOKEN", "").strip()
KO_FI_CURRENCY: str = os.getenv("KO_FI_CURRENCY", "USD").strip().upper()
KO_FI_AMOUNT_PER_STAR: str = os.getenv("KO_FI_AMOUNT_PER_STAR", "1").strip()
KO_FI_WEBHOOK_HOST: str = os.getenv("KO_FI_WEBHOOK_HOST", "0.0.0.0").strip()
KO_FI_WEBHOOK_PORT: int = _int_env("KO_FI_WEBHOOK_PORT", 8080)
KO_FI_WEBHOOK_PATH: str = os.getenv("KO_FI_WEBHOOK_PATH", "/webhooks/kofi").strip()

# PayPal
PAYPAL_CLIENT_ID: str = os.getenv("PAYPAL_CLIENT_ID", "").strip()
PAYPAL_CLIENT_SECRET: str = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
PAYPAL_MODE: str = os.getenv("PAYPAL_MODE", "sandbox").strip()  # sandbox or live
PAYPAL_CURRENCY: str = os.getenv("PAYPAL_CURRENCY", "USD").strip().upper()
PAYPAL_AMOUNT_PER_STAR: str = os.getenv("PAYPAL_AMOUNT_PER_STAR", "1").strip()

# Monobank
MONOBANK_TOKEN: str = os.getenv("MONOBANK_TOKEN", "").strip()
MONOBANK_ACCOUNT_ID: str = os.getenv("MONOBANK_ACCOUNT_ID", "").strip()
MONOBANK_CURRENCY: str = os.getenv("MONOBANK_CURRENCY", "UAH").strip().upper()
MONOBANK_AMOUNT_PER_STAR: str = os.getenv("MONOBANK_AMOUNT_PER_STAR", "10").strip()
MONOBANK_WEBHOOK_HOST: str = os.getenv("MONOBANK_WEBHOOK_HOST", "0.0.0.0").strip()
MONOBANK_WEBHOOK_PORT: int = _int_env("MONOBANK_WEBHOOK_PORT", 8081)
MONOBANK_WEBHOOK_PATH: str = os.getenv("MONOBANK_WEBHOOK_PATH", "/webhooks/monobank").strip()
