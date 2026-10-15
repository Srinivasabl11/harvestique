# Harvestique

AI-powered predictive agricultural platform connecting farmers and buyers.
Final-year engineering research project — **Dynamic Predictive Harvest Pooling**: buyers commit
against predicted, uncertainty-aware supply pooled across many farms, with automatic shortage
detection and minimal-disruption reallocation, calibrated against actual harvests.

| Part | Stack |
|---|---|
| Mobile app | Flutter / Dart (Android), Riverpod, go_router, Dio |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic |
| Database | PostgreSQL 16 |
| AI | Local models via Ollama (advisory only; `llama3.2:3b` recommended on CPU); forecasting & optimisation in Python |
| Weather | Open-Meteo (free, no key) |
| Notifications | Local Android notifications |
| Deployment | Docker Compose |

No paid runtime APIs.

## Repository layout
```
backend/     FastAPI service (app/{api,core,domain,models,schemas,services,providers,repositories}), tests, Alembic
frontend/    Flutter Android app (feature-first)
docs/        ARCHITECTURE.md, DECISIONS.md, DEVELOPMENT.md
scripts/     Windows PowerShell setup/run/validate scripts (+ validate.sh for CI)
```

## Quick start (Windows 11)
```powershell
copy .env.example .env
docker compose up -d --build
# API docs:  http://localhost:8000/api/v1/docs
# Readiness: http://localhost:8000/api/v1/health/ready
```
Full setup, Flutter and validation steps: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
Hosted production (Render + Neon, free tier) and the shareable release APK: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Status
- **Phase 0** — architecture & scaffold: complete.
- **Phase 1** — backend identity (users, farmer/buyer profiles, JWT + refresh rotation, roles, lockout): complete.
- **Phase 2** — farm & crop management backend (farms, plots, crop catalog, crop cycles, expenses,
  activities, observations; ownership authorization; validation): complete, 469 tests.
- **Phase 3** — farm income & land planning (cost/income calculator, land utilization planner, income
  continuity, risk/confidence, saved scenarios and comparison): complete, 883 tests.
- **Phase 4** — agricultural intelligence (weather, harvest prediction p10/p50/p90, farm risk, virtual
  inventory, feedback & calibration): complete, 1,048 tests. See docs/AI_PIPELINE.md and docs/EVALUATION.md.
- **Phase 5** — Dynamic Predictive Harvest Pooling and Dynamic Reallocation: complete, 1,139 tests. See
  docs/HARVEST_POOL.md and docs/EVALUATION.md.
- **Phase 6** — product layer: marketplace (orders on pools, farmer acceptance, collection hubs, batches, quality,
  fulfilment, traceability), reminders, notifications, calendar, admin dashboard, repeatable demo, AI farm assistant
  (controlled tools), English/Kannada voice, advisory crop-health photos, and the Flutter Android app.
  1,340 backend tests. The Flutter app has not been compiled yet (see frontend/README.md). See docs/PROGRESS.md.
- **Completion pass (2026-10-10)**:
  - the income planner workflow in the app;
  - the voice-first Ask Harvestique assistant (expenses and plans, follow-ups, local Ollama, confirmations);
  - phone verification by one-time SMS code for registration and every login.

  1,405 backend tests and 90 Flutter tests pass. Production SMS needs a paid or carrier-charged sender. See
  [docs/PROGRESS.md](docs/PROGRESS.md) §3d and [docs/AUDIT.md](docs/AUDIT.md).
- Next: Phase 7, the final research and security audit. Detailed log: [docs/PROGRESS.md](docs/PROGRESS.md).

See the phase plan in
[docs/ARCHITECTURE.md §10](docs/ARCHITECTURE.md#10-development-phases).
