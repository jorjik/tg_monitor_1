from pathlib import Path
import tempfile
import unittest

from bot.access import user_has_paid_access
from bot.kofi import (
    extract_kofi_code,
    kofi_amount_for_tariff,
    normalize_amount,
    parse_kofi_webhook_payload,
)
from bot.keyboards import subscription_kb
from db.repository import Repository


class KofiHelpersTest(unittest.TestCase):
    def test_normalizes_amounts_and_tariff_price(self):
        tariff = {"stars": 100}

        self.assertEqual(normalize_amount("5"), "5.00")
        self.assertEqual(normalize_amount("5.125"), "5.13")
        self.assertEqual(kofi_amount_for_tariff(tariff, "0.05"), "5.00")

    def test_parses_form_wrapped_payload_and_extracts_payment_code(self):
        payment = parse_kofi_webhook_payload(
            {
                "data": (
                    '{"verification_token":"secret","message_id":"msg-1",'
                    '"type":"Donation","amount":"5","currency":"usd",'
                    '"message":"Оплата KF-ABC12345 спасибо"}'
                )
            }
        )

        self.assertEqual(payment.provider_payment_id, "msg-1")
        self.assertEqual(payment.amount, "5.00")
        self.assertEqual(payment.currency, "USD")
        self.assertEqual(extract_kofi_code(payment.message), "KF-ABC12345")


class KofiRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_kofi_payment_extends_subscription_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            user_id = 123
            tariff = (await repo.get_tariffs(active_only=True))[0]
            intent = await repo.create_kofi_payment_intent(
                user_tg_id=user_id,
                tariff_id=tariff["id"],
                amount="5.00",
                currency="USD",
                duration_days=tariff["duration_days"],
                code="KF-ABC12345",
            )

            result = await repo.record_kofi_payment(
                provider_payment_id="msg-1",
                code=intent["code"],
                amount="5.00",
                currency="USD",
                raw_payload='{"message_id":"msg-1"}',
            )
            duplicate = await repo.record_kofi_payment(
                provider_payment_id="msg-1",
                code=intent["code"],
                amount="5.00",
                currency="USD",
                raw_payload='{"message_id":"msg-1"}',
            )

            self.assertEqual(result["status"], "paid")
            self.assertTrue(result["inserted"])
            self.assertEqual(duplicate["status"], "paid")
            self.assertFalse(duplicate["inserted"])
            self.assertEqual(result["expires_at"], duplicate["expires_at"])
            self.assertTrue(await user_has_paid_access(repo, user_id))

    async def test_kofi_payment_without_code_goes_to_manual_review(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()

            result = await repo.record_kofi_payment(
                provider_payment_id="msg-2",
                code=None,
                amount="5.00",
                currency="USD",
                raw_payload='{"message_id":"msg-2"}',
            )

            self.assertEqual(result["status"], "manual_review")
            self.assertEqual(result["reason"], "code_missing")

    async def test_kofi_amount_mismatch_goes_to_manual_review(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            tariff = (await repo.get_tariffs(active_only=True))[0]
            intent = await repo.create_kofi_payment_intent(
                user_tg_id=123,
                tariff_id=tariff["id"],
                amount="5.00",
                currency="USD",
                duration_days=tariff["duration_days"],
                code="KF-ABC12345",
            )

            result = await repo.record_kofi_payment(
                provider_payment_id="msg-3",
                code=intent["code"],
                amount="4.00",
                currency="USD",
                raw_payload='{"message_id":"msg-3"}',
            )

            self.assertEqual(result["status"], "manual_review")
            self.assertEqual(result["reason"], "amount_or_currency_mismatch")
            self.assertFalse(await user_has_paid_access(repo, 123))


class KofiKeyboardTest(unittest.TestCase):
    def test_subscription_keyboard_includes_kofi_button(self):
        tariffs = [{"id": 1, "name": "Месяц", "stars": 100, "duration_days": 30, "is_active": 1}]

        buttons = [
            button.text
            for row in subscription_kb(tariffs).inline_keyboard
            for button in row
        ]

        self.assertEqual(
            buttons,
            [
                "🌍 Ko-fi: Месяц — 30 дн.",
                "💳 PayPal: Месяц — 30 дн.",
                "💳 Перевод на карту (UA/USD)",
                "🔙 Назад",
            ],
        )


if __name__ == "__main__":
    unittest.main()
