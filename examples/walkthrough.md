# Walkthrough — a nonlinear build meets a linear stakeholder

This is the story Staircase was built for, told with a genericized project:
a small team shipping **dashboard tiles** (each tile = one metric rendered on
a live page) to a **VP who reports upward every evening**. The agent doing
the work runs on a box two timezones west of the VP. Every specific below is
a real pattern from Staircase's customer-zero use, with the internals filed
off. Run `bash examples/demo.sh` to watch the CLI produce this.

## The setup

The team promised five tiles today. Production is bursty: three of them fell
out of one good afternoon; two are still fighting a data-plumbing problem
that shows nothing until it suddenly works. The VP doesn't need the drama —
they need a number they can relay at 18:00 **their** time.

```
staircase init --cadence 3 --by lead \
  --stakeholder-tz America/Chicago --deadline 18:00 \
  --mission "every dashboard tile traceable to the query behind it"
```

## 1. A promise is not a bare id

Each tile is planned with a **meaning** and an **acceptance check**, and the
project adopts the screenshot **burden of proof** (`burden_of_proof:
screenshot`): a tile is not done until an image shows it rendering.

```
staircase plan tile-revenue \
  --means "revenue tile renders live on the dashboard" \
  --accept "curl -sf https://dash/api | grep -q '\"tile\":\"revenue\".*live'"
```

Now "done" has a definition a machine can check, and "proof" is a picture,
not a claim.

## 2. The trap: "released" is not "kept"

Here is the exact mistake that motivated the auditor. The three easy tiles
get logged and released — and the ledger cheerfully reports **3 of 5 kept.**
But one of them was marked done off a *proof link*, not a screenshot of the
live page. It reconciled in the warehouse; it never rendered.

`staircase audit` refuses to take the ledger's word:

```
=== PROMISE AUDIT (released) ===
  ✓ tile-revenue: HONORED — accept check exited 0
  ✗ tile-signups: NOT_HONORED — released as kept but the check fails
AUDIT FAILED: 1 promise(s) RELEASED as kept but NOT honored — tile-signups
```

And `status` now says the same thing the auditor does — no more
tool-contradicts-itself:

```
PROMISES: 1 of 2 HONORED (independent audit)
⚠ RELEASED ≠ KEPT: 1 released but NOT audit-honored — tile-signups.
```

**Released is not kept until a screenshot proves it live.** The
`promise-auditor` subagent goes the last mile: it opens each screenshot and
confirms the image actually shows the tile — a picture that doesn't show it
is not proof.

## 3. The clock, in the VP's timezone

The deadline is 18:00 **Chicago**, and the agent is on the west coast. The
CLOCK line does the conversion so nobody miscounts the runway:

```
CLOCK: now 16:30 CDT (stakeholder) / 14:30 PDT (here, -2h)
     · deadline 18:00 CDT = 16:00 PDT here · 1h30m to deadline · pace: OK
```

(Getting this wrong once — "we have ~6 hours" when it was really under four —
is why time-awareness exists.)

## 4. Under pressure, bisect — half-done visibility

Thirty minutes to the deadline and the last tile still isn't live. The move
is **not** to push harder on the whole thing. The tool goes CRITICAL and says
so:

```
DEADLINE CRITICAL: 0h30m to deadline · 1 promise still needs production
  → SPLIT for half-done visibility — bisect each at-risk promise so a smaller
    piece can LAND and be shown before the deadline. If a half still won't fit
    the clock, halve it again.
```

So you bisect:

```
staircase split tile-cohorts \
  --into tile-cohorts-query-tied tile-cohorts-rendered-live
```

The whole is superseded (neither kept nor slipped — decomposed); the first
half ("the query is tied and correct") is *landable now* and shows the VP
real motion, while the second half ("rendered live") is honestly carried. If
even that half won't fit, split again. This is elephant carpaccio at the
deadline — the same instinct as counting breaths in cold water: shrink the
unit until you can win it.

## 5. The evening report tells the truth

`staircase report --slot evening` renders only from the ledgers, and
`staircase lint` refuses to let it go out while the audit has an unhonored
release. The VP gets: what actually shipped, what's honestly half-done, and
what slipped — with the full ledger one click beneath. Nobody had to inflate
a quiet day or hide a burst one, and nobody claimed a tile that isn't on the
screen.

That's the whole point: **be legibly reliable without faking linearity.**
