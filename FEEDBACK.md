# Builder Feedback — Uniswap + KeeperHub

> Honest, specific, reproducible notes from building OpenClaw KeeperLink during ETHGlobal Open Agents (Apr 24 – May 3, 2026). One file satisfies both Uniswap track qualification and the KeeperHub Builder Feedback Bounty.

**Solo builder:** Scott Boudreaux / Elyan Labs
**Build environment:** Ubuntu 25.10, Python 3.13, Node 22 (POWER8 + x86 mix)
**Time-boxed:** ~9.5 days, all integrations new to this builder

---

## Section 1 — Uniswap Trading API integration

*Filled in during build. Sections below are placeholders to be replaced with real friction notes as integration proceeds.*

### 1.1 First impressions / dashboard signup
*[TBD — will record on Day 1 when fetching API key from developers.uniswap.org/dashboard]*

### 1.2 `/quote` endpoint
*[TBD — Day 1 kill-test]*

### 1.3 `/swap` endpoint + execution path
*[TBD]*

### 1.4 SDK vs raw API
*[TBD]*

### 1.5 Documentation gaps encountered
*[TBD]*

### 1.6 What worked well
*[TBD]*

### 1.7 Suggested improvements
*[TBD]*

---

## Section 2 — KeeperHub integration

### 2.1 Account setup + API key provisioning
**Apr 18, 2026** — Signed up via GitHub OAuth (Scottcjn). Default org auto-created. Generating an API key was straightforward; key format `kh_` + 35 chars stored to `~/.config/keeperhub/keys.json` with `0600` permissions. Wallet auto-provisioned via Turnkey MPC integration with the email I supplied. Address came back within the same session.

**Friction:** None at signup.
**Suggestion:** A "you've created your first wallet — fund it on these networks" UX nudge would help newcomers know they need to top up before the API works for state-changing calls.

### 2.2 Direct Execution API → workflow-based API

**Apr 25, 2026** — The pre-event docs and provisioning checklist (referenced from `docs.keeperhub.com/api`) described a "Direct Execution API" with endpoints like `POST /api/execute/transfer` and `POST /api/execute/contract-call`. **These endpoints don't exist on the live API.** The actual surface, per `https://app.keeperhub.com/openapi.json`, is workflow-based:

- `POST /api/mcp/workflows/<slug>/call` — execute a workflow
- `GET /api/mcp/workflows` — federated bazaar listing
- `GET /api/workflows` — your org's private workflows
- `GET /api/chains` — chain registry

**Friction (medium):** The "Direct Execution" branding in older docs misled my Day-0 planning by ~3 hours. I built a Pydantic schema and HTTP client for endpoints that didn't exist. Once I hit `/openapi.json` (HTTP 200, but not linked from anywhere I could find), the real surface clicked instantly.

**Suggestion:** Add a 1-line "API surface overview" section near the top of `docs.keeperhub.com/api` saying "KeeperHub is workflow-based. Each workflow has an HTTP endpoint at `/api/mcp/workflows/<slug>/call`. There is no separate Direct Execution surface — wrap the action you want in a workflow." That single sentence would have saved my Day-0 prep.

**What actually worked great:**
- Auth: `X-API-Key: kh_...` accepted on first try (no need for the speculatively-suggested `keeper_` prefix)
- `helloworld` workflow returned a clean execution result in under 200ms
- The OpenAPI spec at `/openapi.json` is well-structured 3.1, includes the x402 payment shape inline via `x-payment-info` extension — easy to consume programmatically

### 2.3 MCP server (`https://app.keeperhub.com/mcp`)
*[TBD — will hit `tools/list` first to confirm transport, then `ai_generate_workflow` for the natural-language demo path]*

### 2.4 Native plugins (Uniswap, Aerodrome)
*[TBD]*

### 2.5 x402 integration

**Apr 25, 2026** — Discovered during the helloworld kill-test that x402 is **native** at the protocol level, not a plugin. Calling a paid workflow without payment returns a complete x402 v2 envelope:

```json
{
  "x402Version": 2,
  "error": "Payment required",
  "accepts": [{
    "scheme": "exact",
    "network": "eip155:8453",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "amount": "10000",
    "payTo": "0x52a93213b2748c8121691110ffb1c9389bd22308",
    "maxTimeoutSeconds": 300,
    "extra": {"name": "USD Coin", "version": "2"}
  }]
}
```

**What's great:** No glue code needed. The 402 response is fully spec-compliant — any x402 client library can consume it directly. Payment network is Base USDC, which is exactly where agent payments should live.

**Mild friction:** `amount` is in atomic units (no `decimals` field in the envelope). I had to look up that USDC has 6 decimals to confirm `10000 = $0.01`. The `extra.name` field hints at the asset but doesn't assert decimals. Adding `extra.decimals: 6` would be more self-describing.

**Suggestion:** Document the `x-payment-info` OpenAPI extension somewhere prominent in the developer portal. It's a really nice pattern for declaring per-endpoint pricing in spec form, but I only discovered it by reading the raw OpenAPI.

### 2.6 Documentation gaps encountered
*[TBD]*

### 2.7 What worked well
*[TBD]*

### 2.8 Suggested improvements
*[TBD]*

---

## Reproducibility notes

All integration tests in this build are reproducible from a fresh clone:

```bash
git clone https://github.com/Scottcjn/openclaw-keeperlink
cd openclaw-keeperlink
cp .env.example .env  # fill in real keys
./scripts/sanity-check.sh
```

`sanity-check.sh` hits each integration point in isolation and prints pass/fail. See `docs/demo.md` for the end-to-end orchestration.
