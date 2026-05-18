"""0G Storage wrapper — Python ↔ TypeScript bridge.

The official 0G SDK is `@0gfoundation/0g-ts-sdk` (Node.js). We talk to it via
`scripts/zerog/zerog_helper.mjs` over a single-shot subprocess with stdin/stdout
JSON, which keeps the integration boundary tiny and avoids a long-lived bridge
process.

Three modes:

- `merkle_root(blob)` → root_hash (offline; no RPC, no signer, no gas)
- `upload(blob)` → (root_hash, tx_hash) (requires funded testnet wallet)
- `download(root_hash)` → blob

`merkle_root` is what we use for *log-line traces* and *envelope previews* —
the rootHash is the same the indexer will return on upload, so log lines are
correlatable across the persistence boundary before persistence completes.
"""
from __future__ import annotations

import base64
import json
from typing import Any
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


# Helper script — repo-relative
_HELPER = Path(__file__).resolve().parent.parent / "scripts" / "zerog" / "zerog_helper.mjs"

DEFAULT_EVM_RPC = "https://evmrpc-testnet.0g.ai"
DEFAULT_INDEXER_RPC = "https://indexer-storage-testnet-turbo.0g.ai"


@dataclass(frozen=True)
class ZeroGConfig:
    private_key: str | None
    evm_rpc: str
    indexer_rpc: str

    @classmethod
    def from_env(cls) -> "ZeroGConfig":
        return cls(
            private_key=os.environ.get("ZEROG_PRIVATE_KEY") or None,
            evm_rpc=os.environ.get("ZEROG_RPC_URL", DEFAULT_EVM_RPC),
            indexer_rpc=os.environ.get("ZEROG_INDEXER_URL", DEFAULT_INDEXER_RPC),
        )


@dataclass(frozen=True)
class UploadResult:
    root_hash: str
    tx_hash: str
    bytes_uploaded: int


class ZeroGError(RuntimeError):
    pass


def _call_helper(cmd: dict[str, Any], timeout_s: float = 60.0) -> dict[str, Any]:
    """Send a JSON command to zerog_helper.mjs and parse the JSON response.

    The helper exits with code 0 on success, 1 on failure. On failure, stdout
    contains `{"error": "..."}` which we surface as a ZeroGError.
    """
    if not _HELPER.exists():
        raise ZeroGError(f"helper script not found: {_HELPER}")
    proc = subprocess.run(
        ["node", str(_HELPER)],
        input=json.dumps(cmd).encode("utf-8"),
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    raw = proc.stdout.decode().strip()
    if not raw:
        stderr = proc.stderr.decode().strip()
        raise ZeroGError(f"helper produced no output (exit={proc.returncode}, stderr={stderr!r})")
    try:
        result: dict[str, Any] = json.loads(raw.splitlines()[-1])
    except json.JSONDecodeError as e:
        raise ZeroGError(f"helper produced non-JSON output: {raw!r} ({e})")
    if "error" in result:
        raise ZeroGError(f"helper failed: {result['error']}")
    if proc.returncode != 0:
        raise ZeroGError(f"helper exited {proc.returncode}: {result}")
    return result


# ───────────────────────── public API ─────────────────────────


def merkle_root(blob: bytes) -> str:
    """Compute the 0G Merkle rootHash for a blob *offline*.

    No RPC, no signer, no gas. Useful for previewing what the indexer will
    return, and for log-line correlation before persistence completes.
    """
    result = _call_helper({"op": "merkle_root", "data_b64": base64.b64encode(blob).decode()})
    return str(result["root_hash"])


def wallet_info(config: ZeroGConfig | None = None) -> dict[str, Any]:
    """Get balance + chain ID for the configured wallet."""
    cfg = config or ZeroGConfig.from_env()
    if not cfg.private_key:
        raise ZeroGError("ZEROG_PRIVATE_KEY not set")
    return _call_helper(
        {"op": "wallet_info", "private_key": cfg.private_key, "evm_rpc": cfg.evm_rpc}
    )


def upload(blob: bytes, config: ZeroGConfig | None = None) -> UploadResult:
    """Upload bytes to 0G Storage. Requires funded testnet wallet."""
    cfg = config or ZeroGConfig.from_env()
    if not cfg.private_key:
        raise ZeroGError("ZEROG_PRIVATE_KEY not set — fund testnet wallet first")
    result = _call_helper(
        {
            "op": "upload",
            "data_b64": base64.b64encode(blob).decode(),
            "private_key": cfg.private_key,
            "evm_rpc": cfg.evm_rpc,
            "indexer_rpc": cfg.indexer_rpc,
        },
        timeout_s=180.0,
    )
    return UploadResult(
        root_hash=result["root_hash"],
        tx_hash=result["tx_hash"],
        bytes_uploaded=result["bytes_uploaded"],
    )


def download(root_hash: str, config: ZeroGConfig | None = None) -> bytes:
    """Fetch bytes from 0G Storage by Merkle rootHash."""
    cfg = config or ZeroGConfig.from_env()
    result = _call_helper(
        {"op": "download", "root_hash": root_hash, "indexer_rpc": cfg.indexer_rpc},
        timeout_s=120.0,
    )
    return base64.b64decode(result["data_b64"])
