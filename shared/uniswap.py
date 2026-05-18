"""Uniswap Trading API wrapper.

Reference: https://docs.uniswap.org/api/quote/overview
Endpoints used (verify exact paths on Day-1 kill-test):
  GET  /quote
  POST /swap

Day-1 stub. Replaced once the kill-test in task #5 confirms route shape.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://trade-api.gateway.uniswap.org"
DEFAULT_TIMEOUT_S = 20.0


@dataclass
class UniswapConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL

    @classmethod
    def from_env(cls) -> "UniswapConfig":
        api_key = os.environ.get("UNISWAP_API_KEY", "")
        if not api_key:
            raise RuntimeError("UNISWAP_API_KEY not set in environment")
        return cls(
            api_key=api_key,
            base_url=os.environ.get("UNISWAP_API_BASE", DEFAULT_BASE_URL),
        )


class UniswapClient:
    def __init__(self, config: UniswapConfig | None = None):
        self.config = config or UniswapConfig.from_env()
        self._client = httpx.Client(
            base_url=self.config.base_url,
            headers={"X-API-Key": self.config.api_key},
            timeout=DEFAULT_TIMEOUT_S,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "UniswapClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def quote(
        self,
        *,
        chain_id: int,
        token_in: str,
        token_out: str,
        amount: str,
        trade_type: str = "EXACT_INPUT",
    ) -> dict[str, Any]:
        """Fetch a route quote. Day-1 kill-test target."""
        params = {
            "tokenInChainId": chain_id,
            "tokenOutChainId": chain_id,
            "tokenIn": token_in,
            "tokenOut": token_out,
            "amount": amount,
            "type": trade_type,
        }
        resp = self._client.get("/quote", params=params)  # type: ignore[arg-type]
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]
