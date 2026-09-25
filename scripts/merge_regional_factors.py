#!/usr/bin/env python3
import argparse,pandas as pd
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('inputs',nargs='+',type=Path); p.add_argument('-o','--output',type=Path,required=True); a=p.parse_args()
d=pd.concat([pd.read_csv(x) for x in a.inputs],ignore_index=True); keys=['carrier','region','impact_category']
if d.duplicated(keys).any(): raise SystemExit('Duplicate carrier/region/impact rows')
a.output.parent.mkdir(parents=True,exist_ok=True); d.to_csv(a.output,index=False); print(a.output)
