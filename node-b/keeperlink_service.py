"""Node B — the worker agent.

Hosts the `keeperlink` MCP service that AXL routes peer calls to. Day-1
placeholder. Replaced once AXL + KeeperHub kill-tests are green.
"""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    print(json.dumps({
        "role": "node-b (worker)",
        "axl_local_url": f"http://0.0.0.0:{os.environ.get('AXL_NODE_B_PORT', '9002')}",
        "mcp_router_url": f"http://0.0.0.0:{os.environ.get('AXL_MCP_ROUTER_PORT', '9003')}",
        "service_name": "keeperlink",
        "status": "skeleton — waiting for AXL + KeeperHub kill-tests",
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
