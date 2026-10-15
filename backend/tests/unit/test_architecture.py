"""Executable architecture rules. These fail the build if layering is violated.

Key guarantees requested for the project:
  * AI logic is not placed in API routes.
  * The LLM (and every provider) has no database access.
  * Domain algorithms stay pure (no I/O frameworks).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _files(sub: str) -> list[Path]:
    return sorted((APP / sub).rglob("*.py"))


def _violations(files: list[Path], forbidden: tuple[str, ...]) -> list[str]:
    out = []
    for f in files:
        for imp in _imports(f):
            if any(imp == p or imp.startswith(p + ".") for p in forbidden):
                rel = f.relative_to(APP) if f.is_relative_to(APP) else f.name
                out.append(f"{rel} imports {imp}")
    return out


RULES = [
    # (layer, forbidden imports, files to skip)
    ("providers", ("sqlalchemy", "app.models", "app.repositories", "app.core.database", "app.services", "app.api"), ()),
    (
        "domain",
        (
            "sqlalchemy",
            "fastapi",
            "pydantic",  # the domain stays free of the API's validation layer
            "httpx",
            "app.models",
            "app.repositories",
            "app.providers",
            "app.services",
            "app.api",
            "app.core.database",
        ),
        (),
    ),
    ("core", ("app.services", "app.api", "app.repositories", "app.models"), ()),
    ("services", ("fastapi", "app.api"), ()),
    ("repositories", ("fastapi", "app.services", "app.api", "app.providers"), ()),
    ("models", ("fastapi", "app.services", "app.api", "app.providers", "app.repositories"), ()),
    ("schemas", ("sqlalchemy", "app.services", "app.api", "app.repositories"), ()),
    # Routes talk to services only; wiring lives in api/deps.py.
    ("api", ("app.repositories", "app.models", "app.providers", "app.domain"), ("deps.py",)),
]


@pytest.mark.parametrize(("layer", "forbidden", "skip"), RULES, ids=[r[0] for r in RULES])
def test_layer_dependencies(layer, forbidden, skip):
    files = [f for f in _files(layer) if f.name not in skip]
    assert _violations(files, forbidden) == []


def test_architecture_checker_detects_violations(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("from app.repositories.base import SQLAlchemyRepository\n")
    assert _violations([bad], ("app.repositories",))
