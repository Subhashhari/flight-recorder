"""List-price-equivalent cost (the project itself runs on the free tier)."""

from __future__ import annotations

from flightrec.config import load_pricing, norm_model


def price_for(model: str) -> dict:
    prices = load_pricing()
    m = norm_model(model or "")
    if m in prices:
        return prices[m]
    keys = [k for k in prices if m.startswith(k)]
    return prices[max(keys, key=len)] if keys else {"input": 0.0, "output": 0.0}


def list_cost(model: str, tin: int, tout: int) -> float:
    p = price_for(model)
    return round(tin / 1e6 * float(p["input"]) + tout / 1e6 * float(p["output"]), 6)
