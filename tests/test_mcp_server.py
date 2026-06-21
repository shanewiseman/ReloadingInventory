from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace

import pytest
import requests
from requests import Response

from reloading_mcp.server import (
    McpServer,
    ReloadingApiClient,
    build_server_from_env,
    response_to_structured,
    run_stdio,
)


def json_response(status_code, body):
    response = Response()
    response.status_code = status_code
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(body).encode()
    return response


def raw_response(status_code, body, content_type):
    response = Response()
    response.status_code = status_code
    response.headers["Content-Type"] = content_type
    response._content = body
    return response


def make_server(fake_request=None, token=None):
    if fake_request is None:
        fake_request = lambda **_kwargs: json_response(200, {})
    session = SimpleNamespace(request=fake_request)
    return McpServer(ReloadingApiClient("http://api.example.test", token=token, session=session))


def call_tool(server, name, arguments=None):
    return server.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    })


def test_initialize_declares_tools_capability():
    server = make_server()

    response = server.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0"},
        },
    })

    assert response["result"]["protocolVersion"] == "2025-06-18"
    assert response["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert response["result"]["serverInfo"]["name"] == "reload-ledger-api"


def test_tools_list_exposes_api_bridge_tools():
    server = make_server()

    response = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    names = {tool["name"] for tool in response["result"]["tools"]}
    assert {"login", "api_routes", "api_get", "api_post", "api_patch", "api_put", "api_delete"} <= names


def test_login_stores_token_without_returning_it():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return json_response(200, {
            "token": "secret-token",
            "expires_at": "2026-06-19T13:00:00+00:00",
            "user": {"id": 1, "email": "owner@example.com"},
        })

    server = make_server(fake_request=fake_request)

    response = call_tool(server, "login", {"email": "owner@example.com", "password": "correct-horse-battery"})

    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["authenticated"] is True
    assert "secret-token" not in result["content"][0]["text"]
    assert server.api_client.token == "secret-token"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "http://api.example.test/api/auth/login"
    assert "Authorization" not in calls[0]["headers"]


def test_api_get_calls_relative_path_with_bearer_token_and_query():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return json_response(200, {"items": []})

    server = make_server(fake_request=fake_request, token="session-token")

    response = call_tool(
        server,
        "api_get",
        {"path": "/api/items?category=POWDER", "query": {"archived": "false"}},
    )

    assert response["result"]["structuredContent"]["body"] == {"items": []}
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "http://api.example.test/api/items"
    assert calls[0]["headers"]["Authorization"] == "Bearer session-token"
    assert ("category", "POWDER") in calls[0]["params"]
    assert ("archived", "false") in calls[0]["params"]


def test_build_server_from_env_uses_auth_token(monkeypatch):
    monkeypatch.setenv("RELOADING_API_BASE_URL", "http://api.example.test/api")
    monkeypatch.setenv("RELOADING_API_TOKEN", "env-token")
    monkeypatch.setenv("RELOADING_API_TIMEOUT", "4.5")

    server = build_server_from_env()

    assert server.api_client.base_url == "http://api.example.test"
    assert server.api_client.token == "env-token"
    assert server.api_client.timeout == 4.5


def test_whoami_rejects_unexpected_arguments():
    server = make_server(token="session-token")

    response = call_tool(server, "whoami", {"path": "/api/items"})

    assert response["error"]["code"] == -32602
    assert "Unexpected argument" in response["error"]["message"]


def test_api_path_must_not_be_absolute_url():
    server = make_server()

    response = call_tool(server, "api_get", {"path": "https://example.com/api/items"})

    assert response["error"]["code"] == -32602
    assert "relative" in response["error"]["message"]


def test_api_errors_are_tool_execution_errors():
    def fake_request(method, url, **kwargs):
        return json_response(409, {"error": {"code": "active_lot_exists", "message": "Already active"}})

    server = make_server(fake_request=fake_request, token="session-token")

    response = call_tool(server, "api_post", {"path": "/api/inventory-lots", "body": {}})

    result = response["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["status_code"] == 409
    assert result["structuredContent"]["body"]["error"]["code"] == "active_lot_exists"


def test_protocol_validation_ping_and_unknown_method():
    server = make_server()

    invalid_request = server.handle_message("not a request")
    missing_method = server.handle_message({"jsonrpc": "2.0", "id": 1})
    initialized = server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    ping = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    unknown = server.handle_message({"jsonrpc": "2.0", "id": 3, "method": "unknown"})

    assert invalid_request["error"]["message"] == "Invalid JSON-RPC request"
    assert missing_method["error"]["message"] == "JSON-RPC method is required"
    assert initialized is None
    assert server.initialized is True
    assert ping["result"] == {}
    assert unknown["error"]["code"] == -32601


def test_tool_argument_validation_and_token_setup():
    server = make_server()

    assert server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": []})["error"]["code"] == -32602
    assert server.handle_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"arguments": {}},
    })["error"]["message"] == "tools/call params.name is required"
    assert server.handle_message({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "api_get", "arguments": "not-dict"},
    })["error"]["message"] == "tools/call params.arguments must be an object"
    assert call_tool(server, "missing_tool")["error"]["message"] == "Unknown tool: missing_tool"
    assert call_tool(server, "login", {"email": "", "password": "x"})["error"]["message"] == "email must be a non-empty string"
    assert call_tool(server, "login", {"email": "owner@example.com", "password": ""})["error"]["message"] == "password must be a non-empty string"
    assert call_tool(server, "set_auth_token", {"token": ""})["error"]["message"] == "token must be a non-empty string"
    assert call_tool(server, "api_get", {"path": ""})["error"]["message"] == "path must be a non-empty string"
    assert call_tool(server, "api_get", {"path": "/api/items", "query": []})["error"]["message"] == "query must be a JSON object"

    result = call_tool(server, "set_auth_token", {"token": " bearer-token "})["result"]
    assert result["structuredContent"]["authenticated"] is True
    assert server.api_client.token == "bearer-token"


def test_login_logout_and_whoami_edge_cases():
    invalid_json_client = ReloadingApiClient(
        "http://api.example.test",
        session=SimpleNamespace(request=lambda *_args, **_kwargs: raw_response(200, b"not-json", "application/json")),
    )
    with pytest.raises(RuntimeError, match="not valid JSON"):
        invalid_json_client.login("owner@example.com", "password")

    missing_token_client = ReloadingApiClient(
        "http://api.example.test",
        session=SimpleNamespace(request=lambda *_args, **_kwargs: json_response(200, {"user": {"id": 1}})),
    )
    with pytest.raises(RuntimeError, match="bearer token"):
        missing_token_client.login("owner@example.com", "password")

    failed_login = make_server(
        fake_request=lambda *_args, **_kwargs: json_response(403, {"error": {"message": "No"}})
    )
    assert call_tool(failed_login, "login", {"email": "owner@example.com", "password": "bad"})["result"]["isError"] is True

    no_token_logout = make_server()
    assert call_tool(no_token_logout, "logout")["result"]["structuredContent"]["status"] == "no_token"

    logout_server = make_server(
        fake_request=lambda *_args, **_kwargs: json_response(500, {"error": {"message": "logout failed"}}),
        token="token",
    )
    logout = call_tool(logout_server, "logout")["result"]
    assert logout["isError"] is True
    assert logout_server.api_client.token is None

    whoami = make_server(
        fake_request=lambda *_args, **_kwargs: json_response(401, {"error": {"message": "unauthorized"}}),
        token="token",
    )
    assert call_tool(whoami, "whoami")["result"]["isError"] is True


def test_tool_http_response_content_types_and_request_errors():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/api/report.csv"):
            return raw_response(200, b"id,name\n", "text/csv")
        if url.endswith("/api/qr/batch/1"):
            return raw_response(200, b"png", "image/png")
        if url.endswith("/api/items/7"):
            return json_response(204, {})
        if url.endswith("/api/items"):
            return json_response(201, {"token": "secret", "items": [{"password": "hidden"}]})
        return json_response(404, {"error": {"message": "missing"}})

    server = make_server(fake_request=fake_request, token="token")

    text_result = call_tool(server, "api_get", {"path": "/api/report.csv"})["result"]["structuredContent"]
    image_result = call_tool(server, "api_get", {"path": "/api/qr/batch/1"})["result"]
    post_result = call_tool(server, "api_post", {"path": "/api/items", "body": {"name": "H110"}})["result"]
    delete_result = call_tool(server, "api_delete", {"path": "/api/items/7"})["result"]["structuredContent"]
    missing_result = call_tool(server, "api_get", {"path": "/api/missing"})["result"]

    assert text_result["body"] == "id,name\n"
    assert image_result["content"][0]["type"] == "image"
    assert post_result["structuredContent"]["body"]["token"] == "[redacted]"
    assert post_result["structuredContent"]["body"]["items"][0]["password"] == "[redacted]"
    assert delete_result["status_code"] == 204
    assert missing_result["isError"] is True
    assert calls[2]["json"] == {"name": "H110"}
    assert calls[3]["method"] == "DELETE"

    invalid_json = response_to_structured(raw_response(200, b"not-json", "application/json"))
    binary = response_to_structured(raw_response(200, b"pdf", "application/pdf"))
    assert invalid_json["body"] == "not-json"
    assert binary["body"] == {"base64": "cGRm", "size": 3}

    unavailable = make_server(
        fake_request=lambda *_args, **_kwargs: (_ for _ in ()).throw(requests.RequestException("down")),
        token="token",
    )
    result = call_tool(unavailable, "api_get", {"path": "/api/items"})["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"] == "api_unavailable"


def test_stdio_writes_newline_delimited_json_rpc_messages():
    server = make_server()
    input_messages = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        "",
    ])
    input_stream = StringIO(input_messages)
    output_lines = []
    output_stream = SimpleNamespace(
        write=lambda value: output_lines.append(value),
        flush=lambda: None,
    )

    run_stdio(server, input_stream=input_stream, output_stream=output_stream)

    responses = [json.loads(line) for line in output_lines]
    assert [response["id"] for response in responses] == [1, 2]
    assert server.initialized is True


def test_stdio_reports_parse_errors():
    server = make_server()
    output_lines = []
    output_stream = SimpleNamespace(
        write=lambda value: output_lines.append(value),
        flush=lambda: None,
    )

    run_stdio(server, StringIO("{bad-json\n"), output_stream)

    response = json.loads(output_lines[0])
    assert response["error"]["code"] == -32700
    assert "Parse error" in response["error"]["message"]
