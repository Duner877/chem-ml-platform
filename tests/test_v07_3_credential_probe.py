"""The connectivity probe must diagnose, not merely fail (v0.7.3 audit P1-1).

The probe used to send a hard-coded ``gpt-4o-mini`` to ``/chat/completions``
for *every* provider.  Two independent consequences, both of which make the
"test my key" button lie:

* DeepSeek, Moonshot, SiliconFlow, DashScope and Zhipu do not serve
  ``gpt-4o-mini``.  Each answers 400/404 ``model not found`` with a perfectly
  valid key, and the GUI reported that as *your key was rejected* -- sending
  the user off to regenerate a working credential.
* ``set_credential`` has always accepted a ``base_url`` override, but the probe
  read ``spec.default_base_url`` unconditionally.  Anyone pointing the
  platform at a self-hosted vLLM or an OpenAI-compatible gateway was told
  their key was invalid because the probe had asked a different host.

Anthropic's Messages API is not OpenAI-shaped at all, so it could only ever
have failed either.

These tests stand up a real HTTP server on localhost and point the probe at
it, so every branch is exercised over an actual socket rather than a mock of
one.  ``127.0.0.1`` is used because the probe shells out to ``curl`` and a
mock at the Python level would not test the thing that changed.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Tuple

import pytest

from ai_runtime import credentials as cred

SECRET = "sk-test-0123456789abcdefghijKLMNOP"


class _Handler(BaseHTTPRequestHandler):
    """Answers with whatever the test case queued up."""

    status = 200
    payload: Dict[str, Any] = {"choices": [{"message": {"model": "test-model"}}]}
    raw_body: bytes | None = None
    delay = 0.0
    seen: List[Dict[str, Any]] = []

    def _respond(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        type(self).seen.append({
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": json.loads(raw) if raw else None,
        })
        if type(self).delay:
            import time

            time.sleep(type(self).delay)
        body = type(self).raw_body
        if body is None:
            body = json.dumps(type(self).payload).encode("utf-8")
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _respond
    do_POST = _respond

    def log_message(self, *args: Any) -> None:  # keep the test output clean
        return


@pytest.fixture
def server():
    """A local HTTP server whose responses each test controls."""
    _Handler.seen = []
    _Handler.status = 200
    _Handler.payload = {"choices": [{"message": {"model": "test-model"}}]}
    _Handler.raw_body = None
    _Handler.delay = 0.0

    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    try:
        yield f"http://127.0.0.1:{port}", _Handler
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def stored(monkeypatch, tmp_path):
    """A provider with a stored secret and a patched-out keyring."""
    monkeypatch.setattr(cred, "_read_file", lambda: {"openai": {"secret": SECRET}})
    monkeypatch.setattr(cred, "_keyring", lambda: None)
    monkeypatch.setattr(cred, "load_config", lambda: type("C", (), {"base_urls": {}})())
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    yield


class TestProbeTargetsTheRightProvider:
    """Each provider must be asked for a model *it* actually serves."""

    def test_no_cloud_provider_is_probed_with_a_foreign_model_name(self):
        """The regression in one assertion.

        Every cloud provider used to be sent ``gpt-4o-mini``.  Only OpenAI
        serves that name, so eight out of nine were guaranteed to fail.
        """
        models = {p.id: p.probe_model for p in cred.PROVIDERS if p.kind == "cloud"}
        assert "gpt-4o-mini" not in set(models.values()) or list(models).count("openai") == 1
        assert len(set(models.values())) == len(models), (
            f"two providers probe the same model name: {models}"
        )

    @pytest.mark.parametrize(
        "provider,expected",
        [
            ("openai", "gpt-4o-mini"),
            ("deepseek", "deepseek-chat"),
            ("moonshot", "moonshot-v1-8k"),
            ("dashscope", "qwen-turbo"),
            ("zhipu", "glm-4-flash"),
        ],
    )
    def test_known_providers_have_a_native_model(self, provider, expected):
        assert cred.provider_spec(provider).probe_model == expected

    def test_anthropic_uses_its_native_messages_api(self):
        """A non-OpenAI-shaped API cannot be probed with an OpenAI body."""
        spec = cred.provider_spec("anthropic")
        assert spec.probe_style == "anthropic"
        assert spec.probe_path == "/v1/messages"
        assert dict(spec.probe_headers).get("anthropic-version")

    def test_anthropic_authenticates_with_x_api_key_not_bearer(self):
        spec = cred.provider_spec("anthropic")
        headers = cred._probe_headers(spec, SECRET)
        assert headers["x-api-key"] == SECRET
        assert "Authorization" not in headers, (
            "Anthropic rejects a Bearer token; the old probe always sent one"
        )

    def test_openai_style_providers_still_use_a_bearer_token(self):
        headers = cred._probe_headers(cred.provider_spec("openai"), SECRET)
        assert headers["Authorization"] == f"Bearer {SECRET}"
        assert "x-api-key" not in headers

    def test_local_providers_probe_the_address_not_a_key(self):
        """Ollama and vLLM do not authenticate; the question is 'is it up'."""
        for pid, path in (("ollama", "/api/tags"), ("vllm", "/v1/models")):
            spec = cred.provider_spec(pid)
            assert spec.probe_path == path
            assert cred._probe_body(spec) is None, f"{pid} should send no body"
            assert "Authorization" not in cred._probe_headers(spec, "")


class TestProbeReachesTheConfiguredEndpoint:
    """The probe must go where the user told it to go."""

    def test_effective_base_url_prefers_the_override(self, monkeypatch):
        cfg = type("C", (), {"base_urls": {"openai": "http://gw.internal:8080/v1"}})()
        monkeypatch.setattr(cred, "load_config", lambda: cfg)
        assert cred._effective_base_url(cred.provider_spec("openai")) == "http://gw.internal:8080/v1"

    def test_effective_base_url_falls_back_to_the_default(self, monkeypatch):
        cfg = type("C", (), {"base_urls": {}})()
        monkeypatch.setattr(cred, "load_config", lambda: cfg)
        spec = cred.provider_spec("openai")
        assert cred._effective_base_url(spec) == spec.default_base_url

    def test_a_broken_config_does_not_break_the_probe(self, monkeypatch):
        def boom():
            raise RuntimeError("config/ai.json is corrupt")

        monkeypatch.setattr(cred, "load_config", boom)
        spec = cred.provider_spec("openai")
        assert cred._effective_base_url(spec) == spec.default_base_url

    def test_the_probe_reports_which_url_it_used(self, stored, server, monkeypatch):
        base, handler = server
        monkeypatch.setattr(
            cred, "load_config", lambda: type("C", (), {"base_urls": {"openai": base + "/v1"}})()
        )
        result = cred.test_credential("openai")
        assert result["ok"] is True
        assert result["base_url"] == base + "/v1"
        assert base + "/v1" in result["detail"], (
            "a failure on a custom gateway is undebugable unless the probe says where it looked"
        )
        assert handler.seen[0]["path"] == "/v1/chat/completions"


class TestProbeFailureModesAreDistinguishable:
    """The whole point of the ``outcome`` field: different fixes."""

    def _run(self, server, monkeypatch, status, payload=None, raw=None):
        base, handler = server
        handler.status = status
        handler.payload = payload or {"choices": [{"message": {"model": "m"}}]}
        handler.raw_body = raw
        monkeypatch.setattr(
            cred, "load_config", lambda: type("C", (), {"base_urls": {"openai": base + "/v1"}})()
        )
        return cred.test_credential("openai")

    def test_success(self, server, monkeypatch, stored):
        base, handler = server
        handler.payload = {"choices": [{"message": {"model": "served-model"}}]}
        monkeypatch.setattr(
            cred, "load_config", lambda: type("C", (), {"base_urls": {"openai": base + "/v1"}})()
        )
        result = cred.test_credential("openai")
        assert result["ok"] is True
        assert result["outcome"] == cred.PROBE_OK
        # The model the endpoint actually served is worth reporting: it tells
        # the user which of their gateway's deployments answered.
        assert "served-model" in result["detail"]

    def test_401_is_an_invalid_key(self, server, monkeypatch, stored):
        result = self._run(server, monkeypatch, 401, {"error": {"message": "bad key"}})
        assert result["outcome"] == cred.PROBE_INVALID_KEY
        assert result["ok"] is False

    def test_403_is_separated_from_401(self, server, monkeypatch, stored):
        """403 means the key works but lacks permission -- a different fix."""
        result = self._run(server, monkeypatch, 403, {"error": {"message": "no access"}})
        assert result["outcome"] == cred.PROBE_FORBIDDEN
        assert result["outcome"] != cred.PROBE_INVALID_KEY

    def test_404_on_the_path_is_a_bad_endpoint(self, server, monkeypatch, stored):
        result = self._run(server, monkeypatch, 404, {"error": {"message": "not found"}})
        assert result["outcome"] == cred.PROBE_BAD_ENDPOINT

    def test_404_naming_a_model_is_not_an_invalid_key(self, server, monkeypatch, stored):
        """The false negative that started all of this."""
        result = self._run(
            server, monkeypatch, 404,
            {"error": {"message": "The model `gpt-4o-mini` does not exist"}},
        )
        assert result["outcome"] == cred.PROBE_MODEL_UNSUPPORTED
        assert result["ok"] is False

    def test_400_naming_a_model_is_still_not_a_bad_key(self, server, monkeypatch, stored):
        result = self._run(
            server, monkeypatch, 400,
            {"error": {"message": "model `deepseek-chat` not supported by this endpoint"}},
        )
        assert result["outcome"] == cred.PROBE_MODEL_UNSUPPORTED

    def test_429_is_rate_limiting_not_a_bad_key(self, server, monkeypatch, stored):
        result = self._run(server, monkeypatch, 429, {"error": {"message": "quota"}})
        assert result["outcome"] == cred.PROBE_RATE_LIMITED

    def test_non_json_is_reported_as_such(self, server, monkeypatch, stored):
        result = self._run(server, monkeypatch, 200, raw=b"<html>login page</html>")
        assert result["outcome"] == cred.PROBE_BAD_RESPONSE

    def test_an_unreachable_host_is_a_network_problem(self, monkeypatch, stored):
        # Port 1 on loopback refuses connections.
        monkeypatch.setattr(
            cred, "load_config", lambda: type("C", (), {"base_urls": {"openai": "http://127.0.0.1:1/v1"}})()
        )
        result = cred.test_credential("openai")
        assert result["outcome"] == cred.PROBE_NETWORK
        assert result["ok"] is False


class TestProbeNeverLeaksTheSecret:
    """The detail string travels to the browser verbatim."""

    def test_a_provider_echoing_the_key_is_redacted(self, server, monkeypatch, stored):
        base, handler = server
        handler.status = 401
        # A real class of provider mistake: echo the submitted key back.
        handler.payload = {"error": {"message": f"invalid api key {SECRET}"}}
        monkeypatch.setattr(
            cred, "load_config", lambda: type("C", (), {"base_urls": {"openai": base + "/v1"}})()
        )
        result = cred.test_credential("openai")
        assert SECRET not in result["detail"]
        assert SECRET not in json.dumps(result)

    def test_an_unclassified_status_still_redacts(self):
        spec = cred.provider_spec("openai")
        ok, outcome, detail = cred._classify_http(
            "500", json.dumps({"error": {"message": f"oops {SECRET}"}}), spec, SECRET
        )
        assert SECRET not in detail
        assert ok is False


class TestProbeResultsAreMachineReadable:
    def test_every_return_carries_an_outcome(self, monkeypatch):
        monkeypatch.setattr(cred, "_read_file", lambda: {})
        monkeypatch.setattr(cred, "_keyring", lambda: None)
        result = cred.test_credential("openai")
        assert result["outcome"] == cred.PROBE_NO_CREDENTIAL

    def test_outcomes_are_distinct_constants(self):
        outcomes = [
            cred.PROBE_OK, cred.PROBE_NO_CREDENTIAL, cred.PROBE_INVALID_KEY,
            cred.PROBE_FORBIDDEN, cred.PROBE_BAD_ENDPOINT,
            cred.PROBE_MODEL_UNSUPPORTED, cred.PROBE_RATE_LIMITED,
            cred.PROBE_NETWORK, cred.PROBE_TIMEOUT, cred.PROBE_BAD_RESPONSE,
            cred.PROBE_UNSUPPORTED, cred.PROBE_UNAVAILABLE,
        ]
        assert len(outcomes) == len(set(outcomes)), "two outcomes share a value"
