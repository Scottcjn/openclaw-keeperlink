# Uniswap quote kill-test — Day 1 (Apr 25, 2026)

## Result: ✅ PASS

## Surprise

The original plan was to hit Uniswap's REST Trading API at `https://trade-api.gateway.uniswap.org/quote`. Once we discovered KeeperHub has **native Uniswap V3 actions** via MCP `execute_protocol_action`, the dependency on Uniswap's separate REST API disappeared. KeeperHub wraps Uniswap V3 directly, including read-only quote endpoints.

This means our integration depth on the Uniswap track is satisfied through KeeperHub's wrapper, and we can additionally call Uniswap's REST API on the side for double-coverage if it helps the Uniswap-track narrative.

## Test

```bash
python3 /tmp/mcp_call.py execute_protocol_action '{
  "actionType": "uniswap/quote-exact-input",
  "params": {
    "network": "8453",                    # Base
    "tokenIn":  "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
    "tokenOut": "0x4200000000000000000000000000000000000006",  # WETH on Base
    "amountIn": "5000000",                # 5 USDC (6 decimals)
    "fee": "500",                         # 0.05% fee tier
    "sqrtPriceLimitX96": "0"
  }
}'
```

## Response

```json
{
  "success": true,
  "result": {
    "amountOut": "2163012466384737",
    "sqrtPriceX96After": "3808259116805744780640736",
    "initializedTicksCrossed": "1",
    "gasEstimate": "86295"
  },
  "addressLink": "https://basescan.org/address/0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
}
```

## Confirms

- **Native USDC/WETH pool** on Base (0.05% fee tier) — liquid and routable
- **Output:** 0.002163 WETH for 5 USDC (≈ $5 → 0.002163 ETH ≈ $5 at current ~$2300/ETH)
- **Gas estimate:** 86,295 (cheap on Base, ~$0.001 at typical Base gas prices)
- **Quoter address:** `0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a` (verified Uniswap V3 Quoter on Base)
- **Read-only call** — no wallet integration needed, no funds required

## Strategic implication

The full quote → swap path is now provable via two MCP calls:
1. `execute_protocol_action({actionType: "uniswap/quote-exact-input", ...})` — get expected output
2. `execute_protocol_action({actionType: "uniswap/swap-exact-input", ...})` — execute swap (requires wallet credentials + Base funds)

We can also wrap both steps into a published workflow for bazaar exposure (`keeperlink-swap`, ID `1ao3zjcjngophp36baqht`, created Apr 25).

Day-1 sequencing put this kill-test on Day 1 morning. We're ~24h late but green.

## Cost

$0.00 — read-only call, no Base ETH required.
