from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import aiohttp

from bot.access import user_has_paid_access
from bot.paypal import PayPalClient, paypal_error_summary
from db.repository import Repository


class FakePayPalResponse:
    status = 201

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def json(self):
        return {"id": "ORDER-1"}

    async def text(self):
        return ""


class FakePayPalSession:
    requests = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return FakePayPalResponse()


class FailingPayPalSession:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def post(self, url, **kwargs):
        raise aiohttp.ClientConnectionError("network down")


class PayPalClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_order_uses_paypal_supported_landing_page(self):
        FakePayPalSession.requests = []
        client = PayPalClient()

        async def token():
            return "access-token"

        client._get_access_token = token

        with patch("bot.paypal.aiohttp.ClientSession", FakePayPalSession):
            order = await client.create_order("5.00", "USD", "paypal:123:1")

        self.assertEqual(order, {"id": "ORDER-1"})
        payload = FakePayPalSession.requests[0][1]["json"]
        self.assertEqual(payload["application_context"]["landing_page"], "BILLING")

    async def test_create_order_reports_transport_error_without_raising(self):
        client = PayPalClient()

        async def token():
            return "access-token"

        client._get_access_token = token

        with patch("bot.paypal.aiohttp.ClientSession", FailingPayPalSession):
            order = await client.create_order("5.00", "USD", "paypal:123:1")

        self.assertIsNone(order)
        self.assertIn("transport_error=ClientConnectionError", client.last_error)


class PayPalErrorSummaryTest(unittest.TestCase):
    def test_extracts_debug_id_and_issue_without_raw_payload(self):
        summary = paypal_error_summary(
            400,
            '{"name":"INVALID_REQUEST","debug_id":"debug-1",'
            '"details":[{"issue":"INVALID_PARAMETER_VALUE"}]}',
        )

        self.assertEqual(summary, "400 INVALID_REQUEST debug_id=debug-1 issue=INVALID_PARAMETER_VALUE")


class PayPalRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_completed_paypal_payment_extends_subscription(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            tariff = (await repo.get_tariffs(active_only=True))[0]
            await repo.create_paypal_payment(
                order_id="ORDER-PAID",
                user_tg_id=123,
                tariff_id=tariff["id"],
                amount="5.00",
                currency="USD",
            )

            result = await repo.record_paypal_payment("ORDER-PAID", "COMPLETED")

            self.assertEqual(result["status"], "COMPLETED")
            self.assertIsNotNone(result["expires_at"])
            self.assertTrue(await user_has_paid_access(repo, 123))


if __name__ == "__main__":
    unittest.main()
