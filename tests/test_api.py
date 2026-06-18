from datetime import date

from tests.conftest import register_and_login


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


def create_complete_recipe(client, auth):
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
    inventory = {lot["item"]["category"]: lot for lot in client.get(
        "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
    ).json["lots"]}
    assert inventory["POWDER"]["reserved_quantity"] == 100
    assert inventory["POWDER"]["available_quantity"] == 0
    assert inventory["POWDER"]["opened_on"] == date.today().isoformat()

    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "IN STORAGE"})
    assert response.status_code == 200, response.json
    inventory = {lot["item"]["category"]: lot for lot in client.get(
        "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
    ).json["lots"]}
    assert inventory["POWDER"]["reserved_quantity"] == 0
    assert inventory["POWDER"]["consumed_quantity"] == 100
    assert inventory["POWDER"]["depleted"] is True


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
