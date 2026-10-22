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
