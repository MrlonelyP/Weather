import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_flood_configured", False):
        root.setLevel(level.upper())
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s", "%Y-%m-%dT%H:%M:%S%z")
    )
    root.addHandler(handler)
    root.setLevel(level.upper())
    # httpx logs every request at INFO; keep it quieter, our collectors log themselves
    logging.getLogger("httpx").setLevel(logging.WARNING)
    root._flood_configured = True  # type: ignore[attr-defined]
