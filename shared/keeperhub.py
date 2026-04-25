"""KeeperHub Direct Execution API wrapper.

Reference: https://docs.keeperhub.com/api
Auth: X-API-Key header with kh_-prefixed key.
Endpoints used:
  POST /api/execute/transfer
  POST /api/execute/contract-call
  GET  /api/execute/{id}/status

Day-1 stub. Integration kill-test (task #2) will validate one real call.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://app.keeperhub.com/api"
DEFAULT_TIMEOUT_S = 30.0


@dataclass
class KeeperHubConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    wallet_address: str | None = None

    @classmethod
    def from_env(cls) -> "KeeperHubConfig":
        api_key = os.environ.get("KEEPERHUB_API_KEY", "")
        if not api_key:
            raise RuntimeError("KEEPERHUB_API_KEY not set in environment")
        return cls(
            api_key=api_key,
            base_url=os.environ.get("KEEPERHUB_API_URL", DEFAULT_BASE_URL),
            wallet_address=os.environ.get("KEEPERHUB_WALLET_ADDRESS") or None,
        )


class KeeperHubClient:
    """Thin wrapper around KeeperHub Direct Execution endpoints."""

    def __init__(self, config: KeeperHubConfig | None = None):
        self.config = config or KeeperHubConfig.from_env()
        self._client = httpx.Client(
            base_url=self.config.base_url,
            headers={"X-API-Key": self.config.api_key},
            timeout=DEFAULT_TIMEOUT_S,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "KeeperHubClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ─────────── Day-1 hello-world surface ───────────

    def execute_transfer(
        self,
        *,
        chain: str,
        to: str,
        value_wei: int,
        token_address: str | None = None,
    ) -> dict[str, Any]:
        """Execute a value or ERC20 transfer via KeeperHub.

        Day-1 kill-test target: a self-transfer of 0 value just confirms the
        plumbing. KeeperHub returns transactionHash + transactionLink synchronously.
        """
        payload: dict[str, Any] = {
            "chain": chain,
            "to": to,
            "value": str(value_wei),
        }
        if token_address:
            payload["tokenAddress"] = token_address
        resp = self._client.post("/execute/transfer", json=payload)
        resp.raise_for_status()
        return resp.json()

    def execute_contract_call(
        self,
        *,
        chain: str,
        contract_address: str,
        function_name: str,
        function_args: list[Any],
        value_wei: int = 0,
        abi: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Execute an arbitrary contract call.

        If `abi` is omitted, KeeperHub auto-fetches it from the chain's explorer.
        """
        payload: dict[str, Any] = {
            "chain": chain,
            "contractAddress": contract_address,
            "functionName": function_name,
            "functionArgs": function_args,
            "value": str(value_wei),
        }
        if abi is not None:
            payload["abi"] = abi
        resp = self._client.post("/execute/contract-call", json=payload)
        resp.raise_for_status()
        return resp.json()

    def get_status(self, execution_id: str) -> dict[str, Any]:
        resp = self._client.get(f"/execute/{execution_id}/status")
        resp.raise_for_status()
        return resp.json()
