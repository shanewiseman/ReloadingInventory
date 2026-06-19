# Behavior TODOs

No open behavior TODOs.

## Completed

### Automatically promote the next lot during multi-lot consumption

Implemented 2026-06-19.

- Committed batch consumption that depletes an active lot promotes exactly one non-depleted inactive successor lot consumed by the same batch.
- The depleted lot is deactivated and remains historically visible.
- The promoted successor receives the system-managed opened date.
- Promotion is skipped and audited when multiple consumed successor lots are eligible.
- Reservation-only and cancellation paths do not promote successor lots.
