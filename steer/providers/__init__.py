from .base import Provider
from .mock import MockProvider

__all__ = ["Provider", "MockProvider", "make_provider"]


def make_provider(kind: str = "mock", **kwargs) -> Provider:
    kind = (kind or "mock").lower()
    if kind == "mock":
        return MockProvider(seed=kwargs.get("seed"))
    if kind == "api":
        from .api import APIProvider
        return APIProvider(
            model=kwargs.get("model"),
            base_url=kwargs.get("base_url"),
            api_key=kwargs.get("api_key"),
        )
    if kind == "mlx":
        from .mlx_provider import MLXProvider
        return MLXProvider(
            model_id=kwargs.get("model") or "mlx-community/Qwen2.5-3B-Instruct-4bit",
            layer=kwargs.get("layer"),
            scale=kwargs.get("scale") or 6.0,
        )
    raise SystemExit(f"unknown provider {kind!r}: pick mock, api or mlx")
