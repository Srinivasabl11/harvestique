# Profit estimation with real mandi prices (2026-10-14)

**Status:**
* Implemented and tested.
* Verified live against the real data.gov.in API (AGMARKNET).
* **Live prices are switched off on your server until you add your own free data.gov.in API key**: see "Turn it
  on" below. Until then the assistant asks for the selling price, as before.

## What the assistant now does
"Estimate my profit from growing tomatoes on one acre" (English or Kannada) gives:
1. **Crop and area.**
2. **Harvest:**
   * what you said;
   * or **what you actually harvested** ("I harvested only 50 kg …": used as the real harvest for that area, never
     as a normal yield, with a note that it is far below the usual range);
   * or your saved plan;
   * or the catalogue reference range, labelled "catalogue estimate, not your farm".
3. **Market price:** the latest AGMARKNET report, chosen in this order:
   * your farm's district (its APMC markets);
   * then your state;
   * then neighbouring states (Tamil Nadu, Andhra Pradesh, Telangana, Kerala, Maharashtra, Goa).
   The answer shows the modal price per quintal and its min–max range, the market(s) or "N markets (median)", the
   variety, the reporting date and its age. Reports older than 30 days are not used. **One variety only**: live
   data mixed Hungund maize "Local" ₹2,450 with "Popcorn" ₹4,700.
4. **Gross revenue:** harvest × price, from the existing income calculator, with low/expected/high when the
   harvest or the price is a range.
5. **Costs:**
   * what you said (per acre or total; asked when unclear);
   * or your saved plan;
   * or **your own recorded expenses for that crop** (latest season, labelled "may be incomplete");
   * otherwise asked for.
6. **Net profit or loss** (a loss is shown as "−₹… (a loss)"), and a cautious case (low harvest, costs 10 % over).
7. **Break-even price** per kg and per quintal.
8. **Risks and assumptions:**
   * prices change daily and differ between markets;
   * APMC prices are wholesale, before commission, transport and grading losses;
   * the harvest depends on weather, pests and variety.

**Quantities that are inputs**, such as "50 kg of seed", seedlings or fertiliser, are **asked about, never used as a
harvest**. The language model never calculates or invents a number.

## Live verification (real data.gov.in, 2026-10-14)
For this one test only, I used the public **sample** key shown in data.gov.in's own examples. It is not stored in
the app. The account was the labelled test farmer; farm data was rolled back. Fetched prices (502 public reports,
tomato and maize, 24 states) stay in the new `market_prices` cache table.

| Question | Result |
|---|---|
| Tomato, 1 acre, cost ₹70,000 | No Karnataka tomato report today → neighbouring states: ₹2,800/quintal modal (241 markets, median), reported 14 Oct 2026; 10,000 kg × ₹28 = ₹2,80,000; profit ₹2,10,000; break-even ₹7/kg; cautious case ₹92,000 |
| Same in Kannada | Same numbers, Kannada text |
| "I harvested only 50 kg … cost 70000" | 50 kg × ₹28 = ₹1,400; −₹68,600 (a loss); break-even ₹1,400/kg; note that 50 kg is far below normal |
| Maize, 2 acres, ₹25,000/acre | Karnataka, Hungund APMC (Local) ₹2,450/quintal, today; 4,000 kg × ₹24.50 = ₹98,000; profit ₹48,000 |
| "I used 50 kg of seed" | Asked whether 50 kg is seed, seedlings or fertiliser; no calculation |

All figures were checked by hand. Raw results: `harvestique-eval-data\results\assistant_profit_live_profit3_20261014.json`.

**Problems found live and fixed:**
* **No answer from data.gov.in:** it silently drops requests that carry Python's default HTTP client name (no reply
  in 60 s; any other name is answered in 0.5 s). The client now identifies itself as Harvestique.
* **Wrong message after a failure:** a failed refresh was then reported as "no price reported"; it now says the
  service did not answer, and retries after 10 minutes.
* **Mixed varieties:** maize prices were blended across varieties. One variety is now chosen.

## Cultivation costs: what was and was not found
* I searched for free government cost-of-cultivation tables for tomato in Karnataka: Horticulture Department,
  UAS, NHB and CACP. None came up in a form I could verify and cite.
* The peer-reviewed paper I checked turned out to be about nursery economics (its only usable field figure is the
  recommended 24,691 seedlings per hectare).
* CACP publishes state-wise cost of production only for MSP crops, inside large report PDFs; none was retrieved.
* **Therefore no reference cost table was invented.** Costs come from the farmer: what they said, their saved plan,
  or their **recorded expenses** in Harvestique. Otherwise the assistant asks.
* Adding a cited table later (e.g. CACP Karnataka cost per quintal for ragi, paddy and maize) is a small change: a
  table with source, year and unit, labelled "historical, not current".

## Turn it on (free)
1. Register at https://data.gov.in, then go to "My Account" and generate an API key.
2. In `.env`, set `MARKET_PRICE_PROVIDER=data_gov_in` and `DATA_GOV_IN_API_KEY=<your key>`.
3. Run `docker compose up -d --build backend`.

The server fetches at most once every 6 hours per crop and state (after a failure, once every 10 minutes), and stores
every report, so the latest available price survives days without reports. If the key is missing or wrong, the
assistant says so and asks for the price.

## Changes
* **Database:** migration `0014_market_prices`, a new cache table only. Backup first:
  `harvestique-backups\harvestique_before_0014_20261014.dump`, read back with `pg_restore --list`, 38 tables. After
  the migration, users, crops and expenses were unchanged (14 / 88 / 8).
* **Backend, new:**
  * `app/providers/market/` (contract, disabled, fake, data.gov.in client)
  * `app/domain/market.py` (price choice, commodity names)
  * `app/services/market_prices.py`
* **Backend, changed:**
  * `app/models/intelligence.py` (`MarketPrice`), `app/models/__init__.py`
  * `app/core/config.py` (settings plus a check that a key exists)
  * `app/core/container.py`, `app/providers/registry.py`, `app/composition.py`
  * `app/domain/assistant/estimate.py` (actual harvest, input quantities)
  * `app/services/assistant.py` (estimate v2)
* `.env.example`, `docs/DATABASE.md` (regenerated).
* **Tests, new:** `tests/unit/test_market_prices.py`, `tests/integration/test_assistant_profit.py`. They cover price
  choice, stale and far-away prices, record parsing, variety, User-Agent, provider off or failing, the district
  price, the Kannada answer, the actual 50 kg harvest, the seed clarification, recorded expenses as cost, and
  break-even.
* Full backend suite: **1648 passed** (ruff, format and mypy clean).
* No Flutter change and no new APK needed: the answer is text in the existing chat.

## Limits
* Prices are wholesale APMC prices, not farm-gate prices. Commission and transport are only included if the farmer
  adds them to the cost.
* "Nearest market" means the farm's district, then state, then the neighbouring states listed. No distances are used,
  because the dataset has no market coordinates.
* The commodity-name list for crops not seen live (e.g. "Cucumbar(Kheera)") follows AGMARKNET's naming. A wrong name
  finds no rows, and the farmer is then asked for a price.
* Yield ranges are catalogue references, not local evidence; the farmer's own or recorded figures take priority.
* Kannada speech of these answers was not tested on the phone.
