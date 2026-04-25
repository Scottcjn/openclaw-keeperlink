"""0G Storage wrapper.

The official SDK is `@0gfoundation/0g-ts-sdk` (TypeScript). For Day-1 we
shell out to a Node.js helper script — same as the reference flow:

    upload(blob_bytes) -> rootHash
    download(rootHash) -> blob_bytes

The helper lives at `scripts/zerog_helper.js` (Node) and exposes a
two-command stdin/stdout protocol so we don't need a Python ⇄ TS bridge.

Day-1 stub. Lit up once task #4 (0G testnet upload kill-test) passes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ZeroGConfig:
    private_key: str
    rpc_url: str
    indexer_url: str

    @classmethod
    def from_env(cls) -> "ZeroGConfig":
        return cls(
            private_key=os.environ.get("ZEROG_PRIVATE_KEY", ""),
            rpc_url=os.environ.get("ZEROG_RPC_URL", "https://evmrpc-testnet.0g.ai"),
            indexer_url=os.environ.get(
                "ZEROG_INDEXER_URL",
                "https://indexer-storage-testnet-turbo.0g.ai",
            ),
        )


class ZeroGClient:
    """Day-1 placeholder. Methods raise NotImplementedError until kill-test passes."""

    def __init__(self, config: ZeroGConfig | None = None):
        self.config = config or ZeroGConfig.from_env()

    def upload(self, blob: bytes) -> str:  # noqa: ARG002
        raise NotImplementedError("0G upload comes online after task #4.")

    def download(self, root_hash: str) -> bytes:  # noqa: ARG002
        raise NotImplementedError("0G download comes online after task #4.")
