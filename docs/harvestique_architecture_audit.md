# Architecture audit (2026-10-14): short form

See `ARCHITECTURE.md` for the full design. This lists what was checked in this session and what it found.

## Layers traced
Flutter screen → `ApiClient` (Dio; tokens; offline cache) → FastAPI router (role dependencies: `FarmerDep`,
`BuyerDep`, `FarmerOrBuyerDep`) → service → repository (SQLAlchemy 2) → PostgreSQL 16 → response → screen reload.
Each shell tab reloads when it is opened, so a change made in one tab shows in the others.

| Area | Finding | Status |
|---|---|---|
| Source of truth | All farmer–buyer state lives in PostgreSQL (orders, participations, pools, reservations, notifications); screens hold no shared state | OK |
| Authorization | Role dependencies on every router; ownership enforced in services (404 for someone else's record, 403 for the wrong role); matrices plus the journey's intruder checks pass | OK |
| Money / quantities | Decimal columns; allocation by the deterministic pool engine; the assistant cannot allocate (always refused) | OK |
| Idempotency | `Idempotency-Key` on order placement, pool creation and rebalance; notification dedup keys | OK |
| Concurrency | Row locks and tests for concurrent orders, reservations, pools and fulfilment | OK |
| Voice pipeline | Phone STT (Android recogniser, kn-IN/en-IN; up to 10 hypotheses) → `/voice/intent` (transcript and ≤ 5 alternatives) → rules (normaliser, stems, allowlisted navigation) → one read-only tool, or a proposed write that needs confirmation → template answer (EN/KN) → phone TTS | Fixed today (see `implementation_roadmap.md`) |
| AI models | Ollama on this PC (127.0.0.1): `gemma3:4b` for crop health, `llama3.2:3b` for general answers and English routing only | OK; the PC must be on |
| Network exposure | Backend on 0.0.0.0:8000 (needed for the phone on LAN); **PostgreSQL on 0.0.0.0:5434 (should be 127.0.0.1)** | Open finding |
| Deployment | Docker Compose on a Windows PC; HTTP on LAN; development OTP mode | Internal testing only |
