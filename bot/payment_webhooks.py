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
    MONOBANK_WEBHOOK_SECRET,
)
from db.repository import Repository

logger = logging.getLogger(__name__)


def _normalize_path(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


def build_monobank_webhook_path() -> Optional[str]:
    """Полный путь Monobank-webhook или None, если секрет не задан.

    Monobank не подписывает вебхуки, поэтому единственная защита от подделки —
    секретный путь, который знает только Monobank (устанавливается через API).
    Без MONOBANK_WEBHOOK_SECRET маршрут не регистрируется вовсе.
    """
    if not MONOBANK_WEBHOOK_SECRET:
        return None
    return f"{_normalize_path(MONOBANK_WEBHOOK_PATH).rstrip('/')}/{MONOBANK_WEBHOOK_SECRET}"


async def start_payment_webhooks(bot: Bot, repo: Repository) -> Optional[web.AppRunner]:
    """
    Запустить единый webhook сервер для всех платежных систем.

    Объединяет Ko-fi и Monobank webhook на одном порту.
    Это необходимо для Railway и других платформ, которые предоставляют только один порт.
    """
    monobank_path = build_monobank_webhook_path()

    if not KO_FI_VERIFICATION_TOKEN and not monobank_path:
        logger.info("Payment webhooks: не настроены (нет Ko-fi токена и Monobank секрета)")
        return None

    app = web.Application()
    app["bot"] = bot
    app["repo"] = repo

    if KO_FI_VERIFICATION_TOKEN:
        kofi_path = _normalize_path(KO_FI_WEBHOOK_PATH)
        app.router.add_post(kofi_path, handle_kofi_webhook)
    else:
        kofi_path = None
        logger.warning("Payment webhooks: Ko-fi отключён (KO_FI_VERIFICATION_TOKEN не задан)")

    if monobank_path:
        app.router.add_post(monobank_path, handle_monobank_webhook)
    else:
        logger.error(
            "Payment webhooks: Monobank отключён — задайте MONOBANK_WEBHOOK_SECRET, "
            "иначе вебхук остаётся открытым для подделки платежей."
        )

    # Запускаем сервер на одном порту
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, KO_FI_WEBHOOK_HOST, KO_FI_WEBHOOK_PORT)
    await site.start()

    logger.info(f"Payment webhooks started on http://{KO_FI_WEBHOOK_HOST}:{KO_FI_WEBHOOK_PORT}")
    if kofi_path:
        logger.info(f"  Ko-fi:     {kofi_path}")
    if monobank_path:
        logger.info(f"  Monobank:  {monobank_path}")

    return runner
