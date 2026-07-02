#!/usr/bin/env python3
"""staircase MCP server — a thin stdio wrapper over the staircase CLI.

MCP or CLI — same ledger, same rules. Every tool here shells out to
`tools/staircase.py`; the CLI keeps ALL the logic (ledgers, guardrails,
fail-closed checks) and this layer only translates MCP tool calls into CLI
invocations and CLI JSON output into MCP results. There is no code path
through which an MCP caller can bypass a CLI guardrail: an unsigned cadence
change fails `staircase_release` closed exactly as it fails `release`.

Zero dependencies, like the CLI: a deliberately small JSON-RPC 2.0 loop over
stdio (newline-delimited, per the MCP stdio transport) — no MCP SDK needed.

Project discovery matches the CLI: `.staircase/` is found by walking up
from the server's working directory (Claude Code launches plugin MCP
servers in the project). Set STAIRCASE_DIR to pin a different project root,
or pass `project_dir` (a validated absolute path, walked upward for
.staircase/) on any tool call — the worktree/multi-repo-workspace case,
where the session cwd is not the staircase project.

Prerogative note: `staircase_release` announces work to stakeholders — by
convention it is an owner-session decision. Deny it to subagents via their
`disallowedTools` frontmatter while leaving status/brief open; see the
plugin README.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parent / "staircase.py"
SERVER_VERSION = "0.3.0"
PROTOCOL_VERSION = "2025-06-18"

# ------------------------------------------------------------------- tools
# name -> (description, JSON schema for arguments, CLI argv builder,
#          whether the CLI subcommand speaks --json)
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

TOOLS: dict[str, dict] = {
    "staircase_status": {
        "description": "Operator dashboard (the internal truth): buffer, "
                       "streak, promises kept, alarms — rendered from the "
                       "ledgers only.",
        "schema": {"type": "object", "properties": {},
                   "additionalProperties": False},
        "argv": lambda a: ["status", "--json"],
    },
    "staircase_agent_brief": {
        "description": "One-call orientation for an agent working under the "
                       "staircase contract: current SLA, today's named "
                       "scope, buffer, alarms, definition of done, "
                       "unresolved stakeholder objections.",
        "schema": {"type": "object", "properties": {},
                   "additionalProperties": False},
        "argv": lambda a: ["agent-brief", "--json"],
    },
    "staircase_log_win": {
        "description": "Append a verified win to the production ledger "
                       "(append-only, timestamped at occurrence, never "
                       "backdated). A win exists only when this succeeds.",
        "schema": {"type": "object",
                   "properties": {
                       "id": {"type": "string", "minLength": 1,
                              "description": "unique win id (e.g. PR-123)"},
                       "proof": {"type": "string", "minLength": 1,
                                 "description": "URL or path proving the "
                                                "win"}},
                   "required": ["id", "proof"],
                   "additionalProperties": False},
        "argv": lambda a: ["log-win", a["id"], "--proof", a["proof"],
                           "--json"],
    },
    "staircase_plan": {
        "description": "Name today's commitments in advance (the promise "
                       "ledger). Expanding scope requires a plan entry — "
                       "never silent drift.",
        "schema": {"type": "object",
                   "properties": {
                       "ids": {"type": "array", "minItems": 1,
                               "items": {"type": "string", "minLength": 1},
                               "description": "win ids being committed"}},
                   "required": ["ids"],
                   "additionalProperties": False},
        "argv": lambda a: ["plan", *a["ids"]],
        "plain": True,
    },
    "staircase_release": {
        "description": "Draw the N oldest banked wins (default: the "
                       "cadence) and ledger the announcement. OWNER "
                       "PREROGATIVE by convention: releasing speaks to "
                       "stakeholders — deny this tool to subagents "
                       "(see README). Fails closed on unsigned cadence "
                       "changes.",
        "schema": {"type": "object",
                   "properties": {
                       "n": {"type": "integer", "minimum": 1,
                             "description": "how many to release "
                                            "(default: the cadence)"}},
                   "additionalProperties": False},
        "argv": lambda a: ["release", "--json"]
        + (["--n", str(a["n"])] if "n" in a else []),
    },
    "staircase_report": {
        "description": "Render the stakeholder report for a slot FROM THE "
                       "LEDGERS ONLY, and archive it under "
                       ".staircase/reports/.",
        "schema": {"type": "object",
                   "properties": {
                       "slot": {"type": "string",
                                "enum": ["morning", "evening"]}},
                   "required": ["slot"],
                   "additionalProperties": False},
        "argv": lambda a: ["report", "--slot", a["slot"], "--json"],
    },
    "staircase_lint": {
        "description": "Fail-closed send-gate for a rendered report: every "
                       "number must replay from the ledgers, drill-down "
                       "pointer required, retired vocabulary refused. "
                       "ok=false means DO NOT SEND.",
        "schema": {"type": "object",
                   "properties": {
                       "path": {"type": "string", "minLength": 1,
                                "description": "path to the rendered "
                                               "report .md"}},
                   "required": ["path"],
                   "additionalProperties": False},
        "argv": lambda a: ["lint", a["path"], "--json"],
    },
    "staircase_miss": {
        "description": "MISS protocol: name a slipped commitment EARLY — "
                       "why plus a new date, ledgered. A slip logged at "
                       "15:00 is workflow; one discovered at day's end is "
                       "a surprise.",
        "schema": {"type": "object",
                   "properties": {
                       "id": {"type": "string", "minLength": 1,
                              "description": "the named commitment that "
                                             "slipped"},
                       "reason": {"type": "string", "minLength": 1,
                                  "description": "plain-language reason"},
                       "new_date": {"type": "string",
                                    "pattern": DATE_PATTERN,
                                    "description": "new commitment date "
                                                   "YYYY-MM-DD (default "
                                                   "tomorrow)"}},
                   "required": ["id", "reason"],
                   "additionalProperties": False},
        "argv": lambda a: ["miss", a["id"], "--why", a["reason"]]
        + (["--new-date", a["new_date"]] if "new_date" in a else []),
        "plain": True,
    },
    "staircase_manager_check": {
        "description": "Assemble the Staircase Manager's evidence packet "
                       "deterministically: agent-brief, last-N ledger "
                       "events, plan ages, git log since morning, optional "
                       "transcript tail. Footprints, never the parent's "
                       "claims — the packet is the staircase-manager "
                       "agent's input; judgment stays in the agent.",
        "schema": {"type": "object",
                   "properties": {
                       "last": {"type": "integer", "minimum": 1,
                                "description": "trailing ledger events to "
                                               "include (default 20)"},
                       "transcript": {"type": "string", "minLength": 1,
                                      "description": "path to a session "
                                                     "transcript (size, "
                                                     "mtime, tail become "
                                                     "BUDGET evidence)"},
                       "trigger": {"type": "string", "minLength": 1,
                                   "description": "what prompted this pass "
                                                  "(periodic, stop-hook, "
                                                  "owner-ask, ...)"}},
                   "additionalProperties": False},
        "argv": lambda a: ["manager-check", "--json"]
        + (["--last", str(a["last"])] if "last" in a else [])
        + (["--transcript", a["transcript"]] if "transcript" in a else [])
        + (["--trigger", a["trigger"]] if "trigger" in a else []),
    },
    "staircase_steer_log": {
        "description": "Append one Staircase Manager run to steering.jsonl "
                       "(append-only, never backdated). verdict=drift "
                       "requires message + cited evidence; "
                       "verdict=on_track logs the quiet pass too — "
                       "silence is proven attention.",
        "schema": {"type": "object",
                   "properties": {
                       "verdict": {"type": "string",
                                   "enum": ["drift", "on_track"]},
                       "trigger": {"type": "string", "minLength": 1,
                                   "description": "what prompted the pass "
                                                  "(matches "
                                                  "manager-check)"},
                       "message": {"type": "string", "minLength": 1,
                                   "description": "the steering message "
                                                  "delivered to the parent "
                                                  "(required for drift)"},
                       "evidence": {"type": "array", "minItems": 1,
                                    "items": {"type": "string",
                                              "minLength": 1},
                                    "description": "cited footprints — "
                                                   "ledger lines, mtimes, "
                                                   "git output (drift "
                                                   "requires >= 1)"},
                       "outcome": {"type": "string", "minLength": 1,
                                   "description": "optional: how the "
                                                  "parent responded"}},
                   "required": ["verdict"],
                   "additionalProperties": False},
        "argv": lambda a: ["steer-log", "--verdict", a["verdict"], "--json"]
        + (["--trigger", a["trigger"]] if "trigger" in a else [])
        + (["--message", a["message"]] if "message" in a else [])
        + [x for e in a.get("evidence", []) for x in ("--evidence", e)]
        + (["--outcome", a["outcome"]] if "outcome" in a else []),
    },
}

# v0.2.1 finding (first native use, from a worktree in a multi-repo
# workspace): the server's cwd is not always the staircase project. Every
# tool therefore takes an optional `project_dir` — a validated absolute
# path from which `.staircase/` is discovered by walking upward, exactly
# like the CLI's --dir.
PROJECT_DIR_SPEC = {
    "type": "string", "minLength": 1,
    "description": "optional absolute path to the project (or any "
                   "directory inside it); .staircase/ is discovered by "
                   "walking upward. Overrides the server cwd / "
                   "STAIRCASE_DIR for this call — use from worktrees and "
                   "multi-repo workspaces."}
for _tool in TOOLS.values():
    _tool["schema"]["properties"]["project_dir"] = PROJECT_DIR_SPEC


def project_dir_error(pd: str) -> str | None:
    """Validate a project_dir argument: absolute, existing, and inside a
    staircase project (walked upward for .staircase/)."""
    p = Path(pd)
    if not p.is_absolute():
        return f"project_dir must be an absolute path (got {pd!r})"
    if not p.is_dir():
        return f"project_dir is not an existing directory: {pd}"
    r = p.resolve()
    for d in (r, *r.parents):
        if (d / ".staircase").is_dir():
            return None
    return f"no .staircase/ found from {pd} upward"


# -------------------------------------------------- argument validation
def validate_args(schema: dict, args: dict) -> str | None:
    """Validate args against the (small, hand-rolled) schema subset used in
    TOOLS. Returns a clean human message on failure, None when valid."""
    if not isinstance(args, dict):
        return "arguments must be an object"
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in args:
            return f"missing required argument: {key!r}"
    for key, val in args.items():
        if key not in props:
            return f"unexpected argument: {key!r}"
        spec = props[key]
        t = spec["type"]
        if t == "string":
            if not isinstance(val, str):
                return f"{key!r} must be a string"
            if spec.get("minLength") and len(val) < spec["minLength"]:
                return f"{key!r} must be a non-empty string"
            if "enum" in spec and val not in spec["enum"]:
                return (f"{key!r} must be one of "
                        f"{', '.join(spec['enum'])}")
            if "pattern" in spec and not re.fullmatch(spec["pattern"], val):
                return f"{key!r} must match {spec['pattern']}"
        elif t == "integer":
            if not isinstance(val, int) or isinstance(val, bool):
                return f"{key!r} must be an integer"
            if "minimum" in spec and val < spec["minimum"]:
                return f"{key!r} must be >= {spec['minimum']}"
        elif t == "array":
            if not isinstance(val, list):
                return f"{key!r} must be an array"
            if spec.get("minItems") and len(val) < spec["minItems"]:
                return f"{key!r} must not be empty"
            for x in val:
                if not isinstance(x, str) or not x:
                    return f"{key!r} items must be non-empty strings"
    return None


# ------------------------------------------------------- CLI invocation
def run_cli(argv: list[str],
            project_dir: str | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI — the single owner of all staircase logic. The
    project root resolves exactly as it does for a human at the shell:
    .staircase/ discovered upward from cwd (STAIRCASE_DIR pins it; a
    per-call project_dir outranks both)."""
    cmd = [sys.executable, str(CLI)]
    pin = project_dir or os.environ.get("STAIRCASE_DIR")
    if pin:
        cmd += ["--dir", pin]
    return subprocess.run(cmd + argv, capture_output=True, text=True)


def call_tool(name: str, args: dict) -> dict:
    """tools/call result. CLI exit codes map 1:1: 0/1/3 carry structured
    payloads (lint violations and an empty buffer are results, not
    errors); 2 is a refusal (fail-closed guardrail or bad input) and
    surfaces as an MCP tool error with the CLI's own message."""
    tool = TOOLS[name]
    args = dict(args)
    project_dir = args.pop("project_dir", None)
    proc = run_cli(tool["argv"](args), project_dir)
    if proc.returncode == 2:
        msg = proc.stderr.strip() or proc.stdout.strip() or \
            f"staircase exited {proc.returncode}"
        return {"content": [{"type": "text", "text": msg}],
                "isError": True}
    if tool.get("plain"):
        payload = {"ok": proc.returncode == 0,
                   "message": (proc.stdout.strip()
                               or proc.stderr.strip())}
    else:
        try:
            payload = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError):
            return {"content": [{"type": "text",
                                 "text": "staircase CLI returned "
                                         "unparseable output: "
                                         + (proc.stderr.strip()
                                            or proc.stdout.strip())}],
                    "isError": True}
    return {"content": [{"type": "text",
                         "text": json.dumps(payload, sort_keys=True)}],
            "structuredContent": payload}


# ----------------------------------------------------------- JSON-RPC loop
def _result(rid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": code, "message": message}}


def handle(req: dict) -> dict | None:
    """One request/notification in, one response (or None) out."""
    rid = req.get("id")
    method = req.get("method", "")
    params = req.get("params") or {}

    if method == "initialize":
        return _result(rid, {
            "protocolVersion": params.get("protocolVersion",
                                          PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "staircase",
                           "title": "Staircase (thin wrapper over the "
                                    "staircase CLI)",
                           "version": SERVER_VERSION}})
    if method == "ping":
        return _result(rid, {})
    if method == "tools/list":
        return _result(rid, {"tools": [
            {"name": n, "description": t["description"],
             "inputSchema": t["schema"]} for n, t in TOOLS.items()]})
    if method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            return _error(rid, -32602, f"unknown tool: {name!r}")
        args = params.get("arguments") or {}
        bad = validate_args(TOOLS[name]["schema"], args)
        if bad is None and "project_dir" in args:
            bad = project_dir_error(args["project_dir"])
        if bad:
            return _error(rid, -32602, f"{name}: {bad}")
        try:
            return _result(rid, call_tool(name, args))
        except Exception as e:  # no tracebacks over the wire
            return _error(rid, -32603, f"{name}: {e}")
    if rid is None:
        return None            # notification (initialized, cancelled, ...)
    return _error(rid, -32601, f"method not found: {method}")


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            resp = _error(None, -32700, "parse error")
        else:
            resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
