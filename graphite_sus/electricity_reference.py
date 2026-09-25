"""Single source of truth for national electricity price references.

Numerical values live only in ``data/electricity_reference.csv``.  National
TEA, uncertainty, plotting, tests, and run manifests should read through this
module instead of embedding electricity-price literals.  Spatial workflows
remain state-specific and should not replace their state prices with this
national reference.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd


DEFAULT_ELECTRICITY_REFERENCE_PATH = (
    Path(__file__).resolve().parent / "data" / "electricity_reference.csv"
)
DEFAULT_REFERENCE = "US_industrial"


def load_electricity_references(path: str | Path | None = None) -> pd.DataFrame:
    """Load and validate the authoritative electricity reference table."""
    p = DEFAULT_ELECTRICITY_REFERENCE_PATH if path is None else Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Electricity-reference table not found: {p}")

    out = pd.read_csv(p)
    required = {
        "reference", "baseline", "low", "high", "unit", "geography", "price_year"
    }
    missing = required - set(out.columns)
    if missing:
        raise ValueError(
            f"Electricity-reference table missing required columns: {sorted(missing)}"
        )

    out = out.copy()
    out["reference"] = out["reference"].astype(str).str.strip()
    out["unit"] = out["unit"].astype(str).str.strip()
    for col in ("baseline", "low", "high"):
        out[col] = pd.to_numeric(out[col], errors="raise")

    if out["reference"].duplicated().any():
        raise ValueError("Duplicate reference rows in electricity-reference table")
    if not out["unit"].eq("USD/kWh").all():
        raise ValueError(
            "Electricity references must use unit 'USD/kWh'; "
            f"found {sorted(out['unit'].unique())}"
        )
    if (out["low"] <= 0).any() or (out["high"] <= out["low"]).any():
        raise ValueError("Electricity bounds must satisfy 0 < low < high")
    if not ((out["low"] <= out["baseline"]) & (out["baseline"] <= out["high"])).all():
        raise ValueError("Electricity baseline must lie inside [low, high]")
    if DEFAULT_REFERENCE not in set(out["reference"]):
        raise ValueError(f"Missing required electricity reference {DEFAULT_REFERENCE!r}")

    return out.reset_index(drop=True)


def _row(reference: str = DEFAULT_REFERENCE, path: str | Path | None = None) -> pd.Series:
    df = load_electricity_references(path)
    match = df.loc[df["reference"].eq(str(reference).strip())]
    if len(match) != 1:
        raise ValueError(f"Expected exactly one electricity reference row for {reference!r}")
    return match.iloc[0]


def get_national_electricity_price(path: str | Path | None = None) -> float:
    """Return the deterministic U.S. industrial electricity price in USD/kWh."""
    return float(_row(path=path)["baseline"])


def get_electricity_uncertainty_range(path: str | Path | None = None) -> tuple[float, float]:
    """Return the approved national uncertainty/frontier price range in USD/kWh."""
    row = _row(path=path)
    return float(row["low"]), float(row["high"])


def electricity_reference_manifest(path: str | Path | None = None) -> dict[str, Mapping[str, object]]:
    """JSON-serializable electricity-reference snapshot for run manifests."""
    df = load_electricity_references(path)
    out: dict[str, Mapping[str, object]] = {}
    for row in df.to_dict(orient="records"):
        key = str(row.pop("reference"))
        out[key] = {k: (None if pd.isna(v) else v) for k, v in row.items()}
    return out


__all__ = [
    "DEFAULT_ELECTRICITY_REFERENCE_PATH",
    "DEFAULT_REFERENCE",
    "load_electricity_references",
    "get_national_electricity_price",
    "get_electricity_uncertainty_range",
    "electricity_reference_manifest",
]
