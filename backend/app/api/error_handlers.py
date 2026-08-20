"""Rendering every failure — ours and the framework's — in one shape."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import SERVICE_NAME
from app.errors import ApiError

logger = logging.getLogger(SERVICE_NAME)


def register_error_handlers(app: FastAPI) -> None:
    """Every failure leaves this app in the same shape, not just the ones we raise."""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.as_dict())

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Unknown route, wrong method, and anything raising HTTPException. Without this
        # they come back as {"detail": ...}, which the CMS has no way to render.
        codes = {404: "not_found", 405: "method_not_allowed"}
        return JSONResponse(
            status_code=exc.status_code,
            # Keep the framework's headers: 405 carries `Allow`, and dropping it turns a
            # standards-compliant response into a merely-correct-looking one.
            headers=exc.headers,
            content={
                "error": {
                    "code": codes.get(exc.status_code, "http_error"),
                    "message": str(exc.detail),
                    "problems": [],
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # A bug should still reach the CMS as JSON it can display, and the detail stays
        # server-side: an editor cannot act on a stack trace and should not see one.
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Something went wrong on our side. Try again in a moment.",
                    "problems": [],
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            {
                "field": ".".join(str(part) for part in error["loc"][1:]) or None,
                "message": error["msg"],
                "hint": "",
            }
            for error in exc.errors()
        ]
        summary = problems[0]["message"] if problems else "Some fields need attention."
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": summary,
                    "problems": problems,
                }
            },
        )
