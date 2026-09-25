from pathlib import Path
from graphite_sus.electricity_reference import get_national_electricity_price,get_electricity_uncertainty_range
from graphite_sus.market_reference import get_market_range,get_market_mean
ROOT=Path(__file__).resolve().parents[1]
def test_electricity_reference():
 assert abs(get_national_electricity_price()-0.0862)<1e-12; assert get_electricity_uncertainty_range()==(0.0588,0.2215)
def test_market_reference():
 assert get_market_range('natural')==(2.8,4.5); assert abs(get_market_mean('natural')-3.65)<1e-12; assert get_market_range('synthetic')==(4.2,5.3); assert abs(get_market_mean('synthetic')-4.75)<1e-12
