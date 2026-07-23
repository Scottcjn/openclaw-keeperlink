# The OpenClaw KeeperLink Protocol

> A specification for trust-minimized peer-to-peer hiring of autonomous agents to perform on-chain actions, with cryptographic settlement evidence.

**Version:** 0.1 (draft, ETHGlobal Open Agents 2026 reference implementation)
**Author:** Scott Boudreaux / Elyan Labs
**Reference implementation:** https://github.com/Scottcjn/openclaw-keeperlink
**Status:** demo-grade, mainnet-verified, intentionally minimal — extensible by additive fields rather than breaking changes.

---

## 1. Abstract

OpenClaw KeeperLink is a five-phase protocol for two autonomous agents on independent machines to negotiate, transact, and verify the outcome of an on-chain action without any broker, escrow, or shared infrastructure. The hiring agent (the **Poster**) discovers a service-providing agent (the **Service**) over an encrypted peer-to-peer mesh, signs a stablecoin payment header, and dispatches a structured job request. The Service verifies the payment, executes the requested action through a designated execution environment, wraps the full lineage of the interaction in a signed envelope, and pins the envelope to decentralized storage. The Poster then independently round-trip-verifies the receipt — content match, signature integrity, on-chain confirmation — without trusting either the Service or the storage layer.

The protocol does not specify any particular DEX, chain, payment standard, mesh transport, or storage backend. The reference implementation pairs **Yggdrasil-mesh AXL** for transport, **x402** for the payment header, **KeeperHub MCP** for execution, **Uniswap V3 on Base mainnet** as the settlement venue, and **0G Galileo testnet** for envelope storage — but each layer is replaceable with an equivalent that satisfies the role contracts below.

## 2. Roles

| Role | Responsibility |
|---|---|
| **Poster** | Constructs the JobRequest, signs the payment header, hires the Service, receives and independently verifies the receipt. Holds no execution capability — pays for it. |
| **Service** | Discoverable over the mesh. Verifies the payment header. Executes the job through its delegated execution environment. Signs and persists the audit envelope. Returns the storage pointer to the Poster. |

The protocol is **strictly two-party**. Discovery, payment, and execution are the Poster's responsibility to verify; persistence and signing are the Service's. There is no third-party arbiter, escrow, or marketplace. Disputes are resolved by inspecting the on-chain action and the stored envelope.

## 3. Phases

```
       Poster                                            Service
         │                                                 │
   [1] ──┼─► discover (mesh)                               │
         │  ◄─────────────────────────  pricing payload ───┤
         │                                                 │
   [2] ──┤  build JobRequest                               │
         │  sign x402 payment header                       │
         │                                                 │
   [3] ──┼─► hire (mesh, structured payload + payment) ────┤
         │                                       verify_x402
         │                                                 │
   [4] ──┤                                       execute via execution env
         │                                       sign audit envelope
         │                                       upload to storage
         │  ◄────────────────────────────  receipt + ptr ──┤
         │                                                 │
   [5] ──┤  download envelope from storage                 │
         │  verify content hash                            │
         │  verify Service signature                       │
         │  confirm on-chain action via independent RPC    │
         │                                                 │
         ▼                                                 ▼
       PROOF                                            PAID
```

### Phase 1 — Discovery

The Poster locates the Service over an encrypted peer-to-peer mesh and requests a pricing payload. The Service responds with the price (asset, amount, payee), the supported job types (`capabilities`), and any execution metadata.

The mesh transport is opaque to the protocol; the only requirement is that messages between Poster and Service are confidential and integrity-protected. The reference implementation uses **AXL** (Yggdrasil-mesh-routed MCP envelopes); a TCP+TLS direct path also works.

**Pricing payload (response):**
```jsonc
{
  "status": "ok",
  "service": "<service-name>",
  "pricing": {
    "scheme": "exact",
    "network": "eip155:8453",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "amount": "10000",                      // atomic, e.g. 0.01 USDC
    "payTo": "0xa13944De329EaC2658FB7DC0b6BBC523A0a697C3",
    "maxTimeoutSeconds": 300,
    "extra": { "name": "USD Coin", "version": "2" }
  },
  "node_b_address": "0xa139...",
  "chain": "base",
  "capabilities": ["discover", "hire"]
}
```

### Phase 2 — Hire

The Poster builds a `JobRequest` describing the desired action and signs an `x402` payment header authorizing the price quoted in Phase 1. The signed header proves the Poster owns the funds it claims and authorizes the Service to settle the payment if the job is accepted.

### Phase 3 — Verification

The Service verifies the `x402` header against the pricing it advertised:

- correct payee
- correct asset
- amount ≥ quoted price
- network matches
- signature recovers to the declared payer
- header is not replayed: the nonce must equal `{job_id}:{job_digest}` for the
  job being hired, so a header authorizes that job and nothing else

A failed verification returns a structured error with the failure reason. A successful verification proceeds to Phase 4 immediately — there is no held escrow.

### Phase 4 — Execution + Attestation

The Service executes the job through its **execution environment** (in the reference: KeeperHub MCP wrapping a Uniswap V3 swap, with on-demand `erc20.approve` if allowance is short). The execution returns a transaction hash plus any structured result data.

The Service then constructs an **OpenClaw Audit Envelope** that wraps:

- the original `JobRequest` (canonical JSON)
- the verified `x402` proof
- the execution-environment record (e.g., KeeperHub `executionId`, action type, params)
- the on-chain settlement (chainId, tx_hash, basescan URL)
- a Service signature over the canonical JSON of the above

The envelope is canonicalized (sorted keys, no whitespace) and uploaded to a content-addressed storage backend (reference: 0G). The storage returns a `rootHash` (or equivalent content identifier).

The Service responds to the Poster with the storage pointer + the tx hash + the executor's signature.

### Phase 5 — Independent Verification

The Poster does NOT trust the Service. It downloads the envelope from the storage backend using the returned pointer, then independently verifies:

1. **Content match** — SHA-256 of the downloaded canonical JSON equals the hash the Poster computes from the stored fields. This catches any post-upload mutation.
2. **Signature integrity** — the Service's signature recovers to the address the Service declared in Phase 1.
3. **On-chain confirmation** — the tx hash appears at the claimed block on the claimed chain via an RPC the Poster controls (not the Service's RPC).

Only when all three checks pass does the Poster mark the receipt as PROVEN.

A failure at any step is a public, reproducible, and content-addressed accusation: anyone can re-download the envelope and reproduce the verification.

## 4. Data structures

All data structures are JSON, canonicalized via sorted keys + no whitespace before signing or hashing. Integers are strings in atomic units to avoid float precision loss.

### 4.1 JobRequest

```jsonc
{
  "job_id": "demo_<random-hex>",
  "intent": "human-readable description of the action",
  "kind": "swap",                     // protocol-extensible enum
  "chain": "base",
  "token_in": "0x833589fC...",
  "token_out": "0x42000000...",
  "amount_in": "0.10",               // human units, Decimal-friendly
  "poster_address": "0x46b264...",
  "x402_payment_header": "<base64-encoded x402 envelope>"
}
```

### 4.2 OpenClaw Audit Envelope

```jsonc
{
  "version": "openclaw/v0.1",
  "job_id": "demo_<random-hex>",
  "job_request": { /* full JobRequest from above */ },
  "x402_payment_proof": {
    "payer": "0x46b264...",
    "payee": "0xa13944...",
    "asset": "0x833589fC...",
    "amount_atomic": "10000",
    "network": "eip155:8453",
    "signature": "0x...",
    "valid": true
  },
  "execution": {
    "environment": "keeperhub",
    "execution_id": "<KH execution id, if any>",
    "action_type": "uniswap/swap-exact-input",
    "action_params_hash": "<sha256 of canonical params>"
  },
  "settlement": {
    "chain_id": 8453,
    "tx_hash": "0xeb85abef...",
    "block_number": 45453249,
    "explorer_url": "https://basescan.org/tx/0xeb85abef..."
  },
  "service_address": "0xa13944...",
  "service_signature": "0x...",   // signature over canonical JSON of all above fields
  "created_at": 1777695845
}
```

### 4.3 Receipt (Service → Poster, returned in Phase 4)

```jsonc
{
  "ok": true,
  "job_id": "demo_<random-hex>",
  "tx_hash": "0xeb85abef...",
  "amount_out": "0.000043",
  "basescan_link": "https://basescan.org/tx/0xeb85abef...",
  "envelope_storage_root": "0xa45c313d...",   // 0G rootHash in reference impl
  "service_signature": "0x..."
}
```

## 5. Replaceable surfaces

| Layer | Reference choice | Replaceable with |
|---|---|---|
| Mesh transport | AXL (Yggdrasil) | libp2p, Hypercore, Iroh, direct WSS — anything confidential + integrity-protected |
| Payment header | x402 | EIP-3009 standalone, Permit2 + sig, ERC-4337 paymaster |
| Execution env | KeeperHub MCP | Direct contract call from Service-controlled signer, Gelato Relay, OpenZeppelin Defender |
| Settlement chain | Base mainnet | Any EVM chain with a settled tx hash |
| Storage backend | 0G Galileo | IPFS, Arweave, Filecoin, EigenDA — anything content-addressable |

A future revision will likely formalize the role contracts as Pydantic schemas and publish them as a pip package (`openclaw-protocol`) so that any agent on any stack can implement either side.

## 6. What the protocol does NOT specify

- **Pricing discovery / negotiation** — the reference uses static pricing per Service. A registry, marketplace bid/ask, or off-protocol negotiation is the implementer's choice.
- **Service capability advertisement** — currently a static `capabilities` array. Production implementations will want a richer schema (input/output token sets, gas tolerances, slippage bounds, latency SLA).
- **Service reputation / trust score** — out of scope. A reputation layer can be built atop the audit envelopes (Service X has N proven envelopes over T months).
- **Dispute resolution** — there isn't any, by design. The proof OR its absence is the dispute outcome.
- **Multi-step jobs** — Phase 4 is a single execution. Composed flows (e.g., approve → swap → bridge) are encoded as a single `kind` with a richer `JobRequest`, OR as a sequence of distinct hires.

## 7. Why this protocol matters

Most agentic-payment demos in 2025-2026 either (a) trust a central marketplace to settle between agents, or (b) handwave the proof step ("the agent did the thing, see this screenshot"). OpenClaw KeeperLink shows that with off-the-shelf primitives — encrypted mesh, stablecoin signature, MCP-delegated execution, content-addressed storage — two agents can transact directly with cryptographic proof of every step, no broker required.

The reference implementation's most boring property is its most important one: **the Poster never has to trust the Service, the Service never has to trust the Poster, and neither has to trust the platform.** Everything is signed by an identifiable address, content-addressed at a verifiable hash, settled on a public ledger, and stored on a backend either party can independently query. That's the whole game for autonomous-agent commerce.

---

**Companion documents:**
- `README.md` — what it is, how to run it, real artifacts
- `ARCHITECTURE.md` — implementation detail of the reference stack
- `FEEDBACK.md` — sponsor-track integration notes (Uniswap §1, KeeperHub §2)
- `shared/audit_envelope.py` — the Pydantic schema for the envelope (reference impl)
- `node-a/poster.py` — Poster role (reference impl)
- `node-b/keeperlink_service.py` — Service role (reference impl)
