import logging
import os
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_tg_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    search_terms TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_tg_id, name)
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
    user_tg_id INTEGER NOT NULL,
    topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
    word TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS feed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_tg_id INTEGER NOT NULL,
    chat_tg_id INTEGER NOT NULL,
    chat_title TEXT,
    message_id INTEGER NOT NULL,
    message_text TEXT,
    matched_keywords TEXT,
    sender_name TEXT,
    message_url TEXT,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_read INTEGER DEFAULT 0,
    UNIQUE(user_tg_id, chat_tg_id, message_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_settings (
    user_tg_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY(user_tg_id, key)
);
CREATE TABLE IF NOT EXISTS bot_users (
    tg_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class Repository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_db(self) -> None:
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = OFF")
            await db.executescript(CREATE_SCHEMA)
            await self._migrate_topics(db)
            await self._migrate_keywords(db)
            await self._migrate_feed(db)
            await self._migrate_settings(db)
            await db.execute(
                "DELETE FROM keywords WHERE id NOT IN ("
                "SELECT MIN(id) FROM keywords GROUP BY user_tg_id, word, COALESCE(topic_id, -1)"
                ")"
            )
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_keywords_user_word_topic "
                "ON keywords(user_tg_id, word, COALESCE(topic_id, -1))"
            )
            await db.execute("PRAGMA foreign_keys = ON")
            await db.commit()

    async def _columns(self, db, table: str) -> set[str]:
        cur = await db.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in await cur.fetchall()}

    async def _legacy_owner_tg_id(self, db) -> int:
        raw_admin_id = os.getenv("ADMIN_USER_ID", "").strip()
        if raw_admin_id and raw_admin_id != "0":
            return int(raw_admin_id)
        cur = await db.execute(
            "SELECT tg_id FROM bot_users WHERE is_active = 1 ORDER BY created_at LIMIT 1"
        )
        row = await cur.fetchone()
        return row[0] if row else 0

    async def _legacy_owner_for_table(self, db, table: str) -> int:
        legacy_owner = await self._legacy_owner_tg_id(db)
        if legacy_owner:
            return legacy_owner
        cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
        row = await cur.fetchone()
        if row and row[0] == 0:
            return 0
        message = (
            "Найдена старая общая база без владельца. Укажите ADMIN_USER_ID в .env "
            "один раз для миграции старых тем, ключевых слов и ленты."
        )
        logger.error(message)
        raise RuntimeError(message)

    async def _migrate_topics(self, db) -> None:
        if "user_tg_id" in await self._columns(db, "topics"):
            return
        legacy_owner = await self._legacy_owner_for_table(db, "topics")
        await db.execute(
            "CREATE TABLE topics_new ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_tg_id INTEGER NOT NULL, "
            "name TEXT NOT NULL, "
            "search_terms TEXT NOT NULL, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "UNIQUE(user_tg_id, name)"
            ")"
        )
        await db.execute(
            "INSERT INTO topics_new (id, user_tg_id, name, search_terms, created_at) "
            "SELECT id, ?, name, search_terms, created_at FROM topics",
            (legacy_owner,),
        )
        await db.execute("DROP TABLE topics")
        await db.execute("ALTER TABLE topics_new RENAME TO topics")

    async def _migrate_keywords(self, db) -> None:
        if "user_tg_id" in await self._columns(db, "keywords"):
            return
        legacy_owner = await self._legacy_owner_for_table(db, "keywords")
        await db.execute(
            "CREATE TABLE keywords_new ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_tg_id INTEGER NOT NULL, "
            "topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE, "
            "word TEXT NOT NULL, "
            "is_active INTEGER DEFAULT 1"
            ")"
        )
        await db.execute(
            "INSERT INTO keywords_new (id, user_tg_id, topic_id, word, is_active) "
            "SELECT k.id, COALESCE(t.user_tg_id, ?), k.topic_id, k.word, k.is_active "
            "FROM keywords k LEFT JOIN topics t ON t.id = k.topic_id",
            (legacy_owner,),
        )
        await db.execute("DROP TABLE keywords")
        await db.execute("ALTER TABLE keywords_new RENAME TO keywords")

    async def _migrate_feed(self, db) -> None:
        if "user_tg_id" in await self._columns(db, "feed"):
            return
        legacy_owner = await self._legacy_owner_for_table(db, "feed")
        await db.execute(
            "CREATE TABLE feed_new ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_tg_id INTEGER NOT NULL, "
            "chat_tg_id INTEGER NOT NULL, "
            "chat_title TEXT, "
            "message_id INTEGER NOT NULL, "
            "message_text TEXT, "
            "matched_keywords TEXT, "
            "sender_name TEXT, "
            "message_url TEXT, "
            "received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "is_read INTEGER DEFAULT 0, "
            "UNIQUE(user_tg_id, chat_tg_id, message_id)"
            ")"
        )
        await db.execute(
            "INSERT OR IGNORE INTO feed_new (id, user_tg_id, chat_tg_id, chat_title, "
            "message_id, message_text, matched_keywords, sender_name, message_url, "
            "received_at, is_read) "
            "SELECT id, ?, chat_tg_id, chat_title, message_id, message_text, "
            "matched_keywords, sender_name, message_url, received_at, is_read FROM feed",
            (legacy_owner,),
        )
        await db.execute("DROP TABLE feed")
        await db.execute("ALTER TABLE feed_new RENAME TO feed")

    async def _migrate_settings(self, db) -> None:
        legacy_owner = await self._legacy_owner_tg_id(db)
        if not legacy_owner:
            return
        cur = await db.execute("SELECT COUNT(*) FROM user_settings WHERE user_tg_id = ?", (legacy_owner,))
        row = await cur.fetchone()
        if row and row[0]:
            return
        await db.execute(
            "INSERT OR IGNORE INTO user_settings (user_tg_id, key, value) "
            "SELECT ?, key, value FROM settings",
            (legacy_owner,),
        )

    async def upsert_bot_user(
        self,
        tg_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO bot_users (tg_id, username, first_name, last_name, is_active) "
                "VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT(tg_id) DO UPDATE SET "
                "username = excluded.username, "
                "first_name = excluded.first_name, "
                "last_name = excluded.last_name, "
                "is_active = 1, "
                "updated_at = CURRENT_TIMESTAMP",
                (tg_id, username, first_name, last_name),
            )
            await db.commit()

    async def deactivate_bot_user(self, tg_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE bot_users SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE tg_id = ?",
                (tg_id,),
            )
            await db.commit()

    async def get_active_bot_user_ids(self) -> list[int]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT tg_id FROM bot_users WHERE is_active = 1")
            return [r[0] for r in await cur.fetchall()]

    async def create_topic(self, user_tg_id: int, name: str, search_terms: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT OR IGNORE INTO topics (user_tg_id, name, search_terms) VALUES (?, ?, ?)",
                (user_tg_id, name.strip(), search_terms.strip()),
            )
            await db.commit()
            return cur.lastrowid or 0

    async def get_topics(self, user_tg_id: int) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT t.*, COUNT(c.id) as chat_count FROM topics t "
                "LEFT JOIN chats c ON c.topic_id = t.id "
                "WHERE t.user_tg_id = ? "
                "GROUP BY t.id ORDER BY t.created_at DESC",
                (user_tg_id,),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def get_topic(self, user_tg_id: int, topic_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM topics WHERE id = ? AND user_tg_id = ?",
                (topic_id, user_tg_id),
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_topic_by_name(self, user_tg_id: int, name: str) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM topics WHERE user_tg_id = ? AND name = ?",
                (user_tg_id, name),
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def delete_topic(self, user_tg_id: int, topic_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM topics WHERE id = ? AND user_tg_id = ?",
                (topic_id, user_tg_id),
            )
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

    async def get_chats(self, user_tg_id: int, topic_id: int) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT c.* FROM chats c "
                "JOIN topics t ON t.id = c.topic_id "
                "WHERE c.topic_id = ? AND t.user_tg_id = ? "
                "ORDER BY c.members_count DESC",
                (topic_id, user_tg_id),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def get_chat(self, user_tg_id: int, topic_id: int, chat_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT c.* FROM chats c "
                "JOIN topics t ON t.id = c.topic_id "
                "WHERE c.id = ? AND c.topic_id = ? AND t.user_tg_id = ?",
                (chat_id, topic_id, user_tg_id),
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_active_chats(self, user_tg_id: int) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT DISTINCT c.tg_id, c.username, c.title, c.chat_type "
                "FROM chats c JOIN topics t ON t.id = c.topic_id "
                "WHERE c.is_active = 1 AND t.user_tg_id = ?",
                (user_tg_id,),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def toggle_chat(self, user_tg_id: int, chat_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT c.is_active FROM chats c "
                "JOIN topics t ON t.id = c.topic_id "
                "WHERE c.id = ? AND t.user_tg_id = ?",
                (chat_id, user_tg_id),
            )
            row = await cur.fetchone()
            if not row:
                return False
            new_state = 0 if row[0] else 1
            await db.execute("UPDATE chats SET is_active = ? WHERE id = ?", (new_state, chat_id))
            await db.commit()
            return bool(new_state)

    async def set_all_chats_active(
        self, user_tg_id: int, topic_id: int, is_active: bool
    ) -> int:
        """Включить или выключить все чаты темы. Возвращает кол-во затронутых."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "UPDATE chats SET is_active = ? "
                "WHERE topic_id IN (SELECT id FROM topics WHERE id = ? AND user_tg_id = ?)",
                (1 if is_active else 0, topic_id, user_tg_id),
            )
            await db.commit()
            return cur.rowcount

    async def delete_chat(self, user_tg_id: int, chat_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM chats WHERE id = ? AND topic_id IN ("
                "SELECT id FROM topics WHERE user_tg_id = ?"
                ")",
                (chat_id, user_tg_id),
            )
            await db.commit()

    async def add_keyword(
        self, user_tg_id: int, word: str, topic_id: Optional[int] = None
    ) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            try:
                if topic_id is None:
                    await db.execute(
                        "INSERT INTO keywords (user_tg_id, word, topic_id) VALUES (?, LOWER(?), NULL)",
                        (user_tg_id, word.strip()),
                    )
                else:
                    cur = await db.execute(
                        "SELECT 1 FROM topics WHERE id = ? AND user_tg_id = ?",
                        (topic_id, user_tg_id),
                    )
                    if not await cur.fetchone():
                        return False
                    await db.execute(
                        "INSERT INTO keywords (user_tg_id, word, topic_id) VALUES (?, LOWER(?), ?)",
                        (user_tg_id, word.strip(), topic_id),
                    )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def add_keywords(
        self, user_tg_id: int, words: list[str], topic_id: Optional[int] = None
    ) -> tuple[int, int]:
        async with aiosqlite.connect(self.db_path) as db:
            if topic_id is not None:
                cur = await db.execute(
                    "SELECT 1 FROM topics WHERE id = ? AND user_tg_id = ?",
                    (topic_id, user_tg_id),
                )
                if not await cur.fetchone():
                    return 0, len(words)
            added = 0
            for word in words:
                if topic_id is None:
                    cur = await db.execute(
                        "INSERT OR IGNORE INTO keywords (user_tg_id, word, topic_id) "
                        "VALUES (?, LOWER(?), NULL)",
                        (user_tg_id, word.strip()),
                    )
                else:
                    cur = await db.execute(
                        "INSERT OR IGNORE INTO keywords (user_tg_id, word, topic_id) "
                        "VALUES (?, LOWER(?), ?)",
                        (user_tg_id, word.strip(), topic_id),
                    )
                added += cur.rowcount
            await db.commit()
            return added, len(words) - added

    async def get_keywords(
        self, user_tg_id: int, topic_id: Optional[int] = None
    ) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if topic_id is None:
                cur = await db.execute(
                    "SELECT * FROM keywords WHERE user_tg_id = ? AND topic_id IS NULL ORDER BY word",
                    (user_tg_id,),
                )
            else:
                cur = await db.execute(
                    "SELECT k.* FROM keywords k "
                    "JOIN topics t ON t.id = k.topic_id "
                    "WHERE k.user_tg_id = ? AND k.topic_id = ? AND t.user_tg_id = ? "
                    "ORDER BY k.word",
                    (user_tg_id, topic_id, user_tg_id),
                )
            return [dict(r) for r in await cur.fetchall()]

    async def get_all_active_keywords(self, user_tg_id: int) -> list[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT word FROM keywords WHERE user_tg_id = ? AND is_active = 1",
                (user_tg_id,),
            )
            return [r[0] for r in await cur.fetchall()]

    async def get_active_keywords_for_topic(self, user_tg_id: int, topic_id: int) -> list[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT DISTINCT k.word FROM keywords k "
                "LEFT JOIN topics t ON t.id = k.topic_id "
                "WHERE k.user_tg_id = ? AND k.is_active = 1 "
                "AND (k.topic_id IS NULL OR (k.topic_id = ? AND t.user_tg_id = ?)) "
                "ORDER BY k.word",
                (user_tg_id, topic_id, user_tg_id),
            )
            return [r[0] for r in await cur.fetchall()]

    async def get_monitor_keywords_by_user(self, chat_tg_id: int) -> dict[int, list[str]]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT t.user_tg_id, k.word FROM chats c "
                "JOIN topics t ON t.id = c.topic_id "
                "JOIN bot_users bu ON bu.tg_id = t.user_tg_id AND bu.is_active = 1 "
                "JOIN keywords k ON k.user_tg_id = t.user_tg_id "
                "AND k.is_active = 1 AND (k.topic_id IS NULL OR k.topic_id = t.id) "
                "WHERE c.tg_id = ? AND c.is_active = 1",
                (chat_tg_id,),
            )
            result: dict[int, set[str]] = {}
            for user_tg_id, word in await cur.fetchall():
                result.setdefault(user_tg_id, set()).add(word)
            return {user_tg_id: sorted(words) for user_tg_id, words in result.items()}

    async def toggle_keyword(self, user_tg_id: int, kw_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT is_active FROM keywords WHERE id = ? AND user_tg_id = ?",
                (kw_id, user_tg_id),
            )
            row = await cur.fetchone()
            if not row:
                return False
            new_state = 0 if row[0] else 1
            await db.execute(
                "UPDATE keywords SET is_active = ? WHERE id = ? AND user_tg_id = ?",
                (new_state, kw_id, user_tg_id),
            )
            await db.commit()
            return bool(new_state)

    async def delete_keyword(self, user_tg_id: int, kw_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM keywords WHERE id = ? AND user_tg_id = ?",
                (kw_id, user_tg_id),
            )
            await db.commit()

    async def save_feed_item(
        self,
        user_tg_id: int,
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
                    "INSERT INTO feed (user_tg_id, chat_tg_id, chat_title, message_id, "
                    "message_text, matched_keywords, sender_name, message_url) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_tg_id,
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
        self,
        user_tg_id: int,
        limit: int = 10,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM feed "
                "WHERE user_tg_id = ? AND (? = 0 OR is_read = 0) "
                "ORDER BY received_at DESC LIMIT ? OFFSET ?",
                (user_tg_id, 1 if unread_only else 0, limit, offset),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def get_feed_item(self, user_tg_id: int, item_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM feed WHERE id = ? AND user_tg_id = ?",
                (item_id, user_tg_id),
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def mark_read(self, user_tg_id: int, item_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE feed SET is_read = 1 WHERE id = ? AND user_tg_id = ?",
                (item_id, user_tg_id),
            )
            await db.commit()

    async def mark_all_read(self, user_tg_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE feed SET is_read = 1 WHERE user_tg_id = ?", (user_tg_id,))
            await db.commit()

    async def get_unread_count(self, user_tg_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM feed WHERE user_tg_id = ? AND is_read = 0",
                (user_tg_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_feed_total(self, user_tg_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM feed WHERE user_tg_id = ?", (user_tg_id,))
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_setting(
        self, key: str, default: str = "", user_tg_id: Optional[int] = None
    ) -> str:
        async with aiosqlite.connect(self.db_path) as db:
            if user_tg_id is not None:
                cur = await db.execute(
                    "SELECT value FROM user_settings WHERE user_tg_id = ? AND key = ?",
                    (user_tg_id, key),
                )
                row = await cur.fetchone()
                return row[0] if row else default
            cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cur.fetchone()
            return row[0] if row else default

    async def set_setting(
        self, key: str, value: str, user_tg_id: Optional[int] = None
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            if user_tg_id is None:
                await db.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
            else:
                await db.execute(
                    "INSERT OR REPLACE INTO user_settings (user_tg_id, key, value) "
                    "VALUES (?, ?, ?)",
                    (user_tg_id, key, value),
                )
            await db.commit()
