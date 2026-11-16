"""steer — real-time vector steering console for live prose.

    python -m steer                     # offline corpus provider
    python -m steer --provider mlx      # real activation steering (Apple silicon)
    python -m steer --provider api      # any OpenAI-compatible endpoint
"""

from __future__ import annotations

import argparse
import threading
import webbrowser

from .corpus import SEEDS
from .providers import make_provider
from .server import create_app


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="steer", description="real-time vector steering console")
    p.add_argument("--provider", default="mock", choices=["mock", "api", "mlx"])
    p.add_argument("--model", default=None, help="model id (mlx or api)")
    p.add_argument("--seed", default="keeper", choices=list(SEEDS), help="opening passage")
    p.add_argument("--layer", type=float, default=None, help="steering layer as a fraction of depth")
    p.add_argument("--scale", type=float, default=0.10,
                   help="steering strength as a fraction of the layer's activation norm")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7860)
    p.add_argument("--no-open", action="store_true")
    args = p.parse_args(argv)

    provider = make_provider(
        args.provider, model=args.model, layer=args.layer, scale=args.scale, seed=None
    )
    app = create_app(provider, seed=args.seed)
    url = f"http://{args.host}:{args.port}/"

    if not args.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    import uvicorn

    print(f"steer · {provider.name} · {provider.note() or provider.model}")
    print(f"  {url}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
