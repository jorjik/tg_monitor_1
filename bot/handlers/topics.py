import asyncio
import html
import logging
from io import BytesIO

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.access import (
    require_callback_access,
    require_message_access,
    require_paid_callback_access,
    require_paid_message_access,
)
from bot.keyboards import (
    cancel_kb,
    chats_kb,
    manual_chat_kb,
    skip_topic_terms_kb,
    topic_detail_kb,
    topics_kb,
)
from bot.states import TopicForm
from db.repository import Repository
from userbot.collector import GEO_EXCLUDE_DEFAULT, ChatCollector

logger = logging.getLogger(__name__)
router = Router()
MAX_CHAT_LIST_FILE_BYTES = 128 * 1024
MAX_CHAT_LIST_ITEMS = 100
CONTROL_TEXTS = {
    "📋 Темы",
    "➕ Новая тема",
    "🔑 Ключевые слова",
    "📰 Лента",
    "⚙️ Мониторинг",
    "🚫 Гео-фильтр",
    "🕘 История",
    "💳 Подписка",
    "💎 Тарифы",
    "❓ Помощь",
}


def _is_control_text(value: str) -> bool:
    text = value.strip()
    return text in CONTROL_TEXTS or text.startswith("/")


def _split_search_terms(value: str) -> list[str]:
    return list(
        dict.fromkeys(
            t.strip() for t in value.split(",") if t.strip() and not _is_control_text(t)
        )
    )


def _collection_terms(topic: dict) -> tuple[list[str], str]:
    terms = _split_search_terms(topic.get("search_terms") or "")
    if terms:
        return terms, "доп. слова темы"
    name = (topic.get("name") or "").strip()
    return ([name] if name else []), "название темы"


def _terms_preview(terms: list[str], limit: int = 5) -> str:
    preview = ", ".join(terms[:limit])
    if len(terms) > limit:
        preview += f" и ещё {len(terms) - limit}"
    return preview


def _parse_chat_list_file(value: str) -> list[str]:
    chats: list[str] = []
    seen: set[str] = set()
    for line in value.splitlines():
        item = line.strip()
        if not item:
            continue
        if item not in seen:
            seen.add(item)
            chats.append(item)
        if len(chats) > MAX_CHAT_LIST_ITEMS:
            raise ValueError(f"В файле больше {MAX_CHAT_LIST_ITEMS} чатов.")
    if not chats:
        raise ValueError("Файл не содержит чатов.")
    return chats


def _decode_chat_list_file(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError("Не удалось прочитать файл. Сохраните список в UTF-8 или Windows-1251.")


@router.message(F.text == "📋 Темы")
@router.message(Command("topics"))
async def cmd_topics(message: Message, repo: Repository):
    if not await require_message_access(message, repo):
        return
    user_tg_id = message.from_user.id
    topics = await repo.get_topics(user_tg_id)
    if not topics:
        await message.answer(
            "📂 Нет тем.\n\nНажмите <b>➕ Новая тема</b> чтобы создать первую.",
            reply_markup=topics_kb([]),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"📂 <b>Ваши темы</b> ({len(topics)}):",
            reply_markup=topics_kb(topics),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "topics_list")
async def cb_topics_list(callback: CallbackQuery, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    topics = await repo.get_topics(user_tg_id)
    await callback.message.edit_text(
        f"📂 <b>Ваши темы</b> ({len(topics)}):",
        reply_markup=topics_kb(topics),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("topic:"))
async def cb_topic_detail(callback: CallbackQuery, repo: Repository, state: FSMContext):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    topic_id_str = callback.data.split(":")[1]
    if topic_id_str == "new":
        await state.set_state(TopicForm.waiting_name)
        await callback.message.answer(
            "📝 <b>Новая тема</b>\n\nВведите <b>название темы</b>:",
            reply_markup=cancel_kb(),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    topic_id = int(topic_id_str)
    topic = await repo.get_topic(user_tg_id, topic_id)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    chats = await repo.get_chats(user_tg_id, topic_id)
    active = sum(1 for c in chats if c["is_active"])
    terms, terms_source = _collection_terms(topic)
    if terms_source == "доп. слова темы":
        search_text = _terms_preview(terms, limit=8)
    else:
        search_text = f"не заданы, сбор по названию темы «{topic['name']}»"
    text = (
        f"📂 <b>Тема: {html.escape(topic['name'])}</b>\n\n"
        f"🔍 Доп. слова темы: {html.escape(search_text)}\n"
        f"💬 Чатов: {len(chats)} (активных: {active})"
    )
    await callback.message.edit_text(
        text, reply_markup=topic_detail_kb(topic_id), parse_mode="HTML"
    )
    await callback.answer()


@router.message(F.text == "➕ Новая тема")
@router.message(Command("new_topic"))
async def cmd_new_topic(message: Message, state: FSMContext, repo: Repository):
    if not await require_message_access(message, repo):
        return
    await state.set_state(TopicForm.waiting_name)
    await message.answer(
        "📝 <b>Новая тема</b>\n\nВведите <b>название</b> (напр. Бизнес, Крипта):",
        reply_markup=cancel_kb(),
        parse_mode="HTML",
    )


@router.message(TopicForm.waiting_name)
async def process_topic_name(message: Message, state: FSMContext, repo: Repository):
    if not await require_message_access(message, repo):
        await state.clear()
        return
    user_tg_id = message.from_user.id
    name = (message.text or "").strip()
    if _is_control_text(name):
        await message.answer("Введите название темы текстом или нажмите ❌ Отмена.")
        return
    if len(name) < 2:
        await message.answer("❌ Слишком короткое название.")
        return
    if await repo.get_topic_by_name(user_tg_id, name):
        await message.answer(f"⚠️ Тема «{html.escape(name)}» уже существует.", parse_mode="HTML")
        return
    await state.update_data(topic_name=name)
    await state.set_state(TopicForm.waiting_search_terms)
    await message.answer(
        f"✅ Название: <b>{html.escape(name)}</b>\n\n"
        "Введите <b>доп. слова темы</b> через запятую.\n"
        "Напр: <code>стартап, инвестиции, франшиза</code>\n\n"
        "Или нажмите <b>⏭ Пропустить</b> — тогда первый сбор попробует искать по названию темы.",
        reply_markup=skip_topic_terms_kb(),
        parse_mode="HTML",
    )


@router.message(TopicForm.waiting_search_terms)
async def process_search_terms(message: Message, state: FSMContext, repo: Repository):
    if not await require_message_access(message, repo):
        await state.clear()
        return
    user_tg_id = message.from_user.id
    terms_list = _split_search_terms(message.text or "")
    if not terms_list:
        await message.answer("❌ Введите хотя бы одно слово.")
        return
    terms = ", ".join(terms_list)
    data = await state.get_data()
    topic_id = await repo.create_topic(user_tg_id, data["topic_name"], terms)
    keywords = [term.lower() for term in terms_list]
    added_keywords = 0
    for keyword in keywords:
        if await repo.add_keyword(user_tg_id, keyword, topic_id=topic_id):
            added_keywords += 1
    await state.clear()
    await message.answer(
        f"✅ <b>Тема «{html.escape(data['topic_name'])}» создана!</b>\n\n"
        f"Доп. слова темы: {html.escape(terms)}\n"
        f"Ключевых слов добавлено: {added_keywords}\n\n"
        "Нажмите <b>🔍 Собрать чаты</b> для первого прохода.",
        reply_markup=topic_detail_kb(topic_id),
        parse_mode="HTML",
    )


@router.callback_query(TopicForm.waiting_search_terms, F.data == "topic_terms:skip")
async def cb_skip_search_terms(callback: CallbackQuery, state: FSMContext, repo: Repository):
    if not await require_callback_access(callback, repo):
        await state.clear()
        return
    user_tg_id = callback.from_user.id
    data = await state.get_data()
    topic_id = await repo.create_topic(user_tg_id, data["topic_name"], "")
    await state.clear()
    await callback.message.answer(
        f"✅ <b>Тема «{html.escape(data['topic_name'])}» создана без ключевых слов.</b>\n\n"
        "При сборе чатов бот попробует искать по названию темы.\n"
        "Ключевые слова можно добавить позже в разделе темы или через главное меню.",
        reply_markup=topic_detail_kb(topic_id),
        parse_mode="HTML",
    )
    await callback.answer("Пропущено")


@router.callback_query(F.data.startswith("del_topic:"))
async def cb_delete_topic(callback: CallbackQuery, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    topic_id = int(callback.data.split(":")[1])
    topic = await repo.get_topic(user_tg_id, topic_id)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await repo.delete_topic(user_tg_id, topic_id)
    topics = await repo.get_topics(user_tg_id)
    await callback.message.edit_text(
        f"🗑 Тема «{html.escape(topic['name'])}» удалена.\n\n📂 <b>Темы</b> ({len(topics)}):",
        reply_markup=topics_kb(topics),
        parse_mode="HTML",
    )
    await callback.answer("Удалено")


@router.callback_query(F.data.startswith("collect:"))
async def cb_collect(
    callback: CallbackQuery, repo: Repository, collector: ChatCollector
):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    topic_id = int(callback.data.split(":")[1])
    topic = await repo.get_topic(user_tg_id, topic_id)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    terms, terms_source = _collection_terms(topic)
    if not terms:
        await callback.answer("Нет доп. слов темы для сбора", show_alert=True)
        return
    terms_text = html.escape(_terms_preview(terms))
    msg = await callback.message.edit_text(
        f"🔍 <b>Проход 1: Сбор чатов</b>\n\n"
        f"Тема: {html.escape(topic['name'])}\n"
        f"Источник: {terms_source}\n"
        f"Ищу: <code>{terms_text}</code>\n"
        f"Слов: {len(terms)}\n\n"
        "⏳ Начинаю...",
        parse_mode="HTML",
    )
    await callback.answer()

    # Загружаем гео-фильтр из настроек
    raw_exclude = await repo.get_setting("geo_exclude", "", user_tg_id=user_tg_id)
    exclude_words = [w.strip() for w in raw_exclude.split(",") if w.strip()]

    async def on_progress(current, total, term, found_cnt, excl_cnt):
        try:
            await msg.edit_text(
                f"🔍 <b>Проход 1: Сбор чатов</b>\n\n"
                f"Прогресс: {current}/{total}\n"
                f"🔎 Ищу: «{html.escape(term)}»\n"
                f"Найдено: {found_cnt} | Отфильтровано: {excl_cnt}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    await collector.collect(
        topic_id=topic_id,
        search_terms=terms,
        limit_per_term=50,
        exclude_words=exclude_words,
        progress_callback=on_progress,
    )
    chats = await repo.get_chats(user_tg_id, topic_id)
    await msg.edit_text(
        f"✅ <b>Сбор завершён!</b>\n\n"
        f"Тема: <b>{html.escape(topic['name'])}</b>\n"
        f"Искал по: <code>{terms_text}</code>\n"
        f"Найдено чатов: <b>{len(chats)}</b>\n\n"
        "Выберите какие чаты мониторить.",
        reply_markup=topic_detail_kb(topic_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("add_chat_manual:"))
async def cb_add_chat_manual_start(callback: CallbackQuery, state: FSMContext, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    topic_id = int(callback.data.split(":")[1])
    if not await repo.get_topic(user_tg_id, topic_id):
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.message.edit_text(
        "➕ <b>Добавить чаты вручную</b>\n\n"
        "Выберите способ добавления:",
        reply_markup=manual_chat_kb(topic_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("add_chat_text:"))
async def cb_add_chat_text_start(callback: CallbackQuery, state: FSMContext, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    topic_id = int(callback.data.split(":")[1])
    if not await repo.get_topic(user_tg_id, topic_id):
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await state.set_state(TopicForm.waiting_manual_chat)
    await state.update_data(manual_topic_id=topic_id, manual_user_tg_id=user_tg_id)
    await callback.message.answer(
        "✏️ <b>Ручное добавление чата</b>\n\n"
        "Отправьте @username, ссылку или название:\n"
        "• <code>@startup_global</code>\n"
        "• <code>https://t.me/startup_global</code>",
        reply_markup=cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("add_chat_file:"))
async def cb_add_chat_file_start(callback: CallbackQuery, state: FSMContext, repo: Repository):
    if not await require_paid_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    topic_id = int(callback.data.split(":")[1])
    if not await repo.get_topic(user_tg_id, topic_id):
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await state.set_state(TopicForm.waiting_manual_chat_file)
    await state.update_data(manual_topic_id=topic_id, manual_user_tg_id=user_tg_id)
    await callback.message.answer(
        "📄 <b>Загрузка списка чатов</b>\n\n"
        "Прикрепите текстовый файл до 128 КБ.\n"
        "Каждый чат — с новой строки:\n"
        "• <code>@startup_global</code>\n"
        "• <code>https://t.me/startup_global</code>",
        reply_markup=cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(TopicForm.waiting_manual_chat)
async def process_manual_chat(message: Message, state: FSMContext, repo, collector):
    if not await require_message_access(message, repo):
        await state.clear()
        return
    data = await state.get_data()
    topic_id = data["manual_topic_id"]
    user_tg_id = data["manual_user_tg_id"]
    await state.clear()
    if not await repo.get_topic(user_tg_id, topic_id):
        await message.answer("Тема не найдена.")
        return

    ok, text = await collector.add_by_username(topic_id, message.text or "")
    icon = "✅" if ok else "❌"
    await message.answer(
        f"{icon} {html.escape(text)}",
        reply_markup=topic_detail_kb(topic_id),
        parse_mode="HTML",
    )


@router.message(TopicForm.waiting_manual_chat_file)
async def process_manual_chat_file(message: Message, state: FSMContext, repo, collector):
    if not await require_paid_message_access(message, repo):
        await state.clear()
        return
    data = await state.get_data()
    topic_id = data["manual_topic_id"]
    user_tg_id = data["manual_user_tg_id"]
    if not await repo.get_topic(user_tg_id, topic_id):
        await state.clear()
        await message.answer("Тема не найдена.")
        return
    document = message.document
    if not document:
        await message.answer("❌ Прикрепите текстовый файл со списком чатов.", reply_markup=cancel_kb())
        return
    if document.file_size and document.file_size > MAX_CHAT_LIST_FILE_BYTES:
        await message.answer("❌ Файл слишком большой. Максимум: 128 КБ.", reply_markup=cancel_kb())
        return
    buffer = BytesIO()
    try:
        await message.bot.download(document.file_id, destination=buffer)
    except Exception:
        logger.exception("Failed to download chat list file")
        await message.answer(
            "❌ Не удалось скачать файл. Попробуйте позже.",
            reply_markup=cancel_kb(),
        )
        return
    raw_data = buffer.getvalue()
    if len(raw_data) > MAX_CHAT_LIST_FILE_BYTES:
        await message.answer("❌ Файл слишком большой. Максимум: 128 КБ.", reply_markup=cancel_kb())
        return
    try:
        chats_to_add = _parse_chat_list_file(_decode_chat_list_file(raw_data))
    except ValueError as e:
        await message.answer(f"❌ {html.escape(str(e))}", reply_markup=cancel_kb(), parse_mode="HTML")
        return

    await state.clear()
    added = 0
    failed: list[str] = []
    for index, raw in enumerate(chats_to_add):
        ok, text = await collector.add_by_username(topic_id, raw)
        if ok:
            added += 1
        else:
            failed.append(f"{raw} — {text}")
        if index + 1 < len(chats_to_add):
            await asyncio.sleep(0.4)

    result = (
        f"📄 <b>Импорт завершён</b>\n\n"
        f"Всего в файле: <b>{len(chats_to_add)}</b>\n"
        f"✅ Добавлено: <b>{added}</b>\n"
        f"❌ Не добавлено: <b>{len(failed)}</b>"
    )
    if failed:
        preview = "\n".join(f"• {html.escape(item)}" for item in failed[:10])
        result += f"\n\n<b>Ошибки:</b>\n{preview}"
        if len(failed) > 10:
            result += f"\n…и ещё {len(failed) - 10}"
    await message.answer(
        result,
        reply_markup=topic_detail_kb(topic_id),
        parse_mode="HTML",
    )


async def _refresh_chats(
    callback: CallbackQuery, repo: Repository, user_tg_id: int, topic_id: int, page: int
):
    """Обновить сообщение со списком чатов."""
    topic = await repo.get_topic(user_tg_id, topic_id)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    chats = await repo.get_chats(user_tg_id, topic_id)
    active = sum(1 for c in chats if c["is_active"])
    try:
        await callback.message.edit_text(
            f"💬 <b>Чаты «{html.escape(topic['name'])}»</b>\n"
            f"Всего: {len(chats)} | Активных: {active}\n\n"
            "✅ — мониторится | ⭕ — выключен",
            reply_markup=chats_kb(chats, topic_id, page),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("chats:"))
async def cb_view_chats(callback: CallbackQuery, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    parts = callback.data.split(":")
    topic_id, page = int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
    topic = await repo.get_topic(user_tg_id, topic_id)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    chats = await repo.get_chats(user_tg_id, topic_id)
    if not chats:
        await callback.message.edit_text(
            f"💬 Нет чатов для «{html.escape(topic['name'])}».\nЗапустите 🔍 Собрать чаты.",
            reply_markup=topic_detail_kb(topic_id),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    await callback.answer()
    await _refresh_chats(callback, repo, user_tg_id, topic_id, page)


@router.callback_query(F.data.startswith("chats_all_on:"))
async def cb_chats_all_on(callback: CallbackQuery, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    topic_id = int(callback.data.split(":")[1])
    count = await repo.set_all_chats_active(user_tg_id, topic_id, True)
    await callback.answer(f"✅ Включено {count} чатов")
    await _refresh_chats(callback, repo, user_tg_id, topic_id, page=0)


@router.callback_query(F.data.startswith("chats_all_off:"))
async def cb_chats_all_off(callback: CallbackQuery, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    topic_id = int(callback.data.split(":")[1])
    count = await repo.set_all_chats_active(user_tg_id, topic_id, False)
    await callback.answer(f"⭕ Выключено {count} чатов")
    await _refresh_chats(callback, repo, user_tg_id, topic_id, page=0)


@router.callback_query(F.data.startswith("toggle_chat:"))
async def cb_toggle_chat(callback: CallbackQuery, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    parts = callback.data.split(":")
    chat_id, topic_id = int(parts[1]), int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    new_state = await repo.toggle_chat(user_tg_id, chat_id)
    await callback.answer("✅ Включён" if new_state else "⭕ Выключен")
    await _refresh_chats(callback, repo, user_tg_id, topic_id, page)
