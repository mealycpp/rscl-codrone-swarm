#!/usr/bin/env python3
"""flight_protocol.py — live evaluation runner.
Sends utterances to /api/hu/command, operator verifies PHYSICAL outcome.
Writes experiments/logs/hu_flight_eval.csv (the S-V dataset).
Run: python3 hu/flight_protocol.py hu/protocol_commands.txt
Keys: y = correct physical outcome | n = wrong/none | r = correct refusal | s = skip | q = quit
"""
import csv, json, os, sys, time, urllib.request

API = "http://localhost:8000/api/hu/command"
OUT = "experiments/logs/hu_flight_eval.csv"
FIELDS = ["ts","block","utterance","expected","action","targets","params",
          "confidence","band","latency_ms","dispatched","operator_verdict","note"]

def send(utt):
    req = urllib.request.Request(API, json.dumps({"utterance": utt}).encode(),
                                 {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read())

def main():
    cmds = [l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    new = not os.path.exists(OUT)
    f = open(OUT, "a", newline=""); w = csv.DictWriter(f, FIELDS)
    if new: w.writeheader()
    block = input("block label (e.g. T1-batch1): ").strip() or "B0"
    for n, line in enumerate(cmds, 1):
        expected, utt = (line.split("|", 1) + [""])[:2] if "|" in line else ("", line)
        utt = utt.strip() or line
        print(f"\n[{n}/{len(cmds)}] >>> {utt!r}   (expected: {expected or '?'})")
        try: r = send(utt)
        except Exception as e:
            print("  API ERROR:", e); continue
        print(f"  [{r['band']}] {r['action']} -> {r['targets']} {r['params']} "
              f"conf={r['confidence']} {r['latency_ms']}ms")
        if r["band"] == "CONFIRM":
            ok = input("  CONFIRM band — approve & dispatch? [y/n] ").lower().startswith("y")
            if ok:
                req2 = urllib.request.Request(API.replace("/command","/confirm"),
                        json.dumps({"cmd_id": r["cmd_id"]}).encode(),
                        {"Content-Type": "application/json"})
                c = json.loads(urllib.request.urlopen(req2, timeout=15).read())
                r["dispatched"] = c.get("dispatched", False)
                print(f"  dispatched: {r['dispatched']}")
        v = input("  verdict [y / n / r / s(kip) / q] ").strip().lower()[:1] or "s"
        if v == "q": break
        if v == "s": continue
        if v not in "ynr": v = {"c":"y"}.get(v, v)
        note = ""
        w.writerow(dict(ts=time.time(), block=block, utterance=utt, expected=expected,
                        action=r["action"], targets="|".join(r["targets"]),
                        params=str(r["params"]), confidence=r["confidence"],
                        band=r["band"], latency_ms=r["latency_ms"],
                        dispatched=r["dispatched"], operator_verdict=v, note=note))
        f.flush()
    f.close(); print(f"\nsaved -> {OUT}")

if __name__ == "__main__":
    main()
