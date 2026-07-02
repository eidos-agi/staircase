"""Offline tests for the staircase CLI. No network, no external deps.

Run from the plugin root:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools" / "staircase.py"
spec = importlib.util.spec_from_file_location("staircase", TOOLS)
staircase = importlib.util.module_from_spec(spec)
spec.loader.exec_module(staircase)


def run(*argv, now=None):
    """Invoke the CLI; return (exit_code, stdout+stderr)."""
    old = os.environ.get("STAIRCASE_NOW")
    if now is not None:
        os.environ["STAIRCASE_NOW"] = now
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                code = staircase.main(list(argv))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 2
    finally:
        if old is None:
            os.environ.pop("STAIRCASE_NOW", None)
        else:
            os.environ["STAIRCASE_NOW"] = old
    return code, buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sc = self.root / ".staircase"
        code, out = run("--dir", str(self.root), "init", "--cadence", "5",
                        "--by", "sam", "--stakeholder", "vp-eng",
                        now="2026-07-01T08:00:00Z")
        self.assertEqual(code, 0, out)

    def tearDown(self):
        self.tmp.cleanup()

    def win(self, wid, ts, proof="https://example.com/proof"):
        return run("--dir", str(self.root), "log-win", wid,
                   "--proof", proof, now=ts)

    def wins_lines(self):
        return [json.loads(l) for l in
                (self.sc / "wins.jsonl").read_text().splitlines() if l]


class TestInitScaffolding(Base):
    def test_scaffold(self):
        for f in ("config.yml", "expectations.md", "wins.jsonl",
                  "releases.jsonl", "plans.jsonl",
                  "stakeholders/vp-eng.md", "stakeholders/objections.yml",
                  "reports/.gitkeep"):
            self.assertTrue((self.sc / f).exists(), f"missing {f}")
        cfg = staircase.yamlish_loads((self.sc / "config.yml").read_text())
        self.assertEqual(cfg["cadence_per_day"], 5)
        self.assertEqual(cfg["stakeholders"], ["vp-eng"])
        # the initial SLA is an explicit, dated, owner-signed entry
        p = staircase.Project(self.sc)
        self.assertEqual(p.cadence_history(),
                         [("2026-07-01", 5, "sam")])
        self.assertEqual(p.consistency_errors(), [])

    def test_init_refuses_existing(self):
        code, out = run("--dir", str(self.root), "init", "--by", "sam")
        self.assertEqual(code, 2)


class TestNoBackdate(Base):
    def test_backdated_win_refused_and_ledger_unchanged(self):
        code, _ = self.win("w1", "2026-07-01T10:00:00Z")
        self.assertEqual(code, 0)
        before = (self.sc / "wins.jsonl").read_text()
        # attempt to append an event timestamped BEFORE the last ledger event
        code, out = self.win("w0", "2026-07-01T09:00:00Z")
        self.assertEqual(code, 2)
        self.assertIn("refusing to backdate", out)
        self.assertEqual((self.sc / "wins.jsonl").read_text(), before)

    def test_ts_is_clock_not_caller(self):
        # there is no CLI argument for a timestamp at all
        code, out = run("--dir", str(self.root), "log-win", "w1",
                        "--proof", "p", "--ts", "2020-01-01T00:00:00Z")
        self.assertEqual(code, 2)

    def test_backdated_plan_refused(self):
        code, out = run("--dir", str(self.root), "plan", "w9",
                        "--date", "2026-06-01", now="2026-07-01T10:00:00Z")
        self.assertEqual(code, 2)
        self.assertIn("backdated promise", out)


class TestBufferDrawOrder(Base):
    def test_fifo(self):
        for i, h in enumerate(("10", "11", "12"), 1):
            self.assertEqual(
                self.win(f"w{i}", f"2026-07-01T{h}:00:00Z")[0], 0)
        code, out = run("--dir", str(self.root), "release", "--n", "2",
                        now="2026-07-01T13:00:00Z")
        self.assertEqual(code, 0, out)
        rel = json.loads((self.sc / "releases.jsonl").read_text())
        self.assertEqual(rel["ids"], ["w1", "w2"])  # oldest first
        p = staircase.Project(self.sc)
        self.assertEqual([w["id"] for w in p.banked()], ["w3"])

    def test_release_caps_at_buffer(self):
        self.win("w1", "2026-07-01T10:00:00Z")
        code, out = run("--dir", str(self.root), "release", "--n", "10",
                        now="2026-07-01T13:00:00Z")
        self.assertEqual(code, 0)
        rel = json.loads((self.sc / "releases.jsonl").read_text())
        self.assertEqual(rel["ids"], ["w1"])
        self.assertEqual(rel["requested"], 10)

    def test_empty_buffer_is_exit_3(self):
        code, out = run("--dir", str(self.root), "release",
                        now="2026-07-01T13:00:00Z")
        self.assertEqual(code, 3)
        self.assertIn("production day", out)


class TestReportFromLedgerOnly(Base):
    def seed(self):
        for i in range(1, 9):  # 8 wins
            self.assertEqual(
                self.win(f"w{i}", f"2026-07-01T1{i}:00:00Z")[0], 0)
        code, _ = run("--dir", str(self.root), "release", "--n", "5",
                      now="2026-07-01T20:00:00Z")
        self.assertEqual(code, 0)

    def test_numbers_track_the_ledgers(self):
        self.seed()
        code, out = run("--dir", str(self.root), "report",
                        "--slot", "evening", "--date", "2026-07-01",
                        now="2026-07-01T21:00:00Z")
        self.assertEqual(code, 0, out)
        self.assertIn("Released today: 5", out)
        self.assertIn("Buffer: 3", out)
        self.assertIn("wins=8 releases=1 buffer=3 cadence=5", out)
        # grow the ledger; the rendered numbers move with it — no other input
        self.win("w9", "2026-07-02T09:00:00Z")
        code, out2 = run("--dir", str(self.root), "report",
                         "--slot", "morning", "--date", "2026-07-02",
                         now="2026-07-02T09:30:00Z")
        self.assertEqual(code, 0)
        self.assertIn("Buffer: 4", out2)
        self.assertIn("wins=9 releases=1 buffer=4 cadence=5", out2)

    def test_rendered_report_passes_lint(self):
        self.seed()
        run("--dir", str(self.root), "report", "--slot", "evening",
            "--date", "2026-07-01", now="2026-07-01T21:00:00Z")
        code, out = run("--dir", str(self.root), "lint",
                        str(self.sc / "reports" / "2026-07-01-evening.md"),
                        now="2026-07-01T21:05:00Z")
        self.assertEqual(code, 0, out)

    def test_stale_report_fails_lint(self):
        """A report rendered before the ledger moved is not a rendering of
        the current ledgers — lint refuses it."""
        self.seed()
        run("--dir", str(self.root), "report", "--slot", "evening",
            "--date", "2026-07-01", now="2026-07-01T21:00:00Z")
        self.win("w9", "2026-07-02T09:00:00Z")
        code, out = run("--dir", str(self.root), "lint",
                        str(self.sc / "reports" / "2026-07-01-evening.md"),
                        now="2026-07-02T09:30:00Z")
        self.assertEqual(code, 1)
        self.assertIn("not rendered from the current ledgers", out)

    def test_shortfall_day_keeps_texture(self):
        """Anti-over-smoothing: a short day says so in plain words."""
        for i in (1, 2, 3):
            self.win(f"w{i}", f"2026-07-01T1{i}:00:00Z")
        run("--dir", str(self.root), "release", now="2026-07-01T20:00:00Z")
        code, out = run("--dir", str(self.root), "report",
                        "--slot", "evening", "--date", "2026-07-01",
                        now="2026-07-01T21:00:00Z")
        self.assertEqual(code, 0)
        self.assertIn("3 of 5", out)
        self.assertIn("buffer ran short", out)


class TestLint(Base):
    def rendered(self):
        for i in range(1, 9):
            self.win(f"w{i}", f"2026-07-01T1{i}:00:00Z")
        run("--dir", str(self.root), "release", "--n", "5",
            now="2026-07-01T20:00:00Z")
        run("--dir", str(self.root), "report", "--slot", "evening",
            "--date", "2026-07-01", now="2026-07-01T21:00:00Z")
        return self.sc / "reports" / "2026-07-01-evening.md"

    def lint(self, path):
        return run("--dir", str(self.root), "lint", str(path),
                   now="2026-07-01T21:05:00Z")

    def test_retired_vocabulary_caught(self):
        path = self.rendered()
        for phrase in ("we sandbagged two of them",
                       "the rest stay hidden for now",
                       "managers don't understand burst work",
                       "we kept the message simpler"):
            bad = path.with_name("bad.md")
            bad.write_text(path.read_text().replace(
                "Buffer: 3", f"Buffer: 3 ({phrase})"))
            code, out = self.lint(bad)
            self.assertEqual(code, 1, f"{phrase!r} not caught:\n{out}")
            self.assertIn("retired vocabulary", out)

    def test_project_vocabulary_additions(self):
        cfg = self.sc / "config.yml"
        cfg.write_text(cfg.read_text().replace(
            "retired_vocabulary: []", "retired_vocabulary: [stockpile]"))
        path = self.rendered()
        bad = path.with_name("bad2.md")
        bad.write_text(path.read_text().replace(
            "Buffer: 3", "Buffer: 3 in the stockpile"))
        code, out = self.lint(bad)
        self.assertEqual(code, 1)
        self.assertIn("stockpile", out)

    def test_non_ledger_number_caught(self):
        path = self.rendered()
        bad = path.with_name("bad3.md")
        bad.write_text(path.read_text().replace(
            "Buffer: 3", "Buffer: 3 (42 more in the pipeline)"))
        code, out = self.lint(bad)
        self.assertEqual(code, 1)
        self.assertIn("number 42 does not appear in the ledgers", out)

    def test_missing_drilldown_caught(self):
        path = self.rendered()
        bad = path.with_name("bad4.md")
        bad.write_text(re.sub(r"^Full ledger.*$", "", path.read_text(),
                              flags=re.M))
        code, out = self.lint(bad)
        self.assertEqual(code, 1)
        self.assertIn("drill-down missing", out)

    def test_proof_url_numbers_are_not_false_positives(self):
        """A PR number inside a ledgered proof URL is legitimate."""
        self.win("PR-4711", "2026-07-01T10:00:00Z",
                 proof="https://github.com/acme/x/pull/4711")
        run("--dir", str(self.root), "release", "--n", "1",
            now="2026-07-01T20:00:00Z")
        run("--dir", str(self.root), "report", "--slot", "evening",
            "--date", "2026-07-01", now="2026-07-01T21:00:00Z")
        code, out = self.lint(
            self.sc / "reports" / "2026-07-01-evening.md")
        self.assertEqual(code, 0, out)


class TestExplicitExpectationChanges(Base):
    def test_hand_edited_cadence_fails_closed(self):
        """Guardrail 4: raising the daily number in config.yml without a
        dated owner-signed entry in expectations.md fails every command."""
        cfg = self.sc / "config.yml"
        cfg.write_text(cfg.read_text().replace(
            "cadence_per_day: 5", "cadence_per_day: 10"))
        code, out = run("--dir", str(self.root), "report",
                        "--slot", "morning", now="2026-07-02T08:00:00Z")
        self.assertEqual(code, 2)
        self.assertIn("explicit owner decision", out)
        code, out = run("--dir", str(self.root), "release",
                        now="2026-07-02T08:00:00Z")
        self.assertEqual(code, 2)
        code, out = run("--dir", str(self.root), "status", "--check",
                        now="2026-07-02T08:00:00Z")
        self.assertEqual(code, 4)
        self.assertIn("ALARM", out)

    def test_set_quota_is_the_sanctioned_path(self):
        code, out = run("--dir", str(self.root), "set-quota", "10",
                        "--reason", "team doubled", "--by", "sam",
                        now="2026-07-02T08:00:00Z")
        self.assertEqual(code, 0, out)
        p = staircase.Project(self.sc)
        self.assertEqual(p.consistency_errors(), [])
        self.assertEqual(p.cadence, 10)
        self.assertEqual(p.cadence_history()[-1], ("2026-07-02", 10,
                                                   "sam"))

    def test_set_quota_requires_reason_and_owner(self):
        code, _ = run("--dir", str(self.root), "set-quota", "10",
                      "--by", "sam")
        self.assertEqual(code, 2)
        code, _ = run("--dir", str(self.root), "set-quota", "10",
                      "--reason", "x")
        self.assertEqual(code, 2)


class TestStatusAlarms(Base):
    def test_buffer_below_cadence_is_loud(self):
        for i in (1, 2, 3):
            self.win(f"w{i}", f"2026-07-01T1{i}:00:00Z")
        code, out = run("--dir", str(self.root), "status",
                        now="2026-07-01T18:00:00Z")
        self.assertEqual(code, 0)
        self.assertIn("ALARM", out)
        self.assertIn("BUFFER BELOW CADENCE: 3 banked < 5/day", out)
        code, _ = run("--dir", str(self.root), "status", "--check",
                      now="2026-07-01T18:00:00Z")
        self.assertEqual(code, 4)

    def test_duplicate_win_id_refused(self):
        self.win("w1", "2026-07-01T10:00:00Z")
        code, out = self.win("w1", "2026-07-01T11:00:00Z")
        self.assertEqual(code, 2)
        self.assertIn("already ledgered", out)


class TestAgentAccountability(Base):
    def test_win_without_proof_fails(self):
        """Done means proven: there is no way to log a win with no proof
        reference."""
        code, out = run("--dir", str(self.root), "log-win", "w1",
                        now="2026-07-01T10:00:00Z")
        self.assertEqual(code, 2)
        self.assertEqual(self.wins_lines(), [])

    def test_plan_expansion_writes_a_plans_entry(self):
        """Scope expands only through the promise ledger — never silently."""
        run("--dir", str(self.root), "plan", "w1", "w2",
            "--date", "2026-07-01", now="2026-07-01T08:30:00Z")
        code, _ = run("--dir", str(self.root), "plan", "w3",
                      "--date", "2026-07-01", now="2026-07-01T09:00:00Z")
        self.assertEqual(code, 0)
        p = staircase.Project(self.sc)
        self.assertEqual(p.plan_for("2026-07-01"), ["w1", "w2", "w3"])
        self.assertEqual(len(p.plans), 2)  # two dated, timestamped entries

    def test_agent_brief_shape(self):
        run("--dir", str(self.root), "plan", "w1", "w2",
            "--date", "2026-07-01", now="2026-07-01T08:30:00Z")
        self.win("w1", "2026-07-01T10:00:00Z")
        obj = self.sc / "stakeholders" / "objections.yml"
        obj.write_text(obj.read_text().replace(
            "objections: []",
            'objections:\n'
            '  - stakeholder: vp-eng\n'
            '    question: "why did Tuesday only show 3?"\n'
            '    status: asked\n'
            '    date: 2026-07-01\n'))
        code, out = run("--dir", str(self.root), "agent-brief",
                        now="2026-07-01T11:00:00Z")
        self.assertEqual(code, 0, out)
        for needle in ("=== STAIRCASE AGENT BRIEF — 2026-07-01 ===",
                       # promises lead, loud, with the work-backwards charge
                       "PROMISES ARE THE MOST IMPORTANT THING",
                       "Work BACKWARDS from each open promise",
                       "SLA: 5 verified wins released/day — set 2026-07-01 "
                       "by sam",
                       "Scope (today's named plan): w1, w2",
                       "Open plan items: w1, w2",
                       "Buffer: 1 banked",
                       "Definition of done: proof adapter(s) [manual]",
                       "BUFFER BELOW CADENCE",
                       "why did Tuesday only show 3?",
                       "MISS protocol",
                       "=== END BRIEF ==="):
            self.assertIn(needle, out)

    def test_miss_protocol(self):
        run("--dir", str(self.root), "plan", "w1",
            "--date", "2026-07-01", now="2026-07-01T08:30:00Z")
        # only a named promise can be missed
        code, out = run("--dir", str(self.root), "miss", "w9",
                        "--why", "x", now="2026-07-01T15:00:00Z")
        self.assertEqual(code, 2)
        code, out = run("--dir", str(self.root), "miss", "w1",
                        "--why", "verification still running",
                        now="2026-07-01T15:00:00Z")
        self.assertEqual(code, 0, out)
        p = staircase.Project(self.sc)
        self.assertEqual(p.misses[0]["id"], "w1")
        self.assertEqual(p.misses[0]["new_date"], "2026-07-02")
        self.assertEqual(p.plan_for("2026-07-02"), ["w1"])  # re-committed

    def test_agent_check_warns_never_blocks(self):
        run("--dir", str(self.root), "plan", "w1", "w2",
            "--date", "2026-07-01", now="2026-07-01T08:30:00Z")
        code, out = run("--dir", str(self.root), "agent-check", "--hook",
                        now="2026-07-01T18:00:00Z")
        self.assertEqual(code, 0)  # warn, don't block
        msg = json.loads(out)["systemMessage"]
        self.assertIn("neither released nor MISS-logged", msg)
        self.assertIn("w1, w2", msg)
        # after a MISS + a release, the check is clean
        run("--dir", str(self.root), "miss", "w2", "--why", "blocked",
            now="2026-07-01T18:30:00Z")
        self.win("w1", "2026-07-01T19:00:00Z")
        run("--dir", str(self.root), "release", "--n", "1",
            now="2026-07-01T19:30:00Z")
        code, out = run("--dir", str(self.root), "agent-check", "--hook",
                        now="2026-07-01T20:00:00Z")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")


class TestTimeAwareness(unittest.TestCase):
    """The plugin knows what time it is, in whose zone, and how long is
    left on today's promises — the operator and the stakeholder may be in
    different timezones."""

    def _init_tz(self, deadline="18:00"):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(
            root, ignore_errors=True))
        code, out = run("--dir", str(root), "init", "--cadence", "5",
                        "--by", "sam", "--stakeholder-tz",
                        "America/Chicago", "--deadline", deadline,
                        now="2026-07-02T18:35:00Z")
        self.assertEqual(code, 0, out)
        return str(root)

    def test_init_records_timezones(self):
        root = self._init_tz()
        cfg = staircase.yamlish_loads(
            (Path(root) / ".staircase" / "config.yml").read_text())
        self.assertTrue(cfg["operator_tz"], "operator_tz auto-detected")
        self.assertEqual(cfg["stakeholder_tz"], "America/Chicago")
        self.assertEqual(cfg["deadline_local"], "18:00")

    def test_remaining_computed_in_stakeholder_zone(self):
        # 18:35Z == 13:35 CDT; deadline 18:00 CDT == 23:00Z -> 265 minutes
        root = self._init_tz()
        code, out = run("--dir", root, "status", "--json",
                        now="2026-07-02T18:35:00Z")
        tf = json.loads(out)["time"]
        self.assertEqual(tf["minutes_remaining"], 265)
        self.assertEqual(tf["stakeholder_tz"], "America/Chicago")
        self.assertIn("13:35 CDT", tf["now_stakeholder"])
        self.assertIn("18:00 CDT", tf["deadline_stakeholder"])
        # operator (machine) zone differs and the offset is reported
        self.assertNotEqual(tf["operator_tz"], tf["stakeholder_tz"])

    def test_clock_line_rendered_in_brief_and_status(self):
        root = self._init_tz()
        _, brief = run("--dir", root, "agent-brief",
                       now="2026-07-02T18:35:00Z")
        self.assertIn("CLOCK:", brief)
        self.assertIn("4h25m to deadline", brief)
        _, st = run("--dir", root, "status", now="2026-07-02T18:35:00Z")
        self.assertIn("CLOCK:", st)

    def test_pace_verdict_banked_vs_unbanked(self):
        root = self._init_tz()
        run("--dir", root, "plan", "p1", "--date", "2026-07-02",
            now="2026-07-02T18:00:00Z")
        # 22:30Z == 17:30 CDT -> 30 min left, p1 unbuilt -> CRITICAL
        _, out = run("--dir", root, "status", "--json",
                     now="2026-07-02T22:30:00Z")
        tf = json.loads(out)["time"]
        self.assertEqual(tf["open_unbanked_need_production"], 1)
        self.assertEqual(tf["pace_verdict"], "CRITICAL")
        # bank it -> release-only -> RELEASE_NOW (a release is seconds)
        run("--dir", root, "log-win", "p1", "--proof", "x",
            now="2026-07-02T22:35:00Z")
        _, out = run("--dir", root, "status", "--json",
                     now="2026-07-02T22:40:00Z")
        tf = json.loads(out)["time"]
        self.assertEqual(tf["open_banked_release_only"], 1)
        self.assertEqual(tf["pace_verdict"], "RELEASE_NOW")

    def test_past_deadline_raises_alarm(self):
        root = self._init_tz()
        run("--dir", root, "plan", "p1", "--date", "2026-07-02",
            now="2026-07-02T18:00:00Z")
        # 23:30Z == 18:30 CDT -> deadline passed with p1 open
        _, out = run("--dir", root, "status", now="2026-07-02T23:30:00Z")
        self.assertIn("PAST_DEADLINE", out)
        self.assertIn("PASSED", out)


class TestPromiseAuditor(unittest.TestCase):
    """Promises carry a meaning + acceptance criterion; an independent
    auditor verifies each released promise is well-formed AND honored, with
    a screenshot as the burden of proof. This is the check that stops
    'released' from masquerading as 'kept'."""

    def _proj(self, burden="screenshot"):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(
            root, ignore_errors=True))
        run("--dir", str(root), "init", "--cadence", "5", "--by", "sam",
            now="2026-07-01T08:00:00Z")
        cfg = root / ".staircase" / "config.yml"
        cfg.write_text(cfg.read_text().replace(
            "burden_of_proof: artifact", f"burden_of_proof: {burden}"))
        return str(root)

    def _shot(self, root, name="live.png"):
        p = Path(root) / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)  # minimal PNG-ish file
        return str(p)

    def test_plan_stores_acceptance_criterion(self):
        root = self._proj()
        run("--dir", root, "plan", "row-42", "--means",
            "FEC per lift renders live on the dashboard",
            "--accept", "true", "--date", "2026-07-01",
            now="2026-07-01T08:30:00Z")
        crit = staircase.Project(Path(root) / ".staircase").promise_criteria()
        self.assertEqual(crit["row-42"]["means"],
                         "FEC per lift renders live on the dashboard")
        self.assertEqual(crit["row-42"]["accept"], "true")

    def test_screenshot_burden_rejects_url(self):
        root = self._proj("screenshot")
        code, out = run("--dir", root, "log-win", "row-42",
                        "--proof", "https://example.com/proof",
                        now="2026-07-01T09:00:00Z")
        self.assertEqual(code, 2)
        self.assertIn("screenshot", out)

    def test_screenshot_burden_accepts_image_file(self):
        root = self._proj("screenshot")
        code, out = run("--dir", root, "log-win", "row-42",
                        "--proof", self._shot(root),
                        now="2026-07-01T09:00:00Z")
        self.assertEqual(code, 0, out)

    def test_audit_flags_ill_formed_promise(self):
        root = self._proj("artifact")
        # planned with NO means/accept -> ill-formed
        run("--dir", root, "plan", "row-42", "--date", "2026-07-01",
            now="2026-07-01T08:30:00Z")
        run("--dir", root, "log-win", "row-42", "--proof", "x",
            now="2026-07-01T09:00:00Z")
        run("--dir", root, "release", "--n", "1", now="2026-07-01T09:30:00Z")
        code, out = run("--dir", root, "audit", "--json",
                        now="2026-07-01T10:00:00Z")
        d = json.loads(out)
        self.assertEqual(code, 1)          # fails closed
        self.assertFalse(d["clean"])
        self.assertEqual(d["results"][0]["verdict"], "ILL_FORMED")

    def test_audit_fails_released_promise_with_no_screenshot(self):
        root = self._proj("screenshot")
        run("--dir", root, "plan", "row-42", "--means", "live",
            "--accept", "true", "--date", "2026-07-01",
            now="2026-07-01T08:30:00Z")
        # a win exists but with a NON-screenshot proof would be refused by
        # log-win; simulate the historical gap by planning+releasing with no
        # win at all -> NO_PROOF, and the release is a broken promise
        run("--dir", root, "log-win", "row-42", "--proof",
            self._shot(root), now="2026-07-01T09:00:00Z")
        run("--dir", root, "release", "--n", "1", now="2026-07-01T09:30:00Z")
        # accept "true" passes -> HONORED (deterministic); audit clean
        code, out = run("--dir", root, "audit", "--run", "--json",
                        now="2026-07-01T10:00:00Z")
        d = json.loads(out)
        self.assertEqual(code, 0, out)
        self.assertTrue(d["clean"])
        self.assertEqual(d["results"][0]["verdict"], "HONORED")

    def test_audit_catches_broken_release(self):
        root = self._proj("screenshot")
        run("--dir", root, "plan", "row-42", "--means", "live",
            "--accept", "false", "--date", "2026-07-01",   # accept FAILS
            now="2026-07-01T08:30:00Z")
        run("--dir", root, "log-win", "row-42", "--proof",
            self._shot(root), now="2026-07-01T09:00:00Z")
        run("--dir", root, "release", "--n", "1", now="2026-07-01T09:30:00Z")
        code, out = run("--dir", root, "audit", "--run", "--json",
                        now="2026-07-01T10:00:00Z")
        d = json.loads(out)
        self.assertEqual(code, 1)          # released but accept fails
        self.assertEqual(d["results"][0]["verdict"], "NOT_HONORED")
        self.assertIn("row-42", d["failures"])


    def test_promise_amend_makes_ill_formed_wellformed(self):
        root = self._proj("screenshot")
        run("--dir", root, "plan", "row-42", "--date", "2026-07-01",
            now="2026-07-01T08:30:00Z")               # no criteria -> ill-formed
        run("--dir", root, "log-win", "row-42", "--proof", self._shot(root),
            now="2026-07-01T09:00:00Z")
        run("--dir", root, "release", "--n", "1", now="2026-07-01T09:30:00Z")
        code, out = run("--dir", root, "audit", "--json",
                        now="2026-07-01T10:00:00Z")
        self.assertEqual(json.loads(out)["results"][0]["verdict"], "ILL_FORMED")
        # attach criteria after the fact
        run("--dir", root, "promise", "row-42", "--means", "live",
            "--accept", "true", now="2026-07-01T10:05:00Z")
        code, out = run("--dir", root, "audit", "--run", "--json",
                        now="2026-07-01T10:10:00Z")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["results"][0]["verdict"], "HONORED")

    def test_status_kept_means_honored_not_released(self):
        root = self._proj("screenshot")
        run("--dir", root, "plan", "row-42", "--means", "live",
            "--accept", "false",                       # will NOT honor
            "--date", "2026-07-01", now="2026-07-01T08:30:00Z")
        run("--dir", root, "log-win", "row-42", "--proof", self._shot(root),
            now="2026-07-01T09:00:00Z")
        run("--dir", root, "release", "--n", "1", now="2026-07-01T09:30:00Z")
        run("--dir", root, "audit", "--run", now="2026-07-01T10:00:00Z")
        code, out = run("--dir", root, "status", now="2026-07-01T10:05:00Z")
        # released but not honored -> status must NOT claim it kept
        self.assertIn("0 of 1 HONORED", out)
        self.assertIn("RELEASED ≠ KEPT", out)


if __name__ == "__main__":
    unittest.main()

