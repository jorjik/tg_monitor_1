from aiogram.types import CallbackQuery, Message

from bot.keyboards import subscription_kb
from core.config import ADMIN_USER_ID
from db.repository import Repository


def is_admin(user_tg_id: int) -> bool:
    return bool(ADMIN_USER_ID and user_tg_id == ADMIN_USER_ID)


async def _upsert_user(repo: Repository, user) -> None:
    await repo.upsert_bot_user(
        tg_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )


async def user_has_access(repo: Repository, user_tg_id: int) -> bool:
    if is_admin(user_tg_id):
        return True
    access = await repo.get_subscription_access(user_tg_id)
    if access["status"] == "none":
        access = await repo.ensure_trial(user_tg_id)
    return bool(access["is_active"])


async def require_message_access(message: Message, repo: Repository) -> bool:
    if not message.from_user:
        return False
    await _upsert_user(repo, message.from_user)
    user_tg_id = message.from_user.id
    if await user_has_access(repo, user_tg_id):
        return True
    tariffs = await repo.get_tariffs(active_only=True)
    await message.answer(
        "🔒 Доступ к этому разделу доступен после оплаты или во время демо-доступа.\n\n"
        "Откройте подписку и выберите тариф.",
        reply_markup=subscription_kb(tariffs),
    )
    return False


async def require_callback_access(callback: CallbackQuery, repo: Repository) -> bool:
    await _upsert_user(repo, callback.from_user)
    user_tg_id = callback.from_user.id
    if await user_has_access(repo, user_tg_id):
        return True
    await callback.answer("Нужна активная подписка.", show_alert=True)
    tariffs = await repo.get_tariffs(active_only=True)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "🔒 Доступ к этому действию доступен после оплаты или во время демо-доступа.",
            reply_markup=subscription_kb(tariffs),
        )
    return False
