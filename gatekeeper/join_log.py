from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials

from .blacklist import SHEETS_SCOPE
from .config import GoogleConfig

LOGGER = logging.getLogger(__name__)
JOIN_LOG_HEADERS = ["username", "display_name", "numeric_id", "joined_at"]
LEGACY_JOIN_LOG_HEADERS = ["username", "display_name", "joined_at"]
JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class JoinLogEntry:
    username: str | None
    display_name: str
    numeric_id: int
    joined_at: datetime

    def values(self) -> list[str]:
        # Keep the offset in the ISO 8601 value so JST is explicit in Sheets.
        timestamp = self.joined_at.astimezone(JST).isoformat(timespec="seconds")
        return [self.username or "", self.display_name, str(self.numeric_id), timestamp]


class JoinLogStore:
    """Append join events to a dedicated worksheet without blocking the event loop."""

    def __init__(self, google_config: GoogleConfig) -> None:
        self._config = google_config
        self._lock = asyncio.Lock()

    def worksheet_title(self, chat_id: int) -> str:
        return f"{self._config.join_log_worksheet_prefix}_{chat_id}"

    async def append(self, chat_id: int, entries: Iterable[JoinLogEntry]) -> bool:
        rows = [entry.values() for entry in entries]
        if not rows:
            return True
        # Serializing creates prevents two simultaneous updates from trying to
        # create the same new group worksheet in this Bot process.
        async with self._lock:
            try:
                created = await asyncio.to_thread(self._append_rows, chat_id, rows)
            except Exception:
                # A logging outage must not prevent blacklist enforcement.
                LOGGER.error("JOIN LOG FAILED chat_id=%d rows=%d", chat_id, len(rows), exc_info=True)
                return False
        if created:
            LOGGER.info(
                "JOIN LOG WORKSHEET CREATED chat_id=%d worksheet=%s",
                chat_id,
                self.worksheet_title(chat_id),
            )
        LOGGER.info(
            "JOIN LOG SUCCESS chat_id=%d worksheet=%s rows=%d",
            chat_id,
            self.worksheet_title(chat_id),
            len(rows),
        )
        return True

    def _append_rows(self, chat_id: int, rows: list[list[str]]) -> bool:
        credentials = Credentials.from_service_account_file(
            self._config.credentials_file, scopes=[SHEETS_SCOPE]
        )
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_url(self._config.spreadsheet_url)
        title = self.worksheet_title(chat_id)
        try:
            worksheet = spreadsheet.worksheet(title)
            created = False
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(JOIN_LOG_HEADERS))
            worksheet.append_row(JOIN_LOG_HEADERS, value_input_option="RAW")
            created = True
        if not created:
            self._migrate_headers_if_needed(worksheet, title)
        worksheet.append_rows(rows, value_input_option="RAW")
        return created

    @staticmethod
    def _migrate_headers_if_needed(worksheet: gspread.Worksheet, title: str) -> None:
        headers = worksheet.row_values(1)
        if headers == JOIN_LOG_HEADERS:
            return
        if headers == LEGACY_JOIN_LOG_HEADERS:
            # Insert at C so legacy joined_at values move from C to D intact.
            worksheet.insert_cols([["numeric_id"]], col=3, value_input_option="RAW")
            LOGGER.info("JOIN LOG WORKSHEET MIGRATED worksheet=%s", title)
            return
        raise ValueError(
            f"Worksheet '{title}' has unsupported headers {headers!r}; "
            f"expected {JOIN_LOG_HEADERS!r}"
        )
