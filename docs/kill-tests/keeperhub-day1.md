# KeeperHub kill-test — Day 1 (Apr 25, 2026)

## Result: ✅ PASS

## Discovery: API surface differs from pre-event docs

The pre-event provisioning notes assumed a Direct Execution API
(`POST /api/execute/transfer`, `POST /api/execute/contract-call`).
**These endpoints do not exist on the public API.** What actually exists:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Health probe (no auth required) |
| `/api/chains` | GET | List supported chains (auth required) |
| `/api/workflows` | GET | List org's workflows (auth required) — empty for new orgs |
| `/api/mcp/workflows` | GET | **Federated bazaar of all public workflows** |
| `/api/mcp/workflows/<slug>/call` | POST | Execute a workflow by slug |
| `/openapi.json` | GET | OpenAPI 3.1 spec (no auth) |

KeeperHub is a **workflow platform**. Workflows are the unit of execution.
Free workflows are called directly. Paid workflows return HTTP 402 with
x402 payment requirements; client signs an x402 header and retries.

## Test 1 — `helloworld` (free workflow)

```bash
curl -X POST \
  -H "X-API-Key: $KH_KEY" \
  -H "Content-Type: application/json" \
  -d '{}' \
  https://app.keeperhub.com/api/mcp/workflows/helloworld/call
```

Response (HTTP 200):

```json
{
  "executionId": "xmujxgtkfteva5mxv2h6a",
  "status": "success",
  "output": {
    "logs": [],
    "result": {"message": "Hello World!"},
    "success": true
  }
}
```

**Confirms:** auth works (`X-API-Key: kh_...`), workflow execution path
green, response shape understood.

## Test 2 — `mcp-test` (paid workflow, no payment) → x402 envelope

```bash
curl -X POST \
  -H "X-API-Key: $KH_KEY" \
  -H "Content-Type: application/json" \
  -d '{"address":"0xe12230149b2d5ed561fa51261fb8e02dbd514724"}' \
  https://app.keeperhub.com/api/mcp/workflows/mcp-test/call
```

Response (HTTP 402):

```json
{
  "x402Version": 2,
  "error": "Payment required",
  "resource": {
    "url": "https://app.keeperhub.com/api/mcp/workflows/mcp-test/call",
    "description": "Pay to run workflow: MCP Test: Prod (Updated)",
    "mimeType": "application/json"
  },
  "accepts": [{
    "scheme": "exact",
    "network": "eip155:8453",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "amount": "10000",
    "payTo": "0x52a93213b2748c8121691110ffb1c9389bd22308",
    "maxTimeoutSeconds": 300,
    "extra": {"name": "USD Coin", "version": "2"}
  }],
  "extensions": {
    "bazaar": {"discoverable": true, "schema": {...}}
  }
}
```

**Confirms:**
- KeeperHub natively returns x402 v2 envelopes — no glue needed on our side
- Payment network is **Base (eip155:8453)** with **USDC** (`0x8335...02913`)
- `accepts.amount` is **atomic units** (USDC has 6 decimals → 10000 = $0.01)
- `payTo` is KeeperHub's settlement address; payment routed through Circle/Coinbase rails

## Strategic implication for OpenClaw KeeperLink

The v3 architecture in `/ARCHITECTURE.md` had Node B make raw contract calls
via a (non-existent) Direct Execution API. The real model is:

1. **Node A** (poster) sends a job over **AXL** to **Node B**
2. **Node B** (worker) calls a **KeeperHub workflow** — either:
   - A workflow Node B published, that wraps Uniswap+plugin, OR
   - A pre-existing workflow from the federated bazaar
3. **Node B pays via x402** if the workflow is paid (USDC on Base)
4. KeeperHub handles retry, gas-opt, audit
5. Node B persists the receipt to 0G and returns it to Node A over AXL

This is **cleaner than the original plan**. KeeperHub already does the
"reliable execution + x402 enforcement" — we just orchestrate it via AXL.

## Action items

- [x] Update `ARCHITECTURE.md` to v4 reflecting workflow-based execution
- [x] Update `FEEDBACK.md` with the API-surface discrepancy note
- [ ] Decide: do we publish our own swap workflow to the bazaar (more depth on 0G framework track) or call existing ones?

## Cost so far

- $0.00 — only free workflow + 402-rejection responses. No mainnet gas burned.
