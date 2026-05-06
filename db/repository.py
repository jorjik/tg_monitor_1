import os
from typing import Optional

import aiosqlite

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

    async def save_chat(
        self,
        topic_id: int,
        tg_id: int,
        username: Optional[str],
        title: str,
        chat_type: str,
        members_count: int = 0,
    ) -> None:
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
            cur = await db.execute(
                "SELECT is_active FROM chats WHERE id = ?", (chat_id,)
            )
            row = await cur.fetchone()
            if not row:
                return False
            new_state = 0 if row[0] else 1
            await db.execute(
                "UPDATE chats SET is_active = ? WHERE id = ?", (new_state, chat_id)
            )
            await db.commit()
            return bool(new_state)

    async def set_all_chats_active(self, topic_id: int, is_active: bool) -> int:
        """Включить или выключить все чаты темы. Возвращает кол-во затронутых."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "UPDATE chats SET is_active = ? WHERE topic_id = ?",
                (1 if is_active else 0, topic_id),
            )
            await db.commit()
            return cur.rowcount

    async def delete_chat(self, chat_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
            await db.commit()

    async def is_chat_monitored(self, tg_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT 1 FROM chats WHERE tg_id = ? AND is_active = 1 LIMIT 1",
                (tg_id,),
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
                    "SELECT * FROM keywords WHERE topic_id = ? ORDER BY word",
                    (topic_id,),
                )
            return [dict(r) for r in await cur.fetchall()]

    async def get_all_active_keywords(self) -> list[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT word FROM keywords WHERE is_active = 1")
            return [r[0] for r in await cur.fetchall()]

    async def toggle_keyword(self, kw_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT is_active FROM keywords WHERE id = ?", (kw_id,)
            )
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

    async def save_feed_item(
        self,
        chat_tg_id: int,
        chat_title: str,
        message_id: int,
        message_text: str,
        matched_keywords: list[str],
        sender_name: str,
        message_url: str,
    ) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO feed (chat_tg_id, chat_title, message_id, message_text, "
                    "matched_keywords, sender_name, message_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        chat_tg_id,
                        chat_title,
                        message_id,
                        message_text[:4000],
                        ", ".join(matched_keywords),
                        sender_name,
                        message_url,
                    ),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def get_feed(
        self, limit: int = 10, offset: int = 0, unread_only: bool = False
    ) -> list[dict]:
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
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
            await db.commit()
