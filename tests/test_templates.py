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
