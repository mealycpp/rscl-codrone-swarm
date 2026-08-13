#!/usr/bin/env python3
"""Rules-only baseline: keyword actions + string-match targets. No model."""
import json, sys, re

KW = [("take off","TAKEOFF"),("takeoff","TAKEOFF"),("launch","TAKEOFF"),("lift off","TAKEOFF"),
 ("wheels up","TAKEOFF"),("airborne","TAKEOFF"),("land","LAND"),("touch down","LAND"),
 ("set down","LAND"),("hover","HOVER"),("hold position","HOVER"),("hold still","HOVER"),
 ("stay put","HOVER"),("loiter","HOVER"),("turn","TURN"),("rotate","TURN"),("spin","TURN"),
 ("yaw","TURN"),("pivot","TURN"),("climb","UP"),("go up","UP"),("ascend","UP"),("rise","UP"),
 ("descend","DOWN"),("go down","DOWN"),("drop","DOWN"),("lower","DOWN"),("stop","STOP"),
 ("abort","STOP"),("freeze","STOP"),("halt","STOP"),("move","MOVE"),("go ","MOVE"),
 ("fly","MOVE"),("head","MOVE"),("slide","MOVE"),("shift","MOVE"),("proceed","MOVE")]
COLL = ["everyone","everybody","all drones","all of you","whole fleet","all units","the fleet",
 "whole squad","entire fleet","every drone","all three","the team","full fleet","all birds",
 "squadron"," all "]
EXC = ["except","but not","minus","excluding","apart from","leaving out","other than",
 "besides","save for","not including","without"]
IDX = {"drone one":0,"drone 1":0,"first drone":0,"number one":0,
       "drone two":1,"drone 2":1,"second drone":1,"number two":1,
       "drone three":2,"drone 3":2,"third drone":2,"number three":2}

def parse(utt, roster):
    u = " " + utt.lower() + " "
    act = next((a for k,a in KW if k in u), "REFUSE")
    excl = [n for n in roster if any(e+" "+n.lower() in u or e+" "+n in utt for e in EXC)]
    if excl:
        return act, {n:int(n not in excl) for n in roster}
    if any(c in u for c in COLL):
        return act, {n:1 for n in roster}
    hits = {n:int(n.lower() in u) for n in roster}
    for k,i in IDX.items():
        if k in u and i < len(roster): hits[roster[i]] = 1
    return act, hits

def score(path, label):
    rows = [json.loads(l) for l in open(path)]
    slices = {
      "family-held-out": [r for r in rows if r.get("family_split")=="test"
                          and not r["compound"] and not r.get("negative_subtype")],
      "held-out-name":   [r for r in rows if r.get("name_split")=="test"
                          and not r["compound"] and not r.get("negative_subtype")],
      "negatives(test)": [r for r in rows if r.get("family_split")=="test"
                          and r.get("negative_subtype")],
    }
    print(f"\n== {label} ==")
    print(f"{'slice':18s} {'n':>6s} {'action':>8s} {'tgt-F1':>8s}")
    for name, rs in slices.items():
        if not rs: continue
        a_ok = tp = fp = fn = 0
        for r in rs:
            act, hits = parse(r["utterance"], r["roster"])
            a_ok += int(act == r["action"])
            for n in r["roster"]:
                g = r["target_labels"].get(n,0); p = hits.get(n,0)
                tp += int(g and p); fp += int(p and not g); fn += int(g and not p)
        f1 = 2*tp/max(2*tp+fp+fn,1)
        print(f"{name:18s} {len(rs):6d} {a_ok/len(rs):8.4f} {f1:8.4f}")

score("hu/data/hu_dataset.jsonl", "training-dist (splits)")
score("hu/data/hu_eval_seed99.jsonl", "seed-99 novel-sample")
