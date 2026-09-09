from __future__ import annotations

import json
import logging
import signal
import time

from app.config import get_settings
from app.services.correlation import ResolverConfigurationError, run_correlation_cycle

logger = logging.getLogger("rdp_session_api.correlation_worker")
_stop = False


def _request_stop(signum, frame) -> None:
    global _stop
    _stop = True
    logger.info("correlation worker stop requested")


def _sleep_interruptibly(seconds: int) -> None:
    deadline = time.monotonic() + seconds
    while not _stop and time.monotonic() < deadline:
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    last_disabled_log = False
    while not _stop:
        try:
            result = run_correlation_cycle(settings)
            if result.get("status") == "disabled":
                if not last_disabled_log:
                    logger.info("correlation worker disabled by feature flag")
                    last_disabled_log = True
            else:
                last_disabled_log = False
                logger.info("correlation cycle result=%s", json.dumps(result, ensure_ascii=False, default=str))
        except ResolverConfigurationError as exc:
            last_disabled_log = False
            logger.error("correlation resolver configuration error code=%s", exc.code)
        except Exception:
            last_disabled_log = False
            logger.exception("correlation cycle failed")

        _sleep_interruptibly(settings.correlation_poll_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
