"""Optional trusted-time cross-check for offline license validation."""
from __future__ import annotations

import logging
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

_TRUSTED_TIME_URLS = (
    "https://www.microsoft.com",
    "https://time.cloudflare.com",
    "https://www.baidu.com",
)
_MAX_SKEW_SECONDS = 3600
_TIMEOUT_S = 8


def fetch_trusted_utc_ts() -> int | None:
    """Return approximate UTC epoch from HTTP Date headers, or None if unreachable."""
    for url in _TRUSTED_TIME_URLS:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                date_hdr = resp.headers.get("Date")
                if not date_hdr:
                    continue
                dt = parsedate_to_datetime(date_hdr)
                return int(dt.timestamp())
        except (urllib.error.URLError, OSError, ValueError, TypeError) as exc:
            logger.debug("trusted time probe failed for %s: %s", url, exc)
    return None


def local_clock_skew_seconds(local_ts: int, trusted_ts: int) -> int:
    return abs(int(local_ts) - int(trusted_ts))


def clock_skew_exceeds_tolerance(
    local_ts: int,
    *,
    trusted_ts: int | None = None,
    max_skew_seconds: int = _MAX_SKEW_SECONDS,
) -> bool:
    trusted = trusted_ts if trusted_ts is not None else fetch_trusted_utc_ts()
    if trusted is None:
        return False
    return local_clock_skew_seconds(local_ts, trusted) > max_skew_seconds
