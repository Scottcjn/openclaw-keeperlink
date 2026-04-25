# OpenClaw KeeperLink — Architecture v3 (Planning Doc)

**Status:** Pre-event planning artifact. NO implementation code written before Apr 24 kickoff.

**Event:** ETHGlobal Open Agents — kickoff **Apr 24, 2026 at 11:00 AM CT (16:00 UTC)**; submissions due **May 3, 2026 at 11:00 AM CT (16:00 UTC)**. Virtual, ~9.5-day build window. Source: ethglobal.com/events/openagents (slug `openagents`, uuid `y7m1f`).

**Committed tracks (all four) — pool amounts verified from live event payload 2026-04-23:**
| Sponsor | Pool (verified) | OpenClaw named? | Our fit |
|---|---|---|---|
| **0G** (Framework/Tooling — Track 1) | **$15,000** total sponsor pool | ✅ **VERBATIM** | Receipts persisted to 0G Storage via OpenClaw MCP tool |
| **KeeperHub** (Focus 2) | **$5,000** pool | ✅ **VERBATIM** | OpenClaw↔KeeperHub plugin + x402 payments |
| **Gensyn AXL** | $5,000 pool | generic | AXL P2P transport for agent mesh |
| **Uniswap** | $5,000 pool | generic (requires FEEDBACK.md) | Uniswap API for the actual swap |
| KeeperHub Builder Feedback Bounty | $500 (2× $250) | — | Same FEEDBACK.md satisfies both Uniswap + this |

> Note: 0G's $15K is the aggregated sponsor pool. Re-verify per-track breakdown (Track 1 vs. other 0G tracks) once prize detail UI renders — the old $7,500 / $2,500-top estimate was for Track 1 only and may or may not still hold.

**Direct-target sponsor pools: $30,000.** First-place ceiling on a single coherent build is higher than our earlier $10K estimate. Still not a realistic sweep target, but the fit remains structural, not forced.

**Prior-art anchor:** Hubble Trading Arena (ETHGlobal Buenos Aires winner) — agent-to-agent coordination with x402 payment and real onchain execution. Same recipe, different sponsors.

**Tagline (frozen):** *"Post a job over Gensyn AXL. One MCP call. KeeperHub settles onchain. Receipt back — no middlemen, no failed txs."*

---

## One-loop product thesis (v3)

> **Node A's OpenClaw agent pays Node B via x402 over AXL. Node B executes a real Uniswap swap on Base through KeeperHub. The receipt is simultaneously returned over AXL AND persisted to 0G Storage as a permanent, content-addressed audit record. Node A verifies both paths.**

One product. One story. **Four sponsors hit natively**, via one piece of glue code.

**The five-layer agent-native stack:**
- **Uniswap** = value movement (the actual swap)
- **KeeperHub** = reliability (retry, gas-opt, audit, execution)
- **AXL** = transport (P2P, encrypted, no central broker)
- **0G Storage** = audit memory (permanent, content-addressed via Merkle root)
- **OpenClaw** = agent framework stitching it all together

Each layer is a different sponsor's product. None are redundant. The story is coherent.

---

## System diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  NODE A  (Poster)                                                    │
│                                                                      │
│   ┌───────────────────────┐                                          │
│   │ OpenClaw agent (Py)   │  Sophia Elya lightweight client          │
│   │   1. builds job spec  │     "swap 5 USDC → wRTC on Base"         │
│   │   2. signs x402 pay   │     pays Node B in USDC on Base           │
│   └──────────┬────────────┘                                          │
│              │ HTTP POST  /mcp/{NodeB_peerId}/keeperlink             │
│              ▼                                                       │
│   ┌───────────────────────┐                                          │
│   │ AXL node (Go, :9002)  │  Yggdrasil P2P, native /mcp/ routing     │
│   └──────────┬────────────┘                                          │
└──────────────┼───────────────────────────────────────────────────────┘
               │  TLS/TCP over Yggdrasil mesh (no central broker)
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  NODE B  (Worker)                                                    │
│                                                                      │
│   ┌───────────────────────┐                                          │
│   │ AXL node (Go, :9002)  │                                          │
│   └──────────┬────────────┘                                          │
│              │  envelope {"service":"keeperlink"}                    │
│              ▼                                                       │
│   ┌───────────────────────┐                                          │
│   │ MCP Router (:9003)    │  dispatches by service name              │
│   └──────────┬────────────┘                                          │
│              ▼                                                       │
│   ┌───────────────────────┐                                          │
│   │ keeperlink-mcp svc    │                                          │
│   │   3. verifies x402    │                                          │
│   │      payment + sig    │                                          │
│   │   4. calls KeeperHub  │ ──► KeeperHub Direct Execution API       │
│   │      with Uniswap v4  │     (retry logic, gas opt, audit trail) │
│   │      swap intent      │                                          │
│   │   5. KeeperHub        │     ──► real Uniswap swap on Base        │
│   │      executes + rtns  │         tx confirmed, receipt issued     │
│   │      tx receipt       │                                          │
│   └───────────────────────┘                                          │
└──────────────────────────────────────────────────────────────────────┘
               ▲
               │  receipt: {tx_hash, audit_ref, settled_at, amount_out}
               │  returned over same AXL request/response cycle
```

Every leg is real: real x402 payment, real AXL P2P, real KeeperHub execution, real Uniswap swap, real tx hash on Base.

---

## Sponsor coverage (how each track gets hit)

### Gensyn (AXL) — committed
- **Qualification:** uses AXL for inter-node comms; runs across two separate AXL nodes; built during hackathon. ✅
- **Depth of AXL integration:** Node A's MCP call goes through `/mcp/{peer_id}/keeperhub` — native AXL transport, no centralized broker.
- **Non-trivial use:** not just hello-world; demonstrates agent-to-agent commerce (post → claim → execute → receipt) over P2P.

### KeeperHub (Focus 2, OpenClaw integration + payments) — committed
- **Focus 2 hits BOTH sub-angles in one build:**
  1. *Agent framework integration:* OpenClaw is verbatim in rubric — `keeperlink-mcp` is the integration.
  2. *Payments:* x402 is verbatim in rubric — Node A's payment to Node B uses x402.
- **Depth of integration (two surfaces touched):**
  1. **Direct Execution API** (`POST /api/execute/contract-call`) — Node B's worker agent calls this with Uniswap Router ABI + `exactInputSingle` args. KeeperHub auto-fetches ABI from basescan, executes synchronously, returns `transactionHash` + ready-made `transactionLink`. Receipt goes back over AXL.
  2. **KeeperHub MCP server** (hosted at `https://app.keeperhub.com/mcp`) — Node B also connects via `claude mcp add --transport http keeperhub ...`. Demoable tools: `ai_generate_workflow` (natural-language intent → workflow), `execute_workflow`, `get_execution_logs`. Allows intent-mode demo as an alternative to raw ABI calls.
- **Wallet model:** KeeperHub-managed via Para or Turnkey integration (MPC). Spending caps configurable per-org. No raw key handling in our code.
- **Native plugins leveraged:** Uniswap plugin + Aerodrome plugin both first-class — no custom swap router logic needed.
- **Real utility:** reliable onchain actions with retry/gas/private-routing/audit inherited from KeeperHub.
- **Mergeable code:** clean README, typed interfaces, working example, live on Base.

### Uniswap Foundation — COMMITTED
- **Criteria (published):** "Best Uniswap API Integration — give your agent the ability to swap and settle value onchain." $2,500 / $1,500 / $1,000.
- **Qualification:** MUST include `FEEDBACK.md` in repo root covering builder experience. Missing file = disqualified.
- **Scope:** Uniswap API for the swap (NOT a custom v4 hook — simpler than our earlier assumption).
- **Execution path:** KeeperHub's Uniswap plugin invokes the swap; our agent code also references Uniswap's SDK/API directly so integration depth shows on Uniswap's side too.

### 0G Track 1 "Best Agent Framework, Tooling & Core Extensions" — COMMITTED (promoted from opportunistic)
- **Criteria (published):** "Framework-level innovations using **OpenClaw** or alternatives on 0G." Prize breakdown: $2,500 / $2,000 / $1,500 / $1,000 / $500.
- **Qualification:** Project name, GitHub repo, demo video (<3min), deployment addresses, "at least one working example agent."
- **Our framework contribution:** OpenClaw MCP tool `keeperlink-receipt` that persists any agent execution receipt to 0G Storage and returns the Merkle rootHash. Reusable by any OpenClaw agent mesh — this IS the framework-level extension.
- **SDK:** `@0gfoundation/0g-ts-sdk` (TypeScript). Upload `MemData` → `merkleTree` → `indexer.upload` → returns `rootHash`. Auth is blockchain-based (signer + RPC + indexer RPC) — no API key.
- **Why this wins the framework track:** we're not just using 0G, we're extending OpenClaw with a 0G-backed audit primitive that any OpenClaw agent can inherit. That's a core-extension contribution, not a one-off integration.

### Builder Feedback Bounty (KeeperHub, $500 bonus) — committed
- One `FEEDBACK.md` at repo root satisfies BOTH Uniswap qualification AND this bonus.
- Structure: section 1 = Uniswap integration friction, section 2 = KeeperHub integration friction. Honest, specific, reproducible.
- Up to 2 winners receive $250 each.

---

## Repo layout (to be created Apr 24)

**Key pattern decision:** mirror Gensyn's own `collaborative-autoresearch-demo` structure by shipping the poster-side integration as a **Claude Code skill** at `skills/openclaw-keeperlink/`. Their official demo uses this pattern; we match it for sponsor-alignment signal.

```
openclaw-keeperlink/
├── README.md
├── ARCHITECTURE.md          (this doc, refined)
├── LICENSE
├── docker-compose.yml       (spins up both nodes locally for judges)
├── .env.example
│
├── skills/openclaw-keeperlink/   # Claude Code skill (Gensyn-demo-style)
│   ├── SKILL.md                   # frontmatter: post-job | check-receipts | status
│   └── keeperlink_client.py       # AXL+x402+KeeperHub glue, non-fatal network calls
│
├── node-a/                  (poster)
│   ├── axl-config.json      (AXL node config)
│   └── start.sh             (launches AXL node + registers skill)
│
├── node-b/                  (worker)
│   ├── axl-config.json
│   ├── keeperhub_mcp/       (MCP service exposing KeeperHub tools)
│   │   ├── server.py        (registers "keeperlink" w/ MCP router)
│   │   └── __init__.py
│   └── start.sh             (launches AXL node + router + mcp service)
│
├── shared/
│   ├── schemas.py           (job + receipt Pydantic models)
│   └── wallets.py           (Base chain wallet helpers, x402 verify)
│
└── docs/
    ├── demo.md              (judge-facing demo script + tx-link verifier)
    ├── feedback.md          (running log for Builder Feedback Bounty)
    └── screenshots/
```

**Invocation pattern** (judges see this in the demo):
```bash
/openclaw-keeperlink status       # confirms AXL connectivity + KeeperHub auth
/openclaw-keeperlink post-job --intent "swap 5 USDC to wRTC"
/openclaw-keeperlink check-receipts
```

**Non-fatal philosophy** (copied from Gensyn's demo): if AXL is down or peer unreachable, agent logs and continues. If KeeperHub retry budget exhausted, surface the audit ref and abort cleanly. No crashes mid-demo.

---

## Build sequencing (compressed 9.5-day window)

Revised 2026-04-23 after pulling authoritative event times. Prior draft assumed May 6 23:59 CT submission (13-day window) — reality is **May 3 11:00 AM CT (9.5 days)**. Optional "IF favorable" branches for Uniswap v4 hook and 0G polish are **dropped** — they are now core, not stretch.

| Day | Date (CT) | Goal | Risk kill-check |
|-----|-----------|------|-----------------|
| **Day 1** | Thu Apr 24 (11 AM kickoff → eod) | Four isolated kill-tests green by EOD: (1) 2× AXL nodes + cross-node MCP, (2) KeeperHub hello-world with real Base tx, (3) Uniswap `/quote` round-trip, (4) 0G upload + rootHash fetch. | Any of the 4 not green → narrow sponsor tracks accordingly before Day 2 wiring. |
| **Day 2** | Fri Apr 25 | Node A → Node B over AXL MCP works end-to-end. Structured job payload arrives at Node B, logged. | If AXL dispatch flaky, fix before any further integration. |
| **Day 3** | Sat Apr 26 | Node B calls KeeperHub Direct Execution with Uniswap swap params, tx confirmed on Base. Receipt returns over AXL. | First green loop = MVP demoable. Stop here if later days derail. |
| **Day 4** | Sun Apr 27 | x402 payment integrated — unpaid calls rejected, paid calls execute. | If x402 blocked, fall back to signed-message auth for demo (lose payments angle on KeeperHub rubric). |
| **Day 5** | Mon Apr 28 | 0G Storage receipt persistence + Node A round-trip verify (on-chain + content-addressed). | Full 5-layer story complete. |
| **Day 6** | Tue Apr 29 | Polish: error handling, docker-compose for judges, 5× clean end-to-end run reproducibility. | Must be able to demo blind at least once. |
| **Day 7** | Wed Apr 30 | Demo video (3 min), asciinema captures, thumbnail, transcript. | |
| **Day 8** | Thu May 1 | README, ARCHITECTURE, FEEDBACK.md drafts done. | |
| **Day 9** | Fri May 2 | Buffer: last-mile fixes from dry-run feedback, final submission artifacts staged. | Anything still failing → cut it. |
| **Morning Day 10** | **Sat May 3 (by 11 AM CT)** | **Submit.** File KeeperHub + Uniswap feedback-bounty entries. | **Hard deadline.** |

---

## Anti-scope-creep list (Codex's scope-kill warning)

**We will NOT build:**
- Custom wallet orchestration beyond Coinbase Agentic Wallet defaults
- Multi-agent personality sandbox (no Sophia/Boris show-reel)
- A dashboard or frontend UI (CLI or terminal output suffices)
- Marketplace front-end (RIP-302 stays in RustChain, not ported)
- Novel cryptography / fingerprinting layers (RIP-PoA stays out)
- Pre-hackathon implementation (all submitted code Apr 24+)

**Justification:** One end-to-end commercial interaction beats a "world model" with no crisp demo. Judges reward depth over breadth.

---

## Judge-day headlines (frozen after 2x Grok adversarial review)

**Primary (everyone):** *"Post a job over Gensyn AXL. One MCP call. KeeperHub settles onchain. Receipt back — no middlemen, no failed txs."*

**Nasdaq-judge lens (Mel K):** *"Agent payment rails that actually settle — retry-safe, gas-optimized, audit-traceable. Same recipe as Hubble Trading Arena, production-hardened."*

**Flow-judge lens (Patrick Fuchs):** *"Decentralized agent labor market. Real job posting, real payment, real swap, real receipt. Solo build."*

~~"MCP-everywhere vision"~~ — killed. Buzzword salad.

## Demo visual (frozen)

Split-screen terminal recording:
- **Left pane:** Node A logs — job built, x402 paid, AXL call fired
- **Right pane:** Node B logs — received, verified, KeeperHub dispatched, tx hash emitted
- **Overlay:** live Base tx link + "settled in X seconds, 0 failures"
- 30-second loop. Non-Ethereum viewer understands instantly.

No UI. No dashboard. No animation. The CLI IS the story.
