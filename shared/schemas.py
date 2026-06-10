# SPDX-License-Identifier: MIT
"""Wire-format schemas shared between Node A and Node B.

Pydantic v2. Models are append-only — bump a version field rather than
breaking shape.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


SCHEMA_VERSION = 1


class JobRequest(BaseModel):
    """Posted by Node A, consumed by Node B."""

    schema_version: int = SCHEMA_VERSION
    job_id: str
    intent: str = Field(description="Natural-language statement of the job, e.g., 'swap 5 USDC for ETH on Base'")
    chain: Literal["ethereum", "base", "arbitrum", "optimism"] = "base"
    token_in: str = Field(description="Symbol or address of input token")
    token_out: str = Field(description="Symbol or address of output token")
    amount_in: str = Field(description="Amount in human units, decimal string")
    poster_address: str = Field(description="EVM address of Node A (poster)")
    posted_at: int = Field(description="Unix epoch seconds")
    x402_payment_header: str | None = None


class Receipt(BaseModel):
    """Returned by Node B over AXL after KeeperHub settles."""

    schema_version: int = SCHEMA_VERSION
    job_id: str
    status: Literal["success", "failed", "rejected"]
    tx_hash: str | None = None
    tx_link: str | None = None
    chain: str
    amount_in: str
    amount_out: str | None = None
    gas_used_wei: int | None = None
    settled_at: int | None = None
    keeperhub_audit_ref: str | None = None
    zerog_root_hash: str | None = None
    error: str | None = None


class AuditEntry(BaseModel):
    """What gets uploaded to 0G Storage as the permanent audit record."""

    schema_version: int = SCHEMA_VERSION
    job: JobRequest
    receipt: Receipt
    node_b_signature: str = Field(description="Hex signature over (job || receipt) by Node B's identity key")
