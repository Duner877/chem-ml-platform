"""LLMNode context rendering must not truncate what it forwards.

Found on 2026-10-18 while building workflow 10 (WeChat marketing copy).

``LLMNode._render_context`` routed every input through
``ScientificObject.summary()``.  For a ``Text`` object that is a 120-character
preview -- by design, because node cards need a preview.  But this is the *data
path*: a planner node writing 742 characters of plan had only its first 120
characters forwarded to the writer node, which then wrote a confident article
about an unrelated product.  No error, no warning, plausible-looking output.

The general lesson this test encodes: a display truncation must never sit on a
data path.  It is cheap to write and invisible in review, because the truncated
value is still a string.
"""

from __future__ import annotations

import pytest

from nodes._helpers import collect
from nodes.ai.llm import LLMNode
from workflow_engine.objects import Text


def _render(value) -> str:
    return LLMNode._render_context(value)


def test_a_long_text_reaches_the_prompt_in_full():
    body = "选题策划。" * 400  # far past the 120-char preview
    rendered = _render(Text(name="plan", text=body))
    assert body in rendered, (
        "the whole upstream text must reach the model; a preview makes the "
        "downstream model invent content to fill what it cannot see"
    )
    assert len(rendered) >= len(body)


def test_the_preview_would_have_been_enough_to_hide_the_loss():
    """Pin the failure mode: a 120-char preview is *valid* text, just wrong.

    Without this, someone could 'simplify' the check into "does it return
    something" and the regression would pass again.
    """
    body = "选题策划。" * 400
    preview = Text(name="plan", text=body).summary()
    assert preview != body
    assert len(preview) < 200
    assert preview in body, "the preview is a prefix, which is why it looks fine"


def test_several_texts_are_concatenated_in_order():
    first = Text(name="a", text="第一步策划内容" * 30)
    second = Text(name="b", text="第二步正文内容" * 30)
    rendered = _render([first, second])
    assert first.text in rendered
    assert second.text in rendered
    assert rendered.index(first.text) < rendered.index(second.text)


def test_non_text_objects_still_use_their_summary():
    """The fix must not change every other type's rendering."""

    class FakeReport:
        pass

    from workflow_engine.objects import Table

    table = Table(name="t", columns=["a"], rows=[[1]])
    rendered = _render(table)
    # A Table has no .text, so it falls through to summary() -- unchanged.
    assert rendered
    assert table.summary() in rendered or rendered == table.summary()


def test_empty_text_contributes_nothing():
    assert _render([Text(name="blank", text="")]).strip() == ""


def test_collect_normalises_a_single_edge_into_a_list():
    """A ``multi`` port with one edge delivers the object, not a list.

    The engine does not wrap it.  If this ever changed, ``_render_context``
    would iterate over the object's attributes instead of over objects.
    """
    text = Text(name="x", text="hello")
    assert collect(text) == [text]
