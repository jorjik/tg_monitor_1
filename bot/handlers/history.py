import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import history_interval_kb
from bot.states import HistoryForm
from core.config import ADMIN_USER_ID
from db.repository import Repository
from userbot.collector import ChatCollector
from userbot.history import (
    HISTORY_PREVIEW_LIMIT,
    MAX_HISTORY_MESSAGES,
    HistoryScanner,
    parse_history_interval,
)

router = Router()
logger = logging.getLogger(__name__)


def _is_admin(user_tg_id: int) -> bool:
    return bool(ADMIN_USER_ID and user_tg_id == ADMIN_USER_ID)


async def _callback_answer_message(callback: CallbackQuery, text: str, **kwargs) -> Message:
    if isinstance(callback.message, Message):
        return await callback.message.answer(text, **kwargs)
    return await callback.bot.send_message(callback.from_user.id, text, **kwargs)


async def _hide_callback_keyboard(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest as e:
        logger.info("Не удалось убрать кнопки выбора истории: %s", e)


def _result_summary(
    start, end, total_chats: int, totals: dict, previews: list[tuple[dict, object]]
) -> str:
    scanned_chats = total_chats - totals["skipped_no_keywords"] - totals["errors"]
    lines = [
        "✅ <b>Разовый поиск истории завершён</b>",
        "",
        f"💬 <b>Чатов всего:</b> {total_chats}",
        f"✅ <b>Чатов просканировано:</b> {scanned_chats}",
        f"🕒 <b>Интервал:</b> <code>{start:%Y-%m-%d %H:%M} — {end:%Y-%m-%d %H:%M}</code>",
        f"🔑 <b>Ключевых слов:</b> {totals['keywords']}",
        f"📖 <b>Проверено сообщений:</b> {totals['scanned']}",
        f"🎯 <b>Совпадений:</b> {totals['matched']}",
        f"📰 <b>Добавлено в ленту:</b> {totals['saved']}",
    ]
    if totals["skipped_no_keywords"]:
        lines.append(f"⏭️ Пропущено без ключевых слов: {totals['skipped_no_keywords']}")
    if totals["matched"] > totals["saved"]:
        lines.append(f"↩️ Уже были в ленте: {totals['matched'] - totals['saved']}")
    if totals["errors"]:
        lines.append(f"⚠️ Чатов с ошибкой: {totals['errors']}")
    if totals["limited_chats"]:
        lines.append(
            f"⚠️ В {totals['limited_chats']} чатах достигнут лимит {MAX_HISTORY_MESSAGES} сообщений."
        )
    if not totals["keywords"]:
        lines.append("⚠️ Нет активных ключевых слов для поиска.")
    if previews:
        lines.extend(["", "<b>Первые совпадения:</b>"])
        for chat, item in previews[:HISTORY_PREVIEW_LIMIT]:
            keywords = ", ".join(f"«{html.escape(k)}»" for k in item.matched_keywords)
            preview = html.escape(" ".join(item.text.split())[:180])
            if len(item.text) > 180:
                preview += "…"
            saved_icon = "🆕" if item.saved else "↩️"
            lines.append(
                f"{saved_icon} <a href=\"{item.url}\">{item.date:%Y-%m-%d %H:%M}</a> "
                f"{html.escape(chat['title'])}: {keywords}\n"
                f"{html.escape(item.sender_name)}: {preview}"
            )
    return "\n".join(lines)


@router.message(F.text == "🕘 История")
@router.message(Command("history"))
async def cmd_history(message: Message, state: FSMContext, repo: Repository):
    user_tg_id = message.from_user.id
    if not _is_admin(user_tg_id):
        await message.answer("Эта функция доступна только администратору.")
        return
    chats = await repo.get_history_chats(user_tg_id)
    if not chats:
        await message.answer("⚠️ Нет активных чатов для разового поиска истории.")
        return
    await state.set_state(HistoryForm.waiting_interval)
    await message.answer(
        f"🕘 <b>Разовый поиск по истории</b>\n\n"
        f"Активных чатов: <b>{len(chats)}</b>\n\n"
        "Выберите интервал:\n"
        "• <code>24ч</code> — последние 24 часа\n"
        "• <code>7д</code> — последние 7 дней\n\n"
        f"В каждом чате будет проверено до {MAX_HISTORY_MESSAGES} сообщений. "
        "Совпадения добавятся в ленту без рассылки уведомлений.",
        reply_markup=history_interval_kb(),
        parse_mode="HTML",
    )


@router.callback_query(HistoryForm.waiting_interval, F.data.startswith("history_interval:"))
async def process_history_interval(
    callback: CallbackQuery, state: FSMContext, repo: Repository, collector: ChatCollector
):
    user_tg_id = callback.from_user.id
    if not _is_admin(user_tg_id):
        await callback.answer("Эта функция доступна только администратору.", show_alert=True)
        await state.clear()
        return
    interval_value = (callback.data or "").partition(":")[2]
    try:
        start, end = parse_history_interval(interval_value)
    except ValueError as e:
        await callback.answer(f"❌ {str(e)[:190]}", show_alert=True)
        await _hide_callback_keyboard(callback)
        await state.clear()
        return

    chats = await repo.get_history_chats(user_tg_id)
    if not chats:
        await callback.answer("Нет активных чатов для разового поиска истории.", show_alert=True)
        await _hide_callback_keyboard(callback)
        await state.clear()
        return

    await callback.answer("Запускаю поиск")
    await _hide_callback_keyboard(callback)
    await state.clear()
    scanner = HistoryScanner(client=collector.client, repo=repo)
    status = await _callback_answer_message(
        callback,
        f"🕘 Начинаю разовый поиск истории...\n"
        f"Чатов: {len(chats)}\n"
        f"Интервал: <code>{start:%Y-%m-%d %H:%M} — {end:%Y-%m-%d %H:%M}</code>",
        parse_mode="HTML",
    )
    totals = {
        "scanned": 0,
        "matched": 0,
        "saved": 0,
        "keywords": 0,
        "limited_chats": 0,
        "skipped_no_keywords": 0,
        "errors": 0,
    }
    all_keywords: set[str] = set()
    previews: list[tuple[dict, object]] = []

    for index, chat in enumerate(chats, start=1):
        try:
            await status.edit_text(
                f"🕘 Проверяю историю...\n\n"
                f"Прогресс: {index}/{len(chats)}\n"
                f"Чат: <b>{html.escape(chat['title'])}</b>\n"
                f"Уже найдено: {totals['matched']} | добавлено: {totals['saved']}",
                parse_mode="HTML",
            )
        except Exception:
            pass
        try:
            result = await scanner.scan(user_tg_id, chat["topic_id"], chat, start, end)
        except Exception as e:
            totals["errors"] += 1
            await _callback_answer_message(
                callback,
                f"⚠️ Не удалось проверить «{html.escape(chat['title'])}»: {html.escape(str(e))}",
                parse_mode="HTML",
            )
            continue
        if not result.keywords:
            totals["skipped_no_keywords"] += 1
        all_keywords.update(result.keywords)
        totals["scanned"] += result.scanned
        totals["matched"] += result.matched
        totals["saved"] += result.saved
        if result.limit_reached:
            totals["limited_chats"] += 1
        for item in result.preview:
            if len(previews) < HISTORY_PREVIEW_LIMIT:
                previews.append((chat, item))

    totals["keywords"] = len(all_keywords)
    await status.edit_text(
        _result_summary(start, end, len(chats), totals, previews),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(HistoryForm.waiting_interval)
async def process_history_interval_text(message: Message):
    await message.answer(
        "Ручной ввод интервала отключён. Выберите одну из двух кнопок выше: 24ч или 7д.\n"
        "Для отмены отправьте /start."
    )
