import asyncio
from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler
import os
import sys

os.makedirs("data", exist_ok=True)

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from telethon import TelegramClient
from telethon.sessions import StringSession

from bot.handlers import (
    admin_users,
    billing,
    common,
    feed,
    geo_filter,
    history,
    keywords,
    monitor,
    topics,
)
from bot.kofi_webhook import start_kofi_webhook
from bot.monobank import MonobankClient
from bot.monobank_webhook import start_monobank_webhook
from bot.paypal import PayPalClient
from core.config import (
    API_HASH,
    API_ID,
    BOT_TOKEN,
    DB_PATH,
    MONOBANK_TOKEN,
    PHONE,
    SESSION_MODE,
    SESSION_PATH,
    SESSION_STRING,
)
from db.repository import Repository
from userbot.collector import ChatCollector
from userbot.watcher import MessageWatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            "data/monitor.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        ),
    ],
)
logger = logging.getLogger(__name__)


def _effective_session_mode(session_mode: str, session_string: str) -> str:
    mode = (session_mode or "auto").strip().lower()
    if mode == "auto":
        return "string" if session_string else "file"
    if mode not in {"string", "file"}:
        raise ValueError("SESSION_MODE должен быть auto, string или file")
    return mode


def _check_config() -> None:
    try:
        session_mode = _effective_session_mode(SESSION_MODE, SESSION_STRING)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)
    required = {
        "API_ID": API_ID,
        "API_HASH": API_HASH,
        "BOT_TOKEN": BOT_TOKEN,
    }
    if session_mode == "string":
        required["SESSION_STRING"] = SESSION_STRING
    else:
        required["PHONE"] = PHONE
    missing = [k for k, v in required.items() if not v]
    if missing:
        logger.error(f"Не заданы переменные: {', '.join(missing)}")
        logger.error("Скопируйте .env.example в .env и заполните значения.")
        sys.exit(1)


async def _start_userbot() -> TelegramClient:
    session_mode = _effective_session_mode(SESSION_MODE, SESSION_STRING)
    if session_mode == "string":
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            logger.error("SESSION_STRING недействителен. Сгенерируйте новый через generate_session.py.")
            sys.exit(1)
        logger.info("Telethon: используется SESSION_STRING")
        return client

    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start(phone=PHONE)
    logger.info(f"Telethon: используется файл сессии {SESSION_PATH}")
    return client


async def main() -> None:
    _check_config()

    repo = Repository(DB_PATH)
    await repo.init_db()
    logger.info(f"БД: {DB_PATH}")

    userbot = await _start_userbot()
    me = await userbot.get_me()
    logger.info(f"Userbot: {me.first_name} (@{me.username})")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    collector = ChatCollector(client=userbot, repo=repo)
    watcher = MessageWatcher(client=userbot, repo=repo, bot=bot)
    await watcher.start()

    dp["repo"] = repo
    dp["collector"] = collector
    dp["watcher"] = watcher
    dp["paypal"] = PayPalClient()
    dp["monobank"] = MonobankClient(MONOBANK_TOKEN)
    dp["started_at"] = datetime.now(timezone.utc)

    dp.include_router(admin_users.router)
    dp.include_router(common.router)
    dp.include_router(billing.router)
    dp.include_router(topics.router)
    dp.include_router(keywords.router)
    dp.include_router(history.router)
    dp.include_router(feed.router)
    dp.include_router(monitor.router)
    dp.include_router(geo_filter.router)

    kofi_webhook_runner = await start_kofi_webhook(bot, repo)
    monobank_webhook_runner = await start_monobank_webhook(bot, repo)
    logger.info("Бот запускается...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if kofi_webhook_runner:
            await kofi_webhook_runner.cleanup()
        if monobank_webhook_runner:
            await monobank_webhook_runner.cleanup()
        await watcher.stop()
        await userbot.disconnect()
        await bot.session.close()
        logger.info("Остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлен пользователем.")
