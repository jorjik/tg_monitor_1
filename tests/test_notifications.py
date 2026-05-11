from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from db.repository import Repository


class NotificationCooldownTest(unittest.IsolatedAsyncioTestCase):
    async def test_notification_cooldown_allows_first_and_blocks_immediate_repeat(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)

            await repo.set_notification_cooldown_minutes(123, 10)

            self.assertTrue(await repo.should_send_notification(123, now=now))
            await repo.mark_notification_sent(123, now=now)
            self.assertFalse(
                await repo.should_send_notification(123, now=now + timedelta(minutes=5))
            )
            self.assertTrue(
                await repo.should_send_notification(123, now=now + timedelta(minutes=11))
            )

    async def test_cooldown_does_not_start_until_notification_is_marked_sent(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)

            await repo.set_notification_cooldown_minutes(123, 10)

            self.assertTrue(await repo.should_send_notification(123, now=now))
            self.assertTrue(
                await repo.should_send_notification(123, now=now + timedelta(minutes=5))
            )

    async def test_zero_notification_cooldown_does_not_throttle(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)

            self.assertTrue(await repo.should_send_notification(123, now=now))
            await repo.mark_notification_sent(123, now=now)
            self.assertTrue(await repo.should_send_notification(123, now=now))


if __name__ == "__main__":
    unittest.main()
