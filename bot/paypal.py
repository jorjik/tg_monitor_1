import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

import aiohttp

from core.config import PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_MODE

logger = logging.getLogger(__name__)

BASE_URLS = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}


def paypal_error_summary(status: int, text: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return f"{status} {text[:200]}"
    parts = [str(status)]
    if data.get("name"):
        parts.append(str(data["name"]))
    if data.get("debug_id"):
        parts.append(f"debug_id={data['debug_id']}")
    details = data.get("details") or []
    if details and isinstance(details, list):
        issue = details[0].get("issue") if isinstance(details[0], dict) else None
        if issue:
            parts.append(f"issue={issue}")
    return " ".join(parts)


def paypal_transport_error_summary(exc: BaseException) -> str:
    message = str(exc).strip()
    suffix = f": {message[:160]}" if message else ""
    return f"transport_error={type(exc).__name__}{suffix}"


class PayPalClient:
    def __init__(self, timeout_seconds: int = 15):
        self.client_id = PAYPAL_CLIENT_ID
        self.secret = PAYPAL_CLIENT_SECRET
        self.mode = PAYPAL_MODE
        self.base_url = BASE_URLS.get(self.mode, BASE_URLS["sandbox"])
        self._access_token: Optional[str] = None
        self._access_token_expires_at = 0.0
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.last_error: Optional[str] = None

    async def _get_access_token(self) -> Optional[str]:
        if self._access_token and time.monotonic() < self._access_token_expires_at:
            return self._access_token
        if not self.client_id or not self.secret:
            self.last_error = "credentials_missing"
            logger.error("PayPal credentials missing")
            return None

        url = f"{self.base_url}/v1/oauth2/token"
        auth = aiohttp.BasicAuth(self.client_id, self.secret)
        data = {"grant_type": "client_credentials"}

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, auth=auth, data=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        self._access_token = result.get("access_token")
                        expires_in = int(result.get("expires_in") or 0)
                        self._access_token_expires_at = (
                            time.monotonic() + max(0, expires_in - 60)
                        )
                        self.last_error = None
                        return self._access_token
                    text = await resp.text()
                    self.last_error = paypal_error_summary(resp.status, text)
                    logger.error(f"Failed to get PayPal token: {self.last_error}")
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            self.last_error = paypal_transport_error_summary(exc)
            logger.error(f"Failed to get PayPal token: {self.last_error}")
            return None

    async def create_order(
        self, amount: str, currency: str, reference_id: str
    ) -> Optional[Dict[str, Any]]:
        self.last_error = None
        token = await self._get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/v2/checkout/orders"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        data = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": reference_id,
                    "amount": {
                        "currency_code": currency,
                        "value": amount,
                    },
                }
            ],
            "application_context": {
                "shipping_preference": "NO_SHIPPING",
                "user_action": "PAY_NOW",
                "landing_page": "BILLING",
            },
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, headers=headers, json=data) as resp:
                    if resp.status == 201:
                        self.last_error = None
                        return await resp.json()
                    text = await resp.text()
                    self.last_error = paypal_error_summary(resp.status, text)
                    logger.error(f"Failed to create PayPal order: {self.last_error}")
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            self.last_error = paypal_transport_error_summary(exc)
            logger.error(f"Failed to create PayPal order: {self.last_error}")
            return None

    async def capture_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        self.last_error = None
        token = await self._get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/v2/checkout/orders/{order_id}/capture"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, headers=headers) as resp:
                    if resp.status in [200, 201]:
                        self.last_error = None
                        return await resp.json()
                    text = await resp.text()
                    self.last_error = paypal_error_summary(resp.status, text)
                    logger.error(f"Failed to capture PayPal order: {self.last_error}")
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            self.last_error = paypal_transport_error_summary(exc)
            logger.error(f"Failed to capture PayPal order: {self.last_error}")
            return None

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        self.last_error = None
        token = await self._get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/v2/checkout/orders/{order_id}"
        headers = {
            "Authorization": f"Bearer {token}",
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        self.last_error = None
                        return await resp.json()
                    text = await resp.text()
                    self.last_error = paypal_error_summary(resp.status, text)
                    logger.error(f"Failed to get PayPal order: {self.last_error}")
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            self.last_error = paypal_transport_error_summary(exc)
            logger.error(f"Failed to get PayPal order: {self.last_error}")
            return None
