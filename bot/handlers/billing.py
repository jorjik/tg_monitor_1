import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from bot.access import is_admin
from bot.keyboards import admin_tariff_detail_kb, admin_tariffs_kb, main_menu_kb, subscription_kb
from bot.states import BillingAdminForm
from db.repository import Repository

router = Router()


def _payload(user_tg_id: int, tariff: dict) -> str:
    return (
        f"subscription:{user_tg_id}:{tariff['id']}:"
        f"{tariff['stars']}:{tariff['duration_days']}"
    )


def _parse_payload(value: str) -> tuple[int, int, int, int] | None:
    parts = value.split(":", 4)
    if len(parts) != 5 or parts[0] != "subscription":
        return None
    try:
        user_tg_id = int(parts[1])
        tariff_id = int(parts[2])
        stars = int(parts[3])
        duration_days = int(parts[4])
    except ValueError:
        return None
    if stars <= 0 or duration_days <= 0:
        return None
    return user_tg_id, tariff_id, stars, duration_days


def _access_text(access: dict) -> str:
    status = access.get("status")
    expires_at = access.get("expires_at")
    if access.get("is_active"):
        label = "демо" if status == "trial" else "подписка"
        return f"✅ Активен {label} до <code>{expires_at}</code>."
    if expires_at:
        return f"⭕ Доступ закончился <code>{expires_at}</code>."
    return "⭕ Активной подписки пока нет."


def _tariff_text(tariff: dict) -> str:
    active = "активен" if tariff["is_active"] else "выключен"
    return (
        f"💎 <b>{html.escape(tariff['name'])}</b>\n\n"
        f"Статус: {active}\n"
        f"Цена: <b>{tariff['stars']}</b> Stars\n"
        f"Срок: <b>{tariff['duration_days']}</b> дней"
    )


async def _show_subscription(message: Message, repo: Repository, user_tg_id: int) -> None:
    access = await repo.get_subscription_access(user_tg_id)
    tariffs = await repo.get_tariffs(active_only=True)
    if not tariffs:
        await message.answer("Тарифы пока не настроены. Напишите администратору.")
        return
    tariff_lines = [
        f"• <b>{html.escape(t['name'])}</b>: {t['stars']} Stars / {t['duration_days']} дн."
        for t in tariffs
    ]
    await message.answer(
        "💳 <b>Подписка</b>\n\n"
        f"{_access_text(access)}\n\n"
        "Доступные тарифы:\n"
        + "\n".join(tariff_lines),
        reply_markup=subscription_kb(tariffs),
        parse_mode="HTML",
    )


@router.message(F.text == "💳 Подписка")
@router.message(Command("subscription"))
@router.message(Command("billing"))
async def cmd_subscription(message: Message, repo: Repository):
    if not message.from_user:
        return
    await repo.upsert_bot_user(
        tg_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    if not is_admin(message.from_user.id):
        await repo.ensure_trial(message.from_user.id)
    await _show_subscription(message, repo, message.from_user.id)


@router.callback_query(F.data.startswith("billing_pay:"))
async def cb_billing_pay(callback: CallbackQuery, repo: Repository):
    tariff_id = int(callback.data.split(":")[1])
    tariff = await repo.get_tariff(tariff_id, active_only=True)
    if not tariff:
        await callback.answer("Тариф недоступен.", show_alert=True)
        return
    payload = _payload(callback.from_user.id, tariff)
    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"Подписка: {tariff['name']}",
        description=f"Доступ к боту на {tariff['duration_days']} дней",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=tariff["name"], amount=tariff["stars"])],
    )
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery, repo: Repository):
    parsed = _parse_payload(pre_checkout_query.invoice_payload)
    if not parsed:
        await pre_checkout_query.answer(ok=False, error_message="Некорректный платёж.")
        return
    user_tg_id, tariff_id, stars, _duration_days = parsed
    if user_tg_id != pre_checkout_query.from_user.id:
        await pre_checkout_query.answer(ok=False, error_message="Этот счёт создан для другого пользователя.")
        return
    tariff = await repo.get_tariff(tariff_id, active_only=True)
    if not tariff:
        await pre_checkout_query.answer(ok=False, error_message="Тариф больше недоступен.")
        return
    if pre_checkout_query.currency != "XTR" or pre_checkout_query.total_amount != stars:
        await pre_checkout_query.answer(ok=False, error_message="Цена тарифа изменилась. Создайте новый счёт.")
        return
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, repo: Repository):
    if not message.from_user:
        return
    payment = message.successful_payment
    parsed = _parse_payload(payment.invoice_payload)
    if not parsed:
        await message.answer("Платёж получен, но назначение не распознано. Напишите администратору.")
        return
    user_tg_id, tariff_id, stars, duration_days = parsed
    if user_tg_id != message.from_user.id:
        await message.answer("Платёж получен, но пользователь не совпал. Напишите администратору.")
        return
    if payment.currency != "XTR" or payment.total_amount != stars:
        await message.answer("Платёж получен, но сумма не совпала с тарифом. Напишите администратору.")
        return
    expires_at, inserted = await repo.record_payment(
        user_tg_id=user_tg_id,
        tariff_id=tariff_id,
        payload=payment.invoice_payload,
        currency=payment.currency,
        stars=payment.total_amount,
        duration_days=duration_days,
        telegram_payment_charge_id=payment.telegram_payment_charge_id,
        provider_payment_charge_id=payment.provider_payment_charge_id or "",
    )
    if not expires_at:
        await message.answer("Платёж получен, но тариф не найден. Напишите администратору.")
        return
    prefix = "✅ Подписка активирована" if inserted else "✅ Подписка уже была активирована"
    await message.answer(
        f"{prefix} до <code>{expires_at}</code>.",
        reply_markup=main_menu_kb(is_admin=is_admin(user_tg_id), has_access=True),
        parse_mode="HTML",
    )


async def _show_admin_tariffs(message: Message, repo: Repository) -> None:
    tariffs = await repo.get_tariffs(active_only=False)
    trial_days = await repo.get_trial_days()
    await message.answer(
        f"💎 <b>Тарифы</b>\n\n"
        f"Демо-доступ: <b>{trial_days}</b> дней\n"
        f"Тарифов: <b>{len(tariffs)}</b>",
        reply_markup=admin_tariffs_kb(tariffs),
        parse_mode="HTML",
    )


@router.message(F.text == "💎 Тарифы")
@router.message(Command("tariffs"))
@router.message(Command("admin_tariffs"))
async def cmd_admin_tariffs(message: Message, repo: Repository):
    if not message.from_user:
        return
    if not is_admin(message.from_user.id):
        await message.answer("Эта функция доступна только администратору.")
        return
    await _show_admin_tariffs(message, repo)


@router.callback_query(F.data == "admin_tariffs")
async def cb_admin_tariffs(callback: CallbackQuery, repo: Repository):
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администратора", show_alert=True)
        return
    await callback.answer()
    await _show_admin_tariffs(callback.message, repo)


@router.callback_query(F.data.startswith("admin_tariff:"))
async def cb_admin_tariff(callback: CallbackQuery, repo: Repository, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администратора", show_alert=True)
        return
    value = callback.data.split(":", 1)[1]
    if value == "new":
        await state.set_state(BillingAdminForm.waiting_name)
        await state.update_data(tariff_action="create")
        await callback.message.answer("Введите название нового тарифа:")
        await callback.answer()
        return
    tariff = await repo.get_tariff(int(value))
    if not tariff:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.message.answer(
        _tariff_text(tariff),
        reply_markup=admin_tariff_detail_kb(tariff),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_tariff_edit:"))
async def cb_admin_tariff_edit(callback: CallbackQuery, repo: Repository, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администратора", show_alert=True)
        return
    _, tariff_id_raw, field = callback.data.split(":")
    tariff = await repo.get_tariff(int(tariff_id_raw))
    if not tariff:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await state.update_data(tariff_action="edit", tariff_id=tariff["id"], tariff_field=field)
    if field == "name":
        await state.set_state(BillingAdminForm.waiting_name)
        await callback.message.answer("Введите новое название тарифа:")
    elif field == "stars":
        await state.set_state(BillingAdminForm.waiting_stars)
        await callback.message.answer("Введите цену в Stars целым числом:")
    else:
        await state.set_state(BillingAdminForm.waiting_days)
        await callback.message.answer("Введите срок тарифа в днях:")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_tariff_toggle:"))
async def cb_admin_tariff_toggle(callback: CallbackQuery, repo: Repository):
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администратора", show_alert=True)
        return
    tariff_id = int(callback.data.split(":")[1])
    tariff = await repo.get_tariff(tariff_id)
    if not tariff:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await repo.set_tariff_active(tariff_id, not bool(tariff["is_active"]))
    await callback.answer("Обновлено")
    await _show_admin_tariffs(callback.message, repo)


@router.callback_query(F.data == "admin_trial_days")
async def cb_admin_trial_days(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администратора", show_alert=True)
        return
    await state.set_state(BillingAdminForm.waiting_trial_days)
    await callback.message.answer("Введите новый срок демо-доступа в днях:")
    await callback.answer()


@router.message(BillingAdminForm.waiting_name)
async def process_tariff_name(message: Message, state: FSMContext, repo: Repository):
    if not message.from_user:
        await state.clear()
        return
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Только для администратора.")
        return
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Название слишком короткое.")
        return
    data = await state.get_data()
    if data.get("tariff_action") == "create":
        await state.update_data(tariff_name=name)
        await state.set_state(BillingAdminForm.waiting_stars)
        await message.answer("Введите цену в Stars целым числом:")
        return
    await repo.update_tariff(data["tariff_id"], name=name)
    await state.clear()
    await message.answer("✅ Название тарифа обновлено.")
    await _show_admin_tariffs(message, repo)


@router.message(BillingAdminForm.waiting_stars)
async def process_tariff_stars(message: Message, state: FSMContext, repo: Repository):
    if not message.from_user:
        await state.clear()
        return
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Только для администратора.")
        return
    try:
        stars = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите целое число.")
        return
    if stars <= 0:
        await message.answer("Цена должна быть больше нуля.")
        return
    data = await state.get_data()
    if data.get("tariff_action") == "create":
        await state.update_data(tariff_stars=stars)
        await state.set_state(BillingAdminForm.waiting_days)
        await message.answer("Введите срок тарифа в днях:")
        return
    await repo.update_tariff(data["tariff_id"], stars=stars)
    await state.clear()
    await message.answer("✅ Цена тарифа обновлена.")
    await _show_admin_tariffs(message, repo)


@router.message(BillingAdminForm.waiting_days)
async def process_tariff_days(message: Message, state: FSMContext, repo: Repository):
    if not message.from_user:
        await state.clear()
        return
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Только для администратора.")
        return
    try:
        days = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите целое число.")
        return
    if days <= 0:
        await message.answer("Срок должен быть больше нуля.")
        return
    data = await state.get_data()
    if data.get("tariff_action") == "create":
        tariff_name = data.get("tariff_name")
        tariff_stars = data.get("tariff_stars")
        if not tariff_name or not tariff_stars:
            await state.clear()
            await message.answer("Не хватает данных для создания тарифа. Начните заново.")
            await _show_admin_tariffs(message, repo)
            return
        tariff_id = await repo.create_tariff(tariff_name, tariff_stars, days)
        await state.clear()
        await message.answer(f"✅ Тариф создан: #{tariff_id}.")
        await _show_admin_tariffs(message, repo)
        return
    await repo.update_tariff(data["tariff_id"], duration_days=days)
    await state.clear()
    await message.answer("✅ Срок тарифа обновлён.")
    await _show_admin_tariffs(message, repo)


@router.message(BillingAdminForm.waiting_trial_days)
async def process_trial_days(message: Message, state: FSMContext, repo: Repository):
    if not message.from_user:
        await state.clear()
        return
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Только для администратора.")
        return
    try:
        days = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите целое число.")
        return
    if days < 0:
        await message.answer("Срок не может быть отрицательным.")
        return
    await repo.set_trial_days(days)
    await state.clear()
    await message.answer(f"✅ Демо-доступ для новых пользователей: {days} дней.")
    await _show_admin_tariffs(message, repo)
