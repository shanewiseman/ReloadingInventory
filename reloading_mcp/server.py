from __future__ import annotations

import base64
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
    "or certify that a recipe is safe."
)


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


def object_schema(description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "additionalProperties": True}
    if description:
        schema["description"] = description
    return schema


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


def require_path(args: dict[str, Any]) -> str:
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ToolInputError("path must be a non-empty string")
    return path


def require_no_extra(args: dict[str, Any], allowed: set[str]) -> None:
    extra = set(args) - allowed
    if extra:
        raise ToolInputError(f"Unexpected argument(s): {', '.join(sorted(extra))}")


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
