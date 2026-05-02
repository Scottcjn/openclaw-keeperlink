"""KeeperHub workflow + MCP API wrapper.

Reference:
- ARCHITECTURE.md v4
- docs/kill-tests/keeperhub-day1.md
- docs/kill-tests/workflow-publishing-day2.md

REST surface:
- GET  /api/health
- GET  /api/chains
- GET  /api/workflows
- GET  /api/mcp/workflows
- POST /api/mcp/workflows/{slug}/call

MCP surface:
- POST /api/mcp (JSON-RPC 2.0)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


DEFAULT_BASE_URL = "https://app.keeperhub.com/api"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MCP_PROTOCOL_VERSION = "2024-11-05"
BASESCAN_TX_URL = "https://basescan.org/tx"

TERMINAL_EXECUTION_STATUSES = frozenset(
    {
        "cancelled",
        "canceled",
        "completed",
        "error",
        "failed",
        "success",
    }
)

JsonDict = dict[str, Any]


class _FlexibleModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class X402Resource(_FlexibleModel):
    url: str | None = None
    description: str | None = None
    mimeType: str | None = None


class X402Accept(_FlexibleModel):
    scheme: str | None = None
    network: str | None = None
    asset: str | None = None
    amount: str | None = None
    payTo: str | None = None
    maxTimeoutSeconds: int | None = None
    extra: JsonDict = Field(default_factory=dict)


class X402Envelope(_FlexibleModel):
    x402Version: int | None = None
    error: str | None = None
    resource: X402Resource | None = None
    accepts: list[X402Accept] = Field(default_factory=list)
    extensions: JsonDict = Field(default_factory=dict)


class WorkflowCallResponse(_FlexibleModel):
    executionId: str | None = None
    status: str | None = None
    output: Any = None


class KeeperHubError(RuntimeError):
    """Base class for KeeperHub client failures."""

    def __init__(self, message: str, *, details: JsonDict | None = None):
        super().__init__(message)
        self.details = details or {}


class KeeperHubConfigError(KeeperHubError):
    """Configuration is missing or malformed."""


class KeeperHubTransportError(KeeperHubError):
    """Transport or timeout error while calling KeeperHub."""

    def __init__(self, message: str, *, path: str, cause: Exception):
        super().__init__(message, details={"path": path, "cause": repr(cause)})
        self.path = path
        self.cause = cause


class KeeperHubAPIError(KeeperHubError):
    """HTTP error from the REST API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        path: str,
        payload: Any | None = None,
    ):
        super().__init__(
            message,
            details={
                "status_code": status_code,
                "path": path,
                "payload": payload,
            },
        )
        self.status_code = status_code
        self.path = path
        self.payload = payload


class KeeperHubMCPError(KeeperHubError):
    """JSON-RPC or MCP-tooling failure."""

    def __init__(
        self,
        message: str,
        *,
        method: str,
        code: int | None = None,
        data: Any | None = None,
    ):
        super().__init__(
            message,
            details={
                "method": method,
                "code": code,
                "data": data,
            },
        )
        self.method = method
        self.code = code
        self.data = data


class KeeperHubExecutionTimeout(KeeperHubError):
    """Execution did not reach a terminal state before the timeout."""

    def __init__(
        self,
        message: str,
        *,
        execution_id: str,
        timeout_s: float,
        last_payload: JsonDict | None = None,
    ):
        super().__init__(
            message,
            details={
                "execution_id": execution_id,
                "timeout_s": timeout_s,
                "last_payload": last_payload,
            },
        )
        self.execution_id = execution_id
        self.timeout_s = timeout_s
        self.last_payload = last_payload


class X402PaymentRequired(KeeperHubAPIError):
    """KeeperHub returned a native x402 payment requirement envelope."""

    def __init__(self, *, path: str, envelope: JsonDict):
        description = _extract_error_message(envelope) or "Payment required"
        super().__init__(
            f"KeeperHub workflow requires x402 payment: {description}",
            status_code=402,
            path=path,
            payload=envelope,
        )
        self.envelope = envelope
        self.x402_required = True


@dataclass
class KeeperHubConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    wallet_address: str | None = None
    mcp_url: str | None = None

    @classmethod
    def from_env(cls) -> "KeeperHubConfig":
        api_key = os.environ.get("KEEPERHUB_API_KEY", "").strip()
        if not api_key:
            raise KeeperHubConfigError("KEEPERHUB_API_KEY not set in environment")
        base_url = os.environ.get("KEEPERHUB_API_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
        return cls(
            api_key=api_key,
            base_url=base_url,
            wallet_address=os.environ.get("KEEPERHUB_WALLET_ADDRESS") or None,
            mcp_url=os.environ.get("KEEPERHUB_MCP_URL") or None,
        )


class KeeperHubClient:
    """Thin wrapper around KeeperHub's workflow REST API and hosted MCP server."""

    def __init__(self, config: KeeperHubConfig | None = None):
        self.config = config or KeeperHubConfig.from_env()
        _validate_api_key(self.config.api_key)

        self.config.base_url = _normalize_api_base_url(self.config.base_url)
        self.config.mcp_url = _normalize_mcp_url(self.config.mcp_url, self.config.base_url)

        self._client = httpx.Client(
            base_url=self.config.base_url,
            headers={"X-API-Key": self.config.api_key},
            timeout=DEFAULT_TIMEOUT_S,
        )
        self._mcp_client = httpx.Client(
            base_url=self.config.mcp_url,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                # MCP-spec Accept: server may reply JSON or text/event-stream;
                # without this header KeeperHub's edge returns the SPA HTML page
                # instead of a JSON-RPC response (verified 2026-05-02).
                "Accept": "application/json, text/event-stream",
            },
            timeout=DEFAULT_TIMEOUT_S,
            # KeeperHub redirects /mcp → /mcp/ with HTTP 308; httpx defaults to
            # follow_redirects=False so the client otherwise reads the redirect
            # body as the JSON-RPC response and dies decoding it.
            follow_redirects=True,
        )
        self._mcp_request_id = 0
        self._mcp_session_id: str | None = None

    def close(self) -> None:
        self._mcp_client.close()
        self._client.close()

    def __enter__(self) -> "KeeperHubClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def health(self) -> JsonDict:
        payload = self._rest_request("GET", "health")
        return _require_dict(payload, path="health")

    def list_chains(self) -> list[JsonDict]:
        payload = self._rest_request("GET", "chains")
        return _coerce_object_list(payload, path="chains")

    def list_workflows(self) -> list[JsonDict]:
        payload = self._rest_request("GET", "workflows")
        return _coerce_object_list(payload, path="workflows")

    def list_bazaar(self, search: str | None = None) -> list[JsonDict]:
        query = search.strip() if search else None
        params = {"search": query} if query else None
        payload = self._rest_request("GET", "mcp/workflows", params=params)
        return _coerce_object_list(payload, path="mcp/workflows")

    def execute_workflow(
        self,
        slug: str,
        params: JsonDict | None = None,
        payment_header: str | None = None,
    ) -> JsonDict:
        workflow_slug = slug.strip()
        if not workflow_slug:
            raise ValueError("workflow slug must not be empty")

        headers: dict[str, str] = {}
        if payment_header and payment_header.strip():
            headers["X-Payment"] = payment_header.strip()

        path = f"mcp/workflows/{quote(workflow_slug, safe='-._~')}/call"
        payload = self._rest_request(
            "POST",
            path,
            json_body=params or {},
            headers=headers or None,
            allow_x402=True,
        )
        data = _require_dict(payload, path=path)
        parsed = WorkflowCallResponse.model_validate(data)
        execution_id = parsed.executionId or _extract_execution_id(data)
        tx_hash = _extract_tx_hash(data)
        basescan_link = _extract_basescan_link(data, tx_hash)
        return {
            "execution_id": execution_id,
            "tx_hash": tx_hash,
            "basescan_link": basescan_link,
            "x402_required": False,
        }

    def execute_protocol_action(self, action_type: str, params: JsonDict) -> JsonDict:
        if not action_type.strip():
            raise ValueError("action_type must not be empty")
        payload = self._mcp_tool_call(
            "execute_protocol_action",
            {
                "actionType": action_type,
                "params": params,
            },
        )
        return _require_dict(payload, path="mcp:tools/call:execute_protocol_action")

    def execute_contract_call(
        self,
        contract_address: str,
        function_name: str,
        network: str,
        function_args: str | None = None,
        abi: str | None = None,
        value: str | None = None,
    ) -> JsonDict:
        # KeeperHub's generic contract-call tool: view functions return the
        # result inline (e.g. {"result": "<atomic>"}), state-changing calls
        # return {"executionId": "...", "status": "completed"} after settlement.
        if not contract_address.strip():
            raise ValueError("contract_address must not be empty")
        if not function_name.strip():
            raise ValueError("function_name must not be empty")
        if not network.strip():
            raise ValueError("network must not be empty")
        args: JsonDict = {
            "contract_address": contract_address,
            "function_name": function_name,
            "network": network,
        }
        if function_args is not None:
            args["function_args"] = function_args
        if abi is not None:
            args["abi"] = abi
        if value is not None:
            args["value"] = value
        payload = self._mcp_tool_call("execute_contract_call", args)
        return _require_dict(payload, path="mcp:tools/call:execute_contract_call")

    def create_workflow(self, spec: JsonDict) -> JsonDict:
        payload = self._mcp_tool_call("create_workflow", spec)
        return _require_dict(payload, path="mcp:tools/call:create_workflow")

    def get_execution(self, execution_id: str) -> JsonDict:
        execution_id = execution_id.strip()
        if not execution_id:
            raise ValueError("execution_id must not be empty")

        encoded_id = quote(execution_id, safe="-._~")
        candidate_paths = (
            f"executions/{encoded_id}",
            f"workflows/executions/{encoded_id}",
            f"executions/{encoded_id}/status",
            f"workflows/executions/{encoded_id}/status",
        )
        attempted_paths: list[str] = []
        last_not_found: KeeperHubAPIError | None = None

        for path in candidate_paths:
            attempted_paths.append(path)
            try:
                payload = self._rest_request("GET", path)
            except KeeperHubAPIError as exc:
                if exc.status_code == 404:
                    last_not_found = exc
                    continue
                raise
            return _require_dict(payload, path=path)

        if last_not_found is not None:
            raise KeeperHubAPIError(
                f"KeeperHub execution {execution_id!r} was not found on any known execution endpoint",
                status_code=404,
                path=attempted_paths[0],
                payload={"attempted_paths": attempted_paths},
            ) from last_not_found

        raise KeeperHubError(
            "KeeperHub execution lookup exhausted known endpoints without a response",
            details={"execution_id": execution_id, "attempted_paths": attempted_paths},
        )

    def wait_for_execution(self, execution_id: str, timeout: float = DEFAULT_TIMEOUT_S) -> JsonDict:
        if timeout <= 0:
            raise ValueError("timeout must be > 0")

        deadline = time.monotonic() + timeout
        last_payload: JsonDict | None = None

        while time.monotonic() < deadline:
            try:
                payload = self.get_execution(execution_id)
            except KeeperHubAPIError as exc:
                if exc.status_code != 404:
                    raise
                payload = None

            if payload is not None:
                last_payload = payload
                status = _extract_status(payload)
                if status and status.lower() in TERMINAL_EXECUTION_STATUSES:
                    return payload

                # Some executions may expose the transaction hash before they
                # settle into a final status string. Returning here gives the
                # caller the settlement handle instead of spinning unnecessarily.
                if _extract_tx_hash(payload):
                    return payload

            sleep_for = min(1.0, deadline - time.monotonic())
            if sleep_for > 0:
                time.sleep(sleep_for)

        raise KeeperHubExecutionTimeout(
            f"Timed out waiting for KeeperHub execution {execution_id!r}",
            execution_id=execution_id,
            timeout_s=timeout,
            last_payload=last_payload,
        )

    def get_status(self, execution_id: str) -> JsonDict:
        """Backward-compatible alias for the old status method name."""
        return self.get_execution(execution_id)

    def _rest_request(
        self,
        method: str,
        path: str,
        *,
        params: JsonDict | None = None,
        json_body: JsonDict | None = None,
        headers: dict[str, str] | None = None,
        allow_x402: bool = False,
    ) -> Any:
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json_body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise KeeperHubTransportError(
                f"KeeperHub REST request failed for {path}",
                path=path,
                cause=exc,
            ) from exc

        if allow_x402 and response.status_code == 402:
            envelope = _coerce_x402_envelope(_decode_json_response(response, path))
            raise X402PaymentRequired(path=path, envelope=envelope)

        if response.is_error:
            raise _rest_api_error(response, path)

        return _decode_json_response(response, path)

    def _mcp_tool_call(self, tool_name: str, arguments: JsonDict) -> Any:
        self._ensure_mcp_session()
        result = self._mcp_request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )
        if isinstance(result, dict) and result.get("isError"):
            raise KeeperHubMCPError(
                f"KeeperHub MCP tool {tool_name!r} reported an error",
                method="tools/call",
                data=result,
            )
        return _unwrap_mcp_payload(result)

    def _ensure_mcp_session(self) -> None:
        if self._mcp_session_id:
            return

        init_result = self._mcp_request(
            "initialize",
            {
                "protocolVersion": DEFAULT_MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "openclaw-keeperlink",
                    "version": "0.1.0",
                },
            },
            include_session_header=False,
        )
        if not isinstance(init_result, dict):
            raise KeeperHubMCPError(
                "KeeperHub MCP initialize response was not an object",
                method="initialize",
                data=init_result,
            )

        self._mcp_notification("notifications/initialized", {})

    def _mcp_notification(self, method: str, params: JsonDict | None = None) -> None:
        headers: dict[str, str] = {}
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id

        body: JsonDict = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            body["params"] = params

        try:
            response = self._mcp_client.post("", json=body, headers=headers or None)
        except httpx.HTTPError as exc:
            raise KeeperHubTransportError(
                f"KeeperHub MCP notification failed for {method}",
                path="mcp",
                cause=exc,
            ) from exc

        session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
        if session_id:
            self._mcp_session_id = session_id

        if response.is_error:
            raise _rest_api_error(response, f"mcp:{method}")

    def _mcp_request(
        self,
        method: str,
        params: JsonDict | None = None,
        *,
        include_session_header: bool = True,
    ) -> Any:
        headers: dict[str, str] = {}
        if include_session_header and self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id

        body: JsonDict = {
            "jsonrpc": "2.0",
            "id": self._next_mcp_request_id(),
            "method": method,
        }
        if params is not None:
            body["params"] = params

        try:
            response = self._mcp_client.post("", json=body, headers=headers or None)
        except httpx.HTTPError as exc:
            raise KeeperHubTransportError(
                f"KeeperHub MCP request failed for {method}",
                path="mcp",
                cause=exc,
            ) from exc

        session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
        if session_id:
            self._mcp_session_id = session_id

        if response.is_error:
            raise _rest_api_error(response, f"mcp:{method}")

        payload = _decode_json_response(response, f"mcp:{method}")
        if not isinstance(payload, dict):
            raise KeeperHubMCPError(
                "KeeperHub MCP response was not a JSON object",
                method=method,
                data=payload,
            )

        error = payload.get("error")
        if isinstance(error, dict):
            raise KeeperHubMCPError(
                error.get("message") or f"KeeperHub MCP method {method!r} failed",
                method=method,
                code=error.get("code"),
                data=error.get("data"),
            )

        if "result" not in payload:
            raise KeeperHubMCPError(
                f"KeeperHub MCP method {method!r} returned no result",
                method=method,
                data=payload,
            )
        return payload["result"]

    def _next_mcp_request_id(self) -> int:
        self._mcp_request_id += 1
        return self._mcp_request_id


def _normalize_api_base_url(base_url: str) -> str:
    trimmed = base_url.strip().rstrip("/")
    if not trimmed:
        raise KeeperHubConfigError("KeeperHub base_url must not be empty")
    if trimmed.endswith("/api"):
        return trimmed
    return f"{trimmed}/api"


def _normalize_mcp_url(mcp_url: str | None, base_url: str) -> str:
    # KeeperHub's MCP endpoint lives at /mcp on the host root (verified 2026-05-02
    # via direct probe — /api/mcp returns 404 HTML). Earlier code rewrote /mcp →
    # /api/mcp which always failed; defaults derived from base_url=".../api" likewise
    # produced a broken path. Build from the host with no /api segment.
    if not mcp_url:
        host = base_url.rstrip("/")
        if host.endswith("/api"):
            host = host[:-4]
        return f"{host}/mcp"

    parsed = urlsplit(mcp_url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise KeeperHubConfigError(f"Invalid KeeperHub MCP URL: {mcp_url!r}")

    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _validate_api_key(api_key: str) -> None:
    if not api_key:
        raise KeeperHubConfigError("KeeperHub API key must not be empty")
    if not api_key.startswith("kh_"):
        raise KeeperHubConfigError("KeeperHub API key must start with 'kh_'")

    key_length = len(api_key)
    suffix_length = len(api_key[3:])
    if key_length not in {35, 38} and suffix_length != 35:
        raise KeeperHubConfigError(
            "KeeperHub API key must be kh_-prefixed and 35 chars total or 35 chars after the prefix"
        )


def _decode_json_response(response: httpx.Response, path: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise KeeperHubAPIError(
            f"KeeperHub returned non-JSON from {path}",
            status_code=response.status_code,
            path=path,
            payload=response.text,
        ) from exc


def _rest_api_error(response: httpx.Response, path: str) -> KeeperHubAPIError:
    payload: Any
    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    message = _extract_error_message(payload) or f"HTTP {response.status_code}"
    return KeeperHubAPIError(
        f"KeeperHub request to {path} failed: {message}",
        status_code=response.status_code,
        path=path,
        payload=payload,
    )


def _extract_error_message(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = _extract_error_message(value)
                if nested:
                    return nested
        for value in payload.values():
            nested = _extract_error_message(value)
            if nested:
                return nested
    if isinstance(payload, list):
        for value in payload:
            nested = _extract_error_message(value)
            if nested:
                return nested
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    return None


def _coerce_x402_envelope(payload: Any) -> JsonDict:
    if not isinstance(payload, dict):
        raise KeeperHubAPIError(
            "KeeperHub returned HTTP 402 without a JSON x402 envelope",
            status_code=402,
            path="mcp/workflows/<slug>/call",
            payload=payload,
        )
    try:
        return X402Envelope.model_validate(payload).model_dump(mode="json", exclude_none=True)
    except ValidationError:
        return payload


def _require_dict(payload: Any, *, path: str) -> JsonDict:
    if isinstance(payload, dict):
        return payload
    raise KeeperHubError(
        f"Expected JSON object from {path}, got {type(payload).__name__}",
        details={"path": path, "payload": payload},
    )


def _coerce_object_list(payload: Any, *, path: str) -> list[JsonDict]:
    if isinstance(payload, list):
        return [_require_dict(item, path=path) for item in payload]
    if isinstance(payload, dict):
        for key in ("items", "results", "workflows", "chains", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [_require_dict(item, path=path) for item in value]
    raise KeeperHubError(
        f"Expected JSON array from {path}, got {type(payload).__name__}",
        details={"path": path, "payload": payload},
    )


def _unwrap_mcp_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload

    structured = payload.get("structuredContent")
    if structured is not None:
        return structured

    content = payload.get("content")
    if not isinstance(content, list):
        return payload

    decoded_items: list[Any] = []
    for item in content:
        if not isinstance(item, dict):
            decoded_items.append(item)
            continue

        if "json" in item:
            decoded_items.append(item["json"])
            continue

        text = item.get("text")
        if isinstance(text, str):
            stripped = text.strip()
            if not stripped:
                continue
            try:
                decoded_items.append(json.loads(stripped))
            except json.JSONDecodeError:
                decoded_items.append(stripped)
            continue

        decoded_items.append(item)

    if len(decoded_items) == 1:
        return decoded_items[0]
    if decoded_items:
        return decoded_items
    return payload


def _extract_execution_id(payload: Any) -> str | None:
    value = _find_in_structure(payload, {"executionId", "execution_id"})
    return value if isinstance(value, str) and value else None


def _extract_status(payload: Any) -> str | None:
    value = _find_in_structure(payload, {"status", "state"})
    return value if isinstance(value, str) and value else None


def _extract_basescan_link(payload: Any, tx_hash: str | None) -> str | None:
    value = _find_in_structure(
        payload,
        {
            "basescanLink",
            "transactionLink",
            "txLink",
            "tx_link",
            "transaction_link",
        },
    )
    if isinstance(value, str) and value:
        return value
    if tx_hash:
        return f"{BASESCAN_TX_URL}/{tx_hash}"
    return None


def _extract_tx_hash(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if (
                "tx" in key.lower()
                or "transaction" in key.lower()
                or key.lower() == "hash"
            ) and _looks_like_tx_hash(value):
                return value
        for value in payload.values():
            found = _extract_tx_hash(value)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = _extract_tx_hash(value)
            if found:
                return found
    return None


def _looks_like_tx_hash(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("0x") and len(value) == 66


def _find_in_structure(payload: Any, keys: set[str]) -> Any | None:
    lowered = {key.lower() for key in keys}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys or key.lower() in lowered:
                return value
        for value in payload.values():
            found = _find_in_structure(value, keys)
            if found is not None:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = _find_in_structure(value, keys)
            if found is not None:
                return found
    return None
