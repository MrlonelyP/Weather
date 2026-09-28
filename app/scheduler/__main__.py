"""Run the collection scheduler as its own process:  python -m app.scheduler"""
import logging

from app.config.logging import setup_logging
from app.config.settings import get_settings
from app.scheduler.jobs import create_blocking_scheduler


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logging.getLogger(__name__).info("starting collection scheduler")
    scheduler = create_blocking_scheduler(settings)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
