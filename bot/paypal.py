import logging
import aiohttp
from typing import Optional, Dict, Any
from core.config import PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_MODE

logger = logging.getLogger(__name__)

BASE_URLS = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com"
}

class PayPalClient:
    def __init__(self):
        self.client_id = PAYPAL_CLIENT_ID
        self.secret = PAYPAL_CLIENT_SECRET
        self.mode = PAYPAL_MODE
        self.base_url = BASE_URLS.get(self.mode, BASE_URLS["sandbox"])
        self._access_token: Optional[str] = None

    async def _get_access_token(self) -> Optional[str]:
        if not self.client_id or not self.secret:
            logger.error("PayPal credentials missing")
            return None

        url = f"{self.base_url}/v1/oauth2/token"
        auth = aiohttp.BasicAuth(self.client_id, self.secret)
        data = {"grant_type": "client_credentials"}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, auth=auth, data=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    self._access_token = result.get("access_token")
                    return self._access_token
                else:
                    text = await resp.text()
                    logger.error(f"Failed to get PayPal token: {resp.status} {text}")
                    return None

    async def create_order(self, amount: str, currency: str, reference_id: str) -> Optional[Dict[str, Any]]:
        token = await self._get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/v2/checkout/orders"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        data = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": reference_id,
                "amount": {
                    "currency_code": currency,
                    "value": amount
                }
            }],
            "application_context": {
                "shipping_preference": "NO_SHIPPING",
                "user_action": "PAY_NOW",
                "landing_page": "GUEST_CHECKOUT"
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                if resp.status == 201:
                    return await resp.json()
                else:
                    text = await resp.text()
                    logger.error(f"Failed to create PayPal order: {resp.status} {text}")
                    return None

    async def capture_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        token = await self._get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/v2/checkout/orders/{order_id}/capture"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as resp:
                if resp.status in [200, 201]:
                    return await resp.json()
                else:
                    text = await resp.text()
                    logger.error(f"Failed to capture PayPal order: {resp.status} {text}")
                    return None

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        token = await self._get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/v2/checkout/orders/{order_id}"
        headers = {
            "Authorization": f"Bearer {token}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    text = await resp.text()
                    logger.error(f"Failed to get PayPal order: {resp.status} {text}")
                    return None
