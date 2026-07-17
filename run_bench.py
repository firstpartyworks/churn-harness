#!/usr/bin/env python3
"""Quantization answer-churn bench (repro of arXiv 2607.08734 on our own
GGUF ladder — method per Dutta et al. 2407.09141's 'flips').

For each (model, quant): quantize from the F16 parent if needed, serve on
the V100, ask 500 ARC-Challenge questions at temp 0 with a grammar that
forces a single letter answer — so every answer is deterministic and any
cross-quant difference is attributable to the weights, not sampling.

Writes results/<model>-<QUANT>.json ({qid: {"ans": "A", "ok": true}}).
Run: python3 run_bench.py [--model qwen|mistral|all]
"""
import argparse, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
FAST = Path(os.environ.get("CHURN_MODELS_DIR", "/fast/quant-churn"))
BIN = Path(os.environ.get("CHURN_LLAMA_BIN", "/fast/llama.cpp-stock/build/bin"))
PORT = 4988
QUANTS = ["Q8_0", "Q6_K", "Q4_K_M", "Q3_K_M", "Q2_K"]
MODELS = {
    "qwen": "qwen2.5-7b-instruct",
    "mistral": "mistral-7b-instruct-v0.3",
}
GRAMMAR = 'root ::= "A" | "B" | "C" | "D"'

QS = json.loads((HERE / "arc-challenge-500.json").read_text())


def post(path, payload, timeout=120):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def ensure_quant(model, quant):
    f16 = FAST / f"{model}-f16.gguf"
    if quant.upper() == "F16":
        return f16
    out = FAST / f"{model}-{quant}.gguf"
    if out.exists():
        return out
    print(f"  quantizing {out.name} ...", flush=True)
    t0 = time.time()
    r = subprocess.run(
        [str(BIN / "llama-quantize"), str(f16), str(out), quant],
        env={"LD_LIBRARY_PATH": str(BIN)}, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"quantize failed for {out.name}: {r.stderr[-400:]}")
    print(f"  quantized in {time.time()-t0:.0f}s ({out.stat().st_size/1e9:.1f} GB)", flush=True)
    return out


def serve(gguf):
    proc = subprocess.Popen(
        [str(BIN / "llama-server"), "-m", str(gguf), "--port", str(PORT),
         "-ngl", "99", "-c", "2048", "--no-webui", "-fa", "on",
         "--parallel", "4"],
        env={"LD_LIBRARY_PATH": str(BIN), "CUDA_VISIBLE_DEVICES": "0",
             "CUDA_DEVICE_ORDER": "PCI_BUS_ID"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(240):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2)
            return proc
        except Exception:
            if proc.poll() is not None:
                sys.exit(f"llama-server died loading {gguf.name}")
            time.sleep(1)
    proc.kill()
    sys.exit(f"llama-server never became healthy for {gguf.name}")


def ask(q):
    msgs = [
        {"role": "system", "content": "You are taking a multiple-choice science test. Answer with only the letter of the correct choice."},
        {"role": "user", "content": q["question"] + "\n" + "\n".join(
            f"{l}. {c}" for l, c in zip("ABCD", q["choices"]))},
    ]
    tpl = post("/apply-template", {"messages": msgs})
    res = post("/completion", {
        "prompt": tpl["prompt"], "n_predict": 2, "temperature": 0,
        "seed": 0, "grammar": GRAMMAR, "cache_prompt": False,
    })
    return res["content"].strip()[:1]


def run_model(model):
    results_dir = HERE / "results"
    results_dir.mkdir(exist_ok=True)
    for quant in QUANTS:
        out_file = results_dir / f"{model}-{quant}.json"
        if out_file.exists():
            print(f"[{model} {quant}] already done, skipping", flush=True)
            continue
        gguf = ensure_quant(model, quant)
        print(f"[{model} {quant}] serving + {len(QS)} questions", flush=True)
        proc = serve(gguf)
        t0 = time.time()
        answers = {}
        try:
            for i, q in enumerate(QS):
                a = ask(q)
                answers[q["id"]] = {"ans": a, "ok": a == q["answer"]}
                if (i + 1) % 100 == 0:
                    acc = sum(v["ok"] for v in answers.values()) / len(answers)
                    print(f"  {i+1}/{len(QS)} acc so far {acc:.3f} "
                          f"({(time.time()-t0)/(i+1):.2f}s/q)", flush=True)
        finally:
            proc.terminate()
            proc.wait(timeout=30)
        acc = sum(v["ok"] for v in answers.values()) / len(answers)
        out_file.write_text(json.dumps(answers, indent=0))
        print(f"[{model} {quant}] DONE acc={acc:.3f} in {(time.time()-t0)/60:.1f} min", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="all", choices=[*MODELS, "all"])
    ap.add_argument("--quants", default=None, help="comma list override, e.g. F16")
    args = ap.parse_args()
    if args.quants:
        QUANTS[:] = args.quants.split(",")
    for key, name in MODELS.items():
        if args.model in (key, "all"):
            run_model(name)
    print("ALL BENCH RUNS COMPLETE")
