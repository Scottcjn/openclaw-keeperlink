# SPDX-License-Identifier: MIT
"""CLI entrypoint for the openclaw-keeperlink skill.

The skill stays thin on purpose: it reuses Node A's poster machinery for job
posting and receipt verification so the demo path and the CLI path never drift.
Every command prints structured JSON and returns cleanly, even on integration
failures.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from shared.keeperhub import KeeperHubClient
from shared.schemas import Receipt
from shared.zerog import ZeroGConfig


REPO_ROOT = Path(__file__).resolve().parents[2]
POSTER_PATH = REPO_ROOT / "node-a" / "poster.py"


class HealthReport(BaseModel):
    axl_node_a_reachable: bool
    axl_node_b_reachable: bool
    keeperhub_auth_ok: bool
    zerog_rpc_ok: bool
    axl_url: str | None = None
    zerog_block_number: str | None = None
    notes: list[str] = Field(default_factory=list)


class ReceiptCheckResult(BaseModel):
    total_entries: int
    verified_entries: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class VerifyCommandResult(BaseModel):
    root_hash: str
    zerog_verification: dict[str, Any]
    onchain_verification: dict[str, Any] | None = None
    envelope: dict[str, Any] | None = None


def _print_json(data: BaseModel | dict[str, Any]) -> None:
    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    print(json.dumps(payload, indent=2, sort_keys=True))


def _load_poster_module() -> Any:
    spec = importlib.util.spec_from_file_location("keeperlink_poster", POSTER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load poster module from {POSTER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _probe_http_endpoint(url: str, timeout_s: float = 5.0) -> bool:
    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(url)
        return response.status_code < 500
    except Exception:
        return False


def _probe_keeperhub() -> tuple[bool, str | None]:
    try:
        with KeeperHubClient() as keeperhub:
            response = keeperhub._client.get("/chains")
            response.raise_for_status()
            return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _probe_zerog_rpc() -> tuple[bool, str | None, str | None]:
    cfg = ZeroGConfig.from_env()
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(cfg.evm_rpc, json=payload)
            response.raise_for_status()
            data = response.json()
        if data.get("error"):
            return False, None, str(data["error"])
        return True, str(data.get("result")), None
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)


def cmd_status() -> int:
    """Print health summary for each integration. No state-changing calls."""
    notes: list[str] = []
    poster = _load_poster_module()
    poster_config = poster.PosterConfig.from_env()

    axl_url: str | None = None
    axl_node_a_reachable = False
    for candidate in poster.candidate_axl_urls(poster_config):
        if _probe_http_endpoint(candidate):
            axl_url = candidate
            axl_node_a_reachable = True
            break
    if not axl_node_a_reachable:
        notes.append("No candidate Node A AXL HTTP endpoint responded.")

    axl_node_b_reachable = False
    if poster_config.axl_node_b_peer:
        discovery = poster.discover_peer(poster_config)
        axl_node_b_reachable = bool(discovery.ok and discovery.discovery)
        if not axl_node_b_reachable:
            notes.append(discovery.error or "Node B discovery over AXL failed.")
        elif not axl_url:
            axl_url = discovery.axl_url
    else:
        notes.append("AXL_NODE_B_PEER is not set, so cross-peer discovery was skipped.")

    keeperhub_auth_ok, keeperhub_error = _probe_keeperhub()
    if keeperhub_error:
        notes.append(f"KeeperHub auth probe failed: {keeperhub_error}")

    zerog_rpc_ok, block_number, zerog_error = _probe_zerog_rpc()
    if zerog_error:
        notes.append(f"0G RPC probe failed: {zerog_error}")

    report = HealthReport(
        axl_node_a_reachable=axl_node_a_reachable,
        axl_node_b_reachable=axl_node_b_reachable,
        keeperhub_auth_ok=keeperhub_auth_ok,
        zerog_rpc_ok=zerog_rpc_ok,
        axl_url=axl_url,
        zerog_block_number=block_number,
        notes=notes,
    )
    _print_json(report)
    return 0


def cmd_post_job(intent: str) -> int:
    poster = _load_poster_module()
    result = poster.run_poster_job(intent_override=intent)
    _print_json(result)
    return 0


def cmd_check_receipts() -> int:
    poster = _load_poster_module()
    log_path = Path(
        os.environ.get("KEEPERLINK_RECEIPT_LOG", str(poster.DEFAULT_RECEIPT_LOG))
    ).expanduser()
    entries = poster.load_receipt_log(log_path, limit=int(os.environ.get("KEEPERLINK_RECEIPT_LIMIT", "20")))
    verified_entries: list[dict[str, Any]] = []
    notes: list[str] = []

    if not entries:
        notes.append(f"No receipts found at {log_path}")
    for entry in entries:
        verified = poster.verify_log_entry(entry)
        verified_entries.append(
            {
                "recorded_at_unix": entry.recorded_at_unix,
                "job_id": verified.job.job_id if verified.job else None,
                "status": verified.status,
                "ok": verified.ok,
                "error_kind": verified.error_kind,
                "error": verified.error,
                "receipt": verified.receipt.model_dump(mode="json") if verified.receipt else None,
                "verification": verified.verification.model_dump(mode="json") if verified.verification else None,
                "audit_envelope_hash": verified.audit_envelope_hash,
            }
        )

    report = ReceiptCheckResult(
        total_entries=len(entries),
        verified_entries=verified_entries,
        notes=notes,
    )
    _print_json(report)
    return 0


def cmd_verify(root_hash: str) -> int:
    poster = _load_poster_module()
    zerog_result = poster.verify_envelope_root(root_hash)

    onchain_verification: dict[str, Any] | None = None
    envelope_dump: dict[str, Any] | None = None
    if zerog_result.envelope is not None:
        envelope = zerog_result.envelope
        envelope_dump = envelope.model_dump(mode="json")
        synthetic_receipt = Receipt(
            job_id=envelope.job.job_id,
            status="success",
            tx_hash=envelope.onchain.tx_hash,
            tx_link=envelope.onchain.tx_link,
            chain=envelope.job.chain,
            amount_in=envelope.job.amount_in,
            amount_out=envelope.onchain.amount_out,
            gas_used_wei=envelope.onchain.gas_used_wei,
            settled_at=envelope.onchain.settled_at_unix,
            keeperhub_audit_ref=envelope.keeperhub.execution_id,
            zerog_root_hash=root_hash,
        )
        onchain = poster.verify_onchain(
            envelope.job,
            synthetic_receipt,
            poster.PosterConfig.from_env(),
        )
        onchain_verification = onchain.model_dump(mode="json")

    result = VerifyCommandResult(
        root_hash=root_hash,
        zerog_verification=zerog_result.verification.model_dump(mode="json"),
        onchain_verification=onchain_verification,
        envelope=envelope_dump,
    )
    _print_json(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openclaw-keeperlink")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")

    p_post = sub.add_parser("post-job")
    p_post.add_argument("--intent", required=True)

    sub.add_parser("check-receipts")

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("root_hash")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "status":
            return cmd_status()
        if args.cmd == "post-job":
            return cmd_post_job(args.intent)
        if args.cmd == "check-receipts":
            return cmd_check_receipts()
        if args.cmd == "verify":
            return cmd_verify(args.root_hash)
    except Exception as exc:  # noqa: BLE001 - never crash mid-demo
        _print_json(
            {
                "ok": False,
                "status": "error",
                "error_kind": "unexpected_exception",
                "error": str(exc),
            }
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
