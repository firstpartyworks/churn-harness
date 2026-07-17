# churn-harness

Diff the answers, not the scores. A ~130-line, dependency-free harness that
quantizes a model down the llama.cpp GGUF ladder (F16 → Q8_0 → Q6_K →
Q4_K_M → Q3_K_M → Q2_K) and diffs every individual answer against full
precision — deterministically — so you can see how many answers a quant
*changes*, not just how the benchmark score moves.

Built for a video on [The Local Ceiling](https://www.youtube.com/@TheLocalCeiling),
where we found (Mistral-7B-Instruct-v0.3, n=500 ARC-Challenge): Q4_K_M
scores the same as F16 (75.0% vs 75.4%) while quietly changing **36 of 500
answers** (15 lost, 13 gained). Full numbers in [results.md](results.md).

## The research this reproduces

- **"The Illusion of Equivalency"** (July 2026) — the GGUF-ladder study we
  reproduce: https://arxiv.org/abs/2607.08734
- **"Accuracy is Not All You Need"** (Dutta et al., Microsoft Research,
  2024) — first measured these answer changes as "flips":
  https://arxiv.org/abs/2407.09141
- Proskurina et al., NAACL Findings 2024:
  https://aclanthology.org/2024.findings-naacl.124/

Our run is independent, on locally-quantized GGUFs, on one V100. The whole
grid (2 models × 6 quants × 500 questions) took ~25 minutes of GPU time.

## Why every answer is attributable to the weights

- temperature 0, fixed seed, `cache_prompt: false`
- a GBNF grammar that forces the completion to be exactly one letter:
  `root ::= "A" | "B" | "C" | "D"`
- same prompt template via the server's `/apply-template`

Run the same quant twice and you get byte-identical answer sheets. So when
Q4_K_M answers differently from F16, the only thing that changed is the
weights.

## Install (before you run anything)

1. **Build llama.cpp** with GPU support (we used CUDA on a V100; any
   backend works):

   ```bash
   git clone https://github.com/ggml-org/llama.cpp
   cmake -B build -DGGML_CUDA=ON && cmake --build build -j
   ```

   You need `llama-server` and `llama-quantize` from `build/bin`.

2. **Download an F16 GGUF** for each model you want to test (we used the
   bartowski and MaziyarPanahi conversions from Hugging Face) into a
   models directory, named `<model>-f16.gguf`, e.g.
   `mistral-7b-instruct-v0.3-f16.gguf`. The harness quantizes the rest of
   the ladder from that parent itself — this matters, because it means
   every quant has the same lineage.

3. **Python 3.8+**. No pip installs — stdlib only.

## Quickstart

```bash
export CHURN_MODELS_DIR=/path/to/ggufs       # holds <model>-f16.gguf, quants land here
export CHURN_LLAMA_BIN=/path/to/llama.cpp/build/bin

python3 run_bench.py --model mistral --quants F16   # baseline first
python3 run_bench.py --model mistral                # then the ladder
python3 analyze.py                                  # tables + flips vs F16
```

Each (model, quant) writes `results/<model>-<QUANT>.json` — a per-question
answer matrix (`{qid: {"ans": "A", "ok": true}}`). Finished runs are
skipped on re-run, so it resumes for free. `analyze.py` prints
accuracy/CI/changed/lost/gained per rung and writes
`results/analysis.json`.

## Test your own model

Add a row to `MODELS` in `run_bench.py`:

```python
MODELS = {
    "qwen": "qwen2.5-7b-instruct",
    "mistral": "mistral-7b-instruct-v0.3",
    "mine": "my-model",        # expects my-model-f16.gguf in CHURN_MODELS_DIR
}
```

And/or swap the questions: `arc-challenge-500.json` is a list of
`{"id", "question", "choices" (4 strings), "answer" ("A".."D")}` — any
multiple-choice set in that shape works. If your workload isn't multiple
choice, widen the grammar and diff whatever your "answer" is; the
determinism trick (temp 0 + seed + grammar + no prompt cache) is the part
that carries.

## Data attribution

`arc-challenge-500.json` is a 500-question subset of the ARC-Challenge
test set (Clark et al., Allen Institute for AI, 2018,
https://allenai.org/data/arc), redistributed under CC BY-SA 4.0.

## License

MIT (see [LICENSE](LICENSE)). The ARC questions file carries its own
CC BY-SA 4.0 terms as above.
