"""Parser for Pico's text model protocol."""

import json
import re


def parse(raw):
    raw = str(raw)
    if "<tool>" in raw and ("<final>" not in raw or raw.find("<tool>") < raw.find("<final>")):
        body = extract(raw, "tool")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict) or "name" not in payload:
                return "retry", retry_notice("tool JSON must be an object with name and args")
            args = payload.get("args", {})
            if not isinstance(args, dict):
                return "retry", retry_notice("tool args must be an object")
            return "tool", {"name": payload["name"], "args": args}
        except json.JSONDecodeError:
            parsed = parse_xml_tool(raw)
            if parsed:
                return "tool", parsed
            return "retry", retry_notice("tool payload must be valid JSON or supported XML")

    parsed = parse_xml_tool(raw)
    if parsed and ("<final>" not in raw or raw.find("<tool") < raw.find("<final>")):
        return "tool", parsed

    if "<final>" in raw:
        return "final", extract(raw, "final")

    if not raw.strip():
        return "retry", retry_notice("empty response")
    return "retry", retry_notice("missing <tool> or <final> tag")


def retry_notice(problem=None):
    detail = f" Problem: {problem}." if problem else ""
    return (
        "Your previous response could not be executed."
        f"{detail} Return exactly one valid <tool> call or one <final> answer."
    )


def parse_xml_tool(raw):
    match = re.search(r"<tool\b(?P<attrs>[^>]*)>(?P<body>.*?)</tool>", raw, flags=re.DOTALL)
    if not match:
        return None
    attrs = parse_attrs(match.group("attrs"))
    body = match.group("body")
    name = attrs.get("name", "").strip()
    if not name:
        return None
    args = {key: value for key, value in attrs.items() if key != "name"}
    for tag in ("content", "old_text", "new_text"):
        value = extract_raw(body, tag)
        if value is not None:
            args[tag] = value
    if name == "write_file" and "content" not in args and body.strip():
        args["content"] = body
    return {"name": name, "args": args}


def parse_attrs(text):
    attrs = {}
    for key, value in re.findall(r'([A-Za-z_][A-Za-z0-9_-]*)="(.*?)"', text, flags=re.DOTALL):
        attrs[key] = value
    return attrs


def extract(text, tag):
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, flags=re.DOTALL)
    if not match:
        return text.strip()
    return match.group(1).strip()


def extract_raw(text, tag):
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, flags=re.DOTALL)
    if not match:
        return None
    return match.group(1)
