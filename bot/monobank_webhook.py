import html
import json
import logging
from typing import Optional

from aiogram import Bot
from aiohttp import web

from bot.access import is_admin
from bot.keyboards import main_menu_kb
from core.config import (
    ADMIN_USER_ID,
)
from db.repository import Repository

logger = logging.getLogger(__name__)


async def handle_monobank_webhook(request: web.Request) -> web.Response:
    """
    Обработчик webhook от Monobank.

    Формат webhook от Monobank:
    {
        "type": "StatementItem",
        "data": {
            "account": "account_id",
            "statementItem": {
                "id": "transaction_id",
                "time": 1234567890,
                "description": "Описание платежа",
                "mcc": 4829,
                "originalMcc": 4829,
                "hold": false,
                "amount": 10000,  # В копейках/центах
                "operationAmount": 10000,
                "currencyCode": 980,  # 980 = UAH, 840 = USD
                "commissionRate": 0,
                "cashbackAmount": 0,
                "balance": 100000,
                "comment": "Комментарий к платежу"
            }
        }
    }
    """
    repo: Repository = request.app["repo"]
    bot: Bot = request.app["bot"]

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        logger.error("Invalid JSON in Monobank webhook")
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)

    # Проверяем тип события
    if payload.get("type") != "StatementItem":
        logger.warning(f"Unknown Monobank webhook type: {payload.get('type')}")
        return web.json_response({"ok": True, "message": "ignored"})

    data = payload.get("data", {})
    statement_item = data.get("statementItem", {})

    # Извлекаем данные транзакции
    transaction_id = statement_item.get("id")
    amount = statement_item.get("amount", 0)
    currency_code = statement_item.get("currencyCode", 980)
    description = statement_item.get("description", "")
    comment = statement_item.get("comment", "")

    # Проверяем, что это входящий платеж
    if amount <= 0:
        logger.info(f"Monobank webhook: ignoring outgoing transaction {transaction_id}")
        return web.json_response({"ok": True, "message": "outgoing_transaction"})

    if not transaction_id:
        logger.error("Monobank webhook: missing transaction_id")
        return web.json_response({"ok": False, "error": "missing_transaction_id"}, status=400)

    # Объединяем description и comment для поиска кода
    full_description = f"{description} {comment}".strip()

    # Записываем платеж
    result = await repo.record_monobank_webhook(
        transaction_id=transaction_id,
        amount=amount,
        currency_code=currency_code,
        description=full_description,
        raw_payload=payload,
    )

    # Уведомляем пользователя или админа
    if result["status"] == "paid":
        await _notify_user(bot, result)
    elif result["status"] == "manual_review":
        await _notify_admin(bot, transaction_id, result)

    return web.json_response({"ok": True, "status": result["status"]})


async def _notify_user(bot: Bot, result: dict) -> None:
    """Уведомить пользователя об успешной оплате."""
    user_tg_id = result.get("user_tg_id")
    if not user_tg_id:
        return
    try:
        await bot.send_message(
            user_tg_id,
            f"✅ Monobank платёж получен. Подписка активирована до <code>{result['expires_at']}</code>.",
            reply_markup=main_menu_kb(is_admin=is_admin(user_tg_id), has_access=True),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Failed to notify user about Monobank payment")


async def _notify_admin(bot: Bot, transaction_id: str, result: dict) -> None:
    """Уведомить админа о платеже на ручной проверке."""
    if not ADMIN_USER_ID:
        return
    try:
        await bot.send_message(
            ADMIN_USER_ID,
            "⚠️ Monobank платёж требует ручной проверки.\n\n"
            f"ID транзакции: <code>{html.escape(transaction_id)}</code>\n"
            f"Причина: <code>{html.escape(result.get('reason', '') or '')}</code>",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Failed to notify admin about Monobank manual review")
