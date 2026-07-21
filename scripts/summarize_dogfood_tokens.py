"""Pico 项目运行与验证脚本。

Reads every trace.jsonl under artifacts/dogfood-deepseek and sums the
`completion_metadata` (provider-billed, not estimated) on each `model_parsed`
event. This is the actual-usage counterpart to the estimated_proxy numbers in
engineering/iterations/10-evaluation-results.md.
"""
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLOB = str(ROOT / "artifacts" / "dogfood-deepseek" / "workspaces" / "*" / ".pico" / "runs" / "*" / "trace.jsonl")

totals = {"input": 0, "output": 0, "cached": 0}
calls = 0
cache_hits = 0
per_scenario = {}

for f in sorted(glob.glob(GLOB)):
    scenario = Path(f).parts[-5]  # 工作区/<场景>/.pico/runs/<运行>/trace.jsonl
    s = {"input": 0, "output": 0, "cached": 0, "calls": 0, "cache_hits": 0}
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("event") != "model_parsed":
                continue
            cm = e.get("completion_metadata", {})
            s["calls"] += 1
            s["input"] += cm.get("input_tokens") or 0
            s["output"] += cm.get("output_tokens") or 0
            s["cached"] += cm.get("cached_tokens") or 0
            if cm.get("cache_hit"):
                s["cache_hits"] += 1
    per_scenario.setdefault(scenario, {"input": 0, "output": 0, "cached": 0, "calls": 0, "cache_hits": 0})
    for k in ("input", "output", "cached", "calls", "cache_hits"):
        per_scenario[scenario][k] += s[k]
    for k in ("input", "output", "cached"):
        totals[k] += s[k]
    calls += s["calls"]
    cache_hits += s["cache_hits"]

for name, s in sorted(per_scenario.items()):
    print(f"{name}: calls={s['calls']} input={s['input']} output={s['output']} cached={s['cached']} cache_hits={s['cache_hits']}")
print(f"TOTAL: calls={calls} input_tokens={totals['input']} output_tokens={totals['output']} cached_tokens={totals['cached']} cache_hits={cache_hits}")
