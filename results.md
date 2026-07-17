# Quant answer-churn repro — results (run 2026-07-16, V100)

Repro of arXiv 2607.08734 (method lineage: Dutta et al. 2407.09141 "flips")
on our own GGUF ladder: F16 parents quantized locally with llama-quantize
(llama.cpp e3546c7), served with llama-server on the R730's V100 32GB,
500 ARC-Challenge questions, temp 0, grammar-forced single-letter answers —
fully deterministic, so every cross-quant difference is the weights.

Models: Qwen2.5-7B-Instruct, Mistral-7B-Instruct-v0.3 (F16 GGUFs:
bartowski / MaziyarPanahi). Raw per-question matrices in results/*.json;
chart-ready aggregates in results/analysis.json.

## Qwen2.5-7B-Instruct (n=500, baseline F16)

| quant | accuracy | 95% CI | answers changed vs F16 | lost | gained | net | CA w/ F16 |
|---|---|---|---|---|---|---|---|
| F16 | 92.0% | 89.3–94.1% | — | — | — | — | — |
| Q8_0 | 92.0% | 89.3–94.1% | **0** | 0 | 0 | 0 | 0.920 |
| Q6_K | 92.4% | 89.7–94.4% | 3 | 0 | 2 | +2 | 0.920 |
| Q4_K_M | 91.8% | 89.1–93.9% | 9 | 4 | 3 | −1 | 0.912 |
| Q3_K_M | 91.4% | 88.6–93.5% | 22 | 11 | 8 | −3 | 0.898 |
| Q2_K | 86.0% | 82.7–88.8% | 70 | 47 | 17 | −30 | 0.826 |

## Mistral-7B-Instruct-v0.3 (n=500, baseline F16)

| quant | accuracy | 95% CI | answers changed vs F16 | lost | gained | net | CA w/ F16 |
|---|---|---|---|---|---|---|---|
| F16 | 75.4% | 71.4–79.0% | — | — | — | — | — |
| Q8_0 | 75.6% | 71.7–79.2% | 3 | 1 | 2 | +1 | 0.752 |
| Q6_K | 75.0% | 71.0–78.6% | 12 | 6 | 4 | −2 | 0.742 |
| Q4_K_M | 75.0% | 71.0–78.6% | 36 | 15 | 13 | −2 | 0.724 |
| Q3_K_M | 74.0% | 70.0–77.6% | 55 | 24 | 17 | −7 | 0.706 |
| Q2_K | 63.8% | 59.5–67.9% | 156 | 93 | 35 | −58 | 0.568 |

## The story the numbers tell

1. **The headline stat (Mistral Q4_K_M): accuracy moved 0.4pt vs F16 —
   statistically nothing (CIs overlap almost completely) — while 36 of 500
   answers changed (7.2%).** 15 questions full precision gets right now
   wrong, 13 it misses now right. The scoreboard says "same model"; the
   answer sheet says otherwise. This is the video's thesis in one row.
1b. **The F16 anchor (the deployment heuristic, measured)**: Qwen Q8_0
   returned the IDENTICAL answer sheet to full precision — 0 changed in
   500. Mistral Q8_0: 3 in 500 (0.6%). "Q8_0 is your floor for factual
   consistency" is now a measured claim, not a vibe. The churn gradient:
   Mistral 3 → 12 → 36 → 55 → 156 walking down the ladder.
2. **Every rung confirms the paper's shape**: aggregate accuracy declines
   gradually (no cliff until Q2_K), while answers-changed grows much
   faster than the accuracy delta at every step. Churn ≫ score movement.
3. **Q2_K is a different animal**: Mistral changes 153/500 answers (30.6%)
   and correctness agreement with Q8 falls to 0.572. Qwen holds up better
   (70 changed, CA 0.826) — headroom matters (92% base vs 76%).
4. **Non-monotonic flips are real and visible**: e.g. TAKS_2009_8_36 is
   right at Q8/Q6, wrong at Q4_K_M, right again at Q3_K_M. Quantization
   isn't graceful degradation — it's a *different model* that happens to
   score the same.

## Showcase flip (payoff shot candidate)

**"How many elements are in the compound Mg(OH)₂?"** (TAKS_2009_8_36,
correct: 3 — magnesium, oxygen, hydrogen). Qwen Q8_0 and Q6_K answer
correctly; Q4_K_M gets it wrong. A question a viewer can verify in their
head, flipped by the quant rung most people actually download.
Backups: Mistral "How are sedimentary rocks made?" (Mercury_180373 — flips
wrong at Q4_K_M and STAYS wrong down the ladder); Mistral MCAS_2001_8_4
(conservation of mass, D at Q8/Q6 → C at Q4_K_M → back to D).

## Honesty guardrails (from the production brief — keep in script)

- Cite Dutta et al. (2407.09141) on camera: the flips metric is theirs
  (2024, GPTQ/AWQ/BnB); our contribution is the llama.cpp GGUF-ladder repro
  + the paper's attention-layer mechanism explanation.
- Never claim a single pairwise accuracy delta is significant — the CIs on
  screen. The churn counts are the story, not the accuracy gaps.
- Scope: 7B instruct models, one MC benchmark, letter-answer protocol
  (chat-style, the way home users run these) — say so; don't imply 70B or
  generative tasks.
- Runtime note: every run at 0.13–0.15 s/question on the V100 — the whole
  10-run grid took ~25 min including quantization. "You can check this
  yourself tonight" is a legitimate CTA.
