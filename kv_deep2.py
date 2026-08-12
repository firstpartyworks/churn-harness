#!/usr/bin/env python3
"""Deep-context KV-cache churn, extended sweep (finding #36) — Qwen3.6-27B
at ~20K and ~40K tokens, agentic-scale depths.

Same construction as kv_deep.py: the prompt is a genuine quiz session, but
the pad now draws from arc-challenge-padpool.json (the remaining 665
4-choice questions of the real ARC-Challenge test set — zero overlap with
the 400 targets, which stay identical to every other depth rung). Pad size
is fixed per depth by the model's own tokenizer via /tokenize: smallest
prefix of the pool that reaches the token target. 40K f16 cache verified
to FIT on the V100 (hybrid-attention architecture = small KV footprint).

Stock rig, Q8_0 weights, thinking disabled, --parallel 1, prefix caching;
each depth's f16 rep2 must be byte-identical or that depth is discarded.
Legs per depth: f16(+rep2) / q8_0 / q4_0 K+V.
"""
import json, subprocess, time, urllib.request
from pathlib import Path

BENCH = Path("/bulk/company/videos/quant-churn/bench")
BIN = Path("/bulk/bench/llama.cpp/build/bin")
GGUF = "/bulk/models/models/Qwen3.6-27B-Q8_0.gguf"
PORT = 4989
OUT = Path("/home/chambejp/.claude/jobs/ea560999/tmp")
RESULTS = BENCH / "results"
GRAMMAR = 'root ::= "A" | "B" | "C" | "D"'
CT_KWARGS = {"enable_thinking": False}

DEPTHS = [(20480, 22528, "deep20k"), (40960, 43008, "deep40k")]

ALL = json.loads((BENCH / "arc-challenge-500.json").read_text())
TARGETS = ALL[100:]
POOL = json.loads((BENCH / "arc-challenge-padpool.json").read_text())
SYS = {"role": "system", "content": "You are taking a multiple-choice science test. Answer with only the letter of the correct choice."}


def qtext(q):
    return q["question"] + "\n" + "\n".join(
        f"{l}. {c}" for l, c in zip("ABCD", q["choices"]))


def pad_msgs(n):
    msgs = [SYS]
    for q in POOL[:n]:
        msgs.append({"role": "user", "content": qtext(q)})
        msgs.append({"role": "assistant", "content": q["answer"]})
    return msgs


def post(path, payload, timeout=900):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def serve(ctk, ctv, ctx, logname):
    log = open(OUT / logname, "w")
    proc = subprocess.Popen(
        [str(BIN / "llama-server"), "-m", GGUF, "--port", str(PORT),
         "-ngl", "99", "-c", str(ctx), "--no-webui", "-fa", "on",
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
                print(f"SERVER DIED for {ctk}k/{ctv}v ctx={ctx} — see {logname}", flush=True)
                return None
            time.sleep(1)
    proc.kill()
    print(f"SERVER NEVER HEALTHY for {ctk}k/{ctv}v", flush=True)
    return None


def render(msgs):
    return post("/apply-template",
                {"messages": msgs, "chat_template_kwargs": CT_KWARGS})["prompt"]


def ntokens(msgs):
    return len(post("/tokenize", {"content": render(msgs)})["tokens"])


def size_pad(target):
    """Smallest pool prefix whose rendered pad reaches target tokens."""
    n = min(len(POOL), max(10, target // 90))
    t = ntokens(pad_msgs(n))
    while t < target and n < len(POOL):
        n = min(len(POOL), n + max(1, (target - t) // 90))
        t = ntokens(pad_msgs(n))
    print(f"  pad sized: {n} questions -> {t} tokens (target {target})", flush=True)
    return n, t


def sheet(label, pmsgs):
    t0 = time.time()
    answers = {}
    depth = None
    for i, q in enumerate(TARGETS):
        prompt = render(pmsgs + [{"role": "user", "content": qtext(q)}])
        res = post("/completion", {
            "prompt": prompt, "n_predict": 2, "temperature": 0,
            "seed": 0, "grammar": GRAMMAR, "cache_prompt": True,
        })
        if depth is None:
            depth = res.get("timings", {}).get("prompt_n", -1)
            print(f"  first-request prompt_n={depth} tokens", flush=True)
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
for target, ctx, name in DEPTHS:
    NAME = f"{name}-Qwen3.6-27B-Q8_0w"
    pad_n = None
    for ctk, ctv, suffix in LEGS:
        out_file = RESULTS / f"kv-{NAME}-{ctk}k-{ctv}v{suffix}.json"
        if out_file.exists():
            print(f"[{NAME} {ctk}k/{ctv}v{suffix}] already done, skipping", flush=True)
            continue
        label = f"{NAME} {ctk}k/{ctv}v{suffix}"
        print(f"[{label}] serving + {len(TARGETS)} targets", flush=True)
        proc = serve(ctk, ctv, ctx, f"{name}-{ctk}k-{ctv}v{suffix or ''}.log")
        if proc is None:
            continue
        try:
            if pad_n is None:
                pad_n, pad_t = size_pad(target)
            pmsgs = pad_msgs(pad_n)
            answers = sheet(label, pmsgs)
        finally:
            proc.terminate()
            proc.wait(timeout=30)
        out_file.write_text(json.dumps(answers, indent=0))
        time.sleep(3)

    base_f = RESULTS / f"kv-{NAME}-f16k-f16v.json"
    if not base_f.exists():
        continue
    base = json.loads(base_f.read_text())
    rep2_f = RESULTS / f"kv-{NAME}-f16k-f16v-rep2.json"
    if rep2_f.exists():
        rep2 = json.loads(rep2_f.read_text())
        mism = sum(1 for k in base if base[k]["ans"] != rep2[k]["ans"])
        print(f"[{NAME}] determinism: {'PASS' if mism == 0 else f'FAIL ({mism}) — DISCARD THIS DEPTH'}", flush=True)
    for ctk, ctv, suffix in LEGS[2:]:
        f = RESULTS / f"kv-{NAME}-{ctk}k-{ctv}v.json"
        if not f.exists():
            continue
        r = json.loads(f.read_text())
        acc = sum(v["ok"] for v in r.values()) / len(r)
        changed = [k for k in base if base[k]["ans"] != r[k]["ans"]]
        print(f"[{NAME}] {ctk}k/{ctv}v: acc={acc:.3f} changed_vs_f16={len(changed)}/{len(base)} {changed[:8]}", flush=True)

print("DEEP SWEEP 20K/40K COMPLETE", flush=True)
