#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
import pandas as pd

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]); ap.add_argument('--private-factor-dir',type=Path); args=ap.parse_args(); root=args.root.resolve(); args.private_factor_dir=args.private_factor_dir.resolve() if args.private_factor_dir else None
    banned=['lcia_factor_mapping_reference.csv','electricity_ipccar6_traci21_ecoregion.csv','electricity_ef_ecoinvent_reference.csv']
    found=[str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p.name in banned]
    checks={'restricted_factor_files_absent':not found,'restricted_factor_files_found':found}
    # Factor template should intentionally have blank factors.
    t=pd.read_csv(root/'data/factor_templates/lcia_factors_template.csv'); checks['factor_template_rows']=len(t); checks['factor_template_blank_values']=int(pd.to_numeric(t.factor_value,errors='coerce').isna().sum())
    # Public fuel factors complete.
    f=pd.read_csv(root/'data/public_factors/regional_fuel_factors.csv'); checks['public_fuel_rows']=len(f); checks['public_fuel_factor_values_complete']=bool(pd.to_numeric(f.factor_value,errors='coerce').notna().all())
    # TEA must run and match paper MSPs without any private factors.
    out=root/'validation/_public_smoke'; out.mkdir(parents=True,exist_ok=True)
    p=subprocess.run([sys.executable,'scripts/run_custom_pipeline.py','--root',str(root),'--output-dir',str(out),'--compare-paper'],cwd=root,text=True,capture_output=True)
    checks['tea_smoke_returncode']=p.returncode; checks['tea_smoke_stdout_tail']='\n'.join(p.stdout.splitlines()[-20:]); checks['tea_smoke_pass']=p.returncode==0
    # Notebooks should be executed/saved for read-only inspection.
    import json as _json
    nbstats={}
    for nb in sorted((root/'notebooks/published').glob('*.ipynb')):
        obj=_json.loads(nb.read_text()); code=[c for c in obj.get('cells',[]) if c.get('cell_type')=='code']; nbstats[nb.name]={'code_cells':len(code),'executed':sum(c.get('execution_count') is not None for c in code),'with_outputs':sum(bool(c.get('outputs')) for c in code)}
    checks['notebooks']=nbstats
    if args.private_factor_dir:
        pf=args.private_factor_dir
        cmd=[sys.executable,'scripts/run_custom_pipeline.py','--root',str(root),'--factors',str(pf/'paper_lcia_factors.csv'),'--regional-factors',str(root/'data/public_factors/regional_fuel_factors.csv'),'--regional-factors',str(pf/'paper_regional_electricity.csv'),'--output-dir',str(root/'validation/_paper_replay'),'--compare-paper']
        q=subprocess.run(cmd,cwd=root,text=True,capture_output=True); checks['paper_replay_returncode']=q.returncode; checks['paper_replay_stdout_tail']='\n'.join(q.stdout.splitlines()[-30:]); checks['paper_replay_pass']=q.returncode==0
    checks['passed']=checks['restricted_factor_files_absent'] and checks['public_fuel_factor_values_complete'] and checks['tea_smoke_pass'] and (checks.get('paper_replay_pass',True))
    outp=root/'validation/public_validation.json'; outp.write_text(json.dumps(checks,indent=2)); print(json.dumps(checks,indent=2)); return 0 if checks['passed'] else 1
if __name__=='__main__': raise SystemExit(main())
