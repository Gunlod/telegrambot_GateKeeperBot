from __future__ import annotations

import argparse
import logging
from pathlib import Path

from gatekeeper.bot import build_application, configure_logging
from gatekeeper.config import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GateKeeperBot Telegram group blacklist bot")
    parser.add_argument(
        "--config", default="config.yaml", help="Path to YAML configuration (default: config.yaml)"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        config = load_config(Path(args.config))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    configure_logging(config)
    logging.getLogger(__name__).info("Starting GateKeeperBot action=%s", config.telegram.action)
    build_application(config).run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
