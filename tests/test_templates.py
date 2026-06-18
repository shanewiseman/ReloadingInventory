from flask import render_template, session

from rendering_app.app import create_app, recipe_allocations


def test_dashboard_renders_item_count_instead_of_dict_method():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    metrics = {
        "items": 3,
        "active_inventory_lots": 2,
        "depleted_inventory_lots": 1,
        "batches_under_production": 4,
        "recipes_by_state": {},
        "batches_by_state": {},
        "low_inventory": [],
        "recent_activity": [],
    }

    with app.test_request_context("/"):
        html = render_template("dashboard.html", metrics=metrics)

    assert "<strong>3</strong><span>Items</span>" in html
    assert "built-in method items" not in html
    assert 'href="/static/app.css?v=9"' in html


def test_authenticated_topbar_includes_help_menu():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    metrics = {
        "items": 0,
        "active_inventory_lots": 0,
        "depleted_inventory_lots": 0,
        "batches_under_production": 0,
        "recipes_by_state": {},
        "batches_by_state": {},
        "low_inventory": [],
        "recent_activity": [],
    }

    with app.test_request_context("/"):
        session["user"] = {"email": "test@example.com"}
        html = render_template("dashboard.html", metrics=metrics)

    assert "Help ▾" in html
    assert "Help videos ▸" in html
    assert html.count("https://www.youtube.com/shorts/cEiyRlvhy88") == 8
    for label in [
        "Dashboard", "Items", "Inventory", "Recipes",
        "Batches", "Containers", "Audit", "Settings",
    ]:
        assert f">{label}</a>" in html
    assert 'href="/download/help/llm-context"' in html
    assert "Information for LLM" in html


def test_item_form_marks_category_specific_fields():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})

    with app.test_request_context("/items"):
        html = render_template("items.html", items=[])

    assert 'data-item-categories="BULLET"' in html
    assert 'data-item-categories="PRIMER"' in html
    assert 'data-item-categories="POWDER"' in html
    assert 'src="/static/items.js?v=2"' in html


def test_item_table_uses_only_universal_columns():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    item = {
        "id": 7, "category": "BULLET", "manufacturer": "Maker", "name": "Bullet",
        "product_line": "Line", "characteristics": None, "caliber": ".357",
        "bullet_type": "JHP", "primer_type": None, "powder_type": None,
    }

    with app.test_request_context("/items"):
        html = render_template("items.html", items=[item])

    table_head = html[html.index("<thead>"):html.index("</thead>")]
    assert "<th>Category</th>" in table_head
    assert "<th>Item</th>" in table_head
    assert "<th>Characteristics</th>" in table_head
    assert "<th>Caliber</th>" not in table_head
    assert ".357" not in html
    assert "JHP" not in html


def test_existing_records_render_before_creation_forms():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    item = {
        "id": 7, "category": "PRIMER", "manufacturer": "Maker", "name": "Primer",
        "product_line": None, "caliber": None, "characteristics": None,
        "bullet_type": None, "primer_type": "Small pistol", "powder_type": None,
    }
    lot = {
        "id": 9, "item": item, "manufacturer_lot": "LOT-9",
        "original_quantity": 100, "original_unit": "count", "adjustment_quantity": 0,
        "normalized_unit": "count", "opened_on": None, "available_quantity": 100,
        "reserved_quantity": 0, "consumed_quantity": 0, "depleted": False, "active": True,
    }
    recipe = {
        "id": "9b10b7ad-a78a-4c67-99f4-3c1b74855f89",
        "title": "Existing Recipe", "cartridge": ".357",
        "state": "UNDER DEVELOPMENT", "warnings": [],
    }

    with app.test_request_context("/items"):
        item_html = render_template("items.html", items=[item])
    with app.test_request_context("/inventory"):
        inventory_html = render_template(
            "inventory.html", items=[item], lots=[lot],
            historical="false", active_item_ids={7},
        )
    with app.test_request_context("/recipes"):
        recipe_html = render_template(
            "recipes.html", recipes=[recipe],
            suggested_identity={"title": "Craft Anvil"},
        )

    assert item_html.index("Maker Primer") < item_html.index("<summary>Add item</summary>")
    assert inventory_html.index("LOT-9") < inventory_html.index("<summary>Add lot</summary>")
    assert recipe_html.index("Existing Recipe") < recipe_html.index("<summary>Create recipe</summary>")


def test_containers_render_before_creation_form_with_batch_quantities():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    batch = {
        "id": "869fc201-b09c-4dc4-9cea-63bb4c12b5a4",
        "slug": "test-batch",
        "iterations": 50,
        "state": "PRODUCED",
        "container_unassigned_quantity": 35,
        "recipe": {"title": "Test Recipe"},
    }
    full_batch = {
        "id": "e522df63-6313-43b9-a987-952c9af7ae84",
        "slug": "full-batch",
        "iterations": 50,
        "state": "PRODUCED",
        "container_unassigned_quantity": 0,
        "recipe": {"title": "Full Recipe"},
    }
    container = {
        "id": 7,
        "identifier": "CAN-1",
        "name": "Ammo Can 1",
        "state": "ASSIGNED",
        "total_quantity": 15,
        "cartridge_limit": 25,
        "remaining_capacity": 10,
        "assignments": [{
            "batch_id": batch["id"],
            "batch_slug": batch["slug"],
            "recipe": "Test Recipe",
            "quantity": 15,
            "batch_quantity": 50,
        }],
    }

    with app.test_request_context("/containers"):
        html = render_template(
            "containers.html", containers=[container], batches=[batch, full_batch]
        )

    assert html.index("Ammo Can 1") < html.index("<summary>Create container</summary>")
    assert 'id="container-7"' in html
    assert "CAN-1 · 15 / 25 cartridges" in html
    assert '<a href="/batches/869fc201-b09c-4dc4-9cea-63bb4c12b5a4">test-batch</a>' in html
    assert "15 / 50" in html
    assert (
        '<form action="/containers/7/state" method="post" '
        'class="inline container-lifecycle-menu" data-container-state-form>'
    ) in html
    assert '<label>Lifecycle<select name="state" data-current-state="ASSIGNED">' in html
    assert "<summary>Lifecycle</summary>" not in html
    assert ">Transition</button>" not in html
    assert "<option selected>ASSIGNED</option>" in html
    assert "<option>PARTIALLY USED</option>" in html
    assert 'name="quantity" type="number" min="1" max="10" required' in html
    assert (
        '<option value="869fc201-b09c-4dc4-9cea-63bb4c12b5a4">'
        "test-batch — Test Recipe · 35 / 50 not in containers</option>"
    ) in html
    assert "full-batch — Full Recipe" not in html
    assert 'data-existing-batch-ids="869fc201-b09c-4dc4-9cea-63bb4c12b5a4"' in html
    assert '<label class="check" data-mixed-batch-ack hidden>' in html
    assert 'name="acknowledge_mixed_batch" type="checkbox" disabled' in html
    assert 'name="cartridge_limit" type="number" min="1" step="1" required' in html
    assert 'src="/static/containers.js?v=2"' in html


def test_container_script_toggles_mixed_batch_acknowledgement_and_auto_submits_state():
    script = open("rendering_app/static/containers.js").read()

    assert "data-container-state-form" in script
    assert 'select[name="state"]' in script
    assert "stateSelect.dataset.currentState" in script
    assert "form.submit()" in script
    assert "data-container-assignment-form" in script
    assert "existingBatchIds.some" in script
    assert "batchId !== selectedBatchId" in script
    assert "acknowledgement.hidden = !requiresAcknowledgement" in script
    assert "acknowledgementCheckbox.disabled = !requiresAcknowledgement" in script


def test_inventory_form_uses_expanded_item_picker_for_lot_creation():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    items = [{
        "id": 7,
        "manufacturer": "Maker",
        "name": "Primer",
        "category": "PRIMER",
        "product_line": "Match",
        "characteristics": "Nickel cup",
        "caliber": None,
        "bullet_weight": None,
        "bullet_type": None,
        "primer_type": "Small pistol",
        "powder_type": None,
    }]

    with app.test_request_context("/inventory"):
        html = render_template(
            "inventory.html",
            items=items,
            lots=[],
            historical="false",
            active_item_ids={7},
        )

    assert 'data-has-active-lot="true"' in html
    assert '<option value="">Select type</option>' in html
    assert "Completed cartridge" not in html
    assert 'value="COMPLETED CARTRIDGE"' not in html
    assert 'id="inventory-item-type"' in html
    assert 'data-item-category="PRIMER" hidden' in html
    assert 'type="radio" name="item_id" value="7"' in html
    assert "Product line: Match" in html
    assert "Characteristics: Nickel cup" in html
    assert "Primer type: Small pistol" in html
    assert "Has active consumption lot" in html
    assert "Select an item type to show matching active items." in html
    assert 'name="replace_active"' in html
    assert 'src="/static/inventory.js?v=3"' in html


def test_recipe_component_form_derives_role_from_item():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    recipe = {
        "id": "9b10b7ad-a78a-4c67-99f4-3c1b74855f89",
        "title": "Exact recipe", "cartridge": ".357",
        "state": "UNDER DEVELOPMENT", "warnings": [], "components": [], "sources": [],
        "public": False,
        "aggregate_performance": {
            "batch_count": 0, "total_rounds_produced": 0,
            "average_velocity": None, "average_rating": None,
        },
    }

    items = [{
        "id": 7, "category": "PRIMER", "manufacturer": "Maker", "name": "Primer",
    }]

    with app.test_request_context("/recipes/1"):
        html = render_template("recipe_detail.html", recipe=recipe, items=items)

    assert "Alternative group" not in html
    assert 'name="role"' not in html
    assert "Item / role" in html
    assert "PRIMER — Maker Primer" in html
    assert "category determines its role" in html
    assert "Each component is exact and mandatory" in html
    assert '<details id="add-component">' in html
    assert '<details id="add-component" open>' not in html
    assert "data-missing-source-confirm" in html
    assert 'name="acknowledge_missing_source"' in html
    assert 'src="/static/source-risk.js?v=1"' in html

    with app.test_request_context("/recipes/1?component_form=open"):
        html = render_template(
            "recipe_detail.html", recipe=recipe, items=items, component_form_open=True
        )

    assert '<details id="add-component" open>' in html


def test_recipe_lifecycle_select_reflects_current_state():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    recipe = {
        "id": "9b10b7ad-a78a-4c67-99f4-3c1b74855f89",
        "title": "Lifecycle Recipe", "cartridge": ".357",
        "state": "UNDER TEST", "warnings": [], "components": [], "sources": [],
        "public": False,
        "aggregate_performance": {
            "batch_count": 0, "total_rounds_produced": 0,
            "average_velocity": None, "average_rating": None,
        },
    }

    with app.test_request_context("/recipes/1"):
        html = render_template("recipe_detail.html", recipe=recipe, items=[])

    assert "<option selected>UNDER TEST</option>" in html
    assert "<option selected>UNDER DEVELOPMENT</option>" not in html


def test_batch_lifecycle_select_includes_and_selects_under_production():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    batch = {
        "id": "869fc201-b09c-4dc4-9cea-63bb4c12b5a4",
        "slug": "test-batch",
        "state": "UNDER PRODUCTION",
        "iterations": 10,
        "recipe": {"title": "Test Recipe"},
        "reservations": [],
        "consumptions": [],
        "performance": None,
        "container_assigned_quantity": 0,
        "container_unassigned_quantity": 10,
        "containers": [],
    }

    with app.test_request_context(f"/batches/{batch['id']}"):
        html = render_template(
            "batch_detail.html", batch=batch, lots=[], containers=[]
        )

    assert 'data-batch-state-form' in html
    assert 'data-current-state="UNDER PRODUCTION"' in html
    assert 'action="/batches/869fc201-b09c-4dc4-9cea-63bb4c12b5a4/state"' in html
    assert ">Transition</button>" not in html
    assert "<option selected>UNDER PRODUCTION</option>" in html
    assert "<option>PRODUCED</option>" in html
    assert "<option>CANCELLED</option>" in html
    assert "<option>IN STORAGE</option>" not in html
    assert "<option>PARTIALLY IN STORAGE</option>" not in html
    assert "<option>PARTIALLY DEPLETED</option>" not in html
    assert "<option>DEPLETED</option>" not in html
    assert "<option>DECOMMISSIONED</option>" not in html
    assert "PARTIALLY USED" not in html
    assert "<option>USED</option>" not in html
    assert "<option selected>IN STORAGE</option>" not in html
    assert "0 / 10 cartridges assigned to containers" in html
    performance = html[html.index("<summary>Performance / quality</summary>"):]
    assert '<details class="panel"><summary>Performance / quality</summary>' in html
    assert f'action="/batches/{batch["id"]}/performance"' not in performance
    assert "can be entered after the batch transitions" in performance
    assert f"Batch ID: <code>{batch['id']}</code>" in html
    assert f'href="/qr/batch/{batch["id"]}"' in html
    assert 'src="/static/batch-detail.js?v=1"' in html

    batch["state"] = "PRODUCED"
    batch["container_assigned_quantity"] = 4
    batch["container_unassigned_quantity"] = 6
    batch["containers"] = [{
        "id": 7,
        "identifier": "CAN-1",
        "name": "Ammo Can 1",
        "state": "ASSIGNED",
        "quantity": 4,
        "cartridge_limit": 10,
    }]
    with app.test_request_context(f"/batches/{batch['id']}"):
        html = render_template(
            "batch_detail.html", batch=batch, lots=[], containers=[]
        )

    assert '<details class="panel" open><summary>Performance / quality</summary>' in html
    assert f'action="/batches/{batch["id"]}/performance"' in html
    assert "<option selected>PRODUCED</option>" in html
    assert "<option>DECOMMISSIONED</option>" in html
    assert "<option>CANCELLED</option>" not in html
    assert "<option>IN STORAGE</option>" not in html
    assert "4 / 10 cartridges assigned to containers; 6 not in containers." in html
    assert '<a href="/containers#container-7">CAN-1 — Ammo Can 1</a>' in html

    batch["state"] = "DEPLETED"
    batch["container_assigned_quantity"] = 0
    batch["container_unassigned_quantity"] = 0
    batch["container_depleted_quantity"] = 10
    batch["containers"] = []
    with app.test_request_context(f"/batches/{batch['id']}"):
        html = render_template(
            "batch_detail.html", batch=batch, lots=[], containers=[]
        )

    assert "<option selected>DEPLETED</option>" in html
    assert "<option>DECOMMISSIONED</option>" not in html


def test_batch_detail_script_auto_submits_lifecycle_changes():
    script = open("rendering_app/static/batch-detail.js").read()

    assert "data-batch-state-form" in script
    assert 'select[name="state"]' in script
    assert "stateSelect.dataset.currentState" in script
    assert "form.submit()" in script


def test_batches_table_rows_are_clickable():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    batch = {
        "id": "869fc201-b09c-4dc4-9cea-63bb4c12b5a4",
        "slug": "test-batch",
        "state": "UNDER PRODUCTION",
        "iterations": 10,
        "recipe": {
            "id": "9b10b7ad-a78a-4c67-99f4-3c1b74855f89",
            "title": "Test Recipe",
        },
        "created_at": "2026-06-18T00:00:00",
    }

    with app.test_request_context("/batches"):
        html = render_template("batches.html", batches=[batch])

    assert (
        f'class="clickable-row" data-href="/batches/{batch["id"]}" tabindex="0"'
        in html
    )
    assert f'href="/recipes/{batch["recipe"]["id"]}"' in html
    assert 'src="/static/clickable-rows.js?v=2"' in html


def test_clickable_row_script_suppresses_row_hover_on_links():
    script = open("rendering_app/static/clickable-rows.js").read()
    css = open("rendering_app/static/app.css").read()

    assert "link-hover" in script
    assert ".clickable-row.link-hover:hover td{background:transparent}" in css


def test_qr_page_has_back_link_and_embedded_png():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    entity_id = "869fc201-b09c-4dc4-9cea-63bb4c12b5a4"

    with app.test_request_context(f"/qr/batch/{entity_id}"):
        html = render_template(
            "qr.html",
            entity_type="batch",
            entity_id=entity_id,
            title="Batch QR label",
            back_url=f"/batches/{entity_id}",
        )

    assert f'href="/batches/{entity_id}"' in html
    assert f'src="/download/qr/batch/{entity_id}"' in html
    assert "← Back" in html


def test_llm_context_download_is_protected_text_file():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    client = app.test_client()

    unauthenticated = client.get("/download/help/llm-context")
    assert unauthenticated.status_code == 302
    assert "/login?next=/download/help/llm-context" in unauthenticated.location

    with client.session_transaction() as session:
        session["token"] = "test-token"
        session["user"] = {"email": "test@example.com"}

    response = client.get("/download/help/llm-context")

    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert "reload-ledger-llm-context.txt" in response.headers["Content-Disposition"]
    body = response.get_data(as_text=True)
    assert "Reload Ledger LLM Context" in body
    assert "Missing source material" in body
    assert "Batch identifiers are UUIDs" in body


def test_incomplete_component_submission_redirects_to_open_form(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})

    class Response:
        ok = True
        status_code = 201
        content = b'{"component": {}, "warnings": ["Powder component is missing."]}'

        @staticmethod
        def json():
            return {"component": {}, "warnings": ["Powder component is missing."]}

    monkeypatch.setattr("rendering_app.app.requests.request", lambda *args, **kwargs: Response())
    client = app.test_client()
    with client.session_transaction() as session:
        session["token"] = "test-token"

    response = client.post(
        "/recipes/recipe-id/components",
        data={"item_id": "7", "quantity": "1", "unit": "count"},
    )

    assert response.status_code == 302
    assert response.location.endswith(
        "/recipes/recipe-id?component_form=open#add-component"
    )


def test_complete_component_submission_redirects_to_collapsed_form(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})

    class Response:
        ok = True
        status_code = 201
        content = b'{"component": {}, "warnings": ["No source material is attached or referenced."]}'

        @staticmethod
        def json():
            return {
                "component": {},
                "warnings": ["No source material is attached or referenced."],
            }

    monkeypatch.setattr("rendering_app.app.requests.request", lambda *args, **kwargs: Response())
    client = app.test_client()
    with client.session_transaction() as session:
        session["token"] = "test-token"

    response = client.post(
        "/recipes/recipe-id/components",
        data={"item_id": "7", "quantity": "1", "unit": "count"},
    )

    assert response.status_code == 302
    assert response.location.endswith("/recipes/recipe-id#components")
    assert "component_form=open" not in response.location


def test_recipe_creation_form_is_prefilled_with_suggested_identity():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})

    with app.test_request_context("/recipes"):
        html = render_template(
            "recipes.html",
            recipes=[],
            suggested_identity={"title": "Craft Anvil"},
        )

    assert 'name="title" value="Craft Anvil"' in html
    assert "suggested_slug" not in html


def test_recipe_identifier_is_explicitly_labeled():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    recipe = {
        "id": "9b10b7ad-a78a-4c67-99f4-3c1b74855f89",
        "title": "Test Recipe", "cartridge": ".357",
        "state": "UNDER DEVELOPMENT", "warnings": [],
    }

    with app.test_request_context("/recipes"):
        html = render_template(
            "recipes.html",
            recipes=[recipe],
            suggested_identity={"title": "Craft Anvil"},
        )

    assert "Recipe ID:" in html
    assert "<code>9b10b7ad-a78a-4c67-99f4-3c1b74855f89</code>" in html


def test_batch_form_derives_required_quantities_from_recipe():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    recipe = {
        "id": "9b10b7ad-a78a-4c67-99f4-3c1b74855f89",
        "title": "Test Recipe",
        "state": "APPROVED",
        "sources": [],
        "components": [{
            "id": 11,
            "item_id": 7,
            "role": "POWDER",
            "quantity": 4.2,
            "unit": "grains",
            "item": {"manufacturer": "Maker", "name": "Powder"},
        }],
    }
    lots = [{
        "id": 19,
        "item_id": 7,
        "manufacturer_lot": "P-1",
        "available_quantity": 100,
        "normalized_unit": "grains",
    }]

    with app.test_request_context("/batches/new"):
        html = render_template("batch_new.html", recipes=[recipe], recipe=recipe, lots=lots)

    assert "Total required" not in html
    assert 'name="component_11_quantity"' not in html
    assert 'name="component_11_lot" required' in html
    assert 'data-component-quantity="4.2"' in html
    assert 'src="/static/batch.js?v=1"' in html
    assert "data-missing-source-confirm" in html
    assert 'name="acknowledge_missing_source"' in html
    assert 'src="/static/source-risk.js?v=1"' in html

    allocations = recipe_allocations(recipe, {
        "iterations": "25",
        "component_11_lot": "19",
        "component_11_quantity": "999",
    })
    assert allocations == [{"component_id": 11, "lot_id": "19", "quantity": "105.0"}]
