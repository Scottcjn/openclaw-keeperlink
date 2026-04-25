"""Skill entrypoint for openclaw-keeperlink.

Day-1 stub. Wires up subcommand dispatch but each integration is replaced
with a stubbed `NotImplementedError` until its kill-test passes in isolation.
We refuse to fake-pass anything — partial green is worse than honest red.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any


@dataclass
class HealthReport:
    axl_node_a_reachable: bool
    axl_node_b_reachable: bool
    keeperhub_auth_ok: bool
    zerog_rpc_ok: bool
    notes: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "axl_node_a_reachable": self.axl_node_a_reachable,
            "axl_node_b_reachable": self.axl_node_b_reachable,
            "keeperhub_auth_ok": self.keeperhub_auth_ok,
            "zerog_rpc_ok": self.zerog_rpc_ok,
            "notes": self.notes,
        }


def cmd_status() -> int:
    """Print health summary for each integration. No state-changing calls."""
    notes: list[str] = []
    notes.append("Day-1 skeleton: integrations not wired yet.")
    notes.append(f"KEEPERHUB_API_KEY set: {bool(os.environ.get('KEEPERHUB_API_KEY'))}")
    notes.append(f"UNISWAP_API_KEY set: {bool(os.environ.get('UNISWAP_API_KEY'))}")
    notes.append(f"ZEROG_PRIVATE_KEY set: {bool(os.environ.get('ZEROG_PRIVATE_KEY'))}")

    report = HealthReport(
        axl_node_a_reachable=False,
        axl_node_b_reachable=False,
        keeperhub_auth_ok=False,
        zerog_rpc_ok=False,
        notes=notes,
    )
    print(json.dumps(report.as_dict(), indent=2))
    return 0


def cmd_post_job(intent: str) -> int:
    raise NotImplementedError(
        "post-job lights up after AXL + KeeperHub kill-tests pass. "
        f"Received intent: {intent!r}"
    )


def cmd_check_receipts() -> int:
    raise NotImplementedError("check-receipts lights up after 0G kill-test passes.")


def cmd_verify(root_hash: str) -> int:
    raise NotImplementedError(
        f"verify lights up after 0G download path is wired. rootHash={root_hash!r}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openclaw-keeperlink")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")

    p_post = sub.add_parser("post-job")
    p_post.add_argument("--intent", required=True)

    sub.add_parser("check-receipts")

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("root_hash")

    args = parser.parse_args(argv)

    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "post-job":
        return cmd_post_job(args.intent)
    if args.cmd == "check-receipts":
        return cmd_check_receipts()
    if args.cmd == "verify":
        return cmd_verify(args.root_hash)
    return 1


if __name__ == "__main__":
    sys.exit(main())
