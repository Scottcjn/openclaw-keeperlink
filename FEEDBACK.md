# Builder Feedback — Uniswap + KeeperHub

> Honest, specific, reproducible notes from building OpenClaw KeeperLink during ETHGlobal Open Agents (Apr 24 – May 3, 2026). One file satisfies both **Uniswap track qualification** (required `FEEDBACK.md`) and the **KeeperHub Builder Feedback Bounty** ($500, two winners at $250 each).

**Solo builder:** Scott Boudreaux / Elyan Labs
**Build environment:** Ubuntu 25.10, Python 3.13, Node 22 (POWER8 + x86 mix)
**Time-boxed:** ~9.5 days, all integrations new to this builder

---

## Section 1 — Uniswap integration

### 1.1 What I integrated

KeeperHub's native Uniswap V3 actions: `uniswap/quote-exact-input` and `uniswap/swap-exact-input`, accessed via two surfaces:

1. **MCP `execute_protocol_action`** (JSON-RPC at `https://app.keeperhub.com/api/mcp`)
2. **REST `/api/mcp/workflows/<slug>/call`** when wrapping the swap action in a published workflow

I did **not** end up calling Uniswap's standalone Trading API (`trade-api.gateway.uniswap.org/quote`) directly — KeeperHub's wrapper was complete enough to satisfy the swap path, and adding a second integration just for breadth would have been busy-work for a solo build.

### 1.2 The discovery: `/quote` round-trip via KeeperHub action

**Apr 25, 2026 — Day 1 kill-test (`docs/kill-tests/uniswap-day1.md`):**
A `uniswap/quote-exact-input` call against Base USDC→WETH at the 0.05% fee tier returned a clean route with output amounts in WETH atomic units. Latency was sub-second, no auth surprises, no version-pin issues.

**Friction:** The Uniswap action takes `network` as a stringified chainId (`"8453"`) but other KeeperHub APIs take `chain` as a slug (`"base"`). I inferred the right field from `/openapi.json` — but the docs page I started from didn't note the difference. **Suggestion:** add a one-line "all action params accept stringified chainId in `network`" header to the action reference.

### 1.3 The actual swap path

For `uniswap/swap-exact-input` to settle on Base, the executing wallet (KeeperHub-managed via Turnkey MPC) needs USDC + ETH for gas. With ~$10 USDC + ~$3 ETH on the org wallet, swap-exact-input takes USDC → WETH at the configured fee tier and returns `transactionHash` + a basescan URL. KeeperHub handles slippage protection by accepting `amountOutMinimum`; default behavior used the calculated quote with a small tolerance.

### 1.4 SDK vs raw API decision

I considered importing `@uniswap/sdk-core` + `@uniswap/smart-order-router` into a Node sidecar, but the moment I saw KeeperHub's wrapper exposed both quote and swap as MCP actions, the SDK route became dead weight. **For agent builds where you want least-glue execution, prefer the platform's wrapped action over the SDK direct.** The SDK wins if you need quote-aggregation / multi-hop routing logic the wrapper doesn't expose; for a single-pair swap on Base the wrapper is enough.

### 1.5 Documentation gaps encountered

| Gap | Where | Suggested fix |
|---|---|---|
| `network` vs `chain` parameter naming inconsistency between actions | Action reference | One-line header note |
| Which fee tier KeeperHub picks by default for V3 swaps | `uniswap/swap-exact-input` action page | Add `feeTier` param documentation + default |
| Slippage default for `amountOutMinimum` | Same | State the default tolerance explicitly |
| No clear "graduating from quote to swap" example with state-changing call | Tutorials | A 3-step copy-paste demo would unblock newcomers |

### 1.6 What worked well

- **No SDK install needed** for a basic swap demo. Just a JSON-RPC POST to KeeperHub's MCP endpoint. Massive friction reduction vs the typical "install 5 packages, pin 3 versions" path.
- **Quote endpoint was instantaneous** and the route metadata was rich enough to display in a CLI demo without any post-processing.
- **Token addresses were the standard Base canonical USDC + WETH** — no goose-chase for which deployment to use.

### 1.7 Suggested improvements

1. **A "Uniswap V3 swap quickstart" page** that walks from `quote-exact-input` → `swap-exact-input` with one wallet, one chain, one fee tier. The current docs cover the action surface but assume you already know the V3 conceptual model.
2. **Surface the underlying Router contract address** in the action response. Right now you have to look it up separately if you want to verify the tx came through Uniswap's official Router and not a fork.
3. **A "deltas vs amounts" mode flag** for output. Right now you get `amountOut`; sometimes for downstream auditing you want `(amountInActual, amountOutMin, amountOutActual, slippage)` as a structured tuple.

---

## Section 2 — KeeperHub integration

### 2.1 Account setup + API key provisioning

**Apr 18, 2026** — Signed up via GitHub OAuth (Scottcjn). Default org auto-created. Generating an API key was straightforward; key format `kh_` + 32 chars stored to `~/.config/keeperhub/keys.json` with `0600` permissions. Wallet auto-provisioned via Turnkey MPC integration with the email I supplied. Address came back within the same session.

**Friction:** None at signup.
**Suggestion:** A "you've created your first wallet — fund it on these networks" UX nudge would help newcomers know they need to top up before the API works for state-changing calls. I learned this when my Day-1 swap returned `insufficient funds` and had to chase down the org wallet address.

### 2.2 Direct Execution API → workflow-based API (the biggest pivot)

**Apr 25, 2026** — The pre-event docs and provisioning checklist (referenced from `docs.keeperhub.com/api`) described a "Direct Execution API" with endpoints like `POST /api/execute/transfer` and `POST /api/execute/contract-call`. **These endpoints don't exist on the live API.** The actual surface, per `https://app.keeperhub.com/openapi.json`, is workflow-based:

- `POST /api/mcp/workflows/<slug>/call` — execute a workflow
- `GET /api/mcp/workflows` — federated bazaar listing (paginated `{items, total, page, limit}`)
- `GET /api/workflows` — your org's private workflows
- `GET /api/chains` — chain registry

**Friction (medium):** The "Direct Execution" branding in older docs misled my Day-0 planning by ~3 hours. I built a Pydantic schema and HTTP client for endpoints that didn't exist. Once I hit `/openapi.json` (HTTP 200, but not linked from anywhere I could find), the real surface clicked instantly.

**Suggestion:** Add a 1-line "API surface overview" section near the top of `docs.keeperhub.com/api` saying "KeeperHub is workflow-based. Each workflow has an HTTP endpoint at `/api/mcp/workflows/<slug>/call`. There is no separate Direct Execution surface — wrap the action you want in a workflow, OR call `execute_protocol_action` via the MCP server." That single sentence would have saved my Day-0 prep.

**What actually worked great:**
- Auth: `X-API-Key: kh_...` accepted on first try (no need for the speculatively-suggested `keeper_` prefix).
- `helloworld` workflow returned a clean execution result in under 200ms.
- The OpenAPI spec at `/openapi.json` is well-structured 3.1, includes the x402 payment shape inline via `x-payment-info` extension — easy to consume programmatically.

### 2.3 MCP server (`https://app.keeperhub.com/api/mcp`)

**Apr 25 → May 1** — The MCP server accepts JSON-RPC 2.0 calls (`tools/list`, `tools/call`) with `X-API-Key` auth, and exposes ~20+ tools including `ai_generate_workflow`, `create_workflow`, `execute_workflow`, `execute_protocol_action`, `list_workflows`. This is where most of the leverage lives.

**Friction (medium):**
1. **Two MCP URLs in the wild** — `https://app.keeperhub.com/mcp` and `https://app.keeperhub.com/api/mcp`. The former returned `{"error":"invalid_token","error_description":"Missing or invalid access token"}` with my `kh_` API key, which suggested an OAuth-style bearer flow. The latter accepts `X-API-Key` and works. I burned ~30 minutes deciding which to use; a "always use `/api/mcp` for direct integrations; `/mcp` is for browser MCP client OAuth flow" note in docs would have been the fix.

2. **`tools/list` response shape** — when I curled it with the wrong content negotiation, the response was streamed in a chunked binary form that failed `json.load()`. Discovered later that `tools/list` returns a normal JSON-RPC response if you accept the right MIME — but the failure mode was opaque. **Suggestion:** echo a `406 Not Acceptable` with a hint instead of streaming binary.

3. **`execute_protocol_action` result is double-wrapped** — the JSON-RPC response wraps the action result in `result.content[0].text`, where `text` is a JSON-stringified blob you then have to parse again. That's standard MCP, but I had to write a `_unwrap_mcp_text` helper specifically. **Suggestion:** since most of the time you want the structured result directly, offer a `text/structured` content type that returns the parsed object inline.

**What worked great:** `ai_generate_workflow` produced a usable workflow definition for "swap USDC for WETH on Base" on the first try. Output was a clean ops-list ready to feed into `create_workflow`. The model picked sensible defaults for fee tier and slippage. Real model sweat behind a clean API surface.

### 2.4 Native plugins (Uniswap V3, Aerodrome)

The Uniswap V3 plugin is covered in Section 1. **Aerodrome** I briefly tested via `aerodrome/quote-exact-input` for a sanity check on the BASE → AERO pair — also worked. The pattern is consistent across plugins, which makes the bazaar feel composable rather than per-protocol bespoke.

**Suggestion:** A side-by-side "plugin parity matrix" page would help builders pick. Right now you have to discover plugins by reading the bazaar listings or grepping `actionType` enums.

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

**Caveat for our build:** For our agent-to-agent payment hop (Node A pays Node B, *separate from* Node B paying KeeperHub), we shipped a **declarative x402 promise** — EIP-191-signed payment-intent header, no actual on-chain settlement. Real x402 would use EIP-3009 `transferWithAuthorization` to settle USDC on Base in the same flow. That was a deliberate scope cut for the deadline; documented in `shared/x402.py` docstring.

**Suggestion:** Document the `x-payment-info` OpenAPI extension somewhere prominent in the developer portal. It's a really nice pattern for declaring per-endpoint pricing in spec form, but I only discovered it by reading the raw OpenAPI.

### 2.6 The bazaar listing UX gap

**May 1, 2026** — `GET /api/mcp/workflows?search=keeperlink` returns the federated bazaar paginated `{items: [...], total: N, page, limit}` shape. This is great for cross-org discovery, but:

1. **No way to filter by `chainId`** — I had to download all 26 items and filter client-side
2. **`organizationId` is opaque** — there's no org-name lookup endpoint, so I can't see at a glance which orgs are publishing what
3. **`workflowType` and `category` are unstructured strings** — `read | write | defi | verification` mixed shape; would benefit from a typed enum

**Suggestion:** Add `?chainId=8453&workflowType=write&category=defi` server-side filters; that's the search query agent builders actually want.

### 2.7 The workflow publishing path I never finished

**May 1, 2026 — deadline pivot** — `keeperlink-swap` (the workflow our v4 architecture references by id `1ao3zjcjngophp36baqht`) was authored via `ai_generate_workflow` on Apr 25 and the kill-test (`docs/kill-tests/workflow-publishing-day2.md`) confirmed the auth + author + persist path worked. But **I could not find a programmatic-create-workflow path that didn't require web UI confirmation steps**, and time ran out before I went through the UI.

**My demo runtime works around this** with a fallback: if `/mcp/workflows/<slug>/call` returns 404, Node B falls back to MCP `execute_protocol_action` with the same `uniswap/swap-exact-input` action under the hood. Same KeeperHub surface, same Uniswap V3 plugin, no published workflow object required.

**Suggestion:** Document `create_workflow` (the MCP tool) prominently with a complete "publish your first workflow programmatically" recipe. Right now I can find the API but not the recipe; I had to reverse-engineer from existing bazaar listings.

### 2.8 What worked great (consolidated)

- **Auth**: `X-API-Key: kh_...` works first try, no token rotation friction during the build.
- **Turnkey MPC wallet**: zero handling of raw private keys on my side. I just trust the org wallet on Base.
- **Native protocol actions**: Uniswap V3 + Aerodrome are wrapped to identical-shape MCP calls. Once you know the pattern, every supported protocol is one tool call away.
- **x402 native**: the 402 envelope is a real spec-compliant response, not a vendor-special. Any x402 client can consume it.
- **OpenAPI spec is real**: `/openapi.json` is clean, well-structured 3.1, machine-readable. I generated my Python typed wrapper directly from it.
- **Federated bazaar is a great idea**: 26 workflows from 10+ orgs visible from one endpoint is exactly the agent-discovery primitive you want.

### 2.9 Suggested improvements (consolidated)

1. **One canonical "API surface overview" page** that names all 5 surfaces (REST workflows, MCP server, OpenAPI spec, x402 envelopes, bazaar pagination) in one place. Right now they're discoverable but scattered.
2. **`?chainId=` and `?category=` server-side filters** on the bazaar listing endpoint.
3. **A `create_workflow` MCP recipe** — a full publish flow from `ai_generate_workflow` → `create_workflow` → `list_bazaar` confirmation, with a working sample.
4. **Decimals / pricing-meta fields in x402 envelopes** — `extra.decimals: 6` or similar would prevent the "is `10000` a dollar or a cent" lookup.
5. **MCP `execute_protocol_action` result unwrap helper** — or a content-type negotiation that returns the parsed result directly.

### 2.10 Day-9 (May 2 2026) submission-day findings — corrections + new

When I flipped the demo from Sepolia to Base mainnet at the wire on May 2, six new integration issues surfaced. They're all real (each blocked the demo until fixed) and small enough to be cheap to address. Listing them here for the framework feedback bounty:

1. **The MCP endpoint is `/mcp`, not `/api/mcp`** — supersedes §2.3 ¶1. As of today, `https://app.keeperhub.com/mcp` is what returns HTTP 200 with a valid JSON-RPC response; `https://app.keeperhub.com/api/mcp` returns the SPA HTML 404 page. My §2.3 note had it inverted; the endpoint may have moved or my earlier diagnosis was wrong. Either way, today's truth is `/mcp` on the host root.

2. **MCP requires `Accept: application/json, text/event-stream`** — without it, KeeperHub's edge serves the SPA HTML page instead of JSON-RPC. Most HTTP libraries don't auto-set this, so a clean curl works while a default `httpx.Client(...)` silently fails JSON-decode. **Suggestion:** call this header out in any "use the MCP from your own client" doc snippet, or have the server return `406 Not Acceptable` with a hint when the header is missing.

3. **`/mcp` issues HTTP 308 → `/mcp/`** — clients with `follow_redirects=False` (httpx default, requests with `allow_redirects=False`) read the redirect's body as the JSON-RPC response and crash at parse time. **Suggestion:** either accept both forms server-side, or document the trailing slash, or both.

4. **`uniswap/swap-exact-input` requires V3-shape params** — `fee` (uint24), `recipient`, `amountOutMinimum`, `sqrtPriceLimitX96`. KH validates each one and bails with `Invalid function arguments: params.X is missing` before reaching the chain. The label "Uniswap V3" is honest, but the agent-facing promise of "high-level DeFi action" is broken — agents either need to know V3 mechanics (per-pair fee tiers, slippage math, sqrt-price encoding) or call `quote-exact-input` first to derive them. **Suggestion:** ship a higher-level `uniswap/swap-exact-input-simple` that takes only `tokenIn/tokenOut/amountIn/slippageBps`, auto-quotes for fee tier, and emits a single round-trip.

5. **No bundled approve+swap action** — agents must `execute_contract_call` for `erc20.approve(router, amount)` separately, then `uniswap/swap-exact-input`. That's two round-trips for one logical operation. The first swap on a fresh wallet always fails `Error(STF)` until the agent figures out to approve first. **Suggestion:** an `auto_approve: true` flag on swap actions that emits the approve as a sub-step when allowance is short, or a documented `swap-with-permit` variant for Permit2-aware tokens.

6. **`transactionHash` field naming** — KH's swap response returns the camelCase `transactionHash`, not the more common `tx_hash` / `txHash`. Agent-side parsers built for one convention silently miss the other (in our case, `_find_tx_hash` matched on the substring `"tx"` and dropped `transactionHash`, producing the misleading "workflow response did not include a tx hash" error on successful swaps). **Suggestion:** publish the response schema (Zod or JSON-Schema) for each action so agent-side code can be matcher-free.

---

## Meta: honest overall take

KeeperHub's developer surface is the most agent-shaped I've worked with this year. The bazaar + plugins + MCP + x402 stack is already complete enough to build a swap demo end-to-end without writing protocol-specific glue. The friction I hit was mostly **documentation lag** (Direct Execution branding still showing where the workflow API has shipped), not capability gaps.

Uniswap's piece in our build was via KeeperHub's wrapper rather than the standalone Trading API, because KeeperHub had wrapped it well enough that adding a second integration would have been busy-work. That's a quiet endorsement of the wrapper, but also means I have less to say about the Trading API directly than other teams who used it natively.

**Net:** for solo agent builds with a hard deadline and one execution venue, this stack is a strong default. The discoverability gaps in §2.7 are the main thing keeping a newcomer from publishing their first workflow on day one.

---

## Future extensions (out of scope for this submission)

The OpenClaw Audit Envelope primitive (`shared/audit_envelope.py`) is reusable beyond swaps — any OpenClaw agent that completes a hired job can produce one. Two extensions we sketched but deliberately scope-cut:

1. **BoTTube anchor**: publish a short receipt-summary video to BoTTube (the AI-native video platform in our broader Elyan Labs ecosystem) with the basescan link + 0G rootHash in the description. This would give human-readable "video evidence" backing each on-chain action — useful for marketplaces where humans audit agent behavior. Cost: ~50 lines for the upload skill, but adds a non-sponsor surface so it's deferred.

2. **RustChain anchor**: anchor batches of audit envelope rootHashes to RustChain (our hardware-attested L1) every N envelopes. This gives a second independent persistence layer with hardware-fingerprinted node attestation — useful when the bonded layer of trust matters more than just signature + content-address. Same scope-cut reasoning.

Neither was built for this submission per the anti-scope discipline — but the audit envelope schema is forward-compatible with both extensions (additional `anchors` field, additive). Mentioning here so the framework-track judges see the full reuse surface.

---

**Author:** Scott Boudreaux / Elyan Labs (solo build)
**Built during:** Apr 24 – May 3, 2026
**Repo:** https://github.com/Scottcjn/openclaw-keeperlink
