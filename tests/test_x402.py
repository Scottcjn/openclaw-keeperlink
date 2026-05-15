"""Tests for shared/x402.py — Payment header sign and verify helpers."""

import pytest
from shared.x402 import (
    _normalize_hex,
    _parse_atomic_amount,
    _decode_header,
    _encode_header,
    X402Message,
    X402Envelope,
    X402_VERSION,
    DECLARATIVE_KIND,
)


class TestNormalizeHex:
    """Tests for _normalize_hex helper."""

    def test_adds_0x_prefix(self):
        assert _normalize_hex("abc123") == "0xabc123"

    def test_keeps_existing_prefix(self):
        assert _normalize_hex("0xabc123") == "0xabc123"

    def test_empty_string(self):
        assert _normalize_hex("") == "0x"


class TestParseAtomicAmount:
    """Tests for _parse_atomic_amount helper."""

    def test_valid_integer_string(self):
        assert _parse_atomic_amount("1000000") == 1_000_000

    def test_valid_zero(self):
        assert _parse_atomic_amount("0") == 0

    def test_whitespace_stripped(self):
        assert _parse_atomic_amount("  42  ") == 42

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="invalid atomic amount"):
            _parse_atomic_amount("")

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="invalid atomic amount"):
            _parse_atomic_amount("-5")

    def test_decimal_raises(self):
        with pytest.raises(ValueError, match="invalid atomic amount"):
            _parse_atomic_amount("1.5")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError, match="invalid atomic amount"):
            _parse_atomic_amount("abc")


class TestDecodeHeader:
    """Tests for _decode_header helper."""

    def test_valid_base64_json(self):
        import base64, json
        payload = {"x402_version": 1, "kind": "test"}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        result = _decode_header(encoded)
        assert result == payload

    def test_empty_header_raises(self):
        with pytest.raises(ValueError, match="empty"):
            _decode_header("")

    def test_whitespace_header_raises(self):
        with pytest.raises(ValueError, match="empty"):
            _decode_header("   ")

    def test_invalid_base64_raises(self):
        with pytest.raises(ValueError):
            _decode_header("!!!not-base64!!!")

    def test_non_object_json_raises(self):
        import base64, json
        encoded = base64.b64encode(json.dumps([1, 2, 3]).encode()).decode()
        with pytest.raises(ValueError, match="did not decode to an object"):
            _decode_header(encoded)


class TestX402Message:
    """Tests for X402Message model."""

    def test_minimal_valid_message(self):
        msg = X402Message(
            payer="0x" + "ab" * 20,
            payee="0x" + "cd" * 20,
            amount="5000000",
            asset="0x" + "ef" * 20,
            nonce="abc123",
            timestamp=1715400000,
        )
        assert msg.network == "eip155:8453"  # default

    def test_custom_network(self):
        msg = X402Message(
            payer="0x" + "ab" * 20,
            payee="0x" + "cd" * 20,
            amount="1",
            asset="0x" + "ef" * 20,
            nonce="n1",
            timestamp=0,
            network="eip155:1",
        )
        assert msg.network == "eip155:1"

    def test_missing_required_field(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            X402Message(payer="0x1")  # Missing payee, amount, asset, nonce, timestamp


class TestX402Envelope:
    """Tests for X402Envelope model."""

    def test_default_version_and_kind(self):
        msg = X402Message(
            payer="0x" + "ab" * 20,
            payee="0x" + "cd" * 20,
            amount="1",
            asset="0x" + "ef" * 20,
            nonce="n1",
            timestamp=0,
        )
        envelope = X402Envelope(message=msg, signature="0x" + "ff" * 32)
        assert envelope.x402_version == X402_VERSION
        assert envelope.kind == DECLARATIVE_KIND


class TestEncodeDecodeRoundTrip:
    """Tests that encoding and decoding an envelope round-trips correctly."""

    def test_round_trip(self):
        import json
        msg = X402Message(
            payer="0x" + "ab" * 20,
            payee="0x" + "cd" * 20,
            amount="1000000",
            asset="0x" + "ef" * 20,
            nonce="round-trip-nonce",
            timestamp=1715400000,
        )
        envelope = X402Envelope(message=msg, signature="0x" + "ff" * 32)
        encoded = _encode_header(envelope)
        decoded = _decode_header(encoded)
        assert decoded["x402_version"] == X402_VERSION
        assert decoded["kind"] == DECLARATIVE_KIND
        assert decoded["message"]["amount"] == "1000000"
        assert decoded["message"]["nonce"] == "round-trip-nonce"
