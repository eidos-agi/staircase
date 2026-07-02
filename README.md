# Staircase

**An honest rendering layer between bursty production and a steady delivery
SLA.** Verified wins are banked in a buffer and released on a cadence
stakeholders can trust — with the full ledger one click beneath.

> We run bursty production against a delivery SLA, with a verified buffer.
> Both production and release events are ledgered, timestamped at
> occurrence, never backdated; the full ledger is available to any
> stakeholder at any time.

## Why this exists

Staircase was born from a pattern that kept repeating in real business
problems: **AI work is illegible in a way stakeholders are not equipped
for.** Thirty seconds spent on the right skills file can beat eight hours of
visible, obvious work — but it might take a month of quiet exploration to
discover *which* thirty seconds. Progress on AI projects doesn't announce
itself the way a wall of finished bricks does. Left unmanaged, that
illegibility produces poor estimates, then poor results, then eroded trust —
in that order.

The remedy is old, not new. Navy SEALs surviving icy water don't think about
the swim; they count breaths — the smallest unit they can verifiably win.
Elephant carpaccio slices an impossibly large feature into paper-thin pieces,
each one individually real and shippable. Staircase applies the same
time-tested move to AI work: get down to small, verified, bite-sized wins,
bank each one the moment it is proven, and release them at a cadence the
people above you can actually consume. You stay true to how the problem
really gets solved *and* communicate it upward without distortion.

And underneath the mechanics is the thing the tool is quietly teaching: in
the age of AI, one of the most valuable things a person — or an agent — can
be is **reliable**. Consistent. Reliability makes you a lower risk, and
lower risks are what get invested in. Staircase is a machine for becoming
legibly reliable without faking linearity.

### The nonlinear builder's problem

Real building is nonlinear. Three days go into machinery that shows nothing;
then nine wins land in one afternoon. Meanwhile the people you report to
answer upward on their own weekly cycle, and they need a number they can
relay with confidence. That need is a **legitimate constraint of their job**,
not a comprehension failure.

The occupational injury of the nonlinear builder is being read as stalled on
machine days and lucky on burst days — and slowly learning to distort their
own work rhythm to look linear. The usual fixes are bad: burst-day dumps that
train stakeholders to expect every day to be a burst, or narrative padding on
quiet days that erodes trust.

Staircase is the third option: **an interface between two valid ways of
working.** Produce in bursts; bank each win the moment it is verified;
release a steady, honest cadence; and keep every event — production and
release both — in an append-only ledger any stakeholder can open at any
time. The staircase shape is not a performance. It is a rendering, the way a
chart is a rendering of a table, and the table is always one click away.

## How it works

```
bursty production ──▶ wins.jsonl ──▶ [verified buffer] ──▶ releases.jsonl ──▶ report
     (proof-gated,      (append-only,      (FIFO)             (cadence N/day,     (rendered from
      nonlinear)         never backdated)                      ledgered)           ledgers ONLY,
                                                                                   lint-gated)
```

- **`log-win`** appends a verified win — proof required, timestamp taken at
  occurrence, backdating structurally refused.
- **`release`** draws the N oldest banked wins and ledgers the announcement.
- **`report`** renders the stakeholder report from the ledgers only. There
  is no input through which a hand-authored number can enter.
- **`lint`** is the send-gate: every number must replay from the ledgers,
  the drill-down pointer must be present, retired vocabulary is refused,
  and a stale marker (report older than the ledgers) fails.

## The `.staircase/` folder

Every project gets one — `.git` for history, `.staircase` for
**expectations**. This convention is the product; the CLI is its steward.

```
.staircase/
  config.yml        the SLA: cadence, slots, stakeholders, proof adapters,
                    texture policy, lint vocabulary additions
  expectations.md   THE EXPECTATIONS RECORD: what was promised to whom and
                    when; cadence-change history (explicit, dated,
                    owner-signed — never silent); definitions of done
  wins.jsonl        production ledger
  releases.jsonl    release ledger
  plans.jsonl       named-in-advance commitments + MISS events
  steering.jsonl    manager ledger — every Staircase Manager pass, drift
                    and on-track alike (silence is logged too)
  stakeholders/     persona files + objections.yml (asked/answered/preempted)
  reports/          rendered report archive (derived)
```

`expectations.md` is the anti-ratcheting instrument: when anyone says "but I
thought you were doing 10 a day," you open one file and read the dated,
owner-signed history of every cadence agreement.

## Guardrails — features, not fine print

1. **Internal truth first.** `staircase status` is the operator's primary
   dashboard. A buffer below the daily cadence is a loud ALARM (and
   `--check` exits non-zero for cron gating). The steady external cadence is
   only honest while the operator sees the real curve daily.
2. **Anti-over-smoothing.** The release cadence keeps honest texture. A
   strong day reads "7 — cadence of 5 met, plus 2 beyond (a strong
   production day)." A short day reads "3 of 5 — the buffer ran short; the
   gap is visible here, not smoothed away." Perfect flatness would itself
   be a distortion.
3. **Drill-down always one click away.** Every report ends with the "Full
   ledger" pointer; `lint` refuses a report without it.
4. **Expectation changes are explicit.** Raising or lowering the daily
   cadence happens only through `staircase set-quota N --reason ... --by ...`,
   which writes a dated, owner-signed line into `expectations.md`. A cadence
   edited by hand with no matching entry fails **every** command closed.

## Time awareness — in whose zone, and how long is left

The agent doing the work and the stakeholder reading the report are often
in **different timezones** (a build agent on a rented box in one region; a
manager in Dallas). A deadline like "the 18:00 report" is only meaningful in
the *stakeholder's* zone — so staircase interprets every slot wall-clock in
`stakeholder_tz`, computes the remaining time in absolute UTC, and renders it
in both zones. `init` auto-detects the machine's zone as `operator_tz`; set
`--stakeholder-tz` (and `--deadline HH:MM`) to where the report is read:

```
staircase init --cadence 5 --by <owner> --stakeholder-tz America/Chicago --deadline 18:00
```

Every `agent-brief` and `status` then carries a CLOCK line:

```
CLOCK: now 2026-07-02 13:42 CDT (stakeholder) / 2026-07-02 11:42 PDT (here, -2h)
       · deadline 2026-07-02 18:00 CDT = 2026-07-02 16:00 PDT here
       · 4h17m to deadline · 1 promise(s) open (0 banked→release-only,
       1 need production) · pace: OK
```

The pace verdict distinguishes promises that are **banked** (won but
unreleased — a release is seconds) from those that still **need production**
(real time), so the Manager's TIME domain can say the useful thing —
`CRITICAL` / `TIGHT` when unbuilt promises are running out of clock,
`RELEASE_NOW` when only releases remain and the slot is closing,
`PAST_DEADLINE` (a loud alarm) when the slot passed with work open. The full
block ships in `agent-brief --json` and the manager-check packet under
`time`; config keys are `operator_tz`, `stakeholder_tz`, `deadline_local`,
`morning_local`. Timezones use stdlib `zoneinfo` — still zero-dependency.

## Under pressure, bisect — half-done visibility

The same instinct that made SEALs count breaths and made elephant carpaccio
slice the impossible thin applies hardest at the deadline. When a promise
won't fit the clock, the move is **not** to push harder on the whole — it is
to **bisect it** so a smaller piece can *land and be shown* now:

```
staircase split row-46 --into row-46-tied-in-gold row-46-rendered-live
```

The parent is superseded (neither kept nor slipped — decomposed); the halves
become the scope and inherit the parent's acceptance criteria. Ship the first
half, show it, then carry or split the rest. **If a half still won't fit the
clock, split it again** — recurse until a piece fits. Visible partial progress
beats an all-or-nothing miss, and it keeps the stakeholder seeing motion.

Staircase pushes this for you: when the clock is `TIGHT`/`CRITICAL` with
unbuilt promises, the deadline alarm in `status`, the brief, and the Manager's
TIME domain all carry the SPLIT directive with the exact command. Pressure is
the signal to make the work smaller, not to hide the risk.

## Agents work under the same contract

A repo with `.staircase/` keeps agents accountable too. The plugin ships a
SessionStart hook that runs **`staircase agent-brief`** — one command, full
orientation: current SLA, today's named scope, buffer + alarms, this
project's definition of done, unresolved stakeholder objections. The binding
rules live in the plugin's skill: the day's plan is the scope; scope grows
only through `staircase plan`; "done" means the proof gate passed and the
win is ledgered — an agent may never claim completion otherwise; slips are
MISS-logged early (`staircase miss <id> --why "..."`), and a Stop hook warns
(never blocks) when plan items end a session unaccounted. One promise
ledger, both species.

## The Staircase Manager — a steering subagent

Day two of agent accountability: not just briefing the agent, but
**watching it work**. The bundled `staircase-manager` agent
(`agents/staircase-manager.md`) is spawned periodically inside a working
session; it infers REAL progress from footprints — ledgers, git log, file
mtimes, an optional transcript tail — never the parent's claims, and sends
back ONE evidence-cited steering message only when drift is detected
across its five watch-domains: **SCOPE** (work vs plans.jsonl), **TIME**
(an item at 3× its box: split or MISS now), **PROMISES** (defend the
named-vs-delivered ratio), **BUDGET** (token burn vs ledger progress),
**ALTITUDE** (activity serving no plan item and no mission-relevant
unlock is busywork; a mission-obsolete plan item is steered to a
MISS-with-reason, not ground out). All green → the single word
`ON-TRACK`.

The division of labor is strict: **evidence gathering is deterministic**
(`staircase manager-check` assembles the packet — agent-brief, last-N
ledger events, plan ages, git log since morning, optional transcript
tail), **judgment lives in the agent**, and every pass — steering or
silence — is appended to `.staircase/steering.jsonl` via `staircase
steer-log` (the proven-attention rule). The manager's tools are read-only
plus that one sanctioned write; `staircase_release` is denied in its
frontmatter — releasing stays the owner's prerogative.

Spawning: the parent (or a wakeup/Stop hook) spawns the agent with the
manager-check packet; background managers deliver steering via SendMessage
to the main session. A steering message is an input the parent must **act
on or explicitly rebut** in its next message — never silently ignore.
An optional Stop-hook nudge ships default-OFF: export
`STAIRCASE_MANAGER_NUDGE=1` to enable it (see the skill for details).

## Promises come first

Everything in Staircase serves one thing: **keeping the promises you named in
advance.** Cadence, buffer, and streak are instruments in service of that —
none of them ever outranks a promise at risk. The brief, the status
dashboard, and the Manager subagent all lead with the open promises and the
time left on them, and all carry the same instruction: **work backwards from
each promise** — name what must be true for it to land, then do exactly that
until it is kept or honestly MISS-logged. A dropped promise is the only true
failure; a thin buffer or a missed cadence is survivable and honestly
reported. This is the discipline the whole tool exists to enforce.

## What a promise is (and how it's proven)

A promise in Staircase is not just an id in a list. It has three parts, and
an independent auditor checks all three:

1. **What is promised** — a named id in `plans.jsonl` (`row-42-fec-per-lift`).
2. **What it means** — the definition of done, in one line (`--means "FEC
   per lift renders live on the dashboard"`). A promise with no meaning is
   not verifiable, so it is not a real promise.
3. **How it's proven** — an acceptance criterion (`--accept "<command that
   exits 0 iff honored>"`) and a **burden of proof**. The strongest burden,
   and the recommended one, is a **screenshot showing the thing actually
   done** (`burden_of_proof: screenshot` — then `log-win` refuses any proof
   that is not an existing image file).

```
staircase plan row-42-fec-per-lift \
  --means "FEC per lift renders live on the dashboard" \
  --accept "curl -sf https://.../contract | grep -q '\"row\":42.*shipped_at'"
```

### The independent promise auditor

Releasing a promise marks it delivered in the ledger — but the ledger can be
wrong (a row "shipped" that does not actually render). So `staircase audit`
verifies every released promise **independently**, and fails closed:

- **Is the promise logical?** No `means`/`accept` → `ILL_FORMED`. An
  unverifiable promise cannot be kept.
- **Is the burden of proof met?** No win, or a proof that is not a screenshot
  when one is required → `NO_PROOF`.
- **Is it honored?** The `accept` check is run; a non-zero exit → `NOT_HONORED`.

Any released promise that lands on `ILL_FORMED` / `NO_PROOF` / `NOT_HONORED`
makes the audit **fail** — a released-but-unhonored promise is a broken
promise, said loudly. The deterministic checks are the floor; the bundled
**`promise-auditor` subagent** goes further — it opens each screenshot and
confirms the image actually shows the promised thing, because a picture that
doesn't show it is not proof. `staircase lint` treats a failed audit as a
send-gate: you cannot mail a report claiming promises the auditor rejected.

## The 2×2

Staircase manages four squares and their alignment:

|  | |
| --- | --- |
| **The Work** | what you actually do — bursty, nonlinear, often invisible |
| **The Promise** | what you fulfill — named in advance, MISS-logged early, never quietly dropped |
| **The Production** | how you best show progress on work and promises — the steady, ledgered release cadence |
| **The Mission** | what the first three align to — the one-line why, rendered first in every brief |

Work without Promise is noise. Promise without Production is invisible.
Production without Mission is busywork. Staircase keeps all four in one
ledger.

## Install & keep current

```
/plugin marketplace add eidos-agi/staircase
/plugin install staircase@staircase
```

**Self-update:** `/plugin update staircase` (marketplace install), or
`staircase self-update` from a git checkout — a fast-forward pull of the
latest plugin into the installed location, with a version before/after.
Restart the session afterward so the bundled MCP server reloads.

Then in any project:

```
python3 <plugin>/tools/staircase.py init --cadence 5 --by <owner> --stakeholder <name>
```

(or ask Claude: "set up staircase in this repo"). Slash commands:
`/staircase:staircase-status`, `/staircase:staircase-report morning|evening`,
`/staircase:staircase-redteam`. For plugin development, load a checkout
directly: `claude --plugin-dir ./staircase`.

## CLI reference

```
staircase init --cadence N --by OWNER [--stakeholder NAME]... [--mission "..."]
                                       # mission: the one-line why — rendered
                                       # FIRST in every agent brief, before the SLA
staircase log-win <id> --proof <url-or-path> [--note ...] [--gate CMD]
staircase release [--n N]              # FIFO draw; empty buffer = exit 3
staircase plan <id>... [--date D]      # name commitments in advance
staircase miss <id> --why "..." [--new-date D]   # the MISS protocol
staircase status [--check]             # operator dashboard; alarms; exit 4 on alarm with --check
staircase report --slot morning|evening [--date D]
staircase lint <report.md>             # send-gate; exit 1 = do not send
staircase set-quota N --reason "..." --by OWNER
staircase agent-brief                  # one-command orientation for agents
staircase agent-check [--hook]         # session-end plan accounting (warn only)
staircase manager-check [--last N] [--transcript PATH] [--trigger T]
                                       # the Manager's evidence packet (JSON):
                                       # brief + ledger tail + plan ages +
                                       # git log since morning + transcript tail
staircase steer-log --verdict drift|on_track [--message M]
                    [--evidence E]... [--trigger T] [--outcome O]
                                       # ledger one Manager pass in steering.jsonl
                                       # (drift needs message + evidence;
                                       # silence is logged too)
```

Python 3.9+, stdlib only. Tests: `python3 -m unittest discover -s tests`.

`status`, `agent-brief`, `report`, `lint`, `release`, and `log-win` also
take `--json`: a machine-readable twin of the human output — same data,
same ledgers, no extra numbers.

## MCP server — same ledger, same rules

The plugin bundles a stdio MCP server (`tools/mcp_server.py`, auto-registered
via the plugin's `.mcp.json`). It is a **thin wrapper**: every tool shells out
to the CLI above, which keeps all the logic and every fail-closed guardrail.
MCP or CLI — same ledger, same rules; there is no code path through which an
MCP caller can bypass a CLI refusal.

| Tool | Arguments | CLI twin |
| --- | --- | --- |
| `staircase_status` | — | `status --json` |
| `staircase_agent_brief` | — | `agent-brief --json` |
| `staircase_log_win` | `id`, `proof` | `log-win <id> --proof <proof> --json` |
| `staircase_plan` | `ids[]` | `plan <ids...>` |
| `staircase_release` | `n?` | `release [--n N] --json` |
| `staircase_report` | `slot` (morning\|evening) | `report --slot <slot> --json` |
| `staircase_lint` | `path` | `lint <path> --json` |
| `staircase_miss` | `id`, `reason`, `new_date?` | `miss <id> --why <reason> [--new-date D]` |
| `staircase_manager_check` | `last?`, `transcript?`, `trigger?` | `manager-check --json [...]` |
| `staircase_steer_log` | `verdict`, `trigger?`, `message?`, `evidence[]?`, `outcome?` | `steer-log --verdict ... --json` |

**Every tool also accepts an optional `project_dir`** — a validated
absolute path (to the project or any directory inside it) from which
`.staircase/` is discovered by walking upward, exactly like the CLI's
`--dir`. This is the fix for worktrees and multi-repo workspaces, where the
MCP server's cwd is not the staircase project: pass the project's absolute
path per call instead of relying on cwd or `STAIRCASE_DIR`.

The server discovers `.staircase/` exactly as the CLI does — walking up from
the working directory (set `STAIRCASE_DIR` to pin a project root; a
per-call `project_dir` outranks both). Zero dependencies, like the CLI.

### Owner prerogative: `staircase_release`

Releasing speaks to stakeholders — by convention it is an **owner-session
decision**, not a subagent's. The permission system enforces the convention
at the tool level. Plugin-bundled MCP tools are named
`mcp__plugin_<plugin>_<server>__<tool>`, so for this plugin:

```
mcp__plugin_staircase_staircase__staircase_release
```

To keep `release` out of a subagent's hands while leaving status/brief open,
use the agent's `disallowedTools` frontmatter (per-subagent; the main
session keeps the tool):

```yaml
---
name: builder
description: Produces and banks wins; never announces them.
disallowedTools: mcp__plugin_staircase_staircase__staircase_release
---
```

To deny it session-wide (subagents **and** the main session — permission
rules in settings apply to both), use `.claude/settings.json`:

```json
{
  "permissions": {
    "deny": ["mcp__plugin_staircase_staircase__staircase_release"]
  }
}
```

`set-quota` has no MCP tool at all — changing the SLA stays a deliberate,
owner-signed CLI act.

## Proof-event adapters

A win is logged only with proof:

- **manual** — `--proof <any URL or artifact path>`
- **merged PR** — `--proof "$(gh pr view 123 --json url -q .url)"
  --gate "test \"$(gh pr view 123 --json state -q .state)\" = MERGED"`
- **CI green** — `--proof "$(gh run view 88 --json url -q .url)"
  --gate "test \"$(gh run view 88 --json conclusion -q .conclusion)\" = success"`
- **custom gate** — `--gate "<command>"`; non-zero exit refuses the win.

## Customer zero

Staircase generalizes a delivery discipline first built inside a real
data-warehouse proof program: twice-daily executive score reports rendered
exclusively from committed ledgers, gated by a fail-closed report lint,
under a standing "five verified wins a day" mandate. That reference
implementation lives in a private repo and this plugin carries none of its
data — only the discipline. Customer zero is a customer, not the product.

## License

MIT © 2026 Eidos AGI
