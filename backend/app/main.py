"""FastAPI application factory.

Settings, the content vocabulary and the storage backend are resolved in
``create_app`` — the ``/media`` mount has to be a real route before the app serves,
and neither storage backend opens a connection at construction. The database engine
is built in the lifespan and disposed with it. Nothing here needs a live database,
so tests can construct the app freely.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import SERVICE_NAME, __version__
from app.api.admin_artwork import reference_router as admin_reference_router
from app.api.admin_artwork import router as admin_artwork_router
from app.api.admin_content import router as admin_content_router
from app.api.admin_publish import router as admin_publish_router
from app.api.catalog import router as catalog_router
from app.api.error_handlers import register_error_handlers
from app.api.health import router as health_router
from app.api.media import mount_media
from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.domain.reference import load_reference
from app.storage import build_storage

logger = logging.getLogger(SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info("started environment=%s storage=%s", settings.environment, settings.storage_backend)
    try:
        yield
    finally:
        await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    logging.basicConfig(
        level=resolved.log_level.upper(), format="%(levelname)s %(name)s %(message)s"
    )

    app = FastAPI(
        title="Peblo TV Mini API",
        version=__version__,
        summary="CMS content API, catalogue publisher and viewer catalogue feed.",
        lifespan=lifespan,
        root_path=resolved.root_path,
    )
    app.state.settings = resolved
    app.state.reference = load_reference(
        Path(resolved.reference_path) if resolved.reference_path else None
    )

    # The engine is lazy (nothing connects here), so the session factory can be built
    # before startup — which the Postgres storage backend needs, and which keeps the
    # /media mount a real route rather than something added mid-lifespan.
    engine = create_engine(resolved)
    session_factory = create_session_factory(engine)
    app.state.engine = engine
    app.state.session_factory = session_factory

    storage = build_storage(resolved, session_factory)
    app.state.storage = storage

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(health_router)
    app.include_router(catalog_router)
    app.include_router(admin_content_router)
    app.include_router(admin_artwork_router)
    app.include_router(admin_reference_router)
    app.include_router(admin_publish_router)

    mount_media(app, storage)
    return app
