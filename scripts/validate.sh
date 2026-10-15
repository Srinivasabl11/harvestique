#!/usr/bin/env bash
# Linux/macOS/CI equivalent of validate.ps1.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
failed=()
step() { local name="$1"; shift; echo; echo "== $name"; "$@" || failed+=("$name"); }

cd "$ROOT/backend"
[ -d .venv ] && source .venv/bin/activate
# DB-backed tests need a PostgreSQL test database (auto-created if the server is reachable).
DB_PORT="$(sed -n 's/^[[:space:]]*POSTGRES_HOST_PORT[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$ROOT/.env" 2>/dev/null | head -1)"
export TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+psycopg://harvestique:harvestique@localhost:${DB_PORT:-5433}/harvestique_test}"
echo "TEST_DATABASE_URL=$TEST_DATABASE_URL"
step "ruff lint"   ruff check .
step "ruff format" ruff format --check .
step "mypy"        mypy app
step "pytest"      python -m pytest
drift() { DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head >/dev/null && DATABASE_URL="$TEST_DATABASE_URL" alembic check; }
step "alembic drift" drift

cd "$ROOT"
python3 - <<'PY' || failed+=("compose yaml")
import yaml, sys
c = yaml.safe_load(open("docker-compose.yml"))
assert {"db", "backend", "ollama"} <= set(c["services"]), "missing services"
print("docker-compose.yml parses; services:", ", ".join(c["services"]))
PY
command -v docker >/dev/null && step "compose config" docker compose config --quiet
if command -v flutter >/dev/null; then
  cd "$ROOT/frontend"; step "flutter analyze" flutter analyze; step "flutter test" flutter test
else
  echo; echo "flutter not found - skipping frontend checks"
fi

if [ ${#failed[@]} -gt 0 ]; then echo; echo "FAILED: ${failed[*]}"; exit 1; fi
echo; echo "All checks passed."
