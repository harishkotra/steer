"""HTTP + WebSocket surface for the console."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import auditor, blind, steerer
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

    # --- blind test ------------------------------------------------------
    # The answer never leaves the server until a pick comes back, so the game
    # is a real bet: the browser holds two texts and no truth.
    @app.post("/api/blind")
    async def blind_deal() -> dict:
        if getattr(console, "generating", False):
            return {"error": "stop the stream first — the blind test needs the passage to sit still"}
        payload = await blind.deal(provider, console)
        if payload is None:
            return {"error": "not enough text to mine an axis yet — write a paragraph first"}
        app.state.blind = payload
        return {k: v for k, v in payload.items() if not k.startswith("_")}

    @app.post("/api/blind/{round_id}/{pick}")
    async def blind_guess(round_id: str, pick: str) -> dict:
        payload = getattr(app.state, "blind", None)
        if not payload or payload.get("round") != round_id:
            return {"error": "that round is gone — deal a new one"}
        return blind.resolve(payload, pick)

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
                    # one writer per passage: two live streams interleave their
                    # words into the same document, which reads as garbage.
                    # The flag is time-boxed because a stream whose client went
                    # away must never wedge the console for the next visitor --
                    # that reads to the user as "space does nothing".
                    stale = time.time() - getattr(console, "gen_since", 0.0) > 25.0
                    if getattr(console, "generating", False) and not stale:
                        continue
                    if task and not task.done():
                        continue
                    console.paused = False
                    task = asyncio.create_task(
                        _generate(sock, console, provider, int(msg.get("tokens", 160)))
                    )
                    console.gen_task = task

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
            # the socket that owned the stream is gone: free the console at once
            # instead of waiting for the staleness window
            if getattr(console, "gen_task", None) is task:
                console.generating = False
            if task and not task.done():
                task.cancel()

    return app


def _seed_vectors(console: Console, keep_manual: bool = True) -> None:
    """Propose vectors from the passage itself, the way the reel does.

    Nothing here is a predefined set: the axes are mined from the document
    (its own names, its own register words), each carries the span that
    justified it, and a knob the user has touched is never overwritten.
    """
    from . import propose as prop

    manual = [v for v in console.vectors if v.manual] if keep_manual else []
    prev = {v.label: v for v in console.vectors if not v.manual}
    fresh = []
    for ax in prop.propose(console.doc):
        if ax["label"] in {v.label for v in manual}:
            continue
        old = prev.get(ax["label"])
        if old and old.plus == ax["plus"] and old.minus == ax["minus"]:
            mag = old.magnitude
        else:
            mag = round(min(1.0, 0.25 + abs(prop.lean(console.doc, ax)) * 0.7), 2)
        fresh.append(
            dict(
                label=ax["label"],
                plus=ax["plus"],
                minus=ax["minus"],
                magnitude=mag,
                source=ax["source"],
                attested=ax["attested"],
            )
        )
    # an axis the passage justified earlier stays on the rack even if the last
    # paragraph no longer supports it: the dial is the user's, not the tail's
    have = {f["label"] for f in fresh} | {v.label for v in manual}
    for label, old in prev.items():
        if label not in have:
            fresh.append(
                dict(
                    label=old.label,
                    plus=old.plus,
                    minus=old.minus,
                    magnitude=old.magnitude,
                    source=old.source,
                    attested=old.attested,
                )
            )
    # hold the rack's order: a dial that jumps rows while you are dragging it
    # is a dial you cannot aim
    order = {v.label: i for i, v in enumerate(console.vectors)}
    fresh.sort(key=lambda f: order.get(f["label"], 10 ** 6))

    if not fresh and not manual:
        return
    console.vectors = list(manual)
    for f in fresh:
        console.add_vector(**f)
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
        "generating": console.generating,
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
        # selecting the same span twice should not stack two identical boxes:
        # the panel would then show a duplicate and the lift would be measured twice
        same = next((b for b in console.boxes if b.start == start and b.end == end), None)
        if same is not None:
            console.set_box_weight(same.id, float(msg.get("weight") or 0.6))
            return
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
    gen_from = len(console.doc)
    grown_at = len(console.doc)
    console.gen_at = gen_from
    console.generating = True
    console.gen_since = time.time()
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
            # the passage is still growing, so the vectors it can justify are
            # still changing: re-propose instead of steering with stale axes
            if len(console.doc) - grown_at > 220:
                grown_at = len(console.doc)
                _seed_vectors(console)
                await _safe_send(sock, {"type": "vectors", "vectors": [v.to_dict() for v in console.vectors]})
            if now - last_audit > 0.14:
                last_audit = now
                payload = auditor.audit(console, provider.note())
                await _safe_send(sock, {"type": "audit", **payload})
    except asyncio.CancelledError:
        await _safe_send(sock, {"type": "status", "generating": False})
        raise
    except Exception as exc:
        await _safe_send(sock, {"type": "error", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        console.generating = False
        console.elapsed = max(1e-3, time.perf_counter() - t0)
        _seed_vectors(console)
        payload = auditor.audit(console, provider.note())
        await _safe_send(sock, {"type": "audit", **payload})
        await _safe_send(sock, {"type": "status", "generating": False})
