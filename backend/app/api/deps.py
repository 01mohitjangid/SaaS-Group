"""Request-scoped dependencies: a database session, the storage client, and who you are.

Roles are enforced here and nowhere else, so "editor vs admin" cannot be declared in a
docstring and forgotten in a handler. Every admin route declares one of
``EditorUser`` / ``AdminUser`` in its signature, which means the check is part of the
route's type rather than a line someone can delete without the tests noticing.

Authentication resolves the bearer token against the ``users`` table — never against
the ``API_TOKENS`` setting, which exists only to seed that table. That way
``publish_runs.created_by_user_id`` always points at a real principal.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User
from app.domain.reference import Reference
from app.errors import ApiError
from app.storage import ObjectStorage

bearer = HTTPBearer(auto_error=False, description="A token from API_TOKENS, seeded into users.")


def token_hash(token: str) -> str:
    """The plaintext token never reaches the database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_storage(request: Request) -> ObjectStorage:
    storage: ObjectStorage = request.app.state.storage
    return storage


def get_reference(request: Request) -> Reference:
    reference: Reference = request.app.state.reference
    return reference


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]
ReferenceDep = Annotated[Reference, Depends(get_reference)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="not_authenticated",
            message="You are signed out. Sign in again to continue.",
        )

    user = (
        await session.execute(
            select(User).where(
                User.token_hash == token_hash(credentials.credentials),
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()

    if user is None:
        raise ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_token",
            message="That sign-in is no longer valid. Ask an admin for a new token.",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_editor(user: CurrentUser) -> User:
    """Editors and admins both do CRUD."""
    return user


async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="admin_only",
            message=("Only an admin can change what is live. Ask one of them to run this for you."),
        )
    return user


EditorUser = Annotated[User, Depends(require_editor)]
AdminUser = Annotated[User, Depends(require_admin)]
