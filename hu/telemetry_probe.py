#!/usr/bin/env python3
"""telemetry_probe.py — first-connect instrument audit.
Calls every get_* on a REAL drone, with per-call timeout, and writes
hu/data/telemetry_probe_<port>.json: value, type, latency, verdict.
Run:  python3 hu/telemetry_probe.py [/dev/ttyACM0]
"""
import sys, json, time, signal, inspect, os

PORT = sys.argv[1] if len(sys.argv) > 1 else None

class Timeout(Exception): pass
def _alarm(sig, frm): raise Timeout()
signal.signal(signal.SIGALRM, _alarm)

def probe_call(fn, timeout_s=3):
    t0 = time.monotonic()
    signal.alarm(timeout_s)
    try:
        v = fn()
        ms = (time.monotonic() - t0) * 1000
        r = repr(v)
        return {"ok": True, "ms": round(ms, 1), "type": type(v).__name__,
                "value": r[:120] + ("..." if len(r) > 120 else "")}
    except Timeout:
        return {"ok": False, "error": f"TIMEOUT>{timeout_s}s"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:120]}
    finally:
        signal.alarm(0)

def main():
    from codrone_edu.drone import Drone
    d = Drone()
    print(f"pairing{' on ' + PORT if PORT else ' (auto-detect)'}...")
    d.pair(PORT) if PORT else d.pair()
    print("paired. probing 70 getters (drone stays on the ground)...\n")
    getters = sorted(n for n, f in inspect.getmembers(d, inspect.ismethod)
                     if n.startswith("get_"))
    report = {}
    for name in getters:
        report[name] = probe_call(getattr(d, name))
        tag = "OK  " if report[name]["ok"] else "FAIL"
        detail = (f'{report[name].get("ms","")}ms {report[name].get("type","")} '
                  f'{report[name].get("value", report[name].get("error",""))}')
        print(f"  [{tag}] {name:28s} {detail}")
    try: d.close()
    except Exception: pass
    os.makedirs("hu/data", exist_ok=True)
    out = f"hu/data/telemetry_probe_{(PORT or 'auto').replace('/','_')}.json"
    json.dump(report, open(out, "w"), indent=1)
    ok = sum(1 for r in report.values() if r["ok"])
    print(f"\n{ok}/{len(report)} getters live -> {out}")
    print("Paste the FAIL lines + a few OK lines to Claude for the schema patch.")

if __name__ == "__main__":
    main()
