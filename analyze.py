#!/usr/bin/env python3
"""Churn analysis over run_bench.py results: accuracy per rung (Wilson CIs),
flips vs the F16 baseline (gained/lost/net), correctness agreement, and
showcase flip candidates (stable-correct at Q8/Q6, wrong at Q4_K_M — the
'same score, different answers' payoff shot).

Writes results/analysis.json (chart-ready) + prints a markdown summary.
"""
import json, math
from pathlib import Path

HERE = Path(__file__).parent
RES = HERE / "results"
QUANTS = ["F16", "Q8_0", "Q6_K", "Q4_K_M", "Q3_K_M", "Q2_K"]
MODELS = ["qwen2.5-7b-instruct", "mistral-7b-instruct-v0.3"]

QS = {q["id"]: q for q in json.loads((HERE / "arc-challenge-500.json").read_text())}


def wilson(p, n, z=1.96):
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - s) / d, (c + s) / d)


out = {"quants": QUANTS, "n": len(QS), "models": {}}
for model in MODELS:
    runs = {}
    for q in QUANTS:
        f = RES / f"{model}-{q}.json"
        if f.exists():
            runs[q] = json.loads(f.read_text())
    if len(runs) < 2:
        continue
    base_name = "F16" if "F16" in runs else "Q8_0"
    base = runs.get(base_name)
    m = {"baseline": base_name, "accuracy": {}, "vs_base": {}, "showcase": []}
    for quant, ans in runs.items():
        n = len(ans)
        acc = sum(v["ok"] for v in ans.values()) / n
        lo, hi = wilson(acc, n)
        m["accuracy"][quant] = {"acc": round(acc, 4), "ci": [round(lo, 4), round(hi, 4)]}
        if base and quant != base_name:
            gained = [k for k in ans if ans[k]["ok"] and not base[k]["ok"]]
            lost = [k for k in ans if not ans[k]["ok"] and base[k]["ok"]]
            changed = [k for k in ans if ans[k]["ans"] != base[k]["ans"]]
            both = sum(1 for k in ans if ans[k]["ok"] and base[k]["ok"])
            m["vs_base"][quant] = {
                "answers_changed": len(changed), "flips_gained": len(gained),
                "flips_lost": len(lost), "net": len(gained) - len(lost),
                "correctness_agreement": round(both / len(ans), 4),
            }
    # showcase: right at base AND Q8/Q6, wrong at Q4_K_M (and note deeper rungs)
    if all(q in runs for q in ("Q8_0", "Q6_K", "Q4_K_M")):
        for k, q in QS.items():
            if (base[k]["ok"] and runs["Q8_0"][k]["ok"] and runs["Q6_K"][k]["ok"]
                    and not runs["Q4_K_M"][k]["ok"]):
                m["showcase"].append({
                    "id": k, "question": q["question"], "choices": q["choices"],
                    "answer": q["answer"],
                    "answers_by_quant": {qq: runs[qq][k]["ans"] for qq in runs},
                })
    out["models"][model] = m

(RES / "analysis.json").write_text(json.dumps(out, indent=1))

for model, m in out["models"].items():
    print(f"\n## {model} (n={out['n']})")
    print(f"| quant | accuracy | 95% CI | answers changed vs {m['baseline']} | lost | gained | net | CA w/ base |")
    print("|---|---|---|---|---|---|---|---|")
    for q in QUANTS:
        if q not in m["accuracy"]:
            continue
        a = m["accuracy"][q]
        v = m["vs_base"].get(q, {})
        print(f"| {q} | {a['acc']*100:.1f}% | {a['ci'][0]*100:.1f}–{a['ci'][1]*100:.1f}% "
              f"| {v.get('answers_changed','—')} | {v.get('flips_lost','—')} "
              f"| {v.get('flips_gained','—')} | {v.get('net','—')} "
              f"| {v.get('correctness_agreement','—')} |")
    print(f"showcase flip candidates (Q8✓ Q6✓ Q4_K_M✗): {len(m['showcase'])}")
