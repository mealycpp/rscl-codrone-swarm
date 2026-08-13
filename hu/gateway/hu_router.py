#!/usr/bin/env python3
"""hu_router.py — mounts HU into the existing swarm web app (same process,
same controller, same safety path as the dashboard buttons)."""
import csv, os, time, uuid
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from hu.gateway.hu_service import HU

LOG = "experiments/logs/hu_live.csv"
FIELDS = ["ts","cmd_id","utterance","action","targets","params","confidence",
          "band","reason","parse_ms","dispatched","operator_confirmed","dispatch_error","source"]

def _log(**kw):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    new = not os.path.exists(LOG)
    w = csv.writer(open(LOG, "a", newline=""))
    if new: w.writerow(FIELDS)
    w.writerow([kw.get(f, "") for f in FIELDS])

# ---- HU dialect -> fabric dialect ----
def translate(action, params):
    if action == "TAKEOFF": return [("takeoff", {})]
    if action == "LAND":    return [("land", {})]
    if action == "HOVER":   return [("hover", {"duration": params.get("duration", 3)})]
    if action == "STOP":    return [("hover", {"duration": 0.5})]   # abort-to-hover; e-stop NEVER via language
    if action == "MOVE":
        cmd = {"forward":"forward","back":"backward","left":"left","right":"right"}[params.get("dir","forward")]
        return [(cmd, {"distance_cm": params.get("dist", 50)})]
    if action == "TURN":
        cmd = "turn_right" if params.get("rot","clockwise") == "clockwise" else "turn_left"
        return [(cmd, {"degrees": params.get("angle", 90)})]
    if action in ("UP", "DOWN"):
        return [(action.lower(), {"distance_cm": params.get("dist", 30)})]
    return None

def make_hu_router(controller_holder, name_map=None):
    _NM_DEFAULT = {"Horus": "D0", "Ra": "D1", "Thoth": "D2"}
    _AIR = {"AIRBORNE", "HOVER", "TAKING OFF"}
    _NEED_AIR = {"MOVE", "TURN", "UP", "DOWN", "HOVER"}

    def _drone_states():
        out = {}
        ctrl = getattr(controller_holder, "controller", None) or \
               getattr(controller_holder, "backend", None) or controller_holder
        for attr in ("drones", "workers", "agents"):
            seq = getattr(ctrl, attr, None)
            if not seq: continue
            it = seq.values() if hasattr(seq, "values") else seq
            for w in it:
                st = getattr(w, "state", w)
                did = getattr(st, "drone_id", None) or getattr(w, "drone_id", None)
                if did: out[did] = str(getattr(st, "flight_state", "UNKNOWN")).upper()
            if out: break
        return out

    def do_dispatch(action, names, params):
        act = str(action).upper()
        if act in ("LAND", "STOP"):
            return _do_dispatch_raw(action, names, params)
        states = _drone_states(); nm = name_map or _NM_DEFAULT
        eligible, skips = [], []
        for n in names:
            fs = states.get(nm.get(n, n), "UNKNOWN")
            if fs == "UNKNOWN":
                eligible.append(n); continue
            if fs == "DETACHED":
                skips.append(f"{n}: not connected"); continue
            airborne = fs in _AIR
            if act == "TAKEOFF" and airborne:
                skips.append(f"{n}: already airborne"); continue
            if act in _NEED_AIR and not airborne:
                skips.append(f"{n}: on the ground - take off first"); continue
            eligible.append(n)
        if not eligible:
            return False, "; ".join(skips) or "no eligible drones"
        ok, err = _do_dispatch_raw(action, eligible, params)
        if skips:
            err = ((str(err) + " | ") if err else "") + "skipped: " + "; ".join(skips)
        return ok, err

    """name_map: HU name -> fabric target id, e.g. {"Horus":"D0","Ra":"D1","Thoth":"D2"}"""
    router = APIRouter()
    hu = HU()
    nmap = name_map or {"Horus": "D0", "Ra": "D1", "Thoth": "D2"}
    pending = {}

    def _do_dispatch_raw(action, targets, params):
        steps = translate(action, params)
        if steps is None:
            return False, "vertical motion not exposed by fabric v1"
        try:
            for hu_name in targets:
                fid = nmap.get(hu_name)
                if fid is None:
                    return False, f"{hu_name} has no fabric mapping"
                for cmd, p in steps:
                    controller_holder["controller"].command(fid, cmd, p)
            return True, ""
        except KeyError as e:
            return False, f"unknown fabric target: {e}"
        except RuntimeError as e:
            return False, str(e)

    @router.post("/api/hu/command")
    async def hu_command(request: Request):
        data = await request.json()
        utt = str(data.get("utterance", ""))
        # EMERGENCY channel: bare safety utterances act fleet-wide, no gating.
        # Fires only in the safe direction (land/stop); never takeoff/move.
        _em = utt.lower().strip(" .!?")
        if _em in {"land", "land now", "land land land", "stop", "stop stop stop",
                   "all stop", "everybody down", "everyone down", "emergency", "abort", "khalas", "yalla land"}:
            act = "STOP" if "stop" in _em or _em == "abort" else "LAND"
            names = list(hu.roster())
            ok, derr = do_dispatch(act, names, {})
            cid = uuid.uuid4().hex[:8]
            _log(ts=time.time(), cmd_id=cid, utterance=utt, action=act,
                 targets="|".join(names), params="{}", confidence=1.0,
                 band="EMERGENCY", reason="emergency override -> fleet-wide",
                 parse_ms=0, dispatched=ok, dispatch_error=derr)
            return JSONResponse({"cmd_id": cid, "utterance": utt, "action": act,
                "targets": names, "params": {}, "confidence": 1.0,
                "band": "EMERGENCY", "reason": "emergency override -> fleet-wide",
                "latency_ms": 0, "dispatched": ok})
        src = str(data.get("source", "typed"))
        # Voice-channel ASR alias normalization (observed live transcripts).
        # Mic input only; CSV logs the raw transcript upstream of nothing — utt is replaced here.
        if src == "voice":
            import re as _re
            VOICE_ALIASES = {"rock":"Ra","prop":"Ra","roland":"Ra","raw":"Ra","rah":"Ra",
                             "taurus":"Horus","horace":"Horus","chorus":"Horus","horis":"Horus",
                             "toth":"Thoth","thought":"Thoth","thoss":"Thoth",
                             "yella":"yalla","yallow":"yalla","yellow":"yalla","yala":"yalla","ya la":"yalla"}
            for wrong, right in VOICE_ALIASES.items():
                utt = _re.sub(rf"\b{wrong}\b", right, utt, flags=_re.IGNORECASE)
        r = hu.parse(utt)
        if r.get('params', {}).get('range_violation'):
            r['band'] = 'REFUSE'
            r['reason'] = 'unsafe parameter: ' + str(r['params'].pop('range_violation'))

        cid = uuid.uuid4().hex[:8]
        dispatched, derr = False, ""
        if r["band"] == "EXECUTE":
            dispatched, derr = do_dispatch(r["action"], r["targets"], r["params"])
            if not dispatched:
                r["band"], r["reason"] = "REFUSE", derr
        elif r["band"] == "CONFIRM":
            pending[cid] = r
        _log(ts=time.time(), cmd_id=cid, utterance=utt, action=r["action"],
             targets="|".join(r["targets"]), params=str(r["params"]),
             confidence=r["confidence"], band=r["band"], reason=r["reason"],
             parse_ms=r["latency_ms"], dispatched=dispatched, dispatch_error=derr, source=src)
        return JSONResponse({"cmd_id": cid, **r, "dispatched": dispatched})

    @router.post("/api/hu/confirm")
    async def hu_confirm(request: Request):
        data = await request.json()
        cid = str(data.get("cmd_id", ""))
        r = pending.pop(cid, None)
        if r is None:
            return JSONResponse({"ok": False, "error": "unknown or expired cmd_id"}, status_code=404)
        ok, derr = do_dispatch(r["action"], r["targets"], r["params"])
        _log(ts=time.time(), cmd_id=cid, utterance="(confirmed)", action=r["action"],
             targets="|".join(r["targets"]), params=str(r["params"]), band="EXECUTE",
             dispatched=ok, operator_confirmed="yes", dispatch_error=derr)
        return JSONResponse({"dispatched": ok, "error": derr})

    return router
