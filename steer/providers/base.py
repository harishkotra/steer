"""Provider interface.

A provider turns ``(console state, N tokens)`` into a stream of text.  Two
contracts matter:

1. It must be interruptible.  The console re-steers mid-generation whenever a
   knob moves, so generation is chunked and the loop checks ``console.version``
   between chunks.
2. ``activation=True`` means it can apply real hidden-state offsets.  Anything
   else is prompt-compiled steering, and the UI says which one is running.
"""

from __future__ import annotations

from typing import AsyncIterator

from ..state import Console


class Provider:
    name = "base"
    model = ""
    activation = False

    async def prepare(self, console: Console) -> None:
        """Called once per generation request, before the first chunk."""

    async def stream(self, console: Console, max_tokens: int = 160) -> AsyncIterator[str]:
        raise NotImplementedError

    def note(self) -> str:
        return ""

    def reset(self) -> None:
        """Clear any per-conversation cache when the console resets."""

    def close(self) -> None:
        pass
