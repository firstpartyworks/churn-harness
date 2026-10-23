#!/usr/bin/env python3
"""Same browser-coding tasks for any OpenAI-compatible server, thinking on, Qwen's recommended
thinking sampler, fixed seeds. Saves the thinking, the reply, the extracted HTML and the timings.

  python3 coding_bench.py --url http://127.0.0.1:8083 --label flashnext --out runs/
"""
import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

TASKS = {
    "breakout": (
        "Write a complete browser game in a single HTML file (inline CSS and JavaScript, no external "
        "libraries, images or fonts): a Breakout-style brick breaker. Paddle controlled by the mouse and the "
        "arrow keys, ball physics with angle depending on where it hits the paddle, at least 5 rows of "
        "colored bricks, score, 3 lives, a start screen, game-over and win screens, and R to restart. "
        "Reply with only the HTML file in one code block."),
    "towerdefense": (
        "Write a complete browser game in a single HTML file (inline CSS and JavaScript, no external "
        "libraries, images or fonts): a small tower-defense game. Enemies walk along a fixed winding path "
        "in waves that get harder; the player clicks empty grid cells to place towers that cost gold and "
        "shoot the nearest enemy in range; killing enemies earns gold; enemies that reach the end cost "
        "lives. Show gold, lives and wave number, a button to start the next wave, and a game-over screen. "
        "Reply with only the HTML file in one code block."),
}
SAMPLER = {"temperature": 0.6, "top_p": 0.95, "top_k": 20}


def ask(url, prompt, seed, max_tokens, effort=""):
    kw = {"enable_thinking": effort != "off"}
    if effort and effort != "off":
        kw["reasoning_effort"] = effort
    body = {"messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "seed": seed,
            "chat_template_kwargs": kw, "cache_prompt": False, **SAMPLER}
    req = urllib.request.Request(f"{url}/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t = time.time()
    res = json.load(urllib.request.urlopen(req, timeout=7200))
    return res, time.time() - t


def extract_html(text):
    blocks = re.findall(r"```(?:html)?\s*\n(.*?)```", text, re.S | re.I)
    if blocks:
        return max(blocks, key=len)
    m = re.search(r"<!DOCTYPE html.*?</html>|<html.*?</html>", text, re.S | re.I)
    return m.group(0) if m else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--max-tokens", type=int, default=30000)
    ap.add_argument("--effort", default="", help="template reasoning_effort: low, medium, xhigh; off = thinking off")
    ap.add_argument("--only", default="", help="comma list of task-sN to run, e.g. breakout-s1")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for task, prompt in TASKS.items():
        for seed in map(int, a.seeds.split(",")):
            if a.only and f"{task}-s{seed}" not in a.only.split(","):
                continue
            stem = out / f"{a.label}-{task}-s{seed}"
            if stem.with_suffix(".json").exists():
                continue
            res, wall = ask(a.url, prompt, seed, a.max_tokens, a.effort)
            msg = res["choices"][0]["message"]
            reply, think = msg.get("content") or "", msg.get("reasoning_content") or ""
            html = extract_html(reply)
            tm, usage = res.get("timings") or {}, res.get("usage") or {}
            rec = {"label": a.label, "task": task, "seed": seed, "sampler": SAMPLER, "effort": a.effort or "default (xhigh)", "max_tokens": a.max_tokens,
                   "finish": res["choices"][0].get("finish_reason"), "wall_s": round(wall, 1),
                   "completion_tokens": usage.get("completion_tokens") or tm.get("predicted_n"),
                   "gen_tps": tm.get("predicted_per_second"), "draft_n": tm.get("draft_n"),
                   "draft_accepted": tm.get("draft_n_accepted"),
                   "think_chars": len(think), "reply_chars": len(reply), "html_chars": len(html),
                   "thinking": think, "reply": reply}
            stem.with_suffix(".json").write_text(json.dumps(rec, indent=1))
            if html:
                stem.with_suffix(".html").write_text(html)
            print(f"{stem.name}: {rec['finish']} {rec['completion_tokens']} tok {rec['wall_s']}s "
                  f"think {len(think)} ch, html {len(html)} ch", flush=True)


if __name__ == "__main__":
    main()
