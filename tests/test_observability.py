import pytest

from api.config import get_settings
from api.observability import init_error_tracking


@pytest.fixture(autouse=True)
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_off_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_error_tracking("api") is False


def test_on_with_dsn(monkeypatch):
    sentry_sdk = pytest.importorskip("sentry_sdk")
    calls = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.update(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda k, v: calls.update({k: v}))
    monkeypatch.setenv("SENTRY_DSN", "https://key@example.ingest.sentry.io/1")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert init_error_tracking("worker") is True
    assert calls["environment"] == "production"
    assert calls["send_default_pii"] is False
    assert calls["component"] == "worker"
