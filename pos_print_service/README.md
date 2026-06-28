# Reload Ledger POS Print Service

This is a standalone HTTP-to-ESC/POS bridge for a Rongta RP326 connected over Ethernet. It is intended to run on a Raspberry Pi or another Docker host near the printer.

## Configure

Create a `.env` file next to this directory:

```dotenv
PRINTER_HOST=192.168.1.50
PRINTER_PORT=9100
POS_PRINT_SERVICE_PORT=8088
PRINT_WIDTH_CHARS=42
PRINT_IMAGE_WIDTH_PX=576
POS_PRINT_LOGO_FILE=/home/pi/wiseman-logo.png
```

`PRINTER_PORT` defaults to `9100`, but the RP326 port is configurable because site firmware/network settings may differ.
`POS_PRINT_LOGO_FILE` is optional. It mounts one PNG file into the container as a local fallback logo.

## Run

From the repository root:

```bash
docker compose -f pos_print_service/compose.yaml --env-file pos_print_service/.env up --build -d
```

Set Reload Ledger **Settings -> POS printing** printer hosts to the POS service host name or IP address only:

```text
Batch created printer host: <pi-host-or-ip>
Batch produced printer host: <pi-host-or-ip>
```

Reload Ledger adds `http://`, the configured POS service port, and the event path (`/print/batch-created` or `/print/batch-produced`) when it sends the print request. The renderer uses `POS_PRINT_SERVICE_PORT`, which defaults to `8088`.

## Dry-run Test Container

For integration testing without a physical printer, deploy the dry-run container:

```bash
docker compose -f pos_print_service/compose.test.yaml up --build -d
```

It accepts the same print API calls as the real service:

```text
http://<host-or-ip>:8089/print/batch-created
http://<host-or-ip>:8089/print/batch-produced
http://<host-or-ip>:8089/print/test
```

In dry-run mode the service renders the same ESC/POS byte stream but does not open a TCP connection to a printer. Successful responses return `status: accepted`, `mode: dry_run`, byte count, and a `job_id`.

The dry-run container keeps a bounded in-memory job log for test assertions:

```bash
curl http://localhost:8089/print/jobs
curl -X DELETE http://localhost:8089/print/jobs
```

Use the dry-run service host in Reload Ledger **Settings -> POS printing** to test app-to-service integration before pointing the settings at the physical printer deployment. The configured host should not include `http://`, a port, or a `/print/...` path.

## Logo

Reload Ledger sends the uploaded PNG logo with each print event. That is the normal production path: upload the logo once in Reload Ledger Settings and every configured POS service receives it in the request payload.

The POS service also supports an optional local fallback logo for standalone use, direct `/print/test` calls, or manual sample payloads that do not include a logo. Set `POS_PRINT_LOGO_FILE` in `.env` to mount a specific host PNG file at `/srv/pos-print/logo.png` inside the container. If `POS_PRINT_LOGO_FILE` is unset, the compose file mounts `/dev/null` and the fallback is ignored.

Thermal-friendly logo guidance:

- PNG only.
- Black on white; avoid transparent backgrounds.
- 384-512 px wide is a practical target.
- Keep total width at or under 576 px for 80 mm paper with roughly 72 mm printable width.
- Avoid gradients, fine textures, and strokes thinner than 2-3 px.

## Direct Printer Tests

The test script can print without going through the main Reload Ledger app:

```bash
python3 pos_print_service/scripts/test_print.py text "Printer online"
python3 pos_print_service/scripts/test_print.py image ./logo.png
python3 pos_print_service/scripts/test_print.py sample batch-created
```

Use `--service-url http://<pi-host-or-ip>:8088` when running the script from another machine.
