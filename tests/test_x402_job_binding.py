# SPDX-License-Identifier: MIT
"""A declarative x402 header must only pay for the job it was signed for.

The envelope carries no job fields, so the binding rides in the nonce. Before
the binding was checked, one valid header authorized every later job: the
verifier only looked at payee, asset, network and amount, all of which are
constant for the service.
"""

import sys
import time
from pathlib import Path

import pytest
from eth_account import Account

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "node-b"))

from shared import x402 as shared_x402  # noqa: E402
from shared.schemas import JobRequest  # noqa: E402

keeperlink_service = pytest.importorskip(
    "keeperlink_service",
    reason="node-b service deps (aiohttp/fastapi/uvicorn) not installed",
)

PAYER_KEY = "0x" + "11" * 32
NODE_B_KEY = "0x" + "22" * 32
PAYER = Account.from_key(PAYER_KEY).address
NODE_B = Account.from_key(NODE_B_KEY).address
ASSET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
PRICE = "5000000"
POSTED_AT = 1_715_400_000


def _config(tmp_path: Path) -> "keeperlink_service.ServiceConfig":
    # Each test gets its own nonce ledger file so that replay tracking in one
    # test (or one pytest run) can't bleed into another.
    return keeperlink_service.ServiceConfig(
        node_b_address=NODE_B,
        node_b_private_key=NODE_B_KEY,
        accepted_asset=ASSET,
        price_atomic=PRICE,
        nonce_ledger_path=str(tmp_path / "spent_nonces.db"),
    )


def _job(job_id: str, amount_in: str = "5", token_out: str = "WETH") -> JobRequest:
    return JobRequest(
        job_id=job_id,
        intent=f"swap {amount_in} USDC for {token_out} on Base",
        chain="base",
        token_in="USDC",
        token_out=token_out,
        amount_in=amount_in,
        poster_address=PAYER,
        posted_at=POSTED_AT,
    )


def _header_for(job: JobRequest) -> str:
    """Sign a header the way node-a/poster.py does."""
    return shared_x402.sign_payment(
        payer_priv_key=PAYER_KEY,
        payee_address=NODE_B,
        amount_atomic=PRICE,
        asset_address=ASSET,
        network=keeperlink_service.BASE_NETWORK,
        nonce=shared_x402.job_binding_nonce(job.job_id, keeperlink_service.job_digest(job)),
    )


def test_header_pays_for_its_own_job(tmp_path):
    job = _job("job-0001")
    result = keeperlink_service.verify_x402_payment(_header_for(job), job, _config(tmp_path))
    assert result.valid, result.reason
    assert result.payer.lower() == PAYER.lower()


def test_header_cannot_be_replayed_on_another_job(tmp_path):
    paid = _job("job-0001")
    header = _header_for(paid)

    # Attacker copies the header out of a posted job (or out of the public 0G
    # audit envelope, which embeds it) and hires Node B for a 1000x swap.
    stolen = _job("job-9999", amount_in="5000", token_out="DAI")
    result = keeperlink_service.verify_x402_payment(header, stolen, _config(tmp_path))
    assert not result.valid
    assert "not bound to this job" in result.reason


def test_header_cannot_be_reused_after_the_job_is_edited(tmp_path):
    paid = _job("job-0001")
    header = _header_for(paid)

    # Same job_id, bigger swap: the digest moves, so the binding breaks.
    mutated = paid.model_copy(update={"amount_in": "5000"})
    result = keeperlink_service.verify_x402_payment(header, mutated, _config(tmp_path))
    assert not result.valid
    assert "not bound to this job" in result.reason


def test_header_cannot_be_replayed_on_the_same_job(tmp_path):
    """The header itself is not secret -- it's republished verbatim inside the
    0G audit envelope for the job it paid for. Without a spent-nonce ledger,
    anyone (including the payer) could resubmit the exact same header/job
    pair and trigger another KeeperHub swap for a hire that was already paid
    for exactly once."""
    job = _job("job-0001")
    header = _header_for(job)
    config = _config(tmp_path)

    first = keeperlink_service.verify_x402_payment(header, job, config)
    assert first.valid, first.reason

    replay = keeperlink_service.verify_x402_payment(header, job, config)
    assert not replay.valid
    assert "replay" in replay.reason.lower()


def test_verify_payment_requires_the_binding():
    job = _job("job-0001")
    with pytest.raises(TypeError):
        shared_x402.verify_payment(
            _header_for(job),
            NODE_B,
            PRICE,
            ASSET,
        )


def test_unbound_legacy_nonce_is_rejected(tmp_path):
    job = _job("job-0001")
    legacy = shared_x402.sign_payment(
        payer_priv_key=PAYER_KEY,
        payee_address=NODE_B,
        amount_atomic=PRICE,
        asset_address=ASSET,
        network=keeperlink_service.BASE_NETWORK,
        nonce=f"{job.job_id}:{job.posted_at}",
    )
    result = keeperlink_service.verify_x402_payment(legacy, job, _config(tmp_path))
    assert not result.valid


def test_signed_nonce_survives_a_round_trip_of_the_envelope():
    job = _job("job-0001")
    header = _header_for(job)
    decoded = shared_x402._decode_header(header)
    assert decoded["message"]["nonce"] == shared_x402.job_binding_nonce(
        job.job_id, keeperlink_service.job_digest(job)
    )


def test_time_moves_but_binding_holds(tmp_path):
    """posted_at is part of the digest, so two jobs posted a second apart do not
    share a header even with an identical intent."""
    first = _job("job-0001")
    second = first.model_copy(update={"posted_at": POSTED_AT + 1})
    header = _header_for(first)
    assert not keeperlink_service.verify_x402_payment(header, second, _config(tmp_path)).valid
    assert time.time() > 0  # sanity: no wall-clock dependency in the assertions above
