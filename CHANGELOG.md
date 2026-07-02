# Changelog

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
