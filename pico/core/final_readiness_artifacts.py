"""Pico 运行时实现模块。"""

import re
from pathlib import Path

REQUIRED_ARTIFACT_SUMMARY_SCHEMA = "pico.required_artifact_summary.v1"
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_OUTPUT_CONTEXT_MARKERS = (
    "产出",
    "产物",
    "生成",
    "创建",
    "写入",
    "保存",
    "required artifacts",
    "output",
    "artifact",
    "create",
    "write",
    "produce",
)
_INPUT_CONTEXT_MARKERS = ("输入文件", "input file", "input files")
_NON_OUTPUT_SECTION_MARKERS = ("约束", "评分", "评估", "constraints", "scoring", "evaluation")
_NEGATED_OUTPUT_MARKERS = (
    "do not create",
    "don't create",
    "do not write",
    "don't write",
    "do not modify",
    "don't modify",
    "不要创建",
    "不要生成",
    "不要写入",
    "不要修改",
    "不创建",
    "不生成",
    "不修改",
)
_FILE_SUFFIXES = frozenset(
    ".csv .html .json .jsonl .js .jsx .md .py .sh .sql .toml "
    ".ts .tsx .txt .xml .yaml .yml".split()
)


def summarize_required_artifacts(task_state, workspace_root=None):
    """执行 `summarize_required_artifacts` 的内部逻辑。"""
    root = Path(workspace_root).resolve() if workspace_root else None
    paths = extract_required_artifact_paths(task_state.user_request, root)
    missing = []
    for path in paths:
        if root and not (root / path).exists():
            missing.append(path)
    return {
        "schema_version": REQUIRED_ARTIFACT_SUMMARY_SCHEMA,
        "declared_paths": paths,
        "missing_paths": missing,
    }


def extract_required_artifact_paths(text, workspace_root=None):
    """执行 `extract_required_artifact_paths` 的内部逻辑。"""
    root = Path(workspace_root).resolve() if workspace_root else None
    paths = []
    output_context = False
    output_dir = ""
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if any(marker in lowered for marker in _INPUT_CONTEXT_MARKERS):
            output_context = False
            output_dir = ""
        if _starts_non_output_section(line, lowered):
            output_context = False
            output_dir = ""
        if _line_negates_output(lowered):
            continue
        output_marker_index = _first_marker_index(lowered, _OUTPUT_CONTEXT_MARKERS)
        if output_marker_index >= 0:
            output_context = True
        line_output_dir = output_dir
        for match in _BACKTICK_RE.finditer(line):
            token = match.group(1).strip()
            normalized = _normalize_declared_path(token, root)
            if (
                normalized
                and _looks_like_directory_token(token)
                and _line_declares_output_dir(line)
                and _token_has_output_scope(output_context, output_marker_index, match.start())
            ):
                line_output_dir = normalized
                output_dir = normalized
        for match in _BACKTICK_RE.finditer(line):
            token = match.group(1).strip()
            normalized = _normalize_declared_path(token, root)
            if not normalized:
                continue
            if _looks_like_directory_token(token):
                continue
            if not _token_has_output_scope(output_context, output_marker_index, match.start()):
                continue
            candidate = normalized
            if line_output_dir and "/" not in candidate:
                candidate = f"{line_output_dir.rstrip('/')}/{candidate}"
            if candidate not in paths:
                paths.append(candidate)
    return paths


def _line_negates_output(lowered_line):
    """执行 `_line_negates_output` 的内部逻辑。"""
    return any(marker in lowered_line for marker in _NEGATED_OUTPUT_MARKERS)


def _starts_non_output_section(line, lowered_line):
    """执行 `_starts_non_output_section` 的内部逻辑。"""
    sectionish = line.startswith("#") or line.endswith(":")
    return sectionish and any(
        marker in lowered_line for marker in _NON_OUTPUT_SECTION_MARKERS
    )


def _first_marker_index(lowered_line, markers):
    """执行 `_first_marker_index` 的内部逻辑。"""
    positions = [pos for marker in markers if (pos := lowered_line.find(marker)) >= 0]
    return min(positions) if positions else -1


def _token_has_output_scope(output_context, output_marker_index, token_start):
    """执行 `_token_has_output_scope` 的内部逻辑。"""
    if output_marker_index >= 0:
        return token_start >= output_marker_index
    return output_context


def _line_declares_output_dir(line):
    """执行 `_line_declares_output_dir` 的内部逻辑。"""
    lowered = str(line or "").lower()
    return any(marker in lowered for marker in ("写入", "output", "under", "保存到"))


def _normalize_declared_path(token, root):
    """执行 `_normalize_declared_path` 的内部逻辑。"""
    value = str(token or "").strip().strip("\"'")
    if not value or any(part in value for part in ("*", "{", "}", "\n")):
        return ""
    if value.startswith(("http://", "https://")):
        return ""
    path = Path(value).expanduser()
    if path.is_absolute():
        if root is None:
            return ""
        try:
            return str(path.resolve().relative_to(root))
        except ValueError:
            return ""
    return value.lstrip("./")


def _looks_like_directory_token(token):
    """执行 `_looks_like_directory_token` 的内部逻辑。"""
    value = str(token or "").strip()
    if value.endswith("/"):
        return True
    suffix = Path(value).suffix.lower()
    return not suffix or suffix not in _FILE_SUFFIXES
