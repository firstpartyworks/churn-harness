# Strata vs llama.cpp, and Qwen3.8-Flash-Next vs Qwen3.8-27B (2026-10-22)

One box: Dell R730, 2x Xeon E5-2600 v4 (AVX2, no AVX-512), 160 GB RAM, Tesla V100 32 GB + Tesla P40 24 GB
(the P4 in the box was not used). Model: Qwen3.8-Flash-Next, Unsloth UD-IQ4_XS, the same GGUF for both engines.
Every answer sheet is in this folder; `engine_bench.py --diff A B` reproduces every "changed" count below.

## Protocol

- `engine_bench.py`: chat completions, temperature 0, seed 0, thinking off, system prompt "Answer with only the
  letter", up to 1,024 tokens, answer = a bare letter or the last explicit "answer is / Answer: / choice is /
  option is / boxed" X. Identical for every engine (Strata has no grammar support, so the grammar-forced
  `run_bench.py` protocol cannot be used across engines).
- ARC-Challenge 500 (`arc-challenge-500.json`), MMLU-Pro 500 (`mmlu-pro-500.json`, ten options, 14 subjects),
  and a long-context ARC: the first 300 questions, each behind 110 earlier question/answer turns (8,388 tokens).
- Engines: stock llama.cpp `4d91760` (one comma-separated `--override-tensor` placement, V100 + P40 + 9 expert
  layers on CPU, `-lzm off`); Strata 0.1.39 and Strata release v0.2.2 (engine 0.1.47), int8 KV, MTP drafting
  (`--spec 4`). "Helper" = V100 main card with the P40 as a remote expert cache (`--expert-cache-device1 auto
  --remote-expert-opt`); "V100" = V100 alone with experts resident in RAM.

## Engine: does Strata change the answers?

ARC-500 (short answers):

| run | accuracy | answers changed vs stock llama.cpp |
|---|---:|---:|
| stock llama.cpp, V100+P40 | 97.0% | - |
| Strata 0.1.39 helper, run 1 / run 2 | 97.0% / 96.8% | 2 / 3 |
| Strata 0.2.2 helper | 96.8% | 1 |
| Strata 0.2.2 V100, tail skip on (default) | 96.8% | 2 |
| Strata 0.2.2 V100, tail skip off | 96.8% | 1 |
| Strata 0.2.2 V100, tail skip off + `STRATA_HC_Q8=1` | 97.2% | 1 |

Floor: Strata 0.1.39 against itself, 1 answer of 500.

Long-context ARC (300 questions at 8,388 tokens):

| run | accuracy | changed vs llama.cpp |
|---|---:|---:|
| stock llama.cpp | 99.0% | - |
| Strata 0.1.39 helper | 99.0% | 0 |
| Strata 0.2.2 V100, tail skip on | 98.7% | 1 |
| Strata 0.2.2 V100, tail skip off | 98.7% | 1 (0 vs tail skip on) |

MMLU-Pro 500 (hard; many near-ties among ten options):

| run | accuracy | no answer within 1,024 tokens |
|---|---:|---:|
| Strata 0.1.39 helper | 66.0% | 45 |
| Strata 0.2.2 helper, run 1 / run 2 | 65.2% / 66.2% | 56 / 52 |
| Strata 0.2.2 V100, tail skip on | 66.4% | 56 |
| Strata 0.2.2 V100, tail skip off | 67.2% | 46 |
| Strata 0.2.2 V100, tail skip off + HC_Q8 | 64.8% | 52 |

Floor: the same setup twice changes 36 answers (7.2%) and moved accuracy by 1.0 point. Between settings:
tail skip on/off 57, HC_Q8 on/off 55, helper vs V100 49, 0.1.39 vs 0.2.2 71. Each setting moves 13-35 near-tie
answers beyond the floor; none moves accuracy beyond what the floor allows.

Stock llama.cpp could not complete MMLU-Pro on this placement: four crashes in 75 questions, each a CUDA
"illegal memory access" in `ggml_cuda_mul_mat_id` (V100), on four different questions, two of them reproduced on
fresh servers; not explained by prompt or answer length; not yet isolated. On the 71 questions it answered:
llama.cpp 67.6%, Strata 67.6-69.0%, 7-11 answers changed (in line with the floor).

## Drafting (MTP)

Strata 0.2.2 in its deterministic mode (`--expert-cache 1500 --adapt-every 100000 --pcie-frac 0 --suffix-draft 0`,
tail skip, prompt CPU share and fused prompt kernels off), 5 prompts, greedy, 300 tokens. Drafting on (`--spec 4
--mtp`, 81-295 drafts per prompt) and drafting off (`--spec 2`, no MTP layer, 0 drafts) are each byte-identical
run to run, but differ from each other on all 5 prompts, at near-ties ("merged non-overlapping" vs "merged,
non-overlapping"; "spun swift" vs "sang smooth"). Verifying a window of tokens in one batch rounds differently
from one token at a time. Drafting keeps only tokens the model would have chosen, but it is not bit-identical to
running without it.

## Speed (median of 3; 200 new tokens, greedy; tokens/s)

| setup | story | code | 8K-doc summary | 9,750-token prompt read |
|---|---:|---:|---:|---:|
| stock llama.cpp, V100+P40 (9 expert layers on CPU), no drafting | 24.3 | 24.3 | 21.6 | 232 |
| Strata 0.1.39 helper | 42.0 | 55.2 | 52.9 | 1,040 |
| Strata 0.2.2 helper | 68.6 | 90.7 | 69.5 | 968 |
| Strata 0.2.2 V100, tail skip on | 39.5 | 45.7 | 39.7 | 998 |
| Strata 0.2.2 V100, tail skip off | 39.3 | 44.3 | 39.7 | 1,001 |
| Strata 0.2.2 V100, tail skip off + HC_Q8 | 37.6 | 42.3 | 38.0 | 998 |
| Qwen3.8-27B Q6_K, stock llama.cpp, V100, no drafting | 25.6 | 25.6 | 24.5 | 802 |

Same GGUF, same two cards: Strata 0.2.2 helper over stock llama.cpp is 2.8x (story), 3.7x (code), 3.2x
(document) decode and 4.2x prompt reading. The llama.cpp speed run (2026-10-23, fresh server) did not crash.

0.1.39 -> 0.2.2 on the helper setup: the same expert hit rate (99%+) and draft acceptance; per 200-token reply
generation fell from 4.0-5.4 s to 2.6-3.4 s while the V100's wait on the P40 fell only from 0.49-0.92 s to
0.44-0.71 s, so most of the gain is on the V100's own work. Tail skip: its banner reads ON in the helper setup
but no expert was skipped there; on the V100 alone it skipped 168,180 experts during ARC and gave 0-3% decode.

## Model: Qwen3.8-Flash-Next vs Qwen3.8-27B

Prediction and outcome: `PREDICTION-model-arm.md` (prediction committed before the 27B ran). MMLU-Pro, thinking
off: Flash-Next 64.8-67.2% (five Strata runs) vs 27B 60.6%; recall subjects 81-83% vs 80.0%, calculation subjects
51-57% vs 45.7%. ARC: 96.8-97.2% vs 96.0% (14 answers differ, against 1-3 between engines). With thinking off,
Flash-Next still worked 99 of 500 MMLU-Pro answers out in visible text; the 27B answered 498 with a bare letter.
On the 130 calculation questions Flash-Next also answered at once, it led 60.0% to 51.5%.
