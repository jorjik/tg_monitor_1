from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from bot.handlers.history import _result_summary
from bot.keyboards import main_menu_kb
from db.repository import Repository
from userbot.history import (
    HISTORY_TIMEZONE,
    HistoryScanner,
    find_matches,
    message_url,
    parse_history_interval,
)


class HistoryHelpersTest(unittest.TestCase):
    def test_parses_relative_hours_interval(self):
        now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)

        start, end = parse_history_interval("24ч", now=now)

        self.assertEqual(start, now - timedelta(hours=24))
        self.assertEqual(end, now)

    def test_uses_kyiv_timezone_by_default(self):
        start, end = parse_history_interval("2026-05-01 - 2026-05-02")

        self.assertEqual(start.tzinfo, HISTORY_TIMEZONE)
        self.assertEqual(end.tzinfo, HISTORY_TIMEZONE)

    def test_parses_date_range_as_full_days(self):
        now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)

        start, end = parse_history_interval("2026-05-01 - 2026-05-08", now=now)

        self.assertEqual(start, datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 5, 8, 23, 59, 59, tzinfo=timezone.utc))

    def test_parses_datetime_range(self):
        now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)

        start, end = parse_history_interval(
            "2026-05-01 10:30 - 2026-05-02 11:45", now=now
        )

        self.assertEqual(start, datetime(2026, 5, 1, 10, 30, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 5, 2, 11, 45, tzinfo=timezone.utc))

    def test_rejects_invalid_or_reversed_interval(self):
        now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)

        with self.assertRaises(ValueError):
            parse_history_interval("2026-05-08 - 2026-05-01", now=now)
        with self.assertRaises(ValueError):
            parse_history_interval("abc", now=now)

    def test_finds_case_insensitive_keyword_matches(self):
        self.assertEqual(
            find_matches("Надо чатбот и сайт", ["надо чатбот", "лендинг"]),
            ["надо чатбот"],
        )

    def test_builds_public_and_private_message_urls(self):
        self.assertEqual(
            message_url(123456789, "startup_global", 55),
            "https://t.me/startup_global/55",
        )
        self.assertEqual(
            message_url(-1001234567890, None, 55),
            "https://t.me/c/1234567890/55",
        )
        self.assertEqual(
            message_url(1234567890, None, 55),
            "https://t.me/c/1234567890/55",
        )


class FakeSender:
    username = "sender"


class FakeMessage:
    def __init__(self, message_id, date, text):
        self.id = message_id
        self.date = date
        self.message = text

    async def get_sender(self):
        return FakeSender()


class FakeClient:
    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    async def iter_messages(self, entity_ref, offset_date=None, limit=None):
        self.calls.append((entity_ref, offset_date, limit))
        for message in self.messages[:limit]:
            yield message


class FakeRepo:
    def __init__(self):
        self.saved = []

    async def get_active_keywords_for_topic(self, user_tg_id, topic_id):
        return ["надо сайт"]

    async def save_feed_item(self, **kwargs):
        self.saved.append(kwargs)
        return True


class HistoryScannerTest(unittest.IsolatedAsyncioTestCase):
    async def test_scans_interval_and_saves_keyword_matches(self):
        start = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
        client = FakeClient(
            [
                FakeMessage(3, datetime(2026, 5, 8, 11, 30, tzinfo=timezone.utc), "Надо сайт"),
                FakeMessage(2, datetime(2026, 5, 8, 10, 30, tzinfo=timezone.utc), "мимо"),
                FakeMessage(1, datetime(2026, 5, 8, 9, 59, tzinfo=timezone.utc), "надо сайт"),
            ]
        )
        repo = FakeRepo()

        result = await HistoryScanner(client, repo).scan(
            user_tg_id=123,
            topic_id=5,
            chat={"tg_id": 777, "username": "chatname", "title": "Чат"},
            start=start,
            end=end,
            max_messages=10,
        )

        self.assertEqual(result.scanned, 2)
        self.assertEqual(result.matched, 1)
        self.assertEqual(result.saved, 1)
        self.assertEqual(result.preview[0].url, "https://t.me/chatname/3")
        self.assertEqual(repo.saved[0]["matched_keywords"], ["надо сайт"])
        self.assertEqual(client.calls[0], ("chatname", end, 10))


class HistoryKeyboardTest(unittest.TestCase):
    def test_history_button_is_admin_only_in_main_menu(self):
        admin_buttons = [
            button.text for row in main_menu_kb(is_admin=True).keyboard for button in row
        ]
        user_buttons = [button.text for row in main_menu_kb().keyboard for button in row]

        self.assertIn("🕘 История", admin_buttons)
        self.assertNotIn("🕘 История", user_buttons)


class HistorySummaryTest(unittest.TestCase):
    def test_summary_reports_aggregate_chat_counts(self):
        start = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)

        text = _result_summary(
            start,
            end,
            total_chats=4,
            totals={
                "scanned": 20,
                "matched": 3,
                "saved": 2,
                "keywords": 5,
                "limited_chats": 1,
                "skipped_no_keywords": 1,
                "errors": 1,
            },
            previews=[],
        )

        self.assertIn("Чатов всего:</b> 4", text)
        self.assertIn("Чатов просканировано:</b> 2", text)
        self.assertIn("Пропущено без ключевых слов: 1", text)
        self.assertIn("Уже были в ленте: 1", text)
        self.assertIn("Чатов с ошибкой: 1", text)


class HistoryRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_lists_active_history_chats_with_topic_context(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            user_id = 123
            topic_id = await repo.create_topic(user_id, "бизнес", "бизнес")
            await repo.save_chat(topic_id, 777, "chat", "Chat", "channel", 10)
            chat = (await repo.get_chats(user_id, topic_id))[0]
            await repo.toggle_chat(user_id, chat["id"])
            other_topic_id = await repo.create_topic(user_id, "фриланс", "фриланс")
            await repo.save_chat(other_topic_id, 888, None, "Other", "supergroup", 5)
            alpha_topic_id = await repo.create_topic(user_id, "авто", "авто")
            await repo.save_chat(alpha_topic_id, 889, None, "Alpha", "supergroup", 7)
            other_user_topic_id = await repo.create_topic(999, "чужое", "чужое")
            await repo.save_chat(other_user_topic_id, 999, None, "Foreign", "supergroup", 1)

            chats = await repo.get_history_chats(user_id)

            self.assertEqual([chat["tg_id"] for chat in chats], [889, 888])
            self.assertEqual(chats[0]["topic_id"], alpha_topic_id)
            self.assertEqual(chats[0]["topic_name"], "авто")
            self.assertEqual(chats[0]["is_active"], 1)
            self.assertEqual(chats[1]["topic_id"], other_topic_id)
            self.assertEqual(chats[1]["topic_name"], "фриланс")

    async def test_returns_empty_when_history_chats_are_inactive(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            user_id = 123
            topic_id = await repo.create_topic(user_id, "бизнес", "бизнес")
            await repo.save_chat(topic_id, 777, "chat", "Chat", "channel", 10)
            chat = (await repo.get_chats(user_id, topic_id))[0]
            await repo.toggle_chat(user_id, chat["id"])

            self.assertEqual(await repo.get_history_chats(user_id), [])


if __name__ == "__main__":
    unittest.main()
