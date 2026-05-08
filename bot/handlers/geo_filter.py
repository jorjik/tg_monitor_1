from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.access import require_callback_access, require_message_access
from bot.keyboards import cancel_kb, geo_filter_kb
from bot.states import GeoFilterForm
from db.repository import Repository
from userbot.collector import GEO_EXCLUDE_DEFAULT

router = Router()
MAX_GEO_WORD_BYTES = 55


def _geo_word_error(word: str) -> str | None:
    if not word:
        return "❌ Пустое слово."
    if "," in word:
        return "❌ Слово не должно содержать запятую."
    if len(word.encode("utf-8")) > MAX_GEO_WORD_BYTES:
        return "❌ Слово слишком длинное."
    return None


async def _get_words(repo: Repository, user_tg_id: int) -> list[str]:
    raw = await repo.get_setting("geo_exclude", "", user_tg_id=user_tg_id)
    return sorted({w.strip() for w in raw.split(",") if w.strip()})


async def _show_filter(msg, repo: Repository, user_tg_id: int, edit: bool = False):
    words = await _get_words(repo, user_tg_id)
    if words:
        text = (
            f"🚫 <b>Гео-фильтр</b>\n\n"
            f"При сборе чатов (Проход 1) исключаются чаты, "
            f"у которых в названии есть одно из этих слов.\n\n"
            f"Слов в фильтре: <b>{len(words)}</b>\n"
            f"Нажмите 🗑 на слово чтобы удалить его:"
        )
    else:
        text = (
            f"🚫 <b>Гео-фильтр</b>\n\n"
            f"Сейчас гео-фильтр выключен: при сборе чатов география не исключается.\n\n"
            f"Нажмите <b>🚫 Убрать Гео РФ</b>, чтобы включить текущий набор РФ-маркеров."
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
    if not await require_message_access(message, repo):
        return
    await _show_filter(message, repo, message.from_user.id, edit=False)


@router.callback_query(F.data == "geo_add")
async def cb_geo_add(callback: CallbackQuery, state: FSMContext, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
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
    if not await require_message_access(message, repo):
        await state.clear()
        return
    word = (message.text or "").strip().lower()
    await state.clear()
    error = _geo_word_error(word)
    if error:
        await message.answer(error)
        return

    user_tg_id = message.from_user.id
    words = await _get_words(repo, user_tg_id)
    if word in words:
        await message.answer(f"⚠️ «{word}» уже есть в фильтре.")
    else:
        words.append(word)
        await repo.set_setting("geo_exclude", ",".join(words), user_tg_id=user_tg_id)
        await message.answer(f"✅ «{word}» добавлено в гео-фильтр.")

    await _show_filter(message, repo, user_tg_id, edit=False)


@router.callback_query(F.data.startswith("geo_del:"))
async def cb_geo_del(callback: CallbackQuery, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    word = callback.data.split(":", 1)[1]
    user_tg_id = callback.from_user.id
    words = await _get_words(repo, user_tg_id)
    if word in words:
        words.remove(word)
        await repo.set_setting("geo_exclude", ",".join(words), user_tg_id=user_tg_id)
        await callback.answer(f"🗑 «{word}» удалено")
    else:
        await callback.answer("Слово не найдено")
    await _show_filter(callback.message, repo, user_tg_id, edit=True)


@router.callback_query(F.data == "geo_rf")
async def cb_geo_rf(callback: CallbackQuery, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    await repo.set_setting("geo_exclude", GEO_EXCLUDE_DEFAULT, user_tg_id=user_tg_id)
    await callback.answer("🚫 Гео РФ будет исключаться")
    await _show_filter(callback.message, repo, user_tg_id, edit=True)


@router.callback_query(F.data == "geo_reset")
async def cb_geo_reset(callback: CallbackQuery, repo: Repository):
    if not await require_callback_access(callback, repo):
        return
    user_tg_id = callback.from_user.id
    await repo.set_setting("geo_exclude", "", user_tg_id=user_tg_id)
    await callback.answer("🧹 Гео-фильтр очищен")
    await _show_filter(callback.message, repo, user_tg_id, edit=True)
