#!/bin/bash
set -e
python3 hu/genset.py --n 40000 --out hu/data/hu_dataset.jsonl --seed 13
python3 hu/validate_dataset.py hu/data/hu_dataset.jsonl --clean
python3 - <<'PY'
import json
regs={}
for l in open("hu/data/hu_dataset.jsonl"):
    r=json.loads(l); regs[r["register"]]=regs.get(r["register"],0)+1
need={"nonnative":2000,"arabic_l1":800,"spanish_l1":700,"asr":150,"hard":800,
      "contrast":500,"telegraphic":1500,"sentence":5000,"negative":5000,"compound":3000}
bad=[k for k,v in need.items() if regs.get(k,0)<v]
print("REGISTER GATE:",{k:regs.get(k,0) for k in need})
if bad: print("GATE FAILED:",bad); raise SystemExit(1)
print("REGISTER GATE PASSED")
PY
python3 hu/train_heads.py --data hu/data/hu_dataset.jsonl --seed 0
cp hu/models/hu_heads_v1.pt hu/models/hu_heads_v1_1_REGISTERS.pt
python3 hu/genset.py --n 8000 --out hu/data/hu_eval_seed99.jsonl --seed 99
PYTHONPATH=. python3 hu/eval_registers.py
echo "REBUILD COMPLETE — v1.1 saved"
