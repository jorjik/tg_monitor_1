import unittest
from unittest.mock import patch

from bot.paypal import PayPalClient


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

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return FakePayPalResponse()


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


if __name__ == "__main__":
    unittest.main()
