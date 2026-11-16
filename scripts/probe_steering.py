"""Does a knob actually move the model? Two instruments, no vibes.

  .venv/bin/python scripts/probe_steering.py logits   # is the delta in the graph?
  .venv/bin/python scripts/probe_steering.py text     # does the prose change?

The logits check is the honest one: it compares the next-token distribution with
the offset installed against the same forward pass without it, so a delta that
never reaches the residual stream shows up as a zero difference instead of a
plausible-looking paragraph.
"""

from __future__ import annotations

import asyncio
import sys

from steer.providers.mlx_provider import MLXProvider
from steer.state import Console

SEED = (
    "The wind came off the water all night, worrying at the shutters. "
    "Captain Elias Marlowe set the pen down and listened."
)
N = 30


def probe_logits() -> None:
    provider = MLXProvider(temperature=0.0)
    mx = provider._mx
    console = Console(doc=SEED)
    console.add_vector("tone", "tender", "harsh", magnitude=1.0)
    vector = console.vectors[0]
    prompt = provider._build_prompt(console)
    ids = mx.array(provider.tokenizer.encode(prompt))[None]

    logits_plain = provider.net(ids, cache=provider._make_cache())
    delta = provider.build_delta(console, vector)
    provider.arm(console, rebuild=False)
    logits_steered = provider.net(ids, cache=provider._make_cache())
    provider.disarm()
    mx.eval(logits_plain, logits_steered)

    a = logits_plain[0, -1]
    b = logits_steered[0, -1]
    diff = b - a
    print(f"delta shape {delta.shape} · layer {provider.layer_idx} · scale {provider.scale}")
    print(f"delta L2 norm: {float(mx.linalg.norm(delta)):.3f} (layer ref {provider._ref_norm:.1f})")
    print(f"max |Δlogit|: {float(mx.max(mx.abs(diff))):.3f}")
    print(f"mean |Δlogit|: {float(mx.mean(mx.abs(diff))):.4f}")

    order = mx.argsort(diff)[-5:].tolist()
    print("tokens pushed up the most:")
    for tok in reversed(order):
        print(f"   {provider.tokenizer.decode([tok])!r:>18}  {float(diff[tok]):+.3f}")
    order = mx.argsort(diff)[:5].tolist()
    print("tokens pushed down the most:")
    for tok in order:
        print(f"   {provider.tokenizer.decode([tok])!r:>18}  {float(diff[tok]):+.3f}")


async def _one(provider: MLXProvider, magnitude: float) -> str:
    console = Console(doc=SEED)
    console.add_vector("tone", "tender", "harsh", magnitude=magnitude)
    out = []
    async for chunk in provider.stream(console, max_tokens=N):
        out.append(chunk)
    return "".join(out).strip().replace("\n", " ")


async def probe_text() -> None:
    provider = MLXProvider(temperature=0.0)
    print(f"layer {provider.layer_idx} · model {provider.model_id}\n")
    for scale in (0.04, 0.08, 0.16, 0.28):
        provider.scale = scale
        provider._built.clear()
        warm = await _one(provider, 1.0)
        cold = await _one(provider, -1.0)
        print(f"gain {scale:>5.2f}  same={warm == cold}")
        print(f"   tender: {warm[:130]}")
        print(f"   harsh : {cold[:130]}\n")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "logits"
    if mode == "text":
        asyncio.run(probe_text())
    else:
        probe_logits()
