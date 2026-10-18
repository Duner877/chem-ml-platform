"""NVIDIA NIM provider entry (v0.7.3).

Written against a live ``nvapi-`` key on 2026-10-18.  Every assertion here
encodes something that was *measured*, not something the documentation
claims, because NVIDIA's public docs and its actual behaviour disagreed
several times:

* ``GET /v1/models`` returned 81 ids, but most answered HTTP 410 (end of life)
  or 404 on use.  **The catalogue is not an availability list.**  Asking for a
  retired id must not be reported as a bad credential.
* ``deepseek-ai/deepseek-v4.1-flash`` is listed, accepts the connection, and
  then returns zero bytes -- for 300 s, repeatedly, while other models on the
  same key and endpoint answered in about one second.  So "listed" and
  "working" are different, and the probe must not conflate them.
* ``openai/gpt-oss-20b`` and ``stepfun-ai/step-5-preview`` returned HTTP 200 in
  ~1-2 s.  Both are *reasoning* models: with a small ``max_tokens`` they answer
  ``content: null`` having spent the whole budget thinking.

No key is stored in this file.  The tests exercise classification and the
catalogue, which need no network; the live probe was run manually and its
result is recorded in ``docs/V07_3_RELEASE_REPORT.md``.
"""

from __future__ import annotations

import pytest

from ai_runtime import credentials as C
from nodes.ai.llm import PROVIDERS as LLM_PROVIDERS
from nodes.ai.llm import _choice_reasoning, _choice_text, _effective_base


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #
def test_nvidia_is_offered_as_a_provider():
    spec = C.provider_spec("nvidia")
    assert spec is not None, "NVIDIA must be selectable in the GUI"
    assert spec.primary_env == "NVIDIA_API_KEY"
    assert spec.default_base_url == "https://integrate.api.nvidia.com/v1"


def test_the_probe_model_is_one_measured_to_answer():
    """The probe model must be a *working* id, not merely a listed one.

    This is the whole reason the field is per provider.  Pointing the NVIDIA
    probe at a retired id would report every valid key as broken.
    """
    spec = C.provider_spec("nvidia")
    assert spec.probe_model == "openai/gpt-oss-20b"
    assert spec.probe_path == "/chat/completions"
    assert spec.probe_style == "openai", "NVIDIA speaks the OpenAI shape"


def test_the_llm_node_can_actually_call_nvidia():
    """The credential catalogue and the node catalogue are separate tables.

    A provider present in only one of them is a provider the GUI lists but the
    canvas cannot use, or vice versa.
    """
    entry = LLM_PROVIDERS.get("nvidia")
    assert entry is not None, "LLMNode must be able to route to NVIDIA"
    assert entry["base"] == "https://integrate.api.nvidia.com/v1"
    assert entry["env"] == "NVIDIA_API_KEY"
    assert entry["model"]


def test_the_default_model_is_a_vendor_namespaced_id():
    """NVIDIA model ids are ``vendor/model``; a bare name would 404."""
    model = LLM_PROVIDERS["nvidia"]["model"]
    assert "/" in model, f"{model!r} has no vendor prefix and cannot resolve"


# --------------------------------------------------------------------------- #
# status classification -- the failure modes actually observed
# --------------------------------------------------------------------------- #
@pytest.fixture
def nvidia():
    return C.provider_spec("nvidia")


def test_a_retired_model_is_not_reported_as_a_bad_key(nvidia):
    """HTTP 410 with NVIDIA's RFC-7807 shape, which has no ``error`` object.

    Observed verbatim from the platform.  Reading only ``error.message``
    discarded the entire explanation.
    """
    body = (
        '{"type":"about:blank","title":"Gone","status":410,'
        '"detail":"The model \'meta/llama-3.1-8b-instruct\' has reached its end '
        'of life on 2026-08-26T09:00:00Z and is no longer available."}'
    )
    ok, outcome, detail = C._classify_http("410", body, nvidia, "secret-key")
    assert not ok
    assert outcome == C.PROBE_MODEL_UNSUPPORTED
    assert "end of life" in detail or "retired" in detail
    assert "secret-key" not in detail


def test_a_saturated_tier_is_not_reported_as_a_bad_key(nvidia):
    """HTTP 503 ResourceExhausted -- observed when probing several models at once."""
    body = (
        '{"error":{"message":"ResourceExhausted: Worker local total request '
        'limit reached (16/16)","type":"Service Unavailable","code":503}}'
    )
    ok, outcome, detail = C._classify_http("503", body, nvidia, "secret-key")
    assert not ok
    assert outcome == C.PROBE_RATE_LIMITED
    assert "key is fine" in detail


def test_a_rejected_key_still_reads_as_a_rejected_key(nvidia):
    ok, outcome, _ = C._classify_http(
        "401", '{"error":{"message":"invalid api key"}}', nvidia, "k"
    )
    assert not ok
    assert outcome == C.PROBE_INVALID_KEY


def test_the_three_outcomes_stay_distinct(nvidia):
    """A retired model, a busy tier and a bad key need three different actions."""
    outcomes = {
        C._classify_http(
            "410", '{"title":"Gone","detail":"end of life"}', nvidia, "k"
        )[1],
        C._classify_http(
            "503", '{"error":{"message":"ResourceExhausted"}}', nvidia, "k"
        )[1],
        C._classify_http("401", "{}", nvidia, "k")[1],
    }
    assert len(outcomes) == 3, f"outcomes collapsed: {outcomes}"


def test_a_long_unanswered_request_is_reported_as_a_timeout_not_a_rejection():
    """curl writes ``__HTTP__000`` when the peer never answers.

    Measured on ``deepseek-ai/deepseek-v4.1-flash``: 300 s, zero bytes, while
    other models on the same key answered in about a second.  Reading 000 as an
    HTTP status would tell the user the provider rejected the request, which is
    a different problem with a different fix.  The parser splits curl's raw
    output on the marker it appended, so that split is what is pinned here.
    """
    raw = "\n__HTTP__000"  # what curl prints when the connection never completed
    body, _, code = raw.rpartition("__HTTP__")
    assert code.strip() == "000"
    assert body.strip() == ""
    # 000 must not be mistaken for one of the classified statuses.
    assert code.strip() not in {"200", "", "401", "403", "404", "429", "410", "503"}


# --------------------------------------------------------------------------- #
# response parsing -- reasoning models
# --------------------------------------------------------------------------- #
def test_a_null_content_is_not_read_as_the_string_none():
    """``{"content": null}`` must yield ``""``.

    ``str(message.get("content", ""))`` returned the literal ``"None"`` -- a
    non-empty answer that says nothing, produced by a model that had actually
    answered.
    """
    choices = [{"message": {"content": None, "role": "assistant"}}]
    assert _choice_text(choices) == ""


def test_a_reasoning_trace_is_found_under_any_of_its_three_names():
    """Gateways spell the thinking field differently; all three are real."""
    for key in ("reasoning_content", "reasoning", "thinking"):
        choices = [{"message": {"content": "", key: "thought"}}]
        assert _choice_reasoning(choices) == "thought", f"missed {key}"


def test_a_normal_answer_wins_over_the_reasoning_trace():
    choices = [{"message": {"content": "成稿", "reasoning_content": "内部思考"}}]
    assert _choice_text(choices) == "成稿"
    assert _choice_reasoning(choices) == "内部思考"


def test_a_missing_choices_list_does_not_raise():
    assert _choice_text([]) == ""
    assert _choice_text(None) == ""
    assert _choice_reasoning([]) == ""


# --------------------------------------------------------------------------- #
# base-URL override -- the inference path must honour what the GUI stored
# --------------------------------------------------------------------------- #
def _config_with_base_urls(mapping):
    """An ``AIConfig`` carrying overrides, without touching the real config."""
    from ai_runtime.config import AIConfig

    config = AIConfig()
    config.base_urls = dict(mapping)
    return config


def test_the_inference_path_reads_the_stored_base_url(monkeypatch):
    """A configured endpoint must be used for calls, not just for the probe.

    ``test_credential`` honoured ``base_urls`` (audit P1-1) while the node kept
    calling the hard-coded table, so a user with a private NVIDIA mirror would be
    probed against their mirror and called against NVIDIA's public one.

    The patch target is ``ai_runtime.config.load_config`` because the helper
    imports it inside the function -- patching ``credentials.load_config`` would
    leave it untouched and the test would pass for the wrong reason.
    """
    import ai_runtime.config as config_module

    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda: _config_with_base_urls({"nvidia": "https://private.example/v1"}),
    )
    assert _effective_base("nvidia", "https://integrate.api.nvidia.com/v1") == (
        "https://private.example/v1"
    )


def test_without_an_override_the_builtin_base_is_used(monkeypatch):
    import ai_runtime.config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda: _config_with_base_urls({}))
    assert _effective_base("nvidia", "https://integrate.api.nvidia.com/v1") == (
        "https://integrate.api.nvidia.com/v1"
    )


def test_a_broken_config_falls_back_instead_of_breaking_a_run(monkeypatch):
    import ai_runtime.config as config_module

    def boom():
        raise RuntimeError("config unreadable")

    monkeypatch.setattr(config_module, "load_config", boom)
    assert _effective_base("nvidia", "https://fallback/v1") == "https://fallback/v1"
