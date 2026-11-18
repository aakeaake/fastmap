import os

import pytest

os.environ.setdefault("MML_API_KEY", "test-key")


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """Tile retries back off with real sleeps; tests don't need to wait."""
    from fastmap.services import mml_source

    monkeypatch.setattr(mml_source, "_sleep", lambda s: None)
