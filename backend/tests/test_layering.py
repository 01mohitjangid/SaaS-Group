"""The dependency rule, enforced instead of remembered.

``app/domain`` is the only layer both the API and the seed loader depend on. If it
ever imports the database, the web framework or the settings, the rules engine stops
being reusable and the "one engine, one story" promise quietly dies. Step 2 adds a
DB-backed validation report, which is exactly where that would happen.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

#: Sentinel for an import whose module name the AST does not spell out.
RELATIVE_IMPORT = "<relative import>"

BANNED_FOR_DOMAIN = (
    "app.db",
    "app.api",
    "app.main",
    "app.config",
    "app.storage",
    "fastapi",
    "starlette",
    "sqlalchemy",
    "psycopg",
    "asyncpg",
    "boto3",
)


def _imports(path: Path) -> set[str]:
    """Every module this file imports, including `from app import db` style."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # Relative imports would dodge every name check below.
                found.add(RELATIVE_IMPORT)
                continue
            if node.module:
                found.add(node.module)
                # `from app import db` — the layer is in the alias, not the module.
                found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _modules(pattern: str) -> list[Path]:
    """Recursive, so a future `app/domain/catalog/` subpackage stays covered."""
    found = sorted(APP.rglob(pattern))
    assert found, f"no modules matched {pattern!r} — the layering guard would be vacuous"
    return found


def _offenders(module: Path, banned: tuple[str, ...]) -> list[str]:
    imported = _imports(module)
    found = [i for i in imported if any(i == b or i.startswith(f"{b}.") for b in banned)]
    if RELATIVE_IMPORT in imported:
        # A relative import carries no module name for the checks above to read, so
        # allowing one would leave a hole exactly where the rule matters most.
        found.append("a relative import — use absolute imports so this guard can read them")
    return sorted(found)


@pytest.mark.parametrize("module", _modules("domain/*.py"), ids=lambda p: p.name)
def test_the_domain_layer_depends_on_nothing_below_it(module: Path) -> None:
    assert _offenders(module, BANNED_FOR_DOMAIN) == [], module.name


@pytest.mark.parametrize("module", _modules("db/*.py"), ids=lambda p: p.name)
def test_the_database_layer_does_not_depend_on_the_web_layer(module: Path) -> None:
    assert _offenders(module, ("app.api", "app.main", "fastapi", "starlette")) == [], module.name


@pytest.mark.parametrize("module", _modules("storage/*.py"), ids=lambda p: p.name)
def test_the_storage_layer_knows_nothing_about_http_or_the_database(module: Path) -> None:
    banned = ("app.api", "app.db", "app.main", "fastapi", "starlette", "sqlalchemy")
    assert _offenders(module, banned) == [], module.name


@pytest.mark.parametrize("module", _modules("services/*.py"), ids=lambda p: p.name)
def test_services_do_not_depend_on_the_web_layer(module: Path) -> None:
    """A service that imports the web layer to describe a conflict has the arrow backwards.

    Services may use the database and storage — that is their job — but the errors they
    raise live in `app.errors`, which knows nothing about HTTP.
    """
    assert _offenders(module, ("app.api", "app.main", "fastapi", "starlette")) == [], module.name


def test_the_viewer_module_imports_no_database_code() -> None:
    """`api/catalog.py` claims it cannot reach unpublished content. Make that structural.

    Direct imports are only half of it — `app.api.deps` is a legitimate import (for
    settings and storage) and also exposes `SessionDep`, so the companion test below
    checks no viewer route actually takes one.
    """
    banned = ("app.db", "sqlalchemy", "app.services.publish")
    assert _offenders(APP / "api" / "catalog.py", banned) == []
    assert _offenders(APP / "services" / "catalog_feed.py", ("app.db", "sqlalchemy")) == []
    assert _offenders(APP / "domain" / "search.py", ("app.db", "sqlalchemy")) == []


def test_no_viewer_route_takes_a_database_session() -> None:
    """Every route in the viewer module, not a list someone has to keep up to date."""
    import inspect

    from app.api import catalog

    routes = [
        value
        for name, value in vars(catalog).items()
        if inspect.iscoroutinefunction(value) and not name.startswith("_")
    ]
    assert len(routes) >= 3, [f.__name__ for f in routes]

    for route in routes:
        annotations = {
            str(parameter.annotation) for parameter in inspect.signature(route).parameters.values()
        }
        assert not any("Session" in a or "AsyncSession" in a for a in annotations), route.__name__


@pytest.mark.parametrize("module", _modules("errors.py"), ids=lambda p: p.name)
def test_the_error_types_are_framework_free(module: Path) -> None:
    banned = ("fastapi", "starlette", "app.api", "app.db", "app.storage", "sqlalchemy")
    assert _offenders(module, banned) == [], module.name


# --------------------------------------------------------------- guarding the guard
# A dependency test that cannot fail is worse than none: it reads as coverage. These
# feed known violations through the real checker and require it to catch each one.

VIOLATIONS = [
    ("plain import", "import app.db.models"),
    ("aliased import", "import app.db.models as m"),
    ("from-import", "from app.db.models import Show"),
    ("package alias", "from app import db"),
    ("settings", "from app.config import Settings"),
    ("web framework", "from fastapi import APIRouter"),
    ("orm", "import sqlalchemy as sa"),
    ("relative", "from ..db.models import Show"),
    ("relative package", "from .. import db"),
]


@pytest.mark.parametrize(("label", "source"), VIOLATIONS, ids=[v[0] for v in VIOLATIONS])
def test_the_guard_catches_every_way_of_dodging_it(tmp_path: Path, label: str, source: str) -> None:
    module = tmp_path / "offender.py"
    module.write_text(source, encoding="utf-8")
    assert _offenders(module, BANNED_FOR_DOMAIN), f"{label} slipped past the layering guard"


def test_the_guard_does_not_cry_wolf(tmp_path: Path) -> None:
    module = tmp_path / "clean.py"
    module.write_text(
        "import json\nfrom dataclasses import dataclass\n"
        "from app.domain.reference import Reference\n",
        encoding="utf-8",
    )
    assert _offenders(module, BANNED_FOR_DOMAIN) == []
