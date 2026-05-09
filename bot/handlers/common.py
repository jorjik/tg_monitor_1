from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.access import is_admin
from bot.keyboards import main_menu_kb
from db.repository import Repository

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
/subscription — подписка и оплата
/subscribe — включить уведомления
/unsubscribe — выключить уведомления
"""


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, repo: Repository, bot):
    await state.clear()
    if not message.from_user:
        return
    user_tg_id = message.from_user.id
    
    # Check for referral code
    referred_by = None
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref_id = int(args[1].replace("ref_", ""))
            if ref_id != user_tg_id: # Cannot refer self
                referred_by = ref_id
        except ValueError:
            pass

    is_new = await repo.upsert_bot_user(
        tg_id=user_tg_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        referred_by=referred_by
    )

    # Grant bonus if new user invited by someone
    bonus_applied = False
    if is_new and referred_by:
        bonus_applied = await repo.apply_referral_bonus(user_tg_id, referred_by, days=14)
        if bonus_applied:
            # Notify referrer
            try:
                await bot.send_message(
                    referred_by,
                    f"🎉 По вашей ссылке присоединился новый пользователь!\n"
                    f"Вам и ему начислено по <b>14 дней</b> подписки бонус!",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    admin = is_admin(user_tg_id)
    access = {"is_active": True, "status": "admin", "expires_at": None}
    if not admin:
        access = await repo.ensure_trial(user_tg_id)
    
    if admin:
        access_text = "Админ-доступ активен."
    elif access["is_active"]:
        access_text = f"Доступ активен до <code>{access['expires_at']}</code>."
        if bonus_applied:
            access_text += "\n🎁 Вам начислено 14 дней за переход по реферальной ссылке!"
    else:
        access_text = "Демо-доступ закончился. Откройте <b>💳 Подписка</b> для оплаты."

    await message.answer(
        "👋 <b>Добро пожаловать в Telegram Monitor!</b>\n\n"
        f"{access_text}\n\n"
        "Выберите действие:",
        reply_markup=main_menu_kb(is_admin=admin, has_access=bool(access["is_active"])),
        parse_mode="HTML",
    )


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, repo: Repository):
    if message.from_user:
        await repo.upsert_bot_user(
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
    await message.answer("✅ Уведомления включены.")


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message, repo: Repository):
    if message.from_user:
        await repo.deactivate_bot_user(message.from_user.id)
    await message.answer("⭕ Уведомления выключены. Чтобы включить снова, отправьте /subscribe.")


@router.message(F.text == "🤝 Партнерка")
@router.message(Command("partner"))
@router.message(Command("referral"))
async def cmd_referral(message: Message, repo: Repository, bot):
    user_tg_id = message.from_user.id
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_tg_id}"
    
    stats = await repo.get_referral_stats(user_tg_id)
    
    text = (
        "🤝 <b>Партнерская программа</b>\n\n"
        "Приглашайте друзей и получайте бонусы! 🎁\n\n"
        "<b>Условия:</b>\n"
        "— Вы получаете <b>14 дней</b> подписки за каждого приглашенного.\n"
        "— Ваш друг также получает <b>14 дней</b> доступа сразу после входа.\n\n"
        f"👥 Приглашено друзей: <b>{stats['count']}</b>\n\n"
        f"🔗 <b>Ваша ссылка:</b>\n<code>{ref_link}</code>\n\n"
        "<i>Просто отправьте эту ссылку другу!</i>"
    )
    
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "referral")
async def cb_referral(callback: CallbackQuery, repo: Repository, bot):
    await cmd_referral(callback.message, repo, bot)
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext, repo: Repository):
    await state.clear()
    user_tg_id = callback.from_user.id
    admin = is_admin(user_tg_id)
    access = {"is_active": True} if admin else await repo.get_subscription_access(user_tg_id)
    await callback.message.answer(
        "Главное меню:",
        reply_markup=main_menu_kb(is_admin=admin, has_access=bool(access["is_active"])),
    )
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Действие отменено.")
    await callback.answer()
