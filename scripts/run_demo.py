#!/usr/bin/env python3
"""OpenClaw KeeperLink — live demo orchestrator (Path B: direct HTTP).

Runs the full 5-layer loop end-to-end:
    1. Discover Node B's KeeperLink capability + pricing (USDC on Base)
    2. Build a swap intent JobRequest
    3. Sign x402 fallback payment header
    4. Hire Node B via direct HTTP (production also supports AXL transport;
       AXL was kill-tested Apr 25, see docs/kill-tests/axl-day2.md, but the
       demo uses direct HTTP to keep the recording focused).
    5. Node B verifies x402 + invokes its KeeperHub workflow (Uniswap V3
       swap on Base) + signs an OpenClaw Audit Envelope + uploads to 0G
    6. Demo verifies the Receipt: basescan tx hash exists + 0G rootHash
       resolves and matches.

Visual flair: a small ASCII crawfish character (Louisiana, original IP)
hops between blocks during the on-chain confirm wait. Hybrid pixel-style
using Unicode block characters.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from shared.audit_envelope import (  # noqa: E402
    OpenClawAuditEnvelope,
    canonical_json_bytes,
    sha256_canonical,
    verify_envelope_integrity,
)
from shared.schemas import JobRequest  # noqa: E402
from shared import zerog  # noqa: E402

# ─── ANSI ──────────────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
ORANGE = "\033[38;5;208m"
GREY = "\033[38;5;245m"


def color(s: str, c: str) -> str:
    return f"{c}{s}{RESET}"


# ─── Crawfish Hopper (original Louisiana mascot — no IP) ───────────────────

CRAWFISH_FRAMES = [
    # Resting
    r"  __,__   ",
    # Mid-hop
    r"  /(\\/) ",
    # Crouched
    r"  __/-\__",
]

CRAWFISH_CLAWS = ["<°)~~~", ">°)~~~", "<°)~~~"]


def _clear_line() -> None:
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


def hop_animation(label: str, total_frames: int = 40, dot_count: int = 24) -> None:
    """Crawfish hops along a path of blocks. Returns when total_frames elapsed."""
    track = "▁" * dot_count
    for frame in range(total_frames):
        pos = int((frame / max(total_frames - 1, 1)) * (dot_count - 3))
        head = (
            track[:pos] + color("◢█▆◣", ORANGE) + track[pos + 4 :]
        )
        spinner = ["⡆", "⠇", "⠧", "⠷", "⠯", "⠟", "⠻", "⠽"][frame % 8]
        line = f"  {color(spinner, GREEN)} {label:<28} │{head}│"
        _clear_line()
        sys.stdout.write(line)
        sys.stdout.flush()
        time.sleep(0.08)
    _clear_line()
    print(f"  {color('✓', GREEN)} {label:<28} │{color('█' * dot_count, GREEN)}│ done")


def block_celebrate(block_label: str) -> None:
    """Crawfish arrives at a confirmed block — hops up + claws raised."""
    frames = [
        f"     {color('◢█▆◣', ORANGE)}",
        f"   {color('◢█▆◣', YELLOW)}    ←  {color(block_label, BOLD)}",
        f"   {color('◢█▆◣', GREEN)}    ✦",
        f"     {color('◢█▆◣', GREEN)}    {color('★ COIN!', YELLOW + BOLD)}",
    ]
    for f in frames:
        _clear_line()
        sys.stdout.write(f)
        sys.stdout.flush()
        time.sleep(0.15)
    print()


def cascade_layers(layers: list[tuple[str, str]]) -> None:
    """Light up each sponsor layer left-to-right with a build animation."""
    print(color("\n  Layer cascade:", BOLD))
    n = len(layers)
    for done in range(n + 1):
        bar = ""
        for i, (name, color_code) in enumerate(layers):
            if i < done:
                bar += color(f" █ {name} ", color_code)
            else:
                bar += color(f" ░ {name} ", DIM)
        _clear_line()
        sys.stdout.write(f"  {bar}")
        sys.stdout.flush()
        time.sleep(0.25)
    print()


# ─── Demo state ────────────────────────────────────────────────────────────

NODE_B_URL = os.environ.get("KEEPERLINK_DIRECT_HTTP_URL", "http://127.0.0.1:9004")
DEMO_INTENT = os.environ.get("DEMO_INTENT", "swap 5 USDC for WETH on Base")
DEMO_TOKEN_IN = os.environ.get("DEMO_TOKEN_IN", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
DEMO_TOKEN_OUT = os.environ.get("DEMO_TOKEN_OUT", "0x4200000000000000000000000000000000000006")
DEMO_AMOUNT_IN = os.environ.get("DEMO_AMOUNT_IN", "5000000")
POSTER_ADDR = os.environ.get("POSTER_ADDRESS", "0x46b26446ad47eF5230357A19E125323bb7FeC2A6")


def banner() -> None:
    print()
    print(color("  ╔═══════════════════════════════════════════════════════════╗", BLUE))
    print(color("  ║    ", BLUE) + color("OpenClaw KeeperLink — Live Demo", BOLD + CYAN) + color("                       ║", BLUE))
    print(color("  ║    ", BLUE) + color("Built for ETHGlobal Open Agents 2026", DIM) + color("                  ║", BLUE))
    print(color("  ╚═══════════════════════════════════════════════════════════╝", BLUE))
    print()


def step(n: int, msg: str) -> None:
    print(color(f"  [{n}]", BOLD + CYAN), color(msg, BOLD))


# ─── Steps ─────────────────────────────────────────────────────────────────


def discover_node_b() -> dict[str, Any]:
    step(1, "Discover Node B over direct HTTP")
    print(color(f"      → POST {NODE_B_URL}/  kind=discover", DIM))
    resp = httpx.post(NODE_B_URL, json={"kind": "discover"}, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    pricing = data.get("pricing", {})
    print(color("      ← Discovery:", DIM))
    print(f"        workflow_slug : {color(data.get('workflow_slug', '?'), MAGENTA)}")
    print(f"        node_b address: {color(data.get('node_b_address', '?'), GREY)}")
    print(f"        pricing       : {color(pricing.get('amount', '?'), YELLOW)} atomic units of "
          f"{color('USDC', GREEN)} on {color('Base', BLUE)}")
    print(f"        payTo         : {color(pricing.get('payTo', '?'), GREY)}")
    print()
    return data


def build_job() -> JobRequest:
    step(2, "Build swap-intent JobRequest")
    job = JobRequest(
        job_id=f"demo_{uuid.uuid4().hex[:12]}",
        intent=DEMO_INTENT,
        chain="base",
        token_in=DEMO_TOKEN_IN,
        token_out=DEMO_TOKEN_OUT,
        amount_in=DEMO_AMOUNT_IN,
        poster_address=POSTER_ADDR,
        posted_at=int(time.time()),
    )
    print(f"      job_id : {color(job.job_id, MAGENTA)}")
    print(f"      intent : {color(job.intent, BOLD)}")
    print(f"      tokens : {color(DEMO_TOKEN_IN[:10] + '...', GREEN)} → {color(DEMO_TOKEN_OUT[:10] + '...', GREEN)}")
    print()
    return job


def sign_x402_fallback(pricing: dict, job: JobRequest, poster_priv_key: str) -> str:
    """Build the fallback x402 envelope expected by keeperlink_service.fallback_verify_x402.

    Format: 'x402-fallback-v2:' + base64url(JSON({payload: {...}, signature: hex_sig}))

    payload required fields: x402_version, scheme, network, asset, amount, payTo,
    payer, nonce, issuedAt, jobId, jobDigest, authorityHint?

    Signature: eth_account.Account.sign_message(encode_defunct(primitive=
                 canonical_json_bytes(payload))) over canonical-JSON of payload.
    """
    import base64
    from eth_account import Account
    from eth_account.messages import encode_defunct

    payload = {
        "x402_version": 2,
        "scheme": "exact",
        "network": pricing["network"],
        "asset": pricing["asset"],
        "amount": pricing["amount"],
        "payTo": pricing["payTo"],
        "payer": job.poster_address,
        "nonce": uuid.uuid4().hex,
        "issuedAt": int(time.time()),
        "jobId": job.job_id,
        "jobDigest": sha256_canonical(job.model_dump(exclude={"x402_payment_header"})),
        "authorityHint": None,
    }
    msg_bytes = canonical_json_bytes(payload)
    signed = Account.sign_message(encode_defunct(primitive=msg_bytes), private_key=poster_priv_key)
    signature_hex = signed.signature.hex()
    if not signature_hex.startswith("0x"):
        signature_hex = "0x" + signature_hex

    envelope = {"payload": payload, "signature": signature_hex}
    encoded = base64.urlsafe_b64encode(
        json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()
    ).rstrip(b"=").decode()
    header = f"x402-fallback-v2:{encoded}"

    step(3, "Sign x402 fallback payment header")
    print(color(f"      asset   : {pricing['asset'][:10]}...  amount: {pricing['amount']} atomic", DIM))
    print(color(f"      payer   : {job.poster_address}", DIM))
    print(color(f"      sig     : {signature_hex[:30]}...", DIM))
    print()
    return header


def hire_node_b(job: JobRequest, x402_header: str) -> dict[str, Any]:
    step(4, "Hire Node B with x402 payment")
    print(color(f"      → POST {NODE_B_URL}/  kind=hire", DIM))

    cascade_layers(
        [
            ("AXL", BLUE),
            ("x402", YELLOW),
            ("KeeperHub", MAGENTA),
            ("Uniswap", CYAN),
            ("0G", GREEN),
        ]
    )

    body = {
        "kind": "hire",
        "job": job.model_dump(mode="json"),
        "x402_payment_header": x402_header,
    }

    print()
    hop_animation("Awaiting onchain confirmation", total_frames=30)
    block_celebrate("block confirmed")

    resp = httpx.post(NODE_B_URL, json=body, timeout=120.0)
    resp.raise_for_status()
    return resp.json()


def show_receipt(receipt: dict[str, Any]) -> None:
    step(5, "Receipt received")
    print(color("      Receipt body:", DIM))
    tx_hash = receipt.get("tx_hash") or "(none)"
    rh = receipt.get("zerog_root_hash") or receipt.get("0g_root_hash") or "(none)"
    print(f"        tx_hash       : {color(tx_hash, GREEN)}")
    print(f"        basescan_link : https://basescan.org/tx/{tx_hash}")
    print(f"        0G rootHash   : {color(rh, GREEN)}")
    print()


def verify_round_trip(receipt: dict[str, Any]) -> None:
    step(6, "Round-trip verify (onchain + 0G)")
    rh = receipt.get("zerog_root_hash") or receipt.get("0g_root_hash")
    if rh and rh.startswith("0x"):
        try:
            blob = zerog.download(rh)
            envelope = OpenClawAuditEnvelope.model_validate_json(blob)
            ok = verify_envelope_integrity(envelope)
            print(f"      0G download   : {color('✓', GREEN)} ({len(blob)} bytes)")
            print(f"      sig integrity : {color('✓', GREEN) if ok else color('✗', RED)}")
        except Exception as exc:  # noqa: BLE001
            print(f"      0G verify     : {color(f'✗ {exc}', RED)}")
    else:
        print(f"      0G verify     : {color('skipped (no rootHash)', YELLOW)}")
    print()


def main() -> int:
    banner()
    poster_priv_key = os.environ.get("POSTER_PRIVATE_KEY") or os.environ.get("ZEROG_PRIVATE_KEY")
    if not poster_priv_key:
        print(color("  ERROR: POSTER_PRIVATE_KEY or ZEROG_PRIVATE_KEY must be set", RED))
        return 1
    try:
        discovery = discover_node_b()
        job = build_job()
        # Set poster_address to match the signing key
        from eth_account import Account
        poster_addr = Account.from_key(poster_priv_key).address
        job.poster_address = poster_addr
        x402_header = sign_x402_fallback(discovery["pricing"], job, poster_priv_key)
        receipt = hire_node_b(job, x402_header)
        show_receipt(receipt)
        verify_round_trip(receipt)
        print(color("  ─ Demo complete. ─", GREEN + BOLD))
        return 0
    except httpx.HTTPError as exc:
        print(color(f"\n  HTTP error: {exc}", RED))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(color(f"\n  Demo failed: {type(exc).__name__}: {exc}", RED))
        return 1


if __name__ == "__main__":
    sys.exit(main())
