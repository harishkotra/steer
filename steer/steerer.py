"""Turns console state into something a model can act on.

Two very different targets:

* ``directive()`` — the prompt-compiled path (any hosted model).  Every knob
  becomes an instruction, every attention box becomes a required phrase.
* ``activation_delta()`` — the real path.  A local model gets a hidden-state
  offset per layer instead of a sentence.  See providers/mlx_provider.py.
"""

from __future__ import annotations

from .state import Console

MAX_ANCHOR = 1600


def anchor_text(console: Console, limit: int = MAX_ANCHOR) -> str:
    doc = console.doc
    if console.anchor is not None:
        doc = doc[: console.anchor]
    return doc[-limit:]


def directive(console: Console, sentences: int = 3) -> str:
    lines = ["Continue the story below in the same voice."]
    if console.vectors:
        lines.append("VOICE VECTORS — all apply, strongest first:")
        for v in sorted(console.active, key=lambda x: -x.strength):
            pct = round(v.strength * 100)
            lines.append(f"- {v.label} toward {v.pole} at {pct}% strength")
    if console.boxes:
        phrases = ", ".join(f'"{b.text.strip()}"' for b in sorted(console.boxes, key=lambda b: -b.weight))
        lines.append(f"ATTENTION — the next passage must keep these live: {phrases}")
    if console.pins:
        lines.append("Do not contradict: " + "; ".join(console.pins))
    lines.append(f"Write {sentences} sentences. No preamble, no summary, no quotation marks around the whole reply.")
    return "\n".join(lines)


def strength_map(console: Console) -> dict[str, float]:
    return {v.label.lower(): v.magnitude for v in console.active}


def stack(console: Console):
    """Combine per-vector activation deltas into one offset per layer.

    Each vector carries its own delta (a list of arrays, one per hooked
    layer).  Summing is the simple, honest composition; it is what CAA-style
    steering does when directions are near-orthogonal in practice.
    """
    out = None
    for v in console.active:
        if v.delta is None:
            continue
        for i, d in enumerate(v.delta):
            term = d * v.magnitude
            if out is None:
                out = [None] * len(v.delta)
            out[i] = term if out[i] is None else out[i] + term
    return out


def describe(console: Console) -> dict:
    return {
        "anchor": anchor_text(console, 400),
        "vectors": [v.to_dict() for v in console.vectors],
        "boxes": [b.to_dict() for b in console.boxes],
        "directive": directive(console),
    }
