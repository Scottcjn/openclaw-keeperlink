# Demo — Judge-Facing Walkthrough

> 30-second story, no UI, terminal-only. The CLI **is** the story.

## What you'll see

Split-screen terminal:

- **Left pane** — Node A logs: job built → x402 paid → AXL call fired
- **Right pane** — Node B logs: received → x402 verified → KeeperHub dispatched → tx hash emitted → 0G persisted
- **Overlay** — live Base tx link on basescan, "settled in X seconds, 0 failures"

## Reproducing locally

```bash
git clone https://github.com/Scottcjn/openclaw-keeperlink.git
cd openclaw-keeperlink
cp .env.example .env
# Fill in real keys: KEEPERHUB_API_KEY, UNISWAP_API_KEY, ZEROG_PRIVATE_KEY

docker compose up
```

Wait ~5 seconds for both nodes to handshake over AXL, then:

```bash
docker exec -it openclaw-node-a python skills/openclaw-keeperlink/keeperlink_client.py post-job \
  --intent "swap 5 USDC for ETH on Base"
```

Expected output (final state):

```json
{
  "status": "success",
  "job_id": "...",
  "tx_hash": "0x...",
  "tx_link": "https://basescan.org/tx/0x...",
  "amount_in": "5.0",
  "amount_out": "...",
  "settled_at_unix": 1714060800,
  "zerog_root_hash": "0x...",
  "verification": {
    "onchain": "ok",
    "zerog_content_address": "ok"
  }
}
```

Both panes will have shown the full handshake. Total time from `post-job` to receipt-printed is typically ~10 seconds, dominated by Base block time.

## Verifying after the run

- Base block explorer: `https://basescan.org/tx/<tx_hash>` (shown in receipt)
- 0G content-addressed download: `python -m skills.openclaw-keeperlink.keeperlink_client verify <root_hash>`
  - Pulls the receipt back from 0G Storage by Merkle root
  - Re-runs onchain verification independently
  - Prints PASS/FAIL on both axes

## What this proves

Five sponsor integrations, one execution path:

1. **OpenClaw** — agent framework + MCP glue
2. **Gensyn AXL** — encrypted P2P transport, no central broker
3. **KeeperHub** — reliable onchain execution with retry / gas-opt / audit
4. **Uniswap** — the actual swap on Base via Trading API
5. **0G Storage** — permanent content-addressed audit receipt
