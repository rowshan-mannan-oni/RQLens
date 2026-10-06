"""Optional error tracking with Sentry.

Enabled when SENTRY_DSN is set and the `sentry` extra is installed (pip install ".[sentry]").
The FastAPI and arq integrations are switched on automatically. Request bodies, cookies and
user details are not sent: they can contain research data.
"""

import logging

from api.config import get_settings

log = logging.getLogger(__name__)


def init_error_tracking(component: str) -> bool:
    """Start Sentry for `component` ("api" or "worker"). Returns whether it is on."""
    settings = get_settings()
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.warning("SENTRY_DSN is set but sentry-sdk is not installed; error tracking is off")
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
    )
    sentry_sdk.set_tag("component", component)
    return True
