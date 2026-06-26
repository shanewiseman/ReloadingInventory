from io import BytesIO
from urllib.parse import urlparse

import requests
from werkzeug.datastructures import MultiDict

from rendering_app.app import create_app


class FakeResponse:
    def __init__(self, payload=None, status_code=200, content=None, headers=None):
        self.payload = payload or {}
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.content = content if content is not None else b"{}"
        self.headers = headers or {}

    def json(self):
        return self.payload


class NonJsonResponse(FakeResponse):
    def __init__(self, status_code=500):
        super().__init__(status_code=status_code, content=b"<html>server error</html>")

    def json(self):
        raise ValueError("response is not json")


def authenticated_client(app):
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["token"] = "test-token"
        flask_session["user"] = {"email": "test@example.com"}
    return client


def request_path(url):
    return urlparse(url).path


def minimal_recipe(recipe_id="recipe-1"):
    return {
        "id": recipe_id,
        "title": "Route Test Recipe",
        "cartridge": ".357 Magnum",
        "state": "UNDER DEVELOPMENT",
        "warnings": [],
        "public": False,
        "sources": [],
        "components": [],
        "aggregate_performance": {
            "batch_count": 0,
            "total_rounds_produced": 0,
            "average_velocity": None,
            "average_standard_deviation": None,
            "average_moa": None,
            "average_rating": None,
            "records": [],
        },
    }


def minimal_batch(batch_id="batch-1"):
    return {
        "id": batch_id,
        "slug": "route-test-batch",
        "state": "PRODUCED",
        "iterations": 10,
        "characteristics": "function check",
        "recipe": {
            "title": "Route Test Recipe",
            "components": [],
        },
        "reservations": [],
        "consumptions": [],
        "performance": None,
        "container_assigned_quantity": 0,
        "container_unassigned_quantity": 10,
        "containers": [],
    }


def test_inventory_creation_posts_active_replace_flag(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "path": request_path(url), **kwargs})
        return FakeResponse({"lot": {"id": 1}}, status_code=201)

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    response = client.post("/inventory", data={
        "item_id": "7",
        "manufacturer_lot": "LOT-1",
        "acquired_on": "2026-06-20",
        "quantity": "500",
        "unit": "count",
        "cost": "54.99",
        "weight_grains": "3.5",
        "notes": "new sleeve",
        "active": "on",
        "replace_active": "true",
    })

    assert response.status_code == 302
    assert response.location.endswith("/inventory")
    assert calls == [{
        "method": "POST",
        "path": "/api/inventory-lots",
        "headers": {"Authorization": "Bearer test-token"},
        "timeout": 15,
        "json": {
            "item_id": "7",
            "manufacturer_lot": "LOT-1",
            "acquired_on": "2026-06-20",
            "quantity": "500",
            "unit": "count",
            "cost": "54.99",
            "weight_grains": "3.5",
            "notes": "new sleeve",
            "active": True,
            "replace_active": True,
        },
    }]


def test_recipe_source_upload_posts_multipart_file(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "path": request_path(url), **kwargs})
        return FakeResponse({"source": {"id": 1}}, status_code=201)

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    response = client.post("/recipes/recipe-1/sources", data={
        "kind": "UPLOADED DOCUMENT",
        "notes": "manual page",
        "source_file": (BytesIO(b"source bytes"), "manual.pdf"),
    })

    assert response.status_code == 302
    assert response.location.endswith("/recipes/recipe-1")
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/api/recipes/recipe-1/sources"
    assert calls[0]["data"]["kind"] == "UPLOADED DOCUMENT"
    assert calls[0]["data"]["notes"] == "manual page"
    assert calls[0]["files"]["source_file"][0] == "manual.pdf"
    assert "json" not in calls[0]


def test_new_batch_posts_split_allocations_and_characteristics(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    recipe = {
        "id": "recipe-1",
        "title": "Batch Recipe",
        "state": "APPROVED",
        "components": [{
            "id": 11,
            "item_id": 7,
            "role": "POWDER",
            "quantity": 4.2,
            "unit": "grains",
        }],
    }
    lots = [
        {
            "id": 19,
            "item_id": 7,
            "manufacturer_lot": "ACTIVE-LOT",
            "available_quantity": 100,
            "active": True,
            "depleted": False,
        },
        {
            "id": 20,
            "item_id": 7,
            "manufacturer_lot": "REPLACEMENT-LOT",
            "available_quantity": 50,
            "active": False,
            "depleted": False,
        },
    ]
    batch_posts = []

    def fake_request(method, url, **kwargs):
        path = request_path(url)
        if method == "GET" and path == "/api/recipes":
            return FakeResponse({"recipes": [recipe]})
        if method == "GET" and path == "/api/inventory-lots":
            return FakeResponse({"lots": lots})
        if method == "POST" and path == "/api/batches":
            batch_posts.append(kwargs["json"])
            return FakeResponse({"batch": {"id": "batch-1"}}, status_code=201)
        raise AssertionError(f"Unexpected API call: {method} {path}")

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    response = client.post("/batches/new", data={
        "recipe_id": "recipe-1",
        "iterations": "25",
        "component_11_lot": "19",
        "component_11_replacement_lot": "20",
        "characteristics": "ladder step",
        "notes": "range test",
    })

    assert response.status_code == 302
    assert response.location.endswith("/batches/batch-1")
    assert batch_posts == [{
        "recipe_id": "recipe-1",
        "iterations": "25",
        "allocations": [
            {"component_id": 11, "lot_id": "19", "quantity": "100"},
            {"component_id": 11, "lot_id": "20", "quantity": "5.0"},
        ],
        "characteristics": "ladder step",
        "notes": "range test",
        "acknowledge_non_approved": False,
        "acknowledge_missing_source": False,
    }]


def test_new_batch_rejects_invalid_advanced_allocations(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    batch_posts = []

    def fake_request(method, url, **kwargs):
        path = request_path(url)
        if method == "GET" and path == "/api/recipes":
            return FakeResponse({"recipes": [{"id": "recipe-1", "components": []}]})
        if method == "GET" and path == "/api/inventory-lots":
            return FakeResponse({"lots": []})
        if method == "POST" and path == "/api/batches":
            batch_posts.append(kwargs["json"])
            return FakeResponse({"batch": {"id": "batch-1"}}, status_code=201)
        raise AssertionError(f"Unexpected API call: {method} {path}")

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    response = client.post("/batches/new", data={
        "recipe_id": "recipe-1",
        "iterations": "10",
        "advanced_allocations": "{not-json",
    })

    assert response.status_code == 302
    assert response.location.endswith("/batches/new?recipe_id=recipe-1")
    assert batch_posts == []


def test_garmin_import_uploads_all_files_to_storage_api(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "path": request_path(url), **kwargs})
        return FakeResponse({
            "performance": {"shot_count": 6},
            "files": [{"id": 1}, {"id": 2}],
        }, status_code=201)

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    response = client.post(
        "/batches/batch-1/garmin-import",
        data=MultiDict([
            ("files", (BytesIO(b"fit-one"), "session_1.fit")),
            ("files", (BytesIO(b"fit-two"), "session_2.fit")),
        ]),
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert response.location.endswith("/batches/batch-1#performance")
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/api/batches/batch-1/performance/garmin-import"
    assert [upload[1][0] for upload in calls[0]["files"]] == ["session_1.fit", "session_2.fit"]
    assert "json" not in calls[0]


def test_garmin_import_requires_at_least_one_file(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})

    def fake_request(method, url, **_kwargs):
        raise AssertionError(f"Unexpected API call: {method} {url}")

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    response = client.post("/batches/batch-1/garmin-import", data={})

    assert response.status_code == 302
    assert response.location.endswith("/batches/batch-1")


def test_settings_file_delete_and_backup_routes_call_storage(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "path": request_path(url), **kwargs})
        if method == "POST" and request_path(url) == "/api/admin/backup":
            return FakeResponse({"backup": {"filename": "backup.json"}})
        return FakeResponse({})

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    delete_response = client.post("/settings/files/7/delete")
    backup_response = client.post("/settings/backup")

    assert delete_response.status_code == 302
    assert delete_response.location.endswith("/settings#stored-files")
    assert backup_response.status_code == 302
    assert backup_response.location.endswith("/settings")
    assert [(call["method"], call["path"]) for call in calls] == [
        ("DELETE", "/api/files/7"),
        ("POST", "/api/admin/backup"),
    ]


def test_settings_theme_route_updates_session_without_storage_call(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []

    monkeypatch.setattr("rendering_app.app.requests.request", lambda *args, **kwargs: calls.append(args) or FakeResponse({}))
    client = authenticated_client(app)

    response = client.post("/settings/theme", data={"theme_mode": "dark"})
    assert response.status_code == 302
    assert response.location.endswith("/settings")
    with client.session_transaction() as flask_session:
        assert flask_session["theme_mode"] == "dark"
    assert calls == []

    client.post("/settings/theme", data={"theme_mode": "unexpected"})
    with client.session_transaction() as flask_session:
        assert flask_session["theme_mode"] == "system"


def test_download_routes_proxy_binary_responses(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})

    def fake_request(method, url, **kwargs):
        path = request_path(url)
        if path == "/api/qr/batch/batch-1":
            return FakeResponse(
                content=b"png-bytes",
                headers={"Content-Disposition": "attachment; filename=batch.png"},
            )
        if path == "/api/export/items":
            assert kwargs["params"] == {"format": "csv"}
            return FakeResponse(
                content=b"id,name\n",
                headers={
                    "Content-Disposition": "attachment; filename=items.csv",
                    "Content-Type": "text/csv",
                },
            )
        if path == "/api/files/9/download":
            return FakeResponse(
                content=b"manual",
                headers={
                    "Content-Disposition": "attachment; filename=manual.pdf",
                    "Content-Type": "application/pdf",
                },
            )
        raise AssertionError(f"Unexpected API call: {method} {path}")

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    qr = client.get("/download/qr/batch/batch-1")
    export = client.get("/download/export/items/csv")
    stored_file = client.get("/download/files/9")

    assert qr.get_data() == b"png-bytes"
    assert qr.mimetype == "image/png"
    assert qr.headers["Content-Disposition"] == "attachment; filename=batch.png"
    assert export.get_data() == b"id,name\n"
    assert export.mimetype == "text/csv"
    assert stored_file.get_data() == b"manual"
    assert stored_file.mimetype == "application/pdf"


def test_auth_routes_handle_success_reset_required_and_logout(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []

    def fake_request(method, url, **kwargs):
        path = request_path(url)
        calls.append({"method": method, "path": path, **kwargs})
        if path == "/api/auth/login" and kwargs["json"]["password"] == "good":
            return FakeResponse({
                "token": "login-token",
                "expires_at": "2026-06-20T12:00:00+00:00",
                "user": {"email": kwargs["json"]["email"]},
            })
        if path == "/api/auth/login":
            return FakeResponse({
                "error": {
                    "code": "password_reset_required",
                    "message": "Reset required",
                },
            }, status_code=403)
        if path == "/api/auth/register":
            if kwargs["json"]["email"] == "new@example.com":
                return FakeResponse({"user": {"id": 1}}, status_code=201)
            return FakeResponse({"error": {"message": "Duplicate", "details": {"email": "exists"}}}, status_code=409)
        if path == "/api/auth/reset":
            if kwargs["json"]["new_password"] == "new-password":
                return FakeResponse({})
            return FakeResponse({"error": {"message": "Reset failed"}}, status_code=400)
        if path == "/api/auth/logout":
            return FakeResponse({})
        raise AssertionError(f"Unexpected API call: {method} {path}")

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = app.test_client()

    login = client.post("/login?next=/settings", data={
        "email": "owner@example.com",
        "password": "good",
    })
    with client.session_transaction() as flask_session:
        assert flask_session["token"] == "login-token"
        assert flask_session["token_expires_at"] == "2026-06-20T12:00:00+00:00"
    logout = client.post("/logout")
    reset_redirect = client.post("/login", data={
        "email": "owner@example.com",
        "password": "expired",
    })
    register = client.post("/register", data={
        "email": "new@example.com",
        "password": "good",
        "display_name": "Owner",
    })
    register_error = client.post("/register", data={
        "email": "existing@example.com",
        "password": "good",
    })
    reset = client.post("/reset-password", data={
        "email": "owner@example.com",
        "new_password": "new-password",
    })
    reset_error = client.post("/reset-password", data={
        "email": "owner@example.com",
        "new_password": "bad",
    })

    assert login.status_code == 302
    assert login.location.endswith("/settings")
    assert logout.status_code == 302
    assert logout.location.endswith("/login")
    assert reset_redirect.location.endswith("/reset-password?email=owner@example.com")
    assert register.location.endswith("/login")
    assert register_error.status_code == 200
    assert reset.location.endswith("/login")
    assert reset_error.status_code == 200
    assert ("POST", "/api/auth/logout") in [(call["method"], call["path"]) for call in calls]


def test_login_handles_non_json_storage_error(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert request_path(url) == "/api/auth/login"
        return NonJsonResponse()

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = app.test_client()

    response = client.post("/login", data={
        "email": "owner@example.com",
        "password": "correct-horse-battery",
    })

    assert response.status_code == 200
    assert b"Storage service returned an invalid response" in response.data


def test_renderer_api_error_handlers_redirect_or_render_service_error(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    client = authenticated_client(app)

    def failing_request(_method, _url, **_kwargs):
        return FakeResponse({"error": {"message": "Storage rejected", "details": {"field": "bad"}}}, status_code=422)

    monkeypatch.setattr("rendering_app.app.requests.request", failing_request)
    response = client.get("/items")
    assert response.status_code == 302
    assert response.location.endswith("/")

    def unauthorized_request(_method, _url, **_kwargs):
        return FakeResponse({"error": {"message": "Unauthorized"}}, status_code=401)

    monkeypatch.setattr("rendering_app.app.requests.request", unauthorized_request)
    unauthorized = client.get("/items")
    assert unauthorized.status_code == 302
    assert unauthorized.location.endswith("/login")
    with client.session_transaction() as flask_session:
        assert "token" not in flask_session

    with client.session_transaction() as flask_session:
        flask_session["token"] = "test-token"

    def unavailable_request(_method, _url, **_kwargs):
        raise requests.RequestException("down")

    monkeypatch.setattr("rendering_app.app.requests.request", unavailable_request)
    service_error = client.get("/")
    assert service_error.status_code == 503
    assert "Storage service is unavailable" in service_error.get_data(as_text=True)


def test_readonly_session_allows_auth_mobile_batch_entry_but_blocks_other_writes(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "path": request_path(url), **kwargs})
        if request_path(url) == "/api/auth/login":
            return FakeResponse({
                "token": "readonly-token",
                "user": {"email": "viewer@example.com"},
                "expires_at": "2026-06-20T12:00:00+00:00",
            })
        if request_path(url) == "/api/auth/logout":
            return FakeResponse({})
        if method == "POST" and request_path(url) == "/api/batches/batch-1/transition":
            return FakeResponse({"batch": minimal_batch()})
        if method == "PUT" and request_path(url) == "/api/batches/batch-1/qa-measurements":
            return FakeResponse({"batch": minimal_batch()})
        if method == "POST" and request_path(url) == "/api/batches/batch-1/production-losses":
            return FakeResponse({"production_loss": {"id": 4}, "batch": minimal_batch()})
        if method == "POST" and request_path(url) == "/api/batches/batch-1/returns":
            return FakeResponse({"inventory_return": {"id": 5, "batch_id": "batch-1"}})
        if method == "POST" and request_path(url) == "/api/containers/4/assignments":
            return FakeResponse({"assignment": {"id": 6}})
        if method == "PATCH" and request_path(url) == "/api/containers/4":
            return FakeResponse({"container": {"id": 4}})
        raise AssertionError(f"Unexpected API call: {method} {request_path(url)}")

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = app.test_client()

    entry = client.get("/readonly")
    assert entry.status_code == 302
    assert entry.location.endswith("/")
    with client.session_transaction() as flask_session:
        assert flask_session["readonly"] is True

    login = client.post("/login", data={
        "email": "viewer@example.com",
        "password": "correct-horse-battery",
    })
    assert login.status_code == 302
    with client.session_transaction() as flask_session:
        assert flask_session["readonly"] is True
        assert flask_session["token"] == "readonly-token"

    blocked = client.post("/items", data={
        "category": "POWDER",
        "manufacturer": "Maker",
        "name": "H110",
    })
    assert blocked.status_code == 302
    assert blocked.location.endswith("/")
    assert [call["path"] for call in calls] == ["/api/auth/login"]

    qa = client.post("/batches/batch-1/qa", data={
        "sample_number": ["1", "2"],
        "completed_weight": ["247.125", "247.250"],
        "overall_length": ["1.5900", "1.5905"],
    })
    assert qa.status_code == 302
    assert qa.location.endswith("/batches/batch-1#qa-measurements")

    production_loss = client.post("/batches/batch-1/production-losses", data={
        "source_reservation_id": "7",
        "replacement_lot_id": "9",
        "quantity_lost": "1.5",
        "reason": "spill",
        "notes": "replacement reserved",
    })
    assert production_loss.status_code == 302
    assert production_loss.location.endswith("/batches/batch-1")

    returns = client.post("/batches/batch-1/returns", data={
        "source_lot_id": "19",
        "destination_lot_id": "",
        "quantity_returned": "3",
        "reason": "unused",
        "notes": "back to original lot",
    })
    assert returns.status_code == 302
    assert returns.location.endswith("/batches/batch-1")

    batch_state = client.post("/batches/batch-1/state", data={"state": "PRODUCED", "qa_override": "true"})
    assert batch_state.status_code == 302
    assert batch_state.location.endswith("/batches/batch-1")

    container_assign = client.post("/containers/4/assign", data={
        "batch_id": "batch-1",
        "quantity": "8",
        "acknowledge_mixed_batch": "on",
    })
    assert container_assign.status_code == 302
    assert container_assign.location.endswith("/containers")

    container_state = client.post("/containers/4/state", data={"state": "EMPTY"})
    assert container_state.status_code == 302
    assert container_state.location.endswith("/containers#container-4")

    state = client.post("/batches/batch-1/state", data={"state": "PRODUCED"})
    assert state.status_code == 302
    assert state.location.endswith("/batches/batch-1")

    theme = client.post("/settings/theme", data={"theme_mode": "dark"})
    assert theme.status_code == 302
    assert theme.location.endswith("/settings")
    with client.session_transaction() as flask_session:
        assert flask_session["readonly"] is True
        assert flask_session["theme_mode"] == "dark"
    assert [call["path"] for call in calls] == [
        "/api/auth/login",
        "/api/batches/batch-1/qa-measurements",
        "/api/batches/batch-1/production-losses",
        "/api/batches/batch-1/returns",
        "/api/batches/batch-1/transition",
        "/api/containers/4/assignments",
        "/api/containers/4",
        "/api/batches/batch-1/transition",
    ]

    logout = client.post("/logout")
    assert logout.status_code == 302
    assert logout.location.endswith("/login")
    with client.session_transaction() as flask_session:
        assert flask_session["readonly"] is True
        assert "token" not in flask_session
        assert flask_session["theme_mode"] == "dark"
    assert [call["path"] for call in calls] == [
        "/api/auth/login",
        "/api/batches/batch-1/qa-measurements",
        "/api/batches/batch-1/production-losses",
        "/api/batches/batch-1/returns",
        "/api/batches/batch-1/transition",
        "/api/containers/4/assignments",
        "/api/containers/4",
        "/api/batches/batch-1/transition",
        "/api/auth/logout",
    ]
    assert any(
        call["path"] == "/api/batches/batch-1/qa-measurements"
        and call["json"]["measurements"][0]["completed_weight"] == "247.125"
        for call in calls
    )
    assert any(
        call["path"] == "/api/batches/batch-1/production-losses"
        and call["json"]["quantity_lost"] == "1.5"
        for call in calls
    )
    assert any(
        call["path"] == "/api/batches/batch-1/returns"
        and call["json"]["quantity_returned"] == "3"
        and call["json"]["quantity_lost"] == "0"
        for call in calls
    )
    assert any(
        call["path"] == "/api/batches/batch-1/transition"
        and call["json"] == {"state": "PRODUCED", "qa_override": True}
        for call in calls
    )
    assert any(
        call["path"] == "/api/containers/4/assignments"
        and call["json"] == {"batch_id": "batch-1", "quantity": "8", "acknowledge_mixed_batch": True}
        for call in calls
    )
    assert any(
        call["path"] == "/api/containers/4"
        and call["json"] == {"state": "EMPTY"}
        for call in calls
    )


def test_item_and_inventory_routes_proxy_expected_payloads(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []

    def fake_request(method, url, **kwargs):
        path = request_path(url)
        calls.append({"method": method, "path": path, **kwargs})
        if method == "GET" and path == "/api/items":
            return FakeResponse({"items": [{"id": 7, "category": "POWDER", "manufacturer": "Maker", "name": "H110"}]})
        if method == "GET" and path == "/api/inventory-lots":
            return FakeResponse({"lots": []})
        return FakeResponse({})

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    items_get = client.get("/items?q=powder&category=POWDER&archived=true")
    item_post = client.post("/items", data={
        "category": "POWDER",
        "manufacturer": "Maker",
        "product_line": "Line",
        "name": "H110",
        "characteristics": "magnum",
        "caliber": "",
        "bullet_weight": "",
        "bullet_type": "",
        "primer_type": "",
        "powder_type": "ball",
        "attributes": "{}",
        "notes": "notes",
    })
    archive = client.post("/items/7/archive")
    inventory_get = client.get("/inventory?historical=true")
    activate = client.post("/inventory/19/activate")
    adjust = client.post("/inventory/19/adjust", data={
        "quantity_change": "-5",
        "reason": "count",
        "notes": "adjusted",
        "deplete_remaining": "on",
        "historical": "true",
    })

    assert items_get.status_code == 200
    assert item_post.location.endswith("/items")
    assert archive.location.endswith("/items")
    assert inventory_get.status_code == 200
    assert activate.location.endswith("/inventory")
    assert adjust.location.endswith("/inventory?historical=true")
    assert any(call["path"] == "/api/items" and call.get("json", {}).get("name") == "H110" for call in calls)
    assert any(call["path"] == "/api/items/7" and call["json"] == {"archived": True} for call in calls)
    assert any(
        call["path"] == "/api/inventory-lots/19/adjustments"
        and call["json"]["deplete_remaining"] is True
        for call in calls
    )


def test_items_page_renders_inventory_lot_counts(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []

    def fake_request(method, url, **kwargs):
        path = request_path(url)
        calls.append({"method": method, "path": path, **kwargs})
        if method == "GET" and path == "/api/items":
            return FakeResponse({"items": [
                {"id": 7, "category": "POWDER", "manufacturer": "Maker", "name": "H110"},
                {"id": 8, "category": "PRIMER", "manufacturer": "Maker", "name": "Primer"},
            ]})
        if method == "GET" and path == "/api/inventory-lots":
            return FakeResponse({"lots": [
                {"id": 19, "item_id": 7, "depleted": False},
                {"id": 20, "item_id": 7, "depleted": False},
                {"id": 21, "item_id": 7, "depleted": True},
                {"id": 22, "item_id": 8, "depleted": False},
            ]})
        return FakeResponse({})

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    response = client.get("/items")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<th>Lots</th>" in html
    assert "Maker H110" in html
    assert "Maker Primer" in html
    assert html.index("<td>2</td>") < html.index("Maker Primer")
    assert "<td>1</td>" in html
    assert any(
        call["path"] == "/api/inventory-lots"
        and call["params"] == {"historical": "false"}
        for call in calls
    )


def test_inventory_get_filters_lots_by_item_category(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})

    powder_item = {"id": 7, "category": "POWDER", "manufacturer": "Maker", "name": "H110"}
    primer_item = {"id": 8, "category": "PRIMER", "manufacturer": "Maker", "name": "Primer"}
    lots = [
        {
            "id": 19, "item_id": 7, "item": powder_item, "manufacturer_lot": "POWDER-LOT",
            "original_quantity": 1, "original_unit": "pounds", "adjustment_quantity": 0,
            "normalized_unit": "grains", "opened_on": None, "available_quantity": 7000,
            "reserved_quantity": 0, "consumed_quantity": 0, "depleted": False, "active": True,
            "can_edit": False, "edit_lock_reason": "locked",
        },
        {
            "id": 20, "item_id": 8, "item": primer_item, "manufacturer_lot": "PRIMER-LOT",
            "original_quantity": 100, "original_unit": "count", "adjustment_quantity": 0,
            "normalized_unit": "count", "opened_on": None, "available_quantity": 100,
            "reserved_quantity": 0, "consumed_quantity": 0, "depleted": False, "active": True,
            "can_edit": False, "edit_lock_reason": "locked",
        },
    ]

    def fake_request(method, url, **_kwargs):
        path = request_path(url)
        if method == "GET" and path == "/api/items":
            return FakeResponse({"items": [powder_item, primer_item]})
        if method == "GET" and path == "/api/inventory-lots":
            return FakeResponse({"lots": lots})
        return FakeResponse({})

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    response = client.get("/inventory?historical=true&category=POWDER")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "POWDER-LOT" in html
    assert "PRIMER-LOT" not in html
    assert '<option value="POWDER" selected>Powder</option>' in html
    assert 'href="/inventory?historical=false&amp;category=POWDER"' in html


def test_recipe_routes_proxy_detail_source_state_and_sharing(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []

    def fake_request(method, url, **kwargs):
        path = request_path(url)
        calls.append({"method": method, "path": path, **kwargs})
        if method == "GET" and path == "/api/recipes/recipe-1":
            return FakeResponse({"recipe": minimal_recipe()})
        if method == "GET" and path == "/api/items":
            return FakeResponse({"items": [{"id": 7, "category": "POWDER"}]})
        if method == "POST" and path == "/api/recipes":
            return FakeResponse({"recipe": {"id": "recipe-1"}}, status_code=201)
        if method == "POST" and path == "/api/recipes/recipe-1/components":
            return FakeResponse({"component": {"id": 11}, "warnings": []}, status_code=201)
        return FakeResponse({})

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    detail = client.get("/recipes/recipe-1?component_form=open")
    created = client.post("/recipes", data={
        "title": "Route Test Recipe",
        "cartridge": ".357 Magnum",
        "overall_length": "1.59",
        "case_length": "1.29",
        "expected_velocity": "1210.5",
        "crimp_type": "roll",
        "seating_depth": "",
        "source_notes": "",
        "notes": "",
        "public_notes": "",
        "suggested_title": "",
        "acknowledge_responsibility": "on",
    })
    source = client.post("/recipes/recipe-1/sources", data={
        "kind": "URL",
        "url": "https://example.test/source",
        "citation": "Example",
        "page": "",
        "notes": "web source",
    })
    component = client.post("/recipes/recipe-1/components", data={
        "item_id": "7",
        "powder_quantity": "15.5",
    })
    state = client.post("/recipes/recipe-1/state", data={
        "state": "UNDER TEST",
        "acknowledge_missing_source": "on",
    })
    sharing = client.post("/recipes/recipe-1/sharing", data={"public": "true"})
    deleted = client.post("/recipes/recipe-1/delete")

    assert detail.status_code == 200
    assert created.location.endswith("/recipes/recipe-1")
    assert source.location.endswith("/recipes/recipe-1")
    assert component.location.endswith("/recipes/recipe-1#components")
    assert state.location.endswith("/recipes/recipe-1")
    assert sharing.location.endswith("/recipes/recipe-1")
    assert deleted.location.endswith("/recipes")
    create_payload = next(call["json"] for call in calls if call["path"] == "/api/recipes")
    assert create_payload["acknowledge_responsibility"] is True
    assert create_payload["expected_velocity"] == "1210.5"
    assert any(call["path"] == "/api/recipes/recipe-1/sources" and call.get("json", {}).get("kind") == "URL" for call in calls)
    assert any(call["path"] == "/api/recipes/recipe-1/components" and call["json"] == {
        "item_id": "7", "quantity": "15.5", "unit": "grains",
    } for call in calls)
    assert any(call["path"] == "/api/recipes/recipe-1/transition" and call["json"]["acknowledge_missing_source"] is True for call in calls)
    assert any(call["path"] == "/api/recipes/recipe-1" and call.get("json") == {"public": True} for call in calls)
    assert any(call["method"] == "DELETE" and call["path"] == "/api/recipes/recipe-1" for call in calls)


def test_batch_routes_proxy_detail_state_return_and_performance(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []

    def fake_request(method, url, **kwargs):
        path = request_path(url)
        calls.append({"method": method, "path": path, **kwargs})
        if method == "GET" and path == "/api/batches/batch-1":
            return FakeResponse({"batch": minimal_batch()})
        if method == "GET" and path in {"/api/inventory-lots", "/api/containers"}:
            key = "containers" if path == "/api/containers" else "lots"
            return FakeResponse({key: []})
        return FakeResponse({})

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    detail = client.get("/batches/batch-1")
    state = client.post("/batches/batch-1/state", data={"state": "DECOMMISSIONED"})
    returns = client.post("/batches/batch-1/returns", data={
        "source_lot_id": "19",
        "destination_lot_id": "",
        "quantity_returned": "1",
        "reason": "count",
        "notes": "returned",
    })
    production_loss = client.post("/batches/batch-1/production-losses", data={
        "source_reservation_id": "7",
        "replacement_lot_id": "9",
        "quantity_lost": "1.5",
        "reason": "spill",
        "notes": "replacement reserved",
    })
    qa = client.post("/batches/batch-1/qa", data={
        "sample_number": ["1", "2"],
        "completed_weight": ["247.125", ""],
        "overall_length": ["1.5900", ""],
    })
    performance = client.post("/batches/batch-1/performance", data={
        "recorded_on": "2026-06-20",
        "firearm": "Test revolver",
        "barrel_length": "4.2",
        "distance": "25",
        "group_size": "2",
        "shot_count": "6",
        "velocity_average": "1200",
        "velocity_minimum": "1180",
        "velocity_maximum": "1215",
        "standard_deviation": "9",
        "extreme_spread": "35",
        "temperature": "72",
        "recoil_perception": "3",
        "accuracy_perception": "4",
        "cleanliness_perception": "5",
        "subjective_rating": "4",
        "notes": "solid",
        "raw_data": "1180,1215",
        "processed_data": "{}",
    })

    assert detail.status_code == 200
    assert state.location.endswith("/batches/batch-1")
    assert returns.location.endswith("/batches/batch-1")
    assert production_loss.location.endswith("/batches/batch-1")
    assert qa.location.endswith("/batches/batch-1#qa-measurements")
    assert performance.location.endswith("/batches/batch-1")
    assert any(call["path"] == "/api/batches/batch-1/transition" and call["json"] == {"state": "DECOMMISSIONED"} for call in calls)
    assert any(
        call["path"] == "/api/batches/batch-1/returns"
        and call["json"]["quantity_returned"] == "1"
        and call["json"]["quantity_lost"] == "0"
        for call in calls
    )
    assert any(call["path"] == "/api/batches/batch-1/production-losses" and call["json"]["quantity_lost"] == "1.5" for call in calls)
    assert any(call["path"] == "/api/batches/batch-1/qa-measurements" and call["json"]["measurements"][0]["completed_weight"] == "247.125" for call in calls)
    assert any(call["path"] == "/api/batches/batch-1/performance" and call["json"]["raw_data"] == "1180,1215" for call in calls)


def test_container_audit_and_qr_routes(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []
    container = {
        "id": 4,
        "state": "ASSIGNED",
        "name": "Test Box",
        "identifier": "BOX-1",
        "total_quantity": 0,
        "cartridge_limit": 50,
        "assignments": [],
        "remaining_capacity": 50,
    }
    batch = {
        "id": "batch-1",
        "slug": "route-test-batch",
        "state": "PRODUCED",
        "iterations": 10,
        "container_unassigned_quantity": 10,
        "recipe": {"title": "Route Test Recipe"},
    }

    def fake_request(method, url, **kwargs):
        path = request_path(url)
        calls.append({"method": method, "path": path, **kwargs})
        if method == "GET" and path == "/api/containers":
            return FakeResponse({"containers": [container]})
        if method == "GET" and path == "/api/batches":
            return FakeResponse({"batches": [batch]})
        if method == "GET" and path == "/api/audit":
            return FakeResponse({"audit": []})
        return FakeResponse({})

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    containers_get = client.get("/containers")
    create = client.post("/containers", data={
        "identifier": "BOX-2",
        "name": "Second Box",
        "cartridge_limit": "50",
        "description": "range box",
        "notes": "created",
    })
    assign = client.post("/containers/4/assign", data={
        "batch_id": "batch-1",
        "quantity": "5",
        "acknowledge_mixed_batch": "on",
    })
    state = client.post("/containers/4/state", data={"state": "EMPTY"})
    audit = client.get("/audit")
    qr_recipe = client.get("/qr/recipe/recipe-1")
    qr_batch = client.get("/qr/batch/batch-1")
    qr_unknown = client.get("/qr/item/7")

    assert containers_get.status_code == 200
    assert create.location.endswith("/containers")
    assert assign.location.endswith("/containers")
    assert state.location.endswith("/containers#container-4")
    assert audit.status_code == 200
    assert qr_recipe.status_code == 200
    assert qr_batch.status_code == 200
    assert qr_unknown.status_code == 302
    assert qr_unknown.location.endswith("/")
    assert any(call["path"] == "/api/containers" and call.get("json", {}).get("identifier") == "BOX-2" for call in calls)
    assert any(
        call["path"] == "/api/containers/4/assignments"
        and call["json"]["acknowledge_mixed_batch"] is True
        for call in calls
    )
    assert any(call["path"] == "/api/containers/4" and call["json"] == {"state": "EMPTY"} for call in calls)


def test_edit_routes_proxy_metadata_patch_payloads(monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "path": request_path(url), **kwargs})
        if request_path(url) == "/api/items/7":
            return FakeResponse({"item": {"id": 7}})
        if request_path(url) == "/api/inventory-lots/9":
            return FakeResponse({"lot": {"id": 9}})
        if request_path(url) == "/api/recipes/recipe-1":
            return FakeResponse({"recipe": {"id": "recipe-1"}})
        if request_path(url) == "/api/batches/batch-1":
            return FakeResponse({"batch": {"id": "batch-1"}})
        if request_path(url) == "/api/containers/4":
            return FakeResponse({"container": {"id": 4}})
        raise AssertionError(f"Unexpected API call: {method} {request_path(url)}")

    monkeypatch.setattr("rendering_app.app.requests.request", fake_request)
    client = authenticated_client(app)

    assert client.post("/items/7/edit", data={
        "category": "POWDER",
        "manufacturer": "Maker",
        "product_line": "Line",
        "name": "H110",
        "characteristics": "magnum",
        "powder_type": "spherical",
        "attributes": "{}",
        "notes": "corrected",
    }).location.endswith("/items")
    assert client.post("/inventory/9/edit", data={
        "item_id": "7",
        "manufacturer_lot": "LOT-9",
        "quantity": "100",
        "unit": "count",
        "cost": "12.34",
        "acquired_on": "2026-06-20",
        "opened_on": "",
        "notes": "lot notes",
        "historical": "true",
    }).location.endswith("/inventory?historical=true")
    assert client.post("/recipes/recipe-1/edit", data={
        "title": "Recipe",
        "cartridge": ".357",
        "overall_length": "1.59",
        "case_length": "1.29",
        "expected_velocity": "1225",
        "crimp_type": "roll",
        "seating_depth": "",
        "source_notes": "source",
        "notes": "private",
        "public_notes": "public",
    }).location.endswith("/recipes/recipe-1")
    assert client.post("/batches/batch-1/edit", data={
        "slug": "batch-label",
        "characteristics": "test batch",
        "notes": "batch notes",
    }).location.endswith("/batches/batch-1")
    assert client.post("/containers/4/edit", data={
        "identifier": "BOX-1",
        "name": "Box",
        "cartridge_limit": "50",
        "description": "desc",
        "notes": "notes",
    }).location.endswith("/containers#container-4")

    payloads = {(call["method"], call["path"]): call["json"] for call in calls}
    assert payloads[("PATCH", "/api/items/7")]["category"] == "POWDER"
    assert payloads[("PATCH", "/api/items/7")]["name"] == "H110"
    assert payloads[("PATCH", "/api/inventory-lots/9")]["quantity"] == "100"
    assert payloads[("PATCH", "/api/inventory-lots/9")]["cost"] == "12.34"
    assert payloads[("PATCH", "/api/recipes/recipe-1")]["source_notes"] == "source"
    assert payloads[("PATCH", "/api/recipes/recipe-1")]["expected_velocity"] == "1225"
    assert payloads[("PATCH", "/api/batches/batch-1")]["characteristics"] == "test batch"
    assert payloads[("PATCH", "/api/containers/4")]["identifier"] == "BOX-1"
