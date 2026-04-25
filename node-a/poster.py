"""Node A — the poster agent.

Day-1 placeholder. Logs config + exits. Replaced once AXL kill-test
green-lights actual peer dispatch.
"""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    print(json.dumps({
        "role": "node-a (poster)",
        "axl_local_url": f"http://0.0.0.0:{os.environ.get('AXL_NODE_A_PORT', '9001')}",
        "demo_intent": os.environ.get("DEMO_INTENT", "<unset>"),
        "status": "skeleton — waiting for AXL kill-test",
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
