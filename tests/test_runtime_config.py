import unittest
from pathlib import Path

from main import _effective_session_mode

REPO_ROOT = Path(__file__).resolve().parents[1]


class RuntimeConfigTest(unittest.TestCase):
    def test_effective_session_mode_defaults_to_string_when_session_string_exists(self):
        self.assertEqual(_effective_session_mode("auto", "session"), "string")

    def test_effective_session_mode_defaults_to_file_without_session_string(self):
        self.assertEqual(_effective_session_mode("auto", ""), "file")

    def test_effective_session_mode_rejects_unknown_values(self):
        with self.assertRaises(ValueError):
            _effective_session_mode("bad", "")

    def test_env_example_uses_api_id_key(self):
        with open(REPO_ROOT / ".env.example", encoding="utf-8") as f:
            first_line = f.readline().strip()

        self.assertEqual(first_line, "API_ID=12345678")


if __name__ == "__main__":
    unittest.main()
