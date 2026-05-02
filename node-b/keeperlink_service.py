"""Node B KeeperLink worker service.

Runs an HTTP service that registers itself with the local MCP router as the
`keeperlink` capability. It accepts `discover` and `hire` requests over the
AXL-routed service path, verifies the payment header, calls KeeperHub's
published workflow, signs an OpenClaw audit envelope, and uploads the envelope
to 0G with a best-effort background retry path.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from aiohttp import ClientSession, ClientTimeout, web
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response as FastAPIResponse
from pydantic import BaseModel, Field, ValidationError
import uvicorn

from shared import x402 as shared_x402
from shared.audit_envelope import (
    KeeperHubExecution,
    OnchainSettlement,
    OpenClawAuditEnvelope,
    X402PaymentProof,
    canonical_json_bytes,
    sha256_canonical,
)
from shared.keeperhub import DEFAULT_BASE_URL, KeeperHubClient, KeeperHubConfig
from shared.schemas import JobRequest, Receipt
from shared.zerog import ZeroGError, merkle_root as zerog_merkle_root, upload as zerog_upload


BASE_CHAIN_ID = int(os.getenv("BASE_CHAIN_ID", "8453"))
_IS_SEPOLIA = BASE_CHAIN_ID == 84532
BASE_NETWORK = f"eip155:{BASE_CHAIN_ID}"
BASE_RPC_URL = os.getenv(
    "BASE_RPC_URL",
    "https://sepolia.base.org" if _IS_SEPOLIA else "https://mainnet.base.org",
)
BASESCAN_TX_URL = "https://sepolia.basescan.org/tx" if _IS_SEPOLIA else "https://basescan.org/tx"
BASE_USDC_ADDRESS = (
    "0x036CbD53842c5426634e7929541eC2318f3dCF7e" if _IS_SEPOLIA
    else "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
)
BASE_WETH_ADDRESS = "0x4200000000000000000000000000000000000006"
# Uniswap V3 SwapRouter02 — recipient of token approvals before swap_exact_input.
# Sepolia uses a different deployment; override via env when targeting Sepolia.
UNISWAP_V3_ROUTER02 = os.getenv(
    "UNISWAP_V3_ROUTER02",
    "0x94cC0AaC535CCDB3C01d6787D6413C739ae12bc4" if _IS_SEPOLIA
    else "0x2626664c2603336E57B271c5C0b26F421741e481"
)
# Conventional "infinite" approval value — many tokens treat MAX_UINT256 as
# unlimited and skip the per-transfer allowance decrement.
MAX_UINT256 = "115792089237316195423570985008687907853269984665640564039457584007913129639935"
WORKFLOW_SLUG = "keeperlink-swap"
WORKFLOW_ID = "1ao3zjcjngophp36baqht"

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


class ServiceConfig(BaseModel):
    router_url: str = "http://127.0.0.1:9003"
    host: str = "0.0.0.0"
    service_port: int = 9004
    http_port: int = 9201
    node_b_private_key: str | None = None
    keeperhub_api_key: str | None = None
    keeperhub_api_url: str = DEFAULT_BASE_URL
    keeperhub_wallet_address: str = ""
    workflow_slug: str = WORKFLOW_SLUG
    workflow_id: str = WORKFLOW_ID
    price_atomic: str = "10000"
    accepted_asset: str = BASE_USDC_ADDRESS
    base_rpc_url: str = BASE_RPC_URL
    request_timeout_s: float = 30.0
    zerog_retry_attempts: int = 3

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        router_url = os.environ.get("AXL_MCP_ROUTER_URL")
        if not router_url:
            router_port = int(os.environ.get("AXL_MCP_ROUTER_PORT", "9003"))
            router_url = f"http://127.0.0.1:{router_port}"
        return cls(
            router_url=router_url,
            host=os.environ.get("KEEPERLINK_SERVICE_HOST", "0.0.0.0"),
            service_port=int(os.environ.get("KEEPERLINK_SERVICE_PORT", "9004")),
            http_port=int(os.environ.get("NODE_B_HTTP_PORT", "9201")),
            node_b_private_key=os.environ.get("NODE_B_PRIVATE_KEY") or None,
            keeperhub_api_key=os.environ.get("KEEPERHUB_API_KEY") or None,
            keeperhub_api_url=os.environ.get("KEEPERHUB_API_URL", DEFAULT_BASE_URL),
            keeperhub_wallet_address=os.environ.get("KEEPERHUB_WALLET_ADDRESS", ""),
            workflow_slug=os.environ.get("KEEPERLINK_WORKFLOW_SLUG", WORKFLOW_SLUG),
            workflow_id=os.environ.get("KEEPERLINK_WORKFLOW_ID", WORKFLOW_ID),
            price_atomic=os.environ.get("KEEPERLINK_PRICE_ATOMIC", "10000"),
            accepted_asset=os.environ.get("KEEPERLINK_ACCEPTED_ASSET", BASE_USDC_ADDRESS),
            base_rpc_url=os.environ.get("BASE_RPC_URL", BASE_RPC_URL),
            request_timeout_s=float(os.environ.get("KEEPERLINK_TIMEOUT_S", "30")),
            zerog_retry_attempts=int(os.environ.get("KEEPERLINK_ZEROG_RETRY_ATTEMPTS", "3")),
        )

    @property
    def node_b_address(self) -> str:
        if not self.node_b_private_key:
            raise ValueError("NODE_B_PRIVATE_KEY is required")
        return Account.from_key(self.node_b_private_key).address


class PricingInfo(BaseModel):
    scheme: str = "exact"
    network: str = BASE_NETWORK
    asset: str
    amount: str
    payTo: str
    maxTimeoutSeconds: int = 300
    extra: dict[str, Any] = Field(default_factory=lambda: {"name": "USD Coin", "version": "2"})


class DiscoveryPayload(BaseModel):
    status: str = "ok"
    service: str = "keeperlink"
    workflow_slug: str
    workflow_id: str
    pricing: PricingInfo
    node_b_address: str
    chain: str = "base"
    capabilities: list[str] = Field(default_factory=lambda: ["discover", "hire"])


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


class PaymentVerificationResult(BaseModel):
    valid: bool
    reason: str
    payer: str | None = None
    header: str | None = None


class WorkflowDispatchResult(BaseModel):
    ok: bool
    response: dict[str, Any] = Field(default_factory=dict)
    execution_id: str | None = None
    tx_hash: str | None = None
    amount_out: str | None = None
    workflow_version_hash: str | None = None
    error: str | None = None


class OnchainContext(BaseModel):
    tx_link: str
    block_number: int | None = None
    settled_at_unix: int | None = None
    gas_used_wei: int | None = None


class SignedEnvelopeResult(BaseModel):
    envelope: OpenClawAuditEnvelope
    envelope_bytes: bytes
    preview_root_hash: str


def emit(event: str, **fields: Any) -> None:
    payload = {"ts_unix": int(time.time()), "event": event, **fields}
    print(json.dumps(payload, sort_keys=True), flush=True)


def _normalize_hex(value: str) -> str:
    return value if value.startswith("0x") else f"0x{value}"


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


def job_digest(job: JobRequest) -> str:
    return sha256_canonical(job.model_dump(exclude={"x402_payment_header"}))


def pricing_for(config: ServiceConfig) -> PricingInfo:
    return PricingInfo(
        asset=config.accepted_asset,
        amount=config.price_atomic,
        payTo=config.node_b_address,
    )


def discovery_payload(config: ServiceConfig) -> DiscoveryPayload:
    return DiscoveryPayload(
        workflow_slug=config.workflow_slug,
        workflow_id=config.workflow_id,
        pricing=pricing_for(config),
        node_b_address=config.node_b_address,
    )


def _rpc_call(rpc_url: str, method: str, params: list[Any]) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    with httpx.Client(timeout=20.0) as client:
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


def fetch_onchain_context(tx_hash: str, config: ServiceConfig) -> OnchainContext:
    tx_receipt = _rpc_call(config.base_rpc_url, "eth_getTransactionReceipt", [tx_hash])
    block_number = _hex_to_int(tx_receipt.get("blockNumber")) if isinstance(tx_receipt, dict) else None
    settled_at_unix: int | None = None
    if block_number is not None:
        block = _rpc_call(config.base_rpc_url, "eth_getBlockByNumber", [hex(block_number), False])
        if isinstance(block, dict):
            settled_at_unix = _hex_to_int(block.get("timestamp"))
    gas_used = _hex_to_int(tx_receipt.get("gasUsed")) if isinstance(tx_receipt, dict) else None
    return OnchainContext(
        tx_link=f"{BASESCAN_TX_URL}/{tx_hash}",
        block_number=block_number,
        settled_at_unix=settled_at_unix,
        gas_used_wei=gas_used,
    )


def _find_in_structure(obj: Any, keys: set[str]) -> Any | None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys:
                return value
        for value in obj.values():
            found = _find_in_structure(value, keys)
            if found is not None:
                return found
    if isinstance(obj, list):
        for value in obj:
            found = _find_in_structure(value, keys)
            if found is not None:
                return found
    return None


def _find_tx_hash(obj: Any) -> str | None:
    # Match keys containing "tx" OR "transaction" OR "hash" — covers tx_hash,
    # txHash, transactionHash (KeeperHub), and 0x-prefixed bare "hash" fields.
    def _matches(key: str) -> bool:
        k = key.lower()
        return "tx" in k or "transaction" in k or k.endswith("hash")

    if isinstance(obj, dict):
        for key, value in obj.items():
            if _matches(key) and isinstance(value, str) and value.startswith("0x") and len(value) == 66:
                return value
        for value in obj.values():
            found = _find_tx_hash(value)
            if found:
                return found
    if isinstance(obj, list):
        for value in obj:
            found = _find_tx_hash(value)
            if found:
                return found
    return None


def _ensure_token_allowance(
    keeperhub: KeeperHubClient,
    token_address: str,
    spender_address: str,
    owner_address: str,
    needed_atomic: str,
    chain_id: int,
) -> dict:
    # Idempotent guard so a freshly-funded KeeperHub-managed wallet survives
    # its first swap without manual setup. Pattern: cheap view-call to read
    # the current allowance; if short, fire one approve(MAX_UINT256). KH's
    # generic execute_contract_call wraps the read result as
    # {"result": "<atomic-string>"} per probe on 2026-05-02.
    needed_int = int(needed_atomic)
    current_int = 0
    current_str = "unread"
    try:
        view_result = keeperhub.execute_contract_call(
            contract_address=token_address,
            function_name="allowance",
            network=str(chain_id),
            function_args=json.dumps([owner_address, spender_address]),
        )
        if isinstance(view_result, dict):
            current_str = str(view_result.get("result", "0"))
            if current_str.isdigit():
                current_int = int(current_str)
    except Exception as exc:  # noqa: BLE001
        # Allowance read fails -> fall through and approve to be safe;
        # worst case we burn an extra approval, never block the swap.
        emit("token_allowance_read_failed", error=str(exc)[:200])

    if current_int >= needed_int:
        emit("token_allowance_ok",
             token=token_address, spender=spender_address,
             current_atomic=current_str, needed_atomic=needed_atomic)
        return {"approved": False, "previous_allowance": current_str,
                "tx_hash": None, "reason": "sufficient"}

    emit("token_allowance_short_approving",
         token=token_address, spender=spender_address,
         current_atomic=current_str, needed_atomic=needed_atomic)
    approve_result = keeperhub.execute_contract_call(
        contract_address=token_address,
        function_name="approve",
        network=str(chain_id),
        function_args=json.dumps([spender_address, MAX_UINT256]),
    )
    tx = _find_tx_hash(approve_result)
    emit("token_allowance_approved",
         token=token_address, spender=spender_address, tx_hash=tx)
    return {"approved": True, "previous_allowance": current_str,
            "tx_hash": tx, "reason": "approved_max_uint256"}


def _fetch_workflow_version_hash(client: KeeperHubClient, config: ServiceConfig) -> str | None:
    try:
        response = client._client.get("/workflows")
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    workflow_obj: dict[str, Any] | None = None
    queue: list[Any] = [data]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            if (
                current.get("id") == config.workflow_id
                or current.get("name") == config.workflow_slug
                or current.get("slug") == config.workflow_slug
                or current.get("listedSlug") == config.workflow_slug
            ):
                workflow_obj = current
                break
            queue.extend(current.values())
        elif isinstance(current, list):
            queue.extend(current)
    if workflow_obj is None:
        return None
    return hashlib.sha256(canonical_json_bytes(workflow_obj)).hexdigest()


def call_keeperhub_workflow(job: JobRequest, config: ServiceConfig) -> WorkflowDispatchResult:
    """Dispatch the swap to KeeperHub.

    Strategy (revised 2026-05-01 due to deadline):
    - First try invoking the published workflow `keeperlink-swap` (v4 architecture).
    - On 404 (workflow not yet published to org), fall back to KeeperHub's MCP
      `execute_protocol_action` with `uniswap/swap-exact-input`. Same KeeperHub
      execution surface, same Uniswap V3 plugin, but no workflow object required.
      This makes the demo runnable without manually creating the workflow on
      app.keeperhub.com first.
    """
    if not config.keeperhub_api_key:
        return WorkflowDispatchResult(ok=False, error="KEEPERHUB_API_KEY is not set")

    amount_in_atomic = human_to_atomic(job.amount_in, token_decimals(job.token_in))
    workflow_input = {
        "tokenIn": normalize_token(job.token_in),
        "tokenOut": normalize_token(job.token_out),
        "amountIn": amount_in_atomic,
        "chainId": BASE_CHAIN_ID,
        "chain": job.chain,
        "jobId": job.job_id,
        "intent": job.intent,
        "posterAddress": job.poster_address,
    }

    cfg = KeeperHubConfig(api_key=config.keeperhub_api_key, base_url=config.keeperhub_api_url)
    try:
        with KeeperHubClient(cfg) as keeperhub:
            version_hash = _fetch_workflow_version_hash(keeperhub, config)
            # Path A: try the published workflow first
            response = keeperhub._client.post(
                f"/mcp/workflows/{config.workflow_slug}/call",
                json=workflow_input,
            )
            data = response.json()
            if response.status_code == 404:
                # Path B: fall back to execute_protocol_action via the MCP client.
                # The earlier raw POST to /mcp on the REST client hit /api/mcp
                # (the REST base_url) which 404s; the MCP client uses the proper
                # /mcp endpoint with auth, Accept, and redirect handling.
                emit("workflow_not_found_falling_back",
                     slug=config.workflow_slug,
                     fallback="execute_protocol_action:uniswap/swap-exact-input")
                # On-demand allowance: a freshly-funded KeeperHub-managed wallet
                # has zero ERC-20 approvals, so the very first swap reverts with
                # Uniswap's STF (Safe Transfer Failed). One cheap allowance
                # check + at most one approve(MAX_UINT256) per wallet-lifetime
                # makes the demo work the first time it runs against a clean
                # wallet (judges, contributors).
                if config.keeperhub_wallet_address:
                    try:
                        _ensure_token_allowance(
                            keeperhub=keeperhub,
                            token_address=normalize_token(job.token_in),
                            spender_address=UNISWAP_V3_ROUTER02,
                            owner_address=config.keeperhub_wallet_address,
                            needed_atomic=amount_in_atomic,
                            chain_id=BASE_CHAIN_ID,
                        )
                    except Exception as exc:  # noqa: BLE001
                        # Don't bail — the swap may still succeed if a prior
                        # approval is in place. We log and continue.
                        emit("token_allowance_helper_error",
                             error=str(exc)[:200], job_id=job.job_id)
                # KH's uniswap/swap-exact-input mirrors Uniswap V3 exactInputSingle
                # and requires fee, recipient, amountOutMinimum, sqrtPriceLimitX96.
                # The 0.05% (500) tier is the most liquid for USDC/WETH on Base.
                # amountOutMinimum=1 is acceptable on a $1 demo trade — production
                # callers should compute slippage from a `uniswap/quote-exact-input`.
                try:
                    data = keeperhub.execute_protocol_action(
                        "uniswap/swap-exact-input",
                        {
                            "network": str(BASE_CHAIN_ID),
                            "tokenIn": normalize_token(job.token_in),
                            "tokenOut": normalize_token(job.token_out),
                            "amountIn": amount_in_atomic,
                            "fee": 500,
                            "recipient": config.keeperhub_wallet_address,
                            "amountOutMinimum": "1",
                            "sqrtPriceLimitX96": "0",
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    return WorkflowDispatchResult(
                        ok=False,
                        workflow_version_hash=version_hash,
                        error=f"execute_protocol_action failed: {exc}",
                    )
            elif response.status_code >= 400:
                execution_id = str(data.get("executionId") or data.get("execution_id") or "")
                return WorkflowDispatchResult(
                    ok=False,
                    response=data if isinstance(data, dict) else {"raw": data},
                    execution_id=execution_id or None,
                    workflow_version_hash=version_hash,
                    error=f"KeeperHub returned {response.status_code}",
                )
    except Exception as exc:  # noqa: BLE001
        return WorkflowDispatchResult(ok=False, error=str(exc))

    execution_id = str(data.get("executionId") or data.get("execution_id") or "") or None
    tx_hash = _find_tx_hash(data)
    amount_out = _find_in_structure(
        data,
        {"amountOut", "amount_out", "outputAmount", "output_amount"},
    )
    amount_out_str = str(amount_out) if amount_out is not None else None
    if not tx_hash:
        return WorkflowDispatchResult(
            ok=False,
            response=data if isinstance(data, dict) else {"raw": data},
            execution_id=execution_id,
            workflow_version_hash=version_hash,
            error="workflow response did not include a tx hash",
        )
    return WorkflowDispatchResult(
        ok=True,
        response=data if isinstance(data, dict) else {"raw": data},
        execution_id=execution_id,
        tx_hash=tx_hash,
        amount_out=amount_out_str,
        workflow_version_hash=version_hash,
    )


def _shared_verify_x402(
    header: str,
    job: JobRequest,
    config: ServiceConfig,
) -> PaymentVerificationResult | None:
    try:
        verified = shared_x402.verify_payment(
            payment_header=header,
            expected_payee=config.node_b_address,
            min_amount_atomic=config.price_atomic,
            asset_address=config.accepted_asset,
            network=BASE_NETWORK,
        )
    except NotImplementedError:
        return None
    except Exception:
        return None

    if isinstance(verified, dict):
        payer = verified.get("payer")
        valid = bool(verified.get("valid", False))
        reason = str(verified.get("error") or "ok")
        return PaymentVerificationResult(valid=valid, reason=reason, payer=payer, header=header)
    if isinstance(verified, bool):
        return PaymentVerificationResult(valid=verified, reason="shared verifier bool result")
    payer = getattr(verified, "payer_address", None)
    return PaymentVerificationResult(valid=True, reason="shared verifier object result", payer=payer, header=header)


def fallback_verify_x402(
    header: str,
    job: JobRequest,
    config: ServiceConfig,
) -> PaymentVerificationResult:
    prefix = "x402-fallback-v2:"
    if not header.startswith(prefix):
        return PaymentVerificationResult(valid=False, reason="unsupported x402 header format")
    try:
        decoded = json.loads(_b64url_decode(header[len(prefix) :]).decode("utf-8"))
        envelope = FallbackX402Envelope.model_validate(decoded)
    except Exception as exc:  # noqa: BLE001
        return PaymentVerificationResult(valid=False, reason=f"invalid x402 payload: {exc}")

    payload = envelope.payload
    try:
        recovered = Account.recover_message(
            encode_defunct(primitive=canonical_json_bytes(payload.model_dump(mode="json"))),
            signature=envelope.signature,
        )
    except Exception as exc:  # noqa: BLE001
        return PaymentVerificationResult(valid=False, reason=f"signature recovery failed: {exc}")

    if recovered.lower() != payload.payer.lower():
        return PaymentVerificationResult(valid=False, reason="payer mismatch after signature recovery")
    if payload.payTo.lower() != config.node_b_address.lower():
        return PaymentVerificationResult(valid=False, reason="payTo does not match Node B address")
    if payload.amount != config.price_atomic:
        return PaymentVerificationResult(valid=False, reason="x402 amount mismatch")
    if payload.network != BASE_NETWORK:
        return PaymentVerificationResult(valid=False, reason="x402 network mismatch")
    if payload.asset.lower() != config.accepted_asset.lower():
        return PaymentVerificationResult(valid=False, reason="x402 asset mismatch")
    if payload.jobId != job.job_id:
        return PaymentVerificationResult(valid=False, reason="x402 jobId mismatch")
    if payload.jobDigest != job_digest(job):
        return PaymentVerificationResult(valid=False, reason="x402 job digest mismatch")
    return PaymentVerificationResult(valid=True, reason="ok", payer=recovered, header=header)


def verify_x402_payment(
    header: str | None,
    job: JobRequest,
    config: ServiceConfig,
) -> PaymentVerificationResult:
    if not header:
        return PaymentVerificationResult(valid=False, reason="missing x402 payment header")
    shared_result = _shared_verify_x402(header, job, config)
    if shared_result and shared_result.valid:
        return shared_result
    fallback_result = fallback_verify_x402(header, job, config)
    if fallback_result.valid:
        return fallback_result
    if shared_result and not shared_result.valid:
        return shared_result
    return fallback_result


def build_signed_envelope(
    *,
    job: JobRequest,
    receipt: Receipt,
    workflow: WorkflowDispatchResult,
    payment: PaymentVerificationResult,
    onchain: OnchainContext,
    config: ServiceConfig,
) -> SignedEnvelopeResult:
    proof = X402PaymentProof(
        paid=True,
        network=BASE_NETWORK,
        asset_address=config.accepted_asset,
        amount_atomic=config.price_atomic,
        pay_to=config.node_b_address,
        payer=payment.payer,
        payment_header=payment.header,
    )
    keeperhub_meta = KeeperHubExecution(
        workflow_slug=config.workflow_slug,
        workflow_id=config.workflow_id,
        workflow_version_hash=workflow.workflow_version_hash,
        execution_id=workflow.execution_id or f"exec_{uuid.uuid4().hex[:12]}",
        execution_logs_url=None,
    )
    onchain_meta = OnchainSettlement(
        chain_id=BASE_CHAIN_ID,
        tx_hash=receipt.tx_hash or "",
        tx_link=receipt.tx_link,
        block_number=onchain.block_number,
        settled_at_unix=receipt.settled_at,
        gas_used_wei=receipt.gas_used_wei,
        amount_in=human_to_atomic(job.amount_in, token_decimals(job.token_in)),
        amount_out=receipt.amount_out,
        token_in=normalize_token(job.token_in),
        token_out=normalize_token(job.token_out),
    )
    envelope = OpenClawAuditEnvelope.build_unsigned(
        job=job,
        keeperhub=keeperhub_meta,
        x402_proof=proof,
        onchain=onchain_meta,
        result_payload={
            "keeperhub_response": workflow.response,
            "receipt": receipt.model_dump(mode="json"),
        },
        signer_address=config.node_b_address,
    )
    signature = Account.sign_message(
        encode_defunct(primitive=envelope.signing_bytes()),
        config.node_b_private_key or "",
    )
    signed_envelope = envelope.with_signature(_normalize_hex(signature.signature.hex()))
    envelope_bytes = signed_envelope.model_dump_json().encode("utf-8")
    preview_root_hash = zerog_merkle_root(envelope_bytes)
    return SignedEnvelopeResult(
        envelope=signed_envelope,
        envelope_bytes=envelope_bytes,
        preview_root_hash=preview_root_hash,
    )


async def retry_zerog_upload(
    blob: bytes,
    expected_root_hash: str,
    *,
    attempts: int,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            result = await asyncio.to_thread(zerog_upload, blob)
            emit(
                "zerog_retry_success",
                attempt=attempt,
                root_hash=result.root_hash,
                tx_hash=result.tx_hash,
                expected_root_hash=expected_root_hash,
            )
            return
        except Exception as exc:  # noqa: BLE001
            emit(
                "zerog_retry_failed",
                attempt=attempt,
                expected_root_hash=expected_root_hash,
                error=str(exc),
            )
            await asyncio.sleep(min(5 * attempt, 15))


async def upload_envelope(
    signed: SignedEnvelopeResult,
    config: ServiceConfig,
) -> tuple[str, str | None]:
    try:
        result = await asyncio.to_thread(zerog_upload, signed.envelope_bytes)
        return result.root_hash, None
    except ZeroGError as exc:
        asyncio.create_task(
            retry_zerog_upload(
                signed.envelope_bytes,
                signed.preview_root_hash,
                attempts=config.zerog_retry_attempts,
            )
        )
        return signed.preview_root_hash, str(exc)
    except Exception as exc:  # noqa: BLE001
        asyncio.create_task(
            retry_zerog_upload(
                signed.envelope_bytes,
                signed.preview_root_hash,
                attempts=config.zerog_retry_attempts,
            )
        )
        return signed.preview_root_hash, str(exc)


def _b64url_decode(raw: str) -> bytes:
    pad = "=" * ((4 - len(raw) % 4) % 4)
    import base64

    return base64.urlsafe_b64decode(raw + pad)


def _payment_required_response(
    config: ServiceConfig,
    *,
    job_id: str | None,
    reason: str,
) -> web.Response:
    body = {
        "status": "payment_required",
        "error_kind": "x402_invalid",
        "error": reason,
        "job_id": job_id,
        "accepts": [pricing_for(config).model_dump(mode="json")],
    }
    return web.json_response(body, status=402)


async def handle_hire(job: JobRequest, header: str | None, config: ServiceConfig) -> web.Response:
    payment = verify_x402_payment(header or job.x402_payment_header, job, config)
    if not payment.valid:
        emit("x402_invalid", job_id=job.job_id, reason=payment.reason)
        return _payment_required_response(config, job_id=job.job_id, reason=payment.reason)

    emit("hire_received", job_id=job.job_id, poster_address=job.poster_address, payer=payment.payer)
    workflow = call_keeperhub_workflow(job, config)
    if not workflow.ok or not workflow.tx_hash:
        receipt = Receipt(
            job_id=job.job_id,
            status="failed",
            chain=job.chain,
            amount_in=job.amount_in,
            settled_at=int(time.time()),
            keeperhub_audit_ref=workflow.execution_id,
            error=f"keeperhub_failure: {workflow.error or 'unknown'}",
        )
        emit(
            "keeperhub_failure",
            job_id=job.job_id,
            execution_id=workflow.execution_id,
            error=workflow.error,
        )
        return web.json_response(receipt.model_dump(mode="json"))

    try:
        onchain = fetch_onchain_context(workflow.tx_hash, config)
    except Exception as exc:  # noqa: BLE001
        onchain = OnchainContext(tx_link=f"{BASESCAN_TX_URL}/{workflow.tx_hash}")
        emit("base_rpc_enrich_failed", job_id=job.job_id, tx_hash=workflow.tx_hash, error=str(exc))

    receipt = Receipt(
        job_id=job.job_id,
        status="success",
        tx_hash=workflow.tx_hash,
        tx_link=onchain.tx_link,
        chain=job.chain,
        amount_in=job.amount_in,
        amount_out=workflow.amount_out,
        gas_used_wei=onchain.gas_used_wei,
        settled_at=onchain.settled_at_unix or int(time.time()),
        keeperhub_audit_ref=workflow.execution_id,
    )

    try:
        signed = build_signed_envelope(
            job=job,
            receipt=receipt,
            workflow=workflow,
            payment=payment,
            onchain=onchain,
            config=config,
        )
        root_hash, upload_error = await upload_envelope(signed, config)
        receipt = receipt.model_copy(
            update={
                "zerog_root_hash": root_hash,
                "error": "0g_upload_pending" if upload_error else None,
            }
        )
        emit(
            "hire_completed",
            job_id=job.job_id,
            tx_hash=receipt.tx_hash,
            zerog_root_hash=root_hash,
            zerog_upload_error=upload_error,
        )
    except Exception as exc:  # noqa: BLE001
        receipt = receipt.model_copy(update={"error": f"audit_envelope_failed: {exc}"})
        emit("audit_envelope_failed", job_id=job.job_id, error=str(exc))

    return web.json_response(receipt.model_dump(mode="json"))


def _tools_list_response(msg_id: Any) -> web.Response:
    return web.json_response(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": [
                    {
                        "name": "discover",
                        "description": "Advertise KeeperLink pricing and workflow metadata.",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "hire",
                        "description": "Accept a paid job request and execute the KeeperHub workflow.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "job": {"type": "object"},
                                "x402_payment_header": {"type": "string"},
                            },
                            "required": ["job", "x402_payment_header"],
                        },
                    },
                ]
            },
        }
    )


async def process_keeperlink_payload(body: dict[str, Any], config: ServiceConfig) -> web.Response:
    if not isinstance(body, dict):
        return web.json_response({"status": "error", "error": "json body must be an object"}, status=400)
    if body.get("kind") == "discover":
        payload = discovery_payload(config)
        emit("discover", workflow_id=config.workflow_id, pay_to=config.node_b_address)
        return web.json_response(payload.model_dump(mode="json"))

    if body.get("kind") == "hire":
        try:
            job = JobRequest.model_validate(body.get("job", {}))
        except ValidationError as exc:
            return web.json_response({"status": "error", "error": exc.errors()}, status=400)
        header = body.get("x402_payment_header")
        return await handle_hire(job, header, config)

    method = body.get("method")
    msg_id = body.get("id")
    if method == "initialize":
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "keeperlink", "version": "1.0.0"},
                },
            }
        )
    if method == "notifications/initialized":
        return web.Response(status=204)
    if method == "tools/list":
        return _tools_list_response(msg_id)
    if method == "tools/call":
        params = body.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name == "discover":
            payload = discovery_payload(config).model_dump(mode="json")
            return web.json_response({"jsonrpc": "2.0", "id": msg_id, "result": payload})
        if name == "hire":
            try:
                job = JobRequest.model_validate(arguments.get("job", {}))
            except ValidationError as exc:
                return web.json_response(
                    {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32602, "message": str(exc)}}
                )
            response = await handle_hire(job, arguments.get("x402_payment_header"), config)
            if response.status == 200:
                result = json.loads(response.text)
                return web.json_response({"jsonrpc": "2.0", "id": msg_id, "result": result})
            return response
    return web.json_response({"status": "error", "error": "unsupported request"}, status=400)


async def keeperlink_http(request: web.Request) -> web.Response:
    config = request.app["config"]
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"status": "error", "error": f"invalid json: {exc}"}, status=400)
    return await process_keeperlink_payload(body, config)


async def health(request: web.Request) -> web.Response:
    config = request.app["config"]
    return web.json_response(
        {
            "status": "ok",
            "service": "keeperlink",
            "router_url": config.router_url,
            "workflow_id": config.workflow_id,
            "workflow_slug": config.workflow_slug,
        }
    )


async def bootstrap_register(app: web.Application) -> None:
    config: ServiceConfig = app["config"]
    endpoint = f"http://127.0.0.1:{config.service_port}/"
    payload = {"service": "keeperlink", "endpoint": endpoint}
    for attempt in range(1, 11):
        try:
            async with ClientSession(timeout=ClientTimeout(total=5)) as session:
                async with session.post(f"{config.router_url}/register", json=payload) as response:
                    if response.status == 200:
                        emit("registered", router_url=config.router_url, endpoint=endpoint)
                        return
                    text = await response.text()
                    emit(
                        "register_retry",
                        attempt=attempt,
                        router_url=config.router_url,
                        status=response.status,
                        body=text,
                    )
        except Exception as exc:  # noqa: BLE001
            emit("register_retry", attempt=attempt, router_url=config.router_url, error=str(exc))
        await asyncio.sleep(min(attempt, 5))


async def on_startup(app: web.Application) -> None:
    app["register_task"] = asyncio.create_task(bootstrap_register(app))
    emit(
        "service_starting",
        router_url=app["config"].router_url,
        service_port=app["config"].service_port,
        workflow_id=app["config"].workflow_id,
    )


def build_app(config: ServiceConfig) -> web.Application:
    app = web.Application()
    app["config"] = config
    app.router.add_get("/health", health)
    app.router.add_post("/", keeperlink_http)
    app.on_startup.append(on_startup)
    return app


def _aiohttp_to_fastapi_response(response: web.Response) -> FastAPIResponse:
    if response.content_type == "application/json":
        text = response.text or "{}"
        return JSONResponse(content=json.loads(text), status_code=response.status)
    return FastAPIResponse(
        content=response.body or b"",
        status_code=response.status,
        media_type=response.content_type,
    )


def build_http_app(config: ServiceConfig) -> FastAPI:
    app = FastAPI(title="keeperlink-direct-http")

    @app.get("/health")
    async def direct_health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "keeperlink",
            "mode": "direct_http",
            "workflow_id": config.workflow_id,
            "workflow_slug": config.workflow_slug,
        }

    @app.post("/keeperlink")
    async def keeperlink_direct(request: Request) -> FastAPIResponse:
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                content={"status": "error", "error": f"invalid json: {exc}"},
                status_code=400,
            )
        response = await process_keeperlink_payload(body, config)
        return _aiohttp_to_fastapi_response(response)

    return app


def main_http(config: ServiceConfig | None = None) -> int:
    runtime = config or ServiceConfig.from_env()
    emit(
        "service_starting",
        mode="direct_http",
        http_port=runtime.http_port,
        workflow_id=runtime.workflow_id,
    )
    uvicorn.run(
        build_http_app(runtime),
        host=runtime.host,
        port=runtime.http_port,
        log_level="warning",
        access_log=False,
    )
    return 0


def main() -> int:
    try:
        config = ServiceConfig.from_env()
    except Exception as exc:  # noqa: BLE001
        emit("startup_failed", error=str(exc))
        return 0

    missing: list[str] = []
    if not config.node_b_private_key:
        missing.append("NODE_B_PRIVATE_KEY")
    if not config.keeperhub_api_key:
        missing.append("KEEPERHUB_API_KEY")
    if missing:
        emit("startup_failed", error=f"missing required env vars: {', '.join(missing)}")
        return 0

    if os.environ.get("KEEPERLINK_DIRECT_HTTP_URL"):
        # The Apr 25 AXL kill-test proved the daemon path, but the direct HTTP
        # fallback is faster to stand up for the time-boxed demo recording.
        return main_http(config)

    app = build_app(config)
    web.run_app(app, host=config.host, port=config.service_port, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
