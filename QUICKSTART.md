# Quick start

## A. Verify the public package

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r environment/requirements.txt
python scripts/validate_public.py
```

Expected result: `"passed": true` in `validation/public_validation.json`.

## B. Recompute the paper TEA

```bash
python scripts/run_custom_pipeline.py --compare-paper
```

This writes `outputs/deterministic_tea.csv` and checks the MSPs against the archived paper-reference table.

## C. Use your own emission factors

```bash
cp data/factor_templates/lcia_factors_template.csv my_factors.csv
```

Fill the `factor_value` column using the units already listed in `factor_unit`, then run:

```bash
python scripts/run_custom_pipeline.py --factors my_factors.csv
```

## D. Spatial LCA/sLCC

Fill `data/factor_templates/regional_electricity_template.csv` or supply a regional table using the same schema, then run:

```bash
python scripts/run_custom_pipeline.py \
  --factors my_factors.csv \
  --regional-factors data/public_factors/regional_fuel_factors.csv \
  --regional-factors my_electricity_factors.csv
```

The state mapping can be replaced with `--state-map your_state_mapping.csv`.

## E. Exact paper replay for licensed users

With `paper_lcia_factors.csv` and `paper_regional_electricity.csv` in a private factor directory:

```bash
python scripts/validate_public.py --private-factor-dir /path/to/private_factor_bundle
```

The release was tested this way before publication of the public folder.
