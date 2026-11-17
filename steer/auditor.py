"""The measurement loop.

The console shows numbers next to the prose, and those numbers have to come
from the text that is actually on screen.  Everything here is lexical and
cheap by design: it runs on every tick, in about a millisecond, and it never
blocks generation.
"""

from __future__ import annotations

import re
import time

from . import lexicon, propose

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


def attention_to_next(doc: str, start: int, end: int) -> float:
    """How strongly a span forecasts the text that follows it.

    The reel's rail is not "important lines", it is *what is going to happen
    next*: a span scores high when the words it plants are picked up by the
    sentences after it.  Measured forward, so a closing image that predicts
    nothing scores low even when it is beautifully written.
    """
    span = doc[start:end]
    tail = doc[end:]
    if len(tail.strip()) < 40:
        return 0.0
    planted = {w.lower() for w in lexicon.words(span) if len(w) > 3}
    if not planted:
        return 0.0
    picked = {w.lower() for w in lexicon.words(tail)}
    return len(planted & picked) / float(len(planted))


def attention_lift(console, generated: str) -> list[dict]:
    """Did a box actually pull the next text toward its own words?

    Compare the share of the box's content words in the text written *after*
    the box was placed against their share in the text before it.  A box that
    does nothing reports ~1.0 and the console says so.
    """
    if not generated.strip():
        return []
    before = console.doc[: -len(generated)] if len(generated) < len(console.doc) else ""
    after_terms = [w.lower() for w in lexicon.words(generated)]
    before_terms = [w.lower() for w in lexicon.words(before)]
    out = []
    for b in console.boxes:
        want = {w.lower() for w in lexicon.words(b.text)}
        want = {w for w in want if len(w) > 3}
        if not want:
            continue
        hit_now = sum(1 for w in after_terms if w in want)
        hit_before = sum(1 for w in before_terms if w in want)
        now = hit_now / max(1, len(after_terms))
        prev = hit_before / max(1, len(before_terms)) if before_terms else 0.0
        # a box whose words never appear after it has not been tested, not
        # failed at 1%; report 0.0 so the UI can say "no pull yet"
        lift = 0.0 if hit_now == 0 else (now + 1e-4) / (prev + 1e-4)
        out.append(
            {
                "id": b.id,
                "text": b.text.strip()[:44],
                "weight": round(b.weight, 2),
                "before": round(prev, 4),
                "after": round(now, 4),
                "lift": round(lift, 2),
                "held": hit_now > 0,
            }
        )
    return out


def _clip(text: str, n: int = 120) -> str:
    """Cut on a word boundary, and say so: a sentence that ends mid-word reads
    like a rendering bug, not like a quote."""
    s = text.strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0] + "…"


def verify(console, tail_sentences: int = 6, floor: float = 0.55) -> dict:
    """Attribute each sentence to the vector it realizes, or to nothing.

    "We detected three sentences, each realizing one vector" is a claim the
    console has to earn per sentence, so an unclaimed sentence is reported as
    unclaimed rather than spread thin across every vector.
    """
    vecs = console.active
    if not vecs:
        return {"claims": [], "claimed": 0, "counted": 0, "note": "no active vectors"}

    sents = [s for s in re.split(r"(?<=[.!?])\s+", console.doc.strip()) if len(s.strip()) > 24]
    sents = sents[-tail_sentences:]

    claims = []
    used = set()
    for s in sents:
        best, best_share = None, 0.0
        for v in vecs:
            plus_share, minus_share = lexicon.pair_score(s, propose.expand(v.plus), propose.expand(v.minus))
            share = plus_share if v.pole == v.plus else minus_share
            if share > best_share:
                best, best_share = v, share
        ok = best is not None and best_share >= floor
        if ok:
            used.add(best.id)
        claims.append(
            {
                "sentence": _clip(s),
                "vector": best.label if ok else "",
                "pole": best.pole if ok else "",
                "share": round(best_share, 3),
                "realized": ok,
            }
        )
    claimed = sum(1 for c in claims if c["realized"])
    distinct = len({c["vector"] for c in claims if c["realized"]})
    return {
        "claims": claims,
        "claimed": claimed,
        "counted": len(claims),
        "vectors": distinct,
        "note": f"{claimed} of {len(claims)} new sentences matched a dial"
        + (f", {distinct} different" if distinct else ""),
    }


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
        plus_share, minus_share = lexicon.pair_score(win, propose.expand(v.plus), propose.expand(v.minus))
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

    # the rail measures attention *forward*: what a span sets up in the text
    # that follows it, nudged by recency so the newest lines are never blank
    segs = []
    for c in clauses(doc):
        fwd = attention_to_next(doc, c["start"], c["end"])
        rec = (c["start"] / max(1, len(doc))) ** 2
        segs.append(
            {
                "start": c["start"],
                "end": c["end"],
                "score": round(max(0.0, min(1.0, 0.75 * fwd + 0.25 * rec)), 3),
            }
        )

    words = len(lexicon.words(doc))
    span = max(1e-3, time.time() - console.started)
    rate = console.tokens / span

    return {
        # the box lift is measured against what this session actually generated
        "attention": attention_lift(console, doc[getattr(console, "gen_at", 0):]),
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
        "verification": verify(console),
        "rate": round(rate, 1),
        "latency_ms": round(console.gen_ms, 1),
        "tokens": console.tokens,
        "note": provider_note,
        "counters": console.counters(),
    }
