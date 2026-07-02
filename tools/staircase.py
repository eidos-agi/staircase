#!/usr/bin/env python3
"""staircase — an honest rendering layer between bursty production and a
steady delivery SLA.

We run bursty production against a delivery SLA, with a verified buffer.
Both production and release events are ledgered, timestamped at occurrence,
never backdated; the full ledger is available to any stakeholder at any
time. The buffer is an interface between two valid ways of working — a
builder's nonlinear output and a stakeholder's legitimate need for a
cadence they can relay upward — never a screen in front of either.

Every project gets a `.staircase/` folder — per-project expectations state,
the way `.git/` is per-project history. The CLI holds no global state; it
discovers `.staircase/` by walking up from the current directory.

    .staircase/
      config.yml        the SLA: cadence, slots, stakeholders, proof
                        adapters, texture policy, lint vocabulary additions
      expectations.md   THE EXPECTATIONS RECORD: what was promised to whom
                        and when; cadence-change history (explicit, dated,
                        owner-signed — never silent); definitions of done
      wins.jsonl        production ledger (verified wins, append-only)
      releases.jsonl    release ledger (what was announced, when)
      plans.jsonl       named-in-advance commitments (promise-kept ratio)
      steering.jsonl    manager ledger: every Staircase Manager run —
                        drift AND on-track alike (silence is proven
                        attention, so silence is logged too)
      stakeholders/     persona files + objections.yml (the
                        expectation-learning loop)
      reports/          rendered report archive (derived)

Commands
    init        scaffold .staircase/ with a guided config
    log-win     append a verified win to the production ledger
    release     draw N oldest banked wins and announce them
    plan        name wins in advance (feeds the promise-kept ratio)
    miss        MISS protocol: name a slip early — why + new date, ledgered
    status      operator dashboard: buffer, streak, alarms (internal truth)
    report      render the stakeholder report FROM THE LEDGERS ONLY
    lint        fail-closed send-gate for a rendered report
    set-quota   change the daily cadence — an explicit, ledgered,
                owner-signed decision (writes expectations.md + config.yml)
    agent-brief one-command orientation block for any agent starting work
                in this repo (the agent works under this contract)
    agent-check session-end check: plan items untouched with no MISS
                logged → warn (never block)
    manager-check
                assemble the Staircase Manager's evidence packet
                deterministically: agent-brief + last-N ledger events +
                plan ages + git log since morning + optional transcript
                tail. The packet is the manager agent's input; evidence
                gathering stays deterministic, judgment stays in the agent
    steer-log   append one Staircase Manager run to steering.jsonl —
                drift (message + cited evidence required) or on_track
                (silence, logged: the proven-attention rule)

Guardrails baked in as features:
  1. Internal truth first — `status` is the operator's primary dashboard;
     buffer below cadence is a loud alarm.
  2. Anti-over-smoothing — reports keep honest texture: beyond-cadence days
     say so, shortfall days say so, in plain words.
  3. Drill-down always one click away — every report ends with the ledger
     pointer, and `lint` refuses a report without it.
  4. Expectation changes are explicit — a cadence value in config.yml with
     no matching dated entry in expectations.md fails every command closed.

Exit codes: 0 ok · 1 lint violations · 2 config/input/backdate failure ·
3 nothing to do (empty buffer / flat day) · 4 status --check with alarms.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCHEMA = 1
DEFAULT_CADENCE = 5
DIRNAME = ".staircase"
MARKER_RE = re.compile(
    r"<!-- staircase: wins=(\d+) releases=(\d+) buffer=(\d+) "
    r"cadence=(\d+) -->")
HEADER_RE = re.compile(r"^# Delivery report — (\d{4}-\d{2}-\d{2}) "
                       r"\((morning|evening)\)")
CADENCE_ENTRY_RE = re.compile(
    r"^\s*[-*]\s*(\d{4}-\d{2}-\d{2})\s*—\s*cadence set to (\d+)/day"
    r"\s+by\s+(.+?)\s*(?:—.*)?$")
# Retired vocabulary: words that misframe the buffer. The blocklist exists
# precisely so these framings never reach a stakeholder.
BUILTIN_RETIRED = [
    r"\bsandbag\w*",
    r"\bhid(?:e|es|ing|den)\b",
    r"managers?\s+don'?t\s+understand",
    r"\bsimpler\b",
]


# ---------------------------------------------------------------- plumbing
def _fail(msg: str) -> "SystemExit":
    print(f"staircase: ERROR: {msg}", file=sys.stderr)
    return SystemExit(2)


def _emit_json(command: str, payload: dict) -> None:
    """--json output: a machine-readable twin of the human output. Same
    data, same ledgers, no extra numbers — a rendering, not a new source."""
    print(json.dumps({"schema": SCHEMA, "command": command, **payload},
                     sort_keys=True))


def _now() -> dt.datetime:
    """Current UTC time. STAIRCASE_NOW (ISO-8601) exists for offline tests
    only; it is still subject to the monotonic no-backdate guard."""
    env = os.environ.get("STAIRCASE_NOW")
    if env:
        try:
            t = dt.datetime.fromisoformat(env.replace("Z", "+00:00"))
        except ValueError:
            raise _fail(f"STAIRCASE_NOW is not ISO-8601: {env!r}")
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def _parse_ts(s: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


# --------------------------------------------------------- time awareness
# Occurrence timestamps (what lands in the ledgers) are ALWAYS real UTC and
# never backdated — see log-win/release. The helpers below reason ABOUT the
# clock (how long until the deadline, in whose zone) without ever rewriting
# an occurrence time; that separation keeps the "never backdated" guarantee
# ironclad while making briefs and steering time-aware.
def _zone(name: str):
    """ZoneInfo for an IANA name; None if unavailable (stays stdlib-only —
    zoneinfo ships with Python 3.9+)."""
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


def _system_tz_name() -> str:
    """Best-effort IANA name of the machine's own zone, so `init` can record
    where the agent runs. Reads the /etc/localtime symlink (macOS/Linux);
    falls back to the fixed-offset abbreviation if that is unavailable."""
    try:
        target = os.readlink("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    key = getattr(_now().astimezone().tzinfo, "key", None)
    return key or ""


def _hhmm(s: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(s))
    if not m:
        raise _fail(f"time-of-day must be HH:MM, got {s!r}")
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        raise _fail(f"time-of-day out of range: {s!r}")
    return h, mi


def _human_remaining(mins: int) -> str:
    if mins <= 0:
        m = -mins
        return f"deadline PASSED {m // 60}h{m % 60:02d}m ago"
    return f"{mins // 60}h{mins % 60:02d}m to deadline"


def time_facts(p: "Project", now: dt.datetime,
               open_total: int, open_banked: int) -> dict:
    """Deterministic clock facts for briefs, status and the manager packet.

    The deadline is interpreted in the STAKEHOLDER's timezone (that is when
    they expect delivery); 'now' and the remaining time are computed in
    absolute UTC and rendered in both zones. `open_banked` = promises already
    won (a release is seconds of work); the remainder still needs production
    (real time) — the pace verdict weighs the two differently."""
    op_name = p.config.get("operator_tz") or _system_tz_name()
    sh_name = p.config.get("stakeholder_tz") or op_name
    op = _zone(op_name) or now.astimezone().tzinfo
    sh = _zone(sh_name) or op
    now_op = now.astimezone(op)
    now_sh = now.astimezone(sh)
    h, mi = _hhmm(p.config.get("deadline_local", "18:00"))
    deadline_sh = now_sh.replace(hour=h, minute=mi, second=0, microsecond=0)
    mins = int((deadline_sh - now_sh).total_seconds() // 60)
    open_unbanked = max(0, open_total - open_banked)
    if open_total == 0:
        verdict = "CLEAR"            # nothing outstanding
    elif mins <= 0:
        verdict = "PAST_DEADLINE"    # slot passed with work still open
    elif open_unbanked > 0 and mins < 60:
        verdict = "CRITICAL"         # unbuilt promises, under an hour
    elif open_unbanked > 0 and mins < 120:
        verdict = "TIGHT"            # unbuilt promises, under two hours
    elif open_banked > 0 and mins < 60:
        verdict = "RELEASE_NOW"      # only releases left, slot closing
    else:
        verdict = "OK"
    off_h = ((now_op.utcoffset() or dt.timedelta())
             - (now_sh.utcoffset() or dt.timedelta())).total_seconds() / 3600
    return {
        "operator_tz": op_name, "stakeholder_tz": sh_name,
        "now_operator": now_op.strftime("%Y-%m-%d %H:%M %Z"),
        "now_stakeholder": now_sh.strftime("%Y-%m-%d %H:%M %Z"),
        "operator_minus_stakeholder_hours": round(off_h, 2),
        "deadline_local": f"{h:02d}:{mi:02d}",
        "deadline_stakeholder": deadline_sh.strftime("%Y-%m-%d %H:%M %Z"),
        "deadline_operator":
            deadline_sh.astimezone(op).strftime("%Y-%m-%d %H:%M %Z"),
        "minutes_remaining": mins,
        "hours_remaining": round(mins / 60, 2),
        "remaining_human": _human_remaining(mins),
        "open_promises": open_total,
        "open_banked_release_only": open_banked,
        "open_unbanked_need_production": open_unbanked,
        "pace_verdict": verdict,
    }


def _clock_line(tf: dict) -> str:
    """The one-line CLOCK banner shared by agent-brief and status."""
    same = tf["operator_tz"] == tf["stakeholder_tz"]
    if same:
        parts = [f"now {tf['now_stakeholder']}",
                 f"deadline {tf['deadline_stakeholder']}",
                 tf["remaining_human"]]
    else:
        parts = [f"now {tf['now_stakeholder']} (stakeholder) / "
                 f"{tf['now_operator']} (here, "
                 f"{tf['operator_minus_stakeholder_hours']:+g}h)",
                 f"deadline {tf['deadline_stakeholder']} = "
                 f"{tf['deadline_operator']} here",
                 tf["remaining_human"]]
    if tf["open_promises"]:
        parts.append(
            f"{tf['open_promises']} promise(s) open "
            f"({tf['open_banked_release_only']} banked→release-only, "
            f"{tf['open_unbanked_need_production']} need production)")
    parts.append(f"pace: {tf['pace_verdict']}")
    return "CLOCK: " + " · ".join(parts)


def find_root(start: Path) -> Path | None:
    """Walk up from `start` to the filesystem root looking for .staircase/."""
    p = start.resolve()
    for d in (p, *p.parents):
        if (d / DIRNAME).is_dir():
            return d / DIRNAME
    return None


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for i, ln in enumerate(path.read_text().splitlines(), 1):
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                raise _fail(f"{path.name} line {i} unparseable (fail closed)")
    return out


# --------------------------------------------------- config.yml (flat YAML)
# A deliberately small YAML subset: comments, flat `key: value`, inline
# lists of scalars. No dependency needed; the config stays shallow on
# purpose — expectations that need prose belong in expectations.md.
def yamlish_loads(text: str) -> dict:
    out: dict = {}
    for raw in text.splitlines():
        ln = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("#") \
            else ""
        if not ln.strip():
            continue
        if ":" not in ln:
            raise _fail(f"config.yml: unparseable line {raw!r}")
        key, val = ln.split(":", 1)
        out[key.strip()] = _yamlish_scalar(val.strip())
    return out


def _yamlish_scalar(v: str):
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_yamlish_scalar(x.strip()) for x in inner.split(",")] \
            if inner else []
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def yamlish_dumps(d: dict, header: str = "") -> str:
    lines = [header] if header else []
    for k, v in d.items():
        if isinstance(v, bool):
            s = "true" if v else "false"
        elif isinstance(v, list):
            s = "[" + ", ".join(str(x) for x in v) + "]"
        else:
            s = str(v)
        lines.append(f"{k}: {s}")
    return "\n".join(lines) + "\n"


DEFAULT_CONFIG = {
    "schema": SCHEMA,
    "mission": "",
    "cadence_per_day": DEFAULT_CADENCE,
    "report_slots": ["morning", "evening"],
    "stakeholders": [],
    "proof_adapters": ["manual"],
    "gate_command": "",
    "texture_notes": True,
    "retired_vocabulary": [],
    # --- time awareness (all interpreted in stakeholder_tz) ---
    # operator_tz: where the agent/machine runs (auto-detected at init).
    # stakeholder_tz: where the stakeholder reads the report; "" = same as
    # operator. deadline_local / morning_local: the day's slot wall-clocks,
    # in the STAKEHOLDER's zone — that is when delivery is expected.
    "operator_tz": "",
    "stakeholder_tz": "",
    "deadline_local": "18:00",
    "morning_local": "07:00",
    # --- burden of proof ---
    # What a win's --proof must be for the independent auditor to accept it:
    #   "artifact"   — any URL or file path (permissive default)
    #   "screenshot" — an existing image FILE showing the thing completed
    #                  (the strongest, hardest-to-fake burden; recommended for
    #                  anything a stakeholder should be able to SEE)
    "burden_of_proof": "artifact",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff",
              ".heic", ".pdf"}


def _is_screenshot(proof: str) -> bool:
    """True iff proof points at an existing image file — the screenshot
    burden of proof. A URL or a missing file is not a screenshot."""
    if not proof:
        return False
    pth = Path(proof)
    return pth.suffix.lower() in IMAGE_EXTS and pth.is_file()


# ----------------------------------------------------------- project state
class Project:
    """Everything the CLI knows, loaded from .staircase/ and nowhere else."""

    def __init__(self, sc: Path):
        self.dir = sc
        self.config = dict(DEFAULT_CONFIG)
        cfg_path = sc / "config.yml"
        if cfg_path.is_file():
            self.config.update(yamlish_loads(cfg_path.read_text()))
        self.wins = read_jsonl(sc / "wins.jsonl")
        self.releases = read_jsonl(sc / "releases.jsonl")
        self.steering = read_jsonl(sc / "steering.jsonl")
        self.audits = read_jsonl(sc / "audits.jsonl")
        self._plan_events = read_jsonl(sc / "plans.jsonl")
        self.plans = [e for e in self._plan_events
                      if e.get("type") == "plan"]
        self.misses = [e for e in self._plan_events
                       if e.get("type") == "miss"]
        self.expectations = (sc / "expectations.md").read_text() \
            if (sc / "expectations.md").is_file() else ""

    # -- expectations record ------------------------------------------------
    def cadence_history(self) -> list[tuple[str, int, str]]:
        """(date, cadence, signed-by) entries from expectations.md, in file
        order. The expectations record is the authority on the SLA."""
        out = []
        for ln in self.expectations.splitlines():
            m = CADENCE_ENTRY_RE.match(ln)
            if m:
                out.append((m.group(1), int(m.group(2)), m.group(3)))
        return out

    @property
    def cadence(self) -> int:
        return int(self.config["cadence_per_day"])

    @property
    def mission(self) -> str:
        """The optional one-line why (config.yml `mission:`). Rendered
        FIRST in every agent brief — the why, then the fence."""
        return str(self.config.get("mission") or "").strip()

    def consistency_errors(self) -> list[str]:
        """Guardrail 4: a cadence with no matching owner-signed entry in
        expectations.md is a silent expectation change — fail closed."""
        hist = self.cadence_history()
        if not hist:
            return [f"expectations.md carries no cadence entry — the SLA "
                    f"({self.cadence}/day in config.yml) must be an explicit, "
                    "dated, owner-signed line (run `staircase init` or "
                    "`staircase set-quota`)"]
        latest = hist[-1][1]
        if latest != self.cadence:
            return [f"config.yml cadence_per_day={self.cadence} does not "
                    f"match the latest expectations.md entry ({latest}/day) — "
                    "expectation changes are explicit owner decisions; use "
                    "`staircase set-quota N --reason ... --by ...`"]
        return []

    # -- ledgers --------------------------------------------------------------
    def max_ts(self) -> dt.datetime | None:
        ts = [e["ts"] for e in (*self.wins, *self.releases,
                                *self._plan_events, *self.steering)]
        return max((_parse_ts(t) for t in ts), default=None)

    def released_ids(self) -> set[str]:
        return {i for r in self.releases for i in r["ids"]}

    def banked(self) -> list[dict]:
        """FIFO buffer: wins not yet released, in production order."""
        done = self.released_ids()
        return [w for w in self.wins if w["id"] not in done]

    def released_by_day(self) -> dict[str, int]:
        days: dict[str, int] = {}
        for r in self.releases:
            d = r["ts"][:10]
            days[d] = days.get(d, 0) + len(r["ids"])
        return days

    def streak(self, as_of: dt.date) -> int:
        """Consecutive days meeting the cadence, ending today or (when today
        is still open) yesterday. Any short day breaks it — honest by
        design."""
        days = self.released_by_day()
        d = as_of
        if days.get(d.isoformat(), 0) < self.cadence:
            d -= dt.timedelta(days=1)
        n = 0
        while days.get(d.isoformat(), 0) >= self.cadence:
            n += 1
            d -= dt.timedelta(days=1)
        return n

    def promise_ratio(self, as_of: str) -> tuple[int, int]:
        """(kept, named) across all plans up to as_of."""
        released = self.released_ids()
        named = kept = 0
        for p in self.plans:
            if p["date"] <= as_of:
                named += len(p["ids"])
                kept += sum(1 for i in p["ids"] if i in released)
        return kept, named

    def plan_for(self, date: str) -> list[str]:
        return [i for p in self.plans if p["date"] == date for i in p["ids"]]

    def promise_criteria(self) -> dict[str, dict]:
        """Latest {means, accept} per promise id — the definition of what each
        promise MEANS and how honoring it is checked. Read from ANY plan-ledger
        event carrying `criteria` (a `plan` at naming time OR a later `criteria`
        amendment via `staircase promise`). Absent → the promise is ill-formed."""
        out: dict[str, dict] = {}
        for pl in self._plan_events:              # file order == ts order
            for i, c in (pl.get("criteria") or {}).items():
                out[i] = c
        return out

    def audit_verdicts(self) -> dict[str, str]:
        """The most recent independent-audit verdict per promise id (from the
        last `staircase audit` run). Empty if never audited."""
        return dict(self.audits[-1]["verdicts"]) if self.audits else {}

    def uses_promises(self) -> bool:
        """True once a project adopts verifiable promises — any acceptance
        criteria set, or a screenshot burden of proof. Such a project's
        'kept' means audit-HONORED, not merely released."""
        return (bool(self.promise_criteria())
                or str(self.config.get("burden_of_proof")) == "screenshot")

    def promise_view(self, as_of: str) -> dict:
        """The honest promise scoreboard on UNIQUE ids up to as_of:
        named / released / honored (released AND last audit verdict HONORED).
        For a promise-using project, 'kept' == honored; else kept == released."""
        released = self.released_ids()
        verdicts = self.audit_verdicts()
        named = list(dict.fromkeys(
            i for p in self.plans if p["date"] <= as_of for i in p["ids"]))
        rel = [i for i in named if i in released]
        honored = [i for i in rel if verdicts.get(i) == "HONORED"]
        up = self.uses_promises()
        return {"named": len(named), "released": len(rel),
                "honored": len(honored), "uses_promises": up,
                "kept": len(honored) if up else len(rel),
                "released_not_honored": [i for i in rel
                                         if verdicts.get(i) != "HONORED"]
                if up else []}

    def win_for(self, wid: str) -> dict | None:
        for w in self.wins:
            if w["id"] == wid:
                return w
        return None

    # -- appends ----------------------------------------------------------------
    def append(self, filename: str, event: dict) -> dict:
        """Append-only, timestamped at occurrence, never backdated: the
        event ts is taken from the clock at append time and must not precede
        any event already in ANY project ledger."""
        now = _now()
        last = self.max_ts()
        if last and now < last:
            raise _fail(
                f"refusing to backdate: now={now.isoformat()} precedes the "
                f"latest ledgered event ({last.isoformat()}). Ledger events "
                "are timestamped at occurrence, never backdated.")
        event = {"schema": SCHEMA, **event,
                 "ts": now.isoformat(timespec="seconds")}
        with open(self.dir / filename, "a") as fh:
            fh.write(json.dumps(event, sort_keys=True,
                                separators=(",", ":")) + "\n")
        return event


def load_project(dirarg: str | None) -> Project:
    start = Path(dirarg) if dirarg else Path.cwd()
    sc = find_root(start)
    if sc is None:
        raise _fail(f"no {DIRNAME}/ found from {start.resolve()} upward — "
                    "run `staircase init` at the project root")
    return Project(sc)


# ------------------------------------------------------------------- init
EXPECTATIONS_TEMPLATE = """\
# Expectations record — {project}

The file to open when anyone asks "what was promised, to whom, and when."
Every cadence change below is an explicit, dated, owner-signed decision —
never silent. Raising or lowering the daily number without a line here
fails every staircase command closed.

## Delivery SLA (cadence history)

- {date} — cadence set to {cadence}/day by {by} — initial SLA

## Definitions of done

- A win counts only when its proof gate passes (see proof adapters in
  config.yml). Verified means verified: a proof URL or artifact per win.

## Commitments and renegotiations

(Named-in-advance commitments live in plans.jsonl. Scope agreements and
renegotiations are recorded here in dated prose.)
"""

PERSONA_TEMPLATE = """\
# Stakeholder: {name}

- role: (fill in — e.g. answers upward on a weekly cycle)
- needs: a steady, predictable delivery cadence they can relay in their own
  reporting — a legitimate constraint, not a failing
- reads: morning + evening delivery reports
- cares about: (fill in)
- red-team focus: what would this person question in a report? What number
  would they ask to see behind?
"""

OBJECTIONS_TEMPLATE = """\
# Objections ledger — the expectation-learning loop.
# Every stakeholder question or reaction, ledgered: asked | answered | preempted.
# The red-team command appends here; answering one well often becomes a
# permanent line in the report template or the expectations record.
objections: []
"""


def cmd_init(a) -> int:
    root = Path(a.dir) if a.dir else Path.cwd()
    sc = root / DIRNAME
    if sc.exists():
        raise _fail(f"{sc} already exists")
    now = _now()
    sc.mkdir(parents=True)
    (sc / "stakeholders").mkdir()
    (sc / "reports").mkdir()
    cfg = dict(DEFAULT_CONFIG)
    cfg["mission"] = a.mission or ""
    cfg["cadence_per_day"] = a.cadence
    cfg["stakeholders"] = list(a.stakeholder or [])
    # record WHERE the agent runs so time math is unambiguous across machines
    cfg["operator_tz"] = getattr(a, "operator_tz", "") or _system_tz_name()
    cfg["stakeholder_tz"] = getattr(a, "stakeholder_tz", "") or ""
    if getattr(a, "deadline", None):
        _hhmm(a.deadline)               # validate now, fail fast
        cfg["deadline_local"] = a.deadline
    (sc / "config.yml").write_text(yamlish_dumps(
        cfg, header="# .staircase/config.yml — the delivery SLA for this "
                    "project.\n# Cadence changes: use `staircase set-quota` "
                    "(never edit cadence_per_day by hand).\n# Time: slot "
                    "wall-clocks (deadline_local/morning_local) are read in "
                    "stakeholder_tz; operator_tz is where the agent runs."))
    (sc / "expectations.md").write_text(EXPECTATIONS_TEMPLATE.format(
        project=root.resolve().name, date=now.date().isoformat(),
        cadence=a.cadence, by=a.by))
    for name in ("wins.jsonl", "releases.jsonl", "plans.jsonl",
                 "steering.jsonl"):
        (sc / name).touch()
    for s in a.stakeholder or []:
        (sc / "stakeholders" / f"{s}.md").write_text(
            PERSONA_TEMPLATE.format(name=s))
    (sc / "stakeholders" / "objections.yml").write_text(OBJECTIONS_TEMPLATE)
    (sc / "reports" / ".gitkeep").touch()
    print(f"staircase: initialized {sc}")
    print(f"  SLA: {a.cadence} verified wins released per day, signed by "
          f"{a.by} in expectations.md")
    print("  Next: log wins with `staircase log-win <id> --proof <url>`")
    return 0


# ----------------------------------------------------------------- log-win
def cmd_log_win(a) -> int:
    p = load_project(a.dir)
    if any(w["id"] == a.id for w in p.wins):
        raise _fail(f"win id {a.id!r} already ledgered (ids are unique; "
                    "points earned are earned)")
    burden = str(p.config.get("burden_of_proof", "artifact"))
    if burden == "screenshot" and not _is_screenshot(a.proof):
        raise _fail(
            f"burden of proof is 'screenshot': --proof must be an existing "
            f"image file showing {a.id!r} completed, got {a.proof!r}. A URL "
            "or a missing file does not prove it was done — capture the screen.")
    if a.gate:
        rc = subprocess.run(a.gate, shell=True).returncode
        if rc != 0:
            raise _fail(f"gate command failed (exit {rc}) — win not logged; "
                        "a win counts only when its proof gate passes")
    ev = p.append("wins.jsonl", {
        "type": "win", "id": a.id, "proof": a.proof,
        **({"note": a.note} if a.note else {})})
    buffer_n = len(p.banked()) + 1
    if a.json:
        _emit_json("log-win", {"id": a.id, "proof": a.proof,
                               "ts": ev["ts"], "buffer": buffer_n,
                               **({"note": a.note} if a.note else {})})
        return 0
    print(f"staircase: win {a.id!r} ledgered at {ev['ts']} "
          f"(buffer now {buffer_n})")
    return 0


# ----------------------------------------------------------------- release
def cmd_release(a) -> int:
    p = load_project(a.dir)
    err = p.consistency_errors()
    if err:
        raise _fail(err[0])
    banked = p.banked()
    n = a.n if a.n is not None else p.cadence
    if n <= 0:
        raise _fail("--n must be positive")
    take = banked[:n]
    if not take:
        if a.json:
            _emit_json("release", {
                "released": [], "requested": n, "short": n, "buffer": 0,
                "note": "buffer empty — nothing to release (a production "
                        "day; say so plainly in the report)"})
        else:
            print("staircase: buffer empty — nothing to release (a "
                  "production day; say so plainly in the report)")
        return 3
    ev = p.append("releases.jsonl", {
        "type": "release", "ids": [w["id"] for w in take], "requested": n})
    short = n - len(take)
    if a.json:
        _emit_json("release", {
            "released": [w["id"] for w in take], "requested": n,
            "short": short, "buffer": len(banked) - len(take),
            "ts": ev["ts"]})
        return 0
    print(f"staircase: released {len(take)} of {n} requested at {ev['ts']}: "
          + ", ".join(w["id"] for w in take))
    if short:
        print(f"  buffer ran short by {short} — honest texture: the report "
              "will say so")
    print(f"  buffer now {len(banked) - len(take)}")
    return 0


# -------------------------------------------------------------------- plan
def cmd_plan(a) -> int:
    p = load_project(a.dir)
    date = a.date or _now().date().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise _fail("--date must be YYYY-MM-DD")
    if date < _now().date().isoformat():
        raise _fail("plans are named in advance — a plan for a past date "
                    "would be a backdated promise")
    event = {"type": "plan", "date": date, "ids": list(a.ids)}
    means = getattr(a, "means", None)
    accept = getattr(a, "accept", None)
    if means or accept:
        # the acceptance criterion: what the promise MEANS and how honoring it
        # is checked — stored per id so the auditor can verify each one
        event["criteria"] = {i: {**({"means": means} if means else {}),
                                 **({"accept": accept} if accept else {})}
                             for i in a.ids}
    ev = p.append("plans.jsonl", event)
    tail = (f" — means: {means!r}" if means else "") + \
           (f" · accept: {accept!r}" if accept else "")
    if not (means or accept):
        tail = " — NO acceptance criterion yet (the auditor will flag these " \
               "as ill-formed; add --means/--accept so 'kept' is verifiable)"
    print(f"staircase: {len(a.ids)} commitment(s) named for {date} at "
          f"{ev['ts']}: " + ", ".join(a.ids) + tail)
    return 0


# ----------------------------------------------------------------- promise
def cmd_promise(a) -> int:
    """Attach or amend a promise's acceptance criteria AFTER it was named —
    the fix for a promise planned without a --means/--accept (which the
    auditor flags ill-formed). Appends a criteria event; never inflates the
    named count, never backdates."""
    p = load_project(a.dir)
    tiso = _now().date().isoformat()
    named = {i for pl in p.plans if pl["date"] <= tiso for i in pl["ids"]}
    if a.id not in named:
        raise _fail(f"{a.id!r} is not a named promise (plans.jsonl) — name it "
                    "with `staircase plan` first, then attach criteria")
    if not (a.means or a.accept):
        raise _fail("give at least one of --means / --accept — a promise "
                    "needs a definition of done and/or an acceptance check")
    p.append("plans.jsonl", {
        "type": "criteria", "ids": [a.id],
        "criteria": {a.id: {**({"means": a.means} if a.means else {}),
                            **({"accept": a.accept} if a.accept else {})}}})
    print(f"staircase: criteria attached to {a.id}"
          + (f" — means: {a.means!r}" if a.means else "")
          + (f" · accept: {a.accept!r}" if a.accept else "")
          + ". Run `staircase audit --run` to re-verify.")
    return 0


# ------------------------------------------------------------- self-update
def cmd_self_update(a) -> int:
    """Self-update: pull the latest plugin from its source repo into the
    installed location (the directory this file lives in). Fast-forward only;
    prints the version before/after. For a marketplace install, prefer Claude
    Code's `/plugin update staircase` — this is the CLI path for a git checkout."""
    here = Path(__file__).resolve().parent.parent      # plugin root
    def ver():
        pj = here / ".claude-plugin" / "plugin.json"
        try:
            return json.loads(pj.read_text()).get("version", "?")
        except OSError:
            return "?"
    before = ver()
    rc, _ = 1, ""
    try:
        pr = subprocess.run(["git", "-C", str(here), "pull", "--ff-only"],
                            capture_output=True, text=True, timeout=60)
        rc, out = pr.returncode, pr.stdout + pr.stderr
    except OSError as e:
        raise _fail(f"self-update needs git in a checkout of the plugin repo: {e}")
    after = ver()
    if rc != 0:
        raise _fail(f"self-update failed (git pull --ff-only): {out.strip()}. "
                    "For a marketplace install use `/plugin update staircase`.")
    if before == after:
        print(f"staircase: already up to date (v{after})")
    else:
        print(f"staircase: updated v{before} → v{after}. Restart the session "
              "so the MCP server reloads.")
    return 0


# ------------------------------------------------------------------ status
def cmd_status(a) -> int:
    p = load_project(a.dir)
    today = _now().date()
    tiso = today.isoformat()
    banked = p.banked()
    released_today = p.released_by_day().get(tiso, 0)
    kept, named = p.promise_ratio(tiso)
    stk = p.streak(today)
    released = p.released_ids()
    win_ids = {w["id"] for w in p.wins}
    open_plan = [i for i in p.plan_for(tiso) if i not in released]
    open_banked = [i for i in open_plan if i in win_ids]
    tf = time_facts(p, _now(), len(open_plan), len(open_banked))
    alarms = p.consistency_errors()
    if len(banked) < p.cadence:
        alarms.append(
            f"BUFFER BELOW CADENCE: {len(banked)} banked < {p.cadence}/day "
            "SLA — production must outpace release or the cadence "
            "conversation happens in expectations.md, not silently")
    if tf["pace_verdict"] in ("CRITICAL", "PAST_DEADLINE"):
        alarms.append(
            f"DEADLINE {tf['pace_verdict']}: {tf['remaining_human']} · "
            f"{tf['open_unbanked_need_production']} promise(s) still need "
            f"production, {tf['open_banked_release_only']} banked need only a "
            "release")
    elif tf["pace_verdict"] == "RELEASE_NOW":
        alarms.append(
            f"RELEASE WINDOW CLOSING: {tf['remaining_human']} · "
            f"{tf['open_banked_release_only']} banked promise(s) unreleased — "
            "a release is seconds; the report renders at the slot")

    n_hist = len(p.cadence_history())
    if a.json:
        _emit_json("status", {
            "date": tiso, "cadence": p.cadence,
            "cadence_entries": n_hist, "buffer": len(banked),
            "oldest_banked": banked[0]["id"] if banked else None,
            "released_today": released_today, "streak": stk,
            "promises_kept": kept, "promises_named": named,
            "wins": len(p.wins), "releases": len(p.releases),
            "plans": len(p.plans), "time": tf,
            "alarms": alarms, "dir": str(p.dir)})
        return 4 if (alarms and a.check) else 0
    print(f"Staircase status — {today.isoformat()} (operator dashboard: "
          "this is the internal truth)")
    # promises first and loudest — the one number that matters most, and it
    # means AUDIT-HONORED (not merely released) once the project uses promises
    pv = p.promise_view(tiso)
    open_note = (f" · {len(open_plan)} OPEN: {', '.join(open_plan)}"
                 if open_plan else "")
    if pv["uses_promises"]:
        print(f"  PROMISES: {pv['honored']} of {pv['named']} HONORED "
              f"(independent audit)  ← the one that matters most{open_note}")
        if pv["released_not_honored"]:
            print(f"  ⚠  RELEASED ≠ KEPT: {len(pv['released_not_honored'])} "
                  "released but NOT audit-honored — "
                  + ", ".join(pv["released_not_honored"])
                  + ". Ship the real thing (with a screenshot) or MISS-log; "
                  "run `staircase audit`.")
    else:
        print(f"  PROMISES: {kept} of {named} named-in-advance kept  "
              f"← the one that matters most{open_note}")
    print(f"  {_clock_line(tf)}")
    print(f"  SLA:      {p.cadence} verified wins released per day "
          f"(expectations.md, {n_hist} cadence "
          f"entr{'y' if n_hist == 1 else 'ies'}) — serves the promises")
    print(f"  Buffer:   {len(banked)} verified win(s) banked"
          + (f" (oldest: {banked[0]['id']})" if banked else ""))
    print(f"  Today:    {released_today} released")
    print(f"  Streak:   {stk} day(s) on cadence")
    print(f"  Ledgers:  {len(p.wins)} wins · {len(p.releases)} release "
          f"event(s) · {len(p.plans)} plan(s) — {p.dir}")
    if alarms:
        for al in alarms:
            print(f"  ALARM ⚠  {al}")
    else:
        print("  Alarms:   none")
    return 4 if (alarms and a.check) else 0


# ------------------------------------------------------------------ report
def render_report(p: Project, slot: str, date: str) -> str:
    """The stakeholder report, rendered FROM THE LEDGERS ONLY. Every number
    below is a function of wins.jsonl / releases.jsonl / plans.jsonl /
    expectations.md — there is no argument through which a hand-authored
    number can enter."""
    banked = p.banked()
    buffer_n = len(banked)
    cadence = p.cadence
    d = dt.date.fromisoformat(date)
    released_today_ids = [i for r in p.releases if r["ts"][:10] == date
                          for i in r["ids"]]
    wins_by_id = {w["id"]: w for w in p.wins}
    kept, named = p.promise_ratio(date)
    stk = p.streak(d)
    plan_ids = p.plan_for(date)

    L = [f"# Delivery report — {date} ({slot})", ""]
    if slot == "morning":
        on_deck = min(cadence, buffer_n)
        L.append(f"On deck today: {on_deck} verified win(s) to release from "
                 f"the buffer, against a {cadence}/day cadence.")
        if plan_ids:
            L.append("Named in advance: " + ", ".join(plan_ids) + ".")
        L.append(f"Buffer: {buffer_n} verified win(s) banked.")
        if p.config.get("texture_notes", True) and buffer_n < cadence:
            L.append(f"Plain words: the buffer ({buffer_n}) is below the "
                     f"daily cadence ({cadence}) today — production comes "
                     "first and the release count may land short. You will "
                     "see the real number tonight.")
    else:
        n = len(released_today_ids)
        if n >= cadence:
            extra = n - cadence
            L.append(f"Released today: {n} — cadence of {cadence} met"
                     + (f", plus {extra} beyond (a strong production day)"
                        if extra and p.config.get("texture_notes", True)
                        else "") + ".")
        else:
            L.append(f"Released today: {n} of {cadence} on the cadence — "
                     "the buffer ran short; production continues and the "
                     "gap is visible here, not smoothed away.")
        for i, wid in enumerate(released_today_ids, 1):
            w = wins_by_id.get(wid, {})
            L.append(f"  {i}. {wid} — proof: {w.get('proof', '(ledgered)')}")
        if plan_ids:
            kept_today = [i for i in plan_ids if i in set(released_today_ids)
                          or i in p.released_ids()]
            L.append(f"Named in advance this morning: {len(kept_today)} of "
                     f"{len(plan_ids)} delivered"
                     + ("" if len(kept_today) == len(plan_ids) else
                        " — slipped: " + ", ".join(
                            i for i in plan_ids if i not in kept_today))
                     + ".")
        L.append(f"Buffer: {buffer_n} verified win(s) banked for the coming "
                 "days.")
    if named:
        L.append(f"Promises kept to date: {kept} of {named} named in "
                 "advance.")
    if stk:
        L.append(f"Streak: {stk} day(s) meeting the cadence.")
    L += ["",
          "Full ledger — every production and release event, timestamped "
          f"at occurrence, one click beneath this report: {p.dir.name}/ "
          "(wins.jsonl · releases.jsonl · plans.jsonl · expectations.md)",
          "",
          f"<!-- staircase: wins={len(p.wins)} releases={len(p.releases)} "
          f"buffer={buffer_n} cadence={cadence} -->"]
    return "\n".join(L) + "\n"


def cmd_report(a) -> int:
    p = load_project(a.dir)
    err = p.consistency_errors()
    if err:
        raise _fail(err[0])
    date = a.date or _now().date().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise _fail("--date must be YYYY-MM-DD")
    body = render_report(p, a.slot, date)
    out = p.dir / "reports" / f"{date}-{a.slot}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(body)
    if a.json:
        _emit_json("report", {
            "date": date, "slot": a.slot, "path": str(out), "body": body,
            "marker": {"wins": len(p.wins), "releases": len(p.releases),
                       "buffer": len(p.banked()), "cadence": p.cadence}})
        return 0
    print(body, end="")
    print(f"[written: {out}]", file=sys.stderr)
    return 0


# -------------------------------------------------------------------- lint
def allowed_numbers(p: Project, date: str) -> set[int]:
    """Every integer a truthful report over these ledgers could contain."""
    banked_n = len(p.banked())
    released_today = sum(len(r["ids"]) for r in p.releases
                         if r["ts"][:10] == date)
    kept, named = p.promise_ratio(date)
    plan_ids = p.plan_for(date)
    kept_today = sum(1 for i in plan_ids if i in p.released_ids())
    ok = {0, banked_n, len(p.wins), len(p.releases), released_today,
          kept, named, len(plan_ids), kept_today,
          p.streak(dt.date.fromisoformat(date)),
          min(p.cadence, banked_n),
          sum(len(r["ids"]) for r in p.releases)}
    for _, c, _by in p.cadence_history():
        ok |= {c, max(0, released_today - c)}
    ok |= {p.cadence}
    ok |= set(p.released_by_day().values())
    ok |= set(range(1, released_today + 1))          # enumeration indices
    return ok


def ledger_strings(p: Project) -> list[str]:
    """Strings that legitimately appear verbatim in a report (ids, proofs,
    names) — masked before the numbers check so a PR number in a proof URL
    is never a false positive."""
    out = []
    for w in p.wins:
        out += [w["id"], w.get("proof", ""), w.get("note", "")]
    for pl in p.plans:
        out += pl["ids"]
    out += [str(s) for s in p.config.get("stakeholders", [])]
    out += [by for _, _, by in p.cadence_history()]
    return sorted({s for s in out if s}, key=len, reverse=True)


def lint_report(md: str, p: Project) -> list[str]:
    bad = []
    bad += p.consistency_errors()

    m = HEADER_RE.search(md)
    if not m:
        bad.append('header missing — "# Delivery report — YYYY-MM-DD '
                   '(morning|evening)" (required element)')
        return bad
    date, slot = m.group(1), m.group(2)

    # 1. marker: the report must be a rendering of the CURRENT ledgers
    mk = MARKER_RE.search(md)
    if not mk:
        bad.append("machine marker missing — a report carries the ledger "
                   "state it was rendered from")
    else:
        got = tuple(int(x) for x in mk.groups())
        want = (len(p.wins), len(p.releases), len(p.banked()), p.cadence)
        if got != want:
            bad.append(f"marker {got} does not match the ledgers {want} — "
                       "the report was not rendered from the current "
                       "ledgers; re-render, never hand-edit numbers")

    body = MARKER_RE.sub("", md)

    # 1b. promise audit send-gate — applies once a project adopts verifiable
    # promises (any acceptance criteria, or a screenshot burden). An evening
    # report must not go out claiming promises the independent auditor
    # rejected; a released promise with ILL_FORMED / NO_PROOF / NOT_HONORED is
    # a broken promise. Projects that never set criteria skip this gate.
    uses_promises = (bool(p.promise_criteria())
                     or str(p.config.get("burden_of_proof")) == "screenshot")
    if slot == "evening" and uses_promises:
        last_audit = p.audits[-1] if p.audits else None
        released_today = {i for r in p.releases if r["ts"][:10] == date
                          for i in r["ids"]}
        if released_today and not last_audit:
            bad.append("promise audit missing — this project uses verifiable "
                       "promises, so an evening report that released promises "
                       "must be preceded by `staircase audit` (released is "
                       "not kept until the auditor confirms it)")
        elif last_audit and last_audit.get("failures"):
            bad.append("promise audit FAILED for: "
                       + ", ".join(last_audit["failures"])
                       + " — released but not honored; do not send a report "
                       "claiming these kept (ship the real thing or MISS-log)")

    # 2. required elements
    if "Full ledger" not in body:
        bad.append('drill-down missing — every report ends with the "Full '
                   'ledger" pointer (guardrail 3)')
    if not re.search(r"^Buffer: \d+", body, re.M):
        bad.append("buffer line missing — the buffer is stated, never "
                   "implied")
    lead = "On deck today:" if slot == "morning" else "Released today:"
    if lead not in body:
        bad.append(f'lead line missing — a {slot} report opens with '
                   f'"{lead}"')

    # 3. retired vocabulary (built-in + project additions from config.yml)
    vocab = list(BUILTIN_RETIRED) + [
        r"\b" + re.escape(str(v)) + r"\b"
        for v in p.config.get("retired_vocabulary", [])]
    for rx in vocab:
        for hit in re.finditer(rx, body, re.I):
            bad.append(f"retired vocabulary: {hit.group(0)!r} — this "
                       "framing misdescribes the buffer; the buffer is an "
                       "interface between two valid ways of working")

    # 4. every number must be readable from the ledgers
    masked = re.sub(r"\d{4}-\d{2}-\d{2}", " ", body)          # dates
    masked = re.sub(r"\b\d{1,2}:\d{2}(:\d{2})?\b", " ", masked)  # times
    for s in ledger_strings(p):
        masked = masked.replace(s, " ")
    ok = allowed_numbers(p, date)
    for tok in re.finditer(r"\b\d+\b", masked):
        n = int(tok.group(0))
        if n not in ok:
            bad.append(f"number {n} does not appear in the ledgers — every "
                       "number in a report replays from wins/releases/plans/"
                       "expectations; hand-authored numbers are banned")
    return bad


def cmd_lint(a) -> int:
    p = load_project(a.dir)
    path = Path(a.report)
    if not path.is_file():
        raise _fail(f"{path} not found")
    bad = lint_report(path.read_text(), p)
    if a.json:
        _emit_json("lint", {"report": str(path), "ok": not bad,
                            "violations": bad})
        return 1 if bad else 0
    if bad:
        print(f"STAIRCASE-LINT: FAIL — {len(bad)} violation(s) in "
              f"{path.name} (do not send):")
        for b in bad:
            print(f"  ✗ {b}")
        return 1
    print(f"STAIRCASE-LINT: PASS — {path.name} renders from the ledgers "
          "and keeps the framing honest")
    return 0


# -------------------------------------------------------------------- miss
def cmd_miss(a) -> int:
    """MISS protocol: a slipped commitment is named EARLY, with why and a
    new date — never silently swapped, never discovered at day's end."""
    p = load_project(a.dir)
    today = _now().date().isoformat()
    named = {i for pl in p.plans if pl["date"] <= today for i in pl["ids"]}
    if a.id not in named:
        raise _fail(f"{a.id!r} is not a named commitment (plans.jsonl) — "
                    "only a named promise can be missed")
    if a.id in p.released_ids():
        raise _fail(f"{a.id!r} was already released — nothing slipped")
    new_date = a.new_date or (
        _now().date() + dt.timedelta(days=1)).isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", new_date) \
            or new_date <= today:
        raise _fail("--new-date must be a future YYYY-MM-DD")
    p.append("plans.jsonl", {"type": "miss", "id": a.id, "why": a.why,
                             "new_date": new_date})
    p.append("plans.jsonl", {"type": "plan", "date": new_date,
                             "ids": [a.id], "via": "miss"})
    print(f"staircase: MISS ledgered — {a.id} slipped ({a.why}); "
          f"re-committed for {new_date}. Say so in tonight's report; "
          "never let it surface at day's end.")
    return 0


# ------------------------------------------------------------- agent-brief
def open_objections(sc: Path) -> list[dict]:
    """Unresolved stakeholder objections (status: asked) from
    stakeholders/objections.yml — parsed leniently on purpose."""
    path = sc / "stakeholders" / "objections.yml"
    if not path.is_file():
        return []
    out = []
    for block in re.split(r"\n\s*-\s+(?=stakeholder:)", path.read_text()):
        fields = dict(re.findall(
            r"(stakeholder|question|status|date):\s*(.+)", block))
        if fields.get("status", "").split("#")[0].strip() == "asked":
            fields["question"] = fields.get("question", "").strip("\"' ")
            out.append(fields)
    return out


def brief_payload(p: Project, today: dt.date) -> dict:
    """The agent-brief as data — one computation shared by
    `agent-brief --json` and the manager-check evidence packet."""
    tiso = today.isoformat()
    banked = p.banked()
    kept, named = p.promise_ratio(tiso)
    plan_ids = p.plan_for(tiso)
    released = p.released_ids()
    win_ids = {w["id"] for w in p.wins}
    open_plan = [i for i in plan_ids if i not in released]
    open_banked = [i for i in open_plan if i in win_ids]
    misses_today = [m for m in p.misses if m["ts"][:10] == tiso]
    alarms = p.consistency_errors()
    if len(banked) < p.cadence:
        alarms.append(f"BUFFER BELOW CADENCE ({len(banked)} < "
                      f"{p.cadence}/day) — production outranks polish today")
    tf = time_facts(p, _now(), len(open_plan), len(open_banked))
    if tf["pace_verdict"] in ("CRITICAL", "PAST_DEADLINE"):
        alarms.append(
            f"DEADLINE {tf['pace_verdict']}: {tf['remaining_human']} · "
            f"{tf['open_unbanked_need_production']} promise(s) still need "
            f"production, {tf['open_banked_release_only']} banked need only "
            "a release")
    hist = p.cadence_history()
    return {
        "date": tiso, "mission": p.mission, "cadence": p.cadence,
        "sla": ({"cadence": p.cadence, "set_on": hist[-1][0],
                 "signed_by": hist[-1][2]} if hist else None),
        "plan_today": plan_ids,
        "open_plan": open_plan,
        "open_banked": open_banked,
        "time": tf,
        "misses_today": [m["id"] for m in misses_today],
        "buffer": len(banked), "streak": p.streak(today),
        "promises_kept": kept, "promises_named": named,
        "proof_adapters": [str(x) for x in
                           p.config.get("proof_adapters", ["manual"])],
        "alarms": alarms,
        "objections": [{"stakeholder": o.get("stakeholder", "?"),
                        "question": o.get("question", "?"),
                        **({"date": o["date"]} if o.get("date") else {})}
                       for o in open_objections(p.dir)]}


def cmd_agent_brief(a) -> int:
    """One command = full orientation. Any agent starting work in a repo
    with .staircase/ runs this FIRST and works under its contract."""
    p = load_project(a.dir)
    today = _now().date()
    tiso = today.isoformat()
    banked = p.banked()
    kept, named = p.promise_ratio(tiso)
    plan_ids = p.plan_for(tiso)
    if a.json:
        _emit_json("agent-brief", brief_payload(p, today))
        return 0
    # human path: reuse the payload so text and JSON can never diverge
    payload = brief_payload(p, today)
    open_plan = payload["open_plan"]
    misses_today = [m for m in p.misses if m["ts"][:10] == tiso]
    alarms = payload["alarms"]
    tf = payload["time"]
    hist = p.cadence_history()
    sla = (f"{p.cadence} verified wins released/day — set {hist[-1][0]} "
           f"by {hist[-1][2]} (expectations.md)") if hist else \
        f"{p.cadence}/day (UNSIGNED — see alarms)"
    adapters = ", ".join(str(x) for x in p.config.get("proof_adapters",
                                                      ["manual"]))

    L = [f"=== STAIRCASE AGENT BRIEF — {tiso} ==="]
    if p.mission:
        # the FIRST line, before the SLA: the why, then the fence
        L.append(f"Mission: {p.mission}")
    # PROMISES come first and loudest — they are the point of the whole system.
    L.append(">>> PROMISES ARE THE MOST IMPORTANT THING. Everything else "
             "(cadence, buffer, streak) exists to serve them and NEVER "
             "outranks them. <<<")
    if open_plan:
        rem = tf["remaining_human"]
        L.append(f"Promises: kept {kept} of {named} named today · "
                 f"{len(open_plan)} STILL OPEN ({rem}): "
                 + ", ".join(open_plan) + ". Work BACKWARDS from each open "
                 "promise — name what must be true for it to land, then do "
                 "exactly that. Nothing else earns your attention until every "
                 "promise is kept or honestly MISS-logged.")
    else:
        L.append(f"Promises: kept {kept} of {named} named today · none open — "
                 "hold the line; every promise released before its deadline.")
    L += ["Contract: bursty production against a delivery SLA with a "
         "verified buffer. Every production and release event is ledgered, "
         "timestamped at occurrence, never backdated. You are working "
         "under this contract (binding rules: the staircase skill).",
         f"SLA: {sla}",
         "Scope (today's named plan): "
         + (", ".join(plan_ids) if plan_ids else
            "none named yet — name scope with `staircase plan <ids>` "
            "BEFORE building; expanding scope requires a plans.jsonl "
            "entry, never silent drift"),
         f"Open plan items: "
         + (", ".join(open_plan) if open_plan else "none outstanding")
         + (f" · MISSes logged today: "
            + ", ".join(m['id'] for m in misses_today)
            if misses_today else ""),
         f"Buffer: {len(banked)} banked · streak "
         f"{p.streak(today)} day(s) (buffer/streak serve the promises above)",
         _clock_line(tf),
         f"Definition of done: proof adapter(s) [{adapters}] — a win "
         "EXISTS only when `staircase log-win <id> --proof <artifact>` "
         "succeeds; claim nothing beyond the ledger.",
         "Alarms: " + ("; ".join(alarms) if alarms else "none")]
    objs = open_objections(p.dir)
    if objs:
        L.append("Stakeholder sensitivities (unresolved objections):")
        for o in objs[:5]:
            L.append(f"  - {o.get('stakeholder', '?')}: "
                     f"\"{o.get('question', '?')}\""
                     + (f" (asked {o['date']})" if o.get("date") else ""))
    L.append("MISS protocol: if the plan can't be met, log it EARLY — "
             "`staircase miss <id> --why \"...\"` — not at day's end.")
    L.append("=== END BRIEF ===")
    print("\n".join(L))
    return 0


# ------------------------------------------------------------- agent-check
def cmd_agent_check(a) -> int:
    """Session-end check: today's plan has unreleased items and no MISS was
    logged → warn (never block). --hook emits Claude Code hook JSON."""
    p = load_project(a.dir)
    tiso = _now().date().isoformat()
    released = p.released_ids()
    missed = {m["id"] for m in p.misses if m["ts"][:10] == tiso}
    outstanding = [i for i in p.plan_for(tiso)
                   if i not in released and i not in missed]
    if not outstanding:
        if not a.hook:
            print("staircase: agent-check clean — plan accounted for "
                  "(released or MISS-logged)")
        return 0
    msg = (f"staircase: {len(outstanding)} plan item(s) for {tiso} neither "
           f"released nor MISS-logged: {', '.join(outstanding)}. Log the "
           "slip before ending — `staircase miss <id> --why \"...\"` — "
           "the MISS protocol beats a silent day's end.")
    if a.hook:
        print(json.dumps({"systemMessage": msg}))
    else:
        print(msg)
    return 0


# -------------------------------------------------------------- audit
def audit_promise(p: "Project", pid: str, run_accept: bool) -> dict:
    """Independently verify ONE promise. Deterministic checks only — the CLI
    confirms the promise is well-formed and that its burden of proof exists;
    the promise-auditor SUBAGENT does the content check (does the screenshot
    actually SHOW the thing). Verdicts:
      ILL_FORMED   — no acceptance criterion; the promise isn't verifiable
      NO_PROOF     — no win, or proof missing / not a screenshot when required
      NOT_HONORED  — an --accept check was run and failed
      UNVERIFIED   — well-formed with proof, but no command check run yet
                     (needs the auditor subagent to view the screenshot)
      HONORED      — well-formed, burden met, and (if run) the accept passed
    """
    crit = p.promise_criteria().get(pid, {})
    means, accept = crit.get("means"), crit.get("accept")
    released = pid in p.released_ids()
    win = p.win_for(pid)
    burden = str(p.config.get("burden_of_proof", "artifact"))
    reasons = []
    # 1) logical validity: is this even a well-formed, checkable promise?
    if not (means or accept):
        return {"id": pid, "verdict": "ILL_FORMED", "released": released,
                "reason": "no acceptance criterion (--means/--accept): a "
                          "promise that cannot be checked is not a promise"}
    # 2) burden of proof
    if win is None:
        return {"id": pid, "verdict": "NO_PROOF", "released": released,
                "means": means, "accept": accept,
                "reason": "no win ledgered for this promise"}
    proof = win.get("proof", "")
    is_shot = _is_screenshot(proof)
    if burden == "screenshot" and not is_shot:
        return {"id": pid, "verdict": "NO_PROOF", "released": released,
                "means": means, "accept": accept, "proof": proof,
                "reason": "burden is screenshot but proof is not an existing "
                          "image file"}
    # 3) honor check (deterministic, if a command is provided and requested)
    verdict, reason = "UNVERIFIED", (
        "well-formed with proof; command not run — the promise-auditor "
        "subagent must VIEW the proof to confirm it shows the thing")
    if accept and run_accept:
        rc = subprocess.run(accept, shell=True,
                            capture_output=True).returncode
        verdict = "HONORED" if rc == 0 else "NOT_HONORED"
        reason = (f"accept check `{accept}` exited {rc}"
                  + ("" if rc == 0 else " — promise NOT honored"))
    elif not accept:
        # no runnable check, but a screenshot burden that is met stands as
        # deterministic evidence pending the subagent's visual confirmation
        verdict = "UNVERIFIED"
    return {"id": pid, "verdict": verdict, "released": released,
            "means": means, "accept": accept, "proof": proof,
            "screenshot": is_shot, "reason": reason}


def cmd_audit(a) -> int:
    """The INDEPENDENT promise auditor. For each promise in scope, verify it
    is (a) logically well-formed — it has an acceptance criterion — and (b)
    honored — its burden of proof exists and any accept check passes. Writes
    a verdict record to audits.jsonl and FAILS CLOSED: if any RELEASED promise
    is not HONORED/UNVERIFIED-with-proof, exit non-zero. A released promise
    that the auditor cannot confirm is a broken promise, loudly."""
    p = load_project(a.dir)
    tiso = _now().date().isoformat()
    scope = a.scope or "released"
    released = p.released_ids()
    planned = list(dict.fromkeys(
        i for pl in p.plans if pl["date"] <= tiso for i in pl["ids"]))
    if scope == "released":
        ids = [i for i in planned if i in released]
    elif scope == "open":
        ids = [i for i in planned if i not in released]
    else:
        ids = planned
    results = [audit_promise(p, i, a.run) for i in ids]
    bad = [r for r in results
           if r["released"] and r["verdict"] in
           ("ILL_FORMED", "NO_PROOF", "NOT_HONORED")]
    record = {"type": "audit", "scope": scope, "ran_accept": bool(a.run),
              "verdicts": {r["id"]: r["verdict"] for r in results},
              "failures": [r["id"] for r in bad]}
    p.append("audits.jsonl", record)
    if a.json:
        _emit_json("audit", {"scope": scope, "results": results,
                             "failures": [r["id"] for r in bad],
                             "clean": not bad})
        return 1 if bad else 0
    print(f"=== PROMISE AUDIT ({scope}) — {tiso} ===")
    print("Burden of proof: "
          f"{p.config.get('burden_of_proof', 'artifact')}")
    for r in results:
        mark = {"HONORED": "✓", "UNVERIFIED": "?", "NO_PROOF": "✗",
                "ILL_FORMED": "✗", "NOT_HONORED": "✗"}.get(r["verdict"], "?")
        rel = " [RELEASED as kept]" if r["released"] else ""
        print(f"  {mark} {r['id']}: {r['verdict']}{rel} — {r['reason']}")
    if bad:
        print(f"\nAUDIT FAILED: {len(bad)} promise(s) RELEASED as kept but "
              "NOT honored — " + ", ".join(r["id"] for r in bad))
        print("A released promise the auditor cannot confirm is a broken "
              "promise. Ship the real thing or MISS-log it honestly.")
        return 1
    unver = [r["id"] for r in results if r["verdict"] == "UNVERIFIED"]
    if unver:
        print(f"\n{len(unver)} promise(s) UNVERIFIED — the promise-auditor "
              "subagent must VIEW the screenshot proof to confirm each shows "
              "the thing done. Deterministic checks pass; visual confirmation "
              "pending.")
    else:
        print("\nAUDIT CLEAN — every released promise is honored.")
    return 0


# ----------------------------------------------------------- manager-check
MANAGER_NUDGE = (
    "staircase: manager nudge — a Staircase Manager pass is due. Run "
    "`staircase manager-check` (or the staircase_manager_check MCP tool), "
    "spawn the staircase-manager agent with the packet, and treat its "
    "steering as input you must ACT on or explicitly rebut in your next "
    "message — never silently ignore.")


def _plan_ages(p: Project, now: dt.datetime) -> list[dict]:
    """TIME evidence: how long each named commitment (due today or earlier)
    has sat since it was named, and its current ledger status. Ages come
    from the plan event's own timestamp — footprints, not claims."""
    tiso = now.date().isoformat()
    released = p.released_ids()
    missed_ids = {m["id"] for m in p.misses}
    latest: dict[str, dict] = {}
    for pl in p.plans:
        if pl["date"] > tiso:
            continue
        for i in pl["ids"]:
            latest[i] = pl          # file order == ts order (append-only)
    out = []
    for i, pl in latest.items():
        status = ("released" if i in released
                  else "missed" if i in missed_ids else "open")
        age_h = (now - _parse_ts(pl["ts"])).total_seconds() / 3600
        out.append({"id": i, "planned_for": pl["date"],
                    "named_ts": pl["ts"], "age_hours": round(age_h, 1),
                    "days_past_due": max(
                        0, (now.date()
                            - dt.date.fromisoformat(pl["date"])).days),
                    "status": status})
    return sorted(out, key=lambda e: (e["named_ts"], e["id"]))


def _git_evidence(root: Path, since_date: str) -> dict:
    """SCOPE/TIME footprints from git — commit lines since morning plus the
    dirty-file count. Deterministic; degrades to available=false outside a
    repo (git absence is itself evidence the manager may weigh)."""
    def g(*args):
        try:
            pr = subprocess.run(["git", "-C", str(root), *args],
                                capture_output=True, text=True, timeout=10)
            return pr.returncode, pr.stdout
        except OSError:
            return 1, ""
    rc, _ = g("rev-parse", "--git-dir")
    if rc != 0:
        return {"available": False, "commits_since_morning": [],
                "dirty_files": None}
    _, log = g("log", f"--since={since_date}T00:00:00",
               "--pretty=format:%h %cI %s")
    _, st = g("status", "--porcelain")
    return {"available": True,
            "commits_since_morning":
                [ln for ln in log.splitlines() if ln.strip()],
            "dirty_files": len([ln for ln in st.splitlines()
                                if ln.strip()])}


def _transcript_evidence(path_s: str, tail_n: int = 20) -> dict:
    """BUDGET footprints: size, mtime and tail of a session transcript.
    The packet carries a bounded tail (never the whole file) — the manager
    can Read deeper at the recorded path if the tail warrants it."""
    path = Path(path_s)
    if not path.is_file():
        raise _fail(f"transcript not found: {path}")
    st = path.stat()
    lines = path.read_text(errors="replace").splitlines()
    return {"path": str(path.resolve()), "bytes": st.st_size,
            "mtime": dt.datetime.fromtimestamp(
                st.st_mtime, dt.timezone.utc).isoformat(timespec="seconds"),
            "lines": len(lines),
            "tail": [ln[:200] for ln in lines[-tail_n:]]}


def cmd_manager_check(a) -> int:
    """Assemble the Staircase Manager's evidence packet DETERMINISTICALLY.
    The manager agent supplies judgment; this command supplies footprints:
    agent-brief, the last N ledger events, plan ages, git log since
    morning, an optional transcript tail. Never the parent's claims."""
    if a.hook:
        print(json.dumps({"systemMessage": MANAGER_NUDGE}))
        return 0
    p = load_project(a.dir)
    now = _now()
    today = now.date()

    events = ([{"ledger": "wins", **e} for e in p.wins]
              + [{"ledger": "releases", **e} for e in p.releases]
              + [{"ledger": "plans", **e} for e in p._plan_events]
              + [{"ledger": "steering", **e} for e in p.steering])
    events.sort(key=lambda e: e["ts"])

    packet = {
        "generated_at": now.isoformat(timespec="seconds"),
        "trigger": a.trigger,
        "project": str(p.dir.parent),
        "staircase_dir": str(p.dir),
        "config": {"mission": p.mission,
                   "cadence_per_day": p.cadence,
                   "time_box_hours": p.config.get("time_box_hours"),
                   "report_slots": [str(s) for s in
                                    p.config.get("report_slots", [])]},
        "brief": brief_payload(p, today),
        "ledger_tail": events[-a.last:],
        "plan_ages": _plan_ages(p, now),
        "git": _git_evidence(p.dir.parent, today.isoformat()),
        "transcript": (_transcript_evidence(a.transcript)
                       if a.transcript else None),
        "steering_last": p.steering[-1] if p.steering else None,
    }
    if a.json:
        _emit_json("manager-check", packet)
    else:
        print(json.dumps({"schema": SCHEMA, "command": "manager-check",
                          **packet}, indent=2, sort_keys=True))
    return 0


# --------------------------------------------------------------- steer-log
def cmd_steer_log(a) -> int:
    """Append one Staircase Manager run to steering.jsonl (append-only,
    never backdated — same rules as every other ledger). A drift verdict
    requires the message AND cited evidence; an on_track verdict is logged
    too: silence is proven attention, so silence leaves a footprint."""
    p = load_project(a.dir)
    if a.verdict == "drift":
        if not a.message:
            raise _fail("verdict=drift requires --message — steering is a "
                        "message or it is nothing")
        if not a.evidence:
            raise _fail("verdict=drift requires at least one --evidence — "
                        "steering cites ledger lines, file mtimes, or git "
                        "output, never impressions")
    ev = p.append("steering.jsonl", {
        "type": "steer", "trigger": a.trigger,
        "evidence": list(a.evidence or []),
        "verdict": a.verdict,
        "message_sent": a.verdict == "drift",
        "message": a.message or "",
        **({"outcome": a.outcome} if a.outcome else {})})
    if a.json:
        _emit_json("steer-log", {
            "ts": ev["ts"], "trigger": a.trigger, "verdict": a.verdict,
            "message_sent": ev["message_sent"], "message": ev["message"],
            "evidence": ev["evidence"],
            **({"outcome": a.outcome} if a.outcome else {}),
            "runs": len(p.steering) + 1})
        return 0
    if a.verdict == "drift":
        print(f"staircase: steering logged at {ev['ts']} — DRIFT "
              f"({len(ev['evidence'])} evidence line(s)). Deliver the "
              "message to the parent now; it must act on it or rebut it "
              "explicitly.")
    else:
        print(f"staircase: steering logged at {ev['ts']} — ON-TRACK "
              "(silence is proven attention: the quiet run is ledgered "
              "too)")
    return 0


# --------------------------------------------------------------- set-quota
def cmd_set_quota(a) -> int:
    p = load_project(a.dir)
    if a.n <= 0:
        raise _fail("cadence must be positive")
    now = _now()
    entry = (f"- {now.date().isoformat()} — cadence set to {a.n}/day by "
             f"{a.by} — {a.reason}")
    exp_path = p.dir / "expectations.md"
    text = exp_path.read_text() if exp_path.is_file() else ""
    anchor = "## Delivery SLA (cadence history)"
    if anchor in text:
        head, _, tail = text.partition(anchor)
        # append the entry after the last cadence line in that section
        lines = tail.splitlines()
        last = 0
        for i, ln in enumerate(lines):
            if CADENCE_ENTRY_RE.match(ln):
                last = i
        lines.insert(last + 1, entry)
        text = head + anchor + "\n".join(lines) + "\n" \
            if not tail.endswith("\n") else head + anchor + "\n".join(lines)
        exp_path.write_text(text if text.endswith("\n") else text + "\n")
    else:
        exp_path.write_text(text + f"\n{anchor}\n\n{entry}\n")
    cfg_path = p.dir / "config.yml"
    cfg = yamlish_loads(cfg_path.read_text()) if cfg_path.is_file() \
        else dict(DEFAULT_CONFIG)
    old = cfg.get("cadence_per_day", DEFAULT_CADENCE)
    cfg["cadence_per_day"] = a.n
    cfg_path.write_text(yamlish_dumps(
        cfg, header="# .staircase/config.yml — the delivery SLA for this "
                    "project.\n# Cadence changes: use `staircase set-quota` "
                    "(never edit cadence_per_day by hand)."))
    print(f"staircase: cadence {old}/day → {a.n}/day, signed by {a.by}, "
          "recorded in expectations.md (explicit, dated, never silent)")
    return 0


# -------------------------------------------------------------------- main
JSON_HELP = ("emit a machine-readable JSON twin of the human output "
             "(same data, same ledgers)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="staircase",
        description="bank nonlinear verified wins; release a steady, "
                    "fully-ledgered cadence")
    ap.add_argument("--dir", help="project directory (default: discover "
                    ".staircase/ upward from cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="scaffold .staircase/ for this project")
    s.add_argument("--cadence", type=int, default=DEFAULT_CADENCE,
                   help=f"daily release SLA (default {DEFAULT_CADENCE})")
    s.add_argument("--by", required=True,
                   help="owner signing the initial SLA (goes in "
                        "expectations.md)")
    s.add_argument("--stakeholder", action="append",
                   help="stakeholder persona to scaffold (repeatable)")
    s.add_argument("--mission",
                   help="optional one-line why (config.yml mission:) — "
                        "rendered FIRST in every agent brief, before the "
                        "SLA")
    s.add_argument("--operator-tz", dest="operator_tz", default="",
                   help="IANA zone where the agent runs (default: "
                        "auto-detected from the machine)")
    s.add_argument("--stakeholder-tz", dest="stakeholder_tz", default="",
                   help="IANA zone where the stakeholder reads the report, "
                        "e.g. America/Chicago; slot deadlines are in THIS "
                        "zone (default: same as operator)")
    s.add_argument("--deadline", default="",
                   help="the day's promise deadline as HH:MM in "
                        "stakeholder_tz (default 18:00)")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("log-win", help="append a verified win (append-only, "
                                       "never backdated)")
    s.add_argument("id", help="unique win id (e.g. PR-123, metric-14)")
    s.add_argument("--proof", required=True,
                   help="URL or path proving the win (merged PR, CI run, "
                        "proof pack)")
    s.add_argument("--note", help="optional plain-language note")
    s.add_argument("--gate", help="custom gate command; non-zero exit "
                                  "refuses the win")
    s.add_argument("--json", action="store_true", help=JSON_HELP)
    s.set_defaults(fn=cmd_log_win)

    s = sub.add_parser("release", help="draw the N oldest banked wins and "
                                       "announce them")
    s.add_argument("--n", type=int, help="how many (default: the cadence)")
    s.add_argument("--json", action="store_true", help=JSON_HELP)
    s.set_defaults(fn=cmd_release)

    s = sub.add_parser("plan", help="name wins in advance (promise ledger)")
    s.add_argument("ids", nargs="+", help="win ids being committed")
    s.add_argument("--date", help="commitment date (default today; never "
                                  "past)")
    s.add_argument("--means", help="what this promise MEANS — the definition "
                                   "of done in one line (e.g. 'renders live "
                                   "on the dashboard')")
    s.add_argument("--accept", help="acceptance check: a shell command that "
                                    "exits 0 iff the promise is honored. The "
                                    "auditor runs it; without one the promise "
                                    "is flagged ill-formed")
    s.set_defaults(fn=cmd_plan)

    s = sub.add_parser("promise",
                       help="attach/amend a named promise's acceptance "
                            "criteria (--means/--accept) after planning")
    s.add_argument("id", help="the named promise to give criteria")
    s.add_argument("--means", help="what the promise means (definition of done)")
    s.add_argument("--accept", help="acceptance check: shell cmd, exit 0 iff "
                                    "honored")
    s.set_defaults(fn=cmd_promise)

    s = sub.add_parser("self-update",
                       help="update the installed plugin from its source repo "
                            "(git ff-only); or use `/plugin update staircase`")
    s.set_defaults(fn=cmd_self_update)

    s = sub.add_parser("audit",
                       help="INDEPENDENT promise auditor: verify each promise "
                            "is well-formed AND honored (burden of proof "
                            "met); fails closed on a released-but-unhonored "
                            "promise")
    s.add_argument("--scope", choices=["released", "open", "all"],
                   help="which promises to audit (default: released)")
    s.add_argument("--run", action="store_true",
                   help="execute each promise's --accept check (default: "
                        "deterministic form/proof checks only)")
    s.add_argument("--json", action="store_true", help=JSON_HELP)
    s.set_defaults(fn=cmd_audit)

    s = sub.add_parser("miss", help="MISS protocol: name a slip early — "
                                    "why + new date, ledgered")
    s.add_argument("id", help="the named commitment that slipped")
    s.add_argument("--why", required=True,
                   help="plain-language reason (goes in the ledger)")
    s.add_argument("--new-date", help="new commitment date (default "
                                      "tomorrow)")
    s.set_defaults(fn=cmd_miss)

    s = sub.add_parser("agent-brief",
                       help="one-command orientation for agents working in "
                            "this repo")
    s.add_argument("--json", action="store_true", help=JSON_HELP)
    s.set_defaults(fn=cmd_agent_brief)

    s = sub.add_parser("agent-check",
                       help="session-end check: unaccounted plan items → "
                            "warn, never block")
    s.add_argument("--hook", action="store_true",
                   help="emit Claude Code hook JSON (systemMessage)")
    s.set_defaults(fn=cmd_agent_check)

    s = sub.add_parser("manager-check",
                       help="assemble the Staircase Manager's evidence "
                            "packet (deterministic footprints, never "
                            "claims)")
    s.add_argument("--last", type=int, default=20,
                   help="how many trailing ledger events to include "
                        "(default 20)")
    s.add_argument("--transcript",
                   help="path to a session transcript; its size, mtime and "
                        "tail join the packet as BUDGET evidence")
    s.add_argument("--trigger", default="periodic",
                   help="what prompted this pass (periodic, stop-hook, "
                        "owner-ask, ...) — recorded in the packet")
    s.add_argument("--hook", action="store_true",
                   help="emit a Claude Code hook nudge (systemMessage) "
                        "instead of the packet")
    s.add_argument("--json", action="store_true", help=JSON_HELP)
    s.set_defaults(fn=cmd_manager_check)

    s = sub.add_parser("steer-log",
                       help="append one Staircase Manager run to "
                            "steering.jsonl (silence is logged too)")
    s.add_argument("--verdict", required=True,
                   choices=["drift", "on_track"],
                   help="the manager's judgment for this pass")
    s.add_argument("--trigger", default="periodic",
                   help="what prompted the pass (matches manager-check)")
    s.add_argument("--message",
                   help="the steering message delivered to the parent "
                        "(required for drift)")
    s.add_argument("--evidence", action="append", default=[],
                   help="one cited footprint — ledger line, file mtime, "
                        "git log line (repeatable; drift requires >= 1)")
    s.add_argument("--outcome",
                   help="optional: how the parent responded (acted, "
                        "rebutted, ...)")
    s.add_argument("--json", action="store_true", help=JSON_HELP)
    s.set_defaults(fn=cmd_steer_log)

    s = sub.add_parser("status", help="operator dashboard: buffer, streak, "
                                      "alarms (the internal truth)")
    s.add_argument("--check", action="store_true",
                   help="exit 4 when any alarm is raised (for cron gating)")
    s.add_argument("--json", action="store_true", help=JSON_HELP)
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("report", help="render the stakeholder report from "
                                      "the ledgers only")
    s.add_argument("--slot", required=True, choices=["morning", "evening"])
    s.add_argument("--date", help="report date (default today)")
    s.add_argument("--json", action="store_true", help=JSON_HELP)
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("lint", help="fail-closed send-gate for a rendered "
                                    "report")
    s.add_argument("report", help="path to the rendered report .md")
    s.add_argument("--json", action="store_true", help=JSON_HELP)
    s.set_defaults(fn=cmd_lint)

    s = sub.add_parser("set-quota", help="change the daily cadence — "
                                         "explicit, dated, owner-signed")
    s.add_argument("n", type=int, help="new cadence (wins/day)")
    s.add_argument("--reason", required=True,
                   help="why the expectation is changing")
    s.add_argument("--by", required=True, help="owner signing the change")
    s.set_defaults(fn=cmd_set_quota)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
