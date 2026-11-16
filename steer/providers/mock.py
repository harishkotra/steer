"""Offline provider.

Generates literary continuations from a small hand-written corpus, biased by
the active steer vectors.  It exists so the console is fully alive with zero
API keys and zero downloads: clone, run, drag a knob, watch the prose change.
"""

from __future__ import annotations

import asyncio
import random
from typing import AsyncIterator

from ..state import Console
from .base import Provider

GENERIC = [
    "The air held its shape a moment longer than it should have.",
    "Nothing in the room had moved, and yet the room was different.",
    "Somewhere below, water found a new way through the stone.",
    "She counted the silence the way other people counted coins.",
    "The lamp guttered, recovered, and went on pretending to be reliable.",
    "What came next arrived without announcing itself.",
]

POOLS: dict[str, list[str]] = {
    "tender": [
        "Her hand found his without asking permission, warm and certain.",
        "He held the small weight of it carefully, the way you hold something that can break.",
        "The light softened against her cheek and stayed there, patient.",
        "Close enough to hear him breathe, she let the quiet do the talking.",
        "His thumb brushed the page and left a smear of warmth behind.",
        "She said his name once, quietly, and the room forgave them both.",
        "The blanket settled over her shoulders like a promise someone meant.",
        "There was no hurry in him, only the steady care of someone staying.",
    ],
    "somber": [
        "The house kept its grief in the walls and let no one hear it.",
        "Ash settled on the windowsill, pale as the memory of snow.",
        "He stood in the doorway of a room that had stopped waiting for him.",
        "The bell rang once and the town pretended not to count the hour.",
        "Dust turned slowly in the last of the light, indifferent.",
        "Her name was still written on the beam, faded to the colour of old smoke.",
    ],
    "tense": [
        "The latch clicked, and every muscle in the room answered it.",
        "He heard the second set of footsteps before he saw the door move.",
        "Something in the dark breathed wrong, and then corrected itself.",
        "The rope creaked overhead, once, and the silence after it was worse.",
        "Her fingers closed on the edge of the table until the wood complained.",
        "The shadow at the window did not belong to anything outside.",
    ],
    "action": [
        "He lunged, caught the ledge, and hauled himself through before the shutter fell.",
        "She tore the page free, shoved it into the grate, and struck the match.",
        "The door burst inward and he was already moving, chair overturned behind him.",
        "He grabbed the lantern, swung wide, and drove the thing back into the stairwell.",
        "She sprinted the length of the hall, shoulder down, and hit the bar at a run.",
        "The blade came up, he twisted, and the desk went over between them.",
    ],
    "wonder": [
        "The clearing opened like a held breath, silvered and impossibly still.",
        "Light pooled in the roots and did not belong to any sun she knew.",
        "The stones hummed a note too low to hear and too deep to ignore.",
        "Above her, the sky was full of stars arranged in no pattern she had ever learned.",
        "Something older than the forest watched, and did not look away.",
        "The water mirrored a moon that had not risen yet.",
    ],
    "warm": [
        "Bread smell, lamp glow, and the sound of someone moving in the next room.",
        "The fire took the chill out of her hands one finger at a time.",
        "He laughed, and the whole kitchen leaned toward the sound.",
        "Morning came in gold and nobody hurried it.",
    ],
}

CONTRAST = {
    "tender": "harsh", "somber": "bright", "tense": "calm",
    "action": "reflection", "wonder": "ordinary", "warm": "cold",
}


def _sentence_for(pole: str, rng: random.Random, used: set[int]) -> str:
    pool = POOLS.get(pole.lower()) or POOLS.get(CONTRAST.get(pole.lower(), ""), [])
    if not pool:
        pool = GENERIC
    idx = rng.randrange(len(pool))
    for _ in range(4):
        if idx not in used:
            break
        idx = rng.randrange(len(pool))
    used.add(idx)
    return pool[idx]


class MockProvider(Provider):
    name = "mock"
    model = "corpus"

    def __init__(self, seed: int | None = None) -> None:
        self._used: dict[int, set[int]] = {}
        self._seed = seed

    def reset(self) -> None:
        self._used.clear()

    async def stream(self, console: Console, max_tokens: int = 160) -> AsyncIterator[str]:
        rng = random.Random(self._seed if self._seed is not None else console.version)
        used = self._used.setdefault(id(console), set())

        if console.doc and not console.doc[-1].isspace():
            console.doc += " "
            yield " "

        out = ""
        for _ in range(3):
            if console.paused:
                return
            # re-read the knobs for every sentence: turning a dial changes the
            # next sentence, not the next paragraph.
            poles = [v.pole for v in sorted(console.active, key=lambda v: -v.strength)]
            if console.boxes and out == "":
                piece = console.boxes[0].text.strip()
            else:
                piece = _sentence_for(poles[0] if poles else "", rng, used)

            words = piece.split()
            for i, w in enumerate(words):
                chunk = ("" if out.endswith(" ") or out == "" else " ") + w
                if i == len(words) - 1:
                    chunk += " "
                out += chunk
                console.doc += chunk
                console.tokens += 1
                yield chunk
                await asyncio.sleep(0.018)
