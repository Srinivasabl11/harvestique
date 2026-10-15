# Architecture Decision Log

Short ADRs. Add a new entry instead of editing an accepted one.

| # | Decision | Why | Alternatives rejected |
|---|---|---|---|
| 001 | Modular monolith, layered + per-context modules | One deployable on a laptop; layer rules keep it maintainable | Microservices (operational overhead for a student team) |
| 002 | Layer rules enforced by an AST test | Rules nobody checks erode; this fails the build | Convention only; import-linter (extra tool) |
| 003 | Composition root (`core/container.py`) + FastAPI `Depends` for DI | Explicit, zero-magic, trivially overridable in tests | DI frameworks (dependency-injector) |
| 004 | Sync SQLAlchemy 2.0 + psycopg 3 | Workload is CPU-bound (optimisation); simpler tests and Alembic | Async SQLAlchemy |
| 005 | Pure `app/domain/` package for algorithms | Research core must be reproducible, testable and simulatable without DB | Logic inside services |
| 006 | Predictions stored as quantiles + window, versioned, append-only | Uncertainty is the research contribution; history enables calibration and audit | Single point estimate, update in place |
| 007 | Allocation changes recorded in an append-only event ledger | Explainability ("why did my allocation change?") and evaluation | Overwriting allocation rows only |
| 008 | LLM is advisory-only, no DB access, output schema-validated, never sets numbers | Safety, determinism, works when LLM is offline | LLM agents with SQL tools |
| 009 | Monte Carlo + Gaussian copula for pool uncertainty | Captures regional weather correlation; simple to explain | Independence assumption (overstates pooling gain) |
| 010 | LP via SciPy HiGHS, with a greedy baseline | Free, pip-installable on Windows; baseline needed for evaluation | Commercial solvers; OR-Tools (kept as a swap-in option) |
| 011 | DB-backed job queue (`SKIP LOCKED`) + outbox | Durable without adding Redis/Celery | Celery + Redis; FastAPI BackgroundTasks (not durable) |
| 012 | Local Android notifications fed by a polled notification feed | No paid/third-party push service required | FCM push |
| 013 | Phone + password auth; JWT access + rotating hashed refresh tokens | Farmers use phones; SMS OTP needs a paid gateway | OTP login; long-lived JWTs |
| 014 | Riverpod + go_router + Dio, feature-first Flutter | Testable DI via provider overrides; declarative routing with redirects | BLoC (more boilerplate), Provider |
| 015 | Unimplemented providers fail fast at startup; defaults are `fake`/`disabled` | No silent fallback that hides misconfiguration | Lazy failure at first use |
| 016 | Postgres published on host port 5433 | Avoids clash with a native Windows PostgreSQL on 5432 | 5432 |
| 017 | Run uvicorn with `--factory` | No import-time side effects; tests build isolated apps | Module-level `app = FastAPI()` |
| 018 | Access token carries `sid`; every request verifies the session is live in the DB | Logout and account disabling take effect immediately, not after 15 min | Pure stateless JWT (cannot revoke); token deny-list |
| 019 | Refresh-token rotation with reuse detection that revokes the whole session | Stolen refresh tokens are self-limiting and detectable | Long-lived non-rotating refresh tokens |
| 020 | Authorisation role is read from the database, not the JWT claim | Role changes apply instantly; forged/stale claims cannot escalate | Trust the `role` claim |
| 021 | Public sign-up is a discriminated union (farmer\|buyer); admins only via CLI | No privilege-escalation path through the API | `role` free-text field with server-side blacklist |
| 022 | DB-backed login lockout (5 failures / 15 min per phone, unknown phones included) | Brute-force protection without Redis; no account enumeration | In-memory limiter (lost on restart / per-process) |
| 023 | API and repository tests run on real PostgreSQL via the real Alembic migrations; guard requires "test" in the DB name | SQLite hides timestamptz/constraint behaviour; tests double as migration tests | SQLite in-memory; `create_all` |
| 024 | Validation errors never echo `input`; discriminator tags stripped from field paths | Passwords must not leak in 422 bodies; stable field names for Flutter forms | FastAPI default error body |
| 025 | `app/composition.py` assembles services; `api/deps.py` only adapts HTTP | CLI, tests and routes share one wiring path | Re-wiring in each caller |
| 026 | Another farmer's resource answers **404**, not 403 | Does not reveal that a farm/plot/expense exists; one uniform "not found" | 403 (leaks existence) |
| 027 | Plots: *sum of all plot areas* ≤ farm area (stricter than "each plot ≤ farm") | Plots are disjoint parts of a farm; the weaker rule lets a 10-acre farm hold 5 plots of 10 acres | Per-plot check only |
| 028 | Land capacity = **peak concurrent area** via sweep line over inclusive date ranges; end date falls back to sowing + the crop's typical duration | Allows intercropping and back-to-back crops; exact (pairwise summing wrongly rejects A→B→C chains) | One active cycle per plot; summing all open cycles |
| 029 | All parent→child FKs are `RESTRICT`; "delete" a parent only when empty (409 otherwise), otherwise archive via `is_active=false` | Financial/agronomic history is never destroyed by accident; explicit, explainable errors | `CASCADE`; silent soft-delete everywhere |
| 030 | Row locks (`SELECT … FOR UPDATE`) on farm then plot, always in that order | Two concurrent requests cannot over-allocate land; fixed lock order prevents deadlock; covered by a barrier-based race test | Optimistic retries; DB exclusion constraints |
| 031 | Crop catalog is global and admin-managed; deactivate instead of delete; seeded by an idempotent CLI; durations are *indicative defaults* | One source of truth; existing cycles keep working when a crop is retired | Per-farmer crops |
| 032 | Cycle status is forward-only; `harvested`/`abandoned` are closed; a cycle's crop and plot are immutable | Keeps history trustworthy for later prediction-vs-actual calibration | Free-form status edits |
| 033 | PATCH: omitted ≠ `null`; `null` on required columns is a field-level 422; Decimals exact internally, JSON numbers on the wire | No accidental data loss; mobile clients parse numbers directly | PUT only; Decimals as strings |
| 034 | "Not in the future" checks tolerate +1 day | Server clock is UTC, users are UTC+5:30; avoids rejecting a farmer's own "today" shortly after midnight IST | Strict UTC date; per-user timezone |
| 035 | `app/domain/farming.py` holds the pure rules (state machine, dates, capacity); services call it | Same pure-core pattern the Harvest Pool will use; 100% covered by DB-free unit tests | Rules inline in services |
| 036 | Plans are *scenarios*: one that exceeds land or budget is **saved** and reported `feasible=false`, not rejected; the allocator never produces such a plan | "What if I plant more?" must be explorable; infeasibility is information, structural invalidity is a 422 | Reject at save time |
| 037 | Hard constraints = land and budget only; water, labour, demand, season are warnings | Land and budget are what you asked the planner to respect; the others are coarse season totals | Everything hard |
| 038 | Budget check uses **expected** cost; `budget_at_risk` warns when the overrun case would break it | Hard-failing on the pessimistic cost would reject most real plans | Worst-case cost |
| 039 | Worst-case margin pairs the **lowest revenue with the highest cost**; the plan-level worst case assumes all crops fail together | Honest about downside; documented as deliberately harsh and unlikely | Independent per-crop worst cases only |
| 040 | Risk and confidence are transparent weighted sums of named components (weights/thresholds are constants); they are **not probabilities** | Explainable to a farmer and testable; no pretence of statistical precision | A single opaque score; ML |
| 041 | Planning engine is a pure package (`app/domain/planning`): no FastAPI/SQLAlchemy/pydantic (architecture test forbids all three) | Independent of web and database; reusable by the future prediction/pool code and simulations | Logic in services |
| 042 | Only plan **inputs** are stored; results are recomputed on every read | A stored plan can never show stale numbers; the engine is cheap and deterministic | Persist results |
| 043 | Allocator is greedy and says which limit bound each decision; it is not claimed optimal | One-sentence explanations; reproducible ties (name, then input order) | LP/MILP (kept for the research Harvest Pool) |
| 044 | Land is occupied sowing → last harvest-window day; a staggered crop's own overlapping batches count against the land; the per-crop share cap applies per batch | Found by tests: the first version let a 2-batch crop take 10 acres of a 5-acre farm | Treat batches independently |
| 045 | Revenue is spread evenly over the harvest window and received that month; cost falls in the sowing month; prices are entered net of selling costs | Simple, stated assumptions; refine when real payment data exists | Payment delay / cost schedules |
| 046 | Indicative defaults: 14-day harvest window, 5/10/20 % overrun, sowing-month season calendar | Sensible starting points that must be reviewed by an agronomist; all are overridable or only warnings | Hidden constants |

