import unittest

from gatekeeper.blacklist import (
    BlacklistSnapshot,
    BlacklistStore,
    display_name,
    normalize_display_name,
    normalize_numeric_id,
    normalize_username,
)
from gatekeeper.config import GoogleConfig


class BlacklistNormalizationTests(unittest.TestCase):
    def test_username_ignores_at_sign_case_and_outer_whitespace(self) -> None:
        self.assertEqual(normalize_username("  @ExampleUser "), "exampleuser")

    def test_display_name_collapses_whitespace_and_case(self) -> None:
        self.assertEqual(normalize_display_name(" Example   User "), "example user")

    def test_display_name_is_built_with_one_separator(self) -> None:
        self.assertEqual(display_name("Example", "User"), "Example User")
        self.assertEqual(display_name("Example", None), "Example")

    def test_matching_is_exact_and_uses_or_condition(self) -> None:
        store = BlacklistStore(GoogleConfig("url", "blacklist", "join_log", "credentials.json"))
        store._snapshot = BlacklistSnapshot(
            usernames=frozenset({"exampleuser"}),
            display_names=frozenset({"yamada"}),
            numeric_ids=frozenset({"123456"}),
            entry_count=2,
            last_updated=None,
        )
        self.assertEqual(store.match("@EXAMPLEUSER", "Different", None), "username")
        self.assertEqual(store.match(None, "Yamada", None), "display_name")
        self.assertEqual(store.match(None, "Different", 123456), "numeric_id")
        self.assertIsNone(store.match(None, "Taro Yamada", None))

    def test_numeric_id_normalizes_leading_zeroes(self) -> None:
        self.assertEqual(normalize_numeric_id(" 000123456 "), "123456")


if __name__ == "__main__":
    unittest.main()
