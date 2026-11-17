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


BOX_CLAUSES = [
    "He thought about the {term} and how it had not changed.",
    "The {term} was still in the room with him.",
    "Nothing about the {term} had been decided yet.",
    "It came back to the {term}, the way small things do.",
]


# a box around "until" or "about" is not a subject; the clause path should
# carry the most substantive word the reader selected
STOP = {
    "about", "after", "again", "against", "almost", "already", "because", "before",
    "being", "between", "could", "didn", "does", "down", "each", "even", "ever",
    "from", "have", "here", "into", "just", "like", "made", "make", "many", "more",
    "most", "much", "must", "never", "only", "other", "over", "said", "same",
    "should", "since", "some", "still", "such", "than", "that", "their", "them",
    "then", "there", "these", "they", "this", "those", "through", "under", "until",
    "very", "want", "well", "were", "what", "when", "where", "which", "while",
    "will", "with", "would", "your",
}

POLE_MAP = {
    "strained": "tense",
    "relaxed": "warm",
    "still": "warm",
    "calm": "warm",
    "soft": "tender",
    "gentle": "tender",
    "kind": "tender",
    "cold": "somber",
    "grey": "somber",
    "hard": "somber",
    "warm": "tender",
}


FOCUS = [
    "{name} did not look up from the page.",
    "{name} set the glass down and listened to the water.",
    "Whatever the room was doing, {name} let it finish.",
    "It was {name} who moved first, and the room followed.",
    "{name} kept the name of the place to himself.",
    "{name} counted the stair treads without meaning to.",
]


def _pool_for(label: str) -> str:
    if label in POOLS:
        return label
    mapped = POLE_MAP.get(label, "")
    return mapped if mapped in POOLS else ""


def _resolve(pole: str) -> str:
    """Map any mined pole onto a pool this corpus can actually write.

    The axes are mined from the passage, so they arrive as words the corpus
    was never keyed on ("soft", "shadow", "strained").  Falling back to neutral
    text would make every dial a placebo — the audit would then truthfully
    report 0.5 and nothing would ever be realized.
    """
    key = pole.lower().strip()
    if key in POLE_MAP:
        return POLE_MAP[key]
    if key in POOLS:
        return key
    alt = CONTRAST.get(key, "")
    if alt in POOLS:
        return alt
    from ..propose import REGISTERS

    for reg in REGISTERS.values():
        if key == reg["labels"][0] or key in reg["plus"]:
            hit = _pool_for(reg["labels"][0])
            if hit:
                return hit
        if key == reg["labels"][1] or key in reg["minus"]:
            hit = _pool_for(reg["labels"][1])
            if hit:
                return hit
    return ""


def _attend(piece: str, pole: str, boxes, rng: random.Random) -> str:
    """Bias the next sentence toward the boxed words without quoting them.

    The reel's promise is "the next text will be more related to those words",
    so the mock picks, out of its register pool, the continuation that actually
    shares vocabulary with the box — and the audit then measures that share and
    reports ×1.0 when it failed to happen.
    """
    want = {w.lower().strip(".,;:") for b in sorted(boxes, key=lambda b: -b.weight) for w in b.text.split()}
    want = {w for w in want if len(w) > 3}
    if not want:
        return piece
    pool = POOLS.get(_resolve(pole), [])
    pool = [s for s in pool if s not in piece]
    if not pool:
        return piece

    def score(sentence: str) -> float:
        terms = {w.lower().strip(".,;:") for w in sentence.split()}
        return len(terms & want) / float(len(want))

    best = max(pool, key=score)
    return best if score(best) > 0 else piece


def _pick(vec, pole: str, console, rng: random.Random, used: dict[str, set[int]]) -> str:
    """Choose the next sentence: in register, biased to the box, then unseen."""
    from ..lexicon import pair_score
    from ..propose import expand

    pool = list(POOLS.get(_resolve(pole), []))
    if pole[:1].isupper():
        pool = [f.format(name=pole) for f in FOCUS]
    if not pool:
        pool = list(GENERIC)
    if vec is not None:
        def hit(sentence: str) -> float:
            share = pair_score(sentence, expand(vec.plus), expand(vec.minus))
            return share[0] if vec.pole == vec.plus else share[1]

        strong = [s for s in pool if hit(s) >= 0.6]
        if strong:
            pool = strong
    if console.boxes:
        want = {w.lower().strip(".,;:") for b in console.boxes for w in b.text.split()}
        want = {
            w
            for w in want
            if len(w) > 3
            and w not in STOP
            and not w.endswith(("ed", "ing", "ly", "s"))
        }
        pulled = [s for s in pool if {w.lower().strip(".,;:") for w in s.split()} & want]
        if pulled:
            pool = pulled
        elif want:
            # nothing in the register pool mentions it, so the box is carried by
            # a clause instead — the audit can still measure that it landed
            weight = max(b.weight for b in console.boxes)
            if weight >= 0.35:
                term = max(sorted(want), key=len)
                # do not re-use the same clause for the same box word: a fixed
                # tail reads as a template and inflates the lift for free
                ckey = f"clause:{term}"
                ctaken = used.setdefault(ckey, set())
                left = [i for i in range(len(BOX_CLAUSES)) if i not in ctaken] or list(range(len(BOX_CLAUSES)))
                ci = rng.choice(left)
                ctaken.add(ci)
                tail = BOX_CLAUSES[ci].format(term=term).rstrip(".")
                base = _sentence_for_pool(pool, _resolve(pole) or "generic", rng, used).rstrip(" .")
                # one sentence, not two: otherwise the box clause is scored on
                # its own and the register that earned the vector is lost
                return f"{base} — {tail[:1].lower() + tail[1:]}."
    return _sentence_for_pool(pool, _resolve(pole) or "generic", rng, used)


def _sentence_for(pole: str, rng: random.Random, used: dict[str, set[int]]) -> str:
    pool = POOLS.get(_resolve(pole), [])
    if not pool:
        pool = GENERIC
    if pole[:1].isupper():
        pool = [f.format(name=pole) for f in FOCUS]
    return _sentence_for_pool(pool, _resolve(pole) or "generic", rng, used)


def _sentence_for_pool(pool: list[str], key: str, rng: random.Random, used: dict[str, set[int]]) -> str:
    taken = used.setdefault(key, set())
    idx = rng.randrange(len(pool))
    for _ in range(5):
        if idx not in taken:
            break
        idx = rng.randrange(len(pool))
    taken.add(idx)
    return pool[idx]


class MockProvider(Provider):
    name = "mock"
    model = "corpus"

    def __init__(self, seed: int | None = None) -> None:
        self._used: dict[int, dict[str, set[int]]] = {}
        self._seen: dict[int, set[str]] = {}
        self._seed = seed

    def reset(self) -> None:
        self._used.clear()
        self._seen.clear()

    async def stream(self, console: Console, max_tokens: int = 160) -> AsyncIterator[str]:
        rng = random.Random(self._seed if self._seed is not None else console.version)
        used = self._used.setdefault(id(console), {})

        if console.doc and not console.doc[-1].isspace():
            console.doc += " "
            yield " "

        out = ""
        last_vec = ""
        tally: dict[str, int] = {}
        for _ in range(3):
            if console.paused:
                return
            # re-read the knobs for every sentence: turning a dial changes the
            # next sentence, not the next paragraph.
            # all three vectors act; each sentence lands on one of them, picked
            # in proportion to how hard its dial is pushed
            act = sorted(console.active, key=lambda v: -v.strength)
            if act:
                # keep the last vector out of the draw when another one is live:
                # the console claims "each sentence realizes one vector", and a
                # demo where every sentence realizes the same one proves nothing
                pool_act = [v for v in act if v.label != last_vec] or act
                counts = {v.label: tally.get(v.label, 0) for v in pool_act}
                fewest = min(counts.values())
                fresh = [v for v in pool_act if counts[v.label] == fewest]
                vec = rng.choices(fresh, weights=[max(1e-3, v.strength) for v in fresh], k=1)[0]
                tally[vec.label] = tally.get(vec.label, 0) + 1
                pole, last_vec = vec.pole, vec.label
            else:
                pole = ""
            seen = self._seen.setdefault(id(console), set())
            piece = _pick(vec if act else None, pole, console, rng, used)
            for _ in range(4):
                if piece not in seen:
                    break
                piece = _pick(vec if act else None, pole, console, rng, used)
            seen.add(piece)

            # close the sentence before the next one starts: a piece that runs
            # into its successor ("the silenceThe latch clicked") reads as a bug
            # in the steerer rather than a quirk of the demo text
            piece = piece.strip()
            if piece and piece[-1] not in ".!?\u201d":
                piece += "."

            words = piece.split()
            for i, w in enumerate(words):
                sep = "" if (not console.doc or console.doc[-1].isspace()) else " "
                chunk = sep + w
                if i == len(words) - 1:
                    chunk += " "
                out += chunk
                console.doc += chunk
                yield chunk
                await asyncio.sleep(0.018)
