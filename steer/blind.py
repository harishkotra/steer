"""Blind test: two futures, one steered, the reader guesses, the auditor rules.

This is the counterfactual the console can run on demand. The passage is
cloned twice -- identical except for one vector at full strength on one side --
and each clone streams its own continuation. The player picks the steered one.
The model never sees the guess; the server holds the answer until a pick comes
back, then scores both texts against the axis it used.

It is the honest version of "feel the vector": if a reader cannot pick it, the
steer was not legible, and the audit says as much.
"""

from __future__ import annotations

import random
import uuid

from . import lexicon, propose
from .providers import Provider
from .state import Console, SteerVector

STRENGTH = 0.85          # full-ish, so the bet is decidable at 70 tokens
TOKENS = 70              # ~3 sentences: enough register to read, short enough to race


def _scorable(v: SteerVector) -> bool:
    """The audit must be able to measure the axis, or the reveal is meaningless.

    A dial aimed at a character's name ("focus -> Elias") is a real steering
    target but not a measurable one: `pair_score` counts register words, and a
    name is neither in the lexicon nor reliably repeated. Such a round would
    score the steered side *lower* than the plain one and call the player wrong
    for a steer that may well have worked.
    """
    if v.plus[:1].isupper() or v.minus[:1].isupper():
        return False
    terms = len(propose.expand(v.plus)) + len(propose.expand(v.minus))
    return terms >= 6


def _axis_from(console: Console) -> SteerVector | None:
    """Pick a fair axis: one the passage attests, preferably an idle dial."""
    idle = [v for v in console.vectors if v.attested and abs(v.magnitude) < 0.01]
    pool = [v for v in idle if _scorable(v)]
    if not pool:
        pool = [v for v in console.vectors if v.attested and _scorable(v)]
    if not pool:
        # a short passage can leave every scorable dial unattested (attestation
        # wants a sentence of evidence). A register dial still steers, and the
        # separation check in deal() is what decides whether the round is fair,
        # so an unattested-but-measurable axis beats refusing to play at all.
        pool = [v for v in console.vectors if _scorable(v)]
    if pool:
        v = random.choice(pool)
        return SteerVector(label=v.label, plus=v.plus, minus=v.minus, source=v.source)

    mined = [f for f in propose.propose(console.doc) if f.get("attested")]
    mined = [
        f for f in mined
        if _scorable(SteerVector(label=f["label"], plus=f["plus"], minus=f["minus"]))
    ]
    if not mined:
        return None
    f = random.choice(mined)
    return SteerVector(label=f["label"], plus=f["plus"], minus=f["minus"], source=f.get("source", ""))


def _clone(console: Console, vector: SteerVector | None) -> Console:
    """A private copy of the passage with exactly one knob turned."""
    c = Console(doc=console.doc, provider=console.provider, model=console.model)
    c.vectors = [vector] if vector else []
    c.gen_at = len(console.doc)
    return c


async def _future(provider: Provider, console: Console, vector: SteerVector | None, tokens: int) -> str:
    c = _clone(console, vector)
    await provider.prepare(c)
    start = len(c.doc)
    async for _ in provider.stream(c, max_tokens=tokens):
        pass
    return c.doc[start:].strip()


def _share(text: str, axis: SteerVector) -> float:
    """How much of the text leans toward the axis' positive pole (0..1)."""
    plus, _minus = lexicon.pair_score(text, propose.expand(axis.plus), propose.expand(axis.minus))
    return round(plus, 3)


def _toward(share: float, side: str) -> float:
    """Share expressed toward whichever pole the dial was pushing."""
    return share if side == "plus" else 1.0 - share


async def deal(provider: Provider, console: Console, tokens: int = TOKENS) -> dict | None:
    """Generate both futures and hide which one was steered."""
    axis = _axis_from(console)
    if axis is None:
        return None

    best = None
    best_margin = -1.0
    for _attempt in range(4):
        axis = _axis_from(console) or axis
        sign = random.choice((1.0, -1.0))
        steered = SteerVector(
            label=axis.label, plus=axis.plus, minus=axis.minus,
            magnitude=STRENGTH * sign, source=axis.source,
        )
        one = await _future(provider, console, steered, tokens)
        two = await _future(provider, console, None, tokens)
        side = "plus" if sign > 0 else "minus"
        margin = _toward(_share(one, axis), side) - _toward(_share(two, axis), side)
        # a round where the steered text does not read as steered is not a game,
        # it is a coin flip: keep the widest gap of the attempts, not the last one
        if margin > best_margin:
            best_margin = margin
            best = (axis, steered, one, two, side)
        if margin >= 0.18:
            break
    axis, steered, one, two, side = best

    # left/right is a coin flip, so a lucky reader cannot pattern-match
    sides = [("left", one, True), ("right", two, False)]
    random.shuffle(sides)

    return {
        "round": uuid.uuid4().hex[:10],
        "axis": {"label": axis.label, "plus": axis.plus, "minus": axis.minus,
                 "pole": steered.pole, "side": side, "strength": STRENGTH},
        "sides": {name: text for name, text, _steered in sides},
        "_truth": next(name for name, _text, ok in sides if ok),
    }


def resolve(payload: dict, pick: str) -> dict:
    """Score the guess and show the measurement behind it."""
    if pick not in ("left", "right"):
        pick = "left"
    truth = payload["_truth"]
    axis = payload["axis"]
    v = SteerVector(label=axis["label"], plus=axis["plus"], minus=axis["minus"])
    left, right = payload["sides"]["left"], payload["sides"]["right"]

    def side(text: str, name: str) -> dict:
        share = _share(text, v)
        # the browser should not have to know which pole was pushed
        return {"text": text, "steered": truth == name, "share": share,
                "toward": round(_toward(share, axis["side"]), 3)}

    return {
        "round": payload["round"],
        "axis": axis,
        "pick": pick,
        "answer": truth,
        "correct": pick == truth,
        "sides": {"left": side(left, "left"), "right": side(right, "right")},
    }
