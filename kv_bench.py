#!/usr/bin/env python3
"""KV-cache quantization answer-churn bench (finding #36 — the follow-up to
run_bench.py's weight-quant ladder).

Same instrument as run_bench.py: 500 ARC-Challenge questions, temp 0, fixed
seed, grammar-forced single-letter answers, cache_prompt off — byte-identical
answer sheets on repeat runs. This time the WEIGHTS are held constant and the
KV cache type walks f16 -> q8_0 -> q4_0 (llama.cpp --cache-type-k/-v), plus
K-only / V-only splits, so any answer diff is attributable to cache
quantization alone.

The f16-cache baseline is run TWICE (rep2) as the instrument check: if the
two baseline sheets differ, the rig is noisy and no flip count downstream can
be trusted. -fa is on for every run including the baseline (quantized V cache
requires flash attention; keeping it on everywhere means cache type is the
only variable).

Writes results/kv-<model>-<K>k-<V>v.json ({qid: {"ans": "A", "ok": true}})
and results/kv-meta.json (binary commit, flags, model files).
Run: python3 kv_bench.py [--model qwen7b|mistral7b|qwen27b|all]
"""
import argparse, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
BIN = Path(os.environ.get("CHURN_LLAMA_BIN", "/bulk/bench/llama.cpp/build/bin"))
PORT = 4989

# (cache-type-k, cache-type-v) legs, baseline first
MODES = [
    ("f16", "f16"),
    ("q8_0", "q8_0"),
    ("q4_0", "q4_0"),
    ("q4_0", "f16"),   # K-only: the projection the mechanism paper calls fragile
    ("f16", "q4_0"),   # V-only control
]

# weights are a fixed file per model — never requantized by this script
MODELS = {
    "qwen7b": ("qwen2.5-7b-instruct-F16w", "/fast/quant-churn/qwen2.5-7b-instruct-f16.gguf"),
    "mistral7b": ("mistral-7b-instruct-v0.3-F16w", "/fast/quant-churn/mistral-7b-instruct-v0.3-f16.gguf"),
    "qwen27b": ("Qwen3.6-27B-Q8_0w", "/bulk/models/models/Qwen3.6-27B-Q8_0.gguf"),
    "qwen38": ("Qwen3.8-27B-Q6_Kw", "/bulk/models/models/Qwen3.8-27B-Q6_K.gguf"),
}
# thinking models: grammar-forcing a letter inside an open <think> block
# measures noise, not the model — render with thinking disabled
THINK_OFF = {"qwen27b", "qwen38"}
CT_KWARGS = {}
GRAMMAR = 'root ::= "A" | "B" | "C" | "D"'

QS = json.loads((HERE / "arc-challenge-500.json").read_text())


def post(path, payload, timeout=120):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def serve(gguf, ctk, ctv):
    proc = subprocess.Popen(
        [str(BIN / "llama-server"), "-m", str(gguf), "--port", str(PORT),
         "-ngl", "99", "-c", "2048", "--no-webui", "-fa", "on",
         "--parallel", "4", "-ctk", ctk, "-ctv", ctv],
        env={"LD_LIBRARY_PATH": str(BIN), "CUDA_VISIBLE_DEVICES": "0",
             "CUDA_DEVICE_ORDER": "PCI_BUS_ID"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(300):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2)
            return proc
        except Exception:
            if proc.poll() is not None:
                sys.exit(f"llama-server died loading {gguf} ({ctk}k/{ctv}v)")
            time.sleep(1)
    proc.kill()
    sys.exit(f"llama-server never became healthy for {gguf}")


def ask(q):
    msgs = [
        {"role": "system", "content": "You are taking a multiple-choice science test. Answer with only the letter of the correct choice."},
        {"role": "user", "content": q["question"] + "\n" + "\n".join(
            f"{l}. {c}" for l, c in zip("ABCD", q["choices"]))},
    ]
    body = {"messages": msgs}
    if CT_KWARGS:
        body["chat_template_kwargs"] = CT_KWARGS
    tpl = post("/apply-template", body)
    res = post("/completion", {
        "prompt": tpl["prompt"], "n_predict": 2, "temperature": 0,
        "seed": 0, "grammar": GRAMMAR, "cache_prompt": False,
    })
    return res["content"].strip()[:1]


def run_sheet(label):
    t0 = time.time()
    answers = {}
    for i, q in enumerate(QS):
        a = ask(q)
        answers[q["id"]] = {"ans": a, "ok": a == q["answer"]}
        if (i + 1) % 100 == 0:
            acc = sum(v["ok"] for v in answers.values()) / len(answers)
            print(f"  {i+1}/{len(QS)} acc so far {acc:.3f} "
                  f"({(time.time()-t0)/(i+1):.2f}s/q)", flush=True)
    acc = sum(v["ok"] for v in answers.values()) / len(answers)
    print(f"[{label}] DONE acc={acc:.3f} in {(time.time()-t0)/60:.1f} min", flush=True)
    return answers


def check_template(name):
    """Abort if the rendered prompt leaves an open <think> block — the
    grammar would force the answer letter inside the reasoning span."""
    body = {"messages": [{"role": "user", "content": "ping"}]}
    if CT_KWARGS:
        body["chat_template_kwargs"] = CT_KWARGS
    p = post("/apply-template", body)["prompt"]
    tail = p[-160:].replace("\n", "\\n")
    print(f"[{name}] template tail: ...{tail}", flush=True)
    if p.rstrip().endswith("<think>"):
        sys.exit(f"template for {name} ends with an OPEN <think> block — "
                 f"thinking is still active; refusing to bench garbage")


def run_model(key):
    global CT_KWARGS
    CT_KWARGS = {"enable_thinking": False} if key in THINK_OFF else {}
    name, gguf = MODELS[key]
    if not Path(gguf).exists():
        sys.exit(f"missing model file: {gguf}")
    results_dir = HERE / "results"
    results_dir.mkdir(exist_ok=True)
    legs = list(MODES) + [("f16", "f16", "rep2")]
    for leg in legs:
        ctk, ctv = leg[0], leg[1]
        suffix = f"-{leg[2]}" if len(leg) > 2 else ""
        out_file = results_dir / f"kv-{name}-{ctk}k-{ctv}v{suffix}.json"
        if out_file.exists():
            print(f"[{name} {ctk}k/{ctv}v{suffix}] already done, skipping", flush=True)
            continue
        print(f"[{name} {ctk}k/{ctv}v{suffix}] serving + {len(QS)} questions", flush=True)
        proc = serve(gguf, ctk, ctv)
        try:
            check_template(name)
            answers = run_sheet(f"{name} {ctk}k/{ctv}v{suffix}")
        finally:
            proc.terminate()
            proc.wait(timeout=30)
        out_file.write_text(json.dumps(answers, indent=0))
        time.sleep(3)
    base = json.loads((results_dir / f"kv-{name}-f16k-f16v.json").read_text())
    rep2 = json.loads((results_dir / f"kv-{name}-f16k-f16v-rep2.json").read_text())
    mism = [k for k in base if base[k]["ans"] != rep2[k]["ans"]]
    if mism:
        print(f"!! DETERMINISM CHECK FAILED for {name}: {len(mism)} answers "
              f"differ between identical baseline runs ({mism[:5]}...) — "
              f"flip counts for this model are NOT trustworthy", flush=True)
    else:
        print(f"[{name}] determinism check PASSED: baseline rep2 byte-identical", flush=True)


def write_meta():
    commit = subprocess.run(
        ["git", "-C", str(BIN.parent.parent), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True).stdout.strip()
    meta = {
        "llama_cpp_bin": str(BIN), "llama_cpp_commit": commit,
        "server_flags": "-ngl 99 -c 2048 --no-webui -fa on --parallel 4 -ctk <K> -ctv <V>",
        "gpu": "Tesla V100-PCIE-32GB (CUDA_DEVICE_ORDER=PCI_BUS_ID device 0)",
        "sampling": "temp 0, seed 0, grammar single-letter, cache_prompt false, n_predict 2",
        "models": {k: {"label": n, "file": f, "bytes": Path(f).stat().st_size}
                   for k, (n, f) in MODELS.items() if Path(f).exists()},
    }
    (HERE / "results" / "kv-meta.json").write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="all", choices=[*MODELS, "all"])
    args = ap.parse_args()
    write_meta()
    for key in MODELS:
        if args.model in (key, "all"):
            run_model(key)
    print("ALL KV BENCH RUNS COMPLETE")
