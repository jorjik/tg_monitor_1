from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.access import require_callback_access, require_message_access
from bot.keyboards import monitor_kb
from db.repository import Repository
from userbot.watcher import MessageWatcher

router = Router()


async def _status(repo: Repository, watcher: MessageWatcher, user_tg_id: int) -> str:
    chats = await repo.get_active_chats(user_tg_id)
    kws = await repo.get_all_active_keywords(user_tg_id)
    unread = await repo.get_unread_count(user_tg_id)
    icon = "🟢 Активен" if watcher.is_running else "🔴 Остановлен"
    return (
        f"⚙️ <b>Мониторинг</b>\n\n"
        f"Статус сервиса: {icon}\n"
        f"💬 Ваших активных чатов: {len(chats)}\n"
        f"🔑 Ваших активных ключевых слов: {len(kws)}\n"
        f"📰 Ваших непрочитанных: {unread}"
    )


@router.message(F.text == "⚙️ Мониторинг")
@router.message(Command("monitor"))
async def cmd_monitor(message: Message, repo: Repository, watcher: MessageWatcher):
    if not await require_message_access(message, repo):
        return
    text = await _status(repo, watcher, message.from_user.id)
    await message.answer(text, reply_markup=monitor_kb(watcher.is_running), parse_mode="HTML")


@router.callback_query(F.data == "monitor:status")
async def cb_status(callback: CallbackQuery, repo: Repository, watcher: MessageWatcher):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    text = await _status(repo, watcher, user_tg_id)
    try:
        await callback.message.edit_text(
            text, reply_markup=monitor_kb(watcher.is_running), parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer("Обновлено")


@router.callback_query(F.data == "monitor:start")
async def cb_start(callback: CallbackQuery, repo: Repository, watcher: MessageWatcher):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    if not await repo.get_active_chats(user_tg_id):
        await callback.answer("⚠️ Нет активных чатов!", show_alert=True)
        return
    if not await repo.get_all_active_keywords(user_tg_id):
        await callback.answer("⚠️ Нет ключевых слов!", show_alert=True)
        return
    text = await _status(repo, watcher, user_tg_id)
    await callback.message.edit_text(
        text, reply_markup=monitor_kb(watcher.is_running), parse_mode="HTML"
    )
    await callback.answer("Мониторинг запускается автоматически", show_alert=True)


@router.callback_query(F.data == "monitor:stop")
async def cb_stop(callback: CallbackQuery, repo: Repository, watcher: MessageWatcher):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    text = await _status(repo, watcher, user_tg_id)
    await callback.message.edit_text(
        text, reply_markup=monitor_kb(watcher.is_running), parse_mode="HTML"
    )
    await callback.answer("Отключайте отдельные чаты или ключевые слова в настройках", show_alert=True)
