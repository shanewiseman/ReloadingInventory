from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace

from requests import Response

from reloading_mcp.server import McpServer, ReloadingApiClient, build_server_from_env, run_stdio


def json_response(status_code, body):
    response = Response()
    response.status_code = status_code
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(body).encode()
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
