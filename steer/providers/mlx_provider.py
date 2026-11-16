"""Local provider with real activation steering.

A knob does not become a sentence here.  It becomes a difference vector
between the model's own hidden states for two phrasings of the same context,
normalised and added to a mid-depth layer on every forward pass:

    delta = unit( h(ctx + "voice turns tender") - h(ctx + "voice turns harsh") )
    x_l   += scale * magnitude * delta

``scale`` is in units of the layer's own activation norm, so the same number
behaves the same way across model sizes.  Because the offset is applied inside
the forward pass, moving a knob between tokens steers the token that is about
to be sampled — no restart, no prompt rewrite.

Only works on Apple silicon with ``mlx-lm`` installed and a local model.
"""

from __future__ import annotations

import asyncio
import threading
from typing import AsyncIterator

from .. import steerer
from ..state import Console
from .base import Provider

# module id -> (delta to add, list to capture activations into)
_HOOKS: dict[int, tuple[object | None, list | None]] = {}
_PATCHED: set[int] = set()


def _patch(cls) -> None:
    if id(cls) in _PATCHED:
        return
    original = cls.__call__

    def call(self, *args, **kwargs):
        y = original(self, *args, **kwargs)
        hook = _HOOKS.get(id(self))
        if hook is not None:
            delta, capture = hook
            if delta is not None:
                y = y + delta
            if capture is not None:
                capture.append(y)
        return y

    cls.__call__ = call
    _PATCHED.add(id(cls))


class MLXProvider(Provider):
    name = "mlx"
    activation = True

    def __init__(self, model_id: str = "mlx-community/Qwen2.5-3B-Instruct-4bit",
                 layer: float | None = None, scale: float = 0.10,
                 temperature: float = 0.85, top_p: float = 0.92) -> None:
        import mlx.core as mx
        from mlx_lm import load

        self._mx = mx
        self.model_id = model_id
        self.model = model_id.split("/")[-1]  # display name
        self.scale = float(scale)
        self.temperature = float(temperature)
        self.top_p = float(top_p)
        self.net, self.tokenizer = load(model_id)
        layers = self.net.model.layers
        self.layer_idx = int(len(layers) * (layer if layer is not None else 0.55))
        self.layer_idx = max(0, min(len(layers) - 1, self.layer_idx))
        self.layer = layers[self.layer_idx]
        _patch(type(self.layer))
        self._built: dict[tuple[str, str], object] = {}

    # -- internals -------------------------------------------------------
    def note(self) -> str:
        return f"activation steering · layer {self.layer_idx}"

    def _hidden(self, text: str):
        mx = self._mx
        ids = self.tokenizer.encode(text)
        ids = ids[-880:]
        cap: list = []
        _HOOKS[id(self.layer)] = (None, cap)
        cache = self._make_cache()
        try:
            self.net(mx.array(ids)[None], cache=cache)
        finally:
            _HOOKS[id(self.layer)] = (None, None)
        if not cap:
            raise RuntimeError("activation capture failed: layer was not executed")
        h = cap[0].astype(mx.float32)
        # the layer's own operating scale: offsets are expressed as a fraction of
        # this, so one magnitude number behaves the same on a 3B and a 30B
        self._ref_norm = float(mx.mean(mx.linalg.norm(h, axis=-1)))
        return h[:, -1:, :]

    def _make_cache(self):
        try:
            from mlx_lm.models.cache import make_prompt_cache
            return make_prompt_cache(self.net)
        except Exception:
            return None

    def build_delta(self, console: Console, vector, force: bool = False):
        mx = self._mx
        key = (vector.plus, vector.minus)
        if not force and key in self._built:
            return self._built[key]
        ctx = steerer.anchor_text(console, 700)
        plus = f"{ctx}\n\n> The narration now turns {vector.plus}. Next line:"
        minus = f"{ctx}\n\n> The narration now turns {vector.minus}. Next line:"
        h_plus = self._hidden(plus)
        h_minus = self._hidden(minus)
        d = h_plus - h_minus
        unit = d / (mx.linalg.norm(d) + 1e-6)
        # scale is a fraction of the layer's activation norm, not an absolute
        # number of nats — that is what keeps the dials meaningful across models
        d = unit * (self.scale * getattr(self, "_ref_norm", 1.0))
        self._built[key] = d
        return d

    def arm(self, console: Console, rebuild: bool = False) -> None:
        """Rebuild and install the combined offset for the next forward pass."""
        mx = self._mx
        total = None
        for v in console.active:
            d = self.build_delta(console, v, force=rebuild)
            term = d * (v.magnitude)
            total = term if total is None else total + term
        _HOOKS[id(self.layer)] = (total, None)

    def disarm(self) -> None:
        _HOOKS[id(self.layer)] = (None, None)

    # -- generation ------------------------------------------------------
    async def stream(self, console: Console, max_tokens: int = 160) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def emit(item) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, item)

        def work() -> None:
            try:
                self.arm(console, rebuild=True)
                prompt = self._build_prompt(console)
                self._run(console, prompt, max_tokens, emit)
            except Exception as exc:  # surfaced in the UI, not swallowed
                emit(("error", f"{type(exc).__name__}: {exc}"))
            finally:
                self.disarm()
                emit(("done", None))

        threading.Thread(target=work, daemon=True).start()

        while True:
            kind, payload = await queue.get()
            if kind == "done":
                return
            if kind == "error":
                raise RuntimeError(payload)
            console.doc += payload
            yield payload

    def _build_prompt(self, console: Console) -> str:
        head = steerer.anchor_text(console, 1200)
        system = (
            "You are a novelist continuing a passage already in progress. "
            "Write only the next sentences. Do not repeat, quote or summarise the "
            "text you are given, and do not add a preamble or a label."
        )
        try:
            return self.tokenizer.apply_chat_template(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": head},
                ],
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            return head + "\n"

    def _run(self, console: Console, prompt: str, max_tokens: int, emit):
        mx = self._mx
        from mlx_lm.sample_utils import make_sampler

        sampler = make_sampler(temp=self.temperature, top_p=self.top_p)
        ids = self.tokenizer.encode(prompt)
        cache = self._make_cache()
        logits = self.net(mx.array(ids)[None], cache=cache)
        last_version = console.version
        produced = 0
        buf = ""
        stop = self.tokenizer.encode("\n\nUser") or []

        for _ in range(max_tokens):
            if console.paused:
                break
            if console.version != last_version:
                last_version = console.version
                self.arm(console)
            tok = sampler(logits[:, -1, :])
            tok_id = int(tok.item()) if hasattr(tok, "item") else int(tok[0])
            if tok_id == self.tokenizer.eos_token_id:
                break
            text = self.tokenizer.decode([tok_id])
            produced += 1
            buf += text
            if len(buf) >= 4 or text.endswith((" ", ".", ",", "\n")):
                emit(("text", buf))
                buf = ""
            logits = self.net(mx.array([[tok_id]]), cache=cache)
            if produced >= max_tokens:
                break
        if buf:
            emit(("text", buf))
