from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
def test_factor_template_schema():
 d=pd.read_csv(ROOT/'data/factor_templates/lcia_factors_template.csv'); req={'scenario','pathway','portable_mapping_key','impact_category','factor_value','factor_unit','include_in_lcia'}; assert req<=set(d.columns); assert len(d)==978
def test_public_fuels_complete():
 d=pd.read_csv(ROOT/'data/public_factors/regional_fuel_factors.csv'); assert set(d.carrier)=={'diesel','natural_gas'}; assert pd.to_numeric(d.factor_value,errors='coerce').notna().all(); assert d.impact_category.nunique()==6
def test_no_restricted_factor_files():
 banned={'lcia_factor_mapping_reference.csv','electricity_ipccar6_traci21_ecoregion.csv','electricity_ef_ecoinvent_reference.csv'}; found=[p for p in ROOT.rglob('*') if p.is_file() and p.name in banned]; assert not found
