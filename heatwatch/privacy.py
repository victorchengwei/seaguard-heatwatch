"""Privacy-preserving crew and site views.

Supervisors see risk colours for the crew, never raw health data.
Aggregated reports (site, fleet, region) use small-cell suppression:
any non-zero count below MIN_CELL is shown as "<MIN_CELL" so no single
worker can be identified. Totals are suppressed when a group is too small.

These aggregates are the basis for an anonymous regional heat-health record
that could feed population-level early warning (Department of Health).
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

MIN_CELL = 5
LEVELS = ("GREEN", "AMBER", "RED", "DATA GAP")


def crew_board(levels: dict) -> list:
    """Supervisor board: worker id -> colour only. No HR, no core estimate."""
    return [{"worker": w, "level": lvl} for w, lvl in sorted(levels.items())]


def aggregate(levels: Iterable[str], min_cell: int = MIN_CELL) -> dict:
    """Counts per level with small-cell suppression, for site or regional reports."""
    counts = Counter(levels)
    total = sum(counts.values())
    if total < min_cell:
        return {"total": f"<{min_cell}", "levels": "suppressed (group too small)"}
    out = {}
    for lvl in LEVELS:
        n = counts.get(lvl, 0)
        out[lvl] = f"<{min_cell}" if 0 < n < min_cell else n
    return {"total": total, "levels": out}
