from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.access import is_admin, require_callback_access, require_message_access
from bot.keyboards import monitor_kb
from db.repository import Repository
from userbot.watcher import MessageWatcher

router = Router()


def _uptime_text(started_at: datetime) -> str:
    delta = datetime.now(timezone.utc) - started_at
    total_seconds = max(0, int(delta.total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours:
        return f"{hours}ч {minutes}м"
    return f"{minutes}м"


async def _admin_status_text(
    repo: Repository, watcher: MessageWatcher, collector, started_at: datetime
) -> str:
    total_users = await repo.count_bot_users()
    active_users = await repo.count_active_bot_users()
    total_chats = await repo.count_chats(active_only=False)
    active_chats = await repo.count_chats(active_only=True)
    total_keywords = await repo.count_keywords(active_only=False)
    active_keywords = await repo.count_keywords(active_only=True)
    feed_today = await repo.count_feed_since(datetime.now(timezone.utc) - timedelta(days=1))
    telethon_ok = bool(getattr(collector, "client", None) and collector.client.is_connected())
    watcher_icon = "🟢" if watcher.is_running else "🔴"
    telethon_icon = "🟢" if telethon_ok else "🔴"
    return (
        "🛠 <b>Статус бота</b>\n\n"
        f"Uptime: <b>{_uptime_text(started_at)}</b>\n"
        f"Watcher: {watcher_icon}\n"
        f"Telethon: {telethon_icon}\n\n"
        f"Пользователей: <b>{total_users}</b>\n"
        f"Активных пользователей: <b>{active_users}</b>\n"
        f"Чатов: <b>{active_chats}/{total_chats}</b>\n"
        f"Ключевых слов: <b>{active_keywords}/{total_keywords}</b>\n"
        f"Совпадений за 24ч: <b>{feed_today}</b>"
    )


async def _status(repo: Repository, watcher: MessageWatcher, user_tg_id: int) -> str:
    chats = await repo.get_active_chats(user_tg_id)
    kws = await repo.get_all_active_keywords(user_tg_id)
    unread = await repo.get_unread_count(user_tg_id)
    cooldown = await repo.get_notification_cooldown_minutes(user_tg_id)
    icon = "🟢 Активен" if watcher.is_running else "🔴 Остановлен"
    cooldown_text = "сразу" if cooldown <= 0 else f"не чаще {cooldown} мин"
    return (
        f"⚙️ <b>Мониторинг</b>\n\n"
        f"Статус сервиса: {icon}\n"
        f"💬 Ваших активных чатов: {len(chats)}\n"
        f"🔑 Ваших активных ключевых слов: {len(kws)}\n"
        f"📰 Ваших непрочитанных: {unread}\n"
        f"🔔 Уведомления: {cooldown_text}"
    )


@router.message(Command("status"))
async def cmd_admin_status(message: Message, repo: Repository, watcher: MessageWatcher, collector, started_at):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    text = await _admin_status_text(repo, watcher, collector, started_at)
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "⚙️ Мониторинг")
@router.message(Command("monitor"))
async def cmd_monitor(message: Message, repo: Repository, watcher: MessageWatcher):
    if not await require_message_access(message, repo):
        return
    text = await _status(repo, watcher, message.from_user.id)
    cooldown = await repo.get_notification_cooldown_minutes(message.from_user.id)
    await message.answer(
        text,
        reply_markup=monitor_kb(watcher.is_running, cooldown),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "monitor:status")
async def cb_status(callback: CallbackQuery, repo: Repository, watcher: MessageWatcher):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    text = await _status(repo, watcher, user_tg_id)
    cooldown = await repo.get_notification_cooldown_minutes(user_tg_id)
    try:
        await callback.message.edit_text(
            text,
            reply_markup=monitor_kb(watcher.is_running, cooldown),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer("Обновлено")


@router.callback_query(F.data.startswith("monitor:cooldown:"))
async def cb_cooldown(callback: CallbackQuery, repo: Repository, watcher: MessageWatcher):
    if not await require_callback_access(callback, repo):
        return
    minutes = int(callback.data.split(":")[2])
    await repo.set_notification_cooldown_minutes(callback.from_user.id, minutes)
    text = await _status(repo, watcher, callback.from_user.id)
    await callback.message.edit_text(
        text,
        reply_markup=monitor_kb(watcher.is_running, minutes),
        parse_mode="HTML",
    )
    await callback.answer("Настройка уведомлений обновлена")


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
    cooldown = await repo.get_notification_cooldown_minutes(user_tg_id)
    await callback.message.edit_text(
        text,
        reply_markup=monitor_kb(watcher.is_running, cooldown),
        parse_mode="HTML",
    )
    await callback.answer("Мониторинг запускается автоматически", show_alert=True)


@router.callback_query(F.data == "monitor:stop")
async def cb_stop(callback: CallbackQuery, repo: Repository, watcher: MessageWatcher):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    text = await _status(repo, watcher, user_tg_id)
    cooldown = await repo.get_notification_cooldown_minutes(user_tg_id)
    await callback.message.edit_text(
        text,
        reply_markup=monitor_kb(watcher.is_running, cooldown),
        parse_mode="HTML",
    )
    await callback.answer("Отключайте отдельные чаты или ключевые слова в настройках", show_alert=True)
