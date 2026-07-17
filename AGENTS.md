# AGENTS.md

Guidance for AI and human agents working in this repository. This file applies to
the entire checkout unless a more specific `AGENTS.md` is added in a
subdirectory.

## Project Summary

Reload Ledger is a Dockerized, multi-tenant reloading traceability application.
It tracks cartridge workflows, component items, acquisition lots, recipes,
source evidence, production batches, inventory reservations and consumption,
production loss, returns/loss, storage containers, QR labels, QA, performance
records, firearm profiles, and saved ballistic calculations.

The application stores user-entered load data. It must not recommend powder
charges, infer safe loads, certify recipes as safe, or replace published manuals
or manufacturer data.

## Non-Negotiable Safety Rules

- Do not recommend powder charges, component substitutions, safe loads, maximum
  loads, starting loads, seating depths, pressure expectations, or recipe
  safety conclusions.
- Do not infer that a recipe, batch, firearm, or ballistic calculation is safe.
  Treat all load data as user-supplied traceability data.
- Keep ballistics features descriptive only. They may calculate trajectory
  corrections from user-entered inputs, but must not suggest load data or safety
  decisions.
- Preserve source evidence, acknowledgements, audit history, and explicit user
  intent in workflow changes.
- POS printing can reach a physical printer. Use dry-run mode for automated
  tests and never bypass print guards casually.

## Repository Map

- `storage_service/`: Flask JSON API, SQLAlchemy models, business rules,
  migrations entrypoint, audit records, and SQLite ownership.
- `rendering_app/`: Flask/Jinja browser application. It talks to storage and
  ballistics over HTTP and should not open the database directly.
- `ballistics_service/`: Authenticated Flask service for trajectory calculation
  and Open-Meteo weather/geocode proxying.
- `pos_print_service/`: Standalone HTTP-to-ESC/POS bridge for Ethernet thermal
  printers, with dry-run support and guarded direct-print utilities.
- `reloading_mcp/`: stdio Model Context Protocol server for calling the storage
  API from MCP-capable clients.
- `nginx/`: Browser-facing reverse proxy and static asset routing.
- `migrations/`: Alembic migrations. The storage container applies pending
  migrations on startup.
- `tests/`: Unit, route, template, service, MCP, POS, and opt-in Selenium tests.
- `docs/`: Operator/test/specification documentation.
- `android/`: Android WebView shell documentation and related project files.

## Architecture Rules

- Keep storage business rules in `storage_service/`; renderer code should proxy
  to APIs instead of duplicating domain decisions.
- Keep browser/UI concerns in `rendering_app/`; do not import storage models into
  renderer routes or templates.
- Keep ballistics calculation and weather normalization in `ballistics_service/`.
  Storage may call the service, but should not reimplement solver logic.
- Keep printer transport and ESC/POS rendering in `pos_print_service/`; main app
  code should call configured print-service endpoints.
- Preserve tenant isolation on every storage route and query.
- Prefer explicit JSON error shapes already used by the services over new ad hoc
  response formats.

## Development Workflow

- Start by reading the relevant local code and tests before changing behavior.
- Keep changes narrowly scoped to the request and adjacent behavior.
- Do not rewrite unrelated docs, generated artifacts, or formatting.
- Do not delete or mutate persistent data volumes unless explicitly requested.
- Do not run `docker compose down -v` unless the user explicitly intends to
  delete the `reloading-data` volume.
- Leave unrelated untracked or modified files alone, including local helper
  directories such as `.local-scripts/` when present.
- Use `rg`/`rg --files` for searches where available.
- Prefer existing helper functions and patterns over new abstractions.

## Common Commands

Run the development stack:

```bash
docker compose up --build -d
```

Stop services without deleting data:

```bash
docker compose down
```

Run the full non-Selenium test suite:

```bash
POS_PRINT_DRY_RUN=true docker compose run --rm storage pytest -q
```

Run targeted tests:

```bash
docker compose run --rm storage pytest tests/test_api.py tests/test_domain.py -q
docker compose run --rm storage pytest tests/test_renderer_routes.py -q
docker compose run --rm storage pytest tests/test_templates.py -q
docker compose run --rm storage pytest tests/test_ballistics_service.py tests/test_ballistics_routing_config.py -q
docker compose run --rm storage pytest tests/test_pos_print_service.py tests/test_pos_print_script.py -q
docker compose run --rm storage pytest tests/test_mcp_server.py -q
```

Collect the current test inventory:

```bash
docker compose run --rm storage pytest --collect-only -q
```

Run Selenium workflow tests only when the stack and browser are intended:

```bash
POS_PRINT_DRY_RUN=true docker compose --profile selenium up --build -d
docker compose run --rm \
  -e APP_BASE_URL=http://web:8080 \
  -e SELENIUM_REMOTE_URL=http://selenium:4444/wd/hub \
  storage pytest --run-selenium tests/e2e -q
```

## Testing Expectations

- Add or update tests for behavior changes.
- Use focused tests for small changes, and broader tests when touching shared
  contracts, domain rules, migrations, service boundaries, or browser workflows.
- Renderer/template changes usually need `tests/test_renderer_routes.py` or
  `tests/test_templates.py`.
- Storage API/domain changes usually need `tests/test_api.py` and sometimes
  `tests/test_domain.py`.
- Ballistics changes usually need `tests/test_ballistics_service.py` and, for
  routing/configuration, `tests/test_ballistics_routing_config.py`.
- POS print changes usually need `tests/test_pos_print_service.py` or
  `tests/test_pos_print_script.py`.
- MCP tool or workflow changes usually need `tests/test_mcp_server.py`.
- Keep `POS_PRINT_DRY_RUN=true` for browser or integration runs that should not
  contact a real printer.

## Storage And Migrations

- Use Alembic for schema changes under `migrations/versions/`.
- Keep migrations forward-compatible with existing SQLite data.
- Update model serialization and API tests when adding fields.
- Preserve audit events for user-visible lifecycle and traceability changes.
- Be careful with Decimal/numeric parsing. Existing helpers are preferred for
  quantity, positive-number, and validation behavior.

## Renderer And Frontend

- Match existing Jinja/CSS/JavaScript style.
- Keep operational pages dense, scannable, and task-focused.
- Do not add marketing-style landing pages for app features.
- Keep client-side constraints aligned with backend validation, but never rely on
  client validation alone.
- If a static asset changes, follow the existing cache-bust query parameter
  pattern in templates and tests.
- Do not hide server errors with broad client-only handling; preserve useful
  flash messages and structured errors.

## Ballistics Service

- Treat all inputs as user-supplied descriptive inputs.
- Required physical inputs that feed the solver should validate as positive when
  the service requires positive values.
- Optional values should have explicit range semantics. For example, wind speed
  can be zero but not negative; supplied bullet weight must be positive.
- Weather lookup failures should return structured JSON errors and should not
  imply any safety recommendation.
- Keep solver metadata and warning behavior stable unless tests and docs are
  updated together.

## POS Printing

- The POS service may send bytes to a physical printer. Be deliberate.
- Automated tests and app-to-printer checks should use dry-run mode unless a live
  print is explicitly intended.
- The guarded direct-print script must refuse unverifiable or non-dry-run
  services unless `--allow-real-printer` is supplied.
- Preserve the MCP/API explicit print marker on receipts triggered through the
  explicit batch print API.
- Validate logo/image payloads defensively.

## MCP Server

- MCP workflow creation tools must keep their preview plus `approval_digest`
  contract. Do not allow creation without the matching approval digest.
- Keep route/path normalization and bearer-token handling covered by tests.
- Do not add MCP shortcuts that bypass storage service business rules.
- The application-specific MCP tools must not recommend loads or certify safety.

## Secrets And Local Files

- Do not commit `.env`, `.env.production`, `.vscode/mcp.env`, tokens, private
  keys, database files, backups, or printer credentials.
- `.env.production.example` and documented example values should remain safe to
  publish.
- Treat Codex/GitHub/MCP configuration outside the repository as sensitive.
- Avoid printing tokens or private-key contents in logs or final responses.

## Git And PR Hygiene

- Check `git status --short --branch` before and after changes.
- Commit only intended files. Do not include unrelated local files.
- Use descriptive commit messages with a useful body when addressing review
  feedback or behavior changes.
- When addressing PR review comments, reply on each relevant thread with whether
  you agree or disagree and what change was made or why no change was made.
- Request re-review only after fixes are committed, pushed, and relevant tests
  have passed.

## PR Review Workflow

When asked to address PR feedback for the current branch:

- Identify the current branch and find any open PR for that branch using the
  available GitHub tooling.
- Read all top-level PR comments, reviews, and review threads. Include newly
  added comments and follow-up comments on threads that were addressed in an
  earlier pass.
- Reply directly on each relevant thread with a stable `Codex parsed` marker
  that includes the GitHub actor or SSH identity used to authorize Codex/tooling
  for the change. Include agreement or disagreement, supporting rationale, and
  the remediation plan or completed fix. If a thread was already addressed, add
  a follow-up that states what commit or change handled it. Never include token
  values, private key contents, or other secrets in the marker.
- Treat agreed review comments as directives unless they conflict with safety,
  repository architecture, or explicit user instructions. For disagreements,
  explain the technical reason in the thread and avoid making that change.
- Leave review threads unresolved unless the user explicitly asks to resolve
  them.
- Make the smallest code, test, and documentation changes needed to satisfy the
  agreed comments. Preserve all safety boundaries, especially load-data and POS
  printer guardrails.
- Run focused tests for the changed behavior, plus broader tests when shared
  contracts or user-facing workflows are affected. Record skipped tests and the
  reason.
- Commit only the intended files. Use a descriptive commit subject and a body
  that identifies the PR review feedback addressed and summarizes the actual
  changes.
- Push the current branch to its upstream after tests pass. Use the user's
  provided SSH identity or GitHub authentication method when one was supplied;
  do not commit or print private key material.
- After the push succeeds, request re-review from the relevant reviewer or
  reviewer bot if the tooling supports it.

## Handoff Checklist

Before handing work back:

- Relevant tests were run, or any skipped tests are called out with the reason.
- Safety boundaries were preserved.
- No unrelated local files were modified or staged.
- No secrets or persistent data were committed.
- Any migrations, docs, route tests, or template tests needed by the change were
  updated.
- The final response summarizes changed behavior, verification, and remaining
  risks or blockers.
