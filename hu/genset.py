#!/usr/bin/env python3
"""genset.py v2 — HU dataset generator, ALL registers, per data_spec v1.2."""
import argparse, json, random, string

NAME_POOL = ["Horus","Ra","Thoth","Sobek","Anubis","Osiris","Isis","Seth",
 "Bastet","Khonsu","Ptah","Amun","Geb","Nut","Hathor","Maat","Nefertum",
 "Khepri","Atum","Montu","Sekhmet","Nephthys","Anhur","Aten","Bes","Hapi",
 "Khnum","Menhit","Min","Mut","Nekhbet","Nun","Pakhet","Renenutet","Satet",
 "Seshat","Sopdu","Taweret","Wepwawet","Heka",
 "Tefnut","Shu","Serqet","Wadjet","Neith","Kek","Heh","Apis"]
HELD_OUT_NAMES = set(NAME_POOL[40:])

DIST_BINS=[20,30,50,75,100,150]; ANGLE_BINS=[15,45,90,135,180]; DUR_BINS=[2,3,5,10]
DIRS=["forward","back","left","right"]; ROTS=["clockwise","counterclockwise"]
DIR_WORDS={"forward":["forward","ahead","straight"],"back":["back","backward","backwards","in reverse"],
 "left":["left","to the left"],"right":["right","to the right"]}
ROT_WORDS={"clockwise":["clockwise","cw","to the right"],
 "counterclockwise":["counterclockwise","ccw","anticlockwise","to the left"]}

def num_variant(n, unit_cm=True, rng=None):
    w={15:"fifteen",20:"twenty",30:"thirty",45:"forty five",50:"fifty",75:"seventy five",
       90:"ninety",100:"a hundred",135:"one thirty five",150:"one fifty",2:"two",3:"three",
       5:"five",10:"ten",180:"one eighty"}
    f=[str(n)]
    if n in w: f.append(w[n])
    if unit_cm:
        f+=[f"{n}cm",f"{n} cm",f"{n} centimeters"]
        if n==50: f.append("half a meter")
        if n==100: f.append("one meter")
    return rng.choice(f)

VERBS={
 "TAKEOFF":["take off","launch","deploy","wheels up","airborne now","lift off","get airborne",
  "spool up and take off","up you go","get in the air","start flying","get flying",
  "take to the air","go airborne","begin flight","off the ground","climb out",
  "commence takeoff","take flight","get up there","time to fly","rise and fly"],
 "LAND":["land","touch down","put her down","come down","set down","come down and land",
  "put it down","get on the ground","wrap it up and land","bring it down","back to the ground",
  "end the flight","finish up and land","come on down","descend and land","complete landing",
  "settle down","park it","call it a day and land"],
 "HOVER":["hover","hold position","hold still","stay put","hold there","loiter",
  "maintain position","stay right there","hold altitude","keep station","hold where you are",
  "stay in place","hold steady","maintain hover","just hover there"],
 "MOVE":["move","go","fly","head","slide","shift","proceed","travel","cruise","push","scoot","advance"],
 "TURN":["turn","rotate","spin","yaw","pivot","swing","come around"],
 "UP":["go up","climb","rise","ascend","gain altitude","up","get higher","increase altitude",
  "climb up","move up","gain some height","higher please"],
 "DOWN":["go down","descend","drop","lower","come down a bit","down","get lower",
  "reduce altitude","lose some height","ease down","lower yourself"],
 "STOP":["stop","abort","hold everything","freeze","cancel that","stop now","belay that",
  "cancel the maneuver","abort the maneuver","cease movement","full stop"],
}
COLLECTIVES=["everyone","everybody","all drones","all of you","the whole fleet","all units",
 "the fleet","all","the whole squad","the entire fleet","every drone","all three of you",
 "the team","full fleet","all birds","the squadron"]
PAIR_JOINERS=[" and "," plus ",", "," together with "," along with "]
EXCEPT_WORDS=["except","but not","minus","excluding","apart from","leaving out","other than",
 "besides","save for","not including","without"]
INDEX_WORDS={0:["drone one","drone 1","the first drone","number one"],
 1:["drone two","drone 2","the second drone","number two"],
 2:["drone three","drone 3","the third drone","number three"]}
POLITE=["please ","","","kindly ","","would you ","can you ","go ahead and "]
NOW=["",""," now"," right away"," for me"," when ready"," immediately"," at once"," on my mark"]

def sample_target_expr(rng, roster, allow_absent=False):
    kind=rng.choices(["name","index","all","pair","except"],weights=[30,14,18,20,18])[0]
    if kind=="name":
        if allow_absent and rng.random()<0.5:
            absent=rng.choice([n for n in NAME_POOL if n not in roster])
            return {"type":"NAMES","names":[absent]},absent,"T1"
        n=rng.choice(roster); surf=n if rng.random()<0.8 else n.lower()
        return {"type":"NAMES","names":[n]},surf,"T1"
    if kind=="index":
        k=rng.randrange(min(3,len(roster)))
        return {"type":"NAMES","names":[roster[k]]},rng.choice(INDEX_WORDS[k]),"T2"
    if kind=="all":
        return {"type":"ALL"},rng.choice(COLLECTIVES),"T3"
    if kind=="pair":
        pair=rng.sample(roster,2)
        return {"type":"NAMES","names":pair},rng.choice(PAIR_JOINERS).join(pair),"T3"
    excl=rng.choice(roster); coll=rng.choice(COLLECTIVES[:4])
    return {"type":"EXCEPT","names":[excl]},f"{coll} {rng.choice(EXCEPT_WORDS)} {excl}","T3"

def resolve_labels(expr, roster):
    if expr["type"]=="ALL": return {n:1 for n in roster}
    if expr["type"]=="NAMES": return {n:int(n in expr["names"]) for n in roster}
    if expr["type"]=="EXCEPT": return {n:int(n not in expr["names"]) for n in roster}
    return {n:0 for n in roster}

def sample_action_phrase(rng, action):
    params={}; v=rng.choice(VERBS[action])
    if action=="MOVE":
        d=rng.choice(DIRS); dist=rng.choice(DIST_BINS); params={"dir":d,"dist":dist}
        v=f"{v} {rng.choice(DIR_WORDS[d])} {num_variant(dist,True,rng)}"
    elif action=="TURN":
        a=rng.choice(ANGLE_BINS); r=rng.choice(ROTS); params={"angle":a,"rot":r}
        v=f"{v} {num_variant(a,False,rng)} degrees {rng.choice(ROT_WORDS[r])}"
    elif action=="HOVER":
        s=rng.choice(DUR_BINS); params={"duration":s}
        v=f"{v} for {num_variant(s,False,rng)} seconds"
    elif action in ("UP","DOWN"):
        dist=rng.choice(DIST_BINS); params={"dist":dist}
        v=f"{v} {num_variant(dist,True,rng)}"
    return v,params

def frame(rng, surf, vp, register, vocative):
    p,nw=rng.choice(POLITE),rng.choice(NOW)
    if register=="telegraphic":
        core=vp.replace(" for "," ").replace(" seconds","s")
        return rng.choice([f"{surf.lower()} {core}",f"{core} {surf.lower()}",
                           f"{surf.lower()}: {core}",f"{core} — {surf.lower()}"])
    if vocative=="pre":
        return rng.choice([f"{surf}, {p}{vp}{nw}",f"{surf} {vp}{nw}",
                           f"hey {surf}, {vp}{nw}",f"ok {surf}, {p}{vp}"])
    if vocative=="post":
        return rng.choice([f"{p}{vp}{nw}, {surf}",
                           (f"{vp}, {surf}, "+rng.choice(["will you","ok",""])).rstrip(", "),
                           f"{vp}{nw} {surf}"])
    return rng.choice([f"{p}{vp}, {surf}, "+(nw.strip() or "thanks"),
                       f"i want {surf} to {vp}{nw}",f"let {surf} {vp}{nw}",
                       f"time for {surf} to {vp}"])

FAMILY_OF={"pre":"fam_pre","post":"fam_post","mid":"fam_mid","telegraphic":"fam_tel"}

def typo(rng, s):
    if len(s)<6: return s
    i=rng.randrange(1,len(s)-2); op=rng.random()
    if op<0.4: return s[:i]+s[i+1:]
    if op<0.7: return s[:i]+s[i+1]+s[i]+s[i+2:]
    return s[:i]+rng.choice(string.ascii_lowercase)+s[i+1:]

def nonnative(rng, utt, surf):
    def art(u): return u.replace(surf,"the "+surf,1) if surf in u else u
    def make(u):
        if surf not in u: return "make "+u
        rest=u.split(surf)[-1].strip(" ,.!")
        return ("make "+surf+" to "+rest) if len(rest)>3 else u
    def let(u):
        if surf not in u: return u
        rest=u.split(surf)[-1].strip(" ,.!")
        return ("let "+surf+" to "+rest) if len(rest)>3 else u
    def please2(u): return "please "+u+" please"
    def filler(u): return rng.choice(["uh ","ok so ","yes ","now "])+u+rng.choice([""," ok"," yes"," now"])
    def repeat(u):
        w=u.split()
        if len(w)>2: i=rng.randrange(len(w)); w.insert(i,w[i])
        return " ".join(w)
    def flip(u):
        parts=u.split(", ")
        return ", ".join(reversed(parts)) if len(parts)==2 else u
    def ing(u):
        for a,b in [("take off","taking off"),("land","landing"),("hover","hovering"),
                    ("turn","turning"),("climb","climbing"),("descend","descending")]:
            if a in u: return u.replace(a,b,1)
        return u
    def prep(u):
        return u.replace("go up","go to up").replace("forward","to forward") if rng.random()<0.5 else u
    for f in rng.sample([art,make,let,please2,filler,repeat,flip,ing,prep],rng.choice([1,1,2])):
        utt=f(utt)
    return utt

def arabic_l1(rng, utt, surf):
    def vso(u):
        if ", " in u:
            a,b=u.split(", ",1)
            if surf.lower() in a.lower(): return b+" "+surf
        return u
    def copula(u):
        for a,b in [("take off","is taking off now"),("land","is landing now"),("hover","is hovering")]:
            if a in u and surf in u: return surf+" "+b
        return u
    def yalla(u): return rng.choice(["yalla ","yalla yalla ","tayeb, "])+u
    for f in rng.sample([vso,vso,copula,yalla],rng.choice([1,1,2])):
        utt=f(utt)
    return utt

def spanish_l1(rng, utt, surf):
    def forto(u):
        for a in ["take off","land","hover","turn","climb","descend"]:
            if a in u: return u.replace(a,"for to "+a,1)
        return u
    def prodrop(u):
        for a,b in [("take off","takes off"),("land","lands"),("hover","hovers")]:
            if a in u and surf in u: return u.replace(a,b,1)
        return u
    def vamos(u): return rng.choice(["vamos, ","oye, ","ya, ","andale "])+u
    for f in rng.sample([forto,prodrop,vamos,vamos],rng.choice([1,1,2])):
        utt=f(utt)
    return utt

ASR_CONF={"Horus":["Horace","horis","chorus"],"Ra":["raw","rah","ra ra"],
 "Thoth":["toth","thought","tot","thoss"],"Sobek":["so beck","sobik"],
 "Anubis":["a new bis","anubus"],"Isis":["ices","i sis"],
 "Khonsu":["kon sue","consu"],"Bastet":["bass tet","bast it"]}
def asr_mangle(rng, utt):
    for real,wrongs in ASR_CONF.items():
        for form in (real, real.lower()):
            if form in utt and rng.random()<0.9:
                return utt.replace(form,rng.choice(wrongs),1),True
    return utt,False

HARD_SEEDS=[
 ("TAKEOFF",["{n}, launch","launch, {n}","{n} launch now","launch {n}","{n}, deploy","wheels up, {n}"]),
 ("HOVER",["{n}, hover for {d} seconds","{n} hover {d} seconds","hover {d} seconds, {n}","{n}, hold for {d}"]),
 ("MOVE",["{n}, move forward {c}","{n} move {c} forward","move {n} forward {c}","{n}, forward {c} now"]),
]

IDIOMS=["this project is really taking off","take off your jacket before you fly",
 "we need to land this deal by friday","my career never got off the ground",
 "the meeting is up in the air","let's not go down that road","things are looking up lately",
 "drop me a line when you land in bristol","time really flies here"]
GARBAGE=["what's the weather like today","who won the game last night","open the pod bay doors",
 "play some music","what time is it in cairo","compile the firmware again","order more batteries"]
OOV=["do a barrel roll","flip for me","follow me around the lab","film the whiteboard",
 "do a backflip {name}","{name} follow {name2}","{name} pick up the marker",
 "swarm into a triangle formation"]
UNSAFE=["{name}, forward five meters","everyone up 3 meters","{name} move ahead 400",
 "turn 720 degrees {name}","{name}, hover for ten minutes","all drones climb 500 cm"]
NEGATION=["{name}, don't take off","don't land yet {name}","{name} do not move",
 "nobody take off","everyone, don't land right now","{name}, whatever you do, don't descend"]
UNADDR=["take off","land now","hover for five seconds","move forward 50","go up 30",
 "turn ninety degrees clockwise","stop","please land","up you go"]
EMBED=["check the radar for weather","what's the range on these controllers",
 "the operation ran long today","grab the orange charger","is the radio ok"]
STRESS=["land","LAND","land now","land land land","everybody down now","stop","STOP",
 "stop stop stop","all stop","get down now","down now everyone","abort","abort abort",
 "khalas","khalas khalas","yalla land everyone","everyone land immediately","bring them down"]

def gen_negative(rng, roster):
    sub=rng.choices(["garbage","idiom","oov","unsafe","negation","unaddressed","embedded","stress"],
                    weights=[15,13,13,13,12,12,9,13])[0]
    n1=rng.choice(roster); n2=rng.choice([x for x in roster if x!=n1])
    pick={"garbage":GARBAGE,"idiom":IDIOMS,"oov":OOV,"unsafe":UNSAFE,"negation":NEGATION,
          "unaddressed":UNADDR,"embedded":EMBED,"stress":STRESS}[sub]
    utt=rng.choice(pick).format(name=n1,name2=n2)
    if sub=="stress":
        act="STOP" if ("stop" in utt.lower() or "abort" in utt.lower() or "khalas" in utt.lower()) else "LAND"
        return utt,act,{}, {"type":"ALL"},sub
    if sub=="unaddressed":
        m={"take off":"TAKEOFF","land":"LAND","hover":"HOVER","move":"MOVE","up you":"TAKEOFF",
           "go up":"UP","turn":"TURN","stop":"STOP"}
        action=next((a for k,a in m.items() if k in utt),"LAND")
        if action in ("LAND","STOP"):
            return utt,action,{}, {"type":"ALL"},sub
        return utt,action,{}, {"type":"EMPTY"},sub
    return utt,"REFUSE",{"reason":sub},{"type":"EMPTY"},sub

PARALLEL=[" while "," meanwhile "," and at the same time ","; "]
SEQUENT=[" then "," and then "," after that ",", then "]
def gen_compound(rng, roster, simple_fn):
    a=simple_fn(rng,roster); b=simple_fn(rng,roster)
    if a["target_expr"]["type"]!="NAMES" or b["target_expr"]["type"]!="NAMES": return None
    if set(a["target_expr"]["names"]) & set(b["target_expr"]["names"]): return None
    kind=rng.choice(["parallel","sequential"])
    joiner=rng.choice(PARALLEL if kind=="parallel" else SEQUENT)
    return {"utterance":a["utterance"]+joiner+b["utterance"],"compound":True,"conjunction":kind,
            "clauses":[{k:a[k] for k in ("utterance","action","params","target_expr")},
                       {k:b[k] for k in ("utterance","action","params","target_expr")}],
            "roster":a["roster"],"family":"fam_compound","register":"compound","vocative":"-",
            "negative_subtype":"","action":"COMPOUND","params":{},
            "target_expr":{"type":"COMPOUND"},"target_labels":{},"tier":"T5"}

ACTIONS_POS=["TAKEOFF","LAND","HOVER","MOVE","TURN","UP","DOWN","STOP"]

def gen_simple(rng, roster):
    action=rng.choice(ACTIONS_POS)
    register="telegraphic" if rng.random()<0.20 else "sentence"
    vocative=rng.choice(["pre","post","mid"]) if register=="sentence" else "tel"
    expr,surf,tier=sample_target_expr(rng,roster,allow_absent=(rng.random()<0.06))
    vp,params=sample_action_phrase(rng,action)
    utt=frame(rng,surf,vp,register,vocative if register=="sentence" else "pre")
    r_reg=rng.random()
    is_nn=r_reg<0.20; is_ar=0.20<=r_reg<0.28; is_es=0.28<=r_reg<0.35
    is_asr=False
    if is_nn: utt=nonnative(rng,utt,surf)
    elif is_ar: utt=arabic_l1(rng,utt,surf)
    elif is_es: utt=spanish_l1(rng,utt,surf)
    elif rng.random()<0.10:
        utt,hit=asr_mangle(rng,utt); is_asr=hit
    if rng.random()<0.10: utt=typo(rng,utt)
    labels=resolve_labels(expr,roster)
    if expr["type"]=="NAMES" and not any(labels.values()):
        expr={"type":"EMPTY","absent":expr["names"]}
    if is_nn: register="nonnative"
    elif is_ar: register="arabic_l1"
    elif is_es: register="spanish_l1"
    elif is_asr: register="asr"
    fam=("fam_nn" if is_nn else "fam_ar" if is_ar else "fam_es" if is_es else
         "fam_asr" if is_asr else FAMILY_OF["telegraphic" if register=="telegraphic" else vocative])
    return {"utterance":utt,"action":action,"params":params,"target_expr":expr,"roster":roster,
            "target_labels":labels,"family":f"{fam}_{action}","register":register,
            "vocative":vocative,"negative_subtype":"","compound":False,"clauses":[],
            "conjunction":"","tier":tier}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--n",type=int,default=40000)
    ap.add_argument("--out",default="hu_dataset.jsonl")
    ap.add_argument("--seed",type=int,default=13)
    args=ap.parse_args()
    rng=random.Random(args.seed)
    n_comp=int(args.n*0.15); n_neg=int(args.n*0.27); n_pos=args.n-n_comp-n_neg
    n_hard=int(n_pos*0.08); n_ctr=int(n_pos*0.05)
    rows=[]
    def roster(rng):
        k=rng.choice([3,3,3,4,5,6])
        pool=NAME_POOL[:40] if rng.random()<0.85 else NAME_POOL
        return rng.sample(pool,k)
    for _ in range(n_pos-n_hard-n_ctr):
        rows.append(gen_simple(rng,roster(rng)))
    for _ in range(n_hard):
        r=roster(rng); act,tpls=HARD_SEEDS[rng.randrange(len(HARD_SEEDS))]
        n1=rng.choice(r); d=rng.choice(DUR_BINS); c=rng.choice(DIST_BINS)
        utt=rng.choice(tpls).format(n=(n1 if rng.random()<0.7 else n1.lower()),d=d,c=c)
        params=({"duration":d} if act=="HOVER" else {"dir":"forward","dist":c} if act=="MOVE" else {})
        if rng.random()<0.10: utt=typo(rng,utt)
        rows.append({"utterance":utt,"action":act,"params":params,
            "target_expr":{"type":"NAMES","names":[n1]},"roster":r,
            "target_labels":{n:int(n==n1) for n in r},"family":f"fam_hard_{act}",
            "register":"hard","vocative":"-","negative_subtype":"","compound":False,
            "clauses":[],"conjunction":"","tier":"T1"})
    for _ in range(n_ctr):
        r=roster(rng); excl=rng.choice(r); coll=rng.choice(COLLECTIVES[:4])
        pos=rng.random()<0.5
        word="and" if pos else rng.choice(EXCEPT_WORDS)
        utt=f"{coll} {word} {excl}, land"
        expr={"type":"ALL"} if pos else {"type":"EXCEPT","names":[excl]}
        rows.append({"utterance":utt,"action":"LAND","params":{},"target_expr":expr,"roster":r,
            "target_labels":resolve_labels(expr,r),"family":"fam_contrast","register":"contrast",
            "vocative":"-","negative_subtype":"","compound":False,"clauses":[],
            "conjunction":"","tier":"T3"})
    for _ in range(n_neg):
        r=roster(rng); utt,act,par,expr,sub=gen_negative(rng,r)
        rows.append({"utterance":utt,"action":act,"params":par,"target_expr":expr,"roster":r,
            "target_labels":resolve_labels(expr,r),"family":f"fam_neg_{sub}","register":"negative",
            "vocative":"-","negative_subtype":sub,"compound":False,"clauses":[],
            "conjunction":"","tier":"-"})
    made=0
    while made<n_comp:
        c=gen_compound(rng,roster(rng),gen_simple)
        if c: rows.append(c); made+=1
    rng.shuffle(rows)
    fams=sorted({r["family"] for r in rows
                 if not r["compound"] and not r["family"].startswith("fam_neg")})
    test_fams=set(rng.sample(fams,max(1,len(fams)//6)))
    with open(args.out,"w") as f:
        for i,r in enumerate(rows):
            r["uid"]=f"hu{i:05d}"
            if r["compound"] or r["family"].startswith("fam_neg"):
                r["family_split"]="test" if rng.random()<0.15 else "train"
            else:
                r["family_split"]="test" if r["family"] in test_fams else "train"
            names_in=set(r["roster"])|set(r["target_expr"].get("names",[]) or [])
            r["name_split"]="test" if names_in & HELD_OUT_NAMES else "train"
            f.write(json.dumps(r)+"\n")
    acts={}; regs={}
    for r in rows:
        acts[r["action"]]=acts.get(r["action"],0)+1
        regs[r["register"]]=regs.get(r["register"],0)+1
    print(f"wrote {len(rows)} rows -> {args.out}")
    print("actions:",dict(sorted(acts.items())))
    print("registers:",dict(sorted(regs.items())))
    print("held-out families:",len(test_fams),"| held-out-name rows:",
          sum(1 for r in rows if r["name_split"]=="test"))

if __name__=="__main__":
    main()
