from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

import gspread
from google.oauth2.service_account import Credentials

from .config import GoogleConfig

LOGGER = logging.getLogger(__name__)
# Join logging appends rows to the same spreadsheet, so the service account needs
# the regular Sheets scope (and Editor access to the spreadsheet).
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
BLACKLIST_HEADERS = ["username", "display_name", "numeric_id", "enabled", "note"]
LEGACY_BLACKLIST_HEADERS = ["username", "display_name", "enabled", "note"]


def normalize_username(value: object) -> str:
    """Normalize a Telegram username for exact, case-insensitive comparisons."""
    text = str(value or "").strip()
    return text[1:].strip().casefold() if text.startswith("@") else text.casefold()


def normalize_display_name(value: object) -> str:
    """Normalize whitespace and case without permitting partial matches."""
    # Preserve the original Unicode text; only the normalization required by the
    # matching rules (outer/duplicate whitespace and case) is applied.
    text = str(value or "").strip()
    return re.sub(r"\s+", " ", text).casefold()


def normalize_numeric_id(value: object) -> str:
    """Normalize a Telegram numeric user ID for exact numeric comparison."""
    text = str(value or "").strip()
    if not text or not text.isdecimal():
        return ""
    # Telegram user IDs do not have meaningful leading zeros.
    return str(int(text))


def display_name(first_name: str | None, last_name: str | None) -> str:
    """Build the Telegram display name with exactly one separator when applicable."""
    return " ".join(part for part in (first_name, last_name) if part).strip()


def _is_enabled(value: object) -> bool:
    return str(value or "").strip().casefold() in {"true", "1", "yes", "y"}


@dataclass(frozen=True)
class BlacklistSnapshot:
    usernames: frozenset[str]
    display_names: frozenset[str]
    numeric_ids: frozenset[str]
    entry_count: int
    last_updated: datetime | None

    @classmethod
    def empty(cls) -> "BlacklistSnapshot":
        return cls(frozenset(), frozenset(), frozenset(), 0, None)


MatchType = Literal["username", "display_name", "numeric_id"]


class BlacklistStore:
    """Concurrency-safe in-memory blacklist and Google Sheets loader."""

    def __init__(self, google_config: GoogleConfig) -> None:
        self._config = google_config
        self._snapshot = BlacklistSnapshot.empty()
        self._lock = asyncio.Lock()

    @property
    def snapshot(self) -> BlacklistSnapshot:
        return self._snapshot

    def match(
        self, username: str | None, name: str, numeric_id: int | str | None
    ) -> MatchType | None:
        snapshot = self._snapshot
        normalized_username = normalize_username(username)
        normalized_name = normalize_display_name(name)
        normalized_numeric_id = normalize_numeric_id(numeric_id)
        if normalized_username and normalized_username in snapshot.usernames:
            return "username"
        if normalized_name and normalized_name in snapshot.display_names:
            return "display_name"
        if normalized_numeric_id and normalized_numeric_id in snapshot.numeric_ids:
            return "numeric_id"
        return None

    async def reload(self) -> bool:
        """Reload from Sheets. Keep the last known good snapshot on any failure."""
        async with self._lock:
            try:
                snapshot = await asyncio.to_thread(self._load_snapshot)
            except Exception:
                if self._snapshot.last_updated is None:
                    LOGGER.error(
                        "BLACKLIST REFRESH FAILED: no usable cache is available",
                        exc_info=True,
                    )
                else:
                    LOGGER.warning(
                        "BLACKLIST REFRESH FAILED: retaining previous cache updated=%s",
                        self._snapshot.last_updated.isoformat(),
                        exc_info=True,
                    )
                return False

            self._snapshot = snapshot
            LOGGER.info(
                "BLACKLIST REFRESH rows=%d usernames=%d display_names=%d numeric_ids=%d",
                snapshot.entry_count,
                len(snapshot.usernames),
                len(snapshot.display_names),
                len(snapshot.numeric_ids),
            )
            return True

    def _load_snapshot(self) -> BlacklistSnapshot:
        credentials = Credentials.from_service_account_file(
            self._config.credentials_file, scopes=[SHEETS_SCOPE]
        )
        client = gspread.authorize(credentials)
        worksheet = client.open_by_url(self._config.spreadsheet_url).worksheet(
            self._config.worksheet_name
        )
        self._migrate_headers_if_needed(worksheet)
        records: Iterable[dict[str, Any]] = worksheet.get_all_records(
            expected_headers=BLACKLIST_HEADERS
        )
        usernames: set[str] = set()
        names: set[str] = set()
        numeric_ids: set[str] = set()
        enabled_rows = 0
        for row in records:
            if not _is_enabled(row.get("enabled")):
                continue
            username = normalize_username(row.get("username"))
            name = normalize_display_name(row.get("display_name"))
            numeric_id = normalize_numeric_id(row.get("numeric_id"))
            # An enabled but empty row cannot match anything and is not an entry.
            if not username and not name and not numeric_id:
                continue
            enabled_rows += 1
            if username:
                usernames.add(username)
            if name:
                names.add(name)
            if numeric_id:
                numeric_ids.add(numeric_id)
        return BlacklistSnapshot(
            usernames=frozenset(usernames),
            display_names=frozenset(names),
            numeric_ids=frozenset(numeric_ids),
            entry_count=enabled_rows,
            last_updated=datetime.now(timezone.utc),
        )

    @staticmethod
    def _migrate_headers_if_needed(worksheet: gspread.Worksheet) -> None:
        headers = worksheet.row_values(1)
        if headers == BLACKLIST_HEADERS:
            return
        if headers == LEGACY_BLACKLIST_HEADERS:
            # Insert at C so enabled/note entries retain their columns and values.
            worksheet.insert_cols([["numeric_id"]], col=3, value_input_option="RAW")
            LOGGER.info("BLACKLIST WORKSHEET MIGRATED: numeric_id column added")
            return
        raise ValueError(
            f"Blacklist worksheet has unsupported headers {headers!r}; "
            f"expected {BLACKLIST_HEADERS!r}"
        )
