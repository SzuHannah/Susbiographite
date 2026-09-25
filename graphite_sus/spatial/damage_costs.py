from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

@dataclass
class DamageCostLibrary:
    """Build audited annual damage-price schedules from data, not code literals.

    Reference table gives low/high source-year damage values. The central value is
    their midpoint. Values are CPI-rebased to ``target_dollar_year``. A category
    may use a constant or geometric annual schedule. Optional override rows can
    replace any individual impact/scenario/operation-year value, making annual
    damage schedules editable without touching Python.
    """
    reference_path:Path
    cpi_path:Path
    override_path:Path|None=None
    target_dollar_year:int=2025
    def __post_init__(self):
        self.reference_path=Path(self.reference_path); self.cpi_path=Path(self.cpi_path)
        self.override_path=None if self.override_path is None else Path(self.override_path)
        self.reference=pd.read_csv(self.reference_path)
        self.cpi=pd.read_csv(self.cpi_path)
        self._validate()
    def _validate(self):
        need={'impact_category','low','high','reference_dollar_year','lcia_unit','schedule_mode','annual_real_growth'}
        if not need.issubset(self.reference): raise ValueError(f'Damage reference missing {sorted(need-set(self.reference.columns))}')
        if self.reference.impact_category.duplicated().any(): raise ValueError('Duplicate damage-cost impact rows')
        for c in ['low','high','annual_real_growth']: self.reference[c]=pd.to_numeric(self.reference[c],errors='raise')
        self.reference['reference_dollar_year']=pd.to_numeric(self.reference.reference_dollar_year,errors='raise').astype(int)
        if (self.reference.low<0).any() or (self.reference.high<self.reference.low).any(): raise ValueError('Invalid damage-cost bounds')
        if not {'year','index'}.issubset(self.cpi): raise ValueError('CPI table requires year,index')
        self.cpi['year']=pd.to_numeric(self.cpi.year,errors='raise').astype(int); self.cpi['index']=pd.to_numeric(self.cpi['index'],errors='raise')
        if self.target_dollar_year not in set(self.cpi.year): raise KeyError(f'CPI missing target year {self.target_dollar_year}')
    def inflation_factor(self,from_year:int)->float:
        d=self.cpi.set_index('year')['index']; return float(d.loc[self.target_dollar_year]/d.loc[int(from_year)])
    def rebased_reference(self)->pd.DataFrame:
        d=self.reference.copy(); d['inflation_factor']=d.reference_dollar_year.map(self.inflation_factor)
        d['low_target']=d.low*d.inflation_factor; d['high_target']=d.high*d.inflation_factor; d['central_target']=0.5*(d.low_target+d.high_target)
        d['target_dollar_year']=self.target_dollar_year
        return d
    def schedules(self,*,years_ops:int=30)->dict[str,dict[str,np.ndarray]]:
        d=self.rebased_reference(); out={}
        t=np.arange(years_ops,dtype=float)
        for r in d.itertuples(index=False):
            per={}
            for scen in ('low','central','high'):
                base=float(getattr(r,f'{scen}_target'))
                if str(r.schedule_mode).lower()=='geometric': arr=base*(1+float(r.annual_real_growth))**t
                elif str(r.schedule_mode).lower()=='constant': arr=np.full(years_ops,base,float)
                else: raise ValueError(f'Unknown schedule_mode {r.schedule_mode!r} for {r.impact_category}')
                per[scen]=arr
            out[str(r.impact_category)]=per
        self._apply_overrides(out,years_ops)
        return out
    def _apply_overrides(self,out,years_ops):
        if self.override_path is None or not self.override_path.exists() or self.override_path.stat().st_size==0:return
        ov=pd.read_csv(self.override_path)
        if ov.empty:return
        need={'impact_category','scenario','operation_year','value'}
        if not need.issubset(ov): raise ValueError(f'Damage override missing {sorted(need-set(ov.columns))}')
        for r in ov.itertuples(index=False):
            cat=str(r.impact_category); yr=int(r.operation_year); val=float(r.value); scen=str(r.scenario).lower().strip()
            if hasattr(r, 'target_dollar_year') and not pd.isna(r.target_dollar_year) and int(r.target_dollar_year) != self.target_dollar_year:
                raise ValueError(f'Override for {cat} year {yr} is in ${int(r.target_dollar_year)}; expected ${self.target_dollar_year}')
            if cat not in out: raise KeyError(f'Unknown override impact {cat}')
            if not 1<=yr<=years_ops: raise ValueError(f'operation_year {yr} outside 1..{years_ops}')
            scenarios=('low','central','high') if scen in {'','all','*','nan'} else (scen,)
            for s in scenarios:
                if s not in out[cat]:raise KeyError(f'Unknown damage scenario {s}')
                out[cat][s][yr-1]=val
    def schedule_table(self,*,years_ops=30)->pd.DataFrame:
        sch=self.schedules(years_ops=years_ops); rows=[]
        units=self.reference.set_index('impact_category')['lcia_unit'].to_dict()
        for cat,per in sch.items():
            for scen,arr in per.items():
                for y,v in enumerate(arr,1): rows.append({'impact_category':cat,'scenario':scen,'operation_year':y,'value':float(v),'target_dollar_year':self.target_dollar_year,'lcia_unit':units[cat]})
        return pd.DataFrame(rows)
