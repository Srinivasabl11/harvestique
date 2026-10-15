# API reference

Generated from the running application by `python -m app.cli.gen_docs` (do not edit by hand).
Base path `/api/v1`. Interactive docs: `/docs` (Swagger UI) and `/openapi.json` when the server runs.

* **Auth:** phone + password. `/auth/login` returns the tokens; send `Authorization: Bearer <access token>` and
  refresh with `/auth/refresh`. `/auth/register` signs in at once (201) or, on a server where new accounts wait for
  an admin, answers 202 without tokens. After an admin password reset, `/auth/login` answers 403
  `password_change_required` until `/auth/password/change` sets a new password.
* **Roles** below are the ones the route actually enforces (taken from its dependencies): `public`, `any signed-in`,
  or a role list. Resource routes additionally check ownership and answer **404** for another user's resource.
* **Errors** use one envelope: `{"error": {"code", "message", "details"}}`; 401 not signed in, 403 wrong role,
  404 not found / not yours, 409 state conflict, 422 validation or business rule, 503 provider unavailable.
* **Idempotency:** `POST /buyer-demands/{id}/pool` and `POST /orders` accept `Idempotency-Key`;
  `POST /pools/{id}/rebalance` requires it.
* **Data provenance:** responses label numbers as `measured`, `estimate`, `assumption` or `simulated`.
  No endpoint returns or computes a market price.


**140 operations.**


## activities

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `POST` | `/farms/{farm_id}/activities` | farmer | ActivityCreate (json) | ActivityRead | Create Activity |
| `GET` | `/farms/{farm_id}/activities` | farmer | - | Page_ActivityRead_ | List Activities |
| `GET` | `/activities/{activity_id}` | farmer | - | ActivityRead | Get Activity |
| `PATCH` | `/activities/{activity_id}` | farmer | ActivityUpdate (json) | ActivityRead | Update Activity |
| `DELETE` | `/activities/{activity_id}` | farmer | - | - | Delete Activity |

## admin

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `GET` | `/admin/users` | admin | - | Page_UserRead_ | List users (admin only) |
| `POST` | `/admin/users/{user_id}/access` | admin | AccessUpdate (json) | UserRead | Approve, suspend or revoke a tester's access (admin only) |
| `POST` | `/admin/users/{user_id}/password-reset` | admin | - | TemporaryPasswordOut | Give a farmer or buyer a one-time temporary password; they must change it at sign-in (admin only) |

## assistant, voice and crop health

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `POST` | `/assistant/chat` | any signed-in | AssistantRequest (json) | AssistantResponse | Ask the farm assistant (advisory; English/Kannada) |
| `GET` | `/assistant/tools` | any signed-in | - | list[ToolInfo] | Tools the assistant may use for me |
| `POST` | `/assistant/tools/{name}` | any signed-in | ToolRequest (json) | ToolResultOut | Run one validated tool (write tools need confirm=true) |
| `POST` | `/voice/intent` | buyer, farmer | VoiceIntentRequest (json) | AssistantResponse | Ask by voice: the on-device transcript goes through the same assistant and confirmations as chat |
| `POST` | `/voice/transcribe` | buyer, farmer | Body_transcribe_api_v1_voice_transcribe_post (form-data) | TranscriptOut | Server speech-to-text (503 when speech runs on the phone) |
| `POST` | `/voice/speak` | buyer, farmer | SpeakRequest (json) | audio | Server text-to-speech (503 when speech runs on the phone) |
| `POST` | `/crop-health/analyze` | farmer | Body_analyze_api_v1_crop_health_analyze_post (form-data) | CropHealthOut | Advisory crop-health photo analysis (not a diagnosis) |
| `GET` | `/crop-health/validation` | any signed-in | - | CropValidationReport | Which crops the photo check has been measured on (coverage is not accuracy) |
| `GET` | `/crop-health/analyses` | farmer | - | list[CropHealthOut] | My past crop-health analyses |

## auth

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `POST` | `/auth/register` | public |  (json) | RegistrationOut | Register a farmer or buyer (201 + tokens when usable at once; 202 when it waits for admin approval) |
| `POST` | `/auth/login` | public | LoginRequest (json) | AuthResponse | Sign in with phone and password (403 password_change_required after an admin password reset) |
| `POST` | `/auth/password/change` | public | PasswordChangeRequest (json) | AuthResponse | Set a new password using the current or temporary one; signs out other devices and signs in |
| `POST` | `/auth/me/tour` | any signed-in | TourUpdate (json) | UserRead | Record that the first-login tour (this version) was finished or skipped |
| `POST` | `/auth/refresh` | public | RefreshRequest (json) | TokenPair | Exchange a refresh token for a new token pair (rotation) |
| `POST` | `/auth/logout` | any signed-in | - | - | End the current session |
| `GET` | `/auth/me` | any signed-in | - | UserRead | The authenticated user (with role profile) |

## buyers

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `GET` | `/buyers/me` | buyer | - | BuyerProfileRead | The authenticated buyer's profile |

## crop catalog

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `GET` | `/crops` | any signed-in | - | Page_CropRead_ | Search the crop catalog |
| `POST` | `/crops` | admin | CropCreate (json) | CropRead | Add a crop to the catalog (admin) |
| `GET` | `/crops/{crop_id}` | any signed-in | - | CropRead | Get Crop |
| `PATCH` | `/crops/{crop_id}` | admin | CropUpdate (json) | CropRead | Edit or deactivate a crop (admin) |
| `DELETE` | `/crops/{crop_id}` | admin | - | - | Delete an unused crop (admin) |

## crop cycles

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `POST` | `/plots/{plot_id}/crop-cycles` | farmer | CropCycleCreate (json) | CropCycleRead | Start a crop cycle on a plot |
| `GET` | `/plots/{plot_id}/crop-cycles` | farmer | - | Page_CropCycleRead_ | List Plot Cycles |
| `GET` | `/farms/{farm_id}/crop-cycles` | farmer | - | Page_CropCycleRead_ | List Farm Cycles |
| `GET` | `/crop-cycles/{cycle_id}` | farmer | - | CropCycleRead | Get Cycle |
| `PATCH` | `/crop-cycles/{cycle_id}` | farmer | CropCycleUpdate (json) | CropCycleRead | Update Cycle |
| `DELETE` | `/crop-cycles/{cycle_id}` | farmer | - | - | Delete Cycle |

## crop plans

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `POST` | `/crop-plans` | farmer | CropPlanCreate (json) | CropPlanRead | Create Plan |
| `GET` | `/crop-plans` | farmer | - | Page_CropPlanSummary_ | List my plans |
| `GET` | `/crop-plans/compare` | farmer | - | CompareResponse | Compare 2-5 of my plans side by side |
| `GET` | `/crop-plans/{plan_id}` | farmer | - | CropPlanRead | Get Plan |
| `PATCH` | `/crop-plans/{plan_id}` | farmer | CropPlanUpdate (json) | CropPlanRead | Update Plan |
| `DELETE` | `/crop-plans/{plan_id}` | farmer | - | - | Delete Plan |
| `POST` | `/crop-plans/{plan_id}/duplicate` | farmer | CropPlanDuplicate (json) | CropPlanRead | Copy a plan (with its crops) to try a variation |
| `GET` | `/crop-plans/{plan_id}/evaluation` | farmer | - | PlanResultOut | Evaluate a saved plan (computed fresh from its inputs) |
| `POST` | `/crop-plans/{plan_id}/items/from-prediction` | farmer | PlanItemFromPrediction (json) | PlanItemRead | Add a crop to a plan using a saved prediction's p10/p50/p90 as its yield range |
| `POST` | `/crop-plans/{plan_id}/items` | farmer | PlanItemCreate (json) | PlanItemRead | Add Item |
| `GET` | `/crop-plan-items/{item_id}` | farmer | - | PlanItemRead | Get Item |
| `PATCH` | `/crop-plan-items/{item_id}` | farmer | PlanItemUpdate (json) | PlanItemRead | Update Item |
| `DELETE` | `/crop-plan-items/{item_id}` | farmer | - | - | Delete Item |

## expenses

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `POST` | `/farms/{farm_id}/expenses` | farmer | ExpenseCreate (json) | ExpenseRead | Create Expense |
| `GET` | `/farms/{farm_id}/expenses` | farmer | - | Page_ExpenseRead_ | List Expenses |
| `GET` | `/expenses/{expense_id}` | farmer | - | ExpenseRead | Get Expense |
| `PATCH` | `/expenses/{expense_id}` | farmer | ExpenseUpdate (json) | ExpenseRead | Update Expense |
| `DELETE` | `/expenses/{expense_id}` | farmer | - | - | Delete Expense |

## farmers

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `GET` | `/farmers/me` | farmer | - | FarmerProfileRead | The authenticated farmer's profile |

## farms

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `POST` | `/farms` | farmer | FarmCreate (json) | FarmRead | Create Farm |
| `GET` | `/farms` | farmer | - | Page_FarmRead_ | List my farms |
| `GET` | `/farms/{farm_id}` | farmer | - | FarmRead | Get Farm |
| `PATCH` | `/farms/{farm_id}` | farmer | FarmUpdate (json) | FarmRead | Update Farm |
| `DELETE` | `/farms/{farm_id}` | farmer | - | - | Delete an empty farm (otherwise archive it) |

## harvest pooling

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `PATCH` | `/inventory/lots/{lot_id}` | farmer | LotUpdate (json) | LotOut | Opt a lot into pooling / set its expected grade |
| `POST` | `/buyer-demands` | buyer | DemandCreate (json) | DemandOut | Create Demand |
| `GET` | `/buyer-demands` | buyer | - | Page_DemandOut_ | List Demands |
| `GET` | `/buyer-demands/{demand_id}` | buyer | - | DemandOut | Get Demand |
| `POST` | `/buyer-demands/{demand_id}/cancel` | buyer | - | DemandOut | Withdraw a demand that has no harvest pool yet |
| `GET` | `/buyer-demands/{demand_id}/matches` | buyer | - | MatchesOut | Ranked future-harvest supply for a demand |
| `POST` | `/buyer-demands/{demand_id}/pool` | buyer | PoolCreate | null (json) | PoolOut | Pool uncertain supply from several farms to meet the demand (repeat safely with Idempotency-Key) |
| `GET` | `/pools` | admin, buyer | - | Page_PoolOut_ | My pools (admins: all pools) |
| `GET` | `/pools/{pool_id}` | admin, buyer | - | PoolOut | Get Pool |
| `POST` | `/pools/{pool_id}/rebalance` | admin, buyer | - | EventOut | Detect shortages and reallocate now (Idempotency-Key required) |
| `GET` | `/pools/{pool_id}/events` | admin, buyer | - | list[EventOut] | Reallocation events (why and before/after) |
| `GET` | `/pools/{pool_id}/ledger` | admin, buyer | - | list[LedgerOut] | Append-only allocation audit ledger |

## health

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `GET` | `/health/live` | public | - | LivenessResponse | Live |
| `GET` | `/health/ready` | public | - | ReadinessResponse | Ready |

## intelligence

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `GET` | `/farms/{farm_id}/weather/now` | farmer | - | WeatherNowOut | Current conditions, rain chance (next hours, 7 days) for the farm card (model estimates, cached 15 min) |
| `GET` | `/farms/{farm_id}/weather` | farmer | - | FarmWeatherOut | Forecast and recent weather for a farm |
| `POST` | `/crop-cycles/{cycle_id}/predictions` | farmer | PredictionRequest | null (json) | PredictionOut | Create a new prediction version (p10/p50/p90, harvest window, confidence, risk) |
| `GET` | `/crop-cycles/{cycle_id}/predictions` | farmer | - | Page_PredictionOut_ | All prediction versions, newest first |
| `GET` | `/predictions/{prediction_id}` | farmer | - | PredictionOut | Get Prediction |
| `PATCH` | `/crop-cycles/{cycle_id}/harvest-actual` | farmer | HarvestCorrectionIn (json) | FeedbackReport | Correct a recorded harvest (only before produce from it reached a collection hub) |
| `POST` | `/crop-cycles/{cycle_id}/harvest-actual` | farmer | HarvestActualIn (json) | FeedbackReport | Record the MEASURED harvest; scores every prediction version and updates calibration |
| `GET` | `/crop-cycles/{cycle_id}/feedback` | farmer | - | FeedbackReport | Predicted vs actual for each version |
| `GET` | `/farms/{farm_id}/risk` | farmer | - | FarmRiskOut | Farm risk across open crop cycles |
| `GET` | `/calibration` | any signed-in | - | list[CalibrationOut] | Latest calibration profiles (aggregate statistics only) |
| `POST` | `/admin/calibration/recompute` | admin | - | list[CalibrationOut] | Recompute calibration profiles (admin) |

## inventory

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `GET` | `/inventory/lots` | farmer | - | Page_LotOut_ | List Lots |
| `GET` | `/inventory/lots/{lot_id}` | farmer | - | LotDetail | Get Lot |
| `POST` | `/inventory/lots/{lot_id}/reservations` | farmer | ReservationIn (json) | ReservationOut | Commit part of a lot (never more than can be safely promised) |
| `POST` | `/inventory/reservations/{reservation_id}/release` | farmer | - | ReservationOut | Release |
| `POST` | `/inventory/reservations/{reservation_id}/fulfil` | farmer | - | ReservationOut | Fulfil |

## marketplace

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `GET` | `/market/supply` | admin, buyer | - | list[SupplySummary] | Future supply on offer per crop (p10 estimates) |
| `GET` | `/market/harvests` | buyer | - | MatchesOut | Search eligible future harvests |
| `GET` | `/market/opportunities` | farmer | - | list[Opportunity] | Open buyer demands for crops I grow |
| `POST` | `/orders` | buyer | OrderCreate (json) | OrderOut | Order a harvest pool (farmers are asked to confirm) |
| `GET` | `/orders` | admin, buyer | - | Page_OrderOut_ | My orders (admins: all) |
| `GET` | `/orders/{order_id}` | admin, buyer | - | OrderOut | Get Order |
| `POST` | `/orders/{order_id}/cancel` | buyer | - | OrderOut | Cancel before any produce is received |
| `GET` | `/orders/{order_id}/trace` | admin, buyer | - | OrderTrace | Order -> Pool -> Allocation -> Harvest -> Batch -> Quality -> Fulfilment |
| `GET` | `/orders/{order_id}/batches` | admin, buyer | - | list[app__schemas__marketplace__BatchOut] | Order Batches |
| `GET` | `/participations` | farmer | - | Page_ParticipationOut_ | Supply requests sent to me |
| `POST` | `/participations/{participation_id}/progress` | farmer | ProgressUpdate (json) | ParticipationOut | Mark an accepted request as preparing, then ready (the buyer is notified) |
| `POST` | `/participations/{participation_id}/accept` | farmer | - | ParticipationOut | Accept |
| `POST` | `/participations/{participation_id}/decline` | farmer | ParticipationDecline (json) | ParticipationOut | Decline: supply released and replaced by dynamic reallocation |
| `GET` | `/hubs` | any signed-in | - | list[HubOut] | Active collection hubs |
| `POST` | `/admin/hubs` | admin | HubCreate (json) | HubOut | Create Hub |
| `PATCH` | `/admin/hubs/{hub_id}` | admin | HubUpdate (json) | HubOut | Update Hub |
| `GET` | `/admin/batches` | admin | - | Page_BatchOut_ | Batches (hub operations) |
| `POST` | `/admin/batches` | admin | BatchCreate (json) | app__schemas__marketplace__BatchOut | Record produce received at a hub (measured) |
| `DELETE` | `/admin/batches/{batch_id}` | admin | - | - | Remove a batch entered by mistake (only before its quality check) |
| `POST` | `/admin/batches/{batch_id}/quality` | admin | QualityIn (json) | app__schemas__marketplace__BatchOut | Record the quality check of a batch (measured, once) |
| `POST` | `/admin/order-items/{item_id}/fulfil` | admin | - | FulfilmentOut | Count quality-accepted produce towards the order |
| `GET` | `/trace/batches/{code}` | any signed-in | - | BatchTrace | Trace a batch code back to its farm, harvest and prediction |

## observations

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `POST` | `/crop-cycles/{cycle_id}/observations` | farmer | ObservationCreate (json) | ObservationRead | Create Observation |
| `GET` | `/crop-cycles/{cycle_id}/observations` | farmer | - | Page_ObservationRead_ | List Observations |
| `GET` | `/observations/{observation_id}` | farmer | - | ObservationRead | Get Observation |
| `PATCH` | `/observations/{observation_id}` | farmer | ObservationUpdate (json) | ObservationRead | Update Observation |
| `DELETE` | `/observations/{observation_id}` | farmer | - | - | Delete Observation |

## planning

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `POST` | `/planning/calculate` | farmer | CalcRequest (json) | PlanResultOut | Farm cost & income calculator |
| `POST` | `/planning/suggest-allocation` | farmer | AllocationRequestIn (json) | AllocationResponse | Land utilization planner: suggest how to split land between crops |

## plots

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `POST` | `/farms/{farm_id}/plots` | farmer | PlotCreate (json) | PlotRead | Create Plot |
| `GET` | `/farms/{farm_id}/plots` | farmer | - | Page_PlotRead_ | List Plots |
| `GET` | `/plots/{plot_id}` | farmer | - | PlotRead | Get Plot |
| `PATCH` | `/plots/{plot_id}` | farmer | PlotUpdate (json) | PlotRead | Update Plot |
| `DELETE` | `/plots/{plot_id}` | farmer | - | - | Delete Plot |

## reminders, notifications and calendar

| Method | Path | Roles | Request | Response | Summary |
|---|---|---|---|---|---|
| `PATCH` | `/farmers/me` | farmer | FarmerProfileUpdate (json) | FarmerProfileRead | Update my farmer profile (incl. preferred language) |
| `PATCH` | `/buyers/me` | buyer | BuyerProfileUpdate (json) | BuyerProfileRead | Update my buyer profile |
| `POST` | `/reminders` | buyer, farmer | ReminderCreate (json) | ReminderOut | Create Reminder |
| `GET` | `/reminders` | buyer, farmer | - | Page_ReminderOut_ | List Reminders |
| `GET` | `/reminders/suggestions` | farmer | - | list[ReminderSuggestion] | Reminders suggested from my recorded data |
| `GET` | `/reminders/{reminder_id}` | buyer, farmer | - | ReminderOut | Get Reminder |
| `PATCH` | `/reminders/{reminder_id}` | buyer, farmer | ReminderUpdate (json) | ReminderOut | Update Reminder |
| `DELETE` | `/reminders/{reminder_id}` | buyer, farmer | - | - | Delete one of my reminders |
| `POST` | `/reminders/{reminder_id}/complete` | buyer, farmer | - | ReminderOut | Done (recurring reminders roll forward) |
| `POST` | `/reminders/{reminder_id}/dismiss` | buyer, farmer | - | ReminderOut | Dismiss Reminder |
| `GET` | `/notifications` | any signed-in | - | Page_NotificationOut_ | My notification feed (due reminders are added first) |
| `GET` | `/notifications/unread-count` | any signed-in | - | UnreadCount | Unread |
| `POST` | `/notifications/{notification_id}/read` | any signed-in | - | NotificationOut | Mark Read |
| `POST` | `/notifications/read-all` | any signed-in | - | UnreadCount | Mark All Read |
| `GET` | `/calendar` | buyer, farmer | - | CalendarOut | Farm / delivery calendar (max 180 days) |
| `GET` | `/admin/dashboard` | admin | - | DashboardOut | Platform counts and totals (real data only) |
