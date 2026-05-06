from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import cancel_kb, geo_filter_kb
from bot.states import GeoFilterForm
from db.repository import Repository
from userbot.collector import GEO_EXCLUDE_DEFAULT

router = Router()


async def _get_words(repo: Repository) -> list[str]:
    raw = await repo.get_setting("geo_exclude", GEO_EXCLUDE_DEFAULT)
    return sorted({w.strip() for w in raw.split(",") if w.strip()})


async def _show_filter(msg, repo: Repository, edit: bool = False):
    words = await _get_words(repo)
    text = (
        f"🚫 <b>Гео-фильтр</b>\n\n"
        f"При сборе чатов (Проход 1) исключаются чаты, "
        f"у которых в названии есть одно из этих слов.\n\n"
        f"Слов в фильтре: <b>{len(words)}</b>\n"
        f"Нажмите 🗑 на слово чтобы удалить его:"
    )
    kb = geo_filter_kb(words)
    if edit:
        try:
            await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(F.text == "🚫 Гео-фильтр")
@router.message(Command("geo_filter"))
async def cmd_geo_filter(message: Message, repo: Repository):
    await _show_filter(message, repo, edit=False)


@router.callback_query(F.data == "geo_add")
async def cb_geo_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GeoFilterForm.waiting_add_word)
    await callback.message.answer(
        "➕ Введите слово или фразу для добавления в фильтр.\n\n"
        "Например: <code>беларусь</code> или <code>bel</code>",
        reply_markup=cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(GeoFilterForm.waiting_add_word)
async def process_geo_add(message: Message, state: FSMContext, repo: Repository):
    word = (message.text or "").strip().lower()
    await state.clear()
    if not word:
        await message.answer("❌ Пустое слово.")
        return

    words = await _get_words(repo)
    if word in words:
        await message.answer(f"⚠️ «{word}» уже есть в фильтре.")
    else:
        words.append(word)
        await repo.set_setting("geo_exclude", ",".join(words))
        await message.answer(f"✅ «{word}» добавлено в гео-фильтр.")

    await _show_filter(message, repo, edit=False)


@router.callback_query(F.data.startswith("geo_del:"))
async def cb_geo_del(callback: CallbackQuery, repo: Repository):
    word = callback.data.split(":", 1)[1]
    words = await _get_words(repo)
    if word in words:
        words.remove(word)
        await repo.set_setting("geo_exclude", ",".join(words))
        await callback.answer(f"🗑 «{word}» удалено")
    else:
        await callback.answer("Слово не найдено")
    await _show_filter(callback.message, repo, edit=True)


@router.callback_query(F.data == "geo_reset")
async def cb_geo_reset(callback: CallbackQuery, repo: Repository):
    await repo.set_setting("geo_exclude", GEO_EXCLUDE_DEFAULT)
    await callback.answer("🔄 Сброшено к умолчаниям")
    await _show_filter(callback.message, repo, edit=True)
