# Harvestique — Feature audit (2026-10-09, updated after the assistant / planner / phone-verification pass)

How this was checked:
* **Backend:** full pytest suite against PostgreSQL 16, plus ruff and mypy. Results are under "Test results" below.
* **API contract, app → backend:** every `ApiClient` call in `frontend/lib` was matched against the live OpenAPI
  spec (route and method), and every JSON body's field names against the request schemas. Result: no mismatches.
* **API contract, backend → app:** response fields the UI reads were compared with the response schemas. Result: no
  unknown fields.
* **Runtime:** every GET the app makes was replayed as the demo farmer, buyer and admin against a server running the
  repeatable demo data. Result: 61 of 61 succeed.
* **On device:** confirmed by the owner for Add crop and Farm → Crops.

Legend:
* ✅ complete: UI and backend, tested.
* 🟡 incomplete: the backend exists but there is no or only partial UI.
* ❌ broken.
* ❔ unverified: never exercised against the real thing.

## Farmer
| Feature | Status | Notes |
|---|---|---|
| Register / sign in / silent token refresh | ✅ | **Now two steps with a one-time SMS code** (registration and every login). Production needs a real SMS provider (see DEVELOPMENT.md) |
| Farms: add, list, detail | ✅ | Edit and archive (`PATCH`/`DELETE /farms/{id}`) have no UI 🟡 |
| Plots: add | ✅ | Edit and delete have no UI 🟡 |
| Add crop to a plot; Farm → Crops | ✅ | Confirmed on a phone. The empty catalog was fixed by startup seeding |
| Crop page: predictions, observations, crop-health photo, harvest, feedback | ✅ | Deleting a crop cycle and editing or deleting observations have no UI 🟡 |
| **Expenses** | ✅ **new** | Farm and crop lists with a total; add and delete. Editing (`PATCH`) has no UI |
| Activities (land preparation, sowing, spraying …) | 🟡 | The backend and the calendar show them, but the app has no way to record one |
| Income plans | ✅ **completed** | Create (optionally linked to a farm) → add crops by hand or from a crop's prediction → estimated net income with ranges, next to actual recorded expenses; edit/delete crops and plans; duplicates rejected. Compare, duplicate and the quick calculator still have no UI |
| Market: buyer opportunities, accept / decline | ✅ | |
| Harvest: virtual inventory, offer to buyers, grade | ✅ | |
| Reminders, suggestions, calendar | ✅ | The "Record recent expenses" suggestion can now be acted on |
| In-app notifications (polled) | ✅ | Android system-tray notifications are not wired 🟡 |
| Ask Harvestique (assistant, English/Kannada voice) | ✅ **completed** (❔ on a phone) | Voice-first screen with conversation mode, interruption and confirmations; expense and income-plan tools; follow-ups; local Ollama routing verified live. Phone speech not yet tried on a device. Kannada general AI answers are off (garbled by small local models). Kannada strings need native review |
| Profile (`/farmers/me`) | 🟡 | Only the language can be changed |
| Weather | ❔ | A farm without coordinates gets 422, which the app handles. Live Open-Meteo has not been tried from this machine |

## Buyer
| Feature | Status | Notes |
|---|---|---|
| Supply summary, harvest search | ✅ | |
| Demands, ranked matches, create pool (greedy or LP) | ✅ | |
| Pool: events, ledger; place order | ✅ | Manual rebalance (`POST /pools/{id}/rebalance`) has no UI 🟡 |
| Orders: status, cancel, traceability | ✅ | Trace by batch code (`/trace/batches/{code}`) has no UI 🟡 |
| Buyer profile (`/buyers/me`) | 🟡 | No UI |

## Admin
| Feature | Status | Notes |
|---|---|---|
| Dashboard, orders, batches, quality, fulfil, hubs | ✅ | |
| Crop catalog management (`/crops` POST/PATCH/DELETE) | 🟡 | No UI. The catalog is seeded automatically |
| Users list, calibration recompute | 🟡 | No UI |

## Platform
| Item | Status | Notes |
|---|---|---|
| Repeatable demo `python -m app.cli.demo --reset` | ✅ fixed | It was ❌ after startup crop seeding was added (`POST /crops` returned 409). The demo now turns seeding off for itself, and a unit regression test covers it |
| Offline writes queued | 🟡 | Not implemented. Writes fail with a clear message |
| Crop-health model | 🟡 | A colour heuristic, not a trained model |
| `docker compose up` on this PC | ⚠️ | The DB host port defaults to 5433, which another local Postgres uses. There is no `.env`; set `POSTGRES_HOST_PORT=5434` |
| Phase 7 research and security audit | 🟡 | Not started |

## Priority of remaining work
Order: dependencies first, then value to farmers.
1. **Expenses UI**: done in this pass.
2. **Activities UI**: same pattern as expenses. The calendar already shows activities.
3. ~~Income-plan items~~ done 2026-10-09.
4. **Correcting mistakes**: delete a wrongly added crop cycle; edit or archive farms and plots.
5. Android system-tray notifications.
6. Admin crop-catalog UI; buyer manual rebalance and batch-code trace; profiles.
7. Phase 7 audit.
