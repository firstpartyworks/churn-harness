#!/usr/bin/env python3
"""One fix turn: the original task, the model's own broken reply (thinking dropped, as chat apps do), then a
symptom-only bug report from the player. Same sampler and seeds as coding_bench.py.

  python3 fix_bench.py --url http://127.0.0.1:8083 --run runs64k/flashnext-breakout-s2.json \
      --report "..." --label flashnext-fix --out runs-fix/
"""
import argparse
import json
from pathlib import Path

from coding_bench import SAMPLER, TASKS, extract_html
import time
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--run", required=True, help="the original run's .json")
    ap.add_argument("--report", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--max-tokens", type=int, default=48000)
    a = ap.parse_args()
    orig = json.loads(Path(a.run).read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    msgs = [{"role": "user", "content": TASKS[orig["task"]]},
            {"role": "assistant", "content": orig["reply"]},
            {"role": "user", "content": a.report}]
    for seed in map(int, a.seeds.split(",")):
        stem = out / f"{a.label}-{orig['task']}-orig-s{orig['seed']}-fix-s{seed}"
        if stem.with_suffix(".json").exists():
            continue
        body = {"messages": msgs, "max_tokens": a.max_tokens, "seed": seed, "cache_prompt": False,
                "chat_template_kwargs": {"enable_thinking": True}, **SAMPLER}
        req = urllib.request.Request(f"{a.url}/v1/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        t = time.time()
        res = json.load(urllib.request.urlopen(req, timeout=7200))
        wall = time.time() - t
        msg = res["choices"][0]["message"]
        reply, think = msg.get("content") or "", msg.get("reasoning_content") or ""
        html = extract_html(reply)
        tm, usage = res.get("timings") or {}, res.get("usage") or {}
        rec = {"label": a.label, "task": orig["task"], "orig_seed": orig["seed"], "seed": seed, "report": a.report,
               "finish": res["choices"][0].get("finish_reason"), "wall_s": round(wall, 1),
               "prompt_tokens": usage.get("prompt_tokens"),
               "completion_tokens": usage.get("completion_tokens") or tm.get("predicted_n"),
               "gen_tps": tm.get("predicted_per_second"), "think_chars": len(think), "reply_chars": len(reply),
               "html_chars": len(html), "thinking": think, "reply": reply}
        stem.with_suffix(".json").write_text(json.dumps(rec, indent=1))
        if html:
            stem.with_suffix(".html").write_text(html)
        print(f"{stem.name}: {rec['finish']} prompt {rec['prompt_tokens']} gen {rec['completion_tokens']} tok "
              f"{rec['wall_s']}s, html {len(html)} ch", flush=True)


if __name__ == "__main__":
    main()
