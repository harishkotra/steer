"""OpenAI-compatible provider.

Every knob becomes an instruction here.  Moving a knob re-compiles the
directive and restarts the stream from the anchor, which is the honest
version of "real time" on an API you cannot reach inside.
"""

from __future__ import annotations

import json
import os
from typing import AsyncIterator

import httpx

from .. import steerer
from ..state import Console
from .base import Provider


class APIProvider(Provider):
    name = "api"
    activation = False

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.9,
    ) -> None:
        self.model = model or os.environ.get("STEER_API_MODEL", "gpt-4o-mini")
        self.base_url = (base_url or os.environ.get("STEER_API_BASE", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key or os.environ.get("STEER_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        self.temperature = temperature
        if not self.api_key:
            raise RuntimeError(
                "no API key: set STEER_API_KEY (or OPENAI_API_KEY), or run with --provider mock"
            )

    def note(self) -> str:
        return f"prompt-compiled steering · {self.model}"

    async def stream(self, console: Console, max_tokens: int = 160) -> AsyncIterator[str]:
        prompt = steerer.anchor_text(console)
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": [
                {"role": "system", "content": steerer.directive(console)},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{self.base_url}/chat/completions", json=payload, headers=headers
            ) as r:
                if r.status_code >= 400:
                    body = (await r.aread()).decode("utf-8", "replace")[:400]
                    raise RuntimeError(f"{r.status_code}: {body}")
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content") or ""
                    if text:
                        console.doc += text
                        console.tokens += 1
                        yield text
