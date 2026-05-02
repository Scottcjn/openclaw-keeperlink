# OpenClaw KeeperLink

> **P2P agent jobs that actually settle onchain.** Post over Gensyn AXL, pay via x402, execute via KeeperHub, swap on Uniswap V3, persist receipt on 0G Storage. No middlemen. No failed txs.

**Built for:** [ETHGlobal Open Agents](https://ethglobal.com/events/openagents) — Apr 24 → May 3, 2026
**Author:** [Scott Boudreaux](https://github.com/Scottcjn) / Elyan Labs (solo build)
**Demo video:** _link to be added at submission time_
**Live Base Sepolia tx (sample):** _to be added at submission time after demo run_
**0G receipt rootHash (sample):** _to be added at submission time after demo run_

---

## What we built (in plain English)

Imagine two AI assistants on different computers. Assistant A wants something done — say, swap $5 of one cryptocurrency for another. Instead of doing it itself, it sends a tiny payment to Assistant B (a paid specialist) and asks B to handle it. B does the swap on a real exchange, gets a receipt, and stores that receipt in a tamper-proof shared notebook anyone can verify.

**What's special:**
- **No middleman.** A and B talk directly, encrypted, peer-to-peer. No Stripe, no Uber, no broker between them.
- **The payment is built in.** A doesn't have to trust B, and B doesn't chase A for payment — the protocol settles it. (This is called **x402** — think "credit card swipe, but for AI agents.")
- **The action is real.** B's swap is an actual on-chain transaction on Base. It costs real money, settles in seconds, has a public transaction ID anyone can look up.
- **The receipt is tamper-proof.** After the swap, B saves a signed receipt to a decentralized storage network (**0G**). Anyone — A, a third party, or a court — can fetch the receipt later and verify it's exactly what B claimed.

**Why this matters:** today's "AI agent marketplaces" mostly fake the hard parts. They use centralized brokers, keep manual receipts, have silent failures, and the agents are really just LLM wrappers around one company's API. We built one where **every layer** — payment, transport, execution, audit — is decentralized infrastructure with no central operator.

Built for ETHGlobal Open Agents 2026 in 9.5 days, solo. The repo is the proof.

---

## 30-second read (technical)

Two AI agents on separate nodes coordinate over an encrypted P2P mesh — no central broker.

Agent A posts a job: *"swap 5 USDC for WETH on Base."*
Agent B claims it, verifies the **x402** payment header, calls **KeeperHub**'s MCP `execute_protocol_action(uniswap/swap-exact-input)` to run the swap on Base via the **Uniswap V3** plugin, signs an **OpenClaw Audit Envelope**, and persists it to **0G Storage** with content-addressed Merkle proof.

Agent A receives the receipt back over the same request/response cycle and verifies it two ways — onchain on Base, and by Merkle root on 0G.

One product. One demo. **Five sponsor integrations** in a single coherent loop.

---

## Sponsor integrations

| Sponsor | Role | Code entrypoint |
|---|---|---|
| **Gensyn AXL** | Live encrypted P2P transport — Yggdrasil mesh via 2 dockerized AXL daemons + MCP router sidecar. `keeperlink` service registered with the router, routable via `POST /mcp/{node_b_peer_id}/keeperlink` from Node A. Demo runs through AXL by default (set `AXL_NODE_B_PEER` env). | `docker-compose.yml`, `node-a/axl-config.json`, `node-b/axl-config.json`, `shared/axl_client.py` |
| **KeeperHub** | Reliable onchain execution (workflow API + MCP `execute_protocol_action`) + native x402 | `shared/keeperhub.py`, `node-b/keeperlink_service.py` |
| **Uniswap V3** | The actual swap on Base (via KeeperHub's `uniswap/swap-exact-input` action) | `shared/uniswap.py`, `node-b/keeperlink_service.py:call_keeperhub_workflow` |
| **0G Storage** | Permanent audit receipts (the framework primitive) | `shared/zerog.py`, `shared/audit_envelope.py` |
| **OpenClaw** | Agent framework + MCP glue + the OpenClaw Audit Envelope schema | `skills/openclaw-keeperlink/`, `shared/audit_envelope.py` |

---

## Quick start (judges)

```bash
git clone https://github.com/Scottcjn/openclaw-keeperlink.git
cd openclaw-keeperlink
cp .env.example .env
# Fill in API keys (see "API keys needed" below)
pip install -r requirements.txt
cd scripts/zerog && npm install && cd ../..

# Bring up the AXL daemon stack (Node A + Node B + MCP router)
docker compose up -d
# Read Node B's AXL peer ID from its log:
docker logs openclaw-node-b 2>&1 | grep "Our Public Key" | head -1
export AXL_NODE_B_PEER=<paste-it-here>

# Run the demo (uses AXL transport when AXL_NODE_B_PEER is set)
python3 scripts/run_demo.py
```

Demo completes in ~30 seconds. You'll see a **5-layer cascade animation** light up (AXL → x402 → KeeperHub → Uniswap → 0G), the **Crawfish Hopper** original-IP character chomp blocks while waiting for confirmation, and a structured Receipt with both the Base tx hash and the 0G Merkle rootHash.

---

## API keys needed

| Variable | Where to get it |
|---|---|
| `KEEPERHUB_API_KEY` | [app.keeperhub.com](https://app.keeperhub.com) → Settings → API Keys (`kh_` prefix, 32 chars) |
| `UNISWAP_API_KEY` | [developers.uniswap.org/dashboard](https://developers.uniswap.org/dashboard) (optional — KeeperHub wraps Uniswap natively, but the env var is here in case you want to hit the standalone Trading API) |
| `ZEROG_PRIVATE_KEY` | Any Ethereum private key funded on [0G Galileo testnet](https://faucet.0g.ai) (~0.1 OG is plenty for many demo uploads) |
| `NODE_B_PRIVATE_KEY` | Node B's identity key for signing audit envelopes. Generate with `python3 -c "from eth_account import Account; print('0x' + Account.create('node-b').key.hex())"` |
| `BASE_RPC_URL` | Default: `https://sepolia.base.org` (free public RPC) |

The KeeperHub-managed wallet (Turnkey MPC) needs **test ETH + test USDC on Base Sepolia** for the actual swap demo. Find your org's wallet address in the KeeperHub dashboard, then claim from these free faucets:

- **Base Sepolia ETH**: [coinbase.com/faucets/base-ethereum-sepolia-faucet](https://www.coinbase.com/faucets/base-ethereum-sepolia-faucet)
- **Sepolia USDC**: [faucet.circle.com](https://faucet.circle.com/) → select "Base Sepolia"

No real money required — the entire demo runs on free testnet assets.

---

## What you'll see

Demo orchestrator output (left pane = Node A poster, right pane = Node B service log):

```
  ╔═══════════════════════════════════════════════════════════╗
  ║    OpenClaw KeeperLink — Live Demo                        ║
  ║    Built for ETHGlobal Open Agents 2026                   ║
  ╚═══════════════════════════════════════════════════════════╝

  [1] Discover Node B over direct HTTP
      → POST http://127.0.0.1:9004/keeperlink kind=discover
      ← Discovery: pricing 10000 atomic USDC on Base; payTo 0xa139...

  [2] Build swap-intent JobRequest
      job_id : demo_<id>
      intent : swap 5 USDC for WETH on Base

  [3] Sign x402 fallback payment header
      asset   : 0x036CbD53...  amount: 10000 atomic
      payer   : 0x46b26446...
      sig     : 0x6d47b1331f771ca9...

  [4] Hire Node B with x402 payment

  Layer cascade:
   █ AXL  █ x402  █ KeeperHub  █ Uniswap  █ 0G

  ✓ Awaiting onchain confirmation │████████████████████████│ done
   ◢█▆◣ ←  block confirmed   ★ COIN!

  [5] Receipt received
        tx_hash       : 0xA1b2c3...
        basescan_link : https://basescan.org/tx/0xA1b2c3...
        0G rootHash   : 0xf00dd00d...

  [6] Round-trip verify (onchain + 0G)
      0G download   : ✓ (847 bytes)
      sig integrity : ✓

  ─ Demo complete. ─
```

---

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full five-layer breakdown, sequence diagrams, sponsor-track justifications, and the **OpenClaw Audit Envelope** primitive (the framework-level contribution to the 0G track).

The TL;DR five-layer stack:

```
┌──────────────── OpenClaw (agent framework + MCP glue) ────────────────┐
│   ┌────────── Gensyn AXL (P2P transport, encrypted, no broker) ──────┐│
│   │   ┌────── KeeperHub (workflow execution + x402 + audit) ────────┐│
│   │   │   ┌── Uniswap V3 (the actual swap, via KeeperHub plugin) ──┐│
│   │   │   │                                                        ││
│   │   │   └── 0G Storage (audit receipt, content-addressed) ───────┘│
│   │   └──────────────────────────────────────────────────────────────┘
│   └────────────────────────────────────────────────────────────────────┘
└──────────────────────────────────────────────────────────────────────────┘
```

Each layer is a different sponsor's product. None are redundant. Removing any one weakens or breaks the loop.

---

## Builder feedback

See [FEEDBACK.md](FEEDBACK.md) for honest integration notes covering Uniswap and KeeperHub developer experience. Required for **Uniswap track qualification** and entries the **KeeperHub Builder Feedback Bounty** ($500, two winners).

---

## Tracks targeted

- **0G — Best Agent Framework, Tooling & Core Extensions** — the [OpenClaw Audit Envelope](shared/audit_envelope.py) is a reusable signed/content-addressed proof primitive any OpenClaw agent mesh can produce + verify, with 0G Storage as the persistence backend. That's a framework-level contribution, not just a one-off receipt.
- **KeeperHub — Focus 2** (OpenClaw integration + x402 payments) — both rubric items hit in one build.
- **Gensyn — AXL P2P Transport** — Live AXL daemon stack via `docker compose up -d`: 2 AXL nodes connected over Yggdrasil mesh + MCP router sidecar with `keeperlink` service registered. Demo orchestrator routes hire requests through Node A's AXL HTTP API (`POST /mcp/{peer_id}/keeperlink`), proving the labor-market transport story end-to-end.
- **Uniswap — Best Trading API Integration** — swap executed via Uniswap V3 on Base through KeeperHub's `uniswap/swap-exact-input` action; integration depth on the KeeperHub side.
- **KeeperHub Builder Feedback Bounty** — `FEEDBACK.md` covers both Uniswap qualification + this bonus entry.

Direct-target sponsor pools: **$30,000.**

---

## License

MIT — see [LICENSE](LICENSE).
