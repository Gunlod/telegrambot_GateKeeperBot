from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    action: str = "ban"


@dataclass(frozen=True)
class GoogleConfig:
    spreadsheet_url: str
    worksheet_name: str
    join_log_worksheet_name: str
    credentials_file: Path


@dataclass(frozen=True)
class BlacklistConfig:
    refresh_interval: int = 60


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    file: Path = Path("./logs/gatekeeper.log")
    max_bytes: int = 5 * 1024 * 1024
    backup_count: int = 5


@dataclass(frozen=True)
class AppConfig:
    telegram: TelegramConfig
    google: GoogleConfig
    blacklist: BlacklistConfig
    logging: LoggingConfig


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def _required_string(section: dict[str, Any], key: str, name: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}.{key} must be a non-empty string")
    return value.strip()


def load_config(path: str | Path) -> AppConfig:
    """Load and validate a YAML configuration file."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as source:
        raw = yaml.safe_load(source) or {}
    root = _mapping(raw, "configuration")
    telegram = _mapping(root.get("telegram"), "telegram")
    google = _mapping(root.get("google"), "google")
    blacklist = _mapping(root.get("blacklist", {}), "blacklist")
    logging = _mapping(root.get("logging", {}), "logging")

    action = str(telegram.get("action", "ban")).lower().strip()
    if action not in {"ban", "kick"}:
        raise ValueError("telegram.action must be either 'ban' or 'kick'")

    interval = int(blacklist.get("refresh_interval", 60))
    if interval <= 0:
        raise ValueError("blacklist.refresh_interval must be greater than zero")

    max_bytes = int(logging.get("max_bytes", 5 * 1024 * 1024))
    backup_count = int(logging.get("backup_count", 5))
    if max_bytes <= 0 or backup_count < 0:
        raise ValueError("logging.max_bytes must be > 0 and backup_count must be >= 0")
    join_log_worksheet_name = google.get("join_log_worksheet_name", "join_log")
    if not isinstance(join_log_worksheet_name, str) or not join_log_worksheet_name.strip():
        raise ValueError("google.join_log_worksheet_name must be a non-empty string")

    return AppConfig(
        telegram=TelegramConfig(
            bot_token=_required_string(telegram, "bot_token", "telegram"),
            action=action,
        ),
        google=GoogleConfig(
            spreadsheet_url=_required_string(google, "spreadsheet_url", "google"),
            worksheet_name=_required_string(google, "worksheet_name", "google"),
            join_log_worksheet_name=join_log_worksheet_name.strip(),
            credentials_file=Path(_required_string(google, "credentials_file", "google")),
        ),
        blacklist=BlacklistConfig(refresh_interval=interval),
        logging=LoggingConfig(
            level=str(logging.get("level", "INFO")).upper(),
            file=Path(str(logging.get("file", "./logs/gatekeeper.log"))),
            max_bytes=max_bytes,
            backup_count=backup_count,
        ),
    )
