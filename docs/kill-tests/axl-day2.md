# AXL kill-test — Day 2 (Apr 25, 2026)

## Result: ✅ FULL PASS — both raw transport and cross-node MCP routing green

## Setup

Two AXL daemons + one Python MCP sidecar, all in Docker on a private bridge network. Hub-spoke topology: Node B listens, Node A peers out.

```
┌─────────────────────────────────┐    ┌─────────────────────────────────┐
│ Node A (axl-node:dev)           │    │ Node B (axl-node:dev)           │
│  - Listen: []                   │    │  - Listen: tls://0.0.0.0:9001   │
│  - Peers: [tls://node-b:9001]   │    │  - router_addr:                 │
│  - bridge_addr: 0.0.0.0         │    │    http://node-b-mcp-router     │
│  - api_port: 9002               │◄──►│  - bridge_addr: 0.0.0.0         │
│                                 │    │  - api_port: 9002               │
│  Host:9111 -> :9002             │    │  Host:9112 -> :9002             │
└─────────────────────────────────┘    └─────────────────────────────────┘
                                              │
                                              ▼
                                     ┌─────────────────────────┐
                                     │ node-b-mcp-router       │
                                     │ (python:3.12-slim)      │
                                     │  :9003 — MCP Router     │
                                     │  :9004 — Echo MCP server│
                                     │  Self-registers "echo"  │
                                     └─────────────────────────┘
```

## Public keys (peer IDs)

- **Node A:** `5d912b75fe1f185a3dc7a380ed322e1e802693fd47afb2e331ac5061a2711fe8`
- **Node B:** `2a30713593b6e7a45a571a9a1c891e63ff1620e485c2514b5a3d2ca0eb24a8c8`

## Test 1 — Raw transport (`/send`, `/recv`)

```bash
NODE_B_PEER=2a30...a8c8

# Fire from Node A
curl -X POST -H "X-Destination-Peer-Id: $NODE_B_PEER" \
  --data-binary "kill-test-payload" \
  http://127.0.0.1:9111/send
# → 200 OK, X-Sent-Bytes: 17

# Receive on Node B
curl http://127.0.0.1:9112/recv
# → 200 OK, X-From-Peer-Id: 5d91...1fe8
# → body: "kill-test-payload"
```

Confirms Yggdrasil mesh + raw send/recv works through Docker network.

## Test 2 — Cross-node MCP `tools/list`

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1,"params":{}}' \
  http://127.0.0.1:9111/mcp/$NODE_B_PEER/echo
```

Response (HTTP 200):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [{
      "name": "echo",
      "description": "Echoes the input back unchanged. Kill-test target for AXL routing.",
      "inputSchema": {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"]
      }
    }]
  }
}
```

## Test 3 — Cross-node MCP `tools/call`

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","id":2,"params":{"name":"echo","arguments":{"message":"AXL kill-test from Node A → Node B → echo MCP — green!"}}}' \
  http://127.0.0.1:9111/mcp/$NODE_B_PEER/echo
```

Response:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [{
      "type": "text",
      "text": "echo: AXL kill-test from Node A → Node B → echo MCP — green!"
    }]
  }
}
```

## What this proves

Every leg of the v4 demo loop's transport layer is real:

1. **Two-node AXL topology** — Yggdrasil mesh established, spanning tree built
2. **Cross-node MCP routing** — `/mcp/{peer_id}/{service}` framing propagates a JSON-RPC request through the AXL daemon, Yggdrasil mesh, peer's AXL daemon, peer's MCP router, and into the registered service
3. **Identity propagation** — `X-From-Peer-Id` header reaches the service handler with the caller's ed25519 pubkey, no extra crypto on our side
4. **Service registration** — sidecar self-registers "echo" with the router on startup
5. **JSON-RPC compliance** — both `tools/list` and `tools/call` round-trip cleanly through the entire stack

## Snags discovered (FEEDBACK material)

### Snag 1 — `node-config.json` field naming gotcha

The example config in the README uses PascalCase (`Listen`, `Peers`) for Yggdrasil-inherited fields, but the AXL-specific fields are lowercase-with-underscores (`api_port`, `bridge_addr`, `router_addr`, `router_port`). My initial config used PascalCase for ALL fields and silently fell back to defaults — `bridge_addr` defaulted to `127.0.0.1`, breaking access from outside the container.

**Fix:** lowercase `api_port`, `bridge_addr` in the config.
**Suggestion to Gensyn:** make field naming consistent OR validate-and-warn on unknown fields at startup.

### Snag 2 — `aiohttp` build on python:3.13-alpine

`pip install aiohttp==3.9.5` failed to build a wheel on `python:3.13-alpine` (musl + Cython). Switched to `python:3.12-slim` (Debian-based) and `aiohttp==3.10.11` — clean wheel install. Not an AXL bug, just a Python ecosystem note.

## Tomorrow's plan

Swap the `echo` service for `keeperlink`. The sidecar becomes Node B's
**remote specialist** wrapping the KeeperHub workflow `keeperlink-swap` (id
`1ao3zjcjngophp36baqht`):

```python
async def keeperlink_mcp(request):
    body = await request.json()
    if body.get("method") == "tools/call" and body["params"]["name"] == "swap":
        # 1. Verify x402 payment header
        # 2. Call KeeperHub: execute_workflow(workflowId="1ao3zjcjngophp36baqht", input=...)
        # 3. Build OpenClawAuditEnvelope, sign, upload to 0G
        # 4. Return receipt with tx_hash + 0g_root_hash
        ...
```

Same Docker compose, same routing, same AXL transport. Just swap the handler.

## Cost

$0.00 — all local Docker. AXL is permissionless and has no fees.
