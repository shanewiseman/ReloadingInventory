from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, IO
from urllib.parse import parse_qsl, urlsplit

import requests

from . import __version__

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {PROTOCOL_VERSION, "2025-03-26", "2024-11-05"}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

SENSITIVE_RESPONSE_KEYS = {"password", "new_password", "password_hash", "token"}

SERVER_INSTRUCTIONS = (
    "Use login or set_auth_token before calling authenticated API routes. "
    "Use api_routes to inspect the storage API surface. The app stores user-supplied "
    "reloading traceability data; do not recommend powder charges, infer safe loads, "
    "or certify that a recipe is safe. Workflow creation tools require a prior preview "
    "and matching approval_digest before creating records."
)

CORE_RECIPE_ROLES = {"BULLET", "POWDER", "PRIMER", "CASE"}
APPROVAL_DIGEST_FIELDS = {"approved", "approval_digest"}


API_ROUTES: list[dict[str, Any]] = [
    {"method": "GET", "path": "/health", "auth": False, "summary": "Check service health."},
    {"method": "POST", "path": "/api/auth/register", "auth": False, "summary": "Create a local account."},
    {"method": "POST", "path": "/api/auth/login", "auth": False, "summary": "Create an API session. Prefer the login MCP tool."},
    {"method": "POST", "path": "/api/auth/reset", "auth": False, "summary": "Complete local password reset for eligible accounts."},
    {"method": "POST", "path": "/api/auth/logout", "auth": True, "summary": "Revoke the current API session."},
    {"method": "GET", "path": "/api/auth/me", "auth": True, "summary": "Inspect the current authenticated user."},
    {"method": "GET", "path": "/api/items", "auth": True, "summary": "List item definitions. Query: q, category, archived=true."},
    {"method": "POST", "path": "/api/items", "auth": True, "summary": "Create an item definition."},
    {"method": "GET", "path": "/api/items/{item_id}", "auth": True, "summary": "Get one item definition."},
    {"method": "PATCH", "path": "/api/items/{item_id}", "auth": True, "summary": "Update or archive an item definition."},
    {"method": "GET", "path": "/api/inventory-lots", "auth": True, "summary": "List inventory lots. Query: historical=true."},
    {"method": "POST", "path": "/api/inventory-lots", "auth": True, "summary": "Create an acquisition lot."},
    {"method": "PATCH", "path": "/api/inventory-lots/{lot_id}", "auth": True, "summary": "Update lot metadata or active status."},
    {"method": "POST", "path": "/api/inventory-lots/{lot_id}/adjustments", "auth": True, "summary": "Record an inventory quantity adjustment."},
    {"method": "GET", "path": "/api/inventory-lots/{lot_id}/adjustments", "auth": True, "summary": "List inventory adjustments for a lot."},
    {"method": "GET", "path": "/api/recipes", "auth": True, "summary": "List recipes. Query: state, archived=true."},
    {"method": "GET", "path": "/api/recipes/suggested-identity", "auth": True, "summary": "Generate a unique suggested recipe title."},
    {"method": "POST", "path": "/api/recipes", "auth": True, "summary": "Create a recipe shell."},
    {"method": "GET", "path": "/api/recipes/{recipe_id}", "auth": True, "summary": "Get a recipe with aggregate performance."},
    {"method": "PATCH", "path": "/api/recipes/{recipe_id}", "auth": True, "summary": "Update recipe metadata, visibility, or archival status."},
    {"method": "POST", "path": "/api/recipes/{recipe_id}/components", "auth": True, "summary": "Add an exact item component to a recipe."},
    {"method": "DELETE", "path": "/api/recipes/{recipe_id}/components/{component_id}", "auth": True, "summary": "Remove a recipe component before batching locks it."},
    {"method": "POST", "path": "/api/recipes/{recipe_id}/sources", "auth": True, "summary": "Attach source material to a recipe."},
    {"method": "POST", "path": "/api/recipes/{recipe_id}/transition", "auth": True, "summary": "Move a recipe through its lifecycle."},
    {"method": "POST", "path": "/api/acknowledgements", "auth": True, "summary": "Record an explicit user acknowledgement."},
    {"method": "GET", "path": "/api/public/recipes/{token}", "auth": False, "summary": "Read a public recipe view by share token."},
    {"method": "GET", "path": "/api/batches", "auth": True, "summary": "List batches. Query: state."},
    {"method": "POST", "path": "/api/batches", "auth": True, "summary": "Create a batch and reserve exact inventory allocations."},
    {"method": "GET", "path": "/api/batches/{batch_id}", "auth": True, "summary": "Get a batch, reservations, containers, and performance."},
    {"method": "POST", "path": "/api/batches/{batch_id}/transition", "auth": True, "summary": "Move a batch through production/cancellation lifecycle."},
    {"method": "POST", "path": "/api/batches/{batch_id}/production-losses", "auth": True, "summary": "Record production loss and reserve replacement inventory."},
    {"method": "POST", "path": "/api/batches/{batch_id}/returns", "auth": True, "summary": "Account for reserved or consumed inventory as returned/lost."},
    {"method": "GET", "path": "/api/containers", "auth": True, "summary": "List storage containers."},
    {"method": "POST", "path": "/api/containers", "auth": True, "summary": "Create a storage container."},
    {"method": "PATCH", "path": "/api/containers/{container_id}", "auth": True, "summary": "Update a container or transition its state."},
    {"method": "POST", "path": "/api/containers/{container_id}/assignments", "auth": True, "summary": "Assign produced cartridges to a container."},
    {"method": "GET", "path": "/api/batches/{batch_id}/performance", "auth": True, "summary": "Get one batch performance record."},
    {"method": "PUT", "path": "/api/batches/{batch_id}/performance", "auth": True, "summary": "Create or update one batch performance record."},
    {"method": "GET", "path": "/api/dashboard", "auth": True, "summary": "Read dashboard metrics and recent activity."},
    {"method": "GET", "path": "/api/audit", "auth": True, "summary": "List audit history. Query: entity_type, entity_id, limit."},
    {"method": "GET", "path": "/api/qr/{entity_type}/{entity_id}", "auth": True, "summary": "Render a batch or recipe QR code PNG."},
    {"method": "GET", "path": "/api/export/{entity}", "auth": True, "summary": "Export tenant data. Query: format=json|csv."},
    {"method": "POST", "path": "/api/admin/backup", "auth": True, "summary": "Create a SQLite backup on the storage service."},
]


class ToolInputError(ValueError):
    """Raised when an MCP tool received invalid local arguments."""


class WorkflowStepError(RuntimeError):
    def __init__(self, step: str, structured: dict[str, Any]) -> None:
        super().__init__(step)
        self.step = step
        self.structured = structured


def object_schema(description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "additionalProperties": True}
    if description:
        schema["description"] = description
    return schema


def array_schema(description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array", "items": object_schema()}
    if description:
        schema["description"] = description
    return schema


approval_fields = {
    "approved": {
        "type": "boolean",
        "description": "Must be true only after the user approves the exact previewed workflow payload.",
    },
    "approval_digest": {
        "type": "string",
        "description": "Digest returned by the preview response for this exact workflow payload.",
    },
}


recipe_workflow_properties = {
    "recipe": object_schema(
        "Recipe fields to create. Requires title and cartridge; optional fields mirror POST /api/recipes."
    ),
    "components": array_schema(
        "Explicit exact components. Each object requires role, item_id, quantity, and unit. "
        "BULLET, POWDER, PRIMER, and CASE are all required; no components are inferred."
    ),
    "source_materials": array_schema(
        "Source material records to attach. At least one source is required. Each source must include kind "
        "and an explicit citation, url, file_name, stored_file_id, or notes."
    ),
    "transition_to": {
        "type": "string",
        "description": "Optional recipe target state: UNDER DEVELOPMENT, UNDER TEST, or APPROVED. RETIRED is intentionally not exposed.",
    },
    **approval_fields,
}


batch_workflow_properties = {
    "recipe_id": {"type": "string", "description": "Recipe identifier."},
    "iterations": {"type": "integer", "description": "Explicit number of cartridges in the batch."},
    "allocations": array_schema(
        "Explicit inventory allocations. Each object requires component_id, lot_id, and quantity."
    ),
    "characteristics": {"type": "string"},
    "notes": {"type": "string"},
    "acknowledge_non_approved": {
        "type": "boolean",
        "description": "Explicit acknowledgement required by the API when batching a non-approved recipe.",
    },
    "acknowledge_missing_source": {
        "type": "boolean",
        "description": "Explicit acknowledgement required by the API if source material is missing.",
    },
    "qa_measurements": array_schema(
        "Optional explicit QA samples before transitioning to PRODUCED."
    ),
    "qa_override": {
        "type": "boolean",
        "description": "Explicit audited QA override for transition to PRODUCED when QA samples are incomplete.",
    },
    "transition_to": {
        "type": "string",
        "description": "Optional batch target state. PRODUCED is supported for creation workflows.",
    },
    "performance_record": object_schema(
        "Optional measured performance data to record after the batch is produced. Approval-quality data requires shot_count, velocity_average, velocity_minimum, velocity_maximum, standard_deviation, extreme_spread, and raw_data."
    ),
    **approval_fields,
}


storage_workflow_properties = {
    "batch_id": {"type": "string", "description": "Produced batch identifier."},
    "quantity": {"type": "integer", "description": "Explicit cartridge count to assign."},
    "container_id": {"type": "integer", "description": "Existing container id. Mutually exclusive with create_container."},
    "create_container": object_schema(
        "Optional container to create before assignment. Requires identifier, name, and cartridge_limit."
    ),
    "acknowledge_mixed_batch": {
        "type": "boolean",
        "description": "Explicit acknowledgement if assigning into a container that already holds another batch.",
    },
    **approval_fields,
}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "login",
        "title": "Log In",
        "description": "Authenticate with the Reload Ledger storage API and keep the bearer token in this MCP session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Account email address."},
                "password": {"type": "string", "description": "Account password.", "format": "password"},
            },
            "required": ["email", "password"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "set_auth_token",
        "title": "Set Auth Token",
        "description": "Use an existing Reload Ledger bearer token for subsequent API calls.",
        "inputSchema": {
            "type": "object",
            "properties": {"token": {"type": "string", "description": "Bearer token returned by /api/auth/login."}},
            "required": ["token"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "logout",
        "title": "Log Out",
        "description": "Revoke the current API session and clear the token held by this MCP server.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "whoami",
        "title": "Current User",
        "description": "Return the authenticated API user for the token held by this MCP server.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "name": "api_routes",
        "title": "API Routes",
        "description": "Return a compact route guide for the Reload Ledger storage API.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "api_get",
        "title": "API GET",
        "description": "Call a Reload Ledger API GET route. Paths must be /health or under /api/.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "API path, for example /api/items or /api/recipes/{id}."},
                "query": object_schema("Optional query parameters."),
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "name": "api_post",
        "title": "API POST",
        "description": "Call a Reload Ledger API POST route with an optional JSON body.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "API path under /api/."},
                "body": object_schema("JSON request body."),
                "query": object_schema("Optional query parameters."),
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "api_patch",
        "title": "API PATCH",
        "description": "Call a Reload Ledger API PATCH route with an optional JSON body.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "API path under /api/."},
                "body": object_schema("JSON request body."),
                "query": object_schema("Optional query parameters."),
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "api_put",
        "title": "API PUT",
        "description": "Call a Reload Ledger API PUT route with an optional JSON body.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "API path under /api/."},
                "body": object_schema("JSON request body."),
                "query": object_schema("Optional query parameters."),
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "api_delete",
        "title": "API DELETE",
        "description": "Call a Reload Ledger API DELETE route.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "API path under /api/."},
                "query": object_schema("Optional query parameters."),
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "create_recipe_workflow",
        "title": "Create Recipe Workflow",
        "description": (
            "Preview or create a complete sourced recipe using explicit item components. "
            "Requires BULLET, POWDER, PRIMER, and CASE components and at least one source. "
            "No item, component, source, or recipe is created unless approved is true and approval_digest matches the preview."
        ),
        "inputSchema": {
            "type": "object",
            "properties": recipe_workflow_properties,
            "required": ["recipe", "components", "source_materials"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "create_batch_workflow",
        "title": "Create Batch Workflow",
        "description": (
            "Preview or create a batch from an existing recipe using explicit cartridge count and lot allocations. "
            "Can optionally save QA, transition to PRODUCED, and attach measured performance data. "
            "No batch or performance record is created unless approved is true and approval_digest matches the preview."
        ),
        "inputSchema": {
            "type": "object",
            "properties": batch_workflow_properties,
            "required": ["recipe_id", "iterations", "allocations"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "assign_batch_to_container_workflow",
        "title": "Assign Batch To Container Workflow",
        "description": (
            "Preview or assign an explicit quantity from a produced batch to an existing or newly-created container. "
            "Container creation and assignment are not attempted unless approved is true and approval_digest matches the preview."
        ),
        "inputSchema": {
            "type": "object",
            "properties": storage_workflow_properties,
            "required": ["batch_id", "quantity"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "create_recipe_batch_storage_workflow",
        "title": "Create Recipe, Batch, And Storage Workflow",
        "description": (
            "Preview or run a multi-step workflow that creates a sourced recipe, creates a batch, optionally records QA/performance, "
            "optionally transitions recipe/batch states, and optionally assigns cartridges to storage. "
            "If batch creation fails after recipe creation, the tool attempts to delete the recipe for audited rollback. "
            "If batch creation succeeds but storage cannot be satisfied, the recipe and batch remain and the result reports storage_not_satisfied."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **recipe_workflow_properties,
                "batch": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Batch creation payload: iterations, allocations, optional QA/performance/transition fields.",
                },
                "storage": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Optional storage assignment payload: quantity plus container_id or create_container.",
                },
            },
            "required": ["recipe", "components", "source_materials", "batch"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "transition_recipe_workflow",
        "title": "Transition Recipe Workflow",
        "description": (
            "Move a recipe through non-retirement lifecycle states using the storage API. "
            "Supports UNDER DEVELOPMENT, UNDER TEST, APPROVED, and NOT APPROVED. RETIRED remains manual."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "recipe_id": {"type": "string", "description": "Recipe identifier."},
                "state": {"type": "string", "description": "Target recipe state. RETIRED is rejected by this workflow."},
                "acknowledge_missing_source": {"type": "boolean"},
            },
            "required": ["recipe_id", "state"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "transition_batch_workflow",
        "title": "Transition Batch Workflow",
        "description": (
            "Move an existing batch through supported production lifecycle states using explicit QA data or explicit QA override when required."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "batch_id": {"type": "string", "description": "Batch identifier."},
                "state": {"type": "string", "description": "Target batch state."},
                "qa_measurements": array_schema("Optional explicit QA samples to save before transition."),
                "qa_override": {"type": "boolean"},
            },
            "required": ["batch_id", "state"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
]


@dataclass
class ApiPath:
    path: str
    query_pairs: list[tuple[str, str]]


class ReloadingApiClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 15,
        session: requests.Session | None = None,
    ) -> None:
        base_url = base_url.rstrip("/")
        if base_url.endswith("/api"):
            base_url = base_url[:-4]
        self.base_url = base_url
        self.token = token
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def authenticated(self) -> bool:
        return bool(self.token)

    def login(self, email: str, password: str) -> dict[str, Any]:
        if not isinstance(email, str) or not email.strip():
            raise ToolInputError("email must be a non-empty string")
        if not isinstance(password, str) or not password:
            raise ToolInputError("password must be a non-empty string")
        response = self.request(
            "POST",
            "/api/auth/login",
            body={"email": email, "password": password},
            include_auth=False,
        )
        if response.ok:
            try:
                body = response.json()
            except ValueError as exc:
                raise RuntimeError("Login response was not valid JSON") from exc
            token = body.get("token")
            if not isinstance(token, str) or not token:
                raise RuntimeError("Login response did not include a bearer token")
            self.token = token
            return {
                "authenticated": True,
                "base_url": self.base_url,
                "expires_at": body.get("expires_at"),
                "user": body.get("user"),
            }
        structured = response_to_structured(response)
        return structured

    def set_auth_token(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or not token.strip():
            raise ToolInputError("token must be a non-empty string")
        self.token = token.strip()
        return {"authenticated": True, "base_url": self.base_url}

    def logout(self) -> dict[str, Any]:
        if not self.token:
            return {"authenticated": False, "status": "no_token"}
        response = self.request("POST", "/api/auth/logout")
        structured = response_to_structured(response)
        self.token = None
        structured["authenticated"] = False
        return structured

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: Any | None = None,
        include_auth: bool = True,
    ) -> requests.Response:
        normalized = normalize_api_path(path)
        if query is not None and not isinstance(query, dict):
            raise ToolInputError("query must be a JSON object")
        params: list[tuple[str, Any]] = list(normalized.query_pairs)
        if query:
            params.extend((key, value) for key, value in query.items())
        headers = {"Accept": "application/json, text/csv, image/png;q=0.9, */*;q=0.5"}
        if include_auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return self.session.request(
            method.upper(),
            f"{self.base_url}{normalized.path}",
            headers=headers,
            params=params or None,
            json=body,
            timeout=self.timeout,
        )


class McpServer:
    def __init__(self, api_client: ReloadingApiClient) -> None:
        self.api_client = api_client
        self.initialized = False
        self.tool_handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "login": self.tool_login,
            "set_auth_token": self.tool_set_auth_token,
            "logout": self.tool_logout,
            "whoami": self.tool_whoami,
            "api_routes": self.tool_api_routes,
            "api_get": lambda args: self.tool_http("GET", require_path(args), args),
            "api_post": lambda args: self.tool_http("POST", require_path(args), args),
            "api_patch": lambda args: self.tool_http("PATCH", require_path(args), args),
            "api_put": lambda args: self.tool_http("PUT", require_path(args), args),
            "api_delete": lambda args: self.tool_http("DELETE", require_path(args), args),
            "create_recipe_workflow": self.tool_create_recipe_workflow,
            "create_batch_workflow": self.tool_create_batch_workflow,
            "assign_batch_to_container_workflow": self.tool_assign_batch_to_container_workflow,
            "create_recipe_batch_storage_workflow": self.tool_create_recipe_batch_storage_workflow,
            "transition_recipe_workflow": self.tool_transition_recipe_workflow,
            "transition_batch_workflow": self.tool_transition_batch_workflow,
        }

    def handle_message(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return jsonrpc_error(None, INVALID_REQUEST, "Invalid JSON-RPC request")
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return jsonrpc_error(request_id, INVALID_REQUEST, "JSON-RPC method is required")

        if request_id is None and method.startswith("notifications/"):
            if method == "notifications/initialized":
                self.initialized = True
            return None

        try:
            if method == "initialize":
                result = self.initialize(message.get("params") or {})
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self.call_tool(message.get("params") or {})
            else:
                return jsonrpc_error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
        except ToolInputError as exc:
            return jsonrpc_error(request_id, INVALID_PARAMS, str(exc))
        except Exception as exc:  # pragma: no cover - defensive protocol guard
            return jsonrpc_error(request_id, INTERNAL_ERROR, f"Internal server error: {exc}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        protocol_version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        return {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "reload-ledger-api",
                "title": "Reload Ledger API",
                "version": __version__,
            },
            "instructions": SERVER_INSTRUCTIONS,
        }

    def call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise ToolInputError("tools/call params must be an object")
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            raise ToolInputError("tools/call params.name is required")
        if not isinstance(arguments, dict):
            raise ToolInputError("tools/call params.arguments must be an object")
        handler = self.tool_handlers.get(name)
        if not handler:
            raise ToolInputError(f"Unknown tool: {name}")
        try:
            structured = handler(arguments)
        except requests.RequestException as exc:
            structured = {
                "error": "api_unavailable",
                "message": str(exc),
                "base_url": self.api_client.base_url,
            }
            return tool_result(structured, is_error=True)
        is_error = bool(structured.get("is_error"))
        structured.pop("is_error", None)
        return tool_result(structured, is_error=is_error)

    def tool_login(self, args: dict[str, Any]) -> dict[str, Any]:
        require_no_extra(args, {"email", "password"})
        result = self.api_client.login(args.get("email"), args.get("password"))
        if "status_code" in result and int(result["status_code"]) >= 400:
            result["is_error"] = True
        return result

    def tool_set_auth_token(self, args: dict[str, Any]) -> dict[str, Any]:
        require_no_extra(args, {"token"})
        return self.api_client.set_auth_token(args.get("token"))

    def tool_logout(self, args: dict[str, Any]) -> dict[str, Any]:
        require_no_extra(args, set())
        result = self.api_client.logout()
        if "status_code" in result and int(result["status_code"]) >= 400:
            result["is_error"] = True
        return result

    def tool_whoami(self, args: dict[str, Any]) -> dict[str, Any]:
        require_no_extra(args, set())
        response = self.api_client.request("GET", "/api/auth/me")
        structured = response_to_structured(response)
        if response.status_code >= 400:
            structured["is_error"] = True
        return structured

    def tool_api_routes(self, args: dict[str, Any]) -> dict[str, Any]:
        require_no_extra(args, set())
        return {
            "base_url": self.api_client.base_url,
            "authenticated": self.api_client.authenticated,
            "routes": API_ROUTES,
            "notes": [
                "Use login first for routes where auth is true.",
                "Generic API tools return status_code, content_type, headers, and body.",
                "Use acknowledgement booleans exactly where the API requires them; audited overrides are intentional.",
            ],
        }

    def tool_http(self, method: str, path: str, args: dict[str, Any]) -> dict[str, Any]:
        allowed = {"path", "query", "body"}
        if method in {"GET", "DELETE"}:
            allowed = {"path", "query"}
        require_no_extra(args, allowed)
        body = args.get("body") if method not in {"GET", "DELETE"} else None
        response = self.api_client.request(method, path, query=args.get("query"), body=body)
        structured = response_to_structured(response)
        if response.status_code >= 400:
            structured["is_error"] = True
        return structured

    def tool_create_recipe_workflow(self, args: dict[str, Any]) -> dict[str, Any]:
        require_no_extra(args, {"recipe", "components", "source_materials", "transition_to", "approved", "approval_digest"})
        recipe_payload = validate_recipe_payload(require_object(args, "recipe"))
        components = validate_recipe_components(require_list(args, "components"))
        sources = validate_source_materials(require_list(args, "source_materials"))
        transition_to = normalize_optional_state(args.get("transition_to"), default="UNDER DEVELOPMENT")
        planned = recipe_plan(recipe_payload, components, sources, transition_to)
        approval = self.creation_approval(args, planned)
        if approval:
            return approval

        recipe_id = None
        try:
            recipe_id, recipe, steps = self.run_recipe_creation(recipe_payload, components, sources, transition_to)
        except WorkflowStepError as exc:
            rollback = self.rollback_recipe(recipe_id) if recipe_id else None
            return workflow_error("failed", exc, rollback=rollback)
        return {"status": "created", "recipe": recipe, "steps": steps}

    def tool_create_batch_workflow(self, args: dict[str, Any]) -> dict[str, Any]:
        require_no_extra(args, set(batch_workflow_properties))
        batch_payload = validate_batch_payload(args)
        planned = batch_plan(batch_payload)
        approval = self.creation_approval(args, planned)
        if approval:
            return approval

        try:
            batch_id, batch, steps = self.run_batch_creation(batch_payload)
        except WorkflowStepError as exc:
            return workflow_error("failed", exc)
        return {"status": "created", "batch": batch, "steps": steps}

    def tool_assign_batch_to_container_workflow(self, args: dict[str, Any]) -> dict[str, Any]:
        require_no_extra(args, set(storage_workflow_properties))
        storage_payload = validate_storage_payload(args)
        planned = storage_plan(storage_payload)
        approval = self.creation_approval(args, planned)
        if approval:
            return approval

        try:
            container, steps = self.run_storage_assignment(storage_payload)
        except WorkflowStepError as exc:
            return workflow_error("storage_not_satisfied", exc)
        return {"status": "assigned", "container": container, "steps": steps}

    def tool_create_recipe_batch_storage_workflow(self, args: dict[str, Any]) -> dict[str, Any]:
        require_no_extra(args, {"recipe", "components", "source_materials", "transition_to", "batch", "storage", "approved", "approval_digest"})
        recipe_payload = validate_recipe_payload(require_object(args, "recipe"))
        components = validate_recipe_components(require_list(args, "components"))
        sources = validate_source_materials(require_list(args, "source_materials"))
        recipe_transition_to = normalize_optional_state(args.get("transition_to"), default="UNDER DEVELOPMENT")
        batch_payload = validate_batch_payload(require_object(args, "batch"), recipe_id_required=False)
        storage_payload = validate_storage_payload(require_object(args, "storage"), batch_id_required=False) if args.get("storage") is not None else None
        planned = recipe_plan(recipe_payload, components, sources, recipe_transition_to)
        planned.extend(batch_plan(batch_payload, recipe_id="<created recipe>"))
        if storage_payload:
            planned.extend(storage_plan(storage_payload, batch_id="<created batch>"))
        approval = self.creation_approval(args, planned)
        if approval:
            return approval

        steps = []
        recipe_id = None
        batch_id = None
        recipe = None
        batch = None
        try:
            recipe_id, recipe, recipe_steps = self.run_recipe_creation(
                recipe_payload,
                components,
                sources,
                "UNDER TEST" if recipe_transition_to == "APPROVED" else recipe_transition_to,
            )
            steps.extend(recipe_steps)
            batch_payload = dict(batch_payload)
            batch_payload["recipe_id"] = recipe_id
            batch_id, batch, batch_steps = self.run_batch_creation(batch_payload)
            steps.extend(batch_steps)
            if recipe_transition_to == "APPROVED":
                recipe = self.transition_recipe(recipe_id, "APPROVED")
                steps.append({"step": "transition_recipe", "recipe_id": recipe_id, "state": "APPROVED"})
        except WorkflowStepError as exc:
            rollback = None
            if batch_id is None and recipe_id:
                rollback = self.rollback_recipe(recipe_id)
            return workflow_error(
                "failed",
                exc,
                created={"recipe_id": recipe_id, "batch_id": batch_id},
                rollback=rollback,
            )

        storage_result = None
        if storage_payload:
            storage_payload = dict(storage_payload)
            storage_payload["batch_id"] = batch_id
            try:
                container, storage_steps = self.run_storage_assignment(storage_payload)
                steps.extend(storage_steps)
                storage_result = {"status": "assigned", "container": container}
            except WorkflowStepError as exc:
                return workflow_error(
                    "storage_not_satisfied",
                    exc,
                    created={"recipe_id": recipe_id, "batch_id": batch_id},
                    partial={"recipe": recipe, "batch": batch},
                )
        return {
            "status": "created",
            "recipe": recipe,
            "batch": batch,
            "storage": storage_result,
            "steps": steps,
        }

    def tool_transition_recipe_workflow(self, args: dict[str, Any]) -> dict[str, Any]:
        require_no_extra(args, {"recipe_id", "state", "acknowledge_missing_source"})
        recipe_id = require_string(args, "recipe_id")
        state = normalize_required_state(args.get("state"))
        if state == "RETIRED":
            raise ToolInputError("Recipe retirement remains a manual process")
        try:
            recipe = self.transition_recipe(
                recipe_id,
                state,
                acknowledge_missing_source=bool(args.get("acknowledge_missing_source")),
            )
        except WorkflowStepError as exc:
            return workflow_error("failed", exc)
        return {"status": "transitioned", "recipe": recipe}

    def tool_transition_batch_workflow(self, args: dict[str, Any]) -> dict[str, Any]:
        require_no_extra(args, {"batch_id", "state", "qa_measurements", "qa_override"})
        batch_id = require_string(args, "batch_id")
        try:
            if args.get("qa_measurements") is not None:
                self.workflow_request(
                    "PUT",
                    f"/api/batches/{batch_id}/qa-measurements",
                    "save_batch_qa_measurements",
                    body={"measurements": require_list(args, "qa_measurements")},
                )
            body: dict[str, Any] = {"state": normalize_required_state(args.get("state"))}
            if "qa_override" in args:
                body["qa_override"] = bool(args["qa_override"])
            structured = self.workflow_request(
                "POST",
                f"/api/batches/{batch_id}/transition",
                "transition_batch",
                body=body,
            )
        except WorkflowStepError as exc:
            return workflow_error("failed", exc)
        return {"status": "transitioned", "batch": structured["body"].get("batch")}

    def creation_approval(self, args: dict[str, Any], planned_operations: list[dict[str, Any]]) -> dict[str, Any] | None:
        digest = approval_digest(args)
        if args.get("approved") is not True:
            return {
                "status": "approval_required",
                "message": (
                    "Review these planned creations with the user. Call the same tool again with approved=true "
                    "and this approval_digest only after the user approves the exact payload."
                ),
                "approval_digest": digest,
                "planned_operations": planned_operations,
            }
        if args.get("approval_digest") != digest:
            raise ToolInputError("approval_digest must match the reviewed workflow payload")
        return None

    def workflow_request(
        self,
        method: str,
        path: str,
        step: str,
        *,
        body: Any | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self.api_client.request(method, path, body=body, query=query)
        structured = response_to_structured(response)
        if response.status_code >= 400:
            raise WorkflowStepError(step, structured)
        return structured

    def run_recipe_creation(
        self,
        recipe_payload: dict[str, Any],
        components: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        transition_to: str,
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        steps: list[dict[str, Any]] = []
        created = self.workflow_request("POST", "/api/recipes", "create_recipe", body=recipe_payload)
        recipe = require_body_object(created, "recipe")
        recipe_id = require_body_identifier(recipe, "recipe")
        steps.append({"step": "create_recipe", "recipe_id": recipe_id})
        for component in components:
            self.workflow_request(
                "POST",
                f"/api/recipes/{recipe_id}/components",
                "add_recipe_component",
                body=component_api_payload(component),
            )
            steps.append({"step": "add_recipe_component", "role": component.get("role")})
        for source in sources:
            self.workflow_request("POST", f"/api/recipes/{recipe_id}/sources", "add_recipe_source", body=source)
            steps.append({"step": "add_recipe_source", "kind": source.get("kind")})
        if transition_to and transition_to != "UNDER DEVELOPMENT":
            if transition_to == "APPROVED":
                recipe = self.transition_recipe(recipe_id, "UNDER TEST")
                steps.append({"step": "transition_recipe", "recipe_id": recipe_id, "state": "UNDER TEST"})
                recipe = self.transition_recipe(recipe_id, "APPROVED")
                steps.append({"step": "transition_recipe", "recipe_id": recipe_id, "state": "APPROVED"})
            else:
                recipe = self.transition_recipe(recipe_id, transition_to)
                steps.append({"step": "transition_recipe", "recipe_id": recipe_id, "state": transition_to})
        else:
            recipe = self.workflow_request("GET", f"/api/recipes/{recipe_id}", "get_recipe")["body"].get("recipe")
        return recipe_id, recipe, steps

    def run_batch_creation(self, batch_payload: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        steps: list[dict[str, Any]] = []
        created = self.workflow_request("POST", "/api/batches", "create_batch", body=batch_create_body(batch_payload))
        batch = require_body_object(created, "batch")
        batch_id = require_body_identifier(batch, "batch")
        steps.append({"step": "create_batch", "batch_id": batch_id})
        if batch_payload.get("qa_measurements") is not None:
            batch = self.workflow_request(
                "PUT",
                f"/api/batches/{batch_id}/qa-measurements",
                "save_batch_qa_measurements",
                body={"measurements": batch_payload["qa_measurements"]},
            )["body"].get("batch")
            steps.append({"step": "save_batch_qa_measurements", "batch_id": batch_id})
        transition_to = normalize_optional_state(batch_payload.get("transition_to"))
        if transition_to:
            body: dict[str, Any] = {"state": transition_to}
            if "qa_override" in batch_payload:
                body["qa_override"] = bool(batch_payload["qa_override"])
            batch = self.workflow_request(
                "POST",
                f"/api/batches/{batch_id}/transition",
                "transition_batch",
                body=body,
            )["body"].get("batch")
            steps.append({"step": "transition_batch", "batch_id": batch_id, "state": transition_to})
        if batch_payload.get("performance_record") is not None:
            performance = self.workflow_request(
                "PUT",
                f"/api/batches/{batch_id}/performance",
                "save_performance_record",
                body=batch_payload["performance_record"],
            )["body"].get("performance")
            steps.append({"step": "save_performance_record", "batch_id": batch_id, "performance_id": performance.get("id") if isinstance(performance, dict) else None})
        batch = self.workflow_request("GET", f"/api/batches/{batch_id}", "get_batch")["body"].get("batch")
        return batch_id, batch, steps

    def run_storage_assignment(self, storage_payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        steps: list[dict[str, Any]] = []
        container_id = storage_payload.get("container_id")
        if storage_payload.get("create_container") is not None:
            created = self.workflow_request(
                "POST",
                "/api/containers",
                "create_container",
                body=storage_payload["create_container"],
            )
            container = require_body_object(created, "container")
            container_id = container.get("id")
            steps.append({"step": "create_container", "container_id": container_id})
        body: dict[str, Any] = {
            "batch_id": storage_payload["batch_id"],
            "quantity": storage_payload["quantity"],
        }
        if "acknowledge_mixed_batch" in storage_payload:
            body["acknowledge_mixed_batch"] = bool(storage_payload["acknowledge_mixed_batch"])
        assigned = self.workflow_request(
            "POST",
            f"/api/containers/{container_id}/assignments",
            "assign_container",
            body=body,
        )
        steps.append({"step": "assign_container", "container_id": container_id, "batch_id": storage_payload["batch_id"]})
        return require_body_object(assigned, "container"), steps

    def transition_recipe(self, recipe_id: str, state: str, *, acknowledge_missing_source: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"state": state}
        if acknowledge_missing_source:
            body["acknowledge_missing_source"] = True
        structured = self.workflow_request(
            "POST",
            f"/api/recipes/{recipe_id}/transition",
            "transition_recipe",
            body=body,
        )
        return structured["body"].get("recipe")

    def rollback_recipe(self, recipe_id: str | None) -> dict[str, Any] | None:
        if not recipe_id:
            return None
        try:
            structured = self.workflow_request("DELETE", f"/api/recipes/{recipe_id}", "rollback_delete_recipe")
        except WorkflowStepError as exc:
            return {"status": "failed", "recipe_id": recipe_id, "error": exc.structured}
        return {"status": "deleted", "recipe_id": recipe_id, "response": structured}


def require_path(args: dict[str, Any]) -> str:
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ToolInputError("path must be a non-empty string")
    return path


def require_no_extra(args: dict[str, Any], allowed: set[str]) -> None:
    extra = set(args) - allowed
    if extra:
        raise ToolInputError(f"Unexpected argument(s): {', '.join(sorted(extra))}")


def require_object(args: dict[str, Any], name: str) -> dict[str, Any]:
    value = args.get(name)
    if not isinstance(value, dict):
        raise ToolInputError(f"{name} must be a JSON object")
    return value


def require_list(args: dict[str, Any], name: str) -> list[Any]:
    value = args.get(name)
    if not isinstance(value, list):
        raise ToolInputError(f"{name} must be a list")
    return value


def require_string(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f"{name} must be a non-empty string")
    return value.strip()


def normalize_required_state(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError("state must be a non-empty string")
    return value.strip().upper()


def normalize_optional_state(value: Any, *, default: str | None = None) -> str | None:
    if value in (None, ""):
        return default
    if not isinstance(value, str):
        raise ToolInputError("transition_to must be a string")
    return value.strip().upper()


def validate_recipe_payload(raw: dict[str, Any]) -> dict[str, Any]:
    payload = dict(raw)
    for field in ("title", "cartridge"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ToolInputError(f"recipe.{field} must be a non-empty string")
    return payload


def validate_recipe_components(raw_components: list[Any]) -> list[dict[str, Any]]:
    if not raw_components:
        raise ToolInputError("components must include BULLET, POWDER, PRIMER, and CASE")
    components = []
    roles = set()
    for index, raw in enumerate(raw_components, start=1):
        if not isinstance(raw, dict):
            raise ToolInputError(f"components[{index}] must be a JSON object")
        component = dict(raw)
        role = str(component.get("role") or "").strip().upper()
        if not role:
            raise ToolInputError(f"components[{index}].role is required")
        for field in ("item_id", "quantity", "unit"):
            if component.get(field) in (None, ""):
                raise ToolInputError(f"components[{index}].{field} is required")
        component["role"] = role
        roles.add(role)
        components.append(component)
    missing = CORE_RECIPE_ROLES - roles
    if missing:
        raise ToolInputError(f"components must include explicit roles: {', '.join(sorted(missing))}")
    return components


def validate_source_materials(raw_sources: list[Any]) -> list[dict[str, Any]]:
    if not raw_sources:
        raise ToolInputError("source_materials must include at least one source")
    sources = []
    for index, raw in enumerate(raw_sources, start=1):
        if not isinstance(raw, dict):
            raise ToolInputError(f"source_materials[{index}] must be a JSON object")
        source = dict(raw)
        if not isinstance(source.get("kind"), str) or not source["kind"].strip():
            raise ToolInputError(f"source_materials[{index}].kind is required")
        if not any(source.get(field) for field in ("citation", "url", "file_name", "stored_file_id", "notes")):
            raise ToolInputError(
                f"source_materials[{index}] must include citation, url, file_name, stored_file_id, or notes"
            )
        sources.append(source)
    return sources


def validate_batch_payload(raw: dict[str, Any], *, recipe_id_required: bool = True) -> dict[str, Any]:
    payload = dict(raw)
    if recipe_id_required:
        require_string(payload, "recipe_id")
    if payload.get("iterations") in (None, ""):
        raise ToolInputError("iterations is required")
    try:
        iterations = int(payload["iterations"])
    except (TypeError, ValueError):
        raise ToolInputError("iterations must be a whole number")
    if iterations <= 0:
        raise ToolInputError("iterations must be positive")
    payload["iterations"] = iterations
    allocations = require_list(payload, "allocations")
    if not allocations:
        raise ToolInputError("allocations must include at least one explicit lot allocation")
    cleaned_allocations = []
    for index, raw_allocation in enumerate(allocations, start=1):
        if not isinstance(raw_allocation, dict):
            raise ToolInputError(f"allocations[{index}] must be a JSON object")
        allocation = dict(raw_allocation)
        for field in ("component_id", "lot_id", "quantity"):
            if allocation.get(field) in (None, ""):
                raise ToolInputError(f"allocations[{index}].{field} is required")
        cleaned_allocations.append(allocation)
    payload["allocations"] = cleaned_allocations
    if payload.get("qa_measurements") is not None:
        measurements = require_list(payload, "qa_measurements")
        payload["qa_measurements"] = measurements
    if payload.get("performance_record") is not None:
        performance = require_object(payload, "performance_record")
        if normalize_optional_state(payload.get("transition_to")) != "PRODUCED":
            raise ToolInputError("performance_record requires transition_to PRODUCED for a newly created batch")
        payload["performance_record"] = performance
    return payload


def validate_storage_payload(raw: dict[str, Any], *, batch_id_required: bool = True) -> dict[str, Any]:
    payload = dict(raw)
    if batch_id_required:
        require_string(payload, "batch_id")
    if payload.get("quantity") in (None, ""):
        raise ToolInputError("quantity is required")
    try:
        quantity = int(payload["quantity"])
    except (TypeError, ValueError):
        raise ToolInputError("quantity must be a whole number")
    if quantity <= 0:
        raise ToolInputError("quantity must be positive")
    payload["quantity"] = quantity
    has_container_id = payload.get("container_id") not in (None, "")
    has_create_container = payload.get("create_container") is not None
    if has_container_id == has_create_container:
        raise ToolInputError("provide exactly one of container_id or create_container")
    if has_create_container:
        container = require_object(payload, "create_container")
        for field in ("identifier", "name", "cartridge_limit"):
            if container.get(field) in (None, ""):
                raise ToolInputError(f"create_container.{field} is required")
        payload["create_container"] = container
    return payload


def component_api_payload(component: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": component["item_id"],
        "quantity": component["quantity"],
        "unit": component["unit"],
    }


def batch_create_body(batch_payload: dict[str, Any]) -> dict[str, Any]:
    body = {
        "recipe_id": batch_payload["recipe_id"],
        "iterations": batch_payload["iterations"],
        "allocations": batch_payload["allocations"],
    }
    for field in ("characteristics", "notes", "acknowledge_non_approved", "acknowledge_missing_source"):
        if field in batch_payload:
            body[field] = batch_payload[field]
    return body


def require_body_object(structured: dict[str, Any], key: str) -> dict[str, Any]:
    body = structured.get("body")
    if not isinstance(body, dict) or not isinstance(body.get(key), dict):
        raise WorkflowStepError(
            f"parse_{key}",
            {"error": "unexpected_api_response", "message": f"Response did not include {key}", "response": structured},
        )
    return body[key]


def require_body_identifier(body: dict[str, Any], label: str) -> str:
    identifier = body.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise WorkflowStepError(
            f"parse_{label}_id",
            {"error": "unexpected_api_response", "message": f"Response did not include {label} id", "body": body},
        )
    return identifier


def approval_digest(args: dict[str, Any]) -> str:
    reviewed_payload = {
        key: value for key, value in args.items()
        if key not in APPROVAL_DIGEST_FIELDS
    }
    canonical = json.dumps(reviewed_payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def workflow_error(
    status: str,
    exc: WorkflowStepError,
    *,
    created: dict[str, Any] | None = None,
    rollback: dict[str, Any] | None = None,
    partial: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "failed_step": exc.step,
        "error": exc.structured,
        "is_error": True,
    }
    if created:
        result["created"] = created
    if rollback is not None:
        result["rollback"] = rollback
    if partial:
        result["partial"] = partial
    return result


def recipe_plan(
    recipe_payload: dict[str, Any],
    components: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    transition_to: str | None,
) -> list[dict[str, Any]]:
    plan = [
        {
            "operation": "create_recipe",
            "title": recipe_payload.get("title"),
            "cartridge": recipe_payload.get("cartridge"),
        },
        {
            "operation": "add_recipe_components",
            "components": [
                {
                    "role": component.get("role"),
                    "item_id": component.get("item_id"),
                    "quantity": component.get("quantity"),
                    "unit": component.get("unit"),
                }
                for component in components
            ],
        },
        {
            "operation": "add_source_materials",
            "source_count": len(sources),
            "sources": [
                {
                    key: source.get(key)
                    for key in ("kind", "citation", "url", "file_name", "stored_file_id", "notes", "page")
                    if source.get(key) not in (None, "")
                }
                for source in sources
            ],
        },
    ]
    if transition_to and transition_to != "UNDER DEVELOPMENT":
        plan.append({"operation": "transition_recipe", "state": transition_to})
    return plan


def batch_plan(batch_payload: dict[str, Any], *, recipe_id: str | None = None) -> list[dict[str, Any]]:
    plan = [
        {
            "operation": "create_batch",
            "recipe_id": recipe_id or batch_payload.get("recipe_id"),
            "iterations": batch_payload.get("iterations"),
            "allocations": batch_payload.get("allocations", []),
        }
    ]
    if batch_payload.get("qa_measurements") is not None:
        plan.append({"operation": "save_batch_qa_measurements", "sample_count": len(batch_payload["qa_measurements"])})
    if batch_payload.get("transition_to"):
        plan.append({"operation": "transition_batch", "state": normalize_optional_state(batch_payload.get("transition_to"))})
    if batch_payload.get("performance_record") is not None:
        plan.append({"operation": "save_performance_record", "fields": sorted(batch_payload["performance_record"])})
    return plan


def storage_plan(storage_payload: dict[str, Any], *, batch_id: str | None = None) -> list[dict[str, Any]]:
    plan = []
    if storage_payload.get("create_container") is not None:
        container = storage_payload["create_container"]
        plan.append({
            "operation": "create_container",
            "identifier": container.get("identifier"),
            "name": container.get("name"),
            "cartridge_limit": container.get("cartridge_limit"),
        })
    plan.append({
        "operation": "assign_batch_to_container",
        "batch_id": batch_id or storage_payload.get("batch_id"),
        "container_id": storage_payload.get("container_id") or "<created container>",
        "quantity": storage_payload.get("quantity"),
    })
    return plan


def normalize_api_path(raw_path: str) -> ApiPath:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ToolInputError("path must be a non-empty string")
    parsed = urlsplit(raw_path.strip())
    if parsed.scheme or parsed.netloc:
        raise ToolInputError("path must be relative to the configured Reload Ledger API base URL")
    path = parsed.path if parsed.path.startswith("/") else f"/{parsed.path}"
    if ".." in path.split("/"):
        raise ToolInputError("path must not contain parent-directory segments")
    if path != "/health" and not path.startswith("/api/"):
        raise ToolInputError("path must be /health or begin with /api/")
    return ApiPath(path=path, query_pairs=parse_qsl(parsed.query, keep_blank_values=True))


def response_to_structured(response: requests.Response) -> dict[str, Any]:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    body = response_body(response, content_type)
    return {
        "status_code": response.status_code,
        "content_type": content_type or None,
        "headers": response_headers(response),
        "body": redact_sensitive(body),
    }


def response_body(response: requests.Response, content_type: str) -> Any:
    if not response.content:
        return None
    if content_type == "application/json" or content_type.endswith("+json"):
        try:
            return response.json()
        except ValueError:
            return response.text
    if content_type.startswith("text/") or content_type in {"application/csv"}:
        return response.text
    return {
        "base64": base64.b64encode(response.content).decode("ascii"),
        "size": len(response.content),
    }


def response_headers(response: requests.Response) -> dict[str, str]:
    exposed = ("Content-Type", "Content-Disposition", "ETag", "Last-Modified")
    return {key: value for key, value in response.headers.items() if key in exposed}


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key in SENSITIVE_RESPONSE_KEYS else redact_sensitive(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def tool_result(structured: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    content_type = structured.get("content_type")
    body = structured.get("body")
    if isinstance(body, dict) and isinstance(body.get("base64"), str) and isinstance(content_type, str):
        if content_type.startswith("image/"):
            content.append({"type": "image", "data": body["base64"], "mimeType": content_type})
    content.append({"type": "text", "text": json.dumps(structured, indent=2, sort_keys=True)})
    return {
        "content": content,
        "structuredContent": structured,
        "isError": is_error,
    }


def jsonrpc_error(request_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def run_stdio(server: McpServer, input_stream: IO[str] = sys.stdin, output_stream: IO[str] = sys.stdout) -> int:
    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = jsonrpc_error(None, PARSE_ERROR, f"Parse error: {exc.msg}")
        else:
            response = server.handle_message(message)
        if response is not None:
            output_stream.write(json.dumps(response, separators=(",", ":")) + "\n")
            output_stream.flush()
    return 0


def build_server_from_env() -> McpServer:
    base_url = os.getenv("RELOADING_API_BASE_URL", "http://localhost:8080")
    token = os.getenv("RELOADING_API_TOKEN")
    timeout = float(os.getenv("RELOADING_API_TIMEOUT", "15"))
    return McpServer(ReloadingApiClient(base_url=base_url, token=token, timeout=timeout))


def main() -> int:
    return run_stdio(build_server_from_env())
