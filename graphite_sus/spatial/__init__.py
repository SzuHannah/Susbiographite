"""Clean spatial TEA/LCA/sLCC workflow.

Spatial calculations reuse the same deterministic TEA/LCA core as notebooks 01/02.
Only location-dependent prices and energy-carrier emission factors are replaced.
"""
from .config import DEFAULT_SPATIAL_METHODS, CANON_IMPACTS, SpatialPaths
from .prices import StatePriceBook, load_state_electricity_prices, load_state_feedstock_prices
from .damage_costs import DamageCostLibrary

__all__ = [
    "DEFAULT_SPATIAL_METHODS", "CANON_IMPACTS", "SpatialPaths",
    "StatePriceBook", "load_state_electricity_prices", "load_state_feedstock_prices",
    "DamageCostLibrary",
]
