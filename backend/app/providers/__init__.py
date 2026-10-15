"""External-world adapters behind Protocol interfaces.

Rules (enforced by tests/unit/test_architecture.py):
  * providers never import SQLAlchemy, models, repositories or the database module;
  * the LLM provider receives plain text and returns plain text - it has no DB access;
  * concrete implementations are selected only in providers/registry.py.
"""
