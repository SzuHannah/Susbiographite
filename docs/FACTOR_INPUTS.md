# Emission-factor schemas

## 1. Deterministic/background factors

Start from `data/factor_templates/lcia_factors_template.csv`.

Key columns are `scenario`, `pathway`, `portable_mapping_key`, and `impact_category`. Enter a numeric `factor_value` in the exact unit given by `factor_unit`. The factor applies to one unit of the foreground exchange described by `flow_unit`.

All rows with `include_in_lcia=True` require a numeric value. The public file intentionally contains blanks because background databases differ across users.

## 2. Regional factors

Regional tables use these columns:

`carrier, region, impact_category, factor_value, source_unit, factor_unit, source, reference, notes`

The bundled `data/public_factors/regional_fuel_factors.csv` provides diesel and natural-gas factors per MJ. The electricity template is per kWh.

The runner converts regional fuel factors to the foreground units using the paper conventions:

- diesel lower heating value: 42.8 MJ/kg
- natural gas lower heating value: 35.8 MJ/m3

## 3. State mapping

`data/spatial/state_source_mapping.csv` has:

`state, electricity_region, diesel_region, natural_gas_region`

You can replace it if your regional factor system uses different regions.

## 4. Output units

The six paper impact categories are:

- climate change — kg CO2-eq
- acidification — kg SO2-eq
- eutrophication — kg N-eq
- freshwater ecotoxicity — CTUe
- particulate matter formation — PM2.5-eq
- photochemical oxidant formation — kg O3-eq

The functional unit is 1 kg graphite, cradle-to-gate, with the exported mass-allocation fractions.
