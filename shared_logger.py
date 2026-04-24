from pathlib import Path
import logging


LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

SHARED_LOG_FILE = LOG_DIR / "app_shared.log"


def get_shared_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        file_handler = logging.FileHandler(SHARED_LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
        )
        logger.addHandler(file_handler)
        logger.propagate = False

    return logger


def log_event(logger: logging.Logger, event: str, **kwargs):
    parts = [f"event={event}"]
    for k, v in kwargs.items():
        try:
            txt = repr(v)
            if len(txt) > 2000:
                txt = txt[:2000] + "...<truncated>"
            parts.append(f"{k}={txt}")
        except Exception:
            parts.append(f"{k}=<unserializable>")
    logger.info(" | ".join(parts))