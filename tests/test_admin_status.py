from datetime import datetime, timedelta, timezone
import unittest

from bot.handlers.monitor import _admin_status_text


class FakeStatusRepo:
    async def count_bot_users(self):
        return 10

    async def count_active_bot_users(self):
        return 7

    async def count_chats(self, active_only=False):
        return 15 if active_only else 20

    async def count_keywords(self, active_only=False):
        return 8 if active_only else 12

    async def count_feed_since(self, since):
        return 5


class FakeWatcher:
    is_running = True


class FakeCollector:
    class Client:
        def is_connected(self):
            return True

    client = Client()


class AdminStatusTest(unittest.IsolatedAsyncioTestCase):
    async def test_admin_status_shows_operational_counts(self):
        text = await _admin_status_text(
            FakeStatusRepo(),
            FakeWatcher(),
            FakeCollector(),
            datetime.now(timezone.utc) - timedelta(hours=2),
        )

        self.assertIn("Пользователей: <b>10</b>", text)
        self.assertIn("Активных пользователей: <b>7</b>", text)
        self.assertIn("Watcher: 🟢", text)
        self.assertIn("Telethon: 🟢", text)
        self.assertIn("Совпадений за 24ч: <b>5</b>", text)


if __name__ == "__main__":
    unittest.main()
