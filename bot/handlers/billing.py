import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.access import is_admin

from bot.keyboards import (
    admin_payment_methods_kb,
    admin_tariff_detail_kb,
    admin_tariffs_kb,
    kofi_payment_kb,
    main_menu_kb,
    manual_payment_kb,
    paypal_payment_kb,
    subscription_kb,
)
from bot.kofi import kofi_amount_for_tariff
from bot.paypal import PayPalClient
from bot.states import BillingAdminForm
from core.config import (
    KO_FI_AMOUNT_PER_STAR,
    KO_FI_CURRENCY,
    KO_FI_PAGE_URL,
    PAYPAL_AMOUNT_PER_STAR,
    PAYPAL_CURRENCY,
)
from db.repository import Repository

logger = logging.getLogger(__name__)

router = Router()
PAYMENT_METHOD_LABELS = {
    "kofi": "Ko-fi",
    "paypal": "PayPal",
    "manual": "Перевод на карту",
}


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
    try:
        amount = kofi_amount_for_tariff(tariff, KO_FI_AMOUNT_PER_STAR)
        price_text = f"{amount} {KO_FI_CURRENCY}"
    except ValueError:
        price_text = f"{tariff['stars']} Stars (ошибка цены)"

    return (
        f"💎 <b>{html.escape(tariff['name'])}</b>\n\n"
        f"Статус: {active}\n"
        f"Цена: <b>{price_text}</b>\n"
        f"Срок: <b>{tariff['duration_days']}</b> дней"
    )


async def _show_subscription(message: Message, repo: Repository, user_tg_id: int) -> None:
    access = await repo.get_subscription_access(user_tg_id)
    tariffs = await repo.get_tariffs(active_only=True)
    payment_methods = await repo.get_payment_methods()
    if not tariffs:
        await message.answer("Тарифы пока не настроены. Напишите администратору.")
        return
        
    tariff_lines = []
    for t in tariffs:
        try:
            amount = kofi_amount_for_tariff(t, KO_FI_AMOUNT_PER_STAR)
            price_text = f"{amount} {KO_FI_CURRENCY}"
        except ValueError:
            price_text = "ошибка настройки"
        tariff_lines.append(f"• <b>{html.escape(t['name'])}</b>: {price_text} / {t['duration_days']} дн.")

    await message.answer(
        "💳 <b>Подписка</b>\n\n"
        f"{_access_text(access)}\n\n"
        "Доступные тарифы:\n"
        + "\n".join(tariff_lines)
        + (
            ""
            if any(payment_methods.values())
            else "\n\n⚠️ Способы оплаты временно скрыты администратором."
        ),
        reply_markup=subscription_kb(tariffs, payment_methods),
        parse_mode="HTML",
    )


async def _ensure_payment_method_enabled(
    callback: CallbackQuery, repo: Repository, method: str
) -> bool:
    if is_admin(callback.from_user.id):
        return True
    if await repo.is_payment_method_enabled(method):
        return True
    label = PAYMENT_METHOD_LABELS.get(method, method)
    await callback.answer(
        f"{label} сейчас недоступен.",
        show_alert=True,
    )
    return False


async def _send_kofi_payment(callback: CallbackQuery, repo: Repository, tariff: dict) -> None:
    if not KO_FI_PAGE_URL:
        await callback.answer("Ko-fi пока не настроен.", show_alert=True)
        return
    try:
        amount = kofi_amount_for_tariff(tariff, KO_FI_AMOUNT_PER_STAR)
    except ValueError:
        await callback.answer("Ko-fi цена настроена некорректно.", show_alert=True)
        return
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    intent = await repo.create_kofi_payment_intent(
        user_tg_id=callback.from_user.id,
        tariff_id=tariff["id"],
        amount=amount,
        currency=KO_FI_CURRENCY,
        duration_days=tariff["duration_days"],
    )
    if not intent:
        await callback.answer("Тариф недоступен.", show_alert=True)
        return
    await callback.message.answer(
        "🌍 <b>Оплата через Ko-fi</b>\n\n"
        f"Тариф: <b>{html.escape(tariff['name'])}</b>\n"
        f"Сумма: <b>{amount} {html.escape(KO_FI_CURRENCY)}</b>\n"
        f"Срок: <b>{tariff['duration_days']}</b> дней\n"
        "1. Нажмите «Открыть Ko-fi».\n"
        "2. <b>Важно:</b> после перехода жмите внизу кнопку <b>\"tip\"</b>.\n"
        "3. Оплатите сумму выше.\n"
        "4. В сообщение к платежу вставьте ваш код платежа:\n"
        f"<code>{html.escape(intent['code'])}</code>\n\n"
        "После webhook бот активирует подписку автоматически. "
        "Если код не попал в сообщение, напишите администратору.",
        reply_markup=kofi_payment_kb(KO_FI_PAGE_URL),
        parse_mode="HTML",
    )
    await callback.answer()


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


@router.callback_query(F.data.startswith("billing_kofi:"))
async def cb_billing_kofi(callback: CallbackQuery, repo: Repository):
    if not await _ensure_payment_method_enabled(callback, repo, "kofi"):
        return
    tariff_id = int(callback.data.split(":")[1])
    tariff = await repo.get_tariff(tariff_id, active_only=True)
    if not tariff:
        await callback.answer("Тариф недоступен.", show_alert=True)
        return
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    await _send_kofi_payment(callback, repo, tariff)


@router.callback_query(F.data.startswith("billing_paypal:"))
async def cb_billing_paypal(callback: CallbackQuery, repo: Repository):
    if not await _ensure_payment_method_enabled(callback, repo, "paypal"):
        return
    tariff_id = int(callback.data.split(":")[1])
    tariff = await repo.get_tariff(tariff_id, active_only=True)
    if not tariff:
        await callback.answer("Тариф недоступен.", show_alert=True)
        return

    try:
        amount = kofi_amount_for_tariff(tariff, PAYPAL_AMOUNT_PER_STAR)
    except ValueError:
        await callback.answer("Ошибка настройки цены PayPal.", show_alert=True)
        return

    paypal = PayPalClient()
    order = await paypal.create_order(
        amount=amount,
        currency=PAYPAL_CURRENCY,
        reference_id=f"user_{callback.from_user.id}_tariff_{tariff_id}"
    )

    if not order:
        await callback.answer("Не удалось создать заказ PayPal.", show_alert=True)
        return

    order_id = order["id"]
    approval_url = next(
        (link["href"] for link in order.get("links", []) if link.get("rel") == "approve"),
        None,
    )
    if not approval_url:
        await callback.answer("Не удалось получить ссылку PayPal.", show_alert=True)
        return

    await repo.create_paypal_payment(
        order_id=order_id,
        user_tg_id=callback.from_user.id,
        tariff_id=tariff_id,
        amount=amount,
        currency=PAYPAL_CURRENCY
    )

    await callback.message.edit_text(
        f"💳 <b>Оплата через PayPal</b>\n\n"
        f"Тариф: <b>{html.escape(tariff['name'])}</b>\n"
        f"Сумма к оплате: <b>{amount} {PAYPAL_CURRENCY}</b>\n\n"
        "1. Нажмите кнопку ниже для перехода в PayPal.\n"
        "2. После завершения оплаты вернитесь сюда и нажмите <b>Проверить статус</b>.",
        reply_markup=paypal_payment_kb(approval_url, order_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("paypal_check:"))
async def cb_paypal_check(callback: CallbackQuery, repo: Repository):
    order_id = callback.data.split(":")[1]
    paypal = PayPalClient()
    
    # Check current status
    order = await paypal.get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден в PayPal.", show_alert=True)
        return

    status = order["status"]
    
    if status == "APPROVED":
        # Capture the payment
        capture = await paypal.capture_order(order_id)
        if capture and capture.get("status") == "COMPLETED":
            result = await repo.record_paypal_payment(order_id, "COMPLETED")
            if result["status"] == "COMPLETED":
                await callback.message.edit_text(
                    f"✅ Оплата PayPal успешно получена!\n\n"
                    f"Подписка активна до <code>{result['expires_at']}</code>.",
                    reply_markup=main_menu_kb(is_admin=is_admin(callback.from_user.id), has_access=True),
                    parse_mode="HTML"
                )
                return
            else:
                await callback.answer(f"Ошибка сохранения: {result.get('reason')}", show_alert=True)
        else:
            await callback.answer("Не удалось завершить платеж (Capture failed).", show_alert=True)
    elif status == "COMPLETED":
        # Check if already recorded
        result = await repo.record_paypal_payment(order_id, "COMPLETED")
        if result["status"] == "already_paid":
            await callback.answer("Этот платеж уже был обработан.", show_alert=True)
        elif result["status"] == "COMPLETED":
            await callback.message.edit_text(
                f"✅ Оплата PayPal подтверждена!\n\n"
                f"Подписка активна до <code>{result['expires_at']}</code>.",
                reply_markup=main_menu_kb(is_admin=is_admin(callback.from_user.id), has_access=True),
                parse_mode="HTML"
            )
        else:
             await callback.answer("Ошибка обработки статуса COMPLETED.", show_alert=True)
    else:
        await callback.answer(f"Статус платежа: {status}. Оплатите заказ в PayPal или попробуйте позже.", show_alert=True)


@router.callback_query(F.data == "billing_back")
async def cb_billing_back(callback: CallbackQuery, repo: Repository):
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    await callback.answer()
    await _show_subscription(callback.message, repo, callback.from_user.id)


async def _show_admin_tariffs(message: Message, repo: Repository) -> None:
    tariffs = await repo.get_tariffs(active_only=False)
    trial_days = await repo.get_trial_days()
    payment_methods = await repo.get_payment_methods()
    enabled_methods = [
        label for method, label in PAYMENT_METHOD_LABELS.items() if payment_methods.get(method)
    ]
    methods_text = ", ".join(enabled_methods) if enabled_methods else "все скрыты"
    await message.answer(
        f"💎 <b>Тарифы</b>\n\n"
        f"Демо-доступ: <b>{trial_days}</b> дней\n"
        f"Тарифов: <b>{len(tariffs)}</b>\n"
        f"Оплата: <b>{html.escape(methods_text)}</b>",
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


async def _show_admin_payment_methods(message: Message, repo: Repository) -> None:
    payment_methods = await repo.get_payment_methods()
    lines = [
        f"{'✅' if payment_methods[method] else '⭕'} {label}"
        for method, label in PAYMENT_METHOD_LABELS.items()
    ]
    await message.answer(
        "💳 <b>Способы оплаты</b>\n\n"
        "Нажмите способ, чтобы скрыть или показать его пользователям.\n\n"
        + "\n".join(lines),
        reply_markup=admin_payment_methods_kb(payment_methods),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_payment_methods")
async def cb_admin_payment_methods(callback: CallbackQuery, repo: Repository):
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администратора", show_alert=True)
        return
    await callback.answer()
    await _show_admin_payment_methods(callback.message, repo)


@router.callback_query(F.data.startswith("admin_payment_toggle:"))
async def cb_admin_payment_toggle(callback: CallbackQuery, repo: Repository):
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администратора", show_alert=True)
        return
    method = callback.data.split(":", 1)[1]
    payment_methods = await repo.get_payment_methods()
    if method not in payment_methods:
        await callback.answer("Способ оплаты не найден.", show_alert=True)
        return
    await repo.set_payment_method_enabled(method, not payment_methods[method])
    await callback.answer("Обновлено")
    await _show_admin_payment_methods(callback.message, repo)


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


@router.callback_query(F.data == "billing_manual")
async def cb_billing_manual(callback: CallbackQuery, repo: Repository):
    if not await _ensure_payment_method_enabled(callback, repo, "manual"):
        return
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    text = (
        "💳 <b>Прямой перевод на карту</b>\n\n"
        "Вы можете оплатить подписку напрямую. "
        "После оплаты обязательно пришлите <b>скриншот/чек</b> администратору "
        "<a href='https://t.me/potok2023'>@potok2023</a>.\n\n"
        "<b>Реквизиты:</b>\n\n"
        "🇺🇦 MonoBank (UAH): <b>220 грн</b>\n"
        "<code>4441111062731694</code>\n\n"
        "💵 MonoBank (USD): <b>5$</b>\n"
        "<code>4441111088169200</code>\n\n"
        "👤 Получатель: <b>Грибков Е.Г.</b>\n\n"
        "⚠️ <i>Нажмите на номер карты выше, чтобы скопировать его.</i>\n\n"
        "После перевода напишите администратору для активации доступа."
    )
    await callback.message.edit_text(
        text,
        reply_markup=manual_payment_kb(),
        parse_mode="HTML"
    )
    await callback.answer()
