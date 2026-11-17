"""Calculation breakdowns: every step table must end at the number the engine returns."""

from __future__ import annotations

from app.engine.estimate import estimate
from app.models import ProjectInput

REF = ProjectInput(built_up_area_m2=600, plot_area_m2=500, floors=2, finish_level="standard")


def _line(est, line_id: str):
    return next(line for line in est.bom_lines if line.id == line_id)


def test_every_bom_line_ends_at_its_amount() -> None:
    est = estimate(REF)
    for line in est.bom_lines:
        assert line.calculation, line.id
        assert line.calculation[-1].label == "Amount"
        assert line.calculation[-1].result == f"{line.amount_sar:,} SAR", line.id


def test_concrete_line_shows_the_reference_ratio_and_rate() -> None:
    steps = _line(estimate(REF), "M01").calculation
    assert steps[0].formula == "0.51667 per m² × 600 m² BUA"
    assert steps[1].label == "Rounded quantity"
    assert steps[-1].result == "99,200 SAR"  # 310.0 m³ × 320 SAR


def test_basement_adds_a_step_only_when_it_applies() -> None:
    basement = estimate(REF.model_copy(update={"has_basement": True}))
    assert any(s.label == "Basement" for s in _line(basement, "M01").calculation)
    assert not any(s.label == "Basement" for s in _line(estimate(REF), "M01").calculation)


def test_override_is_recorded_as_the_rate_source() -> None:
    est = estimate(REF.model_copy(update={"rate_overrides": {"M02": 4000}}))
    rate_step = next(s for s in _line(est, "M02").calculation if s.label == "Rate")
    assert rate_step.formula == "user override"
    assert rate_step.source == "rate_overrides input"


def test_finish_factor_shows_for_architectural_lines_only() -> None:
    premium = estimate(REF.model_copy(update={"finish_level": "premium"}))
    assert any(s.label == "Finish" for s in _line(premium, "M10").calculation)
    assert not any(s.label == "Finish" for s in _line(premium, "M01").calculation)


def test_work_package_steps_end_at_the_budget() -> None:
    est = estimate(REF)
    for wp in est.work_packages:
        assert wp.calculation[-1].result == f"{wp.budget_sar:,} SAR", wp.id
        assert not any(s.label == "Escalation" for s in wp.calculation)


def test_escalation_step_appears_for_long_projects() -> None:
    est = estimate(REF.model_copy(update={"duration_months": 14}))
    wp5 = next(wp for wp in est.work_packages if wp.id == "WP5_external")
    esc = next(s for s in wp5.calculation if s.label == "Escalation")
    assert esc.result == "+4,200 SAR"
    assert wp5.calculation[-1].result == f"{wp5.budget_sar:,} SAR"


def test_totals_and_allowances_end_at_the_proposed_budget() -> None:
    est = estimate(REF)
    assert est.totals_calculation[-1].label == "Proposed budget"
    assert est.totals_calculation[-1].result == f"{est.proposed_budget_sar:,} SAR"
    assert est.totals_calculation[4].result == f"{est.total_incl_vat_sar:,} SAR"
    for a in est.allowances:
        assert a.calculation[-1].result == f"{a.baseline_sar:,} SAR", a.id
