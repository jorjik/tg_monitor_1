#!/usr/bin/env python3
"""bootstrap.py — создаёт все файлы проекта. Запустить: python bootstrap.py"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def w(path, content):
    full = os.path.join(ROOT, os.path.normpath(path))
    os.makedirs(os.path.dirname(full) or ROOT, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content.lstrip("\n"))
    print(f"  + {path}")


if "--force" not in sys.argv:
    raise SystemExit(
        "bootstrap.py устарел и перезаписывает рабочий multi-user проект. "
        "Если точно нужно восстановить старый шаблон, запустите: python bootstrap.py --force"
    )

print("Создание файлов проекта...\n")
os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)

w(
    "requirements.txt",
    """
telethon==1.36.0
aiogram==3.13.0
aiosqlite==0.20.0
python-dotenv==1.0.1
""",
)

w(
    ".env.example",
    """
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890
PHONE=+79001234567
BOT_TOKEN=1234567890:AABBccDDeeFFggHHiiJJkkLLmmNNoo
ADMIN_USER_ID=123456789
DB_PATH=data/monitor.db
SESSION_PATH=data/userbot_session
""",
)

w("core/__init__.py", "")

w(
    "core/config.py",
    """
import os
from dotenv import load_dotenv

load_dotenv()

API_ID: int = int(os.getenv("API_ID", "0"))
API_HASH: str = os.getenv("API_HASH", "")
PHONE: str = os.getenv("PHONE", "")
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))
DB_PATH: str = os.getenv("DB_PATH", "data/monitor.db")
SESSION_PATH: str = os.getenv("SESSION_PATH", "data/userbot_session")
""",
)

w("db/__init__.py", "")

w(
    "db/repository.py",
    '''
import os
import aiosqlite
from typing import Optional

CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    search_terms TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
    tg_id INTEGER NOT NULL,
    username TEXT,
    title TEXT NOT NULL,
    chat_type TEXT NOT NULL,
    members_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(topic_id, tg_id)
);
CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
    word TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS feed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_tg_id INTEGER NOT NULL,
    chat_title TEXT,
    message_id INTEGER NOT NULL,
    message_text TEXT,
    matched_keywords TEXT,
    sender_name TEXT,
    message_url TEXT,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_read INTEGER DEFAULT 0,
    UNIQUE(chat_tg_id, message_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Repository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(CREATE_SCHEMA)
            await db.commit()

    async def create_topic(self, name: str, search_terms: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT OR IGNORE INTO topics (name, search_terms) VALUES (?, ?)",
                (name.strip(), search_terms.strip()),
            )
            await db.commit()
            return cur.lastrowid or 0

    async def get_topics(self) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT t.*, COUNT(c.id) as chat_count FROM topics t "
                "LEFT JOIN chats c ON c.topic_id = t.id "
                "GROUP BY t.id ORDER BY t.created_at DESC"
            )
            return [dict(r) for r in await cur.fetchall()]

    async def get_topic(self, topic_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_topic_by_name(self, name: str) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM topics WHERE name = ?", (name,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def delete_topic(self, topic_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
            await db.commit()

    async def save_chat(self, topic_id: int, tg_id: int, username: Optional[str],
                        title: str, chat_type: str, members_count: int = 0) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO chats "
                "(topic_id, tg_id, username, title, chat_type, members_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (topic_id, tg_id, username, title, chat_type, members_count),
            )
            await db.commit()

    async def get_chats(self, topic_id: int) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM chats WHERE topic_id = ? ORDER BY members_count DESC",
                (topic_id,),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def get_active_chats(self) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT DISTINCT tg_id, username, title, chat_type "
                "FROM chats WHERE is_active = 1"
            )
            return [dict(r) for r in await cur.fetchall()]

    async def toggle_chat(self, chat_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT is_active FROM chats WHERE id = ?", (chat_id,))
            row = await cur.fetchone()
            if not row:
                return False
            new_state = 0 if row[0] else 1
            await db.execute("UPDATE chats SET is_active = ? WHERE id = ?", (new_state, chat_id))
            await db.commit()
            return bool(new_state)

    async def delete_chat(self, chat_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
            await db.commit()

    async def is_chat_monitored(self, tg_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT 1 FROM chats WHERE tg_id = ? AND is_active = 1 LIMIT 1", (tg_id,)
            )
            return await cur.fetchone() is not None

    async def add_keyword(self, word: str, topic_id: Optional[int] = None) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO keywords (word, topic_id) VALUES (LOWER(?), ?)",
                    (word.strip(), topic_id),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def get_keywords(self, topic_id: Optional[int] = None) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if topic_id is None:
                cur = await db.execute(
                    "SELECT * FROM keywords WHERE topic_id IS NULL ORDER BY word"
                )
            else:
                cur = await db.execute(
                    "SELECT * FROM keywords WHERE topic_id = ? ORDER BY word", (topic_id,)
                )
            return [dict(r) for r in await cur.fetchall()]

    async def get_all_active_keywords(self) -> list[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT word FROM keywords WHERE is_active = 1")
            return [r[0] for r in await cur.fetchall()]

    async def toggle_keyword(self, kw_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT is_active FROM keywords WHERE id = ?", (kw_id,))
            row = await cur.fetchone()
            if not row:
                return False
            new_state = 0 if row[0] else 1
            await db.execute(
                "UPDATE keywords SET is_active = ? WHERE id = ?", (new_state, kw_id)
            )
            await db.commit()
            return bool(new_state)

    async def delete_keyword(self, kw_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM keywords WHERE id = ?", (kw_id,))
            await db.commit()

    async def save_feed_item(self, chat_tg_id: int, chat_title: str, message_id: int,
                              message_text: str, matched_keywords: list[str],
                              sender_name: str, message_url: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO feed (chat_tg_id, chat_title, message_id, message_text, "
                    "matched_keywords, sender_name, message_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (chat_tg_id, chat_title, message_id, message_text[:4000],
                     ", ".join(matched_keywords), sender_name, message_url),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def get_feed(self, limit: int = 10, offset: int = 0,
                       unread_only: bool = False) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            where = "WHERE is_read = 0" if unread_only else ""
            cur = await db.execute(
                f"SELECT * FROM feed {where} ORDER BY received_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def mark_read(self, item_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE feed SET is_read = 1 WHERE id = ?", (item_id,))
            await db.commit()

    async def mark_all_read(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE feed SET is_read = 1")
            await db.commit()

    async def get_unread_count(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM feed WHERE is_read = 0")
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_feed_total(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM feed")
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_setting(self, key: str, default: str = "") -> str:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cur.fetchone()
            return row[0] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
            await db.commit()
''',
)

w("userbot/__init__.py", "")

w(
    "userbot/collector.py",
    """
import asyncio
import logging
from typing import Optional

from telethon import TelegramClient
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Channel, Chat
from telethon.errors import FloodWaitError

logger = logging.getLogger(__name__)


class ChatCollector:
    def __init__(self, client: TelegramClient, repo):
        self.client = client
        self.repo = repo

    async def collect(self, topic_id: int, search_terms: list[str],
                      limit_per_term: int = 30, progress_callback=None) -> list[dict]:
        found: dict[int, dict] = {}

        for idx, term in enumerate(search_terms):
            if progress_callback:
                await progress_callback(idx + 1, len(search_terms), term)
            try:
                result = await self.client(
                    SearchRequest(q=term.strip(), limit=limit_per_term)
                )
            except FloodWaitError as e:
                logger.warning(f"FloodWait {e.seconds}s на '{term}'")
                await asyncio.sleep(e.seconds)
                try:
                    result = await self.client(
                        SearchRequest(q=term.strip(), limit=limit_per_term)
                    )
                except Exception as ex:
                    logger.error(f"Retry failed: {ex}")
                    continue
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
                found[tg_id] = {"tg_id": tg_id, "username": username,
                                 "title": title, "chat_type": chat_type,
                                 "members_count": members}
                await self.repo.save_chat(
                    topic_id=topic_id, tg_id=tg_id, username=username,
                    title=title, chat_type=chat_type, members_count=members,
                )
            await asyncio.sleep(1.0)

        logger.info(f"Собрано {len(found)} чатов для topic_id={topic_id}")
        return list(found.values())
""",
)

w(
    "userbot/watcher.py",
    """
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

            kw_str = ", ".join(f"\\u00ab{k}\\u00bb" for k in matched)
            preview = text[:300].replace("<", "&lt;").replace(">", "&gt;")
            if len(text) > 300:
                preview += "\\u2026"

            notification = "\\n".join([
                "\\U0001F514 <b>\\u0421\\u043e\\u0432\\u043f\\u0430\\u0434\\u0435\\u043d\\u0438\\u0435 \\u043f\\u043e \\u043a\\u043b\\u044e\\u0447\\u0435\\u0432\\u044b\\u043c \\u0441\\u043b\\u043e\\u0432\\u0430\\u043c!</b>",
                "",
                f"\\U0001F4AC <b>\\u0427\\u0430\\u0442:</b> {chat_title}",
                f"\\U0001F511 <b>\\u0421\\u043b\\u043e\\u0432\\u0430:</b> {kw_str}",
                f"\\U0001F464 <b>\\u041e\\u0442:</b> {sender_name}",
                "",
                f"\\U0001F4DD {preview}",
                "",
                f"\\U0001F517 <a href=\\"{url}\\">\\u041e\\u0442\\u043a\\u0440\\u044b\\u0442\\u044c \\u0441\\u043e\\u043e\\u0431\\u0449\\u0435\\u043d\\u0438\\u0435</a>",
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
""",
)

w("bot/__init__.py", "")

w(
    "bot/states.py",
    """
from aiogram.fsm.state import State, StatesGroup


class TopicForm(StatesGroup):
    waiting_name = State()
    waiting_search_terms = State()


class KeywordForm(StatesGroup):
    waiting_keyword = State()
""",
)

w(
    "bot/keyboards.py",
    """
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Темы"), KeyboardButton(text="➕ Новая тема")],
            [KeyboardButton(text="🔑 Ключевые слова"), KeyboardButton(text="📰 Лента")],
            [KeyboardButton(text="⚙️ Мониторинг"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
    )


def topics_kb(topics: list[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in topics:
        cnt = t.get("chat_count", 0)
        b.button(text=f"📂 {t['name']} ({cnt} чатов)", callback_data=f"topic:{t['id']}")
    b.button(text="➕ Новая тема", callback_data="topic:new")
    b.adjust(1)
    return b.as_markup()


def topic_detail_kb(topic_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔍 Собрать чаты (Проход 1)", callback_data=f"collect:{topic_id}")
    b.button(text="💬 Просмотр чатов", callback_data=f"chats:{topic_id}:0")
    b.button(text="🔑 Ключевые слова темы", callback_data=f"kw_topic:{topic_id}")
    b.button(text="🗑 Удалить тему", callback_data=f"del_topic:{topic_id}")
    b.button(text="◀️ Назад", callback_data="topics_list")
    b.adjust(1)
    return b.as_markup()


def chats_kb(chats: list[dict], topic_id: int, page: int = 0,
             page_size: int = 8) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    start = page * page_size
    end = start + page_size
    for c in chats[start:end]:
        icon = "✅" if c["is_active"] else "⭕"
        ticon = "📢" if c["chat_type"] == "channel" else "👥"
        title = c["title"][:28]
        members = c.get("members_count", 0)
        b.button(
            text=f"{icon} {ticon} {title} ({members:,})",
            callback_data=f"toggle_chat:{c['id']}:{topic_id}:{page}",
        )
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="◀️", callback_data=f"chats:{topic_id}:{page - 1}"))
    if end < len(chats):
        nav.append(InlineKeyboardButton(
            text="▶️", callback_data=f"chats:{topic_id}:{page + 1}"))
    if nav:
        b.row(*nav)
    b.row(
        InlineKeyboardButton(text="✅ Все вкл", callback_data=f"chats_all_on:{topic_id}"),
        InlineKeyboardButton(text="⭕ Все выкл", callback_data=f"chats_all_off:{topic_id}"),
    )
    b.row(InlineKeyboardButton(text="◀️ К теме", callback_data=f"topic:{topic_id}"))
    return b.as_markup()


def keywords_kb(keywords: list[dict], topic_id: int | None = None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for kw in keywords:
        icon = "✅" if kw["is_active"] else "⭕"
        b.button(text=f"{icon} {kw['word']}", callback_data=f"toggle_kw:{kw['id']}")
    b.adjust(2)
    suffix = f":{topic_id}" if topic_id is not None else ":global"
    b.row(InlineKeyboardButton(text="➕ Добавить", callback_data=f"add_kw{suffix}"))
    if topic_id is None:
        b.row(InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    else:
        b.row(InlineKeyboardButton(text="◀️ К теме", callback_data=f"topic:{topic_id}"))
    return b.as_markup()


def feed_kb(items: list[dict], page: int, total: int,
            page_size: int = 5) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for item in items:
        icon = "📖" if item["is_read"] else "🆕"
        title = (item["chat_title"] or "")[:20]
        kws = (item["matched_keywords"] or "")[:20]
        b.button(text=f"{icon} {title} | {kws}",
                 callback_data=f"feed_item:{item['id']}:{page}")
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="◀️", callback_data=f"feed_page:{page - 1}"))
    if (page + 1) * page_size < total:
        nav.append(InlineKeyboardButton(
            text="▶️", callback_data=f"feed_page:{page + 1}"))
    if nav:
        b.row(*nav)
    b.row(
        InlineKeyboardButton(text="✅ Всё прочитано", callback_data="feed_read_all"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"feed_page:{page}"),
    )
    return b.as_markup()


def feed_item_kb(item_id: int, url: str, back_page: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if url:
        b.button(text="🔗 Открыть в Telegram", url=url)
    b.button(text="✅ Прочитано", callback_data=f"read_item:{item_id}:{back_page}")
    b.button(text="◀️ Назад", callback_data=f"feed_page:{back_page}")
    b.adjust(1)
    return b.as_markup()


def monitor_kb(is_running: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if is_running:
        b.button(text="⏹ Остановить мониторинг", callback_data="monitor:stop")
    else:
        b.button(text="▶️ Запустить мониторинг", callback_data="monitor:start")
    b.button(text="🔄 Обновить статус", callback_data="monitor:status")
    b.adjust(1)
    return b.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="❌ Отмена", callback_data="cancel")
    return b.as_markup()
""",
)

w("bot/handlers/__init__.py", "")

w(
    "bot/handlers/common.py",
    """
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.keyboards import main_menu_kb

router = Router()

HELP_TEXT = \"\"\"
<b>🤖 Telegram Monitor Bot</b>

<b>Как работает:</b>
1️⃣ <b>Проход 1 — Сбор чатов:</b> Создайте тему (напр. «бизнес») и задайте поисковые слова. Бот найдёт публичные чаты по этой теме.

2️⃣ <b>Проход 2 — Мониторинг:</b> Добавьте ключевые слова. Запустите мониторинг — бот отслеживает новые сообщения в реальном времени.

3️⃣ <b>Лента:</b> Все совпадения сохраняются. Уведомления мгновенно.

/start — главное меню
/feed — лента
/monitor — мониторинг
\"\"\"


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>Добро пожаловать в Telegram Monitor!</b>\\n\\nВыберите действие:",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Действие отменено.")
    await callback.answer()
""",
)

w(
    "bot/handlers/topics.py",
    """
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.states import TopicForm
from bot.keyboards import topics_kb, topic_detail_kb, chats_kb, cancel_kb
from db.repository import Repository
from userbot.collector import ChatCollector

router = Router()


@router.message(F.text == "📋 Темы")
@router.message(Command("topics"))
async def cmd_topics(message: Message, repo: Repository):
    topics = await repo.get_topics()
    if not topics:
        await message.answer(
            "📂 Нет тем.\\n\\nНажмите <b>➕ Новая тема</b> чтобы создать первую.",
            reply_markup=topics_kb([]), parse_mode="HTML",
        )
    else:
        await message.answer(
            f"📂 <b>Ваши темы</b> ({len(topics)}):",
            reply_markup=topics_kb(topics), parse_mode="HTML",
        )


@router.callback_query(F.data == "topics_list")
async def cb_topics_list(callback: CallbackQuery, repo: Repository):
    topics = await repo.get_topics()
    await callback.message.edit_text(
        f"📂 <b>Ваши темы</b> ({len(topics)}):",
        reply_markup=topics_kb(topics), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("topic:"))
async def cb_topic_detail(callback: CallbackQuery, repo: Repository, state: FSMContext):
    topic_id_str = callback.data.split(":")[1]
    if topic_id_str == "new":
        await state.set_state(TopicForm.waiting_name)
        await callback.message.answer(
            "📝 <b>Новая тема</b>\\n\\nВведите <b>название темы</b>:",
            reply_markup=cancel_kb(), parse_mode="HTML",
        )
        await callback.answer()
        return
    topic_id = int(topic_id_str)
    topic = await repo.get_topic(topic_id)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    chats = await repo.get_chats(topic_id)
    active = sum(1 for c in chats if c["is_active"])
    text = (
        f"📂 <b>Тема: {topic['name']}</b>\\n\\n"
        f"🔍 Поисковые слова: {topic['search_terms']}\\n"
        f"💬 Чатов: {len(chats)} (активных: {active})"
    )
    await callback.message.edit_text(
        text, reply_markup=topic_detail_kb(topic_id), parse_mode="HTML"
    )
    await callback.answer()


@router.message(F.text == "➕ Новая тема")
@router.message(Command("new_topic"))
async def cmd_new_topic(message: Message, state: FSMContext):
    await state.set_state(TopicForm.waiting_name)
    await message.answer(
        "📝 <b>Новая тема</b>\\n\\nВведите <b>название</b> (напр. Бизнес, Крипта):",
        reply_markup=cancel_kb(), parse_mode="HTML",
    )


@router.message(TopicForm.waiting_name)
async def process_topic_name(message: Message, state: FSMContext, repo: Repository):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("❌ Слишком короткое название.")
        return
    if await repo.get_topic_by_name(name):
        await message.answer(f"⚠️ Тема «{name}» уже существует.")
        return
    await state.update_data(topic_name=name)
    await state.set_state(TopicForm.waiting_search_terms)
    await message.answer(
        f"✅ Название: <b>{name}</b>\\n\\n"
        "Введите <b>поисковые слова</b> через запятую.\\n"
        "Напр: <code>стартап, инвестиции, франшиза</code>",
        reply_markup=cancel_kb(), parse_mode="HTML",
    )


@router.message(TopicForm.waiting_search_terms)
async def process_search_terms(message: Message, state: FSMContext, repo: Repository):
    terms = message.text.strip()
    if not terms:
        await message.answer("❌ Введите хотя бы одно слово.")
        return
    data = await state.get_data()
    topic_id = await repo.create_topic(data["topic_name"], terms)
    await state.clear()
    await message.answer(
        f"✅ <b>Тема «{data['topic_name']}» создана!</b>\\n\\n"
        f"Поисковые слова: {terms}\\n\\n"
        "Нажмите <b>🔍 Собрать чаты</b> для первого прохода.",
        reply_markup=topic_detail_kb(topic_id), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("del_topic:"))
async def cb_delete_topic(callback: CallbackQuery, repo: Repository):
    topic_id = int(callback.data.split(":")[1])
    topic = await repo.get_topic(topic_id)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await repo.delete_topic(topic_id)
    topics = await repo.get_topics()
    await callback.message.edit_text(
        f"🗑 Тема «{topic['name']}» удалена.\\n\\n📂 <b>Темы</b> ({len(topics)}):",
        reply_markup=topics_kb(topics), parse_mode="HTML",
    )
    await callback.answer("Удалено")


@router.callback_query(F.data.startswith("collect:"))
async def cb_collect(callback: CallbackQuery, repo: Repository, collector: ChatCollector):
    topic_id = int(callback.data.split(":")[1])
    topic = await repo.get_topic(topic_id)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    terms = [t.strip() for t in topic["search_terms"].split(",") if t.strip()]
    msg = await callback.message.edit_text(
        f"🔍 <b>Проход 1: Сбор чатов</b>\\n\\n"
        f"Тема: {topic['name']}\\nСлов: {len(terms)}\\n\\n⏳ Начинаю...",
        parse_mode="HTML",
    )
    await callback.answer()

    async def on_progress(current, total, term):
        chats_so_far = await repo.get_chats(topic_id)
        try:
            await msg.edit_text(
                f"🔍 <b>Проход 1: Сбор чатов</b>\\n\\n"
                f"Прогресс: {current}/{total}\\n"
                f"🔎 Ищу: «{term}»\\n"
                f"Найдено: {len(chats_so_far)} чатов",
                parse_mode="HTML",
            )
        except Exception:
            pass

    await collector.collect(
        topic_id=topic_id, search_terms=terms,
        limit_per_term=30, progress_callback=on_progress,
    )
    chats = await repo.get_chats(topic_id)
    await msg.edit_text(
        f"✅ <b>Сбор завершён!</b>\\n\\n"
        f"Тема: <b>{topic['name']}</b>\\n"
        f"Найдено чатов: <b>{len(chats)}</b>\\n\\n"
        "Выберите какие чаты мониторить.",
        reply_markup=topic_detail_kb(topic_id), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("chats:"))
async def cb_view_chats(callback: CallbackQuery, repo: Repository):
    parts = callback.data.split(":")
    topic_id, page = int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
    topic = await repo.get_topic(topic_id)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    chats = await repo.get_chats(topic_id)
    if not chats:
        await callback.message.edit_text(
            f"💬 Нет чатов для «{topic['name']}».\\nЗапустите 🔍 Собрать чаты.",
            reply_markup=topic_detail_kb(topic_id), parse_mode="HTML",
        )
        await callback.answer()
        return
    active = sum(1 for c in chats if c["is_active"])
    await callback.message.edit_text(
        f"💬 <b>Чаты «{topic['name']}»</b>\\n"
        f"Всего: {len(chats)} | Активных: {active}\\n\\n"
        "✅ — мониторится | ⭕ — выключен",
        reply_markup=chats_kb(chats, topic_id, page), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_chat:"))
async def cb_toggle_chat(callback: CallbackQuery, repo: Repository):
    parts = callback.data.split(":")
    chat_id, topic_id = int(parts[1]), int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    new_state = await repo.toggle_chat(chat_id)
    chats = await repo.get_chats(topic_id)
    topic = await repo.get_topic(topic_id)
    active = sum(1 for c in chats if c["is_active"])
    await callback.message.edit_text(
        f"💬 <b>Чаты «{topic['name']}»</b>\\n"
        f"Всего: {len(chats)} | Активных: {active}\\n\\n"
        "✅ — мониторится | ⭕ — выключен",
        reply_markup=chats_kb(chats, topic_id, page), parse_mode="HTML",
    )
    await callback.answer("✅ Включён" if new_state else "⭕ Выключен")
""",
)

w(
    "bot/handlers/keywords.py",
    """
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.states import KeywordForm
from bot.keyboards import keywords_kb, cancel_kb
from db.repository import Repository

router = Router()


@router.message(F.text == "🔑 Ключевые слова")
@router.message(Command("keywords"))
async def cmd_keywords(message: Message, repo: Repository):
    kws = await repo.get_keywords(topic_id=None)
    active = sum(1 for k in kws if k["is_active"])
    await message.answer(
        f"🔑 <b>Глобальные ключевые слова</b>\\n"
        f"Всего: {len(kws)} | Активных: {active}\\n\\n"
        "Применяются ко всем темам:",
        reply_markup=keywords_kb(kws, topic_id=None), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("kw_topic:"))
async def cb_kw_topic(callback: CallbackQuery, repo: Repository):
    topic_id = int(callback.data.split(":")[1])
    kws = await repo.get_keywords(topic_id=topic_id)
    active = sum(1 for k in kws if k["is_active"])
    await callback.message.edit_text(
        f"🔑 <b>Ключевые слова темы</b>\\n"
        f"Всего: {len(kws)} | Активных: {active}",
        reply_markup=keywords_kb(kws, topic_id=topic_id), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_kw:"))
async def cb_toggle_kw(callback: CallbackQuery, repo: Repository):
    kw_id = int(callback.data.split(":")[1])
    new_state = await repo.toggle_keyword(kw_id)
    await callback.answer("✅ Включено" if new_state else "⭕ Выключено")
    kws = await repo.get_keywords(topic_id=None)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=keywords_kb(kws, topic_id=None)
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("add_kw"))
async def cb_add_kw_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    scope = parts[1] if len(parts) > 1 else "global"
    await state.update_data(kw_topic_id=None if scope == "global" else int(scope))
    await state.set_state(KeywordForm.waiting_keyword)
    await callback.message.answer(
        "🔑 Введите ключевое слово или фразу:\\n\\n"
        "Напр: <code>инвестиции</code> или <code>ищу партнёра</code>",
        reply_markup=cancel_kb(), parse_mode="HTML",
    )
    await callback.answer()


@router.message(KeywordForm.waiting_keyword)
async def process_keyword(message: Message, state: FSMContext, repo: Repository):
    word = message.text.strip().lower()
    if not word:
        await message.answer("❌ Пустое слово.")
        return
    data = await state.get_data()
    topic_id = data.get("kw_topic_id")
    await state.clear()
    added = await repo.add_keyword(word, topic_id=topic_id)
    scope = "глобально" if topic_id is None else f"для темы #{topic_id}"
    if added:
        await message.answer(
            f"✅ Слово <b>«{word}»</b> добавлено ({scope}).", parse_mode="HTML"
        )
    else:
        await message.answer(f"⚠️ Слово «{word}» уже существует.")
    kws = await repo.get_keywords(topic_id=topic_id)
    active = sum(1 for k in kws if k["is_active"])
    await message.answer(
        f"🔑 Слов: {len(kws)} (активных: {active})",
        reply_markup=keywords_kb(kws, topic_id=topic_id), parse_mode="HTML",
    )
""",
)

w(
    "bot/handlers/feed.py",
    """
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.keyboards import feed_kb, feed_item_kb
from db.repository import Repository

router = Router()
PAGE_SIZE = 5


@router.message(F.text == "📰 Лента")
@router.message(Command("feed"))
async def cmd_feed(message: Message, repo: Repository):
    await _show(message, repo, 0, edit=False)


@router.callback_query(F.data.startswith("feed_page:"))
async def cb_feed_page(callback: CallbackQuery, repo: Repository):
    page = int(callback.data.split(":")[1])
    await _show(callback.message, repo, page, edit=True)
    await callback.answer()


async def _show(msg, repo: Repository, page: int, edit: bool):
    total = await repo.get_feed_total()
    unread = await repo.get_unread_count()
    items = await repo.get_feed(limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    if not items and page == 0:
        text = "📰 <b>Лента пуста</b>\\n\\nЗапустите мониторинг — совпадения появятся здесь."
        kb = feed_kb([], 0, 0)
    else:
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        text = (
            f"📰 <b>Лента</b>\\n"
            f"Всего: {total} | 🆕 Непрочитано: {unread}\\n"
            f"Стр. {page + 1}/{pages}"
        )
        kb = feed_kb(items, page, total, PAGE_SIZE)
    if edit:
        try:
            await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await msg.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("feed_item:"))
async def cb_feed_item(callback: CallbackQuery, repo: Repository):
    parts = callback.data.split(":")
    item_id, back = int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
    all_items = await repo.get_feed(limit=1000, offset=0)
    item = next((i for i in all_items if i["id"] == item_id), None)
    if not item:
        await callback.answer("Не найдено", show_alert=True)
        return
    await repo.mark_read(item_id)
    preview = (item["message_text"] or "")[:1000]
    text = (
        f"💬 <b>{item['chat_title']}</b>\\n"
        f"👤 {item['sender_name']}\\n"
        f"🔑 {item['matched_keywords']}\\n"
        f"🕐 {item['received_at']}\\n\\n"
        f"{preview}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=feed_item_kb(item_id, item.get("message_url", ""), back),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("read_item:"))
async def cb_read_item(callback: CallbackQuery, repo: Repository):
    parts = callback.data.split(":")
    item_id, back = int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
    await repo.mark_read(item_id)
    await callback.answer("✅ Прочитано")
    await _show(callback.message, repo, back, edit=True)


@router.callback_query(F.data == "feed_read_all")
async def cb_read_all(callback: CallbackQuery, repo: Repository):
    await repo.mark_all_read()
    await callback.answer("✅ Все прочитаны")
    await _show(callback.message, repo, 0, edit=True)
""",
)

w(
    "bot/handlers/monitor.py",
    """
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.keyboards import monitor_kb
from db.repository import Repository
from userbot.watcher import MessageWatcher

router = Router()


async def _status(repo: Repository, watcher: MessageWatcher) -> str:
    chats = await repo.get_active_chats()
    kws = await repo.get_all_active_keywords()
    unread = await repo.get_unread_count()
    icon = "🟢 Активен" if watcher.is_running else "🔴 Остановлен"
    return (
        f"⚙️ <b>Мониторинг</b>\\n\\n"
        f"Статус: {icon}\\n"
        f"💬 Активных чатов: {len(chats)}\\n"
        f"🔑 Активных ключевых слов: {len(kws)}\\n"
        f"📰 Непрочитанных: {unread}"
    )


@router.message(F.text == "⚙️ Мониторинг")
@router.message(Command("monitor"))
async def cmd_monitor(message: Message, repo: Repository, watcher: MessageWatcher):
    text = await _status(repo, watcher)
    await message.answer(text, reply_markup=monitor_kb(watcher.is_running), parse_mode="HTML")


@router.callback_query(F.data == "monitor:status")
async def cb_status(callback: CallbackQuery, repo: Repository, watcher: MessageWatcher):
    text = await _status(repo, watcher)
    try:
        await callback.message.edit_text(
            text, reply_markup=monitor_kb(watcher.is_running), parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer("Обновлено")


@router.callback_query(F.data == "monitor:start")
async def cb_start(callback: CallbackQuery, repo: Repository, watcher: MessageWatcher):
    if watcher.is_running:
        await callback.answer("Уже запущен", show_alert=True)
        return
    if not await repo.get_active_chats():
        await callback.answer("⚠️ Нет активных чатов!", show_alert=True)
        return
    if not await repo.get_all_active_keywords():
        await callback.answer("⚠️ Нет ключевых слов!", show_alert=True)
        return
    await watcher.start()
    text = await _status(repo, watcher)
    await callback.message.edit_text(
        text, reply_markup=monitor_kb(watcher.is_running), parse_mode="HTML"
    )
    await callback.answer("▶️ Мониторинг запущен!")


@router.callback_query(F.data == "monitor:stop")
async def cb_stop(callback: CallbackQuery, repo: Repository, watcher: MessageWatcher):
    if not watcher.is_running:
        await callback.answer("Уже остановлен", show_alert=True)
        return
    await watcher.stop()
    text = await _status(repo, watcher)
    await callback.message.edit_text(
        text, reply_markup=monitor_kb(watcher.is_running), parse_mode="HTML"
    )
    await callback.answer("⏹ Остановлен")
""",
)

w(
    "main.py",
    """
import asyncio
import logging
import os
import sys

os.makedirs("data", exist_ok=True)

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from telethon import TelegramClient

from core.config import API_ID, API_HASH, PHONE, BOT_TOKEN, ADMIN_USER_ID, DB_PATH, SESSION_PATH
from db.repository import Repository
from userbot.collector import ChatCollector
from userbot.watcher import MessageWatcher
from bot.handlers import common, topics, keywords, feed, monitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def _check_config() -> None:
    missing = [k for k, v in {
        "API_ID": API_ID, "API_HASH": API_HASH, "PHONE": PHONE,
        "BOT_TOKEN": BOT_TOKEN, "ADMIN_USER_ID": ADMIN_USER_ID,
    }.items() if not v]
    if missing:
        logger.error(f"Не заданы переменные: {', '.join(missing)}")
        logger.error("Скопируйте .env.example в .env и заполните значения.")
        sys.exit(1)


async def main() -> None:
    _check_config()

    repo = Repository(DB_PATH)
    await repo.init_db()
    logger.info(f"БД: {DB_PATH}")

    userbot = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await userbot.start(phone=PHONE)
    me = await userbot.get_me()
    logger.info(f"Userbot: {me.first_name} (@{me.username})")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    collector = ChatCollector(client=userbot, repo=repo)
    watcher = MessageWatcher(client=userbot, repo=repo, bot=bot, admin_id=ADMIN_USER_ID)

    dp["repo"] = repo
    dp["collector"] = collector
    dp["watcher"] = watcher

    dp.include_router(common.router)
    dp.include_router(topics.router)
    dp.include_router(keywords.router)
    dp.include_router(feed.router)
    dp.include_router(monitor.router)

    logger.info("Бот запускается...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await watcher.stop()
        await userbot.disconnect()
        await bot.session.close()
        logger.info("Остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлен пользователем.")
""",
)

print("\\n✅ Все файлы созданы!")
print("\\nДальнейшие шаги:")
print("  1. copy .env.example .env")
print("  2. Заполните .env (API_ID, API_HASH, PHONE, BOT_TOKEN, ADMIN_USER_ID)")
print("  3. .venv\\\\Scripts\\\\python main.py")
