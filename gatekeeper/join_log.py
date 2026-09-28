from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import gspread
from google.oauth2.service_account import Credentials

from .blacklist import SHEETS_SCOPE
from .config import GoogleConfig

LOGGER = logging.getLogger(__name__)


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

    async def append(self, entries: Iterable[JoinLogEntry]) -> bool:
        rows = [entry.values() for entry in entries]
        if not rows:
            return True
        try:
            await asyncio.to_thread(self._append_rows, rows)
        except Exception:
            # A logging outage must not prevent blacklist enforcement.
            LOGGER.error("JOIN LOG FAILED rows=%d", len(rows), exc_info=True)
            return False
        LOGGER.info("JOIN LOG SUCCESS rows=%d", len(rows))
        return True

    def _append_rows(self, rows: list[list[str]]) -> None:
        credentials = Credentials.from_service_account_file(
            self._config.credentials_file, scopes=[SHEETS_SCOPE]
        )
        client = gspread.authorize(credentials)
        worksheet = client.open_by_url(self._config.spreadsheet_url).worksheet(
            self._config.join_log_worksheet_name
        )
        worksheet.append_rows(rows, value_input_option="USER_ENTERED")
