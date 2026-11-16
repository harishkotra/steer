"""The measurement loop.

The console shows numbers next to the prose, and those numbers have to come
from the text that is actually on screen.  Everything here is lexical and
cheap by design: it runs on every tick, in about a millisecond, and it never
blocks generation.
"""

from __future__ import annotations

import re
import time

from . import lexicon

CLAUSE_RE = re.compile(r"[^,;:.!?]+[,;:.!?]*\s*")
WINDOW = 900


def clauses(doc: str) -> list[dict]:
    """Split the document into scorable spans with character offsets."""
    out = []
    for m in CLAUSE_RE.finditer(doc):
        text = m.group(0)
        if text.strip():
            out.append({"start": m.start(), "end": m.end(), "text": text})
    return out


def window(console, size: int = WINDOW) -> str:
    parts = []
    doc = console.doc[-size:]
    parts.append(doc)
    for b in sorted(console.boxes, key=lambda x: -x.weight):
        parts.append(" " + b.text + " " * max(0, int(b.weight * 4)))
    return " ".join(parts)


def last_sentence(doc: str) -> str:
    parts = [p for p in re.split(r"(?<=[.!?])\s+", doc.strip()) if p]
    return parts[-1] if parts else ""


def reported_sentences(doc: str) -> int:
    return len([p for p in re.split(r"(?<=[.!?])\s+", doc.strip()) if p])


def audit(console, provider_note: str = "") -> dict:
    doc = console.doc
    win = window(console)
    sentence = last_sentence(doc)

    t = lexicon.tension(win)
    s = lexicon.surprise(sentence, doc[:-len(sentence)] if sentence else "")
    p = lexicon.pace(win)
    m_label, m_val = lexicon.mode(sentence or win)
    f_name, f_val = lexicon.focus(win)

    vecs = []
    realized_count = 0
    for v in console.active:
        plus_share, minus_share = lexicon.pair_score(win, v.plus, v.minus)
        share = plus_share if v.pole == v.plus else minus_share
        realized = max(0.0, min(1.0, share))
        if realized >= 0.62:
            realized_count += 1
        vecs.append(
            {
                "id": v.id,
                "label": v.label,
                "pole": v.pole,
                "magnitude": round(v.magnitude, 3),
                "realized": round(realized, 3),
            }
        )

    segs = []
    for c in clauses(doc):
        segs.append(
            {
                "start": c["start"],
                "end": c["end"],
                "score": round(lexicon.relevance(c["text"], win), 3),
            }
        )

    words = len(lexicon.words(doc))
    span = max(1e-3, time.time() - console.started)
    rate = console.tokens / span

    return {
        "metrics": {
            "tension": {"value": round(t, 3), "label": lexicon.bucket_tension(t)},
            "surprise": {"value": round(s, 3), "label": lexicon.bucket_surprise(s)},
            "pace": {"value": round(p, 3), "label": lexicon.bucket_pace(p)},
            "mode": {"value": round(m_val, 3), "label": m_label},
            "focus": {"value": round(f_val, 3), "label": f_name},
        },
        "vectors": vecs,
        "realized": realized_count,
        "sentences": reported_sentences(doc),
        "words": words,
        "segments": segs,
        "rate": round(rate, 1),
        "latency_ms": round(console.gen_ms, 1),
        "tokens": console.tokens,
        "note": provider_note,
        "counters": console.counters(),
    }
