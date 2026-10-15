"""Application services (use cases).

Services orchestrate repositories, domain logic and providers. They are
HTTP-agnostic (no FastAPI imports) so they can be reused by workers,
CLI scripts and research simulations.
"""
