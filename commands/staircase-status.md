---
description: Operator dashboard — Staircase buffer level, streak, alarms, promise-kept ratio (the internal truth)
allowed-tools: Bash
---

Run the Staircase operator dashboard from the project root:

```
python3 "${CLAUDE_PLUGIN_ROOT}/tools/staircase.py" status
```

Relay the output faithfully. If any ALARM line appears, lead with it — the
internal dashboard exists so the operator sees trouble before a stakeholder
does. A buffer below the daily cadence means production must outrank polish
today; a cadence-consistency alarm means an expectation was changed without
an owner-signed entry in `.staircase/expectations.md` (fix with
`staircase set-quota N --reason ... --by ...`).

If no `.staircase/` folder is found, offer to scaffold one:
`python3 "${CLAUDE_PLUGIN_ROOT}/tools/staircase.py" init --cadence 5 --by <owner> --stakeholder <name>`.
