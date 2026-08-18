#!/usr/bin/env python3
"""KV-cache churn with a ternary (tq3_0) cache type — experimental legs.

Requires a llama.cpp build that carries a ternary KV-cache type (tq3_0 is
NOT upstream; point CHURN_LLAMA_BIN at a build that has it). Because the
binary differs from the stock one, all numbers are self-contained per
model — own f16 baseline + determinism repeat on THIS binary; never diff
across binaries.

Per MODELS row: f16(+rep2) baseline, the standard quantized legs, then
the tq3_0 leg. Coherence probes run on the interesting legs (grammar-
forced letters can hide babble; the probes surface it).

Setup:
  export CHURN_LLAMA_BIN=/path/to/ternary-llama.cpp/build/bin
  export CHURN_MODELS_DIR=/path/to/ggufs
"""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
BIN = Path(os.environ.get("CHURN_LLAMA_BIN", ""))
MODELS_DIR = Path(os.environ.get("CHURN_MODELS_DIR", str(HERE / "models")))
PORT = 4992
QS = json.loads((HERE / "arc-challenge-500.json").read_text())
GRAMMAR = 'root ::= "A" | "B" | "C" | "D"'
LOGS = HERE / "logs"
RESULTS = HERE / "results"

# (label, gguf in CHURN_MODELS_DIR, think_off, legs)
MODELS = {
    "bonsai": ("tlab-Bonsai-27B-Q2g64w",
               "Ternary-Bonsai-27B-Q2_g64.gguf",
               True,   # thinking model
               [("f16", "f16", ""), ("f16", "f16", "-rep2"), ("q8_0", "q8_0", ""),
                ("q4_0", "q4_0", ""), ("q4_0", "f16", ""), ("tq3_0", "tq3_0", "")]),
    "qwen7b": ("tlab-qwen2.5-7b-instruct-F16w",
               "qwen2.5-7b-instruct-f16.gguf",
               False,
               [("f16", "f16", ""), ("f16", "f16", "-rep2"),
                ("q4_0", "q4_0", ""), ("tq3_0", "tq3_0", "")]),
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
    print(f"SERVER NEVER HEALTHY for {ctk}k/{ctv}v — see {logname}", flush=True)
    return None


def render(msgs):
    body = {"messages": msgs}
    if CT_KWARGS:
        body["chat_template_kwargs"] = CT_KWARGS
    return post("/apply-template", body)["prompt"]


def check_template(name):
    p = render([{"role": "user", "content": "ping"}])
    tail = p[-140:].replace("\n", "\\n")
    print(f"[{name}] template tail: ...{tail}", flush=True)
    if p.rstrip().endswith("<think>"):
        sys.exit(f"template for {name} ends with OPEN <think> — refusing to bench garbage")


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
            print(f"  {i+1}/{len(QS)} acc so far {acc:.3f} "
                  f"({(time.time()-t0)/(i+1):.2f}s/q)", flush=True)
    acc = sum(v["ok"] for v in answers.values()) / len(answers)
    print(f"[{label}] DONE acc={acc:.3f} in {(time.time()-t0)/60:.1f} min", flush=True)
    return answers


def probe(tag):
    print(f"--- coherence probe ({tag}) ---", flush=True)
    for prompt in ["Why is the sky blue?", "Name the planets of the solar system."]:
        p = render([{"role": "user", "content": prompt}])
        res = post("/completion", {"prompt": p, "n_predict": 50,
                                   "temperature": 0, "seed": 0, "cache_prompt": False})
        print(f"Q: {prompt}\nA: {res['content'].strip()[:200]}\n", flush=True)


if not BIN.is_dir():
    sys.exit("set CHURN_LLAMA_BIN to a llama.cpp build/bin that has the "
             "ternary cache types")
LOGS.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)
for key, (name, fname, think_off, legs) in MODELS.items():
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
        label = f"{name} {ctk}k/{ctv}v{suffix}"
        print(f"[{label}] serving + {len(QS)} questions", flush=True)
        proc = serve(gguf, ctk, ctv, f"tlab-{key}-{ctk}k-{ctv}v{suffix or ''}.log")
        if proc is None:
            continue
        try:
            check_template(name)
            answers = sheet(label)
            if suffix == "" and (ctk in ("tq3_0", "q4_0")) and ctv != "f16":
                probe(f"{key} {ctk} K+V")
        finally:
            proc.terminate()
            proc.wait(timeout=30)
        out_file.write_text(json.dumps(answers, indent=0))
        time.sleep(3)

    base_f = RESULTS / f"kv-{name}-f16k-f16v.json"
    if not base_f.exists():
        continue
    base = json.loads(base_f.read_text())
    rep2_f = RESULTS / f"kv-{name}-f16k-f16v-rep2.json"
    if rep2_f.exists():
        rep2 = json.loads(rep2_f.read_text())
        mism = sum(1 for k in base if base[k]["ans"] != rep2[k]["ans"])
        print(f"[{name}] determinism: {'PASS' if mism == 0 else f'FAIL ({mism} mismatches)'}", flush=True)
    for ctk, ctv, suffix in legs:
        if (ctk, ctv) == ("f16", "f16"):
            continue
        f = RESULTS / f"kv-{name}-{ctk}k-{ctv}v{suffix}.json"
        if not f.exists():
            continue
        r = json.loads(f.read_text())
        acc = sum(v["ok"] for v in r.values()) / len(r)
        changed = sum(1 for k in base if base[k]["ans"] != r[k]["ans"])
        print(f"[{name}] {ctk}k/{ctv}v: acc={acc:.3f} changed_vs_f16={changed}/{len(base)}", flush=True)

print("TERNARY-LAB KV EXPERIMENT COMPLETE", flush=True)
