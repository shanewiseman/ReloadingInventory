from __future__ import annotations

import json
import runpy
from io import StringIO
from types import SimpleNamespace

import pytest
import requests
from requests import Response

import reloading_mcp.server as server_module
from reloading_mcp.server import (
    McpServer,
    ReloadingApiClient,
    ToolInputError,
    WorkflowStepError,
    array_schema,
    batch_create_body,
    batch_plan,
    build_server_from_env,
    component_api_payload,
    jsonrpc_error,
    normalize_api_path,
    recipe_plan,
    require_object,
    require_body_identifier,
    require_body_object,
    response_to_structured,
    run_stdio,
    storage_plan,
    tool_result,
    validate_batch_payload,
    validate_recipe_components,
    validate_recipe_payload,
    validate_source_materials,
    validate_storage_payload,
    workflow_error,
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


def approved_payload(server, tool_name, payload):
    preview = call_tool(server, tool_name, payload)["result"]["structuredContent"]
    return {**payload, "approved": True, "approval_digest": preview["approval_digest"]}


def recipe_workflow_payload():
    return {
        "recipe": {
            "title": "357 Magnum 158 JHP H110",
            "cartridge": ".357 Magnum",
            "acknowledge_responsibility": True,
        },
        "components": [
            {"role": "BULLET", "item_id": 1, "quantity": 1, "unit": "count"},
            {"role": "POWDER", "item_id": 2, "quantity": "15.0", "unit": "grains"},
            {"role": "PRIMER", "item_id": 3, "quantity": 1, "unit": "count"},
            {"role": "CASE", "item_id": 4, "quantity": 1, "unit": "count"},
        ],
        "source_materials": [
            {"kind": "MANUAL", "citation": "Published test manual", "page": "42"},
        ],
    }


def combined_workflow_payload():
    payload = recipe_workflow_payload()
    payload["batch"] = {
        "iterations": 10,
        "allocations": [
            {"component_id": 10, "lot_id": 100, "quantity": 10},
            {"component_id": 11, "lot_id": 101, "quantity": 150},
            {"component_id": 12, "lot_id": 102, "quantity": 10},
            {"component_id": 13, "lot_id": 103, "quantity": 10},
        ],
        "acknowledge_non_approved": True,
    }
    return payload


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
    assert {
        "create_recipe_workflow",
        "create_batch_workflow",
        "assign_batch_to_container_workflow",
        "create_recipe_batch_storage_workflow",
        "transition_recipe_workflow",
        "transition_batch_workflow",
        "print_batch_event",
    } <= names


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


def test_api_routes_tool_reports_metadata_and_auth_state():
    server = make_server(token="session-token")

    result = call_tool(server, "api_routes")["result"]["structuredContent"]

    assert result["authenticated"] is True
    assert result["base_url"] == "http://api.example.test"
    assert any(route["path"] == "/api/items" and route["auth"] is True for route in result["routes"])
    assert "Use login first" in result["notes"][0]


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


def test_api_put_patch_and_extra_body_validation():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return json_response(200, {"ok": True})

    server = make_server(fake_request=fake_request, token="session-token")

    patch = call_tool(server, "api_patch", {"path": "/api/items/7", "body": {"name": "Updated"}})
    put = call_tool(server, "api_put", {"path": "/api/settings/pos-printing", "body": {"enabled": True}})
    get_with_body = call_tool(server, "api_get", {"path": "/api/items", "body": {}})

    assert patch["result"]["structuredContent"]["body"] == {"ok": True}
    assert put["result"]["structuredContent"]["body"] == {"ok": True}
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["json"] == {"name": "Updated"}
    assert calls[1]["method"] == "PUT"
    assert calls[1]["json"] == {"enabled": True}
    assert get_with_body["error"]["code"] == -32602
    assert "Unexpected argument" in get_with_body["error"]["message"]


def test_print_batch_event_calls_explicit_api_route():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return json_response(200, {
            "status": "printed",
            "event": "batch_created",
            "batch": {"id": "batch-1"},
        })

    server = make_server(fake_request=fake_request, token="session-token")

    response = call_tool(server, "print_batch_event", {"batch_id": "batch-1", "event": "batch-created"})

    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["status"] == "printed"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "http://api.example.test/api/batches/batch-1/pos-print"
    assert calls[0]["json"] == {"event": "batch_created"}


def test_create_recipe_workflow_requires_approval_before_api_calls():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return json_response(500, {"error": {"message": "should not be called"}})

    server = make_server(fake_request=fake_request, token="session-token")

    response = call_tool(server, "create_recipe_workflow", recipe_workflow_payload())

    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["status"] == "approval_required"
    assert result["structuredContent"]["approval_digest"]
    assert result["structuredContent"]["planned_operations"][0]["operation"] == "create_recipe"
    assert calls == []


def test_create_recipe_workflow_runs_approved_transition_sequence():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if method == "POST" and url.endswith("/api/recipes"):
            return json_response(201, {"recipe": {"id": "recipe-1", "state": "UNDER DEVELOPMENT"}})
        if method == "POST" and "/api/recipes/recipe-1/components" in url:
            return json_response(201, {"component": {"id": len(calls)}})
        if method == "POST" and "/api/recipes/recipe-1/sources" in url:
            return json_response(201, {"source": {"id": 1}})
        if method == "POST" and url.endswith("/api/recipes/recipe-1/transition"):
            return json_response(200, {"recipe": {"id": "recipe-1", "state": kwargs["json"]["state"]}})
        return json_response(404, {"error": {"message": "unexpected"}})

    server = make_server(fake_request=fake_request, token="session-token")
    payload = recipe_workflow_payload()
    payload["transition_to"] = "APPROVED"
    payload = approved_payload(server, "create_recipe_workflow", payload)

    response = call_tool(server, "create_recipe_workflow", payload)

    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["status"] == "created"
    assert [step["state"] for step in result["structuredContent"]["steps"] if step["step"] == "transition_recipe"] == [
        "UNDER TEST",
        "APPROVED",
    ]


def test_create_recipe_workflow_reports_step_failure_without_creating_more_records():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if method == "POST" and url.endswith("/api/recipes"):
            return json_response(201, {"recipe": {"id": "recipe-1", "state": "UNDER DEVELOPMENT"}})
        if method == "POST" and "/api/recipes/recipe-1/components" in url:
            return json_response(409, {"error": {"code": "component_rejected", "message": "bad component"}})
        return json_response(404, {"error": {"message": "unexpected"}})

    server = make_server(fake_request=fake_request, token="session-token")
    payload = approved_payload(server, "create_recipe_workflow", recipe_workflow_payload())

    response = call_tool(server, "create_recipe_workflow", payload)

    result = response["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["status"] == "failed"
    assert result["structuredContent"]["failed_step"] == "add_recipe_component"
    assert not any(call["method"] == "DELETE" for call in calls)


def test_creation_approval_rejects_mismatched_digest():
    server = make_server(token="session-token")
    payload = {**recipe_workflow_payload(), "approved": True, "approval_digest": "not-the-preview-digest"}

    response = call_tool(server, "create_recipe_workflow", payload)

    assert response["error"]["code"] == -32602
    assert "approval_digest" in response["error"]["message"]


def test_create_batch_workflow_runs_approved_transition_and_performance_steps():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if method == "POST" and url.endswith("/api/batches"):
            return json_response(201, {"batch": {"id": "batch-1", "state": "UNDER PRODUCTION"}})
        if method == "PUT" and url.endswith("/api/batches/batch-1/qa-measurements"):
            return json_response(200, {"batch": {"id": "batch-1", "qa": "saved"}})
        if method == "POST" and url.endswith("/api/batches/batch-1/transition"):
            return json_response(200, {"batch": {"id": "batch-1", "state": kwargs["json"]["state"]}})
        if method == "PUT" and url.endswith("/api/batches/batch-1/performance"):
            return json_response(200, {"performance": {"id": "performance-1"}})
        if method == "GET" and url.endswith("/api/batches/batch-1"):
            return json_response(200, {"batch": {"id": "batch-1", "state": "PRODUCED"}})
        return json_response(404, {"error": {"message": "unexpected"}})

    server = make_server(fake_request=fake_request, token="session-token")
    payload = {
        "recipe_id": "recipe-1",
        "iterations": 5,
        "allocations": [{"component_id": 1, "lot_id": 2, "quantity": 5}],
        "transition_to": "PRODUCED",
        "qa_measurements": [{"sample_number": 1}],
        "qa_override": True,
        "performance_record": {"shot_count": 5},
    }
    payload = approved_payload(server, "create_batch_workflow", payload)

    response = call_tool(server, "create_batch_workflow", payload)

    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["status"] == "created"
    assert [step["step"] for step in result["structuredContent"]["steps"]] == [
        "create_batch",
        "save_batch_qa_measurements",
        "transition_batch",
        "save_performance_record",
    ]


def test_assign_batch_to_container_workflow_runs_approved_existing_container_assignment():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if method == "POST" and url.endswith("/api/containers/7/assignments"):
            return json_response(201, {"container": {"id": 7, "identifier": "BOX-7"}})
        return json_response(404, {"error": {"message": "unexpected"}})

    server = make_server(fake_request=fake_request, token="session-token")
    payload = approved_payload(server, "assign_batch_to_container_workflow", {
        "batch_id": "batch-1",
        "quantity": 5,
        "container_id": 7,
        "acknowledge_mixed_batch": True,
    })

    response = call_tool(server, "assign_batch_to_container_workflow", payload)

    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["status"] == "assigned"
    assert calls[0]["json"] == {"batch_id": "batch-1", "quantity": 5, "acknowledge_mixed_batch": True}


def test_combined_workflow_success_assigns_storage_and_finalizes_approved_recipe():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if method == "POST" and url.endswith("/api/recipes"):
            return json_response(201, {"recipe": {"id": "recipe-1", "state": "UNDER DEVELOPMENT"}})
        if method == "POST" and "/api/recipes/recipe-1/components" in url:
            return json_response(201, {"component": {"id": len(calls)}})
        if method == "POST" and "/api/recipes/recipe-1/sources" in url:
            return json_response(201, {"source": {"id": 1}})
        if method == "POST" and url.endswith("/api/recipes/recipe-1/transition"):
            return json_response(200, {"recipe": {"id": "recipe-1", "state": kwargs["json"]["state"]}})
        if method == "POST" and url.endswith("/api/batches"):
            return json_response(201, {"batch": {"id": "batch-1", "state": "UNDER PRODUCTION"}})
        if method == "GET" and url.endswith("/api/batches/batch-1"):
            return json_response(200, {"batch": {"id": "batch-1", "state": "UNDER PRODUCTION"}})
        if method == "POST" and url.endswith("/api/containers/7/assignments"):
            return json_response(201, {"container": {"id": 7, "identifier": "BOX-7"}})
        return json_response(404, {"error": {"message": "unexpected"}})

    server = make_server(fake_request=fake_request, token="session-token")
    payload = combined_workflow_payload()
    payload["transition_to"] = "APPROVED"
    payload["storage"] = {"quantity": 10, "container_id": 7}
    payload = approved_payload(server, "create_recipe_batch_storage_workflow", payload)

    response = call_tool(server, "create_recipe_batch_storage_workflow", payload)

    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["status"] == "created"
    assert result["structuredContent"]["storage"]["status"] == "assigned"
    assert [step["state"] for step in result["structuredContent"]["steps"] if step["step"] == "transition_recipe"] == [
        "UNDER TEST",
        "APPROVED",
    ]


def test_workflow_error_paths_and_rollback_helpers_cover_remaining_branches():
    batch_server = make_server(
        fake_request=lambda *_args, **_kwargs: json_response(409, {"error": {"message": "batch rejected"}}),
        token="session-token",
    )
    batch_payload = approved_payload(batch_server, "create_batch_workflow", {
        "recipe_id": "recipe-1",
        "iterations": 5,
        "allocations": [{"component_id": 1, "lot_id": 2, "quantity": 5}],
    })
    batch_error = call_tool(batch_server, "create_batch_workflow", batch_payload)["result"]["structuredContent"]
    assert batch_error["status"] == "failed"
    assert batch_error["failed_step"] == "create_batch"

    storage_server = make_server(
        fake_request=lambda *_args, **_kwargs: json_response(409, {"error": {"message": "container full"}}),
        token="session-token",
    )
    storage_payload = approved_payload(storage_server, "assign_batch_to_container_workflow", {
        "batch_id": "batch-1",
        "quantity": 5,
        "container_id": 7,
    })
    storage_error = call_tool(storage_server, "assign_batch_to_container_workflow", storage_payload)["result"]["structuredContent"]
    assert storage_error["status"] == "storage_not_satisfied"
    assert storage_error["failed_step"] == "assign_container"

    recipe_transition_server = make_server(
        fake_request=lambda *_args, **_kwargs: json_response(409, {"error": {"message": "missing source"}}),
        token="session-token",
    )
    recipe_error = call_tool(recipe_transition_server, "transition_recipe_workflow", {
        "recipe_id": "recipe-1",
        "state": "APPROVED",
    })["result"]["structuredContent"]
    assert recipe_error["status"] == "failed"
    assert recipe_error["failed_step"] == "transition_recipe"

    batch_transition_server = make_server(
        fake_request=lambda *_args, **_kwargs: json_response(409, {"error": {"message": "qa incomplete"}}),
        token="session-token",
    )
    batch_transition_error = call_tool(batch_transition_server, "transition_batch_workflow", {
        "batch_id": "batch-1",
        "state": "PRODUCED",
    })["result"]["structuredContent"]
    assert batch_transition_error["status"] == "failed"
    assert batch_transition_error["failed_step"] == "transition_batch"

    rollback_server = make_server(
        fake_request=lambda *_args, **_kwargs: json_response(500, {"error": {"message": "delete failed"}}),
        token="session-token",
    )
    assert rollback_server.rollback_recipe(None) is None
    assert rollback_server.rollback_recipe("recipe-1")["status"] == "failed"


def test_transition_workflows_and_print_event_error_paths():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if method == "POST" and url.endswith("/api/recipes/recipe-1/transition"):
            return json_response(200, {"recipe": {"id": "recipe-1", "state": kwargs["json"]["state"]}})
        if method == "PUT" and url.endswith("/api/batches/batch-1/qa-measurements"):
            return json_response(200, {"batch": {"id": "batch-1"}})
        if method == "POST" and url.endswith("/api/batches/batch-1/transition"):
            return json_response(200, {"batch": {"id": "batch-1", "state": kwargs["json"]["state"]}})
        if method == "POST" and url.endswith("/api/batches/batch-1/pos-print"):
            return json_response(502, {"error": {"message": "printer unavailable"}})
        return json_response(404, {"error": {"message": "unexpected"}})

    server = make_server(fake_request=fake_request, token="session-token")

    retired = call_tool(server, "transition_recipe_workflow", {"recipe_id": "recipe-1", "state": "RETIRED"})
    missing_state = call_tool(server, "transition_batch_workflow", {"batch_id": "batch-1"})
    recipe = call_tool(server, "transition_recipe_workflow", {
        "recipe_id": "recipe-1",
        "state": "UNDER TEST",
        "acknowledge_missing_source": True,
    })["result"]["structuredContent"]
    batch = call_tool(server, "transition_batch_workflow", {
        "batch_id": "batch-1",
        "state": "PRODUCED",
        "qa_measurements": [{"sample_number": 1}],
        "qa_override": True,
    })["result"]["structuredContent"]
    invalid_event = call_tool(server, "print_batch_event", {"batch_id": "batch-1", "event": "label"})
    failed_print = call_tool(server, "print_batch_event", {"batch_id": "batch-1", "event": "batch-produced"})

    assert retired["error"]["message"] == "Recipe retirement remains a manual process"
    assert missing_state["error"]["message"] == "state must be a non-empty string"
    assert recipe["status"] == "transitioned"
    assert batch["status"] == "transitioned"
    assert invalid_event["error"]["message"] == "event must be batch_created or batch_produced"
    assert failed_print["result"]["isError"] is True
    assert failed_print["result"]["structuredContent"]["failed_step"] == "print_batch_event"
    transition_recipe_call = next(call for call in calls if call["url"].endswith("/api/recipes/recipe-1/transition"))
    assert transition_recipe_call["json"]["acknowledge_missing_source"] is True


def test_combined_workflow_rolls_back_recipe_when_batch_creation_fails():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if method == "POST" and url.endswith("/api/recipes"):
            return json_response(201, {"recipe": {"id": "recipe-1", "state": "UNDER DEVELOPMENT"}})
        if method == "POST" and "/api/recipes/recipe-1/components" in url:
            return json_response(201, {"component": {"id": len(calls)}})
        if method == "POST" and "/api/recipes/recipe-1/sources" in url:
            return json_response(201, {"source": {"id": 1}})
        if method == "GET" and url.endswith("/api/recipes/recipe-1"):
            return json_response(200, {"recipe": {"id": "recipe-1", "state": "UNDER DEVELOPMENT"}})
        if method == "POST" and url.endswith("/api/batches"):
            return json_response(409, {"error": {"code": "insufficient_inventory", "message": "short"}})
        if method == "DELETE" and url.endswith("/api/recipes/recipe-1"):
            return json_response(204, {})
        return json_response(404, {"error": {"message": "unexpected"}})

    server = make_server(fake_request=fake_request, token="session-token")
    payload = combined_workflow_payload()
    preview = call_tool(server, "create_recipe_batch_storage_workflow", payload)["result"]["structuredContent"]
    payload = {**payload, "approved": True, "approval_digest": preview["approval_digest"]}

    response = call_tool(server, "create_recipe_batch_storage_workflow", payload)

    result = response["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["status"] == "failed"
    assert result["structuredContent"]["failed_step"] == "create_batch"
    assert result["structuredContent"]["rollback"]["status"] == "deleted"
    assert any(call["method"] == "DELETE" and call["url"].endswith("/api/recipes/recipe-1") for call in calls)


def test_combined_workflow_reports_storage_not_satisfied_without_deleting_batch_or_recipe():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if method == "POST" and url.endswith("/api/recipes"):
            return json_response(201, {"recipe": {"id": "recipe-1", "state": "UNDER DEVELOPMENT"}})
        if method == "POST" and "/api/recipes/recipe-1/components" in url:
            return json_response(201, {"component": {"id": len(calls)}})
        if method == "POST" and "/api/recipes/recipe-1/sources" in url:
            return json_response(201, {"source": {"id": 1}})
        if method == "GET" and url.endswith("/api/recipes/recipe-1"):
            return json_response(200, {"recipe": {"id": "recipe-1", "state": "UNDER DEVELOPMENT"}})
        if method == "POST" and url.endswith("/api/batches"):
            return json_response(201, {"batch": {"id": "batch-1", "state": "UNDER PRODUCTION"}})
        if method == "GET" and url.endswith("/api/batches/batch-1"):
            return json_response(200, {"batch": {"id": "batch-1", "state": "UNDER PRODUCTION"}})
        if method == "POST" and url.endswith("/api/containers"):
            return json_response(201, {"container": {"id": 9, "identifier": "CAN-1"}})
        if method == "POST" and url.endswith("/api/containers/9/assignments"):
            return json_response(409, {"error": {"code": "invalid_batch_state", "message": "not produced"}})
        return json_response(404, {"error": {"message": "unexpected"}})

    server = make_server(fake_request=fake_request, token="session-token")
    payload = combined_workflow_payload()
    payload["storage"] = {
        "quantity": 10,
        "create_container": {"identifier": "CAN-1", "name": "Can 1", "cartridge_limit": 10},
    }
    preview = call_tool(server, "create_recipe_batch_storage_workflow", payload)["result"]["structuredContent"]
    payload = {**payload, "approved": True, "approval_digest": preview["approval_digest"]}

    response = call_tool(server, "create_recipe_batch_storage_workflow", payload)

    result = response["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["status"] == "storage_not_satisfied"
    assert result["structuredContent"]["created"] == {"recipe_id": "recipe-1", "batch_id": "batch-1"}
    assert not any(call["method"] == "DELETE" for call in calls)


def test_protocol_validation_ping_and_unknown_method():
    server = make_server()

    invalid_request = server.handle_message("not a request")
    missing_method = server.handle_message({"jsonrpc": "2.0", "id": 1})
    initialized = server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    ignored_notification = server.handle_message({"jsonrpc": "2.0", "method": "notifications/cancelled"})
    ping = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    unknown = server.handle_message({"jsonrpc": "2.0", "id": 3, "method": "unknown"})

    assert invalid_request["error"]["message"] == "Invalid JSON-RPC request"
    assert missing_method["error"]["message"] == "JSON-RPC method is required"
    assert initialized is None
    assert ignored_notification is None
    assert server.initialized is True
    assert ping["result"] == {}
    assert unknown["error"]["code"] == -32601


def test_tool_argument_validation_and_token_setup():
    server = make_server()

    assert server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": [1]})["error"]["code"] == -32602
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


def test_mcp_validation_helpers_cover_malformed_workflows():
    with pytest.raises(ToolInputError, match="recipe must be a JSON object"):
        require_object({"recipe": "not an object"}, "recipe")

    with pytest.raises(ToolInputError, match="recipe.cartridge"):
        validate_recipe_payload({"title": "No cartridge"})

    with pytest.raises(ToolInputError, match="must include BULLET"):
        validate_recipe_components([])
    with pytest.raises(ToolInputError, match=r"components\[1\] must be a JSON object"):
        validate_recipe_components(["not an object"])
    with pytest.raises(ToolInputError, match=r"components\[1\]\.role is required"):
        validate_recipe_components([{"item_id": 1, "quantity": 1, "unit": "count"}])
    with pytest.raises(ToolInputError, match=r"components\[1\]\.quantity is required"):
        validate_recipe_components([{"role": "BULLET", "item_id": 1, "quantity": "", "unit": "count"}])
    with pytest.raises(ToolInputError, match="explicit roles"):
        validate_recipe_components([{"role": "BULLET", "item_id": 1, "quantity": 1, "unit": "count"}])

    with pytest.raises(ToolInputError, match="at least one source"):
        validate_source_materials([])
    with pytest.raises(ToolInputError, match=r"source_materials\[1\] must be a JSON object"):
        validate_source_materials(["not an object"])
    with pytest.raises(ToolInputError, match=r"source_materials\[1\]\.kind is required"):
        validate_source_materials([{"citation": "manual"}])
    with pytest.raises(ToolInputError, match="must include citation"):
        validate_source_materials([{"kind": "MANUAL"}])

    with pytest.raises(ToolInputError, match="recipe_id"):
        validate_batch_payload({"iterations": 1, "allocations": []})
    with pytest.raises(ToolInputError, match="iterations is required"):
        validate_batch_payload({"recipe_id": "recipe-1", "allocations": []})
    with pytest.raises(ToolInputError, match="whole number"):
        validate_batch_payload({"recipe_id": "recipe-1", "iterations": "ten", "allocations": []})
    with pytest.raises(ToolInputError, match="positive"):
        validate_batch_payload({"recipe_id": "recipe-1", "iterations": 0, "allocations": []})
    with pytest.raises(ToolInputError, match="at least one explicit lot allocation"):
        validate_batch_payload({"recipe_id": "recipe-1", "iterations": 1, "allocations": []})
    with pytest.raises(ToolInputError, match=r"allocations\[1\] must be a JSON object"):
        validate_batch_payload({"recipe_id": "recipe-1", "iterations": 1, "allocations": ["lot"]})
    with pytest.raises(ToolInputError, match=r"allocations\[1\]\.lot_id is required"):
        validate_batch_payload({"recipe_id": "recipe-1", "iterations": 1, "allocations": [{"component_id": 1, "quantity": 1}]})
    with pytest.raises(ToolInputError, match="qa_measurements must be a list"):
        validate_batch_payload({
            "recipe_id": "recipe-1",
            "iterations": 1,
            "allocations": [{"component_id": 1, "lot_id": 2, "quantity": 1}],
            "qa_measurements": "bad",
        })
    with pytest.raises(ToolInputError, match="performance_record requires"):
        validate_batch_payload({
            "recipe_id": "recipe-1",
            "iterations": 1,
            "allocations": [{"component_id": 1, "lot_id": 2, "quantity": 1}],
            "performance_record": {"shot_count": 5},
        })
    with pytest.raises(ToolInputError, match="performance_record must be a JSON object"):
        validate_batch_payload({
            "recipe_id": "recipe-1",
            "iterations": 1,
            "allocations": [{"component_id": 1, "lot_id": 2, "quantity": 1}],
            "transition_to": "PRODUCED",
            "performance_record": "bad",
        })
    with pytest.raises(ToolInputError, match="transition_to must be a string"):
        validate_batch_payload({
            "recipe_id": "recipe-1",
            "iterations": 1,
            "allocations": [{"component_id": 1, "lot_id": 2, "quantity": 1}],
            "transition_to": 123,
            "performance_record": {"shot_count": 5},
        })


def test_mcp_valid_workflow_helpers_build_api_payloads_and_plans():
    components = validate_recipe_components(recipe_workflow_payload()["components"])
    sources = validate_source_materials(recipe_workflow_payload()["source_materials"])
    recipe_payload = validate_recipe_payload(recipe_workflow_payload()["recipe"])
    batch_payload = validate_batch_payload({
        "recipe_id": "recipe-1",
        "iterations": "5",
        "allocations": [{"component_id": 1, "lot_id": 2, "quantity": 5}],
        "characteristics": "traceable test",
        "notes": "MCP helper test",
        "acknowledge_non_approved": True,
        "transition_to": "PRODUCED",
        "qa_measurements": [{"sample_number": 1}],
        "qa_override": True,
        "performance_record": {"shot_count": 5},
    })
    storage_payload = validate_storage_payload({
        "batch_id": "batch-1",
        "quantity": "5",
        "create_container": {"identifier": "BOX-1", "name": "Box 1", "cartridge_limit": 50},
        "acknowledge_mixed_batch": True,
    })

    assert component_api_payload(components[0]) == {"item_id": 1, "quantity": 1, "unit": "count"}
    assert batch_payload["iterations"] == 5
    assert batch_create_body(batch_payload)["acknowledge_non_approved"] is True
    assert recipe_plan(recipe_payload, components, sources, "UNDER TEST")[-1] == {
        "operation": "transition_recipe",
        "state": "UNDER TEST",
    }
    assert [step["operation"] for step in batch_plan(batch_payload)] == [
        "create_batch",
        "save_batch_qa_measurements",
        "transition_batch",
        "save_performance_record",
    ]
    assert [step["operation"] for step in storage_plan(storage_payload)] == [
        "create_container",
        "assign_batch_to_container",
    ]


def test_mcp_storage_and_response_helper_edges():
    assert array_schema("Rows")["description"] == "Rows"
    assert "description" not in array_schema()
    normalized = normalize_api_path("api/items?q=powder&empty=")
    assert normalized.path == "/api/items"
    assert normalized.query_pairs == [("q", "powder"), ("empty", "")]

    with pytest.raises(ToolInputError, match="parent-directory"):
        normalize_api_path("/api/../items")
    with pytest.raises(ToolInputError, match="/health"):
        normalize_api_path("/settings")
    with pytest.raises(ToolInputError, match="non-empty string"):
        normalize_api_path("")

    with pytest.raises(ToolInputError, match="quantity is required"):
        validate_storage_payload({"batch_id": "batch-1", "container_id": 1})
    with pytest.raises(ToolInputError, match="whole number"):
        validate_storage_payload({"batch_id": "batch-1", "quantity": "five", "container_id": 1})
    with pytest.raises(ToolInputError, match="positive"):
        validate_storage_payload({"batch_id": "batch-1", "quantity": 0, "container_id": 1})
    with pytest.raises(ToolInputError, match="exactly one"):
        validate_storage_payload({"batch_id": "batch-1", "quantity": 1})
    with pytest.raises(ToolInputError, match="create_container.name"):
        validate_storage_payload({
            "batch_id": "batch-1",
            "quantity": 1,
            "create_container": {"identifier": "BOX-1", "cartridge_limit": 50},
        })

    with pytest.raises(WorkflowStepError) as missing_object:
        require_body_object({"body": {}}, "recipe")
    assert missing_object.value.step == "parse_recipe"

    with pytest.raises(WorkflowStepError) as missing_identifier:
        require_body_identifier({"id": 7}, "recipe")
    assert missing_identifier.value.step == "parse_recipe_id"

    error = workflow_error(
        "failed",
        WorkflowStepError("create_batch", {"error": "insufficient_inventory"}),
        created={"recipe_id": "recipe-1"},
        rollback={"status": "deleted"},
        partial={"recipe": {"id": "recipe-1"}},
    )
    assert error["is_error"] is True
    assert error["created"] == {"recipe_id": "recipe-1"}
    assert error["rollback"] == {"status": "deleted"}
    assert error["partial"] == {"recipe": {"id": "recipe-1"}}
    assert jsonrpc_error(1, -32602, "bad params", data={"field": "path"})["error"]["data"] == {"field": "path"}

    empty_body = response_to_structured(raw_response(204, b"", "application/json"))
    pdf_result = tool_result(response_to_structured(raw_response(200, b"pdf", "application/pdf")))
    assert empty_body["body"] is None
    assert len(pdf_result["content"]) == 1


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

    whoami_success = make_server(
        fake_request=lambda *_args, **_kwargs: json_response(200, {"user": {"email": "owner@example.com"}}),
        token="token",
    )
    assert call_tool(whoami_success, "whoami")["result"]["structuredContent"]["body"]["user"]["email"] == "owner@example.com"


def test_tool_http_response_content_types_and_request_errors():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/api/report.csv"):
            return raw_response(200, b"id,name\n", "text/csv")
        if url.endswith("/api/qr/batch/1"):
            return raw_response(200, b"png", "image/png")
        if url.endswith("/api/document.pdf"):
            return raw_response(200, b"pdf", "application/pdf")
        if url.endswith("/api/items/7"):
            return json_response(204, {})
        if url.endswith("/api/items"):
            return json_response(201, {"token": "secret", "items": [{"password": "hidden"}]})
        return json_response(404, {"error": {"message": "missing"}})

    server = make_server(fake_request=fake_request, token="token")

    text_result = call_tool(server, "api_get", {"path": "/api/report.csv"})["result"]["structuredContent"]
    image_result = call_tool(server, "api_get", {"path": "/api/qr/batch/1"})["result"]
    pdf_result = call_tool(server, "api_get", {"path": "/api/document.pdf"})["result"]
    post_result = call_tool(server, "api_post", {"path": "/api/items", "body": {"name": "H110"}})["result"]
    delete_result = call_tool(server, "api_delete", {"path": "/api/items/7"})["result"]["structuredContent"]
    missing_result = call_tool(server, "api_get", {"path": "/api/missing"})["result"]

    assert text_result["body"] == "id,name\n"
    assert image_result["content"][0]["type"] == "image"
    assert pdf_result["structuredContent"]["body"]["base64"] == "cGRm"
    assert len(pdf_result["content"]) == 1
    assert post_result["structuredContent"]["body"]["token"] == "[redacted]"
    assert post_result["structuredContent"]["body"]["items"][0]["password"] == "[redacted]"
    assert delete_result["status_code"] == 204
    assert missing_result["isError"] is True
    assert calls[3]["json"] == {"name": "H110"}
    assert calls[4]["method"] == "DELETE"

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

    blank_output = []
    run_stdio(server, input_stream=StringIO("\n"), output_stream=SimpleNamespace(
        write=lambda value: blank_output.append(value),
        flush=lambda: None,
    ))
    assert blank_output == []


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


def test_mcp_server_main_and_module_entrypoint_delegate_to_stdio(monkeypatch):
    calls = []

    monkeypatch.setattr(server_module, "build_server_from_env", lambda: "server")
    monkeypatch.setattr(server_module, "run_stdio", lambda server: calls.append(server) or 7)

    assert server_module.main() == 7
    assert calls == ["server"]

    monkeypatch.setattr(server_module, "main", lambda: 5)

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("reloading_mcp.__main__", run_name="__main__")

    assert exit_info.value.code == 5
