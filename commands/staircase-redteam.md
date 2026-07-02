---
description: Boardroom red-team — read the latest delivery report through each stakeholder persona, ledger their likely objections, and propose preempting edits
allowed-tools: Bash, Read, Edit, Glob
---

Run the boardroom red-team against the latest rendered report:

1. Find the newest report in `.staircase/reports/` and read it.
2. Read every persona file in `.staircase/stakeholders/*.md` (skip
   `objections.yml`).
3. For each persona, in character, ask: what would this person question in
   this report? Which number would they want to see behind? What did they
   ask last time (`objections.yml` history) that this report still leaves
   open? Their cadence needs are legitimate — red-team the report's
   clarity, not their way of working.
4. Append each new objection to `.staircase/stakeholders/objections.yml`
   as a list item under `objections:` with fields `stakeholder`,
   `question`, `status` (use `preempted` if the report already answers it,
   else `asked`), and `date` (today). Never delete or rewrite existing
   entries — it is a ledger.
5. Report back: the objections found, which are already preempted, and, for
   each open one, a concrete proposal — usually a wording change in the
   report template, a line for `expectations.md`, or an item for tomorrow's
   plan. Numbers may never be invented to satisfy an objection; if a number
   is missing, the fix is a ledger query or a new ledgered event.

This is the expectation-learning loop: an objection answered well once
should never surprise the team twice.
