from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.keyboards import monitor_kb
from db.repository import Repository
from userbot.watcher import MessageWatcher

router = Router()


async def _status(repo: Repository, watcher: MessageWatcher) -> str:
    chats = await repo.get_active_chats()
    kws = await repo.get_all_active_keywords()
    unread = await repo.get_unread_count()
    icon = "🟢 Активен" if watcher.is_running else "🔴 Остановлен"
    return (
        f"⚙️ <b>Мониторинг</b>\n\n"
        f"Статус: {icon}\n"
        f"💬 Активных чатов: {len(chats)}\n"
        f"🔑 Активных ключевых слов: {len(kws)}\n"
        f"📰 Непрочитанных: {unread}"
    )


@router.message(F.text == "⚙️ Мониторинг")
@router.message(Command("monitor"))
async def cmd_monitor(message: Message, repo: Repository, watcher: MessageWatcher):
    text = await _status(repo, watcher)
    await message.answer(text, reply_markup=monitor_kb(watcher.is_running), parse_mode="HTML")


@router.callback_query(F.data == "monitor:status")
async def cb_status(callback: CallbackQuery, repo: Repository, watcher: MessageWatcher):
    text = await _status(repo, watcher)
    try:
        await callback.message.edit_text(
            text, reply_markup=monitor_kb(watcher.is_running), parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer("Обновлено")


@router.callback_query(F.data == "monitor:start")
async def cb_start(callback: CallbackQuery, repo: Repository, watcher: MessageWatcher):
    if watcher.is_running:
        await callback.answer("Уже запущен", show_alert=True)
        return
    if not await repo.get_active_chats():
        await callback.answer("⚠️ Нет активных чатов!", show_alert=True)
        return
    if not await repo.get_all_active_keywords():
        await callback.answer("⚠️ Нет ключевых слов!", show_alert=True)
        return
    await watcher.start()
    text = await _status(repo, watcher)
    await callback.message.edit_text(
        text, reply_markup=monitor_kb(watcher.is_running), parse_mode="HTML"
    )
    await callback.answer("▶️ Мониторинг запущен!")


@router.callback_query(F.data == "monitor:stop")
async def cb_stop(callback: CallbackQuery, repo: Repository, watcher: MessageWatcher):
    if not watcher.is_running:
        await callback.answer("Уже остановлен", show_alert=True)
        return
    await watcher.stop()
    text = await _status(repo, watcher)
    await callback.message.edit_text(
        text, reply_markup=monitor_kb(watcher.is_running), parse_mode="HTML"
    )
    await callback.answer("⏹ Остановлен")
