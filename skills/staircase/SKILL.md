---
description: The Staircase methodology — bank verified wins in a buffer, release them on a steady, fully-ledgered cadence, and manage expectations through a per-project .staircase/ folder. Use when starting work in any repo containing .staircase/, when logging a verified win, releasing wins, rendering or linting a delivery report, changing a delivery cadence/SLA, or when the user mentions staircase, delivery cadence, win buffer, expectations record, or promise-kept ratio.
---

# Staircase

We run bursty production against a delivery SLA, with a verified buffer.
Both production and release events are ledgered, timestamped at occurrence,
never backdated; the full ledger is available to any stakeholder at any
time.

Builders produce nonlinearly: three quiet days of machinery, then nine
wins in an afternoon. Stakeholders who answer upward on their own cycle
legitimately need a steady cadence they can relay. Neither way of working
is wrong. The buffer is the **interface** between them — never a screen in
front of either. Staircase is that interface, made of ledgers.

## The `.staircase/` folder — the heart of the plugin

Every project gets one, the way it gets a `.git/`. `.git` records history;
`.staircase` records **expectations**. The CLI (`tools/staircase.py`) holds
no global state — it discovers `.staircase/` by walking up from cwd.

```
.staircase/
  config.yml        # the SLA: cadence/day, report slots, stakeholders,
                    # proof adapters, texture policy, lint vocabulary additions,
                    # optional `mission:` one-liner (the why — rendered FIRST
                    # in every agent brief, before the SLA)
  expectations.md   # THE EXPECTATIONS RECORD: what was promised to whom and
                    # when; cadence-change history (explicit, dated,
                    # owner-signed — never silent); definitions of done
  wins.jsonl        # production ledger (verified wins, append-only, never backdated)
  releases.jsonl    # release ledger (what was announced, when)
  plans.jsonl       # named-in-advance commitments + MISS events (promise-kept ratio)
  steering.jsonl    # manager ledger: every Staircase Manager pass — drift AND
                    # on-track alike (silence is proven attention, so it is logged)
  stakeholders/     # one persona file per stakeholder + objections.yml
                    # (asked/answered/preempted — the expectation-learning loop)
  reports/          # rendered report archive (derived)
```

`expectations.md` is the anti-ratcheting instrument: the file you open when
anyone says "but I thought you were doing 10 a day."

## The agent contract (binding)

Any agent — Claude included — starting work in a repo that contains a
`.staircase/` folder works under this contract:

1. **Orient first.** Run `staircase agent-brief` before anything else
   (the plugin's SessionStart hook does this automatically). The brief is
   the orientation: current SLA, today's named scope, buffer, alarms,
   definition of done, unresolved stakeholder objections.
2. **The day's plan is the scope.** The named items in today's plan are
   what you are working toward. Expanding scope requires a
   `staircase plan <ids>` entry in plans.jsonl — never silent drift.
3. **"Done" means the proof gate passed.** A win exists only when
   `staircase log-win <id> --proof <artifact>` succeeds under this
   project's proof adapters. An agent may NEVER claim completion
   otherwise. No ledger entry, no claim.
4. **Progress claims render from the ledgers.** When reporting progress,
   use `staircase status` / `staircase report` output — numbers that
   replay from wins/releases/plans — not impressions.
5. **Slips are named early.** If the plan can't be met, invoke the MISS
   protocol as soon as that is known: `staircase miss <id> --why "..."`.
   A slip logged at 15:00 is workflow; one discovered at day's end is a
   surprise. (The Stop hook warns — never blocks — if plan items are
   neither released nor MISS-logged.)
6. **Sizing comes from ledger queries, never intention.** Estimate
   tomorrow from `released_by_day` history and buffer level, not from
   optimism.

Human and agent teammates work from the same ledgers under the same rules
— `.staircase/` is the shared alignment file for both.

## The daily loop

```bash
staircase init --cadence 5 --by <owner> --stakeholder <name> \
    --mission "<the one-line why>"        # once per project
staircase plan m14 m15 m16 m17 m18        # morning: name the day's five
staircase report --slot morning           # render + archive the morning report
# ... produce; every verified win, the moment it verifies:
staircase log-win m14 --proof https://.../proof/m14
staircase release                         # draw cadence-N oldest banked wins
staircase report --slot evening           # render the evening report
staircase lint .staircase/reports/<date>-evening.md   # send-gate; exit 0 or do not send
staircase status                          # operator dashboard: the internal truth
```

Commit `.staircase/` (minus `reports/` if you prefer) so the ledgers are
git-audited too.

## Guardrails (features, not fine print)

1. **Internal truth first.** `staircase status` is the operator's primary
   dashboard; a buffer below the daily cadence is a loud ALARM, and
   `status --check` exits non-zero for cron gating.
2. **Anti-over-smoothing.** Reports keep honest texture: a beyond-cadence
   day says "+N beyond (a strong production day)"; a short day says "the
   buffer ran short — the gap is visible here, not smoothed away."
3. **Drill-down one click away.** Every report ends with the "Full ledger"
   pointer; `lint` refuses a report without it.
4. **Expectation changes are explicit.** The daily cadence can only change
   through `staircase set-quota N --reason ... --by ...`, which writes a
   dated, owner-signed line into expectations.md. A hand-edited cadence
   with no matching entry fails every command closed.

## The send-gate (`staircase lint`)

A rendered report is refused (exit 1) if any of these fail:

- the machine marker doesn't match the current ledgers (stale or
  hand-edited numbers);
- any number in the body cannot be replayed from the ledgers;
- retired vocabulary appears — framings that misdescribe the buffer as
  concealment (built-in blocklist in `BUILTIN_RETIRED`, plus per-project
  additions in `config.yml: retired_vocabulary`);
- the "Full ledger" drill-down, buffer line, or slot lead line is missing.

## Proof-event adapters

A win is logged only with proof. Pick the adapter per project in
`config.yml: proof_adapters`; all reduce to `log-win <id> --proof <ref>`:

- **manual** — any URL or artifact path: `--proof https://.../proof-pack/`
- **merged-PR (gh)** —
  `staircase log-win PR-123 --proof "$(gh pr view 123 --json url -q .url)" --gate "test \"$(gh pr view 123 --json state -q .state)\" = MERGED"`
- **CI-green** —
  `staircase log-win build-88 --proof "$(gh run view 88 --json url -q .url)" --gate "test \"$(gh run view 88 --json conclusion -q .conclusion)\" = success"`
- **custom gate command** — `--gate "<any command>"`: non-zero exit refuses
  the win. Point it at your acceptance script, freshness audit, or
  eligibility query.

## When to use Staircase

- A team whose production is bursty reports to stakeholders who need a
  steady, relayable cadence.
- An owner wants promise-kept ratios and cadence history to be facts in a
  file rather than recollections in a meeting.
- Human + agent teams need one shared, machine-checkable definition of
  scope, done, and progress.

When asked to check status or render a report, prefer the slash commands
(`/staircase:staircase-status`, `/staircase:staircase-report`) or run the
CLI directly: `python3 "${CLAUDE_PLUGIN_ROOT}/tools/staircase.py" ...`.

## The Staircase Manager — steering from footprints

The plugin ships a steering subagent, **`staircase-manager`**
(`agents/staircase-manager.md`): spawned periodically inside a working
session, it reads the project's `.staircase/` contract, infers REAL
progress from footprints — ledgers, git, file mtimes, a transcript tail
when available, **never the parent's claims** — and sends one
evidence-cited steering message back to the parent ONLY when drift is
detected. It watches five domains:

- **SCOPE** — actual work vs plans.jsonl; silent scope growth = steer.
- **TIME** — deadlines/time-boxes from expectations.md / config.yml
  (optional `time_box_hours` key); an item at 3× its box is steered NOW:
  split it or MISS it now.
- **PROMISES** — named-vs-delivered; the manager defends the
  promise-kept ratio, steering toward named items before extras.
- **BUDGET** — token burn vs ledger progress where task/usage data is
  visible; divergence gets called out with a cheaper path.
- **ALTITUDE** — focus without losing the bigger picture, anchored on
  the config `mission:` one-liner: activity serving no plan item AND no
  mission-relevant unlock is busywork (steer back down); a plan item
  gone mission-obsolete is steered to a MISS-with-reason rather than
  ground out. No mission set → green by default.

The split is deliberate: the AGENT holds judgment only; EVIDENCE
gathering is deterministic, via `staircase manager-check` (CLI) /
`staircase_manager_check` (MCP) — agent-brief + last-N ledger events +
plan ages + git log since morning + optional `--transcript` tail, emitted
as one JSON packet. Every pass ends in `staircase steer-log --verdict
drift|on_track ...`, appending to `steering.jsonl` — **silence is logged
too** (the proven-attention rule: a quiet ledger line proves the manager
looked and found green, and distinguishes attention from absence). The
manager's toolset is read-only plus that one sanctioned write; it can
never `release` (owner prerogative, denied in its frontmatter), never
expands scope, and reports `ON-TRACK` — one word — when all five domains
are green.

### Spawn mechanics

**(a) In-session.** The parent (or a wakeup/Stop hook) spawns the
`staircase-manager` agent, passing the manager-check packet in the spawn
prompt (or just the project path — the manager can gather its own
packet). Foreground: the steering message returns as the subagent's
result. Background: the manager delivers steering via `SendMessage` to
the main session. Either way, **steering messages arrive as inputs the
parent must ACT on or explicitly rebut in its next message — never
silently ignore.** The steering ledger records which happened
(`steer-log --outcome acted|rebutted`).

**(b) Periodic hook (optional, default OFF).** `hooks/hooks.json` carries
a Stop-hook nudge gated on the `STAIRCASE_MANAGER_NUDGE` env var — unset
(the default) it is a no-op, so sessions stay quiet. To enable, export
`STAIRCASE_MANAGER_NUDGE=1` (shell profile or project `.claude/settings
.json` `env`); each Stop then emits a systemMessage telling the parent to
run `manager-check` and spawn the manager. For a time-based cadence
instead, run the same pattern from your own wakeup/loop tooling — the
packet command is deterministic and cheap.

## MCP tools — same ledger, same rules

The plugin bundles a stdio MCP server (`tools/mcp_server.py`) — a thin
wrapper that shells to the CLI, which keeps all logic and every fail-closed
guardrail. The tools are `staircase_status`, `staircase_agent_brief`,
`staircase_log_win(id, proof)`, `staircase_plan(ids[])`,
`staircase_release(n?)`, `staircase_report(slot)`, `staircase_lint(path)`,
`staircase_miss(id, reason, new_date?)`,
`staircase_manager_check(last?, transcript?, trigger?)`, and
`staircase_steer_log(verdict, trigger?, message?, evidence[]?, outcome?)`.
Every tool also takes an optional `project_dir` — a validated absolute
path walked upward for `.staircase/` — for worktrees and multi-repo
workspaces where the session cwd is not the staircase project. Use
whichever surface is at hand — MCP or CLI, the ledgers and refusals are
identical.

**Owner prerogative:** `staircase_release` announces work to stakeholders —
by convention it belongs to the owner's session, not to subagents. Deny it
per-subagent with `disallowedTools:
mcp__plugin_staircase_staircase__staircase_release` in the agent's
frontmatter (leaving status/brief open), or session-wide via a
`permissions.deny` rule in settings. Changing the SLA (`set-quota`) has no
MCP tool at all — it stays a deliberate, owner-signed CLI act. Details and
snippets: the plugin README.
