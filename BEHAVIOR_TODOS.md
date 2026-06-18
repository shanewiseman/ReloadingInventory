# Behavior TODOs

## Automatically promote the next lot during multi-lot consumption

Current behavior:

- A batch can explicitly draw from an active lot and one or more inactive lots.
- When committed consumption depletes the active lot, that lot is automatically deactivated.
- A secondary lot used by the same batch remains inactive.
- The user must manually activate that secondary lot afterward.

Desired behavior:

- When committed batch consumption depletes the active lot, automatically promote the next non-depleted lot for the same item that was consumed by that batch.
- Mark the promoted lot as opened on its first committed consumption.
- Preserve the invariant that a user has no more than one active, non-depleted lot per item.
- Record the depletion, deactivation, opening, and promotion in the audit history.
- If multiple eligible successor lots were consumed, apply a deterministic rule or require the user to choose the successor during batch creation.

Acceptance criteria:

- Consuming the remainder of the active lot and continuing into one successor lot leaves the successor active.
- The depleted lot is inactive and remains historically visible.
- The successor lot has a system-managed opened date.
- No second active lot is created.
- Cancellation or reservation without committed consumption does not promote a lot.
- Multi-lot consumption involving multiple possible successors does not select one ambiguously.

