import html
from itertools import product

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.access import require_callback_access, require_message_access
from bot.states import KeywordForm
from bot.keyboards import keywords_kb, cancel_kb, keyword_confirm_kb
from db.repository import Repository

router = Router()
MAX_KEYWORD_COMBINATIONS = 100
PREVIEW_KEYWORD_LIMIT = 20


def _normalize_keyword(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _split_options(value: str) -> list[str]:
    options = [_normalize_keyword(part) for part in value.split(",")]
    return [option for option in options if option]


def _expand_keyword_input(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        raise ValueError("Пустое слово.")
    if "{" not in text and "}" not in text:
        keywords = _split_options(text)
        if not keywords:
            raise ValueError("Пустое слово.")
        return list(dict.fromkeys(keywords))

    parts: list[list[str]] = []
    literal: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "{":
            literal_options = _split_options("".join(literal))
            if literal_options:
                parts.append(literal_options)
            literal = []
            end = text.find("}", i + 1)
            if end == -1:
                raise ValueError("Не закрыта фигурная скобка.")
            group_text = text[i + 1:end]
            if "{" in group_text:
                raise ValueError("Вложенные фигурные скобки не поддерживаются.")
            options = _split_options(group_text)
            if not options:
                raise ValueError("Пустое множество в фигурных скобках.")
            parts.append(options)
            i = end + 1
            continue
        if char == "}":
            raise ValueError("Лишняя закрывающая фигурная скобка.")
        literal.append(char)
        i += 1

    literal_options = _split_options("".join(literal))
    if literal_options:
        parts.append(literal_options)
    if not parts:
        raise ValueError("Пустое слово.")

    keywords: list[str] = []
    for combo in product(*parts):
        keyword = _normalize_keyword(" ".join(combo))
        if keyword and keyword not in keywords:
            keywords.append(keyword)
        if len(keywords) > MAX_KEYWORD_COMBINATIONS:
            raise ValueError(f"Слишком много комбинаций. Максимум: {MAX_KEYWORD_COMBINATIONS}.")
    return keywords


def _keywords_preview(keywords: list[str]) -> str:
    lines = [f"• {html.escape(keyword)}" for keyword in keywords[:PREVIEW_KEYWORD_LIMIT]]
    if len(keywords) > PREVIEW_KEYWORD_LIMIT:
        lines.append(f"…и ещё {len(keywords) - PREVIEW_KEYWORD_LIMIT}")
    return "\n".join(lines)


@router.message(F.text == "🔑 Ключевые слова")
@router.message(Command("keywords"))
async def cmd_keywords(message: Message, repo: Repository):
    if not await require_message_access(message, repo):
        return
    user_tg_id = message.from_user.id
    kws = await repo.get_keywords(user_tg_id, topic_id=None)
    active = sum(1 for k in kws if k["is_active"])
    await message.answer(
        f"🔑 <b>Глобальные ключевые слова</b>\n"
        f"Всего: {len(kws)} | Активных: {active}\n\n"
        "Применяются ко всем темам:",
        reply_markup=keywords_kb(kws, topic_id=None), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("kw_topic:"))
async def cb_kw_topic(callback: CallbackQuery, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    topic_id = int(callback.data.split(":")[1])
    kws = await repo.get_keywords(user_tg_id, topic_id=topic_id)
    active = sum(1 for k in kws if k["is_active"])
    await callback.message.edit_text(
        f"🔑 <b>Ключевые слова темы</b>\n"
        f"Всего: {len(kws)} | Активных: {active}",
        reply_markup=keywords_kb(kws, topic_id=topic_id), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_kw:"))
async def cb_toggle_kw(callback: CallbackQuery, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    parts = callback.data.split(":")
    kw_id = int(parts[1])
    scope = parts[2] if len(parts) > 2 else "global"
    user_tg_id = callback.from_user.id
    topic_id = None if scope == "global" else int(scope)
    new_state = await repo.toggle_keyword(user_tg_id, kw_id)
    await callback.answer("✅ Включено" if new_state else "⭕ Выключено")
    kws = await repo.get_keywords(user_tg_id, topic_id=topic_id)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=keywords_kb(kws, topic_id=topic_id)
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("add_kw"))
async def cb_add_kw_start(callback: CallbackQuery, state: FSMContext, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    parts = callback.data.split(":")
    scope = parts[1] if len(parts) > 1 else "global"
    await state.update_data(kw_topic_id=None if scope == "global" else int(scope))
    await state.set_state(KeywordForm.waiting_keyword)
    await callback.message.answer(
        "🔑 Введите ключевое слово или фразу:\n\n"
        "Напр: <code>инвестиции</code> или <code>ищу партнёра</code>\n\n"
        "Можно множества: <code>{надо,заказать}{сайт,чатбот}</code>",
        reply_markup=cancel_kb(), parse_mode="HTML",
    )
    await callback.answer()


@router.message(KeywordForm.waiting_keyword)
async def process_keyword(message: Message, state: FSMContext, repo: Repository):
    if not await require_message_access(message, repo):
        await state.clear()
        return
    user_tg_id = message.from_user.id
    raw = message.text or ""
    try:
        keywords = _expand_keyword_input(raw)
    except ValueError as e:
        await message.answer(f"❌ {e}")
        return
    data = await state.get_data()
    topic_id = data.get("kw_topic_id")
    if len(keywords) > 1 or "{" in raw or "}" in raw or "," in raw:
        await state.update_data(kw_candidates=keywords)
        await state.set_state(KeywordForm.waiting_confirm_keywords)
        await message.answer(
            f"🔎 <b>Будет добавлено ключевых слов:</b> {len(keywords)}\n\n"
            f"{_keywords_preview(keywords)}\n\n"
            "Подтвердить добавление?",
            reply_markup=keyword_confirm_kb(),
            parse_mode="HTML",
        )
        return

    word = keywords[0]
    await state.clear()
    added = await repo.add_keyword(user_tg_id, word, topic_id=topic_id)
    scope = "глобально" if topic_id is None else f"для темы #{topic_id}"
    if added:
        word_safe = html.escape(word)
        await message.answer(
            f"✅ Слово <b>«{word_safe}»</b> добавлено ({scope}).", parse_mode="HTML"
        )
    else:
        await message.answer(
            f"⚠️ Слово «{html.escape(word)}» уже существует.",
            parse_mode="HTML",
        )
    kws = await repo.get_keywords(user_tg_id, topic_id=topic_id)
    active = sum(1 for k in kws if k["is_active"])
    await message.answer(
        f"🔑 Слов: {len(kws)} (активных: {active})",
        reply_markup=keywords_kb(kws, topic_id=topic_id), parse_mode="HTML",
    )


@router.callback_query(KeywordForm.waiting_confirm_keywords, F.data == "kw_confirm:add")
async def cb_confirm_keywords(callback: CallbackQuery, state: FSMContext, repo: Repository):
    if not await require_callback_access(callback, repo):
        await state.clear()
        return
    user_tg_id = callback.from_user.id
    data = await state.get_data()
    topic_id = data.get("kw_topic_id")
    keywords = data.get("kw_candidates", [])
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    added, skipped = await repo.add_keywords(user_tg_id, keywords, topic_id=topic_id)
    await callback.message.answer(
        f"✅ Добавлено: {added}\n"
        f"⚠️ Уже было или не добавлено: {skipped}"
    )
    kws = await repo.get_keywords(user_tg_id, topic_id=topic_id)
    active = sum(1 for k in kws if k["is_active"])
    await callback.message.answer(
        f"🔑 Слов: {len(kws)} (активных: {active})",
        reply_markup=keywords_kb(kws, topic_id=topic_id), parse_mode="HTML",
    )
    await callback.answer("Добавлено")
