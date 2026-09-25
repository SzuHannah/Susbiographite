# Susbiographite

This repository contains the publication-ready **foreground life-cycle inventory (LCI)**, **techno-economic analysis (TEA)** inputs, spatial price/mapping data, public regional fuel factors, executed reference notebooks, and a database-neutral interface for using **your own background emission factors**.

Paper: *A Spatially Explicit Societal Life Cycle Cost Framework for Sustainable Bio-Graphite Production in the United States*.

## What works without ecoinvent

- Recompute deterministic TEA/MSPs from exported streams, prices, CAPEX, labour, and financial assumptions.
- Read and reuse the foreground LCI for BC1, BC2, BO1, and BO2.
- Supply your own LCIA/background factors and calculate deterministic LCA.
- Supply regional electricity factors and combine them with the bundled public NETL/EPA diesel/natural-gas factors to reproduce or modify the spatial LCA and sLCC workflow.
- Inspect the seven executed publication notebooks and static paper reference outputs.

The public repository **does not distribute executable ecoinvent-derived factor tables**. Licensed users can regenerate them from ecoinvent 3.9.1, or obtain the private paper factor bundle from the authors subject to licensing. The public code path has been tested against that bundle and reproduces the archived paper outputs to floating-point tolerance; see `validation/paper_replay_validation.json`.

## Quick start

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r environment/requirements.txt
python scripts/validate_public.py
```

This validates the public data and reproduces the paper TEA MSPs without any proprietary database.

### Run with your own emission factors

1. Copy `data/factor_templates/lcia_factors_template.csv` and fill `factor_value`.
2. For spatial analysis, copy `data/factor_templates/regional_electricity_template.csv` and fill the regional electricity factors.
3. Run:

```bash
python scripts/run_custom_pipeline.py \
  --factors my_lcia_factors.csv \
  --regional-factors data/public_factors/regional_fuel_factors.csv \
  --regional-factors my_regional_electricity.csv
```

Outputs are written to `outputs/`.

For the exact factor schemas and units, see `docs/FACTOR_INPUTS.md`. For a file-by-file data guide, see `docs/DATA_DICTIONARY.md`.

## Paper-reference notebooks

`notebooks/published/` contains the executed notebooks with saved results. They are included primarily for transparent inspection of the published workflow. The reusable public command-line workflow is `scripts/run_custom_pipeline.py`.

## Repository map

- `data/foreground_lci/` — physical LCI and mass-allocation audit.
- `data/tea/` — TEA streams, prices, CAPEX, labour, and financial assumptions.
- `data/factor_templates/` — database-neutral factor templates.
- `data/public_factors/` — public NETL/EPA-derived diesel/natural-gas regional factors.
- `data/prices/`, `data/market/`, `data/spatial/` — spatial price, market, damage-cost, and state mapping inputs.
- `reference/paper_results/` — static published/reference outputs for validation.
- `graphite_sus/` — the no-Brightway TEA/spatial/sLCC calculation modules used by the public runner.
- `validation/` — release validation reports.

## Reproducibility boundary

The foreground inventory and TEA are fully public and database-neutral. The published LCA used ecoinvent 3.9.1 for several background processes and regional electricity. Those characterized factors are intentionally omitted from the public executable repository. This avoids redistributing licensed database-derived content while preserving a fully documented route for licensed users to reproduce the paper exactly.

## License

Original code in this repository is released under the MIT License. Original data/documentation produced by the authors are released under CC BY 4.0. Third-party source data and any licensed database-derived material retain their own terms; see `NOTICE.md`.
