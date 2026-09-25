"""Central economic-input conventions used by all three clean workflows."""
from __future__ import annotations

from graphite_sus.electricity_reference import get_national_electricity_price

# Backward-compatible public constant.  The number itself lives only in
# data/electricity_reference.csv.
US_INDUSTRIAL_ELECTRICITY_2025_USD_PER_KWH = get_national_electricity_price()
ELECTRICITY_MATERIAL_CODE = "electricity"


def apply_national_electricity_baseline(
    prices_df,
    *,
    value: float | None = None,
):
    """Return a copy with the deterministic national electricity price replaced.

    By default the value is read from ``data/electricity_reference.csv``.
    The TEA workbook remains unchanged. Spatial workflows should replace this
    row with state-specific prices instead.
    """
    if value is None:
        value = get_national_electricity_price()

    out = prices_df.copy()
    if "material_code" not in out.columns:
        raise ValueError("prices_df is missing 'material_code'")
    mask = out["material_code"].astype(str).str.strip().eq(ELECTRICITY_MATERIAL_CODE)
    if mask.sum() != 1:
        raise ValueError(f"Expected exactly one electricity price row; found {int(mask.sum())}")
    if "unit_cost" not in out.columns:
        raise ValueError("prices_df is missing 'unit_cost'")
    out.loc[mask, "unit_cost"] = float(value)
    if "price_basis_unit" not in out.columns:
        out["price_basis_unit"] = None
    out.loc[mask, "price_basis_unit"] = "kWh"
    return out


__all__ = [
    "US_INDUSTRIAL_ELECTRICITY_2025_USD_PER_KWH",
    "ELECTRICITY_MATERIAL_CODE",
    "apply_national_electricity_baseline",
]
