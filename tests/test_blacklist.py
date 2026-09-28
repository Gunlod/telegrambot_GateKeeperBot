import unittest

from gatekeeper.blacklist import (
    BlacklistSnapshot,
    BlacklistStore,
    display_name,
    normalize_display_name,
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
        store = BlacklistStore(GoogleConfig("url", "blacklist", "credentials.json"))
        store._snapshot = BlacklistSnapshot(
            usernames=frozenset({"exampleuser"}),
            display_names=frozenset({"yamada"}),
            entry_count=2,
            last_updated=None,
        )
        self.assertEqual(store.match("@EXAMPLEUSER", "Different"), "username")
        self.assertEqual(store.match(None, "Yamada"), "display_name")
        self.assertIsNone(store.match(None, "Taro Yamada"))


if __name__ == "__main__":
    unittest.main()
