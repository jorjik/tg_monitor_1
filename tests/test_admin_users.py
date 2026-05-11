from pathlib import Path
import tempfile
import unittest

import bot.access as access_module
from bot.handlers.admin_users import cmd_admin_users
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
    def __init__(self, user_id=999):
        self.from_user = type("User", (), {"id": user_id})()
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


if __name__ == "__main__":
    unittest.main()
