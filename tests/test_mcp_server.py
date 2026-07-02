"""Offline tests for the staircase MCP server (thin wrapper over the CLI)
and the CLI's --json output modes. No network, no external deps.

Run from the plugin root:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"


def _load(name):
    spec = importlib.util.spec_from_file_location(name,
                                                  TOOLS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


staircase = _load("staircase")
mcp_server = _load("mcp_server")


@contextlib.contextmanager
def env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    os.environ.update({k: v for k, v in kv.items() if v is not None})
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def cli(*argv, now=None):
    """Invoke the CLI in-process; return (exit_code, stdout+stderr)."""
    buf = io.StringIO()
    with env(**({"STAIRCASE_NOW": now} if now else {})):
        with contextlib.redirect_stdout(buf), \
                contextlib.redirect_stderr(buf):
            try:
                code = staircase.main(list(argv))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 2
    return code, buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sc = self.root / ".staircase"
        code, out = cli("--dir", str(self.root), "init", "--cadence", "5",
                        "--by", "sam", "--stakeholder", "vp-eng",
                        now="2026-07-01T08:00:00Z")
        self.assertEqual(code, 0, out)

    def tearDown(self):
        self.tmp.cleanup()

    def win(self, wid, ts, proof="https://example.com/proof"):
        return cli("--dir", str(self.root), "log-win", wid,
                   "--proof", proof, now=ts)

    def mcp(self, name, args=None, now="2026-07-01T12:00:00Z"):
        """One MCP tools/call through the real handler (which shells to the
        real CLI)."""
        with env(STAIRCASE_DIR=str(self.root), STAIRCASE_NOW=now):
            return mcp_server.handle({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": name, "arguments": args or {}}})

    def payload(self, resp):
        self.assertIn("result", resp, resp)
        self.assertNotIn("isError", resp["result"], resp)
        got = resp["result"]["structuredContent"]
        # text content is the same payload — one rendering, two shapes
        self.assertEqual(json.loads(resp["result"]["content"][0]["text"]),
                         got)
        return got


# ------------------------------------------------- CLI --json output modes
class TestJsonModes(Base):
    """--json is a machine-readable twin of the human output: same data,
    stable keys."""

    def seed(self):
        for i in range(1, 9):
            self.assertEqual(
                self.win(f"w{i}", f"2026-07-01T1{i}:00:00Z")[0], 0)
        cli("--dir", str(self.root), "release", "--n", "5",
            now="2026-07-01T20:00:00Z")

    def test_log_win_json(self):
        code, out = cli("--dir", str(self.root), "log-win", "w1",
                        "--proof", "https://x/1", "--json",
                        now="2026-07-01T10:00:00Z")
        self.assertEqual(code, 0, out)
        d = json.loads(out)
        self.assertEqual(
            set(d), {"schema", "command", "id", "proof", "ts", "buffer"})
        self.assertEqual((d["command"], d["id"], d["buffer"]),
                         ("log-win", "w1", 1))

    def test_release_json(self):
        self.seed()
        for i in (9, 10):
            self.win(f"w{i}", f"2026-07-01T2{i - 9}:10:00Z")
        code, out = cli("--dir", str(self.root), "release", "--n", "4",
                        "--json", now="2026-07-01T23:00:00Z")
        self.assertEqual(code, 0, out)
        d = json.loads(out)
        self.assertEqual(set(d), {"schema", "command", "released",
                                  "requested", "short", "buffer", "ts"})
        self.assertEqual(d["released"], ["w6", "w7", "w8", "w9"])  # FIFO
        self.assertEqual((d["requested"], d["short"], d["buffer"]),
                         (4, 0, 1))

    def test_release_json_empty_buffer_still_exit_3(self):
        code, out = cli("--dir", str(self.root), "release", "--json",
                        now="2026-07-01T10:00:00Z")
        self.assertEqual(code, 3)
        d = json.loads(out)
        self.assertEqual(d["released"], [])
        self.assertEqual(d["buffer"], 0)

    def test_status_json(self):
        self.seed()
        code, out = cli("--dir", str(self.root), "status", "--json",
                        now="2026-07-01T21:00:00Z")
        self.assertEqual(code, 0, out)
        d = json.loads(out)
        self.assertEqual(set(d), {
            "schema", "command", "date", "cadence", "cadence_entries",
            "buffer", "oldest_banked", "released_today", "streak",
            "promises_kept", "promises_named", "wins", "releases", "plans",
            "time", "alarms", "dir"})
        self.assertEqual((d["buffer"], d["released_today"], d["wins"],
                          d["releases"]), (3, 5, 8, 1))
        self.assertTrue(any("BUFFER BELOW CADENCE" in a
                            for a in d["alarms"]))

    def test_agent_brief_json(self):
        cli("--dir", str(self.root), "plan", "w1", "w2",
            "--date", "2026-07-01", now="2026-07-01T08:30:00Z")
        self.win("w1", "2026-07-01T10:00:00Z")
        code, out = cli("--dir", str(self.root), "agent-brief", "--json",
                        now="2026-07-01T11:00:00Z")
        self.assertEqual(code, 0, out)
        d = json.loads(out)
        self.assertEqual(set(d), {
            "schema", "command", "date", "mission", "cadence", "sla",
            "plan_today", "open_plan", "open_banked", "time", "misses_today",
            "buffer", "streak", "promises_kept", "promises_named",
            "proof_adapters", "alarms", "objections"})
        self.assertEqual(d["sla"], {"cadence": 5, "set_on": "2026-07-01",
                                    "signed_by": "sam"})
        self.assertEqual(d["plan_today"], ["w1", "w2"])
        self.assertEqual(d["open_plan"], ["w1", "w2"])
        # w1 is banked (won, unreleased); w2 is not yet built
        self.assertEqual(d["open_banked"], ["w1"])
        self.assertEqual(d["time"]["open_unbanked_need_production"], 1)

    def test_report_json_body_matches_archived_file(self):
        self.seed()
        code, out = cli("--dir", str(self.root), "report",
                        "--slot", "evening", "--date", "2026-07-01",
                        "--json", now="2026-07-01T21:00:00Z")
        self.assertEqual(code, 0, out)
        d = json.loads(out)
        self.assertEqual(set(d), {"schema", "command", "date", "slot",
                                  "path", "body", "marker"})
        self.assertEqual(d["marker"], {"wins": 8, "releases": 1,
                                       "buffer": 3, "cadence": 5})
        self.assertEqual(Path(d["path"]).read_text(), d["body"])

    def test_lint_json(self):
        self.seed()
        cli("--dir", str(self.root), "report", "--slot", "evening",
            "--date", "2026-07-01", now="2026-07-01T21:00:00Z")
        path = self.sc / "reports" / "2026-07-01-evening.md"
        code, out = cli("--dir", str(self.root), "lint", str(path),
                        "--json", now="2026-07-01T21:05:00Z")
        self.assertEqual(code, 0, out)
        d = json.loads(out)
        self.assertEqual(set(d), {"schema", "command", "report", "ok",
                                  "violations"})
        self.assertEqual((d["ok"], d["violations"]), (True, []))
        # a violating report: same schema, ok=false, exit 1 preserved
        bad = path.with_name("bad.md")
        bad.write_text(path.read_text().replace(
            "Buffer: 3", "Buffer: 3 (42 more in the pipeline)"))
        code, out = cli("--dir", str(self.root), "lint", str(bad),
                        "--json", now="2026-07-01T21:06:00Z")
        self.assertEqual(code, 1)
        d = json.loads(out)
        self.assertFalse(d["ok"])
        self.assertTrue(any("number 42" in v for v in d["violations"]))


# ------------------------------------------------------ MCP wrapper proper
class TestMcpRoundtrip(Base):
    """MCP request -> CLI -> structured MCP result. Same ledger, same
    rules: everything below runs through the real CLI subprocess."""

    def test_tools_list_matches_spec(self):
        resp = mcp_server.handle({"jsonrpc": "2.0", "id": 1,
                                  "method": "tools/list"})
        names = [t["name"] for t in resp["result"]["tools"]]
        self.assertEqual(names, [
            "staircase_status", "staircase_agent_brief",
            "staircase_log_win", "staircase_plan", "staircase_release",
            "staircase_report", "staircase_lint", "staircase_miss",
            "staircase_manager_check", "staircase_steer_log"])
        for t in resp["result"]["tools"]:
            self.assertEqual(t["inputSchema"]["type"], "object")
            # v0.2.1 fix: every tool takes an optional project_dir
            self.assertIn("project_dir",
                          t["inputSchema"]["properties"], t["name"])

    def test_status_roundtrip(self):
        self.win("w1", "2026-07-01T10:00:00Z")
        d = self.payload(self.mcp("staircase_status"))
        self.assertEqual((d["command"], d["buffer"], d["wins"]),
                         ("status", 1, 1))

    def test_log_win_roundtrip_writes_the_ledger(self):
        d = self.payload(self.mcp("staircase_log_win",
                                  {"id": "PR-9", "proof": "https://x/9"},
                                  now="2026-07-01T10:00:00Z"))
        self.assertEqual((d["command"], d["id"], d["buffer"]),
                         ("log-win", "PR-9", 1))
        ledgered = [json.loads(l) for l in
                    (self.sc / "wins.jsonl").read_text().splitlines()]
        self.assertEqual([w["id"] for w in ledgered], ["PR-9"])

    def test_release_roundtrip(self):
        for i in (1, 2, 3):
            self.win(f"w{i}", f"2026-07-01T1{i}:00:00Z")
        d = self.payload(self.mcp("staircase_release", {"n": 2},
                                  now="2026-07-01T20:00:00Z"))
        self.assertEqual(d["released"], ["w1", "w2"])
        self.assertEqual(d["buffer"], 1)

    def test_plan_and_miss_roundtrip(self):
        d = self.payload(self.mcp("staircase_plan", {"ids": ["w1", "w2"]},
                                  now="2026-07-01T08:30:00Z"))
        self.assertTrue(d["ok"], d)
        d = self.payload(self.mcp("staircase_miss",
                                  {"id": "w1", "reason": "blocked on CI",
                                   "new_date": "2026-07-03"},
                                  now="2026-07-01T15:00:00Z"))
        self.assertTrue(d["ok"], d)
        self.assertIn("MISS ledgered", d["message"])
        p = staircase.Project(self.sc)
        self.assertEqual(p.plan_for("2026-07-03"), ["w1"])

    def test_report_then_lint_roundtrip(self):
        self.win("w1", "2026-07-01T10:00:00Z")
        self.payload(self.mcp("staircase_release", {"n": 1},
                              now="2026-07-01T20:00:00Z"))
        d = self.payload(self.mcp("staircase_report", {"slot": "evening"},
                                  now="2026-07-01T21:00:00Z"))
        d2 = self.payload(self.mcp("staircase_lint", {"path": d["path"]},
                                   now="2026-07-01T21:05:00Z"))
        self.assertTrue(d2["ok"], d2)

    def test_release_fails_closed_on_unsigned_cadence_change(self):
        """Guardrail 4 holds through the MCP layer: a hand-edited cadence
        with no owner-signed expectations.md entry refuses release."""
        self.win("w1", "2026-07-01T10:00:00Z")
        cfg = self.sc / "config.yml"
        cfg.write_text(cfg.read_text().replace(
            "cadence_per_day: 5", "cadence_per_day: 10"))
        resp = self.mcp("staircase_release", now="2026-07-01T20:00:00Z")
        self.assertTrue(resp["result"].get("isError"), resp)
        text = resp["result"]["content"][0]["text"]
        self.assertIn("explicit owner decision", text)
        self.assertNotIn("Traceback", text)
        # and nothing was released
        self.assertEqual((self.sc / "releases.jsonl").read_text(), "")


class TestMcpValidation(Base):
    """Bad arguments produce a clean JSON-RPC error — never a traceback,
    never a CLI invocation."""

    def check_invalid(self, name, args, needle):
        resp = self.mcp(name, args)
        self.assertIn("error", resp, resp)
        self.assertEqual(resp["error"]["code"], -32602)
        self.assertIn(needle, resp["error"]["message"])
        self.assertNotIn("Traceback", resp["error"]["message"])

    def test_missing_required(self):
        self.check_invalid("staircase_log_win", {"id": "w1"}, "proof")

    def test_wrong_type(self):
        self.check_invalid("staircase_release", {"n": "five"}, "integer")
        self.check_invalid("staircase_release", {"n": 0}, ">= 1")

    def test_enum(self):
        self.check_invalid("staircase_report", {"slot": "noon"},
                           "morning, evening")

    def test_unknown_argument_and_unknown_tool(self):
        self.check_invalid("staircase_status", {"verbose": True},
                           "unexpected argument")
        resp = self.mcp("staircase_set_quota", {"n": 10})
        self.assertEqual(resp["error"]["code"], -32602)
        self.assertIn("unknown tool", resp["error"]["message"])

    def test_empty_plan_and_bad_date(self):
        self.check_invalid("staircase_plan", {"ids": []}, "empty")
        self.check_invalid("staircase_miss",
                           {"id": "w1", "reason": "x",
                            "new_date": "tomorrow"}, "must match")

    def test_validation_failure_never_touches_the_ledger(self):
        self.mcp("staircase_log_win", {"id": "w1"})
        self.assertEqual((self.sc / "wins.jsonl").read_text(), "")


class TestMcpStdio(Base):
    """One true stdio roundtrip: initialize -> tools/list -> tools/call,
    newline-delimited JSON-RPC against the real server process."""

    def test_stdio_session(self):
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "staircase_status", "arguments": {}}},
        ]
        proc = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "mcp_server.py")],
            input="".join(json.dumps(r) + "\n" for r in reqs),
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "STAIRCASE_DIR": str(self.root),
                 "STAIRCASE_NOW": "2026-07-01T12:00:00Z"})
        lines = [json.loads(l) for l in proc.stdout.splitlines() if l]
        self.assertEqual([l["id"] for l in lines], [1, 2, 3])
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"],
                         "staircase")
        self.assertEqual(len(lines[1]["result"]["tools"]), 10)
        status = lines[2]["result"]["structuredContent"]
        self.assertEqual(status["command"], "status")
        self.assertEqual(status["cadence"], 5)
        self.assertEqual(proc.stderr, "")


if __name__ == "__main__":
    unittest.main()
