from pathlib import Path


def test_core_modules_stay_below_entropy_budget():
    root = Path(__file__).resolve().parents[1]
    budgets = {
        "pico/core/runtime.py": 950,
        "pico/core/engine.py": 450,
        "pico/core/permissions.py": 140,
        "pico/core/plan_mode.py": 140,
        "pico/core/tool_executor.py": 180,
        "pico/core/tool_profiles.py": 80,
        "pico/tools/registry.py": 360,
    }

    for relative_path, max_lines in budgets.items():
        line_count = len((root / relative_path).read_text(encoding="utf-8").splitlines())
        assert line_count <= max_lines, f"{relative_path} has {line_count} lines, budget is {max_lines}"
