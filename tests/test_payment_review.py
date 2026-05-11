from pathlib import Path
import tempfile
import unittest

import aiosqlite

from bot.keyboards import admin_payment_reviews_kb, admin_tariffs_kb
from db.repository import Repository


class PaymentReviewRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_admin_can_approve_matched_kofi_manual_review_payment(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            await repo.upsert_bot_user(123, "buyer", "Buyer", None)
            tariff = (await repo.get_tariffs(active_only=True))[0]
            intent = await repo.create_kofi_payment_intent(
                user_tg_id=123,
                tariff_id=tariff["id"],
                amount="5.00",
                currency="USD",
                duration_days=tariff["duration_days"],
                code="KF-REVIEW123",
            )
            result = await repo.record_kofi_payment(
                provider_payment_id="msg-review",
                code=intent["code"],
                amount="4.00",
                currency="USD",
                raw_payload='{"message_id":"msg-review"}',
            )

            reviews = await repo.list_kofi_manual_review_payments()
            approved = await repo.resolve_kofi_manual_review_payment(reviews[0]["id"], "approve")

            self.assertEqual(result["status"], "manual_review")
            self.assertEqual(approved["status"], "approved")
            self.assertTrue((await repo.get_subscription_access(123))["is_active"])

    async def test_admin_can_reject_unmatched_kofi_manual_review_payment(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            await repo.record_kofi_payment(
                provider_payment_id="msg-missing-code",
                code=None,
                amount="5.00",
                currency="USD",
                raw_payload='{"message_id":"msg-missing-code"}',
            )
            reviews = await repo.list_kofi_manual_review_payments()

            rejected = await repo.resolve_kofi_manual_review_payment(reviews[0]["id"], "reject")

            self.assertEqual(rejected["status"], "rejected")
            self.assertEqual(await repo.list_kofi_manual_review_payments(), [])

    async def test_manual_approval_does_not_overwrite_already_paid_intent(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "db.sqlite"
            repo = Repository(str(db_path))
            await repo.init_db()
            await repo.upsert_bot_user(123, "buyer", "Buyer", None)
            tariff = (await repo.get_tariffs(active_only=True))[0]
            intent = await repo.create_kofi_payment_intent(
                user_tg_id=123,
                tariff_id=tariff["id"],
                amount="5.00",
                currency="USD",
                duration_days=tariff["duration_days"],
                code="KF-PAID123",
            )
            await repo.record_kofi_payment(
                provider_payment_id="msg-paid",
                code=intent["code"],
                amount="5.00",
                currency="USD",
                raw_payload='{"message_id":"msg-paid"}',
            )
            await repo.record_kofi_payment(
                provider_payment_id="msg-late",
                code=intent["code"],
                amount="5.00",
                currency="USD",
                raw_payload='{"message_id":"msg-late"}',
            )
            late_payment = [
                payment
                for payment in await repo.list_kofi_manual_review_payments()
                if payment["provider_payment_id"] == "msg-late"
            ][0]

            await repo.resolve_kofi_manual_review_payment(late_payment["id"], "approve")

            async with aiosqlite.connect(db_path) as db:
                cur = await db.execute(
                    "SELECT status, provider_payment_id FROM payment_intents WHERE id = ?",
                    (intent["id"],),
                )
                row = await cur.fetchone()
            self.assertEqual(row, ("paid", "msg-paid"))


class PaymentReviewKeyboardTest(unittest.TestCase):
    def test_admin_tariffs_link_to_payment_review(self):
        buttons = [
            button.text
            for row in admin_tariffs_kb([]).inline_keyboard
            for button in row
        ]

        self.assertIn("⚠️ Проверка оплат", buttons)

    def test_payment_review_keyboard_contains_review_actions(self):
        rows = admin_payment_reviews_kb(
            [{"id": 1, "provider_payment_id": "msg-1", "reason": "code_missing"}]
        ).inline_keyboard
        buttons = [button.text for row in rows for button in row]

        self.assertIn("⚠️ msg-1 — code_missing", buttons)


if __name__ == "__main__":
    unittest.main()
