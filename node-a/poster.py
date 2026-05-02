"""Node A poster client for the KeeperLink demo loop.

Builds a JobRequest, discovers Node B over AXL, signs an x402-style payment
header, posts the hire, and independently verifies the resulting receipt
against Base RPC + 0G content-addressed storage.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from pydantic import BaseModel, Field, ValidationError

from shared import x402 as shared_x402
from shared.audit_envelope import (
    OpenClawAuditEnvelope,
    canonical_json_bytes,
    sha256_canonical,
    verify_envelope_integrity,
)
from shared.axl_client import AXLClient, AXLConfig
from shared.schemas import JobRequest, Receipt
from shared.zerog import ZeroGError, download as zerog_download, merkle_root as zerog_merkle_root


BASE_CHAIN_ID = 8453
BASE_NETWORK = "eip155:8453"
BASE_RPC_URL = "https://mainnet.base.org"
BASESCAN_TX_URL = "https://basescan.org/tx"
BASE_USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_WETH_ADDRESS = "0x4200000000000000000000000000000000000006"
DEFAULT_RECEIPT_LOG = Path.home() / ".openclaw-keeperlink" / "receipts.jsonl"
DEFAULT_TIMEOUT_S = 15.0

TOKEN_ALIASES: dict[str, str] = {
    "USDC": BASE_USDC_ADDRESS,
    "WETH": BASE_WETH_ADDRESS,
    "ETH": BASE_WETH_ADDRESS,
}
TOKEN_DECIMALS: dict[str, int] = {
    "USDC": 6,
    "ETH": 18,
    "WETH": 18,
    BASE_USDC_ADDRESS.lower(): 6,
    BASE_WETH_ADDRESS.lower(): 18,
}


class PosterConfig(BaseModel):
    """Runtime configuration for Node A."""

    axl_node_a_port: int = 9111
    axl_node_b_peer: str | None = None
    direct_http_url: str | None = None
    keeperhub_api_key: str | None = None
    demo_intent: str | None = None
    demo_token_in: str = "USDC"
    demo_token_out: str = "ETH"
    demo_amount_in: str = "5"
    zerog_private_key: str | None = None
    base_rpc_url: str = BASE_RPC_URL
    receipt_log_path: Path = DEFAULT_RECEIPT_LOG
    request_timeout_s: float = DEFAULT_TIMEOUT_S

    @classmethod
    def from_env(cls, *, intent_override: str | None = None) -> "PosterConfig":
        amount_in = (
            os.environ.get("DEMO_AMOUNT_IN")
            or os.environ.get("DEMO_AMOUNT_IN_USDC")
            or "5"
        )
        return cls(
            axl_node_a_port=int(os.environ.get("AXL_NODE_A_PORT", "9111")),
            axl_node_b_peer=os.environ.get("AXL_NODE_B_PEER") or None,
            direct_http_url=os.environ.get("KEEPERLINK_DIRECT_HTTP_URL") or None,
            keeperhub_api_key=os.environ.get("KEEPERHUB_API_KEY") or None,
            demo_intent=intent_override or os.environ.get("DEMO_INTENT") or None,
            demo_token_in=os.environ.get("DEMO_TOKEN_IN", "USDC"),
            demo_token_out=os.environ.get("DEMO_TOKEN_OUT", "ETH"),
            demo_amount_in=amount_in,
            zerog_private_key=os.environ.get("ZEROG_PRIVATE_KEY") or None,
            base_rpc_url=os.environ.get("BASE_RPC_URL", BASE_RPC_URL),
            receipt_log_path=Path(
                os.environ.get("KEEPERLINK_RECEIPT_LOG", str(DEFAULT_RECEIPT_LOG))
            ).expanduser(),
            request_timeout_s=float(os.environ.get("KEEPERLINK_TIMEOUT_S", str(DEFAULT_TIMEOUT_S))),
        )

    def missing_post_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.direct_http_url and not self.axl_node_b_peer:
            missing.append("AXL_NODE_B_PEER")
        if not self.demo_intent:
            missing.append("DEMO_INTENT")
        if not self.zerog_private_key:
            missing.append("ZEROG_PRIVATE_KEY")
        return missing


class PricingInfo(BaseModel):
    scheme: str = "exact"
    network: str
    asset: str
    amount: str
    payTo: str
    maxTimeoutSeconds: int = 300
    extra: dict[str, Any] = Field(default_factory=dict)


class DiscoveryResponse(BaseModel):
    status: str
    service: str
    workflow_slug: str
    workflow_id: str
    pricing: PricingInfo
    node_b_address: str
    chain: str = "base"
    capabilities: list[str] = Field(default_factory=list)


class DiscoveryAttempt(BaseModel):
    ok: bool
    axl_url: str | None = None
    discovery: DiscoveryResponse | None = None
    error: str | None = None


class FallbackX402Payload(BaseModel):
    x402_version: int = 2
    scheme: str = "exact"
    network: str
    asset: str
    amount: str
    payTo: str
    payer: str
    nonce: str
    issuedAt: int
    jobId: str
    jobDigest: str
    authorityHint: str | None = None


class FallbackX402Envelope(BaseModel):
    payload: FallbackX402Payload
    signature: str


class OnchainVerification(BaseModel):
    ok: bool
    tx_found: bool
    receipt_found: bool
    success: bool | None = None
    swap_like: bool = False
    tx_hash: str | None = None
    tx_link: str | None = None
    basescan_http_ok: bool | None = None
    block_number: int | None = None
    matched_token_addresses: list[str] = Field(default_factory=list)
    error: str | None = None


class ZerogVerification(BaseModel):
    ok: bool
    root_resolves: bool
    root_matches_blob: bool
    envelope_integrity_ok: bool
    signature_ok: bool | None = None
    job_matches: bool | None = None
    onchain_tx_matches: bool | None = None
    envelope_hash: str | None = None
    signer_address: str | None = None
    error: str | None = None


class DualVerification(BaseModel):
    onchain: OnchainVerification
    zerog: ZerogVerification


class PosterRunResult(BaseModel):
    ok: bool
    status: str
    error_kind: str | None = None
    error: str | None = None
    job: JobRequest | None = None
    receipt: Receipt | None = None
    verification: DualVerification | None = None
    axl_url: str | None = None
    peer_id: str | None = None
    discovery: DiscoveryResponse | None = None
    audit_envelope_hash: str | None = None


class ReceiptLogEntry(BaseModel):
    recorded_at_unix: int
    result: PosterRunResult


class VerifyEnvelopeResult(BaseModel):
    verification: ZerogVerification
    envelope: OpenClawAuditEnvelope | None = None


def _normalize_hex(value: str) -> str:
    return value if value.startswith("0x") else f"0x{value}"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    pad = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + pad)


def normalize_token(token: str) -> str:
    upper = token.upper()
    return TOKEN_ALIASES.get(upper, token)


def token_decimals(token: str) -> int:
    normalized = normalize_token(token)
    return TOKEN_DECIMALS.get(normalized.lower(), TOKEN_DECIMALS.get(token.upper(), 18))


def human_to_atomic(amount_human: str, decimals: int) -> str:
    try:
        amount = Decimal(amount_human)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal amount: {amount_human!r}") from exc
    atomic = amount * (Decimal(10) ** decimals)
    return str(int(atomic))


def poster_address(config: PosterConfig) -> str:
    if not config.zerog_private_key:
        raise ValueError("ZEROG_PRIVATE_KEY is required for poster identity")
    return Account.from_key(config.zerog_private_key).address


def job_digest(job: JobRequest) -> str:
    return sha256_canonical(job.model_dump(exclude={"x402_payment_header"}))


def build_job_request(config: PosterConfig) -> JobRequest:
    return JobRequest(
        job_id=f"job_{int(time.time())}_{uuid.uuid4().hex[:8]}",
        intent=config.demo_intent or "",
        chain="base",
        token_in=normalize_token(config.demo_token_in),
        token_out=normalize_token(config.demo_token_out),
        amount_in=config.demo_amount_in,
        poster_address=poster_address(config),
        posted_at=int(time.time()),
    )


def candidate_axl_urls(config: PosterConfig) -> list[str]:
    candidates = [
        os.environ.get("AXL_NODE_A_URL"),
        f"http://127.0.0.1:{config.axl_node_a_port}",
        "http://127.0.0.1:9111",
        "http://127.0.0.1:9002",
        "http://node-a:9002",
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered


def direct_http_endpoint(config: PosterConfig) -> str:
    if not config.direct_http_url:
        raise ValueError("KEEPERLINK_DIRECT_HTTP_URL is not set")
    endpoint = config.direct_http_url.rstrip("/")
    return endpoint if endpoint.endswith("/keeperlink") else f"{endpoint}/keeperlink"


def direct_http_call(
    config: PosterConfig,
    payload: dict[str, Any],
    *,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    # We keep the AXL path for production, but use direct HTTP for the time-boxed
    # demo because the Apr 25 AXL kill-test proved transport and the daemon stack
    # costs more setup time than it saves for recording.
    with httpx.Client(timeout=timeout_s or config.request_timeout_s) as client:
        response = client.post(direct_http_endpoint(config), json=payload)
        response.raise_for_status()
        return response.json()


def discover_peer(config: PosterConfig) -> DiscoveryAttempt:
    if config.direct_http_url:
        try:
            response = direct_http_call(
                config,
                {"kind": "discover", "request_id": f"discover_{uuid.uuid4().hex[:8]}"},
            )
            discovery = DiscoveryResponse.model_validate(response)
            return DiscoveryAttempt(
                ok=True,
                axl_url=direct_http_endpoint(config),
                discovery=discovery,
            )
        except Exception as exc:  # noqa: BLE001 - non-fatal demo path
            return DiscoveryAttempt(ok=False, error=str(exc))
    if not config.axl_node_b_peer:
        return DiscoveryAttempt(ok=False, error="AXL_NODE_B_PEER is not set")
    payload = {"kind": "discover", "request_id": f"discover_{uuid.uuid4().hex[:8]}"}
    last_error: str | None = None
    for base_url in candidate_axl_urls(config):
        try:
            with AXLClient(
                config=AXLConfig(local_axl_url=base_url, timeout_s=config.request_timeout_s)
            ) as axl:
                response = axl.call_peer(
                    peer_id=config.axl_node_b_peer,
                    service="keeperlink",
                    payload=payload,
                )
            discovery = DiscoveryResponse.model_validate(response)
            return DiscoveryAttempt(ok=True, axl_url=base_url, discovery=discovery)
        except Exception as exc:  # noqa: BLE001 - non-fatal demo path
            last_error = f"{base_url}: {exc}"
    return DiscoveryAttempt(ok=False, error=last_error or "no AXL endpoint responded")


def _shared_x402_header(job: JobRequest, pricing: PricingInfo, config: PosterConfig) -> str | None:
    if not config.zerog_private_key:
        return None
    try:
        signed = shared_x402.sign_payment(
            payer_priv_key=config.zerog_private_key,
            payee_address=pricing.payTo,
            amount_atomic=pricing.amount,
            asset_address=pricing.asset,
            network=pricing.network,
            nonce=f"{job.job_id}:{job.posted_at}",
        )
    except NotImplementedError:
        return None
    except Exception:
        return None
    if isinstance(signed, str) and signed:
        return signed
    if isinstance(signed, dict):
        header = signed.get("header") or signed.get("x402_payment_header")
        if isinstance(header, str) and header:
            return header
    return None


def fallback_x402_payment_header(
    job: JobRequest,
    pricing: PricingInfo,
    config: PosterConfig,
) -> str:
    if not config.zerog_private_key:
        raise ValueError("ZEROG_PRIVATE_KEY is required to sign x402 fallback header")
    authority_hint = None
    if config.keeperhub_api_key:
        authority_hint = hashlib.sha256(config.keeperhub_api_key.encode("utf-8")).hexdigest()[:16]
    payload = FallbackX402Payload(
        network=pricing.network,
        asset=pricing.asset,
        amount=pricing.amount,
        payTo=pricing.payTo,
        payer=job.poster_address,
        nonce=uuid.uuid4().hex,
        issuedAt=int(time.time()),
        jobId=job.job_id,
        jobDigest=job_digest(job),
        authorityHint=authority_hint,
    )
    message = encode_defunct(primitive=canonical_json_bytes(payload.model_dump(mode="json")))
    signed = Account.sign_message(message, config.zerog_private_key)
    envelope = FallbackX402Envelope(
        payload=payload,
        signature=_normalize_hex(signed.signature.hex()),
    )
    return f"x402-fallback-v2:{_b64url_encode(canonical_json_bytes(envelope.model_dump(mode='json')))}"


def sign_x402_payment_header(
    job: JobRequest,
    pricing: PricingInfo,
    config: PosterConfig,
) -> str:
    shared_header = _shared_x402_header(job, pricing, config)
    if shared_header:
        return shared_header
    return fallback_x402_payment_header(job, pricing, config)


def _rpc_call(rpc_url: str, method: str, params: list[Any]) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    with httpx.Client(timeout=DEFAULT_TIMEOUT_S) as client:
        response = client.post(rpc_url, json=payload)
        response.raise_for_status()
        data = response.json()
    if data.get("error"):
        raise RuntimeError(f"{method} failed: {data['error']}")
    return data.get("result")


def _hex_to_int(value: str | None) -> int | None:
    if not value:
        return None
    return int(value, 16)


def verify_onchain(job: JobRequest, receipt: Receipt, config: PosterConfig) -> OnchainVerification:
    if not receipt.tx_hash:
        return OnchainVerification(
            ok=False,
            tx_found=False,
            receipt_found=False,
            error="receipt has no tx_hash",
        )
    try:
        tx = _rpc_call(config.base_rpc_url, "eth_getTransactionByHash", [receipt.tx_hash])
        tx_receipt = _rpc_call(config.base_rpc_url, "eth_getTransactionReceipt", [receipt.tx_hash])
        if not tx or not tx_receipt:
            return OnchainVerification(
                ok=False,
                tx_found=bool(tx),
                receipt_found=bool(tx_receipt),
                tx_hash=receipt.tx_hash,
                tx_link=receipt.tx_link or f"{BASESCAN_TX_URL}/{receipt.tx_hash}",
                error="transaction missing from Base RPC",
            )
        log_addresses = {
            str(log.get("address", "")).lower()
            for log in tx_receipt.get("logs", [])
            if isinstance(log, dict)
        }
        expected_tokens = {
            normalize_token(job.token_in).lower(),
            normalize_token(job.token_out).lower(),
        }
        matched = sorted(addr for addr in expected_tokens if addr in log_addresses)
        success = _hex_to_int(tx_receipt.get("status")) == 1
        tx_link = receipt.tx_link or f"{BASESCAN_TX_URL}/{receipt.tx_hash}"
        basescan_http_ok: bool | None = None
        try:
            with httpx.Client(timeout=DEFAULT_TIMEOUT_S, follow_redirects=True) as client:
                head = client.get(tx_link)
            basescan_http_ok = head.status_code == 200
        except Exception:
            basescan_http_ok = None
        return OnchainVerification(
            ok=success and bool(matched),
            tx_found=True,
            receipt_found=True,
            success=success,
            swap_like=bool(matched),
            tx_hash=receipt.tx_hash,
            tx_link=tx_link,
            basescan_http_ok=basescan_http_ok,
            block_number=_hex_to_int(tx_receipt.get("blockNumber")),
            matched_token_addresses=matched,
            error=None if success and matched else "tx exists but token logs did not match expected swap",
        )
    except Exception as exc:  # noqa: BLE001 - demo resilience
        return OnchainVerification(
            ok=False,
            tx_found=False,
            receipt_found=False,
            tx_hash=receipt.tx_hash,
            tx_link=receipt.tx_link or f"{BASESCAN_TX_URL}/{receipt.tx_hash}",
            error=str(exc),
        )


def verify_envelope_root(
    root_hash: str,
    *,
    expected_tx_hash: str | None = None,
    expected_job_id: str | None = None,
) -> VerifyEnvelopeResult:
    try:
        blob = zerog_download(root_hash)
        recomputed_root = zerog_merkle_root(blob)
        envelope = OpenClawAuditEnvelope.model_validate_json(blob.decode("utf-8"))
        integrity_ok, integrity_reason = verify_envelope_integrity(envelope)
        signature_ok: bool | None = None
        signer_address: str | None = envelope.signer_address
        try:
            recovered = Account.recover_message(
                encode_defunct(primitive=envelope.signing_bytes()),
                signature=envelope.signature,
            )
            signature_ok = recovered.lower() == envelope.signer_address.lower()
            signer_address = recovered
        except Exception:
            signature_ok = False
        job_matches = (
            expected_job_id is None or envelope.job.job_id == expected_job_id
        )
        tx_matches = (
            expected_tx_hash is None
            or envelope.onchain.tx_hash.lower() == expected_tx_hash.lower()
        )
        verification = ZerogVerification(
            ok=(
                recomputed_root == root_hash
                and integrity_ok
                and bool(signature_ok)
                and job_matches
                and tx_matches
            ),
            root_resolves=True,
            root_matches_blob=recomputed_root == root_hash,
            envelope_integrity_ok=integrity_ok,
            signature_ok=signature_ok,
            job_matches=job_matches,
            onchain_tx_matches=tx_matches,
            envelope_hash=envelope.envelope_hash(),
            signer_address=signer_address,
            error=None if integrity_ok else integrity_reason,
        )
        return VerifyEnvelopeResult(verification=verification, envelope=envelope)
    except ZeroGError as exc:
        return VerifyEnvelopeResult(
            verification=ZerogVerification(
                ok=False,
                root_resolves=False,
                root_matches_blob=False,
                envelope_integrity_ok=False,
                error=str(exc),
            ),
            envelope=None,
        )
    except Exception as exc:  # noqa: BLE001
        return VerifyEnvelopeResult(
            verification=ZerogVerification(
                ok=False,
                root_resolves=False,
                root_matches_blob=False,
                envelope_integrity_ok=False,
                error=str(exc),
            ),
            envelope=None,
        )


def verify_receipt(job: JobRequest, receipt: Receipt, config: PosterConfig) -> tuple[DualVerification, str | None]:
    onchain = verify_onchain(job, receipt, config)
    audit_envelope_hash: str | None = None
    if receipt.zerog_root_hash:
        zerog_result = verify_envelope_root(
            receipt.zerog_root_hash,
            expected_tx_hash=receipt.tx_hash,
            expected_job_id=receipt.job_id,
        )
        zerog = zerog_result.verification
        audit_envelope_hash = zerog.envelope_hash
    else:
        zerog = ZerogVerification(
            ok=False,
            root_resolves=False,
            root_matches_blob=False,
            envelope_integrity_ok=False,
            error="receipt has no zerog_root_hash",
        )
    return DualVerification(onchain=onchain, zerog=zerog), audit_envelope_hash


def _extract_nested_json(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    if not raw:
        return None
    for candidate in (raw, raw[raw.find("{") :] if "{" in raw else ""):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _structured_error(
    *,
    kind: str,
    message: str,
    job: JobRequest | None = None,
    axl_url: str | None = None,
    peer_id: str | None = None,
    discovery: DiscoveryResponse | None = None,
) -> PosterRunResult:
    return PosterRunResult(
        ok=False,
        status="error",
        error_kind=kind,
        error=message,
        job=job,
        axl_url=axl_url,
        peer_id=peer_id,
        discovery=discovery,
    )


def append_receipt_log(entry: ReceiptLogEntry, log_path: Path | None = None) -> None:
    path = (log_path or DEFAULT_RECEIPT_LOG).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json())
        handle.write("\n")


def load_receipt_log(log_path: Path | None = None, *, limit: int | None = None) -> list[ReceiptLogEntry]:
    path = (log_path or DEFAULT_RECEIPT_LOG).expanduser()
    if not path.exists():
        return []
    entries: list[ReceiptLogEntry] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entries.append(ReceiptLogEntry.model_validate_json(raw))
        except ValidationError:
            continue
    if limit is not None:
        return entries[-limit:]
    return entries


def verify_log_entry(entry: ReceiptLogEntry, config: PosterConfig | None = None) -> PosterRunResult:
    result = entry.result
    if not result.job or not result.receipt:
        return result
    runtime = config or PosterConfig.from_env()
    verification, envelope_hash = verify_receipt(result.job, result.receipt, runtime)
    return result.model_copy(
        update={
            "ok": verification.onchain.ok and verification.zerog.ok,
            "verification": verification,
            "audit_envelope_hash": envelope_hash,
        }
    )


def run_poster_job(*, intent_override: str | None = None) -> PosterRunResult:
    config = PosterConfig.from_env(intent_override=intent_override)
    missing = config.missing_post_fields()
    if missing:
        return _structured_error(
            kind="config_missing",
            message=f"missing required env vars: {', '.join(missing)}",
        )

    try:
        job = build_job_request(config)
    except Exception as exc:  # noqa: BLE001
        return _structured_error(kind="job_build_failed", message=str(exc))

    discovery_attempt = discover_peer(config)
    if not discovery_attempt.ok or not discovery_attempt.discovery or not discovery_attempt.axl_url:
        return _structured_error(
            kind="peer_offline",
            message=discovery_attempt.error or "peer discovery failed",
            job=job,
            peer_id=config.axl_node_b_peer,
        )

    discovery = discovery_attempt.discovery
    try:
        x402_header = sign_x402_payment_header(job, discovery.pricing, config)
    except Exception as exc:  # noqa: BLE001
        return _structured_error(
            kind="payment_sign_failed",
            message=str(exc),
            job=job,
            axl_url=discovery_attempt.axl_url,
            peer_id=config.axl_node_b_peer,
            discovery=discovery,
        )

    signed_job = job.model_copy(update={"x402_payment_header": x402_header})
    hire_payload = {
        "kind": "hire",
        "job": signed_job.model_dump(mode="json"),
        "x402_payment_header": x402_header,
    }

    try:
        if config.direct_http_url:
            raw_response = direct_http_call(
                config,
                hire_payload,
                timeout_s=max(config.request_timeout_s, 30.0),
            )
        else:
            with AXLClient(
                config=AXLConfig(
                    local_axl_url=discovery_attempt.axl_url,
                    timeout_s=max(config.request_timeout_s, 30.0),
                )
            ) as axl:
                raw_response = axl.call_peer(
                    peer_id=config.axl_node_b_peer or "",
                    service="keeperlink",
                    payload=hire_payload,
                )
    except httpx.HTTPStatusError as exc:
        parsed = _extract_nested_json(exc.response.text)
        if parsed and (
            parsed.get("error_kind") == "x402_invalid"
            or parsed.get("status") == "payment_required"
            or "402" in exc.response.text
        ):
            return _structured_error(
                kind="payment_required",
                message=json.dumps(parsed, sort_keys=True),
                job=signed_job,
                axl_url=discovery_attempt.axl_url,
                peer_id=config.axl_node_b_peer,
                discovery=discovery,
            )
        return _structured_error(
            kind="peer_offline",
            message=(
                f"{'direct HTTP' if config.direct_http_url else 'AXL'} call failed: "
                f"{exc.response.status_code} {exc.response.text}"
            ),
            job=signed_job,
            axl_url=discovery_attempt.axl_url,
            peer_id=config.axl_node_b_peer,
            discovery=discovery,
        )
    except Exception as exc:  # noqa: BLE001
        return _structured_error(
            kind="peer_offline",
            message=str(exc),
            job=signed_job,
            axl_url=discovery_attempt.axl_url,
            peer_id=config.axl_node_b_peer,
            discovery=discovery,
        )

    try:
        receipt = Receipt.model_validate(raw_response)
    except ValidationError:
        status = str(raw_response.get("status", "error")) if isinstance(raw_response, dict) else "error"
        error_kind = "payment_required" if status == "payment_required" else "verify_failed"
        return _structured_error(
            kind=error_kind,
            message=json.dumps(raw_response, sort_keys=True),
            job=signed_job,
            axl_url=discovery_attempt.axl_url,
            peer_id=config.axl_node_b_peer,
            discovery=discovery,
        )

    verification, envelope_hash = verify_receipt(signed_job, receipt, config)
    result = PosterRunResult(
        ok=verification.onchain.ok and verification.zerog.ok,
        status=receipt.status,
        error_kind="verify_failed" if not (verification.onchain.ok and verification.zerog.ok) else None,
        error=None if verification.onchain.ok and verification.zerog.ok else "dual verification did not fully pass",
        job=signed_job,
        receipt=receipt,
        verification=verification,
        axl_url=discovery_attempt.axl_url,
        peer_id=config.axl_node_b_peer,
        discovery=discovery,
        audit_envelope_hash=envelope_hash,
    )
    append_receipt_log(ReceiptLogEntry(recorded_at_unix=int(time.time()), result=result), config.receipt_log_path)
    return result


def _print_json(data: BaseModel | dict[str, Any]) -> None:
    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    try:
        result = run_poster_job()
    except Exception as exc:  # noqa: BLE001 - never crash mid-demo
        _print_json(
            {
                "ok": False,
                "status": "error",
                "error_kind": "unexpected_exception",
                "error": str(exc),
            }
        )
        return 0
    _print_json(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
