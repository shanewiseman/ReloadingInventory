# Reload Ledger

A Dockerized, multi-tenant reloading traceability application based on the supplied specification. It tracks cartridge workflows, exact component items, acquisition lots, recipes, source files, production batches, inventory reservations and consumption, production loss, returns/loss, storage containers, QR labels, batch QA, performance data, firearm profiles, and saved ballistic calculations.

The application stores user-entered load data. It does not recommend powder charges, infer safe loads, or certify that a recipe is safe.

## Run

Requirements: Docker with the Compose plugin.

```bash
docker compose up --build -d
```

Open <http://localhost:8080>, create an account, and sign in. Data persists in the `reloading-data` Docker volume.

For non-development use, set strong random values in `.env`:

```dotenv
STORAGE_SECRET_KEY=replace-with-a-long-random-value
RENDERER_SECRET_KEY=replace-with-a-different-long-random-value
APP_PORT=8080
PUBLIC_BASE_URL=https://your-host.example
POS_PRINT_TIMEOUT_SECONDS=8
SESSION_HOURS=12
SESSION_COOKIE_SECURE=true
LOCAL_RESET_ENABLED=true
```

For production, prefer the dedicated compose file and a private `.env.production`:

```bash
cp .env.production.example .env.production
```

```bash
docker compose -f compose.prod.yaml --env-file .env.production up --build -d
```

The production compose file expects an external Traefik network named `dmz_internal` by default. Only the `web` service joins that network and receives Traefik/Authentik labels. The `renderer`, `storage`, and `ballistics` services stay on Reload Ledger's private Docker network and are not published to the host.

Create the host data directory before starting production:

```bash
mkdir -p /mnt/docker_data/dmz/reload-ledger/data
```

Stop the services without deleting data:

```bash
docker compose down
```

Do not add `-v` unless you intentionally want to delete the database volume.

## Architecture

- `storage`: Flask JSON API, SQLAlchemy domain model, business rules, audit records, Alembic migrations, and the SQLite owner.
- `renderer`: separate Flask/Jinja browser application that calls the storage API and never opens the database.
- `ballistics`: Flask service that calculates trajectory corrections with `py-ballisticcalc` and proxies Open-Meteo weather lookup. See `ballistics_service/README.md`.
- `web`: Nginx static asset server and browser-facing reverse proxy.
- `pos_print_service`: optional standalone HTTP-to-ESC/POS bridge for an Ethernet POS printer on another Docker host.

The storage container runs pending Alembic migrations before starting. SQLite and backups live in the persistent `/data` volume.

## POS printing

Reload Ledger can call one or more standalone printer-service deployments when a batch is created or transitions to `PRODUCED`. Configure this under **Settings -> POS printing** after deploying the printer service on the Raspberry Pi or other Docker host near the Rongta RP326.

Browser-created batch events print automatically when POS printing is enabled. MCP/API batch workflows do not print implicitly; call `POST /api/batches/<batch_id>/pos-print` with `{"event": "batch_created"}` or `{"event": "batch_produced"}` when you want an explicit receipt. Receipts triggered through this API include a "Printed by MCP call" marker near the top.

Set `POS_PRINT_DRY_RUN=true` on the main app stack when running automated browser tests or app-to-printer integration checks that must not contact a real printer service.

The printer service lives in `pos_print_service/` and exposes:

- `POST /print/batch-created`
- `POST /print/batch-produced`
- `POST /print/test`

The uploaded PNG logo in Settings is used both in the app header and in POS print payloads. See `pos_print_service/README.md` for Raspberry Pi compose setup, dry-run integration testing, logo guidance, and the guarded direct print utility.

## Main workflows

1. Select or create a cartridge workflow under the top-bar selector or **Settings -> Cartridge workflows**.
2. Create exact component definitions under **Items**. Bullet items can include ballistic coefficient metadata.
3. Add acquisition-based lots under **Inventory**. Powder input is normalized to grains; bullets, primers, and cases normalize to count. Optional lot cost is prorated into batch cost-per-cartridge metrics.
4. Create a **Recipe**, add exact component items, attach source metadata or uploaded source files, then advance its lifecycle.
5. Create a **Batch** with exact lot allocations. Inventory is reserved immediately.
6. Enter required under-production QA measurements or explicitly override the QA requirement, then transition the batch to `PRODUCED` to commit reservations as consumed.
7. Account for production loss, reserved returns, or cancellation return/loss when needed.
8. Assign completed quantities to **Containers**, acknowledging mixed-batch storage when applicable. Storage and depletion states are derived from container assignments and container lifecycle.
9. Add one consolidated performance/quality record to the batch or import Garmin Xero C1 Pro FIT files. Edits are flagged and audited.
10. Use **Firearms** and **Ballistics** to store firearm profiles, calculate trajectory corrections from user-entered data, fetch current weather inputs, and save calculations.

The advanced batch allocation JSON field permits explicit multi-lot allocation:

```json
[
  {"component_id": 1, "lot_id": 4, "quantity": 50},
  {"component_id": 1, "lot_id": 5, "quantity": 50}
]
```

## Account reset policy

Email recovery is intentionally not implemented. An operator marks an account for the configured local reset workflow:

```bash
docker compose exec storage flask --app storage_service.app mark-reset user@example.com
```

The next login redirects that user to the immediate local reset page. Existing sessions are revoked.

## Tests

Tests run in the Python 3.12 storage image. The default command runs the
standard non-Selenium suite; the browser workflow is opt-in below:

```bash
docker compose run --rm storage pytest
```

The standard suite covers unit conversion, lifecycle validation, tenant
isolation, cartridge workflows, source uploads, public recipe privacy,
active-lot rules, reservation and consumption, QA gates, production loss,
depletion, shortage rollback, explicit cancellation accounting, renderer
routes/templates, POS printing, ballistics calculations, and MCP workflows. The
opt-in Selenium workflow covers the full browser path.

## MCP API server

The repo includes a stdio Model Context Protocol server that lets an MCP-capable LLM client call the Reload Ledger storage API directly. Start the app first:

```bash
docker compose up --build -d
```

Then configure your MCP client to launch the server from this checkout:

```json
{
  "mcpServers": {
    "reload-ledger": {
      "command": "python3",
      "args": ["-m", "reloading_mcp"],
      "cwd": "/home/swiseman/repositories/reloading_app",
      "envFile": "/home/swiseman/repositories/reloading_app/.vscode/mcp.env",
      "env": {
        "RELOADING_API_BASE_URL": "http://localhost:8080"
      }
    }
  }
}
```

Available tools include `login`, `set_auth_token`, `logout`, `whoami`, `api_routes`, generic `api_get`/`api_post`/`api_patch`/`api_put`/`api_delete` calls, and workflow tools for creating sourced recipes, creating batches, assigning batches to containers, transitioning recipe/batch state, and explicitly printing batch POS events. Workflow creation tools require a preview first; they return an `approval_digest`, and creation only proceeds when the caller sends the same payload back with `approved: true` and the matching digest. Use `login` first, or provide an existing bearer token with `RELOADING_API_TOKEN` in `.vscode/mcp.env`. The local `.vscode/mcp.env` file is gitignored; `.vscode/mcp.env.example` documents the expected keys.

For a local protocol smoke test:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | RELOADING_API_BASE_URL=http://localhost:8080 python3 -m reloading_mcp
```

### Selenium workflow tests

The browser workflow test is opt-in because it needs a running app and a browser.

Run it headless with the Docker Selenium browser:

```bash
POS_PRINT_DRY_RUN=true docker compose --profile selenium up --build -d
docker compose run --rm \
  -e APP_BASE_URL=http://web:8080 \
  -e SELENIUM_REMOTE_URL=http://selenium:4444/wd/hub \
  storage pytest --run-selenium tests/e2e
```

Run the same remote browser in a visible virtual desktop:

```bash
POS_PRINT_DRY_RUN=true docker compose --profile selenium up --build -d
docker compose run --rm \
  -e APP_BASE_URL=http://web:8080 \
  -e SELENIUM_REMOTE_URL=http://selenium:4444/wd/hub \
  -e SELENIUM_HEADLESS=false \
  -e SELENIUM_SLOW_MS=350 \
  storage pytest --run-selenium tests/e2e
```

Then open <http://localhost:7900> to watch the browser.

If Chrome is installed locally, the host can run the test directly:

```bash
python3 -m pytest --run-selenium --app-base-url=http://localhost:8080 tests/e2e
```

Add `--selenium-headful` to show the local Chrome window. Add `--selenium-slow-ms=350` or set `SELENIUM_SLOW_MS=350` to pause after visible browser actions. The test creates an isolated user and calls `flask --app storage_service.app delete-user <email>` or `docker compose exec -T storage ... delete-user <email>` before and after the run when available.

## Backup and export

Use **Settings** to create a consistent SQLite backup in `/data/backups`. Tenant-scoped JSON and CSV exports are available there for items, inventory, recipes, batches, containers, performance records, firearm profiles, and audit history.

For an additional host-side copy:

```bash
docker compose cp storage:/data/backups ./backups
```

Review and test backups before migrations or deployment changes.

## Feature backlog

See [FEATURE_IDEAS.md](FEATURE_IDEAS.md) for planned and candidate capabilities that are not part of the current implementation.
