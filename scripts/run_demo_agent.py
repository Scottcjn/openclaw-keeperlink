#!/usr/bin/env python3
"""Live LLM-driven agent demo for OpenClaw KeeperLink.

Distinct from `run_demo.py` (deterministic orchestrator). Here, an actual LLM
(Claude Sonnet 4.6 via Abacus router) reasons about a high-level swap intent,
calls tools wrapping the real OpenClaw service, and decides when to spend real
USDC. The on-screen output shows the agent's thinking + tool invocations
verbatim — proof that "agent" is not a marketing label here.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx


# ─── Styling ───────────────────────────────────────────────────────────────
RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
CYAN, GREEN, YELLOW, PURPLE, GREY = "\033[36m", "\033[32m", "\033[33m", "\033[35m", "\033[38;5;245m"


# ─── Config ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
ABACUS_TOKEN_PATH = Path.home() / ".config" / "abacus" / "api_token"
LLM_MODEL = "claude-sonnet-4-6"
LLM_URL = "https://routellm.abacus.ai/v1/chat/completions"


def _load_env() -> None:
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

ABACUS_TOKEN = ABACUS_TOKEN_PATH.read_text().strip()
KH_WALLET = os.environ.get("KEEPERHUB_WALLET_ADDRESS", "0xe12230149b2d5ed561fa51261fb8e02dbd514724")
NODE_B_PEER = os.environ.get("AXL_NODE_B_PEER", "")
AXL_NODE_A_PORT = int(os.environ.get("AXL_NODE_A_PORT", "9111"))
BASE_RPC = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")
BASE_CHAIN_ID = int(os.environ.get("BASE_CHAIN_ID", "8453"))

# Hard-stop: this script will only allow ONE real on-chain hire per invocation.
# Prevents an LLM that's confused or over-eager from racking up real charges.
HIRE_BUDGET = {"remaining": 1, "spent": []}

# Token registry (mainnet defaults; orchestrator overrides if needed)
TOKENS = {
    "USDC": {"address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "decimals": 6},
    "WETH": {"address": "0x4200000000000000000000000000000000000006", "decimals": 18},
}


# ─── Tools (real implementations called by the LLM) ────────────────────────
def discover_executor() -> dict:
    """Ask the AXL mesh for available KeeperLink executors + their pricing."""
    if not NODE_B_PEER:
        return {"error": "AXL_NODE_B_PEER not set in environment"}
    url = f"http://127.0.0.1:{AXL_NODE_A_PORT}/mcp/{NODE_B_PEER}/keeperlink"
    try:
        r = httpx.post(url, json={"kind": "discover"}, timeout=10)
        return r.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"AXL discovery failed: {exc}"}


def get_market_quote(token_in: str, token_out: str, amount_in_atomic: str,
                     chain_id: int = 8453) -> dict:
    """Get a Uniswap quote via the official Trading API."""
    api_key = os.environ.get("UNISWAP_API_KEY", "")
    api_base = os.environ.get("UNISWAP_API_BASE", "https://trade-api.gateway.uniswap.org")
    if not api_key:
        return {"error": "UNISWAP_API_KEY not set"}
    body = {
        "tokenIn": token_in,
        "tokenOut": token_out,
        "amount": amount_in_atomic,
        "tokenInChainId": chain_id,
        "tokenOutChainId": chain_id,
        "type": "EXACT_INPUT",
        "swapper": KH_WALLET,
    }
    try:
        r = httpx.post(f"{api_base}/v1/quote", json=body,
                       headers={"x-api-key": api_key, "Content-Type": "application/json"},
                       timeout=15)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "body": r.text[:300]}
        data = r.json()
        # Uniswap returns {"quote": {...}, "routing": "...", ...}.
        # Inside `route` is a list-of-lists: each outer entry is a path option,
        # each inner entry is a hop in that path. We summarize the first path.
        quote = data.get("quote", data)
        route = quote.get("route", [])
        first_path = route[0] if route and isinstance(route[0], list) else route
        hops = [h.get("type", "?") for h in first_path if isinstance(h, dict)][:4]
        return {
            "input_atomic": str(quote.get("input", {}).get("amount", amount_in_atomic)),
            "output_atomic": str(quote.get("output", {}).get("amount", "")),
            "output_token": quote.get("output", {}).get("token", token_out),
            "gas_use_estimate": str(quote.get("gasUseEstimate", "")),
            "route_summary": hops,
            "routing": data.get("routing", ""),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def verify_balance(wallet: str, token: str = "USDC") -> dict:
    """Read on-chain ERC-20 balance via independent RPC."""
    info = TOKENS.get(token.upper())
    if not info:
        return {"error": f"unknown token: {token}"}
    body = {
        "jsonrpc": "2.0", "method": "eth_call",
        "params": [{"to": info["address"],
                    "data": "0x70a08231000000000000000000000000" + wallet[2:].lower()},
                   "latest"],
        "id": 1,
    }
    try:
        r = httpx.post(BASE_RPC, json=body, timeout=10).json()
        raw = int(r["result"], 16)
        human = raw / (10 ** info["decimals"])
        return {"wallet": wallet, "token": token.upper(),
                "balance_atomic": str(raw), "balance_human": f"{human:.6f}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def hire_agent_for_swap(intent: str, token_in: str, token_out: str,
                        amount_in_human: str) -> dict:
    """Pay the discovered executor to perform a real on-chain swap.

    HARD-LIMITED to one call per process. Spends REAL USDC.
    """
    if HIRE_BUDGET["remaining"] <= 0:
        return {"error": "hire budget exhausted (1 hire per process). prior calls: "
                + str(HIRE_BUDGET["spent"])}
    HIRE_BUDGET["remaining"] -= 1
    HIRE_BUDGET["spent"].append({"intent": intent, "amount": amount_in_human})

    env = os.environ.copy()
    env["DEMO_INTENT"] = intent
    env["DEMO_AMOUNT_IN"] = str(amount_in_human)
    env["DEMO_TOKEN_IN"] = token_in
    env["DEMO_TOKEN_OUT"] = token_out

    try:
        out = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "run_demo.py")],
            env=env, capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return {"error": "hire timed out at 180s"}

    txt = (out.stdout or "") + (out.stderr or "")
    # The orchestrator emits ANSI escapes for animations; strip before pattern-match.
    clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", txt)
    tx = re.search(r"0x[0-9a-fA-F]{64}", clean)
    rh = re.search(r"0G rootHash\s+(0x[0-9a-fA-F]{64})", clean)
    completed = "Demo complete" in clean
    return {
        "ok": completed and tx is not None,
        "tx_hash": tx.group(0) if tx else None,
        "zerog_root_hash": rh.group(1) if rh else None,
        "basescan_link": f"https://basescan.org/tx/{tx.group(0)}" if tx else None,
        "demo_completed_marker": completed,
    }


def verify_settlement(tx_hash: str) -> dict:
    """Independently confirm a tx settled on-chain via Base RPC."""
    body = {"jsonrpc": "2.0", "method": "eth_getTransactionReceipt",
            "params": [tx_hash], "id": 1}
    try:
        r = httpx.post(BASE_RPC, json=body, timeout=10).json()
    except Exception as exc:  # noqa: BLE001
        return {"settled": False, "error": str(exc)}
    receipt = r.get("result")
    if not receipt:
        return {"settled": False, "reason": "receipt not found"}
    return {
        "settled": int(receipt["status"], 16) == 1,
        "block_number": int(receipt["blockNumber"], 16),
        "gas_used": int(receipt["gasUsed"], 16),
        "explorer": f"https://basescan.org/tx/{tx_hash}",
    }


TOOL_FNS = {
    "discover_executor": discover_executor,
    "get_market_quote": get_market_quote,
    "verify_balance": verify_balance,
    "hire_agent_for_swap": hire_agent_for_swap,
    "verify_settlement": verify_settlement,
}


TOOLS_SCHEMA = [
    {"type": "function", "function": {
        "name": "discover_executor",
        "description": "Discover available executor agents on the AXL mesh. Returns service description, x402 pricing, and capabilities.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "get_market_quote",
        "description": "Get an official Uniswap quote (Trading API) for a swap. Use to validate the executor's pricing is reasonable BEFORE hiring.",
        "parameters": {"type": "object", "properties": {
            "token_in": {"type": "string", "description": "ERC-20 input token address"},
            "token_out": {"type": "string", "description": "ERC-20 output token address"},
            "amount_in_atomic": {"type": "string", "description": "Input amount in atomic units (e.g. 100000 = 0.1 USDC)"},
            "chain_id": {"type": "integer", "default": 8453},
        }, "required": ["token_in", "token_out", "amount_in_atomic"]},
    }},
    {"type": "function", "function": {
        "name": "verify_balance",
        "description": "Read on-chain ERC-20 balance for a wallet via Base RPC. Use to confirm the wallet can fund the swap.",
        "parameters": {"type": "object", "properties": {
            "wallet": {"type": "string"},
            "token": {"type": "string", "description": "Token symbol: USDC or WETH", "default": "USDC"},
        }, "required": ["wallet"]},
    }},
    {"type": "function", "function": {
        "name": "hire_agent_for_swap",
        "description": "Pay the executor to perform a real on-chain swap. SPENDS REAL USDC. Limited to ONE call per process. Use only after discover + quote + balance checks pass.",
        "parameters": {"type": "object", "properties": {
            "intent": {"type": "string", "description": "Plain-English description"},
            "token_in": {"type": "string"},
            "token_out": {"type": "string"},
            "amount_in_human": {"type": "string", "description": "Human-units decimal, e.g. '0.1' for 0.1 USDC"},
        }, "required": ["intent", "token_in", "token_out", "amount_in_human"]},
    }},
    {"type": "function", "function": {
        "name": "verify_settlement",
        "description": "Independently confirm a tx hash settled on-chain via Base RPC (not the executor's RPC).",
        "parameters": {"type": "object", "properties": {
            "tx_hash": {"type": "string"},
        }, "required": ["tx_hash"]},
    }},
]


SYSTEM_PROMPT = """You are an autonomous agent on the OpenClaw KeeperLink protocol.

Your job: fulfill the user's swap intent SAFELY on Base mainnet. You spend real USDC.

Operating rules:
1. Discover an executor on the mesh first — read its pricing.
2. Get a market quote so you know what the swap should cost.
3. Verify the wallet has enough balance to actually pay.
4. Only THEN hire the executor (this spends real money).
5. Independently verify the tx settled — never trust the executor's word alone.
6. End with a brief receipt: tx hash, basescan link, what changed.

Be CONCISE. Every word appears live on screen for a human watching. State what you're about to do in 1 sentence, call the tool, react to the result in 1 sentence. No filler."""


# ─── LLM driver ────────────────────────────────────────────────────────────
def chat(messages: list, tools: list) -> dict:
    body = {"model": LLM_MODEL, "messages": messages, "tools": tools, "temperature": 0.2}
    r = httpx.post(LLM_URL, json=body,
                   headers={"Authorization": f"Bearer {ABACUS_TOKEN}",
                            "Content-Type": "application/json"},
                   timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def _print_thought(text: str) -> None:
    for line in str(text).strip().splitlines():
        if line.strip():
            print(f"  {PURPLE}💭{RESET} {DIM}{line}{RESET}")


def _print_tool_call(name: str, args: dict) -> None:
    args_preview = json.dumps(args, separators=(", ", ": "))
    if len(args_preview) > 120:
        args_preview = args_preview[:117] + "..."
    print(f"  {CYAN}🔧 {BOLD}{name}{RESET}{CYAN}({args_preview}){RESET}")


def _print_tool_result(result: dict) -> None:
    if isinstance(result, dict) and "error" in result:
        print(f"  {YELLOW}↪{RESET} {YELLOW}error: {str(result['error'])[:200]}{RESET}\n")
        return
    preview = json.dumps(result, default=str, separators=(", ", ": "))
    if len(preview) > 380:
        preview = preview[:377] + "..."
    print(f"  {GREEN}↪{RESET} {GREY}{preview}{RESET}\n")


def main() -> int:
    intent = (
        f"Hire an executor on the OpenClaw mesh to swap 0.02 USDC for WETH on Base mainnet. "
        f"The KeeperHub-managed wallet address is {KH_WALLET}. Verify the discovery, the "
        f"market quote, and the wallet balance before hiring. After the swap, independently "
        f"confirm the tx settled on-chain. Report the receipt."
    )

    print()
    print(f"{BOLD}{CYAN}╔══ OpenClaw KeeperLink — live LLM agent ══════════════════╗{RESET}")
    print(f"{CYAN}║{RESET} Model:  {YELLOW}{LLM_MODEL}{RESET} via Abacus router")
    print(f"{CYAN}║{RESET} Tools:  {', '.join(TOOL_FNS.keys())}")
    print(f"{CYAN}║{RESET} Budget: 1 real on-chain hire (~0.10 USDC)")
    print(f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════════╝{RESET}")
    print()
    print(f"{BOLD}USER INTENT:{RESET}")
    print(f"  {DIM}{intent}{RESET}")
    print()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": intent},
    ]

    final_tx = None
    for turn in range(15):
        try:
            msg = chat(messages, TOOLS_SCHEMA)
        except Exception as exc:  # noqa: BLE001
            print(f"{YELLOW}LLM call failed: {exc}{RESET}")
            return 1

        # Append the model's message verbatim (with tool_calls intact)
        appended = {"role": "assistant", "content": msg.get("content") or ""}
        if msg.get("tool_calls"):
            appended["tool_calls"] = msg["tool_calls"]
        messages.append(appended)

        # Render the thought
        if msg.get("content"):
            _print_thought(msg["content"])

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            break

        for tc in tool_calls:
            fname = tc["function"]["name"]
            args_raw = tc["function"]["arguments"]
            if isinstance(args_raw, str):
                try:
                    fargs = json.loads(args_raw)
                except json.JSONDecodeError:
                    fargs = {}
            elif isinstance(args_raw, dict):
                fargs = args_raw
            else:
                fargs = {}
            _print_tool_call(fname, fargs)

            fn = TOOL_FNS.get(fname)
            if not fn:
                result = {"error": f"unknown tool: {fname}"}
            else:
                try:
                    result = fn(**fargs)
                except Exception as exc:  # noqa: BLE001
                    result = {"error": str(exc)}
            _print_tool_result(result)

            if fname == "hire_agent_for_swap" and isinstance(result, dict):
                final_tx = result.get("tx_hash") or final_tx

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result, default=str),
            })

    print()
    print(f"{BOLD}{GREEN}─── agent run complete ───{RESET}")
    if final_tx:
        print(f"  Real Base mainnet tx: {CYAN}https://basescan.org/tx/{final_tx}{RESET}")
    else:
        print(f"  {DIM}(no on-chain hire was made){RESET}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
