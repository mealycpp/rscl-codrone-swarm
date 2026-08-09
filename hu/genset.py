#!/usr/bin/env python3
"""genset.py — HU training-set generator (grammar.md v1, frozen 2026-08-08)."""
import argparse, json, random, string

NAME_POOL = ["Horus","Ra","Thoth","Sobek","Anubis","Osiris","Isis","Seth",
             "Bastet","Khonsu","Ptah","Amun","Geb","Nut","Hathor","Maat",
             "Nefertum","Khepri","Atum","Montu",
             "Tefnut","Shu","Serqet","Wadjet","Neith"]
HELD_OUT_NAMES = set(NAME_POOL[20:])

DIST_BINS = [20,30,50,75,100,150]
ANGLE_BINS = [15,45,90,135,180]
DUR_BINS = [2,3,5,10]
DIRS = ["forward","back","left","right"]
ROTS = ["clockwise","counterclockwise"]

DIR_WORDS = {"forward":["forward","ahead","straight"],
             "back":["back","backward","backwards","in reverse"],
             "left":["left","to the left"], "right":["right","to the right"]}
ROT_WORDS = {"clockwise":["clockwise","cw","to the right"],
             "counterclockwise":["counterclockwise","ccw","anticlockwise","to the left"]}

def num_variant(n, unit_cm=True, rng=None):
    words = {15:"fifteen",20:"twenty",30:"thirty",45:"forty five",50:"fifty",
             75:"seventy five",90:"ninety",100:"a hundred",135:"one thirty five",
             150:"one fifty",2:"two",3:"three",5:"five",10:"ten",180:"one eighty"}
    forms = [str(n)]
    if n in words: forms.append(words[n])
    if unit_cm:
        forms += [f"{n}cm", f"{n} cm", f"{n} centimeters"]
        if n == 50: forms.append("half a meter")
        if n == 100: forms.append("one meter")
    return rng.choice(forms)

VERBS = {
 "TAKEOFF": ["take off","launch","lift off","get airborne","spool up and take off",
             "up you go","get in the air","start flying"],
 "LAND":    ["land","touch down","set down","come down and land","put it down",
             "get on the ground","wrap it up and land"],
 "HOVER":   ["hover","hold position","hold still","stay put","hold there","loiter"],
 "MOVE":    ["move","go","fly","head","slide","shift"],
 "TURN":    ["turn","rotate","spin","yaw"],
 "UP":      ["go up","climb","rise","ascend","gain altitude","up"],
 "DOWN":    ["go down","descend","drop","lower","come down a bit","down"],
 "STOP":    ["stop","abort","hold everything","freeze","cancel that","stop now"],
}

COLLECTIVES = ["everyone","everybody","all drones","all of you","the whole fleet",
               "all units","the fleet","all"]
PAIR_JOINERS = [" and ", " plus ", ", "]
EXCEPT_WORDS = ["except","but not","minus","excluding","apart from","leaving out"]
INDEX_WORDS = {0:["drone one","drone 1","the first drone","number one"],
               1:["drone two","drone 2","the second drone","number two"],
               2:["drone three","drone 3","the third drone","number three"]}

POLITE = ["please ","","","kindly ",""]
NOW = ["", "", " now", " right away", " for me", " when ready"]

def sample_target_expr(rng, roster, allow_absent=False):
    kind = rng.choices(["name","index","all","pair","except"],
                       weights=[34,10,18,20,18])[0]
    if kind == "name":
        if allow_absent and rng.random() < 0.5:
            absent = rng.choice([n for n in NAME_POOL if n not in roster])
            return {"type":"NAMES","names":[absent]}, absent, "T1"
        n = rng.choice(roster)
        surf = n if rng.random() < 0.8 else n.lower()
        return {"type":"NAMES","names":[n]}, surf, "T1"
    if kind == "index":
        k = rng.randrange(min(3,len(roster)))
        return {"type":"NAMES","names":[roster[k]]}, rng.choice(INDEX_WORDS[k]), "T2"
    if kind == "all":
        return {"type":"ALL"}, rng.choice(COLLECTIVES), "T3"
    if kind == "pair":
        pair = rng.sample(roster, 2)
        return ({"type":"NAMES","names":pair},
                rng.choice(PAIR_JOINERS).join(pair), "T3")
    excl = rng.choice(roster)
    coll = rng.choice(COLLECTIVES[:4])
    return ({"type":"EXCEPT","names":[excl]},
            f"{coll} {rng.choice(EXCEPT_WORDS)} {excl}", "T3")

def resolve_labels(expr, roster):
    if expr["type"] == "ALL":    return {n: 1 for n in roster}
    if expr["type"] == "NAMES":  return {n: int(n in expr["names"]) for n in roster}
    if expr["type"] == "EXCEPT": return {n: int(n not in expr["names"]) for n in roster}
    return {n: 0 for n in roster}

def sample_action_phrase(rng, action):
    params = {}
    v = rng.choice(VERBS[action])
    if action == "MOVE":
        d = rng.choice(DIRS); dist = rng.choice(DIST_BINS)
        params = {"dir": d, "dist": dist}
        v = f"{v} {rng.choice(DIR_WORDS[d])} {num_variant(dist, True, rng)}"
    elif action == "TURN":
        a = rng.choice(ANGLE_BINS); r = rng.choice(ROTS)
        params = {"angle": a, "rot": r}
        v = f"{v} {num_variant(a, False, rng)} degrees {rng.choice(ROT_WORDS[r])}"
    elif action == "HOVER":
        s = rng.choice(DUR_BINS); params = {"duration": s}
        v = f"{v} for {num_variant(s, False, rng)} seconds"
    elif action in ("UP","DOWN"):
        dist = rng.choice(DIST_BINS); params = {"dist": dist}
        v = f"{v} {num_variant(dist, True, rng)}"
    return v, params

def frame(rng, surf, vp, register, vocative):
    p, nw = rng.choice(POLITE), rng.choice(NOW)
    if register == "telegraphic":
        core = vp.split(" for ")[0]
        return rng.choice([f"{surf.lower()} {core}", f"{core} {surf.lower()}",
                           f"{surf.lower()}: {core}", f"{core} — {surf.lower()}"])
    if vocative == "pre":
        return rng.choice([f"{surf}, {p}{vp}{nw}", f"{surf} {vp}{nw}",
                           f"hey {surf}, {vp}{nw}", f"ok {surf}, {p}{vp}"])
    if vocative == "post":
        return rng.choice([f"{p}{vp}{nw}, {surf}",
                           (f"{vp}, {surf}, " + rng.choice(["will you","ok",""])).rstrip(", "),
                           f"{vp}{nw} {surf}"])
    return rng.choice([f"{p}{vp}, {surf}, " + (nw.strip() or "thanks"),
                       f"i want {surf} to {vp}{nw}", f"let {surf} {vp}{nw}",
                       f"time for {surf} to {vp}"])

FAMILY_OF = {"pre":"fam_pre","post":"fam_post","mid":"fam_mid","telegraphic":"fam_tel"}

def typo(rng, s):
    if len(s) < 6: return s
    i = rng.randrange(1, len(s)-2)
    op = rng.random()
    if op < 0.4:  return s[:i] + s[i+1:]
    if op < 0.7:  return s[:i] + s[i+1] + s[i] + s[i+2:]
    return s[:i] + rng.choice(string.ascii_lowercase) + s[i+1:]

IDIOMS = ["this project is really taking off","take off your jacket before you fly",
 "we need to land this deal by friday","my career never got off the ground",
 "the meeting is up in the air","let's not go down that road",
 "he turned the conversation around","things are looking up lately",
 "drop me a line when you land in bristol","time really flies here"]
GARBAGE = ["what's the weather like today","who won the game last night",
 "open the pod bay doors","play some music","what time is it in cairo",
 "compile the firmware again","how is the paper going","order more batteries"]
OOV = ["do a barrel roll","flip for me","follow me around the lab","film the whiteboard",
 "do a backflip {name}","{name} follow {name2}","draw a circle in the air with the pen",
 "{name} pick up the marker","swarm into a triangle formation"]
UNSAFE = ["{name}, forward five meters","everyone up 3 meters","{name} move ahead 400",
 "turn 720 degrees {name}","{name}, hover for ten minutes","all drones climb 500 cm"]
NEGATION = ["{name}, don't take off","don't land yet {name}","{name} do not move",
 "nobody take off","everyone, don't land right now","{name}, whatever you do, don't descend"]
UNADDR = ["take off","land now","hover for five seconds","move forward 50","go up 30",
 "turn ninety degrees clockwise","stop","please land","up you go"]
EMBED = ["check the radar for weather","what's the range on these controllers",
 "the operation ran long today","the rat ran across the lab floor",
 "grab the orange charger","is the radio ok"]

def gen_negative(rng, roster):
    sub = rng.choices(["garbage","idiom","oov","unsafe","negation","unaddressed","embedded"],
                      weights=[18,15,15,14,14,14,10])[0]
    n1 = rng.choice(roster); n2 = rng.choice([x for x in roster if x != n1])
    pick = {"garbage":GARBAGE,"idiom":IDIOMS,"oov":OOV,"unsafe":UNSAFE,
            "negation":NEGATION,"unaddressed":UNADDR,"embedded":EMBED}[sub]
    utt = rng.choice(pick).format(name=n1, name2=n2)
    if sub == "unaddressed":
        act = {"take off":"TAKEOFF","land":"LAND","hover":"HOVER","move":"MOVE",
               "go up":"UP","up you":"UP","turn":"TURN","stop":"STOP"}
        action = next((a for k,a in act.items() if k in utt), "LAND")
        return utt, action, {}, {"type":"EMPTY"}, sub
    return utt, "REFUSE", {"reason": sub}, {"type":"EMPTY"}, sub

PARALLEL = [" while ", " meanwhile ", " and at the same time ", "; "]
SEQUENT  = [" then ", " and then ", " after that ", ", then "]

def gen_compound(rng, roster, simple_fn):
    a = simple_fn(rng, roster); b = simple_fn(rng, roster)
    if set(a["target_expr"].get("names",[])) & set(b["target_expr"].get("names",[])):
        return None
    if a["target_expr"]["type"] != "NAMES" or b["target_expr"]["type"] != "NAMES":
        return None
    kind = rng.choice(["parallel","sequential"])
    joiner = rng.choice(PARALLEL if kind == "parallel" else SEQUENT)
    return {"utterance": a["utterance"] + joiner + b["utterance"],
            "compound": True, "conjunction": kind,
            "clauses": [ {k: a[k] for k in ("utterance","action","params","target_expr")},
                         {k: b[k] for k in ("utterance","action","params","target_expr")} ],
            "roster": a["roster"], "family": "fam_compound",
            "register": "compound", "vocative": "-", "negative_subtype": "",
            "action": "COMPOUND", "params": {},
            "target_expr": {"type":"COMPOUND"},
            "target_labels": {}}

ACTIONS_POS = ["TAKEOFF","LAND","HOVER","MOVE","TURN","UP","DOWN","STOP"]

def gen_simple(rng, roster):
    action = rng.choice(ACTIONS_POS)
    register = "telegraphic" if rng.random() < 0.20 else "sentence"
    vocative = rng.choice(["pre","post","mid"]) if register == "sentence" else "tel"
    expr, surf, tier = sample_target_expr(rng, roster,
                                          allow_absent=(rng.random() < 0.06))
    vp, params = sample_action_phrase(rng, action)
    utt = frame(rng, surf, vp, register, vocative if register=="sentence" else "pre")
    if rng.random() < 0.10: utt = typo(rng, utt)
    labels = resolve_labels(expr, roster)
    if expr["type"] == "NAMES" and not any(labels.values()):
        expr = {"type":"EMPTY", "absent": expr["names"]}
    fam = FAMILY_OF["telegraphic" if register=="telegraphic" else vocative]
    return {"utterance": utt, "action": action, "params": params,
            "target_expr": expr, "roster": roster, "target_labels": labels,
            "family": f"{fam}_{action}", "register": register,
            "vocative": vocative, "negative_subtype": "", "compound": False,
            "clauses": [], "conjunction": "", "tier": tier}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8000)
    ap.add_argument("--out", default="hu_dataset.jsonl")
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    n_comp = int(args.n * 0.15)
    n_neg  = int(args.n * 0.27)
    n_pos  = args.n - n_comp - n_neg
    rows = []

    def roster(rng):
        k = rng.choice([3,3,3,4,5,6])
        pool = NAME_POOL[:20] if rng.random() < 0.85 else NAME_POOL
        return rng.sample(pool, k)

    for _ in range(n_pos):
        rows.append(gen_simple(rng, roster(rng)))
    for _ in range(n_neg):
        r = roster(rng)
        utt, act, par, expr, sub = gen_negative(rng, r)
        rows.append({"utterance": utt, "action": act, "params": par,
                     "target_expr": expr, "roster": r,
                     "target_labels": resolve_labels(expr, r),
                     "family": f"fam_neg_{sub}", "register": "negative",
                     "vocative": "-", "negative_subtype": sub, "compound": False,
                     "clauses": [], "conjunction": "", "tier": "-"})
    made = 0
    while made < n_comp:
        c = gen_compound(rng, roster(rng), gen_simple)
        if c: c["tier"] = "T5"; rows.append(c); made += 1

    rng.shuffle(rows)
    fams = sorted({r["family"] for r in rows})
    test_fams = set(rng.sample(fams, max(1, len(fams)//6)))
    with open(args.out, "w") as f:
        for i, r in enumerate(rows):
            r["uid"] = f"hu{i:05d}"
            r["family_split"] = "test" if r["family"] in test_fams else "train"
            names_in = set(r["roster"]) | set(r["target_expr"].get("names", []) or [])
            r["name_split"] = "test" if names_in & HELD_OUT_NAMES else "train"
            f.write(json.dumps(r) + "\n")
    acts = {}
    for r in rows: acts[r["action"]] = acts.get(r["action"], 0) + 1
    print(f"wrote {len(rows)} rows -> {args.out}")
    print("action counts:", dict(sorted(acts.items())))
    print("held-out families:", len(test_fams), "| held-out-name rows:",
          sum(1 for r in rows if r.get("name_split")=="test"))

if __name__ == "__main__":
    main()
