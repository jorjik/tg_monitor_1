import asyncio
import html
import logging
from typing import Optional

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from telethon import TelegramClient, events

logger = logging.getLogger(__name__)


class MessageWatcher:
    def __init__(self, client: TelegramClient, repo, bot):
        self.client = client
        self.repo = repo
        self.bot = bot
        self._running = False
        self._handler = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        @self.client.on(events.NewMessage)
        async def _on_message(event):
            await self._handle(event)

        self._handler = _on_message
        logger.info("MessageWatcher: запущен")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._handler is not None:
            self.client.remove_event_handler(self._handler)
            self._handler = None
        logger.info("MessageWatcher: остановлен")

    async def _send_notification(self, recipient_id: int, notification: str) -> None:
        for attempt in range(3):
            try:
                await self.bot.send_message(
                    chat_id=recipient_id,
                    text=notification,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                return
            except TelegramRetryAfter as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(e.retry_after)

    async def _handle(self, event) -> None:
        if not self._running:
            return
        try:
            chat_id = event.chat_id
            text: str = event.message.message or ""
            if not text.strip():
                return
            keywords_by_user = await self.repo.get_monitor_keywords_by_user(chat_id)
            if not keywords_by_user:
                return

            chat = await event.get_chat()
            chat_title: str = getattr(chat, "title", str(chat_id))
            chat_username: Optional[str] = getattr(chat, "username", None)

            sender = await event.get_sender()
            if sender is None:
                sender_name = "Unknown"
            else:
                first = getattr(sender, "first_name", "") or ""
                last = getattr(sender, "last_name", "") or ""
                uname = getattr(sender, "username", None)
                sender_name = (
                    f"@{uname}" if uname
                    else f"{first} {last}".strip() or str(sender.id)
                )

            msg_id = event.message.id
            if chat_username:
                url = f"https://t.me/{chat_username}/{msg_id}"
            else:
                clean_id = str(chat_id).lstrip("-100")
                url = f"https://t.me/c/{clean_id}/{msg_id}"

            safe_chat_title = html.escape(chat_title)
            safe_sender_name = html.escape(sender_name)
            preview = html.escape(text[:300])
            if len(text) > 300:
                preview += "\u2026"

            text_lower = text.lower()
            for recipient_id, keywords in keywords_by_user.items():
                matched = [kw for kw in keywords if kw in text_lower]
                if not matched:
                    continue
                saved = await self.repo.save_feed_item(
                    user_tg_id=recipient_id,
                    chat_tg_id=chat_id, chat_title=chat_title, message_id=msg_id,
                    message_text=text, matched_keywords=matched,
                    sender_name=sender_name, message_url=url,
                )
                if not saved:
                    continue
                if not await self.repo.should_send_notification(recipient_id):
                    logger.info("Уведомление пользователю %s отложено cooldown", recipient_id)
                    continue

                kw_str = ", ".join(f"\u00ab{html.escape(k)}\u00bb" for k in matched)
                notification = "\n".join([
                    "\U0001F514 <b>\u0421\u043e\u0432\u043f\u0430\u0434\u0435\u043d\u0438\u0435 \u043f\u043e \u0432\u0430\u0448\u0438\u043c \u043a\u043b\u044e\u0447\u0435\u0432\u044b\u043c \u0441\u043b\u043e\u0432\u0430\u043c!</b>",
                    "",
                    f"\U0001F4AC <b>\u0427\u0430\u0442:</b> {safe_chat_title}",
                    f"\U0001F511 <b>\u0421\u043b\u043e\u0432\u0430:</b> {kw_str}",
                    f"\U0001F464 <b>\u041e\u0442:</b> {safe_sender_name}",
                    "",
                    f"\U0001F4DD {preview}",
                    "",
                    f"\U0001F517 <a href=\"{url}\">\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435</a>",
                ])
                try:
                    await self._send_notification(recipient_id, notification)
                    await self.repo.mark_notification_sent(recipient_id)
                except TelegramForbiddenError:
                    await self.repo.deactivate_bot_user(recipient_id)
                    logger.warning(f"Пользователь {recipient_id} заблокировал бота")
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление пользователю {recipient_id}: {e}")
        except Exception as e:
            logger.error(f"Ошибка в _handle: {e}", exc_info=True)
