# OpenClaw KeeperLink

> P2P agent jobs that actually settle onchain. Post over Gensyn AXL, pay via x402, execute via KeeperHub, swap on Uniswap, persist receipt on 0G. No middlemen. No failed txs.

**Built for:** [ETHGlobal Open Agents](https://ethglobal.com/events/openagents) — Apr 24 → May 3, 2026
**Author:** [Scott Boudreaux](https://github.com/Scottcjn) / Elyan Labs (solo build)
**Status:** 🏗️ Day-1 scaffolding (Apr 25)

---

## 30-second read

Two AI agents on separate **Gensyn AXL** nodes coordinate over an encrypted P2P mesh — no central broker.

Agent A posts a job: *"swap 5 USDC for ETH on Base."*
Agent B claims it, verifies the **x402** payment header, calls **KeeperHub**'s Direct Execution API to run the swap via the **Uniswap** Trading API, and persists the resulting receipt to **0G Storage** with content-addressed Merkle proof.

Agent A receives the receipt back over the same AXL request/response cycle and verifies it two ways — onchain on Base, and by Merkle root on 0G.

One product. One demo. **Five sponsor integrations** in a single coherent loop.

---

## Sponsor integrations

| Sponsor | Role | Code entrypoint |
|---|---|---|
| **Gensyn AXL** | Encrypted P2P transport | `node-a/axl-config.json`, `node-b/axl-config.json`, `shared/axl_client.py` |
| **KeeperHub** | Reliable onchain execution + x402 | `shared/keeperhub.py`, `node-b/keeperlink_service.py` |
| **Uniswap** | The actual swap (Trading API) | `shared/uniswap.py` |
| **0G** | Permanent audit receipts | `shared/zerog.py` |
| **OpenClaw** | Agent framework + MCP glue | `skills/openclaw-keeperlink/` |

---

## Quick start (judges)

```bash
git clone https://github.com/Scottcjn/openclaw-keeperlink.git
cd openclaw-keeperlink
cp .env.example .env
# Fill in API keys (see "API keys needed" below)

docker compose up
# Watch both terminal panes. Demo completes in ~30 seconds.
```

## API keys needed

| Variable | Where to get it |
|---|---|
| `KEEPERHUB_API_KEY` | [app.keeperhub.com](https://app.keeperhub.com) → Settings → API Keys (`kh_` prefix) |
| `UNISWAP_API_KEY` | [developers.uniswap.org/dashboard](https://developers.uniswap.org/dashboard) |
| `ZEROG_PRIVATE_KEY` | Any Ethereum private key funded on [0G testnet](https://faucet.0g.ai) |
| `BASE_RPC_URL` | Default: `https://mainnet.base.org` (free public RPC) |

---

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full five-layer breakdown, sequence diagrams, and sponsor-track justifications.

The TL;DR five-layer stack:

```
┌──────────────── OpenClaw (agent framework + MCP glue) ────────────────┐
│   ┌────────── Gensyn AXL (P2P transport, encrypted, no broker) ──────┐│
│   │   ┌────── KeeperHub (reliable execution, retry, gas-opt) ──────┐ ││
│   │   │   ┌── Uniswap (Trading API, the actual swap) ──┐           │ ││
│   │   │   │                                            │           │ ││
│   │   │   └── 0G Storage (audit receipt, content-addr) ┘           │ ││
│   │   └────────────────────────────────────────────────────────────┘ ││
│   └────────────────────────────────────────────────────────────────── ┘│
└────────────────────────────────────────────────────────────────────────┘
```

Each layer is a different sponsor's product. None are redundant. Removing any one breaks the demo.

---

## Builder feedback

See [FEEDBACK.md](FEEDBACK.md) for honest integration notes covering Uniswap and KeeperHub developer experience. (Required for Uniswap track qualification + KeeperHub Builder Feedback Bounty.)

---

## Tracks targeted

- **0G — Best Agent Framework, Tooling & Core Extensions** — OpenClaw extension that adds 0G-backed audit primitives any agent mesh can inherit.
- **KeeperHub — Focus 2** (OpenClaw integration + x402 payments) — Both rubric items hit in one build.
- **Gensyn — AXL P2P Transport** — Real agent-to-agent commerce over the AXL mesh, not hello-world.
- **Uniswap — Best Trading API Integration** — Swap executed via Uniswap on Base, depth on the integration side.
- **KeeperHub Builder Feedback Bounty** — One `FEEDBACK.md` covers both Uniswap qual + this bonus.

Direct-target sponsor pools: **$30,000.** First-place ceiling on a coherent build is higher than any single-track win.

---

## License

MIT — see [LICENSE](LICENSE).
