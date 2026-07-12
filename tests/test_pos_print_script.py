from types import SimpleNamespace
import base64

from pos_print_service.scripts import test_print


def response(status_code=200, payload=None, text=""):
    payload = payload or {}

    def raise_for_status():
        if status_code >= 400:
            raise test_print.requests.HTTPError(f"HTTP {status_code}")

    return SimpleNamespace(
        status_code=status_code,
        ok=status_code < 400,
        text=text,
        json=lambda: payload,
        raise_for_status=raise_for_status,
    )


def test_print_script_refuses_real_printer_service_without_explicit_flag(monkeypatch, capsys):
    posts = []

    monkeypatch.setattr(
        test_print.requests,
        "get",
        lambda url, timeout: response(payload={"status": "ok", "mode": "printer"}),
    )
    monkeypatch.setattr(
        test_print.requests,
        "post",
        lambda *args, **kwargs: posts.append((args, kwargs)) or response(),
    )

    status = test_print.main(["--service-url", "http://printer.local:8088", "text", "Printer online"])

    assert status == 2
    assert posts == []
    assert "Refusing to submit a print test" in capsys.readouterr().err


def test_print_script_refuses_when_health_check_cannot_be_verified(monkeypatch, capsys):
    def fail_get(*_args, **_kwargs):
        raise test_print.requests.RequestException("connection refused")

    monkeypatch.setattr(test_print.requests, "get", fail_get)

    status = test_print.main(["--service-url", "http://printer.local:8088", "text", "Printer online"])

    assert status == 2
    assert "could not be verified" in capsys.readouterr().err


def test_print_script_allows_dry_run_service(monkeypatch):
    calls = []

    monkeypatch.setattr(
        test_print.requests,
        "get",
        lambda url, timeout: response(payload={"status": "ok", "mode": "dry_run"}),
    )

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return response(payload={"status": "accepted", "mode": "dry_run"})

    monkeypatch.setattr(test_print.requests, "post", fake_post)

    status = test_print.main(["--service-url", "http://localhost:8089", "text", "Printer online"])

    assert status == 0
    assert calls == [{
        "url": "http://localhost:8089/print/test",
        "json": {"text": "Printer online"},
        "timeout": 15,
    }]


def test_print_script_allows_real_printer_with_explicit_flag(monkeypatch):
    calls = []

    def fail_get(*_args, **_kwargs):
        raise AssertionError("health check should be skipped when live printing is explicitly allowed")

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return response(payload={"status": "printed", "mode": "printer"})

    monkeypatch.setattr(test_print.requests, "get", fail_get)
    monkeypatch.setattr(test_print.requests, "post", fake_post)

    status = test_print.main([
        "--service-url",
        "http://printer.local:8088",
        "--allow-real-printer",
        "text",
        "Printer online",
    ])

    assert status == 0
    assert calls[0]["url"] == "http://printer.local:8088/print/test"


def test_print_script_sends_image_command_to_test_endpoint(monkeypatch, tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"png-bytes")
    calls = []

    monkeypatch.setattr(
        test_print.requests,
        "get",
        lambda url, timeout: response(payload={"status": "ok", "mode": "dry_run"}),
    )

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return response(payload={"status": "accepted", "mode": "dry_run"})

    monkeypatch.setattr(test_print.requests, "post", fake_post)

    status = test_print.main([
        "--service-url",
        "http://localhost:8089",
        "image",
        str(logo),
        "--text",
        "Logo test",
    ])

    assert status == 0
    assert calls[0]["url"] == "http://localhost:8089/print/test"
    assert calls[0]["json"]["text"] == "Logo test"
    assert calls[0]["json"]["image"]["filename"] == "logo.png"


def test_image_payload_encodes_png_file(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"png-bytes")

    payload = test_print.image_payload(logo)

    assert payload == {
        "base64": base64.b64encode(b"png-bytes").decode("ascii"),
        "content_type": "image/png",
        "filename": "logo.png",
    }


def test_post_json_reports_http_failures(monkeypatch, capsys):
    monkeypatch.setattr(
        test_print.requests,
        "post",
        lambda *_args, **_kwargs: response(status_code=500, text="printer failed"),
    )

    status = test_print.post_json("http://localhost:8088", "/print/test", {"text": "test"})

    output = capsys.readouterr().out
    assert status == 1
    assert "HTTP 500" in output
    assert "printer failed" in output


def test_print_script_sends_sample_batch_created_with_logo(monkeypatch, tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"png-bytes")
    calls = []

    monkeypatch.setattr(
        test_print.requests,
        "get",
        lambda url, timeout: response(payload={"status": "ok", "mode": "dry_run"}),
    )
    monkeypatch.setattr(
        test_print,
        "post_json",
        lambda service_url, path, payload: calls.append((service_url, path, payload)) or 0,
    )

    status = test_print.main([
        "--service-url",
        "http://localhost:8088",
        "sample",
        "batch-created",
        "--logo",
        str(logo),
    ])

    assert status == 0
    assert calls[0][1] == "/print/batch-created"
    assert calls[0][2]["batch"]["state"] == "UNDER PRODUCTION"
    assert calls[0][2]["logo"]["filename"] == "logo.png"


def test_print_script_sends_sample_batch_produced(monkeypatch):
    calls = []

    monkeypatch.setattr(
        test_print.requests,
        "get",
        lambda url, timeout: response(payload={"status": "ok", "mode": "dry_run"}),
    )
    monkeypatch.setattr(
        test_print,
        "post_json",
        lambda service_url, path, payload: calls.append((service_url, path, payload)) or 0,
    )

    status = test_print.main(["--service-url", "http://localhost:8088", "sample", "batch-produced"])

    assert status == 0
    assert calls[0][1] == "/print/batch-produced"
    assert calls[0][2]["batch"]["state"] == "PRODUCED"
