from io import BytesIO
import base64

from pos_print_service.app import create_app


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def sample_payload():
    return {
        "company": "Wiseman Precision Cartridges",
        "generated_at": "2026-06-27T12:00:00+00:00",
        "urls": {
            "batch": "http://reload.local/batches/batch-1",
            "recipe": "http://reload.local/recipes/recipe-1",
        },
        "logo": {
            "filename": "logo.png",
            "content_type": "image/png",
            "base64": base64.b64encode(PNG_BYTES).decode("ascii"),
        },
        "batch": {
            "id": "batch-1",
            "slug": "route-test-batch",
            "recipe_id": "recipe-1",
            "state": "UNDER PRODUCTION",
            "iterations": 10,
            "characteristics": "function check",
            "notes": "test batch",
            "recipe": {
                "id": "recipe-1",
                "title": "Route Test Recipe",
                "overall_length": 1.59,
                "components": [{
                    "role": "POWDER",
                    "quantity": 10.5,
                    "unit": "grains",
                    "item": {"manufacturer": "Test", "name": "Powder"},
                }],
            },
            "reservations": [{
                "role": "POWDER",
                "item": "Powder",
                "lot": "LOT-1",
                "quantity": 105,
                "unit": "grains",
                "status": "RESERVED",
            }],
            "consumptions": [],
            "qa": {
                "required_sample_count": 3,
                "completed_sample_count": 0,
                "is_satisfied": False,
            },
            "performance": None,
            "material_cost_status": "unavailable",
        },
    }


def test_pos_print_service_health():
    app = create_app({"TESTING": True, "PRINTER_HOST": "192.0.2.10"})

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.json == {
        "status": "ok",
        "mode": "printer",
        "printer_host_configured": True,
    }


def test_batch_created_endpoint_renders_and_sends_escpos(monkeypatch):
    app = create_app({"TESTING": True})
    captured = {}

    def fake_send(_app, document):
        captured["document"] = document

    monkeypatch.setattr("pos_print_service.app.send_to_printer", fake_send)

    response = app.test_client().post("/print/batch-created", json=sample_payload())

    assert response.status_code == 200
    assert response.json["status"] == "printed"
    document = captured["document"]
    assert document.startswith(b"\x1b@")
    assert b"Wiseman Precision Cartridges" in document
    assert b"Batch Created" in document
    assert b"Production traveler" in document
    assert b"Batch QR" in document
    assert b"Recipe QR" in document


def test_dry_run_accepts_same_batch_endpoint_without_printer(monkeypatch):
    app = create_app({"TESTING": True, "POS_PRINT_DRY_RUN": True})

    def fail_send(_app, _document):
        raise AssertionError("dry-run mode must not call the printer transport")

    monkeypatch.setattr("pos_print_service.app.send_to_printer", fail_send)
    client = app.test_client()

    response = client.post("/print/batch-created", json=sample_payload())

    assert response.status_code == 200
    assert response.json["status"] == "accepted"
    assert response.json["mode"] == "dry_run"
    assert response.json["bytes"] > 0
    assert response.json["job_id"] == 1

    jobs = client.get("/print/jobs")
    assert jobs.status_code == 200
    assert jobs.json["mode"] == "dry_run"
    assert jobs.json["jobs"] == [{
        "id": 1,
        "created_at": jobs.json["jobs"][0]["created_at"],
        "event": "batch_created",
        "bytes": response.json["bytes"],
        "sha256": jobs.json["jobs"][0]["sha256"],
        "batch_id": "batch-1",
        "batch_slug": "route-test-batch",
        "recipe_id": "recipe-1",
        "company": "Wiseman Precision Cartridges",
        "urls": {
            "batch": "http://reload.local/batches/batch-1",
            "recipe": "http://reload.local/recipes/recipe-1",
        },
    }]
    assert len(jobs.json["jobs"][0]["sha256"]) == 64

    cleared = client.delete("/print/jobs")
    assert cleared.status_code == 200
    assert client.get("/print/jobs").json["jobs"] == []


def test_batch_event_requires_batch_object(monkeypatch):
    app = create_app({"TESTING": True})

    response = app.test_client().post("/print/batch-created", json={"company": "Wiseman"})

    assert response.status_code == 400
    assert response.json["error"]["message"] == "batch object is required"


def test_print_service_reports_printer_transport_failure(monkeypatch):
    app = create_app({"TESTING": True})

    def fake_send(_app, _document):
        raise RuntimeError("printer offline")

    monkeypatch.setattr("pos_print_service.app.send_to_printer", fake_send)

    response = app.test_client().post("/print/batch-produced", json=sample_payload())

    assert response.status_code == 502
    assert response.json["error"]["message"] == "printer offline"


def test_print_test_accepts_text_and_png_image(monkeypatch):
    app = create_app({"TESTING": True})
    captured = {}

    def fake_send(_app, document):
        captured["document"] = document

    monkeypatch.setattr("pos_print_service.app.send_to_printer", fake_send)

    response = app.test_client().post("/print/test", json={
        "text": "direct printer check",
        "image": {
            "filename": "logo.png",
            "content_type": "image/png",
            "base64": base64.b64encode(PNG_BYTES).decode("ascii"),
        },
    })

    assert response.status_code == 200
    assert b"direct printer check" in captured["document"]
