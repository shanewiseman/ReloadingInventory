from datetime import date
import uuid

from tests.conftest import register_and_login
from storage_service.models import Batch, ContainerAssignment, StorageContainer, db


def create_item(client, auth, category, name):
    response = client.post("/api/items", headers=auth, json={
        "category": category, "manufacturer": "Test Maker", "name": name,
    })
    assert response.status_code == 201, response.json
    return response.json["item"]


def create_lot(client, auth, item, quantity, unit, active=True):
    response = client.post("/api/inventory-lots", headers=auth, json={
        "item_id": item["id"], "quantity": quantity, "unit": unit, "active": active,
        "manufacturer_lot": f"LOT-{item['id']}",
    })
    assert response.status_code == 201, response.json
    return response.json["lot"]


def create_complete_recipe(client, auth, include_source=True):
    recipe = client.post("/api/recipes", headers=auth, json={
        "title": "Test 357", "cartridge": ".357 Magnum", "acknowledge_responsibility": True,
    }).json["recipe"]
    items = {
        "BULLET": create_item(client, auth, "BULLET", "158 gr JHP"),
        "POWDER": create_item(client, auth, "POWDER", "Test Powder"),
        "PRIMER": create_item(client, auth, "PRIMER", "Small Pistol Primer"),
        "CASE": create_item(client, auth, "CASE", "357 Case"),
    }
    quantities = {"BULLET": (1, "count"), "POWDER": (10, "grains"), "PRIMER": (1, "count"), "CASE": (1, "count")}
    components = {}
    for role, item in items.items():
        quantity, unit = quantities[role]
        response = client.post(f"/api/recipes/{recipe['id']}/components", headers=auth, json={
            "item_id": item["id"], "role": role, "quantity": quantity, "unit": unit,
        })
        assert response.status_code == 201, response.json
        components[role] = response.json["component"]
    if include_source:
        response = client.post(f"/api/recipes/{recipe['id']}/sources", headers=auth, json={
            "kind": "MANUAL", "citation": "Published test manual", "page": "42",
        })
        assert response.status_code == 201
    return recipe, items, components


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


def test_new_active_lot_can_replace_existing_active_lot(client, auth):
    primer = create_item(client, auth, "PRIMER", "Primer")
    first = create_lot(client, auth, primer, 100, "count")

    response = client.post("/api/inventory-lots", headers=auth, json={
        "item_id": primer["id"],
        "quantity": 200,
        "unit": "count",
        "active": True,
        "replace_active": True,
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
        "acknowledge_non_approved": True,
    })
    assert response.status_code == 201, response.json
    batch = response.json["batch"]
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
    assert inventory["POWDER"]["opened_on"] == date.today().isoformat()

    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "PRODUCED"})
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
        json={"state": "PRODUCED"},
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
    assert inventory[successor_bullet["id"]]["opened_on"] == date.today().isoformat()
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
        json={"state": "PRODUCED"},
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
        json={"state": "PRODUCED"},
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
        json={"state": "PRODUCED"},
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
    assert response.json["lot"]["opened_on"] == date.today().isoformat()


def test_opened_date_from_creation_payload_is_ignored(client, auth):
    primer = create_item(client, auth, "PRIMER", "Primer")
    response = client.post("/api/inventory-lots", headers=auth, json={
        "item_id": primer["id"], "quantity": 100, "unit": "count",
        "active": True, "opened_on": "2000-01-01",
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
