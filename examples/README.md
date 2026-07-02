# Examples

Worked examples of Staircase, drawn from real customer-zero use and
genericized to a team shipping **dashboard tiles** (each tile = one metric
rendered live) to a **VP who reports upward every evening**, with the agent
running two timezones west of the stakeholder.

- **[`demo.sh`](demo.sh)** — a runnable, self-contained walk through the core
  moves. Creates a throwaway `.staircase/` in a temp dir, pins the clock for
  reproducible output, and prints real CLI results. Nothing it does touches a
  real project.

  ```
  bash examples/demo.sh
  ```

- **[`walkthrough.md`](walkthrough.md)** — the narrative behind the demo: a
  nonlinear build meeting a linear stakeholder, and how each Staircase feature
  answers a specific failure — "released ≠ kept," the screenshot burden of
  proof, timezone-correct deadlines, and bisecting under pressure for
  half-done visibility.

## The scenarios, at a glance

| Scenario | Command(s) | What it shows |
| --- | --- | --- |
| A real promise | `plan --means … --accept …` | a promise = id + meaning + acceptance check |
| Screenshot burden | `log-win --proof shot.png` | a URL is refused; proof is a picture of it done |
| Released ≠ kept | `audit --run` | the independent auditor fails closed on a released-but-unhonored promise |
| One honest story | `status` | "kept" means HONORED, matching the audit — never released-as-kept |
| Timezone runway | `status` CLOCK line | deadline in the stakeholder's zone, remaining time in both |
| Bisect under pressure | `split <id> --into <a> <b>` | a stuck promise becomes a landable half + the rest; recurse if needed |

Each maps to a section of the [walkthrough](walkthrough.md) and a step of the
[demo](demo.sh).
