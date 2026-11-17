"""Vectors are mined from the passage, not handed to it.

The reel's claim is specific: *"these are actually contextual based on the
story. It's not a predefined set of vectors. Each one is live generated."*

So the axis names come out of the text in front of you.  Detector lists below
are only used to ask *which side of a register this passage is already on*;
the pole a knob pulls toward is a word the story itself used, and every vector
carries the span that justified it.  When only one side is attested the other
pole is proposed and marked `attested: False`, because pretending the text
argued for both sides would be the lie this whole audit exists to avoid.
"""

from __future__ import annotations

import re
from collections import Counter

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")
NAME_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")
SENT_START = re.compile(r"(?:^|[.!?\"\n])\s*$")

# Detectors, not axes: they decide which side of a register the passage sits on.
REGISTERS = {
    "tone": {
        "plus": ["warm", "soft", "gentle", "tender", "held", "quiet", "close", "slow",
                 "kind", "care", "steady", "patient"],
        "minus": ["cold", "grey", "gray", "bleak", "hard", "dark", "dead", "flat",
                  "dull", "grief", "ash", "faded", "dust", "indifferent"],
        "labels": ("tender", "somber"),
    },
    "tension": {
        "plus": ["tense", "tight", "sharp", "urgent", "strain", "brace", "clench",
                 "snap", "creak", "muscle", "footstep", "latch", "footsteps",
                 "muscles", "creaks", "latches", "shadow", "knock"],
        "minus": ["calm", "still", "rest", "settle", "easy", "loose", "quiet", "patient"],
        "labels": ("strained", "relaxed"),
    },
}

SKIP_CAPS = {
    "The", "It", "He", "She", "They", "But", "And", "When", "Then", "That", "This",
    "There", "His", "Her", "Their", "Outside", "Inside", "Above", "Below", "Once",
    "Now", "After", "Before", "Every", "Some", "What", "Why", "How", "Not", "No",
}


def sentences(doc: str) -> list[str]:
    return [p for p in re.split(r"(?<=[.!?])\s+", doc.strip()) if p]


def attested(doc: str, pool: list[str]) -> list[str]:
    low = doc.lower()
    return [w for w in pool if re.search(rf"\b{w}\b", low)]


def _evidence(doc: str, word: str, width: int = 58) -> str:
    m = re.search(rf"\b{word}\b", doc, re.I)
    if not m:
        return ""
    a = max(0, m.start() - width // 2)
    b = min(len(doc), m.end() + width // 2)
    return ("…" if a else "") + doc[a:b].strip().replace("\n", " ") + ("…" if b < len(doc) else "")


def names(doc: str) -> list[tuple[str, int]]:
    """Proper nouns that are not sentence-openers, most frequent first."""
    counts: Counter[str] = Counter()
    for m in NAME_RE.finditer(doc):
        before = doc[: m.start()]
        if SENT_START.search(before):
            continue
        if m.group(0) in SKIP_CAPS:
            continue
        counts[m.group(0)] += 1
    return [(n, c) for n, c in counts.most_common() if c >= 2]


def first_person(doc: str) -> int:
    return len(re.findall(r"\b(?:I|my|me|myself)\b", doc))


def register_axis(doc: str, label: str) -> dict | None:
    reg = REGISTERS[label]
    plus_hits = attested(doc, reg["plus"])
    minus_hits = attested(doc, reg["minus"])
    if not plus_hits and not minus_hits:
        return None

    # the story's own words name the poles; the detector only ranked them
    plus = plus_hits[0] if plus_hits else reg["labels"][0]
    minus = minus_hits[0] if minus_hits else reg["labels"][1]
    both = bool(plus_hits and minus_hits)
    return {
        "label": label,
        "plus": plus,
        "minus": minus,
        "attested": both,
        "source": _evidence(doc, plus if plus_hits else (minus_hits or [""])[0]),
        "found": {"plus": plus_hits[:4], "minus": minus_hits[:4]},
    }


def focus_axis(doc: str) -> dict | None:
    ens = names(doc)
    you = first_person(doc)
    if not ens:
        return None
    top, count = ens[0]
    if you >= max(2, count // 2):
        minus, source = "narrator", _evidence(doc, top)
    elif len(ens) > 1:
        minus, source = ens[1][0], _evidence(doc, top)
    else:
        return None
    return {
        "label": "focus",
        "plus": top,
        "minus": minus,
        "attested": True,          # both poles are literally in the text
        "source": source,
        "found": {"plus": [top], "minus": [minus], "mentions": count},
    }


def propose(doc: str) -> list[dict]:
    """Every vector the passage can justify right now, best-founded first."""
    if len(WORD_RE.findall(doc)) < 18:
        return []
    out = []
    f = focus_axis(doc)
    if f:
        out.append(f)
    for label in ("tone", "tension"):
        ax = register_axis(doc, label)
        if ax:
            out.append(ax)
    return out


def expand(pole: str) -> str:
    """A pole word plus the rest of its register.

    Verification asks "did the passage land on this side of the axis", not
    "did the exact word appear" — a tender sentence that says *steady care*
    instead of *soft* has still realized the vector, and an audit that misses
    it is measuring vocabulary rather than effect.
    """
    w = pole.lower().strip()
    for reg in REGISTERS.values():
        # the label itself ("strained") names a side without appearing in it
        if w == reg["labels"][0]:
            return " ".join([pole] + reg["plus"])
        if w == reg["labels"][1]:
            return " ".join([pole] + reg["minus"])
        for side in ("plus", "minus"):
            if w in reg[side]:
                return " ".join([pole] + [x for x in reg[side] if x != w])
    return pole


def lean(doc: str, ax: dict) -> float:
    """Which end of the axis the passage already sits on, -1..1."""
    from . import lexicon

    plus_share, _ = lexicon.pair_score(doc, ax["plus"], ax["minus"])
    return max(-1.0, min(1.0, (plus_share - 0.5) * 2.0))
