"""Single source of configuration.

Nothing else in the app reads ``os.environ`` — everything goes through ``Settings``
so that every knob is discoverable in one place (and documented in ``.env.example``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Anchored to the repo, not the working directory, so a process started from an
#: unexpected place can never pick up a .env from outside the project.
REPO_ROOT = Path(__file__).resolve().parents[2]

Role = Literal["admin", "editor"]
VALID_ROLES: frozenset[str] = frozenset({"admin", "editor"})
StorageBackend = Literal["local", "postgres", "s3"]

#: Managed Postgres hands out URLs with libpq's SSL options. asyncpg does not understand
#: `sslmode` or `channel_binding` and raises on them, so each driver gets its own form.
_SSL_KEYS = ("sslmode", "channel_binding", "ssl")


def _for_driver(url: str, driver: str) -> str:
    """Rewrite a Postgres URL for one driver, translating its SSL options."""
    parsed = urlsplit(url)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    wants_ssl = any(key in _SSL_KEYS for key, _ in params)
    kept = [(key, value) for key, value in params if key not in _SSL_KEYS]

    if wants_ssl:
        # asyncpg takes `ssl=require`; libpq (psycopg) takes `sslmode=require`.
        kept.append(("ssl", "require") if driver == "asyncpg" else ("sslmode", "require"))

    scheme = f"postgresql+{driver}"
    return urlunsplit((scheme, parsed.netloc, parsed.path, urlencode(kept), parsed.fragment))


class Settings(BaseSettings):
    # The repo-root .env is read wherever the process is started from; a
    # backend-local .env wins if both exist.
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["local", "ci", "staging", "production"] = "local"
    log_level: str = "INFO"

    # --- database -------------------------------------------------------------
    database_url: str
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- auth -----------------------------------------------------------------
    # "token:role,token:role". Static bearer tokens are deliberate for a take-home:
    # they keep role enforcement real and testable without standing up an IdP.
    #
    # BOOTSTRAP ONLY, and therefore optional: `scripts/seed.py` turns these into rows
    # in `users`, and the API authenticates against that table — never against this
    # setting — so `publish_runs.created_by_user_id` always points at a real principal.
    # A production API boots fine without it; only seeding requires it.
    api_tokens: SecretStr | None = None

    # --- storage --------------------------------------------------------------
    storage_backend: StorageBackend = "local"
    #: Relative paths resolve against the **repo root** (see `build_storage`), not the
    #: working directory, so `make seed` and the tests agree wherever they are started.
    storage_local_root: str = "storage/local"
    public_media_base_url: str = "http://localhost:8000/media"

    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_public_base_url: str | None = None

    # --- content vocabulary ---------------------------------------------------
    #: Overridable so the app is not coupled to the repo layout (the image puts it
    #: somewhere else). None means "the checked-in data/challenge/reference.json".
    reference_path: str | None = None

    # --- catalogue ------------------------------------------------------------
    catalog_pointer_key: str = "catalog/current.json"
    catalog_run_key_prefix: str = "catalog/runs"

    #: Set when the API is mounted under a path prefix — `/api` on the single-domain
    #: Vercel deployment. Routes stay `/catalog` and `/admin/...`; only the mount moves.
    root_path: str = ""

    # --- http -----------------------------------------------------------------
    cors_allow_origins: str = "http://localhost:5173,http://localhost:5174"

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _parse_tokens(raw: str) -> dict[str, Role]:
        tokens: dict[str, Role] = {}
        for chunk in (c.strip() for c in raw.split(",") if c.strip()):
            token, separator, role = chunk.partition(":")
            if not separator or not token.strip():
                raise ValueError(
                    f"API_TOKENS entry {chunk!r} is malformed; expected '<token>:<role>'"
                )
            role = role.strip()
            if role not in VALID_ROLES:
                raise ValueError(
                    f"API_TOKENS role {role!r} is unknown; expected one of {sorted(VALID_ROLES)}"
                )
            tokens[token.strip()] = role  # type: ignore[assignment]
        if not tokens:
            raise ValueError("API_TOKENS must define at least one '<token>:<role>' pair")
        return tokens

    @field_validator(
        "s3_bucket",
        "s3_endpoint_url",
        "s3_public_base_url",
        "s3_access_key_id",
        "s3_secret_access_key",
        "reference_path",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """`.env.example` ships these as empty keys, which must mean "not configured".

        Without this, `S3_ENDPOINT_URL=` reaches boto3 as `""` and it raises
        `Invalid endpoint:` — so plain AWS S3, which needs no endpoint override,
        would be the one backend that could not be configured from the template.
        """
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _check_api_tokens(self) -> Settings:
        if self.api_tokens is not None:
            self._parse_tokens(self.api_tokens.get_secret_value())
        return self

    @property
    def token_roles(self) -> dict[str, Role]:
        if self.api_tokens is None:
            raise ValueError("API_TOKENS is not set; it is required to seed users")
        return self._parse_tokens(self.api_tokens.get_secret_value())

    @property
    def async_database_url(self) -> str:
        """What the app connects with."""
        return _for_driver(self.database_url, "asyncpg")

    @property
    def sync_database_url(self) -> str:
        """Alembic runs synchronously; the app runs on asyncpg."""
        return _for_driver(self.database_url, "psycopg")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
