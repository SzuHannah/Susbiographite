"""Single source of truth for market graphite MSP reference ranges.

The numerical benchmarks live only in ``data/market_reference.csv``.  All
notebooks and plotting/post-processing modules should read them through this
module instead of embedding price literals.

This module intentionally has no Brightway dependency so it can be imported by
national deterministic, uncertainty, spatial, plotting, and test workflows.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd


DEFAULT_MARKET_REFERENCE_PATH = (
    Path(__file__).resolve().parent / "data" / "market_reference.csv"
)

_MARKET_ALIASES = {
    "natural": "natural",
    "natural graphite": "natural",
    "market_natural": "natural",
    "market natural": "natural",
    "synthetic": "synthetic",
    "synthetic graphite": "synthetic",
    "market_synthetic": "synthetic",
    "market synthetic": "synthetic",
    "market_current": "synthetic",
    "market current": "synthetic",
    "artificial": "synthetic",  # backward-compatible legacy terminology
    "artificial graphite": "synthetic",
}


def normalize_market_type(value: str) -> str:
    """Normalize legacy/current market labels to ``natural`` or ``synthetic``."""
    key = str(value).strip().lower()
    try:
        return _MARKET_ALIASES[key]
    except KeyError as exc:
        raise ValueError(
            f"Unknown graphite market type {value!r}; expected natural or synthetic"
        ) from exc


def load_market_references(path: str | Path | None = None) -> pd.DataFrame:
    """Load and validate the authoritative market MSP reference table.

    Required columns are ``market_type, quantity, lo, hi, mean, unit``.  The
    table must contain exactly one MSP row for natural graphite and one for
    synthetic graphite.  ``mean`` is explicit in the data file (rather than
    inferred in plotting code) so every workflow uses the same representative
    market price.
    """
    p = DEFAULT_MARKET_REFERENCE_PATH if path is None else Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Market-reference table not found: {p}")

    df = pd.read_csv(p)
    required = {"market_type", "quantity", "lo", "hi", "mean", "unit"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Market-reference table missing required columns: {sorted(missing)}"
        )

    out = df.copy()
    out["market_type"] = out["market_type"].map(normalize_market_type)
    out["quantity"] = out["quantity"].astype(str).str.strip().str.upper()
    out["unit"] = out["unit"].astype(str).str.strip()

    for col in ("lo", "hi", "mean"):
        out[col] = pd.to_numeric(out[col], errors="raise")

    out = out.loc[out["quantity"].eq("MSP")].copy()
    if len(out) != 2 or set(out["market_type"]) != {"natural", "synthetic"}:
        raise ValueError(
            "Market-reference table must contain exactly one MSP row each for "
            "natural and synthetic graphite"
        )
    if out["market_type"].duplicated().any():
        raise ValueError("Duplicate market_type rows in market-reference table")
    if (out["lo"] <= 0).any() or (out["hi"] <= out["lo"]).any():
        raise ValueError("Market-reference bounds must satisfy 0 < lo < hi")
    if not ((out["lo"] <= out["mean"]) & (out["mean"] <= out["hi"])).all():
        raise ValueError("Market-reference mean must lie inside [lo, hi]")
    if not out["unit"].eq("USD/kg").all():
        raise ValueError(
            "Market MSP references must use unit 'USD/kg'; "
            f"found {sorted(out['unit'].unique())}"
        )

    return out.reset_index(drop=True)


def get_market_range(kind: str, path: str | Path | None = None) -> tuple[float, float]:
    """Return ``(lo, hi)`` in USD/kg for natural or synthetic graphite."""
    key = normalize_market_type(kind)
    df = load_market_references(path)
    row = df.loc[df["market_type"].eq(key)].iloc[0]
    return float(row["lo"]), float(row["hi"])


def get_market_mean(kind: str, path: str | Path | None = None) -> float:
    """Return the representative market MSP in USD/kg."""
    key = normalize_market_type(kind)
    df = load_market_references(path)
    row = df.loc[df["market_type"].eq(key)].iloc[0]
    return float(row["mean"])


def get_market_ranges(path: str | Path | None = None) -> dict[str, tuple[float, float]]:
    """Return both authoritative market price bands."""
    df = load_market_references(path)
    return {
        str(r.market_type): (float(r.lo), float(r.hi))
        for r in df.itertuples(index=False)
    }


def get_market_means(path: str | Path | None = None) -> dict[str, float]:
    """Return both representative market MSPs."""
    df = load_market_references(path)
    return {
        str(r.market_type): float(r.mean)
        for r in df.itertuples(index=False)
    }


def market_reference_manifest(path: str | Path | None = None) -> dict[str, Mapping[str, object]]:
    """JSON-serializable market-reference snapshot for run manifests."""
    df = load_market_references(path)
    out: dict[str, Mapping[str, object]] = {}
    for row in df.to_dict(orient="records"):
        key = str(row.pop("market_type"))
        clean = {
            k: (None if pd.isna(v) else v)
            for k, v in row.items()
        }
        out[key] = clean
    return out


__all__ = [
    "DEFAULT_MARKET_REFERENCE_PATH",
    "normalize_market_type",
    "load_market_references",
    "get_market_range",
    "get_market_mean",
    "get_market_ranges",
    "get_market_means",
    "market_reference_manifest",
]
