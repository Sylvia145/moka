"""运行五任务 scripted 上下文压缩成对评测。"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pico.evaluation.context_cost import generate_report, run_paired_experiment


def main(argv=None):
    """执行命令行入口。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="artifacts/context-compression-benchmark")
    parser.add_argument("--tasks", default="benchmarks/long_session_tasks.json")
    parser.add_argument("--repetitions", type=int, default=1)
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))["tasks"]
    results = run_paired_experiment(
        tasks=tasks,
        variants=["no_context_reduction", "full_orchestrator"],
        mode="scripted",
        provider=None,
        repetitions=args.repetitions,
        output_dir=output_dir / "work",
    )
    (output_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        generate_report(results) + "\n", encoding="utf-8"
    )
    print(f"Results: {output_dir / 'results.json'}")
    print(f"Report: {output_dir / 'report.md'}")


if __name__ == "__main__":
    main()
