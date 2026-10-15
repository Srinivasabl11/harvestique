# Development setup (Windows 11)

## Prerequisites
- Python 3.12 (`py -3.12 --version`)
- Docker Desktop with WSL 2 backend
- Flutter SDK (stable) + Android Studio / Android SDK + an emulator (or a USB-debugging phone)
- Git
- Optional: Ollama for Windows (needed from Phase 8)

If PowerShell blocks scripts, run them as `powershell -ExecutionPolicy Bypass -File scripts\<name>.ps1`.

## 1. Backend
```powershell
copy .env.example .env
powershell -ExecutionPolicy Bypass -File scripts\setup-backend.ps1
powershell -ExecutionPolicy Bypass -File scripts\run-backend.ps1
```
Open http://localhost:8000/api/v1/docs and http://localhost:8000/api/v1/health/ready.

Or everything in Docker: `docker compose up -d --build`.

## 2. Frontend
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-frontend.ps1
cd frontend
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1
```
Physical phone: same Wi-Fi as the PC, use the PC's IPv4 from `ipconfig`, and allow port 8000 through
Windows Defender Firewall for Private networks.

## 3. Authentication quick start
```powershell
# 1. Create the first admin (prompts for a hidden password; admins cannot self-register)
cd backend
.\.venv\Scripts\python.exe -m app.cli.create_admin --phone 9876500000 --name "Site Admin"

# 2. Register a farmer: step 1 sends a one-time code (202, no tokens yet)
$c = Invoke-RestMethod -Method Post http://localhost:8000/api/v1/auth/register -ContentType application/json `
  -Body '{"role":"farmer","phone":"9876543210","password":"Harvest123","full_name":"Ramesh Gowda","profile":{"village":"Hunsur","district":"Mysuru","state":"Karnataka"}}'
# With SMS_PROVIDER=dev_console nothing is sent: the code is in $c.dev_code (labelled DEVELOPMENT MODE).
# With a real SMS provider, read it from the phone instead.
# 3. Step 2: verify the code; only now are tokens issued
$r = Invoke-RestMethod -Method Post http://localhost:8000/api/v1/auth/register/verify -ContentType application/json `
  -Body (@{challenge_id=$c.challenge_id; code=$c.dev_code} | ConvertTo-Json)
Invoke-RestMethod http://localhost:8000/api/v1/auth/me -Headers @{Authorization="Bearer $($r.tokens.access_token)"}
```
Signing in works the same way: `POST /auth/login` (phone + password) sends a code, `POST /auth/login/verify`
returns the tokens. `POST /auth/otp/resend` sends a new code (60 s cooldown, 3 resends). Codes expire after
5 minutes and allow 5 wrong attempts in total.

### SMS for one-time codes (`SMS_PROVIDER`)
* `dev_console` (default, development only): **no SMS is sent**. The code is written to the backend log and returned
  in the API response; the app shows it in a box marked "DEVELOPMENT MODE – not sent by SMS". The server refuses to
  start with it when `APP_ENV=production`.
* `android_gateway`: an Android phone with a SIM sends the codes, using the open-source
  [SMS Gateway for Android](https://github.com/capcom6/android-sms-gateway) app (Apache-2.0).
  1. Install the app on a spare Android phone that has a SIM with SMS balance.
  2. In the app, turn on **Local Server**. Note the address, the username and the password it shows.
  3. Put the phone on the same network as the server. Then set these in `.env`:
     `SMS_PROVIDER=android_gateway`, `SMS_GATEWAY_URL=http://<phone-ip>:8080`, `SMS_GATEWAY_USERNAME=...` and
     `SMS_GATEWAY_PASSWORD=...`.
  4. Restart the backend.

  There is no SMS company account or API fee. But **every code is a normal SMS from that SIM**, charged by your
  mobile plan and subject to its daily SMS limits. The phone must stay on and reachable.
* There is no genuinely free SMS service for production; commercial SMS providers charge per message, and Indian
  bulk SMS additionally needs DLT registration of the sender and message template.
Interactive docs with an **Authorize** button: http://localhost:8000/api/v1/docs.
Before deploying anywhere real, set a strong `JWT_SECRET_KEY` (the app refuses to start in
`APP_ENV=production` otherwise).

## 4. Crop catalog seed
Farmers choose crops from a catalog that starts **empty**. Load the starter set (19 common Karnataka
crops; safe to re-run, never overwrites admin edits):
```powershell
cd backend
.\.venv\Scripts\python.exe -m app.cli.seed_crops
```
Durations are indicative and the Kannada names are for display — have an agronomist/native speaker
review them, then correct via `PATCH /api/v1/crops/{id}` (admin). Farm-management endpoints are
documented in `docs/ARCHITECTURE.md` §4.1 and live at http://localhost:8000/api/v1/docs.

## 4b. Trying the planner
With the server running, open http://localhost:8000/api/v1/docs, **Authorize** with a farmer token, and try
`POST /planning/calculate` (stateless) or save a scenario with `POST /crop-plans` and read
`GET /crop-plans/{id}/evaluation`. Every result includes `explanations`, `assumptions` and a `disclaimer`;
read them — the numbers are estimates over the ranges you enter, never guarantees. Reference:
`docs/ARCHITECTURE.md` §4.2.

## 5. Validation
```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate.ps1
```
`validate.ps1` starts the compose database, defaults `TEST_DATABASE_URL` to
`...localhost:5433/harvestique_test` and runs ruff, mypy, pytest and an Alembic drift check.
The test suite creates the `harvestique_test` database if missing, applies the real migrations, and
wipes data between tests. It refuses to run against any database whose name does not contain "test".
Without `TEST_DATABASE_URL`, the 566 database-backed tests are **skipped** (pytest `-ra` lists them).

Run them directly:
```powershell
cd backend
$env:TEST_DATABASE_URL="postgresql+psycopg://harvestique:harvestique@localhost:5433/harvestique_test"
.\.venv\Scripts\python.exe -m pytest            # everything
.\.venv\Scripts\python.exe -m pytest -m "not integration"   # fast, DB-free subset (the full suite takes ~1.5 minutes; the 216 planning-engine unit tests take about 2 seconds)
```

## 6. Migrations
```powershell
cd backend
.\.venv\Scripts\alembic.exe revision --autogenerate -m "add users"
.\.venv\Scripts\alembic.exe upgrade head
```
Always review autogenerated migrations before committing.

## 7. Ollama (local AI for the assistant)
Install Ollama for Windows, then `ollama pull llama3.2:3b` (2 GB). Set `LLM_PROVIDER=ollama` and `OLLAMA_MODEL` in
`.env`. The model must appear in `ollama list`, or the assistant treats the model as unavailable and uses its keyword
rules only. Backend in Docker reaches native Ollama via `http://host.docker.internal:11434` (already set in
docker-compose). To run Ollama in Docker instead: `docker compose --profile ai up -d` and set
`OLLAMA_DOCKER_URL=http://ollama:11434`.

What the model does, the measured speed on this project's CPU-only PC and the hardware advice: see
`docs/AI_PIPELINE.md` ("Local model"). The assistant keeps working without Ollama: questions the keyword rules
understand are answered from your records as usual, and only free-form questions get "I did not understand".
