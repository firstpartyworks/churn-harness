# Prediction, written 2026-10-22 12:27 (before any Qwen3.8-27B MMLU-Pro answer exists)

Question: on mmlu-pro-500.json, thinking off, temperature 0, engine_bench.py protocol, how does
Qwen3.8-Flash-Next (UD-IQ4_XS, ~80B of experts, ~6B active per token, plus a ~50B-parameter
per-layer lookup table) compare with dense Qwen3.8-27B (Q6_K, stock llama.cpp, V100)?

Idea being tested: total (expert) parameters behave like stored knowledge; active parameters like
the computation spent per token. Flash-Next has more storage, the 27B more computation per token.

Groups (fixed now, by MMLU-Pro category):
- RECALL (160 q): history, law, biology, psychology, health, philosophy
- CALCULATION (221 q): math, physics, engineering, chemistry
- not scored for this prediction (119 q): business, economics, computer science, other

Predictions:
1. RECALL: Flash-Next accuracy >= 27B accuracy.
2. CALCULATION: 27B accuracy > Flash-Next accuracy.
3. The gap (Flash-Next minus 27B) is larger on RECALL than on CALCULATION.

What would falsify it: prediction 3 failing (Flash-Next leading or trailing by the same amount
in both groups), which would mean the difference is overall capability, not knowledge vs computation.
Caveats fixed in advance: thinking off (the 27B may gain more from thinking than Flash-Next);
one run each, so gaps of a few questions per group are noise (the engine noise floor on ARC was
1 answer in 500, but model-vs-model differences per group need roughly 10+ questions to mean much).

## Outcome (recorded 2026-10-22 ~16:00, after the 27B MMLU-Pro run)

Flash-Next = four Strata 0.2.2 runs (V100+P40 helper; V100 tail skip on; off; off+HC_Q8). 27B = stock llama.cpp.

| group | Flash-Next (4 runs) | Qwen3.8-27B |
|---|---|---|
| RECALL (160) | 81.2-83.1% | 80.0% |
| CALCULATION (221) | 51.1-56.6% | 45.7% |
| other (119) | 65.5-67.2% | 62.2% |
| overall | 64.8-67.2% | 60.6% |

1. RECALL, Flash-Next >= 27B: HELD, narrowly (2-5 questions).
2. CALCULATION, 27B > Flash-Next: FAILED. Flash-Next leads by 5-11 points.
3. Gap larger on RECALL than on CALCULATION: FAILED. The gap is larger on calculation.

Confound checked, not the explanation: with thinking off, Flash-Next still worked 99 of 500 answers out in
visible text (and hit the 1,024-token cap on ~45), while the 27B answered with a bare letter on 498. But on
the 130 calculation questions where Flash-Next also answered at once (<= 3 tokens), it still led 60.0% to
51.5%. On the 91 where it worked the problem out, 51.6% to 37.4% (the 27B answering those at once).

Reading: on this test the larger-total model is better at both, and more so at calculation. The
knowledge-vs-computation split did not show up. Caveats as written above: thinking off for both, one run
of the 27B, quants differ (Flash-Next UD-IQ4_XS vs 27B Q6_K, i.e. the smaller-bit model won).
