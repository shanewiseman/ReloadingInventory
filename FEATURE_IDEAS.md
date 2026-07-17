# Feature Ideas

Potential additions for Reload Ledger, focused on traceability, operational usefulness, and descriptive analytics without recommending powder charges, inferring safe loads, or certifying recipes as safe.

## Current Baseline

The current implementation already includes cartridge workflows, source file uploads, stored file management, POS batch-created/batch-produced receipts, Android WebView limited mode, firearm profiles, bullet ballistic metadata, a ballistics calculator, Open-Meteo weather lookup, Garmin FIT import, QA measurements, cost-per-cartridge summaries, backups, exports, QR pages, and MCP workflow tools.

## Priority Candidates

### Range Session Log

Allow multiple test sessions per batch instead of one consolidated performance record.

- Capture firearm, target distance, chronograph string, group size, weather, target photos, and notes per session.
- Preserve imported Garmin FIT data as a session source.
- Roll session summaries up to batch and recipe-level analytics.

### Printable Batch Travelers

Generate a production sheet for each batch.

- Include recipe, lot allocations, QA checklist, warnings, acknowledgements, QR codes, and signature/date fields.
- Support browser PDF output and optional POS/thermal summaries.
- Store traveler generation events in audit history.

### Lot and Container Scanning

Add mobile-friendly QR/barcode scanning for inventory lots, batches, and containers.

- Support receive lot, activate lot, assign container, mark partially used/used, record QA sample, and open detail views.
- Keep mutation controls aligned with readonly/mobile mode rules.
- Log scan-driven state changes in audit history.

## Inventory and Operations

### Inventory Planning

Add planning tools around existing inventory quantities.

- Per-item low-stock thresholds.
- "Enough inventory for X rounds" checks by recipe.
- Manual reorder watchlists and shopping/export lists.
- No marketplace or automated purchasing integration.

### Dashboard Alerts

Add actionable dashboard alerts.

- Under-production batches.
- Low inventory by user-defined threshold.
- Missing recipe sources.
- Recipes stuck under test.
- Containers not fully assigned.
- Backup age.
- Lots with unresolved adjustments or notable loss/return events.

### Import and Bulk Tools

Add preview-first import workflows.

- CSV import for items, inventory lots, firearm profiles, and historical batches.
- Validation summary before commit.
- Audit import batches and rejected rows.

## Storage and Traceability

### Container History

Track full container occupancy history.

- Record what was added, removed, depleted, transferred, and when.
- Preserve mixed-batch acknowledgement history.
- Support container retirement.

### Label Printing

Expand print support beyond batch receipts.

- Inventory lot labels.
- Container labels.
- Batch travelers.
- Recipe cards.
- Include QR, item identity, lot number, quantity, and key warnings.

### Source Library Enhancements

Improve source records and verification evidence beyond the current uploaded-file/source-metadata workflow.

- Versioned citations.
- Searchable notes or OCR text.
- Page/image previews.
- Source tags.
- "Verified against source on" fields.

## Quality and Analytics

### Recipe and Batch Analytics

Add descriptive analytics only.

- Velocity trends.
- Standard deviation and extreme spread trends.
- Cost-per-round trends.
- QA variance.
- Lot-to-lot comparisons.
- Recipe scorecards based on user-entered performance data.

### QA Tolerances

Let users define target and tolerance bands.

- Completed weight.
- Overall length.
- Velocity.
- Group size.
- Flag outliers and require acknowledgement before production completion.

## Platform Hardening

### Operational Hardening

Improve deployment and account operations.

- Scoped API tokens.
- Session and device management.
- PostgreSQL support.
- Scheduled backups.
- Restore verification.
- Admin console.
