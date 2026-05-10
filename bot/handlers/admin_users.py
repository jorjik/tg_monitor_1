import html
import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.access import is_admin, require_message_access
from bot.keyboards import admin_user_detail_kb, cancel_kb
from bot.states import AdminUserForm
from db.repository import Repository

logger = logging.getLogger(__name__)
router = Router()

@router.message(F.text == "👥 Пользователи")
async def cmd_admin_users(message: Message, state: FSMContext, repo: Repository):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminUserForm.waiting_search)
    await message.answer(
        "👥 <b>Управление пользователями</b>\n\n"
        "Введите <b>ID</b> пользователя или его <b>@username</b> для поиска:",
        reply_markup=cancel_kb(),
        parse_mode="HTML"
    )

@router.message(AdminUserForm.waiting_search)
async def process_user_search(message: Message, state: FSMContext, repo: Repository):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    query = (message.text or "").strip().replace("@", "")
    if not query:
        await message.answer("Введите что-то для поиска.")
        return

    # Try to find user
    user = None
    if query.isdigit():
        user = await repo.get_bot_user(int(query))
    
    if not user:
        user = await repo.search_bot_user(query)
    
    if not user:
        await message.answer(f"❌ Пользователь «{query}» не найден в базе данных бота.")
        return

    await state.clear()
    await _show_user_detail(message, repo, user)

async def _show_user_detail(message: Message, repo: Repository, user: dict):
    access = await repo.get_subscription_access(user["tg_id"])
    status_icon = "✅" if access["is_active"] else "⭕"
    
    name = f"{user['first_name'] or ''} {user['last_name'] or ''}".strip()
    username = f"@{user['username']}" if user['username'] else "нет"
    
    text = (
        f"👤 <b>Пользователь:</b> {html.escape(name)}\n"
        f"🆔 ID: <code>{user['tg_id']}</code>\n"
        f"🔗 Username: {html.escape(username)}\n\n"
        f"📊 Статус подписки: {status_icon} <b>{access['status']}</b>\n"
        f"📅 Истекает: <code>{access['expires_at'] or '—'}</code>\n\n"
        "Выберите действие ниже, чтобы начислить бонусные дни:"
    )
    
    await message.answer(
        text, 
        reply_markup=admin_user_detail_kb(user["tg_id"]),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("admin_user_add:"))
async def cb_admin_user_add(callback: CallbackQuery, repo: Repository):
    if not is_admin(callback.from_user.id):
        return
    
    parts = callback.data.split(":")
    user_tg_id = int(parts[1])
    days = int(parts[2])
    
    await repo.add_subscription_days(user_tg_id, days)
    
    user = await repo.get_bot_user(user_tg_id)
    await callback.message.edit_text(
        f"✅ Пользователю начислено <b>{days} дней</b> подписки.",
        parse_mode="HTML"
    )
    # Re-show details
    await _show_user_detail(callback.message, repo, user)
    await callback.answer("Подписка продлена")

@router.callback_query(F.data.startswith("admin_user_add_custom:"))
async def cb_admin_user_add_custom(callback: CallbackQuery, state: FSMContext, repo: Repository):
    if not is_admin(callback.from_user.id):
        return
    
    user_tg_id = int(callback.data.split(":")[1])
    await state.set_state(AdminUserForm.waiting_custom_days)
    await state.update_data(target_user_id=user_tg_id)
    
    await callback.message.answer(
        "Введите количество дней для начисления (число):",
        reply_markup=cancel_kb()
    )
    await callback.answer()

@router.message(AdminUserForm.waiting_custom_days)
async def process_custom_days(message: Message, state: FSMContext, repo: Repository):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    data = await state.get_data()
    user_tg_id = data["target_user_id"]
    
    try:
        days = int(message.text)
    except ValueError:
        await message.answer("Введите целое число дней.")
        return
    
    await repo.add_subscription_days(user_tg_id, days)
    await state.clear()
    
    user = await repo.get_bot_user(user_tg_id)
    await message.answer(f"✅ Пользователю начислено <b>{days} дней</b> подписки.", parse_mode="HTML")
    await _show_user_detail(message, repo, user)

@router.callback_query(F.data == "admin_users")
async def cb_admin_users(callback: CallbackQuery, state: FSMContext, repo: Repository):
    await cmd_admin_users(callback.message, state, repo)
    await callback.answer()
