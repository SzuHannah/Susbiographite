from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import numpy as np
import pandas as pd

STATE_ABBREV = {
'Alabama':'AL','Alaska':'AK','Arizona':'AZ','Arkansas':'AR','California':'CA','Colorado':'CO',
'Connecticut':'CT','Delaware':'DE','Florida':'FL','Georgia':'GA','Hawaii':'HI','Idaho':'ID',
'Illinois':'IL','Indiana':'IN','Iowa':'IA','Kansas':'KS','Kentucky':'KY','Louisiana':'LA',
'Maine':'ME','Maryland':'MD','Massachusetts':'MA','Michigan':'MI','Minnesota':'MN',
'Mississippi':'MS','Missouri':'MO','Montana':'MT','Nebraska':'NE','Nevada':'NV',
'New Hampshire':'NH','New Jersey':'NJ','New Mexico':'NM','New York':'NY','North Carolina':'NC',
'North Dakota':'ND','Ohio':'OH','Oklahoma':'OK','Oregon':'OR','Pennsylvania':'PA',
'Rhode Island':'RI','South Carolina':'SC','South Dakota':'SD','Tennessee':'TN','Texas':'TX',
'Utah':'UT','Vermont':'VT','Virginia':'VA','Washington':'WA','West Virginia':'WV',
'Wisconsin':'WI','Wyoming':'WY','District of Columbia':'DC'}

@dataclass
class StatePriceBook:
    table: pd.DataFrame
    def __post_init__(self):
        if 'state' not in self.table or 'value' not in self.table:
            raise ValueError("StatePriceBook requires state,value columns")
        t=self.table.copy(); t['state']=t['state'].astype(str).str.upper()
        if t['state'].duplicated().any(): raise ValueError('Duplicate states in price book')
        self._p=t.set_index('state')
    def get(self,state:str)->float:
        return float(self._p.loc[str(state).upper(),'value'])
    @property
    def states(self): return tuple(self._p.index.astype(str))

def _dateish_columns(df:pd.DataFrame)->list[str]:
    out=[]
    for c in df.columns:
        try:
            pd.to_datetime(str(c), errors='raise'); out.append(c)
        except Exception: pass
    return out

def load_state_electricity_prices(path:str|Path, *, snapshot:str='2025-03-01', mode:str='snapshot')->pd.DataFrame:
    """Load industrial state electricity prices in USD/kWh.

    ``snapshot`` (clean default) selects one explicit EIA observation.
    ``legacy_mean`` reproduces the old notebook, which averaged every numeric
    price column (currently March-2024 and March-2025). It is retained only for
    audit/reconciliation and should not be the publication default.
    """
    df=pd.read_excel(path, sheet_name=0)
    if 'region_or_state' in df:
        df=df.loc[df['region_or_state'].astype(str).str.lower().eq('state')].copy()
    name_col='Region and State' if 'Region and State' in df else 'state_name'
    if name_col not in df: raise ValueError('Electricity workbook lacks state-name column')
    if mode=='snapshot':
        candidates={str(c):c for c in df.columns}
        if snapshot not in candidates:
            # normalize timestamps
            match=[c for c in df.columns if pd.to_datetime(c,errors='coerce')==pd.Timestamp(snapshot)]
            if not match: raise KeyError(f"Electricity snapshot {snapshot!r} not found; columns={list(df.columns)}")
            col=match[0]
        else: col=candidates[snapshot]
        cents=pd.to_numeric(df[col],errors='coerce')
    elif mode=='legacy_mean':
        cols=[c for c in df.select_dtypes(include=[np.number]).columns]
        if not cols: raise ValueError('No numeric electricity-price columns')
        cents=df[cols].mean(axis=1)
    else: raise ValueError("mode must be 'snapshot' or 'legacy_mean'")
    out=pd.DataFrame({'state_name':df[name_col].astype(str),'value':cents/100.0})
    out['state']=out['state_name'].map(STATE_ABBREV)
    out=out.dropna(subset=['state','value']).copy()
    out['source_mode']=mode; out['snapshot']=snapshot if mode=='snapshot' else 'mean_numeric_columns'
    return out[['state','value','state_name','source_mode','snapshot']].reset_index(drop=True)

def load_state_feedstock_prices(path:str|Path)->pd.DataFrame:
    xls=pd.ExcelFile(path)
    if '2025_feed_price' not in xls.sheet_names:
        raise ValueError("Clean spatial workflow requires '2025_feed_price' sheet with explicit USD/kg values")
    df=pd.read_excel(path,sheet_name='2025_feed_price')
    need={'StateCode','industrial_dollar_per_kg'}
    if not need.issubset(df): raise ValueError(f'Missing feedstock columns {sorted(need-set(df.columns))}')
    out=df.rename(columns={'StateCode':'state','industrial_dollar_per_kg':'value'}).copy()
    out['state']=out['state'].astype(str).str.upper()
    out['value']=pd.to_numeric(out['value'],errors='coerce')
    return out[['state','value']].dropna().drop_duplicates('state').reset_index(drop=True)

def build_state_price_table(electricity:pd.DataFrame, feedstock:pd.DataFrame)->pd.DataFrame:
    e=electricity[['state','value']].rename(columns={'value':'electricity_usd_per_kwh'})
    f=feedstock[['state','value']].rename(columns={'value':'feedstock_usd_per_kg'})
    return e.merge(f,on='state',how='inner',validate='one_to_one').sort_values('state').reset_index(drop=True)
