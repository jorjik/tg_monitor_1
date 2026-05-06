from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.states import KeywordForm
from bot.keyboards import keywords_kb, cancel_kb
from db.repository import Repository

router = Router()


@router.message(F.text == "🔑 Ключевые слова")
@router.message(Command("keywords"))
async def cmd_keywords(message: Message, repo: Repository):
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
async def cb_add_kw_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    scope = parts[1] if len(parts) > 1 else "global"
    await state.update_data(kw_topic_id=None if scope == "global" else int(scope))
    await state.set_state(KeywordForm.waiting_keyword)
    await callback.message.answer(
        "🔑 Введите ключевое слово или фразу:\n\n"
        "Напр: <code>инвестиции</code> или <code>ищу партнёра</code>",
        reply_markup=cancel_kb(), parse_mode="HTML",
    )
    await callback.answer()


@router.message(KeywordForm.waiting_keyword)
async def process_keyword(message: Message, state: FSMContext, repo: Repository):
    user_tg_id = message.from_user.id
    word = message.text.strip().lower()
    if not word:
        await message.answer("❌ Пустое слово.")
        return
    data = await state.get_data()
    topic_id = data.get("kw_topic_id")
    await state.clear()
    added = await repo.add_keyword(user_tg_id, word, topic_id=topic_id)
    scope = "глобально" if topic_id is None else f"для темы #{topic_id}"
    if added:
        await message.answer(
            f"✅ Слово <b>«{word}»</b> добавлено ({scope}).", parse_mode="HTML"
        )
    else:
        await message.answer(f"⚠️ Слово «{word}» уже существует.")
    kws = await repo.get_keywords(user_tg_id, topic_id=topic_id)
    active = sum(1 for k in kws if k["is_active"])
    await message.answer(
        f"🔑 Слов: {len(kws)} (активных: {active})",
        reply_markup=keywords_kb(kws, topic_id=topic_id), parse_mode="HTML",
    )
