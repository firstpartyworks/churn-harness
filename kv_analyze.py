#!/usr/bin/env python3
"""Analysis over kv_bench.py results: per cache mode vs the f16-cache
baseline — accuracy (Wilson CI), answers changed with a Wilson CI on the
FLIP RATE (the number comment sections attack first), lost/gained/net,
correctness agreement, and showcase flips (right at f16+q8_0 cache, wrong
at q4_0). Prints markdown, writes results/kv-analysis.json.
"""
import json, math
from pathlib import Path

HERE = Path(__file__).parent
RES = HERE / "results"
MODES = ["f16k-f16v", "q8_0k-q8_0v", "q4_0k-q4_0v", "q4_0k-f16v", "f16k-q4_0v"]
LABELS = {
    "f16k-f16v": "f16 cache (baseline)", "q8_0k-q8_0v": "q8_0 K+V",
    "q4_0k-q4_0v": "q4_0 K+V", "q4_0k-f16v": "q4_0 K only",
    "f16k-q4_0v": "q4_0 V only",
}

QS = {q["id"]: q for q in json.loads((HERE / "arc-challenge-500.json").read_text())}


def wilson(p, n, z=1.96):
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - s) / d, (c + s) / d)


models = sorted({f.name[3:].rsplit("-", 2)[0] for f in RES.glob("kv-*.json")
                 if not f.name.endswith(("rep2.json", "meta.json", "analysis.json"))})
out = {"modes": MODES, "n": len(QS), "models": {}}
for model in models:
    runs = {}
    for mode in MODES:
        f = RES / f"kv-{model}-{mode}.json"
        if f.exists():
            runs[mode] = json.loads(f.read_text())
    if "f16k-f16v" not in runs or len(runs) < 2:
        continue
    base = runs["f16k-f16v"]
    rep2f = RES / f"kv-{model}-f16k-f16v-rep2.json"
    det = None
    if rep2f.exists():
        rep2 = json.loads(rep2f.read_text())
        det = sum(1 for k in base if base[k]["ans"] != rep2[k]["ans"])
    m = {"determinism_mismatches": det, "accuracy": {}, "vs_base": {}, "showcase": []}
    for mode, ans in runs.items():
        n = len(ans)
        acc = sum(v["ok"] for v in ans.values()) / n
        lo, hi = wilson(acc, n)
        m["accuracy"][mode] = {"acc": round(acc, 4), "ci": [round(lo, 4), round(hi, 4)]}
        if mode != "f16k-f16v":
            changed = [k for k in ans if ans[k]["ans"] != base[k]["ans"]]
            gained = [k for k in ans if ans[k]["ok"] and not base[k]["ok"]]
            lost = [k for k in ans if not ans[k]["ok"] and base[k]["ok"]]
            fr = len(changed) / n
            flo, fhi = wilson(fr, n)
            both = sum(1 for k in ans if ans[k]["ok"] and base[k]["ok"])
            m["vs_base"][mode] = {
                "answers_changed": len(changed), "flip_rate": round(fr, 4),
                "flip_rate_ci": [round(flo, 4), round(fhi, 4)],
                "flips_gained": len(gained), "flips_lost": len(lost),
                "net": len(gained) - len(lost),
                "correctness_agreement": round(both / n, 4),
                "changed_ids": changed,
            }
    if all(k in runs for k in ("q8_0k-q8_0v", "q4_0k-q4_0v")):
        for k, q in QS.items():
            if k not in base or k not in runs["q8_0k-q8_0v"] or k not in runs["q4_0k-q4_0v"]:
                continue
            if (base[k]["ok"] and runs["q8_0k-q8_0v"][k]["ok"]
                    and not runs["q4_0k-q4_0v"][k]["ok"]):
                m["showcase"].append({
                    "id": k, "question": q["question"], "choices": q["choices"],
                    "answer": q["answer"],
                    "answers_by_mode": {mm: runs[mm][k]["ans"] for mm in runs},
                })
    out["models"][model] = m

(RES / "kv-analysis.json").write_text(json.dumps(out, indent=1))

for model, m in out["models"].items():
    det = m["determinism_mismatches"]
    det_s = "not run" if det is None else ("PASS (0 mismatches)" if det == 0 else f"FAIL ({det} mismatches)")
    print(f"\n## {model} (n={out['n']}, baseline determinism: {det_s})")
    print("| cache mode | accuracy | 95% CI | changed vs f16 cache | flip rate (95% CI) | lost | gained | net | CA |")
    print("|---|---|---|---|---|---|---|---|---|")
    for mode in MODES:
        if mode not in m["accuracy"]:
            continue
        a = m["accuracy"][mode]
        v = m["vs_base"].get(mode, {})
        fr = (f"{v['flip_rate']*100:.1f}% ({v['flip_rate_ci'][0]*100:.1f}–{v['flip_rate_ci'][1]*100:.1f}%)"
              if v else "—")
        print(f"| {LABELS[mode]} | {a['acc']*100:.1f}% | {a['ci'][0]*100:.1f}–{a['ci'][1]*100:.1f}% "
              f"| {v.get('answers_changed','—')} | {fr} | {v.get('flips_lost','—')} "
              f"| {v.get('flips_gained','—')} | {v.get('net','—')} "
              f"| {v.get('correctness_agreement','—')} |")
    print(f"showcase flips (f16✓ q8✓ q4✗): {len(m['showcase'])}")
