"""
Trading agent entry point — runs two daily jobs (weekdays only):

  09:00 ET  Research report built and emailed (report_time in config)
  09:30 ET  Trading session executed via Robinhood MCP (run_time in config)

Usage:
  python3 main.py                   — start the scheduler
  RUN_NOW=1 python3 main.py         — also fire both jobs immediately on startup
  REPORT_ONLY=1 python3 main.py     — fire report job only (no trade execution)

Required env vars for email:
  EMAIL_SENDER        your Gmail address
  EMAIL_APP_PASSWORD  Gmail App Password
"""

import asyncio
import logging
import os
import time
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import pytz
import schedule
import yaml

from agent import run_session
from report import main as run_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("trading.log"),
    ],
)
logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _is_weekday() -> bool:
    et = pytz.timezone("America/New_York")
    return datetime.now(et).weekday() < 5


def report_job() -> None:
    if not _is_weekday():
        logger.info("Weekend — skipping report.")
        return

    et = pytz.timezone("America/New_York")
    logger.info("=== Report job starting: %s ===",
                datetime.now(et).strftime("%Y-%m-%d %H:%M ET"))
    try:
        run_report()
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        logger.error("Report job failed: %s", exc, exc_info=True)


def trading_job(config: dict) -> None:
    if not _is_weekday():
        logger.info("Weekend — skipping trading session.")
        return

    et = pytz.timezone("America/New_York")
    logger.info("=== Trading session starting: %s ===",
                datetime.now(et).strftime("%Y-%m-%d %H:%M ET"))
    try:
        summary = asyncio.run(run_session(config))
        logger.info("=== Session complete ===\n%s", summary)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        logger.error("Trading session failed: %s", exc, exc_info=True)


def main() -> None:
    config      = load_config()
    tz          = config["schedule"]["timezone"]
    report_time = config["schedule"]["report_time"]
    run_time    = config["schedule"]["run_time"]

    logger.info("=" * 55)
    logger.info("  Trading Agent started")
    logger.info("  Report  : daily at %s %s (weekdays)", report_time, tz)
    logger.info("  Trading : daily at %s %s (weekdays)", run_time, tz)
    logger.info("  Email to: %s", config["email"]["recipient"])
    logger.info("=" * 55)

    schedule.every().day.at(report_time).do(report_job)

    if os.getenv("RUN_NOW") == "1":
        logger.info("RUN_NOW=1 — firing jobs immediately.")
        report_job()

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Agent stopped.")


if __name__ == "__main__":
    main()
