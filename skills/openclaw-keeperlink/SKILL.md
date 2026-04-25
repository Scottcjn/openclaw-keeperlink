---
name: openclaw-keeperlink
description: Post a swap job over Gensyn AXL, settle onchain via KeeperHub + Uniswap, persist receipt on 0G Storage, return both proofs. Use when an OpenClaw agent needs to ask another agent to perform a paid onchain action and get a verifiable, audit-traceable receipt back. Triggers on intents like "swap X USDC for Y on Base", "post a paid job to peer", "verify a KeeperLink receipt".
---

# OpenClaw KeeperLink — Skill

Post a job from one OpenClaw agent (Node A) to another (Node B) over Gensyn AXL with x402 payment, have Node B settle the request onchain via KeeperHub + Uniswap, and persist the receipt to 0G Storage. Node A receives a dual-verifiable receipt back over the same AXL request/response cycle.

## When to use this skill

- The user asks an OpenClaw agent to perform a paid onchain action *via another agent*, not directly from itself
- Decentralized agent commerce — A pays B in USDC for an action B executes
- Audit-traceable execution where the receipt must be both onchain-verifiable AND content-addressed (independent of any single chain)
- Demo / hackathon context for ETHGlobal Open Agents

## What this skill does NOT do

- Execute swaps directly from the calling agent's wallet (use the `uniswap` skill for self-swap)
- Bridge assets between chains (use a dedicated bridge skill)
- Manage long-lived workflows (use KeeperHub MCP `ai_generate_workflow` for that)

## Subcommands

| Command | What it does |
|---|---|
| `/openclaw-keeperlink status` | Confirms AXL connectivity, peer reachability, KeeperHub auth, and 0G testnet RPC. Prints a health summary. |
| `/openclaw-keeperlink post-job --intent "<NL intent>"` | Posts a job to a configured peer, prints tx hash + 0G rootHash on receipt. |
| `/openclaw-keeperlink check-receipts` | Lists recent receipts received by Node A, dual-verifies each (onchain + 0G content-address). |
| `/openclaw-keeperlink verify <rootHash>` | Pulls a receipt from 0G by Merkle rootHash and re-verifies its onchain tx. |

## Failure modes (non-fatal philosophy)

Following Gensyn's `collaborative-autoresearch-demo` pattern:

- AXL peer unreachable → log + continue (return structured "peer_offline" error, don't crash)
- KeeperHub retry budget exhausted → surface KeeperHub's audit ref, abort cleanly
- x402 payment verification fails → 402 response with structured reason, no execution
- 0G upload timeout → tx receipt still returned over AXL; 0G persistence retried in background

The skill never crashes mid-demo. Every error path returns a structured result the calling agent can reason about.

## Implementation

See `keeperlink_client.py` for the glue code. The skill wraps:
- `shared/axl_client.py` — AXL transport + MCP framing
- `shared/keeperhub.py` — Direct Execution API + MCP fallback
- `shared/uniswap.py` — Trading API quote + swap intent
- `shared/zerog.py` — 0G upload + Merkle verification
- `shared/x402.py` — Payment header sign/verify
