from datetime import datetime, timezone
from io import BytesIO
import sqlite3
import struct
import uuid

from sqlalchemy.exc import OperationalError

from tests.conftest import register_and_login
from storage_service.models import Batch, ContainerAssignment, StorageContainer, StoredFile, db, utcnow

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)


def today_utc():
    return utcnow().date().isoformat()


def test_database_errors_return_json(app):
    @app.get("/api/readonly-database-test")
    def readonly_database_test():
        raise OperationalError(
            "INSERT INTO audit_log",
            {},
            sqlite3.OperationalError("attempt to write a readonly database"),
        )

    response = app.test_client().get("/api/readonly-database-test")

    assert response.status_code == 500
    assert response.json["error"] == {
        "code": "database_readonly",
        "message": "Storage database is not writable",
        "details": {},
    }


def create_item(client, auth, category, name, **fields):
    payload = {
        "category": category, "manufacturer": "Test Maker", "name": name,
    }
    payload.update(fields)
    response = client.post("/api/items", headers=auth, json=payload)
    assert response.status_code == 201, response.json
    return response.json["item"]


def create_lot(client, auth, item, quantity, unit, active=True, cost=None, weight_grains=None):
    payload = {
        "item_id": item["id"], "quantity": quantity, "unit": unit, "active": active,
        "manufacturer_lot": f"LOT-{item['id']}",
    }
    if cost is not None:
        payload["cost"] = cost
    if weight_grains is None:
        weight_grains = {"PRIMER": "3.5", "CASE": "75", "OTHER": "1"}.get(item["category"])
    if weight_grains is not None:
        payload["weight_grains"] = weight_grains
    response = client.post("/api/inventory-lots", headers=auth, json=payload)
    assert response.status_code == 201, response.json
    return response.json["lot"]


def create_complete_recipe(client, auth, include_source=True):
    recipe = client.post("/api/recipes", headers=auth, json={
        "title": "Test 357", "cartridge": ".357 Magnum", "acknowledge_responsibility": True,
    }).json["recipe"]
    items = {
        "BULLET": create_item(client, auth, "BULLET", "158 gr JHP", bullet_weight="158"),
        "POWDER": create_item(client, auth, "POWDER", "Test Powder"),
        "PRIMER": create_item(client, auth, "PRIMER", "Small Pistol Primer"),
        "CASE": create_item(client, auth, "CASE", "357 Case"),
    }
    quantities = {"BULLET": (1, "count"), "POWDER": (10, "grains"), "PRIMER": (1, "count"), "CASE": (1, "count")}
    components = {}
    for role, item in items.items():
        quantity, unit = quantities[role]
        component_payload = {
            "item_id": item["id"], "role": role, "quantity": quantity, "unit": unit,
        }
        response = client.post(f"/api/recipes/{recipe['id']}/components", headers=auth, json=component_payload)
        assert response.status_code == 201, response.json
        components[role] = response.json["component"]
    if include_source:
        response = client.post(f"/api/recipes/{recipe['id']}/sources", headers=auth, json={
            "kind": "MANUAL", "citation": "Published test manual", "page": "42",
        })
        assert response.status_code == 201
    return recipe, items, components


def create_produced_batch(client, auth, iterations=10):
    recipe, items, components = create_complete_recipe(client, auth)
    lots = {
        "BULLET": create_lot(client, auth, items["BULLET"], iterations, "count"),
        "POWDER": create_lot(client, auth, items["POWDER"], iterations * 10, "grains"),
        "PRIMER": create_lot(client, auth, items["PRIMER"], iterations, "count"),
        "CASE": create_lot(client, auth, items["CASE"], iterations, "count"),
    }
    allocations = [
        {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
         "quantity": iterations * 10 if role == "POWDER" else iterations}
        for role in components
    ]
    response = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"], "iterations": iterations, "allocations": allocations,
        "acknowledge_non_approved": True,
    })
    assert response.status_code == 201, response.json
    batch = response.json["batch"]
    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "PRODUCED", "qa_override": True})
    assert response.status_code == 200, response.json
    return response.json["batch"]


def create_batch_from_recipe(client, auth, recipe, items, components, iterations=10):
    lots = {
        "BULLET": create_lot(client, auth, items["BULLET"], iterations, "count"),
        "POWDER": create_lot(client, auth, items["POWDER"], iterations * 10, "grains"),
        "PRIMER": create_lot(client, auth, items["PRIMER"], iterations, "count"),
        "CASE": create_lot(client, auth, items["CASE"], iterations, "count"),
    }
    allocations = [
        {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
         "quantity": iterations * 10 if role == "POWDER" else iterations}
        for role in components
    ]
    response = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"], "iterations": iterations, "allocations": allocations,
        "acknowledge_non_approved": True,
    })
    assert response.status_code == 201, response.json
    return response.json["batch"], lots


def xero_fit_bytes(started_at, velocities_mps, shot_start=1):
    def timestamp(value):
        return int((value - FIT_EPOCH).total_seconds())

    data = bytearray()
    data.extend(definition(0, 0, [(4, 4, 134), (1, 2, 132), (2, 2, 132), (3, 4, 140), (0, 1, 0)]))
    data.extend(record(0, struct.pack("<IHHIB", timestamp(started_at), 1, 4053, 123456789, 54)))
    data.extend(definition(1, 23, [(3, 4, 140), (2, 2, 132), (4, 2, 132), (5, 2, 132)]))
    data.extend(record(1, struct.pack("<IHHH", 123456789, 1, 4053, 332)))
    data.extend(definition(2, 387, [(253, 4, 134), (0, 4, 134), (1, 4, 134), (2, 4, 134), (5, 4, 134), (6, 4, 134), (3, 2, 132), (4, 1, 0)]))
    speeds = [int(velocity * 1000) for velocity in velocities_mps]
    average = round(sum(speeds) / len(speeds))
    data.extend(record(2, struct.pack("<IIIIIIHB", 0xFFFFFFFF, min(speeds), max(speeds), average, 1580, 0, len(speeds), 1)))
    data.extend(definition(3, 388, [(253, 4, 134), (0, 4, 134), (1, 2, 132)]))
    for index, speed in enumerate(speeds):
        data.extend(record(3, struct.pack("<IIH", timestamp(started_at) + index * 4, speed, shot_start + index)))
    header = bytearray([14, 16])
    header.extend(struct.pack("<H", 21147))
    header.extend(struct.pack("<I", len(data)))
    header.extend(b".FIT")
    header.extend(b"\0\0")
    return bytes(header + data + b"\0\0")


def definition(local, global_message, fields):
    body = bytearray([0x40 | local, 0, 0])
    body.extend(struct.pack("<H", global_message))
    body.append(len(fields))
    for number, size, base_type in fields:
        body.extend([number, size, base_type])
    return body


def record(local, payload):
    return bytes([local]) + payload


def test_tenant_isolation(client):
    owner = register_and_login(client, "owner@example.com")
    item = create_item(client, owner, "BULLET", "Private Bullet")
    viewer = register_and_login(client, "viewer@example.com")
    assert client.get(f"/api/items/{item['id']}", headers=viewer).status_code == 404
    assert client.patch(f"/api/items/{item['id']}", headers=viewer, json={"name": "Stolen"}).status_code == 404
    assert client.get("/api/items", headers=viewer).json["items"] == []


def test_active_lot_rule_and_powder_normalization(client, auth):
    powder = create_item(client, auth, "POWDER", "Powder")
    lot = create_lot(client, auth, powder, 1, "pounds")
    assert lot["normalized_quantity"] == 7000
    response = client.post("/api/inventory-lots", headers=auth, json={
        "item_id": powder["id"], "quantity": 1, "unit": "pounds", "active": True,
    })
    assert response.status_code == 409
    assert response.json["error"]["code"] == "active_lot_exists"


def test_inventory_lot_cost_is_stored_and_validated(client, auth):
    primer = create_item(client, auth, "PRIMER", "Primer")

    lot = create_lot(client, auth, primer, 1000, "count", cost="89.99")

    assert lot["cost"] == 89.99
    assert round(lot["unit_cost"], 5) == 0.08999

    response = client.patch(
        f"/api/inventory-lots/{lot['id']}",
        headers=auth,
        json={"cost": "79.50"},
    )

    assert response.status_code == 200, response.json
    assert response.json["lot"]["cost"] == 79.5
    assert response.json["lot"]["unit_cost"] == 0.0795

    response = client.post("/api/inventory-lots", headers=auth, json={
        "item_id": primer["id"],
        "quantity": 100,
        "unit": "count",
        "cost": "-1",
        "weight_grains": "3.5",
    })

    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_cost"


def test_new_active_lot_can_replace_existing_active_lot(client, auth):
    primer = create_item(client, auth, "PRIMER", "Primer")
    first = create_lot(client, auth, primer, 100, "count")

    response = client.post("/api/inventory-lots", headers=auth, json={
        "item_id": primer["id"],
        "quantity": 200,
        "unit": "count",
        "active": True,
        "replace_active": True,
        "weight_grains": "3.5",
    })

    assert response.status_code == 201, response.json
    second = response.json["lot"]
    lots = {
        lot["id"]: lot for lot in client.get(
            "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
        ).json["lots"]
    }
    assert lots[first["id"]]["active"] is False
    assert lots[second["id"]]["active"] is True
    assert sum(1 for lot in lots.values() if lot["active"]) == 1


def test_item_ignores_attributes_from_other_categories(client, auth):
    response = client.post("/api/items", headers=auth, json={
        "category": "POWDER",
        "manufacturer": "Test Maker",
        "name": "Test Powder",
        "caliber": ".357",
        "bullet_weight": 158,
        "bullet_type": "JHP",
        "primer_type": "Magnum",
        "powder_type": "Spherical",
    })

    assert response.status_code == 201
    item = response.json["item"]
    assert item["powder_type"] == "Spherical"
    assert item["caliber"] is None
    assert item["bullet_weight"] is None
    assert item["bullet_type"] is None
    assert item["primer_type"] is None


def test_traceability_metadata_is_editable_before_downstream_references(client, auth):
    primer = create_item(client, auth, "PRIMER", "Small primer")
    response = client.patch(f"/api/items/{primer['id']}", headers=auth, json={
        "category": "CASE",
        "manufacturer": "Updated Maker",
        "name": "357 brass",
        "caliber": ".357",
        "primer_type": "Small pistol",
    })
    assert response.status_code == 200, response.json
    item = response.json["item"]
    assert item["can_edit"] is True
    assert item["category"] == "CASE"
    assert item["caliber"] == ".357"
    assert item["primer_type"] is None

    lot = create_lot(client, auth, item, 100, "count")
    response = client.patch(f"/api/inventory-lots/{lot['id']}", headers=auth, json={
        "manufacturer_lot": "UPDATED-LOT",
        "quantity": 120,
        "unit": "count",
        "acquired_on": "2026-06-20",
        "opened_on": "2026-06-21",
        "notes": "Corrected receiving record.",
    })
    assert response.status_code == 200, response.json
    lot = response.json["lot"]
    assert lot["can_edit"] is True
    assert lot["manufacturer_lot"] == "UPDATED-LOT"
    assert lot["original_quantity"] == 120
    assert lot["acquired_on"] == "2026-06-20"
    assert lot["opened_on"] == "2026-06-21"

    recipe = client.post("/api/recipes", headers=auth, json={
        "title": "Editable Recipe",
        "cartridge": ".357 Magnum",
        "acknowledge_responsibility": True,
    }).json["recipe"]
    response = client.patch(f"/api/recipes/{recipe['id']}", headers=auth, json={
        "title": "Updated Recipe",
        "cartridge": ".38 Special",
        "notes": "Corrected cartridge before batching.",
    })
    assert response.status_code == 200, response.json
    assert response.json["recipe"]["can_edit"] is True
    assert response.json["recipe"]["title"] == "Updated Recipe"

    batch_recipe, items, components = create_complete_recipe(client, auth)
    batch, _lots = create_batch_from_recipe(client, auth, batch_recipe, items, components)
    response = client.patch(f"/api/batches/{batch['id']}", headers=auth, json={
        "slug": "editable-batch",
        "characteristics": "test batch",
        "notes": "Corrected before performance or storage.",
    })
    assert response.status_code == 200, response.json
    assert response.json["batch"]["can_edit"] is True
    assert response.json["batch"]["slug"] == "editable-batch"
    assert response.json["batch"]["characteristics"] == "test batch"

    container = client.post("/api/containers", headers=auth, json={
        "identifier": "BOX-1",
        "name": "Original Box",
        "cartridge_limit": 50,
    }).json["container"]
    response = client.patch(f"/api/containers/{container['id']}", headers=auth, json={
        "identifier": "BOX-2",
        "name": "Updated Box",
        "cartridge_limit": 60,
        "description": "Corrected before assignment.",
    })
    assert response.status_code == 200, response.json
    assert response.json["container"]["can_edit"] is True
    assert response.json["container"]["identifier"] == "BOX-2"
    assert response.json["container"]["cartridge_limit"] == 60


def test_traceability_metadata_locks_after_downstream_references(client, auth):
    item = create_item(client, auth, "PRIMER", "Locking primer")
    lot = create_lot(client, auth, item, 100, "count")

    item_record = client.get(f"/api/items/{item['id']}", headers=auth).json["item"]
    assert item_record["can_edit"] is False
    assert "Inventory lots" in item_record["edit_lock_reason"]
    response = client.patch(f"/api/items/{item['id']}", headers=auth, json={"name": "Changed"})
    assert response.status_code == 409
    assert response.json["error"]["code"] == "traceability_lock"

    response = client.post(f"/api/inventory-lots/{lot['id']}/adjustments", headers=auth, json={
        "quantity_change": -1,
        "reason": "Physical count correction",
    })
    assert response.status_code == 201, response.json
    lot_record = client.get("/api/inventory-lots", headers=auth, query_string={"historical": "true"}).json["lots"][0]
    assert lot_record["can_edit"] is False
    assert "Inventory adjustments" in lot_record["edit_lock_reason"]
    response = client.patch(f"/api/inventory-lots/{lot['id']}", headers=auth, json={"manufacturer_lot": "Changed"})
    assert response.status_code == 409
    assert response.json["error"]["code"] == "traceability_lock"

    recipe, items, components = create_complete_recipe(client, auth)
    batch, _lots = create_batch_from_recipe(client, auth, recipe, items, components)
    recipe_record = client.get(f"/api/recipes/{recipe['id']}", headers=auth).json["recipe"]
    assert recipe_record["can_edit"] is False
    assert "Batches" in recipe_record["edit_lock_reason"]
    response = client.patch(f"/api/recipes/{recipe['id']}", headers=auth, json={"title": "Changed"})
    assert response.status_code == 409
    response = client.post(f"/api/recipes/{recipe['id']}/sources", headers=auth, json={
        "kind": "MANUAL",
        "citation": "late source",
    })
    assert response.status_code == 409
    response = client.delete(
        f"/api/recipes/{recipe['id']}/components/{components['BULLET']['id']}",
        headers=auth,
    )
    assert response.status_code == 409

    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "PRODUCED", "qa_override": True})
    assert response.status_code == 200, response.json
    response = client.put(f"/api/batches/{batch['id']}/performance", headers=auth, json={
        "firearm": "Test revolver",
        "shot_count": 5,
    })
    assert response.status_code == 201, response.json
    batch_record = client.get(f"/api/batches/{batch['id']}", headers=auth).json["batch"]
    assert batch_record["can_edit"] is False
    assert "Performance" in batch_record["edit_lock_reason"]
    response = client.patch(f"/api/batches/{batch['id']}", headers=auth, json={"characteristics": "Changed"})
    assert response.status_code == 409

    container = client.post("/api/containers", headers=auth, json={
        "identifier": "LOCK-BOX",
        "name": "Lock Box",
        "cartridge_limit": 20,
    }).json["container"]
    response = client.post(f"/api/containers/{container['id']}/assignments", headers=auth, json={
        "batch_id": batch["id"],
        "quantity": 1,
    })
    assert response.status_code == 201, response.json
    container_record = response.json["container"]
    assert container_record["can_edit"] is False
    assert "Batch assignments" in container_record["edit_lock_reason"]
    response = client.patch(f"/api/containers/{container['id']}", headers=auth, json={"name": "Changed"})
    assert response.status_code == 409
    response = client.patch(f"/api/containers/{container['id']}", headers=auth, json={"state": "EMPTY"})
    assert response.status_code == 200, response.json


def test_recipe_public_view_excludes_private_fields(client, auth):
    recipe, _items, _components = create_complete_recipe(client, auth)
    response = client.patch(f"/api/recipes/{recipe['id']}", headers=auth, json={
        "public": True, "notes": "private note", "public_notes": "public note",
    })
    token = response.json["recipe"]["public_token"]
    public = client.get(f"/api/public/recipes/{token}").json["recipe"]
    assert public["notes"] == "public note"
    assert "source_notes" not in public
    assert "public_token" not in public
    assert "user_id" not in str(public)


def test_recipe_source_upload_creates_stored_file_link(client, auth):
    recipe, _items, _components = create_complete_recipe(client, auth, include_source=False)

    response = client.post(
        f"/api/recipes/{recipe['id']}/sources",
        headers=auth,
        data={
            "kind": "Uploaded document",
            "citation": "Scanned manual page",
            "page": "42",
            "source_file": (BytesIO(b"manual page"), "manual-page.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 201, response.json
    source = response.json["source"]
    assert source["kind"] == "UPLOADED DOCUMENT"
    assert source["file_name"] == "manual-page.pdf"
    assert source["stored_file_id"]
    assert source["stored_file"]["original_filename"] == "manual-page.pdf"
    assert source["stored_file"]["purpose"] == "RECIPE_SOURCE"
    stored_keys = [record.storage_key for record in StoredFile.query.order_by(StoredFile.id)]
    assert len(stored_keys) == 1
    assert stored_keys[0].startswith(f"recipes/{recipe['id']}/")


def test_recipe_aggregate_includes_deviation_and_moa(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    lots = {
        "BULLET": create_lot(client, auth, items["BULLET"], 10, "count"),
        "POWDER": create_lot(client, auth, items["POWDER"], 100, "grains"),
        "PRIMER": create_lot(client, auth, items["PRIMER"], 10, "count"),
        "CASE": create_lot(client, auth, items["CASE"], 10, "count"),
    }
    allocations = [
        {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
         "quantity": 100 if role == "POWDER" else 10}
        for role in components
    ]
    response = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"], "iterations": 10, "allocations": allocations,
        "acknowledge_non_approved": True,
    })
    assert response.status_code == 201, response.json
    batch = response.json["batch"]
    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "PRODUCED", "qa_override": True})
    assert response.status_code == 200, response.json
    response = client.put(
        f"/api/batches/{batch['id']}/performance",
        headers=auth,
        json={
            "standard_deviation": "8.4",
            "distance": "25",
            "group_size": "2.1",
        },
    )
    assert response.status_code == 201, response.json

    aggregate = client.get(f"/api/recipes/{recipe['id']}", headers=auth).json["recipe"]["aggregate_performance"]

    assert aggregate["average_standard_deviation"] == 8.4
    assert round(aggregate["average_moa"], 3) == 8.023


def test_recipe_list_includes_performance_and_cost_summary(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    lots = {
        "BULLET": create_lot(client, auth, items["BULLET"], 10, "count", cost="5"),
        "POWDER": create_lot(client, auth, items["POWDER"], 100, "grains", cost="10"),
        "PRIMER": create_lot(client, auth, items["PRIMER"], 10, "count", cost="1"),
        "CASE": create_lot(client, auth, items["CASE"], 10, "count", cost="4"),
    }
    allocations = [
        {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
         "quantity": 100 if role == "POWDER" else 10}
        for role in components
    ]
    response = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"], "iterations": 10, "allocations": allocations,
        "acknowledge_non_approved": True,
    })
    assert response.status_code == 201, response.json
    batch = response.json["batch"]
    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "PRODUCED", "qa_override": True})
    assert response.status_code == 200, response.json
    response = client.put(
        f"/api/batches/{batch['id']}/performance",
        headers=auth,
        json={"velocity_average": "1210", "standard_deviation": "8.4"},
    )
    assert response.status_code == 201, response.json

    listed = client.get("/api/recipes", headers=auth).json["recipes"]
    aggregate = next(row for row in listed if row["id"] == recipe["id"])["aggregate_performance"]

    assert aggregate["performance_record_count"] == 1
    assert aggregate["average_velocity"] == 1210
    assert aggregate["average_standard_deviation"] == 8.4
    assert aggregate["material_cost_status"] == "calculated"
    assert aggregate["cost_per_cartridge"] == 2


def test_recipe_rejects_second_component_for_same_core_role(client, auth):
    recipe = client.post("/api/recipes", headers=auth, json={
        "title": "Exact components", "cartridge": ".357 Magnum",
        "acknowledge_responsibility": True,
    }).json["recipe"]
    first = create_item(client, auth, "PRIMER", "Primer A")
    second = create_item(client, auth, "PRIMER", "Primer B")

    response = client.post(f"/api/recipes/{recipe['id']}/components", headers=auth, json={
        "item_id": first["id"], "role": "BULLET", "quantity": 1, "unit": "count",
        "alternative_group": "legacy-options",
    })
    assert response.status_code == 201
    assert response.json["component"]["role"] == "PRIMER"
    assert "alternative_group" not in response.json["component"]

    response = client.post(f"/api/recipes/{recipe['id']}/components", headers=auth, json={
        "item_id": second["id"], "quantity": 1, "unit": "count",
    })
    assert response.status_code == 409
    assert response.json["error"]["code"] == "component_role_exists"


def test_recipe_component_role_requires_only_item_category(client, auth):
    recipe = client.post("/api/recipes", headers=auth, json={
        "title": "Derived roles", "cartridge": ".357 Magnum",
        "acknowledge_responsibility": True,
    }).json["recipe"]
    powder = create_item(client, auth, "POWDER", "Derived Powder")

    response = client.post(f"/api/recipes/{recipe['id']}/components", headers=auth, json={
        "item_id": powder["id"], "quantity": 4.2, "unit": "grains",
    })

    assert response.status_code == 201, response.json
    assert response.json["component"]["role"] == "POWDER"


def test_inventory_lot_weight_required_for_case_primer_and_other(client, auth):
    primer = create_item(client, auth, "PRIMER", "Primer")
    response = client.post("/api/inventory-lots", headers=auth, json={
        "item_id": primer["id"], "quantity": 100, "unit": "count",
    })
    assert response.status_code == 400
    assert response.json["error"]["code"] == "lot_weight_required"

    response = client.post("/api/inventory-lots", headers=auth, json={
        "item_id": primer["id"], "quantity": 100, "unit": "count", "weight_grains": "3.5",
    })
    assert response.status_code == 201, response.json
    assert response.json["lot"]["weight_grains"] == 3.5
    assert response.json["lot"]["component_weight_grains"] == 3.5

    powder = create_item(client, auth, "POWDER", "Powder")
    response = client.post("/api/inventory-lots", headers=auth, json={
        "item_id": powder["id"], "quantity": 1, "unit": "pounds", "weight_grains": "999",
    })
    assert response.status_code == 201, response.json
    assert response.json["lot"]["weight_grains"] is None
    assert response.json["lot"]["component_weight_grains"] is None


def test_batch_expected_weight_uses_inventory_lot_weights_and_qa_variance(client, auth):
    recipe = client.post("/api/recipes", headers=auth, json={
        "title": "QA reference", "cartridge": ".357 Magnum", "overall_length": "1.5900",
        "acknowledge_responsibility": True,
    }).json["recipe"]
    items = {
        "BULLET": create_item(client, auth, "BULLET", "158 gr JHP", bullet_weight="158"),
        "POWDER": create_item(client, auth, "POWDER", "Test Powder"),
        "PRIMER": create_item(client, auth, "PRIMER", "Small Pistol Primer"),
        "CASE": create_item(client, auth, "CASE", "357 Case"),
    }
    payloads = {
        "BULLET": {"quantity": 1, "unit": "count"},
        "POWDER": {"quantity": "10", "unit": "grains"},
        "PRIMER": {"quantity": 1, "unit": "count"},
        "CASE": {"quantity": 1, "unit": "count"},
    }
    components = {}
    for role, item in items.items():
        payload = {"item_id": item["id"], **payloads[role]}
        response = client.post(f"/api/recipes/{recipe['id']}/components", headers=auth, json=payload)
        assert response.status_code == 201, response.json
        components[role] = response.json["component"]
    response = client.post(f"/api/recipes/{recipe['id']}/sources", headers=auth, json={
        "kind": "MANUAL", "citation": "Published test manual", "page": "42",
    })
    assert response.status_code == 201

    batch, _lots = create_batch_from_recipe(client, auth, recipe, items, components, iterations=10)
    assert batch["expected_weight_status"] == "calculated"
    assert batch["expected_weight_grains"] == 246.5
    primer_reservation = next(row for row in batch["reservations"] if row["role"] == "PRIMER")
    assert primer_reservation["component_weight_grains"] == 3.5
    response = client.put(
        f"/api/batches/{batch['id']}/qa-measurements",
        headers=auth,
        json={"measurements": [
            {"sample_number": 1, "completed_weight": "247.000", "overall_length": "1.5920"},
        ]},
    )
    assert response.status_code == 200, response.json
    measurement = response.json["batch"]["qa"]["measurements"][0]
    assert measurement["weight_variance"] == 0.5
    assert measurement["length_variance"] == 0.002
    assert response.json["batch"]["qa"]["average_weight_variance"] == 0.5
    assert response.json["batch"]["qa"]["average_length_variance"] == 0.002


def test_recipe_suggested_identity_is_unique_and_used_on_creation(client, auth):
    suggestion = client.get("/api/recipes/suggested-identity", headers=auth)
    assert suggestion.status_code == 200
    identity = suggestion.json["identity"]
    assert len(identity["title"].split()) == 2

    response = client.post("/api/recipes", headers=auth, json={
        "title": identity["title"],
        "suggested_title": identity["title"],
        "cartridge": ".357 Magnum",
        "acknowledge_responsibility": True,
    })
    assert response.status_code == 201, response.json
    assert response.json["recipe"]["title"] == identity["title"]
    uuid.UUID(response.json["recipe"]["id"])

    next_suggestion = client.get("/api/recipes/suggested-identity", headers=auth).json["identity"]
    assert next_suggestion["title"] != identity["title"]


def test_recipe_transition_without_source_requires_audited_override(client, auth):
    recipe, _items, _components = create_complete_recipe(client, auth, include_source=False)

    response = client.post(
        f"/api/recipes/{recipe['id']}/transition",
        headers=auth,
        json={"state": "UNDER TEST"},
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "acknowledgement_required"
    assert response.json["error"]["details"]["acknowledgement"] == (
        "MISSING_SOURCE_RECIPE_TRANSITION"
    )

    response = client.post(
        f"/api/recipes/{recipe['id']}/transition",
        headers=auth,
        json={"state": "UNDER TEST", "acknowledge_missing_source": True},
    )
    assert response.status_code == 200, response.json

    audit = client.get("/api/audit", headers=auth).json["audit"]
    override = next(
        row for row in audit
        if row["action"] == "ACKNOWLEDGED"
        and row["new_value"]["type"] == "MISSING_SOURCE_RECIPE_TRANSITION"
    )
    assert override["entity_type"] == "Recipe"


def test_recipe_can_transition_to_terminal_not_approved(client, auth):
    recipe, _items, _components = create_complete_recipe(client, auth)

    response = client.post(
        f"/api/recipes/{recipe['id']}/transition",
        headers=auth,
        json={"state": "UNDER TEST"},
    )
    assert response.status_code == 200, response.json

    response = client.post(
        f"/api/recipes/{recipe['id']}/transition",
        headers=auth,
        json={"state": "NOT APPROVED"},
    )
    assert response.status_code == 200, response.json
    assert response.json["recipe"]["state"] == "NOT APPROVED"

    response = client.post(
        f"/api/recipes/{recipe['id']}/transition",
        headers=auth,
        json={"state": "UNDER DEVELOPMENT"},
    )
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_transition"


def test_batch_without_source_requires_audited_override(client, auth):
    recipe, items, components = create_complete_recipe(client, auth, include_source=False)
    lots = {
        role: create_lot(
            client, auth, item,
            1000 if role == "POWDER" else 100,
            "grains" if role == "POWDER" else "count",
        )
        for role, item in items.items()
    }
    allocations = [
        {
            "component_id": components[role]["id"],
            "lot_id": lots[role]["id"],
            "quantity": 50 if role == "POWDER" else 5,
        }
        for role in components
    ]
    payload = {
        "recipe_id": recipe["id"],
        "iterations": 5,
        "allocations": allocations,
        "acknowledge_non_approved": True,
    }

    response = client.post("/api/batches", headers=auth, json=payload)
    assert response.status_code == 409
    assert response.json["error"]["code"] == "acknowledgement_required"
    assert response.json["error"]["details"]["acknowledgement"] == "MISSING_SOURCE_BATCH"

    payload["acknowledge_missing_source"] = True
    response = client.post("/api/batches", headers=auth, json=payload)
    assert response.status_code == 201, response.json
    batch = response.json["batch"]
    uuid.UUID(batch["id"])

    audit = client.get(
        "/api/audit",
        headers=auth,
        query_string={"entity_type": "Batch", "entity_id": batch["id"]},
    ).json["audit"]
    assert any(
        row["action"] == "ACKNOWLEDGED"
        and row["new_value"]["type"] == "MISSING_SOURCE_BATCH"
        for row in audit
    )


def test_batch_reservation_consumption_and_depletion(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    lots = {
        "BULLET": create_lot(client, auth, items["BULLET"], 10, "count"),
        "POWDER": create_lot(client, auth, items["POWDER"], 100, "grains"),
        "PRIMER": create_lot(client, auth, items["PRIMER"], 10, "count"),
        "CASE": create_lot(client, auth, items["CASE"], 10, "count"),
    }
    allocations = [
        {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
         "quantity": 100 if role == "POWDER" else 10}
        for role in components
    ]
    response = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"], "iterations": 10, "allocations": allocations,
        "characteristics": "Test batch",
        "acknowledge_non_approved": True,
    })
    assert response.status_code == 201, response.json
    batch = response.json["batch"]
    assert batch["characteristics"] == "Test batch"
    assert {component["role"] for component in batch["recipe"]["components"]} == {"BULLET", "POWDER", "PRIMER", "CASE"}
    response = client.put(
        f"/api/batches/{batch['id']}/performance",
        headers=auth,
        json={"notes": "Premature quality record"},
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "invalid_batch_state"
    inventory = {lot["item"]["category"]: lot for lot in client.get(
        "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
    ).json["lots"]}
    assert inventory["POWDER"]["reserved_quantity"] == 100
    assert inventory["POWDER"]["available_quantity"] == 0
    assert inventory["POWDER"]["opened_on"] == today_utc()

    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "PRODUCED", "qa_override": True})
    assert response.status_code == 200, response.json
    assert response.json["batch"]["state"] == "PRODUCED"
    response = client.put(
        f"/api/batches/{batch['id']}/performance",
        headers=auth,
        json={"notes": "Post-production quality record"},
    )
    assert response.status_code == 201, response.json
    inventory = {lot["item"]["category"]: lot for lot in client.get(
        "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
    ).json["lots"]}
    assert inventory["POWDER"]["reserved_quantity"] == 0
    assert inventory["POWDER"]["consumed_quantity"] == 100
    assert inventory["POWDER"]["depleted"] is True


def test_batch_requires_qa_measurements_before_produced(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    batch, _lots = create_batch_from_recipe(client, auth, recipe, items, components, iterations=10)

    assert batch["qa"]["required_sample_count"] == 1
    assert batch["qa"]["completed_sample_count"] == 0
    assert batch["qa"]["is_satisfied"] is False

    response = client.post(
        f"/api/batches/{batch['id']}/transition",
        headers=auth,
        json={"state": "PRODUCED"},
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "qa_required"
    assert response.json["error"]["details"] == {
        "required_sample_count": 1,
        "completed_sample_count": 0,
    }

    response = client.put(
        f"/api/batches/{batch['id']}/qa-measurements",
        headers=auth,
        json={"measurements": [
            {"sample_number": 1, "completed_weight": "247.125", "overall_length": "1.5900"},
        ]},
    )
    assert response.status_code == 200, response.json
    assert response.json["batch"]["qa"]["completed_sample_count"] == 1
    assert response.json["batch"]["qa"]["is_satisfied"] is True

    response = client.post(
        f"/api/batches/{batch['id']}/transition",
        headers=auth,
        json={"state": "PRODUCED"},
    )
    assert response.status_code == 200, response.json
    assert response.json["batch"]["state"] == "PRODUCED"


def test_batch_cost_per_cartridge_tracks_reserved_consumed_and_lost_materials(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    powder_source = create_lot(client, auth, items["POWDER"], 50, "grains", cost="10.00")
    powder_replacement = create_lot(client, auth, items["POWDER"], 100, "grains", active=False, cost="50.00")
    lots = {
        "BULLET": create_lot(client, auth, items["BULLET"], 5, "count", cost="2.50"),
        "POWDER": powder_source,
        "PRIMER": create_lot(client, auth, items["PRIMER"], 5, "count", cost="0.50"),
        "CASE": create_lot(client, auth, items["CASE"], 5, "count", cost="1.00"),
    }
    allocations = [
        {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
         "quantity": 50 if role == "POWDER" else 5}
        for role in components
    ]
    response = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 5,
        "allocations": allocations,
        "acknowledge_non_approved": True,
    })
    assert response.status_code == 201, response.json
    batch = response.json["batch"]
    assert batch["material_cost_basis"] == "reserved"
    assert batch["material_cost_status"] == "calculated"
    assert batch["material_cost"] == 14
    assert batch["cost_per_cartridge"] == 2.8

    powder_reservation = next(row for row in batch["reservations"] if row["lot_id"] == powder_source["id"])
    response = client.post(f"/api/batches/{batch['id']}/production-losses", headers=auth, json={
        "source_reservation_id": powder_reservation["id"],
        "replacement_lot_id": powder_replacement["id"],
        "quantity_lost": 10,
        "reason": "Powder spill",
    })
    assert response.status_code == 201, response.json
    batch = response.json["batch"]
    assert batch["material_cost_basis"] == "reserved"
    assert batch["material_cost"] == 19
    assert batch["cost_per_cartridge"] == 3.8
    assert next(row for row in batch["production_losses"] if row["source_lot_id"] == powder_source["id"])["material_cost"] == 2

    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "PRODUCED", "qa_override": True})
    assert response.status_code == 200, response.json
    batch = response.json["batch"]
    assert batch["material_cost_basis"] == "consumed"
    assert batch["material_cost"] == 19
    assert batch["cost_per_cartridge"] == 3.8


def test_batch_cost_is_unavailable_when_any_traced_lot_cost_is_missing(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    lots = {
        "BULLET": create_lot(client, auth, items["BULLET"], 5, "count", cost="2.50"),
        "POWDER": create_lot(client, auth, items["POWDER"], 50, "grains"),
        "PRIMER": create_lot(client, auth, items["PRIMER"], 5, "count", cost="0.50"),
        "CASE": create_lot(client, auth, items["CASE"], 5, "count", cost="1.00"),
    }
    response = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 5,
        "allocations": [
            {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
             "quantity": 50 if role == "POWDER" else 5}
            for role in components
        ],
        "acknowledge_non_approved": True,
    })

    assert response.status_code == 201, response.json
    batch = response.json["batch"]
    assert batch["material_cost_status"] == "missing_lot_cost"
    assert batch["material_cost"] is None
    assert batch["cost_per_cartridge"] is None
    assert batch["material_cost_missing_lot_ids"] == [lots["POWDER"]["id"]]


def test_garmin_import_stores_files_and_updates_derived_performance_only(client, auth):
    batch = create_produced_batch(client, auth, iterations=3)
    response = client.put(
        f"/api/batches/{batch['id']}/performance",
        headers=auth,
        json={
            "firearm": "Ruger GP100",
            "barrel_length": "4.2",
            "distance": "25",
            "group_size": "2.1",
            "recoil_perception": 3,
            "accuracy_perception": 4,
            "cleanliness_perception": 5,
            "subjective_rating": 4,
            "shot_count": 99,
        },
    )
    assert response.status_code == 201, response.json
    first = xero_fit_bytes(datetime(2024, 7, 27, 4, 44, 43, tzinfo=timezone.utc), [500, 510])
    second = xero_fit_bytes(datetime(2024, 7, 27, 4, 48, 7, tzinfo=timezone.utc), [520], shot_start=1)

    response = client.post(
        f"/api/batches/{batch['id']}/performance/garmin-import",
        headers=auth,
        data={"files": [(BytesIO(second), "later.fit"), (BytesIO(first), "earlier.fit")]},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200, response.json
    performance = response.json["performance"]
    assert performance["recorded_on"] == "2024-07-27"
    assert performance["firearm"] == "Ruger GP100"
    assert performance["barrel_length"] == 4.2
    assert performance["distance"] == 25
    assert performance["group_size"] == 2.1
    assert performance["recoil_perception"] == 3
    assert performance["accuracy_perception"] == 4
    assert performance["cleanliness_perception"] == 5
    assert performance["subjective_rating"] == 4
    assert performance["shot_count"] == 3
    assert performance["velocity_minimum"] == 1640.42
    assert performance["velocity_maximum"] == 1706.037
    assert performance["extreme_spread"] == 65.617
    assert performance["processed_data"]["chronograph"] == "Garmin Xero C1 Pro"
    assert [shot["sequence"] for shot in performance["processed_data"]["shots"]] == [1, 2, 3]
    assert [shot["source_filename"] for shot in performance["processed_data"]["shots"]] == [
        "earlier.fit",
        "earlier.fit",
        "later.fit",
    ]
    assert "Garmin Xero C1 Pro import" in performance["raw_data"]
    assert "Shot list" in performance["raw_data"]
    assert "1. 1640.420 fps" in performance["raw_data"]

    files = client.get("/api/files", headers=auth).json["files"]
    assert {file["original_filename"] for file in files} == {"later.fit", "earlier.fit"}
    assert {file["purpose"] for file in files} == {"GARMIN_IMPORT"}
    assert {file["entity_type"] for file in files} == {"Batch"}
    assert {file["entity_id"] for file in files} == {batch["id"]}
    stored_keys = [record.storage_key for record in StoredFile.query.order_by(StoredFile.id)]
    assert all(key.startswith(f"batches/{batch['slug']}/") for key in stored_keys)


def test_stored_file_delete_removes_file_record(client, auth):
    response = client.post(
        "/api/files",
        headers=auth,
        data={"files": (BytesIO(b"source material"), "source.txt"), "purpose": "manual"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201, response.json
    stored = response.json["files"][0]

    download = client.get(f"/api/files/{stored['id']}/download", headers=auth)
    assert download.status_code == 200
    assert download.get_data() == b"source material"

    response = client.delete(f"/api/files/{stored['id']}", headers=auth)
    assert response.status_code == 200
    assert client.get("/api/files", headers=auth).json["files"] == []
    assert client.get(f"/api/files/{stored['id']}/download", headers=auth).status_code == 404


def test_depleted_active_lot_promotes_single_consumed_successor(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    active_bullet = create_lot(client, auth, items["BULLET"], 5, "count")
    successor_bullet = create_lot(client, auth, items["BULLET"], 100, "count", active=False)
    powder = create_lot(client, auth, items["POWDER"], 100, "grains")
    primer = create_lot(client, auth, items["PRIMER"], 10, "count")
    case = create_lot(client, auth, items["CASE"], 10, "count")
    allocations = [
        {
            "component_id": components["BULLET"]["id"],
            "lot_id": active_bullet["id"],
            "quantity": 5,
        },
        {
            "component_id": components["BULLET"]["id"],
            "lot_id": successor_bullet["id"],
            "quantity": 5,
        },
        {"component_id": components["POWDER"]["id"], "lot_id": powder["id"], "quantity": 100},
        {"component_id": components["PRIMER"]["id"], "lot_id": primer["id"], "quantity": 10},
        {"component_id": components["CASE"]["id"], "lot_id": case["id"], "quantity": 10},
    ]
    response = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 10,
        "allocations": allocations,
        "acknowledge_non_approved": True,
    })
    assert response.status_code == 201, response.json
    batch = response.json["batch"]

    reserved_inventory = {
        lot["id"]: lot for lot in client.get(
            "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
        ).json["lots"]
    }
    assert reserved_inventory[active_bullet["id"]]["active"] is True
    assert reserved_inventory[active_bullet["id"]]["depleted"] is False
    assert reserved_inventory[successor_bullet["id"]]["active"] is False
    assert reserved_inventory[successor_bullet["id"]]["opened_on"] is None

    response = client.post(
        f"/api/batches/{batch['id']}/transition",
        headers=auth,
        json={"state": "PRODUCED", "qa_override": True},
    )
    assert response.status_code == 200, response.json

    inventory = {
        lot["id"]: lot for lot in client.get(
            "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
        ).json["lots"]
    }
    assert inventory[active_bullet["id"]]["depleted"] is True
    assert inventory[active_bullet["id"]]["active"] is False
    assert inventory[successor_bullet["id"]]["depleted"] is False
    assert inventory[successor_bullet["id"]]["active"] is True
    assert inventory[successor_bullet["id"]]["opened_on"] == today_utc()
    active_bullet_lots = [
        lot for lot in inventory.values()
        if lot["item_id"] == items["BULLET"]["id"] and lot["active"] and not lot["depleted"]
    ]
    assert [lot["id"] for lot in active_bullet_lots] == [successor_bullet["id"]]

    audit = client.get(
        "/api/audit",
        headers=auth,
        query_string={"entity_type": "InventoryLot", "limit": 500},
    ).json["audit"]
    assert any(
        row["entity_id"] == str(active_bullet["id"]) and row["action"] == "DEPLETED"
        for row in audit
    )
    assert any(
        row["entity_id"] == str(active_bullet["id"]) and row["action"] == "DEACTIVATED"
        for row in audit
    )
    assert any(
        row["entity_id"] == str(successor_bullet["id"]) and row["action"] == "OPENED"
        for row in audit
    )
    assert any(
        row["entity_id"] == str(successor_bullet["id"]) and row["action"] == "PROMOTED"
        for row in audit
    )


def test_ambiguous_consumed_successor_lots_are_not_promoted(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    active_bullet = create_lot(client, auth, items["BULLET"], 5, "count")
    first_successor = create_lot(client, auth, items["BULLET"], 100, "count", active=False)
    second_successor = create_lot(client, auth, items["BULLET"], 100, "count", active=False)
    powder = create_lot(client, auth, items["POWDER"], 100, "grains")
    primer = create_lot(client, auth, items["PRIMER"], 10, "count")
    case = create_lot(client, auth, items["CASE"], 10, "count")
    allocations = [
        {
            "component_id": components["BULLET"]["id"],
            "lot_id": active_bullet["id"],
            "quantity": 5,
        },
        {
            "component_id": components["BULLET"]["id"],
            "lot_id": first_successor["id"],
            "quantity": 3,
        },
        {
            "component_id": components["BULLET"]["id"],
            "lot_id": second_successor["id"],
            "quantity": 2,
        },
        {"component_id": components["POWDER"]["id"], "lot_id": powder["id"], "quantity": 100},
        {"component_id": components["PRIMER"]["id"], "lot_id": primer["id"], "quantity": 10},
        {"component_id": components["CASE"]["id"], "lot_id": case["id"], "quantity": 10},
    ]
    batch = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 10,
        "allocations": allocations,
        "acknowledge_non_approved": True,
    }).json["batch"]

    response = client.post(
        f"/api/batches/{batch['id']}/transition",
        headers=auth,
        json={"state": "PRODUCED", "qa_override": True},
    )
    assert response.status_code == 200, response.json

    inventory = {
        lot["id"]: lot for lot in client.get(
            "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
        ).json["lots"]
    }
    assert inventory[active_bullet["id"]]["depleted"] is True
    assert inventory[active_bullet["id"]]["active"] is False
    assert inventory[first_successor["id"]]["depleted"] is False
    assert inventory[first_successor["id"]]["active"] is False
    assert inventory[second_successor["id"]]["depleted"] is False
    assert inventory[second_successor["id"]]["active"] is False
    assert [
        lot for lot in inventory.values()
        if lot["item_id"] == items["BULLET"]["id"] and lot["active"] and not lot["depleted"]
    ] == []

    audit = client.get(
        "/api/audit",
        headers=auth,
        query_string={"entity_type": "InventoryLot", "limit": 500},
    ).json["audit"]
    assert any(
        row["entity_id"] == str(active_bullet["id"])
        and row["action"] == "PROMOTION_SKIPPED"
        and sorted(row["new_value"]["candidate_lot_ids"]) == sorted([
            first_successor["id"], second_successor["id"],
        ])
        for row in audit
    )
    assert not any(row["action"] == "PROMOTED" for row in audit)


def test_container_assignment_quantities_are_exposed(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    lots = {
        role: create_lot(
            client,
            auth,
            item,
            1000 if role == "POWDER" else 100,
            "grains" if role == "POWDER" else "count",
        )
        for role, item in items.items()
    }
    allocations = [
        {
            "component_id": components[role]["id"],
            "lot_id": lots[role]["id"],
            "quantity": 500 if role == "POWDER" else 50,
        }
        for role in components
    ]
    batch = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 50,
        "allocations": allocations,
        "acknowledge_non_approved": True,
    }).json["batch"]
    response = client.post(
        f"/api/containers/999/assignments",
        headers=auth,
        json={"batch_id": batch["id"], "quantity": 1},
    )
    assert response.status_code == 404

    container = client.post("/api/containers", headers=auth, json={
        "identifier": "CAN-1",
        "name": "Ammo Can 1",
        "cartridge_limit": 20,
    }).json["container"]

    response = client.post(
        f"/api/containers/{container['id']}/assignments",
        headers=auth,
        json={"batch_id": batch["id"], "quantity": 1},
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "invalid_batch_state"

    response = client.post(
        f"/api/batches/{batch['id']}/transition",
        headers=auth,
        json={"state": "PRODUCED", "qa_override": True},
    )
    assert response.status_code == 200, response.json

    response = client.post(
        f"/api/containers/{container['id']}/assignments",
        headers=auth,
        json={"batch_id": batch["id"], "quantity": 15},
    )

    assert response.status_code == 201, response.json
    batch_record = client.get(f"/api/batches/{batch['id']}", headers=auth).json["batch"]
    assert batch_record["state"] == "PARTIALLY IN STORAGE"
    assert batch_record["container_assigned_quantity"] == 15
    assert batch_record["container_unassigned_quantity"] == 35
    assert batch_record["containers"][0]["identifier"] == "CAN-1"
    container_record = client.get("/api/containers", headers=auth).json["containers"][0]
    assert container_record["state"] == "ASSIGNED"
    assert container_record["cartridge_limit"] == 20
    assert container_record["remaining_capacity"] == 5
    assert container_record["assignments"][0]["quantity"] == 15
    assert container_record["assignments"][0]["batch_quantity"] == 50

    response = client.post(
        f"/api/containers/{container['id']}/assignments",
        headers=auth,
        json={"batch_id": batch["id"], "quantity": 6},
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "invalid_quantity"
    assert response.json["error"]["message"] == "Assignment exceeds the container cartridge limit"

    second_container = client.post("/api/containers", headers=auth, json={
        "identifier": "CAN-2",
        "name": "Ammo Can 2",
        "cartridge_limit": 35,
    }).json["container"]
    response = client.post(
        f"/api/containers/{second_container['id']}/assignments",
        headers=auth,
        json={"batch_id": batch["id"], "quantity": 35},
    )
    assert response.status_code == 201, response.json
    batch_record = client.get(f"/api/batches/{batch['id']}", headers=auth).json["batch"]
    assert batch_record["state"] == "IN STORAGE"
    assert batch_record["container_assigned_quantity"] == 50
    assert batch_record["container_unassigned_quantity"] == 0

    response = client.patch(
        f"/api/containers/{container['id']}",
        headers=auth,
        json={"state": "PARTIALLY USED"},
    )
    assert response.status_code == 200, response.json
    batch_record = client.get(f"/api/batches/{batch['id']}", headers=auth).json["batch"]
    assert batch_record["state"] == "PARTIALLY DEPLETED"

    response = client.patch(
        f"/api/containers/{container['id']}",
        headers=auth,
        json={"state": "USED"},
    )
    assert response.status_code == 200, response.json
    response = client.patch(
        f"/api/containers/{second_container['id']}",
        headers=auth,
        json={"state": "USED"},
    )
    assert response.status_code == 200, response.json
    batch_record = client.get(f"/api/batches/{batch['id']}", headers=auth).json["batch"]
    assert batch_record["state"] == "DEPLETED"

    response = client.patch(
        f"/api/containers/{container['id']}",
        headers=auth,
        json={"state": "EMPTY"},
    )
    assert response.status_code == 200, response.json
    emptied = response.json["container"]
    assert emptied["state"] == "EMPTY"
    assert emptied["assignments"] == []
    assert emptied["total_quantity"] == 0
    assert emptied["remaining_capacity"] == 20
    batch_record = client.get(f"/api/batches/{batch['id']}", headers=auth).json["batch"]
    assert batch_record["state"] == "DEPLETED"
    assert batch_record["container_depleted_quantity"] == 15
    assert batch_record["container_unassigned_quantity"] == 0

    response = client.patch(
        f"/api/containers/{second_container['id']}",
        headers=auth,
        json={"state": "EMPTY"},
    )
    assert response.status_code == 200, response.json
    batch_record = client.get(f"/api/batches/{batch['id']}", headers=auth).json["batch"]
    assert batch_record["state"] == "DEPLETED"
    assert batch_record["container_depleted_quantity"] == 50
    assert batch_record["container_assigned_quantity"] == 0
    assert batch_record["container_unassigned_quantity"] == 0
    response = client.post(
        f"/api/batches/{batch['id']}/transition",
        headers=auth,
        json={"state": "DECOMMISSIONED"},
    )
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_transition"

    second_allocations = [
        {
            "component_id": components[role]["id"],
            "lot_id": lots[role]["id"],
            "quantity": 100 if role == "POWDER" else 10,
        }
        for role in components
    ]
    second_batch = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 10,
        "allocations": second_allocations,
        "acknowledge_non_approved": True,
    }).json["batch"]
    response = client.post(
        f"/api/batches/{second_batch['id']}/transition",
        headers=auth,
        json={"state": "PRODUCED", "qa_override": True},
    )
    assert response.status_code == 200, response.json
    response = client.post(
        f"/api/containers/{container['id']}/assignments",
        headers=auth,
        json={"batch_id": second_batch["id"], "quantity": 10},
    )
    assert response.status_code == 201, response.json
    reused = response.json["container"]
    assert reused["state"] == "ASSIGNED"
    assert len(reused["assignments"]) == 1
    assert reused["assignments"][0]["batch_id"] == second_batch["id"]


def test_legacy_assigned_under_production_batch_is_reconciled(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    lots = {
        role: create_lot(
            client,
            auth,
            item,
            1000 if role == "POWDER" else 100,
            "grains" if role == "POWDER" else "count",
        )
        for role, item in items.items()
    }
    allocations = [
        {
            "component_id": components[role]["id"],
            "lot_id": lots[role]["id"],
            "quantity": 250 if role == "POWDER" else 25,
        }
        for role in components
    ]
    batch = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 25,
        "allocations": allocations,
        "acknowledge_non_approved": True,
    }).json["batch"]
    container = client.post("/api/containers", headers=auth, json={
        "identifier": "LEGACY-CAN",
        "name": "Legacy Can",
        "cartridge_limit": 25,
    }).json["container"]

    with client.application.app_context():
        batch_record = Batch.query.filter_by(identifier=batch["id"]).one()
        container_record = db.session.get(StorageContainer, container["id"])
        db.session.add(ContainerAssignment(
            user_id=batch_record.user_id,
            container_id=container_record.id,
            batch_id=batch_record.id,
            quantity=25,
        ))
        container_record.state = "ASSIGNED"
        db.session.commit()

    response = client.get(f"/api/batches/{batch['id']}", headers=auth)

    assert response.status_code == 200
    repaired = response.json["batch"]
    assert repaired["state"] == "IN STORAGE"
    assert repaired["container_assigned_quantity"] == 25
    assert repaired["container_unassigned_quantity"] == 0
    assert all(row["status"] == "CONSUMED" for row in repaired["reservations"])
    inventory = client.get(
        "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
    ).json["lots"]
    assert sum(lot["reserved_quantity"] for lot in inventory) == 0


def test_inactive_lot_is_opened_when_activated_after_first_drawdown(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    lots = {
        role: create_lot(
            client, auth, item, 1000 if role == "POWDER" else 100,
            "grains" if role == "POWDER" else "count", active=False,
        )
        for role, item in items.items()
    }
    allocations = [
        {
            "component_id": components[role]["id"],
            "lot_id": lots[role]["id"],
            "quantity": 50 if role == "POWDER" else 5,
        }
        for role in components
    ]
    response = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"], "iterations": 5, "allocations": allocations,
        "acknowledge_non_approved": True,
    })
    assert response.status_code == 201, response.json

    inventory = {
        lot["id"]: lot for lot in client.get("/api/inventory-lots", headers=auth).json["lots"]
    }
    assert inventory[lots["PRIMER"]["id"]]["opened_on"] is None

    response = client.patch(
        f"/api/inventory-lots/{lots['PRIMER']['id']}", headers=auth, json={"active": True}
    )
    assert response.status_code == 200
    assert response.json["lot"]["opened_on"] == today_utc()


def test_opened_date_from_creation_payload_is_ignored(client, auth):
    primer = create_item(client, auth, "PRIMER", "Primer")
    response = client.post("/api/inventory-lots", headers=auth, json={
        "item_id": primer["id"], "quantity": 100, "unit": "count",
        "active": True, "opened_on": "2000-01-01", "weight_grains": "3.5",
    })

    assert response.status_code == 201
    assert response.json["lot"]["opened_on"] is None


def test_inventory_adjustment_can_deplete_and_restore_lot(client, auth):
    primer = create_item(client, auth, "PRIMER", "Primer")
    lot = create_lot(client, auth, primer, 100, "count")

    response = client.post(
        f"/api/inventory-lots/{lot['id']}/adjustments",
        headers=auth,
        json={
            "deplete_remaining": True,
            "reason": "Physical count correction",
            "notes": "Container was empty.",
        },
    )
    assert response.status_code == 201, response.json
    assert response.json["adjustment"]["quantity_change"] == -100
    assert response.json["lot"]["available_quantity"] == 0
    assert response.json["lot"]["depleted"] is True
    assert response.json["lot"]["active"] is False

    response = client.post(
        f"/api/inventory-lots/{lot['id']}/adjustments",
        headers=auth,
        json={"quantity_change": 5, "reason": "Found inventory"},
    )
    assert response.status_code == 201, response.json
    assert response.json["lot"]["available_quantity"] == 5
    assert response.json["lot"]["adjustment_quantity"] == -95
    assert response.json["lot"]["depleted"] is False
    assert response.json["lot"]["active"] is False

    history = client.get(
        f"/api/inventory-lots/{lot['id']}/adjustments", headers=auth
    )
    assert history.status_code == 200
    assert len(history.json["adjustments"]) == 2


def test_inventory_adjustment_rejects_overdraw_and_fractional_count(client, auth):
    primer = create_item(client, auth, "PRIMER", "Primer")
    lot = create_lot(client, auth, primer, 100, "count")

    response = client.post(
        f"/api/inventory-lots/{lot['id']}/adjustments",
        headers=auth,
        json={"quantity_change": -101, "reason": "Count correction"},
    )
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_quantity"

    response = client.post(
        f"/api/inventory-lots/{lot['id']}/adjustments",
        headers=auth,
        json={"quantity_change": -0.5, "reason": "Count correction"},
    )
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_quantity"


def test_inventory_adjustment_is_blocked_while_reserved(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    lots = {
        role: create_lot(
            client,
            auth,
            item,
            1000 if role == "POWDER" else 100,
            "grains" if role == "POWDER" else "count",
        )
        for role, item in items.items()
    }
    allocations = [
        {
            "component_id": components[role]["id"],
            "lot_id": lots[role]["id"],
            "quantity": 50 if role == "POWDER" else 5,
        }
        for role in components
    ]
    response = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 5,
        "allocations": allocations,
        "acknowledge_non_approved": True,
    })
    assert response.status_code == 201

    response = client.post(
        f"/api/inventory-lots/{lots['PRIMER']['id']}/adjustments",
        headers=auth,
        json={"quantity_change": -1, "reason": "Physical count correction"},
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "inventory_reserved"


def test_insufficient_inventory_rolls_back_batch(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    bullet_lot = create_lot(client, auth, items["BULLET"], 2, "count")
    allocations = [{"component_id": components["BULLET"]["id"], "lot_id": bullet_lot["id"], "quantity": 10}]
    response = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"], "iterations": 10, "allocations": allocations,
        "acknowledge_non_approved": True,
    })
    assert response.status_code in (400, 409)
    assert client.get("/api/batches", headers=auth).json["batches"] == []


def test_cancel_requires_explicit_return_and_loss(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    lots = {
        role: create_lot(client, auth, item, 1000 if role == "POWDER" else 100, "grains" if role == "POWDER" else "count")
        for role, item in items.items()
    }
    allocations = [
        {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
         "quantity": 50 if role == "POWDER" else 5}
        for role in components
    ]
    batch = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"], "iterations": 5, "allocations": allocations,
        "acknowledge_non_approved": True,
    }).json["batch"]
    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "CANCELLED"})
    assert response.status_code == 409
    for role, lot in lots.items():
        quantity = 50 if role == "POWDER" else 5
        response = client.post(f"/api/batches/{batch['id']}/returns", headers=auth, json={
            "source_lot_id": lot["id"], "quantity_returned": quantity - 1,
            "quantity_lost": 1, "reason": "Cancelled setup",
        })
        assert response.status_code == 201, response.json
    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "CANCELLED"})
    assert response.status_code == 200


def test_production_loss_replaces_reserved_material_from_compatible_lot(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    powder_source = create_lot(client, auth, items["POWDER"], 50, "grains")
    powder_replacement = create_lot(client, auth, items["POWDER"], 100, "grains", active=False)
    lots = {
        "BULLET": create_lot(client, auth, items["BULLET"], 5, "count"),
        "POWDER": powder_source,
        "PRIMER": create_lot(client, auth, items["PRIMER"], 5, "count"),
        "CASE": create_lot(client, auth, items["CASE"], 5, "count"),
    }
    allocations = [
        {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
         "quantity": 50 if role == "POWDER" else 5}
        for role in components
    ]
    batch = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 5,
        "allocations": allocations,
        "acknowledge_non_approved": True,
    }).json["batch"]
    powder_reservation = next(row for row in batch["reservations"] if row["lot_id"] == powder_source["id"])

    response = client.post(f"/api/batches/{batch['id']}/production-losses", headers=auth, json={
        "source_reservation_id": powder_reservation["id"],
        "replacement_lot_id": powder_replacement["id"],
        "quantity_lost": 7.42,
        "reason": "Powder spill",
    })

    assert response.status_code == 201, response.json
    assert response.json["production_loss"]["unit"] == "grains"
    reservations = response.json["batch"]["reservations"]
    source_reservation = next(row for row in reservations if row["id"] == powder_reservation["id"])
    replacement_reservation = next(row for row in reservations if row["lot_id"] == powder_replacement["id"])
    assert source_reservation["quantity"] == 42.58
    assert source_reservation["status"] == "RESERVED"
    assert replacement_reservation["quantity"] == 7.42

    inventory = {
        lot["id"]: lot for lot in client.get(
            "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
        ).json["lots"]
    }
    assert inventory[powder_source["id"]]["reserved_quantity"] == 42.58
    assert inventory[powder_source["id"]]["consumed_quantity"] == 7.42
    assert inventory[powder_source["id"]]["available_quantity"] == 0
    assert inventory[powder_replacement["id"]]["reserved_quantity"] == 7.42
    assert inventory[powder_replacement["id"]]["available_quantity"] == 92.58
    assert inventory[powder_replacement["id"]]["active"] is False

    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "PRODUCED", "qa_override": True})

    assert response.status_code == 200, response.json
    inventory = {
        lot["id"]: lot for lot in client.get(
            "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
        ).json["lots"]
    }
    assert inventory[powder_source["id"]]["reserved_quantity"] == 0
    assert inventory[powder_source["id"]]["consumed_quantity"] == 50
    assert inventory[powder_source["id"]]["depleted"] is True
    assert inventory[powder_source["id"]]["active"] is False
    assert inventory[powder_replacement["id"]]["reserved_quantity"] == 0
    assert inventory[powder_replacement["id"]]["consumed_quantity"] == 7.42
    assert inventory[powder_replacement["id"]]["active"] is True
    assert inventory[powder_replacement["id"]]["opened_on"] == today_utc()


def test_production_loss_can_replace_from_source_lot_available_inventory(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    lots = {
        "BULLET": create_lot(client, auth, items["BULLET"], 5, "count"),
        "POWDER": create_lot(client, auth, items["POWDER"], 60, "grains"),
        "PRIMER": create_lot(client, auth, items["PRIMER"], 5, "count"),
        "CASE": create_lot(client, auth, items["CASE"], 5, "count"),
    }
    batch = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 5,
        "allocations": [
            {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
             "quantity": 50 if role == "POWDER" else 5}
            for role in components
        ],
        "acknowledge_non_approved": True,
    }).json["batch"]
    powder_reservation = next(row for row in batch["reservations"] if row["lot_id"] == lots["POWDER"]["id"])

    response = client.post(f"/api/batches/{batch['id']}/production-losses", headers=auth, json={
        "source_reservation_id": powder_reservation["id"],
        "quantity_lost": 7.42,
        "reason": "Powder spill",
    })

    assert response.status_code == 201, response.json
    reservations = [row for row in response.json["batch"]["reservations"] if row["lot_id"] == lots["POWDER"]["id"]]
    assert sum(row["quantity"] for row in reservations if row["status"] == "RESERVED") == 50
    inventory = {
        lot["id"]: lot for lot in client.get(
            "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
        ).json["lots"]
    }
    assert inventory[lots["POWDER"]["id"]]["reserved_quantity"] == 50
    assert inventory[lots["POWDER"]["id"]]["consumed_quantity"] == 7.42
    assert inventory[lots["POWDER"]["id"]]["available_quantity"] == 2.58


def test_full_production_loss_depletes_source_and_promotes_replacement(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    powder_source = create_lot(client, auth, items["POWDER"], 50, "grains")
    powder_replacement = create_lot(client, auth, items["POWDER"], 100, "grains", active=False)
    lots = {
        "BULLET": create_lot(client, auth, items["BULLET"], 5, "count"),
        "POWDER": powder_source,
        "PRIMER": create_lot(client, auth, items["PRIMER"], 5, "count"),
        "CASE": create_lot(client, auth, items["CASE"], 5, "count"),
    }
    batch = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 5,
        "allocations": [
            {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
             "quantity": 50 if role == "POWDER" else 5}
            for role in components
        ],
        "acknowledge_non_approved": True,
    }).json["batch"]
    powder_reservation = next(row for row in batch["reservations"] if row["lot_id"] == powder_source["id"])

    response = client.post(f"/api/batches/{batch['id']}/production-losses", headers=auth, json={
        "source_reservation_id": powder_reservation["id"],
        "replacement_lot_id": powder_replacement["id"],
        "quantity_lost": 50,
        "reason": "Container spill",
    })

    assert response.status_code == 201, response.json
    source_reservation = next(row for row in response.json["batch"]["reservations"] if row["id"] == powder_reservation["id"])
    assert source_reservation["status"] == "REPLACED"
    inventory = {
        lot["id"]: lot for lot in client.get(
            "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
        ).json["lots"]
    }
    assert inventory[powder_source["id"]]["reserved_quantity"] == 0
    assert inventory[powder_source["id"]]["consumed_quantity"] == 50
    assert inventory[powder_source["id"]]["depleted"] is True
    assert inventory[powder_source["id"]]["active"] is False
    assert inventory[powder_replacement["id"]]["reserved_quantity"] == 50
    assert inventory[powder_replacement["id"]]["active"] is True
    assert inventory[powder_replacement["id"]]["opened_on"] == today_utc()

    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "PRODUCED", "qa_override": True})
    assert response.status_code == 200, response.json
    inventory = {
        lot["id"]: lot for lot in client.get(
            "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
        ).json["lots"]
    }
    assert inventory[powder_replacement["id"]]["reserved_quantity"] == 0
    assert inventory[powder_replacement["id"]]["consumed_quantity"] == 50


def test_production_loss_validates_replacement_lot_and_units(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    powder_source = create_lot(client, auth, items["POWDER"], 50, "grains")
    bullet_replacement = create_lot(client, auth, items["BULLET"], 10, "count")
    lots = {
        "BULLET": bullet_replacement,
        "POWDER": powder_source,
        "PRIMER": create_lot(client, auth, items["PRIMER"], 5, "count"),
        "CASE": create_lot(client, auth, items["CASE"], 5, "count"),
    }
    batch = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 5,
        "allocations": [
            {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
             "quantity": 50 if role == "POWDER" else 5}
            for role in components
        ],
        "acknowledge_non_approved": True,
    }).json["batch"]
    powder_reservation = next(row for row in batch["reservations"] if row["lot_id"] == powder_source["id"])
    bullet_reservation = next(row for row in batch["reservations"] if row["lot_id"] == bullet_replacement["id"])

    response = client.post(f"/api/batches/{batch['id']}/production-losses", headers=auth, json={
        "source_reservation_id": powder_reservation["id"],
        "replacement_lot_id": bullet_replacement["id"],
        "quantity_lost": 1,
        "reason": "Wrong replacement",
    })
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_replacement_lot"

    response = client.post(f"/api/batches/{batch['id']}/production-losses", headers=auth, json={
        "source_reservation_id": bullet_reservation["id"],
        "quantity_lost": 0.5,
        "reason": "Dropped component",
    })
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_quantity"

    response = client.post(f"/api/batches/{batch['id']}/production-losses", headers=auth, json={
        "source_reservation_id": powder_reservation["id"],
        "quantity_lost": 7.42,
        "reason": "Powder spill",
    })
    assert response.status_code == 409
    assert response.json["error"]["code"] == "insufficient_inventory"


def test_inventory_return_destination_must_be_in_batch_trace(client, auth):
    recipe, items, components = create_complete_recipe(client, auth)
    lots = {
        role: create_lot(client, auth, item, 1000 if role == "POWDER" else 100, "grains" if role == "POWDER" else "count")
        for role, item in items.items()
    }
    unrelated_lot = create_lot(client, auth, items["BULLET"], 100, "count", active=False)
    allocations = [
        {"component_id": components[role]["id"], "lot_id": lots[role]["id"],
         "quantity": 50 if role == "POWDER" else 5}
        for role in components
    ]
    batch = client.post("/api/batches", headers=auth, json={
        "recipe_id": recipe["id"],
        "iterations": 5,
        "allocations": allocations,
        "acknowledge_non_approved": True,
    }).json["batch"]

    response = client.post(f"/api/batches/{batch['id']}/returns", headers=auth, json={
        "source_lot_id": lots["BULLET"]["id"],
        "destination_lot_id": unrelated_lot["id"],
        "quantity_returned": 5,
        "quantity_lost": 0,
        "reason": "Cancelled setup",
    })

    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_destination"
    assert "batch inventory trace" in response.json["error"]["message"]
