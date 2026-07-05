#!/usr/bin/env python3
"""Backfill Reload Ledger cartridge workflows for existing tenants.

Run from inside the storage service container:

    python /app/scripts/backfill_cartridge_workflows.py
    python /app/scripts/backfill_cartridge_workflows.py --apply

Or copy this file onto the production host and run:

    docker compose -f compose.prod.yaml --env-file .env.production cp scripts/backfill_cartridge_workflows.py storage:/tmp/backfill_cartridge_workflows.py
    docker compose -f compose.prod.yaml --env-file .env.production exec storage python /tmp/backfill_cartridge_workflows.py
    docker compose -f compose.prod.yaml --env-file .env.production exec storage python /tmp/backfill_cartridge_workflows.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path("/app")))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage_service.app import create_app
from storage_service.models import (
    CartridgeWorkflow,
    InventoryLot,
    Item,
    ItemCartridgeWorkflow,
    Recipe,
    StorageContainer,
    User,
    db,
)


MAGNUM = ".357 Magnum"
WINCHESTER = ".308 Winchester"


def workflow_for(user_id, name):
    return CartridgeWorkflow.query.filter_by(user_id=user_id, name=name).first()


def ensure_workflow(user_id, name, apply):
    workflow = workflow_for(user_id, name)
    if workflow or not apply:
        return workflow
    workflow = CartridgeWorkflow(user_id=user_id, name=name, archived=False)
    db.session.add(workflow)
    db.session.flush()
    return workflow


def item_missing_count(user_id, workflow):
    if not workflow:
        return Item.query.filter_by(user_id=user_id).count()
    assigned = db.session.query(ItemCartridgeWorkflow.item_id).filter_by(
        user_id=user_id,
        cartridge_workflow_id=workflow.id,
    )
    return Item.query.filter(Item.user_id == user_id, Item.id.notin_(assigned)).count()


def recipe_update_count(user_id, workflow):
    if not workflow:
        return Recipe.query.filter_by(user_id=user_id).count()
    return Recipe.query.filter(
        Recipe.user_id == user_id,
        Recipe.cartridge_workflow_id != workflow.id,
    ).count() + Recipe.query.filter(
        Recipe.user_id == user_id,
        Recipe.cartridge_workflow_id.is_(None),
    ).count()


def container_update_count(user_id, workflow):
    if not workflow:
        return StorageContainer.query.filter_by(user_id=user_id).count()
    return StorageContainer.query.filter(
        StorageContainer.user_id == user_id,
        StorageContainer.cartridge_workflow_id != workflow.id,
    ).count() + StorageContainer.query.filter(
        StorageContainer.user_id == user_id,
        StorageContainer.cartridge_workflow_id.is_(None),
    ).count()


def assign_items(user_id, workflow):
    existing = {
        item_id for (item_id,) in db.session.query(ItemCartridgeWorkflow.item_id).filter_by(
            user_id=user_id,
            cartridge_workflow_id=workflow.id,
        ).all()
    }
    for item in Item.query.filter_by(user_id=user_id).order_by(Item.id).all():
        if item.id not in existing:
            db.session.add(ItemCartridgeWorkflow(
                user_id=user_id,
                item_id=item.id,
                cartridge_workflow_id=workflow.id,
            ))


def backfill_user(user, apply):
    magnum = workflow_for(user.id, MAGNUM)
    winchester = workflow_for(user.id, WINCHESTER)
    item_count = item_missing_count(user.id, magnum)
    inherited_lot_count = InventoryLot.query.filter_by(user_id=user.id).count()
    recipe_count = recipe_update_count(user.id, magnum)
    container_count = container_update_count(user.id, magnum)
    current_change = not magnum or user.current_cartridge_workflow_id != magnum.id

    print(
        f"{'APPLY' if apply else 'DRY'} user={user.email} "
        f"create_357={magnum is None} create_308={winchester is None} "
        f"assign_items={item_count} inherited_lots={inherited_lot_count} "
        f"set_recipes={recipe_count} set_containers={container_count} "
        f"set_current_357={current_change}"
    )

    if not apply:
        return

    magnum = ensure_workflow(user.id, MAGNUM, apply=True)
    ensure_workflow(user.id, WINCHESTER, apply=True)
    assign_items(user.id, magnum)
    Recipe.query.filter_by(user_id=user.id).update(
        {"cartridge_workflow_id": magnum.id},
        synchronize_session=False,
    )
    StorageContainer.query.filter_by(user_id=user.id).update(
        {"cartridge_workflow_id": magnum.id},
        synchronize_session=False,
    )
    user.current_cartridge_workflow_id = magnum.id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes; omit for dry run")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        users = User.query.order_by(User.email).all()
        if not users:
            print("No users found.")
        for user in users:
            backfill_user(user, args.apply)
        if args.apply:
            db.session.commit()
            print("Committed cartridge workflow backfill.")
        else:
            db.session.rollback()
            print("Dry run only. Re-run with --apply to commit.")


if __name__ == "__main__":
    main()
