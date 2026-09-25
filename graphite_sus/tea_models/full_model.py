# -*- coding: utf-8 -*-
"""
full_model.py – IRR‑driven MSP calculator (v4.0‑US‑IDC, 2025‑10‑22)

This version aligns **Interest During Construction (IDC)** treatment with
US GAAP/US tax (IRC §263A(f)) practice:
  • IDC is **capitalized** into the asset basis (depreciable basis).
  • IDC appears as a **construction‑period cash outflow** ("idc_capitalized").
  • IDC is **funded by loan draws** (interest reserve), so debt at COD
    includes both base construction draws and IDC. (Can be adjusted
    if you prefer pro‑rata debt/equity funding.)

Other behavior unchanged unless noted. See inline comments marked "IDC".
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple, Any

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from scipy.optimize import brentq
import numpy_financial as npf

from .assumptions import TEAAssumptions, get_tea_assumptions

# ───────────────────────── helper utils ────────────────────────── #

def pmt(rate: float, nper: int, pv: float, fv: float = 0.0, when: int = 0) -> float:
    """Excel‑style PMT (negative ⇒ payment / outflow)."""
    if rate == 0:
        return -(pv + fv) / nper
    payment = npf.pmt(rate, nper, pv, fv, when='end' if when == 0 else 'begin')
    return payment  # numpy_financial returns negative for standard loan pv>0

# MACRS percentage tables --------------------------------------------------
MACRS: Dict[int, np.ndarray] = {
    7:  np.array([0.1429, 0.2449, 0.1749, 0.1249, 0.0893, 0.0892, 0.0893, 0.0446]),
    10: np.array([0.1000, 0.1800, 0.1440, 0.1152, 0.0922, 0.0737, 0.0655, 0.0655, 0.0656, 0.0655, 0.0328]),
    15: np.array([0.0500, 0.0950, 0.0855, 0.0770, 0.0693, 0.0623, 0.0590, 0.0590, 0.0591, 0.0590, 0.0590,
                   0.0590, 0.0591, 0.0590, 0.0590, 0.0295]),
}

def annual_depr(capex: float, scheme: str, years: int) -> np.ndarray:
    """
    Return a length-*years* vector of depreciation starting in operating Year 1.

    scheme examples:
      - "macrs7", "macrs10", "macrs15"
      - "straight20"  (generic straight-line over 20 years)
      - "straight{N}" (any positive integer N)
    """
    dep = np.zeros(years, dtype=float)
    s = scheme.strip().lower()
    if s.startswith("macrs"):
        macrs_years = int(s.replace("macrs", ""))
        tbl = MACRS.get(macrs_years)
        if tbl is None:
            raise ValueError(f"MACRS table for {macrs_years}-year property not defined.")
        n = min(years, len(tbl))
        dep[:n] = capex * tbl[:n]
        return dep
    if s.startswith("straight"):
        n = int(s.replace("straight", ""))
        if n <= 0:
            raise ValueError("Straight-line years must be > 0.")
        per_year = capex / n
        dep[:min(years, n)] = per_year
        return dep
    raise ValueError(f"Unknown depreciation scheme: {scheme}")


def safe_irr(cf: Sequence[float]) -> float:
    """Calculate IRR robustly, returning NaN on failure."""
    arr = np.asarray(cf, float)
    if not (np.any(arr > 0) and np.any(arr < 0)):
        return np.nan
    if np.all(arr == 0):
        return np.nan
    try:
        v = npf.irr(arr)
        if np.isfinite(v):
            return v
    except Exception:
        pass
    try:
        f = lambda r: np.sum(arr / (1 + r) ** np.arange(len(arr)))
        lo, hi = -0.99, 1.0
        if f(lo) * f(hi) >= 0:
            for _ in range(10):
                hi *= 2
                if f(lo) * f(hi) < 0:
                    break
            else:
                return np.nan
        return brentq(f, lo, hi)
    except (ValueError, RuntimeError):
        return np.nan

# locate NaN quickly -------------------------------------------------------

def first_nan(df: pd.DataFrame):
    for col in df.columns:
        if df[col].isna().any():
            first_nan_index = df.index[df[col].isna()][0]
            return col, first_nan_index
    return None, None

# ───────────────────── data containers ────────────────────── #

@dataclass
class OpEx:
    feedstock: float
    electricity: float
    other_variable: float
    labour: float
    maintenance: float
    insurance: float
    periodic: float = 0.0

    @property
    def variable(self) -> float:
        return self.feedstock + self.electricity + self.other_variable
    @property
    def fixed(self) -> float:
        return self.labour + self.maintenance + self.insurance + self.periodic
    @property
    def total(self) -> float:
        return self.variable + self.fixed

@dataclass
class CapExTotals:
    # Installed-capital scopes.  `isbl` and `osbl` are physical installed-cost
    # subtotals; neither includes project indirects.
    isbl: float
    osbl: float
    steam: float
    total_installed: float
    tdc: float
    # Backward-compatible name: `tic` here means total INDIRECT cost.
    tic: float
    fci: float
    wc: float
    land: float
    # NREL-style TCI excludes land; total_project_capital includes it.
    tci: float
    total_project_capital: float

@dataclass
class TEAResults:
    summary: Dict[str, float | str]
    cashflows: pd.DataFrame
    registry: Dict[str, object] = field(repr=False, default_factory=dict)
    breakdown: Dict[str, Any] = field(default_factory=dict)

# ───────────────────────── TEA model ────────────────────────── #

class TEAModel:
    """Techno-Economic Analysis Model for MSP calculation."""
    # Financing & Tax
    equity_pct: float = 0.40
    loan_interest: float = 0.08
    loan_term_yr: int = 10
    tax_rate: float = 0.21

    # Construction Spend Schedule (fraction of FCI spent relative to startup Year 0)
    construction_schedule: Dict[int, float] = {-2: 0.08, -1: 0.60, 0: 0.32}

    # Indirect Cost Factors (as fraction of Total Installed Equipment Cost)
    warehouse_pct: float = 0.04
    site_dev_pct: float = 0.09
    add_pipe_pct: float = 0.045
    field_exp_pct: float = 0.10
    home_office_pct: float = 0.10
    contingency_pct: float = 0.00
    other_pct: float = 0.10

    # Working Capital & Land
    working_capital_pct: float = 0.05
    land_needed_acre: float = 132
    cost_per_acre: float = 14000

    # Start-up Blend Factors (Year 1)
    start_up_time_yr: float = 0.25
    capacity_ramp: float = 0.50
    variable_ramp: float = 0.75
    fixed_ramp: float = 1.00

    analysis_horizon: int = 30

    def __init__(
        self,
        xl_path: Optional[Path] = None,
        loss_carry_forward: bool = True,
        assumptions: str | TEAAssumptions = "literature_hybrid",
    ):
        self.assumptions = get_tea_assumptions(assumptions)
        # Expose the profile through the historical attribute names so the rest
        # of the cash-flow engine remains simple and inspectable.
        a = self.assumptions
        self.equity_pct = a.equity_pct
        self.loan_interest = a.loan_interest
        self.loan_term_yr = a.loan_term_yr
        self.tax_rate = a.tax_rate
        self.construction_schedule = a.construction_schedule_dict
        self.warehouse_pct = a.warehouse_pct
        self.site_dev_pct = a.site_dev_pct
        self.add_pipe_pct = a.add_pipe_pct
        self.field_exp_pct = a.field_exp_pct
        self.home_office_pct = a.home_office_pct
        self.contingency_pct = a.contingency_pct
        self.other_pct = a.other_pct
        self.working_capital_pct = a.working_capital_pct
        self.land_needed_acre = a.land_needed_acre
        self.cost_per_acre = a.cost_per_acre
        self.start_up_time_yr = a.start_up_time_yr
        self.capacity_ramp = a.capacity_ramp
        self.variable_ramp = a.variable_ramp
        self.fixed_ramp = a.fixed_ramp
        self.analysis_horizon = a.project_years

        self.wb = None
        if xl_path:
            try:
                self.wb = load_workbook(xl_path, data_only=True, keep_vba=False)
            except FileNotFoundError:
                print(f"Warning: Excel file not found at {xl_path}. Labour cost fallback will be used.")
        self.reg: Dict[str, object] = {}
        self.loss_carry_forward = loss_carry_forward

    def _capex_from_area(self, df: pd.DataFrame) -> CapExTotals:
        d = df.copy()
        d["cost"] = pd.to_numeric(d["cost"], errors="coerce").fillna(0.0)
        d["area_code_str"] = d["process_area"].astype(str).str.extract(r"A(\d+)", expand=False)
        d["area_code"] = pd.to_numeric(d["area_code_str"], errors="coerce")

        # Prefer an explicit workbook scope when available.  Otherwise use the
        # project convention agreed for the clean model: A800 steam/power, A900
        # wastewater, and A1000 cooling/utilities are OSBL; all other active
        # process areas are ISBL.  BC2's combined A900 WWT/steam row remains
        # wholly OSBL (no artificial split).
        if "capital_scope" in d.columns and d["capital_scope"].notna().any():
            scope = d["capital_scope"].astype(str).str.upper().str.strip()
            unknown = sorted(set(scope[d["cost"].ne(0)]) - {"ISBL", "OSBL"})
            if unknown:
                raise ValueError(f"Unknown capital_scope values: {unknown}")
        else:
            scope = pd.Series(
                np.where(d["area_code"].isin([800, 900, 1000]), "OSBL", "ISBL"),
                index=d.index,
            )

        isbl = float(d.loc[scope.eq("ISBL"), "cost"].sum())
        osbl = float(d.loc[scope.eq("OSBL"), "cost"].sum())
        total_inst = float(d["cost"].sum())
        if not np.isclose(isbl + osbl, total_inst, rtol=0, atol=1e-6):
            raise AssertionError("ISBL + OSBL does not equal total installed cost")
        steam = float(d.loc[d["area_code"].eq(800), "cost"].sum())

        a = self.assumptions
        direct_base = isbl if a.direct_adders_basis == "isbl" else total_inst
        direct_adders = direct_base * (a.warehouse_pct + a.site_dev_pct + a.add_pipe_pct)
        tdc = total_inst + direct_adders
        indirect_pct_sum = a.indirect_pct_total
        total_indirect = tdc * indirect_pct_sum
        fci = tdc + total_indirect

        wc = fci * a.working_capital_pct
        land = a.land_needed_acre * a.cost_per_acre
        tci = fci + wc
        total_project_capital = tci + land
        return CapExTotals(
            isbl=isbl, osbl=osbl, steam=steam, total_installed=total_inst,
            tdc=tdc, tic=total_indirect, fci=fci, wc=wc, land=land, tci=tci,
            total_project_capital=total_project_capital,
        )

    def _labour_cost(self, labour_df: Optional[pd.DataFrame]) -> float:
        if labour_df is None:
            if self.wb and "OPEX" in self.wb.sheetnames:
                ws = self.wb["OPEX"]
                labour_direct = ws["L114"].value or 0
                labour_indirect = ws["L115"].value or 0
                print("Warning: Using fallback labour costs from Excel sheet.")
                return float(labour_direct + labour_indirect)
            raise ValueError("Labour cost data unavailable (no DataFrame or Excel fallback).")
        labour_df = labour_df.fillna(0)
        burden = labour_df.get("labour_burden_pct", pd.Series([0.90])).iloc[0]
        salary_col = labour_df.get("annual_salary", labour_df.get("now_salary", 0))
        n_required_col = labour_df.get("n_required", 0)
        salaries = (salary_col * n_required_col).sum()
        return float(salaries * (1 + burden))

    def _split_var(self, streams: pd.DataFrame, prices: pd.DataFrame, hrs: float) -> Tuple[float, float]:
        if streams.empty or prices.empty:
            return 0.0, 0.0
        if "material_code" not in streams.columns or "material_code" not in prices.columns:
            raise ValueError("Missing 'material_code' column in streams or prices DataFrame.")
        m = streams.merge(prices, on="material_code", how="left")
        price_col = None
        if "unit_cost" in m.columns:
            price_col = "unit_cost"
        elif "price_$/kg" in m.columns:
            price_col = "price_$/kg"
        if price_col is None:
            raise ValueError("Missing price column ('unit_cost' or 'price_$/kg') in merged price data.")
        missing_price_mask = m[price_col].isna() & (m["mass_flow_kg_hr"] != 0)
        if missing_price_mask.any():
            missing_codes = m.loc[missing_price_mask, "material_code"].unique()
            raise ValueError(f"Missing prices for material codes: {list(missing_codes)}")
        m[price_col] = m[price_col].fillna(0)
        m["mass_flow_kg_hr"] = m["mass_flow_kg_hr"].fillna(0)
        is_feed = m.get("is_feedstock", False).astype(bool)
        is_byp  = m.get("is_byproduct", False).astype(bool)
        is_p    = m.get("is_product", False).astype(bool)
        is_other = ~(is_feed | is_byp | is_p)
        feed_cost = (m.loc[is_feed,  "mass_flow_kg_hr"] * m.loc[is_feed,  price_col] * hrs).sum()
        other_cost = (m.loc[is_other, "mass_flow_kg_hr"] * m.loc[is_other, price_col] * hrs).sum()
        return float(feed_cost), float(other_cost)

    def _split_var3(self,
                    streams: pd.DataFrame,
                    prices: pd.DataFrame,
                    hrs: float,
                    electricity_codes: Optional[Sequence[str]] = None
                ) -> Tuple[float, float, float]:
        """Return annual (feedstock, electricity, other-variable) cost.

        Native LCI units are validated against ``price_basis_unit`` whenever
        both are present.  ``flow_per_hr`` is preferred; the legacy
        ``mass_flow_kg_hr`` alias remains supported during migration.
        """
        if streams.empty or prices.empty:
            return 0.0, 0.0, 0.0
        if "material_code" not in streams.columns or "material_code" not in prices.columns:
            raise ValueError("Missing 'material_code' column in streams or prices DataFrame.")

        flow_col = "flow_per_hr" if "flow_per_hr" in streams.columns else "mass_flow_kg_hr"
        if flow_col not in streams.columns:
            raise ValueError("Streams require 'flow_per_hr' (preferred) or 'mass_flow_kg_hr'.")
        m = streams.merge(prices, on="material_code", how="left")
        price_col = next((c for c in ("unit_cost", "price_$/kg", "price", "cost") if c in m.columns), None)
        if price_col is None:
            raise ValueError("Missing a price column (e.g. 'unit_cost' or 'price_$/kg').")

        flowing = m[flow_col].fillna(0).ne(0)
        missing = m[price_col].isna() & flowing
        if missing.any():
            raise ValueError(f"Missing prices for: {m.loc[missing, 'material_code'].unique().tolist()}")

        if "flow_unit" in m.columns and "price_basis_unit" in m.columns:
            fu = m["flow_unit"].fillna("").astype(str).str.strip()
            pu = m["price_basis_unit"].fillna("").astype(str).str.strip()
            mismatch = flowing & fu.ne("") & pu.ne("") & fu.ne(pu)
            if mismatch.any():
                bad = m.loc[mismatch, ["material_code", "flow_unit", "price_basis_unit"]].drop_duplicates()
                raise ValueError("LCI-flow / TEA-price unit mismatch:\n" + bad.to_string(index=False))

        m[price_col] = m[price_col].fillna(0.0)
        m[flow_col] = m[flow_col].fillna(0.0)
        is_feed = m.get("is_feedstock", False).astype(bool)
        is_byp  = m.get("is_byproduct", False).astype(bool)
        is_prod = m.get("is_product", False).astype(bool)
        code = m["material_code"].astype(str).str.lower()
        if electricity_codes:
            elec_set = {c.lower() for c in electricity_codes}
            is_elec = code.isin(elec_set)
        else:
            is_elec = code.str.contains("electric", regex=False)
        is_other = ~(is_feed | is_byp | is_prod | is_elec)

        feed_cost = (m.loc[is_feed, flow_col] * m.loc[is_feed, price_col] * hrs).sum()
        elec_cost = (m.loc[is_elec, flow_col] * m.loc[is_elec, price_col] * hrs).sum()
        oth_cost  = (m.loc[is_other, flow_col] * m.loc[is_other, price_col] * hrs).sum()
        return float(feed_cost), float(elec_cost), float(oth_cost)


    def _byproduct_revenue(self, streams: pd.DataFrame, prices: pd.DataFrame, hrs: float) -> float:
        if streams.empty or prices.empty:
            return 0.0
        if "material_code" not in streams.columns or "material_code" not in prices.columns:
            raise ValueError("Missing 'material_code' column in streams or prices DataFrame.")
        flow_col = "flow_per_hr" if "flow_per_hr" in streams.columns else "mass_flow_kg_hr"
        m = streams.merge(prices, on="material_code", how="left")
        price_col = "unit_cost" if "unit_cost" in m.columns else ("price_$/kg" if "price_$/kg" in m.columns else None)
        if price_col is None:
            raise ValueError("Missing price column ('unit_cost' or 'price_$/kg') for byproduct revenue.")
        is_byp = m.get("is_byproduct", False).astype(bool)
        is_output = m[flow_col].fillna(0) > 0
        byp_mask = is_byp & is_output
        missing_price_mask = m[price_col].isna() & byp_mask
        if missing_price_mask.any():
            missing_codes = m.loc[missing_price_mask, "material_code"].unique()
            raise ValueError(f"Missing prices for byproduct material codes: {list(missing_codes)}")
        if "flow_unit" in m.columns and "price_basis_unit" in m.columns:
            fu = m["flow_unit"].fillna("").astype(str).str.strip()
            pu = m["price_basis_unit"].fillna("").astype(str).str.strip()
            mismatch = byp_mask & fu.ne("") & pu.ne("") & fu.ne(pu)
            if mismatch.any():
                bad = m.loc[mismatch, ["material_code", "flow_unit", "price_basis_unit"]].drop_duplicates()
                raise ValueError("Byproduct-flow / price unit mismatch:\n" + bad.to_string(index=False))
        rev = (m.loc[byp_mask, flow_col].fillna(0) * m.loc[byp_mask, price_col].fillna(0) * hrs).sum()
        return float(rev)

    # -----------------------------------------------------------------------
    def run(
        self,
        *,
        streams_df: pd.DataFrame,
        prices_df: pd.DataFrame,
        capex_df: pd.DataFrame,
        labour_df: Optional[pd.DataFrame] = None,
        maintenance_pct_isbl: Optional[float] = None,
        insur_pct_fci: Optional[float] = None,
        operating_hours: Optional[float] = None,
        target_irr: Optional[float] = None,
        # OLD single-scheme remains for backward-compat; used if the two below are not supplied
        depreciation: Optional[str] = None,
        # NEW: per-asset schemes
        dep_general: Optional[str] = None,
        dep_steam:   Optional[str] = None,
        # NEW: per-run override of overall horizon (defaults to self.analysis_horizon)
        project_years: Optional[int] = None,
        debug_price: Optional[float] = None,
    ) -> TEAResults:
        """Runs the TEA model to find the MSP or evaluate a fixed price.

        IDC changes vs. prior version:
          • New CF column: idc_capitalized (negative in years < 1).
          • loan_draws in construction years include debt share of base capex
            **plus** IDC (assumed 100 % debt‑funded interest reserve).
          • Depreciation basis = FCI (base) + total capitalized IDC.
        """

        # ───── 1. CAPEX Calculation (base, excl. IDC) ─────────────────────
        a = self.assumptions
        operating_hours = float(a.operating_hours if operating_hours is None else operating_hours)
        target_irr = float(a.target_irr if target_irr is None else target_irr)

        cap = self._capex_from_area(capex_df)
        fci_base, tci, wc_total, land_total = cap.fci, cap.tci, cap.wc, cap.land
        self.reg['capex_details'] = cap
        self.reg['tea_assumptions'] = a
        if fci_base <= 0:
            raise ValueError("Fixed Capital Investment (FCI) must be positive.")

        # ───── 2. OPEX (Annual) ───────────────────────────────────────────
        feed_c, elec_c, oth_c = self._split_var3(streams_df, prices_df, operating_hours)
        labour_c = self._labour_cost(labour_df)

        # Backward-compatible explicit override: if the historical
        # maintenance_pct_isbl argument is supplied, honor its ISBL meaning.
        if maintenance_pct_isbl is not None:
            maint_pct = float(maintenance_pct_isbl)
            maint_basis = cap.isbl
            maint_basis_name = "isbl (explicit legacy override)"
        else:
            maint_pct = float(a.maintenance_pct)
            maint_basis_name = a.maintenance_basis
            maint_basis = {
                "isbl": cap.isbl,
                "total_installed": cap.total_installed,
                "fci": cap.fci,
            }[a.maintenance_basis]
        maint_c = maint_pct * maint_basis
        insurance_pct = float(
            a.insurance_property_tax_pct_fci if insur_pct_fci is None else insur_pct_fci
        )
        insur_c = insurance_pct * fci_base
        self.reg['fixed_opex_bases'] = {
            'maintenance_pct': maint_pct,
            'maintenance_basis': maint_basis_name,
            'maintenance_basis_usd': maint_basis,
            'insurance_property_tax_pct_fci': insurance_pct,
        }
        opex = OpEx(feed_c, elec_c, oth_c, labour_c, maint_c, insur_c, periodic=0.0)
        self.reg['opex_details'] = opex


        # ───── 3. Product Mass (Annual) ───────────────────────────────────
        product_flow_col = "flow_per_hr" if "flow_per_hr" in streams_df.columns else "mass_flow_kg_hr"
        product_mask = streams_df.get("is_product", False).astype(bool) & (streams_df[product_flow_col] > 0)
        prod_mass_yr = streams_df.loc[product_mask, product_flow_col].sum() * operating_hours
        if prod_mass_yr <= 0:
            raise ValueError("No stream flagged as 'is_product=True' with positive flow, or zero operating hours.")
        self.reg['annual_product_kg'] = prod_mass_yr

        # ───── 4. Cash Flow Table Setup ────────────────────────────────────
        horizon = int(project_years) if project_years is not None else int(self.analysis_horizon)
        constr_years = sorted([y for y in self.construction_schedule.keys() if y < 0]) or [-1]
        start_year = min(constr_years)
        end_year = horizon
        years = np.arange(start_year, end_year + 1)
        cf = pd.DataFrame(index=years, dtype=float)


        # Base construction uses (ex‑IDC)
        cf["construction"] = -np.array([self.construction_schedule.get(y, 0) * fci_base for y in years])
        # Land and WC
        cf["land"] = 0.0
        cf.loc[start_year, "land"] = -land_total
        cf["working_capital"] = 0.0
        cf.loc[0, "working_capital"] = -wc_total
        cf.loc[end_year, "working_capital"] += wc_total
        cf.loc[end_year, "land"] += land_total

        # Financing lines
        debt_share = 1.0 - self.equity_pct
        cf["loan_draws"] = 0.0
        cf["loan_principal_pmt"] = 0.0
        cf["loan_interest_pmt"] = 0.0

        # NEW: IDC capitalized line (negative uses during construction)
        cf["idc_capitalized"] = 0.0

        # ── 4.2 Construction‑period draws + IDC (capitalized) ─────────────
        outstanding_principal = 0.0
        # iterate through construction & startup years (y < 1)
        for y in years:
            if y < 1:
                base_use = -cf.loc[y, "construction"]  # >0 magnitude of base capex spend
                debt_draw_for_base = debt_share * base_use
                # mid‑year interest convention on debt balance
                avg_balance_for_interest = outstanding_principal + 0.5 * debt_draw_for_base
                idc_y = self.loan_interest * avg_balance_for_interest

                # record capitalized IDC as a **use** in the construction year
                cf.loc[y, "idc_capitalized"] = -idc_y

                # assume IDC is **100 % debt‑funded** via interest reserve
                loan_draw_y = debt_draw_for_base + idc_y
                cf.loc[y, "loan_draws"] = loan_draw_y

                # update outstanding principal at EOY
                outstanding_principal += loan_draw_y

        # opening loan at Year 1 equals cumulative construction‑period draws (incl. IDC)
        total_debt_drawn = outstanding_principal

        # ── 4.3 Operating‑period amortization ─────────────────────────────
        if total_debt_drawn > 0 and self.loan_term_yr > 0:
            try:
                annual_payment = npf.pmt(self.loan_interest, self.loan_term_yr, total_debt_drawn)
                if annual_payment > 0:
                    annual_payment = -annual_payment
            except ValueError:
                print(
                    f"Warning: Could not calc loan payment for rate={self.loan_interest}, "
                    f"term={self.loan_term_yr}, pv={total_debt_drawn}. Setting to 0."
                )
                annual_payment = 0.0

            current_loan_balance = total_debt_drawn
            for y in years:
                if 1 <= y <= self.loan_term_yr:
                    if current_loan_balance > 1e-6:
                        interest_payment = -(current_loan_balance * self.loan_interest)
                        principal_payment = annual_payment - interest_payment
                        if principal_payment < -current_loan_balance:
                            principal_payment = -current_loan_balance
                        cf.loc[y, "loan_interest_pmt"] = interest_payment
                        cf.loc[y, "loan_principal_pmt"] = principal_payment
                        current_loan_balance += principal_payment
                    else:
                        cf.loc[y:, ["loan_interest_pmt", "loan_principal_pmt"]] = 0.0
                        break
            if 1 <= self.loan_term_yr <= end_year and abs(current_loan_balance) > 1e-6:
                cf.loc[self.loan_term_yr, "loan_principal_pmt"] -= current_loan_balance

        # ── 4.4 Depreciation (on base FCI + **capitalized IDC**) ───────────
        total_idc_cap = float((-cf.loc[years < 1, "idc_capitalized"]).sum())

        # Split base FCI into "steam" vs "general" using installed-cost shares
        steam_share_inst = (cap.steam / cap.total_installed) if cap.total_installed > 0 else 0.0
        steam_fci_base   = fci_base * steam_share_inst
        gen_fci_base     = fci_base - steam_fci_base

        # Allocate capitalized IDC proportionally
        steam_idc = total_idc_cap * steam_share_inst
        gen_idc   = total_idc_cap - steam_idc

        # Depreciable bases
        steam_basis = steam_fci_base + steam_idc
        gen_basis   = gen_fci_base   + gen_idc

        # Choose schemes (fallback: if explicit per-asset not given, use 'depreciation' or defaults)
        scheme_general = dep_general or depreciation or a.dep_general
        scheme_steam   = dep_steam   or depreciation or a.dep_steam

        # Build schedules; they are length = overall project life; zero after the asset life ends
        dep_general_vec = annual_depr(gen_basis,   scheme_general, horizon)
        dep_steam_vec   = annual_depr(steam_basis, scheme_steam,   horizon)

        cf["depreciation"] = 0.0
        oper_mask = (years >= 1) & (years <= horizon)
        # shift schedules to start in Year 1 of ops
        cf.loc[oper_mask, "depreciation"] = (dep_general_vec + dep_steam_vec)[: oper_mask.sum()]

        # keep these for reporting
        self.reg["depr_details"] = {
            "steam_share_installed": steam_share_inst,
            "steam_basis_usd": steam_basis,
            "general_basis_usd": gen_basis,
            "scheme_steam": scheme_steam,
            "scheme_general": scheme_general,
        }

        depreciable_basis = steam_basis + gen_basis
        # ── 4.5 Operating Costs & Revenues ────────────────────────────────
        su_dur = self.start_up_time_yr
        def startup_blend(ramp_factor: float) -> float:
            return ramp_factor * su_dur + (1.0 - su_dur)

        cf[["feed_cost", "elec_cost", "other_var_cost", "fixed_cost"]] = 0.0

        # Year 1 (startup blends)
        cf.loc[1, "feed_cost"]      = -opex.feedstock   * startup_blend(self.variable_ramp)
        cf.loc[1, "elec_cost"]      = -opex.electricity * startup_blend(self.variable_ramp)
        cf.loc[1, "other_var_cost"] = -opex.other_variable * startup_blend(self.variable_ramp)
        cf.loc[1, "fixed_cost"]     = -opex.fixed       * startup_blend(self.fixed_ramp)

        # Year 2+
        steady_state_mask = years >= 2
        cf.loc[steady_state_mask, "feed_cost"]      = -opex.feedstock
        cf.loc[steady_state_mask, "elec_cost"]      = -opex.electricity
        cf.loc[steady_state_mask, "other_var_cost"] = -opex.other_variable
        cf.loc[steady_state_mask, "fixed_cost"]     = -opex.fixed


        cf["prod_rev"], cf["byprod_rev"] = 0.0, 0.0
        byp_rev_annual = self._byproduct_revenue(streams_df, prices_df, operating_hours)
        cf.loc[1, "byprod_rev"] = byp_rev_annual * startup_blend(self.capacity_ramp)
        cf.loc[steady_state_mask, "byprod_rev"] = byp_rev_annual

        cf = cf.fillna(0.0)

        # ── 4.6 Derived CF (tax, net CF) ──────────────────────────────────
        def apply_revenue(price: float):
            cf.loc[1, "prod_rev"] = price * prod_mass_yr * startup_blend(self.capacity_ramp)
            cf.loc[steady_state_mask, "prod_rev"] = price * prod_mass_yr

        def recompute_derived_cf():
            cf["total_revenue"] = cf["prod_rev"] + cf["byprod_rev"]
            cf["ebitda"] = cf["total_revenue"] + cf["feed_cost"] + cf["elec_cost"] + cf["other_var_cost"] + cf["fixed_cost"]
            cf["ebit"] = cf["ebitda"] - cf["depreciation"]
            cf["ebt"] = cf["ebit"] + cf["loan_interest_pmt"]  # operating interest only

            if self.loss_carry_forward:
                nol_balance = 0.0
                taxes = []
                for _, ebt in cf["ebt"].items():
                    if ebt > 0:
                        usable_nol = min(nol_balance, 0.80 * ebt)
                        taxable_income = ebt - usable_nol
                        nol_balance -= usable_nol
                    else:
                        taxable_income = 0.0
                        nol_balance += -ebt
                    taxes.append(-self.tax_rate * taxable_income)
                cf["tax"] = taxes
            else:
                cf["tax"] = np.where(cf["ebt"] > 0, -cf["ebt"] * self.tax_rate, 0.0)

            cash_flow_cols = [
                "construction", "idc_capitalized", "land", "working_capital",
                "loan_draws", "loan_principal_pmt", "loan_interest_pmt",
                "total_revenue", "feed_cost", "elec_cost","other_var_cost", "fixed_cost", "tax"
            ]
            cf["net_cash_flow"] = cf[cash_flow_cols].sum(axis=1)

        # ----- 5. Debug Mode -----
        if debug_price is not None:
            apply_revenue(debug_price)
            recompute_derived_cf()
            nan_col, nan_idx = first_nan(cf)
            note = (f"NaN in '{nan_col}' at year {nan_idx}" if nan_col else
                    "No NaN values detected in cash flow calculations.")
            debug_irr = safe_irr(cf["net_cash_flow"])
            summary = {
                "price_debug_usd_per_kg": debug_price,
                "irr_at_debug_price": debug_irr if not np.isnan(debug_irr) else "NaN/Error",
                "depreciable_basis_usd": depreciable_basis,
                "capitalized_idc_usd": total_idc_cap,
                "note": note,
            }
            return TEAResults(summary, cf.copy(), self.reg.copy())

        # ----- 6. MSP Root‑Finding -----
        def irr_objective(price: float) -> float:
            if price < 0:
                return np.inf
            try:
                apply_revenue(price)
                recompute_derived_cf()
                if cf['net_cash_flow'].isna().any():
                    return np.inf
                current_irr = safe_irr(cf["net_cash_flow"])
                if np.isnan(current_irr):
                    return -target_irr
                return current_irr - target_irr
            except Exception:
                return np.inf

        price_lo, price_hi, max_price = 1e-4, 10.0, 1e6
        try:
            fa, fb = irr_objective(price_lo), irr_objective(price_hi)
            it = 0
            while np.sign(fa) == np.sign(fb) and it < 15:
                price_hi *= 10
                if price_hi > max_price:
                    break
                fb = irr_objective(price_hi)
                it += 1
            if np.sign(fa) == np.sign(fb):
                irr_at_max = irr_objective(max_price)
                if np.isnan(irr_at_max) or irr_at_max < target_irr:
                    msg = (f"Unable to achieve target IRR of {target_irr:.1%} even at max price ({max_price:.2f}). ")
                else:
                    msg = (f"Unable to bracket MSP. Signs at {price_lo:.2f} and {price_hi:.2f} are the same ({fa:.3f}, {fb:.3f}). ")
                raise RuntimeError(msg)
            msp, result = brentq(irr_objective, price_lo, price_hi, xtol=1e-7, rtol=1e-7, full_output=True)
            if not result.converged:
                raise RuntimeError(f"MSP root-finding did not converge: {result.flag}")
        except RuntimeError as e:
            print(f"Error during MSP calculation: {e}")
            apply_revenue(0.0)
            recompute_derived_cf()
            summary = {"msp_usd_per_kg": "Error", "irr": "Error", "note": str(e),
                       "depreciable_basis_usd": depreciable_basis,
                       "capitalized_idc_usd": total_idc_cap}
            return TEAResults(summary, cf.copy(), self.reg.copy())
        except Exception as e:
            print(f"Unexpected error during MSP calculation: {e}")
            apply_revenue(0.0); recompute_derived_cf()
            summary = {"msp_usd_per_kg": "Error", "irr": "Error",
                       "note": f"Unexpected error: {e}",
                       "depreciable_basis_usd": depreciable_basis,
                       "capitalized_idc_usd": total_idc_cap}
            return TEAResults(summary, cf.copy(), self.reg.copy())

        # ----- 7. Final Calculation & Summary -----------------------------
        apply_revenue(msp)
        recompute_derived_cf()
        realised_irr = safe_irr(cf["net_cash_flow"])
        nan_col_final, nan_idx_final = first_nan(cf)
        final_note = f"Target IRR={target_irr:.2%}, Achieved IRR={realised_irr:.2%}"
        if nan_col_final:
            final_note += f" | WARNING: NaN found in final CF: Col='{nan_col_final}', Year={nan_idx_final}"

        summary = {
            "msp_usd_per_kg": msp,
            "irr_calculated": realised_irr,
            "target_irr": target_irr,
            "annual_product_kg": prod_mass_yr,
            "annual_feedstock_cost": opex.feedstock,
            "annual_electricity_cost": opex.electricity,
            "annual_other_variable_cost": opex.other_variable,
            "annual_labour_cost": opex.labour,
            "annual_maintenance_cost": opex.maintenance,
            "annual_insurance_etc_cost": opex.insurance,
            "annual_fixed_cost": opex.fixed,
            "annual_total_opex": opex.total,
            "fci_usd (base_excl_IDC)": fci_base,
            "capitalized_idc_usd": total_idc_cap,
            "dep_basis_general_usd": gen_basis,
            "dep_basis_steam_usd":   steam_basis,
            "depreciable_basis_usd": depreciable_basis,
            "tci_usd_excl_land": tci,
            "land_usd": land_total,
            "total_project_capital_usd": cap.total_project_capital,
            "tea_profile": a.name,
            "note": final_note,
        }
        return TEAResults(summary, cf.copy(), self.reg.copy())

