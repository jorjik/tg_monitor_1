from pathlib import Path
import tempfile
import unittest

from bot.handlers.geo_filter import _get_words
from bot.keyboards import geo_filter_kb
from db.repository import Repository
from userbot.collector import GEO_EXCLUDE_DEFAULT


class GeoFilterDefaultsTest(unittest.IsolatedAsyncioTestCase):
    async def test_geo_filter_is_empty_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()

            self.assertEqual(await _get_words(repo, 123), [])

    async def test_rf_geo_preset_can_be_saved_and_reset_to_empty(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(str(Path(td) / "db.sqlite"))
            await repo.init_db()
            user_id = 123

            await repo.set_setting("geo_exclude", GEO_EXCLUDE_DEFAULT, user_tg_id=user_id)
            self.assertIn("россия", await _get_words(repo, user_id))

            await repo.set_setting("geo_exclude", "", user_tg_id=user_id)
            self.assertEqual(await _get_words(repo, user_id), [])


class GeoFilterKeyboardTest(unittest.TestCase):
    def test_geo_filter_keyboard_has_rf_preset_and_clear_all(self):
        buttons = [
            button
            for row in geo_filter_kb([]).inline_keyboard
            for button in row
        ]

        self.assertIn("🚫 Убрать Гео РФ", [button.text for button in buttons])
        self.assertIn("🧹 Сбросить всё", [button.text for button in buttons])
        self.assertIn("geo_rf", [button.callback_data for button in buttons])
        self.assertIn("geo_reset", [button.callback_data for button in buttons])


if __name__ == "__main__":
    unittest.main()
