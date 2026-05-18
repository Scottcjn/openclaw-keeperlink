"""Smoke tests for the OpenClaw Audit Envelope schema.

Run with: python -m pytest shared/test_audit_envelope.py -v
Or as a script: python shared/test_audit_envelope.py
"""
from __future__ import annotations

import time

from .audit_envelope import (
    ENVELOPE_SCHEMA_VERSION,
    KeeperHubExecution,
    OnchainSettlement,
    OpenClawAuditEnvelope,
    X402PaymentProof,
    canonical_json_bytes,
    sha256_canonical,
    verify_envelope_integrity,
)
from .schemas import JobRequest


def _sample_envelope(signature: str = "0xabcd") -> OpenClawAuditEnvelope:
    job = JobRequest(
        job_id="job_test_001",
        intent="swap 5 USDC for ETH on Base",
        chain="base",
        token_in="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        token_out="0x4200000000000000000000000000000000000006",
        amount_in="5",
        poster_address="0xAaA0000000000000000000000000000000000aaA",
        posted_at=int(time.time()),
        x402_payment_header="x402_v2_demo_header",
    )
    kh = KeeperHubExecution(
        workflow_slug="keeperlink-swap",
        workflow_id="1ao3zjcjngophp36baqht",
        workflow_version_hash="deadbeef" * 8,
        execution_id="exec_test_001",
        execution_logs_url="https://app.keeperhub.com/executions/exec_test_001/logs",
    )
    x402 = X402PaymentProof(
        paid=True,
        network="eip155:8453",
        asset_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        amount_atomic="10000",
        pay_to="0xBbB0000000000000000000000000000000000bBb",
        payer="0xAaA0000000000000000000000000000000000aaA",
        payment_header="x402_v2_demo_header",
    )
    onchain = OnchainSettlement(
        chain_id=8453,
        tx_hash="0x" + "ab" * 32,
        tx_link="https://basescan.org/tx/0x" + "ab" * 32,
        amount_in="5000000",
        amount_out="2163012466384737",
        token_in="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        token_out="0x4200000000000000000000000000000000000006",
    )
    env = OpenClawAuditEnvelope.build_unsigned(
        job=job,
        keeperhub=kh,
        x402_proof=x402,
        onchain=onchain,
        result_payload={
            "amount_out_human": "0.002163",
            "tx_link": onchain.tx_link,
        },
        signer_address="0xBbB0000000000000000000000000000000000bBb",
    )
    return env.with_signature(signature)


def test_canonical_json_is_stable() -> None:
    a = canonical_json_bytes({"b": 1, "a": 2})
    b = canonical_json_bytes({"a": 2, "b": 1})
    assert a == b, "canonical_json must be order-insensitive"
    assert b'"a":2' in a, "should produce tight separators"
    assert b" " not in a, "should produce no whitespace"


def test_sha256_canonical_is_deterministic() -> None:
    h1 = sha256_canonical({"k": [1, 2, 3]})
    h2 = sha256_canonical({"k": [1, 2, 3]})
    assert h1 == h2
    assert len(h1) == 64, "sha256 hex digest is 64 chars"


def test_build_unsigned_computes_payload_hash() -> None:
    env = _sample_envelope(signature="")
    expected = sha256_canonical(env.result_payload)
    assert env.result_payload_hash == expected


def test_signing_bytes_excludes_signature_field() -> None:
    """The whole point: signature commits to the rest of the envelope, not itself."""
    env_a = _sample_envelope(signature="0xaaaa")
    env_b = _sample_envelope(signature="0xbbbb")
    # Different signatures must produce IDENTICAL signing bytes
    assert env_a.signing_bytes() == env_b.signing_bytes()


def test_envelope_hash_is_stable() -> None:
    env_a = _sample_envelope(signature="0x1111")
    env_b = _sample_envelope(signature="0x2222")
    assert env_a.envelope_hash() == env_b.envelope_hash()


def test_verify_integrity_passes_on_well_formed() -> None:
    env = _sample_envelope()
    ok, reason = verify_envelope_integrity(env)
    assert ok, f"expected ok, got {reason!r}"


def test_verify_integrity_catches_tampered_payload() -> None:
    env = _sample_envelope()
    tampered = env.model_copy(update={"result_payload": {"oops": "tampered"}})
    ok, reason = verify_envelope_integrity(tampered)
    assert not ok
    assert "result_payload_hash mismatch" in reason


def test_verify_integrity_catches_empty_signature() -> None:
    env = _sample_envelope(signature="")
    ok, reason = verify_envelope_integrity(env)
    assert not ok
    assert "signature is empty" in reason


def test_round_trip_through_json() -> None:
    """Envelope must survive serialization → deserialization unchanged."""
    env = _sample_envelope()
    raw = env.model_dump_json()
    restored = OpenClawAuditEnvelope.model_validate_json(raw)
    assert restored.envelope_hash() == env.envelope_hash()
    assert restored.signature == env.signature


def test_schema_version_is_locked() -> None:
    assert ENVELOPE_SCHEMA_VERSION == 1, "Bumps must be intentional, append-only"


if __name__ == "__main__":
    # Manual run mode — useful when pytest isn't available
    fns = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    pass_count = 0
    fail_count = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
            pass_count += 1
        except AssertionError as e:
            print(f"  ❌ {fn.__name__}: {e}")
            fail_count += 1
        except Exception as e:
            print(f"  💥 {fn.__name__}: {type(e).__name__}: {e}")
            fail_count += 1
    print(f"\n{pass_count} passed, {fail_count} failed")
    if fail_count:
        raise SystemExit(1)
