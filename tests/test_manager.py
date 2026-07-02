"""Offline tests for the Staircase Manager surface: the manager-check
evidence packet, the steer-log ledger (steering.jsonl), and the per-call
project_dir resolution on the MCP server (the worktree/multi-repo fix).
No network, no external deps.

Run from the plugin root:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
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
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
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

    def packet(self, *extra, now="2026-07-02T14:00:00Z"):
        code, out = cli("--dir", str(self.root), "manager-check", "--json",
                        *extra, now=now)
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def steering_lines(self):
        return [json.loads(ln) for ln in
                (self.sc / "steering.jsonl").read_text().splitlines()
                if ln.strip()]

    def mcp(self, name, args=None, now="2026-07-02T14:00:00Z",
            pin_env=True):
        kv = {"STAIRCASE_NOW": now}
        kv["STAIRCASE_DIR"] = str(self.root) if pin_env else None
        with env(**kv):
            return mcp_server.handle({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": name, "arguments": args or {}}})


# --------------------------------------------------- manager-check packet
class TestManagerCheckPacket(Base):
    def seed(self):
        cli("--dir", str(self.root), "plan", "m1", "m2", "m3",
            "--date", "2026-07-01", now="2026-07-01T08:30:00Z")
        self.win("m1", "2026-07-01T11:00:00Z")
        cli("--dir", str(self.root), "release", "--n", "1",
            now="2026-07-01T18:00:00Z")

    def test_packet_shape(self):
        self.seed()
        d = self.packet()
        self.assertEqual(set(d), {
            "schema", "command", "generated_at", "trigger", "project",
            "staircase_dir", "config", "brief", "ledger_tail", "plan_ages",
            "git", "transcript", "steering_last"})
        self.assertEqual(d["command"], "manager-check")
        self.assertEqual(d["trigger"], "periodic")
        self.assertEqual(d["project"], str(self.root.resolve()))
        self.assertEqual(d["config"]["cadence_per_day"], 5)
        self.assertIn("time_box_hours", d["config"])
        # the embedded brief is the agent-brief payload, same keys
        self.assertEqual(set(d["brief"]), {
            "date", "mission", "cadence", "sla", "plan_today", "open_plan",
            "open_banked", "time", "misses_today", "buffer", "streak",
            "promises_kept", "promises_named", "proof_adapters", "alarms",
            "objections"})
        # the time block is timezone-aware and carries a pace verdict
        self.assertEqual(set(d["brief"]["time"]) >= {
            "now_stakeholder", "deadline_stakeholder", "minutes_remaining",
            "pace_verdict", "open_unbanked_need_production"}, True)
        self.assertEqual(set(d["config"]), {
            "mission", "cadence_per_day", "time_box_hours",
            "report_slots"})
        self.assertIsNone(d["transcript"])
        self.assertIsNone(d["steering_last"])

    def test_ledger_tail_is_merged_sorted_and_bounded(self):
        self.seed()
        d = self.packet()
        tail = d["ledger_tail"]
        self.assertEqual([e["ledger"] for e in tail],
                         ["plans", "wins", "releases"])
        self.assertEqual([e["ts"] for e in tail], sorted(
            e["ts"] for e in tail))
        d = self.packet("--last", "2")
        self.assertEqual(len(d["ledger_tail"]), 2)
        self.assertEqual([e["ledger"] for e in d["ledger_tail"]],
                         ["wins", "releases"])

    def test_plan_ages_status_and_age(self):
        self.seed()
        code, out = cli("--dir", str(self.root), "miss", "m3", "--why",
                        "blocked", "--new-date", "2026-07-03",
                        now="2026-07-01T19:00:00Z")
        self.assertEqual(code, 0, out)
        d = self.packet(now="2026-07-02T14:30:00Z")
        by_id = {e["id"]: e for e in d["plan_ages"]}
        self.assertEqual(by_id["m1"]["status"], "released")
        self.assertEqual(by_id["m2"]["status"], "open")
        self.assertEqual(by_id["m2"]["age_hours"], 30.0)
        self.assertEqual(by_id["m2"]["days_past_due"], 1)
        self.assertEqual(by_id["m3"]["status"], "missed")
        for e in d["plan_ages"]:
            self.assertEqual(set(e), {"id", "planned_for", "named_ts",
                                      "age_hours", "days_past_due",
                                      "status"})

    def test_git_evidence_absent_and_present(self):
        d = self.packet()
        self.assertEqual(d["git"], {"available": False,
                                    "commits_since_morning": [],
                                    "dirty_files": None})
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "f.txt").write_text("x")
        subprocess.run(["git", "-C", str(self.root),
                        "-c", "user.name=t", "-c", "user.email=t@t",
                        "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root),
                        "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "-m", "polish css"], check=True)
        (self.root / "g.txt").write_text("y")
        d = self.packet()
        self.assertTrue(d["git"]["available"])
        self.assertEqual(len(d["git"]["commits_since_morning"]), 1)
        self.assertIn("polish css", d["git"]["commits_since_morning"][0])
        self.assertEqual(d["git"]["dirty_files"], 1)

    def test_transcript_tail(self):
        t = self.root / "session.jsonl"
        t.write_text("\n".join(f"line-{i}" for i in range(100)) + "\n")
        d = self.packet("--transcript", str(t))
        tr = d["transcript"]
        self.assertEqual(set(tr), {"path", "bytes", "mtime", "lines",
                                   "tail"})
        self.assertEqual(tr["lines"], 100)
        self.assertEqual(len(tr["tail"]), 20)
        self.assertEqual(tr["tail"][-1], "line-99")
        # missing transcript fails closed
        code, out = cli("--dir", str(self.root), "manager-check", "--json",
                        "--transcript", str(self.root / "nope.jsonl"),
                        now="2026-07-02T14:00:00Z")
        self.assertEqual(code, 2)
        self.assertIn("transcript not found", out)

    def test_hook_nudge(self):
        code, out = cli("--dir", str(self.root), "manager-check", "--hook")
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertIn("manager nudge", d["systemMessage"])
        self.assertIn("rebut", d["systemMessage"])


# ------------------------------------------------- mission (ALTITUDE why)
class TestMission(unittest.TestCase):
    """config.yml `mission:` — the one-line why. Rendered FIRST in every
    agent brief (before the SLA) and carried in the manager packet as the
    ALTITUDE domain's anchor."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        code, out = cli("--dir", str(self.root), "init", "--cadence", "5",
                        "--by", "sam",
                        "--mission", "every number traceable to its "
                                     "breadcrumb — nothing more",
                        now="2026-07-01T08:00:00Z")
        self.assertEqual(code, 0, out)

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_writes_mission_to_config(self):
        cfg = staircase.yamlish_loads(
            (self.root / ".staircase" / "config.yml").read_text())
        self.assertIn("breadcrumb", cfg["mission"])

    def test_brief_renders_mission_first_before_the_sla(self):
        code, out = cli("--dir", str(self.root), "agent-brief",
                        now="2026-07-01T09:00:00Z")
        self.assertEqual(code, 0, out)
        lines = out.splitlines()
        self.assertTrue(lines[1].startswith("Mission: every number"),
                        lines[:3])
        self.assertLess(lines.index(lines[1]),
                        next(i for i, ln in enumerate(lines)
                             if ln.startswith("SLA:")))

    def test_brief_json_and_packet_carry_mission(self):
        code, out = cli("--dir", str(self.root), "agent-brief", "--json",
                        now="2026-07-01T09:00:00Z")
        self.assertEqual(json.loads(out)["mission"],
                         "every number traceable to its breadcrumb — "
                         "nothing more")
        code, out = cli("--dir", str(self.root), "manager-check", "--json",
                        now="2026-07-01T09:00:00Z")
        d = json.loads(out)
        self.assertIn("breadcrumb", d["config"]["mission"])
        self.assertIn("breadcrumb", d["brief"]["mission"])

    def test_no_mission_stays_quiet(self):
        with tempfile.TemporaryDirectory() as t2:
            cli("--dir", t2, "init", "--by", "eve",
                now="2026-07-01T08:00:00Z")
            code, out = cli("--dir", t2, "agent-brief",
                            now="2026-07-01T09:00:00Z")
            self.assertEqual(code, 0, out)
            self.assertNotIn("Mission:", out)
            code, out = cli("--dir", t2, "agent-brief", "--json",
                            now="2026-07-01T09:00:00Z")
            self.assertEqual(json.loads(out)["mission"], "")


# ------------------------------------------------------------- steer-log
class TestSteerLog(Base):
    def test_drift_entry(self):
        code, out = cli(
            "--dir", str(self.root), "steer-log", "--verdict", "drift",
            "--trigger", "stop-hook",
            "--evidence", "plans.jsonl: m2 named 2026-07-01, still open",
            "--evidence", "git log --since=morning: 0 commits",
            "--message", "TIME: m2 at 3x its box — split or MISS now.",
            now="2026-07-02T14:00:00Z")
        self.assertEqual(code, 0, out)
        self.assertIn("DRIFT", out)
        (e,) = self.steering_lines()
        self.assertEqual(
            (e["type"], e["trigger"], e["verdict"], e["message_sent"]),
            ("steer", "stop-hook", "drift", True))
        self.assertEqual(len(e["evidence"]), 2)
        self.assertIn("split or MISS now", e["message"])
        self.assertEqual(e["ts"], "2026-07-02T14:00:00+00:00")
        self.assertNotIn("outcome", e)

    def test_on_track_silence_is_logged_too(self):
        code, out = cli("--dir", str(self.root), "steer-log",
                        "--verdict", "on_track", "--json",
                        now="2026-07-02T14:00:00Z")
        self.assertEqual(code, 0, out)
        d = json.loads(out)
        self.assertEqual((d["verdict"], d["message_sent"], d["message"],
                          d["evidence"], d["runs"]),
                         ("on_track", False, "", [], 1))
        (e,) = self.steering_lines()
        self.assertEqual((e["verdict"], e["message_sent"]),
                         ("on_track", False))
        # and the packet surfaces the last steering entry
        code, out = cli("--dir", str(self.root), "manager-check", "--json",
                        now="2026-07-02T15:00:00Z")
        d = json.loads(out)
        self.assertEqual(d["steering_last"]["verdict"], "on_track")

    def test_drift_requires_message_and_evidence(self):
        code, out = cli("--dir", str(self.root), "steer-log",
                        "--verdict", "drift",
                        "--evidence", "x", now="2026-07-02T14:00:00Z")
        self.assertEqual(code, 2)
        self.assertIn("--message", out)
        code, out = cli("--dir", str(self.root), "steer-log",
                        "--verdict", "drift", "--message", "m",
                        now="2026-07-02T14:00:00Z")
        self.assertEqual(code, 2)
        self.assertIn("--evidence", out)
        self.assertEqual((self.sc / "steering.jsonl").read_text(), "")

    def test_outcome_recorded(self):
        code, out = cli("--dir", str(self.root), "steer-log",
                        "--verdict", "drift", "--message", "m",
                        "--evidence", "e", "--outcome", "acted",
                        now="2026-07-02T14:00:00Z")
        self.assertEqual(code, 0, out)
        (e,) = self.steering_lines()
        self.assertEqual(e["outcome"], "acted")

    def test_steering_respects_no_backdate(self):
        cli("--dir", str(self.root), "steer-log", "--verdict", "on_track",
            now="2026-07-02T14:00:00Z")
        code, out = cli("--dir", str(self.root), "log-win", "w1",
                        "--proof", "p", now="2026-07-02T13:00:00Z")
        self.assertEqual(code, 2)
        self.assertIn("refusing to backdate", out)


# ------------------------------------- MCP: project_dir + new tools
class TestProjectDirResolution(Base):
    """The v0.2.1 fix: every MCP tool takes an optional project_dir —
    validated absolute path, walked upward for .staircase/."""

    def test_project_dir_resolves_without_env_or_cwd(self):
        self.win("w1", "2026-07-01T10:00:00Z")
        resp = self.mcp("staircase_status",
                        {"project_dir": str(self.root)}, pin_env=False)
        d = resp["result"]["structuredContent"]
        self.assertEqual((d["command"], d["buffer"]), ("status", 1))

    def test_project_dir_walks_up_from_a_subdirectory(self):
        sub = self.root / "worktree" / "deep"
        sub.mkdir(parents=True)
        resp = self.mcp("staircase_status", {"project_dir": str(sub)},
                        pin_env=False)
        self.assertEqual(
            resp["result"]["structuredContent"]["command"], "status")

    def test_project_dir_outranks_staircase_dir_env(self):
        other = Path(self.tmp.name) / "other"
        cli("--dir", str(self.tmp.name), "init", "--by", "x") \
            if False else None
        with tempfile.TemporaryDirectory() as t2:
            cli("--dir", t2, "init", "--cadence", "3", "--by", "eve",
                now="2026-07-01T08:00:00Z")
            with env(STAIRCASE_DIR=t2, STAIRCASE_NOW="2026-07-02T14:00:00Z"):
                resp = mcp_server.handle({
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "staircase_status",
                               "arguments": {"project_dir":
                                             str(self.root)}}})
            d = resp["result"]["structuredContent"]
            self.assertEqual(d["cadence"], 5)      # ours, not the env's 3
        _ = other

    def test_relative_missing_and_staircaseless_paths_rejected(self):
        for args, needle in (
                ({"project_dir": "relative/path"}, "absolute"),
                ({"project_dir": "/no/such/dir/anywhere"}, "existing"),
                ({"project_dir": tempfile.gettempdir()}, ".staircase")):
            resp = self.mcp("staircase_status", args, pin_env=False)
            self.assertIn("error", resp, resp)
            self.assertEqual(resp["error"]["code"], -32602)
            self.assertIn(needle, resp["error"]["message"])

    def test_manager_check_and_steer_log_roundtrip(self):
        resp = self.mcp("staircase_manager_check",
                        {"project_dir": str(self.root), "last": 5,
                         "trigger": "owner-ask"}, pin_env=False)
        d = resp["result"]["structuredContent"]
        self.assertEqual((d["command"], d["trigger"]),
                         ("manager-check", "owner-ask"))
        resp = self.mcp("staircase_steer_log",
                        {"project_dir": str(self.root),
                         "verdict": "drift", "message": "SCOPE: ...",
                         "evidence": ["wins.jsonl unchanged since 09:00"]},
                        pin_env=False)
        d = resp["result"]["structuredContent"]
        self.assertEqual((d["command"], d["verdict"], d["message_sent"]),
                         ("steer-log", "drift", True))
        (e,) = [json.loads(ln) for ln in
                (self.sc / "steering.jsonl").read_text().splitlines()]
        self.assertEqual(e["verdict"], "drift")

    def test_steer_log_drift_refusal_via_mcp(self):
        resp = self.mcp("staircase_steer_log",
                        {"project_dir": str(self.root),
                         "verdict": "drift", "message": "m"},
                        pin_env=False)
        self.assertTrue(resp["result"].get("isError"), resp)
        self.assertIn("--evidence", resp["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
