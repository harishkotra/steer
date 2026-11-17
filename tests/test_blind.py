"""The blind test is a real bet only if the answer stays on the server."""

import asyncio

from steer import blind
from steer.corpus import SEEDS, DEFAULT
from steer.providers import make_provider
from steer.state import Console


def _console():
    provider = make_provider("mock")
    console = Console(doc=SEEDS[DEFAULT], provider=provider.name, model=provider.model)
    console.add_vector(label="tone", plus="soft", minus="somber", source="")
    return provider, console


def test_deal_hides_the_answer_and_writes_two_different_futures():
    provider, console = _console()
    payload = asyncio.run(blind.deal(provider, console))

    assert payload, "a seeded passage must be able to mine an axis"
    assert payload["_truth"] in ("left", "right")
    assert "answer" not in payload
    assert payload["sides"]["left"] and payload["sides"]["right"]
    assert payload["sides"]["left"] != payload["sides"]["right"]


def test_resolve_marks_the_steered_side_and_scores_toward_the_pole():
    provider, console = _console()
    payload = asyncio.run(blind.deal(provider, console))

    answer = payload["_truth"]
    other = "right" if answer == "left" else "left"
    result = blind.resolve(payload, answer)

    assert result["correct"] is True
    assert result["sides"][answer]["steered"] is True
    assert result["sides"][other]["steered"] is False
    assert 0.0 <= result["sides"][answer]["toward"] <= 1.0


def test_toward_is_measured_against_the_pushed_pole_not_against_plus():
    """A minus-pole round must not report the steered side as leaning away."""
    payload = {
        "round": "r1",
        "axis": {"label": "tone", "plus": "soft", "minus": "somber",
                 "pole": "somber", "side": "minus", "strength": 0.85},
        "sides": {
            "left": "the room was somber and quiet and grey",
            "right": "the room was warm and bright and soft",
        },
        "_truth": "left",
    }
    result = blind.resolve(payload, "left")
    assert result["correct"] is True
    assert result["sides"]["left"]["toward"] > result["sides"]["right"]["toward"]


def test_wrong_guess_is_reported_as_wrong():
    provider, console = _console()
    payload = asyncio.run(blind.deal(provider, console))

    wrong = "right" if payload["_truth"] == "left" else "left"
    result = blind.resolve(payload, wrong)
    assert result["correct"] is False
    assert result["answer"] == payload["_truth"]


def test_unknown_pick_falls_back_to_left():
    provider, console = _console()
    payload = asyncio.run(blind.deal(provider, console))
    assert blind.resolve(payload, "middle")["pick"] == "left"


def test_name_axes_are_not_offered_to_the_reader():
    """A dial aimed at a character's name cannot be scored, so it cannot be a round."""
    from steer.state import SteerVector

    name = SteerVector(label="focus", plus="Elias", minus="Marlowe")
    register = SteerVector(label="tone", plus="soft", minus="somber")

    assert blind._scorable(name) is False
    assert blind._scorable(register) is True
