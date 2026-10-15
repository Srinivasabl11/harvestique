"""docs/API.md and docs/DATABASE.md are generated from the code; this fails when they drift.
Fix by running: python -m app.cli.gen_docs ../docs"""

from pathlib import Path

from app.cli.gen_docs import api_markdown, db_markdown

DOCS = Path(__file__).resolve().parents[3] / "docs"


def test_api_reference_matches_the_running_app():
    assert (DOCS / "API.md").read_text() == api_markdown()


def test_database_reference_matches_the_models():
    assert (DOCS / "DATABASE.md").read_text() == db_markdown()
