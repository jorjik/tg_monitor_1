from pathlib import Path
import tempfile
import unittest

import bot.access as access_module
from bot.handlers.admin_users import cmd_admin_users, process_user_search
from db.repository import Repository


class FakeAdminState:
    def __init__(self):
        self.current = None
        self.cleared = False

    async def set_state(self, state):
        self.current = state
        self.cleared = False

    async def clear(self):
        self.current = None
        self.cleared = True


class FakeAdminMessage:
    def __init__(self, user_id=999, text=""):
        self.from_user = type("User", (), {"id": user_id})()
        self.text = text
        self.answers = []

    async def answer(self, text, reply_markup=None, parse_mode=None):
        self.answers.append(
            {"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode}
        )


class AdminUsersRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_counts_and_lists_bot_users_for_admin_screen(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            await repo.upsert_bot_user(111, "alice", "Alice", None)
            await repo.upsert_bot_user(222, None, "Bob", "Smith")

            total = await repo.count_bot_users()
            users = await repo.list_bot_users(limit=10)

            self.assertEqual(total, 2)
            self.assertEqual({user["tg_id"] for user in users}, {111, 222})
            self.assertTrue(all("subscription_status" in user for user in users))

    async def test_lists_bot_users_by_admin_filter(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            await repo.upsert_bot_user(111, "paid", "Paid", None)
            await repo.upsert_bot_user(222, "inactive", "Inactive", None)
            tariff = (await repo.get_tariffs(active_only=True))[0]
            await repo.record_payment(
                user_tg_id=111,
                tariff_id=tariff["id"],
                payload=f"subscription:111:{tariff['id']}:{tariff['stars']}:{tariff['duration_days']}",
                currency="XTR",
                stars=tariff["stars"],
                duration_days=tariff["duration_days"],
                telegram_payment_charge_id="charge-filter",
            )
            await repo.deactivate_bot_user(222)

            paid_users = await repo.list_bot_users(limit=10, status_filter="paid")
            inactive_users = await repo.list_bot_users(limit=10, status_filter="inactive")

            self.assertEqual([user["tg_id"] for user in paid_users], [111])
            self.assertEqual([user["tg_id"] for user in inactive_users], [222])

    async def test_search_bot_user_treats_like_wildcards_as_literal_text(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            await repo.upsert_bot_user(111, "alice", "Alice", None)

            self.assertIsNone(await repo.search_bot_user("%"))
            self.assertEqual((await repo.search_bot_user("alice"))["tg_id"], 111)


class AdminUsersDashboardTest(unittest.IsolatedAsyncioTestCase):
    async def test_users_button_shows_count_list_and_actions_without_search_state(self):
        previous_admin = access_module.ADMIN_USER_ID
        access_module.ADMIN_USER_ID = 999
        try:
            with tempfile.TemporaryDirectory() as td:
                repo = Repository(str(Path(td) / "db.sqlite"))
                await repo.init_db()
                await repo.upsert_bot_user(111, "alice", "Alice", None)
                await repo.upsert_bot_user(222, None, "Bob", "Smith")
                message = FakeAdminMessage()
                state = FakeAdminState()

                await cmd_admin_users(message, state, repo)

                self.assertIsNone(state.current)
                self.assertEqual(len(message.answers), 1)
                answer = message.answers[0]
                self.assertIn("Всего пользователей: <b>2</b>", answer["text"])
                self.assertIn("@alice", answer["text"])
                self.assertIn("Bob Smith", answer["text"])
                buttons = [
                    button.text
                    for row in answer["reply_markup"].inline_keyboard
                    for button in row
                ]
                self.assertEqual(buttons, ["📋 Список пользователей", "🔍 Поиск"])
        finally:
            access_module.ADMIN_USER_ID = previous_admin

    async def test_user_search_escapes_missing_query(self):
        previous_admin = access_module.ADMIN_USER_ID
        access_module.ADMIN_USER_ID = 999
        try:
            with tempfile.TemporaryDirectory() as td:
                repo = Repository(str(Path(td) / "db.sqlite"))
                await repo.init_db()
                message = FakeAdminMessage(text="<b>missing</b>")
                state = FakeAdminState()

                await process_user_search(message, state, repo)

                self.assertIn("&lt;b&gt;missing&lt;/b&gt;", message.answers[0]["text"])
        finally:
            access_module.ADMIN_USER_ID = previous_admin


if __name__ == "__main__":
    unittest.main()
