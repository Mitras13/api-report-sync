import logging
import time

from .downloader_core import AuthExpiredError

logger = logging.getLogger(__name__)


def download_with_retry(
    fetch_func,
    max_retries=3,
    base_delay_seconds=2,
    label="download",
):
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info("%s: attempt %d/%d", label, attempt, max_retries)
            result = fetch_func()
            logger.info("%s: success on attempt %d", label, attempt)
            return result
        except AuthExpiredError:
            logger.error(
                "%s: authentication failure; retry skipped",
                label,
                exc_info=True,
            )
            raise
        except Exception as exc:
            last_error = exc
            logger.warning(
                "%s: attempt %d/%d failed: %s",
                label, attempt, max_retries, exc,
            )
            if attempt < max_retries:
                delay = base_delay_seconds * (2 ** (attempt - 1))
                logger.info("%s: retrying in %s seconds", label, delay)
                time.sleep(delay)

    raise last_error
