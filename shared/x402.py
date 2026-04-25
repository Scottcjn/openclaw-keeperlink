"""x402 payment header sign + verify helpers.

x402 is a thin spec for HTTP-native machine-to-machine payments. Node A
attaches a signed payment header; Node B verifies the signature + checks
funds were actually moved (or escrow), then proceeds.

Day-1 stub — lit up on Day 4 of the build schedule (per ARCHITECTURE.md).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class X402Payment:
    payer_address: str
    payee_address: str
    amount: str
    chain: str
    nonce: str
    signature: str


def sign_payment(*args, **kwargs):
    raise NotImplementedError("x402 sign path comes online on Day 4.")


def verify_payment(*args, **kwargs):
    raise NotImplementedError("x402 verify path comes online on Day 4.")
