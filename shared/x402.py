# SPDX-License-Identifier: MIT
"""x402 payment header sign + verify helpers.

Demo note: this module currently implements a declarative x402-style payment
promise for the ETHGlobal demo, not a settled onchain USDC transfer. The
header is a base64-encoded JSON envelope whose message is signed with EIP-191
`personal_sign`. Real x402 settlement on Base would use an EIP-3009
`transferWithAuthorization`-style flow, but that was intentionally deferred in
FEEDBACK.md to protect the deadline.
"""
from __future__ import annotations

import base64
import binascii
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from eth_account import Account  # type: ignore[import-not-found]
from eth_account.messages import encode_defunct  # type: ignore[import-not-found]
from pydantic import BaseModel, ValidationError

from .audit_envelope import canonical_json_bytes


X402_VERSION = 1
DECLARATIVE_KIND = "openclaw.x402.declarative.v1"


@dataclass
class X402Payment:
    payer_address: str
    payee_address: str
    amount: str
    chain: str
    nonce: str
    signature: str


class X402Message(BaseModel):
    payer: str
    payee: str
    amount: str
    asset: str
    network: str = "eip155:8453"
    nonce: str
    timestamp: int


class X402Envelope(BaseModel):
    x402_version: int = X402_VERSION
    kind: str = DECLARATIVE_KIND
    message: X402Message
    signature: str


def _normalize_hex(value: str) -> str:
    return value if value.startswith("0x") else f"0x{value}"


def job_binding_nonce(job_id: str, job_digest: str) -> str:
    """Nonce that binds a payment header to one specific job.

    The declarative envelope has no job fields of its own, so the binding rides
    in the nonce, which the signature already covers. Including the job digest
    (not just the id) means the header stops being valid the moment any part of
    the job changes — amount, tokens, chain.
    """

    return f"{job_id}:{job_digest}"


def _parse_atomic_amount(value: str) -> int:
    parsed = value.strip()
    if not parsed or not parsed.isdigit():
        raise ValueError(f"invalid atomic amount: {value!r}")
    return int(parsed)


def _message_bytes(message: X402Message) -> bytes:
    return canonical_json_bytes(message.model_dump(mode="json"))


def _encode_header(envelope: X402Envelope) -> str:
    raw = canonical_json_bytes(envelope.model_dump(mode="json"))
    return base64.b64encode(raw).decode("utf-8")


def _decode_header(payment_header: str) -> dict[str, Any]:
    raw = payment_header.strip()
    if not raw:
        raise ValueError("payment header is empty")
    padded = raw + ("=" * ((4 - len(raw) % 4) % 4))
    try:
        decoded = base64.b64decode(padded, validate=True)
    except binascii.Error:
        decoded = base64.urlsafe_b64decode(padded)
    parsed = json.loads(decoded.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("payment header did not decode to an object")
    return parsed


def sign_payment(
    payer_priv_key: str,
    payee_address: str,
    amount_atomic: str,
    asset_address: str,
    network: str = "eip155:8453",
    nonce: str | None = None,
) -> str:
    """Build a declarative x402 payment header for the demo transport.

    This signs a canonical JSON message containing payer, payee, amount, asset,
    network, nonce, and timestamp using EIP-191 `personal_sign`, then returns
    the base64-encoded header body suitable for `X-PAYMENT`.
    """

    _parse_atomic_amount(amount_atomic)
    payer = Account.from_key(payer_priv_key).address
    message = X402Message(
        payer=payer,
        payee=payee_address,
        amount=amount_atomic,
        asset=asset_address,
        network=network,
        nonce=nonce or uuid.uuid4().hex,
        timestamp=int(time.time()),
    )
    signed = Account.sign_message(
        encode_defunct(primitive=_message_bytes(message)),
        payer_priv_key,
    )
    envelope = X402Envelope(
        message=message,
        signature=_normalize_hex(signed.signature.hex()),
    )
    return _encode_header(envelope)


def verify_payment(
    payment_header: str,
    expected_payee: str,
    min_amount_atomic: str,
    asset_address: str,
    network: str = "eip155:8453",
    *,
    expected_nonce: str,
) -> dict[str, Any]:
    """Verify a declarative x402 payment header.

    `expected_nonce` is the job binding — build it with `job_binding_nonce()`
    from the job being paid for. Without it a valid header is a bearer token for
    every future job, so it is keyword-only and required: a caller that forgets
    gets a TypeError rather than a silent bypass.

    Returns a structured result and never raises. This verifies only the signed
    promise for demo purposes; it does not prove funds were settled onchain.
    """

    result: dict[str, Any] = {
        "valid": False,
        "payer": None,
        "amount": "",
        "signature": "",
        "message": {},
        "error": None,
    }
    try:
        payload = _decode_header(payment_header)
        envelope = X402Envelope.model_validate(payload)
        result["amount"] = envelope.message.amount
        result["signature"] = envelope.signature
        result["message"] = envelope.message.model_dump(mode="json")
    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
        result["error"] = f"invalid payment header: {exc}"
        return result
    except Exception as exc:  # noqa: BLE001 - verifier must stay non-throwing
        result["error"] = f"unexpected decode failure: {exc}"
        return result

    try:
        recovered = Account.recover_message(
            encode_defunct(primitive=_message_bytes(envelope.message)),
            signature=envelope.signature,
        )
        result["payer"] = recovered
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"signature recovery failed: {exc}"
        return result

    try:
        if envelope.kind != DECLARATIVE_KIND or envelope.x402_version != X402_VERSION:
            result["error"] = "unsupported x402 envelope version"
            return result
        if recovered.lower() != envelope.message.payer.lower():
            result["error"] = "recovered payer does not match signed message"
            return result
        if envelope.message.nonce != expected_nonce:
            result["error"] = "payment header is not bound to this job"
            return result
        if envelope.message.payee.lower() != expected_payee.lower():
            result["error"] = "payee mismatch"
            return result
        if envelope.message.asset.lower() != asset_address.lower():
            result["error"] = "asset mismatch"
            return result
        if envelope.message.network != network:
            result["error"] = "network mismatch"
            return result
        actual_amount = _parse_atomic_amount(envelope.message.amount)
        minimum_amount = _parse_atomic_amount(min_amount_atomic)
        if actual_amount < minimum_amount:
            result["error"] = "amount below minimum"
            return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        return result

    result["valid"] = True
    return result
