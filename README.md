# OpenClaw KeeperLink

> **👨‍⚖️ Judges:** start with [JUDGE_GUIDE.md](JUDGE_GUIDE.md) — 2-minute evaluation path with the strongest 3 clicks first.
>
> **P2P agent jobs that actually settle onchain.** Post over Gensyn AXL, pay via x402, execute via KeeperHub, swap on Uniswap V3, persist receipt on 0G Storage. No middlemen. No failed txs.

**Built for:** [ETHGlobal Open Agents](https://ethglobal.com/events/openagents) — Apr 24 → May 3, 2026
**Author:** [Scott Boudreaux](https://github.com/Scottcjn) / Elyan Labs (solo build)
**🌐 Live page:** **https://elyanlabs.ai/keeperlink/** — embedded videos, inline architecture diagram, click-to-copy live artifacts
**Demo video (ETHGlobal submission, 3:44):** see the [public showcase](https://ethglobal.com/showcase/openclaw-keeperlink-bvape) — full walkthrough with per-step holds so each transaction beat (discovery → x402 sign → KH dispatch → on-chain settlement → 0G receipt → round-trip verify → LLM-driven repeat) lands instead of rushing.
**Short canonical (38s YouTube preview):** https://youtu.be/brC9l2QefhU · also on [BoTTube](https://bottube.ai/watch/iqXhl1N-N44) — fast-paced overview that fits BoTTube's science-tech 120s cap.
**Live LLM agent addendum (40s YouTube):** https://youtu.be/QIU8s-jHG94 — Claude Sonnet 4.6 in the driver's seat: discover → quote → verify-balance → hire → independently-verify, every step a real tool call, every reasoning step shown live. Distinguishes "agent" from "script." · also on [BoTTube](https://bottube.ai/watch/ZrPDhpMFfwX)
**2:16 mid-length YouTube cut:** https://youtu.be/LcTAyTK6o7A — the v2 we initially submitted before stretching to v3.
**Protocol spec:** [`PROTOCOL.md`](PROTOCOL.md) — formal definition of the OpenClaw KeeperLink Protocol (roles, phases, schemas, replaceable surfaces)
**Live LLM agent script:** [`scripts/run_demo_agent.py`](scripts/run_demo_agent.py) — Claude tool-use loop wrapping the existing service. Run with `python3 scripts/run_demo_agent.py`.
**Live Base mainnet tx (sample):** [`0xeb85abefaf5c7da435c9c32090469d388493a0894c2a41b51178e5ce41345f32`](https://basescan.org/tx/0xeb85abefaf5c7da435c9c32090469d388493a0894c2a41b51178e5ce41345f32) — block 45453249
**0G receipt rootHash (sample):** `0xa45c313d03fec00119069838e91f9e52f6f8f578174a7e72e779e7b1aaaba871` (Galileo testnet, downloaded + content-matched + signature-verified by demo orchestrator)

---

## What we built (in plain English)

Imagine two AI assistants on different computers. Assistant A wants something done — say, swap $5 of one cryptocurrency for another. Instead of doing it itself, it sends a tiny payment to Assistant B (a paid specialist) and asks B to handle it. B does the swap on a real exchange, gets a receipt, and stores that receipt in a tamper-proof shared notebook anyone can verify.

**What's special:**
- **No middleman.** A and B talk directly, encrypted, peer-to-peer. No Stripe, no Uber, no broker between them.
- **The payment is cryptographically authorized in the same exchange.** A signs a payment-intent header (EIP-191 `personal_sign` over an x402-style envelope) that B can verify before doing the work. The reference build ships this as a *declarative* x402 promise — full on-chain settlement (EIP-3009 `transferWithAuthorization`) is the next step on the roadmap and is documented in `shared/x402.py` + `FEEDBACK.md §2.5`. The on-chain swap that B executes via KeeperHub IS settled.
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
| `BASE_RPC_URL` | Default: `https://mainnet.base.org` (free public RPC). Set to `https://sepolia.base.org` + `BASE_CHAIN_ID=84532` to fall back to Sepolia — the chain config is env-driven end-to-end. |
| `BASE_CHAIN_ID` | Default: `8453` (Base mainnet). |

The KeeperHub-managed wallet (Turnkey MPC) needs **a small amount of ETH for gas + USDC as the swap input** on Base. The reference run uses ≤$0.10 USDC per swap. Find your org's wallet address in the KeeperHub dashboard (or `~/.config/keeperhub/keys.json`), then fund it:

- **Recommended (mainnet, fastest):** buy ~0.0015 ETH and ~5 USDC on Coinbase, withdraw both directly to the KH wallet selecting **Base** as the network (no withdrawal fee). Total cost ~$10, gives you ~30+ demo runs.
- **Alternative (Sepolia testnet):** flip `BASE_CHAIN_ID=84532` + `BASE_RPC_URL=https://sepolia.base.org` in `.env`, then claim from [coinbase.com/faucets/base-ethereum-sepolia-faucet](https://www.coinbase.com/faucets/base-ethereum-sepolia-faucet) for ETH + [faucet.circle.com](https://faucet.circle.com/) for USDC. Note: most Base Sepolia ETH faucets gate on holding mainnet ETH, so the mainnet path is often the path of less friction even though it costs real money.

The first swap from a fresh wallet auto-runs `usdc.approve(uniswapV3Router, MAX_UINT256)` once via `_ensure_token_allowance` in `keeperlink_service.py` — judges who clone-and-run won't hit the standard "STF" failure mode.

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
        tx_hash       : 0xeb85abef...41345f32
        basescan_link : https://basescan.org/tx/0xeb85abef...41345f32
        0G rootHash   : 0xa45c313d...aaaba871

  [6] Round-trip verify (onchain + 0G)
      0G download   : ✓ (3252 bytes)
      content match : ✓
      signature     : ✓
      Base confirm  : ✓ block 45453249

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
