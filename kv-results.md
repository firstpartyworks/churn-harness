# KV-cache quant answer-churn — results (run 2026-08-11, finding #36)

Follow-up to [results.md](results.md) (weight-quant churn, video #7): same
instrument — 500 ARC-Challenge questions, temp 0, seed 0, grammar-forced
single-letter answers, `cache_prompt: false` — but weights held constant while
the KV cache type walks f16 → q8_0 → q4_0 (`--cache-type-k/-v`), plus K-only /
V-only splits. Determinism verified per model: the f16 baseline re-run is
byte-identical (0/500 mismatches, every model), so **every flip below is an
exact count with zero run-to-run noise** — the Wilson CIs speak to
generalization beyond these 500 questions, not measurement error.

Main grid: vanilla llama.cpp **432d7ff** (/bulk/bench rig, stock upstream),
V100 32GB, `-ngl 99 -c 2048 -fa on --parallel 4`. TurboQuant suite: PR #21089
build **0aae7d7** (separate checkout — NOT the bench rig), P40. Full flag sets
and model files in `results/kv-meta.json`; per-question matrices in
`results/kv-*.json`; aggregates in `results/kv-analysis.json`.

Models (weights fixed per model, never requantized mid-experiment):
- Qwen2.5-7B-Instruct — F16 weights (same file as the video #7 run)
- Mistral-7B-Instruct-v0.3 — F16 weights (same file as the video #7 run)
- Qwen3.6-27B — stock Q8_0 weights, rendered with thinking disabled
  (template verified closed `<think></think>` — an open think block turns the
  grammar-forced letter into noise; the harness now refuses to run in that state)

## Qwen3.6-27B (Q8_0 weights, n=500)

| cache mode | accuracy | 95% CI | changed vs f16 | flip rate (95% CI) | lost | gained | CA |
|---|---|---|---|---|---|---|---|
| f16 (baseline) | 97.6% | 95.9–98.6% | — | — | — | — | — |
| q8_0 K+V | 97.4% | 95.6–98.5% | 1 | 0.2% (0.0–1.1%) | 1 | 0 | 0.974 |
| q4_0 K+V | 97.2% | 95.4–98.3% | 2 | 0.4% (0.1–1.5%) | 2 | 0 | 0.972 |
| q4_0 K only | 97.6% | 95.9–98.6% | **0** | 0.0% (0.0–0.8%) | 0 | 0 | 0.976 |
| q4_0 V only | 97.4% | 95.6–98.5% | 1 | 0.2% (0.0–1.1%) | 1 | 0 | 0.974 |

## Mistral-7B-Instruct-v0.3 (F16 weights, n=500)

| cache mode | accuracy | 95% CI | changed vs f16 | flip rate (95% CI) | lost | gained | CA |
|---|---|---|---|---|---|---|---|
| f16 (baseline) | 75.4% | 71.4–79.0% | — | — | — | — | — |
| q8_0 K+V | 75.6% | 71.7–79.2% | 4 | 0.8% (0.3–2.0%) | 1 | 2 | 0.752 |
| q4_0 K+V | 74.4% | 70.4–78.0% | **34** | 6.8% (4.9–9.3%) | 16 | 11 | 0.722 |
| q4_0 K only | 73.4% | 69.4–77.1% | 35 | 7.0% (5.1–9.6%) | 20 | 10 | 0.714 |
| q4_0 V only | 75.6% | 71.7–79.2% | 8 | 1.6% (0.8–3.1%) | 2 | 3 | 0.750 |

## Qwen2.5-7B-Instruct (F16 weights, n=500)

| cache mode | accuracy | 95% CI | changed vs f16 | flip rate (95% CI) | lost | gained | CA |
|---|---|---|---|---|---|---|---|
| f16 (baseline) | 92.0% | 89.3–94.1% | — | — | — | — | — |
| q8_0 K+V | 92.0% | 89.3–94.1% | **0** | 0.0% (0.0–0.8%) | 0 | 0 | 0.920 |
| q4_0 K+V | **24.2%** | 20.6–28.1% | **375** | 75.0% (71.0–78.6%) | 351 | 12 | 0.218 |
| q4_0 K only | 24.8% | 21.2–28.8% | 373 | 74.6% (70.6–78.2%) | 346 | 10 | 0.228 |
| q4_0 V only | 91.8% | 89.1–93.9% | 1 | 0.2% (0.0–1.1%) | 1 | 0 | 0.918 |

## The story the numbers tell

1. **q8_0 cache is measurably free on every model tested**: 0 / 4 / 1 flips
   in 500 across Qwen2.5 / Mistral / Qwen3.6-27B. "Run q8_0 KV" graduates
   from folk wisdom to a measured claim (at this context depth).
2. **q4_0 cache is model-dependent — the full spectrum in one flag**:
   - Qwen3.6-27B: rounding error (0–2 flips). The sensitivity is FIXED in
     this generation, at short context.
   - Mistral-7B: the video-#7 story again, now for cache — accuracy moves
     1.0pt (CIs overlap heavily; the scoreboard shrugs) while 34/500 answers
     silently change.
   - Qwen2.5-7B: catastrophic collapse to below random chance (4 choices,
     24.2%). Not churn — destruction. The server stays healthy, tokens
     stream at full speed, nothing on any dashboard moves.
3. **The K cache carries the damage, everywhere it exists**: q4_0 K-only ≈
   the full collapse/churn; q4_0 V-only ≈ baseline (1/8/1 flips). Matches
   the mechanism in arXiv 2607.08734 (K/Q projections most
   quant-sensitive) and the known extreme-outlier channels in Qwen2.5 K
   activations (the reason KIVI-style methods quantize K per-channel).
4. **The Qwen2.5 collapse is real behavior, not a rig artifact** — the
   full verification chain: reproduced on V100/sm70 AND P40/sm61; with
   flash attention on AND off; with cache ops on CUDA AND forced to CPU
   (`-nkvo` — identical 334/500 wreckage, same binary); on three binaries
   (stock 432d7ff, stock e3546c7-era P40 build, PR 0aae7d7). Coherence
   probe (no grammar): stuttering repetition loops, multilingual token
   intrusions ("pérdida pérdida", "重要因素"), broken syntax — at full
   generation speed.

## TurboQuant (PR #21089, commit 0aae7d7) — the fix that isn't shippable yet

Tested on its own build, P40, with its own f16 baseline (the PR trails
upstream; cross-binary diffs are not valid). All legs `-nkvo` because **the
PR has no CUDA kernels for its cache types** — serving on a GPU rig aborts at
startup (`buffer (CUDA0) that cannot run the operation (SET_ROWS)`). That is
finding one: today you cannot run TurboQuant KV on a GPU at all.

Finding two — in our hands, the PR snapshot does not rescue the collapse
(n=500, Qwen2.5-7B, f16-nkvo baseline 92.0%, determinism PASS):

| cache mode | accuracy | changed vs f16 |
|---|---|---|
| q4_0 K only (control) | 31.4% | 334 |
| tbq4_0 K only | 26.0% | 368 |
| tbq4_0 K+V | 23.4% | 385 |
| tbq3_0 K+V | 24.4% | 381 |
| tbq4_0 K only, `-fa off` | 26.4% | 370 |

SCOPE GUARD: this measures the unmerged PR code as it exists today, NOT the
TurboQuant paper's method claims — we cannot distinguish an incomplete
implementation from a method limit here, and the video must not claim
"TurboQuant doesn't work," only "the code you can get today is not mainline,
cannot serve on GPU, and did not rescue this model in our test."

## Ternary-lab fork: Bonsai + our tq3_0 port (run 2026-08-12)

Fork = /bulk/ternary-lab/llama.cpp @ 8fb14733e — carries OUR TurboQuant-family
cache type `tq3_0` (lucebox WHT port + packed-decode CUDA work; ~3-bit,
predates and is unrelated to the upstream PR's tbq naming). NOT the stock
rig; self-contained per model with own f16 baselines + determinism repeats
(both PASS) on the V100. Label all of this on-screen as our fork.

**Ternary-Bonsai-27B Q2_g64** (stock ternary QAT — the production config,
n=500): baseline 93.8%. q8_0 K+V: **0 changed**. q4_0 K+V: 1 changed.
q4_0 K only: 5. **tq3_0 K+V: 6 changed (93.2%)** — six flips in 500 at
~3 bits per cache element, on a model already at 2-bit weights. Coherence
probes clean. The 2-bit-weights + 3-bit-cache stack is behaviorally sound.

**Qwen2.5-7B on the same fork**: f16 baseline 92.0% (matches stock rig
exactly). q4_0 K+V: 24.2%, 375/500 changed — the collapse reproduces with
identical numbers on a fourth binary. **tq3_0 K+V: 25.4%, 376/500 changed —
our port does NOT rescue the collapser either**, with its own distinct
failure texture (modal-verb loops vs q4_0's word-intrusion loops).

Combined with the upstream PR result: two independent TurboQuant/WHT
implementations, same verdict on this model. The rotation trick does not
save Qwen2.5's K cache at 3–4 bits — and the SAME tq3_0 that fails there is
6-flips-clean on Bonsai. Model-dependence is the entire story; no sub-8-bit
cache setting tested is universally safe.

## Deep context — Qwen3.6-27B (run 2026-08-12)

The short-context all-clear on 3.6-27B contradicts real-world reports
(John's own long-session experience included) of q4-cache degradation. The
depth leg re-asks the last 400 questions from inside a genuine quiz
session: the first 60/100 questions of the set rendered as user/assistant
chat history (no target overlaps the pad; no answer leakage), stock rig,
Q8_0 weights, `--parallel 1`, prefix caching (rep2 must be — and was —
byte-identical through the cached-prefix path).

At **4,886 tokens deep** (60-question pad, n=400): q8_0 K+V changed **0**
answers vs the deep-f16 baseline; q4_0 K+V changed **0**. Depth alone
(f16 short vs f16 deep, same questions) moved 6/400 answers — context
reshapes a few decisions before quantization is even involved, and then
cache quantization at this depth adds nothing.

At **7,806 tokens deep** (100-question pad, n=400): q8_0 still **0**
changed; q4_0 K+V changes its **first answer — 1/400** (Mercury_416379,
equatorial-Pacific upwelling → atmospheric CO2: correct A at f16-deep,
flips to wrong D at q4-deep; a lost answer, not a swap between wrongs).

**Agentic-scale rungs** (pad drawn from the remaining 665 questions of the
real ARC-Challenge test set — `arc-challenge-padpool.json`, zero overlap
with targets; pad sized by the model's own tokenizer; every depth's rep2
byte-identical):
- **20,551 tokens** (286-question session): q8_0 **0/400**; q4_0 **1/400 —
  the SAME question as at 7.8K** (Mercury_416379 again).
- **41,037 tokens** (563-question session): q8_0 **0/400**; q4_0 **1/400 —
  a different question (Mercury_SC_415006), flipped wrong→right** (a
  gained answer; Mercury_416379 healed).

The full curve on 3.6-27B q4_0 cache: 2 flips at 2K (n=500), then
0 → 1 → 1 → 1 at 4.9K/7.8K/20.5K/41K (n=400). **It does not accumulate —
the damage flat-lines at ~0.25% and behaves like decision-boundary jitter**
(one marginal question flips at two depths, heals at the third while
another flips the opposite direction). An earlier draft of this file
called the 7.8K flip an "onset point"; the 20K/40K rungs refute the
implied climb — do not script any depth-escalation narrative for this
model. Meanwhile **q8_0 = 0 flips at every depth: 1,600 deep-context
comparisons through 41K tokens without one changed answer.**

Scope: this bounds MC answer-selection with a quantized PREFILL cache.
Real sessions also stream thousands of DECODED tokens through the
quantized cache; generation-quality degradation there remains untested by
this instrument (and by every published flip metric). Reported real-world
q4-cache degradation on this model most plausibly lives on that axis —
say exactly this on camera, with the 41K receipts behind it.

## Compound: Q4 weights x Q4 cache (run 2026-08-12, stock rig, short context)

Completes the 2x2 factorial with video #7. Both models' rep2 checks PASS.
Flip sets vs the original full-weight/f16-cache baseline: W = weights-only
flips, C = cache-only flips, B = both-quantized flips.

**Mistral-7B** (Q4_K_M weights replicate video #7 exactly — 36 flips):
| config | accuracy | changed vs F16w+f16c |
|---|---|---|
| F16w + f16 cache | 75.4% | — |
| Q4_K_M w + f16 cache | 75.0% | 36 |
| F16w + q4_0 cache | 74.4% | 34 |
| **Q4_K_M w + q4_0 cache** | **73.0%** | **46** |

Set algebra: overlap W∩C = 12; union = 58; **17 compound-only flips**
(questions NEITHER factor flips alone — genuine interaction, not
addition); 29 of the union's flips HEAL under the compound (errors
partially cancel). Net: the compound config changes 9.2% of answers —
more than either factor alone, less than their sum — and the accuracy
CIs STILL overlap the baseline (73.0% [69.0–76.7] vs 75.4% [71.4–79.0]).
The scoreboard shrugs at every cell of the factorial; the answer sheet
never does.

**Qwen3.6-27B** — the "27B on a 24GB card" config (Q4_K_M weights +
q4_0 cache; weight effect measured vs the Q8_0-weight baseline, the
closest full-precision stand-in that fits a 32GB card): W = 2, C = 2,
B = **3 changed in 500** (97.4% vs 97.6%), zero compound-only flips.
The people's config is measurably fine on this model.

Scope honesty for the script: this bounds MC answer-selection at the
depths tested. Reported real-world degradation may live deeper still, or —
more likely — in open-ended generation quality over accumulating
DECODED tokens (a live session writes its own output through the
quantized cache turn after turn; this instrument prefills the pad and
generates 2 tokens). No flip-counter sees generation quality. Say so.

## Showcase flips (payoff shot candidates, Mistral q4_0)

- **"The best way to separate salt from water"** (Mercury_7212398): B
  (evaporation) at f16/q8_0 → D at q4_0 K+V. Viewer-verifiable in the head.
- **"When the temperature of a sample of water is -5°C, the water is"**
  (MCAS_2005_5_25): C (solid) at f16/q8_0 → B at q4_0. Ice stops being ice.
- 14 more in `results/kv-analysis.json` → `showcase`.
- Qwen3.6-27B's LONE flip across 2,500 answer-pairs (Mercury_7034843,
  periodic-table left-side property, B→A at q4_0 K+V only) — the "we found
  exactly one" beat.

## Honesty guardrails (for the script)

- Scope: short context (~150–400-token prompts). Cache-quant error grows
  with tokens in cache; this instrument says NOTHING about long-context
  behavior — say so explicitly. John's own observed q4-cache degradation on
  Qwen3.6 in real (long) sessions is consistent with damage living at depth
  this test cannot reach. Do not extrapolate the 27B all-clear to long
  context.
- One benchmark, letter-answer MC protocol, chat-style — same scope
  language as video #7.
- Accuracy deltas within overlapping CIs are never "significant" on screen;
  the flip counts are the story.
- The TurboQuant scope guard above is mandatory phrasing.
- Cite: Dutta et al. 2407.09141 (flips metric), arXiv 2607.08734 (K/Q
  sensitivity mechanism), TurboQuant paper + PR #21089 + discussion #20969
  (status as of 2026-08-11).
- Hardware claims: two Dell R730s (V100 32GB, P40 24GB, P4 8GB). Nothing else.

## Runtime

Whole stock grid (3 models × 5 modes + 3 determinism repeats, 9,000
questions): ~90 min GPU time (7B ≈ 0.12 s/q V100; 27B ≈ 1.05 s/q). The
TurboQuant suite adds ~50 min on the P40. "Check us yourself tonight" holds.
