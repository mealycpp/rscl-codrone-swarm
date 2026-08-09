#!/usr/bin/env python3
"""hu_api.py — HU command endpoint + minimal command window.
Run:  uvicorn hu.gateway.hu_api:app --host 0.0.0.0 --port 8100
Wire: replace dispatch() body with your fleet-manager call."""
import csv, os, time, uuid
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from hu.gateway.hu_service import HU

app = FastAPI()
hu = HU()
LOG = "experiments/logs/hu_live.csv"
os.makedirs("experiments/logs", exist_ok=True)
FIELDS = ["ts","cmd_id","utterance","action","targets","params","confidence",
          "band","reason","parse_ms","dispatched","operator_confirmed"]
if not os.path.exists(LOG):
    csv.writer(open(LOG,"w",newline="")).writerow(FIELDS)

def log_row(**kw):
    csv.writer(open(LOG,"a",newline="")).writerow([kw.get(f,"") for f in FIELDS])

def dispatch(action, targets, params):
    """WIRE HERE: call your fleet manager exactly as the dashboard buttons do.
    e.g. for t in targets: fleet.send(t, action, params)"""
    print(f"[DISPATCH-STUB] {action} -> {targets} {params}")
    return True

class Cmd(BaseModel):
    utterance: str
class Confirm(BaseModel):
    cmd_id: str; action: str; targets: list; params: dict

PENDING = {}

@app.post("/hu/command")
def command(c: Cmd):
    r = hu.parse(c.utterance)
    cid = uuid.uuid4().hex[:8]
    dispatched = False
    if r["band"] == "EXECUTE":
        dispatched = dispatch(r["action"], r["targets"], r["params"])
    elif r["band"] == "CONFIRM":
        PENDING[cid] = r
    log_row(ts=time.time(), cmd_id=cid, utterance=c.utterance, action=r["action"],
            targets="|".join(r["targets"]), params=str(r["params"]),
            confidence=r["confidence"], band=r["band"], reason=r["reason"],
            parse_ms=r["latency_ms"], dispatched=dispatched, operator_confirmed="")
    return {"cmd_id": cid, **r, "dispatched": dispatched}

@app.post("/hu/confirm")
def confirm(c: Confirm):
    PENDING.pop(c.cmd_id, None)
    ok = dispatch(c.action, c.targets, c.params)
    log_row(ts=time.time(), cmd_id=c.cmd_id, utterance="(confirmed)",
            action=c.action, targets="|".join(c.targets), params=str(c.params),
            band="EXECUTE", dispatched=ok, operator_confirmed="yes")
    return {"dispatched": ok}

@app.get("/hu", response_class=HTMLResponse)
def window():
    return """<!doctype html><html><head><title>HU — Command the Fleet</title><style>
body{font-family:monospace;background:#101418;color:#e8e0c8;max-width:760px;margin:2em auto}
h2{color:#d4af37} input{width:70%;padding:.6em;background:#1a2026;color:#e8e0c8;border:1px solid #d4af37}
button{padding:.6em 1.2em;background:#d4af37;border:0;cursor:pointer;font-weight:bold}
.EXECUTE{color:#7cd992}.CONFIRM{color:#e8c547}.REFUSE{color:#e57373}
#hist div{margin:.4em 0;border-left:3px solid #333;padding-left:.6em}</style></head>
<body><h2>&#x1F441; HU &mdash; speak, and it is so</h2>
<input id="u" placeholder="Horus, take off" onkeydown="if(event.key==='Enter')send()">
<button onclick="send()">Send</button><div id="hist"></div><script>
async function send(){const u=document.getElementById('u');const t=u.value;if(!t)return;u.value='';
const r=await(await fetch('/hu/command',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({utterance:t})})).json();render(t,r);}
function render(t,r){const h=document.getElementById('hist');const d=document.createElement('div');
let x=`<b>&raquo; ${t}</b><br><span class="${r.band}">[${r.band}]</span> ${r.action} &rarr; {${r.targets.join(', ')}} `+
`${JSON.stringify(r.params)} conf=${r.confidence} ${r.parse_ms}ms`;
if(r.reason)x+=`<br><i>${r.reason}</i>`;
if(r.band==='CONFIRM')x+=`<br><button onclick='conf("${r.cmd_id}",${JSON.stringify(r.action)},`+
`${JSON.stringify(r.targets)},${JSON.stringify(r.params)},this)'>&#x2713; Confirm</button>`;
d.innerHTML=x;h.prepend(d);}
async function conf(id,a,tg,p,btn){await fetch('/hu/confirm',{method:'POST',
headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd_id:id,action:a,targets:tg,params:p})});
btn.outerHTML='<span class="EXECUTE">dispatched</span>';}
</script></body></html>"""
