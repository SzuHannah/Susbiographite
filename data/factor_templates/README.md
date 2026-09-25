# Emission-factor input templates

This repository deliberately separates the **foreground biographite inventory** from background emission factors.

## Deterministic/background factor file

Copy `lcia_factors_template.csv`, fill `factor_value`, and optionally fill the provenance columns. Rows are keyed by:

- `scenario`
- `pathway`
- `portable_mapping_key`
- `impact_category`

`factor_value` must be expressed in the listed `factor_unit`. Every row with `include_in_lcia=True` must have a numeric factor.

## Regional electricity factors

`regional_electricity_template.csv` contains the eight electricity regions used in the published state mapping and the six LCIA categories. Fill `factor_value` in the listed units. If you use a different regional scheme, you may also replace `data/spatial/state_source_mapping.csv` as long as the region labels match your factor table.

## Public fuel factors

`../public_factors/regional_fuel_factors.csv` contains the NETL/EPA-derived regional diesel and natural-gas factors used by the paper. These can be used directly or replaced.

## Exact paper factors

The public repository does **not** ship the executable ecoinvent-derived factor bundle. Licensed users can regenerate the paper electricity factors with the supplied regeneration script in the full lab archive, or use the private paper factor bundle maintained by the authors. The public code path was validated against that private bundle; see `validation/paper_replay_validation.json`.
