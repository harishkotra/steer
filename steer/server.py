"""HTTP + WebSocket surface for the console."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import auditor, steerer
from .corpus import SEEDS, DEFAULT
from .providers import Provider
from .state import Console

WEB = Path(__file__).parent / "web"


def create_app(provider: Provider, seed: str = DEFAULT) -> FastAPI:
    app = FastAPI(title="steer", docs_url=None, redoc_url=None)
    console = Console(doc=SEEDS.get(seed, SEEDS[DEFAULT]), provider=provider.name, model=provider.model)
    console.started = time.time()
    _seed_vectors(console)
    app.state.console = console
    app.state.provider = provider
    app.state.seed = seed

    if WEB.exists():
        app.mount("/static", StaticFiles(directory=str(WEB)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(str(WEB / "index.html"))

    @app.get("/api/state")
    async def state() -> dict:
        return _init_payload(console, provider)

    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        await sock.accept()
        task: asyncio.Task | None = None
        try:
            await sock.send_json(_init_payload(console, provider))
            while True:
                msg = await sock.receive_json()
                cmd = msg.get("cmd")

                if cmd == "generate":
                    if task and not task.done():
                        continue
                    console.paused = False
                    task = asyncio.create_task(
                        _generate(sock, console, provider, int(msg.get("tokens", 160)))
                    )

                elif cmd == "stop":
                    console.paused = True
                    if task and not task.done():
                        task.cancel()
                    await sock.send_json({"type": "status", "generating": False})

                elif cmd == "vector":
                    _vector_cmd(console, msg)

                elif cmd == "box":
                    _box_cmd(console, msg)

                elif cmd == "pin":
                    console.toggle_pin(msg.get("id", ""))

                elif cmd == "reset":
                    if task and not task.done():
                        task.cancel()
                    console.doc = msg.get("doc") or SEEDS.get(msg.get("seed", seed), SEEDS[DEFAULT])
                    console.boxes.clear()
                    console.vectors.clear()
                    console.pins.clear()
                    console.anchor = None
                    console.version += 1
                    console.tokens = 0
                    console.started = time.time()
                    provider.reset()
                    _seed_vectors(console)
                    await sock.send_json(
                        {"type": "reset", "doc": console.doc, "vectors": [v.to_dict() for v in console.vectors]}
                    )

                await sock.send_json(_state_payload(console, provider))
        except WebSocketDisconnect:
            pass
        finally:
            if task and not task.done():
                task.cancel()

    return app


def _seed_vectors(console: Console) -> None:
    """Open with the three vectors the reel shows, magnitudes read off the text.

    These are suggestions, not constants of the design: the dock lets you
    rewrite the poles or delete them, and the sliders are what actually steer.
    """
    from . import lexicon

    doc = console.doc
    plan = [
        ("tone", "tender", "somber"),
        ("tension", "tense", "calm"),
        ("focus", lexicon.focus(doc)[0], "narrator"),
    ]
    for label, up, down in plan:
        # read which side the opening actually leans to, then put that pole first
        up_share, down_share = lexicon.pair_score(doc, up, down)
        plus, minus = (up, down) if up_share >= down_share else (down, up)
        lean = abs(up_share - down_share)
        console.add_vector(label, plus, minus, magnitude=round(min(1.0, 0.25 + lean * 0.7), 2))
    console.version += 1


def _init_payload(console: Console, provider: Provider) -> dict:
    return {
        "type": "init",
        "doc": console.doc,
        "vectors": [v.to_dict() for v in console.vectors],
        "meta": {
            "provider": provider.name,
            "model": provider.model,
            "activation": provider.activation,
            "note": provider.note(),
        },
        "audit": auditor.audit(console, provider.note()),
        "seeds": list(SEEDS),
    }


def _state_payload(console: Console, provider: Provider) -> dict:
    return {
        "type": "state",
        "vectors": [v.to_dict() for v in console.vectors],
        "boxes": [b.to_dict() for b in console.boxes],
        "pins": list(console.pins),
        "audit": auditor.audit(console, provider.note()),
        "generating": not console.paused,
    }


def _vector_cmd(console: Console, msg: dict) -> None:
    action = msg.get("action")
    if action == "add":
        console.add_vector(
            label=(msg.get("label") or "tone").strip()[:24],
            plus=(msg.get("plus") or "tender").strip()[:24],
            minus=(msg.get("minus") or "harsh").strip()[:24],
            magnitude=float(msg.get("magnitude") or 0.0),
        )
    elif action == "set":
        console.set_vector(msg.get("id", ""), msg.get("magnitude"))
    elif action == "remove":
        console.remove_vector(msg.get("id", ""))


def _box_cmd(console: Console, msg: dict) -> None:
    action = msg.get("action")
    if action == "add":
        text = msg.get("text") or ""
        start = int(msg.get("start", 0))
        end = int(msg.get("end", start + len(text)))
        if not text:
            text = console.doc[start:end]
        console.add_box(text, start, end, float(msg.get("weight") or 0.6))
    elif action == "weight":
        console.set_box_weight(msg.get("id", ""), float(msg.get("weight") or 0))
    elif action == "remove":
        console.remove_box(msg.get("id", ""))


async def _safe_send(sock: WebSocket, payload: dict) -> bool:
    """Send, or report that the client is gone. Never raise on a closed socket."""
    try:
        await sock.send_json(payload)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


async def _generate(sock: WebSocket, console: Console, provider: Provider, tokens: int) -> None:
    last_audit = 0.0
    t0 = time.perf_counter()
    made = 0
    console.started = console.started or time.time()
    try:
        await provider.prepare(console)
        async for chunk in provider.stream(console, max_tokens=tokens):
            made += 1
            # a token model counts tokens; a word model counts words. both are
            # "what came out of the pipe", which is what the rate means.
            console.tokens += 1 if provider.activation else max(1, len(chunk.split()))
            if not await _safe_send(sock, {"type": "delta", "text": chunk}):
                break
            now = time.perf_counter()
            console.elapsed = now - t0
            console.gen_ms = (now - t0) * 1000 / max(1, console.tokens)
            if now - last_audit > 0.14:
                last_audit = now
                await _safe_send(sock, {"type": "audit", **auditor.audit(console, provider.note())})
    except asyncio.CancelledError:
        await _safe_send(sock, {"type": "status", "generating": False})
        raise
    except Exception as exc:
        await _safe_send(sock, {"type": "error", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        console.elapsed = max(1e-3, time.perf_counter() - t0)
        await _safe_send(sock, {"type": "audit", **auditor.audit(console, provider.note())})
        await _safe_send(sock, {"type": "status", "generating": False})
