#!/usr/bin/env python3
"""hu_service.py — HU parse service: utterance -> (action, params, targets, band).
Frozen SmolLM2 + trained heads; symbolic param extraction; mention feature."""
import torch, torch.nn as nn, yaml, time, re as _re
from transformers import AutoTokenizer, AutoModel

DEV = "cuda" if torch.cuda.is_available() else "cpu"
MODEL = "HuggingFaceTB/SmolLM2-135M"
ACTIONS = ["TAKEOFF","LAND","HOVER","MOVE","TURN","UP","DOWN","STOP","REFUSE"]

def _mentions(name, utt):
    u = utt.lower(); n = name.lower()
    if n in u: return "yes"
    toks = [t.strip(",.!?;:") for t in u.split()]
    for t in toks:
        if abs(len(t)-len(n)) <= 1:
            d = sum(a!=b for a,b in zip(t,n)) + abs(len(t)-len(n))
            if d <= 1: return "yes"
    return "no"

WORDNUM = {"two":2,"three":3,"five":5,"ten":10,"fifteen":15,"twenty":20,
 "thirty":30,"forty five":45,"fifty":50,"seventy five":75,"ninety":90,
 "a hundred":100,"one hundred":100,"one thirty five":135,"one fifty":150,
 "one eighty":180,"half a meter":50,"one meter":100}

def extract_params(action, utt):
    u = utt.lower(); out = {}
    u = _re.sub(r"\b(drone|number)\s+(one|two|three|four|five|six|\d)\b", "\\1", u)
    u = _re.sub(r"\bthe (first|second|third|fourth|fifth|sixth) drone\b", "drone", u)
    for w, v in sorted(WORDNUM.items(), key=lambda x: -len(x[0])):
        u = u.replace(w, str(v))
    u = _re.sub(r"(\d+(?:\.\d+)?)\s*(?:meters?|metres?|m)\b",
                lambda mo: str(int(float(mo.group(1)) * 100)), u)
    u = _re.sub(r"(\d+(?:\.\d+)?)\s*(?:feet|foot|ft)\b",
                lambda mo: str(int(float(mo.group(1)) * 30.48)), u)
    u = _re.sub(r"(\d+(?:\.\d+)?)\s*(?:inches|inch)\b",
                lambda mo: str(int(float(mo.group(1)) * 2.54)), u)
    u = _re.sub(r"(\d+(?:\.\d+)?)\s*(?:minutes?|min)\b",
                lambda mo: str(int(float(mo.group(1)) * 60)), u)
    u = _re.sub(r"(\d+(?:\.\d+)?)\s*(?:meters?|metres?|m)\b",
                lambda mo: str(int(float(mo.group(1)) * 100)), u)
    nums = [int(x) for x in _re.findall(r"\d+", u)]
    def snap(n, bins): return min(bins, key=lambda b: abs(b-n))
    def gate(n, lo, hi, unit):
        if n < lo or n > hi:
            out["range_violation"] = f"{n} {unit} outside safe {lo}-{hi} {unit}"
            return None
        return n
    def gate(n, lo, hi, unit):
        if n < lo or n > hi:
            out["range_violation"] = f"{n} {unit} outside safe {lo}-{hi} {unit}"
            return None
        return n
    if action == "MOVE":
        for d, ws in {"forward":["forward","ahead","straight"],"back":["back","reverse"],
                      "left":["left"],"right":["right"]}.items():
            if any(w in u for w in ws): out["dir"] = d; break
        out["dist"] = (snap(g, [20,30,50,75,100,150]) if (g := gate(nums[0], 10, 200, "cm")) else None) if nums else 50
    elif action == "TURN":
        out["rot"] = "counterclockwise" if any(w in u for w in ["ccw","counter","anticlock"]) else "clockwise"
        out["angle"] = (snap(g, [15,45,90,135,180]) if (g := gate(nums[0], 5, 360, "deg")) else None) if nums else 90
    elif action == "HOVER":
        out["duration"] = (snap(g, [2,3,5,10]) if (g := gate(nums[0], 1, 15, "s")) else None) if nums else 3
    elif action in ("UP","DOWN"):
        out["dist"] = (snap(g, [20,30,50,75,100,150]) if (g := gate(nums[0], 10, 200, "cm")) else None) if nums else 30
    return out

IDXWORDS = {0:"drone one, first", 1:"drone two, second", 2:"drone three, third",
            3:"drone four, fourth", 4:"drone five, fifth", 5:"drone six, sixth"}
class Head(nn.Module):
    def __init__(self, d, k, hid=384):
        super().__init__()
        self.f = nn.Sequential(nn.Linear(d,hid), nn.GELU(), nn.Dropout(0.1),
                               nn.Linear(hid,k))
    def forward(self,x): return self.f(x)

class HU:
    def __init__(self, ckpt="hu/models/hu_heads_v1.pt", roster_path="hu/roster.yaml",
                 tau_match=None, band_exec=0.85, band_confirm=0.55):
        self.tok = AutoTokenizer.from_pretrained(MODEL)
        if self.tok.pad_token is None: self.tok.pad_token = self.tok.eos_token
        self.enc = AutoModel.from_pretrained(MODEL).to(DEV).eval()
        ck = torch.load(ckpt, map_location=DEV)
        d = ck["dim"]
        self.heads = {}
        for name, k in [("action",9),("match",1),("compound",1)]:
            h = Head(d, k).to(DEV); h.load_state_dict(ck[name]); h.eval()
            self.heads[name] = h
        self.tau = tau_match if tau_match is not None else ck.get("tau", 0.5)
        self.b_exec, self.b_conf = band_exec, band_confirm
        self.roster_path = roster_path

    def roster(self):
        try: y = yaml.safe_load(open(self.roster_path)) or {}
        except FileNotFoundError: y = {}
        names = list((y.get("assignments") or {}).values())
        return names or ["Horus","Ra","Thoth"]

    @torch.no_grad()
    def _emb(self, texts):
        b = self.tok(texts, return_tensors="pt", padding=True,
                     truncation=True, max_length=64).to(DEV)
        h = self.enc(**b).last_hidden_state
        m = b["attention_mask"].unsqueeze(-1)
        mean = (h*m).sum(1)/m.sum(1)
        mx = h.masked_fill(m==0, -1e9).max(1).values
        return torch.cat([mean, mx], dim=-1).float()

    @torch.no_grad()
    def parse(self, utterance: str):
        t0 = time.monotonic_ns()
        names = self.roster()
        texts = [utterance] + [f"drone: {n} | index: {k} ({IDXWORDS.get(k,k)}) | mentioned: {_mentions(n, utterance)} | utterance: {utterance}"
                               for k, n in enumerate(names)]
        E = self._emb(texts)
        a_prob = torch.softmax(self.heads["action"](E[0:1]), -1)[0]
        a_conf, action = a_prob.max().item(), ACTIONS[a_prob.argmax().item()]
        is_comp = torch.sigmoid(self.heads["compound"](E[0:1]).squeeze()).item() > 0.5
        m_prob = torch.sigmoid(self.heads["match"](E[1:]).squeeze(-1))
        targets = [n for n, p in zip(names, m_prob.tolist()) if p > self.tau]
        t_conf = min([max(p, 1-p) for p in m_prob.tolist()] or [1.0])
        conf = min(a_conf, t_conf)
        if is_comp:
            band, reason = "REFUSE", "compound commands: coming online"
        elif action == "REFUSE":
            band, reason = "REFUSE", "non-command or unsafe utterance"
        elif not targets:
            band, reason = "REFUSE", "no addressee resolved - say a name or 'everyone'"
        elif conf >= self.b_exec:  band, reason = "EXECUTE", ""
        elif conf >= self.b_conf:  band, reason = "CONFIRM", "low confidence - confirm parse"
        else:                      band, reason = "REFUSE", "confidence too low"
        return {"utterance": utterance, "action": action,
                "params": extract_params(action, utterance), "targets": targets,
                "per_drone": {n: round(p,3) for n,p in zip(names, m_prob.tolist())},
                "confidence": round(conf,3), "band": band, "reason": reason,
                "latency_ms": round((time.monotonic_ns()-t0)/1e6, 1)}

if __name__ == "__main__":
    hu = HU()
    for u in ["Horus, take off","everyone except Ra, land","up you go",
              "this project is really taking off","thoth hover for 5 seconds",
              "Ra, move forward half a meter","Horus take off while Ra lands"]:
        r = hu.parse(u)
        print(f"[{r['band']:7s}] {r['action']:8s} {r['targets']} {r['params']} conf={r['confidence']} {r['latency_ms']}ms  <- {u!r}")
