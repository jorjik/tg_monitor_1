from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

def main_menu_kb(is_admin: bool = False, has_access: bool = True) -> ReplyKeyboardMarkup:
    if not is_admin and not has_access:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="💳 Подписка")],
                [KeyboardButton(text="🤝 Партнерка")],
                [KeyboardButton(text="❓ Помощь")],
            ],
            resize_keyboard=True,
        )
    keyboard = [
        [KeyboardButton(text="📋 Темы"), KeyboardButton(text="➕ Новая тема")],
        [KeyboardButton(text="🔑 Ключевые слова"), KeyboardButton(text="📰 Лента")],
        [KeyboardButton(text="⚙️ Мониторинг"), KeyboardButton(text="🚫 Гео-фильтр")],
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text="🕘 История"), KeyboardButton(text="💎 Тарифы")])
        keyboard.append([KeyboardButton(text="👥 Пользователи"), KeyboardButton(text="🤝 Партнерка")])
        keyboard.append([KeyboardButton(text="❓ Помощь")])
    else:
        keyboard.append([KeyboardButton(text="🕘 История"), KeyboardButton(text="💳 Подписка")])
        keyboard.append([KeyboardButton(text="🤝 Партнерка"), KeyboardButton(text="❓ Помощь")])
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


def manual_chat_kb(topic_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Ввести один чат", callback_data=f"add_chat_text:{topic_id}")
    b.button(text="📄 Загрузить файл со списком", callback_data=f"add_chat_file:{topic_id}")
    b.button(text="◀️ К теме", callback_data=f"topic:{topic_id}")
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
        title = c["title"][:25]
        members = c.get("members_count", 0)

        row = [
            InlineKeyboardButton(
                text=f"{icon} {title} ({members:,})",
                callback_data=f"toggle_chat:{c['id']}:{topic_id}:{page}"
            )
        ]

        if c.get("username"):
            row.append(InlineKeyboardButton(text="открыть", url=f"https://t.me/{c['username']}"))

        b.row(*row)
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
    b.row(InlineKeyboardButton(text="➖ Минус-слова", callback_data=f"minus_words{suffix}"))
    if topic_id is None:
        b.row(InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    else:
        b.row(InlineKeyboardButton(text="◀️ К теме", callback_data=f"topic:{topic_id}"))
    return b.as_markup()


def minus_words_kb(words: list[str], topic_id: int | None = None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    scope = "global" if topic_id is None else str(topic_id)
    for index, word in enumerate(words):
        b.button(text=f"➖ {word}", callback_data=f"minus_word:{scope}:{index}")
    if topic_id is None:
        back = InlineKeyboardButton(text="◀️ К ключевым словам", callback_data="kw_global")
    else:
        back = InlineKeyboardButton(text="◀️ К ключевым словам темы", callback_data=f"kw_topic:{topic_id}")
    b.adjust(1)
    b.row(back)
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


def monitor_kb(is_running: bool, cooldown_minutes: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Обновить статус", callback_data="monitor:status")
    if cooldown_minutes:
        b.button(text="🔔 Уведомлять сразу", callback_data="monitor:cooldown:0")
    else:
        b.button(text="🔕 Не чаще раз в 10 мин", callback_data="monitor:cooldown:10")
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


def history_result_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data="main_menu")
    return b.as_markup()


def _payment_enabled(payment_methods: dict[str, bool] | None, method: str) -> bool:
    return True if payment_methods is None else bool(payment_methods.get(method))


def subscription_kb(
    tariffs: list[dict], payment_methods: dict[str, bool] | None = None
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for tariff in tariffs:
        if _payment_enabled(payment_methods, "kofi"):
            b.button(
                text=f"🌍 Ko-fi — {tariff['duration_days']} дн.",
                callback_data=f"billing_kofi:{tariff['id']}",
            )
        if _payment_enabled(payment_methods, "paypal"):
            b.button(
                text=f"💳 PayPal — {tariff['duration_days']} дн.",
                callback_data=f"billing_paypal:{tariff['id']}",
            )
        if _payment_enabled(payment_methods, "monobank"):
            b.button(
                text=f"🇺🇦 Monobank — {tariff['duration_days']} дн.",
                callback_data=f"billing_monobank:{tariff['id']}",
            )
    b.button(text="🔙 Назад", callback_data="main_menu")
    b.adjust(1)
    return b.as_markup()


def kofi_payment_kb(page_url: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🌍 Открыть Ko-fi", url=page_url)
    b.button(text="◀️ К подписке", callback_data="billing_back")
    b.adjust(1)
    return b.as_markup()


def paypal_payment_kb(approval_url: str, order_id: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💳 Оплатить через PayPal", url=approval_url)
    b.button(text="✅ Проверить статус", callback_data=f"paypal_check:{order_id}")
    b.button(text="◀️ К подписке", callback_data="billing_back")
    b.adjust(1)
    return b.as_markup()


def monobank_payment_kb(code: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="◀️ К подписке", callback_data="billing_back")
    b.adjust(1)
    return b.as_markup()


def admin_tariffs_kb(tariffs: list[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for tariff in tariffs:
        icon = "✅" if tariff["is_active"] else "⭕"
        b.button(
            text=f"{icon} {tariff['stars']}⭐ / {tariff['duration_days']} дн.",
            callback_data=f"admin_tariff:{tariff['id']}",
        )
    b.button(text="➕ Новый тариф", callback_data="admin_tariff:new")
    b.button(text="🎁 Демо-доступ", callback_data="admin_trial_days")
    b.button(text="💳 Способы оплаты", callback_data="admin_payment_methods")
    b.button(text="⚠️ Проверка оплат", callback_data="admin_payment_reviews")
    b.adjust(1)
    return b.as_markup()


def admin_payment_methods_kb(payment_methods: dict[str, bool]) -> InlineKeyboardMarkup:
    labels = {
        "monobank": "Monobank",
        "kofi": "Ko-fi",
        "paypal": "PayPal",
    }
    b = InlineKeyboardBuilder()
    for method, label in labels.items():
        icon = "✅" if payment_methods.get(method) else "⭕"
        b.button(text=f"{icon} {label}", callback_data=f"admin_payment_toggle:{method}")
    b.button(text="◀️ К тарифам", callback_data="admin_tariffs")
    b.adjust(1)
    return b.as_markup()


def admin_users_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📋 Список пользователей", callback_data="admin_users_list:0")
    b.button(text="🔍 Поиск", callback_data="admin_users_search")
    b.adjust(1)
    return b.as_markup()


def admin_users_list_kb(
    users: list[dict],
    page: int,
    total: int,
    page_size: int = 10,
    status_filter: str = "all",
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for user in users:
        name = f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
        label = f"@{user['username']}" if user.get("username") else name or str(user["tg_id"])
        b.button(text=f"👤 {label}"[:64], callback_data=f"admin_user:{user['tg_id']}")
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀️", callback_data=f"admin_users_list:{page - 1}:{status_filter}"
            )
        )
    if (page + 1) * page_size < total:
        nav.append(
            InlineKeyboardButton(
                text="▶️", callback_data=f"admin_users_list:{page + 1}:{status_filter}"
            )
        )
    if nav:
        b.row(*nav)
    b.row(
        InlineKeyboardButton(text="Все", callback_data="admin_users_list:0:all"),
        InlineKeyboardButton(text="Активные", callback_data="admin_users_list:0:active"),
    )
    b.row(
        InlineKeyboardButton(text="Платные", callback_data="admin_users_list:0:paid"),
        InlineKeyboardButton(text="Демо", callback_data="admin_users_list:0:trial"),
    )
    b.row(
        InlineKeyboardButton(text="Без оплаты", callback_data="admin_users_list:0:none"),
        InlineKeyboardButton(text="Отключены", callback_data="admin_users_list:0:inactive"),
    )
    b.row(InlineKeyboardButton(text="🔍 Поиск", callback_data="admin_users_search"))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_users"))
    return b.as_markup()


def admin_payment_reviews_kb(kofi_payments: list[dict], monobank_payments: list[dict] = None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()

    # Ko-fi платежи
    for payment in kofi_payments:
        provider_id = str(payment.get("provider_payment_id") or payment["id"])
        reason = str(payment.get("reason") or "manual_review")
        b.button(
            text=f"🌍 Ko-fi: {provider_id} — {reason}"[:64],
            callback_data=f"admin_kofi_review:{payment['id']}",
        )

    # Monobank платежи
    if monobank_payments:
        for payment in monobank_payments:
            transaction_id = str(payment.get("transaction_id") or payment["id"])
            reason = str(payment.get("reason") or "manual_review")
            b.button(
                text=f"🇺🇦 Monobank: {transaction_id[:10]} — {reason}"[:64],
                callback_data=f"admin_monobank_review:{payment['id']}",
            )

    b.button(text="🔄 Обновить", callback_data="admin_payment_reviews")
    b.button(text="◀️ К тарифам", callback_data="admin_tariffs")
    b.adjust(1)
    return b.as_markup()


def admin_payment_review_detail_kb(payment_id: int, can_approve: bool, provider: str = "kofi") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if can_approve:
        b.button(text="✅ Засчитать", callback_data=f"admin_{provider}_review_action:{payment_id}:approve")
    b.button(text="❌ Отклонить", callback_data=f"admin_{provider}_review_action:{payment_id}:reject")
    b.button(text="◀️ К проверке оплат", callback_data="admin_payment_reviews")
    b.adjust(1)
    return b.as_markup()


def admin_tariff_detail_kb(tariff: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Название", callback_data=f"admin_tariff_edit:{tariff['id']}:name")
    b.button(text="⭐ Цена", callback_data=f"admin_tariff_edit:{tariff['id']}:stars")
    b.button(text="📅 Дней", callback_data=f"admin_tariff_edit:{tariff['id']}:days")
    toggle = "⭕ Выключить" if tariff["is_active"] else "✅ Включить"
    b.button(text=toggle, callback_data=f"admin_tariff_toggle:{tariff['id']}")
    b.button(text="◀️ К тарифам", callback_data="admin_tariffs")
    b.adjust(1)
    return b.as_markup()


def admin_user_detail_kb(user_tg_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ 14 дней", callback_data=f"admin_user_add:{user_tg_id}:14")
    b.button(text="➕ 30 дней", callback_data=f"admin_user_add:{user_tg_id}:30")
    b.button(text="➕ 100 дней", callback_data=f"admin_user_add:{user_tg_id}:100")
    b.button(text="➕ Своё число", callback_data=f"admin_user_add_custom:{user_tg_id}")
    b.button(text="◀️ Назад", callback_data="admin_users")
    b.adjust(3, 1, 1)
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
