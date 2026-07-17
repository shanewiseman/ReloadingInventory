from io import BytesIO
import base64

import pytest
from jinja2 import Undefined
from PIL import Image

from pos_print_service.app import (
    create_app,
    env_bool,
    load_logo,
    record_dry_run_job,
    render_event_document,
    render_test_document,
    send_document_response,
    send_to_printer,
)
from pos_print_service.escpos import (
    build_document,
    command_text,
    image_bytes,
    qr_image,
    send_tcp_print_job,
)


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
                "expected_velocity": 1210,
                "aggregate_performance": {
                    "performance_record_count": 1,
                    "average_velocity": 1208,
                    "average_standard_deviation": 8.4,
                    "average_extreme_spread": 26,
                    "average_moa": 2.3,
                    "average_rating": 4,
                },
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


def test_pos_print_create_app_uses_environment_defaults(monkeypatch):
    monkeypatch.setenv("POS_PRINT_DRY_RUN", "true")
    monkeypatch.setenv("PRINTER_HOST", "printer.local")

    app = create_app()

    assert app.config["POS_PRINT_DRY_RUN"] is True
    assert app.config["PRINTER_HOST"] == "printer.local"


def test_env_bool_and_template_filters_handle_defaults_and_bad_values(monkeypatch):
    monkeypatch.delenv("TEST_POS_FLAG", raising=False)
    assert env_bool("TEST_POS_FLAG", default=True) is True

    monkeypatch.setenv("TEST_POS_FLAG", "yes")
    assert env_bool("TEST_POS_FLAG") is True

    monkeypatch.setenv("TEST_POS_FLAG", "off")
    assert env_bool("TEST_POS_FLAG") is False

    app = create_app({"TESTING": True})
    value_filter = app.jinja_env.filters["value"]
    number_filter = app.jinja_env.filters["number"]
    money_filter = app.jinja_env.filters["money"]

    assert value_filter(Undefined(name="missing")) == "N/A"
    assert value_filter("loaded") == "loaded"
    assert number_filter(None) == "N/A"
    assert number_filter("bad number") == "bad number"
    assert number_filter("5.50") == "5.5"
    assert money_filter("") == "N/A"
    assert money_filter("bad money") == "bad money"
    assert money_filter("1.25") == "$1.2500"


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
    assert b"Required QA samples" in document
    assert b"Completed QA samples" not in document
    assert b"QC checks" not in document
    assert b"Components match traveler" not in document
    assert b"Batch QR" not in document
    assert b"Recipe QR" not in document


def test_batch_created_endpoint_renders_mcp_marker_near_top(monkeypatch):
    app = create_app({"TESTING": True})
    payload = sample_payload()
    payload["mcp_print_notice"] = "Printed by MCP call"
    captured = {}

    def fake_send(_app, document):
        captured["document"] = document

    monkeypatch.setattr("pos_print_service.app.send_to_printer", fake_send)

    response = app.test_client().post("/print/batch-created", json=payload)

    assert response.status_code == 200
    document = captured["document"]
    assert b"Printed by MCP call" in document
    assert document.find(b"Printed by MCP call") < document.find(b"Batch:")


def test_batch_created_endpoint_renders_bullet_ballistics(monkeypatch):
    app = create_app({"TESTING": True})
    payload = sample_payload()
    payload["batch"]["recipe"]["components"].append({
        "role": "BULLET",
        "quantity": 1,
        "unit": "count",
        "item": {
            "manufacturer": "Test",
            "name": "168 BTHP",
            "ballistics": {
                "drag_model": "G7",
                "ballistic_coefficient": 0.243,
            },
        },
    })
    captured = {}

    def fake_send(_app, document):
        captured["document"] = document

    monkeypatch.setattr("pos_print_service.app.send_to_printer", fake_send)

    response = app.test_client().post("/print/batch-created", json=payload)

    assert response.status_code == 200
    assert b"BC: 0.243 G7" in captured["document"]


def test_batch_produced_endpoint_omits_performance_and_consumed_inventory(monkeypatch):
    app = create_app({"TESTING": True})
    payload = sample_payload()
    payload["batch"]["state"] = "PRODUCED"
    payload["batch"]["qa"].update({
        "average_completed_weight": 252.4,
        "average_overall_length": 1.5905,
        "weight_difference_standard_deviation": 0.25,
        "length_difference_standard_deviation": 0.0005,
    })
    payload["batch"]["performance"] = {
        "recorded_on": "2026-06-27",
        "firearm": "test revolver",
        "velocity_average": 1210,
    }
    payload["batch"]["consumptions"] = [{
        "role": "POWDER",
        "item": "Powder",
        "lot_id": "LOT-CONSUMED",
        "quantity": 105,
        "unit": "grains",
    }]
    captured = {}

    def fake_send(_app, document):
        captured["document"] = document

    monkeypatch.setattr("pos_print_service.app.send_to_printer", fake_send)

    response = app.test_client().post("/print/batch-produced", json=payload)

    assert response.status_code == 200
    document = captured["document"]
    assert b"Batch Produced" in document
    assert b"Produced batch label" in document
    assert b"Recipe ID:" not in document
    assert b"State:" not in document
    assert b"Expected velocity: 1210 fps" in document
    assert b"Recipe performance" in document
    assert b"Performance records: 1" in document
    assert b"Avg velocity: 1208 fps" in document
    assert b"Avg std dev: 8.4 fps" in document
    assert b"Avg extreme spread: 26 fps" in document
    assert b"Avg MOA: 2.3" in document
    assert b"Avg rating: 4" in document
    assert b"Weight std dev: 0.25 gr" in document
    assert b"OAL std dev: 0.0005 in" in document
    assert b"Batch QR" in document
    assert b"Recipe QR" in document
    assert b"Velocity avg" not in document
    assert b"test revolver" not in document
    assert b"Inventory consumed" not in document
    assert b"LOT-CONSUMED" not in document


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


def test_print_test_requires_text_or_image():
    app = create_app({"TESTING": True})

    response = app.test_client().post("/print/test", json={})

    assert response.status_code == 400
    assert response.json["error"]["message"] == "text or image is required"


def test_render_event_document_rejects_unknown_events_and_missing_batch():
    app = create_app({"TESTING": True})

    with pytest.raises(ValueError, match="Unknown print event"):
        render_event_document(app, "inventory_received", sample_payload())

    with pytest.raises(ValueError, match="batch object is required"):
        render_event_document(app, "batch_created", {"company": "Wiseman"})


def test_render_test_document_accepts_text_only_without_image():
    app = create_app({"TESTING": True})

    with app.app_context():
        document = render_test_document(app, {"text": "text-only printer test"})

    assert b"text-only printer test" in document


def test_render_test_document_accepts_image_only_without_text():
    app = create_app({"TESTING": True})

    with app.app_context():
        document = render_test_document(app, {
            "image": {
                "filename": "logo.png",
                "content_type": "image/png",
                "base64": base64.b64encode(PNG_BYTES).decode("ascii"),
            },
        })

    assert document.startswith(b"\x1b@")


def test_record_dry_run_job_uses_recipe_fallback_and_respects_limit():
    app = create_app({"TESTING": True, "DRY_RUN_JOB_LIMIT": 1})

    first = record_dry_run_job(
        app,
        b"first",
        event="first",
        payload={"batch": {"id": "batch-1", "slug": "batch-1", "recipe_id": "recipe-from-batch"}},
    )
    second = record_dry_run_job(
        app,
        b"second",
        event="second",
        payload={"batch": {"id": "batch-2", "slug": "batch-2", "recipe_id": "recipe-2"}},
    )

    assert first["recipe_id"] == "recipe-from-batch"
    assert [job["id"] for job in app.print_jobs] == [second["id"]]


def test_record_dry_run_job_accepts_non_dict_payload_and_unbounded_limit():
    app = create_app({"TESTING": True, "DRY_RUN_JOB_LIMIT": 0})

    first = record_dry_run_job(app, b"first", event="test", payload=None)
    second = record_dry_run_job(app, b"second", event="test", payload="not a dict")

    assert len(app.print_jobs) == 2
    assert first["batch_id"] is None
    assert second["urls"] == {}


def test_send_document_response_records_successful_printer_jobs(monkeypatch):
    app = create_app({"TESTING": True, "POS_PRINT_DRY_RUN": False})
    sent = []

    monkeypatch.setattr("pos_print_service.app.send_to_printer", lambda _app, document: sent.append(document))

    with app.app_context():
        response = send_document_response(app, b"print document", event="test", payload={"company": "Wiseman"})

    assert response.status_code == 200
    assert response.json["status"] == "printed"
    assert sent == [b"print document"]
    assert app.print_jobs[0]["company"] == "Wiseman"


def test_empty_local_fallback_logo_is_ignored(monkeypatch, tmp_path):
    empty_logo = tmp_path / "logo.png"
    empty_logo.write_bytes(b"")
    app = create_app({
        "TESTING": True,
        "LOGO_PATH": str(empty_logo),
        "POS_PRINT_DRY_RUN": True,
    })

    response = app.test_client().post("/print/batch-created", json={
        key: value for key, value in sample_payload().items() if key != "logo"
    })

    assert response.status_code == 200
    assert response.json["status"] == "accepted"


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


def test_load_logo_reports_bad_base64_bad_formats_and_uses_file_fallback(tmp_path):
    app = create_app({"TESTING": True})

    with pytest.raises(ValueError, match="logo image must be valid base64"):
        load_logo(app, {"base64": "not base64"})

    with pytest.raises(ValueError, match="image must be valid base64"):
        load_logo(app, "not base64")

    jpeg_buffer = BytesIO()
    Image.new("RGB", (1, 1), "white").save(jpeg_buffer, format="JPEG")
    jpeg_payload = base64.b64encode(jpeg_buffer.getvalue()).decode("ascii")
    with pytest.raises(ValueError, match="logo image must be a PNG"):
        load_logo(app, {"base64": jpeg_payload})

    bad_png_payload = base64.b64encode(b"this is not a png").decode("ascii")
    with pytest.raises(ValueError, match="logo image must be a valid PNG"):
        load_logo(app, {"base64": bad_png_payload})

    fallback_logo = tmp_path / "fallback.png"
    fallback_logo.write_bytes(PNG_BYTES)
    fallback_app = create_app({"TESTING": True, "LOGO_PATH": str(fallback_logo)})

    image = load_logo(fallback_app, None)

    assert image.size == (1, 1)
    assert load_logo(fallback_app, None, allow_fallback=False) is None


def test_send_to_printer_and_tcp_transport_use_configured_connection(monkeypatch):
    app = create_app({
        "TESTING": True,
        "PRINTER_HOST": "printer.test",
        "PRINTER_PORT": 9101,
        "PRINTER_TIMEOUT_SECONDS": 2.5,
    })
    send_calls = []

    monkeypatch.setattr(
        "pos_print_service.app.send_tcp_print_job",
        lambda host, port, content, timeout: send_calls.append((host, port, content, timeout)),
    )

    send_to_printer(app, b"document")

    assert send_calls == [("printer.test", 9101, b"document", 2.5)]

    with pytest.raises(RuntimeError, match="PRINTER_HOST"):
        send_tcp_print_job("", 9100, b"document")

    socket_calls = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def sendall(self, content):
            socket_calls.append(content)

    def fake_connection(address, timeout):
        socket_calls.append((address, timeout))
        return FakeConnection()

    monkeypatch.setattr("pos_print_service.escpos.socket.create_connection", fake_connection)

    send_tcp_print_job("printer.test", "9100", b"document", timeout="1.5")

    assert socket_calls == [(("printer.test", 9100), 1.5), b"document"]


def test_escpos_helpers_cover_wrapping_images_qr_and_no_cut_documents():
    wrapped = command_text("abcd efgh\n\nwide", width=4)
    image = Image.new("RGBA", (12, 2), (0, 0, 0, 0))

    raster = image_bytes(image, max_width_px=4)
    qr = qr_image("http://reload.local/batches/batch-1", box_size=1)
    document = build_document([wrapped, raster], feed_and_cut=False)

    assert b"\n\n" in wrapped
    assert raster.startswith(b"\x1dv0\x00")
    assert qr.size[0] > 0
    assert document.startswith(b"\x1b@")
    assert not document.endswith(b"\x1dV\x00")
