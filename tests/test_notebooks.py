import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_notebooks_are_executed_snapshots():
 for p in (ROOT/'notebooks/published').glob('*.ipynb'):
  obj=json.loads(p.read_text()); code=[c for c in obj['cells'] if c.get('cell_type')=='code']; assert code; assert sum(c.get('execution_count') is not None for c in code)>=max(1,int(0.8*len(code)))
