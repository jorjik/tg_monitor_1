import unittest

from bot.keyboards import keywords_kb, minus_words_kb


class KeywordsKeyboardTest(unittest.TestCase):
    def test_global_keywords_keyboard_has_minus_words_item_under_add(self):
        rows = [
            [(button.text, button.callback_data) for button in row]
            for row in keywords_kb([], topic_id=None).inline_keyboard
        ]

        self.assertEqual(rows[0], [("➕ Добавить", "add_kw:global")])
        self.assertEqual(rows[1], [("➖ Минус-слова", "minus_words:global")])

    def test_topic_keywords_keyboard_has_topic_scoped_minus_words_item(self):
        rows = [
            [(button.text, button.callback_data) for button in row]
            for row in keywords_kb([], topic_id=7).inline_keyboard
        ]

        self.assertEqual(rows[0], [("➕ Добавить", "add_kw:7")])
        self.assertEqual(rows[1], [("➖ Минус-слова", "minus_words:7")])


class MinusWordsKeyboardTest(unittest.TestCase):
    def test_global_minus_words_keyboard_returns_to_global_keywords(self):
        rows = [
            [(button.text, button.callback_data) for button in row]
            for row in minus_words_kb([], topic_id=None).inline_keyboard
        ]

        self.assertEqual(rows, [[("◀️ К ключевым словам", "kw_global")]])

    def test_topic_minus_words_keyboard_returns_to_topic_keywords(self):
        rows = [
            [(button.text, button.callback_data) for button in row]
            for row in minus_words_kb([], topic_id=7).inline_keyboard
        ]

        self.assertEqual(rows, [[("◀️ К ключевым словам темы", "kw_topic:7")]])

    def test_minus_words_keyboard_uses_distinct_callbacks_for_words(self):
        rows = [
            [(button.text, button.callback_data) for button in row]
            for row in minus_words_kb(["спам", "реклама"], topic_id=None).inline_keyboard
        ]

        self.assertEqual(rows[0], [("➖ спам", "minus_word:global:0")])
        self.assertEqual(rows[1], [("➖ реклама", "minus_word:global:1")])
        self.assertEqual(rows[2], [("◀️ К ключевым словам", "kw_global")])


if __name__ == "__main__":
    unittest.main()
