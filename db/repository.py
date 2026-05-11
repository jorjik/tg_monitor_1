import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite

from core.config import ADMIN_USER_ID

logger = logging.getLogger(__name__)
BILLING_TRIAL_DAYS_KEY = "billing_trial_days"
DEFAULT_TRIAL_DAYS = 7
GEO_FILTER_DEFAULT_MIGRATED_KEY = "geo_filter_empty_default_migrated"
PAYMENT_METHODS = ("kofi", "paypal", "manual")
PAYMENT_METHOD_SETTING_PREFIX = "payment_method_enabled_"
NOTIFICATION_COOLDOWN_KEY = "notification_cooldown_minutes"
NOTIFICATION_LAST_SENT_KEY = "notification_last_sent_at"
KNOWN_SCHEMA_TABLES = frozenset({"chats", "topics", "keywords", "feed", "payments"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _payment_code() -> str:
    return f"KF-{secrets.token_hex(5).upper()}"



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
    access_hash TEXT,
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
    referred_by INTEGER REFERENCES bot_users(tg_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tariffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    stars INTEGER NOT NULL CHECK(stars >= 1),
    duration_days INTEGER NOT NULL CHECK(duration_days >= 1),
    is_active INTEGER DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS user_subscriptions (
    user_tg_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    tariff_id INTEGER REFERENCES tariffs(id),
    trial_started_at TIMESTAMP,
    started_at TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_tg_id INTEGER NOT NULL,
    tariff_id INTEGER NOT NULL REFERENCES tariffs(id),
    payload TEXT NOT NULL,
    currency TEXT NOT NULL,
    stars INTEGER NOT NULL CHECK(stars >= 1),
    duration_days INTEGER NOT NULL CHECK(duration_days >= 1),
    telegram_payment_charge_id TEXT NOT NULL UNIQUE,
    provider_payment_charge_id TEXT,
    paid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payment_intents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    user_tg_id INTEGER NOT NULL,
    tariff_id INTEGER NOT NULL REFERENCES tariffs(id),
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    duration_days INTEGER NOT NULL CHECK(duration_days >= 1),
    status TEXT NOT NULL DEFAULT 'pending',
    provider_payment_id TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    paid_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS kofi_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_payment_id TEXT NOT NULL UNIQUE,
    intent_id INTEGER REFERENCES payment_intents(id),
    user_tg_id INTEGER,
    tariff_id INTEGER,
    code TEXT,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    raw_payload TEXT NOT NULL,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS paypal_payments (
    order_id TEXT PRIMARY KEY,
    user_tg_id INTEGER NOT NULL,
    tariff_id INTEGER NOT NULL REFERENCES tariffs(id),
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    captured_at TIMESTAMP
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

            # Migration: referred_by
            try:
                await db.execute("ALTER TABLE bot_users ADD COLUMN referred_by INTEGER REFERENCES bot_users(tg_id)")
                await db.commit()
            except aiosqlite.OperationalError:
                pass

            await self._migrate_topics(db)
            await self._migrate_chats(db)
            await self._migrate_keywords(db)
            await self._migrate_feed(db)
            await self._migrate_settings(db)
            await self._migrate_geo_filter_default(db)
            await self._seed_billing_defaults(db)
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

    async def _seed_billing_defaults(self, db) -> None:
        await self._migrate_billing(db)
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (BILLING_TRIAL_DAYS_KEY, str(DEFAULT_TRIAL_DAYS)),
        )
        for method in PAYMENT_METHODS:
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (f"{PAYMENT_METHOD_SETTING_PREFIX}{method}", "1"),
            )
        cur = await db.execute("SELECT COUNT(*) FROM tariffs")
        row = await cur.fetchone()
        if row and row[0] == 0:
            await db.execute(
                "INSERT INTO tariffs (name, stars, duration_days, is_active) VALUES (?, ?, ?, 1)",
                ("Месячный доступ", 100, 30),
            )

    async def _migrate_billing(self, db) -> None:
        payment_columns = await self._columns(db, "payments")
        if "duration_days" not in payment_columns:
            await db.execute(
                "ALTER TABLE payments ADD COLUMN duration_days INTEGER NOT NULL DEFAULT 30"
            )

    async def _columns(self, db, table: str) -> set[str]:
        if table not in KNOWN_SCHEMA_TABLES:
            raise ValueError(f"Unknown schema table: {table}")
        # SQLite PRAGMA table names cannot be parameterized; the allowlist above
        # keeps this f-string constrained to known internal table names.
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

    async def _migrate_chats(self, db) -> None:
        chat_columns = await self._columns(db, "chats")
        if "access_hash" not in chat_columns:
            await db.execute("ALTER TABLE chats ADD COLUMN access_hash TEXT")
            await db.commit()

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

    async def _migrate_geo_filter_default(self, db) -> None:
        cur = await db.execute(
            "SELECT value FROM settings WHERE key = ?",
            (GEO_FILTER_DEFAULT_MIGRATED_KEY,),
        )
        if await cur.fetchone():
            return
        from userbot.collector import GEO_EXCLUDE_DEFAULT

        await db.execute(
            "INSERT OR IGNORE INTO user_settings (user_tg_id, key, value) "
            "SELECT tg_id, ?, ? FROM bot_users",
            ("geo_exclude", GEO_EXCLUDE_DEFAULT),
        )
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (GEO_FILTER_DEFAULT_MIGRATED_KEY, "1"),
        )

    async def upsert_bot_user(
        self,
        tg_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
        referred_by: Optional[int] = None,
    ) -> bool:
        """Returns True if user was newly created."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT tg_id FROM bot_users WHERE tg_id = ?", (tg_id,)) as cursor:
                exists = await cursor.fetchone() is not None

            if not exists:
                await db.execute(
                    "INSERT INTO bot_users (tg_id, username, first_name, last_name, referred_by, is_active) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (tg_id, username, first_name, last_name, referred_by),
                )
            else:
                await db.execute(
                    "UPDATE bot_users SET username = ?, first_name = ?, last_name = ?, is_active = 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE tg_id = ?",
                    (username, first_name, last_name, tg_id),
                )
            await db.commit()
            return not exists

    async def apply_referral_bonus(self, user_tg_id: int, referrer_tg_id: int, days: int = 14) -> bool:
        """Apply bonus days to both users."""
        await self.add_subscription_days(user_tg_id, days)
        await self.add_subscription_days(referrer_tg_id, days)
        return True

    async def add_subscription_days(self, user_tg_id: int, days: int) -> None:
        if days <= 0:
            return
        async with aiosqlite.connect(self.db_path) as db:
            now = _utc_now()
            # Ensure subscription record exists
            await db.execute(
                "INSERT OR IGNORE INTO user_subscriptions (user_tg_id, status, expires_at) VALUES (?, ?, ?)",
                (user_tg_id, "trial", _format_ts(now))
            )
            await db.execute(
                """
                UPDATE user_subscriptions
                SET expires_at = datetime(
                    CASE WHEN expires_at > CURRENT_TIMESTAMP THEN expires_at ELSE CURRENT_TIMESTAMP END,
                    '+' || ? || ' days'
                )
                WHERE user_tg_id = ?
                """,
                (days, user_tg_id),
            )
            await db.commit()

    async def get_referral_stats(self, user_tg_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM bot_users WHERE referred_by = ?", (user_tg_id,)
            ) as cursor:
                count = (await cursor.fetchone())[0]
                return {"count": count}

    async def deactivate_bot_user(self, tg_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE bot_users SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE tg_id = ?",
                (tg_id,),
            )
            await db.commit()

    async def get_bot_user(self, tg_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM bot_users WHERE tg_id = ?", (tg_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    def _bot_user_filter_clause(self, status_filter: str = "all") -> tuple[str, tuple]:
        filters = {
            "all": ("", ()),
            "active": ("WHERE bu.is_active = 1", ()),
            "inactive": ("WHERE bu.is_active = 0", ()),
            "paid": ("WHERE us.status = 'paid'", ()),
            "trial": ("WHERE us.status = 'trial'", ()),
            "none": ("WHERE us.status IS NULL", ()),
        }
        return filters.get(status_filter, filters["all"])

    async def count_bot_users(self, status_filter: str = "all") -> int:
        async with aiosqlite.connect(self.db_path) as db:
            where, params = self._bot_user_filter_clause(status_filter)
            cur = await db.execute(
                "SELECT COUNT(*) FROM bot_users bu "
                "LEFT JOIN user_subscriptions us ON us.user_tg_id = bu.tg_id "
                f"{where}",
                params,
            )
            row = await cur.fetchone()
            return row[0] if row else 0

    async def count_active_bot_users(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM bot_users WHERE is_active = 1")
            row = await cur.fetchone()
            return row[0] if row else 0

    async def list_bot_users(
        self, limit: int = 10, offset: int = 0, status_filter: str = "all"
    ) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            where, params = self._bot_user_filter_clause(status_filter)
            cur = await db.execute(
                f"""
                SELECT bu.*,
                       COALESCE(us.status, 'none') AS subscription_status,
                       us.expires_at AS subscription_expires_at
                FROM bot_users bu
                LEFT JOIN user_subscriptions us ON us.user_tg_id = bu.tg_id
                {where}
                ORDER BY datetime(bu.updated_at) DESC, datetime(bu.created_at) DESC, bu.tg_id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            )
            users = [dict(r) for r in await cur.fetchall()]
            for user in users:
                expires_at = _parse_ts(user.get("subscription_expires_at"))
                user["subscription_is_active"] = bool(expires_at and expires_at > _utc_now())
            return users

    async def count_chats(self, active_only: bool = False) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM chats WHERE (? = 0 OR is_active = 1)",
                (1 if active_only else 0,),
            )
            row = await cur.fetchone()
            return row[0] if row else 0

    async def count_keywords(self, active_only: bool = False) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM keywords WHERE (? = 0 OR is_active = 1)",
                (1 if active_only else 0,),
            )
            row = await cur.fetchone()
            return row[0] if row else 0

    async def count_feed_since(self, since: datetime) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM feed WHERE received_at >= ?",
                (_format_ts(since),),
            )
            row = await cur.fetchone()
            return row[0] if row else 0

    async def search_bot_user(self, query: str) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            safe_query = _escape_like(query)
            # Search by username or First/Last name; escape LIKE wildcards so
            # operator searches for literal text rather than patterns.
            async with db.execute(
                """
                SELECT * FROM bot_users
                WHERE username LIKE ? ESCAPE '\\'
                OR (COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) LIKE ? ESCAPE '\\'
                LIMIT 1
                """,
                (f"%{safe_query}%", f"%{safe_query}%"),
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

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
        access_hash: Optional[int | str] = None,
    ) -> None:
        access_hash_value = str(access_hash) if access_hash is not None else None
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO chats "
                "(topic_id, tg_id, username, access_hash, title, chat_type, members_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(topic_id, tg_id) DO UPDATE SET "
                "username = excluded.username, "
                "access_hash = COALESCE(excluded.access_hash, chats.access_hash), "
                "title = excluded.title, "
                "chat_type = excluded.chat_type, "
                "members_count = excluded.members_count",
                (
                    topic_id,
                    tg_id,
                    username,
                    access_hash_value,
                    title,
                    chat_type,
                    members_count,
                ),
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

    async def get_history_chats(self, user_tg_id: int) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT c.id, c.topic_id, c.tg_id, c.username, c.access_hash, c.title, "
                "c.chat_type, c.members_count, c.is_active, c.added_at, "
                "t.name as topic_name FROM chats c "
                "JOIN topics t ON t.id = c.topic_id "
                "WHERE c.is_active = 1 AND t.user_tg_id = ? "
                "ORDER BY t.name, c.title",
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
                "LEFT JOIN user_subscriptions us ON us.user_tg_id = t.user_tg_id "
                "JOIN keywords k ON k.user_tg_id = t.user_tg_id "
                "AND k.is_active = 1 AND (k.topic_id IS NULL OR k.topic_id = t.id) "
                "WHERE c.tg_id = ? AND c.is_active = 1 "
                "AND (t.user_tg_id = ? OR us.expires_at > CURRENT_TIMESTAMP)",
                (chat_tg_id, ADMIN_USER_ID),
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

    async def get_notification_cooldown_minutes(self, user_tg_id: int) -> int:
        raw = await self.get_setting(
            NOTIFICATION_COOLDOWN_KEY, "0", user_tg_id=user_tg_id
        )
        try:
            return max(0, int(raw))
        except ValueError:
            return 0

    async def set_notification_cooldown_minutes(self, user_tg_id: int, minutes: int) -> None:
        await self.set_setting(
            NOTIFICATION_COOLDOWN_KEY, str(max(0, minutes)), user_tg_id=user_tg_id
        )

    async def should_send_notification(
        self, user_tg_id: int, now: Optional[datetime] = None
    ) -> bool:
        cooldown = await self.get_notification_cooldown_minutes(user_tg_id)
        if cooldown <= 0:
            return True
        current = (now or _utc_now()).astimezone(timezone.utc).replace(microsecond=0)
        last_raw = await self.get_setting(
            NOTIFICATION_LAST_SENT_KEY, "", user_tg_id=user_tg_id
        )
        last_sent = _parse_ts(last_raw)
        if last_sent and current - last_sent < timedelta(minutes=cooldown):
            return False
        return True

    async def mark_notification_sent(
        self, user_tg_id: int, now: Optional[datetime] = None
    ) -> None:
        current = (now or _utc_now()).astimezone(timezone.utc).replace(microsecond=0)
        await self.set_setting(
            NOTIFICATION_LAST_SENT_KEY, _format_ts(current), user_tg_id=user_tg_id
        )

    async def get_trial_days(self) -> int:
        raw = await self.get_setting(BILLING_TRIAL_DAYS_KEY, str(DEFAULT_TRIAL_DAYS))
        try:
            days = int(raw)
        except ValueError:
            return DEFAULT_TRIAL_DAYS
        return max(0, days)

    async def set_trial_days(self, days: int) -> None:
        await self.set_setting(BILLING_TRIAL_DAYS_KEY, str(max(0, days)))

    async def ensure_trial(self, user_tg_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM user_subscriptions WHERE user_tg_id = ?",
                (user_tg_id,),
            )
            row = await cur.fetchone()
            if row:
                return self._subscription_access(dict(row))
            now = _utc_now()
            expires_at = now + timedelta(days=await self.get_trial_days())
            await db.execute(
                "INSERT OR IGNORE INTO user_subscriptions "
                "(user_tg_id, status, trial_started_at, expires_at) VALUES (?, ?, ?, ?)",
                (user_tg_id, "trial", _format_ts(now), _format_ts(expires_at)),
            )
            await db.commit()
            cur = await db.execute(
                "SELECT * FROM user_subscriptions WHERE user_tg_id = ?",
                (user_tg_id,),
            )
            row = await cur.fetchone()
            if not row:
                return {"status": "none", "expires_at": None, "is_active": False}
            return self._subscription_access(dict(row))

    async def get_subscription_access(self, user_tg_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM user_subscriptions WHERE user_tg_id = ?",
                (user_tg_id,),
            )
            row = await cur.fetchone()
            if not row:
                return {"status": "none", "expires_at": None, "is_active": False}
            return self._subscription_access(dict(row))

    def _subscription_access(self, subscription: dict) -> dict:
        expires_at = _parse_ts(subscription.get("expires_at"))
        is_active = bool(expires_at and expires_at > _utc_now())
        result = dict(subscription)
        result["is_active"] = is_active
        return result

    async def get_tariffs(self, active_only: bool = False) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if active_only:
                cur = await db.execute(
                    "SELECT * FROM tariffs WHERE is_active = 1 ORDER BY stars, duration_days, id"
                )
            else:
                cur = await db.execute("SELECT * FROM tariffs ORDER BY is_active DESC, stars, id")
            return [dict(r) for r in await cur.fetchall()]

    async def get_tariff(self, tariff_id: int, active_only: bool = False) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if active_only:
                cur = await db.execute(
                    "SELECT * FROM tariffs WHERE id = ? AND is_active = 1",
                    (tariff_id,),
                )
            else:
                cur = await db.execute("SELECT * FROM tariffs WHERE id = ?", (tariff_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def create_tariff(self, name: str, stars: int, duration_days: int) -> int:
        name = name.strip()
        if len(name) < 2:
            raise ValueError("Tariff name is too short")
        if stars <= 0:
            raise ValueError("Tariff price must be positive")
        if duration_days <= 0:
            raise ValueError("Tariff duration must be positive")
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO tariffs (name, stars, duration_days, is_active) VALUES (?, ?, ?, 1)",
                (name, stars, duration_days),
            )
            await db.commit()
            return cur.lastrowid

    async def update_tariff(self, tariff_id: int, **fields) -> bool:
        allowed = {"name", "stars", "duration_days"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return False
        if "name" in updates:
            updates["name"] = str(updates["name"]).strip()
            if len(updates["name"]) < 2:
                raise ValueError("Tariff name is too short")
        if "stars" in updates and int(updates["stars"]) <= 0:
            raise ValueError("Tariff price must be positive")
        if "duration_days" in updates and int(updates["duration_days"]) <= 0:
            raise ValueError("Tariff duration must be positive")
        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [tariff_id]
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                f"UPDATE tariffs SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values,
            )
            await db.commit()
            return cur.rowcount > 0

    async def set_tariff_active(self, tariff_id: int, is_active: bool) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "UPDATE tariffs SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (1 if is_active else 0, tariff_id),
            )
            await db.commit()
            return cur.rowcount > 0

    async def create_kofi_payment_intent(
        self,
        user_tg_id: int,
        tariff_id: int,
        amount: str,
        currency: str,
        duration_days: int,
        code: Optional[str] = None,
    ) -> Optional[dict]:
        amount = amount.strip()
        currency = currency.strip().upper()
        if not amount or not currency or duration_days <= 0:
            raise ValueError("Invalid Ko-fi payment intent")
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM tariffs WHERE id = ? AND is_active = 1",
                (tariff_id,),
            )
            if not await cur.fetchone():
                return None
            for _ in range(8):
                intent_code = (code or _payment_code()).strip().upper()
                try:
                    cur = await db.execute(
                        "INSERT INTO payment_intents "
                        "(provider, code, user_tg_id, tariff_id, amount, currency, duration_days) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            "kofi",
                            intent_code,
                            user_tg_id,
                            tariff_id,
                            amount,
                            currency,
                            duration_days,
                        ),
                    )
                except aiosqlite.IntegrityError:
                    if code:
                        raise
                    continue
                await db.commit()
                cur = await db.execute(
                    "SELECT * FROM payment_intents WHERE id = ?",
                    (cur.lastrowid,),
                )
                row = await cur.fetchone()
                return dict(row) if row else None
        raise RuntimeError("Unable to create unique Ko-fi payment code")

    async def record_kofi_payment(
        self,
        provider_payment_id: str,
        code: Optional[str],
        amount: str,
        currency: str,
        raw_payload: str,
    ) -> dict:
        provider_payment_id = provider_payment_id.strip()
        code = code.strip().upper() if code else None
        amount = amount.strip()
        currency = currency.strip().upper()
        if not provider_payment_id or not amount or not currency:
            raise ValueError("Invalid Ko-fi payment")
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            duplicate = await self._kofi_payment_result(db, provider_payment_id)
            if duplicate:
                return duplicate

            intent = None
            status = "manual_review"
            reason = "code_missing"
            if code:
                cur = await db.execute(
                    "SELECT * FROM payment_intents WHERE provider = ? AND code = ?",
                    ("kofi", code),
                )
                intent = await cur.fetchone()
                if not intent:
                    reason = "intent_not_found"
                elif intent["status"] != "pending":
                    reason = "intent_not_pending"
                elif intent["amount"] != amount or intent["currency"].upper() != currency:
                    reason = "amount_or_currency_mismatch"
                else:
                    status = "paid"
                    reason = None

            intent_id = intent["id"] if intent else None
            user_tg_id = intent["user_tg_id"] if intent else None
            tariff_id = intent["tariff_id"] if intent else None
            duration_days = intent["duration_days"] if intent else None
            try:
                await db.execute(
                    "INSERT INTO kofi_payments "
                    "(provider_payment_id, intent_id, user_tg_id, tariff_id, code, amount, "
                    "currency, status, reason, raw_payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        provider_payment_id,
                        intent_id,
                        user_tg_id,
                        tariff_id,
                        code,
                        amount,
                        currency,
                        status,
                        reason,
                        raw_payload,
                    ),
                )
            except aiosqlite.IntegrityError:
                duplicate = await self._kofi_payment_result(db, provider_payment_id)
                if duplicate:
                    return duplicate
                raise

            if status != "paid":
                await db.commit()
                return {
                    "status": status,
                    "reason": reason,
                    "inserted": True,
                    "expires_at": None,
                    "user_tg_id": user_tg_id,
                    "tariff_id": tariff_id,
                }

            cur = await db.execute(
                "UPDATE payment_intents SET status = ?, provider_payment_id = ?, "
                "paid_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = ?",
                ("paid", provider_payment_id, intent_id, "pending"),
            )
            if cur.rowcount == 0:
                await db.execute(
                    "UPDATE kofi_payments SET status = ?, reason = ? WHERE provider_payment_id = ?",
                    ("manual_review", "intent_not_pending", provider_payment_id),
                )
                await db.commit()
                return {
                    "status": "manual_review",
                    "reason": "intent_not_pending",
                    "inserted": True,
                    "expires_at": None,
                    "user_tg_id": user_tg_id,
                    "tariff_id": tariff_id,
                }

            await db.execute(
                "INSERT INTO user_subscriptions "
                "(user_tg_id, status, tariff_id, started_at, expires_at, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP, datetime(CURRENT_TIMESTAMP, '+' || ? || ' days'), CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_tg_id) DO UPDATE SET "
                "status = excluded.status, "
                "tariff_id = excluded.tariff_id, "
                "started_at = CASE "
                "WHEN user_subscriptions.status = 'paid' "
                "AND user_subscriptions.started_at IS NOT NULL "
                "THEN user_subscriptions.started_at ELSE excluded.started_at END, "
                "expires_at = datetime("
                "CASE WHEN user_subscriptions.expires_at > CURRENT_TIMESTAMP "
                "THEN user_subscriptions.expires_at ELSE CURRENT_TIMESTAMP END, "
                "'+' || ? || ' days'), "
                "updated_at = CURRENT_TIMESTAMP",
                (user_tg_id, "paid", tariff_id, duration_days, duration_days),
            )
            cur = await db.execute(
                "SELECT expires_at FROM user_subscriptions WHERE user_tg_id = ?",
                (user_tg_id,),
            )
            row = await cur.fetchone()
            await db.commit()
            return {
                "status": "paid",
                "reason": None,
                "inserted": True,
                "expires_at": row["expires_at"] if row else None,
                "user_tg_id": user_tg_id,
                "tariff_id": tariff_id,
            }

    async def _kofi_payment_result(self, db, provider_payment_id: str) -> Optional[dict]:
        cur = await db.execute(
            "SELECT kp.*, us.expires_at FROM kofi_payments kp "
            "LEFT JOIN user_subscriptions us ON us.user_tg_id = kp.user_tg_id "
            "WHERE kp.provider_payment_id = ?",
            (provider_payment_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        payment = dict(row)
        return {
            "status": payment["status"],
            "reason": payment.get("reason"),
            "inserted": False,
            "expires_at": payment.get("expires_at"),
            "user_tg_id": payment.get("user_tg_id"),
            "tariff_id": payment.get("tariff_id"),
        }

    async def list_kofi_manual_review_payments(self, limit: int = 10) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT kp.*, bu.username, bu.first_name, bu.last_name, t.name AS tariff_name "
                "FROM kofi_payments kp "
                "LEFT JOIN bot_users bu ON bu.tg_id = kp.user_tg_id "
                "LEFT JOIN tariffs t ON t.id = kp.tariff_id "
                "WHERE kp.status = 'manual_review' "
                "ORDER BY datetime(kp.received_at) DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in await cur.fetchall()]

    async def get_kofi_payment_review(self, payment_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT kp.*, bu.username, bu.first_name, bu.last_name, t.name AS tariff_name, "
                "t.duration_days AS tariff_duration_days "
                "FROM kofi_payments kp "
                "LEFT JOIN bot_users bu ON bu.tg_id = kp.user_tg_id "
                "LEFT JOIN tariffs t ON t.id = kp.tariff_id "
                "WHERE kp.id = ?",
                (payment_id,),
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def resolve_kofi_manual_review_payment(self, payment_id: int, action: str) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM kofi_payments WHERE id = ?", (payment_id,))
            payment = await cur.fetchone()
            if not payment:
                return {"status": "error", "reason": "not_found"}
            if payment["status"] != "manual_review":
                return {"status": "error", "reason": "not_manual_review"}
            if action == "reject":
                await db.execute(
                    "UPDATE kofi_payments SET status = ?, reason = ? WHERE id = ?",
                    ("rejected", "manual_rejected", payment_id),
                )
                await db.commit()
                return {"status": "rejected", "user_tg_id": payment["user_tg_id"]}
            if action != "approve":
                return {"status": "error", "reason": "unknown_action"}
            if not payment["user_tg_id"] or not payment["tariff_id"]:
                return {"status": "error", "reason": "user_or_tariff_missing"}
            tariff = await (
                await db.execute("SELECT * FROM tariffs WHERE id = ?", (payment["tariff_id"],))
            ).fetchone()
            if not tariff:
                return {"status": "error", "reason": "tariff_not_found"}
            await db.execute(
                "UPDATE kofi_payments SET status = ?, reason = NULL WHERE id = ?",
                ("paid_manual", payment_id),
            )
            if payment["intent_id"]:
                await db.execute(
                    "UPDATE payment_intents SET status = ?, provider_payment_id = ?, "
                    "paid_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND status = ?",
                    (
                        "paid_manual",
                        payment["provider_payment_id"],
                        payment["intent_id"],
                        "pending",
                    ),
                )
            await db.execute(
                "INSERT INTO user_subscriptions "
                "(user_tg_id, status, tariff_id, started_at, expires_at, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP, datetime(CURRENT_TIMESTAMP, '+' || ? || ' days'), CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_tg_id) DO UPDATE SET "
                "status = excluded.status, "
                "tariff_id = excluded.tariff_id, "
                "started_at = CASE "
                "WHEN user_subscriptions.status = 'paid' "
                "AND user_subscriptions.started_at IS NOT NULL "
                "THEN user_subscriptions.started_at ELSE excluded.started_at END, "
                "expires_at = datetime("
                "CASE WHEN user_subscriptions.expires_at > CURRENT_TIMESTAMP "
                "THEN user_subscriptions.expires_at ELSE CURRENT_TIMESTAMP END, "
                "'+' || ? || ' days'), "
                "updated_at = CURRENT_TIMESTAMP",
                (
                    payment["user_tg_id"],
                    "paid",
                    payment["tariff_id"],
                    tariff["duration_days"],
                    tariff["duration_days"],
                ),
            )
            cur = await db.execute(
                "SELECT expires_at FROM user_subscriptions WHERE user_tg_id = ?",
                (payment["user_tg_id"],),
            )
            row = await cur.fetchone()
            await db.commit()
            return {
                "status": "approved",
                "user_tg_id": payment["user_tg_id"],
                "expires_at": row["expires_at"] if row else None,
            }

    async def record_payment(
        self,
        user_tg_id: int,
        tariff_id: int,
        payload: str,
        currency: str,
        stars: int,
        duration_days: int,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str = "",
    ) -> tuple[Optional[str], bool]:
        if currency != "XTR" or stars <= 0 or duration_days <= 0:
            return None, False
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM tariffs WHERE id = ?", (tariff_id,))
            tariff = await cur.fetchone()
            if not tariff:
                return None, False
            inserted = True
            try:
                await db.execute(
                    "INSERT INTO payments "
                    "(user_tg_id, tariff_id, payload, currency, stars, duration_days, "
                    "telegram_payment_charge_id, provider_payment_charge_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_tg_id,
                        tariff_id,
                        payload,
                        currency,
                        stars,
                        duration_days,
                        telegram_payment_charge_id,
                        provider_payment_charge_id,
                    ),
                )
            except aiosqlite.IntegrityError:
                cur = await db.execute(
                    "SELECT 1 FROM payments WHERE telegram_payment_charge_id = ?",
                    (telegram_payment_charge_id,),
                )
                if not await cur.fetchone():
                    raise
                inserted = False

            cur = await db.execute(
                "SELECT * FROM user_subscriptions WHERE user_tg_id = ?",
                (user_tg_id,),
            )
            subscription = await cur.fetchone()
            if inserted:
                await db.execute(
                    "INSERT INTO user_subscriptions "
                    "(user_tg_id, status, tariff_id, started_at, expires_at, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP, datetime(CURRENT_TIMESTAMP, '+' || ? || ' days'), CURRENT_TIMESTAMP) "
                    "ON CONFLICT(user_tg_id) DO UPDATE SET "
                    "status = excluded.status, "
                    "tariff_id = excluded.tariff_id, "
                    "started_at = CASE "
                    "WHEN user_subscriptions.status = 'paid' "
                    "AND user_subscriptions.started_at IS NOT NULL "
                    "THEN user_subscriptions.started_at ELSE excluded.started_at END, "
                    "expires_at = datetime("
                    "CASE WHEN user_subscriptions.expires_at > CURRENT_TIMESTAMP "
                    "THEN user_subscriptions.expires_at ELSE CURRENT_TIMESTAMP END, "
                    "'+' || ? || ' days'), "
                    "updated_at = CURRENT_TIMESTAMP",
                    (user_tg_id, "paid", tariff_id, duration_days, duration_days),
                )
                cur = await db.execute(
                    "SELECT expires_at FROM user_subscriptions WHERE user_tg_id = ?",
                    (user_tg_id,),
                )
                row = await cur.fetchone()
                await db.commit()
                return row["expires_at"], True

            await db.commit()
            if subscription:
                return subscription["expires_at"], False
            return None, False

    async def get_payment_methods(self) -> dict[str, bool]:
        keys = [f"{PAYMENT_METHOD_SETTING_PREFIX}{method}" for method in PAYMENT_METHODS]
        placeholders = ",".join("?" for _ in keys)
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                f"SELECT key, value FROM settings WHERE key IN ({placeholders})",
                keys,
            )
            values = dict(await cur.fetchall())
        return {
            method: values.get(f"{PAYMENT_METHOD_SETTING_PREFIX}{method}", "1") == "1"
            for method in PAYMENT_METHODS
        }

    async def is_payment_method_enabled(self, method: str) -> bool:
        if method not in PAYMENT_METHODS:
            raise ValueError("Unknown payment method")
        methods = await self.get_payment_methods()
        return methods[method]

    async def set_payment_method_enabled(self, method: str, enabled: bool) -> None:
        if method not in PAYMENT_METHODS:
            raise ValueError("Unknown payment method")
        await self.set_setting(
            f"{PAYMENT_METHOD_SETTING_PREFIX}{method}",
            "1" if enabled else "0",
        )

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
    async def create_paypal_payment(
        self, order_id: str, user_tg_id: int, tariff_id: int, amount: str, currency: str
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO paypal_payments (order_id, user_tg_id, tariff_id, amount, currency, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (order_id, user_tg_id, tariff_id, amount, currency, "created"),
            )
            await db.commit()

    async def get_paypal_payment(self, order_id: str) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM paypal_payments WHERE order_id = ?", (order_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def record_paypal_payment(self, order_id: str, status: str) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            payment = await (await db.execute(
                "SELECT * FROM paypal_payments WHERE order_id = ?", (order_id,)
            )).fetchone()

            if not payment:
                return {"status": "error", "reason": "not_found"}

            if payment["status"] == "COMPLETED":
                return {"status": "already_paid"}

            if status != "COMPLETED":
                await db.execute(
                    "UPDATE paypal_payments SET status = ? WHERE order_id = ?",
                    (status, order_id)
                )
                await db.commit()
                return {"status": status}

            # PayPal payments are tracked in paypal_payments; extend access directly
            # because record_payment is limited to Telegram Stars (XTR).
            tariff = await (await db.execute(
                "SELECT * FROM tariffs WHERE id = ?", (payment["tariff_id"],)
            )).fetchone()

            if not tariff:
                return {"status": "error", "reason": "tariff_not_found"}

            now = datetime.now(timezone.utc)
            await db.execute(
                """
                UPDATE paypal_payments
                SET status = 'COMPLETED', captured_at = ?
                WHERE order_id = ?
                """,
                (_format_ts(now), order_id),
            )

            await db.execute(
                "INSERT INTO user_subscriptions "
                "(user_tg_id, status, tariff_id, started_at, expires_at, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP, datetime(CURRENT_TIMESTAMP, '+' || ? || ' days'), CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_tg_id) DO UPDATE SET "
                "status = excluded.status, "
                "tariff_id = excluded.tariff_id, "
                "started_at = CASE "
                "WHEN user_subscriptions.status = 'paid' "
                "AND user_subscriptions.started_at IS NOT NULL "
                "THEN user_subscriptions.started_at ELSE excluded.started_at END, "
                "expires_at = datetime("
                "CASE WHEN user_subscriptions.expires_at > CURRENT_TIMESTAMP "
                "THEN user_subscriptions.expires_at ELSE CURRENT_TIMESTAMP END, "
                "'+' || ? || ' days'), "
                "updated_at = CURRENT_TIMESTAMP",
                (
                    payment["user_tg_id"],
                    "paid",
                    payment["tariff_id"],
                    tariff["duration_days"],
                    tariff["duration_days"],
                ),
            )
            cur = await db.execute(
                "SELECT expires_at FROM user_subscriptions WHERE user_tg_id = ?",
                (payment["user_tg_id"],),
            )
            row = await cur.fetchone()

            await db.commit()
            return {
                "status": "COMPLETED",
                "user_tg_id": payment["user_tg_id"],
                "expires_at": row["expires_at"] if row else None,
                "inserted": True
            }
