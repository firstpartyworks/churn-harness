#!/usr/bin/env python3
"""Deep-context KV-cache answer churn — the same determinism instrument as
kv_bench.py, but every question is asked from thousands of tokens deep.

The prompt is a genuine quiz session: enough held-out multiple-choice
questions (arc-challenge-padpool.json) are prepended as user/assistant
chat history to reach the target depth — sized against the model's own
tokenizer via the server's /tokenize — then the target question is asked.
The pad pool and the target set share no questions, so there is no answer
leakage. Depths beyond what the pool holds (~60k tokens for the stock
pool) cycle it, repeating pad questions — the cache still stores every
token, so it remains a real KV stress, just with repeated history.

Per depth the cache-type legs run against an f16-cache baseline, and the
baseline runs TWICE: with temp 0, seed 0, a single-letter grammar,
--parallel 1 and prefix caching, the two f16 sheets must come back
byte-identical or that depth's flip counts are not trustworthy (the
script says so loudly). Flash attention is on for every leg including the
baseline (quantized V cache requires it; keeping it on everywhere means
cache type is the only variable).

Setup:
  export CHURN_LLAMA_BIN=/path/to/llama.cpp/build/bin

Run:
  python3 kv_deep.py --gguf /path/to/model.gguf                # 8k deep
  python3 kv_deep.py --gguf model.gguf --depths 8k,20k,40k,80k,120k
  python3 kv_deep.py --gguf model.gguf --legs q8_0,q4_0,q4_0:f16
  python3 kv_deep.py --gguf model.gguf --limit 25              # smoke run

Thinking models need --think-off (the template check aborts with a hint
if you forget). Context per leg is depth + --ctx-headroom; if the f16
cache at that size doesn't fit your GPU, the server log under logs/ will
say so.

Writes results/kv-deep<depth>-<name>-<K>k-<V>v.json; finished legs are
skipped on re-run, so a sweep resumes for free. kv_analyze.py picks the
files up for tables.
"""
import argparse, json, os, shlex, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = HERE / "results"
LOGS = HERE / "logs"
GRAMMAR = 'root ::= "A" | "B" | "C" | "D"'

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("--gguf", required=True, help="model file to serve")
ap.add_argument("--name", default=None,
                help="label used in result filenames (default: gguf stem)")
ap.add_argument("--depths", default="8k",
                help="comma list of token depths, e.g. 8k,20k,40k or 12000")
ap.add_argument("--legs", default="q8_0,q4_0",
                help="comma list of cache types to diff against f16; "
                     "K:V syntax for splits, e.g. q8_0,q4_0,q4_0:f16")
ap.add_argument("--think-off", action="store_true",
                help="render with enable_thinking=false (thinking models)")
ap.add_argument("--ctx-headroom", type=int, default=2048,
                help="context on top of depth for the question + answer")
ap.add_argument("--port", type=int, default=4989)
ap.add_argument("--questions", default=str(HERE / "arc-challenge-500.json"),
                help="target questions (see README for the shape)")
ap.add_argument("--padpool", default=str(HERE / "arc-challenge-padpool.json"),
                help="held-out questions used only as chat-history padding")
ap.add_argument("--limit", type=int, default=0,
                help="only ask the first N targets (files get a -nN suffix "
                     "so smoke runs never masquerade as full sheets)")
ap.add_argument("--server-args", default="",
                help="extra llama-server flags, e.g. rope scaling to reach "
                     "past the model's trained context")
args = ap.parse_args()

BIN = Path(os.environ.get("CHURN_LLAMA_BIN", ""))
if not BIN.is_dir():
    sys.exit("set CHURN_LLAMA_BIN to your llama.cpp build/bin directory "
             "(needs llama-server, built with flash attention)")
GGUF = Path(args.gguf)
if not GGUF.exists():
    sys.exit(f"missing model file: {GGUF}")
NAME = args.name or GGUF.stem
CT_KWARGS = {"enable_thinking": False} if args.think_off else {}

TARGETS = json.loads(Path(args.questions).read_text())
POOL = json.loads(Path(args.padpool).read_text())
overlap = {q["id"] for q in TARGETS} & {q["id"] for q in POOL}
if overlap:
    sys.exit(f"pad pool overlaps targets ({len(overlap)} shared ids) — "
             f"that leaks answers into the context; fix the files")
SUFFIX_N = ""
if args.limit:
    TARGETS = TARGETS[:args.limit]
    SUFFIX_N = f"-n{args.limit}"

SYS = {"role": "system", "content": "You are taking a multiple-choice science test. Answer with only the letter of the correct choice."}


def parse_depth(s):
    s = s.strip().lower()
    return (int(float(s[:-1]) * 1024), s) if s.endswith("k") else (int(s), s)


def parse_leg(s):
    k, _, v = s.strip().partition(":")
    return (k, v or k)


DEPTHS = [parse_depth(d) for d in args.depths.split(",")]
USER_LEGS = [parse_leg(l) for l in args.legs.split(",")]


def qtext(q):
    return q["question"] + "\n" + "\n".join(
        f"{l}. {c}" for l, c in zip("ABCD", q["choices"]))


def pad_msgs(n):
    msgs = [SYS]
    for i in range(n):
        q = POOL[i % len(POOL)]
        msgs.append({"role": "user", "content": qtext(q)})
        msgs.append({"role": "assistant", "content": q["answer"]})
    return msgs


def post(path, payload, timeout=900):
    req = urllib.request.Request(
        f"http://127.0.0.1:{args.port}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def serve(ctk, ctv, ctx, logname):
    log = open(LOGS / logname, "w")
    proc = subprocess.Popen(
        [str(BIN / "llama-server"), "-m", str(GGUF), "--port", str(args.port),
         "-ngl", "99", "-c", str(ctx), "--no-webui", "-fa", "on",
         "--parallel", "1", "-ctk", ctk, "-ctv", ctv]
        + shlex.split(args.server_args),
        env={**os.environ, "LD_LIBRARY_PATH": str(BIN)},
        stdout=log, stderr=log)
    for _ in range(360):
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{args.port}/health", timeout=2)
            return proc
        except Exception:
            if proc.poll() is not None:
                print(f"SERVER DIED for {ctk}k/{ctv}v ctx={ctx} — see "
                      f"logs/{logname} (an f16 cache at that size may not "
                      f"fit your GPU)", flush=True)
                return None
            time.sleep(1)
    proc.kill()
    print(f"SERVER NEVER HEALTHY for {ctk}k/{ctv}v — see logs/{logname}", flush=True)
    return None


def server_ctx():
    """The context the server actually granted (it silently caps -c at the
    model's trained context and rejects longer requests)."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{args.port}/props", timeout=5) as r:
            props = json.load(r)
        return ((props.get("default_generation_settings") or {}).get("n_ctx")
                or props.get("n_ctx"))
    except Exception:
        return None


def render(msgs):
    body = {"messages": msgs}
    if CT_KWARGS:
        body["chat_template_kwargs"] = CT_KWARGS
    return post("/apply-template", body)["prompt"]


def ntokens(msgs):
    return len(post("/tokenize", {"content": render(msgs)})["tokens"])


def check_template():
    p = render(pad_msgs(1) + [{"role": "user", "content": "ping"}])
    tail = p[-120:].replace("\n", "\\n")
    print(f"template tail: ...{tail}", flush=True)
    if p.rstrip().endswith("<think>"):
        sys.exit("rendered template leaves an OPEN <think> block — the "
                 "grammar would force answers inside the reasoning span; "
                 "re-run with --think-off")


def size_pad(target):
    """Smallest pad-question count whose rendered chat reaches target
    tokens; the pool cycles when the depth needs more questions than it
    holds."""
    n, cap = 10, 100_000
    t = ntokens(pad_msgs(n))
    while t < target and n < cap:
        per_q = max(1, t // n)
        n = min(cap, n + max(1, (target - t) // per_q))
        t = ntokens(pad_msgs(n))
    cycled = f" (pool of {len(POOL)} cycled)" if n > len(POOL) else ""
    print(f"  pad sized: {n} questions -> {t} tokens (target {target}){cycled}", flush=True)
    return n


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


RESULTS.mkdir(exist_ok=True)
LOGS.mkdir(exist_ok=True)
for target, dlabel in DEPTHS:
    run = f"deep{dlabel}-{NAME}{SUFFIX_N}"
    ctx = target + args.ctx_headroom
    legs = [("f16", "f16", ""), ("f16", "f16", "-rep2")] + \
           [(k, v, "") for k, v in USER_LEGS]
    pad_n = None
    for ctk, ctv, suffix in legs:
        out_file = RESULTS / f"kv-{run}-{ctk}k-{ctv}v{suffix}.json"
        if out_file.exists():
            print(f"[{run} {ctk}k/{ctv}v{suffix}] already done, skipping", flush=True)
            continue
        label = f"{run} {ctk}k/{ctv}v{suffix}"
        print(f"[{label}] serving + {len(TARGETS)} targets", flush=True)
        proc = serve(ctk, ctv, ctx, f"{run}-{ctk}k-{ctv}v{suffix or ''}.log")
        if proc is None:
            continue
        got = server_ctx()
        if got and got + 256 < ctx:
            print(f"[{run}] server granted only {got} context of the {ctx} "
                  f"this depth needs (the model's trained limit) — skipping "
                  f"this depth. Use a longer-context model, or pass rope "
                  f"scaling via --server-args if you accept the tradeoffs.",
                  flush=True)
            proc.terminate()
            proc.wait(timeout=30)
            break
        try:
            check_template()
            if pad_n is None:
                pad_n = size_pad(target)
            answers = sheet(label, pad_msgs(pad_n))
        finally:
            proc.terminate()
            proc.wait(timeout=30)
        out_file.write_text(json.dumps(answers, indent=0))
        time.sleep(3)

    base_f = RESULTS / f"kv-{run}-f16k-f16v.json"
    if not base_f.exists():
        continue
    base = json.loads(base_f.read_text())
    rep2_f = RESULTS / f"kv-{run}-f16k-f16v-rep2.json"
    if rep2_f.exists():
        rep2 = json.loads(rep2_f.read_text())
        mism = sum(1 for k in base if base[k]["ans"] != rep2[k]["ans"])
        print(f"[{run}] determinism (cached-prefix): "
              f"{'PASS' if mism == 0 else f'FAIL ({mism} mismatches) — DISCARD THIS DEPTH'}",
              flush=True)
    # depth effect alone, if a short-context kv_bench.py baseline exists
    short_f = RESULTS / f"kv-{NAME}-f16k-f16v.json"
    if short_f.exists():
        short = json.loads(short_f.read_text())
        both = [k for k in base if k in short]
        moved = sum(1 for k in both if base[k]["ans"] != short[k]["ans"])
        print(f"[{run}] depth effect alone (f16 cache, short vs deep): "
              f"{moved}/{len(both)} answers differ", flush=True)
    for ctk, ctv in USER_LEGS:
        f = RESULTS / f"kv-{run}-{ctk}k-{ctv}v.json"
        if not f.exists():
            continue
        r = json.loads(f.read_text())
        acc = sum(v["ok"] for v in r.values()) / len(r)
        changed = [k for k in base if base[k]["ans"] != r[k]["ans"]]
        print(f"[{run}] {ctk}k/{ctv}v: acc={acc:.3f} "
              f"changed_vs_f16={len(changed)}/{len(base)} {changed[:8]}", flush=True)

print("DEEP-CONTEXT SWEEP COMPLETE", flush=True)
