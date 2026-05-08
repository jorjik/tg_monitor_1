import asyncio
import logging
from typing import Optional

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Channel, Chat

logger = logging.getLogger(__name__)
MAX_FLOOD_WAIT_SECONDS = 60

# Слова-маркеры РФ-географии для кнопки «Убрать Гео РФ»
GEO_EXCLUDE_DEFAULT = ",".join(
    [
        "рф",
        "россия",
        "russia",
        "rf",
        "мск",
        "москва",
        "moscow",
        "спб",
        "санкт-петербург",
        "питер",
        "spb",
        "нск",
        "новосибирск",
        "екб",
        "екатеринбург",
        "казань",
        "краснодар",
        "нижний новгород",
        "самара",
        "омск",
        "челябинск",
        "уфа",
        "волгоград",
        "красноярск",
        "пермь",
        "воронеж",
        "саратов",
        "тюмень",
        "ростов",
        "тольятти",
        "ижевск",
        "барнаул",
        "иркутск",
        "хабаровск",
        "владивосток",
        "снг",
        "sng",
        "новокузнецк",
        "кузбасс",
        "кузба",
    ]
)


def _is_geo_excluded(title: str, exclude_words: list[str]) -> bool:
    """Возвращает True если название чата содержит гео-маркер из списка."""
    title_lower = title.lower()
    return any(w in title_lower for w in exclude_words)


class ChatCollector:
    """
    Проход 1: поиск публичных чатов/каналов по слову в названии.
    Поддерживает гео-фильтр (исключение по словам) и ручное добавление.
    """

    def __init__(self, client: TelegramClient, repo):
        self.client = client
        self.repo = repo

    async def collect(
        self,
        topic_id: int,
        search_terms: list[str],
        limit_per_term: int = 50,
        exclude_words: Optional[list[str]] = None,
        progress_callback=None,
    ) -> list[dict]:
        """
        Для каждого слова ищет чаты по названию.
        exclude_words — список слов-маркеров, чаты с которыми пропускаются.
        """
        found: dict[int, dict] = {}
        excluded_count = 0

        for idx, term in enumerate(search_terms):
            if progress_callback:
                await progress_callback(
                    idx + 1, len(search_terms), term, len(found), excluded_count
                )

            try:
                result = await self._search(term.strip(), limit_per_term)
            except Exception as e:
                logger.error(f"Search failed for '{term}': {e}")
                continue

            for entity in result.chats:
                tg_id = entity.id
                if tg_id in found:
                    continue

                username: Optional[str] = getattr(entity, "username", None)
                title: str = getattr(entity, "title", str(tg_id))
                members: int = getattr(entity, "participants_count", 0) or 0

                if isinstance(entity, Channel):
                    chat_type = "channel" if entity.broadcast else "supergroup"
                elif isinstance(entity, Chat):
                    chat_type = "group"
                else:
                    continue

                # ── Гео-фильтр ──────────────────────────────────────────────
                if exclude_words and _is_geo_excluded(title, exclude_words):
                    logger.debug(f"Гео-фильтр: пропускаем «{title}»")
                    excluded_count += 1
                    continue

                found[tg_id] = {
                    "tg_id": tg_id,
                    "username": username,
                    "title": title,
                    "chat_type": chat_type,
                    "members_count": members,
                }
                await self.repo.save_chat(
                    topic_id=topic_id,
                    tg_id=tg_id,
                    username=username,
                    title=title,
                    chat_type=chat_type,
                    members_count=members,
                )

            logger.info(
                f"[{idx + 1}/{len(search_terms)}] «{term}» → "
                f"+{len(result.chats)} (пропущено гео: {excluded_count}, итого: {len(found)})"
            )
            await asyncio.sleep(1.0)

        logger.info(
            f"Сбор завершён: {len(found)} чатов, отфильтровано: {excluded_count}"
        )
        return list(found.values())

    async def add_by_username(self, topic_id: int, raw: str) -> tuple[bool, str]:
        """
        Ручное добавление чата по @username или ссылке t.me/...
        Возвращает (успех, сообщение).
        """
        # Парсим входную строку
        username = (
            raw.strip()
            .lstrip("@")
            .replace("https://t.me/", "")
            .replace("http://t.me/", "")
            .replace("t.me/", "")
            .split("/")[0]  # убираем /msg_id если есть
            .strip()
        )

        if not username:
            return False, "Не удалось распознать username."

        try:
            entity = await self.client.get_entity(username)
        except FloodWaitError as e:
            if e.seconds > MAX_FLOOD_WAIT_SECONDS:
                logger.warning(
                    f"FloodWait {e.seconds}s превышает лимит при ручном добавлении «{username}»"
                )
                return False, "Telegram временно ограничил запросы. Попробуйте позже."
            logger.warning(f"FloodWait {e.seconds}s при ручном добавлении «{username}»")
            await asyncio.sleep(e.seconds + 2)
            try:
                entity = await self.client.get_entity(username)
            except (UsernameNotOccupiedError, UsernameInvalidError):
                return False, f"Чат @{username} не найден."
            except Exception as retry_error:
                return False, f"Ошибка после ожидания: {retry_error}"
        except (UsernameNotOccupiedError, UsernameInvalidError):
            return False, f"Чат @{username} не найден."
        except Exception as e:
            return False, f"Ошибка: {e}"

        title: str = getattr(entity, "title", username)
        members: int = getattr(entity, "participants_count", 0) or 0
        tg_id: int = entity.id
        entity_username: Optional[str] = getattr(entity, "username", None)

        if isinstance(entity, Channel):
            chat_type = "channel" if entity.broadcast else "supergroup"
        elif isinstance(entity, Chat):
            chat_type = "group"
        else:
            return False, "Это не группа и не канал."

        await self.repo.save_chat(
            topic_id=topic_id,
            tg_id=tg_id,
            username=entity_username,
            title=title,
            chat_type=chat_type,
            members_count=members,
        )
        return True, f"«{title}» ({chat_type}, {members:,} уч.) добавлен."

    async def _search(self, term: str, limit: int):
        try:
            return await self.client(SearchRequest(q=term, limit=limit))
        except FloodWaitError as e:
            logger.warning(f"FloodWait {e.seconds}s на «{term}»")
            await asyncio.sleep(e.seconds + 1)
            return await self.client(SearchRequest(q=term, limit=limit))
