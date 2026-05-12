import logging
from typing import Optional

from aiogram import Bot
from aiohttp import web

from bot.kofi_webhook import handle_kofi_webhook
from bot.monobank_webhook import handle_monobank_webhook
from core.config import (
    KO_FI_VERIFICATION_TOKEN,
    KO_FI_WEBHOOK_HOST,
    KO_FI_WEBHOOK_PATH,
    KO_FI_WEBHOOK_PORT,
    MONOBANK_WEBHOOK_PATH,
)
from db.repository import Repository

logger = logging.getLogger(__name__)


async def start_payment_webhooks(bot: Bot, repo: Repository) -> Optional[web.AppRunner]:
    """
    Запустить единый webhook сервер для всех платежных систем.

    Объединяет Ko-fi и Monobank webhook на одном порту.
    Это необходимо для Railway и других платформ, которые предоставляют только один порт.
    """
    # Если ни один webhook не настроен, не запускаем сервер
    if not KO_FI_VERIFICATION_TOKEN:
        logger.info("Payment webhooks: не настроены (Ko-fi token отсутствует)")
        return None

    app = web.Application()
    app["bot"] = bot
    app["repo"] = repo

    # Добавляем маршруты для всех платежных систем
    kofi_path = KO_FI_WEBHOOK_PATH if KO_FI_WEBHOOK_PATH.startswith("/") else f"/{KO_FI_WEBHOOK_PATH}"
    monobank_path = MONOBANK_WEBHOOK_PATH if MONOBANK_WEBHOOK_PATH.startswith("/") else f"/{MONOBANK_WEBHOOK_PATH}"

    app.router.add_post(kofi_path, handle_kofi_webhook)
    app.router.add_post(monobank_path, handle_monobank_webhook)

    # Запускаем сервер на одном порту
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, KO_FI_WEBHOOK_HOST, KO_FI_WEBHOOK_PORT)
    await site.start()

    logger.info(f"Payment webhooks started on http://{KO_FI_WEBHOOK_HOST}:{KO_FI_WEBHOOK_PORT}")
    logger.info(f"  Ko-fi:     {kofi_path}")
    logger.info(f"  Monobank:  {monobank_path}")

    return runner
