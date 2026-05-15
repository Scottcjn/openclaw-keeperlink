"""Tests for shared/schemas.py — Pydantic model validation."""

import pytest
from pydantic import ValidationError

from shared.schemas import JobRequest, Receipt, AuditEntry, SCHEMA_VERSION


class TestJobRequest:
    """Tests for the JobRequest model."""

    def test_minimal_valid_job(self):
        """A JobRequest with all required fields should validate."""
        job = JobRequest(
            job_id="job_abc123",
            intent="swap 5 USDC for ETH on Base",
            token_in="USDC",
            token_out="ETH",
            amount_in="5.0",
            poster_address="0x1234567890abcdef1234567890abcdef12345678",
            posted_at=1715400000,
        )
        assert job.job_id == "job_abc123"
        assert job.schema_version == SCHEMA_VERSION
        assert job.chain == "base"  # default

    def test_chain_must_be_literal(self):
        """Only allowed chain values should pass validation."""
        # Valid chains
        for chain in ("ethereum", "base", "arbitrum", "optimism"):
            job = JobRequest(
                job_id="j1",
                intent="test",
                token_in="USDC",
                token_out="ETH",
                amount_in="1",
                poster_address="0x" + "ab" * 20,
                posted_at=0,
                chain=chain,
            )
            assert job.chain == chain

        # Invalid chain
        with pytest.raises(ValidationError):
            JobRequest(
                job_id="j1",
                intent="test",
                token_in="USDC",
                token_out="ETH",
                amount_in="1",
                poster_address="0x" + "ab" * 20,
                posted_at=0,
                chain="solana",
            )

    def test_x402_payment_header_optional(self):
        """x402_payment_header should default to None."""
        job = JobRequest(
            job_id="j1",
            intent="test",
            token_in="USDC",
            token_out="ETH",
            amount_in="1",
            poster_address="0x" + "ab" * 20,
            posted_at=0,
        )
        assert job.x402_payment_header is None

    def test_missing_required_field(self):
        """Omitting a required field should raise ValidationError."""
        with pytest.raises(ValidationError):
            JobRequest(job_id="j1")  # Missing intent, token_in, etc.

    def test_serialization_round_trip(self):
        """A JobRequest should survive JSON round-trip."""
        job = JobRequest(
            job_id="j_round",
            intent="swap",
            token_in="USDC",
            token_out="ETH",
            amount_in="10.0",
            poster_address="0x" + "ab" * 20,
            posted_at=1715400000,
            x402_payment_header="header-value",
        )
        json_str = job.model_dump_json()
        restored = JobRequest.model_validate_json(json_str)
        assert restored.job_id == job.job_id
        assert restored.x402_payment_header == "header-value"


class TestReceipt:
    """Tests for the Receipt model."""

    def test_success_receipt(self):
        """A successful receipt with tx_hash should validate."""
        receipt = Receipt(
            job_id="j1",
            status="success",
            tx_hash="0xabc123",
            tx_link="https://basescan.org/tx/0xabc123",
            chain="base",
            amount_in="5.0",
            amount_out="0.002",
            gas_used_wei=21000,
            settled_at=1715400100,
        )
        assert receipt.status == "success"
        assert receipt.tx_hash == "0xabc123"

    def test_failed_receipt(self):
        """A failed receipt should have error populated."""
        receipt = Receipt(
            job_id="j1",
            status="failed",
            chain="base",
            amount_in="5.0",
            error="Insufficient liquidity",
        )
        assert receipt.status == "failed"
        assert receipt.error == "Insufficient liquidity"
        assert receipt.tx_hash is None

    def test_status_must_be_literal(self):
        """Only allowed status values should pass validation."""
        for status in ("success", "failed", "rejected"):
            receipt = Receipt(
                job_id="j1",
                status=status,
                chain="base",
                amount_in="1",
            )
            assert receipt.status == status

        with pytest.raises(ValidationError):
            Receipt(
                job_id="j1",
                status="pending",  # Not allowed
                chain="base",
                amount_in="1",
            )

    def test_optional_fields_default_none(self):
        """Optional receipt fields should default to None."""
        receipt = Receipt(
            job_id="j1",
            status="success",
            chain="base",
            amount_in="1",
        )
        assert receipt.tx_hash is None
        assert receipt.amount_out is None
        assert receipt.gas_used_wei is None
        assert receipt.settled_at is None
        assert receipt.keeperhub_audit_ref is None
        assert receipt.zerog_root_hash is None
        assert receipt.error is None


class TestAuditEntry:
    """Tests for the AuditEntry model."""

    def test_audit_entry_with_job_and_receipt(self):
        """An AuditEntry combines a JobRequest and Receipt with a signature."""
        job = JobRequest(
            job_id="j_audit",
            intent="test audit",
            token_in="USDC",
            token_out="ETH",
            amount_in="1",
            poster_address="0x" + "ab" * 20,
            posted_at=1715400000,
        )
        receipt = Receipt(
            job_id="j_audit",
            status="success",
            chain="base",
            amount_in="1",
            amount_out="0.0005",
        )
        entry = AuditEntry(
            job=job,
            receipt=receipt,
            node_b_signature="0x" + "ff" * 32,
        )
        assert entry.job.job_id == "j_audit"
        assert entry.receipt.status == "success"
        assert entry.node_b_signature.startswith("0x")

    def test_schema_version_propagated(self):
        """All nested models should share the same schema_version."""
        job = JobRequest(
            job_id="j_ver",
            intent="test",
            token_in="USDC",
            token_out="ETH",
            amount_in="1",
            poster_address="0x" + "ab" * 20,
            posted_at=0,
        )
        receipt = Receipt(
            job_id="j_ver",
            status="success",
            chain="base",
            amount_in="1",
        )
        entry = AuditEntry(job=job, receipt=receipt, node_b_signature="sig")
        assert entry.schema_version == SCHEMA_VERSION
        assert entry.job.schema_version == SCHEMA_VERSION
        assert entry.receipt.schema_version == SCHEMA_VERSION
