#!/usr/bin/env python3
"""Deep-context KV-cache churn (finding #36, experiment 4) — Qwen3.6-27B.

Short-context (2K) legs showed 3.6-27B robust to q4_0 cache (0-2 flips).
John + @PvMLad both report real degradation at depth. This leg re-asks the
same questions from ~8K tokens deep: the prompt is a genuine quiz session —
the first 100 ARC-C questions as user/assistant chat history (assistant
answering with the correct letter, exactly this harness's own output
format) — then the target question. Targets = the remaining 400 questions
(no target appears in the pad; no answer leakage).

Stock rig binary (V100), Q8_0 weights, thinking disabled. cache_prompt=true
(the shared pad prefix computes once — also the real deployment mode for a
long session) with --parallel 1; the f16 rep2 leg must come back
byte-identical or the cached-prefix path is declared noisy and results
discarded. Legs: f16(+rep2) / q8_0 / q4_0 K+V.
"""
import json, subprocess, time, urllib.request
from pathlib import Path

BENCH = Path("/bulk/company/videos/quant-churn/bench")
BIN = Path("/bulk/bench/llama.cpp/build/bin")
GGUF = "/bulk/models/models/Qwen3.6-27B-Q8_0.gguf"
PORT = 4989
NAME = "deep100-Qwen3.6-27B-Q8_0w"
CTX = 12288
PAD_N = 100
OUT = Path("/home/chambejp/.claude/jobs/ea560999/tmp")
RESULTS = BENCH / "results"
GRAMMAR = 'root ::= "A" | "B" | "C" | "D"'
CT_KWARGS = {"enable_thinking": False}

ALL = json.loads((BENCH / "arc-challenge-500.json").read_text())
PAD, TARGETS = ALL[:PAD_N], ALL[100:]


def qtext(q):
    return q["question"] + "\n" + "\n".join(
        f"{l}. {c}" for l, c in zip("ABCD", q["choices"]))


PAD_MSGS = [{"role": "system", "content": "You are taking a multiple-choice science test. Answer with only the letter of the correct choice."}]
for q in PAD:
    PAD_MSGS.append({"role": "user", "content": qtext(q)})
    PAD_MSGS.append({"role": "assistant", "content": q["answer"]})


def post(path, payload, timeout=600):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def serve(ctk, ctv, logname):
    log = open(OUT / logname, "w")
    proc = subprocess.Popen(
        [str(BIN / "llama-server"), "-m", GGUF, "--port", str(PORT),
         "-ngl", "99", "-c", str(CTX), "--no-webui", "-fa", "on",
         "--parallel", "1", "-ctk", ctk, "-ctv", ctv],
        env={"LD_LIBRARY_PATH": str(BIN), "CUDA_VISIBLE_DEVICES": "0",
             "CUDA_DEVICE_ORDER": "PCI_BUS_ID"},
        stdout=log, stderr=log)
    for _ in range(360):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2)
            return proc
        except Exception:
            if proc.poll() is not None:
                print(f"SERVER DIED for {ctk}k/{ctv}v — see {logname} "
                      f"(f16 cache at -c {CTX} may not fit; check the log)", flush=True)
                return None
            time.sleep(1)
    proc.kill()
    print(f"SERVER NEVER HEALTHY for {ctk}k/{ctv}v", flush=True)
    return None


def render(msgs):
    return post("/apply-template",
                {"messages": msgs, "chat_template_kwargs": CT_KWARGS})["prompt"]


def check_template():
    p = render(PAD_MSGS + [{"role": "user", "content": "ping"}])
    tail = p[-120:].replace("\n", "\\n")
    print(f"template tail: ...{tail}", flush=True)
    if p.rstrip().endswith("<think>"):
        import sys
        sys.exit("OPEN <think> in rendered template — refusing to bench")


def sheet(label):
    t0 = time.time()
    answers = {}
    depth = None
    for i, q in enumerate(TARGETS):
        prompt = render(PAD_MSGS + [{"role": "user", "content": qtext(q)}])
        res = post("/completion", {
            "prompt": prompt, "n_predict": 2, "temperature": 0,
            "seed": 0, "grammar": GRAMMAR, "cache_prompt": True,
        })
        if depth is None:
            depth = res.get("timings", {}).get("prompt_n", -1)
            print(f"  first-request prompt_n={depth} tokens (full pad prefill)", flush=True)
        a = res["content"].strip()[:1]
        answers[q["id"]] = {"ans": a, "ok": a == q["answer"]}
        if (i + 1) % 100 == 0:
            acc = sum(v["ok"] for v in answers.values()) / len(answers)
            print(f"  {i+1}/{len(TARGETS)} acc so far {acc:.3f} "
                  f"({(time.time()-t0)/(i+1):.2f}s/q)", flush=True)
    acc = sum(v["ok"] for v in answers.values()) / len(answers)
    print(f"[{label}] DONE acc={acc:.3f} in {(time.time()-t0)/60:.1f} min", flush=True)
    return answers


LEGS = [("f16", "f16", ""), ("f16", "f16", "-rep2"),
        ("q8_0", "q8_0", ""), ("q4_0", "q4_0", "")]
for ctk, ctv, suffix in LEGS:
    out_file = RESULTS / f"kv-{NAME}-{ctk}k-{ctv}v{suffix}.json"
    if out_file.exists():
        print(f"[{ctk}k/{ctv}v{suffix}] already done, skipping", flush=True)
        continue
    label = f"{NAME} {ctk}k/{ctv}v{suffix}"
    print(f"[{label}] serving + {len(TARGETS)} targets at depth", flush=True)
    proc = serve(ctk, ctv, f"deep-{ctk}k-{ctv}v{suffix or ''}.log")
    if proc is None:
        continue
    try:
        check_template()
        answers = sheet(label)
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    out_file.write_text(json.dumps(answers, indent=0))
    time.sleep(3)

base_f = RESULTS / f"kv-{NAME}-f16k-f16v.json"
if base_f.exists():
    base = json.loads(base_f.read_text())
    rep2_f = RESULTS / f"kv-{NAME}-f16k-f16v-rep2.json"
    if rep2_f.exists():
        rep2 = json.loads(rep2_f.read_text())
        mism = sum(1 for k in base if base[k]["ans"] != rep2[k]["ans"])
        print(f"determinism (deep, cached-prefix): "
              f"{'PASS' if mism == 0 else f'FAIL ({mism} mismatches) — DISCARD DEEP RESULTS'}", flush=True)
    # depth-0 cross-comparison on the same 400 targets, from the short-context run
    short_f = RESULTS / "kv-Qwen3.6-27B-Q8_0w-f16k-f16v.json"
    if short_f.exists():
        short = json.loads(short_f.read_text())
        moved = sum(1 for k in base if k in short and base[k]["ans"] != short[k]["ans"])
        print(f"depth effect alone (f16 cache, short 2K vs deep): {moved}/{len(base)} answers differ", flush=True)
    for ctk, ctv, suffix in LEGS[2:]:
        f = RESULTS / f"kv-{NAME}-{ctk}k-{ctv}v.json"
        if not f.exists():
            continue
        r = json.loads(f.read_text())
        acc = sum(v["ok"] for v in r.values()) / len(r)
        changed = sum(1 for k in base if base[k]["ans"] != r[k]["ans"])
        print(f"{ctk}k/{ctv}v deep: acc={acc:.3f} changed_vs_deep_f16={changed}/{len(base)}", flush=True)
print("DEEP-CONTEXT EXPERIMENT COMPLETE", flush=True)
