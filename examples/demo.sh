#!/usr/bin/env bash
# demo.sh — a self-contained walk through Staircase's core moves, using a
# genericized "ship dashboard tiles to a live page" project. Runnable from a
# checkout; creates a throwaway .staircase/ in a temp dir and prints real CLI
# output. Time is pinned (STAIRCASE_NOW) so the deadline math is reproducible.
#
#   bash examples/demo.sh
#
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SC="python3 $HERE/tools/staircase.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
say() { printf '\n\033[1m# %s\033[0m\n' "$*"; }

# The operator (agent/machine) is on the US west coast; the stakeholder — the
# person who reads the report — is in Chicago. Deadline is 18:00 THEIR time.
export STAIRCASE_NOW="2026-05-04T21:30:00Z"   # 16:30 CDT / 14:30 PDT

say "1. init — cadence 3/day, stakeholder in Chicago, 18:00 deadline"
$SC --dir "$TMP" init --cadence 3 --by lead \
    --stakeholder-tz America/Chicago --deadline 18:00 \
    --mission "every dashboard tile traceable to the query behind it"
# adopt the screenshot burden of proof: a tile is not done until an image
# shows it rendering
python3 - "$TMP/.staircase/config.yml" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); t = p.read_text()
p.write_text(t.replace("burden_of_proof: artifact", "burden_of_proof: screenshot"))
PY

say "2. plan two promises WITH a definition of done + acceptance check"
$SC --dir "$TMP" plan tile-revenue \
    --means "revenue tile renders live on the dashboard" \
    --accept "true"    # in reality: a curl|grep against the live page
$SC --dir "$TMP" plan tile-signups \
    --means "signups tile renders live on the dashboard" \
    --accept "false"   # pretend this one is NOT actually live yet
# a third promise we will NOT get to in time — the one we bisect under pressure
$SC --dir "$TMP" plan tile-cohorts \
    --means "cohort-retention tile renders live on the dashboard"

say "3. a win needs a SCREENSHOT — a URL is refused"
$SC --dir "$TMP" log-win tile-revenue --proof "https://example.com/proof" \
    || echo "(refused, as it should be — the burden is a screenshot)"

say "4. log both wins with real image files, then release them"
printf '\x89PNG\r\n\x1a\n' > "$TMP/revenue.png"
printf '\x89PNG\r\n\x1a\n' > "$TMP/signups.png"
$SC --dir "$TMP" log-win tile-revenue --proof "$TMP/revenue.png"
$SC --dir "$TMP" log-win tile-signups --proof "$TMP/signups.png"
$SC --dir "$TMP" release --n 2

say "5. the INDEPENDENT auditor — released is not kept until it verifies"
# tile-revenue's accept passes; tile-signups' accept fails -> released but
# NOT honored. The audit fails closed and names the broken promise.
$SC --dir "$TMP" audit --run || echo "(audit exited non-zero — a released promise is not honored)"

say "6. status tells the SAME story (HONORED, not merely released)"
$SC --dir "$TMP" status | sed -n '2,5p'

say "7. deadline pressure: the clock goes CRITICAL and the tool says SPLIT"
# jump to 30 min before the Chicago deadline; tile-cohorts is unbuilt
export STAIRCASE_NOW="2026-05-04T22:30:00Z"   # 17:30 CDT, 30 min left
$SC --dir "$TMP" status | grep -iE "DEADLINE|SPLIT" | head -2

say "8. bisect the stuck promise into a landable half + the rest"
$SC --dir "$TMP" split tile-cohorts \
    --into tile-cohorts-query-tied tile-cohorts-rendered-live
say "   the monolith is superseded; the first half is landable NOW"
$SC --dir "$TMP" agent-brief | grep -iE "STILL OPEN" | head -1

echo
echo "Done. Nothing here touched a real project — it all lived in $TMP."
