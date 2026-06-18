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

    response = client.post(f"/api/batches/{batch['id']}/transition", headers=auth, json={"state": "IN STORAGE"})
    assert response.status_code == 200, response.json
    inventory = {lot["item"]["category"]: lot for lot in client.get(
        "/api/inventory-lots", headers=auth, query_string={"historical": "true"}
    ).json["lots"]}
    assert inventory["POWDER"]["reserved_quantity"] == 0
    assert inventory["POWDER"]["consumed_quantity"] == 100
    assert inventory["POWDER"]["depleted"] is True


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

