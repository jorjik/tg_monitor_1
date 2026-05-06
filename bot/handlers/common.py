from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.keyboards import main_menu_kb

router = Router()

HELP_TEXT = """
<b>🤖 Telegram Monitor Bot</b>

<b>Как работает:</b>
1️⃣ <b>Проход 1 — Сбор чатов:</b> Создайте тему (напр. «бизнес») и задайте поисковые слова. Бот найдёт публичные чаты по этой теме.

2️⃣ <b>Проход 2 — Мониторинг:</b> Добавьте ключевые слова. Запустите мониторинг — бот отслеживает новые сообщения в реальном времени.

3️⃣ <b>Лента:</b> Все совпадения сохраняются. Уведомления мгновенно.

/start — главное меню
/feed — лента
/monitor — мониторинг
"""


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>Добро пожаловать в Telegram Monitor!</b>\n\nВыберите действие:",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Действие отменено.")
    await callback.answer()
