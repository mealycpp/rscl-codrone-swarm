#!/usr/bin/env python3
"""train_heads.py — HU v1: frozen SmolLM2-135M + task heads.
Trains: action(9) / target-matching(1, per-candidate) / dir(4) rot(2) dist(6)
angle(5) dur(4) / compound-detector(1).  Reports family-held-out and
NAME-held-out metrics (the scalability number). Compounds excluded from
simple heads; splitter integration comes after v1 numbers."""
import json, random, argparse, torch, torch.nn as nn
from collections import defaultdict
from transformers import AutoTokenizer, AutoModel

DEV = "cuda" if torch.cuda.is_available() else "cpu"
MODEL = "HuggingFaceTB/SmolLM2-135M"
ACTIONS = ["TAKEOFF","LAND","HOVER","MOVE","TURN","UP","DOWN","STOP","REFUSE"]
A2I = {a:i for i,a in enumerate(ACTIONS)}
DIRS=["forward","back","left","right"]; ROTS=["clockwise","counterclockwise"]
DISTS=[20,30,50,75,100,150]; ANGLES=[15,45,90,135,180]; DURS=[2,3,5,10]


def _mentions(name, utt):
    u = utt.lower(); n = name.lower()
    if n in u: return "yes"
    toks = [t.strip(",.!?;:") for t in u.split()]
    for t in toks:
        if abs(len(t)-len(n)) <= 1:
            d = sum(a!=b for a,b in zip(t,n)) + abs(len(t)-len(n))
            if d <= 1: return "yes"
    return "no"

def load(path):
    return [json.loads(l) for l in open(path)]

@torch.no_grad()
def embed(texts, tok, enc, bs=128):
    outs=[]
    for i in range(0, len(texts), bs):
        b = tok(texts[i:i+bs], return_tensors="pt", padding=True,
                truncation=True, max_length=64).to(DEV)
        h = enc(**b).last_hidden_state
        m = b["attention_mask"].unsqueeze(-1)
        mean = (h*m).sum(1)/m.sum(1)
        mx = h.masked_fill(m==0, -1e9).max(1).values
        outs.append(torch.cat([mean, mx], dim=-1).float().cpu())
        if i % 2048 == 0: print(f"  embed {i}/{len(texts)}", flush=True)
    return torch.cat(outs)

class Head(nn.Module):
    def __init__(self, d, k, hid=384):
        super().__init__()
        self.f = nn.Sequential(nn.Linear(d,hid), nn.GELU(), nn.Dropout(0.1),
                               nn.Linear(hid,k))
    def forward(self,x): return self.f(x)

def fit(X, y, k, epochs=30, w=None, lr=1e-3, name=""):
    h = Head(X.shape[1], k).to(DEV)
    opt = torch.optim.AdamW(h.parameters(), lr=lr, weight_decay=1e-4)
    lossf = (nn.BCEWithLogitsLoss(pos_weight=w) if k==1
             else nn.CrossEntropyLoss(weight=w, label_smoothing=0.05))
    X, y = X.to(DEV), y.to(DEV)
    for ep in range(epochs):
        h.train(); perm = torch.randperm(len(X))
        for i in range(0, len(X), 256):
            idx = perm[i:i+256]; opt.zero_grad()
            out = h(X[idx]); out = out.squeeze(-1) if k==1 else out
            loss = lossf(out, y[idx]); loss.backward(); opt.step()
    return h

@torch.no_grad()
def acc(h, X, y, k):
    h.eval(); out = h(X.to(DEV))
    if k==1:
        p = (torch.sigmoid(out.squeeze(-1)) > 0.5).float().cpu()
        tp=((p==1)&(y==1)).sum().item(); fp=((p==1)&(y==0)).sum().item()
        fn=((p==0)&(y==1)).sum().item()
        prec=tp/max(tp+fp,1); rec=tp/max(tp+fn,1)
        return {"acc":(p==y).float().mean().item(),
                "f1":2*prec*rec/max(prec+rec,1e-9),"prec":prec,"rec":rec}
    return {"acc":(out.argmax(1).cpu()==y).float().mean().item()}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="hu/data/hu_dataset.jsonl")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    torch.manual_seed(args.seed); random.seed(args.seed)

    rows = load(args.data)
    simple = [r for r in rows if not r["compound"]]
    print(f"{len(rows)} rows ({len(simple)} simple, {len(rows)-len(simple)} compound)")

    tok = AutoTokenizer.from_pretrained(MODEL)
    if tok.pad_token is None: tok.pad_token = tok.eos_token
    enc = AutoModel.from_pretrained(MODEL).to(DEV).eval()
    print("encoder loaded on", DEV)

    # ---------- utterance embeddings (action/param/compound heads) ----------
    print("embedding utterances...")
    U = embed([r["utterance"] for r in rows], tok, enc)
    d = U.shape[1]

    idx_simple = [i for i,r in enumerate(rows) if not r["compound"]]
    tr = [i for i in idx_simple if rows[i]["family_split"]=="train"]
    te_fam = [i for i in idx_simple if rows[i]["family_split"]=="test"]

    ya = torch.tensor([A2I[rows[i]["action"]] for i in idx_simple])
    pos = {i:j for j,i in enumerate(idx_simple)}
    Xa = U[idx_simple]

    print("training action head...")
    ha = fit(Xa[[pos[i] for i in tr]], ya[[pos[i] for i in tr]], 9, name="action")
    ra = acc(ha, Xa[[pos[i] for i in te_fam]], ya[[pos[i] for i in te_fam]], 9)
    print(f"ACTION  family-held-out acc = {ra['acc']:.4f}  (bar 0.98)")
    with torch.no_grad():
        pred = ha(Xa[[pos[i] for i in te_fam]].to(DEV)).argmax(1).cpu()
    tru = ya[[pos[i] for i in te_fam]]
    conf = {}
    for p_, y_ in zip(pred.tolist(), tru.tolist()):
        if p_ != y_: conf[(ACTIONS[y_], ACTIONS[p_])] = conf.get((ACTIONS[y_], ACTIONS[p_]), 0) + 1
    for (yt, pt), c in sorted(conf.items(), key=lambda x: -x[1])[:8]:
        print(f"   confuse {yt:8s} -> {pt:8s} x{c}")

    # ---------- compound detector ----------
    yc = torch.tensor([1.0 if r["compound"] else 0.0 for r in rows])
    ct = [i for i,r in enumerate(rows) if r["family_split"]=="train"]
    cv = [i for i,r in enumerate(rows) if r["family_split"]=="test"]
    hc = fit(U[ct], yc[ct], 1, name="compound")
    rc = acc(hc, U[cv], yc[cv], 1)
    print(f"COMPOUND detector f1 = {rc['f1']:.4f}")

    # ---------- param heads ----------
    PARAM_STATES = {}
    def param_head(key, vocab, label):
        ids = [i for i in idx_simple if key in rows[i]["params"]]
        if not ids: return
        y = torch.tensor([vocab.index(rows[i]["params"][key]) for i in ids])
        t = [i for i in ids if rows[i]["family_split"]=="train"]
        v = [i for i in ids if rows[i]["family_split"]=="test"] or t[:50]
        m = {i:j for j,i in enumerate(ids)}
        h = fit(U[ids][[m[i] for i in t]], y[[m[i] for i in t]], len(vocab))
        r = acc(h, U[ids][[m[i] for i in v]], y[[m[i] for i in v]], len(vocab))
        print(f"PARAM {label:6s} acc = {r['acc']:.4f}  (bar 0.95)")
        PARAM_STATES[label] = h.state_dict()
    param_head("dir", DIRS, "dir"); param_head("rot", ROTS, "rot")
    param_head("dist", DISTS, "dist"); param_head("angle", ANGLES, "angle")
    param_head("duration", DURS, "dur")

    # ---------- target matching head (the scalability result) ----------
    print("building matching pairs...")
    q_texts, q_y, q_name_split, q_excl = [], [], [], []
    for r in simple:
        for k, nm in enumerate(r["roster"]):
            q_texts.append(f"drone: {nm} | index: {k} | mentioned: {_mentions(nm, r['utterance'])} | utterance: {r['utterance']}")
            q_y.append(float(r["target_labels"].get(nm, 0)))
            q_name_split.append(r["name_split"])
            q_excl.append(r["target_expr"]["type"]=="EXCEPT")
    print(f"  {len(q_texts)} pairs; embedding...")
    Q = embed(q_texts, tok, enc)
    qy = torch.tensor(q_y)
    t = [i for i,s in enumerate(q_name_split) if s=="train"]
    v_name = [i for i,s in enumerate(q_name_split) if s=="test"]
    v_excl = [i for i in range(len(q_texts)) if q_excl[i] and q_name_split[i]=="test"] \
             or [i for i in range(len(q_texts)) if q_excl[i]][:500]
    pw = torch.sqrt(torch.tensor([ (len(t)-qy[t].sum())/max(qy[t].sum(),1) ])).to(DEV)
    import random as _r
    _r.seed(7); _r.shuffle(t)
    t_fit, t_val = t[:int(len(t)*0.9)], t[int(len(t)*0.9):]
    hm = fit(Q[t_fit], qy[t_fit], 1, w=pw, epochs=40, name="match")
    with torch.no_grad():
        pv = torch.sigmoid(hm(Q[t_val].to(DEV)).squeeze(-1)).cpu()
    best_tau, best_f1 = 0.5, 0.0
    for tau in [x/100 for x in range(30, 86, 2)]:
        p = (pv > tau).float()
        tp = ((p==1)&(qy[t_val]==1)).sum().item(); fp = ((p==1)&(qy[t_val]==0)).sum().item()
        fn = ((p==0)&(qy[t_val]==1)).sum().item()
        f1 = 2*tp/max(2*tp+fp+fn, 1)
        if f1 > best_f1: best_tau, best_f1 = tau, f1
    print(f"tuned tau = {best_tau:.2f} (val F1 {best_f1:.4f})")
    def acc_tau(h, X, y, tau):
        with torch.no_grad():
            p = (torch.sigmoid(h(X.to(DEV)).squeeze(-1)).cpu() > tau).float()
        tp=((p==1)&(y==1)).sum().item(); fp=((p==1)&(y==0)).sum().item()
        fn=((p==0)&(y==1)).sum().item()
        prec=tp/max(tp+fp,1); rec=tp/max(tp+fn,1)
        return {"acc":(p==y).float().mean().item(),
                "f1":2*prec*rec/max(prec+rec,1e-9),"prec":prec,"rec":rec}
    rn = acc_tau(hm, Q[v_name], qy[v_name], best_tau)
    re = acc_tau(hm, Q[v_excl], qy[v_excl], best_tau)
    per = defaultdict(lambda: [0,0])
    import re as _re
    for i in v_name:
        nm = _re.match(r"drone: (\w+)", q_texts[i]).group(1)
        with torch.no_grad():
            p = (torch.sigmoid(hm(Q[i:i+1].to(DEV)).squeeze(-1)).item() > best_tau)
        per[nm][int(p == bool(qy[i]))] += 1
    for nm, (wrong, right) in sorted(per.items()):
        if nm in {"Tefnut","Shu","Serqet","Wadjet","Neith","Kek","Heh","Apis"}:
            print(f"   name {nm:8s} acc = {right/max(right+wrong,1):.3f}")
    print(f"TARGET  HELD-OUT-NAME  F1 = {rn['f1']:.4f}  P={rn['prec']:.3f} R={rn['rec']:.3f}  (bar 0.95)")
    print(f"TARGET  exclusion slice acc = {re['acc']:.4f}  (bar 0.90)")

    torch.save({"action":ha.state_dict(),"match":hm.state_dict(),
                "compound":hc.state_dict(),"params":PARAM_STATES,"dim":d,"actions":ACTIONS},
               "hu/models/hu_heads_v1.pt")
    print("saved -> hu/models/hu_heads_v1.pt")

if __name__ == "__main__":
    main()
