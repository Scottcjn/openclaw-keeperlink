"""Gensyn AXL transport wrapper.

AXL exposes a `/mcp/{peer_id}/{service}` HTTP-over-Yggdrasil routing
surface. Day-1 stub validates we can hit a peer's MCP service through
the local AXL node.

Reference structure: /home/scott/hackathon-refs/axl/ (Gensyn template).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_TIMEOUT_S = 10.0


@dataclass
class AXLConfig:
    local_axl_url: str
    timeout_s: float = DEFAULT_TIMEOUT_S

    @classmethod
    def from_env(cls, role: str = "a") -> "AXLConfig":
        port_var = "AXL_NODE_A_PORT" if role == "a" else "AXL_NODE_B_PORT"
        port = os.environ.get(port_var, "9001" if role == "a" else "9002")
        return cls(local_axl_url=f"http://127.0.0.1:{port}")


class AXLClient:
    def __init__(self, config: AXLConfig | None = None, role: str = "a"):
        self.config = config or AXLConfig.from_env(role=role)
        self._client = httpx.Client(
            base_url=self.config.local_axl_url,
            timeout=self.config.timeout_s,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AXLClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def call_peer(
        self,
        *,
        peer_id: str,
        service: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """POST a JSON-RPC-shaped payload to /mcp/{peer_id}/{service}."""
        resp = self._client.post(f"/mcp/{peer_id}/{service}", json=payload)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]
