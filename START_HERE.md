# Start here — public GitHub release

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r environment/requirements.txt
python scripts/validate_public.py
```

Expected result: `"passed": true`. This public validation reproduces the paper TEA and checks the open-data/factor-template package.

To use your own emission factors, follow `QUICKSTART.md` and `docs/FACTOR_INPUTS.md`.

The exact paper LCA can be reproduced by licensed users with the private paper factor bundle; the release validation against that bundle is recorded in `validation/paper_replay_validation.json`.
