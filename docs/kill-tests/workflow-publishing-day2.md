# Workflow publishing path — Day 2 (Apr 25, 2026)

## Codex flagged this as the biggest Day-2 risk

Per the architecture pivot review, until we proved a real swap-capable workflow could be **authored**, **persisted**, and **invoked** end-to-end, Path B (publish to bazaar) was story not system. This kill-test resolves it.

## Result: ✅ PASS for author + persist. ⏳ Bazaar listing path TBD.

## What we ran

### Step 1 — `ai_generate_workflow` (natural language → workflow ops)

```python
mcp_call("ai_generate_workflow", {
    "prompt": "Accept tokenIn, tokenOut, amountIn. First call uniswap quote-exact-input on Base. Then call uniswap swap-exact-input on Base using org wallet. Return tx hash + quote.",
    "context": "Bazaar-callable workflow for OpenClaw KeeperLink hackathon. Network must be Base (8453). Use existing wallet integration."
})
```

Response was a stream of JSON-line operations:
- `setName: "ERC20 Swap Workflow on Base"`
- `setDescription: ...`
- `addNode trigger-1` (Manual trigger)
- `addNode quote-input` (uniswap/quote-exact-input)
- `addNode swap-execution` (uniswap/swap-exact-input)
- `addEdge e1: trigger-1 → quote-input`
- `addEdge e2: quote-input → swap-execution`

### Step 2 — `create_workflow` (persist as org workflow)

After parsing the operations into a `{name, description, nodes, edges}` object, we overrode the name to `keeperlink-swap` and submitted via MCP `create_workflow`. Response:

```json
{
  "id": "1ao3zjcjngophp36baqht",
  "name": "keeperlink-swap",
  "description": "Bazaar-callable swap on Base via Uniswap V3...",
  "userId": "cfnEBq83w20N51rBCubc7ksjlFrBkbjh",
  "organizationId": "067adfa2-ad1c-4ea6-ad03-e9f7095dd0fb",
  "isAnonymous": false,
  "featured": false,
  ...
}
```

Workflow exists in our org. Two action nodes wired through Manual trigger.

## Issues found

### Issue 1 — `ai_generate_workflow` doesn't wire quote→swap output references

The generated workflow has `swap-execution` reading `{{input.tokenIn}}`, etc., directly from the trigger input. It does **not** use template syntax to consume the quote's `amountOut` and set `swap-execution.amountOutMinimum`. With `amountOutMinimum = "0"`, the swap accepts any output — fine for a kill-test, lethal for production (sandwich attack vector).

**Fix:** Set `swap-execution.config.amountOutMinimum = "{{@quote-input:Quote Exact Input.amountOut * 0.99}}"` (or whatever KeeperHub's templating syntax supports for arithmetic). Will tighten via `update_workflow` once swap path is funded.

### Issue 2 — Bazaar listing not in MCP tool set

Existing public bazaar workflows (`microtip`, `mcp-test`, `helloworld`) have `listedSlug` and `listedAt` populated. None of the 26 MCP tools have an obvious "publish" or "list" verb. `update_workflow`'s schema only mentions `name`, `description`, `nodes`, `edges`, `projectId`, `tagId`.

**Hypothesis:** Listing happens via the web UI at `app.keeperhub.com`, OR there's an `update_workflow` field we haven't tried (e.g., `listedSlug`, `listed`, or `pricingUsdc`). Will probe + escalate to KeeperHub team if needed.

### Issue 3 — `recipient: "org_wallet"` may be a placeholder, not a literal

The AI generated `swap-execution.config.recipient = "org_wallet"` which probably won't resolve at execution time. Need to substitute the actual wallet address (`0xe122...4724`) or a template like `{{wallet.address}}`. Test on first execution.

## What's proven

- ✅ Auth + MCP session handshake (Bearer + Mcp-Session-Id JWT)
- ✅ Tool discovery (26 tools)
- ✅ `ai_generate_workflow` returns structured workflow ops from NL prompt
- ✅ `create_workflow` persists workflow, returns workflow ID
- ✅ Workflow visible in `list_workflows` for the org
- ⏳ Manual execution via `execute_workflow` not yet attempted (next step)
- ⏳ Bazaar listing path not yet figured out
- ⏳ Calling the listed workflow from another org via `/api/mcp/workflows/<slug>/call` blocked on listing

## Next actions

1. Run `execute_workflow` with placeholder inputs to see what happens when the swap step lacks Base funds (graceful failure expected)
2. Probe `update_workflow` with various publish-adjacent fields (`listedSlug`, `listed`, `priceUsdc`)
3. Read the KeeperHub web UI's "publish" affordance via Playwright if MCP path fails
4. Update FEEDBACK.md section 2.3 with the bazaar listing observation

## Cost

$0.00 — workflow creation is free; no on-chain transaction occurred.
