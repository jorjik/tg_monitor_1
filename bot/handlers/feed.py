import html

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.keyboards import feed_kb, feed_item_kb
from db.repository import Repository

router = Router()
PAGE_SIZE = 5


@router.message(F.text == "📰 Лента")
@router.message(Command("feed"))
async def cmd_feed(message: Message, repo: Repository):
    await _show(message, repo, message.from_user.id, 0, edit=False)


@router.callback_query(F.data.startswith("feed_page:"))
async def cb_feed_page(callback: CallbackQuery, repo: Repository):
    page = int(callback.data.split(":")[1])
    await _show(callback.message, repo, callback.from_user.id, page, edit=True)
    await callback.answer()


async def _show(msg, repo: Repository, user_tg_id: int, page: int, edit: bool):
    total = await repo.get_feed_total(user_tg_id)
    unread = await repo.get_unread_count(user_tg_id)
    items = await repo.get_feed(user_tg_id, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    if not items and page == 0:
        text = "📰 <b>Лента пуста</b>\n\nЗапустите мониторинг — совпадения появятся здесь."
        kb = feed_kb([], 0, 0)
    else:
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        text = (
            f"📰 <b>Лента</b>\n"
            f"Всего: {total} | 🆕 Непрочитано: {unread}\n"
            f"Стр. {page + 1}/{pages}"
        )
        kb = feed_kb(items, page, total, PAGE_SIZE)
    if edit:
        try:
            await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await msg.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("feed_item:"))
async def cb_feed_item(callback: CallbackQuery, repo: Repository):
    parts = callback.data.split(":")
    item_id, back = int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
    user_tg_id = callback.from_user.id
    item = await repo.get_feed_item(user_tg_id, item_id)
    if not item:
        await callback.answer("Не найдено", show_alert=True)
        return
    await repo.mark_read(user_tg_id, item_id)
    chat_title = html.escape(item["chat_title"] or "")
    sender_name = html.escape(item["sender_name"] or "")
    matched_keywords = html.escape(item["matched_keywords"] or "")
    preview = html.escape((item["message_text"] or "")[:1000])
    text = (
        f"💬 <b>{chat_title}</b>\n"
        f"👤 {sender_name}\n"
        f"🔑 {matched_keywords}\n"
        f"🕐 {item['received_at']}\n\n"
        f"{preview}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=feed_item_kb(item_id, item.get("message_url", ""), back),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("read_item:"))
async def cb_read_item(callback: CallbackQuery, repo: Repository):
    parts = callback.data.split(":")
    item_id, back = int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
    user_tg_id = callback.from_user.id
    await repo.mark_read(user_tg_id, item_id)
    await callback.answer("✅ Прочитано")
    await _show(callback.message, repo, user_tg_id, back, edit=True)


@router.callback_query(F.data == "feed_read_all")
async def cb_read_all(callback: CallbackQuery, repo: Repository):
    user_tg_id = callback.from_user.id
    await repo.mark_all_read(user_tg_id)
    await callback.answer("✅ Все прочитаны")
    await _show(callback.message, repo, user_tg_id, 0, edit=True)
