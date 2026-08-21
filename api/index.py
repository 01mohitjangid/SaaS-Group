"""Vercel entry point for the API.

Vercel serves this project three ways from one domain, which is why there is no CORS
configuration in the deployment at all:

    /            the viewer   (static)
    /admin       the CMS      (static)
    /api/...     this app     (python function)

`root_path` tells FastAPI it is mounted under `/api`, so it generates correct URLs while
the routes themselves stay `/catalog`, `/admin/shows` and so on — the same paths the
container serves. Nothing about the application knows it is running serverless.

Migrations are **not** run here. A function is the wrong place to alter a schema: it can
run in parallel with itself, and a request timing out mid-migration is not recoverable.
`make deploy-db` applies them from a machine, once, before the deploy.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The application lives in backend/; Vercel's function root is the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import create_app  # noqa: E402

app = create_app()
