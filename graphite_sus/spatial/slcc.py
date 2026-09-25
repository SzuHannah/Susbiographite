from __future__ import annotations
from dataclasses import dataclass
from typing import Dict,Iterable,Mapping
from itertools import product
import numpy as np
import pandas as pd
from ..market_reference import get_market_mean,normalize_market_type

CANON_MAP={
'global warming':'climate change','climate change':'climate change','acidification':'acidification',
'eutrophication':'eutrophication','ecotoxicity':'ecotoxicity: freshwater','ecotoxicity: freshwater':'ecotoxicity: freshwater',
'respiratory effects':'particulate matter formation','particulate matter formation':'particulate matter formation',
'photochemical oxidant formation':'photochemical oxidant formation','smog':'photochemical oxidant formation'}

def pv_factor(years,r):
    y=np.asarray(years,float); return (1/(1+float(r)))**y

def extract_social_cost_vectors(res,*,include_idc=False,include_fixed=True):
    """Extract real-resource cash flows from the private TEA result.

    Financing, principal/interest, product revenue, and income tax are excluded as
    transfers. IDC is excluded by default because it is a financing cost. Operating
    costs and byproduct credits are included. This reproduces the active legacy
    sLCC convention while making the inclusion policy explicit.
    """
    cf=res.cashflows.copy(); yrs=cf.index.astype(int); msp=float(res.summary['msp_usd_per_kg'])
    if msp<=0: raise ValueError('Non-positive MSP cannot infer output')
    out=cf.loc[yrs>=1,'prod_rev'].astype(float).to_numpy()/msp
    def sumcols(cols):
        keep=[c for c in cols if c in cf]; return cf[keep].sum(axis=1) if keep else pd.Series(0.,index=cf.index)
    cons=sumcols(['feed_cost','elec_cost','other_var_cost']+(['fixed_cost'] if include_fixed else [])+['byprod_rev']).loc[yrs>=1].to_numpy(float)
    cap=['construction','land','working_capital','replacement_capex','decommissioning']+(['idc_capitalized'] if include_idc else [])
    inv=sumcols(cap).to_numpy(float)
    return {'year_index':np.asarray(yrs,int),'annual_output_kg':out,'annual_consumption_costs':cons,'annual_investment_costs':inv}

def social_production_cost_perkg(vectors,*,social_rate=0.03,spc=1.10,alpha_consumption_as_capital=0.0):
    years=np.asarray(vectors['year_index'],float); ops=years>=1; yops=years[ops]
    out=np.asarray(vectors['annual_output_kg'],float); cons=np.asarray(vectors['annual_consumption_costs'],float); inv=np.asarray(vectors['annual_investment_costs'],float)
    dout=pv_factor(yops,social_rate); dall=pv_factor(years,social_rate); pvout=float(np.sum(out*dout))
    if pvout<=0:raise ValueError('Non-positive PV(output)')
    pvcons=-float(np.sum(cons*dout)); pvinv=-float(np.sum(inv*dall))
    pvcons_adj=(1-alpha_consumption_as_capital)*pvcons+alpha_consumption_as_capital*spc*pvcons
    return (pvcons_adj+spc*pvinv)/pvout

def resolve_schedules(damage_schedules,categories,scenario='central',years_ops=30):
    out={}
    for cat in categories:
        if cat not in damage_schedules or scenario not in damage_schedules[cat]: raise KeyError(f'Missing damage schedule {cat}/{scenario}')
        a=np.asarray(damage_schedules[cat][scenario],float).ravel()
        if a.size!=years_ops: raise ValueError(f'{cat}/{scenario}: expected {years_ops} annual prices, got {a.size}')
        out[cat]=a
    return out

def environmental_damage_perkg(intensity,price_schedule,vectors,*,social_rate=0.03):
    years=np.asarray(vectors['year_index'],float); yops=years[years>=1]; out=np.asarray(vectors['annual_output_kg'],float)
    p=np.asarray(price_schedule,float); disc=pv_factor(yops,social_rate); pvout=float(np.sum(out*disc))
    return float(np.sum(float(intensity)*out*p*disc)/pvout)

def market_impact_means(market_df:pd.DataFrame,market_kind:str,categories:Iterable[str])->dict[str,float]:
    kind=normalize_market_type(market_kind); legacy_type='market_natural' if kind=='natural' else 'market_current'
    d=market_df.copy(); d['canon']=d.impact_category.astype(str).str.strip().str.lower().map(lambda x:CANON_MAP.get(x,x))
    vals={}
    for cat in categories:
        x=pd.to_numeric(d.loc[(d['type'].astype(str)==legacy_type)&(d.canon==cat),'value'],errors='coerce').dropna()
        if x.empty: raise KeyError(f'No market impact for {kind}/{cat}')
        vals[cat]=float(x.mean())
    return vals

def compare_state_to_market(*,res,green_intensities,market_intensities,damage_schedules,market_kind='synthetic',social_rate=0.03,spc=1.10,damage_scenario='central',include_idc=False):
    vec=extract_social_cost_vectors(res,include_idc=include_idc)
    private=social_production_cost_perkg(vec,social_rate=social_rate,spc=spc)
    market_price=get_market_mean(market_kind); rows=[]; dg=dm=0.0
    cats=sorted(set(green_intensities)&set(market_intensities)&set(damage_schedules))
    sch=resolve_schedules(damage_schedules,cats,damage_scenario,len(vec['annual_output_kg']))
    for cat in cats:
        g=environmental_damage_perkg(green_intensities[cat],sch[cat],vec,social_rate=social_rate)
        m=environmental_damage_perkg(market_intensities[cat],sch[cat],vec,social_rate=social_rate)
        market_slcc=market_price+m; green_slcc=private+g; delta=green_slcc-market_slcc
        rows.append({'impact_category':cat,'sLCC_private':private,'env_green_perkg':g,'env_market_perkg':m,'delta_env_perkg':g-m,'sLCC_green':green_slcc,'sLCC_market':market_slcc,'sLCC_green_vs_market_abs':delta,'sLCC_green_vs_market_pct':100*delta/market_slcc,'market_price':market_price})
        dg+=g; dm+=m
    market_slcc=market_price+dm; green_slcc=private+dg; delta=green_slcc-market_slcc
    rows.append({'impact_category':'_ALL_','sLCC_private':private,'env_green_perkg':dg,'env_market_perkg':dm,'delta_env_perkg':dg-dm,'sLCC_green':green_slcc,'sLCC_market':market_slcc,'sLCC_green_vs_market_abs':delta,'sLCC_green_vs_market_pct':100*delta/market_slcc,'market_price':market_price})
    return pd.DataFrame(rows)

def state_slcc_table(*,state_prices,scenarios,tea_runner,lca_table,market_df,damage_schedules,market_kind='synthetic',social_rate=0.03,spc=1.10,damage_scenario='central'):
    cats=[c for c in lca_table.columns if c not in {'state','scenario','MSP','electricity_price','feedstock_price'}]
    market=market_impact_means(market_df,market_kind,cats); rows=[]
    lidx=lca_table.set_index(['state','scenario'])
    for r in state_prices.itertuples(index=False):
        for sc in scenarios:
            res,_=tea_runner.run(sc,electricity_usd_per_kwh=r.electricity_usd_per_kwh,feedstock_usd_per_kg=r.feedstock_usd_per_kg)
            li=lidx.loc[(r.state,sc)]; green={c:float(li[c]) for c in cats}
            cmp=compare_state_to_market(res=res,green_intensities=green,market_intensities=market,damage_schedules=damage_schedules,market_kind=market_kind,social_rate=social_rate,spc=spc,damage_scenario=damage_scenario)
            cmp.insert(0,'scenario',sc); cmp.insert(0,'state',r.state); cmp['MSP_model']=float(res.summary['msp_usd_per_kg']); cmp['electricity_price']=float(r.electricity_usd_per_kwh); cmp['feedstock_price']=float(r.feedstock_usd_per_kg); cmp['market_type']=normalize_market_type(market_kind)
            cmp['social_rate']=float(social_rate); cmp['spc']=float(spc); cmp['damage_scenario']=str(damage_scenario)
            rows.append(cmp)
    return pd.concat(rows,ignore_index=True) if rows else pd.DataFrame()

def impact_average_full_slcc_pct(eff_df:pd.DataFrame)->pd.DataFrame:
    """Legacy Figure-6 average: mean of per-impact full-sLCC ratios.

    This is deliberately distinct from the additive ``_ALL_`` row. For each
    state/scenario, compute (green full sLCC / market full sLCC) for every
    canonical impact category, average those ratios, then express relative to 1.
    """
    d=eff_df.loc[~eff_df.impact_category.astype(str).str.startswith('_')].copy()
    d['ratio_full']=np.where(d.sLCC_market!=0,d.sLCC_green/d.sLCC_market,np.nan)
    group=[c for c in ['state','scenario','market_type','social_rate','spc','damage_scenario'] if c in d.columns]
    out=d.groupby(group,dropna=False).ratio_full.mean().reset_index(name='impact_avg_full_ratio')
    out['impact_avg_full_pct']=(out.impact_avg_full_ratio-1)*100
    out['impact_category']='_IMPACT_AVG_'
    return out


# -----------------------------------------------------------------------------
# sLCC valuation sensitivity
# -----------------------------------------------------------------------------
DEFAULT_SLCC_FACTOR_LEVELS = {
    'social_rate': (0.01, 0.05),
    'spc': (1.05, 1.20),
    'damage_scenario': ('low', 'high'),
}


def slcc_factorial_design(levels: Mapping[str, tuple] | None = None) -> pd.DataFrame:
    """Return the 2^3 full-factorial design described in Note S6.

    The three factors are social discounting rate, shadow price of capital, and
    environmental damage-cost scenario.  Each has exactly a low and a high
    level.  The central 3%/1.10/central case is the deterministic sLCC baseline,
    not an extra factorial level.
    """
    levels = dict(levels or DEFAULT_SLCC_FACTOR_LEVELS)
    required = ('social_rate', 'spc', 'damage_scenario')
    for name in required:
        if name not in levels or len(levels[name]) != 2:
            raise ValueError(f'{name} must have exactly two levels')
    rows=[]
    for sr, sp, ds in product(levels['social_rate'], levels['spc'], levels['damage_scenario']):
        rows.append({
            'social_rate': float(sr),
            'spc': float(sp),
            'damage_scenario': str(ds),
            'social_rate_level': 'low' if sr == levels['social_rate'][0] else 'high',
            'spc_level': 'low' if sp == levels['spc'][0] else 'high',
            'damage_scenario_level': 'low' if ds == levels['damage_scenario'][0] else 'high',
        })
    out=pd.DataFrame(rows)
    if len(out) != 8:
        raise AssertionError('Expected a 2^3 = 8-run factorial design')
    return out


def factorial_main_effects(
    impact_average_df: pd.DataFrame,
    *,
    response: str = 'impact_avg_full_pct',
    levels: Mapping[str, tuple] | None = None,
) -> pd.DataFrame:
    """State-wise high-minus-low main effects from a full 2^3 factorial design.

    For a factor, the response is averaged over all combinations of the other
    two factors at each level, then the low-level mean is subtracted from the
    high-level mean.  This is the standard factorial main effect and matches the
    SI description of asking how *increasing* each sLCC assumption changes the
    average sLCC difference across impact categories.
    """
    levels=dict(levels or DEFAULT_SLCC_FACTOR_LEVELS)
    d=impact_average_df.copy()
    need={'state','scenario','social_rate','spc','damage_scenario',response}
    missing=need-set(d.columns)
    if missing:
        raise ValueError(f'Impact-average sensitivity table missing {sorted(missing)}')
    rows=[]
    for (state,scenario),g in d.groupby(['state','scenario'],dropna=False):
        for factor in ('social_rate','spc','damage_scenario'):
            low,high=levels[factor]
            lo=pd.to_numeric(g.loc[g[factor].eq(low),response],errors='coerce').dropna()
            hi=pd.to_numeric(g.loc[g[factor].eq(high),response],errors='coerce').dropna()
            # In a 2^3 design, fixing one factor leaves 2^2 = 4 combinations.
            if len(lo)!=4 or len(hi)!=4:
                raise ValueError(
                    f'{state}/{scenario}/{factor}: expected 4 low and 4 high factorial rows; '
                    f'got {len(lo)} and {len(hi)}'
                )
            low_mean=float(lo.mean()); high_mean=float(hi.mean())
            rows.append({
                'state':state,
                'scenario':scenario,
                'factor':factor,
                'low_level':low,
                'high_level':high,
                'low_mean_impact_avg_full_pct':low_mean,
                'high_mean_impact_avg_full_pct':high_mean,
                'effect_pct_points':high_mean-low_mean,
            })
    return pd.DataFrame(rows)


def state_slcc_sensitivity_table(
    *,
    state_prices: pd.DataFrame,
    scenarios,
    tea_runner,
    lca_table: pd.DataFrame,
    market_df: pd.DataFrame,
    damage_schedules,
    market_kind: str = 'synthetic',
    levels: Mapping[str, tuple] | None = None,
):
    """Evaluate the 2^3 sLCC factorial for every state and requested pathway.

    TEA is run only once per state/pathway because social discounting, SPC, and
    damage valuation do not change the private TEA cash-flow solution.  The same
    TEA result is then re-valued under each societal-assumption combination.

    Returns ``(raw, impact_average, main_effects)``.
    """
    design=slcc_factorial_design(levels)
    cats=[c for c in lca_table.columns if c not in {'state','scenario','MSP','electricity_price','feedstock_price'}]
    market=market_impact_means(market_df,market_kind,cats)
    lidx=lca_table.set_index(['state','scenario'])
    rows=[]
    for r in state_prices.itertuples(index=False):
        for sc in scenarios:
            key=(r.state,sc)
            if key not in lidx.index:
                raise KeyError(f'Missing state LCA row for {key}')
            res,_=tea_runner.run(
                sc,
                electricity_usd_per_kwh=float(r.electricity_usd_per_kwh),
                feedstock_usd_per_kg=float(r.feedstock_usd_per_kg),
            )
            li=lidx.loc[key]
            green={c:float(li[c]) for c in cats}
            for drow in design.itertuples(index=False):
                cmp=compare_state_to_market(
                    res=res,
                    green_intensities=green,
                    market_intensities=market,
                    damage_schedules=damage_schedules,
                    market_kind=market_kind,
                    social_rate=float(drow.social_rate),
                    spc=float(drow.spc),
                    damage_scenario=str(drow.damage_scenario),
                )
                cmp.insert(0,'scenario',sc); cmp.insert(0,'state',r.state)
                cmp['MSP_model']=float(res.summary['msp_usd_per_kg'])
                cmp['electricity_price']=float(r.electricity_usd_per_kwh)
                cmp['feedstock_price']=float(r.feedstock_usd_per_kg)
                cmp['market_type']=normalize_market_type(market_kind)
                cmp['social_rate']=float(drow.social_rate)
                cmp['spc']=float(drow.spc)
                cmp['damage_scenario']=str(drow.damage_scenario)
                rows.append(cmp)
    raw=pd.concat(rows,ignore_index=True) if rows else pd.DataFrame()
    avg=impact_average_full_slcc_pct(raw) if not raw.empty else pd.DataFrame()
    effects=factorial_main_effects(avg,levels=levels) if not avg.empty else pd.DataFrame()
    return raw,avg,effects


def validate_slcc_sensitivity_coverage(
    raw: pd.DataFrame,
    *,
    expected_states: Iterable[str],
    scenarios=('s_c2','s_o2'),
) -> pd.DataFrame:
    """Return hard coverage diagnostics for the full spatial factorial."""
    states={str(x).upper() for x in expected_states}
    rows=[]
    for sc in scenarios:
        d=raw.loc[raw.scenario.eq(sc)]
        rows.append({'check':f'{sc}:states','expected':len(states),'actual':d.state.nunique(),'pass':set(d.state.astype(str).str.upper())==states})
        combos=d[['social_rate','spc','damage_scenario']].drop_duplicates()
        rows.append({'check':f'{sc}:factorial_combinations','expected':8,'actual':len(combos),'pass':len(combos)==8})
        per=d.groupby('state').apply(lambda x: len(x[['social_rate','spc','damage_scenario']].drop_duplicates()),include_groups=False)
        rows.append({'check':f'{sc}:8_combinations_per_state','expected':8,'actual':int(per.min()) if len(per) else 0,'pass':bool((per==8).all())})
    return pd.DataFrame(rows)
