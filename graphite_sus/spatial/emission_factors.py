from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple
import re
import pandas as pd


def _slug_part(s:str)->str:
    s=str(s or '').replace('(','_').replace(')','_')
    return re.sub(r'_{2,}','_',re.sub(r'[^\w]+','_',s,flags=re.UNICODE)).strip('_')

def method_slug(method)->str:
    return '__'.join(_slug_part(p) for p in method) if isinstance(method,(tuple,list)) else _slug_part(method)

def provider_slug(name:str,location:str|None)->str:
    return f"{_slug_part(name)}__{str(location or 'GLO')}"

def _norm(s:str)->str:
    return re.sub(r'[^a-z0-9]+','',str(s or '').lower())

def _method_norm(s): return _norm(method_slug(s))

def _pick(df,cands):
    d={_norm(c):c for c in df.columns}
    for c in cands:
        if _norm(c) in d:return d[_norm(c)]
    raise ValueError(f'Required column not found; tried {cands}; have {list(df.columns)}')

# IMPORTANT: the historical external EF tables use carrier-specific LCIA labels.
# In particular, electricity uses particulate_matter_formation while NETL diesel
# and natural gas use Human_health_particulate_matter. Keep these mappings explicit
# and auditable; do not use fuzzy method guessing in publication calculations.
CARRIER_METHOD_ALIASES = {
    'electricity': {
        'climate change': ['climate change','global warming','Climate_change','Global_warming'],
        'acidification': ['acidification','Acidification'],
        'eutrophication': ['eutrophication','Eutrophication'],
        'ecotoxicity: freshwater': ['freshwater ecotoxicity','Freshwater_ecotoxicity','ecotoxicity freshwater'],
        'particulate matter formation': ['particulate matter formation','particulate_matter_formation','particulate formation','Particulate_formation'],
        'photochemical oxidant formation': ['smog formation','Smog_formation','smog','Smog'],
    },
    'diesel': {
        'climate change': ['climate change','global warming','Climate_change','Global_warming'],
        'acidification': ['acidification','Acidification'],
        'eutrophication': ['eutrophication','Eutrophication'],
        'ecotoxicity: freshwater': ['freshwater ecotoxicity','Freshwater_ecotoxicity','ecotoxicity freshwater'],
        'particulate matter formation': ['human health particulate matter','Human_health_particulate_matter','particulate matter formation','particulate_matter_formation'],
        'photochemical oxidant formation': ['smog formation','Smog_formation','smog','Smog'],
    },
    'natural_gas': {
        'climate change': ['climate change','global warming','Climate_change','Global_warming'],
        'acidification': ['acidification','Acidification'],
        'eutrophication': ['eutrophication','Eutrophication'],
        'ecotoxicity: freshwater': ['freshwater ecotoxicity','Freshwater_ecotoxicity','ecotoxicity freshwater'],
        'particulate matter formation': ['human health particulate matter','Human_health_particulate_matter','particulate matter formation','particulate_matter_formation'],
        'photochemical oxidant formation': ['smog formation','Smog_formation','smog','Smog'],
    },
}


def unit_token(u:str)->str:
    t=str(u or '').strip().lower()
    if t in {'kilowatt hour','kwh','kw·h','kw h'}: return 'kwh'
    if t in {'kilogram','kg'}: return 'kg'
    if t in {'cubic meter','m3','meter^3','m^3'}: return 'm3'
    if t in {'mj','megajoule','mega joule','mega-joule'}: return 'mj'
    return re.sub(r'\s+','',t)


def scale_factor(from_unit:str,to_unit:str,*,diesel_lhv=42.8,ng_lhv=35.8)->float:
    """Quantity conversion q_to = q_from * scale_factor(from,to)."""
    f,t=unit_token(from_unit),unit_token(to_unit)
    if f==t:return 1.0
    if f=='mj' and t=='kwh':return 1/3.6
    if f=='kwh' and t=='mj':return 3.6
    if f=='mj' and t=='kg':return 1/diesel_lhv
    if f=='kg' and t=='mj':return diesel_lhv
    if f=='mj' and t=='m3':return 1/ng_lhv
    if f=='m3' and t=='mj':return ng_lhv
    raise ValueError(f'Unsupported unit conversion {from_unit!r}->{to_unit!r}')


@dataclass
class StateSourceMap:
    by_state: pd.DataFrame

    @classmethod
    def from_csv(cls,path:str|Path,state_col='STUSPS',ele_col='ecoinvent_region',gas_col='top_basin_abbrv',padd_col='stage_code'):
        df=pd.read_csv(path)
        if not {state_col,ele_col,gas_col,padd_col}.issubset(df.columns):
            state_col=_pick(df,('STUSPS','state','abbr','code'))
            ele_col=_pick(df,('ecoinvent_region','ele_region','electricity_region','ecoregion','egrid_region'))
            gas_col=_pick(df,('top_basin_abbrv','ng_basin','gas_basin','basin'))
            padd_col=_pick(df,('stage_code','padd_region','padd','diesel_padd'))
        out=df.rename(columns={state_col:'state',ele_col:'ele_region',gas_col:'ng_basin',padd_col:'padd_region'})[['state','ele_region','ng_basin','padd_region']].dropna().copy()
        out['state']=out.state.astype(str).str.upper()
        if out.state.duplicated().any(): raise ValueError('Duplicate states in state-source map')
        return cls(out.set_index('state'))


@dataclass
class EFTables:
    electricity:pd.DataFrame
    diesel:pd.DataFrame
    natural_gas:pd.DataFrame

    @classmethod
    def from_csvs(cls,ele_csv,diesel_csv,ng_csv):
        def tidy(path,region_candidates):
            df=pd.read_csv(path)
            reg=_pick(df,region_candidates)
            rows=[]
            for col in df.columns:
                if col==reg: continue
                values=pd.to_numeric(df[col],errors='coerce')
                # Ignore columns with no numeric EF values (metadata/unit columns).
                if values.notna().sum()==0: continue
                ms=method_slug(col)
                rows.append(pd.DataFrame({
                    'region':df[reg].astype(str).str.strip(),
                    'method_slug':ms,
                    'factor':values,
                    'unit':'',
                }))
            if not rows: raise ValueError(f'No numeric EF columns found in {path}')
            out=pd.concat(rows,ignore_index=True)
            out['region_key']=out.region.map(_norm)
            out['method_key']=out.method_slug.map(_norm)
            return out
        return cls(
            tidy(ele_csv,('location','ecoregion','egrid','egrid_region','ele_region')),
            tidy(diesel_csv,('stage_code','padd','padd_region','diesel_padd')),
            tidy(ng_csv,('basin','ng_basin','gas_basin')),
        )

    def lookup(self,carrier:str,region:str,method_category:str)->Tuple[float,str]:
        tables={'electricity':self.electricity,'diesel':self.diesel,'natural_gas':self.natural_gas}
        if carrier not in tables: raise KeyError(f'Unknown carrier {carrier!r}; expected {list(tables)}')
        tab=tables[carrier]
        rkey=_norm(region)
        region_tab=tab.loc[tab.region_key.eq(rkey)].copy()
        if region_tab.empty:
            have=sorted(tab.region.dropna().astype(str).unique())
            raise KeyError(
                f"No EF region found: carrier={carrier!r}, region={region!r}. "
                f"Available regions={have}"
            )

        aliases=CARRIER_METHOD_ALIASES.get(carrier,{}).get(method_category,[method_category])
        candidates=[method_category,*aliases]
        for candidate in candidates:
            mk=_method_norm(candidate)
            hit=region_tab.loc[region_tab.method_key.eq(mk) & region_tab.factor.notna()]
            if not hit.empty:
                r=hit.iloc[0]
                return float(r.factor),str(r.unit or '')

        available=(region_tab.loc[region_tab.factor.notna(),['method_slug','method_key','factor']]
                   .drop_duplicates().sort_values('method_slug'))
        raise KeyError(
            "Spatial EF METHOD mismatch\n"
            f"carrier={carrier!r}\nregion={region!r}\nrequested impact={method_category!r}\n"
            f"aliases tried={aliases!r}\n\nAvailable methods:\n{available.to_string(index=False)}"
        )

    def audit_methods(self, carrier:str, region:str, requested_categories):
        rows=[]
        for cat in requested_categories:
            try:
                v,u=self.lookup(carrier,region,cat)
                rows.append({'carrier':carrier,'region':region,'impact_category':cat,'factor':v,'unit':u,'passed':True,'error':''})
            except Exception as e:
                rows.append({'carrier':carrier,'region':region,'impact_category':cat,'factor':None,'unit':'','passed':False,'error':str(e)})
        return pd.DataFrame(rows)

__all__=['StateSourceMap','EFTables','CARRIER_METHOD_ALIASES','method_slug','provider_slug','unit_token','scale_factor']