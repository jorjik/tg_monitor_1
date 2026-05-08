from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="📋 Темы"), KeyboardButton(text="➕ Новая тема")],
        [KeyboardButton(text="🔑 Ключевые слова"), KeyboardButton(text="📰 Лента")],
        [KeyboardButton(text="⚙️ Мониторинг"), KeyboardButton(text="🚫 Гео-фильтр")],
        [KeyboardButton(text="❓ Помощь")],
    ]
    if is_admin:
        keyboard.insert(3, [KeyboardButton(text="🕘 История")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def topics_kb(topics: list[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in topics:
        cnt = t.get("chat_count", 0)
        b.button(text=f"📂 {t['name']} ({cnt} чатов)", callback_data=f"topic:{t['id']}")
    b.button(text="➕ Новая тема", callback_data="topic:new")
    b.adjust(1)
    return b.as_markup()


def topic_detail_kb(topic_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔍 Собрать чаты (Проход 1)", callback_data=f"collect:{topic_id}")
    b.button(
        text="➕ Добавить чат вручную", callback_data=f"add_chat_manual:{topic_id}"
    )
    b.button(text="💬 Просмотр чатов", callback_data=f"chats:{topic_id}:0")
    b.button(text="🔑 Ключевые слова темы", callback_data=f"kw_topic:{topic_id}")
    b.button(text="🗑 Удалить тему", callback_data=f"del_topic:{topic_id}")
    b.button(text="◀️ Назад", callback_data="topics_list")
    b.adjust(1)
    return b.as_markup()


def chats_kb(
    chats: list[dict], topic_id: int, page: int = 0, page_size: int = 8
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    start = page * page_size
    end = start + page_size
    for c in chats[start:end]:
        icon = "✅" if c["is_active"] else "⭕"
        ticon = "📢" if c["chat_type"] == "channel" else "👥"
        title = c["title"][:28]
        members = c.get("members_count", 0)
        b.button(
            text=f"{icon} {ticon} {title} ({members:,})",
            callback_data=f"toggle_chat:{c['id']}:{topic_id}:{page}",
        )
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="◀️", callback_data=f"chats:{topic_id}:{page - 1}")
        )
    if end < len(chats):
        nav.append(
            InlineKeyboardButton(text="▶️", callback_data=f"chats:{topic_id}:{page + 1}")
        )
    if nav:
        b.row(*nav)
    b.row(
        InlineKeyboardButton(
            text="✅ Все вкл", callback_data=f"chats_all_on:{topic_id}"
        ),
        InlineKeyboardButton(
            text="⭕ Все выкл", callback_data=f"chats_all_off:{topic_id}"
        ),
    )
    b.row(InlineKeyboardButton(text="◀️ К теме", callback_data=f"topic:{topic_id}"))
    return b.as_markup()


def keywords_kb(
    keywords: list[dict], topic_id: int | None = None
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    scope = "global" if topic_id is None else str(topic_id)
    for kw in keywords:
        icon = "✅" if kw["is_active"] else "⭕"
        b.button(text=f"{icon} {kw['word']}", callback_data=f"toggle_kw:{kw['id']}:{scope}")
    b.adjust(2)
    suffix = f":{topic_id}" if topic_id is not None else ":global"
    b.row(InlineKeyboardButton(text="➕ Добавить", callback_data=f"add_kw{suffix}"))
    if topic_id is None:
        b.row(InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    else:
        b.row(InlineKeyboardButton(text="◀️ К теме", callback_data=f"topic:{topic_id}"))
    return b.as_markup()


def feed_kb(
    items: list[dict], page: int, total: int, page_size: int = 5
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for item in items:
        icon = "📖" if item["is_read"] else "🆕"
        title = (item["chat_title"] or "")[:20]
        kws = (item["matched_keywords"] or "")[:20]
        b.button(
            text=f"{icon} {title} | {kws}",
            callback_data=f"feed_item:{item['id']}:{page}",
        )
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="◀️", callback_data=f"feed_page:{page - 1}")
        )
    if (page + 1) * page_size < total:
        nav.append(
            InlineKeyboardButton(text="▶️", callback_data=f"feed_page:{page + 1}")
        )
    if nav:
        b.row(*nav)
    b.row(
        InlineKeyboardButton(text="✅ Всё прочитано", callback_data="feed_read_all"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"feed_page:{page}"),
    )
    return b.as_markup()


def feed_item_kb(item_id: int, url: str, back_page: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if url:
        b.button(text="🔗 Открыть в Telegram", url=url)
    b.button(text="✅ Прочитано", callback_data=f"read_item:{item_id}:{back_page}")
    b.button(text="◀️ Назад", callback_data=f"feed_page:{back_page}")
    b.adjust(1)
    return b.as_markup()


def geo_filter_kb(words: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for w in words:
        b.button(text=f"🗑 {w}", callback_data=f"geo_del:{w}")
    b.adjust(3)
    b.row(InlineKeyboardButton(text="➕ Добавить слово", callback_data="geo_add"))
    b.row(InlineKeyboardButton(text="🚫 Убрать Гео РФ", callback_data="geo_rf"))
    b.row(
        InlineKeyboardButton(text="🧹 Сбросить всё", callback_data="geo_reset")
    )
    b.row(InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()


def monitor_kb(is_running: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Обновить статус", callback_data="monitor:status")
    b.adjust(1)
    return b.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="❌ Отмена", callback_data="cancel")
    return b.as_markup()


def history_interval_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="24ч — последние 24 часа", callback_data="history_interval:24ч")
    b.button(text="7д — последние 7 дней", callback_data="history_interval:7д")
    b.adjust(1)
    return b.as_markup()


def keyword_confirm_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Добавить", callback_data="kw_confirm:add")
    b.button(text="❌ Отмена", callback_data="cancel")
    b.adjust(1)
    return b.as_markup()


def skip_topic_terms_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⏭ Пропустить", callback_data="topic_terms:skip")
    b.button(text="❌ Отмена", callback_data="cancel")
    b.adjust(1)
    return b.as_markup()
