"""Combined MCP router + minimal 'echo' MCP server for Node B.

Day-2 kill-test scope. The same container runs:
  - MCP Router on :9003 (compatible with AXL daemon's `router_addr`)
  - Echo MCP server on :9004 (registered with the router as service "echo")

Once the kill-test passes, this module becomes the template for `keeperlink`
(Node B's actual remote-specialist service that wraps the keeperlink-swap
KeeperHub workflow).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("router-echo")

ROUTER_PORT = int(os.environ.get("ROUTER_PORT", "9003"))
ECHO_PORT = int(os.environ.get("ECHO_PORT", "9004"))

# Service registry keyed by service name
SERVICES: dict[str, dict[str, Any]] = {}


# ─────────────── MCP Router (lifted from AXL reference) ───────────────


async def router_route(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception as e:
        return web.json_response({"response": None, "error": f"Invalid JSON: {e}"}, status=400)

    service_name = body.get("service", "")
    mcp_request = body.get("request")
    from_peer_id = body.get("from_peer_id", "unknown")

    if not service_name:
        return web.json_response({"response": None, "error": "Missing 'service'"}, status=400)
    if service_name not in SERVICES:
        return web.json_response({"response": None, "error": f"Service not found: {service_name}"}, status=404)

    endpoint = SERVICES[service_name]["endpoint"]
    log.info(f"Routing {service_name} from peer {from_peer_id[:16]}...")
    try:
        async with ClientSession(timeout=ClientTimeout(total=30)) as session:
            async with session.post(
                endpoint,
                json=mcp_request,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "X-From-Peer-Id": from_peer_id,
                    "X-Service": service_name,
                },
            ) as resp:
                if resp.status == 204:
                    return web.json_response({"response": None, "error": None})
                if resp.status != 200:
                    text = await resp.text()
                    return web.json_response(
                        {"response": None, "error": f"Service {service_name} returned {resp.status}: {text}"},
                        status=502,
                    )
                response_data = await resp.json()
                return web.json_response({"response": response_data, "error": None})
    except asyncio.TimeoutError:
        return web.json_response({"response": None, "error": "Service timeout"}, status=504)
    except Exception as e:
        return web.json_response({"response": None, "error": f"Forward error: {e}"}, status=502)


async def router_register(request: web.Request) -> web.Response:
    body = await request.json()
    service = body.get("service", "")
    endpoint = body.get("endpoint", "")
    if not service or not endpoint:
        return web.json_response({"error": "service and endpoint required"}, status=400)
    SERVICES[service] = {
        "endpoint": endpoint,
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    log.info(f"Registered: {service} -> {endpoint}")
    return web.json_response({"status": "registered", "service": service})


async def router_services(request: web.Request) -> web.Response:
    return web.json_response(SERVICES)


async def router_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "services": list(SERVICES.keys())})


def build_router_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/route", router_route)
    app.router.add_post("/register", router_register)
    app.router.add_get("/services", router_services)
    app.router.add_get("/health", router_health)
    return app


# ─────────────── Echo MCP server ───────────────
# Implements minimal MCP-shaped JSON-RPC for the kill-test.
# Real MCP servers handle initialize / tools/list / tools/call. We support
# the bare minimum: tools/list and tools/call({name=echo}) and notifications.


async def echo_mcp(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception as e:
        return web.json_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": f"parse: {e}"}})

    method = body.get("method", "")
    msg_id = body.get("id")
    log.info(f"echo MCP got: method={method!r}")

    if method == "initialize":
        return web.json_response({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "echo", "version": "0.1.0"},
            },
        })

    if method == "notifications/initialized":
        return web.Response(status=204)

    if method == "tools/list":
        return web.json_response({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": [{
                    "name": "echo",
                    "description": "Echoes the input back unchanged. Kill-test target for AXL routing.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                }],
            },
        })

    if method == "tools/call":
        params = body.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {})
        if name == "echo":
            return web.json_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"content": [{"type": "text", "text": f"echo: {args.get('message', '')}"}]},
            })
        return web.json_response({
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"unknown tool: {name}"},
        })

    return web.json_response({
        "jsonrpc": "2.0", "id": msg_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    })


def build_echo_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/", echo_mcp)
    return app


# ─────────────── Bootstrap ───────────────


async def bootstrap_register() -> None:
    """After both servers come up, register echo MCP with the router."""
    await asyncio.sleep(0.5)
    async with ClientSession() as s:
        try:
            async with s.post(
                f"http://127.0.0.1:{ROUTER_PORT}/register",
                json={"service": "echo", "endpoint": f"http://127.0.0.1:{ECHO_PORT}/"},
            ) as r:
                log.info(f"Self-register echo → router status={r.status}")
        except Exception as e:
            log.error(f"Self-register failed: {e}")


async def main() -> None:
    router_app = build_router_app()
    echo_app = build_echo_app()

    router_runner = web.AppRunner(router_app)
    echo_runner = web.AppRunner(echo_app)
    await router_runner.setup()
    await echo_runner.setup()

    router_site = web.TCPSite(router_runner, "0.0.0.0", ROUTER_PORT)
    echo_site = web.TCPSite(echo_runner, "0.0.0.0", ECHO_PORT)
    await router_site.start()
    await echo_site.start()

    log.info(f"MCP Router on :{ROUTER_PORT}, Echo MCP on :{ECHO_PORT}")
    asyncio.create_task(bootstrap_register())

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
