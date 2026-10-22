#!/usr/bin/env python3
"""Engine-neutral answer sheet: ask a multiple-choice set through any
OpenAI-compatible server and save every answer.

run_bench.py forces a single letter with a llama.cpp grammar. Engines without
grammar support (Strata, for one) can't take that protocol, so this one is
unconstrained and identical for every engine: chat completions, temperature 0,
thinking off, a few tokens, first choice letter in the reply. Compare engines
only on sheets made by this script, never against run_bench.py sheets.

  python3 engine_bench.py --url http://127.0.0.1:8080 --set arc-challenge-500.json --out results/x.json
  python3 engine_bench.py --diff results/a.json results/b.json
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

SYSTEM = ("You are taking a multiple-choice test. "
          "Answer with only the letter of the correct choice.")


def load_set(path):
    data = json.loads(Path(path).read_text())
    return data if isinstance(data, list) else data["questions"]


def qtext(q):
    letters = "ABCDEFGHIJ"[:len(q["choices"])]
    return q["question"] + "\n" + "\n".join(f"{l}. {c}" for l, c in zip(letters, q["choices"]))


def pad_history(pool, n):
    msgs = []
    for i in range(n):
        q = pool[i % len(pool)]
        msgs += [{"role": "user", "content": qtext(q)}, {"role": "assistant", "content": q["answer"]}]
    return msgs


def ask(url, q, max_tokens, history=()):
    letters = "ABCDEFGHIJ"[:len(q["choices"])]
    msgs = [{"role": "system", "content": SYSTEM}, *history, {"role": "user", "content": qtext(q)}]
    # A padded run shares one long prefix across questions, so the cached prefix is reused.
    body = {"messages": msgs, "temperature": 0, "seed": 0, "max_tokens": max_tokens,
            "reasoning_effort": "none", "cache_prompt": bool(history),
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(f"{url}/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    res = json.load(urllib.request.urlopen(req, timeout=600))
    text = res["choices"][0]["message"].get("content") or ""
    m = re.search(rf"\b([{letters}])\b", text.strip())
    return (m.group(1) if m else ""), text, res.get("timings") or {}


def run(args):
    qs = load_set(args.set)[:args.limit or None]
    history = []
    if args.pad_questions:
        pool = load_set(args.padpool)
        overlap = {str(q["id"]) for q in qs} & {str(q["id"]) for q in pool}
        if overlap:
            sys.exit(f"pad pool shares {len(overlap)} questions with the set")
        history = pad_history(pool, args.pad_questions)
    out = Path(args.out)
    sheet = json.loads(out.read_text()) if out.exists() else {"meta": {}, "answers": {}}
    sheet["meta"].update({"url": args.url, "set": Path(args.set).name, "label": args.label,
                          "pad_questions": args.pad_questions,
                          "started": sheet["meta"].get("started") or time.strftime("%Y-%m-%dT%H:%M:%S")})
    t0 = time.time()
    for i, q in enumerate(qs):
        qid = str(q["id"])
        if qid in sheet["answers"]:
            continue
        ans, text, tm = ask(args.url, q, args.max_tokens, history)
        sheet["answers"][qid] = {"ans": ans, "ok": ans == q["answer"], "raw": text[:80],
                                 "decode_tps": tm.get("predicted_per_second")}
        if history and "prompt_tokens" not in sheet["meta"]:
            sheet["meta"]["prompt_tokens"] = (tm.get("prompt_n") or 0) + (tm.get("cache_n") or 0)
            print(f"  first padded prompt: {sheet['meta']['prompt_tokens']} tokens", flush=True)
        if (i + 1) % 50 == 0:
            out.write_text(json.dumps(sheet, indent=0))
            a = sheet["answers"].values()
            print(f"  {i+1}/{len(qs)} acc {sum(v['ok'] for v in a)/len(sheet['answers']):.3f} "
                  f"({(time.time()-t0)/(i+1):.2f}s/q)", flush=True)
    a = sheet["answers"].values()
    sheet["meta"]["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    sheet["meta"]["accuracy"] = sum(v["ok"] for v in a) / len(sheet["answers"])
    sheet["meta"]["unparsed"] = sum(1 for v in a if not v["ans"])
    out.write_text(json.dumps(sheet, indent=0))
    print(f"DONE {args.label or out.stem}: acc {sheet['meta']['accuracy']:.3f}, "
          f"unparsed {sheet['meta']['unparsed']}", flush=True)


def diff(a_path, b_path):
    a = json.loads(Path(a_path).read_text())["answers"]
    b = json.loads(Path(b_path).read_text())["answers"]
    common = sorted(set(a) & set(b))
    changed = [k for k in common if a[k]["ans"] != b[k]["ans"]]
    lost = sum(1 for k in changed if a[k]["ok"] and not b[k]["ok"])
    gained = sum(1 for k in changed if b[k]["ok"] and not a[k]["ok"])
    acc_a = sum(a[k]["ok"] for k in common) / len(common)
    acc_b = sum(b[k]["ok"] for k in common) / len(common)
    print(f"{Path(a_path).stem} -> {Path(b_path).stem}: n={len(common)} "
          f"acc {acc_a:.3f} -> {acc_b:.3f}; changed {len(changed)} "
          f"({100*len(changed)/len(common):.1f}%), lost {lost}, gained {gained}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--set")
    ap.add_argument("--out")
    ap.add_argument("--label", default="")
    ap.add_argument("--max-tokens", type=int, default=8)
    ap.add_argument("--diff", nargs=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pad-questions", type=int, default=0,
                    help="prepend this many pad-pool Q/A turns as chat history (long-context run)")
    ap.add_argument("--padpool", default=str(Path(__file__).resolve().parent / "arc-challenge-padpool.json"))
    args = ap.parse_args()
    if args.diff:
        diff(*args.diff)
    elif args.url and args.set and args.out:
        run(args)
    else:
        sys.exit("need --url --set --out, or --diff A B")
