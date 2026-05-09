import json
import logging
from typing import Optional

from aiogram import Bot
from aiohttp import web

from bot.access import is_admin
from bot.keyboards import main_menu_kb
from bot.kofi import extract_kofi_code, parse_kofi_webhook_payload
from core.config import (
    ADMIN_USER_ID,
    KO_FI_VERIFICATION_TOKEN,
    KO_FI_WEBHOOK_HOST,
    KO_FI_WEBHOOK_PATH,
    KO_FI_WEBHOOK_PORT,
)
from db.repository import Repository

logger = logging.getLogger(__name__)


async def handle_kofi_webhook(request: web.Request) -> web.Response:
    repo: Repository = request.app["repo"]
    bot: Bot = request.app["bot"]
    try:
        payload = await _read_payload(request)
        payment = parse_kofi_webhook_payload(payload)
    except (json.JSONDecodeError, ValueError):
        return web.json_response({"ok": False, "error": "invalid_payload"}, status=400)
    if payment.verification_token != KO_FI_VERIFICATION_TOKEN:
        return web.json_response({"ok": False, "error": "invalid_token"}, status=403)

    result = await repo.record_kofi_payment(
        provider_payment_id=payment.provider_payment_id,
        code=extract_kofi_code(payment.message),
        amount=payment.amount,
        currency=payment.currency,
        raw_payload=json.dumps(payment.raw_payload, ensure_ascii=False, sort_keys=True),
    )
    if result["status"] == "paid" and result["inserted"]:
        await _notify_user(bot, result)
    elif result["status"] == "manual_review" and result["inserted"]:
        await _notify_admin(bot, payment.provider_payment_id, result)
    return web.json_response({"ok": True, "status": result["status"], "reason": result["reason"]})


async def _read_payload(request: web.Request) -> dict | str:
    if request.content_type == "application/json":
        return await request.json()
    post = await request.post()
    if post:
        return dict(post)
    return await request.text()


async def _notify_user(bot: Bot, result: dict) -> None:
    user_tg_id = result.get("user_tg_id")
    if not user_tg_id:
        return
    try:
        await bot.send_message(
            user_tg_id,
            f"✅ Ko-fi платёж получен. Подписка активирована до <code>{result['expires_at']}</code>.",
            reply_markup=main_menu_kb(is_admin=is_admin(user_tg_id), has_access=True),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Failed to notify user about Ko-fi payment")


async def _notify_admin(bot: Bot, provider_payment_id: str, result: dict) -> None:
    if not ADMIN_USER_ID:
        return
    try:
        await bot.send_message(
            ADMIN_USER_ID,
            "⚠️ Ko-fi платёж требует ручной проверки.\n\n"
            f"ID: <code>{provider_payment_id}</code>\n"
            f"Причина: <code>{result['reason']}</code>",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Failed to notify admin about Ko-fi manual review")


async def start_kofi_webhook(bot: Bot, repo: Repository) -> Optional[web.AppRunner]:
    if not KO_FI_VERIFICATION_TOKEN:
        return None
    path = KO_FI_WEBHOOK_PATH if KO_FI_WEBHOOK_PATH.startswith("/") else f"/{KO_FI_WEBHOOK_PATH}"
    app = web.Application()
    app["bot"] = bot
    app["repo"] = repo
    app.router.add_post(path, handle_kofi_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, KO_FI_WEBHOOK_HOST, KO_FI_WEBHOOK_PORT)
    await site.start()
    logger.info(f"Ko-fi webhook: http://{KO_FI_WEBHOOK_HOST}:{KO_FI_WEBHOOK_PORT}{path}")
    return runner
