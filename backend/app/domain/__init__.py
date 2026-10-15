"""Pure domain logic and research algorithms.

No I/O: no SQLAlchemy, FastAPI, HTTP or LLM calls. Functions here take plain
data and return plain data, which makes the core research contribution
(uncertainty aggregation, pooling, allocation, shortage detection, calibration)
unit-testable, reproducible and runnable in offline simulations.
"""
