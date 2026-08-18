#!/usr/bin/env python3
"""Compound quantization churn — Q4 weights x Q4 cache.

Completes the 2x2 factorial: run_bench.py measures weight-quant churn at
f16 cache; kv_bench.py measures cache-quant churn at full-precision
weights. These legs add the missing cells — Q4_K_M weights with f16 cache
(weight effect re-anchored on this binary) and Q4_K_M weights with q4_0
cache (the compound config people actually run) — so flipped-question
sets can be tested for additivity vs interaction against the SAME
original baselines. Short context (the regime where each factor's solo
effect is already measured).

Each MODELS row names the kv_bench.py result prefix it factors against;
run kv_bench.py on the full-precision weights first.

Setup:
  export CHURN_LLAMA_BIN=/path/to/llama.cpp/build/bin
  export CHURN_MODELS_DIR=/path/to/ggufs
"""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
BIN = Path(os.environ.get("CHURN_LLAMA_BIN", ""))
MODELS_DIR = Path(os.environ.get("CHURN_MODELS_DIR", str(HERE / "models")))
PORT = 4989
QS = json.loads((HERE / "arc-challenge-500.json").read_text())
GRAMMAR = 'root ::= "A" | "B" | "C" | "D"'
LOGS = HERE / "logs"
RESULTS = HERE / "results"

# (label, gguf in CHURN_MODELS_DIR, think_off, kv_bench baseline prefix, legs)
MODELS = {
    "mistral": ("mistral-7b-instruct-v0.3-Q4KMw",
                "mistral-7b-instruct-v0.3-Q4_K_M.gguf",
                False,
                "kv-mistral-7b-instruct-v0.3-F16w",
                [("f16", "f16", ""), ("f16", "f16", "-rep2"), ("q4_0", "q4_0", "")]),
    "qwen27b": ("Qwen3.6-27B-Q4KMw",
                "Qwen3.6-27B-Q4_K_M.gguf",
                True,
                "kv-Qwen3.6-27B-Q8_0w",
                [("f16", "f16", ""), ("f16", "f16", "-rep2"),
                 ("q8_0", "q8_0", ""), ("q4_0", "q4_0", "")]),
}
CT_KWARGS = {}


def post(path, payload, timeout=300):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def serve(gguf, ctk, ctv, logname):
    log = open(LOGS / logname, "w")
    proc = subprocess.Popen(
        [str(BIN / "llama-server"), "-m", str(gguf), "--port", str(PORT),
         "-ngl", "99", "-c", "2048", "--no-webui", "-fa", "on",
         "--parallel", "4", "-ctk", ctk, "-ctv", ctv],
        env={**os.environ, "LD_LIBRARY_PATH": str(BIN)},
        stdout=log, stderr=log)
    for _ in range(300):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2)
            return proc
        except Exception:
            if proc.poll() is not None:
                print(f"SERVER DIED for {Path(gguf).name} {ctk}k/{ctv}v — see {logname}", flush=True)
                return None
            time.sleep(1)
    proc.kill()
    return None


def render(msgs):
    body = {"messages": msgs}
    if CT_KWARGS:
        body["chat_template_kwargs"] = CT_KWARGS
    return post("/apply-template", body)["prompt"]


def check_template(name):
    p = render([{"role": "user", "content": "ping"}])
    print(f"[{name}] template tail: ...{p[-100:].rstrip()[-60:]!r}", flush=True)
    if p.rstrip().endswith("<think>"):
        sys.exit(f"OPEN <think> for {name} — refusing to bench")


def sheet(label):
    t0 = time.time()
    answers = {}
    for i, q in enumerate(QS):
        prompt = render([
            {"role": "system", "content": "You are taking a multiple-choice science test. Answer with only the letter of the correct choice."},
            {"role": "user", "content": q["question"] + "\n" + "\n".join(
                f"{l}. {c}" for l, c in zip("ABCD", q["choices"]))},
        ])
        res = post("/completion", {
            "prompt": prompt, "n_predict": 2, "temperature": 0,
            "seed": 0, "grammar": GRAMMAR, "cache_prompt": False,
        })
        a = res["content"].strip()[:1]
        answers[q["id"]] = {"ans": a, "ok": a == q["answer"]}
        if (i + 1) % 100 == 0:
            acc = sum(v["ok"] for v in answers.values()) / len(answers)
            print(f"  {i+1}/{len(QS)} acc {acc:.3f} ({(time.time()-t0)/(i+1):.2f}s/q)", flush=True)
    acc = sum(v["ok"] for v in answers.values()) / len(answers)
    print(f"[{label}] DONE acc={acc:.3f} in {(time.time()-t0)/60:.1f} min", flush=True)
    return answers


if not BIN.is_dir():
    sys.exit("set CHURN_LLAMA_BIN to your llama.cpp build/bin directory")
LOGS.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)
for key, (name, fname, think_off, orig_prefix, legs) in MODELS.items():
    gguf = MODELS_DIR / fname
    if not gguf.exists():
        print(f"[{key}] missing model file {gguf} — skipping", flush=True)
        continue
    CT_KWARGS = {"enable_thinking": False} if think_off else {}
    for ctk, ctv, suffix in legs:
        out_file = RESULTS / f"kv-{name}-{ctk}k-{ctv}v{suffix}.json"
        if out_file.exists():
            print(f"[{name} {ctk}k/{ctv}v{suffix}] already done, skipping", flush=True)
            continue
        print(f"[{name} {ctk}k/{ctv}v{suffix}] serving + {len(QS)} questions", flush=True)
        proc = serve(gguf, ctk, ctv, f"comp-{key}-{ctk}k-{ctv}v{suffix or ''}.log")
        if proc is None:
            continue
        try:
            check_template(name)
            answers = sheet(f"{name} {ctk}k/{ctv}v{suffix}")
        finally:
            proc.terminate()
            proc.wait(timeout=30)
        out_file.write_text(json.dumps(answers, indent=0))
        time.sleep(3)

    # factorial analysis vs the ORIGINAL full-weight baseline
    orig_base_f = RESULTS / f"{orig_prefix}-f16k-f16v.json"
    orig_q4c_f = RESULTS / f"{orig_prefix}-q4_0k-q4_0v.json"
    new_base_f = RESULTS / f"kv-{name}-f16k-f16v.json"
    new_q4c_f = RESULTS / f"kv-{name}-q4_0k-q4_0v.json"
    if not all(f.exists() for f in (orig_base_f, orig_q4c_f, new_base_f, new_q4c_f)):
        continue
    ob = json.loads(orig_base_f.read_text())
    oc = json.loads(orig_q4c_f.read_text())
    nb = json.loads(new_base_f.read_text())
    nc = json.loads(new_q4c_f.read_text())
    rep2_f = RESULTS / f"kv-{name}-f16k-f16v-rep2.json"
    if rep2_f.exists():
        rep2 = json.loads(rep2_f.read_text())
        mism = sum(1 for k in nb if nb[k]["ans"] != rep2[k]["ans"])
        print(f"[{name}] determinism: {'PASS' if mism == 0 else f'FAIL ({mism})'}", flush=True)
    W = {k for k in ob if ob[k]["ans"] != nb[k]["ans"]}   # weights-only flips
    C = {k for k in ob if ob[k]["ans"] != oc[k]["ans"]}   # cache-only flips
    B = {k for k in ob if ob[k]["ans"] != nc[k]["ans"]}   # both-quantized flips
    for tag, d in (("orig baseline", ob), ("Q4w f16c", nb), ("F16w q4c", oc), ("Q4w q4c", nc)):
        acc = sum(v["ok"] for v in d.values()) / len(d)
        print(f"[{name}] {tag}: acc={acc:.3f}", flush=True)
    print(f"[{name}] flips vs orig baseline — weights only: {len(W)}, "
          f"cache only: {len(C)}, compound: {len(B)}", flush=True)
    print(f"[{name}] overlap W∩C={len(W & C)}, union W∪C={len(W | C)}, "
          f"compound-only (in B, not W∪C): {len(B - (W | C))}, "
          f"healed (in W∪C, not B): {len((W | C) - B)}", flush=True)

print("COMPOUND EXPERIMENT COMPLETE", flush=True)
