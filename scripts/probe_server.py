"""Smoke the whole pipe: real server, real socket, real weights.

  .venv/bin/python scripts/probe_server.py http://127.0.0.1:7862
"""

from __future__ import annotations

import asyncio
import json
import sys

import websockets


async def main(url: str) -> None:
    ws_url = url.replace("http", "ws").rstrip("/") + "/ws"
    async with websockets.connect(ws_url, max_size=None) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 30))
        print("meta:", json.dumps(first.get("meta") or first.get("audit", {}).get("note")))
        await ws.send(json.dumps({"cmd": "generate", "tokens": 12}))

        text = ""
        chunks = 0
        audit = {}
        while True:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 90))
            except asyncio.TimeoutError:
                break
            if msg.get("type") == "delta":
                chunks += 1
                text += msg.get("text", "")
                if chunks >= 12:
                    break
            elif msg.get("type") == "audit":
                audit = msg
            elif msg.get("type") == "error":
                print("error:", msg.get("message"))
                break
        print(f"chunks: {chunks}")
        print("text:", text.strip()[:220])
        vecs = [(v["label"], v["pole"], round(v["realized"], 2)) for v in audit.get("vectors", [])]
        print("vectors:", vecs)


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7861"))
