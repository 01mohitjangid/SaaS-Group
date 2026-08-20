from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = REPO_ROOT / "data" / "challenge" / "seed_shows.json"
REFERENCE_PATH = REPO_ROOT / "data" / "challenge" / "reference.json"

# Settings are strict on purpose (no silent defaults for the database or tokens), so
# the suite supplies its own before anything imports `app.main`.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://peblo:peblo@localhost:5432/peblo_tv_test"
)
os.environ.setdefault("API_TOKENS", "test-admin-token:admin,test-editor-token:editor")
os.environ.setdefault("ENVIRONMENT", "ci")

# Forced, not defaulted: an exported STORAGE_LOCAL_ROOT would otherwise make the suite
# write test fixtures into the developer's real artwork store.
_TEST_STORAGE_ROOT = tempfile.mkdtemp(prefix="peblo-test-storage-")
os.environ["STORAGE_LOCAL_ROOT"] = _TEST_STORAGE_ROOT
atexit.register(shutil.rmtree, _TEST_STORAGE_ROOT, ignore_errors=True)

from app.domain.reference import Reference, load_reference  # noqa: E402


@pytest.fixture(scope="session")
def reference() -> Reference:
    return load_reference(REFERENCE_PATH)


@pytest.fixture(scope="session")
def seed_path() -> Path:
    return SEED_PATH


# API integration fixtures live in tests/_api.py so importing them is explicit.
pytest_plugins = ["tests._api"]
