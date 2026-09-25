#!/usr/bin/env python3
"""Run the exported biographite TEA/LCA with user-supplied background factors.

No Brightway or ecoinvent installation is required. Exact paper LCA reproduction
requires the paper factor bundle (not distributed in the public repository).
"""
from __future__ import annotations
import argparse, json, sys
from dataclasses import fields
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

# Allow direct execution from a source checkout without package installation.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

IMPACTS = ['climate change','acidification','eutrophication','ecotoxicity: freshwater','particulate matter formation','photochemical oxidant formation']


def _bool_series(s):
    if s.dtype==bool: return s
    out=s.astype(str).str.strip().str.lower().map({'true':True,'false':False,'1':True,'0':False})
    if out.isna().any(): raise ValueError(f'Cannot parse boolean values: {s[out.isna()].unique()[:5]}')
    return out.astype(bool)


def load_assumptions(path:Path):
    from graphite_sus.tea_models.assumptions import TEAAssumptions
    df=pd.read_csv(path); valid={f.name for f in fields(TEAAssumptions)}
    strings={'name','direct_adders_basis','maintenance_basis','dep_general','dep_steam'}; ints={'loan_term_yr','project_years'}
    kwargs={}; schedule=[]
    for r in df.itertuples(index=False):
        k=str(r.parameter); v=r.value
        if k.startswith('construction_fraction_year_'):
            schedule.append((int(k.rsplit('_',1)[1]),float(v))); continue
        if k not in valid: continue
        kwargs[k]=str(v) if k in strings else int(float(v)) if k in ints else float(v)
    if schedule: kwargs['construction_schedule']=tuple(sorted(schedule))
    return TEAAssumptions(**kwargs)


class ExportedTEA:
    def __init__(self,root:Path):
        from graphite_sus.tea_models.vector_model import VectorModel
        d=root/'data/tea'; self.model=VectorModel(assumptions=load_assumptions(d/'tea_financial_assumptions.csv'))
        self.streams=pd.read_csv(d/'tea_streams.csv'); self.prices=pd.read_csv(d/'tea_prices.csv'); self.capex=pd.read_csv(d/'tea_capex_inputs.csv'); self.labour=pd.read_csv(d/'tea_labour_inputs.csv')
        for c in ['is_feedstock','is_product','is_byproduct']:
            if c in self.streams: self.streams[c]=_bool_series(self.streams[c])
        self.cache={}
    @staticmethod
    def _subset(df,scenario):
        x=df.loc[df.scenario.eq(scenario)].copy(); return x.drop(columns=[c for c in ['scenario','pathway'] if c in x])
    def run(self,scenario,electricity=None,feedstock=None,*,electricity_usd_per_kwh=None,feedstock_usd_per_kg=None):
        if electricity_usd_per_kwh is not None: electricity=electricity_usd_per_kwh
        if feedstock_usd_per_kg is not None: feedstock=feedstock_usd_per_kg
        key=(scenario,electricity,feedstock)
        if key in self.cache:return self.cache[key]
        p=self._subset(self.prices,scenario)
        for code,val in [('electricity',electricity),('feedstock',feedstock)]:
            if val is not None:
                m=p.material_code.astype(str).eq(code)
                if m.sum()!=1: raise ValueError(f'{scenario}: expected one {code} price row')
                p.loc[m,'unit_cost']=float(val)
        s=self._subset(self.streams,scenario)
        s=s.drop(columns=[c for c in ['product_rate_kg_per_hr','quantity_per_kg_graphite','quantity_per_kg_graphite_unit'] if c in s])
        res=self.model.run_breakdown(streams_df=s,prices_df=p,capex_df=self._subset(self.capex,scenario),labour_df=self._subset(self.labour,scenario))
        self.cache[key]=(res,s); return res,s


def deterministic_tea(root:Path):
    tea=ExportedTEA(root); rows=[]
    for sc in ['s_c1','s_c2','s_o1','s_o2']:
        res,_=tea.run(sc); rows.append({'scenario':sc,'pathway':{'s_c1':'BC1','s_c2':'BC2','s_o1':'BO1','s_o2':'BO2'}[sc],**{k:res.summary[k] for k in ['msp_usd_per_kg','irr','fci','total_opex_annual','byproduct_revenue_annual'] if k in res.summary}})
    return pd.DataFrame(rows),tea


def load_factors(path:Path):
    f=pd.read_csv(path)
    req={'scenario','pathway','portable_mapping_key','impact_category','factor_value','factor_unit','include_in_lcia'}
    miss=req-set(f.columns)
    if miss: raise ValueError(f'Factor file missing columns: {sorted(miss)}')
    f=f.copy(); f['include_in_lcia']=_bool_series(f['include_in_lcia'])
    f['factor_value']=pd.to_numeric(f['factor_value'],errors='coerce')
    bad=f.loc[f.include_in_lcia & f.factor_value.isna()]
    if len(bad): raise ValueError(f'{len(bad)} included factor rows have blank/non-numeric factor_value')
    keys=['scenario','pathway','portable_mapping_key','impact_category']
    if f.duplicated(keys).any(): raise ValueError('Duplicate factor keys detected')
    return f


def deterministic_lca(root:Path,factor_file:Path):
    lci=pd.read_csv(root/'data/foreground_lci/lci_foreground_inventory.csv'); lci['include_in_lcia']=_bool_series(lci['include_in_lcia'])
    lci=lci.loc[lci.include_in_lcia].copy(); fac=load_factors(factor_file)
    keys=['scenario','pathway','portable_mapping_key']
    m=lci.merge(fac,on=keys,how='left',suffixes=('_lci','_factor'),validate='many_to_many')
    if m.factor_value.isna().any():
        bad=m.loc[m.factor_value.isna(),keys].drop_duplicates().head(10); raise ValueError('Missing factors after merge:\n'+bad.to_string(index=False))
    m['contribution']=pd.to_numeric(m.quantity_per_functional_unit)*pd.to_numeric(m.mass_allocation_fraction)*pd.to_numeric(m.factor_value)
    summary=m.groupby(['scenario','pathway','impact_category','impact_unit'],as_index=False).contribution.sum().rename(columns={'contribution':'value'})
    return summary,m


def load_regional(paths):
    if not paths:return pd.DataFrame()
    dfs=[]
    for p in paths:
        d=pd.read_csv(p); req={'carrier','region','impact_category','factor_value','source_unit'}; miss=req-set(d.columns)
        if miss: raise ValueError(f'Regional factor file {p} missing {sorted(miss)}')
        d=d.copy(); d['factor_value']=pd.to_numeric(d.factor_value,errors='coerce')
        if d.factor_value.isna().any(): raise ValueError(f'Regional factor file {p} contains blank factor_value')
        dfs.append(d)
    out=pd.concat(dfs,ignore_index=True)
    keys=['carrier','region','impact_category']
    if out.duplicated(keys).any(): raise ValueError('Duplicate regional carrier/region/impact rows')
    return out


def state_prices(root:Path):
    from graphite_sus.spatial.prices import load_state_electricity_prices,load_state_feedstock_prices,build_state_price_table
    e=load_state_electricity_prices(root/'data/prices/electricity_price_eia.xlsx',snapshot='2025-03-01',mode='snapshot')
    f=load_state_feedstock_prices(root/'data/prices/feedstock_price_eia.xlsx')
    return build_state_price_table(e,f)


def spatial_lca(root:Path,factor_file:Path,regional_paths,state_map_path:Path):
    from graphite_sus.spatial.emission_factors import scale_factor
    lci=pd.read_csv(root/'data/foreground_lci/lci_foreground_inventory.csv'); lci['include_in_lcia']=_bool_series(lci['include_in_lcia']); lci=lci.loc[lci.include_in_lcia].copy()
    fac=load_factors(factor_file)
    x=lci.merge(fac,on=['scenario','pathway','portable_mapping_key'],how='left',suffixes=('_lci','_factor'),validate='many_to_many')
    if x.factor_value.isna().any(): raise ValueError('Missing deterministic factors before spatial substitution')
    reg=load_regional(regional_paths); rlookup={(str(r.carrier),str(r.region),str(r.impact_category)):(float(r.factor_value),str(r.source_unit)) for r in reg.itertuples(index=False)}
    sm=pd.read_csv(state_map_path)
    req={'state','electricity_region','diesel_region','natural_gas_region'}
    if req-set(sm.columns): raise ValueError('State map must contain '+','.join(sorted(req)))
    rows=[]
    for sr in sm.sort_values('state').itertuples(index=False):
        regions={'electricity':str(sr.electricity_region),'diesel':str(sr.diesel_region),'natural_gas':str(sr.natural_gas_region)}
        for sc in sorted(x.scenario.unique()):
            z=x.loc[x.scenario.eq(sc)].copy(); z['state_factor']=z.factor_value.astype(float)
            for idx,r in z.iterrows():
                material=str(r.get('material_code','')).strip().lower(); provider=str(r.get('provider_or_flow_name_lci',r.get('provider_or_flow_name',''))).lower(); impact=str(r.impact_category)
                carrier=None
                if material=='electricity' or 'electricity' in provider: carrier='electricity'
                elif material=='diesel' or 'diesel' in provider: carrier='diesel'
                elif material in {'natural gas','ng'} or 'natural gas' in provider: carrier='natural_gas'
                if carrier:
                    key=(carrier,regions[carrier],impact)
                    if key not in rlookup: raise KeyError(f'Missing regional factor {key}')
                    v,source_unit=rlookup[key]; provider_unit=str(r.get('flow_unit_lci',r.get('flow_unit','')))
                    if carrier=='electricity': sf=scale_factor(source_unit,provider_unit)
                    elif carrier=='diesel': sf=scale_factor(source_unit,provider_unit,diesel_lhv=42.8)
                    else: sf=scale_factor(source_unit,provider_unit,ng_lhv=35.8)
                    z.at[idx,'state_factor']=v/sf
            z['contribution']=pd.to_numeric(z.quantity_per_functional_unit)*pd.to_numeric(z.mass_allocation_fraction)*pd.to_numeric(z.state_factor)
            sums=z.groupby('impact_category').contribution.sum(); row={'state':str(sr.state),'scenario':sc}; row.update({c:float(sums[c]) for c in IMPACTS}); rows.append(row)
    return pd.DataFrame(rows).sort_values(['state','scenario']).reset_index(drop=True)


def maxdiff(a,b,keys):
    m=a.merge(b,on=keys,how='outer',suffixes=('__new','__ref'),indicator=True)
    if not m._merge.eq('both').all(): raise AssertionError('Reference key mismatch')
    mx=0.; cols={}
    for c in a.columns:
        if c in keys or c not in b.columns:continue
        n=pd.to_numeric(m[c+'__new'],errors='coerce'); r=pd.to_numeric(m[c+'__ref'],errors='coerce')
        if (n.notna()|r.notna()).any():
            d=(n-r).abs(); d[(n.isna()&r.isna())]=0.; v=float(d.max(skipna=True)); cols[c]=v; mx=max(mx,v)
    return mx,cols


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    ap.add_argument('--factors',type=Path,help='Filled lcia factor file based on data/factor_templates/lcia_factors_template.csv')
    ap.add_argument('--regional-factors',type=Path,action='append',default=[],help='Regional factor file; repeat for multiple files')
    ap.add_argument('--state-map',type=Path,default=None)
    ap.add_argument('--output-dir',type=Path,default=None)
    ap.add_argument('--compare-paper',action='store_true')
    ap.add_argument('--skip-spatial',action='store_true')
    args=ap.parse_args(); root=args.root.resolve(); out=(args.output_dir or root/'outputs').resolve(); out.mkdir(parents=True,exist_ok=True)
    tea,tea_runner=deterministic_tea(root); tea.to_csv(out/'deterministic_tea.csv',index=False)
    report={'tea_rows':len(tea)}
    if args.compare_paper:
        ref=pd.read_csv(root/'reference/paper_results/deterministic_tea_summary.csv')
        # Compare MSP only because public summary column naming may differ across exports.
        keymap={'s_c1':'BC1','s_c2':'BC2','s_o1':'BO1','s_o2':'BO2'}
        vals=dict(zip(tea.pathway,tea.msp_usd_per_kg)); refcol='MSP ($/kg)' if 'MSP ($/kg)' in ref.columns else ('MSP' if 'MSP' in ref.columns else 'msp_usd_per_kg')
        report['tea_msp_max_abs_diff']=max(abs(vals[p]-float(ref.loc[ref.pathway.eq(p),refcol].iloc[0])) for p in vals)
    if args.factors:
        ds,flows=deterministic_lca(root,args.factors); ds.to_csv(out/'deterministic_lca.csv',index=False); flows.to_csv(out/'deterministic_lca_flow_contributions.csv',index=False)
        report['deterministic_lca_rows']=len(ds)
        if args.compare_paper:
            rr=pd.read_csv(root/'reference/paper_results/deterministic_lca.csv'); d,_=maxdiff(ds,rr,['scenario','pathway','impact_category','impact_unit']); report['deterministic_lca_max_abs_diff']=d
        if args.regional_factors and not args.skip_spatial:
            state_map=args.state_map or root/'data/spatial/state_source_mapping.csv'
            slca=spatial_lca(root,args.factors,args.regional_factors,state_map); slca.to_csv(out/'state_lca.csv',index=False); report['state_lca_rows']=len(slca)
            if args.compare_paper:
                rr=pd.read_csv(root/'reference/paper_results/state_lca.csv'); d,_=maxdiff(slca,rr,['state','scenario']); report['state_lca_max_abs_diff']=d
            # State TEA + central sLCC
            sp=state_prices(root); stea=[]
            for r in sp.itertuples(index=False):
                for sc in ['s_c1','s_c2','s_o1','s_o2']:
                    res,_=tea_runner.run(sc,float(r.electricity_usd_per_kwh),float(r.feedstock_usd_per_kg)); stea.append({'state':r.state,'scenario':sc,'MSP':float(res.summary['msp_usd_per_kg']),'electricity_price':float(r.electricity_usd_per_kwh),'feedstock_price':float(r.feedstock_usd_per_kg)})
            stea=pd.DataFrame(stea); stea.to_csv(out/'state_tea.csv',index=False)
            from graphite_sus.spatial.damage_costs import DamageCostLibrary
            from graphite_sus.spatial.slcc import state_slcc_table
            lib=DamageCostLibrary(root/'data/prices/damage_cost_reference.csv',root/'data/prices/cpi_reference.csv',root/'data/prices/damage_cost_schedule_overrides.csv',target_dollar_year=2025)
            damages=lib.schedules(years_ops=30); market=pd.read_csv(root/'data/market/graphite_impacts_long.csv')
            for mk in ['synthetic','natural']:
                raw=state_slcc_table(state_prices=sp,scenarios=['s_c1','s_c2','s_o1','s_o2'],tea_runner=tea_runner,lca_table=slca,market_df=market,damage_schedules=damages,market_kind=mk,social_rate=0.03,spc=1.10,damage_scenario='central')
                raw.to_csv(out/f'state_slcc_vs_{mk}.csv',index=False)
                if args.compare_paper:
                    rr=pd.read_csv(root/f'reference/paper_results/state_slcc_vs_{mk}.csv'); d,_=maxdiff(raw,rr,['state','scenario','impact_category']); report[f'state_slcc_{mk}_max_abs_diff']=d
    report['passed']=all(float(v)<=1e-9 for k,v in report.items() if k.endswith('max_abs_diff'))
    (out/'validation_report.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2)); return 0 if report['passed'] else 1
if __name__=='__main__': raise SystemExit(main())
