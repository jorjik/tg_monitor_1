import asyncio
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from aiogram.types import Chat, Message

from bot.access import user_has_paid_access
from bot.keyboards import (
    admin_payment_methods_kb,
    admin_tariffs_kb,
    main_menu_kb,
    subscription_kb,
)
from db import repository as repository_module
from db.repository import Repository


class BillingRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_seeds_default_tariff_and_trial_days(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()

            tariffs = await repo.get_tariffs(active_only=True)

            self.assertEqual(await repo.get_trial_days(), 7)
            self.assertEqual(len(tariffs), 1)
            self.assertEqual(tariffs[0]["stars"], 100)
            self.assertEqual(tariffs[0]["duration_days"], 30)

    async def test_trial_is_created_once_and_payment_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            user_id = 123
            trial = await repo.ensure_trial(user_id)
            trial_again = await repo.ensure_trial(user_id)
            tariff = (await repo.get_tariffs(active_only=True))[0]

            expires_at, inserted = await repo.record_payment(
                user_tg_id=user_id,
                tariff_id=tariff["id"],
                payload=f"subscription:{user_id}:{tariff['id']}:{tariff['stars']}:{tariff['duration_days']}",
                currency="XTR",
                stars=tariff["stars"],
                duration_days=tariff["duration_days"],
                telegram_payment_charge_id="charge-1",
            )
            duplicate_expires_at, duplicate_inserted = await repo.record_payment(
                user_tg_id=user_id,
                tariff_id=tariff["id"],
                payload=f"subscription:{user_id}:{tariff['id']}:{tariff['stars']}:{tariff['duration_days']}",
                currency="XTR",
                stars=tariff["stars"],
                duration_days=tariff["duration_days"],
                telegram_payment_charge_id="charge-1",
            )

            self.assertEqual(trial["expires_at"], trial_again["expires_at"])
            self.assertTrue(inserted)
            self.assertFalse(duplicate_inserted)
            self.assertEqual(expires_at, duplicate_expires_at)
            self.assertGreater(expires_at, trial["expires_at"])

    async def test_payment_uses_invoice_duration_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            user_id = 123
            trial = await repo.ensure_trial(user_id)
            tariff = (await repo.get_tariffs(active_only=True))[0]
            await repo.update_tariff(tariff["id"], stars=200, duration_days=1)

            expires_at, inserted = await repo.record_payment(
                user_tg_id=user_id,
                tariff_id=tariff["id"],
                payload=f"subscription:{user_id}:{tariff['id']}:{tariff['stars']}:{tariff['duration_days']}",
                currency="XTR",
                stars=tariff["stars"],
                duration_days=tariff["duration_days"],
                telegram_payment_charge_id="charge-snapshot",
            )

            self.assertTrue(inserted)
            fmt = "%Y-%m-%d %H:%M:%S"
            delta = datetime.strptime(expires_at, fmt) - datetime.strptime(trial["expires_at"], fmt)
            self.assertGreaterEqual(delta.days, 29)

    async def test_trial_creation_is_idempotent_for_parallel_requests(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()

            first, second = await asyncio.gather(repo.ensure_trial(123), repo.ensure_trial(123))

            self.assertEqual(first["expires_at"], second["expires_at"])
            self.assertTrue(first["is_active"])

    async def test_tariff_values_must_be_positive(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            tariff = (await repo.get_tariffs(active_only=True))[0]

            with self.assertRaises(ValueError):
                await repo.create_tariff("Bad", 0, 30)
            with self.assertRaises(ValueError):
                await repo.update_tariff(tariff["id"], duration_days=0)

    async def test_trial_access_is_not_paid_access(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            user_id = 123

            await repo.ensure_trial(user_id)

            self.assertFalse(await user_has_paid_access(repo, user_id))

    async def test_payment_grants_paid_access(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            user_id = 123
            tariff = (await repo.get_tariffs(active_only=True))[0]

            await repo.record_payment(
                user_tg_id=user_id,
                tariff_id=tariff["id"],
                payload=f"subscription:{user_id}:{tariff['id']}:{tariff['stars']}:{tariff['duration_days']}",
                currency="XTR",
                stars=tariff["stars"],
                duration_days=tariff["duration_days"],
                telegram_payment_charge_id="charge-paid-access",
            )

            self.assertTrue(await user_has_paid_access(repo, user_id))

    async def test_monitor_keywords_only_include_users_with_access_or_admin(self):
        previous_admin = repository_module.ADMIN_USER_ID
        repository_module.ADMIN_USER_ID = 999
        try:
            with tempfile.TemporaryDirectory() as td:
                repo = Repository(str(Path(td) / "db.sqlite"))
                await repo.init_db()
                active_user = 123
                inactive_user = 124
                admin_user = 999
                for user_id in (active_user, inactive_user, admin_user):
                    await repo.upsert_bot_user(user_id, None, None, None)
                    topic_id = await repo.create_topic(user_id, f"topic-{user_id}", "term")
                    await repo.save_chat(topic_id, 777, None, "Chat", "supergroup", 1)
                    await repo.add_keyword(user_id, f"term-{user_id}", topic_id=topic_id)
                await repo.ensure_trial(active_user)

                keywords_by_user = await repo.get_monitor_keywords_by_user(777)

                self.assertIn(active_user, keywords_by_user)
                self.assertNotIn(inactive_user, keywords_by_user)
                self.assertIn(admin_user, keywords_by_user)
        finally:
            repository_module.ADMIN_USER_ID = previous_admin

    async def test_payment_methods_are_enabled_by_default_and_can_be_toggled(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()

            self.assertEqual(
                await repo.get_payment_methods(),
                {"monobank": True, "kofi": True, "paypal": True},
            )

            await repo.set_payment_method_enabled("paypal", False)

            self.assertEqual(
                await repo.get_payment_methods(),
                {"monobank": True, "kofi": True, "paypal": False},
            )


class BillingKeyboardTest(unittest.TestCase):
    def test_locked_main_menu_only_shows_subscription_and_help(self):
        rows = [[button.text for button in row] for row in main_menu_kb(has_access=False).keyboard]

        self.assertEqual(rows, [["💳 Подписка"], ["🤝 Партнерка"], ["❓ Помощь"]])

    def test_accessible_main_menu_shows_history_for_regular_user(self):
        buttons = [button.text for row in main_menu_kb(is_admin=False, has_access=True).keyboard for button in row]

        self.assertIn("🕘 История", buttons)

    def test_subscription_and_admin_tariff_keyboards(self):
        tariffs = [{"id": 1, "name": "Месяц", "stars": 100, "duration_days": 30, "is_active": 1}]

        subscription_buttons = [
            button.text
            for row in subscription_kb(
                tariffs,
                {"monobank": True, "kofi": True, "paypal": True},
            ).inline_keyboard
            for button in row
        ]
        admin_buttons = [
            button.text for row in admin_tariffs_kb(tariffs).inline_keyboard for button in row
        ]

        self.assertEqual(
            subscription_buttons,
            [
                "🌍 Ko-fi — 30 дн.",
                "💳 PayPal — 30 дн.",
                "🇺🇦 Monobank — 30 дн.",
                "🔙 Назад",
            ],
        )
        self.assertIn("✅ 100⭐ / 30 дн.", admin_buttons)
        self.assertIn("➕ Новый тариф", admin_buttons)
        self.assertIn("💳 Способы оплаты", admin_buttons)

    def test_subscription_keyboard_hides_disabled_payment_methods(self):
        tariffs = [{"id": 1, "name": "Месяц", "stars": 100, "duration_days": 30, "is_active": 1}]

        buttons = [
            button.text
            for row in subscription_kb(
                tariffs,
                {"monobank": False, "kofi": False, "paypal": True},
            ).inline_keyboard
            for button in row
        ]

        self.assertEqual(buttons, ["💳 PayPal — 30 дн.", "🔙 Назад"])

    def test_admin_payment_methods_keyboard_toggles_each_method(self):
        buttons = [
            (button.text, button.callback_data)
            for row in admin_payment_methods_kb(
                {"monobank": False, "kofi": True, "paypal": False}
            ).inline_keyboard
            for button in row
        ]

        self.assertEqual(
            buttons,
            [
                ("⭕ Monobank", "admin_payment_toggle:monobank"),
                ("✅ Ko-fi", "admin_payment_toggle:kofi"),
                ("⭕ PayPal", "admin_payment_toggle:paypal"),
                ("◀️ К тарифам", "admin_tariffs"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
