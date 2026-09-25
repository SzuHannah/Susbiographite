"""Central techno-economic assumptions for the graphite TEA.

The clean package exposes named profiles instead of scattering financial/capital
constants through notebooks.  `legacy` reproduces the current package's capital
arithmetic as closely as practical; `literature_hybrid` implements the agreed
literature-consistent capital basis while retaining project-specific choices
(21% federal income tax, 0.25-y startup, 1% FCI insurance/property tax).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Mapping

CapitalBase = Literal["total_installed", "isbl"]
MaintenanceBase = Literal["total_installed", "isbl", "fci"]


@dataclass(frozen=True)
class TEAAssumptions:
    name: str

    # Financing / tax / schedule
    target_irr: float = 0.10
    equity_pct: float = 0.40
    loan_interest: float = 0.08
    loan_term_yr: int = 10
    tax_rate: float = 0.21
    project_years: int = 30
    operating_hours: float = 8_000.0
    construction_schedule: tuple[tuple[int, float], ...] = ((-2, 0.08), (-1, 0.60), (0, 0.32))

    # Direct-capital adders
    direct_adders_basis: CapitalBase = "total_installed"
    warehouse_pct: float = 0.04
    site_dev_pct: float = 0.09
    add_pipe_pct: float = 0.045

    # Indirect-capital adders, all as fractions of TDC
    proratable_pct: float = 0.00
    field_exp_pct: float = 0.10
    home_office_pct: float = 0.10
    contingency_pct: float = 0.00
    other_pct: float = 0.10

    # Working capital / land
    working_capital_pct: float = 0.05
    land_needed_acre: float = 132.0
    cost_per_acre: float = 14_000.0

    # Fixed OPEX
    maintenance_pct: float = 0.03
    maintenance_basis: MaintenanceBase = "total_installed"
    insurance_property_tax_pct_fci: float = 0.01

    # Startup
    start_up_time_yr: float = 0.25
    capacity_ramp: float = 0.50
    variable_ramp: float = 0.75
    fixed_ramp: float = 1.00

    # Depreciation.  These preserve the currently documented implementation;
    # a separate MACRS-20 option can be selected explicitly once desired.
    dep_general: str = "macrs7"
    dep_steam: str = "straight20"

    @property
    def construction_schedule_dict(self) -> dict[int, float]:
        return dict(self.construction_schedule)

    @property
    def indirect_pct_total(self) -> float:
        return (
            self.proratable_pct
            + self.field_exp_pct
            + self.home_office_pct
            + self.contingency_pct
            + self.other_pct
        )

    def with_overrides(self, **kwargs) -> "TEAAssumptions":
        return replace(self, **kwargs)


LEGACY = TEAAssumptions(name="legacy")

# Literature-consistent but deliberately not identical to any one NREL report:
# * 4/9/4.5% direct adders applied to ISBL installed cost
# * 60% of TDC total indirect costs (10 + 10 + 20 + 10 + 10)
# * maintenance = 3% FCI
# * insurance + property tax = 1% FCI (project choice)
# * contemporary 21% federal income tax and current 0.25-y startup retained
LITERATURE_HYBRID = TEAAssumptions(
    name="literature_hybrid",
    direct_adders_basis="isbl",
    proratable_pct=0.10,
    field_exp_pct=0.10,
    home_office_pct=0.20,
    contingency_pct=0.10,
    other_pct=0.10,
    maintenance_basis="fci",
    maintenance_pct=0.03,
    insurance_property_tax_pct_fci=0.01,
)

PROFILES: Mapping[str, TEAAssumptions] = {
    LEGACY.name: LEGACY,
    LITERATURE_HYBRID.name: LITERATURE_HYBRID,
}


def get_tea_assumptions(profile: str | TEAAssumptions = "literature_hybrid") -> TEAAssumptions:
    if isinstance(profile, TEAAssumptions):
        return profile
    try:
        return PROFILES[str(profile)]
    except KeyError as exc:
        raise KeyError(f"Unknown TEA profile {profile!r}; choose from {sorted(PROFILES)}") from exc


__all__ = [
    "TEAAssumptions",
    "LEGACY",
    "LITERATURE_HYBRID",
    "PROFILES",
    "get_tea_assumptions",
]
