"""Reconcile batches assigned to containers before derived states existed.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-18
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    metadata = sa.MetaData()
    batch = sa.Table("batch", metadata, autoload_with=connection)
    assignment = sa.Table("container_assignment", metadata, autoload_with=connection)
    container = sa.Table("storage_container", metadata, autoload_with=connection)
    reservation = sa.Table("batch_inventory_reservation", metadata, autoload_with=connection)
    consumption = sa.Table("batch_inventory_consumption", metadata, autoload_with=connection)
    lot = sa.Table("inventory_lot", metadata, autoload_with=connection)
    audit = sa.Table("audit_log", metadata, autoload_with=connection)

    assigned_batches = connection.execute(
        sa.select(batch).where(
            batch.c.id.in_(
                sa.select(assignment.c.batch_id).group_by(assignment.c.batch_id)
            )
        )
    ).mappings().all()
    now = datetime.now(timezone.utc)
    today = date.today()

    for row in assigned_batches:
        if row["state"] in {"CANCELLED", "DECOMMISSIONED"}:
            continue

        if row["state"] == "UNDER PRODUCTION":
            reserved_rows = connection.execute(
                sa.select(reservation).where(
                    reservation.c.batch_id == row["id"],
                    reservation.c.status == "RESERVED",
                )
            ).mappings().all()
            for reserved in reserved_rows:
                lot_row = connection.execute(
                    sa.select(lot).where(lot.c.id == reserved["inventory_lot_id"])
                ).mappings().first()
                if lot_row:
                    new_reserved = lot_row["reserved_quantity"] - reserved["quantity"]
                    new_consumed = lot_row["consumed_quantity"] + reserved["quantity"]
                    available = (
                        lot_row["normalized_quantity"]
                        + lot_row["adjustment_quantity"]
                        - new_reserved
                        - new_consumed
                    )
                    connection.execute(
                        lot.update()
                        .where(lot.c.id == reserved["inventory_lot_id"])
                        .values(
                            reserved_quantity=new_reserved,
                            consumed_quantity=new_consumed,
                            depleted=available <= 0,
                            active=False if available <= 0 else lot_row["active"],
                            opened_on=lot_row["opened_on"] or today,
                        )
                    )
                existing_consumption = connection.execute(
                    sa.select(consumption.c.id).where(
                        consumption.c.batch_id == reserved["batch_id"],
                        consumption.c.inventory_lot_id == reserved["inventory_lot_id"],
                        consumption.c.recipe_component_id == reserved["recipe_component_id"],
                    )
                ).first()
                if not existing_consumption:
                    connection.execute(
                        consumption.insert().values(
                            user_id=reserved["user_id"],
                            batch_id=reserved["batch_id"],
                            inventory_lot_id=reserved["inventory_lot_id"],
                            recipe_component_id=reserved["recipe_component_id"],
                            quantity=reserved["quantity"],
                            created_at=now,
                            updated_at=now,
                        )
                    )
                connection.execute(
                    reservation.update()
                    .where(reservation.c.id == reserved["id"])
                    .values(status="CONSUMED", updated_at=now)
                )

        target_state = _derived_state(connection, batch, assignment, container, row)
        if target_state != row["state"]:
            connection.execute(
                batch.update()
                .where(batch.c.id == row["id"])
                .values(state=target_state, updated_at=now)
            )
            connection.execute(
                audit.insert().values(
                    user_id=row["user_id"],
                    created_at=now,
                    entity_type="Batch",
                    entity_id=row["identifier"],
                    action="STATE_CHANGED",
                    previous_value={"state": row["state"]},
                    new_value={"state": target_state},
                    notes="Migration reconciled existing container assignments.",
                )
            )


def downgrade():
    # State reconciliation is data repair and is intentionally not reversed.
    pass


def _derived_state(connection, batch, assignment, container, batch_row):
    rows = connection.execute(
        sa.select(assignment.c.quantity, container.c.state)
        .join(container, container.c.id == assignment.c.container_id)
        .where(assignment.c.batch_id == batch_row["id"])
    ).mappings().all()
    assigned_quantity = sum(row["quantity"] for row in rows)
    if assigned_quantity <= 0:
        return "PRODUCED"
    has_depleted_container = any(row["state"] in {"PARTIALLY USED", "USED", "EMPTY"} for row in rows)
    all_depleted = all(row["state"] in {"USED", "EMPTY"} for row in rows)
    if has_depleted_container:
        if assigned_quantity >= batch_row["iterations"] and all_depleted:
            return "DEPLETED"
        return "PARTIALLY DEPLETED"
    if assigned_quantity >= batch_row["iterations"]:
        return "IN STORAGE"
    return "PARTIALLY IN STORAGE"
