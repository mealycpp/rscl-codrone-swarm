#!/usr/bin/env python3
"""eval_slices.py — per-register action accuracy on family-held-out rows,
against the FROZEN checkpoint. The table the register claims cite."""
import json, torch
from collections import defaultdict
from hu.gateway.hu_service import HU

hu = HU()
rows = [json.loads(l) for l in open("hu/data/hu_dataset.jsonl")]
test = [r for r in rows if r["family_split"] == "test" and not r["compound"]]
by = defaultdict(lambda: [0, 0])
for r in test:
    p = hu.parse(r["utterance"])
    ok = (p["action"] == r["action"])
    key = ("fam_" + r["family"].split("_")[1]) if r["family"].startswith("fam_") else "other"
    by[key][ok] += 1
    by["ALL"][ok] += 1
print(f"{'slice':14s} {'n':>6s} {'action acc':>10s}")
for k in sorted(by):
    w, c = by[k]
    print(f"{k:14s} {w+c:6d} {c/max(w+c,1):10.4f}")
