# HU — Command Grammar v1 (frozen 2026-08-08)
Model: SmolLM2-135M frozen + heads. Laptop GPU only. No FPGA/CAP content.
ACTIONS (9): TAKEOFF, LAND, HOVER(2/3/5/10s), MOVE(F/B/L/R; 20/30/50/75/100/150cm),
TURN(15/45/90/135/180; CW/CCW), UP(dist), DOWN(dist), STOP(abort-to-hover), REFUSE.
Bins ARE the safe range; gate re-validates downstream.
TARGETS: per-drone matching query "drone:{name}|index:{k}|utterance:{text}" -> sigmoid.
Roster = runtime config (serial->sticky name). ALL/collectives -> currently-healthy set,
GUI shows expansion. Unaddressed -> empty set -> gateway refuses (never default ALL).
Roster-absent name -> empty set -> refuse aloud. Action still labeled on absent-name rows.
TIERS: T1 name, T2 index, T3 sets (ALL/pair/exclusion), T4 state-conditioned (DEFERRED v2),
T5 compounds.
REFUSE subtypes: garbage, oov capability, unsafe param, action negation (v1 = affirmative
commands only), idiom near-miss. Gateway refusals: empty set, absent/offline name,
clause conflict, low confidence.
COMPOUNDS: detector head -> splitter (while/meanwhile/then/";"; "and" splits only before
its own action verb) -> per-clause heads -> conjunction head PARALLEL|SEQUENTIAL.
Policies: ATOMICITY (any clause refuses -> all refuse, reason spoken);
OVERLAP (same drone in conflicting parallel clauses -> refuse, name the drone).
CONFIDENCE: temperature-scaled; 3 bands: execute / one-tap confirm / refuse.
Matching tau ~0.7 precision-biased. Bars: action>=98%, params>=95%, target F1>=95% on
HELD-OUT NAMES, exclusion slice>=90%, unsafe-accept<=0.5%, clean refusal<=10%, ECE<=5%,
live >=95% over 60 commands. 3 seeds, mean+-std.
SKILLS v1.1 (DEFERRED-BUT-DESIGNED): zigzag/square/orbit = deterministic compositions
with geometry closure predicates. Language selects+parameterizes, never generates
trajectories. "form X" -> path skill in v1; formation-as-shape DEFERRED (needs localization).
DATASET: 8k rows, 25-30% negatives (1/3 hard near-miss), telegraphic>=20%, vocative
pre/post/mid, typos 10%, exclusions oversampled, splits BY FAMILY and BY NAME (5 held out).
AUTO-SCALE: udev/poll watcher -> dynamic worker spawn -> sticky names -> joining drone
grounded until telemetry healthy. Model unchanged at any N.
