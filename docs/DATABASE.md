# Database

PostgreSQL 16, SQLAlchemy 2.0 models in `backend/app/models/`, Alembic migrations `0001_baseline` ->
`0007_marketplace`. Generated from the model metadata by `python -m app.cli.gen_docs` (do not edit by hand);
`alembic check` verifies the migrations produce exactly this schema (no drift).

Conventions: UUID primary keys; `created_at`/`updated_at` timestamps with time zone; quantities `NUMERIC(14,3)` kg;
enums stored as strings with CHECK constraints; foreign keys are `RESTRICT` unless stated, so audit history cannot be
deleted from under it. Append-only tables (never updated by the application): `yield_predictions`,
`calibration_profiles`, `reallocation_events`, `allocation_ledger`, `quality_checks`.

## Invariants enforced by the database (beyond the application)
* inventory: non-negative quantities; unique (lot, booking key) - no double booking
* pools: allocated within demand, one pool per demand, one allocation per (pool, lot), events account for every
  kilogram of shortage (`replaced + unresolved >= shortage`), unique event idempotency keys
* marketplace: one order per pool, one item and one participation per allocation, fulfilled <= ordered,
  fulfilled <= item quantity, unique batch codes, positive batch weight, one quality check per batch whose result
  matches its quantities (accepted / partially accepted / rejected)
* notifications: unique (user, dedup key) - the same event never notifies twice


**39 tables.**


### `allocation_ledger`

| Column | Type | Null | Notes |
|---|---|---|---|
| `pool_id` | CHAR(32) | no | FK -> `harvest_pools` (RESTRICT), indexed |
| `allocation_id` | CHAR(32) | yes | FK -> `harvest_allocations` (RESTRICT) |
| `lot_id` | CHAR(32) | no | FK -> `inventory_lots` (RESTRICT) |
| `action` | VARCHAR(32) | no |  |
| `quantity_before` | NUMERIC(14, 3) | no |  |
| `quantity_after` | NUMERIC(14, 3) | no |  |
| `reason` | TEXT | no |  |
| `reallocation_event_id` | CHAR(32) | yes | FK -> `reallocation_events` (RESTRICT) |
| `actor_id` | CHAR(32) | yes | FK -> `users` (RESTRICT) |
| `created_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

Constraints: CHECK `ck_allocation_ledger_quantities_non_negative`: `quantity_before >= 0 AND quantity_after >= 0`

### `buyer_demands`

| Column | Type | Null | Notes |
|---|---|---|---|
| `buyer_id` | CHAR(32) | no | FK -> `users` (RESTRICT), indexed |
| `crop_id` | CHAR(32) | no | FK -> `crops` (RESTRICT), indexed |
| `quantity_kg` | NUMERIC(14, 3) | no |  |
| `min_grade` | VARCHAR(2) | no |  |
| `window_start` | DATE | no |  |
| `window_end` | DATE | no |  |
| `latitude` | NUMERIC(9, 6) | yes |  |
| `longitude` | NUMERIC(9, 6) | yes |  |
| `max_distance_km` | NUMERIC(8, 1) | yes |  |
| `min_confidence` | NUMERIC(4, 1) | no |  |
| `max_risk` | NUMERIC(4, 1) | no |  |
| `status` | VARCHAR(16) | no |  |
| `notes` | TEXT | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_buyer_demands_coordinates_paired`: `(latitude IS NULL) = (longitude IS NULL)`; CHECK `ck_buyer_demands_demand_status`: `buyer_demands.status IN (__[POSTCOMPILE_param_1])`; CHECK `ck_buyer_demands_distance_positive`: `max_distance_km IS NULL OR max_distance_km > 0`; CHECK `ck_buyer_demands_min_grade`: `buyer_demands.min_grade IN (__[POSTCOMPILE_param_1])`; CHECK `ck_buyer_demands_quantity_positive`: `quantity_kg > 0`; CHECK `ck_buyer_demands_thresholds_range`: `min_confidence BETWEEN 0 AND 100 AND max_risk BETWEEN 0 AND 100`; CHECK `ck_buyer_demands_window_ordered`: `window_end >= window_start`

### `buyer_order_items`

| Column | Type | Null | Notes |
|---|---|---|---|
| `order_id` | CHAR(32) | no | FK -> `buyer_orders` (RESTRICT), indexed |
| `allocation_id` | CHAR(32) | no | FK -> `harvest_allocations` (RESTRICT) |
| `lot_id` | CHAR(32) | no | FK -> `inventory_lots` (RESTRICT), indexed |
| `farmer_id` | CHAR(32) | no | FK -> `users` (RESTRICT), indexed |
| `participation_id` | CHAR(32) | no | FK -> `farmer_participations` (RESTRICT) |
| `quantity_kg` | NUMERIC(14, 3) | no |  |
| `fulfilled_kg` | NUMERIC(14, 3) | no |  |
| `status` | VARCHAR(24) | no |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_buyer_order_items_fulfilled_within_item`: `fulfilled_kg <= quantity_kg`; CHECK `ck_buyer_order_items_order_item_status`: `buyer_order_items.status IN (__[POSTCOMPILE_param_1])`; CHECK `ck_buyer_order_items_quantities_non_negative`: `quantity_kg >= 0 AND fulfilled_kg >= 0`; UNIQUE (allocation_id)

### `buyer_orders`

| Column | Type | Null | Notes |
|---|---|---|---|
| `buyer_id` | CHAR(32) | no | FK -> `users` (RESTRICT), indexed |
| `pool_id` | CHAR(32) | no | FK -> `harvest_pools` (RESTRICT) |
| `status` | VARCHAR(24) | no |  |
| `ordered_kg` | NUMERIC(14, 3) | no |  |
| `fulfilled_kg` | NUMERIC(14, 3) | no |  |
| `delivery_hub_id` | CHAR(32) | yes | FK -> `collection_hubs` (RESTRICT) |
| `notes` | TEXT | yes |  |
| `idempotency_key` | VARCHAR(80) | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |
| `version` | INTEGER | no |  |

Constraints: CHECK `ck_buyer_orders_fulfilled_within_order`: `fulfilled_kg >= 0 AND fulfilled_kg <= ordered_kg`; CHECK `ck_buyer_orders_order_status`: `buyer_orders.status IN (__[POSTCOMPILE_param_1])`; CHECK `ck_buyer_orders_ordered_positive`: `ordered_kg > 0`; UNIQUE (buyer_id, idempotency_key); UNIQUE (pool_id)

### `buyer_profiles`

| Column | Type | Null | Notes |
|---|---|---|---|
| `user_id` | CHAR(32) | no | FK -> `users` (CASCADE), unique |
| `business_name` | VARCHAR(160) | no |  |
| `buyer_type` | VARCHAR(16) | no |  |
| `city` | VARCHAR(100) | yes |  |
| `district` | VARCHAR(100) | yes |  |
| `state` | VARCHAR(100) | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_buyer_profiles_buyer_type`: `buyer_profiles.buyer_type IN (__[POSTCOMPILE_param_1])`; UNIQUE (user_id)

### `calibration_profiles`

| Column | Type | Null | Notes |
|---|---|---|---|
| `scope` | VARCHAR(64) | no |  |
| `crop_id` | CHAR(32) | yes | FK -> `crops` (RESTRICT), indexed |
| `version` | INTEGER | no |  |
| `sample_size` | INTEGER | no |  |
| `sufficient` | BOOLEAN | no |  |
| `coverage` | NUMERIC(6, 4) | yes |  |
| `mape` | NUMERIC(10, 2) | yes |  |
| `bias_factor` | NUMERIC(6, 4) | no |  |
| `interval_scale` | NUMERIC(6, 4) | no |  |
| `date_mae_days` | NUMERIC(8, 1) | yes |  |
| `note` | TEXT | no |  |
| `created_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

Constraints: CHECK `ck_calibration_profiles_factors_positive`: `bias_factor > 0 AND interval_scale > 0`; CHECK `ck_calibration_profiles_sample_size_non_negative`: `sample_size >= 0`; UNIQUE (scope, version)

### `collection_hubs`

| Column | Type | Null | Notes |
|---|---|---|---|
| `name` | VARCHAR(120) | no |  |
| `district` | VARCHAR(100) | yes |  |
| `address` | VARCHAR(255) | yes |  |
| `latitude` | NUMERIC(9, 6) | yes |  |
| `longitude` | NUMERIC(9, 6) | yes |  |
| `is_active` | BOOLEAN | no |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_collection_hubs_coordinates_paired`: `(latitude IS NULL) = (longitude IS NULL)`; UNIQUE (name)

### `crop_cycles`

| Column | Type | Null | Notes |
|---|---|---|---|
| `plot_id` | CHAR(32) | no | FK -> `farm_plots` (RESTRICT) |
| `crop_id` | CHAR(32) | no | FK -> `crops` (RESTRICT), indexed |
| `variety` | VARCHAR(80) | yes |  |
| `status` | VARCHAR(24) | no |  |
| `area_acres` | NUMERIC(10, 3) | no |  |
| `sowing_date` | DATE | no |  |
| `expected_harvest_date` | DATE | yes |  |
| `actual_harvest_date` | DATE | yes |  |
| `notes` | TEXT | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_crop_cycles_actual_not_before_sowing`: `actual_harvest_date IS NULL OR actual_harvest_date >= sowing_date`; CHECK `ck_crop_cycles_area_positive`: `area_acres > 0`; CHECK `ck_crop_cycles_cycle_status`: `crop_cycles.status IN (__[POSTCOMPILE_param_1])`; CHECK `ck_crop_cycles_expected_after_sowing`: `expected_harvest_date IS NULL OR expected_harvest_date > sowing_date`; CHECK `ck_crop_cycles_harvest_date_iff_harvested`: `(status = 'harvested') = (actual_harvest_date IS NOT NULL)`

### `crop_health_analyses`

| Column | Type | Null | Notes |
|---|---|---|---|
| `owner_id` | CHAR(32) | no | FK -> `users` (CASCADE), indexed |
| `crop_cycle_id` | CHAR(32) | yes | FK -> `crop_cycles` (CASCADE) |
| `image_sha256` | VARCHAR(64) | no |  |
| `width` | INTEGER | no |  |
| `height` | INTEGER | no |  |
| `label` | VARCHAR(24) | no |  |
| `probabilities` | JSON | no |  |
| `features` | JSON | no |  |
| `model_name` | VARCHAR(40) | no |  |
| `model_version` | VARCHAR(16) | no |  |
| `created_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

Constraints: CHECK `ck_crop_health_analyses_crop_health_class`: `crop_health_analyses.label IN (__[POSTCOMPILE_param_1])`; CHECK `ck_crop_health_analyses_dimensions_positive`: `width > 0 AND height > 0`

### `crop_observations`

| Column | Type | Null | Notes |
|---|---|---|---|
| `crop_cycle_id` | CHAR(32) | no | FK -> `crop_cycles` (RESTRICT) |
| `observed_on` | DATE | no |  |
| `growth_stage` | VARCHAR(24) | yes |  |
| `health_status` | VARCHAR(24) | no |  |
| `estimated_loss_percent` | NUMERIC(5, 2) | yes |  |
| `notes` | TEXT | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_crop_observations_growth_stage`: `crop_observations.growth_stage IN (__[POSTCOMPILE_param_1])`; CHECK `ck_crop_observations_health_status`: `crop_observations.health_status IN (__[POSTCOMPILE_param_1])`; CHECK `ck_crop_observations_loss_percent_range`: `estimated_loss_percent IS NULL OR (estimated_loss_percent >= 0 AND estimated_loss_percent <= 100)`

### `crop_plan_items`

| Column | Type | Null | Notes |
|---|---|---|---|
| `plan_id` | CHAR(32) | no | FK -> `crop_plans` (CASCADE) |
| `crop_id` | CHAR(32) | yes | FK -> `crops` (RESTRICT), indexed |
| `position` | INTEGER | no |  |
| `crop_name` | VARCHAR(80) | no |  |
| `area_acres` | NUMERIC(10, 3) | no |  |
| `sowing_date` | DATE | no |  |
| `duration_days` | INTEGER | no |  |
| `harvest_window_days` | INTEGER | no |  |
| `batches` | INTEGER | no |  |
| `batch_interval_days` | INTEGER | yes |  |
| `yield_low_kg` | NUMERIC(12, 3) | no |  |
| `yield_expected_kg` | NUMERIC(12, 3) | no |  |
| `yield_high_kg` | NUMERIC(12, 3) | no |  |
| `price_low` | NUMERIC(12, 2) | no |  |
| `price_expected` | NUMERIC(12, 2) | no |  |
| `price_high` | NUMERIC(12, 2) | no |  |
| `seed_cost` | NUMERIC(12, 2) | no |  |
| `fertilizer_cost` | NUMERIC(12, 2) | no |  |
| `pesticide_cost` | NUMERIC(12, 2) | no |  |
| `irrigation_cost` | NUMERIC(12, 2) | no |  |
| `machinery_cost` | NUMERIC(12, 2) | no |  |
| `other_cost` | NUMERIC(12, 2) | no |  |
| `labour_person_days` | NUMERIC(8, 2) | no |  |
| `labour_wage` | NUMERIC(10, 2) | no |  |
| `fixed_cost` | NUMERIC(14, 2) | no |  |
| `cost_overrun_pct` | NUMERIC(6, 2) | yes |  |
| `water_kl_per_acre` | NUMERIC(12, 2) | yes |  |
| `demand_level` | VARCHAR(24) | no |  |
| `demand_quantity_kg` | NUMERIC(14, 3) | yes |  |
| `declared_risk` | VARCHAR(24) | no |  |
| `estimate_basis` | VARCHAR(24) | no |  |
| `notes` | TEXT | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_crop_plan_items_area_positive`: `area_acres > 0`; CHECK `ck_crop_plan_items_batch_interval_required`: `batches = 1 OR (batch_interval_days IS NOT NULL AND batch_interval_days >= 1)`; CHECK `ck_crop_plan_items_batches_range`: `batches BETWEEN 1 AND 12`; CHECK `ck_crop_plan_items_costs_non_negative`: `seed_cost >= 0 AND fertilizer_cost >= 0 AND pesticide_cost >= 0 AND irrigation_cost >= 0 AND machinery_cost >= 0 AND other_cost >= 0 AND lab`; CHECK `ck_crop_plan_items_declared_risk`: `crop_plan_items.declared_risk IN (__[POSTCOMPILE_param_1])`; CHECK `ck_crop_plan_items_demand_level`: `crop_plan_items.demand_level IN (__[POSTCOMPILE_param_1])`; CHECK `ck_crop_plan_items_demand_positive`: `demand_quantity_kg IS NULL OR demand_quantity_kg > 0`; CHECK `ck_crop_plan_items_duration_positive`: `duration_days > 0`; CHECK `ck_crop_plan_items_estimate_basis`: `crop_plan_items.estimate_basis IN (__[POSTCOMPILE_param_1])`; CHECK `ck_crop_plan_items_harvest_window_range`: `harvest_window_days BETWEEN 1 AND 365`; CHECK `ck_crop_plan_items_overrun_non_negative`: `cost_overrun_pct IS NULL OR cost_overrun_pct >= 0`; CHECK `ck_crop_plan_items_price_ordered`: `price_low >= 0 AND price_low <= price_expected AND price_expected <= price_high AND price_expected > 0`; CHECK `ck_crop_plan_items_water_non_negative`: `water_kl_per_acre IS NULL OR water_kl_per_acre >= 0`; CHECK `ck_crop_plan_items_yield_ordered`: `yield_low_kg >= 0 AND yield_low_kg <= yield_expected_kg AND yield_expected_kg <= yield_high_kg AND yield_expected_kg > 0`

### `crop_plans`

| Column | Type | Null | Notes |
|---|---|---|---|
| `owner_id` | CHAR(32) | no | FK -> `users` (RESTRICT) |
| `farm_id` | CHAR(32) | yes | FK -> `farms` (RESTRICT), indexed |
| `name` | VARCHAR(120) | no |  |
| `description` | TEXT | yes |  |
| `season` | VARCHAR(24) | no |  |
| `available_land_acres` | NUMERIC(10, 3) | no |  |
| `budget_inr` | NUMERIC(14, 2) | yes |  |
| `available_water_kl` | NUMERIC(14, 3) | yes |  |
| `available_labour_person_days` | NUMERIC(12, 2) | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_crop_plans_budget_positive`: `budget_inr IS NULL OR budget_inr > 0`; CHECK `ck_crop_plans_labour_positive`: `available_labour_person_days IS NULL OR available_labour_person_days > 0`; CHECK `ck_crop_plans_land_positive`: `available_land_acres > 0`; CHECK `ck_crop_plans_plan_season`: `crop_plans.season IN (__[POSTCOMPILE_param_1])`; CHECK `ck_crop_plans_water_positive`: `available_water_kl IS NULL OR available_water_kl > 0`; UNIQUE (owner_id, name)

### `crops`

| Column | Type | Null | Notes |
|---|---|---|---|
| `name` | VARCHAR(80) | no | unique |
| `local_name` | VARCHAR(80) | yes |  |
| `category` | VARCHAR(24) | no |  |
| `typical_duration_days` | INTEGER | no |  |
| `season` | VARCHAR(24) | yes |  |
| `notes` | TEXT | yes |  |
| `is_active` | BOOLEAN | no |  |
| `reference_yield_kg_per_acre` | NUMERIC(12, 3) | yes |  |
| `reference_yield_cv` | NUMERIC(4, 3) | yes |  |
| `water_need_mm` | NUMERIC(8, 1) | yes |  |
| `scientific_name` | VARCHAR(120) | yes |  |
| `aliases` | JSON | no |  |
| `crop_group` | VARCHAR(24) | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_crops_crop_category`: `crops.category IN (__[POSTCOMPILE_param_1])`; CHECK `ck_crops_crop_group`: `crops.crop_group IN (__[POSTCOMPILE_param_1])`; CHECK `ck_crops_crop_season`: `crops.season IN (__[POSTCOMPILE_param_1])`; CHECK `ck_crops_duration_range`: `typical_duration_days > 0 AND typical_duration_days <= 3650`; UNIQUE (name)

### `farm_activities`

| Column | Type | Null | Notes |
|---|---|---|---|
| `farm_id` | CHAR(32) | no | FK -> `farms` (RESTRICT) |
| `plot_id` | CHAR(32) | yes | FK -> `farm_plots` (RESTRICT), indexed |
| `crop_cycle_id` | CHAR(32) | yes | FK -> `crop_cycles` (RESTRICT), indexed |
| `activity_type` | VARCHAR(24) | no |  |
| `activity_date` | DATE | no |  |
| `description` | TEXT | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_farm_activities_activity_type`: `farm_activities.activity_type IN (__[POSTCOMPILE_param_1])`

### `farm_expenses`

| Column | Type | Null | Notes |
|---|---|---|---|
| `farm_id` | CHAR(32) | no | FK -> `farms` (RESTRICT) |
| `crop_cycle_id` | CHAR(32) | yes | FK -> `crop_cycles` (RESTRICT), indexed |
| `category` | VARCHAR(24) | no |  |
| `amount` | NUMERIC(12, 2) | no |  |
| `expense_date` | DATE | no |  |
| `description` | VARCHAR(255) | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_farm_expenses_amount_positive`: `amount > 0`; CHECK `ck_farm_expenses_expense_category`: `farm_expenses.category IN (__[POSTCOMPILE_param_1])`

### `farm_plots`

| Column | Type | Null | Notes |
|---|---|---|---|
| `farm_id` | CHAR(32) | no | FK -> `farms` (RESTRICT) |
| `name` | VARCHAR(100) | no |  |
| `area_acres` | NUMERIC(10, 3) | no |  |
| `soil_type` | VARCHAR(24) | yes |  |
| `irrigation_type` | VARCHAR(24) | yes |  |
| `notes` | TEXT | yes |  |
| `is_active` | BOOLEAN | no |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_farm_plots_area_positive`: `area_acres > 0`; CHECK `ck_farm_plots_irrigation_type`: `farm_plots.irrigation_type IN (__[POSTCOMPILE_param_1])`; CHECK `ck_farm_plots_soil_type`: `farm_plots.soil_type IN (__[POSTCOMPILE_param_1])`; UNIQUE (farm_id, name)

### `farmer_participations`

| Column | Type | Null | Notes |
|---|---|---|---|
| `allocation_id` | CHAR(32) | no | FK -> `harvest_allocations` (RESTRICT) |
| `farmer_id` | CHAR(32) | no | FK -> `users` (RESTRICT), indexed |
| `status` | VARCHAR(16) | no |  |
| `responded_at` | DATETIME | yes |  |
| `reason` | VARCHAR(255) | yes |  |
| `progress` | VARCHAR(16) | yes |  |
| `progress_at` | DATETIME | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_farmer_participations_farmer_progress`: `farmer_participations.progress IN (__[POSTCOMPILE_param_1])`; CHECK `ck_farmer_participations_participation_status`: `farmer_participations.status IN (__[POSTCOMPILE_param_1])`; UNIQUE (allocation_id)

### `farmer_profiles`

| Column | Type | Null | Notes |
|---|---|---|---|
| `user_id` | CHAR(32) | no | FK -> `users` (CASCADE), unique |
| `village` | VARCHAR(100) | yes |  |
| `district` | VARCHAR(100) | yes |  |
| `state` | VARCHAR(100) | yes |  |
| `preferred_language` | VARCHAR(5) | no |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_farmer_profiles_preferred_language`: `farmer_profiles.preferred_language IN (__[POSTCOMPILE_param_1])`; UNIQUE (user_id)

### `farms`

| Column | Type | Null | Notes |
|---|---|---|---|
| `owner_id` | CHAR(32) | no | FK -> `users` (RESTRICT) |
| `name` | VARCHAR(120) | no |  |
| `village` | VARCHAR(100) | yes |  |
| `district` | VARCHAR(100) | yes |  |
| `state` | VARCHAR(100) | yes |  |
| `latitude` | NUMERIC(9, 6) | yes |  |
| `longitude` | NUMERIC(9, 6) | yes |  |
| `total_area_acres` | NUMERIC(10, 3) | no |  |
| `notes` | TEXT | yes |  |
| `is_active` | BOOLEAN | no |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_farms_area_positive`: `total_area_acres > 0`; CHECK `ck_farms_coordinates_paired`: `(latitude IS NULL) = (longitude IS NULL)`; CHECK `ck_farms_latitude_range`: `latitude BETWEEN -90 AND 90`; CHECK `ck_farms_longitude_range`: `longitude BETWEEN -180 AND 180`; UNIQUE (owner_id, name)

### `harvest_actuals`

| Column | Type | Null | Notes |
|---|---|---|---|
| `crop_cycle_id` | CHAR(32) | no | FK -> `crop_cycles` (RESTRICT), unique |
| `quantity_kg` | NUMERIC(14, 3) | no |  |
| `harvest_start_date` | DATE | no |  |
| `recorded_by` | CHAR(32) | no | FK -> `users` (RESTRICT) |
| `created_at` | DATETIME | no |  |
| `previous_quantity_kg` | NUMERIC(14, 3) | yes |  |
| `corrected_at` | DATETIME | yes |  |
| `correction_reason` | VARCHAR(255) | yes |  |
| `id` | CHAR(32) | no | PK |

Constraints: CHECK `ck_harvest_actuals_quantity_non_negative`: `quantity_kg >= 0`; UNIQUE (crop_cycle_id)

### `harvest_allocations`

| Column | Type | Null | Notes |
|---|---|---|---|
| `pool_id` | CHAR(32) | no | FK -> `harvest_pools` (RESTRICT), indexed |
| `lot_id` | CHAR(32) | no | FK -> `inventory_lots` (RESTRICT), indexed |
| `member_id` | CHAR(32) | no | FK -> `harvest_pool_members` (RESTRICT) |
| `quantity_kg` | NUMERIC(14, 3) | no |  |
| `status` | VARCHAR(16) | no |  |
| `risk_level` | VARCHAR(20) | no |  |
| `reservation_id` | CHAR(32) | yes | FK -> `inventory_reservations` (RESTRICT) |
| `reservation_seq` | INTEGER | no |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_harvest_allocations_allocation_status`: `harvest_allocations.status IN (__[POSTCOMPILE_param_1])`; CHECK `ck_harvest_allocations_quantity_non_negative`: `quantity_kg >= 0`; UNIQUE (pool_id, lot_id)

### `harvest_pool_members`

| Column | Type | Null | Notes |
|---|---|---|---|
| `pool_id` | CHAR(32) | no | FK -> `harvest_pools` (RESTRICT), indexed |
| `lot_id` | CHAR(32) | no | FK -> `inventory_lots` (RESTRICT), indexed |
| `score` | NUMERIC(5, 2) | no |  |
| `components` | JSON | no |  |
| `excluded` | BOOLEAN | no |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: UNIQUE (pool_id, lot_id)

### `harvest_pools`

| Column | Type | Null | Notes |
|---|---|---|---|
| `demand_id` | CHAR(32) | no | FK -> `buyer_demands` (RESTRICT) |
| `buyer_id` | CHAR(32) | no | FK -> `users` (RESTRICT), indexed |
| `status` | VARCHAR(16) | no |  |
| `algorithm` | VARCHAR(16) | no |  |
| `demand_kg` | NUMERIC(14, 3) | no |  |
| `allocated_kg` | NUMERIC(14, 3) | no |  |
| `shortage_kg` | NUMERIC(14, 3) | no |  |
| `max_pool_risk` | NUMERIC(4, 1) | no |  |
| `max_share` | NUMERIC(4, 3) | no |  |
| `weights` | JSON | no |  |
| `idempotency_key` | VARCHAR(80) | yes |  |
| `closed_at` | DATETIME | yes |  |
| `close_reason` | VARCHAR(80) | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |
| `version` | INTEGER | no |  |

Constraints: CHECK `ck_harvest_pools_allocated_within_demand`: `allocated_kg >= 0 AND allocated_kg <= demand_kg`; CHECK `ck_harvest_pools_pool_algorithm`: `harvest_pools.algorithm IN (__[POSTCOMPILE_param_1])`; CHECK `ck_harvest_pools_pool_status`: `harvest_pools.status IN (__[POSTCOMPILE_param_1])`; CHECK `ck_harvest_pools_shortage_non_negative`: `shortage_kg >= 0`; UNIQUE (buyer_id, idempotency_key); UNIQUE (demand_id)

### `inventory_lots`

| Column | Type | Null | Notes |
|---|---|---|---|
| `crop_cycle_id` | CHAR(32) | no | FK -> `crop_cycles` (RESTRICT), unique |
| `owner_id` | CHAR(32) | no | FK -> `users` (RESTRICT), indexed |
| `prediction_id` | CHAR(32) | yes | FK -> `yield_predictions` (RESTRICT) |
| `status` | VARCHAR(16) | no |  |
| `p10_kg` | NUMERIC(14, 3) | yes |  |
| `p50_kg` | NUMERIC(14, 3) | yes |  |
| `p90_kg` | NUMERIC(14, 3) | yes |  |
| `actual_kg` | NUMERIC(14, 3) | yes |  |
| `committable_kg` | NUMERIC(14, 3) | no |  |
| `committed_kg` | NUMERIC(14, 3) | no |  |
| `available_kg` | NUMERIC(14, 3) | no |  |
| `shortfall_kg` | NUMERIC(14, 3) | no |  |
| `basis` | VARCHAR(80) | no |  |
| `pool_eligible` | BOOLEAN | no |  |
| `expected_grade` | VARCHAR(2) | no |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_inventory_lots_expected_grade`: `inventory_lots.expected_grade IN (__[POSTCOMPILE_param_1])`; CHECK `ck_inventory_lots_lot_status`: `inventory_lots.status IN (__[POSTCOMPILE_param_1])`; CHECK `ck_inventory_lots_quantities_non_negative`: `committable_kg >= 0 AND committed_kg >= 0 AND available_kg >= 0 AND shortfall_kg >= 0`; UNIQUE (crop_cycle_id)

### `inventory_reservations`

| Column | Type | Null | Notes |
|---|---|---|---|
| `lot_id` | CHAR(32) | no | FK -> `inventory_lots` (RESTRICT), indexed |
| `quantity_kg` | NUMERIC(14, 3) | no |  |
| `booking_key` | VARCHAR(80) | no |  |
| `status` | VARCHAR(16) | no |  |
| `note` | VARCHAR(255) | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_inventory_reservations_quantity_positive`: `quantity_kg > 0`; CHECK `ck_inventory_reservations_reservation_status`: `inventory_reservations.status IN (__[POSTCOMPILE_param_1])`; UNIQUE (lot_id, booking_key)

### `login_attempts`

| Column | Type | Null | Notes |
|---|---|---|---|
| `phone` | VARCHAR(16) | no |  |
| `succeeded` | BOOLEAN | no |  |
| `attempted_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

### `market_prices`

| Column | Type | Null | Notes |
|---|---|---|---|
| `state` | VARCHAR(60) | no | indexed |
| `district` | VARCHAR(80) | no |  |
| `market` | VARCHAR(120) | no |  |
| `commodity` | VARCHAR(80) | no | indexed |
| `variety` | VARCHAR(80) | no |  |
| `grade` | VARCHAR(40) | no |  |
| `arrival_date` | DATE | no |  |
| `min_price` | NUMERIC(10, 2) | no |  |
| `modal_price` | NUMERIC(10, 2) | no |  |
| `max_price` | NUMERIC(10, 2) | no |  |
| `source` | VARCHAR(40) | no |  |
| `fetched_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

Constraints: CHECK `ck_market_prices_prices_ordered`: `min_price > 0 AND min_price <= modal_price AND modal_price <= max_price`; UNIQUE (state, district, market, commodity, variety, grade, arrival_date)

### `notifications`

| Column | Type | Null | Notes |
|---|---|---|---|
| `user_id` | CHAR(32) | no | FK -> `users` (CASCADE) |
| `category` | VARCHAR(32) | no |  |
| `title` | VARCHAR(160) | no |  |
| `body` | TEXT | no |  |
| `severity` | VARCHAR(16) | no |  |
| `data` | JSON | no |  |
| `dedup_key` | VARCHAR(160) | no |  |
| `read_at` | DATETIME | yes |  |
| `created_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

Constraints: CHECK `ck_notifications_notification_category`: `notifications.category IN (__[POSTCOMPILE_param_1])`; UNIQUE (user_id, dedup_key)

### `otp_challenges`

| Column | Type | Null | Notes |
|---|---|---|---|
| `user_id` | CHAR(32) | yes | FK -> `users` (SET NULL), indexed |
| `purpose` | VARCHAR(16) | no |  |
| `phone` | VARCHAR(16) | no |  |
| `code_hash` | VARCHAR(64) | no |  |
| `decoy` | BOOLEAN | no |  |
| `expires_at` | DATETIME | no |  |
| `attempts` | INTEGER | no |  |
| `sends` | INTEGER | no |  |
| `last_sent_at` | DATETIME | no |  |
| `consumed_at` | DATETIME | yes |  |
| `client` | VARCHAR(64) | yes |  |
| `created_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

Constraints: CHECK `ck_otp_challenges_otp_purpose`: `otp_challenges.purpose IN (__[POSTCOMPILE_param_1])`

### `prediction_feedback`

| Column | Type | Null | Notes |
|---|---|---|---|
| `prediction_id` | CHAR(32) | no | FK -> `yield_predictions` (RESTRICT), unique |
| `harvest_actual_id` | CHAR(32) | no | FK -> `harvest_actuals` (RESTRICT), indexed |
| `signed_error_kg` | NUMERIC(14, 3) | no |  |
| `abs_error_kg` | NUMERIC(14, 3) | no |  |
| `abs_pct_error` | NUMERIC(10, 2) | yes |  |
| `within_interval` | BOOLEAN | no |  |
| `pinball_loss` | NUMERIC(14, 3) | no |  |
| `date_error_days` | INTEGER | yes |  |
| `date_within_window` | BOOLEAN | yes |  |
| `created_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

Constraints: UNIQUE (prediction_id)

### `produce_batches`

| Column | Type | Null | Notes |
|---|---|---|---|
| `code` | VARCHAR(24) | no |  |
| `order_item_id` | CHAR(32) | no | FK -> `buyer_order_items` (RESTRICT) |
| `lot_id` | CHAR(32) | no | FK -> `inventory_lots` (RESTRICT) |
| `harvest_actual_id` | CHAR(32) | no | FK -> `harvest_actuals` (RESTRICT) |
| `hub_id` | CHAR(32) | no | FK -> `collection_hubs` (RESTRICT), indexed |
| `received_kg` | NUMERIC(14, 3) | no |  |
| `received_at` | DATETIME | no |  |
| `received_by` | CHAR(32) | no | FK -> `users` (RESTRICT) |
| `status` | VARCHAR(16) | no |  |
| `notes` | TEXT | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_produce_batches_batch_status`: `produce_batches.status IN (__[POSTCOMPILE_param_1])`; CHECK `ck_produce_batches_received_positive`: `received_kg > 0`; UNIQUE (code)

### `produce_gradings`

| Column | Type | Null | Notes |
|---|---|---|---|
| `harvest_actual_id` | CHAR(32) | no | FK -> `harvest_actuals` (RESTRICT), unique |
| `owner_id` | CHAR(32) | no | FK -> `users` (RESTRICT), indexed |
| `profile` | VARCHAR(16) | no |  |
| `criteria_version` | INTEGER | no |  |
| `proposal_status` | VARCHAR(24) | yes |  |
| `proposal_reason` | VARCHAR(40) | yes |  |
| `proposed_levels` | JSON | yes |  |
| `proposed_grade` | VARCHAR(2) | yes |  |
| `proposal_details` | JSON | yes |  |
| `proposed_at` | DATETIME | yes |  |
| `levels` | JSON | yes |  |
| `criteria_grade` | VARCHAR(2) | yes |  |
| `grade` | VARCHAR(2) | yes |  |
| `grade_source` | VARCHAR(16) | yes |  |
| `override_reason` | VARCHAR(255) | yes |  |
| `confirmed_at` | DATETIME | yes |  |
| `confirmed_by` | CHAR(32) | yes | FK -> `users` (RESTRICT) |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_produce_gradings_criteria_grade_with_grade`: `(grade IS NULL) = (criteria_grade IS NULL)`; CHECK `ck_produce_gradings_criteria_grade`: `produce_gradings.criteria_grade IN (__[POSTCOMPILE_param_1])`; CHECK `ck_produce_gradings_grade_iff_confirmed`: `(grade IS NULL) = (confirmed_at IS NULL)`; CHECK `ck_produce_gradings_grade_not_above_criteria`: `grade IS NULL OR grade >= criteria_grade`; CHECK `ck_produce_gradings_grade_source_known`: `grade_source IS NULL OR grade_source IN ('manual', 'photo_confirmed', 'photo_corrected')`; CHECK `ck_produce_gradings_produce_grade`: `produce_gradings.grade IN (__[POSTCOMPILE_param_1])`; CHECK `ck_produce_gradings_proposal_status_known`: `proposal_status IS NULL OR proposal_status IN ('proposed', 'needs_more_evidence', 'retake_photo', 'unavailable')`; CHECK `ck_produce_gradings_proposed_grade`: `produce_gradings.proposed_grade IN (__[POSTCOMPILE_param_1])`; UNIQUE (harvest_actual_id)

### `quality_checks`

| Column | Type | Null | Notes |
|---|---|---|---|
| `batch_id` | CHAR(32) | no | FK -> `produce_batches` (RESTRICT) |
| `inspector_id` | CHAR(32) | no | FK -> `users` (RESTRICT) |
| `grade` | VARCHAR(2) | yes |  |
| `result` | VARCHAR(24) | no |  |
| `accepted_kg` | NUMERIC(14, 3) | no |  |
| `rejected_kg` | NUMERIC(14, 3) | no |  |
| `moisture_percent` | NUMERIC(5, 2) | yes |  |
| `defects` | TEXT | yes |  |
| `checked_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

Constraints: CHECK `ck_quality_checks_moisture_range`: `moisture_percent IS NULL OR (moisture_percent >= 0 AND moisture_percent <= 100)`; CHECK `ck_quality_checks_quality_grade`: `quality_checks.grade IN (__[POSTCOMPILE_param_1])`; CHECK `ck_quality_checks_quality_result`: `quality_checks.result IN (__[POSTCOMPILE_param_1])`; CHECK `ck_quality_checks_quantities_non_negative`: `accepted_kg >= 0 AND rejected_kg >= 0`; CHECK `ck_quality_checks_result_matches_quantities`: `(result = 'accepted' AND rejected_kg = 0 AND accepted_kg > 0) OR (result = 'rejected' AND accepted_kg = 0) OR (result = 'partially_accepted'`; UNIQUE (batch_id)

### `reallocation_events`

| Column | Type | Null | Notes |
|---|---|---|---|
| `pool_id` | CHAR(32) | no | FK -> `harvest_pools` (RESTRICT), indexed |
| `trigger` | VARCHAR(40) | no |  |
| `trigger_ref` | VARCHAR(80) | yes |  |
| `idempotency_key` | VARCHAR(160) | no |  |
| `outcome` | VARCHAR(16) | no |  |
| `algorithm` | VARCHAR(16) | no |  |
| `shortage_kg` | NUMERIC(14, 3) | no |  |
| `replaced_kg` | NUMERIC(14, 3) | no |  |
| `unresolved_kg` | NUMERIC(14, 3) | no |  |
| `topped_up_kg` | NUMERIC(14, 3) | no |  |
| `steps` | INTEGER | no |  |
| `duration_ms` | INTEGER | no |  |
| `reason` | TEXT | no |  |
| `before` | JSON | no |  |
| `after` | JSON | no |  |
| `created_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

Constraints: CHECK `ck_reallocation_events_quantities_non_negative`: `shortage_kg >= 0 AND replaced_kg >= 0 AND unresolved_kg >= 0`; CHECK `ck_reallocation_events_reallocation_outcome`: `reallocation_events.outcome IN (__[POSTCOMPILE_param_1])`; CHECK `ck_reallocation_events_shortage_accounted`: `replaced_kg + unresolved_kg >= shortage_kg - 0.001`; UNIQUE (idempotency_key)

### `refresh_tokens`

| Column | Type | Null | Notes |
|---|---|---|---|
| `user_id` | CHAR(32) | no | FK -> `users` (CASCADE), indexed |
| `family_id` | CHAR(32) | no | indexed |
| `token_hash` | VARCHAR(64) | no | unique |
| `expires_at` | DATETIME | no |  |
| `rotated_at` | DATETIME | yes |  |
| `revoked_at` | DATETIME | yes |  |
| `created_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

Constraints: UNIQUE (token_hash)

### `reminders`

| Column | Type | Null | Notes |
|---|---|---|---|
| `owner_id` | CHAR(32) | no | FK -> `users` (CASCADE) |
| `reminder_type` | VARCHAR(24) | no |  |
| `title` | VARCHAR(160) | no |  |
| `notes` | TEXT | yes |  |
| `due_at` | DATETIME | no |  |
| `recurrence` | VARCHAR(8) | no |  |
| `status` | VARCHAR(16) | no |  |
| `farm_id` | CHAR(32) | yes | FK -> `farms` (CASCADE) |
| `crop_cycle_id` | CHAR(32) | yes | FK -> `crop_cycles` (CASCADE) |
| `source` | VARCHAR(24) | no |  |
| `notified_for` | DATETIME | yes |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_reminders_recurrence`: `reminders.recurrence IN (__[POSTCOMPILE_param_1])`; CHECK `ck_reminders_reminder_status`: `reminders.status IN (__[POSTCOMPILE_param_1])`; CHECK `ck_reminders_reminder_type`: `reminders.reminder_type IN (__[POSTCOMPILE_param_1])`

### `users`

| Column | Type | Null | Notes |
|---|---|---|---|
| `phone` | VARCHAR(16) | no | unique |
| `email` | VARCHAR(254) | yes | unique |
| `password_hash` | VARCHAR(255) | no |  |
| `full_name` | VARCHAR(120) | no |  |
| `role` | VARCHAR(16) | no |  |
| `is_active` | BOOLEAN | no |  |
| `access_status` | VARCHAR(16) | no |  |
| `access_changed_at` | DATETIME | yes |  |
| `last_login_at` | DATETIME | yes |  |
| `phone_verified_at` | DATETIME | yes |  |
| `registration_pending` | BOOLEAN | no |  |
| `must_change_password` | BOOLEAN | no |  |
| `tour_version_seen` | INTEGER | no |  |
| `id` | CHAR(32) | no | PK |
| `created_at` | DATETIME | no |  |
| `updated_at` | DATETIME | no |  |

Constraints: CHECK `ck_users_access_status`: `users.access_status IN (__[POSTCOMPILE_param_1])`; CHECK `ck_users_user_role`: `users.role IN (__[POSTCOMPILE_param_1])`; UNIQUE (email); UNIQUE (phone)

### `weather_daily`

| Column | Type | Null | Notes |
|---|---|---|---|
| `lat_key` | NUMERIC(6, 2) | no |  |
| `lon_key` | NUMERIC(6, 2) | no |  |
| `day` | DATE | no |  |
| `kind` | VARCHAR(16) | no |  |
| `tmin_c` | NUMERIC(5, 2) | no |  |
| `tmax_c` | NUMERIC(5, 2) | no |  |
| `rain_mm` | NUMERIC(7, 2) | no |  |
| `et0_mm` | NUMERIC(6, 2) | yes |  |
| `source` | VARCHAR(40) | no |  |
| `fetched_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

Constraints: CHECK `ck_weather_daily_weather_kind`: `weather_daily.kind IN (__[POSTCOMPILE_param_1])`; UNIQUE (lat_key, lon_key, day, kind)

### `yield_predictions`

| Column | Type | Null | Notes |
|---|---|---|---|
| `crop_cycle_id` | CHAR(32) | no | FK -> `crop_cycles` (RESTRICT), indexed |
| `version` | INTEGER | no |  |
| `status` | VARCHAR(24) | no |  |
| `model_name` | VARCHAR(40) | no |  |
| `model_version` | VARCHAR(20) | no |  |
| `p10_kg` | NUMERIC(14, 3) | yes |  |
| `p50_kg` | NUMERIC(14, 3) | yes |  |
| `p90_kg` | NUMERIC(14, 3) | yes |  |
| `harvest_start_p10` | DATE | no |  |
| `harvest_start_p50` | DATE | no |  |
| `harvest_start_p90` | DATE | no |  |
| `harvest_end_p90` | DATE | no |  |
| `confidence_score` | NUMERIC(4, 1) | no |  |
| `confidence_level` | VARCHAR(16) | no |  |
| `confidence_basis` | VARCHAR(16) | no |  |
| `risk_score` | NUMERIC(4, 1) | yes |  |
| `risk_level` | VARCHAR(20) | no |  |
| `weather_status` | VARCHAR(16) | no |  |
| `calibration_profile_id` | CHAR(32) | yes | FK -> `calibration_profiles` (RESTRICT) |
| `payload` | JSON | no |  |
| `created_at` | DATETIME | no |  |
| `id` | CHAR(32) | no | PK |

Constraints: CHECK `ck_yield_predictions_confidence_range`: `confidence_score BETWEEN 0 AND 100`; CHECK `ck_yield_predictions_dates_ordered`: `harvest_start_p10 <= harvest_start_p50 AND harvest_start_p50 <= harvest_start_p90`; CHECK `ck_yield_predictions_prediction_status`: `yield_predictions.status IN (__[POSTCOMPILE_param_1])`; CHECK `ck_yield_predictions_quantiles_ordered`: `(p50_kg IS NULL) OR (p10_kg >= 0 AND p10_kg <= p50_kg AND p50_kg <= p90_kg)`; CHECK `ck_yield_predictions_version_positive`: `version >= 1`; CHECK `ck_yield_predictions_weather_status`: `yield_predictions.weather_status IN (__[POSTCOMPILE_param_1])`; UNIQUE (crop_cycle_id, version)
