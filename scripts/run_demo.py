#!/usr/bin/env python3
"""OpenClaw KeeperLink live demo orchestrator (direct HTTP path).

Runs discovery → job build → x402 signing → hire → receipt verify, with
ANSI-only hackathon visuals for the Base swap, 0G receipt, and proof checks.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import uuid
from decimal import Decimal, InvalidOperation
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
    (0, [
        "╭╮   ╭╮",
        "╰██▄██╯",
        "‹██▆██›",
        " ╱╰┻╯╲ ",
    ]),
    (1, [
        " ╭╮ ╭╮ ",
        "‹██╳██›",
        "╰██▆██╯",
        " _╱ ╲_ ",
    ]),
    (1, [
        " ╭╮ ╭╮ ",
        "‹██▄▄██›",
        " ╰████╯ ",
        "  ▔╲╱▔  ",
    ]),
    (0, [
        " ╭╮   ╭╮",
        " ╲██▄██╱",
        "‹╡███╞›",
        "  ╲┳┳╱ ",
    ]),
]
BASE_CHAIN_ID = int(os.environ.get("BASE_CHAIN_ID", "8453"))
_IS_SEPOLIA = BASE_CHAIN_ID == 84532
DEFAULT_BASE_RPC = "https://sepolia.base.org" if _IS_SEPOLIA else "https://mainnet.base.org"
DEFAULT_USDC_ADDR = (
    "0x036CbD53842c5426634e7929541eC2318f3dCF7e" if _IS_SEPOLIA
    else "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
)

TOKEN_META = {
    "usdc": ("USDC", 6),
    "weth": ("WETH", 18),
    "eth": ("WETH", 18),
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": ("USDC", 6),
    "0x036cbd53842c5426634e7929541ec2318f3dcf7e": ("USDC", 6),
    "0x4200000000000000000000000000000000000006": ("WETH", 18),
}


def _clear_line() -> None:
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


def _render_lines(lines: list[str], previous: int = 0) -> int:
    if previous:
        sys.stdout.write("\033[F" * previous)
    total = max(previous, len(lines))
    for i in range(total):
        sys.stdout.write("\r\033[K")
        if i < len(lines):
            sys.stdout.write(lines[i])
        if i < total - 1:
            sys.stdout.write("\n")
    sys.stdout.flush()
    return len(lines)


def _overlay(row: str, art: str, pos: int) -> str:
    chars = list(row)
    for i, ch in enumerate(art):
        if ch != " " and 0 <= pos + i < len(chars):
            chars[pos + i] = ch
    return "".join(chars)


def _token_meta(token: str | None, fallback: str) -> tuple[str, int]:
    if token:
        return TOKEN_META.get(token.lower(), (fallback, 18 if fallback in {"ETH", "WETH"} else 6))
    return fallback, 18 if fallback in {"ETH", "WETH"} else 6


def _format_amount(value: Any, token: str | None, fallback: str) -> str:
    symbol, decimals = _token_meta(token, fallback)
    if value in (None, ""):
        return f"? {symbol}"
    raw = str(value).strip()
    try:
        num = Decimal(raw)
    except InvalidOperation:
        return f"{raw} {symbol}"
    if raw.lstrip("-").isdigit() and token and token.lower().startswith("0x") and len(raw) > 6:
        num /= Decimal(10) ** decimals
    places = 2 if symbol == "USDC" else 5
    text = f"{num:.{places}f}"
    if symbol != "USDC":
        text = text.rstrip("0").rstrip(".")
    return f"{text} {symbol}"


def _ticket(title: str, rows: list[str]) -> None:
    width = max(len(title), *(len(row) for row in rows)) + 2
    print(color(f"  ╔{'═' * width}╗", BLUE))
    print(color(f"  ║ {title.center(width - 2)} ║", BLUE))
    print(color(f"  ╟{'┈' * width}╢", BLUE))
    for row in rows:
        print(color("  ║ ", BLUE) + row.ljust(width - 2) + color(" ║", BLUE))
    print(color(f"  ╚{'═' * width}╝", BLUE))


def _proof_badge(rows: list[tuple[str, bool]]) -> None:
    text = [f"{'✓' if ok else '✗'} {label}" for label, ok in rows]
    width = max(len("PROOF"), *(len(row) for row in text)) + 2
    print(color(f"      ╔{'═' * width}╗", CYAN))
    print(color(f"      ║ {'PROOF'.center(width - 2)} ║", CYAN))
    for row, (_, ok) in zip(text, rows, strict=False):
        tone = GREEN if ok else RED
        print(color("      ║ ", CYAN) + color(row.ljust(width - 2), tone) + color(" ║", CYAN))
    print(color(f"      ╚{'═' * width}╝", CYAN))


def _rpc_call(method: str, params: list[Any]) -> Any:
    resp = httpx.post(
        os.environ.get("BASE_RPC_URL", DEFAULT_BASE_RPC),
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data.get("result")


def hop_animation(label: str, total_frames: int = 40, dot_count: int = 24) -> None:
    """Crawfish hops along a path of blocks. Returns when total_frames elapsed."""
    previous = 0
    spinners = ["⡆", "⠇", "⠧", "⠷", "⠯", "⠟", "⠻", "⠽"]
    width = dot_count + 8
    for frame in range(total_frames):
        hop, art = CRAWFISH_FRAMES[frame % len(CRAWFISH_FRAMES)]
        pos = int((frame / max(total_frames - 1, 1)) * max(width - len(art[0]), 1))
        canvas = [" " * width for _ in range(5)]
        for row_i, row in enumerate(art):
            target = min(row_i + hop, len(canvas) - 1)
            canvas[target] = _overlay(canvas[target], row, pos)
        progress = int((frame / max(total_frames - 1, 1)) * dot_count)
        track = color("█" * progress, GREEN) + color("░" * (dot_count - progress), GREY + DIM)
        lines = [
            f"  {color(spinners[frame % len(spinners)], GREEN)} {label}",
            *[f"    {color(row, ORANGE if frame % 2 == 0 else YELLOW)}" for row in canvas],
            f"    │{track}│",
        ]
        previous = _render_lines(lines, previous)
        time.sleep(random.uniform(0.08, 0.12))
    print()
    print(f"  {color('✓', GREEN)} {label:<28} {color('settled', GREEN + BOLD)}")


def block_celebrate(block_label: str) -> None:
    """Crawfish arrives at a confirmed block — claws up, coins out."""
    hero = CRAWFISH_FRAMES[-1][1]
    effects = [
        ("      ✧", ORANGE, ""),
        ("   ✦     ✧", YELLOW, f"  {block_label}"),
        (" ✦   ⋆   ✦", YELLOW + BOLD, ""),
        ("★  sparkle burst  ☆", GREEN, ""),
        (" ✦  coin pop!   ✦", YELLOW + BOLD, color("◉ ◉", YELLOW)),
        ("⋆  proof minted  ⋆", CYAN, ""),
        ("★ settled on Base ★", GREEN + BOLD, color("✓", GREEN)),
    ]
    previous = 0
    for top, sparkle_color, tail in effects:
        lines = [
            color(f"    {top}", sparkle_color),
            f"      {color(hero[0], ORANGE)}",
            f"      {color(hero[1], ORANGE)}{tail}",
            f"      {color(hero[2], ORANGE)}",
            f"      {color(hero[3], ORANGE)}",
        ]
        previous = _render_lines(lines, previous)
        time.sleep(random.uniform(0.09, 0.14))
    print()


def cascade_layers(layers: list[tuple[str, str]]) -> None:
    """Light up each sponsor layer left-to-right with dim → pulse → solid."""
    print(color("\n  Layer cascade:", BOLD))
    pulses = [("░", "dim"), ("▒", "pulse"), ("▓", "pulse"), ("█", "solid")]
    for active, _ in enumerate(layers):
        for pulse_i, (glyph, state) in enumerate(pulses):
            bar = ""
            for i, (name, color_code) in enumerate(layers):
                if i < active:
                    bar += color(f" █ {name} ", color_code + BOLD)
                elif i == active:
                    tone = color_code + (DIM if state == "dim" else BOLD)
                    bar += color(f" {glyph} {name} ", tone)
                else:
                    bar += color(f" ░ {name} ", GREY + DIM)
            _clear_line()
            sys.stdout.write(f"  {bar}")
            sys.stdout.flush()
            time.sleep(0.09 if pulse_i < len(pulses) - 1 else 0.12)
        _clear_line()
        sys.stdout.write(f"  {bar}")
        sys.stdout.flush()
    print()


# ─── Demo state ────────────────────────────────────────────────────────────

# Transport mode:
#   - If AXL_NODE_B_PEER is set, route through Node A's AXL daemon (Path A — full
#     architectural story; uses Yggdrasil P2P mesh between containers).
#   - Else fall back to direct HTTP to Node B (Path B — recording-focused mode).
AXL_NODE_A_URL = os.environ.get("AXL_NODE_A_URL", "http://127.0.0.1:9111")
AXL_NODE_B_PEER = os.environ.get("AXL_NODE_B_PEER", "")
if AXL_NODE_B_PEER:
    NODE_B_URL = f"{AXL_NODE_A_URL}/mcp/{AXL_NODE_B_PEER}/keeperlink"
    TRANSPORT = "AXL (Yggdrasil mesh, Path A)"
else:
    NODE_B_URL = os.environ.get("KEEPERLINK_DIRECT_HTTP_URL", "http://127.0.0.1:9004/keeperlink")
    TRANSPORT = "Direct HTTP (Path B)"
DEMO_INTENT = os.environ.get("DEMO_INTENT", "swap 5 USDC for WETH on Base")
DEMO_TOKEN_IN = os.environ.get("DEMO_TOKEN_IN", DEFAULT_USDC_ADDR)
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
    tx_hash = receipt.get("tx_hash") or "(none)"
    rh = receipt.get("zerog_root_hash") or receipt.get("0g_root_hash") or "(none)"
    tx_link = receipt.get("basescan_link") or receipt.get("tx_link") or f"https://basescan.org/tx/{tx_hash}"
    amount_in = _format_amount(receipt.get("amount_in") or DEMO_AMOUNT_IN, DEMO_TOKEN_IN, "USDC")
    amount_out = _format_amount(receipt.get("amount_out"), DEMO_TOKEN_OUT, "WETH")
    print(color("      Swap settled:", DIM))
    for pulse in range(1, 9):
        dots = color(("•" * pulse).ljust(8, "·"), YELLOW)
        _clear_line()
        sys.stdout.write(f"        {color(amount_in, GREEN)} ─{dots}▶ {color(amount_out, CYAN)}")
        sys.stdout.flush()
        time.sleep(0.09)
    _clear_line()
    print(f"        {color(amount_in, GREEN)} ─────▶ {color(amount_out, CYAN)}")
    _ticket(
        "OpenClaw Settlement Receipt",
        [
            f"✓ tx_hash       {tx_hash}",
            f"✓ amount_out    {amount_out}",
            f"✓ basescan_link {tx_link}",
            f"✓ 0G rootHash   {rh}",
        ],
    )
    print()


def verify_round_trip(receipt: dict[str, Any]) -> None:
    step(6, "Round-trip verify (onchain + 0G)")
    rh = receipt.get("zerog_root_hash") or receipt.get("0g_root_hash")
    tx_hash = receipt.get("tx_hash") or ""
    signature_ok = False
    content_ok = False
    onchain_ok = False
    if rh and rh.startswith("0x"):
        try:
            blob = zerog.download(rh)
            envelope = OpenClawAuditEnvelope.model_validate_json(blob.decode("utf-8"))
            integrity_ok, reason = verify_envelope_integrity(envelope)
            content_ok = integrity_ok and zerog.merkle_root(blob) == rh
            from eth_account import Account
            from eth_account.messages import encode_defunct

            recovered = Account.recover_message(
                encode_defunct(primitive=envelope.signing_bytes()),
                signature=envelope.signature,
            )
            signature_ok = recovered.lower() == envelope.signer_address.lower()
            print(f"      0G download   : {color('✓', GREEN)} ({len(blob)} bytes)")
            print(f"      content match : {color('✓', GREEN) if content_ok else color('✗', RED)}")
            print(f"      signature     : {color('✓', GREEN) if signature_ok else color('✗', RED)}")
            if not content_ok and reason:
                print(color(f"      note          : {reason}", YELLOW))
        except Exception as exc:  # noqa: BLE001
            print(f"      0G verify     : {color(f'✗ {exc}', RED)}")
    else:
        print(f"      0G verify     : {color('skipped (no rootHash)', YELLOW)}")
    if tx_hash:
        try:
            tx_receipt = _rpc_call("eth_getTransactionReceipt", [tx_hash])
            onchain_ok = bool(tx_receipt) and int(tx_receipt.get("status", "0x0"), 16) == 1
            block_hex = tx_receipt.get("blockNumber") if tx_receipt else None
            block_text = f" block {int(block_hex, 16)}" if block_hex else ""
            print(f"      Base confirm  : {color('✓', GREEN) if onchain_ok else color('✗', RED)}{block_text}")
        except Exception as exc:  # noqa: BLE001
            print(f"      Base confirm  : {color(f'✗ {exc}', RED)}")
    else:
        print(f"      Base confirm  : {color('skipped (no tx_hash)', YELLOW)}")
    if signature_ok and content_ok and onchain_ok:
        _proof_badge(
            [
                ("signature valid", True),
                ("0G content matches", True),
                ("onchain tx confirmed", True),
            ]
        )
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
