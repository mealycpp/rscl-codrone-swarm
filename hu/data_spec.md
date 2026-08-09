# HU Dataset Generation Specification v1.1
Companion to grammar.md. Every datapoint-generation mechanism must satisfy
the Four Rules; every register must have a Documented Basis and a Slice Metric.

## The Four Rules (admission criteria for any transform)
R1. LABEL INVARIANCE — a transform may change surface form only; the ground
    truth (action, params, target set) must remain recoverable and unchanged.
    A transform that can silently alter meaning is rejected.
R2. DOCUMENTED BASIS — each register models production phenomena documented in
    the SLA / communications literature, cited below. No invented dialects.
R3. NO CARICATURE — we model syntax, morphology, and lexical code-switching
    (real loanwords used by bilinguals). We never model phonology-in-spelling
    ("dees drone" is banned). Grammar transfer is linguistics; eye-dialect is
    stereotype.
R4. MEASURABILITY — every register is its own template family (fam_*), held
    out by the family split, reported as its own evaluation slice. A register
    without a number does not exist.

## Registers and their bases
1. CANONICAL (native, 3 vocative positions) — baseline register. ~55% of
   positives after all shares; the majority anchor (transformed total <= 35%).
2. TELEGRAPHIC (~20% of positives) — brevity under operational load.
   Basis: ICAO standard radiotelephony phraseology; ATC brevity conventions —
   operator language under load is clipped, verb-first, function-word-poor.
3. STRESS (negative-bank subtype; unaddressed LAND/STOP -> ALL) — repetition,
   bare imperatives, urgency markers. Basis: emergency-communication studies
   of distress calls (repetition, ellipsis under arousal). Policy basis:
   risk-asymmetric gating — ambiguity resolves toward the safe direction only.
4. GENERIC L2 "nonnative" (~20%) — L1-agnostic interlanguage phenomena.
   Basis: error-analysis tradition (Corder 1967; Selinker 1972, interlanguage):
   article insertion/omission, preposition transfer, infinitive/gerund
   confusion ("make X to land"), filler insertion, clause-order flips,
   repetition disfluency. Max 2 transforms per utterance (R1 protection).
5. ARABIC-L1 (~8%) — case study 1 (RSCL operator population).
   Basis: Swan & Smith, *Learner English* (CUP), Arabic-speakers chapter:
   VSO order transfer (Arabic verb-initial), copula/progressive transfer
   ("Horus is landing now" as imperative), article transfer. Code-switch
   tokens: yalla, tayeb, khalas — documented Egyptian Arabic discourse
   markers in bilingual speech. khalas maps to STOP (semantic: "enough").
6. SPANISH-L1 (~7%) — case study 2 (regional operator population).
   Basis: Swan & Smith, Spanish/Catalan-speakers chapter: para+infinitive
   transfer ("for to land"), subject pro-drop, 3sg -s overgeneralization.
   Code-switch: vamos, oye, ya, andale.
7. TYPOS (10% char-level, all registers) — drop/swap/substitute, incl. names
   ("thot"). Basis: standard typing-error models; R1 preserved by mention
   matching with edit-distance 1.

## Quantitative rules
- Shares: canonical remains majority; transformed registers total <= 35%.
- Stacking cap: <= 2 transforms per utterance (realism + R1).
- Exclusions oversampled x3 (difficulty-weighted sampling; hardest slice).
- Negatives 25-30%, 1/3 hard near-misses (idioms, embedded names, absent names).
- Splits: BY TEMPLATE FAMILY and BY NAME (8 held-out names). Never by row.
- Seeded generation (seed 13): byte-reproducible datasets.

## Verification
validate_dataset.py enforces R1 mechanically on every generated row:
names in NAMES-rows still present (edit-distance <= 1) in the utterance;
param numbers still extractable; ALL/EMPTY semantics intact. Rows failing
invariants are counted and the build fails above 0.5%.

## Extension rule
A new L1 register requires: a Swan & Smith (or equivalent) basis, transforms
passing R1-R4, a share <= 8%, and its slice reported. Cost: ~20 lines + regen.
