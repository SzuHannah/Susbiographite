"""
tea_models  – small registry for interchangeable TEA solvers.

Usage
-----
from tea_models import get_model
model = get_model("full",loss_carry_forward=True)
result = model.run(streams_df=..., prices_df=..., capex_df=..., labour_df=...)
"""
from importlib import import_module
import pandas as pd

_REGISTRY = {
    "full":   "tea_models.full_model:TEAModel",
    "vector": "tea_models.vector_model:VectorModel",
}


def get_model(name: str = "full", *args, **kwargs):
    """Instantiate one of the registered TEA classes."""
    try:
        mod_path, cls_name = _REGISTRY[name].split(":")
    except KeyError as err:
        raise ValueError(
            f"Unknown TEA model '{name}'.  Choose from {list(_REGISTRY)}"
        ) from err
    cls = getattr(import_module(mod_path), cls_name)
    return cls(*args, **kwargs)

