"""Quantities and cost for a villa. Pure functions, no I/O.

Pipeline:
1. quantity per BOM line = qty_per_m2_bua × BUA × modifiers, rounded to sensible units
2. amount = quantity × rate (an override rate wins)
3. work-package budget = Σ(material × work-package share) × labor factor × escalation
4. contingency 10%, VAT 15%, totals, allowances, proposed budget, cost per m²

Each step is also recorded as a CalcStep so the UI can show how every number was reached.
"""

from __future__ import annotations

import math

from app.engine.allowances import allowance_lines
from app.engine.reference import REFERENCE_BOM, WORK_PACKAGES, RefLine
from app.models import BOMLine, CalcStep, Estimate, ProjectInput, WorkPackageBudget

# ---- Reference geometry: the seed villa this BOM was built for -------------
REFERENCE_BUA_M2 = 600
REFERENCE_PLOT_M2 = 500
REFERENCE_FLOORS = 2  # ground + first; the roof annex is inside the BUA ratios
REFERENCE_FOOTPRINT_M2 = REFERENCE_BUA_M2 / REFERENCE_FLOORS  # 300
REFERENCE_YARD_M2 = REFERENCE_PLOT_M2 - REFERENCE_FOOTPRINT_M2  # 200

CONTINGENCY_PCT = 0.10
VAT_PCT = 0.15

# Units that are measured continuously (rounded to 0.1). Everything else is
# counted in whole pieces, bags, sets, lots and so on, and rounded up.
CONTINUOUS_UNITS = frozenset({"m³", "t", "m²", "m"})

# Every number in this dict is an assumption to validate with engineers.
MODIFIERS: dict[str, object] = {
    # ASSUMPTION — validate with engineers. Scales architectural *rates* only.
    "finish_rate_factor": {"economy": 0.8, "standard": 1.0, "premium": 1.4},
    # ASSUMPTION — validate with engineers. Basement adds below-grade work.
    "basement_qty_factor": {"M07": 1.40, "M01": 1.25, "M02": 1.20},
    # ASSUMPTION — validate with engineers. Items driven by plot minus footprint.
    # Measured items scale their quantity; lump-sum items (lot) scale their rate.
    "plot_driven_ids": frozenset({"M34", "M35", "M36"}),
}

# Labor factors = work-package budget ÷ work-package materials at the reference.
# Calibrated once from seed/work_packages.json and seed/bom_reference_600m2.csv
# (tests/test_engine.py re-derives them). Stored at full precision so the
# reference reproduces the seed budgets exactly.
LABOR_FACTORS: dict[str, float] = {
    "WP1_site_foundations": 2.4164317358034637,
    "WP2_structure": 1.5464415735043011,
    "WP3_mep": 1.4410705095213587,
    "WP4_finishes": 1.5714104676213407,
    "WP5_external": 2.150537634408602,
}

_REF_BY_ID: dict[str, RefLine] = {line.id: line for line in REFERENCE_BOM}
_BOM_SOURCE = "seed/bom_reference_600m2.csv"


def sar_round(value: float) -> int:
    """Round half up to an integer SAR amount (avoids banker's rounding)."""
    return int(math.floor(value + 0.5))


def _round_qty(unit: str, qty: float) -> float:
    if unit in CONTINUOUS_UNITS:
        return round(qty, 1)
    # Round up to a whole unit; the 0.05 tolerance absorbs float noise such as 14500.002.
    return float(math.ceil(qty - 0.05))


def plot_scale(inp: ProjectInput) -> float:
    """Yard (plot minus footprint) relative to the reference villa. 1.0 at the reference."""
    footprint = inp.built_up_area_m2 / inp.floors
    yard = inp.plot_area_m2 - footprint
    if yard <= 0:
        raise ValueError(
            f"Footprint {footprint:.0f} m² (BUA ÷ floors) does not fit on a "
            f"{inp.plot_area_m2} m² plot. Increase floors or reduce BUA."
        )
    return yard / REFERENCE_YARD_M2


def escalation_years(end_month: int, duration_months: int) -> int:
    """Full years of price rise before a work package ends.

    Projects of 12 months or less are priced at today's rates. Longer projects
    escalate work that ends after month 12 (one step per year completed).
    """
    if duration_months <= 12:
        return 0
    return (end_month - 1) // 12


def _end_month(months: str) -> int:
    # Work-package windows are written "start-end", for example "12-14".
    return int(months.split("-")[-1])


def _line(ref: RefLine, inp: ProjectInput, yard_ratio: float) -> BOMLine:
    finish_factor = MODIFIERS["finish_rate_factor"][inp.finish_level]  # type: ignore[index]
    basement = MODIFIERS["basement_qty_factor"]  # type: ignore[assignment]
    plot_ids = MODIFIERS["plot_driven_ids"]  # type: ignore[assignment]
    unit = ref.unit
    steps: list[CalcStep] = []

    # ---- quantity
    qty = ref.qty_per_m2_bua * inp.built_up_area_m2
    steps.append(
        CalcStep(
            label="Quantity before adjustments",
            formula=f"{ref.qty_per_m2_bua:g} per m² × {inp.built_up_area_m2} m² BUA",
            result=f"{qty:,.3f} {unit}",
            source=_BOM_SOURCE,
        )
    )
    if inp.has_basement and ref.id in basement:  # type: ignore[operator]
        factor = basement[ref.id]  # type: ignore[index]
        qty *= factor
        steps.append(
            CalcStep(
                label="Basement",
                formula=f"× {factor}",
                result=f"{qty:,.3f} {unit}",
                source="MODIFIERS (ASSUMPTION)",
            )
        )

    lot_scale = 1.0
    if ref.id in plot_ids:  # type: ignore[operator]
        if ref.unit == "lot":
            lot_scale = yard_ratio  # lump sums scale with the yard, applied to the rate below
        else:
            qty *= yard_ratio  # measured items scale with the yard
            steps.append(
                CalcStep(
                    label="Yard scale",
                    formula=f"× {yard_ratio:.3f} (yard ÷ {REFERENCE_YARD_M2:.0f} m² reference)",
                    result=f"{qty:,.3f} {unit}",
                    source="MODIFIERS (ASSUMPTION)",
                )
            )

    qty = _round_qty(ref.unit, qty)
    rule = "to 0.1" if unit in CONTINUOUS_UNITS else "up to whole units"
    steps.append(CalcStep(label="Rounded quantity", formula=f"round {rule}", result=f"{qty:,} {unit}"))

    # ---- rate
    override = inp.rate_overrides.get(ref.id)
    if override is not None:
        rate = float(override)
        overridden = True
        steps.append(
            CalcStep(
                label="Rate",
                formula="user override",
                result=f"{rate:g} SAR per {unit}",
                source="rate_overrides input",
            )
        )
    else:
        rate = ref.rate_sar
        overridden = False
        steps.append(
            CalcStep(
                label="Reference rate",
                formula=f"{ref.rate_sar:g} SAR per {unit}",
                result=f"{rate:g} SAR per {unit}",
                source=_BOM_SOURCE,
            )
        )
        if ref.category == "architectural":
            rate *= finish_factor
            steps.append(
                CalcStep(
                    label="Finish",
                    formula=f"× {finish_factor} ({inp.finish_level})",
                    result=f"{rate:g} SAR per {unit}",
                    source="MODIFIERS (ASSUMPTION)",
                )
            )
        if lot_scale != 1.0:
            rate *= lot_scale
            steps.append(
                CalcStep(
                    label="Yard scale (lump sum)",
                    formula=f"× {lot_scale:.3f}",
                    result=f"{rate:g} SAR per {unit}",
                    source="MODIFIERS (ASSUMPTION)",
                )
            )

    amount = sar_round(qty * rate)
    steps.append(
        CalcStep(label="Amount", formula=f"{qty:,} × {rate:g} SAR", result=f"{amount:,} SAR")
    )
    return BOMLine(
        id=ref.id,
        category=ref.category,
        item=ref.item,
        unit=unit,
        qty=qty,
        rate_sar=round(rate, 2),
        amount_sar=amount,
        rate_overridden=overridden,
        work_package_split=dict(ref.wp_split),
        calculation=steps,
    )


def _work_package(wp_id: str, name: str, months: str, materials: int, inp: ProjectInput) -> WorkPackageBudget:
    labor = LABOR_FACTORS[wp_id]
    base = sar_round(materials * labor)
    years = escalation_years(_end_month(months), inp.duration_months)
    budget = sar_round(materials * labor * (1 + inp.annual_inflation_pct) ** years)
    steps = [
        CalcStep(
            label="Materials",
            formula="Σ BOM amounts × this package's share",
            result=f"{materials:,} SAR",
            source="bom_lines",
        ),
        CalcStep(
            label="Base budget",
            formula=f"{materials:,} × labor factor {labor:.4f}",
            result=f"{base:,} SAR",
            source="LABOR_FACTORS, calibrated from seed/work_packages.json",
        ),
    ]
    if years:
        steps.append(
            CalcStep(
                label="Escalation",
                formula=f"× (1 + {inp.annual_inflation_pct:.1%})^{years}, ends in month {_end_month(months)}",
                result=f"+{budget - base:,} SAR",
                source="ASSUMPTION — validate with the market",
            )
        )
    steps.append(
        CalcStep(label="Budget", formula="base budget × escalation", result=f"{budget:,} SAR")
    )
    return WorkPackageBudget(
        id=wp_id,
        name=name,
        months=months,
        materials_sar=materials,
        labor_factor=labor,
        budget_sar=budget,
        escalation_years=years,
        escalation_sar=budget - base,
        calculation=steps,
    )


def _assumptions(inp: ProjectInput, yard_ratio: float, wp_budgets: list[WorkPackageBudget]) -> list[str]:
    notes = [
        "Quantities are reference ratios × BUA (seed/bom_reference_600m2.csv).",
        "Labor factors calibrated once from the reference work-package budgets.",
        f"Contingency {CONTINGENCY_PCT:.0%} of work packages; VAT {VAT_PCT:.0%} shown separately.",
        "Rates are SAR excluding VAT and are indicative, not supplier quotes.",
        "Allowances (permits, soil, survey, utilities, design and PM) are added to the proposed "
        "budget at baseline midpoints and carry no VAT (ASSUMPTION). See engine/allowances.py. "
        "Not included: swimming pool, landscaping beyond the yard items, and furniture, fittings "
        "and equipment.",
    ]
    footprint = inp.built_up_area_m2 / inp.floors
    notes.append(
        f"Footprint = BUA ÷ floors = {footprint:.0f} m²; yard = {inp.plot_area_m2 - footprint:.0f} m² "
        f"(reference {REFERENCE_YARD_M2:.0f} m²) — drives paving, boundary and landscape."
    )
    if any(wp.escalation_years for wp in wp_budgets):
        escalated = sum(wp.escalation_sar for wp in wp_budgets)
        notes.append(
            f"Price escalation {inp.annual_inflation_pct:.1%} a year on work packages that end after "
            f"month 12 (duration {inp.duration_months} months): +{escalated:,} SAR "
            "(ASSUMPTION — validate with the market)."
        )
    if inp.finish_level != "standard":
        notes.append(
            f"Finish '{inp.finish_level}' scales architectural rates by "
            f"{MODIFIERS['finish_rate_factor'][inp.finish_level]} "  # type: ignore[index]
            "(ASSUMPTION — validate with engineers)."
        )
    if inp.has_basement:
        notes.append(
            "Basement: +40% below-grade waterproofing, +25% concrete, +20% steel "
            "(ASSUMPTION — validate with engineers). Excavation and retaining are not yet modelled."
        )
    if not inp.has_roof_annex:
        notes.append(
            "has_roof_annex=false is recorded but no quantity change is applied yet "
            "(ASSUMPTION — to be modelled with engineers)."
        )
    if inp.rate_overrides:
        notes.append(f"Rate overrides applied to: {', '.join(sorted(inp.rate_overrides))}.")
    return notes


def estimate(inp: ProjectInput) -> Estimate:
    """Compute the full estimate for a project. Deterministic: same input, same output."""
    unknown = set(inp.rate_overrides) - set(_REF_BY_ID)
    if unknown:
        raise ValueError(f"Unknown BOM line id(s) in rate_overrides: {sorted(unknown)}")

    yard_ratio = plot_scale(inp)
    lines = [_line(ref, inp, yard_ratio) for ref in REFERENCE_BOM]

    materials_total = sum(line.amount_sar for line in lines)

    # Allocate each line's amount to work packages by its share, then add labor.
    materials_by_wp: dict[str, float] = {wp.id: 0.0 for wp in WORK_PACKAGES}
    for line in lines:
        for wp_id, share in line.work_package_split.items():
            materials_by_wp[wp_id] += line.amount_sar * share

    wp_budgets = [
        _work_package(wp.id, wp.name, wp.months, sar_round(materials_by_wp[wp.id]), inp)
        for wp in WORK_PACKAGES
    ]

    wp_total = sum(wp.budget_sar for wp in wp_budgets)
    contingency = sar_round(wp_total * CONTINGENCY_PCT)
    subtotal = wp_total + contingency
    vat = sar_round(subtotal * VAT_PCT)
    total = subtotal + vat

    allowances = allowance_lines(wp_total)
    allowances_total = sum(a.baseline_sar for a in allowances)
    proposed = total + allowances_total

    totals_steps = [
        CalcStep(label="Work packages", formula="Σ five package budgets", result=f"{wp_total:,} SAR"),
        CalcStep(
            label="Contingency",
            formula=f"{CONTINGENCY_PCT:.0%} × {wp_total:,}",
            result=f"{contingency:,} SAR",
            source="estimate.py",
        ),
        CalcStep(
            label="Subtotal excl. VAT",
            formula=f"{wp_total:,} + {contingency:,}",
            result=f"{subtotal:,} SAR",
        ),
        CalcStep(
            label="VAT",
            formula=f"{VAT_PCT:.0%} × {subtotal:,}",
            result=f"{vat:,} SAR",
            source="estimate.py",
        ),
        CalcStep(label="Total incl. VAT", formula=f"{subtotal:,} + {vat:,}", result=f"{total:,} SAR"),
        CalcStep(
            label="Allowances",
            formula="Σ allowance baselines",
            result=f"{allowances_total:,} SAR",
            source="engine/allowances.py",
        ),
        CalcStep(
            label="Proposed budget",
            formula=f"{total:,} + {allowances_total:,}",
            result=f"{proposed:,} SAR",
        ),
    ]

    return Estimate(
        project=inp,
        bom_lines=lines,
        work_packages=wp_budgets,
        materials_total_sar=materials_total,
        work_packages_total_sar=wp_total,
        contingency_pct=CONTINGENCY_PCT,
        contingency_sar=contingency,
        subtotal_excl_vat_sar=subtotal,
        vat_pct=VAT_PCT,
        vat_sar=vat,
        total_incl_vat_sar=total,
        cost_per_m2_excl_vat_sar=sar_round(subtotal / inp.built_up_area_m2),
        allowances=allowances,
        allowances_total_sar=allowances_total,
        proposed_budget_sar=proposed,
        totals_calculation=totals_steps,
        assumptions=_assumptions(inp, yard_ratio, wp_budgets),
    )
