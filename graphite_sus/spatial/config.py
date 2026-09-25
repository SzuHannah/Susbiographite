from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os

DEFAULT_SPATIAL_METHODS = (
    ('IPCC 2021','climate change','global warming potential (GWP100)'),
    ('TRACI v2.1','acidification','acidification potential (AP)'),
    ('TRACI v2.1','eutrophication','eutrophication potential'),
    ('TRACI v2.1','ecotoxicity: freshwater','ecotoxicity: freshwater'),
    ('TRACI v2.1','particulate matter formation','particulate matter formation potential (PMFP)'),
    ('TRACI v2.1','photochemical oxidant formation','maximum incremental reactivity (MIR)'),
)
CANON_IMPACTS = tuple(m[1] for m in DEFAULT_SPATIAL_METHODS)

_PACKAGE = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class SpatialPaths:
    """All spatial inputs in one explicit object.

    State-source mapping is bundled by default. Electricity, natural-gas, and
    diesel environmental factors default to project-owned regenerated files so
    notebooks 01--03 use one auditable LCIA convention. Environment variables
    can still override any spatial input path.
    """
    electricity_prices: Path = _PACKAGE / 'data/price/electricity_price_eia.xlsx'
    feedstock_prices: Path = _PACKAGE / 'data/price/feedstock_price_eia.xlsx'
    market_impacts: Path = _PACKAGE / 'data/market_impact/graphite_impacts_long.csv'
    state_geometries: Path = _PACKAGE / 'data/map/us-state-boundaries.geojson'
    damage_reference: Path = _PACKAGE / 'data/spatial/damage_cost_reference.csv'
    damage_overrides: Path = _PACKAGE / 'data/spatial/damage_cost_schedule_overrides.csv'
    cpi_reference: Path = _PACKAGE / 'data/spatial/cpi_reference.csv'
    state_source_map: Path = Path(os.environ.get(
        'GRAPHITE_STATE_SOURCE_MAP',
        str(_PACKAGE / 'data/spatial/states_energy_src.csv')))
    electricity_ef: Path = Path(os.environ.get(
        'GRAPHITE_ELECTRICITY_EF',
        str(_PACKAGE / 'data/derived/electricity_ipccar6_traci21_ecoregion.csv')))
    diesel_ef: Path = Path(os.environ.get(
        'GRAPHITE_DIESEL_EF',
        str(_PACKAGE / 'data/derived/diesel_ipccar6_traci21_padd.csv')))
    natural_gas_ef: Path = Path(os.environ.get(
        'GRAPHITE_NG_EF',
        str(_PACKAGE / 'data/derived/ng_ipccar6_traci21_basin.csv')))

    def audit(self):
        import pandas as pd
        rows=[]
        for name, p in self.__dict__.items():
            p=Path(p); rows.append({'input':name,'path':str(p),'exists':p.exists()})
        return pd.DataFrame(rows)
