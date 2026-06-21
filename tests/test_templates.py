from flask import render_template, session

from rendering_app.app import (
    active_batch_lots,
    create_app,
    inventory_lot_groups,
    recipe_allocations,
    recipe_component_item_options,
    replacement_batch_lots,
    recipe_garmin_performance_series,
)


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
    assert 'href="/static/app.css?v=15"' in html


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
    assert "<summary>Advanced item attributes</summary>" in html
    assert html.index("<summary>Advanced item attributes</summary>") < html.index('name="attributes"')
    assert 'src="/static/items.js?v=3"' in html


def test_item_form_script_uses_category_specific_placeholders():
    script = open("rendering_app/static/items.js").read()

    assert "const placeholders" in script
    for expected in [
        'BULLET: {',
        'POWDER: {',
        'PRIMER: {',
        'CASE: {',
        'OTHER: {',
        'name: "H110"',
        'primer_type: "Small pistol magnum"',
        'name: ".357 Magnum Nickel Brass"',
    ]:
        assert expected in script


def test_recipe_detail_script_toggles_source_fields():
    script = open("rendering_app/static/recipe-detail.js").read()

    for expected in [
        "[data-source-form]",
        "[data-source-kind]",
        "source-label",
        "image/*",
        "uploaded document",
        'input[type="file"]',
    ]:
        assert expected in script
    assert "file reference" not in script


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
    table_body = html[html.index("<tbody>"):html.index("</tbody>")]
    assert ".357" not in table_body
    assert "JHP" not in table_body


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
            inventory_groups=inventory_lot_groups([lot]),
            historical="false", active_item_ids={7},
        )
    with app.test_request_context("/recipes"):
        recipe_html = render_template(
            "recipes.html", recipes=[recipe],
            suggested_identity={"title": "Craft Anvil"}, retired="false",
        )

    assert item_html.index("Maker Primer") < item_html.index("<summary>Add item</summary>")
    assert inventory_html.index("LOT-9") < inventory_html.index("<summary>Add lot</summary>")
    assert recipe_html.index("Existing Recipe") < recipe_html.index("<summary>Create recipe</summary>")


def test_inventory_lots_are_grouped_by_item():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    item = {
        "id": 7, "category": "PRIMER", "manufacturer": "Maker", "name": "Primer",
        "product_line": "Match", "caliber": None, "characteristics": None,
        "bullet_type": None, "primer_type": "Small pistol", "powder_type": None,
    }
    lots = [
        {
            "id": 9, "item_id": 7, "item": item, "manufacturer_lot": "LOT-A",
            "original_quantity": 100, "original_unit": "count", "adjustment_quantity": 0,
            "normalized_unit": "count", "opened_on": None, "available_quantity": 80,
            "reserved_quantity": 10, "consumed_quantity": 10, "depleted": False, "active": True,
        },
        {
            "id": 10, "item_id": 7, "item": item, "manufacturer_lot": "LOT-B",
            "original_quantity": 50, "original_unit": "count", "adjustment_quantity": 0,
            "normalized_unit": "count", "opened_on": None, "available_quantity": 50,
            "reserved_quantity": 0, "consumed_quantity": 0, "depleted": False, "active": False,
        },
    ]

    with app.test_request_context("/inventory"):
        html = render_template(
            "inventory.html", items=[item], lots=lots,
            inventory_groups=inventory_lot_groups(lots),
            historical="false", active_item_ids={7},
        )

    assert html.count("Maker Primer") == 2
    assert 'class="inventory-item-group"' in html
    assert 'class="inventory-lot-row"' in html
    group_row = html[html.index('class="inventory-item-group"'):html.index('class="inventory-lot-row"')]
    assert "2 lots" in group_row
    assert "130 count available" in group_row
    assert "10 reserved" in group_row
    assert "10 consumed" in group_row
    assert "LOT-A" in html
    assert "LOT-B" in html


def test_containers_render_before_creation_form_with_batch_quantities():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    batch = {
        "id": "869fc201-b09c-4dc4-9cea-63bb4c12b5a4",
        "slug": "test-batch",
        "iterations": 50,
        "state": "PRODUCED",
        "container_unassigned_quantity": 35,
        "recipe": {
            "title": "Test Recipe",
            "components": [
                {
                    "role": "BULLET",
                    "quantity": 1,
                    "unit": "count",
                    "item": {"manufacturer": "Hornady", "name": "158 gr JHP"},
                },
                {
                    "role": "POWDER",
                    "quantity": 15,
                    "unit": "grains",
                    "item": {"manufacturer": "Hodgdon", "name": "H110"},
                },
            ],
        },
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
            inventory_groups=[],
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
    assert 'data-active-replacement-warning hidden' in html
    assert "Creating this lot as active will deactivate the current active lot." in html
    assert 'src="/static/inventory.js?v=6"' in html


def test_inventory_script_uses_item_type_specific_placeholders():
    script = open("rendering_app/static/inventory.js").read()

    assert "const placeholders" in script
    for expected in [
        'BULLET: {',
        'POWDER: {',
        'PRIMER: {',
        'CASE: {',
        'OTHER: {',
        'manufacturer_lot: "H110-ACT"',
        'manufacturer_lot: "CCI550-ACT"',
        'manufacturer_lot: "STAR-NI-ACT"',
    ]:
        assert expected in script


def test_inventory_script_uses_yes_no_dialog_for_missing_active_lot_prompt():
    script = open("rendering_app/static/inventory.js").read()

    assert "askYesNo" in script
    assert "data-choice-yes>Yes</button>" in script
    assert "data-choice-no>No</button>" in script
    assert "This item does not have an active consumption lot. Make this new lot active?" in script
    assert "form.requestSubmit()" in script
    assert "window.confirm(\n        \"This item does not have an active consumption lot" not in script


def test_inventory_script_warns_before_replacing_active_lot():
    script = open("rendering_app/static/inventory.js").read()

    assert "activeReplacementWarning.hidden" in script
    assert "selectedItemHasActiveLot" in script
    assert "This item already has an active consumption lot. Continue and replace the existing active lot?" in script
    assert 'replaceActive.value = "true"' in script
    assert "window.confirm" not in script


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


def test_recipe_component_options_hide_used_core_roles_but_keep_other():
    recipe = {
        "components": [
            {"role": "BULLET", "item": {"manufacturer": "Maker", "name": "Existing Bullet"}},
            {"role": "OTHER", "item": {"manufacturer": "Tool", "name": "Existing Other"}},
        ],
    }
    items = [
        {"id": 1, "category": "BULLET", "manufacturer": "Maker", "name": "New Bullet"},
        {"id": 2, "category": "POWDER", "manufacturer": "Maker", "name": "Powder"},
        {"id": 3, "category": "OTHER", "manufacturer": "Tool", "name": "Label"},
    ]

    options = recipe_component_item_options(recipe, items)

    assert [item["id"] for item in options] == [2, 3]


def test_recipe_component_form_excludes_used_core_role_items():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    recipe = {
        "id": "9b10b7ad-a78a-4c67-99f4-3c1b74855f89",
        "title": "Exact recipe", "cartridge": ".357",
        "state": "UNDER DEVELOPMENT", "warnings": [],
        "components": [{
            "id": 11,
            "role": "BULLET",
            "quantity": 1,
            "unit": "count",
            "item": {"manufacturer": "Maker", "name": "Existing Bullet"},
        }],
        "sources": [],
        "public": False,
        "aggregate_performance": {
            "batch_count": 0, "total_rounds_produced": 0,
            "average_velocity": None, "average_rating": None,
        },
    }
    items = [
        {"id": 1, "category": "BULLET", "manufacturer": "Maker", "name": "New Bullet"},
        {"id": 2, "category": "POWDER", "manufacturer": "Maker", "name": "Powder"},
        {"id": 3, "category": "OTHER", "manufacturer": "Tool", "name": "Label"},
    ]

    with app.test_request_context("/recipes/1"):
        html = render_template(
            "recipe_detail.html",
            recipe=recipe,
            items=items,
            component_items=recipe_component_item_options(recipe, items),
        )

    assert "BULLET — Maker New Bullet" not in html
    assert "POWDER — Maker Powder" in html
    assert "OTHER — Tool Label" in html


def test_recipe_detail_shows_aggregate_deviation_and_moa_with_na_fallback():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    recipe = {
        "id": "9b10b7ad-a78a-4c67-99f4-3c1b74855f89",
        "title": "Aggregate Recipe", "cartridge": ".357",
        "state": "UNDER TEST", "warnings": [], "components": [], "sources": [{"kind": "MANUAL"}],
        "public": False,
        "aggregate_performance": {
            "batch_count": 1, "total_rounds_produced": 10,
            "average_velocity": 1210, "average_standard_deviation": 8.4,
            "average_moa": None, "average_rating": None,
        },
    }

    with app.test_request_context("/recipes/1"):
        html = render_template("recipe_detail.html", recipe=recipe, items=[])

    assert "<span>Deviation</span>" in html
    assert "<strong>8.4</strong><span>Deviation</span>" in html
    assert "<span>MOA</span>" in html
    assert "<strong>N/A</strong><span>MOA</span>" in html


def test_recipe_source_form_supports_uploaded_images_and_documents():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    recipe = {
        "id": "9b10b7ad-a78a-4c67-99f4-3c1b74855f89",
        "title": "Source Recipe", "cartridge": ".357",
        "state": "UNDER DEVELOPMENT", "warnings": [], "components": [], "sources": [
            {
                "kind": "UPLOADED DOCUMENT",
                "citation": "Manual scan",
                "page": "42",
                "file_name": "manual.pdf",
                "stored_file": {"id": 12, "original_filename": "manual.pdf"},
            }
        ],
        "public": False,
        "aggregate_performance": {
            "batch_count": 0, "total_rounds_produced": 0,
            "average_velocity": None, "average_rating": None,
        },
    }

    with app.test_request_context("/recipes/1"):
        html = render_template("recipe_detail.html", recipe=recipe, items=[])

    assert '<a href="/download/files/12">Manual scan</a>' in html
    assert 'enctype="multipart/form-data"' in html
    assert 'data-source-form' in html
    assert '<option>Image</option>' in html
    assert '<option>Uploaded document</option>' in html
    assert '<option>Citation</option>' not in html
    assert '<option>File reference</option>' not in html
    assert "File name" not in html
    assert 'name="source_file" type="file"' in html
    assert 'src="/static/recipe-detail.js?v=1"' in html


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
    assert "<option>NOT APPROVED</option>" in html
    assert "<option selected>UNDER DEVELOPMENT</option>" not in html


def test_recipe_garmin_series_filters_and_formats_shot_data():
    recipe = {
        "aggregate_performance": {
            "records": [
                {
                    "batch_id": "batch-a",
                    "recorded_on": "2024-07-27",
                    "processed_data": {
                        "chronograph": "Garmin Xero C1 Pro",
                        "shots": [
                            {"sequence": 1, "velocity_fps": 1650.1},
                            {"sequence": 2, "velocity_fps": 1660.2},
                        ],
                    },
                },
                {
                    "batch_id": "batch-b",
                    "recorded_on": "2024-07-28",
                    "processed_data": {"chronograph": "Other", "shots": [{"sequence": 1, "velocity_fps": 1000}]},
                },
            ]
        }
    }

    series = recipe_garmin_performance_series(recipe)

    assert series == [{
        "id": "batch-a-0",
        "batch_id": "batch-a",
        "date": "2024-07-27",
        "label": "2024-07-27 · batch-a",
        "shots": [{"shot": 1, "speed": 1650.1}, {"shot": 2, "speed": 1660.2}],
    }]


def test_recipe_detail_renders_garmin_velocity_chart():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    recipe = {
        "id": "9b10b7ad-a78a-4c67-99f4-3c1b74855f89",
        "title": "Chart Recipe", "cartridge": ".357",
        "state": "UNDER TEST", "warnings": [], "components": [], "sources": [{"kind": "MANUAL"}],
        "public": False,
        "aggregate_performance": {
            "batch_count": 1, "total_rounds_produced": 10,
            "average_velocity": 1655.15, "average_rating": None,
            "records": [{
                "batch_id": "batch-a",
                "recorded_on": "2024-07-27",
                "processed_data": {
                    "chronograph": "Garmin Xero C1 Pro",
                    "shots": [
                        {"sequence": 1, "velocity_fps": 1650.1},
                        {"sequence": 2, "velocity_fps": 1660.2},
                    ],
                },
            }],
        },
    }
    series = recipe_garmin_performance_series(recipe)

    with app.test_request_context("/recipes/1"):
        html = render_template(
            "recipe_detail.html", recipe=recipe, items=[],
            garmin_performance_series=series,
        )

    assert "Garmin velocity graph" in html
    assert '<option value="all">Show All</option>' in html
    assert '<option value="batch-a-0">2024-07-27 · batch-a</option>' in html
    assert 'id="recipe-performance-data"' in html
    assert '"speed": 1650.1' in html
    assert 'src="/static/recipe-performance.js?v=1"' in html


def test_batch_lifecycle_select_includes_and_selects_under_production():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    batch = {
        "id": "869fc201-b09c-4dc4-9cea-63bb4c12b5a4",
        "slug": "test-batch",
        "state": "UNDER PRODUCTION",
        "iterations": 10,
        "characteristics": "Ladder test",
        "recipe": {
            "title": "Test Recipe",
            "components": [
                {
                    "role": "BULLET",
                    "quantity": 1,
                    "unit": "count",
                    "item": {"manufacturer": "Hornady", "name": "158 gr JHP"},
                },
                {
                    "role": "POWDER",
                    "quantity": 15,
                    "unit": "grains",
                    "item": {"manufacturer": "Hodgdon", "name": "H110"},
                },
            ],
        },
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
    assert "Ladder test" in html
    assert "<h2>Recipe materials</h2>" in html
    assert "BULLET" in html
    assert "Hornady 158 gr JHP" in html
    assert "1 count each" in html
    assert "Hodgdon H110" in html
    assert "15 grains each" in html
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
    assert '<details class="panel" id="performance"><summary>Performance / quality</summary>' in html
    assert f'action="/batches/{batch["id"]}/performance"' not in performance
    assert "can be entered after the batch transitions" in performance
    assert f"Batch ID: <code>{batch['id']}</code>" in html
    assert f'href="/qr/batch/{batch["id"]}"' in html
    assert f'action="/batches/{batch["id"]}/garmin-import"' in html
    assert "Import Garmin Data" in html
    assert 'data-garmin-import-form' in html
    assert 'src="/static/batch-detail.js?v=2"' in html

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

    assert '<details class="panel" id="performance"><summary>Performance / quality</summary>' in html
    assert '<details class="panel" open><summary>Performance / quality</summary>' not in html
    assert f'action="/batches/{batch["id"]}/performance"' in html
    assert "<option selected>PRODUCED</option>" in html
    assert "<option>DECOMMISSIONED</option>" in html
    assert "<option>CANCELLED</option>" not in html
    assert "<option>IN STORAGE</option>" not in html
    assert "4 / 10 cartridges assigned to containers; 6 not in containers." in html
    assert '<a href="/containers#container-7">CAN-1 — Ammo Can 1</a>' in html
    assert "<summary>Advanced performance data</summary>" in html
    assert html.index("<summary>Advanced performance data</summary>") < html.index('name="processed_data"')
    assert 'name="reliability_notes"' not in html
    assert 'name="pressure_sign_notes"' not in html
    assert 'name="weather_notes"' not in html

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


def test_garmin_imported_performance_fields_are_ordered_and_locked():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    batch = {
        "id": "869fc201-b09c-4dc4-9cea-63bb4c12b5a4",
        "slug": "test-batch",
        "state": "PRODUCED",
        "iterations": 10,
        "recipe": {"title": "Test Recipe"},
        "reservations": [],
        "consumptions": [],
        "performance": {
            "recorded_on": "2024-07-27",
            "firearm": "Ruger GP100",
            "barrel_length": 4.2,
            "distance": 25,
            "group_size": 2.1,
            "shot_count": 15,
            "velocity_average": 1654.195,
            "velocity_minimum": 1584.826,
            "velocity_maximum": 1685.761,
            "standard_deviation": 26.279,
            "extreme_spread": 100.935,
            "temperature": 62,
            "recoil_perception": 3,
            "accuracy_perception": 4,
            "cleanliness_perception": 4,
            "subjective_rating": 4,
            "reliability_notes": "No failures.",
            "pressure_sign_notes": "No abnormal pressure signs.",
            "weather_notes": "Indoor range.",
            "notes": "Manual notes.",
            "raw_data": "Garmin Xero C1 Pro import\n\nShot list\n1. 1660.600 fps",
            "processed_data": {"chronograph": "Garmin Xero C1 Pro", "shots": []},
            "edited": False,
        },
        "container_assigned_quantity": 0,
        "container_unassigned_quantity": 10,
        "containers": [],
    }

    with app.test_request_context(f"/batches/{batch['id']}"):
        html = render_template("batch_detail.html", batch=batch, lots=[], containers=[])

    assert html.index('name="firearm"') < html.index('name="recorded_on"')
    assert html.index('name="shot_count"') < html.index('name="raw_data"')
    assert html.index('name="extreme_spread"') < html.index('name="raw_data"')
    assert html.index('name="raw_data"') < html.index('name="notes"')
    assert html.index('name="processed_data"') < html.index('name="notes"')
    assert 'name="reliability_notes"' not in html
    assert 'name="pressure_sign_notes"' not in html
    assert 'name="weather_notes"' not in html
    assert 'name="velocity_average" type="number" step=".001" value="1654.195" placeholder="1210" readonly' in html
    assert 'name="raw_data" placeholder="1210,1198,1224,1208" readonly' in html
    firearm_field = html[html.index('name="firearm"'):html.index('name="barrel_length"')]
    assert "readonly" not in firearm_field


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
        "characteristics": "Test batch",
        "recipe": {
            "id": "9b10b7ad-a78a-4c67-99f4-3c1b74855f89",
            "title": "Test Recipe",
        },
        "created_at": "2026-06-18T00:00:00",
    }

    with app.test_request_context("/batches"):
        html = render_template("batches.html", batches=[batch], depleted="false")

    assert (
        f'class="clickable-row" data-href="/batches/{batch["id"]}" tabindex="0"'
        in html
    )
    assert f'href="/recipes/{batch["recipe"]["id"]}"' in html
    assert "<th>Characteristics</th>" in html
    assert "Test batch" in html
    assert 'href="?depleted=true">Show depleted</a>' in html
    assert 'src="/static/clickable-rows.js?v=2"' in html


def test_batches_template_toggle_hides_depleted_batches_by_default():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})

    with app.test_request_context("/batches?depleted=true"):
        html = render_template("batches.html", batches=[], depleted="true")

    assert 'href="?depleted=false">Hide depleted</a>' in html


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


def test_settings_page_shows_current_session_api_token(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    client = app.test_client()

    class Response:
        ok = True
        status_code = 200
        content = b"{}"

        def json(self):
            return {"files": []}

    monkeypatch.setattr("rendering_app.app.requests.request", lambda *_args, **_kwargs: Response())

    unauthenticated = client.get("/settings")
    assert unauthenticated.status_code == 302
    assert "/login?next=/settings" in unauthenticated.location

    with client.session_transaction() as flask_session:
        flask_session["token"] = "session-token-for-mcp"
        flask_session["token_expires_at"] = "2026-06-19T20:00:00+00:00"
        flask_session["user"] = {"email": "test@example.com"}

    response = client.get("/settings")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "API token" in html
    assert "session-token-for-mcp" in html
    assert "RELOADING_API_TOKEN=session-token-for-mcp" in html
    assert "2026-06-19T20:00:00+00:00" in html
    assert "Stored files" in html


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


def test_recipe_creation_form_uses_examples_without_submitted_default_title():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})

    with app.test_request_context("/recipes"):
        html = render_template(
            "recipes.html",
            recipes=[],
            suggested_identity={"title": "Craft Anvil"},
            retired="false",
        )

    assert 'name="title" placeholder="357 Magnum 158 XTP H110" required' in html
    assert 'name="title" value=' not in html
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
            retired="false",
        )

    assert "Recipe ID:" in html
    assert "<code>9b10b7ad-a78a-4c67-99f4-3c1b74855f89</code>" in html
    assert 'href="?retired=true">Show retired</a>' in html


def test_recipes_template_toggle_hides_retired_recipes_by_default():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})

    with app.test_request_context("/recipes?retired=true"):
        html = render_template(
            "recipes.html",
            recipes=[],
            suggested_identity={"title": "Craft Anvil"},
            retired="true",
        )

    assert 'href="?retired=false">Hide retired</a>' in html


def test_recipes_route_hides_retired_records_until_toggled(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    recipes = [
        {
            "id": "active-recipe",
            "title": "Active Recipe",
            "cartridge": ".357",
            "state": "APPROVED",
            "warnings": [],
        },
        {
            "id": "retired-recipe",
            "title": "Retired Recipe",
            "cartridge": ".357",
            "state": "RETIRED",
            "warnings": [],
        },
    ]

    class Response:
        ok = True
        status_code = 200
        content = b"{}"

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    def fake_request(_method, url, **_kwargs):
        if url.endswith("/api/recipes/suggested-identity"):
            return Response({"identity": {"title": "Craft Anvil"}})
        if url.endswith("/api/recipes"):
            return Response({"recipes": recipes})
        raise AssertionError(url)

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["token"] = "test-token"
        flask_session["user"] = {"email": "test@example.com"}

    default = client.get("/recipes").get_data(as_text=True)
    assert "Active Recipe" in default
    assert "Retired Recipe" not in default
    assert 'href="?retired=true">Show retired</a>' in default

    toggled = client.get("/recipes?retired=true").get_data(as_text=True)
    assert "Active Recipe" in toggled
    assert "Retired Recipe" in toggled
    assert 'href="?retired=false">Hide retired</a>' in toggled


def test_batches_route_hides_depleted_records_until_toggled(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    batches = [
        {
            "id": "active-batch",
            "slug": "active-batch",
            "state": "PRODUCED",
            "iterations": 8,
            "recipe": {"id": "active-recipe", "title": "Active Recipe"},
            "created_at": "2026-06-18T00:00:00",
        },
        {
            "id": "depleted-batch",
            "slug": "depleted-batch",
            "state": "DEPLETED",
            "iterations": 8,
            "recipe": {"id": "active-recipe", "title": "Active Recipe"},
            "created_at": "2026-06-18T00:00:00",
        },
    ]

    class Response:
        ok = True
        status_code = 200
        content = b"{}"

        def json(self):
            return {"batches": batches}

    monkeypatch.setattr("rendering_app.app.requests.request", lambda *_args, **_kwargs: Response())
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["token"] = "test-token"
        flask_session["user"] = {"email": "test@example.com"}

    default = client.get("/batches").get_data(as_text=True)
    assert "active-batch" in default
    assert "depleted-batch" not in default
    assert 'href="?depleted=true">Show depleted</a>' in default

    toggled = client.get("/batches?depleted=true").get_data(as_text=True)
    assert "active-batch" in toggled
    assert "depleted-batch" in toggled
    assert 'href="?depleted=false">Hide depleted</a>' in toggled


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
        "active": True,
        "depleted": False,
    }]

    with app.test_request_context("/batches/new"):
        html = render_template("batch_new.html", recipes=[recipe], recipe=recipe, lots=lots)

    assert "Total required" not in html
    assert 'name="component_11_quantity"' not in html
    assert 'name="component_11_lot" required' in html
    assert 'data-available="100"' in html
    assert 'data-replacement-row hidden' in html
    assert "The selected active lot will be depleted by this batch" in html
    assert 'data-component-quantity="4.2"' in html
    assert 'src="/static/batch.js?v=2"' in html
    assert 'name="characteristics"' in html
    assert "Test batch, ladder step, function check" in html
    assert "data-missing-source-confirm" in html
    assert 'name="acknowledge_missing_source"' in html
    assert 'src="/static/source-risk.js?v=1"' in html

    allocations = recipe_allocations(recipe, {
        "iterations": "25",
        "component_11_lot": "19",
        "component_11_quantity": "999",
    })
    assert allocations == [{"component_id": 11, "lot_id": "19", "quantity": "105.0"}]

    split_allocations = recipe_allocations(recipe, {
        "iterations": "25",
        "component_11_lot": "19",
        "component_11_replacement_lot": "20",
    }, lots + [{
        "id": 20,
        "item_id": 7,
        "manufacturer_lot": "P-2",
        "available_quantity": 50,
        "normalized_unit": "grains",
        "active": False,
        "depleted": False,
    }])
    assert split_allocations == [
        {"component_id": 11, "lot_id": "19", "quantity": "100"},
        {"component_id": 11, "lot_id": "20", "quantity": "5.0"},
    ]


def test_batch_creation_only_lists_active_lots():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    recipe = {
        "id": "recipe-1",
        "title": "Batch Recipe",
        "state": "APPROVED",
        "sources": [{"kind": "MANUAL"}],
        "components": [{
            "id": 11,
            "item_id": 7,
            "role": "POWDER",
            "quantity": 4.2,
            "unit": "grains",
            "item": {"manufacturer": "Maker", "name": "Powder"},
        }],
    }
    lots = [
        {
            "id": 19,
            "item_id": 7,
            "manufacturer_lot": "ACTIVE-LOT",
            "available_quantity": 100,
            "normalized_unit": "grains",
            "active": True,
            "depleted": False,
        },
        {
            "id": 20,
            "item_id": 7,
            "manufacturer_lot": "INACTIVE-LOT",
            "available_quantity": 100,
            "normalized_unit": "grains",
            "active": False,
            "depleted": False,
        },
        {
            "id": 21,
            "item_id": 7,
            "manufacturer_lot": "DEPLETED-LOT",
            "available_quantity": 0,
            "normalized_unit": "grains",
            "active": True,
            "depleted": True,
        },
    ]

    filtered_lots = active_batch_lots(lots)
    replacement_lots = replacement_batch_lots(lots)
    with app.test_request_context("/batches/new"):
        html = render_template(
            "batch_new.html",
            recipes=[recipe],
            recipe=recipe,
            lots=filtered_lots,
            replacement_lots=replacement_lots,
        )

    assert [lot["manufacturer_lot"] for lot in filtered_lots] == ["ACTIVE-LOT"]
    assert [lot["manufacturer_lot"] for lot in replacement_lots] == ["INACTIVE-LOT"]
    primary_select = html[html.index('name="component_11_lot"'):html.index('name="component_11_replacement_lot"')]
    replacement_select = html[html.index('name="component_11_replacement_lot"'):]
    assert "ACTIVE-LOT" in primary_select
    assert "INACTIVE-LOT" not in primary_select
    assert "INACTIVE-LOT" in replacement_select
    assert "DEPLETED-LOT" not in html
