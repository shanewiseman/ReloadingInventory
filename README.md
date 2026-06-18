# Reload Ledger

A Dockerized, multi-tenant reloading traceability application based on the supplied specification. It tracks exact component items, acquisition lots, recipes, production batches, inventory reservations and consumption, returns/loss, storage containers, QR labels, and batch performance data.

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
SESSION_HOURS=12
SESSION_COOKIE_SECURE=true
LOCAL_RESET_ENABLED=true
```

Stop the services without deleting data:

```bash
docker compose down
```

Do not add `-v` unless you intentionally want to delete the database volume.

## Architecture

- `storage`: Flask JSON API, SQLAlchemy domain model, business rules, audit records, Alembic migrations, and the SQLite owner.
- `renderer`: separate Flask/Jinja browser application that calls the storage API and never opens the database.
- `web`: Nginx static asset server and browser-facing reverse proxy.

The storage container runs pending Alembic migrations before starting. SQLite and backups live in the persistent `/data` volume.

## Main workflows

1. Create exact component definitions under **Items**.
2. Add acquisition-based lots under **Inventory**. Powder input is normalized to grains; bullets, primers, and cases normalize to count.
3. Create a **Recipe**, add exact component items and at least one source, then advance its lifecycle.
4. Create a **Batch** with exact lot allocations. Inventory is reserved immediately.
5. Move the batch to `IN STORAGE` to commit reservations as consumed, or account for every reserved amount as returned/lost before cancellation.
6. Assign completed quantities to **Containers**, acknowledging mixed-batch storage when applicable.
7. Add one consolidated performance/quality record to the batch. Edits are flagged and audited.

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

Tests run in the Python 3.12 storage image:

```bash
docker compose run --rm storage pytest
```

They cover unit conversion, slug collision handling, lifecycle validation, tenant isolation, public recipe privacy, active-lot rules, reservation and consumption, depletion, shortage rollback, and explicit cancellation accounting.

## Backup and export

Use **Settings** to create a consistent SQLite backup in `/data/backups`. Tenant-scoped JSON and CSV exports are available there for items, inventory, recipes, batches, containers, performance records, and audit history.

For an additional host-side copy:

```bash
docker compose cp storage:/data/backups ./backups
```

Review and test backups before migrations or deployment changes.
