from pathlib import Path
import tempfile
import unittest

from bot import payment_webhooks
from db.repository import Repository


class MonobankWebhookPathTest(unittest.TestCase):
    def test_path_is_none_without_secret(self):
        original = payment_webhooks.MONOBANK_WEBHOOK_SECRET
        payment_webhooks.MONOBANK_WEBHOOK_SECRET = ""
        try:
            self.assertIsNone(payment_webhooks.build_monobank_webhook_path())
        finally:
            payment_webhooks.MONOBANK_WEBHOOK_SECRET = original

    def test_path_includes_secret_and_normalizes_missing_slash(self):
        original_secret = payment_webhooks.MONOBANK_WEBHOOK_SECRET
        original_path = payment_webhooks.MONOBANK_WEBHOOK_PATH
        payment_webhooks.MONOBANK_WEBHOOK_SECRET = "s3cr3t"
        payment_webhooks.MONOBANK_WEBHOOK_PATH = "webhooks/monobank/"
        try:
            self.assertEqual(
                payment_webhooks.build_monobank_webhook_path(),
                "/webhooks/monobank/s3cr3t",
            )
        finally:
            payment_webhooks.MONOBANK_WEBHOOK_SECRET = original_secret
            payment_webhooks.MONOBANK_WEBHOOK_PATH = original_path


class MonobankRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def _make_repo(self, td: str) -> Repository:
        repo = Repository(str(Path(td) / "db.sqlite"))
        await repo.init_db()
        return repo

    async def test_valid_webhook_credits_subscription_once(self):
        with tempfile.TemporaryDirectory() as td:
            repo = await self._make_repo(td)
            await repo.upsert_bot_user(123, "buyer", "Buyer", None)
            tariff = (await repo.get_tariffs(active_only=True))[0]
            intent = await repo.create_monobank_payment_intent(
                user_tg_id=123,
                tariff_id=tariff["id"],
                amount=1000,
                currency_code=980,
                duration_days=tariff["duration_days"],
            )

            result = await repo.record_monobank_webhook(
                transaction_id="tx-1",
                amount=1000,
                currency_code=980,
                description=f"Перевод {intent['code']}",
                raw_payload={"id": "tx-1"},
            )
            duplicate = await repo.record_monobank_webhook(
                transaction_id="tx-1",
                amount=1000,
                currency_code=980,
                description=f"Перевод {intent['code']}",
                raw_payload={"id": "tx-1"},
            )

            self.assertEqual(result["status"], "paid")
            self.assertEqual(duplicate["status"], "already_processed")
            self.assertTrue((await repo.get_subscription_access(123))["is_active"])

    async def test_currency_mismatch_goes_to_manual_review(self):
        with tempfile.TemporaryDirectory() as td:
            repo = await self._make_repo(td)
            await repo.upsert_bot_user(123, "buyer", "Buyer", None)
            tariff = (await repo.get_tariffs(active_only=True))[0]
            intent = await repo.create_monobank_payment_intent(
                user_tg_id=123,
                tariff_id=tariff["id"],
                amount=1000,
                currency_code=980,
                duration_days=tariff["duration_days"],
            )

            result = await repo.record_monobank_webhook(
                transaction_id="tx-2",
                amount=1000,
                currency_code=840,
                description=f"Перевод {intent['code']}",
                raw_payload={"id": "tx-2"},
            )

            self.assertEqual(result["status"], "manual_review")
            self.assertEqual(result["reason"], "amount_or_currency_mismatch")
            self.assertFalse((await repo.get_subscription_access(123))["is_active"])

    async def test_amount_mismatch_goes_to_manual_review(self):
        with tempfile.TemporaryDirectory() as td:
            repo = await self._make_repo(td)
            await repo.upsert_bot_user(123, "buyer", "Buyer", None)
            tariff = (await repo.get_tariffs(active_only=True))[0]
            intent = await repo.create_monobank_payment_intent(
                user_tg_id=123,
                tariff_id=tariff["id"],
                amount=1000,
                currency_code=980,
                duration_days=tariff["duration_days"],
            )

            result = await repo.record_monobank_webhook(
                transaction_id="tx-3",
                amount=999,
                currency_code=980,
                description=f"Перевод {intent['code']}",
                raw_payload={"id": "tx-3"},
            )

            self.assertEqual(result["status"], "manual_review")
            self.assertEqual(result["reason"], "amount_or_currency_mismatch")

    async def test_intent_for_inactive_tariff_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = await self._make_repo(td)
            tariff = (await repo.get_tariffs(active_only=True))[0]
            await repo.set_tariff_active(tariff["id"], False)

            intent = await repo.create_monobank_payment_intent(
                user_tg_id=123,
                tariff_id=tariff["id"],
                amount=1000,
                currency_code=980,
                duration_days=30,
            )

            self.assertIsNone(intent)


if __name__ == "__main__":
    unittest.main()
