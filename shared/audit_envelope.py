"""OpenClaw Audit Envelope — the 0G framework-track primitive.

A standardized, signed, content-addressed proof structure that any OpenClaw
agent mesh can produce and verify. 0G Storage is the persistence backend;
the schema is the framework-level contribution.

## Why this is a primitive, not a one-off receipt

- **Reusable** — any agent that hires another agent can produce + verify these
  envelopes. Not specific to swaps, Uniswap, or KeeperHub.
- **Verifiable independent of execution path** — the 0G Merkle root proves the
  envelope existed at a specific timestamp without trusting any single chain.
- **Composable** — envelopes can reference each other via `result_payload_hash`,
  making multi-step agent compositions auditable as DAGs.
- **0G-native** — schema is content-addressable; bytes are stable across
  serialization round-trips (canonical JSON).

## Lifecycle

1. **Worker (Node B)** completes a hired job
2. Builds an envelope with all execution metadata
3. Signs the canonical-JSON-of-envelope-minus-signature with its identity key
4. Uploads the signed envelope bytes to 0G Storage → receives Merkle root
5. Returns `(root_hash, envelope)` to the poster (Node A)
6. **Poster (Node A)** can verify by:
   - Downloading bytes from 0G by `root_hash` and comparing to the received envelope
   - Recovering the signer address from the signature and checking it matches
     `envelope.signer_address`
   - Independently checking `envelope.onchain_tx_hash` on the target chain

## Signature scheme

EIP-191 `personal_sign` over the canonical JSON of the envelope with the
`signature` field set to `""`. This makes envelopes signable by any standard
Ethereum wallet (MetaMask, Turnkey, KeeperHub-managed) without bespoke crypto.

## Canonical JSON

Pydantic v2's `model_dump_json` is *not* canonical (key order varies, whitespace
varies). This module ships `canonical_json()` which sorts keys and uses tight
separators to produce stable bytes for hashing and signing.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from .schemas import JobRequest, SCHEMA_VERSION as JOB_SCHEMA_VERSION


ENVELOPE_SCHEMA_VERSION = 1


# ───────────────────────── x402 sub-model ─────────────────────────


class X402PaymentProof(BaseModel):
    """The verified x402 payment that authorized this hire.

    Carries enough information for an independent verifier to re-check the
    payment without trusting Node B. We embed both the payment header and
    the verification result.
    """

    schema_version: int = 1
    paid: bool = Field(description="True if Node B verified the payment before executing")
    network: str = Field(description="x402 network spec, e.g. 'eip155:8453'")
    asset_address: str = Field(description="Token contract address (e.g. USDC on Base)")
    amount_atomic: str = Field(description="Amount in token's atomic units (string for arbitrary precision)")
    pay_to: str = Field(description="Recipient address (Node B's settlement address)")
    payer: str | None = Field(default=None, description="Node A's address derived from x402 signature")
    payment_header: str | None = Field(default=None, description="The x402 payment header value")
    verification_tx_hash: str | None = Field(
        default=None,
        description="Optional onchain proof if the payment was settled via a USDC transfer rather than escrow",
    )


# ───────────────────────── KeeperHub execution metadata ─────────────────────────


class KeeperHubExecution(BaseModel):
    """Metadata about the KeeperHub workflow execution that fulfilled the job."""

    schema_version: int = 1
    workflow_slug: str = Field(description="Bazaar slug, e.g. 'keeperlink-swap'")
    workflow_id: str = Field(description="KeeperHub-internal workflow ID")
    workflow_version_hash: str | None = Field(
        default=None,
        description="blake2b256 of the workflow definition JSON at invocation time. Pins the exact behavior the caller hired.",
    )
    execution_id: str = Field(description="KeeperHub-assigned execution ID")
    execution_logs_url: str | None = Field(
        default=None,
        description="Pointer to KeeperHub's execution logs (for forensic replay)",
    )


# ───────────────────────── Onchain settlement ─────────────────────────


class OnchainSettlement(BaseModel):
    """The actual on-chain transaction that fulfilled the job."""

    schema_version: int = 1
    chain_id: int = Field(description="EIP-155 chain ID, e.g. 8453 for Base")
    tx_hash: str = Field(description="0x-prefixed 32-byte tx hash")
    tx_link: str | None = Field(default=None, description="Explorer URL convenience field")
    block_number: int | None = None
    settled_at_unix: int | None = None
    gas_used_wei: int | None = None
    amount_in: str | None = Field(default=None, description="Input amount in atomic units")
    amount_out: str | None = Field(default=None, description="Output amount in atomic units")
    token_in: str | None = None
    token_out: str | None = None


# ───────────────────────── The envelope itself ─────────────────────────


class OpenClawAuditEnvelope(BaseModel):
    """The OpenClaw Audit Envelope — Schema v1.

    Field ordering is intentional: identity → context → execution → settlement →
    integrity. Canonical JSON sorts keys alphabetically for stability, but the
    model class declaration order matters for human readers.
    """

    schema_version: int = ENVELOPE_SCHEMA_VERSION
    envelope_kind: Literal["openclaw.audit.v1"] = "openclaw.audit.v1"

    # The hire context (what was asked)
    job: JobRequest

    # The execution path (what was done)
    keeperhub: KeeperHubExecution
    x402_proof: X402PaymentProof
    onchain: OnchainSettlement

    # Result integrity
    result_payload: dict[str, Any] = Field(description="The result returned to Node A — small, serializable")
    result_payload_hash: str = Field(description="sha256 hex of canonical_json(result_payload), no 0x prefix")

    # Identity + integrity of the envelope itself
    signer_address: str = Field(description="Node B's identity address (EVM checksum)")
    signature: str = Field(default="", description="EIP-191 personal_sign over canonical_json(envelope_unsigned). Empty during signing.")
    timestamp_unix: int = Field(default_factory=lambda: int(time.time()))

    # ─── Class methods for build / sign / verify ───

    @classmethod
    def build_unsigned(
        cls,
        *,
        job: JobRequest,
        keeperhub: KeeperHubExecution,
        x402_proof: X402PaymentProof,
        onchain: OnchainSettlement,
        result_payload: dict[str, Any],
        signer_address: str,
    ) -> "OpenClawAuditEnvelope":
        """Build a complete envelope ready for signing.

        result_payload_hash is computed from result_payload here. The signature
        field stays empty until `sign()` is called.
        """
        payload_hash = sha256_canonical(result_payload)
        return cls(
            job=job,
            keeperhub=keeperhub,
            x402_proof=x402_proof,
            onchain=onchain,
            result_payload=result_payload,
            result_payload_hash=payload_hash,
            signer_address=signer_address,
            signature="",
        )

    def signing_bytes(self) -> bytes:
        """Canonical JSON bytes the envelope's signature commits to.

        Excludes the `signature` field itself (otherwise we'd have a chicken/egg).
        """
        return canonical_json_bytes(self.model_dump(exclude={"signature"}))

    def with_signature(self, sig_hex: str) -> "OpenClawAuditEnvelope":
        """Return a copy of this envelope with `signature` populated."""
        return self.model_copy(update={"signature": sig_hex})

    def envelope_hash(self) -> str:
        """Stable hash of the *unsigned* envelope (for pairing with 0G uploads)."""
        return hashlib.sha256(self.signing_bytes()).hexdigest()


# ───────────────────────── canonical JSON helpers ─────────────────────────


def canonical_json_bytes(obj: Any) -> bytes:
    """Stable, deterministic JSON encoding suitable for hashing and signing.

    Rules: sort_keys=True, no whitespace, ensure_ascii=False, default str() for
    Pydantic-serialized values that already round-trip cleanly via model_dump.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def sha256_canonical(obj: Any) -> str:
    """sha256 hex of canonical-JSON-encoded obj. No 0x prefix."""
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()


# ───────────────────────── verification ─────────────────────────


def verify_envelope_integrity(env: OpenClawAuditEnvelope) -> tuple[bool, str]:
    """Cheap structural checks. Does NOT verify the EIP-191 signature
    (that requires eth_account or web3 — done in a separate verifier
    module to keep this file dependency-light).

    Checks:
    - schema_version is current
    - result_payload_hash matches sha256(canonical(result_payload))
    - signature is non-empty
    """
    if env.schema_version != ENVELOPE_SCHEMA_VERSION:
        return False, f"schema_version mismatch: got {env.schema_version}, expected {ENVELOPE_SCHEMA_VERSION}"
    if env.envelope_kind != "openclaw.audit.v1":
        return False, f"envelope_kind mismatch: {env.envelope_kind}"
    if env.job.schema_version != JOB_SCHEMA_VERSION:
        return False, f"job.schema_version mismatch: got {env.job.schema_version}"
    expected_hash = sha256_canonical(env.result_payload)
    if env.result_payload_hash != expected_hash:
        return False, f"result_payload_hash mismatch: stored={env.result_payload_hash}, recomputed={expected_hash}"
    if not env.signature:
        return False, "signature is empty"
    if not env.signer_address:
        return False, "signer_address is empty"
    return True, "structural integrity ok"
