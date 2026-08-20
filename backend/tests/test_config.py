from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def _settings(**overrides: object) -> Settings:
    """Build Settings in isolation.

    `_env_file=None` matters: the README tells a developer to create a repo-root
    `.env`, and `Settings` is anchored to that absolute path, so without this these
    tests would pass or fail depending on whether the developer followed the README.
    """
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "api_tokens": "admin-token:admin,editor-token:editor",
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_api_tokens_parse_into_a_role_map() -> None:
    settings = _settings()
    assert settings.token_roles == {"admin-token": "admin", "editor-token": "editor"}


def test_unknown_role_in_api_tokens_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(api_tokens="some-token:superuser")


def test_malformed_api_tokens_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(api_tokens="just-a-token")


def test_api_tokens_are_optional_because_only_seeding_reads_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A production API boots without them; it authenticates against the users table."""
    monkeypatch.delenv("API_TOKENS", raising=False)
    settings = Settings(database_url="postgresql+asyncpg://u:p@localhost/db", _env_file=None)
    assert settings.api_tokens is None
    with pytest.raises(ValueError, match="API_TOKENS"):
        _ = settings.token_roles


def test_sync_database_url_is_derived_for_alembic() -> None:
    assert _settings().sync_database_url == "postgresql+psycopg://u:p@localhost/db"


def test_blank_optional_values_mean_unset_not_empty_string() -> None:
    """`.env.example` ships S3_* as empty keys; boto3 rejects endpoint_url="" outright."""
    settings = _settings(
        s3_bucket="",
        s3_endpoint_url="",
        s3_public_base_url="   ",
        s3_access_key_id="",
        s3_secret_access_key="",
        reference_path="",
    )
    assert settings.s3_bucket is None
    assert settings.s3_endpoint_url is None
    assert settings.s3_public_base_url is None
    assert settings.s3_access_key_id is None
    assert settings.s3_secret_access_key is None
    assert settings.reference_path is None


def test_settings_never_repr_their_secrets() -> None:
    settings = _settings(s3_secret_access_key="super-secret-value")
    assert "super-secret-value" not in repr(settings)
