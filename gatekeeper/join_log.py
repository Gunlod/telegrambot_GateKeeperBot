from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials

from .blacklist import SHEETS_SCOPE
from .config import GoogleConfig

LOGGER = logging.getLogger(__name__)
JOIN_LOG_HEADERS = ["username", "display_name", "joined_at"]


@dataclass(frozen=True)
class JoinLogEntry:
    username: str | None
    display_name: str
    joined_at: datetime

    def values(self) -> list[str]:
        # ISO 8601 in UTC is sortable and unambiguous when viewed in Sheets.
        timestamp = self.joined_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        return [self.username or "", self.display_name, timestamp]


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
        worksheet.append_rows(rows, value_input_option="RAW")
        return created
