import unittest

from bot.handlers.topics import (
    MAX_CHAT_LIST_ITEMS,
    _decode_chat_list_file,
    _parse_chat_list_file,
)
from bot.keyboards import manual_chat_kb


class ManualChatKeyboardTest(unittest.TestCase):
    def test_manual_chat_keyboard_offers_text_and_paid_file_upload(self):
        rows = [
            [(button.text, button.callback_data) for button in row]
            for row in manual_chat_kb(7).inline_keyboard
        ]

        self.assertEqual(rows[0], [("✏️ Ввести один чат", "add_chat_text:7")])
        self.assertEqual(rows[1], [("📄 Загрузить файл со списком", "add_chat_file:7")])
        self.assertEqual(rows[2], [("◀️ К теме", "topic:7")])


class ChatListFileParserTest(unittest.TestCase):
    def test_parse_chat_list_file_ignores_empty_lines_and_deduplicates(self):
        self.assertEqual(
            _parse_chat_list_file("@one\n\nhttps://t.me/two\n@one\n"),
            ["@one", "https://t.me/two"],
        )

    def test_parse_chat_list_file_rejects_empty_file(self):
        with self.assertRaises(ValueError):
            _parse_chat_list_file("\n  \n")

    def test_parse_chat_list_file_enforces_unique_item_limit(self):
        valid = "\n".join(f"@chat{i}" for i in range(MAX_CHAT_LIST_ITEMS))
        too_many = "\n".join(f"@chat{i}" for i in range(MAX_CHAT_LIST_ITEMS + 1))

        self.assertEqual(len(_parse_chat_list_file(valid)), MAX_CHAT_LIST_ITEMS)
        with self.assertRaises(ValueError):
            _parse_chat_list_file(too_many)


class ChatListFileDecoderTest(unittest.TestCase):
    def test_decode_chat_list_file_reads_utf8_bom(self):
        self.assertEqual(_decode_chat_list_file(b"\xef\xbb\xbf@one\n@two"), "@one\n@two")

    def test_decode_chat_list_file_reads_plain_utf8(self):
        self.assertEqual(_decode_chat_list_file("@канал\n@test".encode("utf-8")), "@канал\n@test")

    def test_decode_chat_list_file_reads_cp1251(self):
        self.assertEqual(_decode_chat_list_file("@канал\n@test".encode("cp1251")), "@канал\n@test")

    def test_decode_chat_list_file_rejects_undecodable_bytes(self):
        with self.assertRaises(ValueError):
            _decode_chat_list_file(b"\x98")


if __name__ == "__main__":
    unittest.main()
