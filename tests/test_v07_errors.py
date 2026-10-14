"""v0.7 Phase A tests -- unified error model (spec section 9)."""

from __future__ import annotations

import pytest

from workflow_engine.error_model import (
    RECOVERABLE_CODES,
    ErrorCode,
    PlatformError,
    from_exception,
    redact_secrets,
)


class TestErrorCode:
    def test_all_spec_codes_present(self):
        expected = {
            "VALIDATION_ERROR", "INPUT_FORMAT_ERROR", "NODE_EXECUTION_ERROR",
            "DEPENDENCY_MISSING", "MODEL_UNAVAILABLE", "API_AUTH_ERROR",
            "NETWORK_ERROR", "GPU_UNAVAILABLE", "OUT_OF_MEMORY", "TIMEOUT",
            "EXTERNAL_SOFTWARE_ERROR", "STORAGE_SECURITY_ERROR",
            "WORKFLOW_INVALID", "CANCELLED",
        }
        assert {c.value for c in ErrorCode} == expected

    def test_recoverability_default(self):
        assert PlatformError(ErrorCode.TIMEOUT, "slow").recoverable is True
        assert PlatformError(ErrorCode.STORAGE_SECURITY_ERROR, "no").recoverable is False

    def test_suggested_action_filled(self):
        err = PlatformError(ErrorCode.DEPENDENCY_MISSING, "缺少依赖：rdkit")
        assert "依赖" in err.suggested_action

    def test_to_dict_round_trip(self):
        err = PlatformError(
            ErrorCode.NODE_EXECUTION_ERROR,
            "boom",
            node_id="n1",
            node_type="FooNode",
            run_id="run_1",
        )
        payload = err.to_dict()
        assert payload["code"] == "NODE_EXECUTION_ERROR"
        assert payload["node_id"] == "n1"
        assert payload["run_id"] == "run_1"
        assert isinstance(payload["recoverable"], bool)


class TestRedaction:
    def test_openai_style_key_masked(self):
        text = "request failed for key sk-abcdef1234567890abcdef"
        assert "sk-abcdef1234567890abcdef" not in redact_secrets(text)
        assert "***REDACTED" in redact_secrets(text)

    def test_bearer_masked(self):
        text = "Authorization: Bearer abc123def456ghi789"
        assert "abc123def456ghi789" not in redact_secrets(text)

    def test_platform_error_redacts(self):
        err = PlatformError(ErrorCode.API_AUTH_ERROR, "invalid key sk-abcdefghijklmnop")
        assert "sk-abcdefghijklmnop" not in err.message
        assert "sk-abcdefghijklmnop" not in err.technical


class TestFromException:
    def test_passthrough(self):
        err = PlatformError(ErrorCode.TIMEOUT, "x")
        assert from_exception(err) is err

    def test_generic_wrapped(self):
        wrapped = from_exception(ValueError("bad value"))
        assert wrapped.code == ErrorCode.NODE_EXECUTION_ERROR
        assert "bad value" in wrapped.message

    def test_safepath_mapped(self):
        from storage import SafePathError

        wrapped = from_exception(SafePathError("escape"))
        assert wrapped.code == ErrorCode.STORAGE_SECURITY_ERROR
