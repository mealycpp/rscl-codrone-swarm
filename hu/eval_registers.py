#!/usr/bin/env python3
"""eval_registers.py — frozen-model accuracy per register on a fresh
seed-99 eval-only set (never trained). Label in paper: novel-sample."""
import json
from collections import defaultdict
from hu.gateway.hu_service import HU

hu = HU()
rows = [json.loads(l) for l in open("hu/data/hu_eval_seed99.jsonl")]
keep = {"nonnative":"L2 generic","arabic_l1":"Arabic-L1","spanish_l1":"Spanish-L1",
        "asr":"ASR-mangled","hard":"live-mined","telegraphic":"telegraphic",
        "sentence":"canonical"}
by = defaultdict(lambda: [0,0,0])   # [action_ok, target_ok, n]
for r in rows:
    if r["compound"] or r["negative_subtype"]: continue
    reg = r["register"]
    if reg not in keep: continue
    p = hu.parse(r["utterance"])
    want = {n for n,v in r["target_labels"].items() if v}
    # roster mismatch: parse uses live roster; compare only on overlap names
    got = {t for t in p["targets"] if t in r["roster"]}
    a_ok = int(p["action"] == r["action"])
    t_ok = int(got & set(hu.roster()) == want & set(hu.roster())) if want else int(not got)
    by[reg][0] += a_ok; by[reg][1] += t_ok; by[reg][2] += 1
print(f"{'register':14s} {'n':>5s} {'action':>8s} {'targets':>8s}")
for reg, label in keep.items():
    a,t,n = by[reg]
    if n: print(f"{label:14s} {n:5d} {a/n:8.4f} {t/n:8.4f}")
