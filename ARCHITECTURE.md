# OpenClaw KeeperLink — Architecture v4

**Status:** Active build doc (Apr 25, 2026, Day 2 of ETHGlobal Open Agents).
v3 was the pre-event planning artifact and is preserved in git history (commit `1c7ba0c` — first scaffolding). v4 incorporates Day-1/Day-2 kill-test discoveries + Codex adversarial review.

**Event:** ETHGlobal Open Agents — kickoff **Apr 24, 2026 at 11:00 AM CT**; submissions due **May 3, 2026 at 11:00 AM CT**. Solo build, ~7.5 days remaining.

---

## What changed v3 → v4

| Aspect | v3 (planning) | v4 (after kill-tests) |
|---|---|---|
| KeeperHub surface | "Direct Execution API" at `POST /api/execute/transfer` | **Workflow platform** — `/api/mcp/workflows/<slug>/call` plus 26 MCP tools including native Uniswap V3 actions |
| x402 integration | "Bolt x402 onto KeeperHub" | **Native** — paid workflows return x402 v2 envelopes (Base USDC) directly. No glue code. |
| Uniswap integration | Custom v4 hook OR Uniswap REST Trading API | **KeeperHub native** `uniswap/swap-exact-input` action. Optional Uniswap REST API on the side for breadth. |
| Node B's role | Custom MCP service wrapping raw contract calls | **Remote specialist** that owns and invokes a published KeeperHub workflow |
| AXL's role | "Encrypted P2P transport" (decorative if KeeperHub is internet-facing) | **Labor market + delegation channel** — Node B advertises capability + price over AXL; Node A *hires* over AXL |
| 0G's role | "Persist receipt to 0G after execution" (integration) | **Standardized OpenClaw audit envelope as a reusable primitive** (framework extension) |

The core demo loop is unchanged — five sponsor surfaces, one coherent execution path. The implementation is significantly cleaner.

---

## One-loop product thesis (v4)

> **Node A's OpenClaw agent hires Node B over Gensyn AXL with an x402-paid request. Node B (the remote specialist) invokes its published `keeperlink-swap` KeeperHub workflow, which executes a real Uniswap V3 swap on Base. Node B wraps the result in a standardized OpenClaw audit envelope, persists it to 0G Storage, and returns both the on-chain tx hash and the 0G Merkle root over AXL. Node A independently verifies the receipt two ways — onchain on Base and by content-address on 0G.**

One product. One demo. **Five sponsor integrations** that each carry weight in the loop:

- **OpenClaw** — the agent framework + the audit-envelope primitive
- **Gensyn AXL** — the agent labor market + delegation transport
- **KeeperHub** — workflow execution + x402 enforcement + native Uniswap V3
- **Uniswap** — the actual swap (via KeeperHub's `uniswap/swap-exact-input` action)
- **0G Storage** — content-addressed audit memory

Removing any single layer breaks the demo. Each is real, none is decorative.

---

## System diagram (v4)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  NODE A  (OpenClaw poster)                                               │
│                                                                          │
│   ┌──────────────────────┐                                               │
│   │ OpenClaw skill (Py)  │  Sophia-persona client                        │
│   │  1. discovers peers  │                                               │
│   │     over AXL         │                                               │
│   │  2. signs x402 USDC  │                                               │
│   │  3. fires hire req   │                                               │
│   └──────────┬───────────┘                                               │
│              │  POST /mcp/{NodeB_peerId}/keeperlink                      │
│              │  Body: {intent, tokenIn, tokenOut, amountIn,              │
│              │         x402_payment_header}                              │
│              ▼                                                           │
│   ┌──────────────────────┐                                               │
│   │ AXL node (Go, :9001) │  Yggdrasil P2P, encrypted, no broker          │
│   └──────────┬───────────┘                                               │
└──────────────┼───────────────────────────────────────────────────────────┘
               │  TLS over Yggdrasil mesh
               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  NODE B  (OpenClaw remote specialist)                                    │
│                                                                          │
│   ┌──────────────────────┐                                               │
│   │ AXL node (Go, :9002) │  receives hire req                            │
│   └──────────┬───────────┘                                               │
│              ▼                                                           │
│   ┌──────────────────────┐                                               │
│   │ MCP Router (:9003)   │  routes to "keeperlink" service               │
│   └──────────┬───────────┘                                               │
│              ▼                                                           │
│   ┌──────────────────────┐                                               │
│   │ keeperlink-service   │                                               │
│   │  4. verifies x402    │                                               │
│   │  5. calls own KH     │ ──► KeeperHub MCP                             │
│   │     workflow:        │     POST /api/mcp/workflows/                  │
│   │     keeperlink-swap  │          keeperlink-swap/call                 │
│   │                      │          (workflow id 1ao3zjcjngophp36baqht)  │
│   │  6. workflow runs:   │                                               │
│   │     a. quote-exact   │     ──► Uniswap V3 Quoter on Base             │
│   │     b. swap-exact    │     ──► Uniswap V3 Router on Base             │
│   │        (real tx)     │         tx confirmed, hash returned           │
│   │  7. builds audit env │                                               │
│   │  8. uploads to 0G    │ ──► 0G testnet, returns Merkle rootHash       │
│   │  9. returns receipt  │                                               │
│   │     over AXL         │                                               │
│   └──────────────────────┘                                               │
└──────────────────────────────────────────────────────────────────────────┘
               ▲
               │  Receipt: {tx_hash, basescan_link, amount_out,
               │            0g_root_hash, audit_envelope_signature}
               │  returned over the same AXL request/response cycle
```

Every leg is real: real x402 USDC payment, real AXL P2P, real KeeperHub workflow execution, real Uniswap V3 swap, real Base tx, real 0G content-addressed receipt.

---

## Why AXL stays load-bearing

The pre-pivot worry was: "if Node B just calls KeeperHub HTTPS, AXL becomes decorative — judges see unnecessary indirection."

The v4 model resolves this by making **Node B the remote specialist**:

- Node B owns the KeeperHub org + API key + published `keeperlink-swap` workflow
- Node B advertises its capability + price over AXL (peer discovery + capability gossip)
- **Node A can only access this capability by hiring Node B over AXL** — there is no direct path from "user with intent" to "KeeperHub workflow execution" without the AXL hop
- Receipt + 0G root return over AXL, not direct HTTP

AXL is the **labor market**, not a decorative transport. Drop AXL and the model collapses to "agent calls KeeperHub directly," which is just a CLI tool, not agent commerce.

This also keeps our story aligned with Hubble Trading Arena (the ETHGlobal Buenos Aires winner): agent-to-agent coordination over a peer mesh with x402 settlement and real on-chain execution. Same recipe, different sponsors.

---

## Why 0G is a framework extension, not just an integration

The 0G Track 1 prompt asks for "framework-level innovations using OpenClaw." Storing one receipt per execution is integration, not framework.

Our framework-level contribution is the **OpenClaw Audit Envelope** — a standardized, signed, content-addressed proof structure that any OpenClaw agent mesh can produce and verify, with 0G Storage as the persistence backend.

Schema (defined in `shared/audit_envelope.py` — see task #8):

```python
class OpenClawAuditEnvelope(BaseModel):
    schema_version: int            # bump-only, append-compatible
    job: JobRequest                # AXL request metadata (intent, params, poster)
    workflow_slug: str             # KeeperHub bazaar slug invoked (e.g. "keeperlink-swap")
    workflow_version: str | None   # workflow definition hash at invocation time
    x402_proof: X402PaymentProof   # signed payment header + verification result
    keeperhub_execution_id: str    # KeeperHub-assigned execution ID
    onchain_tx_hash: str           # tx hash on the target chain
    onchain_chain_id: int          # e.g. 8453 for Base
    result_payload_hash: str       # blake3(canonical_json(result_data))
    signer_address: str            # Node B's identity address
    signature: str                 # signed: hash(envelope_minus_signature)
    timestamp_unix: int
```

What makes this **framework-level**:

1. **Reusable** — any OpenClaw agent that hires another agent can produce and verify these envelopes. Not specific to swaps, not specific to Uniswap, not specific to KeeperHub.
2. **Verifiable independent of any single chain** — the 0G Merkle root proves the envelope existed at a specific time without trusting any particular execution path.
3. **Composable** — envelopes can reference each other via `result_payload_hash`. Multi-step agent mesh compositions become auditable as DAGs.
4. **0G-native** — the envelope schema is designed around 0G's content-addressed storage primitives. Mid-flight upgrades to 0G's KV store or compute layer extend the primitive without breaking the schema.

This is the contribution to the framework track. The `keeperlink-swap` workflow is one example user; the envelope is the reusable primitive.

---

## Sponsor coverage (v4)

### Gensyn (AXL) — committed
- **Qualification:** uses AXL for inter-node comms; built during hackathon; runs across two separate AXL nodes.
- **Depth:** AXL serves as the **agent labor market**, not just a transport hop. Node B's capability is only accessible via hiring through AXL.
- **Non-trivial use:** capability advertisement + x402-paid hire + receipt return all over the AXL mesh.

### KeeperHub (Focus 2: OpenClaw integration + payments) — committed
- **Both rubric items hit:**
  1. **OpenClaw integration:** `keeperlink-service` on Node B is an OpenClaw skill that wraps KeeperHub's MCP server. Demonstrable end-to-end.
  2. **Payments:** native x402 USDC on Base — paid workflows return x402 v2 envelopes; Node A signs and pays. No third-party x402 gateway.
- **Depth (multiple surfaces touched):**
  - **MCP `ai_generate_workflow`** — natural language → workflow definition. Demoable.
  - **MCP `create_workflow`** — persists workflow to org. *Done Apr 25.*
  - **MCP `execute_protocol_action`** — direct execution path; useful as fallback or for the quote step. *Validated Apr 25.*
  - **REST `/api/mcp/workflows/<slug>/call`** — bazaar invocation surface. Path A pattern.
  - **Native plugins** — `uniswap/swap-exact-input`, `uniswap/quote-exact-input` — both validated.
- **Wallet model:** KeeperHub-managed (Turnkey MPC). Spending caps configurable. No raw key handling on our side.
- **Real utility:** retry, gas-opt, audit, private mempool inherited from KeeperHub.

### Uniswap Foundation — committed
- **Criteria:** "Best Uniswap API Integration — give your agent the ability to swap and settle value onchain." $2,500 / $1,500 / $1,000.
- **Required:** `FEEDBACK.md` in repo root. *Drafted Apr 25, ongoing log.*
- **Path:** KeeperHub's `uniswap/quote-exact-input` + `uniswap/swap-exact-input` actions natively wrap Uniswap V3. Quote validated on Base USDC→WETH 0.05% fee tier on Apr 25. Swap path validated next once Base wallet is funded (Apr 26 morning).

### 0G Track 1 (Best Agent Framework, Tooling & Core Extensions) — committed
- **Criteria:** "Framework-level innovations using OpenClaw or alternatives on 0G."
- **Our framework contribution:** the OpenClaw Audit Envelope (above). Reusable across any OpenClaw agent mesh. Any agent that completes a hired job produces and persists one. Verification primitive that doesn't depend on any specific execution path.
- **SDK:** `@0gfoundation/0g-ts-sdk` (TypeScript). Upload `MemData` → `merkleTree` → `indexer.upload` → returns `rootHash`. Auth is signer + RPC + indexer RPC; no API key needed.
- **Why this wins framework track:** we're extending OpenClaw with a 0G-backed audit primitive, not just persisting a receipt. The schema, the verifier, and the reusable Pydantic model are the framework-level contribution.

### KeeperHub Builder Feedback Bounty — committed
- One `FEEDBACK.md` satisfies both Uniswap qualification AND this bonus.
- Section 1 = Uniswap integration friction (DX with KeeperHub's wrapped surface vs direct Trading API).
- Section 2 = KeeperHub integration friction (the `Direct Execution API` doc-vs-reality gap, the bazaar listing UX gap, the ai_generate_workflow output template gaps).
- Up to 2 winners receive $250 each.

---

## Repo layout (current)

Already scaffolded Apr 25. Diff-from-plan: docker-compose stub is minimal until both services have working entrypoints. CI is `ruff` + `mypy --strict shared/`.

```
openclaw-keeperlink/
├── README.md
├── ARCHITECTURE.md          (this doc)
├── FEEDBACK.md              (Uniswap qual + KH bonus, ongoing log)
├── LICENSE                  (MIT)
├── docker-compose.yml       (two-node local stack)
├── .env.example             (all five sponsor surfaces)
├── .gitignore               (excludes .env, keys, ~/.config/keeperhub)
│
├── skills/openclaw-keeperlink/
│   ├── SKILL.md             (frontmatter: post-job, status, check-receipts, verify)
│   └── keeperlink_client.py (subcommand dispatch)
│
├── node-a/
│   └── poster.py            (Sophia-persona poster client)
│
├── node-b/
│   └── keeperlink_service.py (MCP service that hosts the keeperlink AXL endpoint)
│
├── shared/
│   ├── schemas.py           (JobRequest, Receipt, AuditEntry — Pydantic v2)
│   ├── audit_envelope.py    (OpenClaw Audit Envelope — TBD task #8)
│   ├── x402.py              (sign + verify x402 v2)
│   ├── keeperhub.py         (MCP session + workflow execution)
│   ├── uniswap.py           (optional — Trading API direct calls for breadth)
│   ├── zerog.py             (upload + download via 0G TS SDK helper)
│   └── axl_client.py        (AXL HTTP wrapper, hire + capability gossip)
│
├── scripts/
│   ├── sanity-check.sh      (pass/fail on each integration in isolation)
│   └── zerog_helper.js      (TS bridge for 0G SDK — TBD)
│
├── docs/
│   ├── demo.md              (judge-facing 30-second walkthrough)
│   ├── kill-tests/
│   │   ├── keeperhub-day1.md
│   │   ├── uniswap-day1.md
│   │   └── workflow-publishing-day2.md
│   └── screenshots/         (basescan tx, 0G rootHash, split-terminal frames)
│
└── .github/workflows/ci.yml
```

---

## Build sequencing — revised after Day 2

Original plan (v3) put Day 1 as four isolated kill-tests. We're a day late; Days 1-2 collapsed into today (Apr 25). Revised remaining schedule:

| Day | Date (CT) | Goal | Risk kill-check |
|-----|-----------|------|-----------------|
| ~~Day 1~~ | Apr 24 | Skipped | (rolled into Day 2) |
| **Day 2** | **Apr 25** | ✅ Repo skeleton + KeeperHub + Uniswap quote + workflow author paths green. ARCHITECTURE v4 + audit envelope schema drafted. | KeeperHub *and* workflow paths confirmed green. |
| **Day 3** | Sat Apr 26 | Fund Base wallet (0.01 ETH + 5-10 USDC). Run real `uniswap/swap-exact-input` via published workflow. AXL kill-test on two local nodes. 0G testnet upload + verify. | First real on-chain swap = MVP demoable. |
| **Day 4** | Sun Apr 27 | x402 sign + verify on the AXL hire path. Bazaar listing UX figured out. | x402 + bazaar listing unblock the published-workflow demo. |
| **Day 5** | Mon Apr 28 | Wire all five layers end-to-end. First clean dry-run reproducing in 30 seconds. 0G round-trip verify. | Full 5-layer demo loop closes. |
| **Day 6** | Tue Apr 29 | Polish: error handling, docker-compose for judges, 5× clean reproducibility. | Demo blind at least once. |
| **Day 7** | Wed Apr 30 | Demo video (3 min) recorded. Asciinema captures. Thumbnail. | |
| **Day 8** | Thu May 1 | README final polish, ARCHITECTURE v5 freeze, FEEDBACK final. | |
| **Day 9** | Fri May 2 | Buffer: last-mile fixes from dry-run feedback, final submission artifacts staged. | Anything still failing → cut it. |
| **Morning Day 10** | **Sat May 3 (by 11 AM CT)** | **Submit.** File KeeperHub + Uniswap feedback-bounty entries. | **Hard deadline.** |

---

## Anti-scope-creep (carried forward from v3)

We will NOT build:
- Custom wallet orchestration (KeeperHub Turnkey MPC handles it)
- Multi-agent personality sandbox (no Sophia/Boris show-reel)
- Dashboard / frontend UI (CLI is the demo)
- Marketplace front-end (RIP-302 stays in RustChain, not ported)
- Novel cryptography / fingerprinting (RIP-PoA stays out)
- Pre-hackathon implementation (all submitted code Apr 24+)

**Carried from Codex review:** also will NOT make both A→B and B→KeeperHub payment hops demo-critical. One visible x402 payment is enough for judges.

---

## Demo visual (frozen)

Split-screen terminal:

- **Left pane:** Node A — capability discovery over AXL → x402 USDC sign → AXL hire fired
- **Right pane:** Node B — AXL hire received → x402 verified → KeeperHub workflow invoked → tx hash emitted → audit envelope built → 0G uploaded → receipt returned
- **Overlay:** live Base tx link on basescan + "settled in X seconds, 0 failures"

30-second loop. No UI. No dashboard. Non-Ethereum viewer understands instantly.

---

## Reference

- ETHGlobal Open Agents: https://ethglobal.com/events/openagents
- Prior art: Hubble Trading Arena (ETHGlobal Buenos Aires winner)
- Codex adversarial review: invoked Apr 25; surfaced Path B as submission core, AXL as labor market, audit envelope as 0G framework angle.
- Day-1/Day-2 kill-test transcripts: `docs/kill-tests/`
