from flask import render_template

from rendering_app.app import create_app


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


def test_item_form_marks_category_specific_fields():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})

    with app.test_request_context("/items"):
        html = render_template("items.html", items=[])

    assert 'data-item-categories="BULLET"' in html
    assert 'data-item-categories="PRIMER"' in html
    assert 'data-item-categories="POWDER"' in html
    assert 'src="/static/items.js?v=2"' in html


def test_inventory_form_exposes_active_lot_state_to_confirmation_script():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    items = [{"id": 7, "manufacturer": "Maker", "name": "Primer", "category": "PRIMER"}]

    with app.test_request_context("/inventory"):
        html = render_template(
            "inventory.html",
            items=items,
            lots=[],
            historical="false",
            active_item_ids={7},
        )

    assert 'data-has-active-lot="true"' in html
    assert 'name="replace_active"' in html
    assert 'src="/static/inventory.js?v=1"' in html


def test_recipe_component_form_has_no_alternative_group():
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

    with app.test_request_context("/recipes/1"):
        html = render_template("recipe_detail.html", recipe=recipe, items=[])

    assert "Alternative group" not in html
    assert "Each component is exact and mandatory" in html


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
