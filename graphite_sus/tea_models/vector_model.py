"""Fast MSP solver that is algebraically aligned with :mod:`full_model`.

The parent :class:`TEAModel` is the single source of truth for CAPEX, fixed OPEX,
construction/IDC, debt, depreciation and tax schedules.  This class only
vectorises the operating-price root; every final cash-flow table is regenerated
by the parent at the solved price.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .full_model import TEAModel, TEAResults


class VectorModel(TEAModel):
    def _compose_breakdown(
        self,
        *,
        capex_df: pd.DataFrame,
        cap: Any,
        feed_c: float,
        elec_c: float,
        oth_c: float,
        labour_c: float,
        maint_c: float,
        insur_c: float,
        operating_hours: float,
    ) -> dict:
        area_capex = (
            capex_df.groupby("process_area", sort=False)["cost"].sum().to_dict()
            if "process_area" in capex_df.columns
            else {}
        )
        capex_section = {
            "isbl_installed": float(cap.isbl),
            "osbl_installed": float(cap.osbl),
            "total_installed": float(cap.total_installed),
            "tdc": float(cap.tdc),
            "total_indirect": float(cap.tic),
            "fci": float(cap.fci),
            "working_capital": float(cap.wc),
            "land": float(cap.land),
            "by_area": area_capex,
        }
        opex_section = {
            "variable": {
                "feedstock": float(feed_c),
                "electricity": float(elec_c),
                "other": float(oth_c),
            },
            "fixed": {
                "labour": float(labour_c),
                "maintenance": float(maint_c),
                "insurance_property_tax": float(insur_c),
            },
        }
        opex_section["total_annual"] = (
            sum(opex_section["variable"].values()) + sum(opex_section["fixed"].values())
        )
        return {"capex": capex_section, "opex": opex_section}

    @staticmethod
    def _npv_at_rate(cashflows: pd.Series, years: np.ndarray, rate: float) -> float:
        return float(np.sum(np.asarray(cashflows, float) / (1.0 + rate) ** np.asarray(years, float)))

    def _run_core(
        self,
        *,
        streams_df: pd.DataFrame,
        prices_df: pd.DataFrame,
        capex_df: pd.DataFrame,
        labour_df: pd.DataFrame | None = None,
        maintenance_pct_isbl: Optional[float] = None,
        insur_pct_fci: Optional[float] = None,
        operating_hours: Optional[float] = None,
        target_irr: Optional[float] = None,
        depreciation: Optional[str] = None,
        dep_general: Optional[str] = None,
        dep_steam: Optional[str] = None,
        project_years: Optional[int] = None,
        debug_price: float | None = None,
    ) -> tuple[TEAResults, dict]:
        a = self.assumptions
        operating_hours = float(a.operating_hours if operating_hours is None else operating_hours)
        target_irr = float(a.target_irr if target_irr is None else target_irr)
        dep_general = dep_general or (depreciation if depreciation else a.dep_general)
        dep_steam = dep_steam or (depreciation if depreciation else a.dep_steam)
        yrs = int(a.project_years if project_years is None else project_years)

        common = dict(
            streams_df=streams_df,
            prices_df=prices_df,
            capex_df=capex_df,
            labour_df=labour_df,
            maintenance_pct_isbl=maintenance_pct_isbl,
            insur_pct_fci=insur_pct_fci,
            operating_hours=operating_hours,
            target_irr=target_irr,
            dep_general=dep_general,
            dep_steam=dep_steam,
            project_years=yrs,
        )

        # Parent debug run is the authoritative construction/fixed-cost schedule.
        parent_zero = super().run(**common, debug_price=0.0)
        full_cf = parent_zero.cashflows
        cap = parent_zero.registry["capex_details"]
        opex = parent_zero.registry["opex_details"]

        flow_col = "flow_per_hr" if "flow_per_hr" in streams_df.columns else "mass_flow_kg_hr"
        prod_mask = streams_df.get("is_product", False).astype(bool) & streams_df[flow_col].gt(0)
        prod_mass_yr = float(streams_df.loc[prod_mask, flow_col].sum()) * operating_hours
        if prod_mass_yr <= 0:
            raise ValueError("No product stream with positive flow found")
        byp_rev_annual = self._byproduct_revenue(streams_df, prices_df, operating_hours)

        su = self.start_up_time_yr
        blend = lambda r: r * su + (1.0 - su)
        prod_vec = np.array([prod_mass_yr * blend(self.capacity_ramp)] + [prod_mass_yr] * (yrs - 1))
        byp_vec = np.array([byp_rev_annual * blend(self.capacity_ramp)] + [byp_rev_annual] * (yrs - 1))
        var_annual = opex.variable
        fixed_annual = opex.fixed
        var_vec = np.array([var_annual * blend(self.variable_ramp)] + [var_annual] * (yrs - 1))
        fixed_vec = np.array([fixed_annual * blend(self.fixed_ramp)] + [fixed_annual] * (yrs - 1))

        interest_vec = full_cf.loc[1:yrs, "loan_interest_pmt"].to_numpy(dtype=float)
        dep_vec = full_cf.loc[1:yrs, "depreciation"].to_numpy(dtype=float)
        years_full = full_cf.index.to_numpy(dtype=int)
        cap_cash_vec = full_cf[[
            "construction", "idc_capitalized", "land", "working_capital",
            "loan_draws", "loan_principal_pmt",
        ]].sum(axis=1).to_numpy(dtype=float)

        ops_disc = 1.0 / (1.0 + target_irr) ** np.arange(1, yrs + 1)
        cap_disc = 1.0 / (1.0 + target_irr) ** years_full

        def taxes_with_nol(taxable_before_nol: np.ndarray) -> np.ndarray:
            taxes = np.zeros_like(taxable_before_nol, dtype=float)
            nol = 0.0
            for i, ti in enumerate(taxable_before_nol):
                if ti > 0:
                    usable = min(nol, 0.80 * ti)
                    taxable = ti - usable
                    nol -= usable
                    taxes[i] = -self.tax_rate * taxable
                else:
                    nol += -ti
            return taxes

        def npv(price: float) -> float:
            ebt = price * prod_vec + byp_vec - var_vec - fixed_vec - dep_vec + interest_vec
            taxes = taxes_with_nol(ebt)
            ncf_ops = price * prod_vec + byp_vec - var_vec - fixed_vec + taxes + interest_vec
            return float(np.sum(ncf_ops * ops_disc) + np.sum(cap_cash_vec * cap_disc))

        ctx = dict(
            capex_df=capex_df,
            cap=cap,
            feed_c=opex.feedstock,
            elec_c=opex.electricity,
            oth_c=opex.other_variable,
            labour_c=opex.labour,
            maint_c=opex.maintenance,
            insur_c=opex.insurance,
            operating_hours=operating_hours,
        )

        def enrich_summary(summary: dict) -> dict:
            out = dict(summary)
            out.update({
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
                "fci_usd (base_excl_IDC)": cap.fci,
                "tci_usd_excl_land": cap.tci,
                "land_usd": cap.land,
                "total_project_capital_usd": cap.total_project_capital,
                "tea_profile": self.assumptions.name,
            })
            return out

        if debug_price is not None:
            parent_dbg = super().run(**common, debug_price=float(debug_price))
            summary = enrich_summary(parent_dbg.summary)
            summary["npv_at_target_irr_usd"] = self._npv_at_rate(
                parent_dbg.cashflows["net_cash_flow"],
                parent_dbg.cashflows.index.to_numpy(dtype=int),
                target_irr,
            )
            return TEAResults(summary, parent_dbg.cashflows, parent_dbg.registry), ctx

        lo, hi = 1e-4, 10.0
        flo, fhi = npv(lo), npv(hi)
        while np.sign(flo) == np.sign(fhi):
            hi *= 2.0
            if hi > 1e5:
                raise RuntimeError("Could not bracket MSP root up to 100,000 $/kg")
            fhi = npv(hi)
        msp = float(brentq(npv, lo, hi, xtol=1e-10, rtol=1e-10))

        parent_ok = super().run(**common, debug_price=msp)
        summary = enrich_summary(parent_ok.summary)
        summary["msp_usd_per_kg"] = msp
        summary["npv_at_target_irr_usd"] = self._npv_at_rate(
            parent_ok.cashflows["net_cash_flow"],
            parent_ok.cashflows.index.to_numpy(dtype=int),
            target_irr,
        )
        return TEAResults(summary, parent_ok.cashflows, parent_ok.registry), ctx

    def run(self, **kwargs) -> TEAResults:
        result, _ = self._run_core(**kwargs)
        return result

    def run_breakdown(self, **kwargs) -> TEAResults:
        result, ctx = self._run_core(**kwargs)
        result.breakdown = self._compose_breakdown(**ctx)
        return result
