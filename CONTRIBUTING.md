# Contributing

Issues and PRs welcome. Things we'd genuinely like:

- **More model families** at 7B-ish scale (Llama, Gemma, Phi) — add a
  `MODELS` row, run the ladder, PR your `results/*.json` with the exact
  llama.cpp commit and GPU noted.
- **Other question sets** in the same JSON shape (see README) —
  especially non-science domains, or sets targeting a real workload
  (extraction, routing, log triage).
- **Other quant formats** (AWQ/GPTQ/EXL2 servers with deterministic
  settings) — the diff logic doesn't care where answers come from.

Ground rules:

- Keep `run_bench.py` stdlib-only and small. If your change needs pip
  installs, it probably belongs in a fork or a separate script.
- Determinism is the product: temp 0, fixed seed, grammar-forced answers,
  `cache_prompt: false`. Don't trade any of it for speed.
- Results PRs must state model source (repo + file), llama.cpp commit,
  and hardware, so someone else can reproduce your numbers.
