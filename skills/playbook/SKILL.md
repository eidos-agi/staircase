---
description: A curated playbook of time-tested mental models for builders — reach for it when facing a judgment call about business, complexity, design, architecture, decision-making, or delivery under pressure (deadline risk, an irreversible choice, a tangle you can't size, an over-engineering temptation, a stakeholder mismatch). Each lens has a trigger and a concrete move, and several wire directly to Staircase's promises / buffer / split / audit mechanics. Use when the question is "how should I think about this?", not "what does this command do?".
---

# The Staircase Playbook

Lenses, not laws. When you are stuck on *how to think* about a problem —
not how to run a command — match your situation to a lens below and take the
move. Each entry is: **Principle** — *when to reach for it* — the move.
Several connect to Staircase's own mechanics; those links are marked `↳`.

The through-line of the whole tool: **be legibly reliable without faking
linearity.** These lenses are how you stay reliable when the work fights back.

## Delivery & complexity

- **Elephant carpaccio** — *a task feels too big to finish or even estimate.*
  Slice it until one slice is shippable **today**. If you can't name a
  piece that lands today, you haven't sliced thin enough. ↳ `staircase
  split`.
- **Count the breaths** (SEAL doctrine for cold water) — *panic/overwhelm
  under a deadline.* Stop solving the whole; do the single next controllable
  unit, then the next. Tempo beats spiral. ↳ the SPLIT directive fires under
  `CRITICAL` time.
- **The bottleneck governs** (Theory of Constraints) — *lots of effort, whole
  not moving.* Find the one constraint; an hour spent anywhere else is
  wasted. Improve the constraint, then re-find it (it moves).
- **Limit work-in-progress** — *many things 80% done, nothing shipped.*
  Finish before you start. WIP is undelivered risk; stop starting, start
  finishing. ↳ the buffer rewards *finished* wins, not started ones.
- **No plan survives contact** — *reality just diverged from the plan.* Plan
  to replan. The plan's value was the thinking, not the document; update it
  out loud (a `staircase plan`/`miss`), never silently.

## Decision-making under uncertainty

- **Two-way vs one-way doors** — *a decision is stalling you.* Reversible?
  Decide in seconds and move — you can undo it. Irreversible/expensive to
  undo? Slow down, get more eyes. Most decisions are two-way doors treated as
  one-way. ↳ Staircase proceeds on reversible acts, confirms irreversible
  ones.
- **OODA loop** (Boyd) — *a fast-changing or adversarial situation.* Observe,
  orient, decide, act — and shorten the loop. The one who re-orients fastest,
  not the one with the best single plan, wins.
- **Premortem** — *about to commit to something big.* Assume it's six months
  later and it failed. What killed it? Fix that now, before you commit.
- **Satisfice, don't maximize** — *deciding with scarce information.* Pick the
  first option that clears the bar and move; the info to choose "optimally"
  usually arrives only after you act. Good-now beats perfect-late.
- **Disagree and commit** — *decision made, you'd have chosen otherwise.* Say
  your piece once, on the record, then row hard in the chosen direction. A
  team that re-litigates every call has no tempo.

## Design & architecture

- **Make it work, make it right, make it fast** — *unsure what to optimize.*
  In that order. A fast wrong answer and a beautiful unshipped one are both
  worth zero. Correctness first, then clarity, then speed — never reordered.
- **YAGNI / last responsible moment** — *tempted to build for a future you
  imagine.* Defer the commitment until the cost of deciding late exceeds the
  cost of deciding wrong. Most speculative generality is never used.
- **Chesterton's fence** — *about to delete/replace something whose purpose
  is unclear.* Don't remove it until you understand why it's there. The
  reason is often load-bearing and invisible. ↳ "look at the target before
  you overwrite it."
- **Conway's Law** — *the architecture keeps fighting you.* Systems mirror the
  communication structure that built them. If two modules must not couple,
  the two teams must not need to talk constantly — fix the org, not just the
  code.
- **Sacrificial architecture** — *designing v1 under uncertainty.* Build the
  version you intend to replace. Plan to throw one away — you will anyway;
  deciding so up front keeps you from over-investing in the disposable.

## Business & stakeholders

- **Sell the hole, not the drill** — *reporting or scoping work.* The
  stakeholder buys the outcome, not your activity. Frame and define promises
  as the result they can see, never the effort you spent. ↳ a promise's
  `--means` is an outcome ("renders live"), not a task.
- **A verified buffer, honestly** — *tempted to hide bursts or pad quiet
  days.* Under-promise and over-deliver — but never with a hidden buffer.
  Bank real wins, release a steady honest cadence, keep the ledger open. ↳
  the whole Staircase buffer.
- **Reliability compounds** — *choosing between a heroic burst and steady
  delivery.* Consistent small gains beat sporadic big ones, because
  reliability is what gets invested in — a low-risk collaborator is a
  fundable one. Boring and dependable wins the long game.
- **Manage expectations before managing work** — *a stakeholder mismatch.*
  Most "delivery problems" are expectation problems. Realign the promise (in
  writing, dated) before you sprint on the work. ↳ `expectations.md`.

## Military / mission command

- **Commander's intent** — *delegating, or the plan just broke.* State the
  *why* and the end-state, not just the steps, so people (and agents) can
  adapt correctly when the steps stop applying. ↳ the mission line, rendered
  first in every brief.
- **Schwerpunkt** (point of main effort) — *resources spread across many
  fronts.* Concentrate force at the one decisive point; a thin push
  everywhere breaks through nowhere. Pick the Schwerpunkt and starve the rest
  today.
- **Slow is smooth, smooth is fast** — *rushing and making errors.* Deliberate
  beats frantic; the rework from haste is slower than doing it once, calmly.
- **Reconnaissance before commitment** — *about to spend a lot on an
  unknown.* Scout cheaply first — a query, a spike, a one-day probe — before
  you commit the expensive force. ↳ "tie it locally first" before the costly
  build.

---
*These are starting points, not scripture. When a situation doesn't fit a
lens, reason from first principles — and if you find a durable lens this list
is missing, add it.*
