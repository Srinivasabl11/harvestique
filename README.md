# Harvestique

Harvestique is a farm-to-buyer platform for Karnataka. Farmers record their farms and crops, get uncertainty-aware
harvest predictions, plan income and land use, and offer their **predicted** harvests to buyers. Buyers state a demand
(crop, quantity, delivery window, minimum grade). Harvestique matches that demand against pessimistic (p10) predicted
supply pooled across several farms. When a farm's prediction falls, it detects the shortage and reallocates the gap
to other farms. Delivery is counted only after a measured harvest, a hub quality check and fulfilment.

It is a final-year engineering research project. Its research core is **Dynamic Predictive Harvest Pooling**:
[docs/HARVEST_POOL.md](docs/HARVEST_POOL.md), [docs/ALGORITHMS.md](docs/ALGORITHMS.md).

> **Which branch is this?** This README describes **`main`**, the project as published on 2026-10-15. Newer work,
> including the hosted production setup, is on the
> [`deploy/free-tier-production`](https://github.com/Srinivasabl11/harvestique/tree/deploy/free-tier-production)
> branch and is **not on `main` yet**:
> * password-only sign-in with admin approval;
> * the farmer's A/B/C produce grade;
> * the upgraded crop-health result (item identification and an A/B/C health category);
> * the cloud deployment files ([render.yaml](https://github.com/Srinivasabl11/harvestique/blob/deploy/free-tier-production/render.yaml),
>   [docs/DEPLOYMENT.md](https://github.com/Srinivasabl11/harvestique/blob/deploy/free-tier-production/docs/DEPLOYMENT.md));
> * the seedling branding.
>
> Sections below mark these as **deployment branch only**.
>
> Harvest predictions are **rule-based estimates, not a trained model**. No real-world prediction accuracy has been
> measured yet (see [Evidence and verification](#14-evidence-and-verification)). AI outputs are advisory.

## Contents
1. [Features and their status](#1-features-and-their-status)
2. [Screenshots](#2-screenshots)
3. [Architecture](#3-architecture)
4. [Predicted harvest vs available produce](#4-predicted-harvest-vs-available-produce)
5. [From farm to buyer: the implemented workflow](#5-from-farm-to-buyer-the-implemented-workflow)
6. [Planning tools](#6-planning-tools)
7. [Harvest prediction](#7-harvest-prediction)
8. [AI in Harvestique](#8-ai-in-harvestique)
9. [Quality grading](#9-quality-grading)
10. [Languages and voice](#10-languages-and-voice)
11. [Accounts and security](#11-accounts-and-security)
12. [Run it locally](#12-run-it-locally)
13. [Deployment](#13-deployment)
14. [Evidence and verification](#14-evidence-and-verification)
15. [Limitations and proposed enhancements](#15-limitations-and-proposed-enhancements)
16. [Documentation index](#16-documentation-index)

## 1. Features and their status

"App" means a screen in the Flutter Android app. "API" means a backend endpoint (all under `/api/v1`). The full,
generated endpoint list for `main` is [docs/API.md](docs/API.md) (142 operations).

| Area | What exists on `main` | Where |
|---|---|---|
| Farms, plots, crop cycles | Create and edit farms, plots and crop cycles. Plot land capacity is enforced over time. Expenses, field work and observations can be recorded. | App + API |
| Crop catalogue | 213 standard crops in 18 groups (86 with a Kannada name); admins can add more | API (seeded); app pickers |
| Harvest prediction | p10/p50/p90 quantity, harvest window, confidence, farm risk; prediction feedback and calibration | App (crop screen) + API |
| Income planning | Saved income plans with a full evaluation (cost, income ranges, land use over time, risk, confidence) | App ("Income plans") + API |
| Cost & income calculator, land utilization planner | One-off calculation and a land-split suggestion | **API only** (`/planning/calculate`, `/planning/suggest-allocation`); not in the app |
| Virtual inventory | Each crop cycle has a lot whose promisable quantity is p10 before harvest and the measured quantity after | App ("Harvest") + API |
| Buyer demand and matching | Demands, ranked matches with reasons, search of future supply | App (buyer) + API |
| Harvest pooling and reallocation | A pool reserves supply across farms. When predictions drop or a farmer declines, shortages are detected and replaced. Every change is in an event log and ledger. | App (buyer pool screen) + API |
| Orders, collection, fulfilment | Order on a pool; farmers accept or decline; hub batches, quality checks, fulfilment and traceability | App (buyer, farmer, admin screens) + API |
| Crop health photo check | Advisory analysis of one photo by a local vision model: a most-likely category with category bars, the signs seen and a 0-10 visual condition score; colour measurements only when no model is configured | App + API |
| Farmer's produce grade (A/B/C) | **Deployment branch only.** On `main` the grade is the lot's expected grade set by the farmer, and the hub's measured quality check. | - |
| Farm assistant | Questions answered from the farmer's own records by fixed tools; voice in English and Kannada | App + API |
| Reminders, notifications, calendar | Reminders and an in-app notification feed (no push notifications) | App + API |
| Weather | Open-Meteo forecast and history for farms that have coordinates | App + API |
| Mandi prices | data.gov.in adapter | Off by default (needs a key) |
| Hosted deployment (Render, Neon, Ollama Cloud) | **Deployment branch only.** `main` runs with Docker Compose. | - |
| Payments, contracts, prices on orders | **Not implemented.** Orders carry quantities only. | - |

## 2. Screenshots

These are genuine screenshots of the Android app. Every original photo is copied byte for byte: no resizing,
cropping, redaction or retouching.

* **Emulator set** (5 images marked "emulator"): debug build on the Android emulator, 2026-10-16, test accounts
  on a throwaway local server.
* **Phone set** (99 original photos): an Android phone, mostly 2026-10-25, with the project author's own test
  accounts. Names, mobile numbers and test data appear as captured, published with the author's permission. The
  farms, crops, demands and orders are test data: farm `f1` (1 acre), a tomato crop and a test buyer ("vasa business").
  The source folder holds some screenshots more than once. Each copy is included, and the identical copies are
  listed at the end.

> **Branch:** both sets come from the **`deploy/free-tier-production`** build, not `main`, except the sign-in code
> screen, which comes from an earlier build that matches `main`. On `main` the screens have the same layout but show
> the earlier Karnataka-flag artwork instead of the seedling photo. Captions mark screens that exist on only one
> branch (checked against each branch's app source). A screenshot here does not prove a feature is on `main`.

**Gallery:** [Sign-in and accounts](#sign-in-and-accounts) · [Farmer home](#farmer-home) · [Farm, plots and crops](#farm-plots-and-crops) · [Predicted supply and the farmer's market](#predicted-supply-and-the-farmers-market) · [Buyer: market, demands, orders, traceability](#buyer-market-demands-orders-traceability) · [Crop-health photo check](#crop-health-photo-check) · [Assistant and voice](#assistant-and-voice) · [Reminders and account](#reminders-and-account) · [Admin](#admin) · [Duplicate copies in the source folder](#duplicate-copies-in-the-source-folder)

### Sign-in and accounts

| **Sign-in (emulator)** | **Sign-in (phone)** | **Sign-in: farmer** |
|---|---|---|
| <img src="docs/images/app-sign-in.png" width="240" alt="Sign-in screen with the seedling logo, country code, mobile number and password fields"> | <img src="docs/images/sign-in-empty.jpg" width="240" alt="Sign-in screen on the phone with empty mobile number and password fields"> | <img src="docs/images/sign-in-farmer-filled.png" width="240" alt="Sign-in screen with a farmer test account's mobile number typed and the password hidden"> |
| Emulator, 2026-10-16. Phone number and password. | Phone number and password. | A farmer test account signing in. |

| **Sign-in: second farmer** | **Sign-in: second farmer (again)** | **Sign-in: buyer** |
|---|---|---|
| <img src="docs/images/sign-in-farmer2-filled.png" width="240" alt="Sign-in screen with a second farmer test account's mobile number typed and the password hidden"> | <img src="docs/images/sign-in-farmer2-filled-2.jpg" width="240" alt="Sign-in screen with the second farmer's mobile number typed, captured at a later time"> | <img src="docs/images/sign-in-buyer-filled.jpg" width="240" alt="Sign-in screen with a buyer test account's mobile number typed and the password hidden"> |
| A second farmer test account. | The same account, signing in again. | A buyer test account. |

| **Sign-in: admin** | **Create account: farmer** | **Create account: buyer** |
|---|---|---|
| <img src="docs/images/sign-in-admin-filled.jpeg" width="240" alt="Sign-in screen with the admin account's mobile number typed and the password hidden"> | <img src="docs/images/create-account-farmer.jpg" width="240" alt="Create account form with Farmer selected: full name, mobile number, password, optional district and assistant language"> | <img src="docs/images/create-account-buyer.jpg" width="240" alt="Create account form with Buyer selected, adding business name and business type Retailer"> |
| The admin account. | The language set here is used by the assistant and voice. The approval note is deployment branch only. | Buyers also give a business name and type. The approval note is deployment branch only. |

| **Sign-in code (development mode)** | **Set a new password** |
|---|---|
| <img src="docs/images/sign-in-code-development-mode.jpeg" width="240" alt="Enter your code screen in development mode: the 6-digit code is shown on screen because the server has no SMS provider; the phone number is masked"> | <img src="docs/images/set-new-password.jpg" width="240" alt="Change password screen showing the account's mobile number and fields for current, new and confirmed password"> |
| Without an SMS provider the development server shows the code on screen. **`main` only** (earlier build; the deployment branch removed SMS codes). | Changing the password signs other phones out. **Deployment branch only.** |

### Farmer home

| **Home: Kannada quote** | **Home: before the first farm** | **Home: weather** |
|---|---|---|
| <img src="docs/images/farmer-home-quote.jpg" width="240" alt="Farmer Home with a rotating Kannada quote over the seedling photo, a Get started card and the Ask button"> | <img src="docs/images/farmer-home-get-started.jpg" width="240" alt="Home scrolled down: Get started, no supply requests, no pending reminders, Check crop health and Ask assistant buttons"> | <img src="docs/images/farmer-home-weather.png" width="240" alt="Home weather card: 23 degrees overcast, rain chance by hour and a three-day Open-Meteo forecast labelled Estimate"> |
| One of 100 Kannada quotes. Before a farm exists Home shows "Get started". | Shortcuts to the photo check and the assistant. | An Open-Meteo forecast, labelled as a model estimate, not a measurement. |

| **Home: weather unavailable** | **Home: farm risk** | **Home: farm without a location** |
|---|---|---|
| <img src="docs/images/farmer-home-weather-unavailable.jpg" width="240" alt="Home with a Kannada quote and a weather card saying weather could not be loaded because there is no connection to Open-Meteo"> | <img src="docs/images/farmer-home-farm-risk.jpg" width="240" alt="Home with farm risk Low (33), supply requests, next reminders and buttons for Check crop health and Ask assistant"> | <img src="docs/images/farmer2-home-no-location.jpg" width="240" alt="Home for the second farmer: Kannada quote, notification badge 2, weather card asking to add the farm's latitude and longitude"> |
| When Open-Meteo cannot be reached, the card says so. | Built from the latest prediction of each crop cycle. | Weather needs the farm's coordinates. |

| **Home (emulator)** |
|---|
| <img src="docs/images/app-farmer-home.png" width="240" alt="Farmer Home on the emulator with a Kannada quote over the seedling photo"> |
| Emulator, 2026-10-16. |

<details>
<summary><b>First-run guide (11 screens)</b>: shown once after sign-in; reopen it from Account → Help &amp; guide</summary>

| **1 Welcome** | **2 Farm and plots** | **3 Crops** | **4 Weather** |
|---|---|---|---|
| <img src="docs/images/guide-01-welcome.jpg" width="180" alt="Guide 1 of 11: Welcome"> | <img src="docs/images/guide-02-farm-and-plots.jpg" width="180" alt="Guide 2 of 11: Farm and plots"> | <img src="docs/images/guide-03-crops.jpg" width="180" alt="Guide 3 of 11: Crops"> | <img src="docs/images/guide-04-weather.jpg" width="180" alt="Guide 4 of 11: Weather"> |

| **5 Income planner** | **6 Expenses** | **7 Observations and crop health** | **8 Harvest** |
|---|---|---|---|
| <img src="docs/images/guide-05-income-planner.jpg" width="180" alt="Guide 5 of 11: Income planner"> | <img src="docs/images/guide-06-expenses.jpg" width="180" alt="Guide 6 of 11: Expenses"> | <img src="docs/images/guide-07-observations-crop-health.jpg" width="180" alt="Guide 7 of 11: Observations and crop health"> | <img src="docs/images/guide-08-harvest.jpg" width="180" alt="Guide 8 of 11: Harvest"> |

| **9 Reminders** | **10 Orders** | **11 Ask Harvestique** |
|---|---|---|
| <img src="docs/images/guide-09-reminders.jpg" width="180" alt="Guide 9 of 11: Reminders"> | <img src="docs/images/guide-10-orders.jpg" width="180" alt="Guide 10 of 11: Orders"> | <img src="docs/images/guide-11-ask-harvestique.jpg" width="180" alt="Guide 11 of 11: Ask Harvestique"> |

</details>

### Farm, plots and crops

| **My Farm** | **My Farm: no location** | **Farm: weather and risk** | **Farm: plots and crops** |
|---|---|---|---|
| <img src="docs/images/my-farm.jpg" width="180" alt="My Farm list with farm f1, 1 acre, Mysore, an Add farm button and the Income plans entry"> | <img src="docs/images/farmer2-my-farm-no-location.jpg" width="180" alt="My Farm for the second farmer: farm f1, 1 acre, Mandya, no location so weather is unavailable"> | <img src="docs/images/farm-weather-and-risk.jpg" width="180" alt="Farm detail with a stale five-day forecast after Open-Meteo returned HTTP 429, and a risk breakdown with most categories not assessed"> | <img src="docs/images/farm-plots-and-crops.jpg" width="180" alt="Farm detail with plot p1 (1 acre, drip) growing tomato, plus Expenses and Field work log entries"> |
| Farms, archived farms and the way into Income plans. | Without coordinates there is no weather. | Stale weather is labelled. Risk categories without data say "not assessed". | Plots, crop cycles, expenses and the field work log. |

| **Crop catalogue** | **Add plot** | **Add expense** | **Add field work** |
|---|---|---|---|
| <img src="docs/images/crop-catalogue.jpg" width="180" alt="Add crop screen: a searchable catalogue with All (213), Vegetables (53), Fruits (47) and Kannada names where available"> | <img src="docs/images/add-plot.jpg" width="180" alt="Add plot dialog: plot name, area in acres and irrigation type"> | <img src="docs/images/add-expense.jpg" width="180" alt="Add expense form: category chips, amount in rupees, date, optional crop and note"> | <img src="docs/images/add-field-work.jpg" width="180" alt="Add field work form: work type chips such as sowing, irrigation and weeding, date, optional crop and note"> |
| All 213 crops, with Kannada names where available. | Area and irrigation for each plot. | Costs for a farm or a crop. | The work log for a farm or a crop. |

### Predicted supply and the farmer's market

| **Harvest: committed** | **Harvest: awaiting an answer** | **Supply request** |
|---|---|---|
| <img src="docs/images/farmer-harvest-inventory.jpg" width="240" alt="Harvest tab for tomato: predicted harvest 2,530 kg (estimate), can promise 1,123.4 kg, 40 kg committed and confirmed, Offer to buyers on, grade A"> | <img src="docs/images/farmer2-harvest-awaiting-answer.jpg" width="240" alt="Harvest tab for the second farmer: predicted 2,526.3 kg, can promise 1,054.1 kg, 40 kg requested and awaiting the farmer's answer"> | <img src="docs/images/farmer-supply-request.jpg" width="240" alt="Farmer Market with a request for 40 kg of tomato from a wholesaler, a delivery window and grade A or better, with Decline and Accept buttons"> |
| Only the pessimistic p10 prediction can be promised. | A pool has reserved 40 kg of this lot. The farmer has not answered yet. | The farmer must accept or decline. |

| **Accepted order** |
|---|
| <img src="docs/images/farmer-market-accepted-order.jpg" width="240" alt="Farmer Market with the accepted 40 kg tomato order marked Ready, and a buyer demand that is already pooled"> |
| After accepting, the farmer reports progress (here "Ready"). |

### Buyer: market, demands, orders, traceability

| **Market (emulator)** | **Market: future supply** | **My demands** | **New demand** |
|---|---|---|---|
| <img src="docs/images/app-buyer-market.png" width="180" alt="Buyer Market on the emulator with the Search future harvests button and no supply on offer"> | <img src="docs/images/buyer-market-future-supply.jpg" width="180" alt="Buyer Market showing 3,746.4 kg of tomato from 4 farm lots, harvest December to March, labelled Estimate"> | <img src="docs/images/buyer-demands.jpg" width="180" alt="My demands: tomato 100 kg, grade A, awaiting farmer confirmation"> | <img src="docs/images/buyer-new-demand.jpg" width="180" alt="New demand dialog: crop, quantity in kilograms, minimum grade and delivery window"> |
| Emulator, 2026-10-16. No supply on offer yet. | Uncommitted p10 supply across farms. No prices are shown. | The stage each demand has reached. | Crop, kg, minimum grade and delivery window. |

| **Orders** | **Order detail** | **Order detail (again)** | **Order: one item per farm** |
|---|---|---|---|
| <img src="docs/images/buyer-orders.jpg" width="180" alt="Buyer Orders: an order for 100 kg of tomato, 40 kg confirmed, 60 kg waiting, 0 kg delivered"> | <img src="docs/images/buyer-order-detail.jpg" width="180" alt="Order detail: 100 kg ordered, 40 kg confirmed by farmers (estimate), 60 kg waiting, 0 kg delivered and quality-accepted (measured)"> | <img src="docs/images/buyer-order-detail-2.jpg" width="180" alt="The same order detail screen captured a moment later"> | <img src="docs/images/buyer-order-farms.jpg" width="180" alt="Order detail listing four farm items, one accepted and marked Ready, three pending"> |
| Confirmed, waiting and delivered kg. | Estimates and measured kg are labelled separately. | Captured again; the screen is unchanged. | The pool spread the order across four farms. |

| **Traceability** |
|---|
| <img src="docs/images/buyer-traceability.jpg" width="180" alt="Traceability: order to pool to farm allocation to harvest to collection batch to quality to fulfilment, with zero pool reallocations"> |
| Order, pool, allocation, harvest, batch, quality, fulfilment. |

### Crop-health photo check

> The A/B/C result card is **deployment branch only**. The analysed photos were third-party stock images
> (iStock, Alamy, Magnific) found by web image search and opened from Gallery. The browser screenshots show
> where each photo came from and are not app screens. Texts are in Kannada because the account's language
> was Kannada. The score is a visual estimate, not a diagnosis.

| **Start** | **Source photo: tomato** | **Tomato: Category A** | **Source photo: mango** |
|---|---|---|---|
| <img src="docs/images/crop-health-check.jpg" width="180" alt="Crop health check screen with Camera and Gallery buttons"> | <img src="docs/images/crop-health-source-tomato-stock.jpg" width="180" alt="Phone browser showing an iStock stock photo of a red tomato in a web image search"> | <img src="docs/images/crop-health-tomato-category-a.jpg" width="180" alt="Photo check result in Kannada: tomato, vegetables, Category A, health score 100 percent, AI confidence high"> | <img src="docs/images/crop-health-source-mango-stock.jpg" width="180" alt="Phone browser showing an Alamy watermarked stock photo of a mango in a web image search"> |
| Take a photo or choose one from Gallery. | Not an app screen. The stock image (iStock, third-party) was later chosen from Gallery. | A smooth, unblemished tomato. The photo was analysed by `gemma4:31b` on Ollama Cloud. **Deployment branch only.** | Not an app screen. The stock image (Alamy, third-party, watermarked) used for the next check. |

| **Mango: Category B** | **Source photo: damaged tomato** | **Damaged tomato: Category C** | **Groundnut leaf (emulator)** |
|---|---|---|---|
| <img src="docs/images/crop-health-mango-category-b.jpg" width="180" alt="Photo check result in Kannada: mango, fruits, Category B, health score 45 percent, signs such as brown and black spots"> | <img src="docs/images/crop-health-source-damaged-tomato-stock.jpg" width="180" alt="Phone browser showing a Magnific stock image of a cracked, damaged tomato in a web image search"> | <img src="docs/images/crop-health-tomato-category-c.jpg" width="180" alt="Photo check result in Kannada: tomato, Category C, health score 30 percent, signs such as cracking and sunken spots"> | <img src="docs/images/app-crop-health-result.png" width="180" alt="Crop health result: Groundnut, Oilseeds, Category B, health score 60 percent, AI confidence high"> |
| A speckled mango. The photo was analysed by `gemma4:31b` on Ollama Cloud. **Deployment branch only.** | Not an app screen. The stock image (Magnific, third-party) used for the next check. | A cracked, damaged tomato. The photo was analysed by `gemma4:31b` on Ollama Cloud. **Deployment branch only.** | Emulator: a public groundnut leaf-spot photo, commit `c9eb9bb`. **Deployment branch only.** |

| **Not a crop (emulator)** |
|---|
| <img src="docs/images/app-crop-health-unable.png" width="180" alt="Crop health result: Unable to classify, the photo does not show a crop plant"> |
| Emulator: the virtual camera scene, so no guess is given. **Deployment branch only.** |

### Assistant and voice

Use the EN / ಕನ್ನಡ switch to change the language. Hold the microphone to speak, or type.

| **Kannada: my farms** | **Reminder: confirm** | **Reminder: added** |
|---|---|---|
| <img src="docs/images/assistant-kannada-farms.jpg" width="240" alt="Assistant in Kannada answering how many farms: 1 farm, 1 plot of 1 acre, growing tomato, labelled Measured"> | <img src="docs/images/assistant-reminder-confirm.jpg" width="240" alt="Assistant in English asking to confirm a reminder to irrigate on 2026-10-26 at 06:00, with Confirm and Cancel buttons"> | <img src="docs/images/assistant-reminder-added.jpg" width="240" alt="Assistant confirming the irrigation reminder was added for 2026-10-26 06:00"> |
| Answered from the farmer's own records. | Writes need confirmation. The title "irrigate a.m" is the parser's literal reading. | Added only after Confirm. |

| **Kannada: weather tomorrow** | **Kannada: this month's expenses** |
|---|---|
| <img src="docs/images/assistant-kannada-weather.jpg" width="240" alt="Assistant in Kannada giving tomorrow's forecast for farm f1, 20.7 to 28 degrees and about 7.2 mm rain, noting the forecast is old and may change"> | <img src="docs/images/assistant-kannada-expenses.jpg" width="240" alt="Assistant in Kannada reporting 5000 rupees of expenses this month, all labour, labelled Measured"> |
| It says when the stored forecast is old. | From the farmer's expense records. |

### Reminders and account

| **Reminders** | **Reminders: none pending** | **Buyer reminders** |
|---|---|---|
| <img src="docs/images/farmer-reminders.jpg" width="240" alt="Reminders: New reminder and Calendar buttons, a suggestion to check the tomato crop, and the pending irrigation reminder"> | <img src="docs/images/farmer2-reminders.jpg" width="240" alt="Reminders for the second farmer: a suggestion to check the tomato crop and no pending reminders"> | <img src="docs/images/buyer-reminders.jpg" width="240" alt="Buyer Reminders screen with New reminder and Calendar buttons and nothing pending"> |
| Suggestions come from the farmer's records. | A suggestion, but nothing pending yet. | Buyers have reminders too. |

| **Account menu** |
|---|
| <img src="docs/images/account-menu.jpg" width="240" alt="Account menu showing the farmer's name and role, assistant language English or Kannada, Help and guide, Change password, Server status and Sign out"> |
| Change password is deployment branch only. |

### Admin

> The **Testers** tab (approving and suspending accounts) is **deployment branch only**. `main` has Dashboard,
> Orders, Quality and Hubs.

| **Dashboard** | **Dashboard: demands and pools** | **Dashboard: collection and accuracy** | **Orders** |
|---|---|---|---|
| <img src="docs/images/admin-dashboard.jpg" width="180" alt="Admin dashboard: user counts by role, farms, active crop cycles, supply on offer 3,746.4 kg (estimate), lots by status"> | <img src="docs/images/admin-dashboard-pools.jpg" width="180" alt="Admin dashboard scrolled: demands, pools filled and unfilled, orders, reallocations in 30 days, collection and quality"> | <img src="docs/images/admin-dashboard-quality.jpg" width="180" alt="Admin dashboard: collection and quality in measured kg, and prediction accuracy with 5 prediction versions scored"> | <img src="docs/images/admin-orders.jpg" width="180" alt="Admin Orders: a placed tomato order and a cancelled browntop millet order that was 50 kg short"> |
| Counts across all users (test data). | Pools and reallocations. | Accuracy is measured only from recorded harvests. | Every order, with how much of it is covered. |

| **Order: receive batch** | **Cancelled order** | **Traceability: cancelled item** | **Traceability: accepted item** |
|---|---|---|---|
| <img src="docs/images/admin-order-receive-batch.jpg" width="180" alt="Admin order detail: a farm item the farmer accepted and marked Ready shows a Receive batch button"> | <img src="docs/images/admin-cancelled-order.jpg" width="180" alt="Cancelled browntop millet order: 50 kg ordered, 0 confirmed, 50 kg shortage, the farmer withdrew"> | <img src="docs/images/admin-traceability-cancelled.jpg" width="180" alt="Traceability of the cancelled order: allocation 50 kg with 2 ledger entries, participation withdrawn, prediction range, harvest and fulfilment pending"> | <img src="docs/images/admin-traceability-accepted.jpg" width="180" alt="Traceability: a farm that accepted 40 kg, its prediction range, harvest pending, and the next farm awaiting the farmer"> |
| A batch can be received only for an accepted item. | The shortage is shown, not hidden. | Every change is in the ledger. | Allocation, participation, prediction, harvest and fulfilment for each farm. |

| **Traceability: pending item** | **Hubs** | **Testers: approved** | **Testers: approved (more)** |
|---|---|---|---|
| <img src="docs/images/admin-traceability-pending.jpg" width="180" alt="Traceability scrolled to a farm awaiting the farmer: 20 kg allocation, pending participation, prediction range"> | <img src="docs/images/admin-hubs.jpg" width="180" alt="Hubs screen with Add collection hub and one active hub in Mysore"> | <img src="docs/images/admin-testers-approved.jpg" width="180" alt="Testers list, Approved tab: test accounts with role, mobile number and join date, and an action menu with Suspend, Revoke access and Reset password"> | <img src="docs/images/admin-testers-approved-2.jpg" width="180" alt="Testers list, Approved tab, more test accounts with role, mobile number and join date"> |
| Further down the same trace. | Collection hubs. | Managing test accounts. **Deployment branch only.** | More approved test accounts. **Deployment branch only.** |

| **Testers: suspended** | **Testers: suspended (later)** |
|---|---|
| <img src="docs/images/admin-testers-suspended.jpg" width="180" alt="Testers list, Suspended tab, right after suspending a test farmer, with a 'suspended' confirmation"> | <img src="docs/images/admin-testers-suspended-2.jpg" width="180" alt="Testers list, Suspended tab, a little later, without the confirmation"> |
| Suspending an account. **Deployment branch only.** | The same list a little later. **Deployment branch only.** |

### Duplicate copies in the source folder

<details>
<summary>22 identical copies (same bytes as a screenshot above)</summary>

| **Source photo: tomato (copy)** | **Source photo: tomato (copy)** | **Tomato: Category A (copy)** | **Tomato: Category A (copy)** |
|---|---|---|---|
| <img src="docs/images/crop-health-source-tomato-stock-farmer1-19.jpg" width="180" alt="Identical copy of the screenshot 'Source photo: tomato'"> | <img src="docs/images/crop-health-source-tomato-stock-farmer1-crop-analysis.jpg" width="180" alt="Identical copy of the screenshot 'Source photo: tomato'"> | <img src="docs/images/crop-health-tomato-category-a-farmer1-20.jpg" width="180" alt="Identical copy of the screenshot 'Tomato: Category A'"> | <img src="docs/images/crop-health-tomato-category-a-farmer1-crop-analysis.jpg" width="180" alt="Identical copy of the screenshot 'Tomato: Category A'"> |
| Identical copy of `crop-health-source-tomato-stock.jpg`, found at `Farmer/farmer 1/19.jpg` in the source folder. | Identical copy of `crop-health-source-tomato-stock.jpg`, found at `Farmer/farmer 1/crop analysis/1.jpg` in the source folder. | Identical copy of `crop-health-tomato-category-a.jpg`, found at `Farmer/farmer 1/20.jpg` in the source folder. | Identical copy of `crop-health-tomato-category-a.jpg`, found at `Farmer/farmer 1/crop analysis/2.jpg` in the source folder. |

| **Source photo: mango (copy)** | **Source photo: mango (copy)** | **Mango: Category B (copy)** | **Mango: Category B (copy)** |
|---|---|---|---|
| <img src="docs/images/crop-health-source-mango-stock-farmer1-21.jpg" width="180" alt="Identical copy of the screenshot 'Source photo: mango'"> | <img src="docs/images/crop-health-source-mango-stock-farmer1-crop-analysis.jpg" width="180" alt="Identical copy of the screenshot 'Source photo: mango'"> | <img src="docs/images/crop-health-mango-category-b-farmer1-22.jpg" width="180" alt="Identical copy of the screenshot 'Mango: Category B'"> | <img src="docs/images/crop-health-mango-category-b-farmer1-crop-analysis.jpg" width="180" alt="Identical copy of the screenshot 'Mango: Category B'"> |
| Identical copy of `crop-health-source-mango-stock.jpg`, found at `Farmer/farmer 1/21.jpg` in the source folder. | Identical copy of `crop-health-source-mango-stock.jpg`, found at `Farmer/farmer 1/crop analysis/3.jpg` in the source folder. | Identical copy of `crop-health-mango-category-b.jpg`, found at `Farmer/farmer 1/22.jpg` in the source folder. | Identical copy of `crop-health-mango-category-b.jpg`, found at `Farmer/farmer 1/crop analysis/4.jpg` in the source folder. |

| **Source photo: damaged tomato (copy)** | **Source photo: damaged tomato (copy)** | **Damaged tomato: Category C (copy)** | **Damaged tomato: Category C (copy)** |
|---|---|---|---|
| <img src="docs/images/crop-health-source-damaged-tomato-stock-farmer1-23.jpg" width="180" alt="Identical copy of the screenshot 'Source photo: damaged tomato'"> | <img src="docs/images/crop-health-source-damaged-tomato-stock-farmer1-crop-analysis.jpg" width="180" alt="Identical copy of the screenshot 'Source photo: damaged tomato'"> | <img src="docs/images/crop-health-tomato-category-c-farmer1-24.jpg" width="180" alt="Identical copy of the screenshot 'Damaged tomato: Category C'"> | <img src="docs/images/crop-health-tomato-category-c-farmer1-crop-analysis.jpg" width="180" alt="Identical copy of the screenshot 'Damaged tomato: Category C'"> |
| Identical copy of `crop-health-source-damaged-tomato-stock.jpg`, found at `Farmer/farmer 1/23.jpg` in the source folder. | Identical copy of `crop-health-source-damaged-tomato-stock.jpg`, found at `Farmer/farmer 1/crop analysis/5.jpg` in the source folder. | Identical copy of `crop-health-tomato-category-c.jpg`, found at `Farmer/farmer 1/24.jpg` in the source folder. | Identical copy of `crop-health-tomato-category-c.jpg`, found at `Farmer/farmer 1/crop analysis/6.jpg` in the source folder. |

| **Kannada: my farms (copy)** | **Kannada: my farms (copy)** | **Reminder: confirm (copy)** | **Reminder: confirm (copy)** |
|---|---|---|---|
| <img src="docs/images/assistant-kannada-farms-farmer1-25.jpg" width="180" alt="Identical copy of the screenshot 'Kannada: my farms'"> | <img src="docs/images/assistant-kannada-farms-farmer1-voice.jpg" width="180" alt="Identical copy of the screenshot 'Kannada: my farms'"> | <img src="docs/images/assistant-reminder-confirm-farmer1-26.jpg" width="180" alt="Identical copy of the screenshot 'Reminder: confirm'"> | <img src="docs/images/assistant-reminder-confirm-farmer1-voice.jpg" width="180" alt="Identical copy of the screenshot 'Reminder: confirm'"> |
| Identical copy of `assistant-kannada-farms.jpg`, found at `Farmer/farmer 1/25.jpg` in the source folder. | Identical copy of `assistant-kannada-farms.jpg`, found at `Farmer/farmer 1/voice assitent/1.jpg` in the source folder. | Identical copy of `assistant-reminder-confirm.jpg`, found at `Farmer/farmer 1/26.jpg` in the source folder. | Identical copy of `assistant-reminder-confirm.jpg`, found at `Farmer/farmer 1/voice assitent/2.jpg` in the source folder. |

| **Reminder: added (copy)** | **Reminder: added (copy)** | **Kannada: weather tomorrow (copy)** | **Kannada: weather tomorrow (copy)** |
|---|---|---|---|
| <img src="docs/images/assistant-reminder-added-farmer1-27.jpg" width="180" alt="Identical copy of the screenshot 'Reminder: added'"> | <img src="docs/images/assistant-reminder-added-farmer1-voice.jpg" width="180" alt="Identical copy of the screenshot 'Reminder: added'"> | <img src="docs/images/assistant-kannada-weather-farmer1-28.jpg" width="180" alt="Identical copy of the screenshot 'Kannada: weather tomorrow'"> | <img src="docs/images/assistant-kannada-weather-farmer1-voice.jpg" width="180" alt="Identical copy of the screenshot 'Kannada: weather tomorrow'"> |
| Identical copy of `assistant-reminder-added.jpg`, found at `Farmer/farmer 1/27.jpg` in the source folder. | Identical copy of `assistant-reminder-added.jpg`, found at `Farmer/farmer 1/voice assitent/3.jpg` in the source folder. | Identical copy of `assistant-kannada-weather.jpg`, found at `Farmer/farmer 1/28.jpg` in the source folder. | Identical copy of `assistant-kannada-weather.jpg`, found at `Farmer/farmer 1/voice assitent/4.jpg` in the source folder. |

| **Kannada: this month's expenses (copy)** | **Kannada: this month's expenses (copy)** |
|---|---|
| <img src="docs/images/assistant-kannada-expenses-farmer1-29.jpg" width="180" alt="Identical copy of the screenshot 'Kannada: this month's expenses'"> | <img src="docs/images/assistant-kannada-expenses-farmer1-voice.jpg" width="180" alt="Identical copy of the screenshot 'Kannada: this month's expenses'"> |
| Identical copy of `assistant-kannada-expenses.jpg`, found at `Farmer/farmer 1/29.jpg` in the source folder. | Identical copy of `assistant-kannada-expenses.jpg`, found at `Farmer/farmer 1/voice assitent/5.jpg` in the source folder. |

</details>

**Not pictured yet:**
* Income-plan screens.
* The crop screen with its prediction card.
* The buyer's pool screen.
* A hub quality check.
* The notification feed.

## 3. Architecture

```mermaid
flowchart LR
    subgraph Phone["Android phone or emulator"]
        App["Flutter app<br/>Riverpod, go_router, Dio"]
        Speech["On-device speech<br/>speech_to_text, flutter_tts<br/>en-IN / kn-IN"]
    end
    subgraph PC["Docker Compose on the PC"]
        API["FastAPI /api/v1<br/>domain rules, services"]
        DB[("PostgreSQL 16")]
    end
    Ollama["Ollama<br/>local, optional"]
    Meteo["Open-Meteo<br/>weather"]
    SMS["SMS codes<br/>dev console or phone gateway"]
    App -- "HTTP + JWT" --> API
    Speech --- App
    API -- "SQLAlchemy" --> DB
    API -- "assistant and photo models" --> Ollama
    API -- "forecast and history" --> Meteo
    API -- "sign-in codes" --> SMS
```

| Part | Stack on `main` (verified in this repository) |
|---|---|
| Mobile app | Flutter / Dart for Android: `flutter_riverpod`, `go_router`, `dio`, `flutter_secure_storage`, `shared_preferences` (offline cache), `speech_to_text`, `flutter_tts`, `image_picker` |
| Backend | Python 3.12, FastAPI, Pydantic, SQLAlchemy 2.0, Alembic (15 migrations), PostgreSQL. Business rules are pure Python in `backend/app/domain/`; SciPy (HiGHS) only for the optional LP pool allocator |
| AI | A **local** Ollama server only (`.env.example`: `llama3.2:3b` for the assistant; the photo check is off by default and uses `gemma3:4b` when enabled). There is no setting for a hosted Ollama key on `main` |
| Local development | Docker Compose ([docker-compose.yml](docker-compose.yml)): PostgreSQL, backend, optional Ollama (`--profile ai`) |

The app also contains the **admin** screens: Dashboard, Orders, Quality and Hubs. On an order's detail screen
(opened from Orders) an admin receives batches and fulfils items; quality checks are recorded on the Quality tab.
A user's role decides which screens they see.

## 4. Predicted harvest vs available produce

This distinction runs through the whole system (`backend/app/domain/inventory.py`):

| State of a crop cycle | What the farmer can promise (`committable_kg`) | Label |
|---|---|---|
| Growing, with a prediction | the **p10** (pessimistic) predicted quantity | estimate |
| Growing, no usable prediction | 0 | - |
| Harvest recorded | the **measured** harvest | measured |
| Abandoned | 0 | - |

`available_kg = committable_kg - (active + fulfilled reservations)`, never negative. If commitments exceed what can
now be promised, the excess is the lot's `shortfall_kg` and the lot is *at risk*. A farmer must **opt a lot in**
before any buyer pool can use it, and sets its expected grade.

What a buyer sees as "future supply" (`GET /market/supply`) is the sum of p10 estimates on opted-in lots, not stock
in a warehouse. A reservation against a prediction is **not** a confirmed delivery. Nothing is confirmed until the
farmer accepts, and nothing is delivered until produce is weighed at a hub, quality-checked and fulfilled.

## 5. From farm to buyer: the implemented workflow

```mermaid
flowchart TD
    A["Farm, plot, crop cycle<br/>(farmer)"] --> B["Harvest prediction<br/>p10 / p50 / p90, window, confidence"]
    B --> C["Inventory lot<br/>promisable = p10"]
    C --> D{"Farmer opts the lot in<br/>and sets expected grade"}
    E["Buyer demand<br/>crop, kg, window, min grade"] --> F["Matching<br/>eligibility + score"]
    D --> F
    F --> G["Harvest pool<br/>greedy (default) or LP"]
    G --> H["Reservations on lots"]
    H --> I["Order on the pool<br/>one item per farm"]
    I --> J{"Farmer accepts?"}
    J -- "declines" --> K["Release + reallocate"]
    K --> H
    B -. "prediction falls" .-> L["Shortage detected<br/>newest commitments cut first"]
    L --> K
    J -- "accepts" --> M["Measured harvest recorded"]
    M --> N["Batch received at hub<br/>(measured kg)"]
    N --> O["Quality check<br/>grade >= buyer minimum"]
    O --> P["Fulfilment"]
    P --> Q["Trace: order to pool, harvest,<br/>batch, quality"]
    M --> R["Prediction feedback<br/>and calibration"]
```

| Stage | How it works (verified in code) | Endpoint(s) |
|---|---|---|
| Farm data | Farms, plots, crop cycles; plot capacity checked over time | `POST /farms`, `POST /plots/{plot_id}/crop-cycles` |
| Prediction | Hybrid rule model, new version on each request ([section 7](#7-harvest-prediction)) | `POST /crop-cycles/{cycle_id}/predictions` |
| Offer supply | Farmer opts a lot in and sets an expected grade | `PATCH /inventory/lots/{lot_id}` |
| Demand | Buyer states crop, kg, delivery window, minimum grade, optional location and distance, minimum confidence, maximum risk | `POST /buyer-demands` |
| Matching | Every opted-in lot is checked: same crop; grade at least the minimum; window overlap; available > 0; confidence, risk and distance limits. Each failure has a named reason. Eligible lots get a 0-100 score (confidence, risk, reliability, window fit, proximity, availability). | `GET /buyer-demands/{demand_id}/matches`, `GET /market/harvests` |
| Pooling | Allocates **only `available_kg`** (p10 minus commitments) and reserves it on each lot. Default: greedy by score; optional two-stage LP (risk cap, share cap). Idempotent. | `POST /buyer-demands/{demand_id}/pool` |
| Shortage handling | When a prediction or recorded harvest changes, the exact shortfall is computed and cut from the **newest** pool commitments first (farmers' own reservations are never cut), then replaced from other eligible lots. When new supply appears, short pools are topped up. Each change writes an event and ledger rows. Unresolved gaps leave the pool `at_risk`. | automatic; `POST /pools/{pool_id}/rebalance`, `GET /pools/{pool_id}/events`, `.../ledger` |
| Order and confirmation | An order on a pool creates one item per farm; each farmer **accepts or declines**. A decline releases that supply and reallocates in the same transaction. | `POST /orders`, `POST /participations/{participation_id}/accept`, `.../decline` |
| Harvest | Farmer records the **measured** harvest. This scores every prediction version and updates calibration. | `POST /crop-cycles/{cycle_id}/harvest-actual` |
| Collection | A hub records the weighed batch, only for an accepted item with a recorded harvest | `POST /admin/batches` |
| Quality | Measured check, once per batch: accepted/rejected kg and grade; a grade below the buyer's minimum can only be rejected | `POST /admin/batches/{batch_id}/quality` |
| Fulfilment | Only quality-accepted produce counts; every batch must be checked first | `POST /admin/order-items/{item_id}/fulfil` |
| Traceability | Order to pool to allocation to harvest to batch to quality to fulfilment | `GET /orders/{order_id}/trace`, `GET /trace/batches/{code}` |

A buyer's demand is **not** fulfilled or confirmed because a farmer registered a prediction. The buyer-facing
`stage` moves through matching, `supply_reserved`, `awaiting_farmer_confirmation`, `confirmed`, `in_fulfilment` and
`fulfilled`, or to `partially_matched`, `reallocation_required` or `partially_fulfilled` when supply falls short.

**Limits:** quantities in kilograms only; no prices, contracts or payments; one pool and one order per demand;
reallocation is triggered by events (prediction change, decline, new supply, manual), not on a schedule.

## 6. Planning tools

All planning maths is deterministic Python (`backend/app/domain/planning/`), over **ranges** (low / expected / high)
entered by the farmer. Prices are the farmer's own inputs; Harvestique does not supply market prices.

| Tool | What it computes | Where |
|---|---|---|
| **Income plans** (Farm Income Planner) | A saved plan of crops on an area of land, evaluated fresh each time. Cost per acre and totals (high cost includes an overrun), production, revenue and margin ranges. Also break-even price and yield, land use month by month, income continuity, budget, water and labour checks, risk and confidence scores, and feasibility. A crop can take its yield range from a saved prediction. Plans can be duplicated and compared (2-5). | App "Income plans": `/crop-plans`, `GET /crop-plans/{plan_id}/evaluation`; compare and duplicate are API only |
| **Cost & income calculator** | The same evaluation for an unsaved set of crops | API only: `POST /planning/calculate` |
| **Land utilization planner** | Deterministic greedy split of the available land between candidate crops, limited by land over time, budget, water, labour, demand and per-crop caps; excluded crops come with reasons | API only: `POST /planning/suggest-allocation` |

Formulas: [docs/ALGORITHMS.md](docs/ALGORITHMS.md) section 2. These are planning estimates, not forecasts of income.

## 7. Harvest prediction

The prediction provider is `hybrid-rules` 1.0.0 (`backend/app/domain/prediction/engine.py`), a **deterministic,
documented rule model**. It is not machine learning: nothing in this repository trains a model.

* **Base yield per acre:** an evidence-weighted mean of the farmer's own recorded harvests, the farmer's estimate and
  the catalogue's reference yield. No evidence gives `insufficient_data` (no quantity).
* **Factors:** water deficit, heat-stress days, heavy-rain days (from Open-Meteo), the latest field observation and,
  once at least 5 recorded outcomes exist, a calibration bias.
* **Uncertainty:** a coefficient of variation, widened for missing or stale weather, recent damage and time left in
  the season. p10 / p90 = p50 x (1 -/+ 1.2816 x CV).
* **Window and confidence:** harvest start and end windows, and a 0-100 confidence that is labelled "heuristic,
  not a measured accuracy" until calibration has enough data.
* **Farm risk:** nine categories, each 0-100 or "not assessed" when its data is missing.
* **Feedback:** a measured harvest scores every prediction version (error, interval hit, pinball loss). Calibration
  profiles are versioned and applied only with 5 or more outcomes.

Details and constants: [docs/ALGORITHMS.md](docs/ALGORITHMS.md) sections 3-7.

## 8. AI in Harvestique

### What runs where

| Question | Answer on `main` (verified in code and configuration) |
|---|---|
| Does Harvestique train models? | **No.** There is no training code or ML library in the backend dependencies. |
| What models are used? | `.env.example`: `llama3.2:3b` for the assistant. The photo check is off (colour measurements only) unless `CROP_HEALTH_CLASSIFIER=ollama_vision`, which uses `gemma3:4b`. |
| Where do they run? | Inference only, on a **local** Ollama server through its HTTP API. (Ollama Cloud with `gemma4:31b` is used by the deployment branch.) |
| What is AI-generated? | Assistant wording for general questions; tool choice when the keyword rules fail; the model's description, signs and category for a photo. |
| What is deterministic? | Predictions, risk, inventory, matching, pooling, reallocation, planning, the photo's 0-10 condition score, and the assistant's answers about the farmer's own data. |

### Farm assistant (`backend/app/services/assistant.py`, `backend/app/domain/assistant/`)
* Questions are routed by keyword rules to fixed tools: weather, predictions, farm risk, reminders, inventory, buyer
  opportunities, supply requests, orders, income plans, expenses, crop estimates and suggestions, navigation.
* Answers about the farmer's data come from those tools, never from the model.
* The model may pick a tool when the rules do not understand a question, and may give short, labelled
  general-knowledge answers. Kannada general answers are off by default: the small local models wrote poor Kannada.
  Kannada general questions are first translated with a project glossary.
* Writes (for example recording an expense) need the farmer's confirmation. Allocation requests are always refused:
  only the pool engine allocates.

### Crop health photo check on `main`

```mermaid
flowchart TD
    U["Photo from Camera or Gallery<br/>JPEG / PNG / WebP, max 5 MB"] --> V["Validate and decode<br/>type check, pixel limit, resize to 768 px"]
    V --> W{"Too dark or blurred?"}
    W -- "yes" --> X["Unclear: no model call"]
    W -- "no" --> Y["Local Ollama chat: system prompt,<br/>JSON schema, image; temperature 0.1"]
    Y --> Z["Parse the answer as JSON<br/>and validate every field"]
    Y -. "timeout, unreachable,<br/>invalid answer" .-> AB["Colour measurements only<br/>no health label"]
    Z --> AD["Category: healthy, possible disease,<br/>stress, possible deficiency or unknown"]
    AD --> AE["Report: signs seen, possible explanations,<br/>0-10 visual condition score, limits, next steps"]
```

* **Result:** a most-likely category with category bars (labelled an AI estimate, not a measured probability), the
  signs the model described, and a structured report with a 0-10 visual condition score when the photo gives enough
  evidence.
* **Safety:** never a diagnosis. Sentences about sprays, chemicals or doses are removed, and spraying is referred to
  an agriculture officer.
* **Privacy:** the photo itself is not stored. Only its SHA-256 and the result are kept.
* **Deployment branch only:** the farmer-facing decision (Healthy, Needs attention, Clearer photo needed,
  Unavailable), item identification against the catalogue, the 0-100 % health score with A/B/C categories, and
  tolerant reading of fenced JSON answers. That last part is needed for Ollama Cloud. See
  [docs/CROP_HEALTH_AND_GRADING.md](docs/CROP_HEALTH_AND_GRADING.md).

### Measured results (local `gemma3:4b`, from the project's evaluation reports, not re-run here)

| Set | Result | Report |
|---|---|---|
| PlantDoc web photos (108) | macro F1 0.82; healthy-leaf recall 0.59 | [docs/CROP_HEALTH_EVAL_2026-10-14.md](docs/CROP_HEALTH_EVAL_2026-10-14.md) |
| Koppal groundnut field photos (20) | macro F1 0.334: healthy leaves were called diseased | [docs/KOPPAL_GROUNDNUT_EVAL_2026-10-14.md](docs/KOPPAL_GROUNDNUT_EVAL_2026-10-14.md) |
| Reserved held-out set (74) | macro F1 0.779 | [docs/CROP_HEALTH_AND_GRADING.md](docs/CROP_HEALTH_AND_GRADING.md) |
| Assistant, 26 Kannada/English questions | 25/26 correct after the glossary (was 14/26) | [docs/ASSISTANT_EVAL_2026-10-14.md](docs/ASSISTANT_EVAL_2026-10-14.md) |

These are small samples. The photo check is a visual estimate that an agriculture officer should confirm. The
condition score is a documented rubric that has not been validated against expert severity ratings.

## 9. Quality grading

On `main` there are two grades, both A/B/C:

* **Expected grade of a lot:** set by the farmer when offering the lot (`PATCH /inventory/lots/{lot_id}`). Matching
  uses it against the buyer's minimum grade.
* **Hub quality check:** the measured grade and accepted/rejected kilograms of a received batch. It decides acceptance
  against the buyer's minimum grade (`POST /admin/batches/{batch_id}/quality`).

The farmer's evidence-based produce grade (checklist plus optional AI photo suggestion) is **deployment branch
only** ([docs/CROP_HEALTH_AND_GRADING.md](docs/CROP_HEALTH_AND_GRADING.md)). Neither grade is an official AGMARK or
BIS grade.

## 10. Languages and voice

* **App screens are in English.** There are no Flutter localization files.
* **Kannada** appears where the server writes the text in the user's language: assistant answers, crop-health
  reports, plus the 100 Kannada quotes on Home. The language is the farmer's profile setting (`en`/`kn`).
* **Voice:** speech recognition and text-to-speech run on the phone (`en-IN`, `kn-IN`). The transcript goes to
  `POST /voice/intent`, the same assistant as chat. Offline use needs the language packs on the phone. Server-side
  speech endpoints answer 503 by design.
* Kannada texts were written for this project and have not been reviewed by a native speaker.

## 11. Accounts and security

* **Roles:** farmer, buyer, admin. Admins are created only from the command line (`app.cli.create_admin`).
* **Sign-in on `main`:** phone number and password (Argon2id) **plus a one-time code by SMS**, at registration and at
  every login. A forgotten password is also reset with an SMS code.
  * `SMS_PROVIDER=dev_console` (the default) writes the codes to the server log for development.
  * `android_gateway` sends them through an SMS gateway app on a phone.
* **Sessions:** JWT access tokens (15 minutes) with rotating refresh tokens, stored in Android's secure storage.
* **Lockout:** a number is locked for 15 minutes after 5 wrong passwords. Code sends and resends are rate-limited.
* **Access control:** every resource route checks ownership and answers 404 for another user's data.
* **CORS:** `CORS_ORIGINS` defaults to `*`; set it for any non-development use.
* **Deployment branch only:** password-only sign-in, admin approval of new testers (Testers screen), request IDs and
  JSON logs, and a per-person limit on AI photo checks.

## 12. Run it locally

Windows 11 with Docker Desktop:

```powershell
copy .env.example .env
docker compose up -d --build
# API docs:  http://localhost:8000/api/v1/docs
# Readiness: http://localhost:8000/api/v1/health/ready
```

Flutter app on the emulator (`10.0.2.2` is the emulator's address for the PC):

```powershell
cd frontend
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1
```

* **Sign-in codes:** with the default `SMS_PROVIDER=dev_console`, they appear in the backend log
  (`docker compose logs backend`).
* **Without Docker:** [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) covers the backend virtual environment, a physical
  phone on Wi-Fi, local Ollama and migrations.
* **Demo data:** `python -m app.cli.demo --reset` runs the whole workflow through the real API. It works only on a
  database whose name contains `demo`, and its data is labelled simulated.
* **Tests:** `powershell -ExecutionPolicy Bypass -File scripts\test-backend.ps1` (ruff, mypy, pytest in Docker) and
  `flutter test` in `frontend/`. See [docs/TESTING.md](docs/TESTING.md).

## 13. Deployment

`main` contains only the local Docker Compose setup ([docker-compose.yml](docker-compose.yml)).

The hosted deployment is on the
[`deploy/free-tier-production`](https://github.com/Srinivasabl11/harvestique/tree/deploy/free-tier-production) branch
and is **not on `main`**. It uses the Render free plan, Neon PostgreSQL and Ollama Cloud, with a signed release APK.
See its [render.yaml](https://github.com/Srinivasabl11/harvestique/blob/deploy/free-tier-production/render.yaml) and
[docs/DEPLOYMENT.md](https://github.com/Srinivasabl11/harvestique/blob/deploy/free-tier-production/docs/DEPLOYMENT.md).

## 14. Evidence and verification

| Claim | Evidence level |
|---|---|
| Features, endpoints, algorithms, model names and limits described for `main` | **Verified against `main`** (source, `.env.example`, `docker-compose.yml`, generated [docs/API.md](docs/API.md)) on 2026-10-25 |
| Backend suite 1,834 passed; 969 unit tests and 212 Flutter tests passed | **Test runs on the deployment branch** (commit `c9eb9bb`), 2026-10-16; not re-run on `main` |
| Hosted production API ready; a crop-health check stored with `gemma4:31b` | **Verified on the deployment branch's production setup**, 2026-10-16 and 2026-10-18; not applicable to `main` |
| Screenshots above | **App runs of the deployment branch**: emulator 2026-10-16, Android phone mostly 2026-10-25 (test data); the sign-in code screen is from an earlier build matching `main` |
| Photo-check and assistant accuracy numbers | **Previously reported** in the linked evaluation reports; not re-run |
| Real-world harvest prediction accuracy, income or yield improvements | **Not measured.** No farm has recorded enough harvests in this system. [docs/EVALUATION.md](docs/EVALUATION.md) has a **simulated** calibration study and a simulated pooling experiment only |
| Harvest-pooling algorithm superiority | **Not claimed:** in simulation the LP did not beat greedy reallocation, so greedy is the default |

## 15. Limitations and proposed enhancements

Known limitations of `main`:
* Harvest predictions are rule-based estimates with heuristic confidence until real outcomes accumulate.
* The photo check over-reports problems on healthy leaves in the local evaluations.
* The cost & income calculator and land utilization planner are API only.
* There are no prices, contracts or payments. Mandi prices are off by default.
* Notifications are in-app only. App screens are English only. 127 catalogue crops have no Kannada name.
* Sign-in needs an SMS code. Without a configured SMS sender, codes are only in the server log.

Proposed enhancements (not implemented on `main`):
* Merge the deployment branch: password sign-in with admin approval, produce grading, the upgraded crop-health
  result and the hosted setup.
* Evaluate the vision model on the reserved photo set.
* Have Kannada texts reviewed by a native speaker and add the missing Kannada crop names.
* Expose the calculator and land planner in the app.
* Add push notifications.
* Collect real recorded harvests to measure prediction accuracy and enable calibration.

## 16. Documentation index

| Topic | Document |
|---|---|
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Algorithms | [docs/ALGORITHMS.md](docs/ALGORITHMS.md) |
| Harvest pooling | [docs/HARVEST_POOL.md](docs/HARVEST_POOL.md) |
| AI pipeline | [docs/AI_PIPELINE.md](docs/AI_PIPELINE.md) |
| Crop health and grading (deployment branch features) | [docs/CROP_HEALTH_AND_GRADING.md](docs/CROP_HEALTH_AND_GRADING.md) |
| API (generated) | [docs/API.md](docs/API.md) |
| Database (generated) | [docs/DATABASE.md](docs/DATABASE.md) |
| Evaluation | [docs/EVALUATION.md](docs/EVALUATION.md) |
| Testing | [docs/TESTING.md](docs/TESTING.md) |
| Development setup | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| Decisions | [docs/DECISIONS.md](docs/DECISIONS.md) |
| Progress log | [docs/PROGRESS.md](docs/PROGRESS.md) |
