#!/usr/bin/env python3
"""运行可审计记忆跨 Session 演示与评测。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pico.evaluation.memory_e2e_demo import (
    run_live_memory_e2e_smoke,
    run_memory_e2e_demo_v1,
)


def build_arg_parser():
    """构造演示脚本参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("scripted", "live"), default="scripted")
    parser.add_argument("--provider", default="openai", help="真实模型冒烟使用的 provider profile")
    parser.add_argument("--output", type=Path, required=True, help="写入脱敏摘要 artifact 的路径")
    parser.add_argument("--evidence-root", type=Path, default=None, help="scripted 运行证据的保存目录")
    return parser


def main(argv=None):
    """执行脚本入口。"""
    args = build_arg_parser().parse_args(argv)
    if args.mode == "live":
        artifact = run_live_memory_e2e_smoke(args.output, args.provider)
    else:
        artifact = run_memory_e2e_demo_v1(args.output, evidence_root=args.evidence_root)
    print(json.dumps(artifact.get("summary", artifact), ensure_ascii=False))
    return 0 if artifact.get("summary", {}).get("failed", 0) == 0 and artifact.get("status", "passed") != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
