from types import SimpleNamespace

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
