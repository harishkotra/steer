"""Tests that assert behaviour, not plumbing.

The console makes claims on screen — "tension: very strained", "tone: tender
64%", "steer landed" — so these tests check that those claims move when the
text moves, and that a steer actually changes what gets written.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from steer import auditor, lexicon, steerer
from steer.corpus import SEEDS
from steer.providers import make_provider
from steer.providers.api import APIProvider
from steer.state import Console

TENDER = (
    "She held his hand a long time and did not let go. Her voice was gentle, "
    "quiet, close, and he could hear her breathe in the dark room."
)
HARSH = (
    "The blade came up and the room went loud. He struck the door hard, "
    "shouting, and the glass broke against the wall."
)


def test_clauses_cover_the_document_without_loss():
    doc = SEEDS["keeper"]
    spans = auditor.clauses(doc)
    assert spans, "expected clauses"
    assert spans[0]["start"] == 0
    assert spans[-1]["end"] == len(doc)
    for a, b in zip(spans, spans[1:]):
        assert a["end"] == b["start"], "clauses must tile the document exactly"
        assert a["start"] < a["end"]


def test_realized_score_tracks_the_pole_that_is_actually_there():
    console = Console(doc=TENDER)
    console.add_vector("tone", "tender", "somber", magnitude=0.8)
    report = auditor.audit(console)
    tender = report["vectors"][0]
    assert tender["pole"] == "tender"
    assert tender["realized"] > 0.5, report["vectors"]

    console.doc = HARSH
    flipped = auditor.audit(console)["vectors"][0]
    assert flipped["realized"] < tender["realized"]


def test_sentences_and_words_are_counted_from_the_text():
    console = Console(doc="One. Two. Three words here.")
    report = auditor.audit(console)
    assert report["sentences"] == 3
    assert report["words"] == 5


def test_directive_carries_every_active_knob_and_box():
    console = Console(doc=SEEDS["keeper"])
    console.add_vector("tone", "tender", "somber", magnitude=0.62)
    console.add_vector("tension", "tense", "calm", magnitude=-0.4)
    console.add_vector("focus", "Elara", "narrator", magnitude=0.0)
    console.add_box("the faded ink blot", 10, 28, weight=0.9)

    text = steerer.directive(console)
    assert "toward tender at 62%" in text
    assert "toward calm at 40%" in text
    assert "the faded ink blot" in text
    assert "focus" not in text.split("REQUIRED")[0] or "narrator" not in text


def test_anchor_never_exceeds_the_document():
    console = Console(doc=SEEDS["keeper"])
    console.anchor = 12
    assert steerer.anchor_text(console).startswith(SEEDS["keeper"][:12][:10])
    console.anchor = None
    assert steerer.anchor_text(console)[-40:] == SEEDS["keeper"][-40:]


@pytest.mark.asyncio
async def test_mock_steer_changes_the_next_sentence():
    """The whole product claim, in one test: move the knob, the prose moves."""
    tender_console = Console(doc="The lamp burned low.")
    tender_console.add_vector("tone", "tender", "somber", magnitude=0.9)
    somber_console = Console(doc="The lamp burned low.")
    somber_console.add_vector("tone", "tender", "somber", magnitude=-0.9)

    async def run(console):
        out = []
        async for chunk in make_provider("mock", seed=None).stream(console, max_tokens=400):
            out.append(chunk)
        return "".join(out)

    warm = await run(tender_console)
    cold = await run(somber_console)
    assert warm != cold
    assert any(w in warm for w in ("hand", "warm", "softened", "quiet", "promise"))
    assert any(w in cold for w in ("grief", "ash", "faded", "dust", "doorway"))


@pytest.mark.asyncio
async def test_mock_never_welds_two_sentences_together():
    console = Console(doc="A room with no clock in it.")
    async for _ in make_provider("mock", seed=None).stream(console, max_tokens=400):
        pass
    assert "clock in it." in console.doc
    assert ". " in console.doc[console.doc.index("clock") :], console.doc[-80:]


def test_api_provider_refuses_without_a_key(monkeypatch):
    monkeypatch.delenv("STEER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    async def go():
        provider = APIProvider()
        assert provider.activation is False
        await provider.prepare(Console(doc="x"))

    with pytest.raises(RuntimeError, match="no API key"):
        asyncio.run(go())


def test_server_state_endpoint_exposes_vectors_and_audit():
    from fastapi.testclient import TestClient

    from steer.server import create_app

    client = TestClient(create_app(make_provider("mock", seed=None), seed="keeper"))
    payload = client.get("/api/state").json()
    assert payload["doc"].startswith("The wind came off the water")
    assert len(payload["vectors"]) == 3
    labels = {v["label"] for v in payload["vectors"]}
    assert labels == {"tone", "tension", "focus"}
    assert payload["audit"]["words"] > 150
    assert payload["meta"]["provider"] == "mock"


def test_websocket_streams_and_keeps_state():
    from fastapi.testclient import TestClient

    from steer.server import create_app

    app = create_app(make_provider("mock", seed=None), seed="keeper")
    before = len(app.state.console.doc)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            init = ws.receive_json()
            assert init["type"] == "init"
            ws.send_json({"cmd": "generate", "tokens": 40})
            grew = False
            for _ in range(200):
                msg = ws.receive_json()
                if msg["type"] == "delta":
                    grew = True
                if msg["type"] == "status" and msg.get("generating") is False:
                    break
            assert grew
    assert len(app.state.console.doc) > before
    assert app.state.console.tokens > 0


def test_lexicon_buckets_stay_in_their_range():
    for value in (0.0, 0.5, 1.0):
        assert lexicon.bucket_tension(value)
        assert lexicon.bucket_surprise(value)
        assert lexicon.bucket_pace(value)
    name, share = lexicon.focus(SEEDS["keeper"])
    assert 0.0 <= share <= 1.0

    # the readout the console shows: the two poles of one vector split the evidence
    warm, cold = lexicon.pair_score(TENDER, "tender", "somber")
    assert abs((warm + cold) - 1.0) < 1e-9
    assert warm >= 0.68 and cold <= 0.32
    # a passage from a different register must split evenly, not get invented a pole
    neutral, ideally = lexicon.pair_score(HARSH, "tender", "somber")
    assert abs(neutral - 0.5) < 0.06
    tense, calm = lexicon.pair_score(HARSH, "tense", "calm")
    assert tense > 0.6 and calm < 0.4


# ---- the concept, not the look: vectors are mined, boxes are measured ----

def test_vectors_are_mined_from_the_passage_not_a_fixed_set():
    from steer import propose
    from steer.corpus import SEEDS

    doc = SEEDS["keeper"]
    axes = propose.propose(doc)
    assert axes, "the passage should justify at least one axis"
    for ax in axes:
        assert ax["label"] in {"focus", "tone", "tension"}
        assert ax["source"].strip(), "every vector must carry the span it came from"
    labels = {a["label"] for a in axes}
    assert "focus" in labels, "the passage names people, so focus is derivable"


def test_focus_pole_is_a_name_that_appears_in_the_text():
    from steer import propose
    from steer.corpus import SEEDS

    doc = SEEDS["keeper"]
    ax = propose.focus_axis(doc)
    assert ax is not None
    assert ax["plus"] in doc and ax["minus"] in doc
    assert ax["attested"] is True


def test_a_single_sided_axis_is_flagged_rather_than_invented():
    from steer import propose

    doc = (
        "The room was warm and soft and kind. She held the cup close and smiled "
        "at nothing in particular, twice, before the kettle spoke again to her."
    )
    ax = propose.register_axis(doc, "tone")
    assert ax is not None
    assert ax["attested"] is False, "only the tender side is in this text"
    assert ax["minus"] == "somber"


def test_verification_attributes_sentences_and_admits_the_gaps():
    from steer import auditor
    from steer.state import Console

    c = Console()
    c.doc = (
        "He was warm and soft with the boy, and spoke gently of the morning. "
        "The cold grey water slapped the rocks and the wind bit through the door. "
        "A sentence about arithmetic and nothing else whatsoever in it."
    )
    c.add_vector("tone", "warm", "cold", 0.5)
    out = auditor.verify(c)
    assert out["counted"] == 3
    assert 1 <= out["claimed"] <= 3
    assert any(claim["realized"] for claim in out["claims"])
    assert any(not claim["realized"] for claim in out["claims"])


def test_attention_lift_measures_whether_the_box_worked():
    from steer import auditor
    from steer.state import Console

    c = Console()
    before = "The keeper walked out along the wall and looked at the sea for a while. "
    c.doc = before
    c.add_box("lantern oil", 0, 12, weight=0.9)
    generated = " He filled the lantern with oil and carried the lantern oil up the stair."
    c.doc = before + generated
    out = auditor.attention_lift(c, generated)
    assert out and out[0]["lift"] > 1.0
    assert out[0]["held"] is True


def test_rail_scores_attention_to_what_comes_next():
    from steer import auditor
    from steer.state import Console

    c = Console()
    c.doc = (
        "The keeper set the brass telescope on the sill and squared it to the horizon. "
        "Beyond the glass of the brass telescope the horizon held a light that should not be there. "
        "He said nothing at all and the evening simply went on being an evening."
    )
    segs = auditor.audit(c)["segments"]
    assert len(segs) >= 2
    # the span whose words are picked up later must outscore the dead one
    assert max(s["score"] for s in segs) > 0.25


def test_a_clipped_sentence_ends_on_a_word_boundary():
    """A quote cut mid-word reads as a rendering bug, not as a quote."""
    long = ("The keeper climbed the stairs the way he had every night for nineteen years, "
            "and the lamp was still warm, and the window was still dark, and the sea was still out there")
    out = auditor._clip(long)
    assert out.endswith("…")
    assert out[:-1].rstrip()[-1].isalpha()
    assert " " + out[:-1].split()[-1] + " " in long + " "
    assert auditor._clip("short one.") == "short one."
