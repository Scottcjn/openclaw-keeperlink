# OpenClaw KeeperLink — Judge's Guide

> **2-minute evaluation path.** This file exists so a time-poor judge can verify the project's strongest claims in three clicks without cloning the repo or reading code.

---

## What the project is, in one line

Two AI agents transact peer-to-peer on Base mainnet — discover via AXL, pay via x402, execute via KeeperHub, swap on Uniswap V3, persist receipt on 0G — with cryptographic proof of every step.

## 30-second verification (3 clicks)

1. **🌐 [Live page](https://elyanlabs.ai/keeperlink/)** — embedded videos + architecture diagram + click-to-copy live artifacts. Hosted on Elyan Labs' own VPS, the same .131 box that runs the RustChain explorer.

2. **▶️ [Watch the 38s demo](https://youtu.be/brC9l2QefhU)** — 5-layer cascade narrated by Sophia Elya. See the protocol execute a real on-chain swap end-to-end.

3. **🔎 [Verify the tx on basescan](https://basescan.org/tx/0xeb85abefaf5c7da435c9c32090469d388493a0894c2a41b51178e5ce41345f32)** — block 45453249, USDC → WETH on Base mainnet, status 1 ✓.

**That's it.** Real settled tx. Real Merkle-rooted audit envelope. Independently verifiable. Not a mock, not a testnet, not a screenshot.

## 90-second deep verification (5 more clicks)

4. **🤖 [Watch the live LLM agent addendum (40s)](https://youtu.be/QIU8s-jHG94)** — same demo, but Claude Sonnet 4.6 holds the orchestration role via a real tool-use loop. Distinguishes "agent" from "script" by *showing* the model reason and call tools live.

5. **📜 [Read PROTOCOL.md](PROTOCOL.md)** — formal protocol spec. Two roles (Poster, Service), five phases (Discovery → Hire → Verification → Execution+Attestation → Independent Verification), wire-format schemas, replaceable surfaces. The reusable contract — implementations of either side can be swapped without breaking the other.

6. **📝 [Read FEEDBACK.md](FEEDBACK.md)** — sponsor-track integration notes. Section 1 = Uniswap, Section 2 = KeeperHub. **Section 2.10** has six new bugs surfaced during the May 2 mainnet flip (URL convention, Accept header, redirect handling, V3 param shape, approve+swap bundling, response field naming). **Section 2.11** is a writeup of the LLM-driveability test with concrete improvement suggestions for KH.

7. **🏗️ [Read ARCHITECTURE.md](ARCHITECTURE.md)** — sequence diagrams, every pivot decision documented honestly. Includes the v4-vs-v5 migration (workflow-publishing-path → execute_protocol_action fallback) and the on-demand `usdc.approve` helper that lets fresh wallets survive their first swap.

8. **💻 [Browse the repo](https://github.com/Scottcjn/openclaw-keeperlink)** — 16 commits today (May 2), all within the hackathon window (Apr 24+). Working tree clean. Two demo entrypoints: `scripts/run_demo.py` (deterministic) and `scripts/run_demo_agent.py` (Claude tool-use loop).

## Sponsor track contributions

> **Note on prize claims.** ETHGlobal caps each project at **3 partner-prize claims**. We claimed the three with the deepest integrations: **0G**, **KeeperHub**, **Uniswap Foundation**. Gensyn (AXL) is listed as "additional partner technology used" — it's load-bearing for the protocol but doesn't fit the Gensyn track's distributed-compute thesis as cleanly, so we left the slot for projects that do.

### Claimed prizes (3)

| Track | What we built | Where to look |
|---|---|---|
| **0G Framework** | `OpenClawAuditEnvelope` Pydantic schema — signed envelope wrapping x402 proof + KH execution + on-chain settlement, content-addressed via Merkle rootHash, round-trip verified by demo orchestrator. Reusable beyond swaps. | `shared/audit_envelope.py` (schema, 248 lines). `scripts/zerog/zerog_helper.mjs` (TS-SDK helper). Demo orchestrator's "Round-trip verify" step downloads + content-matches + signature-verifies the envelope. Live receipt rootHash: `0xa45c313d03fec00119069838e91f9e52f6f8f578174a7e72e779e7b1aaaba871`. |
| **KeeperHub** (incl. Builder Feedback Bounty) | `execute_protocol_action(uniswap/swap-exact-input)` via the MCP server. Real settled tx on Base mainnet. **240+ line FEEDBACK.md** (§1 Uniswap, §2 KeeperHub, §2.10 mainnet-day bugs, §2.11 LLM-driveability) submitted as the Builder Feedback artifact alongside the integration. | `node-b/keeperlink_service.py:dispatch_workflow()` (Path B branch). Live LLM agent (`scripts/run_demo_agent.py`) demonstrates the same path is drivable by Claude with no KH-specific knowledge. `FEEDBACK.md` for the writeup. |
| **Uniswap Foundation** | Real settled USDC→WETH swap on Base mainnet via SwapRouter02. Both KH-wrapped path AND direct Trading API consultation. | `node-b/keeperlink_service.py` (KH-wrapped swap with on-demand approve) + `scripts/run_demo_agent.py` `get_market_quote` tool (direct Trading API quote that the LLM consults before hiring). |

### Used but not claimed

| Track | What we built | Where to look |
|---|---|---|
| **Gensyn AXL** | Two real AXL nodes in Docker containers routing MCP envelopes between Poster and Service over Yggdrasil mesh. Path A live and load-bearing — without AXL the discovery handshake doesn't work. | `docker compose up` brings up `openclaw-node-a`, `openclaw-node-b`, `openclaw-node-b-mcp-router`. Discovery probe: `curl :9111/mcp/{peer}/keeperlink -d '{"kind":"discover"}'`. |

## Live artifacts

| What | Value |
|---|---|
| Sample on-chain tx | https://basescan.org/tx/0xeb85abefaf5c7da435c9c32090469d388493a0894c2a41b51178e5ce41345f32 |
| Block | 45453249 |
| 0G receipt rootHash | `0xa45c313d03fec00119069838e91f9e52f6f8f578174a7e72e779e7b1aaaba871` |
| KeeperHub-managed wallet (Turnkey MPC) | `0xe12230149b2d5ed561fa51261fb8e02dbd514724` |
| Node B identity (x402 payee) | `0xa13944De329EaC2658FB7DC0b6BBC523A0a697C3` |

## Anti-scope (what we deliberately did NOT do)

- ❌ No RustChain integration (Elyan Labs has its own L1; out of scope for the demo)
- ❌ No multi-protocol breadth — stuck to Uniswap V3 on Base
- ❌ No frontend dashboard / live web app — the linked frontend is a static landing page, the agents are the product
- ❌ No custom Uniswap V4 hook
- ❌ All code committed during hackathon window (Apr 24+); no pre-event code

This discipline is intentional. The five sponsor surfaces are load-bearing — replace any one and the protocol breaks. Everything else would have been busy-work.

---

**Build details:** Solo build by [Scott Boudreaux](https://github.com/Scottcjn) / Elyan Labs · Apr 24 → May 3 2026 · ~9.5 days · all integrations new to this builder.

**Questions?** The repo's [README.md](README.md) has the long-form intro and "Run it yourself" steps. The [live page](https://elyanlabs.ai/keeperlink/) has everything else.
