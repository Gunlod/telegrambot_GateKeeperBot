import unittest
from datetime import datetime, timezone

from gatekeeper.join_log import JoinLogEntry
from gatekeeper.join_log import JoinLogStore
from gatekeeper.config import GoogleConfig


class JoinLogEntryTests(unittest.TestCase):
    def test_values_include_username_name_and_utc_timestamp(self) -> None:
        entry = JoinLogEntry(
            username="@Gunlod",
            display_name="Example User",
            joined_at=datetime(2026, 9, 28, 12, 34, 56, tzinfo=timezone.utc),
        )
        self.assertEqual(
            entry.values(),
            ["@Gunlod", "Example User", "2026-09-28T12:34:56+00:00"],
        )

    def test_worksheet_title_is_unique_per_group(self) -> None:
        store = JoinLogStore(GoogleConfig("url", "blacklist", "join_log", "credentials.json"))
        self.assertEqual(store.worksheet_title(-1001234567890), "join_log_-1001234567890")


if __name__ == "__main__":
    unittest.main()
