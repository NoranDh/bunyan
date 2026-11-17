"""Allowances: costs outside the BOM that a villa still needs (permits, soil, survey, utilities, fees).

Each allowance has a low and high range; the baseline is the midpoint. The baseline is used
until the owner uploads documents or enters real figures. The ranges come from the contractor
guide cited in estimate.py (May 2026, not verified). Replace them here once the team has
reviewed the figures. Pure functions, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.models import AllowanceLine, CalcStep

SOURCE = "engine/allowances.py (ASSUMPTION — contractor guide, not verified)"


@dataclass(frozen=True)
class _Allowance:
    id: str
    item: str
    basis: str  # "fixed" = SAR, "percent" = share of work packages (excl. VAT)
    low: float
    high: float
    permit_id: str | None  # the permit step this cost belongs to, if any


ALLOWANCES: tuple[_Allowance, ...] = (
    _Allowance("A01", "Building permit and municipal fees (Balady)", "fixed", 15_000, 60_000, "P03"),
    _Allowance("A02", "Geotechnical / soil investigation", "fixed", 8_000, 25_000, "P02"),
    _Allowance("A03", "Topographic survey", "fixed", 3_000, 8_000, None),
    _Allowance("A04", "Utility connections (electricity, water)", "fixed", 20_000, 80_000, "P05"),
    _Allowance("A05", "Design and supervision fees", "percent", 0.04, 0.08, "P01"),
    _Allowance("A06", "Project management", "percent", 0.02, 0.04, None),
)


def _round(value: float) -> int:
    return int(math.floor(value + 0.5))


def allowance_lines(work_packages_total_sar: int) -> list[AllowanceLine]:
    lines: list[AllowanceLine] = []
    for a in ALLOWANCES:
        steps: list[CalcStep] = []
        if a.basis == "percent":
            low = _round(work_packages_total_sar * a.low)
            high = _round(work_packages_total_sar * a.high)
            steps.append(
                CalcStep(
                    label="Basis",
                    formula="work packages total",
                    result=f"{work_packages_total_sar:,} SAR",
                    source="estimate.py",
                )
            )
            steps.append(
                CalcStep(
                    label="Range",
                    formula=f"{a.low:.0%} to {a.high:.0%} × {work_packages_total_sar:,}",
                    result=f"{low:,} to {high:,} SAR",
                    source=SOURCE,
                )
            )
        else:
            low, high = int(a.low), int(a.high)
            steps.append(
                CalcStep(
                    label="Range",
                    formula="fixed range",
                    result=f"{low:,} to {high:,} SAR",
                    source=SOURCE,
                )
            )
        baseline = _round((low + high) / 2)
        steps.append(
            CalcStep(
                label="Baseline",
                formula=f"midpoint of {low:,} and {high:,}",
                result=f"{baseline:,} SAR",
            )
        )
        lines.append(
            AllowanceLine(
                id=a.id,
                item=a.item,
                basis=a.basis,  # type: ignore[arg-type]
                low_sar=low,
                high_sar=high,
                baseline_sar=baseline,
                permit_id=a.permit_id,
                calculation=steps,
            )
        )
    return lines
