#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Regenerate the national powerflow GeoJSON with the SNAPPED + RECONNECT
# topology and A/B-compare it against the currently deployed data.
#
# Heavy compute (DC+AC Newton-Raphson on all 10 regions) -> intended for the
# pws-160core server, decoupled from the (static) rendering layer.
#
#   pws-160core:  ssh pws-ubuntu-server@100.104.225.55
#
# Usage:
#   bash scripts/regen_powerflow_snapped.sh                 # stage + compare
#   bash scripts/regen_powerflow_snapped.sh --promote       # stage + compare + replace docs/
#
# After review, "promote" replaces docs/data/powerflow/ with the staged output.
# Then commit + push docs/ so GitHub Pages redeploys.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

STAGE="docs/data/powerflow_snapped"
DEPLOYED="docs/data/powerflow"
PROMOTE="no"
[ "${1:-}" = "--promote" ] && PROMOTE="yes"

echo "==> 1/3  Generating snapped+reconnect powerflow into $STAGE (heavy)…"
PYTHONPATH=. python3 scripts/export_powerflow_pages.py \
    --topology snapped --reconnect --output-dir "$STAGE"

echo ""
echo "==> 2/3  A/B comparison (deployed legacy  vs  staged snapped)"
python3 - "$DEPLOYED/summary.json" "$STAGE/summary.json" <<'PY'
import json, sys
old = json.load(open(sys.argv[1]))
new = json.load(open(sys.argv[2]))
hdr = f"{'region':9s} {'n_comp A→B':>14s} {'active A→B':>16s} {'vm_min A→B':>18s} {'dc_va A→B':>26s} synth"
print(hdr); print("-"*len(hdr))
for r in new:
    a, b = old.get(r, {}), new[r]
    def g(d,k): return d.get(k, "?")
    comp = f"{g(a,'n_components')}→{g(b,'n_components')}"
    act  = f"{g(a,'n_active_buses')}/{g(a,'n_buses')}→{g(b,'n_active_buses')}/{g(b,'n_buses')}"
    vm   = f"{g(a,'ac_vm_min')}→{g(b,'ac_vm_min')}"
    dva  = f"[{g(a,'dc_va_min')},{g(a,'dc_va_max')}]→[{g(b,'dc_va_min')},{g(b,'dc_va_max')}]"
    print(f"{r:9s} {comp:>14s} {act:>16s} {vm:>18s} {dva:>26s} {g(b,'n_synthetic_lines')}")
print("\nGoal: n_comp→1, active buses == total, vm_min ≥ ~0.9, |dc_va| ≤ 180.")
PY

echo ""
if [ "$PROMOTE" = "yes" ]; then
    echo "==> 3/3  Promoting staged output to $DEPLOYED"
    # keep a backup of the current deployed data
    ts="$(date +%Y%m%d_%H%M%S 2>/dev/null || echo bak)"
    cp -r "$DEPLOYED" "${DEPLOYED}.legacy_${ts}"
    cp -f "$STAGE"/*.geojson "$STAGE"/*.json "$DEPLOYED"/
    echo "Promoted. Backup at ${DEPLOYED}.legacy_${ts} (gitignored)."
    echo "Next: review docs/ in the map, then  git add docs/data/powerflow && git commit && git push"
else
    echo "==> 3/3  Review only (no promote). To deploy after review:"
    echo "      bash scripts/regen_powerflow_snapped.sh --promote"
fi

echo ""
echo "NOTE: snapped topology currently falls back to straight 2-point lines for"
echo "branches that touch junction buses (geom_lookup is keyed by legacy sub pairs)."
echo "Connectivity & physics are correct; real-route geometry is a follow-up"
echo "(carry line geometry through examples/build_snapped_topology.py)."
