---
description: "Render today's stakeholder delivery report from the ledgers, then lint it (send-gate). Argument: morning or evening."
allowed-tools: Bash
---

Slot requested: "$ARGUMENTS" (default to `morning` before midday UTC,
`evening` otherwise, if not given).

1. Render the report — it is generated from the `.staircase/` ledgers only;
   never author or adjust a number by hand:

```
python3 "${CLAUDE_PLUGIN_ROOT}/tools/staircase.py" report --slot <morning|evening>
```

2. Immediately run the send-gate on the file it wrote
   (`.staircase/reports/<date>-<slot>.md`):

```
python3 "${CLAUDE_PLUGIN_ROOT}/tools/staircase.py" lint .staircase/reports/<date>-<slot>.md
```

3. If lint PASSES, show the report body to the user and note it is ready to
   send. If lint FAILS, show the violations and do NOT present the report
   as sendable — fix by re-rendering (stale marker), releasing/logging via
   the CLI (numbers), or rewording (retired vocabulary). Never edit the
   numbers in the rendered file: the fix is always upstream in the ledgers.
