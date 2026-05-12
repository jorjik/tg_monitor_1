import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://api.monobank.ua"


def monobank_error_summary(status: int, text: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return f"{status} {text[:200]}"
    parts = [str(status)]
    if data.get("errorDescription"):
        parts.append(str(data["errorDescription"]))
    return " ".join(parts)


def monobank_transport_error_summary(exc: BaseException) -> str:
    message = str(exc).strip()
    suffix = f": {message[:160]}" if message else ""
    return f"transport_error={type(exc).__name__}{suffix}"


class MonobankClient:
    """
    Клиент для работы с Monobank Personal API.

    Документация: https://monobank.ua/api-docs/monobank

    Для получения токена:
    1. Перейдите на https://api.monobank.ua/
    2. Авторизуйтесь через Monobank
    3. Получите персональный токен

    Ограничения API:
    - Не более 1 запроса в 60 секунд для персонального токена
    - Выписка доступна за последние 31 день + 1 час
    """

    def __init__(self, token: str, timeout_seconds: int = 15):
        self.token = token
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.last_error: Optional[str] = None
        self._last_request_time = 0.0
        self._min_request_interval = 60.0  # Monobank API limit: 1 request per 60 seconds

    async def _wait_for_rate_limit(self) -> None:
        """Ожидание перед запросом для соблюдения rate limit."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_request_interval:
            wait_time = self._min_request_interval - elapsed
            logger.info(f"Monobank rate limit: waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
        self._last_request_time = time.monotonic()

    async def get_client_info(self) -> Optional[Dict[str, Any]]:
        """
        Получить информацию о клиенте и его счетах.

        Returns:
            Dict с информацией о клиенте и списком счетов (accounts)
        """
        self.last_error = None
        if not self.token:
            self.last_error = "token_missing"
            logger.error("Monobank token missing")
            return None

        await self._wait_for_rate_limit()

        url = f"{BASE_URL}/personal/client-info"
        headers = {"X-Token": self.token}

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        self.last_error = None
                        return await resp.json()
                    text = await resp.text()
                    self.last_error = monobank_error_summary(resp.status, text)
                    logger.error(f"Failed to get Monobank client info: {self.last_error}")
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            self.last_error = monobank_transport_error_summary(exc)
            logger.error(f"Failed to get Monobank client info: {self.last_error}")
            return None

    async def set_webhook(self, webhook_url: str) -> bool:
        """
        Установить WebHook URL для получения уведомлений о новых транзакциях.

        Args:
            webhook_url: URL для webhook (должен быть доступен извне по HTTPS)

        Returns:
            True если успешно установлен
        """
        self.last_error = None
        if not self.token:
            self.last_error = "token_missing"
            logger.error("Monobank token missing")
            return False

        await self._wait_for_rate_limit()

        url = f"{BASE_URL}/personal/webhook"
        headers = {"X-Token": self.token, "Content-Type": "application/json"}
        data = {"webHookUrl": webhook_url}

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, headers=headers, json=data) as resp:
                    if resp.status == 200:
                        self.last_error = None
                        logger.info(f"Monobank webhook set to: {webhook_url}")
                        return True
                    text = await resp.text()
                    self.last_error = monobank_error_summary(resp.status, text)
                    logger.error(f"Failed to set Monobank webhook: {self.last_error}")
                    return False
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            self.last_error = monobank_transport_error_summary(exc)
            logger.error(f"Failed to set Monobank webhook: {self.last_error}")
            return False

    async def get_statement(
        self, account_id: str, from_timestamp: int, to_timestamp: Optional[int] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Получить выписку по счету.

        Args:
            account_id: ID счета (из get_client_info -> accounts[].id)
            from_timestamp: Начало периода (Unix timestamp в секундах)
            to_timestamp: Конец периода (Unix timestamp в секундах), если None - текущее время

        Returns:
            Список транзакций
        """
        self.last_error = None
        if not self.token:
            self.last_error = "token_missing"
            logger.error("Monobank token missing")
            return None

        await self._wait_for_rate_limit()

        to_ts = to_timestamp or int(time.time())
        url = f"{BASE_URL}/personal/statement/{account_id}/{from_timestamp}/{to_ts}"
        headers = {"X-Token": self.token}

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        self.last_error = None
                        return await resp.json()
                    text = await resp.text()
                    self.last_error = monobank_error_summary(resp.status, text)
                    logger.error(f"Failed to get Monobank statement: {self.last_error}")
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            self.last_error = monobank_transport_error_summary(exc)
            logger.error(f"Failed to get Monobank statement: {self.last_error}")
            return None

    async def find_payment_by_comment(
        self,
        account_id: str,
        comment: str,
        amount: int,
        from_timestamp: int,
        to_timestamp: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Найти платеж по комментарию и сумме.

        Args:
            account_id: ID счета
            comment: Комментарий для поиска
            amount: Сумма в минимальных единицах валюты (копейки для UAH, центы для USD)
            from_timestamp: Начало периода поиска
            to_timestamp: Конец периода поиска

        Returns:
            Транзакция или None
        """
        statement = await self.get_statement(account_id, from_timestamp, to_timestamp)
        if not statement:
            return None

        comment_lower = comment.lower().strip()
        for transaction in statement:
            # Проверяем входящий платеж (amount > 0)
            if transaction.get("amount", 0) <= 0:
                continue

            # Проверяем сумму
            if transaction.get("amount") != amount:
                continue

            # Проверяем комментарий
            tx_comment = (transaction.get("description") or "").lower().strip()
            if comment_lower in tx_comment:
                return transaction

        return None

    def format_amount(self, amount_minor: int, currency_code: int) -> str:
        """
        Форматировать сумму из минимальных единиц.

        Args:
            amount_minor: Сумма в минимальных единицах (копейки/центы)
            currency_code: Код валюты (980 = UAH, 840 = USD, 978 = EUR)

        Returns:
            Отформатированная строка с суммой
        """
        amount_major = amount_minor / 100
        currency_symbols = {
            980: "UAH",  # Гривна
            840: "USD",  # Доллар США
            978: "EUR",  # Евро
        }
        symbol = currency_symbols.get(currency_code, f"CUR{currency_code}")
        return f"{amount_major:.2f} {symbol}"
