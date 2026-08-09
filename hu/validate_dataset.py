#!/usr/bin/env python3
"""validate_dataset.py — mechanical R1 (label-invariance) check.
Fails the build if >0.5% of rows violate invariants."""
import json, re, sys

def edit1(a, b):
    if abs(len(a)-len(b)) > 1: return False
    if len(a) == len(b): return sum(x!=y for x,y in zip(a,b)) <= 1
    s, l = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(l)):
        if s == l[:i] + l[i+1:]: return True
    return False

def name_present(name, utt):
    toks = [t.strip(",.!?;:—-").lower() for t in utt.split()]
    n = name.lower()
    return any(t == n or edit1(t, n) for t in toks)

bad, total = [], 0
for line in open(sys.argv[1] if len(sys.argv) > 1 else "hu/data/hu_dataset.jsonl"):
    r = json.loads(line); total += 1
    if r["compound"] or r["negative_subtype"]: continue
    te = r["target_expr"]
    if te["type"] == "NAMES":
        for nm in te["names"]:
            if not name_present(nm, r["utterance"]):
                bad.append((r["uid"], "name-lost", nm, r["utterance"])); break
    nums = [str(v) for v in r["params"].values() if isinstance(v, (int, float))]
    # numbers may appear as words; only flag if NO digit and NO word-number trace
    if nums and not re.search(r"\d|two|three|five|ten|fifteen|twenty|thirty|forty|fifty|seventy|ninety|hundred|meter|eighty", r["utterance"], re.I):
        bad.append((r["uid"], "param-lost", nums, r["utterance"]))
rate = len(bad) / max(total, 1)
print(f"{total} rows checked, {len(bad)} invariant violations ({rate:.3%})")
for b in bad[:10]: print("  ", b)
sys.exit(1 if rate > 0.005 else 0)
