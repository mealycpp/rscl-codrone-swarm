#!/usr/bin/env python3
"""bench_scale.py — parse latency vs fleet size N (synthetic rosters, frozen model)."""
import time, statistics
from hu.gateway.hu_service import HU

POOL = ["Horus","Ra","Thoth","Sobek","Anubis","Osiris","Isis","Seth","Bastet","Khonsu",
 "Ptah","Amun","Geb","Nut","Hathor","Maat","Nefertum","Khepri","Atum","Montu","Sekhmet",
 "Nephthys","Anhur","Aten","Bes","Hapi","Khnum","Menhit","Min","Mut","Nekhbet","Nun",
 "Pakhet","Renenutet","Satet","Seshat","Sopdu","Taweret","Wepwawet","Heka","Tefnut",
 "Shu","Serqet","Wadjet","Neith","Kek","Heh","Apis","Sia","Hu"]

hu = HU()
# find the roster attribute (implementation-tolerant)
attr = next((a for a in ("names","_names","roster_names","_roster") if hasattr(hu, a)), None)
if attr is None:
    print("roster attribute not found — paste: grep -n 'def roster' -A4 hu/gateway/hu_service.py")
    raise SystemExit(1)

UTTS = ["{n}, take off", "everyone, land", "{n} and {m}, hover for 3 seconds",
        "everyone except {n}, land", "this project is really taking off"]
print(f"{'N':>4s} {'mean ms':>9s} {'p95 ms':>9s}")
for N in (3, 5, 10, 20, 50):
    setattr(hu, attr, POOL[:N])
    lat = []
    for rep in range(6):
        for u in UTTS:
            t0 = time.monotonic()
            hu.parse(u.format(n=POOL[rep % N], m=POOL[(rep+1) % N]))
            lat.append((time.monotonic()-t0)*1000)
    lat = lat[5:]  # drop warmup
    print(f"{N:4d} {statistics.mean(lat):9.1f} {sorted(lat)[int(len(lat)*0.95)]:9.1f}")
