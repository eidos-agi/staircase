# Changelog

## 0.6.0 — 2026-07-02

Promises get a definition and an independent auditor. "Released" no longer
masquerades as "kept."

- A promise now carries a **meaning** and an **acceptance criterion**:
  `plan <id> --means "<definition of done>" --accept "<cmd, 0 iff honored>"`,
  stored per id in `plans.jsonl`.
- **Burden of proof**: `burden_of_proof: screenshot` in config makes
  `log-win` refuse any proof that is not an existing image file — the
  hardest-to-fake evidence that a thing is actually done.
- **`staircase audit`** — the independent promise auditor. Verdicts per
  promise: `ILL_FORMED` (no criterion), `NO_PROOF` (missing/again-not a
  screenshot), `NOT_HONORED` (accept check failed), `UNVERIFIED` (well-formed,
  awaiting the subagent's visual confirmation), `HONORED`. Fails closed on any
  released-but-unhonored promise. Verdicts append to `audits.jsonl`.
- **`promise-auditor` subagent** — opens each screenshot and confirms it
  actually shows the promised thing; a picture that doesn't show it is not
  proof.
- **`staircase lint`** treats a failed/absent audit as an evening-report
  send-gate (for projects that adopt verifiable promises).

## 0.5.0 — 2026-07-02

Promises first, emphatically. The named-in-advance promises are the point of
the whole system; everything else serves them.

- `agent-brief` leads with a loud PROMISES banner and the open promises +
  time left, with the standing charge to **work backwards from each promise**.
  Cadence/buffer/streak are explicitly framed as serving the promises.
- `status` puts PROMISES first ("← the one that matters most") above SLA,
  buffer, and streak.
- The Staircase Manager gains a PRIME DIRECTIVE preamble: promises outrank
  all five watch-domains; a dropped promise is the only true failure.
- The skill's agent contract adds rule 0: promises are the most important
  thing; work backwards to keep them.

## 0.4.0 — 2026-07-02

Time awareness. Briefs, status and manager steering now know what time it
is, in whose zone, and how long is left on today's promises.

- Config: `operator_tz` (auto-detected at init), `stakeholder_tz`,
  `deadline_local`, `morning_local`. Slot wall-clocks are interpreted in
  the stakeholder's zone — that is when delivery is expected — while the
  agent may run in another. `init` gains `--operator-tz`,
  `--stakeholder-tz`, `--deadline`.
- `agent-brief` and `status` render a CLOCK line (now in both zones, the
  offset, time-to-deadline, and a pace verdict). A `time` block is added to
  `agent-brief --json`, `status --json`, and the manager-check packet.
- Pace verdicts split open promises into banked (release-only) vs unbuilt
  (need production): `CRITICAL` / `TIGHT` / `RELEASE_NOW` / `PAST_DEADLINE`.
  `CRITICAL` and `PAST_DEADLINE` raise status/brief alarms.
- The Staircase Manager's TIME domain now reads the clock and must cite
  time-remaining in its steering.
- Occurrence timestamps in the ledgers remain real UTC and never backdated —
  time-awareness reasons about the clock, it never rewrites an event time.
- Timezones via stdlib `zoneinfo`; still zero-dependency. 74 tests.

## 0.3.0 — 2026-07-02

Initial public release, extracted from the customer-zero implementation.

- `.staircase/` folder convention: `config.yml`, `expectations.md`
  (owner-signed cadence history, hand-edits fail closed), append-only
  `wins.jsonl` / `releases.jsonl` / `plans.jsonl` / `steering.jsonl`,
  `stakeholders/`, `reports/`.
- CLI (`tools/staircase.py`, stdlib only): `init`, `plan`, `log-win`
  (proof-gated), `release` (FIFO buffer draw), `report`, `lint`
  (fail-closed send-gate), `status` (alarms; `--check` for cron),
  `set-quota` (owner-signed), `miss`, `agent-brief`, `agent-check`,
  `manager-check`, `steer-log`. `--json` twins on the read paths.
- Stdio MCP server (`tools/mcp_server.py`): thin wrapper over the CLI —
  same ledger, same rules; per-call `project_dir`; `set-quota`
  deliberately has no MCP tool; deny `staircase_release` to subagents.
- Agent accountability: SessionStart `agent-brief` hook, Stop-hook plan
  accounting (warn only), the Staircase Manager steering subagent
  (SCOPE / TIME / PROMISES / BUDGET / ALTITUDE; footprints, never claims;
  every pass ledgered, silence included).
- 69 tests.
