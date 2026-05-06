import logging
from typing import Optional

from telethon import TelegramClient, events

logger = logging.getLogger(__name__)


class MessageWatcher:
    def __init__(self, client: TelegramClient, repo, bot, admin_id: int):
        self.client = client
        self.repo = repo
        self.bot = bot
        self.admin_id = admin_id
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

    async def _handle(self, event) -> None:
        if not self._running:
            return
        try:
            chat_id = event.chat_id
            if not await self.repo.is_chat_monitored(chat_id):
                return
            text: str = event.message.message or ""
            if not text.strip():
                return
            keywords = await self.repo.get_all_active_keywords()
            if not keywords:
                return
            matched = [kw for kw in keywords if kw in text.lower()]
            if not matched:
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

            saved = await self.repo.save_feed_item(
                chat_tg_id=chat_id, chat_title=chat_title, message_id=msg_id,
                message_text=text, matched_keywords=matched,
                sender_name=sender_name, message_url=url,
            )
            if not saved:
                return

            kw_str = ", ".join(f"\u00ab{k}\u00bb" for k in matched)
            preview = text[:300].replace("<", "&lt;").replace(">", "&gt;")
            if len(text) > 300:
                preview += "\u2026"

            notification = "\n".join([
                "\U0001F514 <b>\u0421\u043e\u0432\u043f\u0430\u0434\u0435\u043d\u0438\u0435 \u043f\u043e \u043a\u043b\u044e\u0447\u0435\u0432\u044b\u043c \u0441\u043b\u043e\u0432\u0430\u043c!</b>",
                "",
                f"\U0001F4AC <b>\u0427\u0430\u0442:</b> {chat_title}",
                f"\U0001F511 <b>\u0421\u043b\u043e\u0432\u0430:</b> {kw_str}",
                f"\U0001F464 <b>\u041e\u0442:</b> {sender_name}",
                "",
                f"\U0001F4DD {preview}",
                "",
                f"\U0001F517 <a href=\"{url}\">\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435</a>",
            ])

            try:
                await self.bot.send_message(
                    chat_id=self.admin_id,
                    text=notification,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление: {e}")
        except Exception as e:
            logger.error(f"Ошибка в _handle: {e}", exc_info=True)
